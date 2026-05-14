from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from .current_state import preview_current_state
from .presentation import build_guided_output
from .paths import resolve_data_dir
from .cli_helpers import _infer_project_for_workspace, _load_projects_config, _resolve_workspace_context
from .cli_workspace import _do_switch, _normalize_workspace_name, _workspace_root, cmd_workspace_init

def _status_payload(data_dir: Path, *, workspace: str | None = None) -> dict:
    project, resolved_workspace = _resolve_workspace_context(data_dir, workspace=workspace)
    state = preview_current_state(data_dir, resolved_workspace)
    state["project"] = project or state.get("project")
    return state


def _guided_envelope(route_context: dict, *, guided_view: str, payload: dict) -> dict:
    return {
        "workspace": route_context.get("workspace"),
        "project": route_context.get("project"),
        "navigation_state": route_context.get("navigation_state"),
        "recommended_skills": route_context.get("recommended_skills", []),
        "handoff_hint": route_context.get("handoff_hint"),
        "route_reason": route_context.get("route_reason"),
        "phase": route_context.get("phase"),
        "guided_view": guided_view,
        "next_recommended_step": route_context.get("next_recommended_step"),
        "suggested_command": route_context.get("suggested_command"),
        "phase_status_command": route_context.get("phase_status_command"),
        "payload": payload,
    }


def _guided_envelope_override(
    route_context: dict,
    *,
    guided_view: str,
    payload: dict,
    route_reason: str,
    suggested_command: str | None,
    next_recommended_step: dict | None = None,
) -> dict:
    return {
        "workspace": route_context.get("workspace"),
        "project": route_context.get("project"),
        "navigation_state": route_context.get("navigation_state"),
        "recommended_skills": route_context.get("recommended_skills", []),
        "handoff_hint": route_context.get("handoff_hint"),
        "route_reason": route_reason,
        "phase": route_context.get("phase"),
        "guided_view": guided_view,
        "next_recommended_step": next_recommended_step if next_recommended_step is not None else route_context.get("next_recommended_step"),
        "suggested_command": suggested_command,
        "phase_status_command": route_context.get("phase_status_command"),
        "payload": payload,
    }


def _route_payload(data_dir: Path, *, workspace: str | None = None, project: str | None = None) -> dict:
    config = _load_projects_config(data_dir)
    resolved_workspace = workspace or str(config.get("active_workspace") or "").strip() or None
    inferred_project = project or (_infer_project_for_workspace(data_dir, resolved_workspace) if resolved_workspace else None) or str(config.get("active_project") or "").strip() or None
    if not resolved_workspace or not _workspace_root(data_dir, resolved_workspace).exists():
        target_project = inferred_project or "<project>"
        target_workspace = resolved_workspace or (f"{target_project}-discovery" if target_project != "<project>" else "<workspace>")
        return {
            "workspace": resolved_workspace,
            "project": inferred_project,
            "navigation_state": "setup",
            "recommended_skills": [
                {
                    "id": "workspace-init",
                    "skill_path": "pmagent://workspace-init",
                    "reason": "Create and select a PM Data workspace before running workflow skills.",
                    "command": f"pmagent workspace-init --project {target_project} --workspace {target_workspace}",
                }
            ],
            "handoff_hint": _handoff_hint_for_next_step("workspace_init"),
            "route_reason": "No initialized active workspace was found; bootstrap a workspace before continuing the PM workflow.",
            "phase": None,
            "active_step": None,
            "pending_user_decision": None,
            "next_recommended_step": {
                "id": "workspace_init",
                "reason": "Create and select a workspace so the guided workflow has a stateful starting point.",
            },
            "suggested_command": f"pmagent workspace-init --project {target_project} --workspace {target_workspace}",
            "phase_status_command": None,
            "readiness": {},
        }

    payload = _status_payload(data_dir, workspace=resolved_workspace)
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    requirement = artifacts.get("requirement", {}) if isinstance(artifacts, dict) else {}
    prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
    route_reason = (
        "Use artifact state, readiness, inbox, and recommended skills to choose the next PM workflow action."
        if bool(requirement.get("exists")) or str(prd.get("status")) in {"draft", "active", "maintained"}
        else "No persisted workspace context was found beyond the scaffold; start by clarifying the requirement."
    )
    next_step = payload.get("next_recommended_step", {}) if isinstance(payload.get("next_recommended_step"), dict) else {}
    suggested_command = _command_for_next_step(next_step.get("id"), payload.get("workspace"))
    return {
        "workspace": payload.get("workspace"),
        "project": payload.get("project"),
        "navigation_state": "ready",
        "recommended_skills": payload.get("recommended_skills", []),
        "handoff_hint": _handoff_hint_for_next_step(next_step.get("id")),
        "route_reason": route_reason,
        "phase": payload.get("phase"),
        "active_step": payload.get("active_step"),
        "pending_user_decision": payload.get("pending_user_decision"),
        "next_recommended_step": next_step,
        "suggested_command": suggested_command,
        "phase_status_command": _phase_status_command(
            phase=payload.get("phase"),
            workspace=payload.get("workspace"),
            project=payload.get("project"),
            active_step=payload.get("active_step"),
            pending_user_decision=payload.get("pending_user_decision"),
        ),
        "readiness": payload.get("readiness"),
    }


def _command_for_next_step(step_id: object, workspace: object) -> str:
    workspace_name = str(workspace or "<workspace>")
    step = str(step_id or "")
    if step.startswith("clarify_") or step == "continue_clarifying":
        return "pmagent clarify status"
    if step in {"confirm_start_research", "start_research"}:
        return f"pmagent research start --workspace {workspace_name} --json"
    if step in {"continue_research", "write_strategy"}:
        return "pmagent research status"
    if step == "write_prd":
        return "pmagent prd status"
    if step == "review_candidates":
        return f"pmagent observe review --workspace {workspace_name}"
    if step in {"observe_audit", "observe_run"}:
        return f"pmagent observe audit --workspace {workspace_name} --run-catch-up --json"
    if step in {"draft_maintenance", "apply_maintenance"}:
        return f"pmagent observe maintenance-status --workspace {workspace_name}"
    if step in {"confirm_observation_policy", "confirm_observation_cadence"}:
        return f"pmagent observe status --workspace {workspace_name} --json"
    return "pmagent status"


