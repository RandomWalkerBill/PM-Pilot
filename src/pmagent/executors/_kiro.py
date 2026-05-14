from __future__ import annotations

from pathlib import Path
from shutil import which
from uuid import uuid4

from . import ExecutorError, ExecutorResult
from ._subprocess import run_subprocess


def run_kiro(
    prompt: str,
    *,
    cwd: Path,
    session_id: str | None = None,
    model: str | None = None,
    schema: dict | None = None,
    timeout_seconds: float | None = None,
    trust_all_tools: bool = False,
) -> ExecutorResult:
    if session_id:
        raise ExecutorError("kiro executor does not support session resume")
    if schema:
        raise ExecutorError("kiro executor does not support output schema enforcement")
    executable = which("kiro-cli") or "kiro-cli"
    argv = [executable, "chat", "--no-interactive"]
    if trust_all_tools:
        argv.append("--trust-all-tools")
    if model:
        argv.extend(["--model", model])
    argv.append(prompt)
    content = run_subprocess(argv, cwd=cwd, timeout_seconds=timeout_seconds)
    return ExecutorResult(content=content, session_id=str(uuid4()))
