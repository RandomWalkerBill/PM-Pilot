"""Stop hook: Score Visibility & Depth Retention.

If any recent tool result contains a score-bearing object (readiness,
dimensions, blocking_gates, etc.), the final assistant reply must contain a
markdown table. Otherwise we block once and ask for a rewrite.

Re-blocks are disabled when ``stop_hook_active`` is true to avoid infinite
retries.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ._common import (
    block,
    extract_text_from_message,
    load_context,
    main_wrapper,
    read_transcript_messages,
)


SCORE_KEYS = {
    "readiness",
    "score",
    "scores",
    "dimensions",
    "threshold",
    "gates",
    "blocking_gates",
    "target_dimension",
}

SCORE_CONTAINER_KEYS = {
    "readiness",
    "candidate_review",
    "maintenance_readiness",
    "cards",
}

TABLE_LINE_RE = re.compile(r"\|\s*-{3,}\s*\|")


def _walk(value: Any, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SCORE_KEYS:
                return True
            if isinstance(k, str) and k.lower() in SCORE_CONTAINER_KEYS:
                return True
            if _walk(v, depth + 1):
                return True
    elif isinstance(value, list):
        for item in value:
            if _walk(item, depth + 1):
                return True
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return False
            return _walk(parsed, depth + 1)
    return False


def _tool_result_has_scores(message: dict[str, Any]) -> bool:
    content = message.get("content")
    if isinstance(content, list):
        for block_obj in content:
            if isinstance(block_obj, dict) and block_obj.get("type") in {
                "tool_result",
                "tool_use_result",
            }:
                if _walk(block_obj.get("content")):
                    return True
    return False


def _has_markdown_table(text: str) -> bool:
    return bool(TABLE_LINE_RE.search(text))


def _run() -> None:
    ctx = load_context()
    if ctx.payload.get("stop_hook_active"):
        return

    messages = read_transcript_messages(ctx.transcript_path, limit=40)
    if not messages:
        return

    # Walk backwards to find the most recent assistant message and gather tool
    # results that appeared after the previous user turn.
    last_assistant_text: str | None = None
    recent_tool_results: list[dict[str, Any]] = []
    saw_user = False
    for msg in reversed(messages):
        role = msg.get("role") or msg.get("type")
        if last_assistant_text is None and role == "assistant":
            last_assistant_text = extract_text_from_message(msg)
        if role in {"user", "tool", "tool_result"}:
            recent_tool_results.append(msg)
            if role == "user":
                saw_user = True
                break
        if saw_user:
            break

    if last_assistant_text is None:
        return

    has_scores = any(_tool_result_has_scores(m) for m in recent_tool_results)
    if not has_scores:
        return

    if _has_markdown_table(last_assistant_text):
        return

    block(
        "blocked by score_visibility gate: a score-bearing object (readiness / "
        "dimensions / blocking_gates / cards.scores) appeared in this turn's tool "
        "results but your reply did not render the score table. AGENTS.md Score "
        "Visibility Contract requires the raw scores table before prose, plus "
        "per-dimension scores when dimensions exist. Rewrite your reply with the "
        "score table followed by depth-retained explanation, risks and next-step "
        "guidance."
    )


def main() -> None:
    main_wrapper("response_validator", _run)


if __name__ == "__main__":
    main()
