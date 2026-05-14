from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .infra import (
    FEISHU_CARDS_TABLE_ID_ENV,
    FEISHU_MINIMAL_AUTH_SCOPES,
    FEISHU_WIKI_SPACE_ID_ENV,
    GITHUB_REMOTE_ENV,
    feishu_auth_guide,
)
from .paths import resolve_data_dir


SETUP_STATE_PATH = ".pmagent/setup-state.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
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
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _setup_state_path(data_dir: Path) -> Path:
    return data_dir / SETUP_STATE_PATH


def _load_setup_state(data_dir: Path) -> dict[str, Any]:
    return _read_json(_setup_state_path(data_dir))


def _dismissed(state: dict[str, Any], integration: str) -> bool:
    dismissed = state.get("dismissed_integrations")
    return isinstance(dismissed, dict) and bool(dismissed.get(integration))


def _lark_auth_status() -> dict[str, Any]:
    executable = shutil.which("lark-cli")
    if not executable:
        return {"available": False, "status": "not_installed"}
    try:
        completed = subprocess.run(
            [executable, "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "status": "error", "message": str(exc)}
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "available": True,
            "status": "error",
            "message": (completed.stderr or completed.stdout or "").strip(),
        }
    token_status = str(payload.get("tokenStatus") or "").strip()
    identity = str(payload.get("identity") or "").strip()
    scopes = set(str(payload.get("scope") or "").split())
    missing = [scope for scope in FEISHU_MINIMAL_AUTH_SCOPES if scope not in scopes]
    authenticated = completed.returncode == 0 and token_status != "expired" and not missing
    return {
        "available": True,
        "status": "authenticated" if authenticated else "not_authenticated",
        "identity": identity,
        "token_status": token_status or None,
        "missing_scopes": missing,
        "user": payload.get("userName"),
        "app_id": payload.get("appId"),
        "note": payload.get("note"),
    }


def build_setup_status(data_dir: Path) -> dict[str, Any]:
    env = _read_env_file(data_dir)
    state = _load_setup_state(data_dir)
    local_ready = (data_dir / "AGENTS.md").exists() and (data_dir / "config" / "agent-workflow.yaml").exists()

    github_remote = env.get(GITHUB_REMOTE_ENV, "").strip()
    github_dismissed = _dismissed(state, "github")
    github_status = "dismissed" if github_dismissed else ("configured" if github_remote else "not_configured")

    lark_status = _lark_auth_status()
    wiki_space = env.get(FEISHU_WIKI_SPACE_ID_ENV, "").strip()
    feishu_dismissed = _dismissed(state, "feishu")
    feishu_missing: list[str] = []
    if not lark_status["available"]:
        feishu_missing.append("lark-cli")
    if lark_status["available"] and lark_status["status"] != "authenticated":
        feishu_missing.append("lark-cli user auth")
    if not wiki_space:
        feishu_missing.append(FEISHU_WIKI_SPACE_ID_ENV)
    feishu_status = "dismissed" if feishu_dismissed else ("configured" if not feishu_missing else "not_configured")

    return {
        "data_dir": str(data_dir),
        "local": {
            "status": "ready" if local_ready else "not_initialized",
            "required": True,
            "missing": [] if local_ready else ["AGENTS.md", "config/agent-workflow.yaml"],
        },
        "mode": {
            "local_only_available": True,
            "note": "GitHub and Feishu are optional integrations.",
        },
        "github": {
            "status": github_status,
            "required": False,
            "missing": [] if github_remote else [GITHUB_REMOTE_ENV],
            "remote": github_remote or None,
            "dismissed": github_dismissed,
            "next_commands": [
                "Add PMAGENT_GITHUB_REMOTE=<github-pm-data-repo-url> to .env",
                "pmagent infra github-push --json",
            ],
        },
        "feishu": {
            "status": feishu_status,
            "required": False,
            "missing": feishu_missing,
            "dismissed": feishu_dismissed,
            "wiki_space_id": wiki_space or None,
            "lark_cli": lark_status,
            "next_commands": [
                "brew install lark-cli",
                "pmagent infra auth-guide --brand lark --app-id <approved-app-id>",
                "pmagent infra bootstrap --project <project> --json",
            ],
        },
        "setup_state": {
            "path": SETUP_STATE_PATH,
            "dismissed_integrations": state.get("dismissed_integrations", {}),
        },
    }


def _symbol(status: str) -> str:
    if status in {"ready", "configured"}:
        return "OK"
    if status == "dismissed":
        return "SKIP"
    return "TODO"


def _render_guide(payload: dict[str, Any]) -> str:
    github = payload["github"]
    feishu = payload["feishu"]
    lines = [
        "PMAgent Setup Guide",
        "",
        "Local PMA",
        f"{_symbol(payload['local']['status'])} {payload['local']['status']}",
        "",
        "Current mode",
        "Local-only mode is available. GitHub and Feishu are optional.",
        "",
        "GitHub mirror",
        f"{_symbol(github['status'])} {github['status']}",
    ]
    if github["missing"] and not github["dismissed"]:
        lines.extend(
            [
                f"Missing: {', '.join(github['missing'])}",
                "Use this only if OpenClaw or another agent needs a remote PM Data mirror.",
                "",
                "Next:",
                "1. Create a private GitHub repository for this PM Data directory.",
                "2. Add PMAGENT_GITHUB_REMOTE=<github-pm-data-repo-url> to .env.",
                "3. Run: pmagent infra github-push --json",
                "4. Or dismiss: pmagent setup dismiss --integration github",
            ]
        )
    lines.extend(["", "Feishu / Lark", f"{_symbol(feishu['status'])} {feishu['status']}"])
    if feishu["missing"] and not feishu["dismissed"]:
        auth = feishu_auth_guide()
        lines.extend(
            [
                f"Missing: {', '.join(feishu['missing'])}",
                "Use this only if you want Wiki document sync and Candidate Cards Base.",
                "",
                "Next:",
                "1. Install lark-cli if missing: brew install lark-cli",
                f"2. Add approved app profile: {auth['commands']['add_profile']}",
                f"3. Authenticate with minimal scopes: {auth['commands']['login']}",
                "4. Set PMAGENT_FEISHU_WIKI_SPACE_ID=<space-id> in .env if not using the default.",
                "5. Bootstrap project infra: pmagent infra bootstrap --project <project> --json",
                "6. Or dismiss: pmagent setup dismiss --integration feishu",
            ]
        )
    lines.extend(
        [
            "",
            "Continue local-only at any time:",
            "pmagent workspace-init --project <project> --workspace <workspace>",
        ]
    )
    return "\n".join(lines)


def dismiss_integration(data_dir: Path, integration: str) -> dict[str, Any]:
    state = _load_setup_state(data_dir)
    dismissed = state.setdefault("dismissed_integrations", {})
    dismissed[integration] = {"dismissed_at": _utc_now()}
    _write_json(_setup_state_path(data_dir), state)
    return {
        "integration": integration,
        "status": "dismissed",
        "setup_state": SETUP_STATE_PATH,
    }


def cmd_setup(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    if args.subcommand in {"guide", "status"}:
        payload = build_setup_status(data_dir)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(_render_guide(payload))
        return 0
    if args.subcommand == "dismiss":
        payload = dismiss_integration(data_dir, args.integration)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Dismissed optional integration: {args.integration}")
        return 0
    raise SystemExit(f"unsupported setup subcommand: {args.subcommand}")
