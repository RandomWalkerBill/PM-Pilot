from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from shutil import which
from uuid import uuid4

from . import ExecutorResult
from ._subprocess import run_subprocess


CLAUDE_BACKGROUND_FULL_ACCESS_FLAGS = [
    "--dangerously-skip-permissions",
]


def _env_positive_int(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return str(value)


def discover_git_bash() -> Path | None:
    configured = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if configured and Path(configured).exists():
        return Path(configured)

    candidates: list[Path] = []
    git_path = which("git")
    if git_path:
        git_exe = Path(git_path)
        if git_exe.parent.name.lower() == "cmd":
            git_root = git_exe.parent.parent
            candidates.extend([git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"])
        candidates.extend([git_exe.parent / "bash.exe", git_exe.parent.parent / "bin" / "bash.exe"])

    candidates.extend(
        [
            Path("C:/Program Files/Git/bin/bash.exe"),
            Path("C:/Program Files/Git/usr/bin/bash.exe"),
            Path("C:/Program Files (x86)/Git/bin/bash.exe"),
            Path("C:/Program Files (x86)/Git/usr/bin/bash.exe"),
            Path("D:/Git/bin/bash.exe"),
            Path("D:/Git/usr/bin/bash.exe"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_claude(
    prompt: str,
    *,
    cwd: Path,
    session_id: str | None = None,
    model: str | None = None,
    schema: dict | None = None,
    timeout_seconds: float | None = None,
    trust_all_tools: bool = False,
) -> ExecutorResult:
    executable = which("claude") or "claude"
    sid = session_id or str(uuid4())
    argv = [executable, "-p"]
    if trust_all_tools:
        argv.extend(CLAUDE_BACKGROUND_FULL_ACCESS_FLAGS)
    max_turns = _env_positive_int("PMAGENT_CLAUDE_MAX_TURNS")
    if max_turns:
        argv.extend(["--max-turns", max_turns])
    if model:
        argv.extend(["--model", model])
    if schema:
        argv.extend(["--json-schema", json.dumps(schema, ensure_ascii=False)])
    if session_id:
        argv.extend(["--resume", sid])
    else:
        argv.extend(["--session-id", sid])
    extra_env: dict[str, str] = {}
    if sys.platform.startswith("win") and not os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
        git_bash = discover_git_bash()
        if git_bash is not None:
            extra_env["CLAUDE_CODE_GIT_BASH_PATH"] = str(git_bash)
    content = run_subprocess(argv, cwd=cwd, stdin_text=prompt, timeout_seconds=timeout_seconds, extra_env=extra_env or None)
    return ExecutorResult(content=content, session_id=sid)
