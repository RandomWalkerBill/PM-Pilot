from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from .current_state import preview_current_state, sync_current_state
from .paths import resolve_data_dir
from .cli_helpers import _infer_project_for_workspace
from .cli_routing import _guided_envelope, _phase_status_command, _route_payload, _status_payload, cmd_status
from .presentation import build_guided_output
from .cli_workspace import _workspace_root
from .cli_scaffold import _read_packaged_text

def cmd_prd_status(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    try:
        payload = _status_payload(data_dir, workspace=args.workspace)
    except SystemExit:
        route_payload = _route_payload(data_dir, workspace=args.workspace)
        if args.json:
            print(json.dumps(route_payload, ensure_ascii=False, indent=2))
        else:
            print(f"navigation_state={route_payload.get('navigation_state')}")
            print(f"handoff_hint={route_payload.get('handoff_hint')}")
            print(f"route_reason={route_payload.get('route_reason')}")
            next_step = route_payload.get("next_recommended_step", {}) if isinstance(route_payload.get("next_recommended_step"), dict) else {}
            print(f"next_step={next_step.get('id')}")
            print(f"next_step_reason={next_step.get('reason')}")
            print(f"suggested_command={route_payload.get('suggested_command')}")
        return 0
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
    route_context = _route_payload(data_dir, workspace=payload.get("workspace"), project=payload.get("project"))
    response = {
        "workspace": payload.get("workspace"),
        "project": payload.get("project"),
        "phase": payload.get("phase"),
        "prd_status": prd.get("status"),
        "prd_canonical_path": prd.get("canonical_path"),
        "next_recommended_step": payload.get("next_recommended_step"),
        "recommended_skills": route_context.get("recommended_skills", []),
        "handoff_hint": route_context.get("handoff_hint"),
        "suggested_command": route_context.get("suggested_command"),
    }
    if args.json:
        print(json.dumps(_guided_envelope(route_context, guided_view="prd-status", payload=response), ensure_ascii=False, indent=2))
    else:
        print(
            build_guided_output(
                mode=None,
                phase=response.get("phase"),
                guided_view="prd-status",
                readiness=None,
                next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason=route_context.get("route_reason"),
                detail_lines=[
                    f"- workspace: {response.get('workspace')}",
                    f"- project: {response.get('project')}",
                    f"- recommended_skills: {[item.get('id') for item in response.get('recommended_skills', []) if isinstance(item, dict)]}",
                    f"- handoff_hint: {response.get('handoff_hint')}",
                    f"- prd_status: {response.get('prd_status')}",
                    f"- prd_canonical_path: {response.get('prd_canonical_path')}",
                    f"- suggested_command: {response.get('suggested_command')}",
                ],
            )
        )
    return 0


def cmd_prd(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)

    if args.subcommand == "status":
        return cmd_prd_status(argparse.Namespace(data_dir=str(data_dir), workspace=args.workspace, json=args.json))

    payload = _status_payload(data_dir, workspace=args.workspace)

    if args.subcommand == "review":
        workspace = str(payload.get("workspace"))
        artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
        prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
        observation = payload.get("observation", {}) if isinstance(payload.get("observation"), dict) else {}
        accepted_count = int(observation.get("queue", {}).get("accepted", 0)) if isinstance(observation, dict) else 0
        downstream_options = [
            {
                "id": "challenge_prd",
                "reason": "Stress-test scope, risks, and acceptance criteria before locking the draft.",
                "suggested_command": "skills/steps/challenge-prd/skill.md",
            },
            {
                "id": "export_workspace",
                "reason": "Export only after the PRD is stable enough for downstream engineering handoff.",
                "suggested_command": f"pmagent export --project {payload.get('project')} --workspace {workspace}",
            },
            {
                "id": "observe_status",
                "reason": "Check whether observation focus and backlog still align with the current PRD.",
                "suggested_command": f"pmagent observe status --project {payload.get('project')} --workspace {workspace}",
            },
        ]
        response = {
            "workspace": workspace,
            "project": payload.get("project"),
            "prd_status": prd.get("status"),
            "prd_canonical_path": prd.get("canonical_path"),
            "accepted_count": accepted_count,
            "next_recommended_step": payload.get("next_recommended_step"),
            "downstream_options": downstream_options,
        }
        route_context = _route_payload(data_dir, workspace=workspace, project=payload.get("project"))
        if args.json:
            print(json.dumps(_guided_envelope(route_context, guided_view="prd-review", payload=response), ensure_ascii=False, indent=2))
        else:
            option_lines: list[str] = []
            for option in downstream_options:
                option_lines.extend(
                    [
                        f"- option: {option['id']}",
                        f"  reason: {option['reason']}",
                        f"  suggested_command: {option['suggested_command']}",
                    ]
                )
            print(
                build_guided_output(
                    mode=None,
                    phase=payload.get("phase"),
                    guided_view="prd-review",
                    readiness=None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=payload.get("pending_user_decision"),
                    route_reason=route_context.get("route_reason"),
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- project: {response['project']}",
                        f"- prd_status: {response['prd_status']}",
                        f"- prd_canonical_path: {response['prd_canonical_path']}",
                        f"- accepted_count: {response['accepted_count']}",
                        *option_lines,
                    ],
                )
            )
        return 0

    if args.subcommand == "challenge":
        workspace = str(payload.get("workspace"))
        state = sync_current_state(
            data_dir,
            workspace,
            patch={
                "phase": "delivery",
                "active_step": "challenge-prd",
                "next_recommended_step": {
                    "id": "export_workspace",
                    "reason": "After challenging the PRD, either revise it or export it for downstream use.",
                },
            },
            updated_by="prd-challenge",
        )
        artifacts = state.get("artifacts", {}) if isinstance(state.get("artifacts"), dict) else {}
        prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
        challenge_checklist = [
            "Check whether the current scope still matches the stated goals and non-goals.",
            "Check whether the main risks and mitigations are explicit.",
            "Check whether acceptance criteria are concrete and testable.",
            "Check whether observation should keep watching any post-launch signals.",
        ]
        downstream_options = [
            {
                "id": "revise_prd",
                "reason": "If challenge feedback reveals scope or risk gaps, revise the canonical PRD first.",
                "suggested_command": "pmagent prd status",
            },
            {
                "id": "export_workspace",
                "reason": "If the PRD is stable enough, export it for downstream engineering use.",
                "suggested_command": f"pmagent export --project {state.get('project')} --workspace {workspace}",
            },
            {
                "id": "observe_status",
                "reason": "If the PRD changed materially, verify that observation focus still matches it.",
                "suggested_command": f"pmagent observe status --project {state.get('project')} --workspace {workspace}",
            },
        ]
        response = {
            "workspace": workspace,
            "project": state.get("project"),
            "prd_status": prd.get("status"),
            "prd_canonical_path": prd.get("canonical_path"),
            "challenge_skill_path": "skills/steps/challenge-prd/skill.md",
            "checklist": challenge_checklist,
            "next_recommended_step": state.get("next_recommended_step"),
            "downstream_options": downstream_options,
        }
        route_context = _route_payload(data_dir, workspace=workspace, project=state.get("project"))
        if args.json:
            print(json.dumps(_guided_envelope(route_context, guided_view="prd-challenge", payload=response), ensure_ascii=False, indent=2))
        else:
            option_lines: list[str] = []
            for option in downstream_options:
                option_lines.extend(
                    [
                        f"- option: {option['id']}",
                        f"  reason: {option['reason']}",
                        f"  suggested_command: {option['suggested_command']}",
                    ]
                )
            print(
                build_guided_output(
                    mode=None,
                    phase="delivery",
                    guided_view="prd-challenge",
                    readiness=None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=state.get("pending_user_decision"),
                    route_reason=route_context.get("route_reason"),
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- project: {response['project']}",
                        f"- prd_status: {response['prd_status']}",
                        f"- prd_canonical_path: {response['prd_canonical_path']}",
                        f"- challenge_skill_path: {response['challenge_skill_path']}",
                        *[f"- checklist: {item}" for item in challenge_checklist],
                        *option_lines,
                    ],
                )
            )
        return 0

    if args.subcommand == "init-draft":
        workspace = str(payload.get("workspace"))
        workspace_path = _workspace_root(data_dir, workspace)
        prd_root = workspace_path / "prd"
        prd_root.mkdir(parents=True, exist_ok=True)
        canonical = prd_root / "current.md"
        if not canonical.exists():
            template = _read_packaged_text("templates/PRD_TEMPLATE.md")
            canonical.write_text(template, encoding="utf-8")
        state = sync_current_state(
            data_dir,
            workspace,
            patch={
                "phase": "delivery",
                "active_step": "write-prd",
                "pending_user_decision": None,
                "next_recommended_step": {
                    "id": "challenge_prd",
                    "reason": "PRD draft exists; review and challenge it before export or observation maintenance.",
                },
            },
            updated_by="prd-init-draft",
        )
        response = {
            "workspace": workspace,
            "prd_path": str(canonical.relative_to(data_dir)).replace("\\", "/"),
            "readiness": state.get("readiness"),
            "next_recommended_step": state.get("next_recommended_step"),
        }
        route_context = _route_payload(data_dir, workspace=workspace, project=state.get("project"))
        if args.json:
            print(json.dumps(_guided_envelope(route_context, guided_view="prd-init-draft", payload=response), ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase="delivery",
                    guided_view="prd-init-draft",
                    readiness=None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=state.get("pending_user_decision"),
                    route_reason=route_context.get("route_reason"),
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- prd_path: {response['prd_path']}",
                    ],
                )
            )
        return 0

    raise SystemExit(f"unsupported prd subcommand: {args.subcommand}")
