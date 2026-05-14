from __future__ import annotations

import argparse
from pathlib import Path

from pmagent.cli_helpers import configure_stdio_utf8
from pmagent.observation.executor import (
    accept_card,
    apply_maintenance,
    audit_observation,
    bootstrap_workspace,
    disable_observation,
    draft_maintenance,
    enable_observation,
    ingest_external,
    initialize_workspace_observation,
    mark_read_observations,
    maintenance_status,
    observation_status,
    plan_only,
    init_profile,
    reject_card,
    run_live,
    review_candidates,
    set_observation_cadence,
    snooze_card,
    unread_observations,
)
from pmagent.paths import resolve_data_dir


CADENCE_CONFIRM_ERROR = "observation cadence changes require explicit user confirmation; rerun with --confirm-cadence"


def _resolve_repo_root(value: Path | None) -> Path:
    return value.resolve() if value else resolve_data_dir()


def _repo_root_from_args(args: argparse.Namespace) -> Path:
    return _resolve_repo_root(args.repo_root)


def _cmd_init_profile(args: argparse.Namespace) -> int:
    project = args.project or args.workspace
    if not project:
        raise SystemExit("init-profile requires --project or --workspace")
    return init_profile(_repo_root_from_args(args), project)


def _cmd_run(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_args(args)
    project = args.project or (_run_observation_project_from_workspace(repo_root, args.workspace) if args.workspace else None) or args.workspace
    if not project:
        raise SystemExit("run requires --project or --workspace")
    return run_live(repo_root, project, as_json=args.json, timeout_seconds=args.timeout_seconds)


def _cmd_plan(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_args(args)
    project = args.project or (_run_observation_project_from_workspace(repo_root, args.workspace) if args.workspace else None) or args.workspace
    if not project:
        raise SystemExit("plan requires --project or --workspace")
    payload = plan_only(repo_root, project)
    if args.json:
        import json

        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Observation plan created for project={project}")
        print(f"run_id={payload['run_id']}")
        print(f"findings_path={payload['findings_path']}")
        print(f"next_command={payload['next_command']}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_args(args)
    project = args.project or (_run_observation_project_from_workspace(repo_root, args.workspace) if args.workspace else None) or args.workspace
    if not project:
        raise SystemExit("ingest requires --project or --workspace")
    return ingest_external(repo_root, project, run_id=args.run_id, findings_path=args.findings)


def _cmd_bootstrap_workspace(args: argparse.Namespace) -> int:
    return bootstrap_workspace(_repo_root_from_args(args), args.workspace)


def _cmd_accept(args: argparse.Namespace) -> int:
    return accept_card(_repo_root_from_args(args), args.workspace, args.card)


def _cmd_reject(args: argparse.Namespace) -> int:
    return reject_card(_repo_root_from_args(args), args.workspace, args.card)


def _cmd_snooze(args: argparse.Namespace) -> int:
    return snooze_card(_repo_root_from_args(args), args.workspace, args.card)


def _cmd_draft(args: argparse.Namespace) -> int:
    return draft_maintenance(_repo_root_from_args(args), args.workspace, args.card)


def _cmd_apply(args: argparse.Namespace) -> int:
    return apply_maintenance(_repo_root_from_args(args), args.workspace, args.draft)


def _cmd_init_workspace(args: argparse.Namespace) -> int:
    if args.cadence != "manual" and not args.confirm_cadence:
        raise SystemExit(CADENCE_CONFIRM_ERROR)
    return initialize_workspace_observation(
        _repo_root_from_args(args),
        args.workspace,
        cadence=args.cadence,
        task_name=args.task_name,
    )


def _cmd_enable(args: argparse.Namespace) -> int:
    if not args.confirm_cadence:
        raise SystemExit(CADENCE_CONFIRM_ERROR)
    project = args.project or (_run_observation_project_from_workspace(_repo_root_from_args(args), args.workspace) if args.workspace else None) or args.workspace
    return enable_observation(
        _repo_root_from_args(args),
        project,
        cadence=args.cadence,
        task_name=args.task_name,
    )


def _cmd_disable(args: argparse.Namespace) -> int:
    project = args.project or (_run_observation_project_from_workspace(_repo_root_from_args(args), args.workspace) if args.workspace else None) or args.workspace
    return disable_observation(_repo_root_from_args(args), project)


def _cmd_set_cadence(args: argparse.Namespace) -> int:
    if not args.confirm_cadence:
        raise SystemExit(CADENCE_CONFIRM_ERROR)
    project = args.project or (_run_observation_project_from_workspace(_repo_root_from_args(args), args.workspace) if args.workspace else None) or args.workspace
    return set_observation_cadence(
        _repo_root_from_args(args),
        project,
        cadence=args.cadence,
    )


def _cmd_audit(args: argparse.Namespace) -> int:
    return audit_observation(
        _repo_root_from_args(args),
        args.workspace,
        run_catch_up=args.run_catch_up,
        as_json=args.json,
    )


def _cmd_status(args: argparse.Namespace) -> int:
    project = args.project or (_run_observation_project_from_workspace(_repo_root_from_args(args), args.workspace) if args.workspace else None) or args.workspace
    return observation_status(
        _repo_root_from_args(args),
        project,
        workspace=args.workspace,
        as_json=args.json,
    )


def _cmd_review(args: argparse.Namespace) -> int:
    return review_candidates(
        _repo_root_from_args(args),
        args.workspace,
        as_json=args.json,
    )


def _cmd_maintenance_status(args: argparse.Namespace) -> int:
    return maintenance_status(
        _repo_root_from_args(args),
        args.workspace,
        as_json=args.json,
    )


def _cmd_unread(args: argparse.Namespace) -> int:
    return unread_observations(_repo_root_from_args(args), args.workspace, as_json=args.json)


def _cmd_mark_read(args: argparse.Namespace) -> int:
    return mark_read_observations(_repo_root_from_args(args), args.workspace, list(args.ids), as_json=args.json)


def _run_observation_project_from_workspace(repo_root: Path, workspace: str | None) -> str | None:
    if not workspace:
        return None
    import json

    config_path = repo_root / "config" / "projects.json"
    if not config_path.exists():
        return None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    projects = payload.get("projects", {})
    if not isinstance(projects, dict):
        return None
    for project, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        workspaces = entry.get("workspaces", [])
        if isinstance(workspaces, list) and workspace in {str(item) for item in workspaces}:
            return str(project)
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmagent.observation")
    parser.add_argument("--repo-root", type=Path, default=None, help="PM Agent data directory")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init-profile", help="Create observation-owned scaffold for a project")
    init_p.add_argument("--project", default=None)
    init_p.add_argument("--workspace", default=None)
    init_p.set_defaults(func=_cmd_init_profile)

    run_p = sub.add_parser("run", help="Run project observation")
    run_p.add_argument("--project", default=None)
    run_p.add_argument("--workspace", default=None)
    run_p.add_argument("--json", action="store_true")
    run_p.add_argument("--timeout-seconds", type=float, default=None)
    run_p.set_defaults(func=_cmd_run)

    plan_p = sub.add_parser("plan", help="Create an Agent-executable observation plan without searching")
    plan_p.add_argument("--project", default=None)
    plan_p.add_argument("--workspace", default=None)
    plan_p.add_argument("--json", action="store_true")
    plan_p.set_defaults(func=_cmd_plan)

    ingest_p = sub.add_parser("ingest", help="Ingest Agent-produced raw observation findings")
    ingest_p.add_argument("--project", default=None)
    ingest_p.add_argument("--workspace", default=None)
    ingest_p.add_argument("--run-id", required=True)
    ingest_p.add_argument("--findings", type=Path, required=True)
    ingest_p.set_defaults(func=_cmd_ingest)

    bootstrap_p = sub.add_parser("bootstrap-workspace", help="Create candidate-update queue scaffold")
    bootstrap_p.add_argument("--workspace", required=True)
    bootstrap_p.set_defaults(func=_cmd_bootstrap_workspace)

    accept_p = sub.add_parser("accept", help="Move a candidate card to accepted")
    accept_p.add_argument("--workspace", required=True)
    accept_p.add_argument("--card", required=True)
    accept_p.set_defaults(func=_cmd_accept)

    reject_p = sub.add_parser("reject", help="Move a candidate card to rejected")
    reject_p.add_argument("--workspace", required=True)
    reject_p.add_argument("--card", required=True)
    reject_p.set_defaults(func=_cmd_reject)

    snooze_p = sub.add_parser("snooze", help="Move a candidate card to snoozed")
    snooze_p.add_argument("--workspace", required=True)
    snooze_p.add_argument("--card", required=True)
    snooze_p.set_defaults(func=_cmd_snooze)

    draft_p = sub.add_parser("draft-maintenance", help="Create a PRD maintenance draft from accepted candidate cards")
    draft_p.add_argument("--workspace", required=True)
    draft_p.add_argument("--card", default=None)
    draft_p.set_defaults(func=_cmd_draft)

    apply_p = sub.add_parser("apply-maintenance", help="Apply a maintenance draft to the current PRD")
    apply_p.add_argument("--workspace", required=True)
    apply_p.add_argument("--draft", default=None)
    apply_p.set_defaults(func=_cmd_apply)

    init_workspace_p = sub.add_parser(
        "init-workspace",
        help="Initialize the observation stack for a new workspace and optionally schedule it",
    )
    init_workspace_p.add_argument("--workspace", required=True)
    init_workspace_p.add_argument(
        "--cadence",
        default="manual",
        choices=["manual", "weekly", "weekday-morning", "daily", "every-12-hours", "every-6-hours"],
    )
    init_workspace_p.add_argument("--confirm-cadence", action="store_true")
    init_workspace_p.add_argument("--task-name", default=None)
    init_workspace_p.set_defaults(func=_cmd_init_workspace)

    enable_p = sub.add_parser("enable", help="Enable scheduled observation for a project")
    enable_p.add_argument("--project", default=None)
    enable_p.add_argument("--workspace", default=None)
    enable_p.add_argument(
        "--cadence",
        required=True,
        choices=["weekly", "weekday-morning", "daily", "every-12-hours", "every-6-hours"],
    )
    enable_p.add_argument("--confirm-cadence", action="store_true")
    enable_p.add_argument("--task-name", default=None)
    enable_p.set_defaults(func=_cmd_enable)

    disable_p = sub.add_parser("disable", help="Disable scheduled observation for a project")
    disable_p.add_argument("--project", default=None)
    disable_p.add_argument("--workspace", default=None)
    disable_p.set_defaults(func=_cmd_disable)

    cadence_p = sub.add_parser("set-cadence", help="Update the scheduled observation cadence for a project")
    cadence_p.add_argument("--project", default=None)
    cadence_p.add_argument("--workspace", default=None)
    cadence_p.add_argument(
        "--cadence",
        required=True,
        choices=["weekly", "weekday-morning", "daily", "every-12-hours", "every-6-hours"],
    )
    cadence_p.add_argument("--confirm-cadence", action="store_true")
    cadence_p.set_defaults(func=_cmd_set_cadence)

    audit_p = sub.add_parser("audit", help="Summarize observation queue state before starting interactive work")
    audit_p.add_argument("--workspace", required=True)
    audit_p.add_argument("--run-catch-up", action="store_true")
    audit_p.add_argument("--json", action="store_true")
    audit_p.set_defaults(func=_cmd_audit)

    status_p = sub.add_parser("status", help="Show the current project observation status")
    status_p.add_argument("--project", default=None)
    status_p.add_argument("--workspace", default=None)
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=_cmd_status)

    unread_p = sub.add_parser("unread", help="List unread observation files for a workspace")
    unread_p.add_argument("--workspace", required=True)
    unread_p.add_argument("--json", action="store_true")
    unread_p.set_defaults(func=_cmd_unread)

    mark_read_p = sub.add_parser("mark-read", help="Mark observation ids as read for a workspace")
    mark_read_p.add_argument("--workspace", required=True)
    mark_read_p.add_argument("--ids", nargs="+", required=True)
    mark_read_p.add_argument("--json", action="store_true")
    mark_read_p.set_defaults(func=_cmd_mark_read)

    review_p = sub.add_parser("review", help="Summarize inbox candidate cards for user review")
    review_p.add_argument("--workspace", required=True)
    review_p.add_argument("--json", action="store_true")
    review_p.set_defaults(func=_cmd_review)

    maintenance_status_p = sub.add_parser("maintenance-status", help="Show maintenance readiness for accepted cards and drafts")
    maintenance_status_p.add_argument("--workspace", required=True)
    maintenance_status_p.add_argument("--json", action="store_true")
    maintenance_status_p.set_defaults(func=_cmd_maintenance_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
