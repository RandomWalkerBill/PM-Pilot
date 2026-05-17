from __future__ import annotations

import argparse
import json
import re
import shutil
from copy import deepcopy
from importlib import resources
from pathlib import Path

from . import __version__
from .paths import DEFAULT_DATA_DIR, package_root, resolve_data_dir, write_global_config


MANAGED_BEGIN = "<!-- PMAGENT:MANAGED:BEGIN -->"
MANAGED_END = "<!-- PMAGENT:MANAGED:END -->"
MANAGED_MARKER = "PMAGENT:MANAGED"
MANAGED_FILES = ("AGENTS.md", "CLAUDE.md", "MEMORY.md")
LEGACY_MANAGED_RENAMES = {"claude.md": "CLAUDE.md"}
REFRESH_FILES = ("GOAL_STATE.md", "SUMMARY.md", "TEAM_SNAPSHOT.md", "README.md", ".env.example")
VERSION_FILE = ".pmagent-version"
INIT_DIRECTORIES = (
    "memory/persona",
    "memory/global",
    "decisions",
    "research/daily-digest",
    "context",
    "projects",
    "workspaces",
    "config",
    "ops/quality-log",
    "ops/weekly-reports",
    "cache",
    "ppt",
)
INIT_CONFIG_FILES = (
    "config/projects.json",
    "config/watchlist.json",
    "config/agent-workflow.yaml",
    "config/debate-executors.yaml",
    "config/executors.yaml",
    "config/integrations.json",
)
PACKAGE_SYNC_DIRS = ("skills", "templates")
HOST_AGENT_FILES = (".claude/settings.json", ".codex/config.toml.example")
PMAGENT_CLAUDE_HOOKS = (
    "session_bootstrap",
    "state_surface",
    "pre_bash_guard",
    "pre_write_guard",
    "post_mutation_check",
    "response_validator",
)

def _scaffold_root() -> Path:
    return package_root() / "scaffold"


def _copy_scaffold_file(data_dir: Path, relative_path: str) -> None:
    source = _scaffold_root() / relative_path
    target = data_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_host_agent_file(data_dir: Path, relative_path: str) -> str:
    """Copy a host-agent config (e.g. .claude/settings.json) into data_dir.

    Host-agent configs are written by end users all the time, so we must not
    clobber an existing file. If the target already exists we drop a
    ``.pmagent`` sibling (e.g. ``.claude/settings.pmagent.json``) so the user
    can diff and merge by hand.
    """

    source = _scaffold_root() / relative_path
    target = data_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        shutil.copy2(source, target)
        print(f"  created {relative_path}")
        return "created"

    # Build a sibling path that keeps the original suffix so the file is still
    # recognised by linters / validators. For .example files we just append.
    suffix = target.suffix
    if suffix:
        stem = target.stem
        sibling = target.parent / f"{stem}.pmagent{suffix}"
    else:
        sibling = target.with_name(target.name + ".pmagent")
    shutil.copy2(source, sibling)
    rel_sibling = sibling.relative_to(data_dir).as_posix()
    print(
        f"  SKIP {relative_path} (user file preserved); wrote template to {rel_sibling} for manual merge"
    )
    return "sibling"


def _is_pmagent_hook_command(command: object) -> bool:
    if not isinstance(command, str):
        return False
    return any(
        f"pmagent hook {hook_name}" in command or f"pmagent.cli hook {hook_name}" in command
        for hook_name in PMAGENT_CLAUDE_HOOKS
    )


def _remove_pmagent_hook_entries(matchers: object) -> list[object]:
    if not isinstance(matchers, list):
        return []

    cleaned: list[object] = []
    for matcher in matchers:
        if not isinstance(matcher, dict):
            cleaned.append(matcher)
            continue

        hooks = matcher.get("hooks")
        if not isinstance(hooks, list):
            cleaned.append(matcher)
            continue

        kept_hooks = [
            hook
            for hook in hooks
            if not (isinstance(hook, dict) and _is_pmagent_hook_command(hook.get("command")))
        ]
        if not kept_hooks:
            continue

        updated = dict(matcher)
        updated["hooks"] = kept_hooks
        cleaned.append(updated)
    return cleaned


