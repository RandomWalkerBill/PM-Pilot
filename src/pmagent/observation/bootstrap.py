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
    mark_policy_decision,
    record_review_outcome,
    reset_cadence_recommendation,
    save_profile,
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
    _empty_queue_counts,
    _infer_project_for_workspace,
    _project_exists,
    _project_observation_index,
    _project_observation_state,
    _queue_summary_string,
    _run_id,
    _sync_observation_summary_from_state,
    _utc_now,
    _workspace_exists,
    _write_json,
    _write_project_observation_index,
    _write_project_observation_state,
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


def enable_observation(
    repo_root: Path,
    project: str,
    *,
    cadence: str,
    task_name: str | None = None,
) -> int:
    if cadence == "manual":
        raise SystemExit("cadence 'manual' cannot be enabled; use disable instead")
    if cadence not in SUPPORTED_CADENCES:
        raise SystemExit(f"unsupported observation cadence: {cadence}")

    _project_exists(repo_root, project)
    init_profile(repo_root, project)
    scheduler = configure_schedule(repo_root, project, cadence=cadence, task_name=task_name)
    profile = set_schedule_state(
        repo_root,
        project,
        enabled=True,
        cadence=cadence,
        scheduler=scheduler,
        reason="enabled observation scheduling",
    )
    mark_policy_decision(profile, decision_status="enabled", confirmation_source="observe-enable")
    save_profile(repo_root, project, profile)
    reset_cadence_recommendation(repo_root, project, "cadence changed; review new observation signal quality first")
    state = _project_observation_state(repo_root, project)
    state["next_scheduled_run_at"] = profile.get("scheduler", {}).get("last_configured_at")
    _write_project_observation_state(repo_root, project, state)
    print(f"Enabled observation scheduling for project={project}")
    print(f"cadence={cadence}")
    print(f"task_name={profile['scheduler'].get('task_name')}")
    return 0


def disable_observation(repo_root: Path, project: str) -> int:
    _project_exists(repo_root, project)
    profile = load_profile(repo_root, project, create=True)
    delete_schedule(
        profile.get("scheduler", {}).get("task_name"),
        platform=profile.get("scheduler", {}).get("platform"),
        plist_path=profile.get("scheduler", {}).get("plist_path"),
        unit_path=profile.get("scheduler", {}).get("unit_path"),
        timer_path=profile.get("scheduler", {}).get("timer_path"),
    )
    scheduler = {
        "platform": profile.get("scheduler", {}).get("platform"),
        "task_name": None,
        "command": None,
        "plist_path": None,
        "unit_path": None,
        "timer_path": None,
    }
    profile = set_schedule_state(
        repo_root,
        project,
        enabled=False,
        cadence="manual",
        scheduler=scheduler,
        reason="disabled observation scheduling",
    )
    mark_policy_decision(profile, decision_status="manual", confirmation_source="observe-disable")
    save_profile(repo_root, project, profile)
    reset_cadence_recommendation(repo_root, project, "observation scheduling disabled")
    state = _project_observation_state(repo_root, project)
    state["next_scheduled_run_at"] = None
    _write_project_observation_state(repo_root, project, state)
    print(f"Disabled observation scheduling for project={project}")
    return 0


def set_observation_cadence(repo_root: Path, project: str, *, cadence: str) -> int:
    if cadence == "manual":
        raise SystemExit("use 'disable' to stop observation scheduling")
    if cadence not in SUPPORTED_CADENCES:
        raise SystemExit(f"unsupported observation cadence: {cadence}")

    _project_exists(repo_root, project)
    profile = load_profile(repo_root, project, create=True)
    task_name = profile.get("scheduler", {}).get("task_name")
    scheduler = configure_schedule(
        repo_root,
        project,
        cadence=cadence,
        task_name=task_name,
        platform=profile.get("scheduler", {}).get("platform"),
    )
    profile = set_schedule_state(
        repo_root,
        project,
        enabled=True,
        cadence=cadence,
        scheduler=scheduler,
        reason="updated observation cadence",
    )
    mark_policy_decision(profile, decision_status="enabled", confirmation_source="observe-set-cadence")
    save_profile(repo_root, project, profile)
    reset_cadence_recommendation(repo_root, project, "cadence changed; observe the next review window before suggesting another adjustment")
    state = _project_observation_state(repo_root, project)
    _write_project_observation_state(repo_root, project, state)
    print(f"Updated observation cadence for project={project}")
    print(f"cadence={cadence}")
    print(f"task_name={scheduler.get('task_name')}")
    return 0


def initialize_workspace_observation(
    repo_root: Path,
    workspace: str,
    *,
    cadence: str = "manual",
    task_name: str | None = None,
) -> int:
    if cadence not in SUPPORTED_CADENCES:
        raise SystemExit(f"unsupported observation cadence: {cadence}")

    _workspace_exists(repo_root, workspace)
    project = _infer_project_for_workspace(repo_root, workspace)
    init_profile(repo_root, project)
    bootstrap_workspace(repo_root, workspace)

    if cadence == "manual":
        profile = set_schedule_state(
            repo_root,
            project,
            enabled=False,
            cadence="manual",
            scheduler={"platform": load_profile(repo_root, project, create=True).get("scheduler", {}).get("platform")},
            reason="initialized workspace observation in manual mode",
        )
        mark_policy_decision(profile, decision_status="unresolved", confirmation_source="workspace-init-default")
        save_profile(repo_root, project, profile)
        reset_cadence_recommendation(repo_root, project, "project observation initialized in manual mode")
    else:
        scheduler = configure_schedule(repo_root, project, cadence=cadence, task_name=task_name)
        profile = set_schedule_state(
            repo_root,
            project,
            enabled=True,
            cadence=cadence,
            scheduler=scheduler,
            reason="initialized project observation with scheduled cadence",
        )
        mark_policy_decision(profile, decision_status="enabled", confirmation_source="workspace-init")
        save_profile(repo_root, project, profile)
        reset_cadence_recommendation(repo_root, project, "project observation initialized; wait for review outcomes before changing cadence")

    summary_action = "unchanged"
    state = sync_current_state(
        repo_root,
        workspace,
        patch={
            "observation_ref": str(project_observation_root(repo_root, project).relative_to(repo_root)).replace("\\", "/"),
            "observation_tracking": {
                "project": project,
                "seen_observation_ids": [],
                "pending_observation_ids": [],
                "last_observation_sync_at": None,
            },
            "active_step": "write-requirement",
            "next_recommended_step": {
                "id": "clarify_scope",
                "reason": "Confirm the initial scope, non-goals, and delivery boundaries before expanding downstream artifacts.",
            },
        },
        updated_by="observe-init-workspace",
    )
    sync_project_state(
        repo_root,
        project,
        patch={
            "workspace_refs": sorted({workspace, *(preview_project_state(repo_root, project).get("workspace_refs", []))}),
            "observation": {
                "ref": str(project_observation_root(repo_root, project).relative_to(repo_root)).replace("\\", "/"),
                "index": str(project_observation_index_path(repo_root, project).relative_to(repo_root)).replace("\\", "/"),
            },
        },
    )
    print(f"Initialized workspace observation for workspace={workspace}")
    print(f"project={project}")
    print(f"cadence={profile.get('cadence')}")
    print(f"enabled={profile.get('enabled')}")
    print(f"summary_action={summary_action}")
    scheduler_state = profile.get("scheduler", {})
    if scheduler_state.get("task_name"):
        print(f"task_name={scheduler_state.get('task_name')}")
    return 0
