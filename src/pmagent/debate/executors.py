from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which as _shutil_which
from typing import Callable

from pmagent.executors import ExecutorError as DebateExecutorError, ExecutorResult
from pmagent.executors import _claude, _codex, _subprocess
from pmagent.executors import registry as _registry

# Compatibility aliases for callers/tests that reached into the old
# debate-local executor implementation. The real implementation now lives in
# pmagent.executors, but keeping these hook points makes the extraction
# backwards-compatible and avoids forcing all debate callers to update at once.
which: Callable[[str], str | None] = _shutil_which
_codex_sessions_root: Callable[[], Path] = _codex.codex_sessions_root
_discover_git_bash = _claude.discover_git_bash
_run_subprocess = _subprocess.run_subprocess

_ORIGINAL_WHICH = _shutil_which
_ORIGINAL_CODEX_SESSIONS_ROOT = _codex.codex_sessions_root
_ORIGINAL_NEWEST_CODEX_SESSION = _codex.newest_codex_session
_ORIGINAL_DISCOVER_GIT_BASH = _claude.discover_git_bash
_ORIGINAL_RUN_SUBPROCESS = _subprocess.run_subprocess


def _newest_codex_session(*, after_timestamp: float | None = None, cwd: Path | None = None) -> str | None:
    previous_root = _codex.codex_sessions_root
    if _codex_sessions_root is not _ORIGINAL_CODEX_SESSIONS_ROOT:
        _codex.codex_sessions_root = _codex_sessions_root
    try:
        return _ORIGINAL_NEWEST_CODEX_SESSION(after_timestamp=after_timestamp, cwd=cwd)
    finally:
        _codex.codex_sessions_root = previous_root


_COMPAT_NEWEST_CODEX_SESSION = _newest_codex_session


def _with_compat_hooks(fn):
    """Run a shared executor function while honoring legacy monkeypatch hooks."""

    changed: list[tuple[object, str, object]] = []

    def set_if_legacy_patched(target: object, name: str, value: object, original: object) -> None:
        if value is original:
            return
        previous = getattr(target, name)
        setattr(target, name, value)
        changed.append((target, name, previous))

    set_if_legacy_patched(_codex, "codex_sessions_root", _codex_sessions_root, _ORIGINAL_CODEX_SESSIONS_ROOT)
    set_if_legacy_patched(_codex, "newest_codex_session", _newest_codex_session, _COMPAT_NEWEST_CODEX_SESSION)
    set_if_legacy_patched(_claude, "discover_git_bash", _discover_git_bash, _ORIGINAL_DISCOVER_GIT_BASH)
    set_if_legacy_patched(_registry, "discover_git_bash", _discover_git_bash, _ORIGINAL_DISCOVER_GIT_BASH)
    set_if_legacy_patched(_subprocess, "run_subprocess", _run_subprocess, _ORIGINAL_RUN_SUBPROCESS)
    set_if_legacy_patched(_claude, "run_subprocess", _run_subprocess, _ORIGINAL_RUN_SUBPROCESS)
    set_if_legacy_patched(_codex, "run_subprocess", _run_subprocess, _ORIGINAL_RUN_SUBPROCESS)
    set_if_legacy_patched(_registry, "which", which, _ORIGINAL_WHICH)
    set_if_legacy_patched(_claude, "which", which, _ORIGINAL_WHICH)
    set_if_legacy_patched(_codex, "which", which, _ORIGINAL_WHICH)

    try:
        return fn()
    finally:
        for target, name, previous in reversed(changed):
            setattr(target, name, previous)


def precheck_executor_plan(plan: dict[str, dict[str, object]]) -> list[dict[str, str]]:
    return _with_compat_hooks(lambda: _registry.precheck_executor_plan(plan))


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
    return _with_compat_hooks(
        lambda: _registry.run_executor(
            executor_id,
            prompt,
            cwd=cwd,
            session_id=session_id,
            model=model,
            schema=schema,
            timeout_seconds=timeout_seconds,
            trust_all_tools=trust_all_tools,
        )
    )


__all__ = [
    "DebateExecutorError",
    "ExecutorResult",
    "_codex_sessions_root",
    "_discover_git_bash",
    "_newest_codex_session",
    "_run_subprocess",
    "precheck_executor_plan",
    "run_executor",
    "subprocess",
    "sys",
    "which",
]
