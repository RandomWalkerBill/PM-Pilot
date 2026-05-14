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

from .helpers import (
    QueueStatus,
    _infer_project_for_workspace,
    _mark_observations_seen,
    _card_names,
    _parse_card_frontmatter,
    _rel,
    _utc_now,
    _queue_error,
    _read_json,
    _sync_observation_summary_from_state,
    _workspace_exists,
    _write_json,
)

def _resolve_prd(repo_root: Path, workspace: str) -> tuple[Path | None, str]:
    current = prd_root(repo_root, workspace) / "current.md"
    if current.exists():
        return current, "explicit-current"

    files = sorted(prd_root(repo_root, workspace).glob("*-prd.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if files:
        return files[0], "brownfield-fallback"
    return None, "absent"


def _classify_queue(repo_root: Path, workspace: str) -> QueueStatus:
    queue_root = candidate_updates_root(repo_root, workspace)
    summary_path = queue_summary_path(repo_root, workspace)

    if not queue_root.exists():
        return _queue_error(
            "missing_directory",
            "candidate-updates directory is missing",
            "missing_candidate_updates_directory",
            "queue scaffold missing",
        )
    if not summary_path.exists():
        return _queue_error(
            "missing_summary_file",
            "queue-summary.json is missing",
            "missing_queue_summary_file",
            "queue summary missing",
        )
    try:
        data = _read_json(summary_path)
        if not isinstance(data, dict) or "counts" not in data:
            raise ValueError("queue summary missing counts")
    except Exception:
        return _queue_error(
            "invalid_summary",
            "queue-summary.json is invalid",
            "invalid_queue_summary",
            "queue summary invalid",
        )
    return QueueStatus("valid", "queue summary is valid", False, [], [])


def _read_optional_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_candidate_cards(
    *,
    repo_root: Path,
    workspace: str,
    run_id: str,
    findings: list[dict[str, object]],
    prd_path: Path | None,
) -> list[dict[str, object]]:
    queue_root = candidate_updates_root(repo_root, workspace)
    inbox_root = queue_root / "inbox"
    inbox_root.mkdir(parents=True, exist_ok=True)

    decisions: list[dict[str, object]] = []
    for index, finding in enumerate(findings, start=1):
        title = str(finding.get("title", "")).strip() or f"{finding.get('kind', 'general')} signal"
        slug = f"{run_id}-{index:02d}"
        card_path = inbox_root / f"{slug}.md"
        frontmatter = {
            "schema_version": 1,
            "workspace": workspace,
            "status": "inbox",
            "run_id": run_id,
            "kind": finding.get("kind", "general"),
            "title": title,
            "url": finding.get("url", ""),
            "prd_path": _rel(repo_root, prd_path),
            "confidence": "medium",
        }
        body = [
            "---",
            yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(),
            "---",
            "",
            "# Candidate Update",
            "",
            f"- title: {title}",
            f"- query: {finding.get('query', '')}",
            f"- age: {finding.get('age', '')}",
            "",
            "## Summary",
            str(finding.get("description", "")).strip() or "No summary available.",
            "",
            "## Impact Draft",
            f"This finding may affect the `{workspace}` workspace and should be reviewed.",
            "",
            "## Evidence",
            f"- {finding.get('url', '')}",
            "",
        ]
        card_path.write_text("\n".join(body), encoding="utf-8")
        decisions.append(
            {
                "card_path": _rel(repo_root, card_path),
                "status": "created",
                "title": title,
            }
        )
    return decisions


def _update_queue_summary(*, repo_root: Path, workspace: str) -> None:
    queue_root = candidate_updates_root(repo_root, workspace)
    counts = {
        state: len(list((queue_root / state).glob("*.md")))
        for state in ("inbox", "accepted", "rejected", "snoozed")
    }
    _write_json(
        queue_summary_path(repo_root, workspace),
        {
            "schema_version": 1,
            "workspace": workspace,
            "counts": counts,
            "updated_at": _utc_now(),
        },
    )


def _find_card(repo_root: Path, workspace: str, card: str, preferred_state: str | None = None) -> Path:
    card_path = Path(card)
    if card_path.is_absolute():
        if not card_path.exists():
            raise SystemExit(f"candidate card does not exist: {card_path}")
        return card_path

    root = candidate_updates_root(repo_root, workspace)
    candidates: list[Path] = []
    if preferred_state:
        candidates.append(root / preferred_state / card)
        if not card.endswith(".md"):
            candidates.append(root / preferred_state / f"{card}.md")
    for state in QUEUE_BUCKETS:
        candidates.append(root / state / card)
        if not card.endswith(".md"):
            candidates.append(root / state / f"{card}.md")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(f"candidate card not found in workspace={workspace}: {card}")


def _materialize_observation_review_file(repo_root: Path, workspace: str, observation_id: str, target_state: str) -> Path:
    project = _infer_project_for_workspace(repo_root, workspace)
    source = observation_file_path(repo_root, project, observation_id)
    if not source.exists():
        raise SystemExit(f"observation file not found for review: {observation_id}")
    payload = _read_json(source)
    target_dir = candidate_updates_root(repo_root, workspace) / target_state
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{observation_id}.md"
    if target.exists():
        raise SystemExit(f"target candidate card already exists: {target}")
    frontmatter = {
        "schema_version": 1,
        "workspace": workspace,
        "project": project,
        "status": target_state,
        "observation_id": observation_id,
        "kind": payload.get("kind", "general"),
        "title": payload.get("title", observation_id),
        "url": payload.get("source_url", ""),
    }
    body = [
        "---",
        yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(),
        "---",
        "",
        "# Candidate Update",
        "",
        "## Summary",
        str(payload.get("summary", "")).strip() or "No summary available.",
        "",
        "## Evidence",
    ]
    for item in payload.get("evidence", []) if isinstance(payload.get("evidence"), list) else []:
        if isinstance(item, dict):
            url = item.get("url", "")
            body.append(f"- {url}")
    body.extend(["", f"## Observation Reference", f"- `{_rel(repo_root, source)}`", ""])
    target.write_text("\n".join(body), encoding="utf-8")
    return target


def _move_card(repo_root: Path, workspace: str, card: str, target_state: str) -> Path:
    if target_state not in QUEUE_BUCKETS:
        raise SystemExit(f"invalid candidate state: {target_state}")

    try:
        source = _find_card(repo_root, workspace, card, preferred_state="inbox")
    except SystemExit:
        target = _materialize_observation_review_file(repo_root, workspace, card.removesuffix(".json").removesuffix(".md"), target_state)
        _update_queue_summary(repo_root=repo_root, workspace=workspace)
        return target
    target_dir = candidate_updates_root(repo_root, workspace) / target_state
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists():
        raise SystemExit(f"target candidate card already exists: {target}")

    text = source.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                if isinstance(meta, dict):
                    meta["status"] = target_state
                    text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip() + "\n---" + parts[2]
            except Exception:
                pass
    target.write_text(text, encoding="utf-8")
    source.unlink()
    _update_queue_summary(repo_root=repo_root, workspace=workspace)
    return target


def accept_card(repo_root: Path, workspace: str, card: str) -> int:
    target = _move_card(repo_root, workspace, card, "accepted")
    observation_id = Path(card).stem
    project = _infer_project_for_workspace(repo_root, workspace)
    profile = record_review_outcome(repo_root, project, "accepted")
    _mark_observations_seen(repo_root, workspace, [observation_id])
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "active_step": "candidate-review",
        },
        updated_by="observe-accept",
    )
    queue = state.get("observation", {}).get("queue", {}) if isinstance(state, dict) else {}
    inbox = int(queue.get("inbox", 0)) if isinstance(queue, dict) else 0
    accepted = int(queue.get("accepted", 0)) if isinstance(queue, dict) else 0
    followup_id = "review_candidates" if inbox else "draft_maintenance"
    followup_reason = (
        "There are still inbox cards waiting for review."
        if inbox
        else "Accepted cards are ready to be turned into a maintenance draft."
    )
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "pending_user_decision": "candidate-review" if inbox else None,
            "next_recommended_step": {"id": followup_id, "reason": followup_reason},
        },
        updated_by="observe-accept",
    )
    _sync_observation_summary_from_state(repo_root, workspace, state=state)
    print(f"Accepted candidate card: {target}")
    suggestion = profile.get("cadence_recommendation", {}).get("suggested_cadence")
    if suggestion:
        print(f"cadence_recommendation={suggestion}")
    return 0