def _phase_status_command(
    *,
    phase: object,
    workspace: object,
    project: object = None,
    active_step: object = None,
    pending_user_decision: object = None,
) -> str:
    workspace_name = str(workspace or "<workspace>")
    project_name = str(project or "<project>")
    current_phase = str(phase or "")
    current_step = str(active_step or "")
    pending = str(pending_user_decision or "")
    if pending == "candidate-review" or current_step == "candidate-review":
        return f"pmagent observe review --workspace {workspace_name} --json"
    if current_phase == "clarifying":
        return f"pmagent clarify status --workspace {workspace_name} --json"
    if current_phase == "researching":
        return f"pmagent research status --workspace {workspace_name} --json"
    if current_phase == "delivery":
        return f"pmagent prd status --workspace {workspace_name} --json"
    if current_phase == "dev-readiness":
        return f"pmagent dev slices --workspace {workspace_name} --json"
    if current_phase == "maintaining":
        return f"pmagent observe maintenance-status --workspace {workspace_name} --json"
    if current_phase == "observing":
        return f"pmagent observe status --project {project_name} --workspace {workspace_name} --json"
    return f"pmagent status --workspace {workspace_name} --json"


def _handoff_hint_for_next_step(step_id: object) -> str | None:
    step = str(step_id or "")
    if step == "workspace_init":
        return "setup -> workspace-init"
    if step == "confirm_start_research":
        return "clarifying -> research (confirm first)"
    if step.startswith("clarify_") or step in {"start_research", "continue_clarifying"}:
        return "clarifying -> research"
    if step in {"continue_research", "write_strategy"}:
        return "research -> strategy"
    if step == "write_prd":
        return "research -> PRD"
    if step in {"challenge_prd", "export_workspace"}:
        return "PRD -> challenge/export"
    if step in {"review_candidates", "observe_run", "observe_audit"}:
        return "observation -> review"
    if step in {"draft_maintenance", "apply_maintenance"}:
        return "candidate-review -> maintenance"
    if step in {"confirm_observation_policy", "confirm_observation_cadence"}:
        return "observation policy -> confirmation"
    return None


def _emit_route_fallback(route_payload: dict, *, guided_view: str, as_json: bool) -> int:
    if as_json:
        payload = {"route": route_payload} if guided_view == "route" else route_payload
        print(json.dumps(_guided_envelope(route_payload, guided_view=guided_view, payload=payload), ensure_ascii=False, indent=2))
        return 0
    print(f"navigation_state={route_payload.get('navigation_state')}")
    print(f"handoff_hint={route_payload.get('handoff_hint')}")
    print(f"route_reason={route_payload.get('route_reason')}")
    print(f"phase_status_command={route_payload.get('phase_status_command')}")
    next_step = route_payload.get("next_recommended_step", {}) if isinstance(route_payload.get("next_recommended_step"), dict) else {}
    print(f"next_step={next_step.get('id')}")
    print(f"next_step_reason={next_step.get('reason')}")
    print(f"suggested_command={route_payload.get('suggested_command')}")
    skills = route_payload.get("recommended_skills", [])
    if isinstance(skills, list) and skills:
        print("recommended_skills=" + ", ".join(str(item.get("id")) for item in skills if isinstance(item, dict)))
    return 0


def _detail_lines_for_status(payload: dict, route_context: dict) -> list[str]:
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
    observation = payload.get("observation", {}) if isinstance(payload.get("observation"), dict) else {}
    queue = observation.get("queue", {}) if isinstance(observation.get("queue"), dict) else {}
    debates = payload.get("debates", {}) if isinstance(payload.get("debates"), dict) else {}
    debate_review = payload.get("debate_review", {}) if isinstance(payload.get("debate_review"), dict) else {}
    return [
        f"- workspace: {_string_or_dash(payload.get('workspace'))}",
        f"- project: {_string_or_dash(payload.get('project'))}",
        f"- active_step: {_string_or_dash(payload.get('active_step'))}",
        f"- recommended_skills: {_string_or_dash([item.get('id') for item in route_context.get('recommended_skills', []) if isinstance(item, dict)])}",
        f"- handoff_hint: {_string_or_dash(route_context.get('handoff_hint'))}",
        f"- phase_status_command: {_string_or_dash(route_context.get('phase_status_command'))}",
        f"- suggested_command: {_string_or_dash(route_context.get('suggested_command'))}",
        f"- prd_status: {_string_or_dash(prd.get('status'))}",
        f"- prd_canonical_path: {_string_or_dash(prd.get('canonical_path'))}",
        f"- observation_enabled: {_string_or_dash(observation.get('enabled'))}",
        f"- observation_cadence: {_string_or_dash(observation.get('cadence'))}",
        f"- observation_needs_review: {_string_or_dash(observation.get('needs_review'))}",
        f"- queue_counts: {_string_or_dash(queue)}",
        f"- debate_active_count: {_string_or_dash(debates.get('active_count'))}",
        f"- debate_completed_awaiting_review_count: {_string_or_dash(debates.get('completed_awaiting_review_count'))}",
        f"- debate_failed_count: {_string_or_dash(debates.get('failed_count'))}",
        f"- debate_latest_topic: {_string_or_dash(debates.get('latest_topic'))}",
        f"- debate_latest_failed_topic: {_string_or_dash(debates.get('latest_failed_topic'))}",
        f"- debate_review_topics: {_string_or_dash(debate_review.get('awaiting_review_topics'))}",
    ]


