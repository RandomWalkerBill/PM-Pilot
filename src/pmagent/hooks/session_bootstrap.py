"""SessionStart hook: read-order + audit_gate.

Injects AGENTS.md / agent-workflow.yaml / projects.json / workspace-summary /
current-state excerpts, plus the output of ``pmagent observe audit
--run-catch-up --json`` when an active workspace is present.
"""

from __future__ import annotations

import json
from pathlib import Path

from ._common import (
    HookContext,
    emit_context_block,
    load_context,
    main_wrapper,
    run_pmagent,
)


SUMMARY_HEAD_LINES = 40
AGENTS_HEAD_LINES = 120
WORKFLOW_HEAD_LINES = 80


def _head(path: Path, n: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    head = "\n".join(lines[:n])
    if len(lines) > n:
        head += f"\n... ({len(lines) - n} more lines truncated)"
    return head


def _inject_base_context(ctx: HookContext) -> None:
    if ctx.data_dir is None:
        emit_context_block(
            "session-bootstrap",
            "pmagent data_dir is not configured. Run `pmagent init` or set PMAGENT_DATA_DIR.",
        )
        return

    sections: list[str] = []
    sections.append(f"data_dir: {ctx.data_dir}")
    sections.append(f"active_project: {ctx.active_project or '(none)'}")
    sections.append(f"active_workspace: {ctx.active_workspace or '(none)'}")

    agents_md = ctx.data_dir / "AGENTS.md"
    if agents_md.exists():
        sections.append("\n## AGENTS.md (head)\n" + _head(agents_md, AGENTS_HEAD_LINES))

    workflow_yaml = ctx.data_dir / "config" / "agent-workflow.yaml"
    if workflow_yaml.exists():
        sections.append(
            "\n## agent-workflow.yaml (head)\n"
            + _head(workflow_yaml, WORKFLOW_HEAD_LINES)
        )

    projects_json = ctx.data_dir / "config" / "projects.json"
    if projects_json.exists():
        try:
            content = projects_json.read_text(encoding="utf-8")
        except OSError:
            content = ""
        if content:
            sections.append("\n## projects.json\n```json\n" + content.strip() + "\n```")

    emit_context_block("session-bootstrap", "\n".join(sections))


def _inject_workspace_context(ctx: HookContext) -> None:
    root = ctx.workspace_root
    if root is None or not root.exists():
        return

    parts: list[str] = []

    summary = root / "workspace-summary.md"
    if summary.exists():
        parts.append("## workspace-summary.md (head)\n" + _head(summary, SUMMARY_HEAD_LINES))

    cur_state = ctx.current_state_path
    if cur_state and cur_state.exists():
        try:
            state = json.loads(cur_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        if state:
            keep = {
                k: state.get(k)
                for k in (
                    "project",
                    "workspace",
                    "phase",
                    "active_step",
                    "pending_user_decision",
                    "next_recommended_step",
                    "recommended_skills",
                    "observation",
                    "observation_tracking",
                    "debates",
                    "debate_review",
                    "debate_launch",
                    "updated_at",
                )
                if k in state
            }
            parts.append(
                "## current-state.json (selected)\n```json\n"
                + json.dumps(keep, ensure_ascii=False, indent=2)
                + "\n```"
            )

    if parts:
        emit_context_block("session-workspace", "\n\n".join(parts))


def _inject_debate_attention(ctx: HookContext) -> None:
    cur_state = ctx.current_state_path
    if cur_state is None or not cur_state.exists():
        return
    try:
        state = json.loads(cur_state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(state, dict):
        return

    debates = state.get("debates") if isinstance(state.get("debates"), dict) else {}
    debate_review = state.get("debate_review") if isinstance(state.get("debate_review"), dict) else {}
    debate_launch = state.get("debate_launch") if isinstance(state.get("debate_launch"), dict) else {}

    failed = int(debates.get("failed_count", 0) or 0)
    if failed > 0:
        topics = debates.get("failed_topics") if isinstance(debates.get("failed_topics"), list) else []
        topic_tail = f" topics: {', '.join(str(item) for item in topics[:5])}" if topics else ""
        emit_context_block(
            "debate-failure",
            f"WARNING debate_failure_gate: {failed} debate run(s) failed and need inspection.{topic_tail}\n"
            "Inspect the failed debate topic before resuming normal workflow.",
        )

    pending = int(debates.get("completed_awaiting_review_count", 0) or 0)
    if pending > 0:
        topics = debate_review.get("awaiting_review_topics") if isinstance(debate_review.get("awaiting_review_topics"), list) else []
        topic_tail = f" topics: {', '.join(str(item) for item in topics[:5])}" if topics else ""
        emit_context_block(
            "debate-review",
            f"WARNING debate_visibility_gate: {pending} debate synthesis file(s) await review.{topic_tail}\n"
            "Review the debate result before mutating canonical PRD / Requirement documents.",
        )

    if bool(debate_launch.get("active")):
        emit_context_block(
            "debate-launch",
            "\n".join(
                [
                    f"WARNING debate_launch_pending: {debate_launch.get('reason') or 'debate executor precheck previously failed'}",
                    f"thesis: {debate_launch.get('thesis') or ''}",
                    f"axis: {debate_launch.get('axis') or ''}",
                    f"topic_slug: {debate_launch.get('topic_slug') or ''}",
                    "Once the user updates the Debate executor/model config, execute `pmagent debate start ...` before continuing normal work.",
                ]
            ),
        )


def _inject_audit(ctx: HookContext) -> None:
    if not ctx.active_workspace:
        return
    code, stdout, stderr = run_pmagent(
        [
            "observe",
            "audit",
            "--workspace",
            ctx.active_workspace,
            "--run-catch-up",
            "--json",
        ],
        timeout=6.0,
    )
    body_parts = [f"command exit: {code}"]
    if stdout.strip():
        body_parts.append("stdout:\n" + stdout.strip())
    if stderr.strip():
        body_parts.append("stderr:\n" + stderr.strip())
    emit_context_block("observe-audit", "\n\n".join(body_parts))


def _run() -> None:
    ctx = load_context()
    _inject_base_context(ctx)
    _inject_workspace_context(ctx)
    _inject_debate_attention(ctx)
    _inject_audit(ctx)


def main() -> None:
    main_wrapper("session_bootstrap", _run)


if __name__ == "__main__":
    main()
