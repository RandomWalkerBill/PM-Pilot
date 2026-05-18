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
from ..presentation import build_guided_output, markdown_table
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

from .bootstrap import bootstrap_workspace
from .cards import _classify_queue, _resolve_prd
from .helpers import (
    _infer_project_for_workspace,
    _utc_now,
    _mark_observations_seen,
    _card_names,
    _project_exists,
    _project_observation_index,
    _project_observation_state,
    _read_json,
    _resolve_project,
    _unread_observation_ids,
    _workspace_exists,
    _workspace_tracking,
)
from .review_queue import (
    candidate_card_counts,
    candidate_card_ids,
    candidate_card_paths,
    parse_candidate_card,
)


def _base_card_setup_guidance(project: str) -> dict[str, object]:
    return {
        "status": "missing-cards-base",
        "message": f"No Cards Base is configured for project={project}.",
        "commands": [
            "pmagent infra auth-guide --brand lark --app-id <approved-app-id> --json",
            f"pmagent infra bootstrap --project {project} --json",
            f"pmagent infra bootstrap --project {project} --adopt-existing-base --base-token <base-app-token> --table-id <table-id> --json",
        ],
    }


def _is_missing_cards_base_error(exc: SystemExit) -> bool:
    message = str(exc)
    return (
        "No Cards Base is configured" in message
        or "PMAGENT_FEISHU_BASE_APP_TOKEN is not configured" in message
        or "PMAGENT_FEISHU_CARDS_TABLE_ID is not configured" in message
    )


def _candidate_review_detail_lines(payload: dict[str, object]) -> list[str]:
    candidate_review = payload.get("candidate_review", {}) if isinstance(payload.get("candidate_review"), dict) else {}
    cards = payload.get("cards", []) if isinstance(payload.get("cards"), list) else []
    cadence_recommendation = payload.get("cadence_recommendation", {}) if isinstance(payload.get("cadence_recommendation"), dict) else {}
    lines = [
        "Candidate Review 概览",
        markdown_table(
            ["字段", "值"],
            [
                ["workspace", str(payload.get("workspace") or "—")],
                ["project", str(payload.get("project") or "—")],
                ["inbox_count", str(candidate_review.get("inbox_count", payload.get("counts", {}).get("inbox", 0)) if isinstance(payload.get("counts"), dict) else candidate_review.get("inbox_count", 0))],
                ["accepted_count", str(candidate_review.get("accepted_count", payload.get("counts", {}).get("accepted", 0)) if isinstance(payload.get("counts"), dict) else candidate_review.get("accepted_count", 0))],
                ["pending_user_decision", str(payload.get("pending_user_decision") or "—")],
            ],
        ),
    ]
    suggestion = str(cadence_recommendation.get("suggested_cadence") or "").strip()
    if suggestion:
        lines.extend(
            [
                "",
                "Cadence Recommendation",
                markdown_table(
                    ["字段", "值"],
                    [
                        ["suggested_cadence", suggestion],
                        ["reason", str(cadence_recommendation.get("reason") or "—")],
                    ],
                ),
            ]
        )
    if cards:
        headers = ["card", "title", "kind"]
        rows: list[list[str]] = []
        for card in cards:
            row = [
                str(card.get("card") or "—"),
                str(card.get("title") or "—"),
                str(card.get("kind") or "—"),
            ]
            rows.append(row)
        lines.extend(["", "Candidate Review 单卡列表", markdown_table(headers, rows)])
        for card in cards:
            summary = str(card.get("summary") or "").strip()
            if not summary:
                continue
            lines.extend(
                [
                    "",
                    f"### {card.get('card')}",
                    f"- title: {card.get('title')}",
                    f"- summary: {summary}",
                    f"- file: {card.get('file')}",
                ]
            )
    return lines


