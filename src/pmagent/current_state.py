from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from .observation.paths import (
    project_observation_index_path,
    project_observation_root,
    project_observation_runs_root,
    project_state_path,
    maintenance_drafts_root,
    prd_root,
    queue_summary_path,
    workspace_root,
    workspace_summary_path,
)
from .observation.profile import cadence_interval, catch_up_due, load_profile, parse_utc, utc_now
from .readiness import infer_phase_readiness
from .observation.summary_protocol import (
    build_observation_section,
    inspect_summary,
    replace_observation_section,
    sync_core_section_from_state,
)


LEGACY_MODE_KEYS = {"mode", "route_mode", "mode_skill_path"}


def current_state_root(repo_root: Path, workspace: str) -> Path:
    return workspace_root(repo_root, workspace) / ".pmagent"


def current_state_path(repo_root: Path, workspace: str) -> Path:
    return current_state_root(repo_root, workspace) / "current-state.json"


def project_state_root(repo_root: Path, project: str) -> Path:
    return project_state_path(repo_root, project).parent


def _lock_timeout_seconds() -> float:
    raw = os.environ.get("PMAGENT_STATE_LOCK_TIMEOUT", "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return 10.0


def _read_json_payload(path: Path) -> Any | None:
    deadline = time.time() + _lock_timeout_seconds()
    last_error: Exception | None = None
    while True:
        try:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, json.JSONDecodeError) as exc:
            last_error = exc
            if time.time() >= deadline:
                raise last_error
            time.sleep(0.05)


def _read_text_with_retry(path: Path) -> str | None:
    deadline = time.time() + _lock_timeout_seconds()
    last_error: Exception | None = None
    while True:
        try:
            if not path.exists():
                return None
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except PermissionError as exc:
            last_error = exc
            if time.time() >= deadline:
                raise last_error
            time.sleep(0.05)


def _read_json(path: Path) -> dict[str, Any] | None:
    raw = _read_json_payload(path)
    return raw if isinstance(raw, dict) else None


@contextmanager
def _state_write_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.time() + _lock_timeout_seconds()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > max(_lock_timeout_seconds() * 3, 30.0)
            except OSError:
                stale = False
            if stale:
                lock_path.unlink(missing_ok=True)
                continue
            if time.time() >= deadline:
                raise RuntimeError(f"timed out waiting for state lock: {lock_path}")
            time.sleep(0.05)
            continue
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json_list(path: Path) -> list[Any]:
    raw = _read_json_payload(path)
    return raw if isinstance(raw, list) else []


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _queue_summary_string(queue: dict[str, Any]) -> str:
    return " ".join(
        [
            f"inbox={_safe_int(queue.get('inbox'))}",
            f"accepted={_safe_int(queue.get('accepted'))}",
            f"rejected={_safe_int(queue.get('rejected'))}",
            f"snoozed={_safe_int(queue.get('snoozed'))}",
        ]
    )


def _infer_project(repo_root: Path, workspace: str) -> str | None:
    config_path = repo_root / "config" / "projects.json"
    if not config_path.exists():
        return None
    payload = _read_json(config_path) or {}
    projects = payload.get("projects", {})
    if not isinstance(projects, dict):
        return None
    for project, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        workspaces = entry.get("workspaces", [])
        if isinstance(workspaces, list) and workspace in {str(item) for item in workspaces}:
            return str(project)
    return payload.get("active_project") if payload.get("active_workspace") == workspace else None


def _latest_export(repo_root: Path, workspace: str) -> str | None:
    exports_root = workspace_root(repo_root, workspace) / "exports"
    if not exports_root.exists():
        return None
    candidates = sorted((path for path in exports_root.iterdir() if path.is_dir()), key=lambda item: item.name)
    if not candidates:
        return None
    return _rel(repo_root, candidates[-1])


