from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


OBSERVE_SUBCOMMAND_ERROR = "observe requires a subcommand, e.g. 'run' or 'init-profile'"
CADENCE_CONFIRM_ERROR = "observation cadence changes require explicit user confirmation; rerun with --confirm-cadence"


def configure_stdio_utf8() -> None:
    """Prefer UTF-8 CLI output, especially for redirected JSON on Windows."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _dispatch_module(name: str, args: argparse.Namespace, extra: list[str] | None = None) -> int:
    module = __import__(f"pmagent.{name}", fromlist=["main"])
    argv = list(extra or [])
    if getattr(args, "data_dir", None):
        argv.extend(["--repo-root", str(Path(args.data_dir).expanduser().resolve())])
    old_argv = sys.argv[:]
    sys.argv = [f"pmagent.{name}", *argv]
    try:
        result = module.main()
        return 0 if result is None else int(result)
    finally:
        sys.argv = old_argv


def cmd_retrieve(args: argparse.Namespace) -> int:
    extra = ["--query", args.query]
    if args.mode:
        extra += ["--mode", args.mode]
    if args.project:
        extra += ["--project", args.project]
    if args.global_only:
        extra += ["--global-only"]
    if args.include_memory_index:
        extra += ["--include-memory-index"]
    if args.out:
        extra += ["--out", args.out]
    extra += ["--top-k", str(args.top_k)]
    return _dispatch_module("retrieval", args, extra)


def cmd_link(args: argparse.Namespace) -> int:
    extra: list[str] = []
    if args.file:
        extra += ["--file", args.file]
    if args.project:
        extra += ["--project", args.project]
    if args.all_projects:
        extra += ["--all-projects"]
    if args.reindex:
        extra += ["--reindex"]
    if args.dry_run:
        extra += ["--dry-run"]
    return _dispatch_module("linker", args, extra)


def cmd_conflicts(args: argparse.Namespace) -> int:
    extra: list[str] = []
    if args.new:
        extra += ["--new", args.new]
    if args.all:
        extra += ["--all"]
    extra += ["--threshold", str(args.threshold)]
    if args.out:
        extra += ["--out", args.out]
    return _dispatch_module("conflicts", args, extra)


def cmd_export(args: argparse.Namespace) -> int:
    extra: list[str] = []
    if args.project:
        extra += ["--project", args.project]
    if args.workspace:
        extra += ["--workspace", args.workspace]
    if args.output:
        extra += ["--output", args.output]
    return _dispatch_module("exporter", args, extra)


def cmd_digest(args: argparse.Namespace) -> int:
    extra = ["digest"]
    if args.config:
        extra += ["--config", args.config]
    return _dispatch_module("web_search", args, extra)


def cmd_search(args: argparse.Namespace) -> int:
    extra = ["search", "--query", args.query, "--count", str(args.count)]
    if args.freshness:
        extra += ["--freshness", args.freshness]
    if args.summary:
        extra += ["--summary"]
    if args.domain_preset:
        extra += ["--domain-preset", args.domain_preset]
    if args.out:
        extra += ["--out", args.out]
    if args.extra_prefer_domains:
        extra += ["--extra-prefer-domains", *args.extra_prefer_domains]
    return _dispatch_module("web_search", args, extra)


def cmd_weekly(args: argparse.Namespace) -> int:
    return _dispatch_module("weekly", args, [])


def cmd_skills_sync(args: argparse.Namespace) -> int:
    extra: list[str] = []
    if args.output_dir:
        extra += ["--output-dir", args.output_dir]
    return _dispatch_module("skills_sync", args, extra)


def cmd_install_launchd(args: argparse.Namespace) -> int:
    extra = [args.job]
    if args.hour is not None:
        extra += ["--hour", str(args.hour)]
    if args.minute is not None:
        extra += ["--minute", str(args.minute)]
    if args.weekday is not None:
        extra += ["--weekday", str(args.weekday)]
    return _dispatch_module("launchd", args, extra)


def _observe_repo_root_args(data_dir: str | None) -> list[str]:
    if not data_dir:
        return []
    repo_root = Path(data_dir).expanduser().resolve()
    return ["--repo-root", str(repo_root)]


def _require_cadence_confirmation(cadence: str, confirmed: bool) -> None:
    if cadence != "manual" and not confirmed:
        raise SystemExit(CADENCE_CONFIRM_ERROR)


def _resolve_workspace_init_cadence(cadence: str, *, enable_observation: bool, confirmed: bool) -> str:
    if enable_observation:
        if cadence == "manual":
            raise SystemExit(
                "--enable-observation requires a scheduled --observation-cadence; "
                "omit --enable-observation for manual mode or choose daily/weekly/every-12-hours/every-6-hours"
            )
        _require_cadence_confirmation(cadence, confirmed)
        return cadence
    if cadence != "manual":
        raise SystemExit("workspace-init will not schedule observation unless --enable-observation is provided")
    return "manual"
def _config_path(data_dir: Path) -> Path:
    return data_dir / "config" / "projects.json"


def _settings_path(data_dir: Path) -> Path:
    return data_dir / ".vscode" / "settings.json"


def _load_projects_config(data_dir: Path) -> dict:
    path = _config_path(data_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_projects_config(data_dir: Path, config: dict) -> None:
    path = _config_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_vscode_settings(data_dir: Path) -> dict:
    path = _settings_path(data_dir)
    if not path.exists():
        return {}
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("//"):
            continue
        lines.append(line)
    return json.loads("\n".join(lines))


def _save_vscode_settings(data_dir: Path, settings: dict) -> None:
    path = _settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


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


def _resolve_workspace_context(data_dir: Path, *, workspace: str | None = None) -> tuple[str | None, str]:
    config = _load_projects_config(data_dir)
    resolved_workspace = workspace or str(config.get("active_workspace") or "").strip()
    if not resolved_workspace:
        raise SystemExit("no active workspace found; use switch or pass --workspace")
    project = _infer_project_for_workspace(data_dir, resolved_workspace) or str(config.get("active_project") or "").strip() or None
    return project, resolved_workspace


def _infer_project_for_workspace(data_dir: Path, workspace: str) -> str | None:
    config = _load_projects_config(data_dir)
    projects = config.get("projects", {})
    if not isinstance(projects, dict):
        return None
    for project, info in projects.items():
        if not isinstance(info, dict):
            continue
        workspaces = info.get("workspaces", [])
        if isinstance(workspaces, list) and workspace in {str(item) for item in workspaces}:
            return str(project)
    return None