def _maintenance_detail_lines(payload: dict[str, object]) -> list[str]:
    accepted_cards = payload.get("accepted_cards", []) if isinstance(payload.get("accepted_cards"), list) else []
    drafts = payload.get("drafts", []) if isinstance(payload.get("drafts"), list) else []
    cadence_recommendation = payload.get("cadence_recommendation", {}) if isinstance(payload.get("cadence_recommendation"), dict) else {}
    lines = [
        "Maintenance 概览",
        markdown_table(
            ["字段", "值"],
            [
                ["workspace", str(payload.get("workspace") or "—")],
                ["project", str(payload.get("project") or "—")],
                ["accepted_count", str(payload.get("accepted_count") or 0)],
                ["latest_draft", str(payload.get("latest_draft") or "—")],
            ],
        ),
    ]
    suggestion = str(cadence_recommendation.get("suggested_cadence") or "").strip()
    if suggestion:
        lines.extend(
            [
                "",
                "Cadence Recommendation",
                markdown_table(
                    ["字段", "值"],
                    [
                        ["suggested_cadence", suggestion],
                        ["reason", str(cadence_recommendation.get("reason") or "—")],
                    ],
                ),
            ]
        )
    if accepted_cards:
        lines.extend(["", "Accepted Cards", *[f"- {card}" for card in accepted_cards]])
    if drafts:
        lines.extend(["", "Drafts", *[f"- {draft}" for draft in drafts]])
    return lines


def _observation_decision_checkpoint_from_state(state: dict[str, object]) -> dict[str, object] | None:
    observation = state.get("observation", {}) if isinstance(state.get("observation"), dict) else {}
    decision_status = str(observation.get("decision_status", "unresolved") or "unresolved")
    enabled = bool(observation.get("enabled", False))
    cadence = str(observation.get("cadence", "manual") or "manual")
    recommendation = observation.get("cadence_recommendation", {}) if isinstance(observation.get("cadence_recommendation"), dict) else {}
    suggested_cadence = str(recommendation.get("suggested_cadence") or "").strip()
    phase = str(state.get("phase") or "")
    active_step = str(state.get("active_step") or "")
    next_step = state.get("next_recommended_step", {}) if isinstance(state.get("next_recommended_step"), dict) else {}
    next_step_id = str(next_step.get("id") or "")
    project = str(state.get("project") or "<project>")

    if decision_status == "unresolved":
        if phase == "clarifying" and active_step in {"write-requirement", "confirm-transition"}:
            return {
                "id": "confirm_observation_policy",
                "checkpoint": "workspace-init",
                "prompt": "This workspace has started, but observation policy is still unresolved. Ask whether observation should be enabled now and, if yes, which cadence to start with.",
                "reason": "Confirm observation strategy early so long-running workspaces do not silently stay in manual mode.",
                "enable_command": f"pmagent observe enable --project {project} --cadence weekly --confirm-cadence",
                "disable_command": f"pmagent observe disable --project {project}",
            }
        if phase == "researching" and next_step_id == "write_prd":
            return {
                "id": "confirm_observation_policy",
                "checkpoint": "pre-prd",
                "prompt": "Before moving into PRD drafting, confirm whether this workspace should keep a live observation loop and what cadence it should use.",
                "reason": "PRD drafting is the last stable checkpoint before long-lived downstream work; unresolved observation policy should be decided here.",
                "enable_command": f"pmagent observe enable --project {project} --cadence weekly --confirm-cadence",
                "disable_command": f"pmagent observe disable --project {project}",
            }

    if enabled and suggested_cadence and next_step_id in {"draft_maintenance", "observe_run", "export_workspace"}:
        return {
            "id": "confirm_observation_cadence",
            "checkpoint": "post-review",
            "prompt": "The latest review outcomes suggest a cadence change. Ask the user whether to keep the current cadence or switch to the suggested one.",
            "reason": str(recommendation.get("reason") or "Recent review outcomes changed the recommended observation cadence."),
            "current_cadence": cadence,
            "suggested_cadence": suggested_cadence,
            "set_cadence_command": f"pmagent observe set-cadence --project {project} --cadence {suggested_cadence} --confirm-cadence",
        }

    return None