def _merge_claude_settings_hooks(data_dir: Path) -> bool:
    source = _scaffold_root() / ".claude/settings.json"
    target = data_dir / ".claude/settings.json"

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print("  created .claude/settings.json")
        return True

    try:
        current = json.loads(target.read_text(encoding="utf-8"))
        template = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _copy_host_agent_file(data_dir, ".claude/settings.json")
        return False

    if not isinstance(current, dict) or not isinstance(template, dict):
        _copy_host_agent_file(data_dir, ".claude/settings.json")
        return False

    template_hooks = template.get("hooks")
    if not isinstance(template_hooks, dict):
        _copy_host_agent_file(data_dir, ".claude/settings.json")
        return False

    current_hooks = current.get("hooks")
    if isinstance(current_hooks, dict):
        merged_hooks = dict(current_hooks)
    elif "hooks" in current:
        _copy_host_agent_file(data_dir, ".claude/settings.json")
        return False
    else:
        merged_hooks = {}

    for event, template_matchers in template_hooks.items():
        existing_matchers = merged_hooks.get(event)
        merged_hooks[event] = [
            *_remove_pmagent_hook_entries(existing_matchers),
            *deepcopy(template_matchers if isinstance(template_matchers, list) else []),
        ]

    updated = dict(current)
    updated["hooks"] = merged_hooks

    if updated != current:
        target.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("  updated .claude/settings.json pmagent hooks")
    else:
        print("  .claude/settings.json pmagent hooks already up to date")
    return True


def _upgrade_host_agent_file(data_dir: Path, relative_path: str) -> str:
    if relative_path == ".claude/settings.json":
        return "merged" if _merge_claude_settings_hooks(data_dir) else "sibling"
    return _copy_host_agent_file(data_dir, relative_path)


def _copy_package_tree_preserving_existing(package_subdir: str, target_root: Path) -> tuple[int, int]:
    copied = 0
    skipped = 0
    with resources.as_file(resources.files("pmagent").joinpath(package_subdir)) as source_root:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file():
                continue
            target = target_root / source.relative_to(source_root)
            if target.exists():
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
    return copied, skipped


