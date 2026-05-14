from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    return markdown_table(headers, rows)


def _string(value: Any) -> str:
    if value is None:
        return "—"
    return str(value)


def _blocking_gates(readiness: dict[str, Any] | None) -> str:
    if not isinstance(readiness, dict):
        return "—"
    failing = readiness.get("blocking_gates")
    if isinstance(failing, list):
        return ", ".join(str(item) for item in failing) if failing else "none"
    gates = readiness.get("gates")
    if isinstance(gates, dict):
        failed = [str(key) for key, value in gates.items() if not value]
        return ", ".join(sorted(failed)) if failed else "none"
    return "—"


def _readiness_overview_table(readiness: dict[str, Any] | None) -> str:
    if not isinstance(readiness, dict):
        readiness = {}
    transition = readiness.get("transition_recommendation") if isinstance(readiness.get("transition_recommendation"), dict) else {}
    transition_label = "—"
    transition_reason = "—"
    if transition:
        to_phase = transition.get("to_phase")
        status = transition.get("status")
        if to_phase:
            transition_label = f"{to_phase}（待确认）" if status == "recommended" else str(to_phase)
        transition_reason = _string(transition.get("reason"))
    rows = [
        ["阶段", _string(readiness.get("phase"))],
        ["总分", _string(readiness.get("score"))],
        ["硬性条件", _blocking_gates(readiness)],
        ["阶段阈值", _string(readiness.get("threshold"))],
        ["阶段切换建议", transition_label],
        ["切换原因", transition_reason],
        ["摘要", _string(readiness.get("summary"))],
    ]
    return markdown_table(["字段", "值"], rows)


def score_rows(score_object: dict[str, Any] | None) -> list[list[str]]:
    if not isinstance(score_object, dict):
        return []
    dimensions = score_object.get("dimensions")
    rows: list[list[str]] = []
    if score_object.get("score") is not None:
        rows.append(["overall", _string(score_object.get("score"))])
    if not isinstance(dimensions, dict) or not dimensions:
        return rows
    rows.extend([[str(key), _string(value)] for key, value in dimensions.items()])
    return rows


def score_table(
    score_object: dict[str, Any] | None,
    *,
    headers: tuple[str, str] = ("评分项", "分数"),
) -> str:
    rows = score_rows(score_object)
    if not rows:
        return ""
    return markdown_table(list(headers), rows)


def _readiness_scores_table(readiness: dict[str, Any] | None) -> str:
    if not isinstance(readiness, dict):
        return ""
    return score_table(readiness)


def _has_visible_readiness(readiness: dict[str, Any] | None) -> bool:
    if not isinstance(readiness, dict):
        return False
    if readiness.get("score") is not None:
        return True
    dimensions = readiness.get("dimensions")
    if isinstance(dimensions, dict) and dimensions:
        return True
    return False


def build_status_block(
    *,
    mode: str | None,
    phase: str | None,
    guided_view: str | None,
    readiness: dict[str, Any] | None,
    next_step: dict[str, Any] | None,
    pending_user_decision: str | None = None,
    route_reason: str | None = None,
) -> str:
    del mode
    overview = markdown_table(
        ["字段", "值"],
        [
            ["当前阶段", _string(phase)],
            ["当前工作面", _string(guided_view)],
            ["路由原因", _string(route_reason)],
            ["待用户确认", _string(pending_user_decision)],
        ],
    )
    next_table = markdown_table(
        ["字段", "值"],
        [
            ["动作", _string(next_step.get("id") if isinstance(next_step, dict) else None)],
            ["原因", _string(next_step.get("reason") if isinstance(next_step, dict) else None)],
        ],
    )
    parts = ["状态概览", overview]
    if _has_visible_readiness(readiness):
        parts.extend(["", "Readiness 概览", _readiness_overview_table(readiness)])
        scores_table = _readiness_scores_table(readiness)
        if scores_table:
            parts.extend(["", "Readiness 评分表", scores_table])
    parts.extend(["", "下一步", next_table])
    return "\n".join(parts)


def build_guided_output(
    *,
    mode: str | None,
    phase: str | None,
    guided_view: str | None,
    readiness: dict[str, Any] | None,
    next_step: dict[str, Any] | None,
    pending_user_decision: str | None = None,
    route_reason: str | None = None,
    detail_lines: Sequence[str] | None = None,
) -> str:
    parts = [
        build_status_block(
            mode=mode,
            phase=phase,
            guided_view=guided_view,
            readiness=readiness,
            next_step=next_step,
            pending_user_decision=pending_user_decision,
            route_reason=route_reason,
        )
    ]
    if detail_lines:
        parts.extend(["---", *detail_lines])
    return "\n".join(parts)
