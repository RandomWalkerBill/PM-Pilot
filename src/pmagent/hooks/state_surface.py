"""UserPromptSubmit hook: state_first_gate + backlog_visibility_gate.

Runs on every user message; keeps the agent's mental state fresh and flags
unread observation backlog before mainline work resumes.
"""

from __future__ import annotations

import json

from ._common import emit_context_block, load_context, main_wrapper, run_pmagent


STATE_KEYS = (
    "project",
    "workspace",
    "phase",
    "active_step",
    "pending_user_decision",
    "next_recommended_step",
    "recommended_skills",
    "debates",
    "debate_review",
    "debate_launch",
    "updated_at",
)


def _inject_status() -> None:
    ctx = load_context()
    if ctx.data_dir is None:
        return
    if not ctx.active_workspace:
        emit_context_block(
            "state-surface",
            "no active workspace — use `pmagent status` or `pmagent start` to begin.",
        )
        return

    code, stdout, _ = run_pmagent(
        ["status", "--workspace", ctx.active_workspace, "--json"],
        timeout=3.0,
    )
    block_body: str | None = None
    if code == 0 and stdout.strip():
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            compact = {k: payload.get(k) for k in STATE_KEYS if k in payload}
            block_body = (
                "refresh before advancing phase/step. `pmagent status --json`:\n"
                + "```json\n"
                + json.dumps(compact, ensure_ascii=False, indent=2)
                + "\n```"
            )
    if block_body is None:
        state = ctx.load_current_state()
        if state:
            compact = {k: state.get(k) for k in STATE_KEYS if k in state}
            block_body = (
                "fallback state from `.pmagent/current-state.json`:\n"
                + "```json\n"
                + json.dumps(compact, ensure_ascii=False, indent=2)
                + "\n```"
            )
    if block_body:
        emit_context_block("state-surface", block_body)


def _inject_backlog() -> None:
    ctx = load_context()
    if not ctx.active_workspace:
        return

    code, stdout, _ = run_pmagent(
        ["observe", "unread", "--workspace", ctx.active_workspace, "--json"],
        timeout=3.0,
    )
    if code != 0 or not stdout.strip():
        return
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return

    count: int | None = None
    ids: list[str] = []
    if isinstance(payload, dict):
        raw_ids = payload.get("ids") or payload.get("unread") or []
        if isinstance(raw_ids, list):
            ids = [str(x) for x in raw_ids][:10]
        raw_count = payload.get("count")
        if isinstance(raw_count, int):
            count = raw_count
        elif ids:
            count = len(ids)
    elif isinstance(payload, list):
        ids = [str(x) for x in payload][:10]
        count = len(payload)

    if not count:
        return

    id_tail = ""
    if ids:
        id_tail = " first ids: " + ", ".join(ids)
    emit_context_block(
        "backlog-visibility",
        f"WARNING backlog_visibility_gate: {count} unread observation(s).{id_tail}\n"
        "Per AGENTS.md you must surface and handle candidate-review before advancing main work.",
    )


def _inject_debate_backlog() -> None:
    ctx = load_context()
    if not ctx.active_workspace:
        return

    state = ctx.load_current_state()
    debates = state.get("debates") if isinstance(state.get("debates"), dict) else {}
    debate_review = state.get("debate_review") if isinstance(state.get("debate_review"), dict) else {}
    pending = int(debates.get("completed_awaiting_review_count", 0) or 0)
    if pending <= 0:
        return
    topics = debate_review.get("awaiting_review_topics") if isinstance(debate_review.get("awaiting_review_topics"), list) else []
    topic_tail = f" topics: {', '.join(str(item) for item in topics[:5])}" if topics else ""
    emit_context_block(
        "debate-visibility",
        f"WARNING debate_visibility_gate: {pending} debate synthesis file(s) await review.{topic_tail}\n"
        "Review the debate result before mutating canonical PRD / Requirement documents.",
    )


def _inject_debate_failures() -> None:
    ctx = load_context()
    if not ctx.active_workspace:
        return

    state = ctx.load_current_state()
    debates = state.get("debates") if isinstance(state.get("debates"), dict) else {}
    failed = int(debates.get("failed_count", 0) or 0)
    if failed <= 0:
        return
    topics = debates.get("failed_topics") if isinstance(debates.get("failed_topics"), list) else []
    topics = [str(item) for item in topics[:5] if str(item).strip()]
    topic_tail = f" topics: {', '.join(topics)}" if topics else ""
    emit_context_block(
        "debate-failure",
        f"WARNING debate_failure_gate: {failed} debate run(s) failed and need inspection.{topic_tail}\n"
        "Inspect the failed debate topic before resuming normal workflow.",
    )


def _inject_debate_launch_pending() -> None:
    ctx = load_context()
    if not ctx.active_workspace:
        return
    state = ctx.load_current_state()
    launch = state.get("debate_launch") if isinstance(state.get("debate_launch"), dict) else {}
    if not launch.get("active"):
        return
    thesis = launch.get("thesis") or ""
    axis = launch.get("axis") or ""
    topic_slug = launch.get("topic_slug") or ""
    reason = launch.get("reason") or "debate executor precheck previously failed"
    emit_context_block(
        "debate-launch-pending",
        "\n".join(
            [
                f"WARNING debate_launch_pending: {reason}",
                f"thesis: {thesis}",
                f"axis: {axis}",
                f"topic_slug: {topic_slug}",
                "Once the user updates the Debate executor/model config, execute `pmagent debate start ...` before continuing normal work.",
            ]
        ),
    )


def _run() -> None:
    _inject_status()
    _inject_backlog()
    _inject_debate_failures()
    _inject_debate_backlog()
    _inject_debate_launch_pending()


def main() -> None:
    main_wrapper("state_surface", _run)


if __name__ == "__main__":
    main()