def _detail_lines_for_route_summary(response: dict) -> list[str]:
    return [
        f"- workspace: {_string_or_dash(response.get('workspace'))}",
        f"- project: {_string_or_dash(response.get('project'))}",
        f"- recommended_skills: {_string_or_dash(response.get('recommended_skills'))}",
        f"- handoff_hint: {_string_or_dash(response.get('handoff_hint'))}",
        f"- phase_status_command: {_string_or_dash(response.get('phase_status_command'))}",
        f"- suggested_command: {_string_or_dash(response.get('suggested_command'))}",
    ]


def _observation_checkpoint_payload(data_dir: Path, payload: dict) -> dict | None:
    workspace = str(payload.get("workspace") or "")
    project = str(payload.get("project") or "")
    if not workspace or not project:
        return None
    from .observation.executor import build_observation_status_payload

    observation_payload = build_observation_status_payload(data_dir, project, workspace=workspace)
    checkpoint = observation_payload.get("decision_checkpoint")
    return observation_payload if isinstance(checkpoint, dict) and checkpoint else None


def _debate_review_payload(payload: dict) -> dict | None:
    debate_review = payload.get("debate_review", {}) if isinstance(payload.get("debate_review"), dict) else {}
    topics = debate_review.get("awaiting_review_topics")
    if not isinstance(topics, list):
        topics = []
    topics = [str(item) for item in topics if str(item).strip()]
    if not topics:
        return None
    workspace = str(payload.get("workspace") or "")
    first_topic = topics[0]
    return {
        "workspace": workspace,
        "count": len(topics),
        "topics": topics,
        "recommended_command": f"pmagent debate review --workspace {workspace} --topic {first_topic}",
    }


def _debate_failed_payload(payload: dict) -> dict | None:
    debates = payload.get("debates", {}) if isinstance(payload.get("debates"), dict) else {}
    topics = debates.get("failed_topics")
    if not isinstance(topics, list):
        topics = []
    topics = [str(item) for item in topics if str(item).strip()]
    if not topics:
        return None
    workspace = str(payload.get("workspace") or "")
    first_topic = topics[0]
    return {
        "workspace": workspace,
        "count": len(topics),
        "topics": topics,
        "recommended_command": f"pmagent debate status --workspace {workspace} --topic {first_topic}",
    }


def _debate_launch_payload(payload: dict) -> dict | None:
    launch = payload.get("debate_launch", {}) if isinstance(payload.get("debate_launch"), dict) else {}
    if not bool(launch.get("active")):
        return None
    workspace = str(payload.get("workspace") or "")
    thesis = str(launch.get("thesis") or "").strip()
    axis = str(launch.get("axis") or "").strip()
    topic_slug = str(launch.get("topic_slug") or "").strip()
    reason = str(launch.get("reason") or "").strip() or "debate executor precheck previously failed"
    command_parts = [f"pmagent debate start --workspace {workspace}"]
    if thesis:
        command_parts.append(f'--thesis "{thesis}"')
    if axis:
        command_parts.append(f'--axis "{axis}"')
    if topic_slug:
        command_parts.append(f"--topic-slug {topic_slug}")
    return {
        "workspace": workspace,
        "thesis": thesis,
        "axis": axis,
        "topic_slug": topic_slug,
        "reason": reason,
        "config_path": launch.get("config_path"),
        "recommended_command": " ".join(command_parts),
    }


def _observation_detail_lines(observation_payload: dict) -> list[str]:
    checkpoint = observation_payload.get("decision_checkpoint", {}) if isinstance(observation_payload.get("decision_checkpoint"), dict) else {}
    cadence_recommendation = observation_payload.get("cadence_recommendation", {}) if isinstance(observation_payload.get("cadence_recommendation"), dict) else {}
    lines = [
        f"- workspace: {_string_or_dash(observation_payload.get('workspace'))}",
        f"- project: {_string_or_dash(observation_payload.get('project'))}",
        f"- enabled: {_string_or_dash(observation_payload.get('enabled'))}",
        f"- cadence: {_string_or_dash(observation_payload.get('cadence'))}",
        f"- decision_status: {_string_or_dash(observation_payload.get('decision_status'))}",
        f"- last_confirmed_at: {_string_or_dash(observation_payload.get('last_confirmed_at'))}",
        f"- confirmation_source: {_string_or_dash(observation_payload.get('confirmation_source'))}",
    ]
    if checkpoint:
        lines.extend(
            [
                f"- decision_checkpoint: {_string_or_dash(checkpoint.get('checkpoint'))}",
                f"- decision_reason: {_string_or_dash(checkpoint.get('reason'))}",
                f"- decision_prompt: {_string_or_dash(checkpoint.get('prompt'))}",
            ]
        )
        if checkpoint.get("enable_command"):
            lines.append(f"- enable_command: {_string_or_dash(checkpoint.get('enable_command'))}")
        if checkpoint.get("disable_command"):
            lines.append(f"- disable_command: {_string_or_dash(checkpoint.get('disable_command'))}")
        if checkpoint.get("set_cadence_command"):
            lines.append(f"- set_cadence_command: {_string_or_dash(checkpoint.get('set_cadence_command'))}")
    suggestion = cadence_recommendation.get("suggested_cadence")
    if suggestion:
        lines.extend(
            [
                f"- cadence_recommendation: {_string_or_dash(suggestion)}",
                f"- cadence_reason: {_string_or_dash(cadence_recommendation.get('reason'))}",
            ]
        )
    return lines


def _string_or_dash(value: object) -> str:
    return "—" if value is None else str(value)


