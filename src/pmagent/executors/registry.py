from __future__ import annotations

import os
import sys
from pathlib import Path
from shutil import which

from . import ExecutorError, ExecutorResult
from ._claude import discover_git_bash, run_claude
from ._codex import run_codex
from ._kiro import run_kiro


_EXECUTOR_COMMANDS = {
    "claude": "claude",
    "codex": "codex",
    "kiro": "kiro-cli",
}


def normalize_executor_id(executor_id: str) -> str:
    normalized = str(executor_id or "").strip().lower()
    if normalized == "kiro-cli":
        return "kiro"
    return normalized


def is_inside_agent() -> bool:
    markers = (
        "KIRO_SESSION",
        "CLAUDE_CODE",
        "CODEX_SESSION",
        "PMAGENT_AGENT_MODE",
    )
    return any(os.environ.get(key) for key in markers)


def resolve_available_backend() -> str:
    explicit = os.environ.get("PMAGENT_AGENT_BACKEND", "").strip()
    if explicit and explicit.lower() != "auto":
        normalized = normalize_executor_id(explicit)
        if normalized not in _EXECUTOR_COMMANDS:
            raise ExecutorError(f"unsupported PMAGENT_AGENT_BACKEND `{explicit}`; use one of: claude, codex, kiro")
        command = _EXECUTOR_COMMANDS[normalized]
        if which(command) is None:
            raise ExecutorError(f"configured agent backend `{explicit}` requires `{command}` on PATH")
        return normalized
    for executor_id in ("kiro", "claude", "codex"):
        if which(_EXECUTOR_COMMANDS[executor_id]) is not None:
            return executor_id
    raise ExecutorError("No agent backend found. Install kiro-cli, claude, or codex, or set PMAGENT_AGENT_BACKEND.")


def precheck_executor(executor_id: str) -> list[dict[str, str]]:
    normalized = normalize_executor_id(executor_id)
    if not normalized:
        return [{"issue": "missing_exec", "message": "executor is not configured"}]
    if normalized not in _EXECUTOR_COMMANDS:
        return [
            {
                "issue": "unsupported_exec",
                "message": f"executor `{executor_id}` is unsupported; use one of: {', '.join(sorted(_EXECUTOR_COMMANDS))}",
            }
        ]
    command = _EXECUTOR_COMMANDS[normalized]
    if which(command) is None:
        return [{"issue": "missing_cli", "message": f"executor `{command}` is not installed or not on PATH"}]
    if normalized == "claude" and sys.platform.startswith("win") and discover_git_bash() is None:
        return [
            {
                "issue": "missing_git_bash",
                "message": "executor `claude` requires Git Bash on Windows. Install Git for Windows or set CLAUDE_CODE_GIT_BASH_PATH to bash.exe.",
            }
        ]
    return []


def precheck_executor_plan(plan: dict[str, dict[str, object]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for role, config in plan.items():
        exec_id = str(config.get("exec") or "").strip()
        role_issues = precheck_executor(exec_id)
        for issue in role_issues:
            issues.append({"role": role, **issue})
    return issues


def run_executor(
    executor_id: str,
    prompt: str,
    *,
    cwd: Path,
    session_id: str | None = None,
    model: str | None = None,
    schema: dict | None = None,
    timeout_seconds: float | None = None,
    trust_all_tools: bool = False,
) -> ExecutorResult:
    normalized = normalize_executor_id(executor_id)
    if normalized == "claude":
        return run_claude(
            prompt,
            cwd=cwd,
            session_id=session_id,
            model=model,
            schema=schema,
            timeout_seconds=timeout_seconds,
            trust_all_tools=trust_all_tools,
        )
    if normalized == "codex":
        return run_codex(
            prompt,
            cwd=cwd,
            session_id=session_id,
            model=model,
            schema=schema,
            timeout_seconds=timeout_seconds,
            trust_all_tools=trust_all_tools,
        )
    if normalized == "kiro":
        return run_kiro(
            prompt,
            cwd=cwd,
            session_id=session_id,
            model=model,
            schema=schema,
            timeout_seconds=timeout_seconds,
            trust_all_tools=trust_all_tools,
        )
    raise ExecutorError(f"unknown executor: {executor_id}")
