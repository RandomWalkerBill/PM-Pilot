from __future__ import annotations

from . import bootstrap as _bootstrap
from . import runner as _runner
from .bootstrap import (
    bootstrap_workspace as _bootstrap_workspace_impl,
    disable_observation as _disable_observation_impl,
    enable_observation as _enable_observation_impl,
    init_profile,
    initialize_workspace_observation as _initialize_workspace_observation_impl,
    set_observation_cadence as _set_observation_cadence_impl,
)
from .cards import accept_card, reject_card, snooze_card
from .maintenance import apply_maintenance, draft_maintenance
from .runner import (
    build_query_plan as _build_query_plan_impl,
    fetch_query_results as _fetch_query_results_impl,
    ingest_external as _ingest_external_impl,
    plan_only as _plan_only_impl,
    run_dry_run as _run_dry_run_impl,
    run_live as _run_live_impl,
)
from .status import (
    audit_observation,
    build_maintenance_status_payload,
    build_observation_status_payload,
    build_review_payload,
    maintenance_status,
    mark_read_observations,
    observation_status,
    review_candidates,
    unread_observations,
)

configure_schedule = _bootstrap.configure_schedule
delete_schedule = _bootstrap.delete_schedule
build_query_plan = _build_query_plan_impl
fetch_query_results = _fetch_query_results_impl
plan_only = _plan_only_impl
ingest_external = _ingest_external_impl


def _sync_bootstrap_hooks() -> None:
    _bootstrap.configure_schedule = configure_schedule
    _bootstrap.delete_schedule = delete_schedule


def bootstrap_workspace(repo_root, workspace):
    _sync_bootstrap_hooks()
    return _bootstrap_workspace_impl(repo_root, workspace)


def initialize_workspace_observation(repo_root, workspace, cadence='manual', task_name=None):
    _sync_bootstrap_hooks()
    return _initialize_workspace_observation_impl(repo_root, workspace, cadence=cadence, task_name=task_name)


def enable_observation(repo_root, project, cadence='daily', task_name=None):
    _sync_bootstrap_hooks()
    return _enable_observation_impl(repo_root, project, cadence=cadence, task_name=task_name)


def disable_observation(repo_root, project):
    _sync_bootstrap_hooks()
    return _disable_observation_impl(repo_root, project)


def set_observation_cadence(repo_root, project, cadence):
    _sync_bootstrap_hooks()
    return _set_observation_cadence_impl(repo_root, project, cadence=cadence)


def run_dry_run(repo_root, workspace):
    return _run_dry_run_impl(repo_root, workspace)


def run_live(repo_root, project, *, as_json=False, timeout_seconds=None):
    # keep monkeypatch compatibility for tests/consumers patching pmagent.observation.executor
    _runner.build_query_plan = build_query_plan
    _runner.fetch_query_results = fetch_query_results
    return _run_live_impl(repo_root, project, as_json=as_json, timeout_seconds=timeout_seconds)


def plan(repo_root, project):
    _runner.build_query_plan = build_query_plan
    return _plan_only_impl(repo_root, project)


__all__ = [
    'accept_card',
    'apply_maintenance',
    'audit_observation',
    'bootstrap_workspace',
    'build_maintenance_status_payload',
    'build_observation_status_payload',
    'build_query_plan',
    'build_review_payload',
    'configure_schedule',
    'delete_schedule',
    'disable_observation',
    'draft_maintenance',
    'enable_observation',
    'fetch_query_results',
    'ingest_external',
    'init_profile',
    'initialize_workspace_observation',
    'maintenance_status',
    'mark_read_observations',
    'observation_status',
    'plan_only',
    'reject_card',
    'review_candidates',
    'run_dry_run',
    'run_live',
    'set_observation_cadence',
    'snooze_card',
    'unread_observations',
]
