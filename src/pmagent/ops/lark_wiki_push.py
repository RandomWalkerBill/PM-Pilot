from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


# Maps local folder names to Feishu display names per the file-layer design doc.
_FOLDER_DISPLAY_NAMES: dict[str, str] = {
    "background": "background",
    "research": "research",
    "decisions": "decisions",
    "prd": "prd",
    "strategy": "strategy",
    "context": "context",
    "dev": "dev",
    "exports": "exports",
    "memory": "memory",
}

# Top-level files get fixed display names instead of folder treatment.
_TOPLEVEL_DISPLAY_NAMES: dict[str, str] = {
    "workspace-summary.md": "00-Workspace Summary",
    "Requirement.md": "01-Requirement",
    "PROJECT.md": "Project Overview",
}

_PROJECT_ROOT_KEY_TEMPLATE = "project/{project}"
_WORKSPACES_KEY_TEMPLATE = "project/{project}/workspaces"
_WORKSPACE_ROOT_KEY_TEMPLATE = "project/{project}/workspaces/{workspace}"
_PROJECT_FOLDER_KEY_TEMPLATE = "project/{project}/{path}"
_WORKSPACE_FOLDER_KEY_TEMPLATE = "project/{project}/workspaces/{workspace}/{path}"


def _lark_cli() -> str:
    executable = shutil.which("lark-cli.cmd") or shutil.which("lark-cli") or shutil.which("lark-cli.exe")
    if not executable:
        raise SystemExit("lark-cli is required")
    return executable


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(stdout.lstrip())
    if not isinstance(payload, dict):
        raise SystemExit("lark-cli returned unexpected JSON")
    return payload