def audit_observation(
    repo_root: Path,
    workspace: str,
    *,
    run_catch_up: bool = False,
    as_json: bool = False,
) -> int:
    _workspace_exists(repo_root, workspace)
    project = _infer_project_for_workspace(repo_root, workspace)
    profile = load_profile(repo_root, project, create=True)
    queue_status = _classify_queue(repo_root, workspace)
    if queue_status.state != "valid":
        bootstrap_workspace(repo_root, workspace)
        queue_status = _classify_queue(repo_root, workspace)

    last_run = {
        "last_run_id": profile.get("last_run_id"),
        "updated_at": profile.get("last_run_at"),
    }
    catch_up_needed = catch_up_due(profile, last_run if isinstance(last_run, dict) else None)
    catch_up_performed = False
    pull_result: dict[str, object] | None = None
    base_guidance: dict[str, object] | None = None

    if run_catch_up:
        try:
            from ..infra import pull_cards_from_base

            pull_result = pull_cards_from_base(repo_root, project=project, workspace=workspace)
            catch_up_performed = True
        except SystemExit as exc:
            if not _is_missing_cards_base_error(exc):
                raise
            base_guidance = _base_card_setup_guidance(project)

    unread_ids = _unread_observation_ids(repo_root, workspace)
    queue_summary = _read_json(queue_summary_path(repo_root, workspace))
    queue_counts = dict(queue_summary.get("counts", {}))
    queue_counts.update(candidate_card_counts(repo_root, workspace))
    inbox_card_ids = candidate_card_ids(repo_root, workspace, "inbox")
    total_inbox = len(inbox_card_ids) + len(unread_ids)
    queue_counts["inbox"] = total_inbox
    payload = {
        "project": project,
        "workspace": workspace,
        "primary_source": "candidate-updates",
        "base_pull": pull_result,
        "base_setup": base_guidance,
        "enabled": bool(profile.get("enabled", False)),
        "cadence": profile.get("cadence", "manual"),
        "catch_up_policy": profile.get("catch_up_policy"),
        "catch_up_needed": bool(base_guidance) or catch_up_needed,
        "catch_up_performed": catch_up_performed,
        "scheduler": profile.get("scheduler", {}),
        "review_stats": profile.get("review_stats", {}),
        "cadence_recommendation": profile.get("cadence_recommendation", {}),
        "last_run": last_run or {},
        "queue_counts": queue_counts,
        "pending_card_ids": inbox_card_ids,
        "unread_observation_ids": unread_ids,
        "legacy_observation_count": len(unread_ids),
        "inbox_cards": inbox_card_ids + unread_ids,
        "accepted_cards": _card_names(repo_root, workspace, "accepted"),
        "snoozed_cards": _card_names(repo_root, workspace, "snoozed"),
    }
    pending_review = total_inbox > 0
    if base_guidance:
        next_step = {
            "id": "infra_bootstrap",
            "reason": "Project Cards Base is not configured; bootstrap or bind Feishu Base before pulling inbound Candidate Cards.",
        }
    elif pending_review:
        next_step = {
            "id": "review_candidates",
            "reason": "Inbound Candidate Cards are waiting for review.",
        }
    else:
        next_step = {
            "id": "pull_base_cards",
            "reason": "No inbound Candidate Cards are pending; pull Feishu Base cards when you want to refresh the relay.",
        }
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "active_step": "candidate-review" if pending_review else "write-requirement",
            "pending_user_decision": "candidate-review" if pending_review else None,
            "observation_tracking": {
                "project": project,
                "pending_card_ids": inbox_card_ids,
                "pending_observation_ids": unread_ids,
                "last_card_pull_at": _utc_now() if pull_result is not None else None,
                "last_observation_sync_at": _utc_now(),
            },
            "next_recommended_step": {
                "id": next_step["id"],
                "reason": next_step["reason"],
            },
        },
        updated_by="observe-audit",
    )

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Observation audit for workspace={workspace}")
        print(f"enabled={payload['enabled']}")
        print(f"cadence={payload['cadence']}")
        print(f"catch_up_needed={payload['catch_up_needed']}")
        print(f"catch_up_performed={payload['catch_up_performed']}")
        print(f"task_name={payload['scheduler'].get('task_name')}")
        print(f"last_run_id={payload['last_run'].get('last_run_id')}")
        print(f"inbox_cards={len(inbox_card_ids)}")
        print(f"legacy_unread_observations={len(unread_ids)}")
        print(f"accepted={payload['queue_counts'].get('accepted', 0)}")
        print(f"snoozed={payload['queue_counts'].get('snoozed', 0)}")
        if base_guidance:
            print(base_guidance["message"])
            print("Run one of:")
            for command in base_guidance["commands"]:
                print(f"- {command}")
        suggestion = payload["cadence_recommendation"].get("suggested_cadence")
        if suggestion:
            print(f"cadence_recommendation={suggestion}")
            print(f"cadence_reason={payload['cadence_recommendation'].get('reason')}")
        if payload["inbox_cards"]:
            print("inbox_cards=" + ", ".join(payload["inbox_cards"]))
    return 0