def cmd_status(args: argparse.Namespace) -> int:
    if getattr(args, "next_only", False):
        return cmd_next(argparse.Namespace(data_dir=args.data_dir, workspace=args.workspace, json=args.json))
    if getattr(args, "detail", False):
        return cmd_review(argparse.Namespace(data_dir=args.data_dir, workspace=args.workspace, json=args.json))
    data_dir = resolve_data_dir(args.data_dir)
    try:
        payload = _status_payload(data_dir, workspace=args.workspace)
    except SystemExit:
        route_payload = _route_payload(data_dir, workspace=args.workspace)
        return _emit_route_fallback(route_payload, guided_view="route", as_json=args.json)
    route_context = _route_payload(data_dir, workspace=payload.get("workspace"), project=payload.get("project"))
    if args.json:
        print(json.dumps(_guided_envelope(route_context, guided_view="status", payload=payload), ensure_ascii=False, indent=2))
    else:
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="status",
                readiness=payload.get("readiness") if isinstance(payload.get("readiness"), dict) else None,
                next_step=payload.get("next_recommended_step") if isinstance(payload.get("next_recommended_step"), dict) else None,
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason=route_context.get("route_reason"),
                detail_lines=_detail_lines_for_status(payload, route_context),
            )
        )
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    payload = _route_payload(data_dir, workspace=args.workspace, project=getattr(args, "project", None))
    if args.json:
        print(json.dumps(_guided_envelope(payload, guided_view="route", payload={"route": payload}), ensure_ascii=False, indent=2))
    else:
        print(f"workspace={payload.get('workspace')}")
        print(f"project={payload.get('project')}")
        print(f"navigation_state={payload.get('navigation_state')}")
        print(f"handoff_hint={payload.get('handoff_hint')}")
        print(f"route_reason={payload.get('route_reason')}")
        print(f"phase={payload.get('phase')}")
        print(f"phase_status_command={payload.get('phase_status_command')}")
        print(f"suggested_command={payload.get('suggested_command')}")
        skills = payload.get("recommended_skills", [])
        if isinstance(skills, list) and skills:
            print("recommended_skills=" + ", ".join(str(item.get("id")) for item in skills if isinstance(item, dict)))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    if args.project:
        workspace = _normalize_workspace_name(args.project, args.workspace)
        if not _workspace_root(data_dir, workspace).exists():
            init_args = argparse.Namespace(
                data_dir=str(data_dir),
                project=args.project,
                workspace=workspace,
                description=args.description,
                requirement_summary=args.requirement_summary,
                priority="P1",
                status="drafting",
                keywords=[],
                observation_cadence=args.observation_cadence,
                enable_observation=args.enable_observation,
                confirm_cadence=args.confirm_cadence,
            )
            if args.json:
                with contextlib.redirect_stdout(io.StringIO()):
                    cmd_workspace_init(init_args)
            else:
                cmd_workspace_init(init_args)
        else:
            _do_switch(data_dir, args.project, workspace)
    else:
        workspace = args.workspace
    payload = _route_payload(data_dir, workspace=workspace, project=args.project)
    readiness = payload.get("readiness", {}) if isinstance(payload.get("readiness"), dict) else {}
    next_step = payload.get("next_recommended_step", {}) if isinstance(payload.get("next_recommended_step"), dict) else {}
    if payload.get("navigation_state") == "setup":
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"navigation_state={payload.get('navigation_state')}")
            print(f"handoff_hint={payload.get('handoff_hint')}")
            print(f"route_reason={payload.get('route_reason')}")
            print(f"next_step={next_step.get('id')}")
            print(f"next_step_reason={next_step.get('reason')}")
            print(f"suggested_command={payload.get('suggested_command')}")
        return 0
    status_payload = _status_payload(data_dir, workspace=payload.get("workspace"))
    observation = status_payload.get("observation", {}) if isinstance(status_payload, dict) else {}
    tracking = status_payload.get("observation_tracking", {}) if isinstance(status_payload.get("observation_tracking"), dict) else {}
    pending_observations = tracking.get("pending_observation_ids", []) if isinstance(tracking, dict) else []
    inbox_count = len(pending_observations)
    phase = payload.get("phase")
    active_step = payload.get("active_step")
    pending_decision = payload.get("pending_user_decision")
    observation_checkpoint = _observation_checkpoint_payload(data_dir, payload)
    debate_failed_payload = _debate_failed_payload(status_payload)
    debate_review_payload = _debate_review_payload(status_payload)
    debate_launch_payload = _debate_launch_payload(status_payload)
    if args.json:
        view_payload = None
        if debate_failed_payload:
            response = _guided_envelope_override(
                payload,
                guided_view="debate-failure",
                payload=debate_failed_payload,
                route_reason="A debate run failed and should be inspected before normal workflow continues.",
                suggested_command=debate_failed_payload.get("recommended_command"),
                next_recommended_step={"id": "debate_failure", "reason": "Inspect the failed debate run before continuing."},
            )
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        if debate_review_payload:
            response = _guided_envelope_override(
                payload,
                guided_view="debate-review",
                payload=debate_review_payload,
                route_reason="A debate synthesis is awaiting review before canonical updates should continue.",
                suggested_command=debate_review_payload.get("recommended_command"),
                next_recommended_step={"id": "debate_review", "reason": "Review pending debate synthesis before continuing canonical work."},
            )
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        if debate_launch_payload:
            response = _guided_envelope_override(
                payload,
                guided_view="debate-launch",
                payload=debate_launch_payload,
                route_reason="A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                suggested_command=debate_launch_payload.get("recommended_command"),
                next_recommended_step={"id": "debate_launch", "reason": "Resume the previously blocked debate launch after fixing executor configuration."},
            )
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        if pending_decision == "candidate-review" or inbox_count > 0:
            from .observation.executor import build_review_payload

            view_payload = {"payload": build_review_payload(data_dir, str(payload.get("workspace")))}
        elif observation_checkpoint:
            view_payload = {"payload": observation_checkpoint}
        elif phase == "maintaining" or pending_decision == "prd-approval" or next_step.get("id") in {"draft_maintenance", "apply_maintenance"}:
            from .observation.executor import build_maintenance_status_payload

            view_payload = {"payload": build_maintenance_status_payload(data_dir, str(payload.get("workspace")))}
        elif phase == "clarifying":
            status_payload = _status_payload(data_dir, workspace=payload.get("workspace"))
            view_payload = {
                "payload": {
                    "workspace": status_payload.get("workspace"),
                    "project": status_payload.get("project"),
                    "phase": status_payload.get("phase"),
                    "readiness": readiness,
                    },
                }
        elif phase == "researching":
            if next_step.get("id") == "write_prd":
                status_payload = _status_payload(data_dir, workspace=payload.get("workspace"))
                view_payload = {
                    "payload": {
                        "workspace": status_payload.get("workspace"),
                        "project": status_payload.get("project"),
                        "phase": status_payload.get("phase"),
                        "prd_status": status_payload.get("artifacts", {}).get("prd", {}).get("status") if isinstance(status_payload.get("artifacts"), dict) else None,
                        "prd_canonical_path": status_payload.get("artifacts", {}).get("prd", {}).get("canonical_path") if isinstance(status_payload.get("artifacts"), dict) else None,
                        "readiness": readiness,
                        "next_recommended_step": next_step,
                    },
                }
            else:
                status_payload = _status_payload(data_dir, workspace=payload.get("workspace"))
                view_payload = {
                    "payload": {
                        "workspace": status_payload.get("workspace"),
                        "project": status_payload.get("project"),
                        "phase": status_payload.get("phase"),
                        "active_step": status_payload.get("active_step"),
                        "preview": False,
                        "readiness": readiness,
                        "next_recommended_step": next_step,
                    },
                }
        elif phase == "delivery":
            if next_step.get("id") in {"challenge_prd", "export_workspace", "observe_status"} or active_step in {"write-prd", "challenge-prd"}:
                from io import StringIO
                buffer = StringIO()
                from .cli_phases import cmd_prd

                with contextlib.redirect_stdout(buffer):
                    cmd_prd(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=True, subcommand="review"))
                view_payload = {"payload": json.loads(buffer.getvalue())}
            else:
                view_payload = {"payload": _status_payload(data_dir, workspace=payload.get("workspace"))}
        elif active_step == "observe-status" or bool(observation.get("enabled")):
            from .observation.executor import build_observation_status_payload

            view_payload = {"payload": build_observation_status_payload(data_dir, str(payload.get("workspace")))}
        else:
            view_payload = {"payload": _status_payload(data_dir, workspace=payload.get("workspace"))}

        if pending_decision == "candidate-review" or inbox_count > 0:
            guided_view = "observe-review"
        elif observation_checkpoint:
            guided_view = "observe-status"
        elif phase == "maintaining" or pending_decision == "prd-approval" or next_step.get("id") in {"draft_maintenance", "apply_maintenance"}:
            guided_view = "maintenance-status"
        elif phase == "clarifying":
            guided_view = "clarify-status"
        elif phase == "researching" and next_step.get("id") == "write_prd":
            guided_view = "prd-status"
        elif phase == "researching":
            guided_view = "research-status"
        elif phase == "delivery":
            guided_view = "prd-review"
        elif active_step == "observe-status" or bool(observation.get("enabled")):
            guided_view = "observe-status"
        else:
            guided_view = "status"

        print(json.dumps(_guided_envelope(payload, guided_view=guided_view, payload=view_payload["payload"]), ensure_ascii=False, indent=2))
        return 0
    if debate_failed_payload:
        print(
            build_guided_output(
                mode=None,
                phase=status_payload.get("phase"),
                guided_view="debate-failure",
                readiness=None,
                next_step={"id": "debate_failure", "reason": "Inspect the failed debate run before continuing."},
                pending_user_decision=status_payload.get("pending_user_decision"),
                route_reason="A debate run failed and should be inspected before normal workflow continues.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_failed_payload.get('workspace'))}",
                    f"- failed_topics: {_string_or_dash(debate_failed_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_failed_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_review_payload:
        print(
            build_guided_output(
                mode=None,
                phase=status_payload.get("phase"),
                guided_view="debate-review",
                readiness=None,
                next_step={"id": "debate_review", "reason": "Review pending debate synthesis before continuing canonical work."},
                pending_user_decision=status_payload.get("pending_user_decision"),
                route_reason="A debate synthesis is awaiting review before canonical updates should continue.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_review_payload.get('workspace'))}",
                    f"- debate_topics: {_string_or_dash(debate_review_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_review_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_launch_payload:
        print(
            build_guided_output(
                mode=None,
                phase=status_payload.get("phase"),
                guided_view="debate-launch",
                readiness=None,
                next_step={"id": "debate_launch", "reason": "Resume the previously blocked debate launch after fixing executor configuration."},
                pending_user_decision=status_payload.get("pending_user_decision"),
                route_reason="A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_launch_payload.get('workspace'))}",
                    f"- thesis: {_string_or_dash(debate_launch_payload.get('thesis'))}",
                    f"- axis: {_string_or_dash(debate_launch_payload.get('axis'))}",
                    f"- config_path: {_string_or_dash(debate_launch_payload.get('config_path'))}",
                    f"- suggested_command: {_string_or_dash(debate_launch_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if pending_decision == "candidate-review" or inbox_count > 0:
        from .observation.executor import review_candidates

        return review_candidates(data_dir, str(payload.get("workspace")), as_json=False)
    if observation_checkpoint:
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="observe-status",
                readiness=None,
                next_step=payload.get("next_recommended_step") if isinstance(payload.get("next_recommended_step"), dict) else None,
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="Observation policy confirmation is due at this workflow checkpoint.",
                detail_lines=_observation_detail_lines(observation_checkpoint),
            )
        )
        return 0
    if phase == "maintaining" or pending_decision == "prd-approval" or next_step.get("id") in {"draft_maintenance", "apply_maintenance"}:
        from .observation.executor import maintenance_status

        return maintenance_status(data_dir, str(payload.get("workspace")), as_json=False)
    if phase == "clarifying":
        from .cli_phases import cmd_clarify

        return cmd_clarify(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False, subcommand="status"))
    if phase == "researching" and next_step.get("id") == "write_prd":
        from .cli_phases import cmd_prd_status

        return cmd_prd_status(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False))
    if phase == "researching":
        from .cli_phases import cmd_research

        return cmd_research(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False, subcommand="status"))
    if phase == "delivery":
        from .cli_phases import cmd_prd

        return cmd_prd(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False, subcommand="review"))
    if active_step == "observe-status" or bool(observation.get("enabled")):
        from .observation.executor import observation_status

        return observation_status(data_dir, str(payload.get("workspace")), as_json=False)
    return cmd_status(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False))


