"""PostToolUse check: summary_sync_gate + phase_raw_logging.

- After an Edit/Write to ``workspace-summary.md`` we check that
  ``.pmagent/current-state.json`` was refreshed recently enough. If not, we
  emit a non-blocking system-reminder telling the agent to sync it.
- After a Bash run of ``pmagent clarify answer`` or ``pmagent research note``
  we check that the matching raw-log file's mtime moved. If not, we remind
  the agent to append the raw content.

Both checks are advisory only — they never block.
"""

from __future__ import annotations

import os
import re
import time
import json
from fnmatch import fnmatch
from pathlib import Path

from ..infra import WIKI_SYNC_EXCLUDES, WIKI_SYNC_WHITELIST
from ._common import HookContext, load_context, main_wrapper, run_pmagent


SUMMARY_SYNC_THRESHOLD_SECONDS = 30.0

CLARIFY_ANSWER_RE = re.compile(r"\bpmagent\s+clarify\s+answer\b", re.IGNORECASE)
RESEARCH_NOTE_RE = re.compile(r"\bpmagent\s+research\s+note\b", re.IGNORECASE)


def _reminder(body: str) -> None:
    import sys

    body = body.strip()
    if not body:
        return
    sys.stdout.write(
        f"<pmagent-hook source=\"post-mutation\">\n{body}\n</pmagent-hook>\n"
    )


def _summary_sync_check(ctx: HookContext) -> None:
    tool_name = ctx.payload.get("tool_name") or ""
    if tool_name not in {"Edit", "Write", "MultiEdit"}:
        return
    paths = _touched_paths(ctx)

    touched_summary = any(
        os.path.normpath(p).replace("\\", "/").lower().endswith("/workspace-summary.md")
        or os.path.normpath(p).replace("\\", "/").lower() == "workspace-summary.md"
        for p in paths
    )
    if not touched_summary:
        return

    cur_state = ctx.current_state_path
    if cur_state is None or not cur_state.exists():
        _reminder(
            "summary_sync_gate: you edited workspace-summary.md but "
            "`.pmagent/current-state.json` is missing. Run `pmagent status --json` "
            "or the relevant phase command to regenerate machine state."
        )
        return

    try:
        state_mtime = cur_state.stat().st_mtime
    except OSError:
        return
    now = time.time()
    if now - state_mtime > SUMMARY_SYNC_THRESHOLD_SECONDS:
        delta = int(now - state_mtime)
        _reminder(
            f"summary_sync_gate: workspace-summary.md was just edited but "
            f".pmagent/current-state.json is {delta}s old. Refresh structured "
            "state via the phase-specific status command so the two stay in sync."
        )


def _touched_paths(ctx: HookContext) -> list[str]:
    tool_input = ctx.payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []
    paths: list[str] = []
    for key in ("file_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str):
            paths.append(value)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for item in edits:
            if isinstance(item, dict):
                v = item.get("file_path") or item.get("path")
                if isinstance(v, str):
                    paths.append(v)
    return paths


def _workspace_relative(ctx: HookContext, raw_path: str) -> str | None:
    root = ctx.workspace_root
    if root is None:
        return None
    try:
        path = Path(raw_path)
        if not path.is_absolute():
            cwd = ctx.cwd or Path.cwd()
            path = cwd / path
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _is_wiki_sync_candidate(relative: str) -> bool:
    if any(fnmatch(relative, pattern) for pattern in WIKI_SYNC_EXCLUDES):
        return False
    return any(fnmatch(relative, pattern) for pattern in WIKI_SYNC_WHITELIST)


def _feishu_sync_check(ctx: HookContext) -> None:
    tool_name = ctx.payload.get("tool_name") or ""
    if tool_name not in {"Edit", "Write", "MultiEdit"}:
        return
    if not ctx.active_workspace:
        return
    touched = [
        relative
        for raw_path in _touched_paths(ctx)
        for relative in [_workspace_relative(ctx, raw_path)]
        if relative and _is_wiki_sync_candidate(relative)
    ]
    if not touched:
        return
    code, stdout, _ = run_pmagent(
        ["infra", "sync-status", "--workspace", ctx.active_workspace, "--json"],
        timeout=4.0,
    )
    if code != 0 or not stdout.strip():
        return
    try:
        payload = json.loads(stdout)
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    pending = payload.get("pending_files") if isinstance(payload.get("pending_files"), list) else []
    pending = [str(item) for item in pending if str(item).strip()]
    if not pending:
        return
    if payload.get("configured"):
        _reminder(
            "feishu_sync_pending: human-readable PM Data files changed and must be mirrored to Feishu Wiki. "
            "Ask the user whether to sync these files to Feishu Wiki now. "
            "If the user confirms, run "
            f"`pmagent infra wiki-push --workspace {ctx.active_workspace} --json`. "
            f"pending_files={pending}"
        )
    else:
        _reminder(
            "feishu_sync_pending: human-readable PM Data files changed but "
            "no Feishu Wiki adapter is available. Install/configure `lark-cli` "
            "or set `PMAGENT_FEISHU_WIKI_PUSH_COMMAND` for a custom push adapter. "
            f"Run `pmagent infra sync-status --workspace {ctx.active_workspace} --json` after setup. "
            f"pending_files={pending}"
        )


def _raw_log_check(ctx: HookContext) -> None:
    tool_name = ctx.payload.get("tool_name") or ""
    if tool_name != "Bash":
        return
    tool_input = ctx.payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if not isinstance(command, str) or not command:
        return

    root = ctx.workspace_root
    if root is None:
        return

    if CLARIFY_ANSWER_RE.search(command):
        _verify_log_mtime(
            log_path=root / "context" / "clarifying-log.md",
            label="clarifying-log.md",
            cli_hint="append the raw Q/A to context/clarifying-log.md",
        )
    if RESEARCH_NOTE_RE.search(command):
        _verify_log_mtime(
            log_path=root / "research" / "research-log.md",
            label="research-log.md",
            cli_hint="append the raw research note to research/research-log.md",
        )


def _verify_log_mtime(*, log_path: Path, label: str, cli_hint: str) -> None:
    if not log_path.exists():
        _reminder(
            f"phase_raw_logging: expected {label} does not exist yet. {cli_hint}."
        )
        return
    try:
        age = time.time() - log_path.stat().st_mtime
    except OSError:
        return
    # Anything older than ~2 minutes is unlikely to reflect the command we just saw.
    if age > 120:
        _reminder(
            f"phase_raw_logging: {label} was last modified {int(age)}s ago. "
            f"{cli_hint} — AGENTS.md requires the raw content, not only distilled conclusions."
        )


def _run() -> None:
    ctx = load_context()
    _summary_sync_check(ctx)
    _raw_log_check(ctx)
    _feishu_sync_check(ctx)


def main() -> None:
    main_wrapper("post_mutation_check", _run)


if __name__ == "__main__":
    main()