def observation_status(repo_root: Path, project: str, *, workspace: str | None = None, as_json: bool = False) -> int:
    _project_exists(repo_root, project)
    payload = build_observation_status_payload(repo_root, project, workspace=workspace)

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        readiness = payload.get("readiness", {}) if isinstance(payload.get("readiness"), dict) else {}
        print(f"Observation status for project={project}")
        print(f"enabled={payload['enabled']}")
        print(f"cadence={payload['cadence']}")
        print(f"last_run_id={payload['last_run_id']}")
        print(f"last_run_at={payload['last_run_at']}")
        print(f"next_scheduled_run_at={payload['next_scheduled_run_at']}")
        print(f"catch_up_needed={payload['catch_up_needed']}")
        print(f"observation_count={payload['observation_count']}")
        print(f"decision_status={payload.get('decision_status')}")
        print(f"last_confirmed_at={payload.get('last_confirmed_at')}")
        print(f"confirmation_source={payload.get('confirmation_source')}")
        if workspace:
            print(f"workspace={workspace}")
            print(f"unread_observations={payload['workspace_tracking'].get('pending_count')}")
        suggestion = payload["cadence_recommendation"].get("suggested_cadence") if isinstance(payload["cadence_recommendation"], dict) else None
        if suggestion:
            print(f"cadence_recommendation={suggestion}")
            print(f"cadence_reason={payload['cadence_recommendation'].get('reason')}")
        checkpoint = payload.get("decision_checkpoint", {}) if isinstance(payload.get("decision_checkpoint"), dict) else {}
        if checkpoint:
            print(f"decision_checkpoint={checkpoint.get('checkpoint')}")
            print(f"decision_prompt={checkpoint.get('prompt')}")
    return 0


def build_observation_status_payload(repo_root: Path, project: str, *, workspace: str | None = None) -> dict[str, object]:
    _project_exists(repo_root, project)
    profile = load_profile(repo_root, project, create=True)
    state = _project_observation_state(repo_root, project)
    unread_ids: list[str] = []
    inbox_card_ids: list[str] = []
    decision_checkpoint: dict[str, object] | None = None
    if workspace:
        _workspace_exists(repo_root, workspace)
        unread_ids = _unread_observation_ids(repo_root, workspace)
        inbox_card_ids = candidate_card_ids(repo_root, workspace, "inbox")
        decision_checkpoint = _observation_decision_checkpoint_from_state(preview_current_state(repo_root, workspace))
    return {
        "project": project,
        "workspace": workspace,
        "enabled": bool(profile.get("enabled", False)),
        "cadence": profile.get("cadence", "manual"),
        "decision_status": profile.get("decision_status", "unresolved"),
        "last_confirmed_at": profile.get("last_confirmed_at"),
        "confirmation_source": profile.get("confirmation_source"),
        "last_run_id": state.get("last_run_id"),
        "last_run_at": state.get("last_run_at"),
        "next_scheduled_run_at": state.get("next_scheduled_run_at"),
        "catch_up_needed": catch_up_due(profile, {"updated_at": state.get("last_run_at")}),
        "needs_review": bool(inbox_card_ids or unread_ids),
        "observation_count": int(state.get("observation_count", 0) or 0),
        "cadence_recommendation": profile.get("cadence_recommendation", {}),
        "decision_checkpoint": decision_checkpoint,
        "workspace_tracking": {
            "pending_count": len(inbox_card_ids) + len(unread_ids),
            "pending_card_ids": inbox_card_ids,
            "pending_observation_ids": unread_ids,
        },
    }