def reject_card(repo_root: Path, workspace: str, card: str) -> int:
    target = _move_card(repo_root, workspace, card, "rejected")
    observation_id = Path(card).stem
    project = _infer_project_for_workspace(repo_root, workspace)
    profile = record_review_outcome(repo_root, project, "rejected")
    _mark_observations_seen(repo_root, workspace, [observation_id])
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "active_step": "candidate-review",
        },
        updated_by="observe-reject",
    )
    queue = state.get("observation", {}).get("queue", {}) if isinstance(state, dict) else {}
    inbox = int(queue.get("inbox", 0)) if isinstance(queue, dict) else 0
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "pending_user_decision": "candidate-review" if inbox else None,
            "next_recommended_step": {
                "id": "review_candidates" if inbox else "observe_run",
                "reason": "There are still inbox cards waiting for review." if inbox else "No inbox cards remain; keep observation current.",
            },
        },
        updated_by="observe-reject",
    )
    _sync_observation_summary_from_state(repo_root, workspace, state=state)
    print(f"Rejected candidate card: {target}")
    suggestion = profile.get("cadence_recommendation", {}).get("suggested_cadence")
    if suggestion:
        print(f"cadence_recommendation={suggestion}")
    return 0


def snooze_card(repo_root: Path, workspace: str, card: str) -> int:
    target = _move_card(repo_root, workspace, card, "snoozed")
    observation_id = Path(card).stem
    project = _infer_project_for_workspace(repo_root, workspace)
    profile = record_review_outcome(repo_root, project, "snoozed")
    _mark_observations_seen(repo_root, workspace, [observation_id])
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "active_step": "candidate-review",
        },
        updated_by="observe-snooze",
    )
    queue = state.get("observation", {}).get("queue", {}) if isinstance(state, dict) else {}
    inbox = int(queue.get("inbox", 0)) if isinstance(queue, dict) else 0
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "pending_user_decision": "candidate-review" if inbox else None,
            "next_recommended_step": {
                "id": "review_candidates" if inbox else "observe_run",
                "reason": "There are still inbox cards waiting for review." if inbox else "No inbox cards remain; continue observation monitoring.",
            },
        },
        updated_by="observe-snooze",
    )
    _sync_observation_summary_from_state(repo_root, workspace, state=state)
    print(f"Snoozed candidate card: {target}")
    suggestion = profile.get("cadence_recommendation", {}).get("suggested_cadence")
    if suggestion:
        print(f"cadence_recommendation={suggestion}")
    return 0
