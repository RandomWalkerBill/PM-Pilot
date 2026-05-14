from pmagent.presentation import build_guided_output, score_table


def test_score_table_renders_overall_and_dimensions() -> None:
    table = score_table(
        {
            "score": 0.72,
            "dimensions": {
                "scope": 0.4,
                "constraints": 0.8,
            },
        }
    )

    assert "| 评分项 | 分数 |" in table
    assert "| overall | 0.72 |" in table
    assert "| scope | 0.4 |" in table
    assert "| constraints | 0.8 |" in table


def test_build_guided_output_keeps_tables_and_detail_lines() -> None:
    output = build_guided_output(
        mode=None,
        phase="clarifying",
        guided_view="clarify-status",
        readiness={
            "phase": "clarifying",
            "score": 0.42,
            "target_dimension": "scope",
            "threshold": 0.8,
            "summary": "Need more scope clarity.",
            "dimensions": {
                "scope": 0.2,
                "constraints": 0.5,
            },
            "gates": {
                "non_goals_resolved": False,
            },
        },
        next_step={"id": "clarify_scope", "reason": "Clarify scope first."},
        pending_user_decision="scope-confirmation",
        route_reason="Clarifying is still active.",
        detail_lines=[
            "- explanation: scope is still too broad",
            "- next_action_note: ask for non-goals explicitly",
        ],
    )

    assert "Readiness 评分表" in output
    assert "| scope | 0.2 |" in output
    assert "zero-to-one" not in output
    assert "- explanation: scope is still too broad" in output
    assert "- next_action_note: ask for non-goals explicitly" in output
