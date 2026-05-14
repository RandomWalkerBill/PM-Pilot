from __future__ import annotations

from pathlib import Path
from typing import Any, Literal


CLARIFY_READY_THRESHOLD = 0.80
RESEARCH_READY_THRESHOLD = 0.80
QUALITY_LEVELS = {"weak": 0.30, "moderate": 0.60, "strong": 0.85}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def _average(dimensions: dict[str, float]) -> float:
    return _clamp(sum(dimensions.values()) / len(dimensions)) if dimensions else 0.0


def _blocking_gates(gates: dict[str, bool]) -> list[str]:
    return sorted(key for key, value in gates.items() if not value)


def _gate_completion_score(gates: dict[str, bool]) -> float:
    return _clamp(sum(1 for value in gates.values() if value) / len(gates)) if gates else 0.0


def _clarifying_score(dimensions: dict[str, float]) -> float:
    scored_dimensions = {key: value for key, value in dimensions.items() if key not in {"non_goals", "decision_boundaries"}}
    return _clamp(_average(scored_dimensions))


def _build_payload(
    *,
    phase: str,
    dimensions: dict[str, float],
    score: float,
    gates: dict[str, bool],
    summary: str,
    threshold: float,
    ready_when: Literal["gte", "lte"] = "gte",
    transition_recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking = _blocking_gates(gates)
    ready = score >= threshold if ready_when == "gte" else score <= threshold
    return {
        "phase": phase,
        "dimensions": dimensions,
        "score": score,
        "gates": gates,
        "blocking_gates": blocking,
        "summary": summary,
        "threshold": threshold,
        "ready": ready and not blocking,
        "transition_recommendation": transition_recommendation,
    }


def build_clarifying_readiness(*, has_requirement: bool, has_context: bool = False) -> dict[str, Any]:
    dimensions = {
        "intent": 0.0,
        "outcome": 0.0,
        "scope": 0.0,
        "constraints": 0.0,
        "non_goals": 0.0,
        "decision_boundaries": 0.0,
        "context": 0.0,
    }
    gates = {
        "non_goals_resolved": False,
        "decision_boundaries_resolved": False,
    }
    return _build_payload(
        phase="clarifying",
        dimensions=dimensions,
        score=_clarifying_score(dimensions),
        gates=gates,
        summary=(
            "Clarifying is active. Record user answers, then let the external agent update clarifying scores."
            if has_requirement or has_context
            else "Clarifying is active. Collect the first answers, then let the external agent update clarifying scores."
        ),
        threshold=CLARIFY_READY_THRESHOLD,
    )


def advance_clarifying_readiness(
    readiness: dict[str, Any],
    *,
    answered_dimension: str | None = None,
    quality: str = "moderate",
) -> dict[str, Any]:
    existing_dimensions = readiness.get("dimensions", {}) if isinstance(readiness, dict) else {}
    dimensions = {
        "intent": _clamp(float(existing_dimensions.get("intent", 0.2))),
        "outcome": _clamp(float(existing_dimensions.get("outcome", 0.1))),
        "scope": _clamp(float(existing_dimensions.get("scope", 0.2))),
        "constraints": _clamp(float(existing_dimensions.get("constraints", 0.15))),
        "non_goals": _clamp(float(existing_dimensions.get("non_goals", 0.0))),
        "decision_boundaries": _clamp(float(existing_dimensions.get("decision_boundaries", 0.0))),
        "context": _clamp(float(existing_dimensions.get("context", 0.1))),
    }
    existing_gates = readiness.get("gates", {}) if isinstance(readiness, dict) else {}
    gates = {
        "non_goals_resolved": bool(existing_gates.get("non_goals_resolved", False)),
        "decision_boundaries_resolved": bool(existing_gates.get("decision_boundaries_resolved", False)),
    }
    target = answered_dimension or "scope"
    dimensions[target] = _clamp(max(dimensions.get(target, 0.0), QUALITY_LEVELS.get(quality, QUALITY_LEVELS["moderate"])))
    if target == "non_goals":
        gates["non_goals_resolved"] = True
    if target == "decision_boundaries":
        gates["decision_boundaries_resolved"] = True
    return _build_payload(
        phase="clarifying",
        dimensions=dimensions,
        score=_clarifying_score(dimensions),
        gates=gates,
        summary="Clarifying scores updated.",
        threshold=CLARIFY_READY_THRESHOLD,
    )


def build_research_readiness(
    *,
    has_research: bool,
    has_strategy: bool,
    prd_exists: bool,
    has_decisions: bool,
) -> dict[str, Any]:
    gates = {
        "evidence_present": False,
        "decision_direction_recorded": False,
        "ready_for_prd": False,
    }
    dimensions = {
        "evidence_coverage": 0.0,
        "source_quality": 0.0,
        "decision_confidence": 0.0,
        "risk_clarity": 0.0,
        "acceptance_criteria_clarity": 0.0,
    }
    return _build_payload(
        phase="researching",
        dimensions=dimensions,
        score=0.0,
        gates=gates,
        summary=(
            "Research is active. Record evidence, then let the external agent update research scores."
            if has_research or has_strategy or has_decisions or prd_exists
            else "Research is active. Collect the first evidence, then let the external agent update research scores."
        ),
        threshold=RESEARCH_READY_THRESHOLD,
    )


def infer_phase_readiness(
    *,
    phase: str | None,
    active_step: str | None,
    pending_user_decision: str | None,
    artifacts: dict[str, Any] | None,
    observation: dict[str, Any] | None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    del active_step
    del observation
    artifacts = artifacts or {}
    prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
    prd_exists = bool(prd.get("canonical_path")) or str(prd.get("status")) in {"active", "maintained", "draft"}
    requirement = artifacts.get("requirement", {}) if isinstance(artifacts, dict) else {}
    has_requirement = bool(requirement.get("exists"))
    has_research = False
    has_strategy = False
    has_decisions = False
    has_export = False
    has_context = False
    if workspace_root is not None:
        context_root = workspace_root / "context"
        has_context = context_root.exists() and any(context_root.iterdir())
        research_root = workspace_root / "research"
        has_research = research_root.exists() and any(research_root.iterdir())
        strategy_root = workspace_root / "strategy"
        has_strategy = strategy_root.exists() and any(strategy_root.iterdir())
        decisions_root = workspace_root / "decisions"
        has_decisions = decisions_root.exists() and any(decisions_root.iterdir())
        exports_root = workspace_root / "exports"
        has_export = exports_root.exists() and any(exports_root.iterdir())
        drafts_root = workspace_root / "maintenance" / "drafts"
        draft_exists = drafts_root.exists() and any(drafts_root.glob("*.md"))
        accepted_root = workspace_root / "candidate-updates" / "accepted"
        accepted = len(list(accepted_root.glob("*.md"))) if accepted_root.exists() else 0
    else:
        draft_exists = False
        accepted = 0

    if phase == "researching":
        return build_research_readiness(
            has_research=has_research,
            has_strategy=has_strategy,
            prd_exists=prd_exists,
            has_decisions=has_decisions,
        )

    if phase in {"delivery", "dev-readiness", "maintaining"}:
        return {}

    return build_clarifying_readiness(has_requirement=has_requirement, has_context=has_context)
