from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from .cli_helpers import _resolve_workspace_context
from .current_state import preview_current_state, sync_current_state
from .debate.config import debate_executor_config_path, resolve_executor_plan
from .debate.orchestrator import mark_failed, run_debate, utc_now_iso
from .debate.executors import precheck_executor_plan
from .observation.paths import workspace_root
from .paths import resolve_data_dir


def _debates_root(data_dir: Path, workspace: str) -> Path:
    return workspace_root(data_dir, workspace) / "context" / "debates"


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "debate"


def _topic_dir(topic_root: Path, topic: str) -> Path:
    if not topic_root.exists():
        raise SystemExit(f"no debate topics found under workspace: {topic_root}")
    exact = topic_root / topic
    if exact.exists() and exact.is_dir():
        return exact
    matches = [p for p in topic_root.iterdir() if p.is_dir() and (p.name == topic or p.name.endswith(f"-{topic}"))]
    if not matches:
        raise SystemExit(f"debate topic not found: {topic}")
    if len(matches) > 1:
        raise SystemExit(f"debate topic is ambiguous: {topic}")
    return matches[0]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _topic_payload(topic_dir: Path) -> dict[str, Any]:
    run = _read_json(topic_dir / "run.json")
    status = _read_json(topic_dir / "status.json")
    signal = _read_json(topic_dir / "signal.json")
    review = _read_json(topic_dir / "review.json")
    synthesis = topic_dir / "synthesis.md"
    review_status = review.get("status")
    action_needed = None if str(review_status or "").strip().lower() in {"accepted", "rejected", "deferred"} else signal.get("action_needed")
    return {
        "topic": topic_dir.name,
        "thesis": run.get("thesis"),
        "executors": run.get("executors"),
        "state": status.get("state"),
        "round": status.get("round"),
        "action_needed": action_needed,
        "event": signal.get("event"),
        "completed_at": signal.get("completed_at") or status.get("completed_at"),
        "review_status": review_status,
        "synthesis_path": str(synthesis).replace("\\", "/") if synthesis.exists() else None,
        "path": str(topic_dir).replace("\\", "/"),
    }


def _list_topics(topic_root: Path) -> list[Path]:
    if not topic_root.exists():
        return []
    return sorted((p for p in topic_root.iterdir() if p.is_dir()), key=lambda item: item.name)


def _json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _topic_failed(topic_dir: Path) -> bool:
    status = _read_json(topic_dir / "status.json")
    signal = _read_json(topic_dir / "signal.json")
    return str(status.get("state") or "").strip().lower() == "failed" or str(signal.get("event") or "").strip().lower() == "failed"


def _resolved_execution_plan(data_dir: Path, args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    return resolve_executor_plan(
        data_dir,
        pro_exec=args.pro_exec,
        con_exec=args.con_exec,
        synth_exec=args.synth_exec,
        pro_model=getattr(args, "pro_model", None),
        con_model=getattr(args, "con_model", None),
        synth_model=getattr(args, "synth_model", None),
    )


def _clear_debate_launch(data_dir: Path, workspace: str, *, updated_by: str) -> dict[str, Any]:
    return sync_current_state(
        data_dir,
        workspace,
        patch={
            "debate_launch": {
                "active": False,
                "reason": None,
                "thesis": None,
                "axis": None,
                "topic_slug": None,
                "executors": {},
                "config_path": None,
            }
        },
        updated_by=updated_by,
    )


def _sync_debate_snapshot(data_dir: Path, workspace: str, *, updated_by: str) -> dict[str, Any]:
    return sync_current_state(data_dir, workspace, updated_by=updated_by)


def _run_topic_worker(data_dir: Path, workspace: str, topic_name: str) -> None:
    topic_dir = _topic_dir(_debates_root(data_dir, workspace), topic_name)
    run_payload = _read_json(topic_dir / "run.json")
    axis_payload = _read_json(topic_dir / "axis.json")
    executors = run_payload.get("executors") if isinstance(run_payload.get("executors"), dict) else {}
    _sync_debate_snapshot(data_dir, workspace, updated_by="debate-worker-start")
    try:
        run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root(data_dir, workspace),
            thesis=str(run_payload.get("thesis") or ""),
            axis=str(axis_payload.get("chosen_axis") or ""),
            defender_exec=str((executors.get("defender") or {}).get("exec") or ""),
            attacker_exec=str((executors.get("attacker") or {}).get("exec") or ""),
            synthesizer_exec=str((executors.get("synthesizer") or {}).get("exec") or ""),
            defender_model=(executors.get("defender") or {}).get("model"),
            attacker_model=(executors.get("attacker") or {}).get("model"),
            synthesizer_model=(executors.get("synthesizer") or {}).get("model"),
            round_count=int(run_payload.get("round_count") or 3),
        )
    except Exception as exc:  # noqa: BLE001
        if not _topic_failed(topic_dir):
            mark_failed(topic_dir, reason=str(exc))
        raise
    finally:
        _sync_debate_snapshot(data_dir, workspace, updated_by="debate-worker-finished")


