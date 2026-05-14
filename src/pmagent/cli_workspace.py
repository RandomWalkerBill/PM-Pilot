from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .current_state import sync_current_state
from .observation.summary_protocol import build_workspace_summary_document_with_core
from .paths import resolve_data_dir
from .cli_helpers import (
    _load_projects_config,
    _load_vscode_settings,
    _resolve_workspace_init_cadence,
    _save_projects_config,
    _save_vscode_settings,
)
from .cli_scaffold import _copy_scaffold_file, _read_packaged_text

def _normalize_workspace_name(project: str, workspace: str | None, *, default_suffix: str = "discovery") -> str:
    project_name = str(project).strip()
    candidate = str(workspace or "").strip()
    if not project_name:
        return candidate
    if not candidate:
        return f"{project_name}-{default_suffix}"
    if candidate == project_name:
        return f"{project_name}-{default_suffix}"
    if candidate.startswith(f"{project_name}-"):
        return candidate
    return f"{project_name}-{candidate}"


def _project_root(data_dir: Path, project: str) -> Path:
    return data_dir / "projects" / project


def _workspace_root(data_dir: Path, workspace: str) -> Path:
    return data_dir / "workspaces" / workspace


def _ensure_project_scaffold(data_dir: Path, project: str, description: str, keywords: list[str]) -> None:
    project_root = _project_root(data_dir, project)
    for rel in ("strategy", "decisions", "memory", "research", "exports", "background"):
        (project_root / rel).mkdir(parents=True, exist_ok=True)

    project_file = project_root / "PROJECT.md"
    if not project_file.exists():
        keyword_text = ", ".join(keywords) if keywords else project
        project_file.write_text(
            "\n".join(
                [
                    f"# Project: {project}",
                    "",
                    f"- Description: {description or project}",
                    f"- Keywords: {keyword_text}",
                    f"- Created: {date.today().isoformat()}",
                    "",
                    "## Purpose",
                    "",
                    "<!-- Fill in the long-lived project direction here. -->",
                    "",
                ]
            ),
            encoding="utf-8",
        )


def _initial_observation_section(cadence: str) -> str:
    mode = "manual" if cadence == "manual" else "scheduled"
    return "\n".join(
        [
            "## Observation Focus",
            "",
            "<!-- What the observation layer should watch for this workspace. -->",
            "",
            "## Recent Observation",
            "",
            f"- Observation enabled: {'no' if cadence == 'manual' else 'yes'}",
            f"- Observation mode: {mode}",
            f"- Cadence: {cadence}",
            "- Last run: not started",
            "- Next scheduled run: not scheduled",
            "- Queue summary: inbox=0 accepted=0 rejected=0 snoozed=0",
            "- Needs review: no",
            "- Catch-up needed: no",
            "- Candidate updates: 0",
            "- Important pending signals: none",
        ]
    )


def _write_initial_workspace_summary(
    data_dir: Path,
    *,
    workspace: str,
    requirement_summary: str,
    cadence: str,
) -> None:
    summary_path = _workspace_root(data_dir, workspace) / "workspace-summary.md"
    if summary_path.exists():
        return

    core_section = "\n".join(
        [
            "## Current Goal",
            "",
            requirement_summary,
            "",
            "## Business Context / Current Scope",
            "",
            f"- Current scope: {requirement_summary}",
            "- Business context: <!-- Fill this in from requirement / user context. -->",
            "",
            "## Current State",
            "",
            "- Phase: `clarifying`",
            "- Active step: `write-requirement`",
            "- Pending user decision: `scope-confirmation`",
            "- Next recommended step: confirm the initial scope, non-goals, and delivery boundaries",
            "",
            "## Current PRD",
            "",
            "- Exists: `no`",
            "- Canonical path:",
            "- Current scope:",
            "",
            "## Current Understanding",
            "",
            "- The workspace has been initialized from the current requirement summary.",
            "- Observation is configured and can be audited before interactive work begins.",
            "- The next step is to confirm scope, non-goals, and decision boundaries before expanding downstream artifacts.",
            "",
            "## Key Decisions",
            "",
            "<!-- Link decision records rather than copying full text. -->",
            "",
            "## Open Questions",
            "",
            "- What is the smallest deliverable outcome for this workspace?",
            "- Which downstream artifact should become canonical first?",
            "",
            "## Readiness Overview",
            "",
            "- Readiness phase:",
            "- Readiness score:",
            "- Blocking gates:",
            "- Readiness summary:",
            "",
            "## Important Links",
            "",
            "- Requirement: `Requirement.md`",
            "- Research:",
            "- Decisions:",
            "- PRD:",
        ]
    )
    summary_path.write_text(
        build_workspace_summary_document_with_core(
            workspace=workspace,
            core_section=core_section,
            observation_section=_initial_observation_section(cadence),
        ),
        encoding="utf-8",
    )


