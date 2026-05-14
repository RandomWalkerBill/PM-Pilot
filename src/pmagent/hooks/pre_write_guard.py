"""PreToolUse (Edit | Write | MultiEdit) guard: canonical review boundaries.

Blocks direct edits to canonical workspace documents when either:

- observation ``candidate_review`` is active
- debate ``debate_review`` has pending synthesis awaiting review

Canonical docs currently include ``workspaces/<ws>/prd/**`` and the workspace
root ``Requirement.md``. Debate / observation signals should first be reviewed
and then flow through decision / strategy / maintenance paths rather than
directly mutating the canonical docs from the review surface.
"""

from __future__ import annotations

import os
from ._common import block, load_context, main_wrapper


WATCHED_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _candidate_paths(tool_name: str, tool_input: dict) -> list[str]:
    paths: list[str] = []
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for item in edits:
            if isinstance(item, dict):
                v = item.get("file_path") or item.get("path")
                if isinstance(v, str) and v:
                    paths.append(v)
    return paths


def _hits_canonical_doc(path_str: str, workspace: str) -> bool:
    try:
        norm = os.path.normpath(path_str).replace("\\", "/").lower()
    except Exception:  # noqa: BLE001
        return False
    prd_needle = f"workspaces/{workspace.lower()}/prd/"
    requirement_suffix = f"workspaces/{workspace.lower()}/requirement.md"
    return prd_needle in norm or norm.endswith(requirement_suffix)


def _run() -> None:
    ctx = load_context()
    if not ctx.active_workspace:
        return
    tool_name = ctx.payload.get("tool_name") or ""
    if tool_name not in WATCHED_TOOLS:
        return
    tool_input = ctx.payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return

    state = ctx.load_current_state()
    candidate_review = state.get("candidate_review") if isinstance(state.get("candidate_review"), dict) else {}
    debate_review = state.get("debate_review") if isinstance(state.get("debate_review"), dict) else {}
    candidate_review_active = bool(candidate_review.get("active")) or (state.get("active_step") or "").strip().lower() == "candidate-review"
    debate_review_pending = int(debate_review.get("completed_awaiting_review_count", 0) or 0) > 0
    if not candidate_review_active and not debate_review_pending:
        return

    paths = _candidate_paths(tool_name, tool_input)
    for candidate in paths:
        if not _hits_canonical_doc(candidate, ctx.active_workspace):
            continue
        if candidate_review_active:
            block(
                "blocked by observation_boundary_gate: candidate-review must not edit "
                f"`{candidate}` directly. Accept signals first, then run "
                "`pmagent observe draft-maintenance` and author the PRD change via the "
                "maintenance draft container."
            )
        if debate_review_pending:
            block(
                "blocked by debate_boundary_gate: a completed debate synthesis is awaiting review, "
                f"so `{candidate}` must not be edited directly yet. Review the debate result, "
                "record the decision or strategy change, then update canonical docs through the "
                "agreed path."
            )


def main() -> None:
    main_wrapper("pre_write_guard", _run)


if __name__ == "__main__":
    main()