def review_candidates(repo_root: Path, workspace: str, *, as_json: bool = False) -> int:
    payload = build_review_payload(repo_root, workspace)

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            build_guided_output(
                mode=None,
                phase=str(payload.get("phase") or ""),
                guided_view="observe-review",
                readiness=None,
                next_step=payload.get("next_recommended_step") if isinstance(payload.get("next_recommended_step"), dict) else None,
                pending_user_decision=str(payload.get("pending_user_decision") or ""),
                route_reason="Candidate review is active because unread observation items are waiting for user disposition.",
                detail_lines=_candidate_review_detail_lines(payload),
            )
        )
    return 0


def build_review_payload(repo_root: Path, workspace: str) -> dict[str, object]:
    _workspace_exists(repo_root, workspace)
    project = _infer_project_for_workspace(repo_root, workspace)
    unread_ids = _unread_observation_ids(repo_root, workspace)
    inbox_cards = [parse_candidate_card(repo_root, path) for path in candidate_card_paths(repo_root, workspace, "inbox")]
    inbox_card_ids = [str(card.get("card") or "") for card in inbox_cards if str(card.get("card") or "").strip()]
    total_inbox = len(inbox_cards) + len(unread_ids)
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "active_step": "candidate-review",
            "pending_user_decision": "candidate-review" if total_inbox else None,
            "observation_tracking": {
                "project": project,
                "pending_card_ids": inbox_card_ids,
                "pending_observation_ids": unread_ids,
                "last_observation_sync_at": _utc_now(),
            },
            "next_recommended_step": {
                "id": "review_candidates" if total_inbox else "pull_base_cards",
                "reason": "Inbound Candidate Cards are waiting for review." if total_inbox else "No inbound Candidate Cards remain; pull Feishu Base cards to refresh the relay.",
            },
        },
        updated_by="observe-review",
    )
    payload_cards: list[dict[str, object]] = list(inbox_cards)
    for observation_id in unread_ids:
        observation_path = observation_file_path(repo_root, project, observation_id)
        meta = _read_json(observation_path)
        if not isinstance(meta, dict):
            meta = {}
        body = str(meta.get("summary", ""))
        payload_cards.append(
            {
                "card": observation_id,
                "title": str(meta.get("title", observation_id)),
                "kind": str(meta.get("kind", "general")),
                "source": "legacy_observation",
                "url": str(meta.get("url") or meta.get("source_url") or ""),
                "status": "unread",
                "summary": body.strip(),
                "file": str(observation_path.relative_to(repo_root)).replace("\\", "/"),
            }
        )
    state = preview_current_state(repo_root, workspace)

    return {
        "workspace": workspace,
        "project": state.get("project"),

        "phase": state.get("phase"),
        "active_step": state.get("active_step"),
        "pending_user_decision": state.get("pending_user_decision"),
        "next_recommended_step": state.get("next_recommended_step"),
        "readiness": state.get("readiness"),
        "candidate_review": {
            "active": True,
            "inbox_count": len(payload_cards),
            "accepted_count": int(state.get("observation", {}).get("queue", {}).get("accepted", 0)) if isinstance(state.get("observation"), dict) else 0,
            "primary_source": "candidate-updates" if inbox_cards else "legacy_observation",
            "legacy_observation_count": len(unread_ids),
        },
        "cadence_recommendation": state.get("observation", {}).get("cadence_recommendation", {}) if isinstance(state.get("observation"), dict) else {},
        "cards": payload_cards,
        "counts": {
            "inbox": len(payload_cards),
            "accepted": int(state.get("observation", {}).get("queue", {}).get("accepted", 0)) if isinstance(state.get("observation"), dict) else 0,
            "legacy_observation": len(unread_ids),
        },
    }


