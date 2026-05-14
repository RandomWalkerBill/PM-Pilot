from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4

import yaml

from ..current_state import preview_current_state, preview_project_state, sync_current_state, sync_project_state
from .paths import (
    candidate_updates_root,
    maintenance_changelog_root,
    maintenance_consumed_root,
    maintenance_drafts_root,
    observation_file_path,
    prd_root,
    project_observation_files_root,
    project_observation_index_path,
    project_observation_policy_path,
    project_observation_root,
    project_observation_runs_root,
    project_observation_state_path,
    project_root,
    queue_summary_path,
    workspace_root,
    workspace_summary_path,
)
from .profile import (
    SUPPORTED_CADENCES,
    catch_up_due,
    load_profile,
    record_review_outcome,
    reset_cadence_recommendation,
    set_schedule_state,
)
from .scheduler import configure_schedule, delete_schedule
from .summary_protocol import (
    build_observation_section,
    build_workspace_summary_document,
    inspect_summary,
    replace_observation_section,
    summary_revision,
)
QUEUE_BUCKETS = ("inbox", "accepted", "rejected", "snoozed")
PROJECT_OBSERVATION_STATE_POLICY_KEYS = {
    "enabled",
    "cadence",
    "decision_status",
    "last_confirmed_at",
    "confirmation_source",
    "catch_up_policy",
    "focus",
    "keywords",
    "preferred_domains",
    "excluded_domains",
}