def _ensure_workspace_scaffold(data_dir: Path, project: str, workspace: str, requirement_summary: str, priority: str, status: str) -> None:
    workspace_root = _workspace_root(data_dir, workspace)
    for rel in ("strategy", "decisions", "research", "context", "prd", "exports", "maintenance"):
        (workspace_root / rel).mkdir(parents=True, exist_ok=True)

    requirement_path = workspace_root / "Requirement.md"
    if not requirement_path.exists():
        template = _read_packaged_text("templates/REQUIREMENT_TEMPLATE.md")
        rendered = (
            template.replace("[需求名称]", workspace)
            .replace("<project>", project)
            .replace("> 一句话描述这个需求要解决什么问题、为谁解决。", f"> {requirement_summary}")
        )
        requirement_path.write_text(rendered, encoding="utf-8")


def _upsert_project_registry(data_dir: Path, project: str, workspace: str, description: str, keywords: list[str]) -> None:
    config = _load_projects_config(data_dir)
    projects = config.setdefault("projects", {})
    entry = projects.setdefault(project, {})
    entry["description"] = description or entry.get("description") or project
    existing_keywords = [str(item) for item in entry.get("keywords", []) if str(item).strip()]
    merged_keywords = list(dict.fromkeys([*existing_keywords, *[item for item in keywords if item]]))
    if merged_keywords:
        entry["keywords"] = merged_keywords
    workspaces = [str(item) for item in entry.get("workspaces", []) if str(item).strip()]
    if workspace not in workspaces:
        workspaces.append(workspace)
    entry["workspaces"] = workspaces
    config.setdefault("projects_root", "projects")
    config.setdefault("workspace_root", "workspaces")
    config["active_project"] = project
    config["active_workspace"] = workspace
    _save_projects_config(data_dir, config)


def cmd_workspace_init(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    project = args.project
    workspace = _normalize_workspace_name(project, args.workspace)
    keywords = [item.strip() for item in (args.keywords or []) if item.strip()]
    requirement_summary = args.requirement_summary or f"Define and deliver the {workspace} workspace."
    observation_cadence = _resolve_workspace_init_cadence(
        args.observation_cadence,
        enable_observation=bool(getattr(args, "enable_observation", False)),
        confirmed=bool(getattr(args, "confirm_cadence", False)),
    )

    _ensure_project_scaffold(data_dir, project, args.description or project, keywords)
    _ensure_workspace_scaffold(
        data_dir,
        project,
        workspace,
        requirement_summary,
        args.priority,
        args.status,
    )
    _write_initial_workspace_summary(
        data_dir,
        workspace=workspace,
        requirement_summary=requirement_summary,
        cadence=observation_cadence,
    )
    _upsert_project_registry(data_dir, project, workspace, args.description or project, keywords)
    _do_switch(data_dir, project, workspace)

    if not bool(getattr(args, "no_infra_bootstrap", False)):
        from .infra import bootstrap_project_infra

        bootstrap_project_infra(data_dir, project=project, fail_open=True)

    from .observation.executor import initialize_workspace_observation

    initialize_workspace_observation(
        data_dir,
        workspace,
        cadence=observation_cadence,
    )

    state = sync_current_state(
        data_dir,
        workspace,
        patch={
            "project": project,
            "phase": "clarifying",
            "active_step": "write-requirement",
            "pending_user_decision": "scope-confirmation",
            "next_recommended_step": {
                "id": "clarify_scope",
                "reason": "Confirm the initial scope, non-goals, and delivery boundaries before expanding downstream artifacts.",
            },
            "readiness": {
                "phase": "clarifying",
                "gates": {
                    "non_goals_resolved": False,
                    "decision_boundaries_resolved": False,
                },
                "summary": "Workspace scaffold created; confirm scope, non-goals, and decision boundaries before expanding downstream artifacts.",
            },
        },
        updated_by="workspace-init",
    )

    print(f"Initialized workspace scaffold: project={project}, workspace={workspace}")
    return 0
def _is_managed_key(key: str) -> bool:
    return key.startswith("projects/") or key.startswith("workspaces/")


def _scan_dirs(data_dir: Path, dirname: str) -> list[str]:
    base = data_dir / dirname
    if not base.exists():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir())


