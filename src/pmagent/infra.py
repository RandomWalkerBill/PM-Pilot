from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from .advisor import CARD_SCHEMA, write_protocol
from .cli_helpers import _infer_project_for_workspace, _resolve_workspace_context
from .current_state import sync_current_state
from .observation.cards import _update_queue_summary
from .observation.paths import candidate_updates_root, project_root, workspace_root
from .paths import resolve_data_dir


WIKI_SYNC_WHITELIST = [
    "Requirement.md",
    "workspace-summary.md",
    "research/*.md",
    "decisions/*.md",
    "prd/*.md",
    "strategy/*.md",
    "context/clarifying-log.md",
    "dev/dev-plan.md",
    "dev/slices/*.md",
    "dev/qa/*.md",
    "dev/lessons/*.md",
    "dev/runs/**/*.md",
    "exports/**",
]

PROJECT_WIKI_SYNC_WHITELIST = [
    "PROJECT.md",
    "background/**/*.md",
    "research/**/*.md",
    "strategy/**/*.md",
    "decisions/**/*.md",
    "memory/**/*.md",
    "exports/**",
]

WIKI_SYNC_EXCLUDES = [
    ".pmagent/*.json",
    "observations/**",
    "candidate-updates/**",
    "cache/**",
]

FEISHU_WIKI_PUSH_COMMAND_ENV = "PMAGENT_FEISHU_WIKI_PUSH_COMMAND"
FEISHU_WIKI_SPACE_ID_ENV = "PMAGENT_FEISHU_WIKI_SPACE_ID"
FEISHU_BASE_APP_TOKEN_ENV = "PMAGENT_FEISHU_BASE_APP_TOKEN"
FEISHU_CARDS_TABLE_ID_ENV = "PMAGENT_FEISHU_CARDS_TABLE_ID"
GITHUB_REMOTE_ENV = "PMAGENT_GITHUB_REMOTE"
GIT_USER_NAME_ENV = "PMAGENT_GIT_USER_NAME"
GIT_USER_EMAIL_ENV = "PMAGENT_GIT_USER_EMAIL"
DEFAULT_FEISHU_WIKI_SPACE_ID = "my_library"

BASE_CARD_FIELDS = [
    "card_id",
    "source_type",
    "source_ref",
    "target_project",
    "target_workspace",
    "title",
    "body",
    "evidence",
    "suggested_action",
    "urgency",
    "status",
    "created_at",
    "reviewed_at",
    "review_note",
    "expires_at",
]

BASE_CARD_FIELD_TYPES = {
    "card_id": "text",
    "source_type": "select",
    "source_ref": "text",
    "target_project": "text",
    "target_workspace": "text",
    "title": "text",
    "body": "text",
    "evidence": "text",
    "suggested_action": "text",
    "urgency": "select",
    "status": "select",
    "created_at": "datetime",
    "reviewed_at": "datetime",
    "review_note": "text",
    "expires_at": "datetime",
}

BASE_CARD_SELECT_OPTIONS = {
    "urgency": ["low", "normal", "high"],
    "status": ["inbox", "accepted", "rejected", "snoozed"],
}

