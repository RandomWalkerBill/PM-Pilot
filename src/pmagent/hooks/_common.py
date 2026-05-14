"""Shared helpers for Claude Code hook entry points.

Design notes:

- Hooks are invoked by Claude Code with a JSON payload on stdin and return
  context to the agent via stdout. A non-zero exit code of 2 signals a hard
  block (PreToolUse / Stop); any other non-zero exit simply surfaces stderr.
- Hooks must be **fail-open**: an exception, a missing file, a missing CLI, or
  a stalled subprocess must never break the user's session. ``run_safely``
  takes care of that for every hook ``main()``.
- Hooks stay out of model territory: they never rewrite tool inputs or modify
  user prompts. They only inject extra context or block with a reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..paths import resolve_data_dir


DEFAULT_SUBPROCESS_TIMEOUT = 4.0
HOOK_DEBUG_ENV = "PMAGENT_HOOK_DEBUG"


@dataclass
class HookContext:
    """Materialised view of a hook invocation."""

    payload: dict[str, Any]
    data_dir: Path | None
    active_project: str | None
    active_workspace: str | None

    @property
    def cwd(self) -> Path | None:
        raw = self.payload.get("cwd")
        if not raw:
            return None
        try:
            return Path(raw)
        except (TypeError, ValueError):
            return None

    @property
    def transcript_path(self) -> Path | None:
        raw = self.payload.get("transcript_path")
        if not raw:
            return None
        try:
            return Path(raw)
        except (TypeError, ValueError):
            return None

    @property
    def workspace_root(self) -> Path | None:
        if not (self.data_dir and self.active_workspace):
            return None
        return self.data_dir / "workspaces" / self.active_workspace

    @property
    def current_state_path(self) -> Path | None:
        root = self.workspace_root
        if root is None:
            return None
        return root / ".pmagent" / "current-state.json"

    def load_current_state(self) -> dict[str, Any]:
        path = self.current_state_path
        if path is None or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_context() -> HookContext:
    payload = read_payload()
    data_dir: Path | None = None
    try:
        data_dir = resolve_data_dir()
    except Exception:
        data_dir = None

    active_project: str | None = None
    active_workspace: str | None = None
    if data_dir is not None:
        projects_json = data_dir / "config" / "projects.json"
        if projects_json.exists():
            try:
                cfg = json.loads(projects_json.read_text(encoding="utf-8"))
                active_project = (cfg.get("active_project") or "").strip() or None
                active_workspace = (cfg.get("active_workspace") or "").strip() or None
            except (OSError, json.JSONDecodeError):
                pass

    return HookContext(
        payload=payload,
        data_dir=data_dir,
        active_project=active_project,
        active_workspace=active_workspace,
    )


def run_pmagent(
    args: Iterable[str],
    *,
    timeout: float = DEFAULT_SUBPROCESS_TIMEOUT,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Invoke the pmagent CLI and return (returncode, stdout, stderr).

    Never raises: times out, missing-binary and encoding errors become a
    synthetic ``(1, "", reason)`` tuple so callers can silently drop them.
    """

    cmd = [sys.executable, "-m", "pmagent.cli", *args]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        completed = subprocess.run(
            cmd,
            input="",
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged_env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 1, "", "pmagent hook subprocess timed out"
    except FileNotFoundError as exc:
        return 1, "", f"pmagent CLI not found: {exc}"
    except Exception as exc:  # noqa: BLE001 - fail-open
        return 1, "", f"pmagent hook subprocess error: {exc}"
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def read_transcript_messages(path: Path | None, *, limit: int = 80) -> list[dict[str, Any]]:
    """Return the last ``limit`` transcript entries as dicts.

    Claude Code writes JSONL transcripts; we read from the tail to keep cost
    bounded. Missing / unreadable files yield an empty list.
    """

    if path is None or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    tail = lines[-limit:] if limit > 0 else lines
    out: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def extract_text_from_message(message: dict[str, Any]) -> str:
    """Pull plain-text content out of a transcript entry."""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") in {"text", "input_text", "output_text"}:
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "\n".join(parts)
    return ""


def emit_context_block(title: str, body: str) -> None:
    """Write a framed context block to stdout.

    Claude Code merges hook stdout into the conversation as additional
    context. We wrap it so the agent can visually separate hook-injected
    content from user text.
    """

    body = (body or "").strip()
    if not body:
        return
    sys.stdout.write(f"<pmagent-hook source=\"{title}\">\n{body}\n</pmagent-hook>\n")


def block(reason: str) -> None:
    """Block the current tool call or stop event with exit code 2."""

    sys.stderr.write(reason.rstrip() + "\n")
    sys.exit(2)


@contextmanager
def run_safely(hook_name: str):
    """Wrap a hook ``main`` body so unexpected errors fail open.

    A genuine block path should call :func:`block` which raises SystemExit(2);
    that propagates up untouched. Everything else is swallowed.
    """

    try:
        yield
    except SystemExit:
        raise
    except Exception:
        if os.environ.get(HOOK_DEBUG_ENV):
            traceback.print_exc(file=sys.stderr)
        else:
            sys.stderr.write(f"[pmagent-hook {hook_name}] suppressed error\n")
        sys.exit(0)


def main_wrapper(hook_name: str, fn: Callable[[], None]) -> None:
    with run_safely(hook_name):
        fn()