def _launch_background_worker(data_dir: Path, workspace: str, topic_name: str, topic_dir: Path) -> int:
    log_path = topic_dir / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        "-m",
        "pmagent.cli",
        "debate",
        "--data-dir",
        str(data_dir),
        "_run-topic",
        "--workspace",
        workspace,
        "--topic",
        topic_name,
    ]
    log_file = log_path.open("ab")
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    process = subprocess.Popen(  # noqa: S603
        argv,
        cwd=str(data_dir),
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        close_fds=not sys.platform.startswith("win"),
        creationflags=creationflags,
    )
    log_file.close()
    _write_json(
        topic_dir / "worker.json",
        {
            "pid": process.pid,
            "log_path": str(log_path).replace("\\", "/"),
            "argv": argv,
            "started_at": utc_now_iso(),
        },
    )
    return int(process.pid)


def _cmd_start(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    project, workspace = _resolve_workspace_context(data_dir, workspace=args.workspace)
    config_path = str(debate_executor_config_path(data_dir)).replace("\\", "/")
    topic_root = _debates_root(data_dir, workspace)
    topic_root.mkdir(parents=True, exist_ok=True)
    topic_slug = args.topic_slug or _slugify(args.thesis)
    topic_name = f"{date.today().isoformat()}-{topic_slug}"
    topic_dir = topic_root / topic_name
    chosen_axis = str(args.axis or "").strip()
    if not chosen_axis:
        raise SystemExit("debate start requires --axis; let the main agent propose candidate axes and ask the user to choose one before starting the debate")
    plan = _resolved_execution_plan(data_dir, args)
    issues = precheck_executor_plan(plan)
    if issues:
        sync_current_state(
            data_dir,
            workspace,
            patch={
                "debate_launch": {
                    "active": True,
                    "reason": "; ".join(item["message"] for item in issues),
                    "thesis": args.thesis,
                    "axis": chosen_axis,
                    "topic_slug": topic_slug,
                    "executors": plan,
                    "config_path": config_path,
                }
            },
            updated_by="debate-precheck-failed",
        )
        raise SystemExit(
            "debate executor precheck failed. Update the Debate executor/model config and try again next turn.\n"
            + "\n".join(f"- {item['message']}" for item in issues)
            + f"\nConfig path: {config_path}"
        )

    if topic_dir.exists():
        if not getattr(args, "force", False):
            raise SystemExit(f"debate topic already exists: {topic_name}")
        if not _topic_failed(topic_dir):
            raise SystemExit(f"debate topic exists and is not failed: {topic_name} (use a new topic slug instead of --force)")
        shutil.rmtree(topic_dir, ignore_errors=False)
    topic_dir.mkdir(parents=True, exist_ok=False)

    _write_json(
        topic_dir / "run.json",
        {
            "topic": topic_name,
            "project": project,
            "workspace": workspace,
            "thesis": args.thesis,
            "round_count": int(args.rounds or 3),
            "executors": plan,
            "created_at": utc_now_iso(),
        },
    )
    _write_json(topic_dir / "axis.json", {"source": "main-agent", "candidates": [], "chosen_axis": chosen_axis})

    _write_json(
        topic_dir / "status.json",
        {
            "state": "running",
            "round": None,
            "started_at": utc_now_iso(),
            "completed_at": None,
        },
    )
    _write_json(
        topic_dir / "signal.json",
        {
            "event": "started",
            "topic": topic_name,
            "action_needed": None,
        },
    )
    _sync_debate_snapshot(data_dir, workspace, updated_by="debate-start-initialized")
    if getattr(args, "foreground", False):
        try:
            _run_topic_worker(data_dir, workspace, topic_name)
        except Exception as exc:  # noqa: BLE001
            _clear_debate_launch(data_dir, workspace, updated_by="debate-start-failed")
            raise SystemExit(
                f"debate run failed for topic={topic_name}. Inspect {str(topic_dir).replace(chr(92), '/')} for partial artifacts. "
                f"reason={exc}\nIf the configured Debate executor/model is unavailable on this machine, edit: {config_path}"
            ) from exc
        _clear_debate_launch(data_dir, workspace, updated_by="debate-start")
        state = "completed"
        pid = None
    else:
        try:
            pid = _launch_background_worker(data_dir, workspace, topic_name, topic_dir)
        except Exception as exc:  # noqa: BLE001
            mark_failed(topic_dir, reason=f"failed to launch background worker: {exc}")
            _clear_debate_launch(data_dir, workspace, updated_by="debate-start-launch-failed")
            raise SystemExit(
                f"debate background launch failed for topic={topic_name}. Inspect {str(topic_dir).replace(chr(92), '/')} for partial artifacts. "
                f"reason={exc}"
            ) from exc
        _clear_debate_launch(data_dir, workspace, updated_by="debate-start-background")
        state = "running"
    payload = {
        "project": project,
        "workspace": workspace,
        "topic": topic_name,
        "state": state,
        "chosen_axis": chosen_axis,
        "path": str(topic_dir).replace("\\", "/"),
        "background": not getattr(args, "foreground", False),
        "pid": pid,
    }
    if args.json:
        _json_print(payload)
    else:
        print(f"debate topic={topic_name}")
        print(f"state={state}")
        if pid is not None:
            print(f"pid={pid}")
        print(f"path={payload['path']}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    project, workspace = _resolve_workspace_context(data_dir, workspace=args.workspace)
    _sync_debate_snapshot(data_dir, workspace, updated_by="debate-status")
    topic_root = _debates_root(data_dir, workspace)
    if args.topic:
        topic_dir = _topic_dir(topic_root, args.topic)
        payload = {
            "project": project,
            "workspace": workspace,
            "topic": _topic_payload(topic_dir),
        }
    else:
        topics = [_topic_payload(topic_dir) for topic_dir in _list_topics(topic_root)]
        payload = {
            "project": project,
            "workspace": workspace,
            "count": len(topics),
            "topics": topics,
        }
    if args.json:
        _json_print(payload)
    else:
        print(f"project={project}")
        print(f"workspace={workspace}")
        if args.topic:
            topic = payload["topic"]
            print(f"topic={topic.get('topic')}")
            print(f"state={topic.get('state')}")
            print(f"action_needed={topic.get('action_needed')}")
            print(f"synthesis_path={topic.get('synthesis_path')}")
        else:
            print(f"count={payload['count']}")
            for topic in payload["topics"]:
                print(
                    f"- {topic.get('topic')}: state={topic.get('state')} action_needed={topic.get('action_needed')} "
                    f"review_status={topic.get('review_status') or '-'}"
                )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    _, workspace = _resolve_workspace_context(data_dir, workspace=args.workspace)
    topic_dir = _topic_dir(_debates_root(data_dir, workspace), args.topic)

    target: Path
    if args.synthesis:
        target = topic_dir / "synthesis.md"
    elif args.round is not None:
        user_round = int(args.round)
        if user_round < 1:
            raise SystemExit("debate show --round is 1-indexed; use --round 1 for the first round")
        round_num = user_round - 1
        side = "pro" if args.side == "defender" else "con"
        target = topic_dir / f"round-{round_num}-{side}.md"
    else:
        target = topic_dir / "synthesis.md"
        if not target.exists():
            payload = _topic_payload(topic_dir)
            if args.json:
                _json_print(payload)
            else:
                print(f"topic={payload.get('topic')}")
                print(f"state={payload.get('state')}")
                print(f"path={payload.get('path')}")
            return 0

    if not target.exists():
        raise SystemExit(f"debate artifact not found: {target.name}")

    if args.json:
        _json_print(
            {
                "topic": topic_dir.name,
                "path": str(target).replace("\\", "/"),
                "content": target.read_text(encoding="utf-8"),
            }
        )
    else:
        print(target.read_text(encoding="utf-8"))
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    _, workspace = _resolve_workspace_context(data_dir, workspace=args.workspace)
    topic_dir = _topic_dir(_debates_root(data_dir, workspace), args.topic)
    synthesis_path = topic_dir / "synthesis.md"
    if not synthesis_path.exists():
        raise SystemExit("cannot enter debate review before synthesis.md exists")
    review = _read_json(topic_dir / "review.json")
    review_status = str(review.get("status") or "").strip().lower()
    if review_status in {"accepted", "rejected", "deferred"}:
        raise SystemExit(f"debate topic already resolved with status={review_status}; do not reopen review for this topic")

    state = preview_current_state(data_dir, workspace)
    warning: str | None = None
    candidate_review = state.get("candidate_review") if isinstance(state.get("candidate_review"), dict) else {}
    if candidate_review.get("active"):
        warning = "observation candidate-review is also active; consider clearing observation backlog before reviewing debate."

    existing_topics = []
    debate_review = state.get("debate_review") if isinstance(state.get("debate_review"), dict) else {}
    if isinstance(debate_review.get("awaiting_review_topics"), list):
        existing_topics = [str(item) for item in debate_review.get("awaiting_review_topics", []) if str(item).strip()]
    if topic_dir.name not in existing_topics:
        existing_topics.append(topic_dir.name)

    updated = sync_current_state(
        data_dir,
        workspace,
        patch={
            "debate_review": {
                "active": True,
                "awaiting_review_topics": existing_topics,
            }
        },
        updated_by="debate-review",
    )
    payload = {
        "workspace": workspace,
        "topic": topic_dir.name,
        "debate_review": updated.get("debate_review"),
        "warning": warning,
    }
    if args.json:
        _json_print(payload)
    else:
        print(f"debate review topic={topic_dir.name}")
        if warning:
            print(f"warning={warning}")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    _, workspace = _resolve_workspace_context(data_dir, workspace=args.workspace)
    topic_dir = _topic_dir(_debates_root(data_dir, workspace), args.topic)
    chosen_status = "accepted" if args.accepted else "rejected" if args.rejected else "deferred"
    _write_json(
        topic_dir / "review.json",
        {
            "topic": topic_dir.name,
            "status": chosen_status,
            "resolved_at": date.today().isoformat(),
            "resolved_by": "agent",
            "notes": args.notes or "",
        },
    )
    signal = _read_json(topic_dir / "signal.json")
    _write_json(
        topic_dir / "signal.json",
        {
            **signal,
            "event": str(signal.get("event") or "completed"),
            "topic": topic_dir.name,
            "action_needed": None,
            "resolved_at": date.today().isoformat(),
        },
    )

    state = preview_current_state(data_dir, workspace)
    debate_review = state.get("debate_review") if isinstance(state.get("debate_review"), dict) else {}
    remaining_topics = []
    if isinstance(debate_review.get("awaiting_review_topics"), list):
        remaining_topics = [
            str(item)
            for item in debate_review.get("awaiting_review_topics", [])
            if str(item).strip() and str(item) != topic_dir.name
        ]
    updated = sync_current_state(
        data_dir,
        workspace,
        patch={
            "debate_review": {
                "active": bool(remaining_topics),
                "awaiting_review_topics": remaining_topics,
            }
        },
        updated_by="debate-resolve",
    )
    payload = {
        "workspace": workspace,
        "topic": topic_dir.name,
        "status": chosen_status,
        "debate_review": updated.get("debate_review"),
    }
    if args.json:
        _json_print(payload)
    else:
        print(f"debate resolved topic={topic_dir.name} status={chosen_status}")
    return 0


def cmd_debate(args: argparse.Namespace) -> int:
    if args.subcommand == "start":
        return _cmd_start(args)
    if args.subcommand == "_run-topic":
        data_dir = resolve_data_dir(args.data_dir)
        _run_topic_worker(data_dir, args.workspace, args.topic)
        return 0
    if args.subcommand == "status":
        return _cmd_status(args)
    if args.subcommand == "show":
        return _cmd_show(args)
    if args.subcommand == "review":
        return _cmd_review(args)
    if args.subcommand == "resolve":
        return _cmd_resolve(args)
    raise SystemExit(f"unknown debate subcommand: {args.subcommand}")
