from pmagent.readiness import QUALITY_LEVELS, advance_clarifying_readiness, build_clarifying_readiness


def test_clarifying_initial_score_starts_conservative() -> None:
    readiness = build_clarifying_readiness(has_requirement=True, has_context=False)

    assert readiness["phase"] == "clarifying"
    assert readiness["score"] < 0.35
    assert readiness["transition_recommendation"] is None
    assert "prompt" not in readiness


def test_single_clarifying_answer_does_not_jump_to_ready() -> None:
    readiness = build_clarifying_readiness(has_requirement=True, has_context=False)
    advanced = advance_clarifying_readiness(readiness, answered_dimension="scope")

    assert advanced["dimensions"]["scope"] < 0.70
    assert advanced["score"] < advanced["threshold"]
    assert advanced["ready"] is False
    assert advanced["transition_recommendation"] is None
    assert "prompt" not in advanced


def test_clarifying_quality_levels_are_bounded_and_non_regressive() -> None:
    readiness = build_clarifying_readiness(has_requirement=True, has_context=False)

    weak = advance_clarifying_readiness(readiness, answered_dimension="scope", quality="weak")
    assert weak["dimensions"]["scope"] == QUALITY_LEVELS["weak"]

    strong = advance_clarifying_readiness(weak, answered_dimension="scope", quality="strong")
    assert strong["dimensions"]["scope"] == QUALITY_LEVELS["strong"]

    still_strong = advance_clarifying_readiness(strong, answered_dimension="scope", quality="weak")
    assert still_strong["dimensions"]["scope"] == QUALITY_LEVELS["strong"]


def test_research_readiness_score_is_gate_driven_but_keeps_dimensions() -> None:
    from pmagent.readiness import build_research_readiness

    readiness = build_research_readiness(has_research=True, has_strategy=False, prd_exists=False, has_decisions=False)

    assert readiness["score"] == 0.0
    assert readiness["gates"]["evidence_present"] is False
    assert readiness["dimensions"]["evidence_coverage"] == 0.0
    assert readiness["dimensions"]["source_quality"] == 0.0
    assert readiness["dimensions"]["decision_confidence"] == 0.0