def _run_json(args: list[str], *, input_text: str | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        [_lark_cli(), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise SystemExit(message)
    return _json_from_stdout(completed.stdout or "{}")


def _extract_node_token(payload: dict[str, Any]) -> str:
    """Extract node_token from wiki +node-create response (data may be nested or flat)."""
    data = payload.get("data")
    if isinstance(data, dict):
        token = str(data.get("node_token") or "").strip()
        if token:
            return token
    token = str(payload.get("node_token") or "").strip()
    return token


def _extract_obj_token(payload: dict[str, Any]) -> str:
    """Extract obj_token from wiki +node-create response."""
    data = payload.get("data")
    if isinstance(data, dict):
        token = str(data.get("obj_token") or "").strip()
        if token:
            return token
    token = str(payload.get("obj_token") or "").strip()
    return token


def _extract_url(payload: dict[str, Any]) -> str | None:
    """Extract wiki URL from +node-create response."""
    data = payload.get("data")
    if isinstance(data, dict):
        url = data.get("url") or data.get("doc_url")
        if url:
            return str(url)
    return payload.get("url") or payload.get("doc_url")


# ---------- node log (per-file mapping) ----------

def _node_log_path(data_dir: Path, workspace: str, project: str | None = None) -> Path:
    if project:
        return data_dir / "projects" / project / ".pmagent" / "feishu-wiki-nodes.jsonl"
    return data_dir / "workspaces" / workspace / ".pmagent" / "feishu-wiki-nodes.jsonl"


def _existing_node(data_dir: Path | None, workspace: str, relative: str, project: str | None = None) -> dict[str, Any] | None:
    if data_dir is None:
        return None
    log_path = _node_log_path(data_dir, workspace, project)
    if not log_path.exists():
        return None
    found: dict[str, Any] | None = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        same_project = not project or item.get("project") == project
        same_workspace = item.get("workspace") in (None, workspace)
        if (
            same_project
            and same_workspace
            and item.get("relative") == relative
            and item.get("obj_token")
        ):
            found = item
    return found


def _append_node_log(data_dir: Path | None, workspace: str, result: dict[str, Any], project: str | None = None) -> None:
    if data_dir is None:
        return
    log_path = _node_log_path(data_dir, workspace, project)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")


# ---------- folder node cache ----------

def _folder_cache_path(data_dir: Path, workspace: str, project: str | None = None) -> Path:
    if project:
        return data_dir / "projects" / project / ".pmagent" / "feishu-wiki-folders.json"
    return data_dir / "workspaces" / workspace / ".pmagent" / "feishu-wiki-folders.json"


def _load_folder_cache(data_dir: Path | None, workspace: str, project: str | None = None) -> dict[str, str]:
    """Returns {logical_key -> node_token} for created folder/section nodes."""
    if data_dir is None:
        return {}
    path = _folder_cache_path(data_dir, workspace, project)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in payload.items() if v}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_folder_cache(data_dir: Path | None, workspace: str, cache: dict[str, str], project: str | None = None) -> None:
    if data_dir is None:
        return
    path = _folder_cache_path(data_dir, workspace, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _project_infra_path(data_dir: Path, project: str) -> Path:
    return data_dir / "projects" / project / ".pmagent" / "feishu-infra.json"


def _read_project_infra(data_dir: Path, project: str | None) -> dict[str, Any]:
    if not project:
        return {}
    path = _project_infra_path(data_dir, project)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _create_wiki_node(
    title: str,
    *,
    space_id: str | None = None,
    parent_token: str | None = None,
) -> dict[str, Any]:
    """Create a docx wiki node under a space root or a parent node."""
    args = ["wiki", "+node-create", "--title", title, "--obj-type", "docx"]
    if parent_token:
        args.extend(["--parent-node-token", parent_token])
    elif space_id:
        args.extend(["--space-id", space_id])
    return _run_json(args)


def _ensure_workspace_root(
    workspace: str,
    space_id: str,
    folder_cache: dict[str, str],
    *,
    project: str | None = None,
) -> str:
    """Return node_token for the workspace root node, creating it if needed."""
    if project:
        project_key = _PROJECT_ROOT_KEY_TEMPLATE.format(project=project)
        if project_key in folder_cache:
            project_token = folder_cache[project_key]
        else:
            payload = _create_wiki_node(project, space_id=space_id)
            project_token = _extract_node_token(payload)
            if not project_token:
                raise SystemExit(f"wiki node create for project root did not return node_token: {payload}")
            folder_cache[project_key] = project_token

        workspaces_key = _WORKSPACES_KEY_TEMPLATE.format(project=project)
        if workspaces_key in folder_cache:
            workspaces_token = folder_cache[workspaces_key]
        else:
            payload = _create_wiki_node("workspaces", parent_token=project_token)
            workspaces_token = _extract_node_token(payload)
            if not workspaces_token:
                raise SystemExit(f"wiki node create for workspaces folder did not return node_token: {payload}")
            folder_cache[workspaces_key] = workspaces_token

        key = _WORKSPACE_ROOT_KEY_TEMPLATE.format(project=project, workspace=workspace)
        if key in folder_cache:
            return folder_cache[key]
        payload = _create_wiki_node(workspace, parent_token=workspaces_token)
        token = _extract_node_token(payload)
        if not token:
            raise SystemExit(f"wiki node create for workspace root did not return node_token: {payload}")
        folder_cache[key] = token
        return token

    key = f"__root__/{workspace}"
    if key in folder_cache:
        return folder_cache[key]
    payload = _create_wiki_node(workspace, space_id=space_id)
    token = _extract_node_token(payload)
    if not token:
        raise SystemExit(f"wiki node create for workspace root did not return node_token: {payload}")
    folder_cache[key] = token
    return token


def _ensure_project_root(
    project: str,
    space_id: str,
    folder_cache: dict[str, str],
) -> str:
    project_key = _PROJECT_ROOT_KEY_TEMPLATE.format(project=project)
    if project_key in folder_cache:
        return folder_cache[project_key]
    payload = _create_wiki_node(project, space_id=space_id)
    token = _extract_node_token(payload)
    if not token:
        raise SystemExit(f"wiki node create for project root did not return node_token: {payload}")
    folder_cache[project_key] = token
    return token


def _prime_project_folder_cache(
    folder_cache: dict[str, str],
    *,
    project: str | None,
    project_infra: dict[str, Any],
) -> None:
    """Seed folder cache from project infra so pushes reuse bootstrap-created nodes."""
    if not project:
        return
    project_node_token = str(project_infra.get("project_node_token") or "").strip()
    if project_node_token:
        folder_cache.setdefault(_PROJECT_ROOT_KEY_TEMPLATE.format(project=project), project_node_token)


def _folder_cache_key(*, scope: str, project: str | None, workspace: str, path: str) -> str:
    if scope == "project":
        if not project:
            raise SystemExit("project scope requires --project")
        return _PROJECT_FOLDER_KEY_TEMPLATE.format(project=project, path=path)
    if project:
        return _WORKSPACE_FOLDER_KEY_TEMPLATE.format(project=project, workspace=workspace, path=path)
    return f"{workspace}/{path}"


def _ensure_folder_node(
    folder_key: str,
    display_name: str,
    parent_token: str,
    folder_cache: dict[str, str],
) -> str:
    """Return node_token for a folder section node, creating it if needed."""
    if folder_key in folder_cache:
        return folder_cache[folder_key]
    payload = _create_wiki_node(display_name, parent_token=parent_token)
    token = _extract_node_token(payload)
    if not token:
        raise SystemExit(f"wiki node create for folder '{display_name}' did not return node_token: {payload}")
    folder_cache[folder_key] = token
    return token


def _resolve_parent_node(
    relative: str,
    workspace: str,
    space_id: str,
    folder_cache: dict[str, str],
    *,
    project: str | None = None,
    scope: str = "workspace",
) -> str:
    """
    Ensure all ancestor folder nodes exist for the given relative path and
    return the node_token of the immediate parent.

    Examples:
      "Requirement.md"            -> workspace root
      "research/research-log.md"  -> research node
      "dev/slices/SL-001.md"      -> dev/slices node
    """
    if scope == "project":
        if not project:
            raise SystemExit("project scope requires --project")
        root_token = _ensure_project_root(project, space_id, folder_cache)
    else:
        root_token = _ensure_workspace_root(workspace, space_id, folder_cache, project=project)

    parts = relative.split("/")
    if len(parts) == 1:
        # Top-level file: parent is the project or workspace root.
        return root_token

    # Build hierarchy level by level, excluding the filename (last part)
    parent_token = root_token
    accumulated: list[str] = []
    for folder in parts[:-1]:
        accumulated.append(folder)
        folder_key = _folder_cache_key(
            scope=scope,
            project=project,
            workspace=workspace,
            path="/".join(accumulated),
        )
        display_name = _FOLDER_DISPLAY_NAMES.get(folder, folder)
        parent_token = _ensure_folder_node(folder_key, display_name, parent_token, folder_cache)

    return parent_token


def _doc_display_title(workspace: str, relative: str) -> str:
    """Return a human-friendly title for the wiki node."""
    # Top-level files get fixed names
    if relative in _TOPLEVEL_DISPLAY_NAMES:
        return _TOPLEVEL_DISPLAY_NAMES[relative]
    # Nested files: use the filename without extension as title
    filename = relative.split("/")[-1]
    if filename.endswith(".md"):
        filename = filename[:-3]
    return filename


def push_file_to_wiki(
    *,
    file_path: Path,
    relative: str,
    workspace: str,
    space_id: str,
    data_dir: Path | None = None,
    project: str | None = None,
    scope: str = "workspace",
) -> dict[str, Any]:
    text = file_path.read_text(encoding="utf-8-sig", errors="replace")
    if not text.lstrip().startswith("#"):
        title_prefix = project if scope == "project" and project else workspace
        text = f"# {title_prefix} / {relative}\n\n{text}"

    title = _doc_display_title(workspace, relative)

    # Load persistent folder cache (workspace root + section folder nodes)
    folder_cache = _load_folder_cache(data_dir, workspace, project)
    project_infra = _read_project_infra(data_dir, project)
    _prime_project_folder_cache(folder_cache, project=project, project_infra=project_infra)

    existing = _existing_node(data_dir, workspace, relative, project)
    if scope == "project" and relative == "PROJECT.md":
        project_overview_node_token = str(project_infra.get("project_overview_node_token") or "").strip()
        project_overview_obj_token = str(project_infra.get("project_overview_obj_token") or "").strip()
        if project_overview_node_token and project_overview_obj_token:
            existing = {
                "node_token": project_overview_node_token,
                "obj_token": project_overview_obj_token,
                "url": None,
            }
    created = False
    node: dict[str, Any] = {}

    if existing:
        node = dict(existing)
        obj_token = str(existing["obj_token"]).strip()
    else:
        # Ensure all ancestor folder nodes exist and get parent token
        parent_token = _resolve_parent_node(relative, workspace, space_id, folder_cache, project=project, scope=scope)

        node_payload = _create_wiki_node(title, parent_token=parent_token)
        obj_token = _extract_obj_token(node_payload)
        if not obj_token:
            raise SystemExit(f"wiki node create did not return obj_token: {node_payload}")
        node = {
            "node_token": _extract_node_token(node_payload),
            "obj_token": obj_token,
            "url": _extract_url(node_payload),
        }
        created = True

    # Persist updated folder cache (may have grown during _resolve_parent_node)
    _save_folder_cache(data_dir, workspace, folder_cache, project)

    # Update document content via v2 API (--command / --doc-format / --content)
    update_payload = _run_json(
        [
            "docs",
            "+update",
            "--api-version",
            "v2",
            "--doc",
            obj_token,
            "--command",
            "overwrite",
            "--doc-format",
            "markdown",
            "--content",
            "-",
        ],
        input_text=text,
    )
    result = {
        "relative": relative,
        "project": project,
        "workspace": workspace,
        "scope": scope,
        "created": created,
        "node_token": node.get("node_token"),
        "obj_token": obj_token,
        "url": node.get("url"),
        "update": update_payload.get("data", update_payload),
    }
    _append_node_log(data_dir, workspace, result, project)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m pmagent.ops.lark_wiki_push")
    parser.add_argument("--file", required=True)
    parser.add_argument("--relative", default=None)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--space-id", default="my_library")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--scope", choices=["project", "workspace"], default=None)
    args = parser.parse_args()

    file_path = Path(args.file).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else None
    relative = args.relative or os.environ.get("PMAGENT_SYNC_RELATIVE") or file_path.name
    workspace = args.workspace or os.environ.get("PMAGENT_WORKSPACE") or "workspace"
    project = args.project or os.environ.get("PMAGENT_PROJECT") or None
    scope = args.scope or os.environ.get("PMAGENT_SYNC_SCOPE") or "workspace"
    if data_dir is None and os.environ.get("PMAGENT_DATA_DIR"):
        data_dir = Path(os.environ["PMAGENT_DATA_DIR"]).expanduser().resolve()

    result = push_file_to_wiki(
        file_path=file_path,
        relative=relative,
        workspace=workspace,
        space_id=args.space_id,
        data_dir=data_dir,
        project=project,
        scope=scope,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