def _do_switch(data_dir: Path, project: str, workspace: str) -> None:
    config = _load_projects_config(data_dir)
    all_projects = _scan_dirs(data_dir, "projects")
    all_workspaces = _scan_dirs(data_dir, "workspaces")

    settings = _load_vscode_settings(data_dir)
    files_exclude = settings.get("files.exclude", {})
    files_exclude = {k: v for k, v in files_exclude.items() if not _is_managed_key(k)}

    for name in all_projects:
        if name != project:
            files_exclude[f"projects/{name}"] = True
    for name in all_workspaces:
        if name != workspace:
            files_exclude[f"workspaces/{name}"] = True

    settings["files.exclude"] = files_exclude
    _save_vscode_settings(data_dir, settings)

    config["active_project"] = project
    config["active_workspace"] = workspace
    _save_projects_config(data_dir, config)
    print(f"switched to project={project}, workspace={workspace}")


def _do_list(data_dir: Path) -> None:
    config = _load_projects_config(data_dir)
    projects = config.get("projects", {})
    if not projects:
        print("No projects registered.")
        return
    active_project = config.get("active_project")
    active_workspace = config.get("active_workspace")
    for name, info in projects.items():
        marker = " [active]" if name == active_project else ""
        print(f"{name}{marker}")
        if info.get("description"):
            print(f"  description: {info['description']}")
        for workspace in info.get("workspaces", []):
            ws_marker = " [active]" if workspace == active_workspace else ""
            print(f"  workspace: {workspace}{ws_marker}")


def _do_clear(data_dir: Path) -> None:
    settings = _load_vscode_settings(data_dir)
    files_exclude = settings.get("files.exclude", {})
    settings["files.exclude"] = {k: v for k, v in files_exclude.items() if not _is_managed_key(k)}
    _save_vscode_settings(data_dir, settings)

    config = _load_projects_config(data_dir)
    config["active_project"] = ""
    config["active_workspace"] = ""
    _save_projects_config(data_dir, config)
    print("cleared project isolation")



def cmd_switch(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)

    if args.list:
        _do_list(data_dir)
        return 0
    if args.clear:
        _do_clear(data_dir)
        return 0
    if not args.project:
        raise SystemExit("switch requires a project name unless --list or --clear is used")
    _do_switch(data_dir, args.project, _normalize_workspace_name(args.project, args.workspace))
    return 0


def cmd_workspace_close(args: argparse.Namespace) -> int:
    from .cli_routing import _status_payload

    data_dir = resolve_data_dir(args.data_dir)
    payload = _status_payload(data_dir, workspace=args.workspace)
    tracking = payload.get("observation_tracking", {}) if isinstance(payload.get("observation_tracking"), dict) else {}
    pending_observation_ids = tracking.get("pending_observation_ids", []) if isinstance(tracking, dict) else []
    blockers: list[str] = []
    if payload.get("pending_user_decision"):
        blockers.append(f"pending_user_decision={payload.get('pending_user_decision')}")
    if pending_observation_ids:
        blockers.append(f"pending_observations={len(pending_observation_ids)}")

    promotion_root = data_dir / "memory" / "global-candidates"
    promotion_root.mkdir(parents=True, exist_ok=True)
    candidate_path = promotion_root / f"{date.today().isoformat()}-{payload.get('workspace')}-global-promotion.md"

    payload_out = {
        "workspace": payload.get("workspace"),
        "project": payload.get("project"),
        "closable": not blockers,
        "blockers": blockers,
        "global_candidate_path": str(candidate_path.relative_to(data_dir)).replace("\\", "/") if not blockers else None,
    }

    if not blockers:
        lines = [
            f"# Global Promotion Candidate: {payload.get('workspace')}",
            "",
            f"- Workspace: `{payload.get('workspace')}`",
            f"- Project: `{payload.get('project')}`",
            f"- Phase at close: `{payload.get('phase')}`",
            f"- Active step at close: `{payload.get('active_step')}`",
            "",
            "## Candidate Knowledge",
            "",
            "<!-- Distill only cross-project reusable knowledge here. -->",
            "",
            "## Source Links",
            "",
            f"- Summary: `workspaces/{payload.get('workspace')}/workspace-summary.md`",
            f"- Current state: `workspaces/{payload.get('workspace')}/.pmagent/current-state.json`",
        ]
        candidate_path.write_text("\n".join(lines), encoding="utf-8")
        sync_current_state(
            data_dir,
            str(payload.get("workspace")),
            patch={
                "next_recommended_step": {
                    "id": "review_global_candidate",
                    "reason": "Review the generated global promotion candidate before merging knowledge into the global layer.",
                }
            },
            updated_by="workspace-close",
        )

    if args.json:
        print(json.dumps(payload_out, ensure_ascii=False, indent=2))
    else:
        print(f"workspace={payload_out['workspace']}")
        print(f"project={payload_out['project']}")
        print(f"closable={payload_out['closable']}")
        if blockers:
            print("blockers=" + ", ".join(blockers))
        else:
            print(f"global_candidate_path={payload_out['global_candidate_path']}")
    return 0
