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

from .cards import _find_card, _resolve_prd, _update_queue_summary
from .helpers import _rel, _sync_observation_summary_from_state, _utc_now, _workspace_exists

def draft_maintenance(repo_root: Path, workspace: str, card: str | None = None) -> int:
    _workspace_exists(repo_root, workspace)
    accepted_root = candidate_updates_root(repo_root, workspace) / "accepted"
    cards = [_find_card(repo_root, workspace, card, preferred_state="accepted")] if card else sorted(accepted_root.glob("*.md"))
    if not cards:
        raise SystemExit(f"no accepted candidate cards found for workspace={workspace}")

    drafts_root = maintenance_drafts_root(repo_root, workspace)
    drafts_root.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_root / f"{_utc_now()[:10]}-{workspace}-prd-update-draft.md"

    lines = [
        f"# PRD Maintenance Draft: {workspace}",
        "",
        f"> Generated: {_utc_now()}",
        "",
        "## Candidate Cards",
        "",
    ]
    for card_path in cards:
        rel = _rel(repo_root, card_path)
        lines.append(f"- `{rel}`")
    lines.extend(
        [
            "",
            "## Proposed PRD Update",
            "",
            "<!-- Frontend agent should turn the accepted card evidence into concrete PRD edits here. -->",
            "",
            "## Evidence and Rationale",
            "",
        ]
    )
    for card_path in cards:
        lines.append(f"### {card_path.name}")
        lines.append("")
        lines.append(card_path.read_text(encoding="utf-8"))
        lines.append("")
    lines.extend(
        [
            "## User Confirmation",
            "",
            "- [ ] User approved applying this draft to PRD",
            "- [ ] Changelog will be written",
            "- [ ] Decision record will be updated if this changes direction/scope",
        ]
    )
    draft_path.write_text("\n".join(lines), encoding="utf-8")
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "phase": "maintaining",
            "active_step": "draft-maintenance",
            "pending_user_decision": "prd-approval",
            "next_recommended_step": {
                "id": "apply_maintenance",
                "reason": "Maintenance draft is ready; apply it after user approval.",
            },
        },
        updated_by="observe-draft-maintenance",
    )
    print(f"Maintenance draft created: {draft_path}")
    return 0


def _find_draft(repo_root: Path, workspace: str, draft: str | None) -> Path:
    drafts_root = maintenance_drafts_root(repo_root, workspace)
    if draft:
        draft_path = Path(draft)
        if draft_path.is_absolute():
            if draft_path.exists():
                return draft_path
            raise SystemExit(f"maintenance draft does not exist: {draft_path}")
        candidates = [drafts_root / draft]
        if not draft.endswith(".md"):
            candidates.append(drafts_root / f"{draft}.md")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise SystemExit(f"maintenance draft not found: {draft}")

    drafts = sorted(drafts_root.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not drafts:
        raise SystemExit(f"no maintenance drafts found for workspace={workspace}")
    return drafts[0]


def _extract_card_refs(draft_text: str) -> list[str]:
    refs: list[str] = []
    for line in draft_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- `") and "`" in stripped[3:]:
            ref = stripped[3:].split("`", 1)[0]
            if "candidate-updates/" in ref:
                refs.append(ref)
    return refs


def _write_changelog(repo_root: Path, workspace: str, draft_path: Path, card_refs: list[str]) -> Path:
    changelog_root = maintenance_changelog_root(repo_root, workspace)
    changelog_root.mkdir(parents=True, exist_ok=True)
    path = changelog_root / f"{_utc_now()[:10]}-{workspace}-maintenance.md"
    path.write_text(
        "\n".join(
            [
                f"# Maintenance Changelog: {workspace}",
                "",
                f"- Applied at: {_utc_now()}",
                f"- Source draft: `{_rel(repo_root, draft_path)}`",
                "",
                "## Consumed Candidate Cards",
                "",
                *[f"- `{ref}`" for ref in card_refs],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _consume_cards(repo_root: Path, workspace: str, card_refs: list[str]) -> list[str]:
    consumed_root = maintenance_consumed_root(repo_root, workspace)
    consumed_root.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for ref in card_refs:
        source = repo_root / ref if ref.startswith("workspaces/") else workspace_root(repo_root, workspace) / ref
        if not source.exists():
            continue
        target = consumed_root / source.name
        if target.exists():
            raise SystemExit(f"consumed card already exists: {target}")
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        source.unlink()
        moved.append(_rel(repo_root, target) or str(target))
    _update_queue_summary(repo_root=repo_root, workspace=workspace)
    return moved


def apply_maintenance(repo_root: Path, workspace: str, draft: str | None = None) -> int:
    _workspace_exists(repo_root, workspace)
    draft_path = _find_draft(repo_root, workspace, draft)
    draft_text = draft_path.read_text(encoding="utf-8")
    card_refs = _extract_card_refs(draft_text)
    changelog_path = _write_changelog(repo_root, workspace, draft_path, card_refs)
    consumed = _consume_cards(repo_root, workspace, card_refs)
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "phase": "maintaining",
            "active_step": "apply-maintenance",
            "pending_user_decision": None,
            "next_recommended_step": {
                "id": "observe_audit",
                "reason": "Maintenance changes have been applied; review the next observation window when ready.",
            },
        },
        updated_by="observe-apply-maintenance",
    )
    _sync_observation_summary_from_state(repo_root, workspace, state=state)
    print(f"Finalized maintenance draft: {draft_path}")
    print("Canonical semantic edits are expected to be applied by the Agent before/alongside finalization.")
    print(f"Wrote changelog: {changelog_path}")
    print(f"Consumed cards: {len(consumed)}")
    return 0