def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _write_json(path: Path, payload: object) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix=".tmp.", suffix=".json")
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(repo_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.relative_to(repo_root).as_posix()


def _queue_summary_string(queue: dict[str, object]) -> str:
    return (
        f"inbox={int(queue.get('inbox', 0))} "
        f"accepted={int(queue.get('accepted', 0))} "
        f"rejected={int(queue.get('rejected', 0))} "
        f"snoozed={int(queue.get('snoozed', 0))}"
    )


def _parse_card_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                return meta if isinstance(meta, dict) else {}, parts[2].strip()
            except Exception:
                return {}, text
    return {}, text


def _extract_summary(body: str) -> str:
    marker = "## Summary"
    impact = "## Impact Draft"
    if marker in body:
        segment = body.split(marker, 1)[1]
        if impact in segment:
            segment = segment.split(impact, 1)[0]
        cleaned = segment.strip()
        return cleaned.splitlines()[0].strip() if cleaned else ""
    return ""


def _observation_section_from_state(
    state: dict[str, object],
    *,
    workspace: str,
    run_id: str,
    findings_count: int,
    candidate_count: int,
    status: str,
) -> str:
    observation = state.get("observation", {}) if isinstance(state, dict) else {}
    queue = observation.get("queue", {}) if isinstance(observation, dict) else {}
    return build_observation_section(
        workspace=workspace,
        run_id=run_id,
        findings_count=findings_count,
        candidate_count=candidate_count,
        status=status,
        enabled=bool(observation.get("enabled", False)),
        cadence=str(observation.get("cadence", "manual")),
        next_scheduled_run=str(observation.get("next_scheduled_run_at") or "not scheduled"),
        queue_summary=_queue_summary_string(queue if isinstance(queue, dict) else {}),
        needs_review=bool(observation.get("needs_review", False)),
        catch_up_needed=bool(observation.get("catch_up_needed", False)),
    )


def _sync_observation_summary_from_state(
    repo_root: Path,
    workspace: str,
    *,
    state: dict[str, object],
    status: str = "idle",
    findings_count: int = 0,
    candidate_count: int | None = None,
) -> None:
    summary_path = workspace_summary_path(repo_root, workspace)
    summary_status = inspect_summary(summary_path)
    if summary_status.state != "valid":
        return
    observation = state.get("observation", {}) if isinstance(state, dict) else {}
    queue = observation.get("queue", {}) if isinstance(observation, dict) else {}
    queue_dict = queue if isinstance(queue, dict) else {}
    run_id = str(observation.get("last_run_id") or "not started")
    created_candidates = candidate_count if candidate_count is not None else int(queue_dict.get("inbox", 0))
    replace_observation_section(
        summary_path,
        _observation_section_from_state(
            state,
            workspace=workspace,
            run_id=run_id,
            findings_count=findings_count,
            candidate_count=created_candidates,
            status=status,
        ),
    )


@dataclass(frozen=True)
class QueueStatus:
    state: str
    reason: str
    bootstrap_required: bool
    bootstrap_actions: list[str]
    blocking_conditions: list[str]


def _queue_error(state: str, reason: str, action: str, condition: str) -> QueueStatus:
    return QueueStatus(state, reason, True, [action], [condition])


def _workspace_exists(repo_root: Path, workspace: str) -> Path:
    root = workspace_root(repo_root, workspace)
    if not root.exists():
        raise SystemExit(f"workspace does not exist: {root}")
    return root


def _infer_project_for_workspace(repo_root: Path, workspace: str) -> str:
    config_path = repo_root / "config" / "projects.json"
    if not config_path.exists():
        return workspace
    payload = _read_json(config_path)
    if not isinstance(payload, dict):
        return workspace
    projects = payload.get("projects", {})
    if not isinstance(projects, dict):
        return workspace
    for project, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        workspaces = entry.get("workspaces", [])
        if isinstance(workspaces, list) and workspace in {str(item) for item in workspaces}:
            return str(project)
    return workspace


def _project_exists(repo_root: Path, project: str) -> Path:
    root = project_root(repo_root, project)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_project(repo_root: Path, *, project: str | None = None, workspace: str | None = None) -> str:
    if project:
        _project_exists(repo_root, project)
        return project
    if workspace:
        _workspace_exists(repo_root, workspace)
        return _infer_project_for_workspace(repo_root, workspace)
    raise SystemExit("a project or workspace is required")


def _project_observation_index(repo_root: Path, project: str) -> dict[str, object]:
    path = project_observation_index_path(repo_root, project)
    payload = _read_json(path) if path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("project", project)
    payload.setdefault("observation_ids", [])
    payload.setdefault("updated_at", _utc_now())
    return payload


def _write_project_observation_index(repo_root: Path, project: str, payload: dict[str, object]) -> dict[str, object]:
    payload["project"] = project
    payload["updated_at"] = _utc_now()
    _write_json(project_observation_index_path(repo_root, project), payload)
    return payload


def _project_observation_state(repo_root: Path, project: str) -> dict[str, object]:
    path = project_observation_state_path(repo_root, project)
    payload = _read_json(path) if path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("project", project)
    payload.setdefault("last_run_id", None)
    payload.setdefault("last_run_at", None)
    payload.setdefault("next_scheduled_run_at", None)
    payload.setdefault("observation_count", 0)
    payload.setdefault("updated_at", _utc_now())
    return payload


def _write_project_observation_state(repo_root: Path, project: str, payload: dict[str, object]) -> dict[str, object]:
    for key in PROJECT_OBSERVATION_STATE_POLICY_KEYS:
        payload.pop(key, None)
    payload["project"] = project
    payload["updated_at"] = _utc_now()
    _write_json(project_observation_state_path(repo_root, project), payload)
    return payload


def _workspace_tracking(state: dict[str, object]) -> dict[str, object]:
    tracking = state.get("observation_tracking", {}) if isinstance(state.get("observation_tracking"), dict) else {}
    tracking.setdefault("seen_observation_ids", [])
    tracking.setdefault("pending_observation_ids", [])
    tracking.setdefault("last_observation_sync_at", None)
    return tracking


def _unread_observation_ids(repo_root: Path, workspace: str) -> list[str]:
    project = _infer_project_for_workspace(repo_root, workspace)
    state = preview_current_state(repo_root, workspace)
    tracking = _workspace_tracking(state)
    seen = {str(item) for item in tracking.get("seen_observation_ids", [])}
    index = _project_observation_index(repo_root, project)
    all_ids = [str(item) for item in index.get("observation_ids", []) if str(item).strip()]
    return [item for item in all_ids if item not in seen]


def _mark_observations_seen(repo_root: Path, workspace: str, observation_ids: list[str]) -> dict[str, object]:
    state = preview_current_state(repo_root, workspace)
    tracking = _workspace_tracking(state)
    seen = [str(item) for item in tracking.get("seen_observation_ids", []) if str(item).strip()]
    updated_seen = sorted({*seen, *[str(item) for item in observation_ids if str(item).strip()]})
    pending = [str(item) for item in tracking.get("pending_observation_ids", []) if str(item) not in set(observation_ids)]
    return sync_current_state(
        repo_root,
        workspace,
        patch={
            "observation_tracking": {
                "seen_observation_ids": updated_seen,
                "pending_observation_ids": pending,
                "last_observation_sync_at": _utc_now(),
            }
        },
        updated_by="observe-mark-read",
    )


def _write_last_run(path: Path, project: str) -> None:
    _write_json(
        path,
        {
            "schema_version": 1,
            "project": project,
            "last_run_id": None,
            "updated_at": _utc_now(),
        },
    )


def init_profile(repo_root: Path, project: str) -> int:
    root = _project_exists(repo_root, project)
    obs_root = project_observation_root(repo_root, project)
    obs_root.mkdir(parents=True, exist_ok=True)
    project_observation_runs_root(repo_root, project).mkdir(parents=True, exist_ok=True)
    project_observation_files_root(repo_root, project).mkdir(parents=True, exist_ok=True)

    profile = load_profile(repo_root, project, create=True)
    index = _project_observation_index(repo_root, project)
    _write_project_observation_index(repo_root, project, index)
    state = _project_observation_state(repo_root, project)
    _write_project_observation_state(repo_root, project, state)

    print(f"Initialized observation profile for project={project}")
    print(f"project_root={root}")
    return 0


def _empty_queue_counts() -> dict[str, int]:
    return {name: 0 for name in QUEUE_BUCKETS}


def bootstrap_workspace(repo_root: Path, workspace: str) -> int:
    _workspace_exists(repo_root, workspace)
    queue_root = candidate_updates_root(repo_root, workspace)
    for child in QUEUE_BUCKETS:
        (queue_root / child).mkdir(parents=True, exist_ok=True)

    summary_path = queue_summary_path(repo_root, workspace)
    if not summary_path.exists():
        _write_json(
            summary_path,
            {
                "schema_version": 1,
                "workspace": workspace,
                "counts": _empty_queue_counts(),
                "updated_at": _utc_now(),
            },
        )

    print(f"Bootstrapped candidate-update queue for workspace={workspace}")
    return 0


def _card_names(repo_root: Path, workspace: str, state: str, limit: int = 10) -> list[str]:
    root = candidate_updates_root(repo_root, workspace) / state
    if not root.exists():
        return []
    return [path.name for path in sorted(root.glob("*.md"))[:limit]]
