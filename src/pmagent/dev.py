from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cli_helpers import _resolve_workspace_context
from .current_state import sync_current_state
from .observation.paths import workspace_root
from .paths import resolve_data_dir


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _lesson_candidates_path(data_dir: Path, workspace: str) -> Path:
    return workspace_root(data_dir, workspace) / "dev" / "lessons" / "lesson-candidates.jsonl"


def _load_lesson_candidates(path: Path) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    if not path.exists():
        return lessons
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            lessons.append(item)
    return lessons


def _write_lesson_candidates(path: Path, lessons: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in lessons),
        encoding="utf-8",
    )


def _append_lesson_summary(path: Path, lesson: dict[str, Any], *, status: str, note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            f"## {lesson.get('lesson_id')}",
            "",
            f"- Slice: `{lesson.get('slice')}`",
            f"- Run: `{lesson.get('run')}`",
            f"- Status: `{status}`",
            f"- Reviewed at: `{lesson.get('reviewed_at')}`",
            f"- Review note: {note or 'none'}",
            "",
            str(lesson.get("lesson") or "").strip(),
            "",
        ]
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def list_slices(data_dir: Path, workspace: str) -> dict[str, Any]:
    root = workspace_root(data_dir, workspace) / "dev" / "slices"
    slices = sorted(path.name for path in root.glob("*.md")) if root.exists() else []
    return {"workspace": workspace, "slices": slices}