FEISHU_MINIMAL_AUTH_SCOPES = [
    "offline_access",
    "wiki:wiki",
    "wiki:wiki:readonly",
    "wiki:space:retrieve",
    "wiki:space:read",
    "wiki:node:create",
    "wiki:node:read",
    "wiki:node:retrieve",
    "base:app:create",
    "base:app:read",
    "base:table:create",
    "base:table:read",
    "base:field:create",
    "base:field:read",
    "base:record:create",
    "base:record:read",
    "base:record:update",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_env_file(data_dir: Path) -> dict[str, str]:
    path = data_dir / ".env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _env_or_file(data_dir: Path, key: str) -> str | None:
    value = os.environ.get(key)
    if value and value.strip():
        return value.strip()
    value = _read_env_file(data_dir).get(key)
    if value and value.strip():
        return value.strip()
    return None


def _integration_feishu_config(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "config" / "integrations.json"
    if not path.exists():
        return {}
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    feishu = payload.get("feishu")
    return feishu if isinstance(feishu, dict) else {}


def _lark_cli_executable_path() -> str | None:
    return shutil.which("lark-cli.cmd") or shutil.which("lark-cli") or shutil.which("lark-cli.exe")


def _lark_cli_executable() -> str:
    executable = _lark_cli_executable_path()
    if not executable:
        raise SystemExit("lark-cli is required for Feishu Base integration")
    return executable


def _lark_cli_available() -> bool:
    return bool(_lark_cli_executable_path())


def _lark_cli_config_available(data_dir: Path) -> bool:
    executable = _lark_cli_executable_path()
    if not executable:
        return False
    try:
        completed = subprocess.run(
            [executable, "config", "show"],
            cwd=data_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _shell_arg(value: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def _builtin_lark_wiki_push_command(data_dir: Path) -> tuple[str, str] | None:
    if not _lark_cli_available() or not _lark_cli_config_available(data_dir):
        return None
    feishu_config = _integration_feishu_config(data_dir)
    configured_space_env = str(feishu_config.get("wiki_space_id_env") or "").strip()
    space_id = (
        _env_or_file(data_dir, FEISHU_WIKI_SPACE_ID_ENV)
        or (_env_or_file(data_dir, configured_space_env) if configured_space_env else None)
        or str(feishu_config.get("wiki_space_id") or "").strip()
        or str(feishu_config.get("default_wiki_space_id") or "").strip()
        or DEFAULT_FEISHU_WIKI_SPACE_ID
    )
    command = (
        f"{_shell_arg(sys.executable)} -m pmagent.ops.lark_wiki_push "
        '--file "{file}" --relative "{relative}" --workspace "{workspace}" --project "{project}" --data-dir "{data_dir}" '
        f"--space-id {_shell_arg(space_id)}"
    )
    return command, space_id


def _wiki_push_adapter(data_dir: Path, *, command: str | None = None) -> dict[str, Any]:
    if command and command.strip():
        return {
            "configured": True,
            "adapter": "custom-command",
            "command": command.strip(),
            "command_source": "argument",
            "space_id": None,
        }

    env_command = _env_or_file(data_dir, FEISHU_WIKI_PUSH_COMMAND_ENV)
    if env_command:
        return {
            "configured": True,
            "adapter": "custom-command",
            "command": env_command,
            "command_source": FEISHU_WIKI_PUSH_COMMAND_ENV,
            "space_id": None,
        }

    builtin = _builtin_lark_wiki_push_command(data_dir)
    if builtin:
        builtin_command, space_id = builtin
        return {
            "configured": True,
            "adapter": "builtin-lark",
            "command": builtin_command,
            "command_source": "builtin-lark",
            "space_id": space_id,
        }

    return {
        "configured": False,
        "adapter": "none",
        "command": None,
        "command_source": None,
        "space_id": None,
    }


def _run_lark_cli_json(data_dir: Path, args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [_lark_cli_executable(), *args],
        cwd=data_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise SystemExit(f"lark-cli failed: {message}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"lark-cli returned non-JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("lark-cli returned unexpected non-object JSON output")
    return payload


def _project_infra_path(data_dir: Path, project: str) -> Path:
    return data_dir / "projects" / project / ".pmagent" / "feishu-infra.json"


def _read_project_infra(data_dir: Path, project: str | None) -> dict[str, Any]:
    if not project:
        return {}
    path = _project_infra_path(data_dir, project)
    if not path.exists():
        return {}
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_project_infra(data_dir: Path, project: str, payload: dict[str, Any]) -> None:
    path = _project_infra_path(data_dir, project)
    existing = _read_project_infra(data_dir, project)
    merged = {**existing, **payload}
    merged.setdefault("schema_version", 1)
    merged["project"] = project
    merged["updated_at"] = _utc_now()
    if "created_at" not in merged:
        merged["created_at"] = merged["updated_at"]
    _write_json(path, merged)


def _base_config(
    data_dir: Path,
    *,
    base_token: str | None,
    table_id: str | None,
    project: str | None = None,
) -> tuple[str, str]:
    project_infra = _read_project_infra(data_dir, project)
    resolved_base = (
        base_token
        or str(project_infra.get("cards_base_app_token") or "").strip()
        or _env_or_file(data_dir, FEISHU_BASE_APP_TOKEN_ENV)
    )
    resolved_table = (
        table_id
        or str(project_infra.get("cards_table_id") or "").strip()
        or _env_or_file(data_dir, FEISHU_CARDS_TABLE_ID_ENV)
    )
    if not resolved_base:
        raise SystemExit(f"{FEISHU_BASE_APP_TOKEN_ENV} is not configured")
    if not resolved_table:
        raise SystemExit(f"{FEISHU_CARDS_TABLE_ID_ENV} is not configured")
    return resolved_base, resolved_table


def _extract_payload_value(payload: dict[str, Any], *keys: str) -> str:
    candidates: list[dict[str, Any]] = []

    def collect(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        candidates.append(candidate)
        for value in candidate.values():
            if isinstance(value, dict):
                collect(value)

    collect(payload)
    for candidate in candidates:
        for key in keys:
            value = str(candidate.get(key) or "").strip()
            if value:
                return value
    return ""


def _ensure_project_wiki_node(data_dir: Path, project: str, space_id: str) -> tuple[str | None, str]:
    project_infra = _read_project_infra(data_dir, project)
    existing = str(project_infra.get("project_node_token") or "").strip()
    if existing:
        return existing, "existing"
    payload = _run_lark_cli_json(
        data_dir,
        ["wiki", "+node-create", "--title", project, "--obj-type", "docx", "--space-id", space_id],
    )
    token = _extract_payload_value(payload, "node_token")
    if not token:
        raise SystemExit(f"wiki node create for project root did not return node_token: {payload}")
    return token, "created"


def _create_cards_base(data_dir: Path, project: str, project_node_token: str | None) -> tuple[str, str | None]:
    args = ["base", "+base-create", "--as", "user", "--name", f"{project} Cards Base", "--time-zone", "Asia/Shanghai"]
    payload = _run_lark_cli_json(data_dir, args)
    token = _extract_payload_value(payload, "app_token", "base_token", "base_app_token")
    node_token = _extract_payload_value(payload, "node_token")
    if not token:
        raise SystemExit(f"base app create did not return app_token: {payload}")
    return token, node_token or None


def _move_cards_base_to_project_wiki(
    data_dir: Path,
    *,
    space_id: str,
    project_node_token: str | None,
    base_token: str,
) -> str | None:
    if not project_node_token:
        return None
    payload = _run_lark_cli_json(
        data_dir,
        [
            "wiki",
            "+move",
            "--obj-type",
            "bitable",
            "--obj-token",
            base_token,
            "--target-space-id",
            space_id,
            "--target-parent-token",
            project_node_token,
        ],
    )
    return _extract_payload_value(payload, "wiki_token", "node_token") or None


def _create_cards_table(data_dir: Path, base_token: str) -> str:
    payload = _run_lark_cli_json(
        data_dir,
        ["base", "+table-create", "--as", "user", "--base-token", base_token, "--name", "Candidate Cards"],
    )
    table_id = _extract_payload_value(payload, "table_id", "id")
    if not table_id:
        raise SystemExit(f"base table create did not return table_id: {payload}")
    return table_id


def _record_list_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    candidates: list[Any] = [payload.get("items"), payload.get("records"), payload.get("fields")]
    if isinstance(data, dict):
        candidates.extend([data.get("items"), data.get("records"), data.get("fields")])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _existing_base_field_names(data_dir: Path, base_token: str, table_id: str) -> set[str]:
    payload = _run_lark_cli_json(
        data_dir,
        ["base", "+field-list", "--as", "user", "--base-token", base_token, "--table-id", table_id],
    )
    names: set[str] = set()
    for item in _record_list_items(payload):
        name = str(item.get("field_name") or item.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def _base_card_field_payload(field: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": field,
        "type": BASE_CARD_FIELD_TYPES.get(field, "text"),
    }
    if field in BASE_CARD_SELECT_OPTIONS:
        payload["multiple"] = False
        payload["options"] = [{"name": value} for value in BASE_CARD_SELECT_OPTIONS[field]]
    if payload["type"] == "datetime":
        payload["style"] = {"format": "yyyy/MM/dd HH:mm"}
    return payload


def _ensure_cards_table_fields(data_dir: Path, base_token: str, table_id: str) -> list[str]:
    created: list[str] = []
    existing_names = _existing_base_field_names(data_dir, base_token, table_id)
    for field in BASE_CARD_FIELDS:
        if field in existing_names:
            continue
        field_payload = _base_card_field_payload(field)
        try:
            _run_lark_cli_json(
                data_dir,
                [
                    "base",
                    "+field-create",
                    "--as",
                    "user",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--json",
                    json.dumps(field_payload, ensure_ascii=False),
                ],
            )
        except SystemExit as exc:
            if "exist" in str(exc).lower() or "duplicate" in str(exc).lower():
                continue
            raise
        created.append(field)
    return created


def _bootstrap_plan(data_dir: Path, project: str, space_id: str) -> dict[str, Any]:
    return {
        "project": project,
        "dry_run": True,
        "mapping": _rel(data_dir, _project_infra_path(data_dir, project)),
        "wiki_space_id": space_id,
        "planned": [
            {"step": "ensure_project_wiki_node", "title": project, "space_id": space_id},
            {"step": "create_cards_base", "name": f"{project} Cards Base", "identity": "user"},
            {"step": "create_candidate_cards_table", "name": "Candidate Cards"},
            {"step": "ensure_candidate_card_fields", "fields": [_base_card_field_payload(field) for field in BASE_CARD_FIELDS]},
            {"step": "write_project_mapping", "path": _rel(data_dir, _project_infra_path(data_dir, project))},
        ],
    }


def bootstrap_project_infra(
    data_dir: Path,
    *,
    project: str,
    base_token: str | None = None,
    table_id: str | None = None,
    adopt_existing_base: bool = False,
    fail_open: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    feishu_config = _integration_feishu_config(data_dir)
    configured_space_env = str(feishu_config.get("wiki_space_id_env") or "").strip()
    space_id = (
        _env_or_file(data_dir, FEISHU_WIKI_SPACE_ID_ENV)
        or (_env_or_file(data_dir, configured_space_env) if configured_space_env else None)
        or str(feishu_config.get("wiki_space_id") or "").strip()
        or str(feishu_config.get("default_wiki_space_id") or "").strip()
        or DEFAULT_FEISHU_WIKI_SPACE_ID
    )
    existing = _read_project_infra(data_dir, project)
    env_base = base_token or _env_or_file(data_dir, FEISHU_BASE_APP_TOKEN_ENV)
    env_table = table_id or _env_or_file(data_dir, FEISHU_CARDS_TABLE_ID_ENV)
    has_existing_base = bool(existing.get("cards_base_app_token") and existing.get("cards_table_id"))
    if has_existing_base:
        cards_base_token = str(existing.get("cards_base_app_token") or "").strip()
        cards_table_id = str(existing.get("cards_table_id") or "").strip()
        project_node_token = str(existing.get("project_node_token") or "").strip() or None
        cards_base_node_token = str(existing.get("cards_base_node_token") or "").strip() or None
        if not cards_base_node_token:
            cards_base_node_token = _move_cards_base_to_project_wiki(
                data_dir,
                space_id=space_id,
                project_node_token=project_node_token,
                base_token=cards_base_token,
            )
        created_fields = _ensure_cards_table_fields(data_dir, cards_base_token, cards_table_id)
        payload = {
            "wiki_space_id": space_id,
            "project_node_token": project_node_token,
            "cards_base_node_token": cards_base_node_token,
            "cards_base_app_token": cards_base_token,
            "cards_table_id": cards_table_id,
            "cards_base_status": "ready",
            "cards_table_fields": sorted(set([*existing.get("cards_table_fields", []), *created_fields]))
            if isinstance(existing.get("cards_table_fields", []), list)
            else created_fields,
        }
        _write_project_infra(data_dir, project, payload)
        return {
            "project": project,
            "status": "ready",
            "infra": _read_project_infra(data_dir, project),
            "mapping": _rel(data_dir, _project_infra_path(data_dir, project)),
        }

    if dry_run:
        return _bootstrap_plan(data_dir, project, space_id)

    if adopt_existing_base or (env_base and env_table):
        if not env_base or not env_table:
            raise SystemExit("adopt-existing-base requires base token and table id")
        payload = {
            "wiki_space_id": space_id,
            "project_node_token": str(existing.get("project_node_token") or "").strip() or None,
            "cards_base_app_token": env_base,
            "cards_table_id": env_table,
            "cards_base_status": "adopted",
        }
        _write_project_infra(data_dir, project, payload)
        return {
            "project": project,
            "status": "adopted",
            "infra": _read_project_infra(data_dir, project),
            "mapping": _rel(data_dir, _project_infra_path(data_dir, project)),
        }

    if not _lark_cli_available() or not _lark_cli_config_available(data_dir):
        payload = {
            "wiki_space_id": space_id,
            "cards_base_status": "skipped-not-configured",
            "skip_reason": "lark-cli is not available or not configured",
        }
        _write_project_infra(data_dir, project, payload)
        return {
            "project": project,
            "status": "skipped-not-configured",
            "infra": _read_project_infra(data_dir, project),
            "mapping": _rel(data_dir, _project_infra_path(data_dir, project)),
        }

    try:
        project_node_token, wiki_status = _ensure_project_wiki_node(data_dir, project, space_id)
        cards_base_token = str(existing.get("cards_base_app_token") or "").strip()
        cards_base_node_token = str(existing.get("cards_base_node_token") or "").strip() or None
        if not cards_base_token:
            cards_base_token, cards_base_node_token = _create_cards_base(data_dir, project, project_node_token)
        if not cards_base_node_token:
            cards_base_node_token = _move_cards_base_to_project_wiki(
                data_dir,
                space_id=space_id,
                project_node_token=project_node_token,
                base_token=cards_base_token,
            )
        cards_table_id = str(existing.get("cards_table_id") or "").strip() or _create_cards_table(data_dir, cards_base_token)
        created_fields = _ensure_cards_table_fields(data_dir, cards_base_token, cards_table_id)
    except SystemExit as exc:
        if not fail_open:
            raise
        payload = {
            "wiki_space_id": space_id,
            "cards_base_status": "skipped-bootstrap-failed",
            "skip_reason": str(exc),
        }
        _write_project_infra(data_dir, project, payload)
        return {
            "project": project,
            "status": "skipped-bootstrap-failed",
            "infra": _read_project_infra(data_dir, project),
            "mapping": _rel(data_dir, _project_infra_path(data_dir, project)),
        }
    payload = {
        "wiki_space_id": space_id,
        "project_node_token": project_node_token,
        "project_wiki_status": wiki_status,
        "cards_base_node_token": cards_base_node_token,
        "cards_base_app_token": cards_base_token,
        "cards_table_id": cards_table_id,
        "cards_base_status": "ready",
        "cards_table_fields": created_fields,
    }
    _write_project_infra(data_dir, project, payload)
    return {
        "project": project,
        "status": "ready",
        "infra": _read_project_infra(data_dir, project),
        "mapping": _rel(data_dir, _project_infra_path(data_dir, project)),
    }


def feishu_auth_guide(
    *,
    profile: str = "pma-feishu",
    app_id: str | None = None,
    brand: str = "lark",
) -> dict[str, Any]:
    scope = " ".join(FEISHU_MINIMAL_AUTH_SCOPES)
    app_id_placeholder = app_id or "<approved-app-id>"
    profile_add = (
        "printf '%s' '<app-secret>' | "
        f"lark-cli profile add --name {_shell_arg(profile)} "
        f"--app-id {_shell_arg(app_id_placeholder)} --app-secret-stdin "
        f"--brand {_shell_arg(brand)} --use"
    )
    login = f"lark-cli auth login --scope {_shell_arg(scope)}"
    return {
        "purpose": "Authorize only the minimal Feishu/Lark scopes PMAgent needs for Wiki mirroring and Candidate Cards Base.",
        "brand": brand,
        "profile": profile,
        "app_id": app_id_placeholder,
        "minimal_scopes": FEISHU_MINIMAL_AUTH_SCOPES,
        "commands": {
            "add_profile": profile_add,
            "login": login,
            "check": f"lark-cli auth check --scope {_shell_arg(scope)}",
        },
        "notes": [
            "Create or select an approved Feishu/Lark app first.",
            "The app must have these scopes approved in the developer console before login.",
            "Do not run auth login without --scope; that may request broader permissions than PMAgent needs.",
            "Use --brand feishu for China Feishu tenants and --brand lark for Lark tenants.",
        ],
    }


def _run_git(data_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=data_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise SystemExit(f"git {' '.join(args)} failed: {message}")
    return completed


def _record_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), list) and isinstance(data.get("fields"), list):
        field_names = [str(item) for item in data.get("fields", [])]
        record_ids = data.get("record_id_list") if isinstance(data.get("record_id_list"), list) else []
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(data["data"]):
            if not isinstance(row, list):
                continue
            fields = {field_names[pos]: value for pos, value in enumerate(row) if pos < len(field_names)}
            rows.append(
                {
                    "record_id": str(record_ids[index]) if index < len(record_ids) else "",
                    "fields": fields,
                }
            )
        return rows

    candidates: list[Any] = [
        payload.get("records"),
        payload.get("items"),
        payload.get("record_list"),
    ]
    if isinstance(data, dict):
        candidates.extend([data.get("records"), data.get("items"), data.get("record_list")])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _payload_has_more(payload: dict[str, Any]) -> bool:
    if isinstance(payload.get("has_more"), bool):
        return bool(payload["has_more"])
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("has_more"), bool):
        return bool(data["has_more"])
    return False


def _record_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields")
    return fields if isinstance(fields, dict) else {}


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "").strip()


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(part for part in (_cell_text(item) for item in value) if part).strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value", "id"):
            if key in value:
                text = _cell_text(value.get(key))
                if text:
                    return text
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _card_from_base_record(record: dict[str, Any]) -> dict[str, Any]:
    fields = _record_fields(record)
    get = lambda key: _cell_text(fields.get(key))
    return {
        "card_id": get("card_id"),
        "source_type": get("source_type"),
        "source_ref": get("source_ref"),
        "target": {
            "project": get("target_project"),
            "workspace": get("target_workspace"),
        },
        "suggestion": {
            "title": get("title"),
            "body": get("body"),
            "evidence": get("evidence"),
            "suggested_action": get("suggested_action"),
            "urgency": get("urgency") or "normal",
        },
        "lifecycle": {
            "status": get("status") or "inbox",
            "created_at": get("created_at") or _utc_now(),
            "reviewed_at": get("reviewed_at") or None,
            "review_note": get("review_note") or None,
            "expires_at": get("expires_at") or None,
        },
    }


def _project_workspace(data_dir: Path, project: str | None, workspace: str | None) -> tuple[str | None, str | None]:
    if workspace:
        return project or _infer_project_for_workspace(data_dir, workspace), workspace
    try:
        active_project, active_workspace = _resolve_workspace_context(data_dir, workspace=None)
    except SystemExit:
        return project, workspace
    return project or active_project, active_workspace


def _wiki_sync_ledger_path(data_dir: Path, workspace: str) -> Path:
    return workspace_root(data_dir, workspace) / ".pmagent" / "feishu-sync-ledger.json"


def _glob_workspace_files(root: Path, pattern: str) -> list[Path]:
    return sorted(path for path in root.glob(pattern) if path.is_file())


def _is_excluded_from_wiki(relative: str) -> bool:
    return any(fnmatch(relative, pattern) for pattern in WIKI_SYNC_EXCLUDES)


def _wiki_sync_files(data_dir: Path, workspace: str) -> list[Path]:
    root = workspace_root(data_dir, workspace)
    files: dict[str, Path] = {}
    for pattern in WIKI_SYNC_WHITELIST:
        for path in _glob_workspace_files(root, pattern):
            relative = path.relative_to(root).as_posix()
            if not _is_excluded_from_wiki(relative):
                files[relative] = path
    return [files[key] for key in sorted(files)]


def _wiki_sync_items(data_dir: Path, project: str, workspace: str) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    p_root = project_root(data_dir, project)
    for pattern in PROJECT_WIKI_SYNC_WHITELIST:
        for path in _glob_workspace_files(p_root, pattern):
            relative = path.relative_to(p_root).as_posix()
            if not _is_excluded_from_wiki(relative):
                key = f"project/{relative}"
                items[key] = {"key": key, "scope": "project", "relative": relative, "path": path}

    w_root = workspace_root(data_dir, workspace)
    for pattern in WIKI_SYNC_WHITELIST:
        for path in _glob_workspace_files(w_root, pattern):
            relative = path.relative_to(w_root).as_posix()
            if not _is_excluded_from_wiki(relative):
                key = f"workspace/{relative}"
                items[key] = {"key": key, "scope": "workspace", "relative": relative, "path": path}
    return [items[key] for key in sorted(items)]


def _file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def wiki_sync_status(
    data_dir: Path,
    *,
    project: str | None = None,
    workspace: str | None = None,
    command: str | None = None,
) -> dict[str, Any]:
    project, workspace = _project_workspace(data_dir, project, workspace)
    if not project or not workspace:
        raise SystemExit("project/workspace required for Feishu Wiki sync status")

    ledger_path = _wiki_sync_ledger_path(data_dir, workspace)
    ledger = _read_json(ledger_path) if ledger_path.exists() else {}
    synced_files = ledger.get("files", {}) if isinstance(ledger, dict) else {}
    sync_items = _wiki_sync_items(data_dir, project, workspace)
    pending: list[str] = []
    current_files: dict[str, dict[str, Any]] = {}
    for item in sync_items:
        key = item["key"]
        fingerprint = _file_fingerprint(item["path"])
        current_files[key] = fingerprint
        previous = synced_files.get(key) if isinstance(synced_files, dict) else None
        if not isinstance(previous, dict) or previous.get("mtime_ns") != fingerprint["mtime_ns"] or previous.get("size") != fingerprint["size"]:
            pending.append(key)

    adapter = _wiki_push_adapter(data_dir, command=command)
    return {
        "project": project,
        "workspace": workspace,
        "configured": bool(adapter["configured"]),
        "adapter": adapter["adapter"],
        "command_source": adapter["command_source"],
        "command_env": FEISHU_WIKI_PUSH_COMMAND_ENV,
        "space_id_env": FEISHU_WIKI_SPACE_ID_ENV,
        "space_id": adapter["space_id"],
        "sync_files": [item["key"] for item in sync_items],
        "pending_files": pending,
        "last_synced_at": ledger.get("last_synced_at") if isinstance(ledger, dict) else None,
        "ledger": _rel(data_dir, ledger_path),
        "status": "pending" if pending else "synced",
    }


def _format_push_command(
    template: str,
    *,
    data_dir: Path,
    project: str,
    workspace: str,
    relative: str,
    file_path: Path,
) -> str:
    return template.format(
        data_dir=str(data_dir),
        project=project,
        workspace=workspace,
        relative=relative,
        file=str(file_path),
    )


def wiki_push(
    data_dir: Path,
    *,
    project: str | None = None,
    workspace: str | None = None,
    command: str | None = None,
    dry_run: bool = False,
    include_all: bool = False,
) -> dict[str, Any]:
    project, workspace = _project_workspace(data_dir, project, workspace)
    if not project or not workspace:
        raise SystemExit("project/workspace required for Feishu Wiki push")

    adapter = _wiki_push_adapter(data_dir, command=command)
    resolved_command = adapter["command"]
    if not resolved_command:
        raise SystemExit(
            "No Feishu Wiki adapter is available; install/configure lark-cli "
            f"or set {FEISHU_WIKI_PUSH_COMMAND_ENV}"
        )

    status = wiki_sync_status(data_dir, project=project, workspace=workspace, command=resolved_command)
    targets = status["sync_files"] if include_all else status["pending_files"]
    sync_items = {item["key"]: item for item in _wiki_sync_items(data_dir, project, workspace)}
    planned = [
        {
            "key": key,
            "scope": sync_items[key]["scope"],
            "relative": sync_items[key]["relative"],
            "command": _format_push_command(
                resolved_command,
                data_dir=data_dir,
                project=project,
                workspace=workspace,
                relative=sync_items[key]["relative"],
                file_path=sync_items[key]["path"],
            ),
        }
        for key in targets
    ]
    if dry_run:
        return {
            "project": project,
            "workspace": workspace,
            "dry_run": True,
            "adapter": adapter["adapter"],
            "command_source": adapter["command_source"],
            "space_id": adapter["space_id"],
            "planned": planned,
            "pushed": [],
            "ledger": status["ledger"],
        }

    pushed: list[str] = []
    results: list[dict[str, Any]] = []
    env = os.environ.copy()
    env["PMAGENT_DATA_DIR"] = str(data_dir)
    env["PMAGENT_PROJECT"] = project
    env["PMAGENT_WORKSPACE"] = workspace
    for item in planned:
        key = item["key"]
        relative = item["relative"]
        scope = item["scope"]
        command_line = item["command"]
        path = sync_items[key]["path"]
        env["PMAGENT_SYNC_KEY"] = key
        env["PMAGENT_SYNC_SCOPE"] = scope
        env["PMAGENT_SYNC_RELATIVE"] = relative
        env["PMAGENT_SYNC_FILE"] = str(path)
        completed = subprocess.run(
            command_line,
            cwd=data_dir,
            env=env,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            {
                "relative": relative,
                "key": key,
                "scope": scope,
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                "stderr": (completed.stderr or "").strip(),
            }
        )
        if completed.returncode != 0:
            raise SystemExit(
                f"Feishu Wiki push failed for {key}: {completed.stderr or completed.stdout or completed.returncode}"
            )
        pushed.append(key)

    ledger_files: dict[str, Any] = {}
    for item in _wiki_sync_items(data_dir, project, workspace):
        key = item["key"]
        if include_all or key in pushed or key not in status["pending_files"]:
            ledger_files[key] = _file_fingerprint(item["path"])
    ledger = {
        "schema_version": 1,
        "project": project,
        "workspace": workspace,
        "last_synced_at": _utc_now(),
        "adapter": adapter["adapter"],
        "command_source": adapter["command_source"],
        "space_id": adapter["space_id"],
        "command_env": FEISHU_WIKI_PUSH_COMMAND_ENV,
        "files": ledger_files,
    }
    ledger_path = _wiki_sync_ledger_path(data_dir, workspace)
    _write_json(ledger_path, ledger)
    return {
        "project": project,
        "workspace": workspace,
        "dry_run": False,
        "adapter": adapter["adapter"],
        "command_source": adapter["command_source"],
        "space_id": adapter["space_id"],
        "pushed": pushed,
        "results": results,
        "ledger": _rel(data_dir, ledger_path),
    }


def write_infra_protocol(
    data_dir: Path,
    *,
    project: str | None = None,
    workspace: str | None = None,
) -> dict[str, Any]:
    project, workspace = _project_workspace(data_dir, project, workspace)
    protocol_paths = write_protocol(data_dir, project=project, workspace=workspace)

    wiki_plan_path = data_dir / "config" / "feishu-wiki-sync-plan.md"
    github_plan_path = data_dir / "config" / "github-pm-data-plan.md"
    manifest_path = data_dir / "config" / "pm-infra-protocol.json"

    wiki_plan_path.write_text(
        "\n".join(
            [
                "# Feishu Wiki Sync Plan",
                "",
                f"- Generated at: `{_utc_now()}`",
                f"- Project: `{project or '<project>'}`",
                f"- Workspace: `{workspace or '<workspace>'}`",
                "",
                "## Canonical Boundary",
                "",
                "Local PM Data remains canonical. Feishu Wiki is a human-readable collaboration mirror.",
                "",
                "## Push Whitelist",
                "",
                *[f"- `{item}`" for item in WIKI_SYNC_WHITELIST],
                "",
                "## Excludes",
                "",
                *[f"- `{item}`" for item in WIKI_SYNC_EXCLUDES],
                "",
                "## Conflict Rule",
                "",
                "Feishu-side body edits never overwrite local Markdown. They must enter conflict / inbox review.",
                "",
                "## Push Triggers",
                "",
                "- After a session mutates whitelisted human-readable Markdown.",
                "- Before phase handoff when whitelisted files changed.",
                "- Manual after user confirmation: `pmagent infra wiki-push --workspace <workspace>`.",
                "",
                "## Adapter Contract",
                "",
                "- Default adapter: `python -m pmagent.ops.lark_wiki_push` when `lark-cli` is available and configured.",
                f"- Built-in Wiki space env: `{FEISHU_WIKI_SPACE_ID_ENV}` (default `{DEFAULT_FEISHU_WIKI_SPACE_ID}`).",
                f"- Optional custom command env: `{FEISHU_WIKI_PUSH_COMMAND_ENV}`.",
                "- Wiki target hierarchy: `<project>/workspaces/<workspace>/<relative-file>`.",
                "- Built-in node mapping: `projects/<project>/.pmagent/feishu-wiki-nodes.jsonl`.",
                "- Custom commands are invoked once per pending file.",
                "- Custom placeholders: `{file}`, `{relative}`, `{workspace}`, `{project}`, `{data_dir}`.",
                "- Push success is recorded in `workspaces/<workspace>/.pmagent/feishu-sync-ledger.json`.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    github_plan_path.write_text(
        "\n".join(
            [
                "# GitHub PM Data Mirror Plan",
                "",
                f"- Generated at: `{_utc_now()}`",
                "",
                "## Boundary",
                "",
                "- The PM Data directory created by `pmagent init --dir <data_dir>` is the Git repository.",
                "- The `pmagent` source checkout is never the PM Data repository for OpenClaw analysis.",
                "- OpenClaw clones or pulls the GitHub PM Data repository.",
                "",
                "## Includes",
                "",
                "- `projects/`",
                "- `workspaces/`",
                "- `.pmagent` state files inside PM Data",
                "- `observations/`",
                "- `candidate-updates/`",
                "- `dev/` planning and run evidence",
                "",
                "## Excludes",
                "",
                "- `.env`",
                "- secrets",
                "- transient cache",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "project": project,
        "workspace": workspace,
        "canonical": {
            "pm_data_dir": ".",
            "source_checkout_forbidden_as_pm_data": True,
        },
        "feishu_wiki": {
            "role": "human-readable collaboration mirror",
            "push_whitelist": WIKI_SYNC_WHITELIST,
            "excludes": WIKI_SYNC_EXCLUDES,
            "conflict_rule": "remote body edits enter conflict/inbox review",
            "default_adapter": "builtin-lark",
            "default_adapter_command": "python -m pmagent.ops.lark_wiki_push",
            "default_adapter_requires": "available and configured lark-cli",
            "space_id_env": FEISHU_WIKI_SPACE_ID_ENV,
            "default_space_id": DEFAULT_FEISHU_WIKI_SPACE_ID,
            "push_command_env": FEISHU_WIKI_PUSH_COMMAND_ENV,
            "push_command_env_role": "optional custom adapter override",
            "push_command_template_placeholders": ["file", "relative", "workspace", "project", "data_dir"],
            "target_hierarchy": "<project>/workspaces/<workspace>/<relative-file>",
            "node_mapping": "projects/<project>/.pmagent/feishu-wiki-nodes.jsonl",
            "push_triggers": ["session_end", "phase_handoff", "manual"],
            "sync_status_command": "pmagent infra sync-status --workspace <workspace> --json",
            "manual_push_command": "pmagent infra wiki-push --workspace <workspace> --json",
            "confirmed_sync_rule": "Ask the user before running wiki-push; do not silently sync draft edits.",
            "ledger": "workspaces/<workspace>/.pmagent/feishu-sync-ledger.json",
        },
        "feishu_base": {
            "role": "Candidate Card relay",
            "table_grain": "project",
            "workspace_route_field": "target_workspace",
            "schema": protocol_paths["schema_path"],
            "bootstrap_command": "pmagent infra bootstrap --project <project> --json",
            "pull_command": "pmagent infra pull-cards --from-base --workspace <workspace> --json",
            "feedback_push_command": "pmagent infra push-feedback --workspace <workspace> --json",
        },
        "github_pm_data": {
            "role": "machine-readable full mirror for OpenClaw",
            "remote_env": GITHUB_REMOTE_ENV,
            "push_command": "pmagent infra github-push --json",
            "secrets_excluded": True,
        },
        "openclaw": {
            "role": "external advisor runtime",
            "protocol": protocol_paths["protocol_path"],
            "reads": "GitHub PM Data repository",
            "writes": "Feishu Base Candidate Cards",
            "does_not_write_pm_data": True,
        },
        "pma_polling": {
            "pull_filter": {"status": "inbox", "target_workspace": workspace or "<workspace>"},
            "local_target": "workspaces/<workspace>/candidate-updates/inbox",
            "feedback_ledger": "workspaces/<workspace>/candidate-updates/feedback.jsonl",
        },
    }
    _write_json(manifest_path, manifest)

    return {
        "protocol_path": protocol_paths["protocol_path"],
        "schema_path": protocol_paths["schema_path"],
        "wiki_plan": _rel(data_dir, wiki_plan_path),
        "github_plan": _rel(data_dir, github_plan_path),
        "manifest": _rel(data_dir, manifest_path),
    }


def _card_id(card: dict[str, Any]) -> str:
    card_id = str(card.get("card_id") or "").strip()
    if not card_id:
        raise SystemExit("Candidate Card missing card_id")
    return card_id


def _target(card: dict[str, Any]) -> dict[str, Any]:
    target = card.get("target")
    if not isinstance(target, dict):
        raise SystemExit(f"Candidate Card {_card_id(card)} missing target")
    return target


def _lifecycle(card: dict[str, Any]) -> dict[str, Any]:
    lifecycle = card.get("lifecycle")
    if not isinstance(lifecycle, dict):
        raise SystemExit(f"Candidate Card {_card_id(card)} missing lifecycle")
    return lifecycle


def _suggestion(card: dict[str, Any]) -> dict[str, Any]:
    suggestion = card.get("suggestion")
    if not isinstance(suggestion, dict):
        raise SystemExit(f"Candidate Card {_card_id(card)} missing suggestion")
    return suggestion


def _require_text(value: Any, *, field: str, card_id: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SystemExit(f"Candidate Card {card_id} missing required field: {field}")
    return text


def _validate_candidate_card(card: dict[str, Any]) -> None:
    card_id = _card_id(card)
    _require_text(card.get("source_ref"), field="source_ref", card_id=card_id)
    source_type = _require_text(card.get("source_type"), field="source_type", card_id=card_id)
    source_enum = set(CARD_SCHEMA["properties"]["source_type"]["enum"])
    if source_type not in source_enum:
        raise SystemExit(f"Candidate Card {card_id} has invalid source_type: {source_type}")

    target = _target(card)
    _require_text(target.get("project"), field="target.project", card_id=card_id)
    _require_text(target.get("workspace"), field="target.workspace", card_id=card_id)

    suggestion = _suggestion(card)
    for field in ("title", "body", "evidence", "suggested_action", "urgency"):
        _require_text(suggestion.get(field), field=f"suggestion.{field}", card_id=card_id)
    urgency_enum = set(CARD_SCHEMA["properties"]["suggestion"]["properties"]["urgency"]["enum"])
    if suggestion.get("urgency") not in urgency_enum:
        raise SystemExit(f"Candidate Card {card_id} has invalid urgency: {suggestion.get('urgency')}")

    lifecycle = _lifecycle(card)
    for field in ("status", "created_at"):
        _require_text(lifecycle.get(field), field=f"lifecycle.{field}", card_id=card_id)
    status_enum = set(CARD_SCHEMA["properties"]["lifecycle"]["properties"]["status"]["enum"])
    if lifecycle.get("status") not in status_enum:
        raise SystemExit(f"Candidate Card {card_id} has invalid status: {lifecycle.get('status')}")


def _slug(value: str) -> str:
    allowed = [ch.lower() if ch.isalnum() else "-" for ch in value]
    slug = "".join(allowed).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "card"


def _card_markdown(card: dict[str, Any], *, project: str, workspace: str) -> str:
    suggestion = _suggestion(card)
    lifecycle = _lifecycle(card)
    frontmatter = {
        "schema_version": 1,
        "card_id": _card_id(card),
        "source_type": card.get("source_type"),
        "source_ref": card.get("source_ref"),
        "project": project,
        "workspace": workspace,
        "status": lifecycle.get("status"),
        "urgency": suggestion.get("urgency", "normal"),
        "created_at": lifecycle.get("created_at") or _utc_now(),
    }
    return "\n".join(
        [
            "---",
            yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(),
            "---",
            "",
            "# Candidate Card",
            "",
            f"## {suggestion.get('title', _card_id(card))}",
            "",
            str(suggestion.get("body") or "").strip(),
            "",
            "## Suggested Action",
            "",
            str(suggestion.get("suggested_action") or "").strip(),
            "",
            "## Evidence",
            "",
            str(suggestion.get("evidence") or "").strip(),
            "",
        ]
    )


def _import_candidate_cards(
    data_dir: Path,
    *,
    cards: list[Any],
    project: str | None,
    workspace: str | None,
) -> dict[str, Any]:
    project, workspace = _project_workspace(data_dir, project, workspace)
    if not project or not workspace:
        raise SystemExit("project/workspace required to pull cards")

    inbox = candidate_updates_root(data_dir, workspace) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    skipped: list[str] = []
    for raw_card in cards:
        if not isinstance(raw_card, dict):
            continue
        _validate_candidate_card(raw_card)
        card_id = _card_id(raw_card)
        target = _target(raw_card)
        lifecycle = _lifecycle(raw_card)
        if target.get("project") != project or target.get("workspace") != workspace:
            skipped.append(card_id)
            continue
        if lifecycle.get("status") != "inbox":
            skipped.append(card_id)
            continue
        card_path = inbox / f"{_slug(card_id)}.md"
        card_path.write_text(_card_markdown(raw_card, project=project, workspace=workspace), encoding="utf-8")
        imported.append(_rel(data_dir, card_path))

    _update_queue_summary(repo_root=data_dir, workspace=workspace)
    state = sync_current_state(
        data_dir,
        workspace,
        patch={
            "active_step": "candidate-review" if imported else None,
            "pending_user_decision": "candidate-review" if imported else None,
            "next_recommended_step": {
                "id": "review_candidates" if imported else "observe_run",
                "reason": "Feishu Base Candidate Cards were pulled into local inbox." if imported else "No matching inbox cards were imported.",
            },
        },
        updated_by="infra-pull-cards",
    )
    return {
        "project": project,
        "workspace": workspace,
        "imported": imported,
        "skipped_card_ids": skipped,
        "recommended_skills": state.get("recommended_skills", []),
    }


def pull_cards_from_file(
    data_dir: Path,
    *,
    cards_file: Path,
    project: str | None,
    workspace: str | None,
) -> dict[str, Any]:
    payload = _read_json(cards_file)
    cards = payload.get("cards") if isinstance(payload, dict) else payload
    if not isinstance(cards, list):
        raise SystemExit("cards file must be a JSON array or {\"cards\": [...]}")
    result = _import_candidate_cards(data_dir, cards=cards, project=project, workspace=workspace)
    result["source"] = _rel(data_dir, cards_file) if cards_file.is_relative_to(data_dir) else str(cards_file)
    return result


def pull_cards_from_base(
    data_dir: Path,
    *,
    project: str | None,
    workspace: str | None,
    base_token: str | None = None,
    table_id: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    project, workspace = _project_workspace(data_dir, project, workspace)
    resolved_base, resolved_table = _base_config(data_dir, base_token=base_token, table_id=table_id, project=project)
    cards: list[dict[str, Any]] = []
    offset = 0
    while True:
        args = [
            "base",
            "+record-list",
            "--base-token",
            resolved_base,
            "--table-id",
            resolved_table,
            "--format",
            "json",
            "--limit",
            str(limit),
            "--offset",
            str(offset),
        ]
        for field in BASE_CARD_FIELDS:
            args.extend(["--field-id", field])
        payload = _run_lark_cli_json(data_dir, args)
        records = _record_items(payload)
        cards.extend(_card_from_base_record(record) for record in records)
        if not _payload_has_more(payload) or not records:
            break
        offset += len(records)

    result = _import_candidate_cards(data_dir, cards=cards, project=project, workspace=workspace)
    result.update(
        {
            "source": "feishu-base",
            "base_token_env": FEISHU_BASE_APP_TOKEN_ENV,
            "table_id_env": FEISHU_CARDS_TABLE_ID_ENV,
            "read_records": len(cards),
        }
    )
    return result


def _find_local_card(data_dir: Path, workspace: str, card: str) -> Path:
    root = candidate_updates_root(data_dir, workspace)
    candidates = []
    for bucket in ("inbox", "accepted", "rejected", "snoozed"):
        candidates.append(root / bucket / card)
        if not card.endswith(".md"):
            candidates.append(root / bucket / f"{card}.md")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(f"candidate card not found: {card}")


def review_card(
    data_dir: Path,
    *,
    workspace: str,
    card: str,
    status: str,
    note: str,
) -> dict[str, Any]:
    if status not in {"accepted", "rejected", "snoozed"}:
        raise SystemExit("status must be accepted, rejected, or snoozed")

    source = _find_local_card(data_dir, workspace, card)
    target_dir = candidate_updates_root(data_dir, workspace) / status
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    text = source.read_text(encoding="utf-8")
    card_id = source.stem
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            meta = yaml.safe_load(parts[1]) or {}
            if isinstance(meta, dict):
                card_id = str(meta.get("card_id") or card_id)
                meta["status"] = status
                meta["reviewed_at"] = _utc_now()
                meta["review_note"] = note
                text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip() + "\n---" + parts[2]
    target.write_text(text, encoding="utf-8")
    if source != target:
        source.unlink()

    feedback_path = candidate_updates_root(data_dir, workspace) / "feedback.jsonl"
    with feedback_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "card_id": card_id,
                    "status": status,
                    "review_note": note,
                    "reviewed_at": _utc_now(),
                    "feishu_writeback": {
                        "status": status,
                        "reviewed_at": "<same-as-reviewed_at>",
                        "review_note": note,
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    _update_queue_summary(repo_root=data_dir, workspace=workspace)
    sync_current_state(
        data_dir,
        workspace,
        patch={
            "active_step": "candidate-review",
            "pending_user_decision": None,
            "next_recommended_step": {
                "id": "observe_run",
                "reason": "Candidate Card review feedback was recorded for Feishu Base writeback.",
            },
        },
        updated_by="infra-review-card",
    )
    return {"workspace": workspace, "card_id": card_id, "status": status, "feedback": _rel(data_dir, feedback_path), "card_path": _rel(data_dir, target)}


def _feedback_rows(data_dir: Path, workspace: str) -> list[dict[str, Any]]:
    feedback_path = candidate_updates_root(data_dir, workspace) / "feedback.jsonl"
    if not feedback_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in feedback_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("card_id"):
            rows.append(payload)
    return rows


def _base_record_index(
    data_dir: Path,
    *,
    base_token: str,
    table_id: str,
    limit: int = 200,
) -> dict[str, str]:
    index: dict[str, str] = {}
    offset = 0
    while True:
        payload = _run_lark_cli_json(
            data_dir,
            [
                "base",
                "+record-list",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--format",
                "json",
                "--field-id",
                "card_id",
                "--limit",
                str(limit),
                "--offset",
                str(offset),
            ],
        )
        records = _record_items(payload)
        for record in records:
            card_id = _cell_text(_record_fields(record).get("card_id"))
            record_id = _record_id(record)
            if card_id and record_id:
                index[card_id] = record_id
        if not _payload_has_more(payload) or not records:
            break
        offset += len(records)
    return index


def push_feedback_to_base(
    data_dir: Path,
    *,
    workspace: str | None,
    base_token: str | None = None,
    table_id: str | None = None,
) -> dict[str, Any]:
    resolved_project, resolved_workspace = _resolve_workspace_context(data_dir, workspace=workspace)
    resolved_base, resolved_table = _base_config(
        data_dir,
        base_token=base_token,
        table_id=table_id,
        project=resolved_project,
    )
    rows = _feedback_rows(data_dir, resolved_workspace)
    if not rows:
        return {
            "workspace": resolved_workspace,
            "source": _rel(data_dir, candidate_updates_root(data_dir, resolved_workspace) / "feedback.jsonl"),
            "updated": [],
            "skipped_card_ids": [],
            "status": "no-feedback",
        }

    index = _base_record_index(data_dir, base_token=resolved_base, table_id=resolved_table)
    updated: list[str] = []
    skipped: list[str] = []
    for row in rows:
        card_id = str(row.get("card_id") or "").strip()
        record_id = index.get(card_id)
        if not record_id:
            skipped.append(card_id)
            continue
        reviewed_at = str(row.get("reviewed_at") or _utc_now())
        patch = {
            "status": str(row.get("status") or "").strip(),
            "reviewed_at": reviewed_at,
            "review_note": str(row.get("review_note") or ""),
        }
        _run_lark_cli_json(
            data_dir,
            [
                "base",
                "+record-upsert",
                "--base-token",
                resolved_base,
                "--table-id",
                resolved_table,
                "--record-id",
                record_id,
                "--json",
                json.dumps(patch, ensure_ascii=False),
            ],
        )
        updated.append(card_id)

    return {
        "workspace": resolved_workspace,
        "source": _rel(data_dir, candidate_updates_root(data_dir, resolved_workspace) / "feedback.jsonl"),
        "updated": updated,
        "skipped_card_ids": skipped,
        "status": "pushed" if updated else "no-matching-records",
    }


def assert_pm_data_git_boundary(data_dir: Path) -> dict[str, Any]:
    git_dir = data_dir / ".git"
    looks_like_source_checkout = (data_dir / "pyproject.toml").exists() and (data_dir / "src" / "pmagent").exists()
    return {
        "pm_data_dir": str(data_dir),
        "is_git_repo": git_dir.exists(),
        "looks_like_pmagent_source_checkout": looks_like_source_checkout,
        "boundary_ok": git_dir.exists() and not looks_like_source_checkout,
        "source_checkout_warning": "Run git init in the PM Data directory created by pmagent init, not in the pmagent source checkout.",
    }


def github_push_pm_data(
    data_dir: Path,
    *,
    remote: str | None = None,
    branch: str = "main",
    message: str | None = None,
) -> dict[str, Any]:
    boundary = assert_pm_data_git_boundary(data_dir)
    if boundary["looks_like_pmagent_source_checkout"]:
        raise SystemExit("refusing to push: data_dir looks like the pmagent source checkout")

    resolved_remote = remote or _env_or_file(data_dir, GITHUB_REMOTE_ENV)
    if not resolved_remote:
        raise SystemExit(f"{GITHUB_REMOTE_ENV} is not configured")

    if not (data_dir / ".git").exists():
        _run_git(data_dir, ["init"])
    if branch:
        _run_git(data_dir, ["checkout", "-B", branch])

    git_name = _env_or_file(data_dir, GIT_USER_NAME_ENV)
    git_email = _env_or_file(data_dir, GIT_USER_EMAIL_ENV)
    if git_name:
        _run_git(data_dir, ["config", "user.name", git_name])
    if git_email:
        _run_git(data_dir, ["config", "user.email", git_email])

    remotes = _run_git(data_dir, ["remote"]).stdout.splitlines()
    if "origin" in remotes:
        _run_git(data_dir, ["remote", "set-url", "origin", resolved_remote])
    else:
        _run_git(data_dir, ["remote", "add", "origin", resolved_remote])

    _run_git(data_dir, ["add", "-A"])
    dirty = _run_git(data_dir, ["status", "--porcelain"]).stdout.strip().splitlines()
    committed = False
    if dirty:
        commit_message = message or f"Mirror PM Data for OpenClaw {_utc_now()}"
        _run_git(data_dir, ["commit", "-m", commit_message])
        committed = True

    commit = _run_git(data_dir, ["rev-parse", "HEAD"]).stdout.strip()
    _run_git(data_dir, ["push", "-u", "origin", f"HEAD:refs/heads/{branch}"])
    return {
        "pm_data_dir": str(data_dir),
        "remote_env": GITHUB_REMOTE_ENV,
        "remote": resolved_remote,
        "branch": branch,
        "commit": commit,
        "committed": committed,
        "boundary_ok": not boundary["looks_like_pmagent_source_checkout"],
        "pushed": True,
    }


def cmd_infra(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    if args.subcommand == "protocol":
        payload = write_infra_protocol(data_dir, project=args.project, workspace=args.workspace)
    elif args.subcommand == "auth-guide":
        payload = feishu_auth_guide(profile=args.profile, app_id=args.app_id, brand=args.brand)
    elif args.subcommand == "bootstrap":
        payload = bootstrap_project_infra(
            data_dir,
            project=args.project,
            base_token=args.base_token,
            table_id=args.table_id,
            adopt_existing_base=args.adopt_existing_base,
            dry_run=args.dry_run,
        )
    elif args.subcommand == "sync-status":
        payload = wiki_sync_status(
            data_dir,
            project=args.project,
            workspace=args.workspace,
            command=args.command,
        )
    elif args.subcommand == "wiki-push":
        payload = wiki_push(
            data_dir,
            project=args.project,
            workspace=args.workspace,
            command=args.command,
            dry_run=args.dry_run,
            include_all=args.all,
        )
    elif args.subcommand == "pull-cards":
        if getattr(args, "from_base", False):
            payload = pull_cards_from_base(
                data_dir,
                project=args.project,
                workspace=args.workspace,
                base_token=args.base_token,
                table_id=args.table_id,
            )
        elif getattr(args, "from_file", None):
            payload = pull_cards_from_file(
                data_dir,
                cards_file=Path(args.from_file).expanduser().resolve(),
                project=args.project,
                workspace=args.workspace,
            )
        else:
            raise SystemExit("pull-cards requires --from <cards.json> or --from-base")
    elif args.subcommand == "review-card":
        _, workspace = _resolve_workspace_context(data_dir, workspace=args.workspace)
        payload = review_card(data_dir, workspace=workspace, card=args.card, status=args.status, note=args.note)
    elif args.subcommand == "push-feedback":
        payload = push_feedback_to_base(
            data_dir,
            workspace=args.workspace,
            base_token=args.base_token,
            table_id=args.table_id,
        )
    elif args.subcommand == "github-push":
        payload = github_push_pm_data(
            data_dir,
            remote=args.remote,
            branch=args.branch,
            message=args.message,
        )
    elif args.subcommand == "git-boundary":
        payload = assert_pm_data_git_boundary(data_dir)
    else:
        raise SystemExit(f"unsupported infra subcommand: {args.subcommand}")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}={value}")
    return 0


def copy_protocol_to_docs(data_dir: Path, docs_dir: Path) -> None:
    for relative in ("config/openclaw-advisor-protocol.md", "config/candidate-card.schema.json"):
        source = data_dir / relative
        if source.exists():
            target = docs_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