def _rel(repo_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _artifacts_snapshot(repo_root: Path, workspace: str) -> dict[str, Any]:
    root = workspace_root(repo_root, workspace)
    requirement_path = root / "Requirement.md"
    strategy_root = root / "strategy"
    strategy_exists = strategy_root.exists() and any(strategy_root.glob("*.md"))
    prd_current = prd_root(repo_root, workspace) / "current.md"
    prd_dir = prd_root(repo_root, workspace)
    prd_files = sorted(prd_dir.glob("*.md")) if prd_dir.exists() else []

    if prd_current.exists():
        prd_status = "active"
    elif prd_files:
        prd_status = "draft"
    else:
        prd_status = "absent"

    return {
        "requirement": {
            "exists": requirement_path.exists(),
            "path": _rel(repo_root, requirement_path) if requirement_path.exists() else None,
        },
        "strategy": {
            "exists": strategy_exists,
        },
        "prd": {
            "status": prd_status,
            "canonical_path": _rel(repo_root, prd_current) if prd_current.exists() else None,
        },
        "export": {
            "latest": _latest_export(repo_root, workspace),
        },
    }


def _project_state_default(repo_root: Path, project: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": project,
        "workspace_refs": [],
        "observation": {
            "ref": _rel(repo_root, project_observation_root(repo_root, project)),
            "index": _rel(repo_root, project_observation_index_path(repo_root, project)),
        },
        "updated_at": utc_now(),
    }


def load_project_state(repo_root: Path, project: str) -> dict[str, Any] | None:
    return _read_json(project_state_path(repo_root, project))


def preview_project_state(repo_root: Path, project: str, *, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    state = _deep_merge(_project_state_default(repo_root, project), load_project_state(repo_root, project) or {})
    if patch:
        state = _deep_merge(state, patch)
    state["project"] = project
    state.setdefault("observation", {})
    state["observation"]["ref"] = _rel(repo_root, project_observation_root(repo_root, project))
    state["observation"]["index"] = _rel(repo_root, project_observation_index_path(repo_root, project))
    return state


def write_project_state(repo_root: Path, project: str, state: dict[str, Any]) -> dict[str, Any]:
    path = project_state_path(repo_root, project)
    _atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return state


def sync_project_state(repo_root: Path, project: str, *, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    with _state_write_lock(project_state_path(repo_root, project)):
        state = preview_project_state(repo_root, project, patch=patch)
        state["updated_at"] = utc_now()
        return write_project_state(repo_root, project, state)


def _observation_index(repo_root: Path, project: str | None) -> dict[str, Any]:
    if not project:
        return {"observation_ids": []}
    return _read_json(project_observation_index_path(repo_root, project)) or {"observation_ids": []}


def _workspace_observation_tracking(project: str | None) -> dict[str, Any]:
    return {
        "project": project,
        "seen_observation_ids": [],
        "pending_observation_ids": [],
        "last_observation_sync_at": None,
    }


def _summary_hints(repo_root: Path, workspace: str) -> dict[str, Any]:
    summary_path = workspace_summary_path(repo_root, workspace)
    text = _read_text_with_retry(summary_path)
    if text is None:
        return {}
    hints: dict[str, Any] = {}
    patterns = {
        "phase": r"- Phase:\s*`([^`]+)`",
        "active_step": r"- Active step:\s*`([^`]+)`",
        "pending_user_decision": r"- Pending user decision:\s*`([^`]+)`",
        "next_step_reason": r"- Next recommended step:\s*(.+)",
    }
    import re

    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            hints[key] = match.group(1).strip()
    return hints


def _normalized_phase(value: Any, *, artifacts: dict[str, Any], workspace_root_path: Path) -> str | None:
    phase = str(value).strip() if value is not None and str(value).strip() else None
    if phase != "observing":
        return phase

    prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
    if str(prd.get("status") or "") in {"active", "draft", "maintained"}:
        return "delivery"
    strategy_root = workspace_root_path / "strategy"
    research_root = workspace_root_path / "research"
    if (strategy_root.exists() and any(strategy_root.iterdir())) or (research_root.exists() and any(research_root.iterdir())):
        return "researching"
    return "clarifying"


def _skill(skill_id: str, path: str, reason: str, command: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": skill_id,
        "skill_path": path,
        "reason": reason,
    }
    if command:
        payload["command"] = command
    return payload


def _recommended_skills_for_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    phase = str(state.get("phase") or "").strip()
    active_step = str(state.get("active_step") or "").strip()
    pending = str(state.get("pending_user_decision") or "").strip()
    next_step = state.get("next_recommended_step", {})
    next_id = str(next_step.get("id") or "").strip() if isinstance(next_step, dict) else ""

    if pending == "candidate-review" or active_step == "candidate-review" or next_id == "review_candidates":
        return [
            _skill(
                "candidate-review",
                "skills/steps/candidate-review/skill.md",
                "Review inbound Candidate Cards before changing canonical PM Data.",
                "pmagent review",
            )
        ]

    if phase == "dev-readiness" or active_step in {"dev-readiness", "slice-run-record"}:
        return [
            _skill(
                "dev-readiness",
                "skills/steps/dev-readiness/skill.md",
                "External Agent turns the stable PRD into a dev-plan and vertical slices.",
            ),
            _skill(
                "dev-run-record",
                "skills/steps/dev-run-record/skill.md",
                "Record slice execution evidence and lesson candidates.",
                "pmagent dev run-record --slice SL-001",
            ),
        ]

    if phase == "delivery":
        return [
            _skill(
                "dev-readiness",
                "skills/steps/dev-readiness/skill.md",
                "Prepare the PRD for implementation through a vertical-slice handoff.",
            ),
            _skill(
                "challenge-prd",
                "skills/steps/challenge-prd/skill.md",
                "Challenge the PRD before it is handed to development.",
                "pmagent prd challenge",
            ),
        ]

    if phase == "researching":
        return [
            _skill(
                "do-research",
                "skills/steps/do-research/skill.md",
                "Collect evidence until the PRD handoff is defensible.",
                "pmagent research status",
            ),
            _skill(
                "write-prd",
                "skills/steps/write-prd/skill.md",
                "Draft or refresh the canonical PRD once research readiness is high.",
                "pmagent prd init-draft",
            ),
        ]

    return [
        _skill(
            "write-requirement",
            "skills/steps/write-requirement/skill.md",
            "Clarify the stable requirement consensus before downstream artifacts.",
            "pmagent clarify status",
        ),
        _skill(
            "do-research",
            "skills/steps/do-research/skill.md",
            "Start an evidence-gathering side path if scope is already clear.",
            "pmagent research status",
        ),
    ]


def _observation_snapshot(repo_root: Path, workspace: str) -> dict[str, Any]:
    project = _infer_project(repo_root, workspace)
    if project:
        profile = load_profile(repo_root, project, create=True)
        last_run = {
            "last_run_id": profile.get("last_run_id"),
            "updated_at": profile.get("last_run_at"),
        }
    else:
        profile = {
            "enabled": False,
            "cadence": "manual",
            "scheduler": {"last_configured_at": None},
            "cadence_recommendation": {"status": "stable", "suggested_cadence": None, "reason": None},
            "last_run_id": None,
            "last_run_at": None,
        }
        last_run = {}
    queue_summary = _read_json(queue_summary_path(repo_root, workspace)) or {}
    counts = queue_summary.get("counts", {})
    queue = {
        "inbox": int(counts.get("inbox", 0)),
        "accepted": int(counts.get("accepted", 0)),
        "rejected": int(counts.get("rejected", 0)),
        "snoozed": int(counts.get("snoozed", 0)),
    }

    enabled = bool(profile.get("enabled", False))
    cadence = str(profile.get("cadence", "manual"))
    last_run_at = last_run.get("updated_at") if isinstance(last_run, dict) else None
    next_scheduled_run_at = None
    interval = cadence_interval(cadence)
    if enabled and interval is not None:
        last_seen = parse_utc(last_run_at)
        if last_seen is None:
            scheduler = profile.get("scheduler") or {}
            last_seen = parse_utc(scheduler.get("last_configured_at"))
        if last_seen is not None:
            next_scheduled_run_at = (last_seen + interval).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return {
        "enabled": enabled,
        "cadence": cadence,
        "decision_status": str(profile.get("decision_status", "unresolved")),
        "last_confirmed_at": profile.get("last_confirmed_at"),
        "confirmation_source": profile.get("confirmation_source"),
        "last_run_id": last_run.get("last_run_id") if isinstance(last_run, dict) else None,
        "last_run_at": last_run_at,
        "observation_count": int(profile.get("observation_count", 0) or 0),
        "next_scheduled_run_at": next_scheduled_run_at,
        "catch_up_needed": catch_up_due(profile, last_run if isinstance(last_run, dict) else None),
        "needs_review": queue["inbox"] > 0,
        "queue": queue,
        "cadence_recommendation": profile.get("cadence_recommendation", {}),
    }


def _debates_root(repo_root: Path, workspace: str) -> Path:
    return workspace_root(repo_root, workspace) / "context" / "debates"


def _maintenance_next_step(repo_root: Path, workspace: str, *, accepted: int, pending_count: int) -> dict[str, str] | None:
    if pending_count > 0 or accepted <= 0:
        return None
    drafts_root = maintenance_drafts_root(repo_root, workspace)
    has_draft = drafts_root.exists() and any(drafts_root.glob("*.md"))
    if has_draft:
        return {
            "id": "apply_maintenance",
            "reason": "Accepted cards already have a maintenance draft; apply it after user approval.",
        }
    return {
        "id": "draft_maintenance",
        "reason": "Accepted cards are ready to be turned into a maintenance draft.",
    }


def _debate_snapshot(repo_root: Path, workspace: str) -> dict[str, Any]:
    root = _debates_root(repo_root, workspace)
    if not root.exists():
        return {
            "active_count": 0,
            "completed_awaiting_review_count": 0,
            "failed_count": 0,
            "latest_topic": None,
            "latest_failed_topic": None,
            "awaiting_review_topics": [],
            "failed_topics": [],
        }

    active_states = {
        "queued",
        "awaiting-axis",
        "running",
        "synthesizing",
    }
    active_events = {"started", "round_completed", "human_injected"}
    completed_states = {"completed"}
    completed_events = {"completed"}
    failed_states = {"failed"}
    failed_events = {"failed"}
    terminal_review_statuses = {"accepted", "rejected", "deferred"}

    active_count = 0
    awaiting_review_topics: list[str] = []
    failed_topics: list[str] = []
    latest_topic: str | None = None
    latest_failed_topic: str | None = None
    latest_mtime = -1.0
    latest_failed_mtime = -1.0

    for topic_dir in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda item: item.name):
        status = _read_json(topic_dir / "status.json") or {}
        signal = _read_json(topic_dir / "signal.json") or {}
        review = _read_json(topic_dir / "review.json") or {}

        state = str(status.get("state") or "").strip().lower()
        event = str(signal.get("event") or "").strip().lower()
        review_status = str(review.get("status") or "").strip().lower()

        completed = state in completed_states or event in completed_events
        reviewed = review_status in terminal_review_statuses
        if completed and not reviewed:
            awaiting_review_topics.append(topic_dir.name)
        failed = state in failed_states or event in failed_events
        if failed:
            failed_topics.append(topic_dir.name)
        if (
            not completed
            and not failed
            and (
                state in active_states
                or re.fullmatch(r"round-\d+-running", state)
                or event in active_events
            )
        ):
            active_count += 1

        try:
            topic_mtime = max(
                path.stat().st_mtime
                for path in topic_dir.rglob("*")
            )
        except ValueError:
            topic_mtime = topic_dir.stat().st_mtime
        except OSError:
            topic_mtime = -1.0
        if topic_mtime >= latest_mtime:
            latest_mtime = topic_mtime
            latest_topic = topic_dir.name
        if failed and topic_mtime >= latest_failed_mtime:
            latest_failed_mtime = topic_mtime
            latest_failed_topic = topic_dir.name

    return {
        "active_count": active_count,
        "completed_awaiting_review_count": len(awaiting_review_topics),
        "failed_count": len(failed_topics),
        "latest_topic": latest_topic,
        "latest_failed_topic": latest_failed_topic,
        "awaiting_review_topics": awaiting_review_topics,
        "failed_topics": failed_topics,
    }


def _default_state(repo_root: Path, workspace: str) -> dict[str, Any]:
    project = _infer_project(repo_root, workspace)
    summary_hints = _summary_hints(repo_root, workspace)
    artifacts = _artifacts_snapshot(repo_root, workspace)
    return {
        "schema_version": 1,
        "project": project,
        "project_ref": _rel(repo_root, repo_root / "projects" / project) if project else None,
        "workspace": workspace,
        "phase": _normalized_phase(summary_hints.get("phase"), artifacts=artifacts, workspace_root_path=workspace_root(repo_root, workspace)),
        "active_step": summary_hints.get("active_step"),
        "pending_user_decision": summary_hints.get("pending_user_decision"),
        "next_recommended_step": {
            "id": None,
            "reason": summary_hints.get("next_step_reason"),
        },
        "recommended_skills": [],
        "route_reason": None,
        "artifacts": artifacts,
        "observation": _observation_snapshot(repo_root, workspace),
        "observation_ref": _rel(repo_root, project_observation_root(repo_root, project)) if project else None,
        "observation_tracking": _workspace_observation_tracking(project),
        "transition_recommendation": None,
        "candidate_review": None,
        "debates": {
            "active_count": 0,
            "completed_awaiting_review_count": 0,
            "failed_count": 0,
            "latest_topic": None,
            "latest_failed_topic": None,
        },
        "debate_review": {
            "active": False,
            "awaiting_review_topics": [],
            "completed_awaiting_review_count": 0,
        },
        "debate_launch": {
            "active": False,
            "reason": None,
            "thesis": None,
            "axis": None,
            "topic_slug": None,
            "executors": {},
            "config_path": None,
        },
        "readiness": {},
        "updated_at": utc_now(),
        "updated_by": None,
        "state_revision": None,
    }


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value) if key in merged else value
        return merged
    return patch


def load_current_state(repo_root: Path, workspace: str) -> dict[str, Any] | None:
    return _read_json(current_state_path(repo_root, workspace))


def write_current_state(repo_root: Path, workspace: str, state: dict[str, Any]) -> dict[str, Any]:
    path = current_state_path(repo_root, workspace)
    _atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return state


def preview_current_state(
    repo_root: Path,
    workspace: str,
    *,
    patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = load_current_state(repo_root, workspace) or {}
    state = _deep_merge(_default_state(repo_root, workspace), existing)
    for key in LEGACY_MODE_KEYS:
        state.pop(key, None)
    state["project"] = _infer_project(repo_root, workspace)
    state["workspace"] = workspace
    state["artifacts"] = _artifacts_snapshot(repo_root, workspace)
    state["phase"] = _normalized_phase(state.get("phase"), artifacts=state["artifacts"], workspace_root_path=workspace_root(repo_root, workspace))
    state["observation"] = _observation_snapshot(repo_root, workspace)
    state["project_ref"] = _rel(repo_root, repo_root / "projects" / state["project"]) if state.get("project") else None
    state["observation_ref"] = _rel(repo_root, project_observation_root(repo_root, state["project"])) if state.get("project") else None

    if patch:
        patch_without_readiness = {
            key: value for key, value in patch.items() if key not in {"readiness", "mode"}
        }
        state = _deep_merge(state, patch_without_readiness)

    inferred_readiness = infer_phase_readiness(
        phase=state.get("phase"),
        active_step=state.get("active_step"),
        pending_user_decision=state.get("pending_user_decision"),
        artifacts=state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {},
        observation=state.get("observation") if isinstance(state.get("observation"), dict) else {},
        workspace_root=workspace_root(repo_root, workspace),
    )
    existing_readiness = existing.get("readiness", {}) if isinstance(existing, dict) else {}
    if (
        isinstance(existing_readiness, dict)
        and inferred_readiness.get("phase") in {"clarifying", "researching"}
        and existing_readiness.get("phase") == inferred_readiness.get("phase")
    ):
        state["readiness"] = _deep_merge(inferred_readiness, existing_readiness)
    else:
        state["readiness"] = inferred_readiness

    if patch and isinstance(patch.get("readiness"), dict):
        state["readiness"] = _deep_merge(state["readiness"], patch["readiness"])
    state["transition_recommendation"] = (
        state["readiness"].get("transition_recommendation")
        if isinstance(state.get("readiness"), dict)
        else None
    )

    prd = state.get("artifacts", {}).get("prd", {}) if isinstance(state.get("artifacts"), dict) else {}
    prd_exists = bool(prd.get("canonical_path")) or str(prd.get("status") or "") in {"active", "maintained", "draft"}
    tracking = state.get("observation_tracking", {}) if isinstance(state.get("observation_tracking"), dict) else _workspace_observation_tracking(state.get("project"))
    index = _observation_index(repo_root, state.get("project"))
    all_ids = [str(item) for item in index.get("observation_ids", []) if str(item).strip()]
    seen_ids = [str(item) for item in tracking.get("seen_observation_ids", []) if str(item).strip()]
    pending_ids = [item for item in all_ids if item not in seen_ids]
    tracking["project"] = state.get("project")
    tracking["pending_observation_ids"] = pending_ids
    state["observation_tracking"] = tracking
    observation = state.get("observation", {}) if isinstance(state.get("observation"), dict) else {}
    queue = observation.get("queue", {}) if isinstance(observation.get("queue"), dict) else {}
    queue["inbox"] = len(pending_ids)
    observation["queue"] = queue
    observation["needs_review"] = bool(pending_ids)
    state["observation"] = observation
    accepted = _safe_int(queue.get("accepted"))
    candidate_review_active = (
        state.get("active_step") == "candidate-review"
        or state.get("pending_user_decision") == "candidate-review"
        or bool(pending_ids)
    )
    if candidate_review_active:
        state["candidate_review"] = {
            "active": True,
            "inbox_count": len(pending_ids),
            "accepted_count": accepted,
        }
    else:
        state["candidate_review"] = None

    debate_snapshot = _debate_snapshot(repo_root, workspace)
    existing_debate_review = state.get("debate_review") if isinstance(state.get("debate_review"), dict) else {}
    snapshot_awaiting = [
        str(item) for item in debate_snapshot.get("awaiting_review_topics", []) if str(item).strip()
    ]
    awaiting_topics = existing_debate_review.get("awaiting_review_topics")
    if not isinstance(awaiting_topics, list) or not awaiting_topics:
        awaiting_topics = snapshot_awaiting
    else:
        awaiting_topics = [str(item) for item in awaiting_topics if str(item).strip() and str(item) in snapshot_awaiting]
        if not awaiting_topics:
            awaiting_topics = snapshot_awaiting
    state["debates"] = {
        "active_count": int(debate_snapshot.get("active_count", 0) or 0),
        "completed_awaiting_review_count": int(debate_snapshot.get("completed_awaiting_review_count", 0) or 0),
        "failed_count": int(debate_snapshot.get("failed_count", 0) or 0),
        "latest_topic": debate_snapshot.get("latest_topic"),
        "latest_failed_topic": debate_snapshot.get("latest_failed_topic"),
        "failed_topics": debate_snapshot.get("failed_topics", []),
    }
    state["debate_review"] = {
        "active": bool(existing_debate_review.get("active", False) or awaiting_topics),
        "awaiting_review_topics": awaiting_topics,
        "completed_awaiting_review_count": len(awaiting_topics),
    }
    existing_debate_launch = state.get("debate_launch") if isinstance(state.get("debate_launch"), dict) else {}
    state["debate_launch"] = {
        "active": bool(existing_debate_launch.get("active", False)),
        "reason": existing_debate_launch.get("reason"),
        "thesis": existing_debate_launch.get("thesis"),
        "axis": existing_debate_launch.get("axis"),
        "topic_slug": existing_debate_launch.get("topic_slug"),
        "executors": existing_debate_launch.get("executors") if isinstance(existing_debate_launch.get("executors"), dict) else {},
        "config_path": existing_debate_launch.get("config_path"),
    }
    maintenance_step = _maintenance_next_step(repo_root, workspace, accepted=accepted, pending_count=len(pending_ids))
    if maintenance_step:
        state["phase"] = "maintaining"
        state["active_step"] = "draft-maintenance"
        state["pending_user_decision"] = "prd-approval" if maintenance_step["id"] == "apply_maintenance" else None
        state["next_recommended_step"] = maintenance_step

    state["recommended_skills"] = _recommended_skills_for_state(state)

    return state


def _latest_run_findings_count(repo_root: Path, state: dict[str, Any]) -> int:
    observation = state.get("observation", {}) if isinstance(state.get("observation"), dict) else {}
    project = str(state.get("project") or "").strip()
    run_id = str(observation.get("last_run_id") or "").strip()
    if project and run_id:
        meta = _read_json(project_observation_runs_root(repo_root, project) / run_id / "meta.json") or {}
        if isinstance(meta, dict):
            return _safe_int(meta.get("findings_count"), _safe_int(observation.get("observation_count")))
    return _safe_int(observation.get("observation_count"))


def _sync_observation_section_from_state(repo_root: Path, workspace: str, state: dict[str, Any]) -> None:
    summary_path = workspace_summary_path(repo_root, workspace)
    if not summary_path.exists() or inspect_summary(summary_path).state != "valid":
        return
    observation = state.get("observation", {}) if isinstance(state.get("observation"), dict) else {}
    queue = observation.get("queue", {}) if isinstance(observation.get("queue"), dict) else {}
    inbox_count = _safe_int(queue.get("inbox"))
    section = build_observation_section(
        workspace=workspace,
        run_id=str(observation.get("last_run_id") or "not started"),
        findings_count=_latest_run_findings_count(repo_root, state),
        candidate_count=inbox_count,
        status="active" if bool(observation.get("needs_review")) else "idle",
        enabled=bool(observation.get("enabled", False)),
        cadence=str(observation.get("cadence", "manual")),
        next_scheduled_run=str(observation.get("next_scheduled_run_at") or "not scheduled"),
        queue_summary=_queue_summary_string(queue),
        needs_review=bool(observation.get("needs_review")),
        catch_up_needed=bool(observation.get("catch_up_needed")),
    )
    replace_observation_section(summary_path, section)


def sync_current_state(
    repo_root: Path,
    workspace: str,
    *,
    patch: dict[str, Any] | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    with _state_write_lock(current_state_path(repo_root, workspace)):
        state = preview_current_state(repo_root, workspace, patch=patch)
        state["updated_at"] = utc_now()
        if updated_by is not None:
            state["updated_by"] = updated_by
        written = write_current_state(repo_root, workspace, state)
        summary_path = workspace_summary_path(repo_root, workspace)
        if summary_path.exists() and inspect_summary(summary_path).state == "valid":
            sync_core_section_from_state(summary_path, written)
            _sync_observation_section_from_state(repo_root, workspace, written)
        return written