def _append_clarifying_note(
    data_dir: Path,
    workspace: str,
    *,
    answer: str,
) -> Path:
    context_root = _workspace_root(data_dir, workspace) / "context"
    context_root.mkdir(parents=True, exist_ok=True)
    log_path = context_root / "clarifying-log.md"
    lines = [
        f"## {date.today().isoformat()} | response",
        "",
        answer.strip(),
        "",
    ]
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return log_path


def _load_scores_patch(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("patch file must contain a JSON object")
    return payload


def _validated_dimensions(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("dimensions", {})
    if not isinstance(raw, dict):
        raise SystemExit("patch file field 'dimensions' must be an object")
    validated: dict[str, float] = {}
    for key, value in raw.items():
        try:
            numeric = max(0.0, min(1.0, round(float(value), 2)))
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"invalid dimension score for '{key}': {value}") from exc
        validated[str(key)] = numeric
    return validated


def _validated_gates(payload: dict[str, Any]) -> dict[str, bool]:
    raw = payload.get("gates", {})
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("patch file field 'gates' must be an object")
    return {str(key): bool(value) for key, value in raw.items()}


def _clarifying_transition_from_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
    gates = readiness.get("gates", {}) if isinstance(readiness.get("gates"), dict) else {}
    all_gates_passed = all(bool(value) for value in gates.values()) if gates else False
    transition_recommended = all_gates_passed and float(readiness.get("score", 0.0) or 0.0) >= float(
        readiness.get("threshold", 0.80) or 0.80
    )
    readiness_patch = dict(readiness)
    if transition_recommended:
        readiness_patch["transition_recommendation"] = {
            "status": "recommended",
            "to_phase": "researching",
            "step_id": "confirm_start_research",
            "reason": "Clarifying is sufficiently grounded. Pause here and confirm whether we should enter research next.",
        }
    else:
        readiness_patch["transition_recommendation"] = None
    return {
        "phase": "clarifying",
        "active_step": "confirm-transition" if transition_recommended else "write-requirement",
        "pending_user_decision": "confirm-start-research" if transition_recommended else "scope-confirmation",
        "next_recommended_step": {
            "id": "confirm_start_research" if transition_recommended else "continue_clarifying",
            "reason": (
                "Clarifying is sufficiently grounded. Pause here and confirm whether we should enter research next."
                if transition_recommended
                else "Continue clarifying the open questions before entering research."
            ),
        },
        "readiness": readiness_patch,
    }


def _research_transition_from_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
    gates = readiness.get("gates", {}) if isinstance(readiness.get("gates"), dict) else {}
    ready_for_prd = bool(gates.get("ready_for_prd", False))
    return {
        "phase": "researching",
        "active_step": "do-research",
        "pending_user_decision": None,
        "next_recommended_step": {
            "id": "write_prd" if ready_for_prd else "continue_research",
            "reason": (
                "Research readiness is strong enough to move into PRD drafting."
                if ready_for_prd
                else "Continue reviewing research evidence and update readiness when enough signal is available."
            ),
        },
        "readiness": readiness,
    }


def cmd_clarify(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    payload = _status_payload(data_dir, workspace=args.workspace)
    readiness = payload.get("readiness", {}) if isinstance(payload.get("readiness"), dict) else {}
    if payload.get("phase") != "clarifying":
        raise SystemExit("clarify is only available while the workspace is in clarifying readiness phase")

    if args.subcommand == "status":
        transition = readiness.get("transition_recommendation", {}) if isinstance(readiness.get("transition_recommendation"), dict) else {}
        response = {
            "workspace": payload.get("workspace"),
            "project": payload.get("project"),
            "phase": payload.get("phase"),
            "transition_recommendation": transition or None,
            "phase_status_command": _phase_status_command(
                phase=payload.get("phase"),
                workspace=payload.get("workspace"),
                project=payload.get("project"),
                active_step=payload.get("active_step"),
                pending_user_decision=payload.get("pending_user_decision"),
            ),
            "readiness": readiness,
        }
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase=response.get("phase"),
                    guided_view="clarify-status",
                    readiness=readiness,
                    next_step=payload.get("next_recommended_step") if isinstance(payload.get("next_recommended_step"), dict) else None,
                    pending_user_decision=payload.get("pending_user_decision"),
                    route_reason=None,
                    detail_lines=[
                        f"- workspace: {response.get('workspace')}",
                        f"- project: {response.get('project')}",
                        f"- phase_status_command: {response.get('phase_status_command')}",
                        f"- blocking_gates: {json.dumps(readiness.get('gates', {}), ensure_ascii=False, sort_keys=True)}",
                        *( [f"- transition_to: {transition.get('to_phase')}", f"- transition_reason: {transition.get('reason')}"] if transition else [] ),
                    ],
                )
            )
        return 0

    if args.subcommand == "answer":
        log_path = _append_clarifying_note(
            data_dir,
            payload["workspace"],
            answer=args.answer,
        )
        state = sync_current_state(
            data_dir,
            payload["workspace"],
            patch={
                "phase": "clarifying",
                "active_step": "write-requirement",
                "next_recommended_step": {
                    "id": "continue_clarifying",
                    "reason": "Review the latest answer and update clarifying scores via pmagent clarify set-scores.",
                },
            },
            updated_by="clarify-answer",
        )
        response = {
            "workspace": payload["workspace"],
            "logged_to": str(log_path.relative_to(data_dir)).replace("\\", "/"),
            "readiness": state.get("readiness"),
            "pending_user_decision": state.get("pending_user_decision"),
            "next_recommended_step": state.get("next_recommended_step"),
        }
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase="clarifying",
                    guided_view="clarify-answer",
                    readiness=response.get("readiness") if isinstance(response.get("readiness"), dict) else None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=response.get("pending_user_decision"),
                    route_reason=None,
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- logged_to: {response['logged_to']}",
                        "- scoring_update: pending external agent review",
                    ],
                )
            )
        return 0

    if args.subcommand == "set-scores":
        patch_payload = _load_scores_patch(args.patch_file)
        dimensions = _validated_dimensions(patch_payload)
        gates = _validated_gates(patch_payload)
        next_readiness = dict(readiness)
        next_readiness["phase"] = "clarifying"
        next_readiness["dimensions"] = dimensions
        if gates:
            next_readiness["gates"] = gates
        if "score" not in patch_payload:
            values = [float(value) for key, value in dimensions.items() if key not in {"non_goals", "decision_boundaries"}]
            next_readiness["score"] = round(sum(values) / len(values), 2) if values else 0.0
        else:
            next_readiness["score"] = round(float(patch_payload["score"]), 2)
        next_readiness["threshold"] = float(next_readiness.get("threshold", 0.80) or 0.80)
        blocking = sorted(key for key, value in (next_readiness.get("gates", {}) or {}).items() if not value)
        next_readiness["blocking_gates"] = blocking
        next_readiness["summary"] = str(
            patch_payload.get("summary")
            or next_readiness.get("summary")
            or "Clarifying scores updated by external agent assessment."
        )
        next_readiness["ready"] = bool(next_readiness.get("score", 0.0) >= next_readiness.get("threshold", 0.80) and not blocking)
        patch = _clarifying_transition_from_readiness(next_readiness)
        state = sync_current_state(data_dir, payload["workspace"], patch=patch, updated_by="clarify-set-scores")
        response = {
            "workspace": payload["workspace"],
            "readiness": state.get("readiness"),
            "pending_user_decision": state.get("pending_user_decision"),
            "next_recommended_step": state.get("next_recommended_step"),
            "reason": patch_payload.get("reason"),
            "evidence_refs": patch_payload.get("evidence_refs", []),
        }
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase="clarifying",
                    guided_view="clarify-set-scores",
                    readiness=response.get("readiness") if isinstance(response.get("readiness"), dict) else None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=response.get("pending_user_decision"),
                    route_reason=None,
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- reason: {response.get('reason')}",
                        f"- evidence_refs: {json.dumps(response.get('evidence_refs', []), ensure_ascii=False)}",
                    ],
                )
            )
        return 0

    raise SystemExit(f"unsupported clarify subcommand: {args.subcommand}")