def cmd_next(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    try:
        payload = _status_payload(data_dir, workspace=args.workspace)
    except SystemExit:
        route_payload = _route_payload(data_dir, workspace=args.workspace)
        response = {
            "workspace": route_payload.get("workspace"),
            "project": route_payload.get("project"),
            "phase": route_payload.get("phase"),
            "pending_user_decision": route_payload.get("pending_user_decision"),
            "next_recommended_step": route_payload.get("next_recommended_step"),
            "recommended_skills": route_payload.get("recommended_skills", []),
            "handoff_hint": route_payload.get("handoff_hint"),
            "suggested_command": route_payload.get("suggested_command"),
            "phase_status_command": route_payload.get("phase_status_command"),
        }
        if args.json:
            print(json.dumps(_guided_envelope(route_payload, guided_view="next", payload=response), ensure_ascii=False, indent=2))
        else:
            print(
                build_guided_output(
                    mode=None,
                    phase=response.get("phase"),
                    guided_view="next",
                    readiness=None,
                    next_step=response.get("next_recommended_step") if isinstance(response.get("next_recommended_step"), dict) else None,
                    pending_user_decision=response.get("pending_user_decision"),
                    route_reason=route_payload.get("route_reason"),
                    detail_lines=_detail_lines_for_route_summary(response),
                )
            )
        return 0
    next_step = payload.get("next_recommended_step", {}) if isinstance(payload.get("next_recommended_step"), dict) else {}
    route_context = _route_payload(data_dir, workspace=payload.get("workspace"), project=payload.get("project"))
    observation_checkpoint = _observation_checkpoint_payload(data_dir, payload)
    debate_failed_payload = _debate_failed_payload(payload)
    debate_review_payload = _debate_review_payload(payload)
    debate_launch_payload = _debate_launch_payload(payload)
    if debate_failed_payload:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "A debate run failed and should be inspected before normal workflow continues.",
                "suggested_command": debate_failed_payload.get("recommended_command"),
                "view": "debate-failure",
                "payload": debate_failed_payload,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-failure",
                readiness=None,
                next_step={"id": "debate_failure", "reason": "Inspect the failed debate run before continuing."},
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="A debate run failed and should be inspected before normal workflow continues.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_failed_payload.get('workspace'))}",
                    f"- failed_topics: {_string_or_dash(debate_failed_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_failed_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_review_payload:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "A debate synthesis is awaiting review before canonical updates should continue.",
                "suggested_command": debate_review_payload.get("recommended_command"),
                "view": "debate-review",
                "payload": debate_review_payload,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-review",
                readiness=None,
                next_step={"id": "debate_review", "reason": "Review pending debate synthesis before continuing canonical work."},
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="A debate synthesis is awaiting review before canonical updates should continue.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_review_payload.get('workspace'))}",
                    f"- debate_topics: {_string_or_dash(debate_review_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_review_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_launch_payload:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                "suggested_command": debate_launch_payload.get("recommended_command"),
                "view": "debate-launch",
                "payload": debate_launch_payload,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-launch",
                readiness=None,
                next_step={"id": "debate_launch", "reason": "Resume the previously blocked debate launch after fixing executor configuration."},
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_launch_payload.get('workspace'))}",
                    f"- thesis: {_string_or_dash(debate_launch_payload.get('thesis'))}",
                    f"- axis: {_string_or_dash(debate_launch_payload.get('axis'))}",
                    f"- config_path: {_string_or_dash(debate_launch_payload.get('config_path'))}",
                    f"- suggested_command: {_string_or_dash(debate_launch_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if observation_checkpoint:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "Observation policy confirmation is due at this workflow checkpoint.",
                "suggested_command": route_context.get("suggested_command"),
                "view": "observe-status",
                "payload": observation_checkpoint,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="observe-status",
                readiness=None,
                next_step=next_step,
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="Observation policy confirmation is due at this workflow checkpoint.",
                detail_lines=_observation_detail_lines(observation_checkpoint),
            )
        )
        return 0
    response = {
        "workspace": payload.get("workspace"),
        "project": payload.get("project"),
        "phase": payload.get("phase"),
        "pending_user_decision": payload.get("pending_user_decision"),
        "next_recommended_step": next_step,
        "recommended_skills": route_context.get("recommended_skills", []),
        "handoff_hint": route_context.get("handoff_hint"),
        "suggested_command": route_context.get("suggested_command"),
        "phase_status_command": route_context.get("phase_status_command"),
    }
    if args.json:
        print(json.dumps(_guided_envelope(route_context, guided_view="next", payload=response), ensure_ascii=False, indent=2))
    else:
        print(
            build_guided_output(
                mode=None,
                phase=response.get("phase"),
                guided_view="next",
                readiness=payload.get("readiness") if isinstance(payload.get("readiness"), dict) else None,
                next_step=next_step,
                pending_user_decision=response.get("pending_user_decision"),
                route_reason=route_context.get("route_reason"),
                detail_lines=_detail_lines_for_route_summary(response),
            )
        )
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    if args.project:
        workspace = _normalize_workspace_name(args.project, args.workspace)
        _do_switch(data_dir, args.project, workspace)
    else:
        workspace = args.workspace
    try:
        payload = _status_payload(data_dir, workspace=workspace)
    except SystemExit:
        route_payload = _route_payload(data_dir, workspace=workspace, project=args.project)
        if args.json:
            print(json.dumps(_guided_envelope(route_payload, guided_view="route", payload={"route": route_payload}), ensure_ascii=False, indent=2))
        else:
            print(f"navigation_state={route_payload.get('navigation_state')}")
            print(f"handoff_hint={route_payload.get('handoff_hint')}")
            print(f"route_reason={route_payload.get('route_reason')}")
            print(f"phase_status_command={route_payload.get('phase_status_command')}")
            next_step = route_payload.get("next_recommended_step", {}) if isinstance(route_payload.get("next_recommended_step"), dict) else {}
            print(f"next_step={next_step.get('id')}")
            print(f"next_step_reason={next_step.get('reason')}")
            print(f"suggested_command={route_payload.get('suggested_command')}")
        return 0
    next_step = payload.get("next_recommended_step", {}) if isinstance(payload.get("next_recommended_step"), dict) else {}
    route_context = _route_payload(data_dir, workspace=payload.get("workspace"), project=payload.get("project"))
    debate_failed_payload = _debate_failed_payload(payload)
    debate_review_payload = _debate_review_payload(payload)
    debate_launch_payload = _debate_launch_payload(payload)
    if debate_failed_payload:
        if args.json:
            response = _guided_envelope_override(
                route_context,
                guided_view="debate-failure",
                payload=debate_failed_payload,
                route_reason="A debate run failed and should be inspected before normal workflow continues.",
                suggested_command=debate_failed_payload.get("recommended_command"),
                next_recommended_step={"id": "debate_failure", "reason": "Inspect the failed debate run before continuing."},
            )
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-failure",
                readiness=None,
                next_step={"id": "debate_failure", "reason": "Inspect the failed debate run before continuing."},
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="A debate run failed and should be inspected before normal workflow continues.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_failed_payload.get('workspace'))}",
                    f"- failed_topics: {_string_or_dash(debate_failed_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_failed_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_review_payload:
        if args.json:
            response = _guided_envelope_override(
                route_context,
                guided_view="debate-review",
                payload=debate_review_payload,
                route_reason="A debate synthesis is awaiting review before canonical updates should continue.",
                suggested_command=debate_review_payload.get("recommended_command"),
                next_recommended_step={"id": "debate_review", "reason": "Review pending debate synthesis before continuing canonical work."},
            )
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-review",
                readiness=None,
                next_step={"id": "debate_review", "reason": "Review pending debate synthesis before continuing canonical work."},
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="A debate synthesis is awaiting review before canonical updates should continue.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_review_payload.get('workspace'))}",
                    f"- debate_topics: {_string_or_dash(debate_review_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_review_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_launch_payload:
        if args.json:
            response = _guided_envelope_override(
                route_context,
                guided_view="debate-launch",
                payload=debate_launch_payload,
                route_reason="A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                suggested_command=debate_launch_payload.get("recommended_command"),
                next_recommended_step={"id": "debate_launch", "reason": "Resume the previously blocked debate launch after fixing executor configuration."},
            )
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-launch",
                readiness=None,
                next_step={"id": "debate_launch", "reason": "Resume the previously blocked debate launch after fixing executor configuration."},
                pending_user_decision=payload.get("pending_user_decision"),
                route_reason="A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_launch_payload.get('workspace'))}",
                    f"- thesis: {_string_or_dash(debate_launch_payload.get('thesis'))}",
                    f"- axis: {_string_or_dash(debate_launch_payload.get('axis'))}",
                    f"- config_path: {_string_or_dash(debate_launch_payload.get('config_path'))}",
                    f"- suggested_command: {_string_or_dash(debate_launch_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    response = {
        "workspace": payload.get("workspace"),
        "project": payload.get("project"),
        "phase": payload.get("phase"),
        "active_step": payload.get("active_step"),
        "pending_user_decision": payload.get("pending_user_decision"),
        "next_recommended_step": next_step,
        "readiness": payload.get("readiness"),
        "recommended_skills": route_context.get("recommended_skills", []),
        "handoff_hint": route_context.get("handoff_hint"),
        "suggested_command": route_context.get("suggested_command"),
        "phase_status_command": route_context.get("phase_status_command"),
    }
    if args.json:
        print(json.dumps(_guided_envelope(route_context, guided_view="resume", payload=response), ensure_ascii=False, indent=2))
    else:
        print(
            build_guided_output(
                mode=None,
                phase=response.get("phase"),
                guided_view="resume",
                readiness=response.get("readiness") if isinstance(response.get("readiness"), dict) else None,
                next_step=next_step,
                pending_user_decision=response.get("pending_user_decision"),
                route_reason=route_context.get("route_reason"),
                detail_lines=[
                    f"- resumed_workspace: {_string_or_dash(response.get('workspace'))}",
                    f"- project: {_string_or_dash(response.get('project'))}",
                    f"- active_step: {_string_or_dash(response.get('active_step'))}",
                    *_detail_lines_for_route_summary(response),
                ],
            )
        )
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from .cli_phases import cmd_clarify, cmd_prd, cmd_research

    data_dir = resolve_data_dir(args.data_dir)
    try:
        payload = _status_payload(data_dir, workspace=args.workspace)
    except SystemExit:
        route_payload = _route_payload(data_dir, workspace=args.workspace)
        if args.json:
            print(json.dumps(route_payload, ensure_ascii=False, indent=2))
        else:
            next_step = route_payload.get("next_recommended_step", {}) if isinstance(route_payload.get("next_recommended_step"), dict) else {}
            print(f"navigation_state={route_payload.get('navigation_state')}")

            print(f"handoff_hint={route_payload.get('handoff_hint')}")
            print(f"route_reason={route_payload.get('route_reason')}")
            print(f"next_step={next_step.get('id')}")
            print(f"next_step_reason={next_step.get('reason')}")
            print(f"suggested_command={route_payload.get('suggested_command')}")
        return 0
    route_context = _route_payload(data_dir, workspace=payload.get("workspace"), project=payload.get("project"))
    readiness = payload.get("readiness", {}) if isinstance(payload.get("readiness"), dict) else {}
    tracking = payload.get("observation_tracking", {}) if isinstance(payload.get("observation_tracking"), dict) else {}
    inbox = len(tracking.get("pending_observation_ids", [])) if isinstance(tracking, dict) else 0
    pending = payload.get("pending_user_decision")
    next_step = payload.get("next_recommended_step", {}) if isinstance(payload.get("next_recommended_step"), dict) else {}
    phase = payload.get("phase")
    observation_checkpoint = _observation_checkpoint_payload(data_dir, payload)
    debate_failed_payload = _debate_failed_payload(payload)
    debate_review_payload = _debate_review_payload(payload)
    debate_launch_payload = _debate_launch_payload(payload)

    if debate_failed_payload:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "A debate run failed and should be inspected before normal workflow continues.",
                "suggested_command": debate_failed_payload.get("recommended_command"),
                "view": "debate-failure",
                "payload": debate_failed_payload,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-failure",
                readiness=None,
                next_step={"id": "debate_failure", "reason": "Inspect the failed debate run before continuing."},
                pending_user_decision=pending,
                route_reason="A debate run failed and should be inspected before normal workflow continues.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_failed_payload.get('workspace'))}",
                    f"- failed_topics: {_string_or_dash(debate_failed_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_failed_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_review_payload:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "A debate synthesis is awaiting review before canonical updates should continue.",
                "suggested_command": debate_review_payload.get("recommended_command"),
                "view": "debate-review",
                "payload": debate_review_payload,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-review",
                readiness=None,
                next_step={"id": "debate_review", "reason": "Review pending debate synthesis before continuing canonical work."},
                pending_user_decision=pending,
                route_reason="A debate synthesis is awaiting review before canonical updates should continue.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_review_payload.get('workspace'))}",
                    f"- debate_topics: {_string_or_dash(debate_review_payload.get('topics'))}",
                    f"- suggested_command: {_string_or_dash(debate_review_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if debate_launch_payload:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                "suggested_command": debate_launch_payload.get("recommended_command"),
                "view": "debate-launch",
                "payload": debate_launch_payload,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="debate-launch",
                readiness=None,
                next_step={"id": "debate_launch", "reason": "Resume the previously blocked debate launch after fixing executor configuration."},
                pending_user_decision=pending,
                route_reason="A debate launch is pending because executor precheck failed earlier; resume it before continuing normal work.",
                detail_lines=[
                    f"- workspace: {_string_or_dash(debate_launch_payload.get('workspace'))}",
                    f"- thesis: {_string_or_dash(debate_launch_payload.get('thesis'))}",
                    f"- axis: {_string_or_dash(debate_launch_payload.get('axis'))}",
                    f"- config_path: {_string_or_dash(debate_launch_payload.get('config_path'))}",
                    f"- suggested_command: {_string_or_dash(debate_launch_payload.get('recommended_command'))}",
                ],
            )
        )
        return 0
    if pending == "candidate-review" or inbox > 0:
        from .observation.executor import build_review_payload, review_candidates

        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": route_context.get("route_reason"),
                "suggested_command": route_context.get("suggested_command"),
                "view": "observe-review",
                "payload": build_review_payload(data_dir, str(payload.get("workspace"))),
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        return review_candidates(data_dir, str(payload.get("workspace")), as_json=False)
    if observation_checkpoint:
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": "Observation policy confirmation is due at this workflow checkpoint.",
                "suggested_command": route_context.get("suggested_command"),
                "view": "observe-status",
                "payload": observation_checkpoint,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        print(
            build_guided_output(
                mode=None,
                phase=payload.get("phase"),
                guided_view="observe-status",
                readiness=None,
                next_step=next_step,
                pending_user_decision=pending,
                route_reason="Observation policy confirmation is due at this workflow checkpoint.",
                detail_lines=_observation_detail_lines(observation_checkpoint),
            )
        )
        return 0
    if phase == "maintaining" or pending == "prd-approval" or next_step.get("id") in {"draft_maintenance", "apply_maintenance"}:
        from .observation.executor import build_maintenance_status_payload, maintenance_status

        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": route_context.get("route_reason"),
                "suggested_command": route_context.get("suggested_command"),
                "view": "maintenance-status",
                "payload": build_maintenance_status_payload(data_dir, str(payload.get("workspace"))),
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        return maintenance_status(data_dir, str(payload.get("workspace")), as_json=False)
    if phase == "clarifying":
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": route_context.get("route_reason"),
                "suggested_command": route_context.get("suggested_command"),
                "view": "clarify-status",
                "payload": {
                    "workspace": payload.get("workspace"),
                    "project": payload.get("project"),

                    "phase": payload.get("phase"),
                    "readiness": readiness,
                },
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        return cmd_clarify(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False, subcommand="status"))
    if phase == "researching":
        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": route_context.get("route_reason"),
                "suggested_command": route_context.get("suggested_command"),
                "view": "research-status",
                "payload": {
                    "workspace": payload.get("workspace"),
                    "project": payload.get("project"),
                    "phase": payload.get("phase"),
                    "active_step": payload.get("active_step"),
                    "preview": False,
                    "readiness": readiness,
                    "next_recommended_step": next_step,
                },
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        return cmd_research(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False, subcommand="status"))
    if phase == "delivery" or next_step.get("id") == "challenge_prd":
        if args.json:
            from io import StringIO
            import contextlib

            buffer = StringIO()
            with contextlib.redirect_stdout(buffer):
                cmd_prd(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=True, subcommand="review"))
            prd_payload = json.loads(buffer.getvalue())
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": route_context.get("route_reason"),
                "suggested_command": route_context.get("suggested_command"),
                "view": "prd-review",
                "payload": prd_payload,
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        from .cli_phases import cmd_prd

        return cmd_prd(argparse.Namespace(data_dir=str(data_dir), workspace=payload.get("workspace"), json=False, subcommand="review"))
    if payload.get("phase") == "observing":
        from .observation.executor import build_observation_status_payload, observation_status

        if args.json:
            response = {
                "navigation_state": route_context.get("navigation_state"),
                "recommended_skills": route_context.get("recommended_skills", []),
                "handoff_hint": route_context.get("handoff_hint"),
                "route_reason": route_context.get("route_reason"),
                "suggested_command": route_context.get("suggested_command"),
                "view": "observe-status",
                "payload": build_observation_status_payload(data_dir, str(payload.get("workspace"))),
            }
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        return observation_status(data_dir, str(payload.get("workspace")), as_json=False)
    return cmd_status(args)