def maintenance_status(repo_root: Path, workspace: str, *, as_json: bool = False) -> int:
    payload = build_maintenance_status_payload(repo_root, workspace)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            build_guided_output(
                mode=None,
                phase=str(payload.get("phase") or ""),
                guided_view="maintenance-status",
                readiness=None,
                next_step=payload.get("next_recommended_step") if isinstance(payload.get("next_recommended_step"), dict) else None,
                pending_user_decision=str(payload.get("pending_user_decision") or ""),
                route_reason="Maintenance status is active because accepted candidate cards and/or drafts are present.",
                detail_lines=_maintenance_detail_lines(payload),
            )
        )
    return 0


def build_maintenance_status_payload(repo_root: Path, workspace: str) -> dict[str, object]:
    _workspace_exists(repo_root, workspace)
    state = preview_current_state(repo_root, workspace)
    accepted_root = candidate_updates_root(repo_root, workspace) / "accepted"
    accepted_cards = sorted(path.name for path in accepted_root.glob("*.md")) if accepted_root.exists() else []
    drafts_root = maintenance_drafts_root(repo_root, workspace)
    drafts = sorted(path.name for path in drafts_root.glob("*.md")) if drafts_root.exists() else []
    latest_draft = drafts[-1] if drafts else None
    artifacts = state.get("artifacts", {}) if isinstance(state.get("artifacts"), dict) else {}
    prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
    prd_exists = bool(prd.get("canonical_path")) or str(prd.get("status") or "") in {"active", "maintained", "draft"}
    next_step = state.get("next_recommended_step", {}) if isinstance(state.get("next_recommended_step"), dict) else {}
    return {
        "workspace": workspace,
        "project": state.get("project"),

        "phase": "maintaining" if accepted_cards or drafts else state.get("phase"),
        "pending_user_decision": state.get("pending_user_decision"),
        "accepted_cards": accepted_cards,
        "accepted_count": len(accepted_cards),
        "drafts": drafts,
        "latest_draft": latest_draft,
        "cadence_recommendation": state.get("observation", {}).get("cadence_recommendation", {}) if isinstance(state.get("observation"), dict) else {},
        "next_recommended_step": next_step,
    }


def unread_observations(repo_root: Path, workspace: str, *, as_json: bool = False) -> int:
    _workspace_exists(repo_root, workspace)
    project = _infer_project_for_workspace(repo_root, workspace)
    unread_ids = _unread_observation_ids(repo_root, workspace)
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "observation_tracking": {
                "project": project,
                "pending_observation_ids": unread_ids,
                "last_observation_sync_at": _utc_now(),
            },
            "active_step": "candidate-review" if unread_ids else None,
            "pending_user_decision": "candidate-review" if unread_ids else None,
            "next_recommended_step": {
                "id": "review_candidates" if unread_ids else "write-requirement",
                "reason": "Unread observation items are waiting for review." if unread_ids else "No unread observation items remain.",
            },
        },
        updated_by="observe-unread",
    )
    files = [str(observation_file_path(repo_root, project, obs_id).relative_to(repo_root)).replace("\\", "/") for obs_id in unread_ids]
    payload = {
        "project": project,
        "workspace": workspace,
        "unread_observation_ids": unread_ids,
        "files": files,
        "tracking": state.get("observation_tracking"),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"workspace={workspace}")
        print(f"project={project}")
        print(f"unread_count={len(unread_ids)}")
        for file in files:
            print(file)
    return 0


def mark_read_observations(repo_root: Path, workspace: str, observation_ids: list[str], *, as_json: bool = False) -> int:
    _workspace_exists(repo_root, workspace)
    project = _infer_project_for_workspace(repo_root, workspace)
    state = _mark_observations_seen(repo_root, workspace, observation_ids)
    payload = {
        "project": project,
        "workspace": workspace,
        "marked_read_ids": observation_ids,
        "tracking": state.get("observation_tracking"),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"workspace={workspace}")
        print(f"project={project}")
        print("marked_read=" + ", ".join(observation_ids))
    return 0