def record_run(
    data_dir: Path,
    workspace: str,
    *,
    slice_id: str,
    command: str,
    status: str,
    lesson: str | None = None,
) -> dict[str, Any]:
    root = workspace_root(data_dir, workspace)
    if not root.exists():
        raise SystemExit(f"workspace does not exist: {workspace}")
    normalized_slice_id = slice_id[:-3] if slice_id.endswith(".md") else slice_id
    slice_file = f"{normalized_slice_id}.md"
    slice_path = root / "dev" / "slices" / slice_file
    if not slice_path.exists():
        raise SystemExit(
            "slice artifact does not exist; have an external Agent execute "
            f"`skills/steps/dev-readiness/skill.md` first: {slice_file}"
        )
    run_id = _utc_now().replace(":", "").replace("-", "").replace("Z", "")
    run_name = f"run-{run_id}"
    run_root = root / "dev" / "runs" / normalized_slice_id / run_name
    run_root.mkdir(parents=True, exist_ok=True)
    recorded_at = _utc_now()
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "slice": normalized_slice_id,
                "run": run_name,
                "status": status,
                "recorded_at": recorded_at,
                "command": command,
                "slice_artifact": _rel(data_dir, slice_path),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "touched-files.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [],
                "note": "Fill after implementation if changed files are known.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "commands.jsonl").write_text(
        json.dumps({"command": command, "status": status, "recorded_at": recorded_at}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_root / "test-results.json").write_text(
        json.dumps({"status": status, "command": command, "recorded_at": recorded_at}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_root / "decisions.md").write_text("# Decisions\n\n<!-- Fill with implementation decisions made during this slice run. -->\n", encoding="utf-8")
    (run_root / "blockers.md").write_text("# Blockers\n\n<!-- Fill if this slice is blocked or partially blocked. -->\n", encoding="utf-8")
    (run_root / "diff-summary.md").write_text("# Diff Summary\n\n<!-- Fill after implementation. -->\n", encoding="utf-8")
    lesson_path = _lesson_candidates_path(data_dir, workspace)
    lesson_path.parent.mkdir(parents=True, exist_ok=True)
    if lesson:
        with lesson_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "lesson_id": f"{normalized_slice_id}-{run_name}-001",
                        "slice": normalized_slice_id,
                        "run": run_name,
                        "lesson": lesson,
                        "status": "inbox",
                        "created_at": recorded_at,
                        "source_run": _rel(data_dir, run_root),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    state = sync_current_state(
        data_dir,
        workspace,
        patch={
            "phase": "dev-readiness",
            "active_step": "slice-run-record",
            "next_recommended_step": {
                "id": "lesson_review" if lesson else "run_slice",
                "reason": "Review generated lesson candidates before promoting them." if lesson else "Continue slice execution.",
            },
        },
        updated_by="dev-run-record",
    )
    return {
        "workspace": workspace,
        "slice": normalized_slice_id,
        "run": _rel(data_dir, run_root),
        "lesson_candidates": _rel(data_dir, lesson_path),
        "recommended_skills": state.get("recommended_skills", []),
    }


def lesson_review(data_dir: Path, workspace: str) -> dict[str, Any]:
    path = _lesson_candidates_path(data_dir, workspace)
    lessons = _load_lesson_candidates(path)
    return {"workspace": workspace, "inbox_count": len([item for item in lessons if item.get("status") == "inbox"]), "lessons": lessons}


def review_lesson_candidate(
    data_dir: Path,
    workspace: str,
    *,
    lesson_id: str,
    status: str,
    note: str = "",
) -> dict[str, Any]:
    if status not in {"accepted", "rejected", "deferred"}:
        raise SystemExit("status must be accepted, rejected, or deferred")
    path = _lesson_candidates_path(data_dir, workspace)
    lessons = _load_lesson_candidates(path)
    if not lessons:
        raise SystemExit("no lesson candidates found")

    selected: dict[str, Any] | None = None
    for lesson in lessons:
        if str(lesson.get("lesson_id") or "") == lesson_id:
            selected = lesson
            break
    if selected is None:
        raise SystemExit(f"lesson candidate not found: {lesson_id}")

    selected["status"] = status
    selected["reviewed_at"] = _utc_now()
    selected["review_note"] = note
    _write_lesson_candidates(path, lessons)

    promoted_path: Path | None = None
    if status == "accepted":
        promoted_path = workspace_root(data_dir, workspace) / "dev" / "lessons" / "accepted-lessons.md"
        _append_lesson_summary(promoted_path, selected, status=status, note=note)
    elif status == "rejected":
        promoted_path = workspace_root(data_dir, workspace) / "dev" / "lessons" / "rejected-lessons.md"
        _append_lesson_summary(promoted_path, selected, status=status, note=note)

    state = sync_current_state(
        data_dir,
        workspace,
        patch={
            "phase": "dev-readiness",
            "active_step": "lesson-review",
            "next_recommended_step": {
                "id": "run_slice" if status in {"accepted", "rejected"} else "lesson_review",
                "reason": "Lesson candidate review was recorded; continue slice execution or update dev-plan if needed.",
            },
        },
        updated_by="dev-lesson-review",
    )
    response: dict[str, Any] = {
        "workspace": workspace,
        "lesson_id": lesson_id,
        "status": status,
        "lesson_candidates": _rel(data_dir, path),
        "recommended_skills": state.get("recommended_skills", []),
    }
    if promoted_path is not None:
        response["review_artifact"] = _rel(data_dir, promoted_path)
    return response


def _resolve(data_dir_arg: str | None, workspace_arg: str | None) -> tuple[Path, str]:
    data_dir = resolve_data_dir(data_dir_arg)
    _, workspace = _resolve_workspace_context(data_dir, workspace=workspace_arg)
    return data_dir, workspace


def cmd_dev(args: argparse.Namespace) -> int:
    data_dir, workspace = _resolve(args.data_dir, args.workspace)
    if args.subcommand == "slices":
        payload = list_slices(data_dir, workspace)
    elif args.subcommand == "run-record":
        payload = record_run(
            data_dir,
            workspace,
            slice_id=args.slice,
            command=args.command,
            status=args.status,
            lesson=args.lesson,
        )
    elif args.subcommand == "lesson-review":
        if getattr(args, "lesson_id", None):
            if not args.status:
                raise SystemExit("--status is required when --lesson-id is provided")
            payload = review_lesson_candidate(
                data_dir,
                workspace,
                lesson_id=args.lesson_id,
                status=args.status,
                note=args.note,
            )
        else:
            payload = lesson_review(data_dir, workspace)
    else:
        raise SystemExit(f"unsupported dev subcommand: {args.subcommand}")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}={value}")
    return 0