def _sync_package_tree_refreshing_packaged(package_subdir: str, target_root: Path) -> tuple[int, int]:
    refreshed = 0
    created = 0
    with resources.as_file(resources.files("pmagent").joinpath(package_subdir)) as source_root:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file():
                continue
            target = target_root / source.relative_to(source_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            shutil.copy2(source, target)
            if existed:
                refreshed += 1
            else:
                created += 1
    return refreshed, created


def _read_packaged_text(package_subpath: str) -> str:
    with resources.as_file(resources.files("pmagent").joinpath(package_subpath)) as path:
        return path.read_text(encoding="utf-8")


def _version_file(data_dir: Path) -> Path:
    return data_dir / VERSION_FILE


def _write_version_file(data_dir: Path) -> None:
    _version_file(data_dir).write_text(f"{__version__}\n", encoding="utf-8")


def _has_managed_markers(text: str) -> bool:
    return MANAGED_BEGIN in text and MANAGED_END in text


def _upgrade_managed_file(data_dir: Path, filename: str) -> str:
    target = data_dir / filename
    template = _scaffold_root() / filename

    if not target.exists():
        _copy_scaffold_file(data_dir, filename)
        print(f"  created {filename}")
        return "created"

    current = target.read_text(encoding="utf-8")
    if not _has_managed_markers(current):
        print(f"  SKIP {filename} (exists, no managed markers - manual migration required)")
        return "skipped"

    new_managed = template.read_text(encoding="utf-8")
    managed_end = new_managed.find(MANAGED_END)
    if managed_end == -1:
        print(f"  WARNING: {filename} template has no MANAGED markers, skipping")
        return "warning"
    new_managed_block = new_managed[: managed_end + len(MANAGED_END)]

    end_pos = current.find(MANAGED_END)
    current_managed_block = current[: end_pos + len(MANAGED_END)] if end_pos != -1 else ""
    if current_managed_block == new_managed_block:
        version_match = re.search(r"PMAGENT:VERSION:(.+?)-->", current)
        version = version_match.group(1).strip() if version_match else __version__
        print(f"  {filename} already up to date (v{version})")
        return "up_to_date"

    user_section = current[end_pos + len(MANAGED_END):] if end_pos != -1 else ""
    new_content = new_managed_block + user_section
    target.write_text(new_content, encoding="utf-8")
    print(f"  upgraded {filename} to v{__version__}")
    return "upgraded"


def _refresh_scaffold_file(data_dir: Path, filename: str) -> str:
    target = data_dir / filename
    if target.exists():
        _copy_scaffold_file(data_dir, filename)
        print(f"  refreshed {filename}")
        return "refreshed"
    _copy_scaffold_file(data_dir, filename)
    print(f"  created {filename}")
    return "created"


def _ensure_env_example_unignored(data_dir: Path) -> str:
    target = data_dir / ".gitignore"
    if not target.exists():
        _copy_scaffold_file(data_dir, ".gitignore")
        print("  created .gitignore")
        return "created"

    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    if "!.env.example" in {line.strip() for line in lines}:
        print("  .gitignore already allows .env.example")
        return "up_to_date"

    suffix = "" if not lines or lines[-1] == "" else "\n"
    target.write_text(
        "\n".join(lines) + suffix + "!.env.example\n",
        encoding="utf-8",
    )
    print("  updated .gitignore to allow .env.example")
    return "updated"


def _normalize_managed_aliases(data_dir: Path) -> None:
    existing_names = {path.name for path in data_dir.iterdir()} if data_dir.exists() else set()
    for legacy, canonical in LEGACY_MANAGED_RENAMES.items():
        legacy_path = data_dir / legacy
        canonical_path = data_dir / canonical
        has_legacy_exact = legacy in existing_names
        has_canonical_exact = canonical in existing_names
        if has_legacy_exact and not has_canonical_exact and legacy_path.exists():
            temp_path = data_dir / f"{canonical}.tmp-rename"
            legacy_path.replace(temp_path)
            temp_path.replace(canonical_path)
            print(f"  renamed {legacy} -> {canonical}")


def cmd_upgrade(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    _normalize_managed_aliases(data_dir)

    for filename in MANAGED_FILES:
        _upgrade_managed_file(data_dir, filename)

    for filename in REFRESH_FILES + INIT_CONFIG_FILES[1:]:
        _refresh_scaffold_file(data_dir, filename)

    _ensure_env_example_unignored(data_dir)

    for relative_path in HOST_AGENT_FILES:
        _upgrade_host_agent_file(data_dir, relative_path)

    for package_subdir in PACKAGE_SYNC_DIRS:
        refreshed, created = _sync_package_tree_refreshing_packaged(package_subdir, data_dir / package_subdir)
        print(f"  refreshed {package_subdir}/ ({refreshed} refreshed, {created} created)")

    _write_version_file(data_dir)
    print("upgrade complete")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    data_dir = Path(args.dir).expanduser().resolve() if args.dir else DEFAULT_DATA_DIR
    write_global_config(data_dir=data_dir)
    _normalize_managed_aliases(data_dir)

    for rel in INIT_DIRECTORIES:
        (data_dir / rel).mkdir(parents=True, exist_ok=True)

    for filename in MANAGED_FILES + ("GOAL_STATE.md", "SUMMARY.md", "TEAM_SNAPSHOT.md"):
        target = data_dir / filename
        if target.exists():
            content = target.read_text(encoding="utf-8")
            if MANAGED_MARKER in content:
                if filename in MANAGED_FILES:
                    _upgrade_managed_file(data_dir, filename)
                else:
                    print(f"  SKIP {filename} (exists, managed markers detected but no upgrade handler)")
            else:
                print(f"  SKIP {filename} (exists, no managed markers - manual migration required)")
        else:
            _copy_scaffold_file(data_dir, filename)
            print(f"  created {filename}")

    for filename in INIT_CONFIG_FILES:
        target = data_dir / filename
        if target.exists():
            print(f"  SKIP {filename} (exists, user data preserved)")
        else:
            _copy_scaffold_file(data_dir, filename)
            print(f"  created {filename}")

    for filename in ("README.md", ".env.example"):
        _copy_scaffold_file(data_dir, filename)
        print(f"  copied {filename}")

    for relative_path in HOST_AGENT_FILES:
        _copy_host_agent_file(data_dir, relative_path)

    for package_subdir in PACKAGE_SYNC_DIRS:
        copied, skipped = _copy_package_tree_preserving_existing(package_subdir, data_dir / package_subdir)
        print(f"  synced {package_subdir}/ ({copied} copied, {skipped} preserved)")

    env_path = data_dir / ".env"
    if not env_path.exists():
        _copy_scaffold_file(data_dir, ".env")
        print("  created .env")
    else:
        print("  SKIP .env (exists, user secrets preserved)")

    gitignore_path = data_dir / ".gitignore"
    if not gitignore_path.exists():
        _copy_scaffold_file(data_dir, ".gitignore")
        print("  created .gitignore")
    else:
        print("  SKIP .gitignore (exists, user data preserved)")

    _write_version_file(data_dir)

    print("  note: project-scoped observations/ plus workspace-local candidate-updates/ maintenance/ folders are created by workspace-init or observe init-workspace")
    print(f"Initialized data directory: {data_dir}")
    return 0