def _append_research_note(
    data_dir: Path,
    workspace: str,
    *,
    title: str,
    summary: str,
    source: str | None,
) -> Path:
    research_root = _workspace_root(data_dir, workspace) / "research"
    research_root.mkdir(parents=True, exist_ok=True)
    log_path = research_root / "research-log.md"
    lines = [
        f"## {date.today().isoformat()} | {title}",
        "",
        f"- source: {source or 'unspecified'}",
        "",
        summary.strip(),
        "",
    ]
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return log_path


def cmd_research(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    payload = _status_payload(data_dir, workspace=args.workspace)

    if args.subcommand == "status":
        if payload.get("phase") != "researching":
            payload = preview_current_state(
                data_dir,
                payload["workspace"],
                patch={"phase": "researching", "active_step": "do-research"},
            )
            payload["project"] = _infer_project_for_workspace(data_dir, payload["workspace"]) or payload.get("project")
            payload["preview"] = True
        response = {
            "workspace": payload.get("workspace"),
            "project": payload.get("project"),
            "phase": payload.get("phase"),
            "active_step": payload.get("active_step"),
            "preview": bool(payload.get("preview", False)),
            "phase_status_command": _phase_status_command(
                phase=payload.get("phase"),
                workspace=payload.get("workspace"),
                project=payload.get("project"),
                active_step=payload.get("active_step"),
                pending_user_decision=payload.get("pending_user_decision"),
            ),
            "readiness": payload.get("readiness"),
            "next_recommended_step": payload.get("next_recommended_step"),
        }
        if response["preview"]:
            response["start_command"] = f"pmagent research start --workspace {payload.get('workspace')} --json"
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            readiness = response.get("readiness", {}) if isinstance(response.get("readiness"), dict) else {}
            start_command = response.get("start_command")
            print(
                build_guided_output(
                    mode=None,
                    phase=response.get("phase"),
                    guided_view="research-status",
                    readiness=readiness,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=payload.get("pending_user_decision"),
                    route_reason=None,
                    detail_lines=[
                        f"- workspace: {response.get('workspace')}",
                        f"- project: {response.get('project')}",
                        f"- active_step: {response.get('active_step')}",
                        f"- preview: {response.get('preview')}",
                        f"- phase_status_command: {response.get('phase_status_command')}",
                        *([f"- start_command: {start_command}"] if start_command else []),
                    ],
                )
            )
        return 0

    if args.subcommand == "start":
        workspace = str(payload.get("workspace"))
        if payload.get("phase") == "researching":
            state = payload
            status = "already-researching"
        else:
            readiness = payload.get("readiness", {}) if isinstance(payload.get("readiness"), dict) else {}
            transition = (
                readiness.get("transition_recommendation", {})
                if isinstance(readiness.get("transition_recommendation"), dict)
                else {}
            )
            next_step = payload.get("next_recommended_step", {}) if isinstance(payload.get("next_recommended_step"), dict) else {}
            can_start = (
                payload.get("phase") == "clarifying"
                and (
                    payload.get("pending_user_decision") == "confirm-start-research"
                    or transition.get("to_phase") == "researching"
                    or next_step.get("id") == "confirm_start_research"
                )
            )
            if not can_start:
                raise SystemExit(
                    "research start requires a clarifying workspace with pending confirm-start-research; "
                    "run `pmagent clarify status --json` first"
                )
            state = sync_current_state(
                data_dir,
                workspace,
                patch={
                    "phase": "researching",
                    "active_step": "do-research",
                    "pending_user_decision": None,
                    "next_recommended_step": {
                        "id": "continue_research",
                        "reason": "Research has started; gather evidence, log notes explicitly, and update research scores when enough signal is available.",
                    },
                },
                updated_by="research-start",
            )
            status = "started"
        response = {
            "workspace": workspace,
            "project": state.get("project"),
            "status": status,
            "phase": state.get("phase"),
            "active_step": state.get("active_step"),
            "pending_user_decision": state.get("pending_user_decision"),
            "readiness": state.get("readiness"),
            "next_recommended_step": state.get("next_recommended_step"),
            "phase_status_command": _phase_status_command(
                phase=state.get("phase"),
                workspace=workspace,
                project=state.get("project"),
                active_step=state.get("active_step"),
                pending_user_decision=state.get("pending_user_decision"),
            ),
        }
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase="researching",
                    guided_view="research-start",
                    readiness=response.get("readiness") if isinstance(response.get("readiness"), dict) else None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=state.get("pending_user_decision"),
                    route_reason=None,
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- status: {response['status']}",
                        f"- phase_status_command: {response['phase_status_command']}",
                    ],
                )
            )
        return 0

    if args.subcommand == "note":
        title = args.title or "Research note"
        note_path = _append_research_note(
            data_dir,
            payload["workspace"],
            title=title,
            summary=args.summary,
            source=args.source,
        )
        state = sync_current_state(
            data_dir,
            payload["workspace"],
            patch={
                "phase": "researching",
                "active_step": "do-research",
                "pending_user_decision": None,
                "next_recommended_step": {
                    "id": "continue_research",
                    "reason": "Review the latest research note and update research scores via pmagent research set-scores.",
                },
            },
            updated_by="research-note",
        )
        response = {
            "workspace": payload["workspace"],
            "logged_to": str(note_path.relative_to(data_dir)).replace("\\", "/"),
            "readiness": state.get("readiness"),
            "next_recommended_step": state.get("next_recommended_step"),
        }
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase="researching",
                    guided_view="research-note",
                    readiness=response.get("readiness") if isinstance(response.get("readiness"), dict) else None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=state.get("pending_user_decision"),
                    route_reason=None,
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- logged_to: {response['logged_to']}",
                        "- scoring_update: pending external agent review",
                    ],
                )
            )
        return 0

    if args.subcommand == "set-scores":
        patch_payload = _load_scores_patch(args.patch_file)
        dimensions = _validated_dimensions(patch_payload)
        gates = _validated_gates(patch_payload)
        next_readiness = dict(payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {})
        next_readiness["phase"] = "researching"
        next_readiness["dimensions"] = dimensions
        if gates:
            next_readiness["gates"] = gates
        if "score" not in patch_payload:
            gate_values = [bool(value) for value in (next_readiness.get("gates", {}) or {}).values()]
            next_readiness["score"] = round(sum(1 for value in gate_values if value) / len(gate_values), 2) if gate_values else 0.0
        else:
            next_readiness["score"] = round(float(patch_payload["score"]), 2)
        next_readiness["threshold"] = float(next_readiness.get("threshold", 0.80) or 0.80)
        blocking = sorted(key for key, value in (next_readiness.get("gates", {}) or {}).items() if not value)
        next_readiness["blocking_gates"] = blocking
        next_readiness["summary"] = str(
            patch_payload.get("summary")
            or next_readiness.get("summary")
            or "Research scores updated by external agent assessment."
        )
        next_readiness["ready"] = bool(next_readiness.get("score", 0.0) >= next_readiness.get("threshold", 0.80) and not blocking)
        patch = _research_transition_from_readiness(next_readiness)
        state = sync_current_state(data_dir, payload["workspace"], patch=patch, updated_by="research-set-scores")
        response = {
            "workspace": payload["workspace"],
            "readiness": state.get("readiness"),
            "next_recommended_step": state.get("next_recommended_step"),
            "reason": patch_payload.get("reason"),
            "evidence_refs": patch_payload.get("evidence_refs", []),
        }
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase="researching",
                    guided_view="research-set-scores",
                    readiness=response.get("readiness") if isinstance(response.get("readiness"), dict) else None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=payload.get("pending_user_decision"),
                    route_reason=None,
                    detail_lines=[
                        f"- workspace: {response['workspace']}",
                        f"- reason: {response.get('reason')}",
                        f"- evidence_refs: {json.dumps(response.get('evidence_refs', []), ensure_ascii=False)}",
                    ],
                )
            )
        return 0

    raise SystemExit(f"unsupported research subcommand: {args.subcommand}")
