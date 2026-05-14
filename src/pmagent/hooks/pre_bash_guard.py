"""PreToolUse (Bash) guard: review_gate.

Intercepts ``pmagent observe accept|reject|snooze`` calls when the recent
transcript does not contain an explicit user confirmation for the action.
All other Bash commands pass through untouched.
"""

from __future__ import annotations

import re
import shlex

from ._common import (
    block,
    extract_text_from_message,
    load_context,
    main_wrapper,
    read_transcript_messages,
)


REVIEW_CMD_RE = re.compile(
    r"\bpmagent\s+observe\s+(accept|reject|snooze)\b",
    re.IGNORECASE,
)

CONFIRM_TOKENS = (
    "accept",
    "reject",
    "snooze",
    "confirm",
    "approve",
    "dismiss",
    "接受",
    "拒绝",
    "驳回",
    "通过",
    "跳过",
    "确认",
    "snooz",
)


def _parse_card_id(command: str) -> str | None:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    for i, tok in enumerate(tokens):
        if tok == "--card" and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok.startswith("--card="):
            return tok.split("=", 1)[1]
    return None


def _recent_user_text(ctx) -> str:
    messages = read_transcript_messages(ctx.transcript_path, limit=30)
    texts: list[str] = []
    for msg in reversed(messages):
        if msg.get("role") == "user" or msg.get("type") == "user":
            texts.append(extract_text_from_message(msg).lower())
            if len(texts) >= 3:
                break
    return "\n".join(texts)


def _user_has_confirmed(recent: str, verb: str, card_id: str | None) -> bool:
    if not recent:
        return False
    if verb.lower() in recent:
        return True
    for token in CONFIRM_TOKENS:
        if token in recent:
            return True
    if card_id and card_id.lower() in recent:
        return True
    return False


def _run() -> None:
    ctx = load_context()
    tool_input = ctx.payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if not isinstance(command, str) or not command:
        return

    match = REVIEW_CMD_RE.search(command)
    if not match:
        return

    verb = match.group(1)
    card_id = _parse_card_id(command)
    recent_user_text = _recent_user_text(ctx)

    if _user_has_confirmed(recent_user_text, verb, card_id):
        return

    reason = (
        "blocked by review_gate: `pmagent observe "
        f"{verb}` requires explicit user confirmation in the current turn "
        "(matching card id, or an accept/reject/snooze statement). "
        "Surface the unread observation to the user, get a clear decision, "
        "then rerun."
    )
    block(reason)


def main() -> None:
    main_wrapper("pre_bash_guard", _run)


if __name__ == "__main__":
    main()
