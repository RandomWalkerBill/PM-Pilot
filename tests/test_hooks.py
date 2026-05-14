"""Tests for pmagent Claude Code hook entry points.

Each hook's ``main()`` reads a JSON payload from stdin, writes context to
stdout, and exits with 0 on success or 2 on block. The tests exercise the
fail-open contract and the individual gate logic.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any

import pytest

from pmagent.hooks import (
    _common,
    post_mutation_check,
    pre_bash_guard,
    pre_write_guard,
    response_validator,
    session_bootstrap,
    state_surface,
)


# ---------- scaffolding helpers ----------


def _mk_data_dir(tmp_path: Path, *, workspace: str | None = "alpha-observe") -> Path:
    data_dir = tmp_path / "pm-data"
    (data_dir / "config").mkdir(parents=True, exist_ok=True)
    (data_dir / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (data_dir / "config" / "agent-workflow.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    projects_payload = {
        "active_project": "alpha" if workspace else "",
        "active_workspace": workspace or "",
        "projects": {},
    }
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(projects_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if workspace:
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        (ws_root / ".pmagent" / "current-state.json").write_text(
            json.dumps(
                {
                    "project": "alpha",
                    "workspace": workspace,
                    "phase": "clarifying",
                    "active_step": "clarifying",
                    "updated_at": "2026-04-21T00:00:00Z",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return data_dir


def _set_data_dir_env(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    monkeypatch.setenv(_common.resolve_data_dir.__globals__["ENV_DATA_DIR"], str(data_dir))


def _run_hook(
    module,
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            module.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


# ---------- _common.read_payload ----------


def test_read_payload_handles_empty_and_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert _common.read_payload() == {}
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json"))
    assert _common.read_payload() == {}
    monkeypatch.setattr("sys.stdin", io.StringIO('"scalar"'))
    assert _common.read_payload() == {}


def test_run_safely_swallows_unexpected_errors(capsys: pytest.CaptureFixture) -> None:
    def explode() -> None:
        raise RuntimeError("boom")

    with pytest.raises(SystemExit) as exc:
        _common.main_wrapper("unit-test", explode)
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "suppressed error" in captured.err


def test_run_safely_lets_block_propagate() -> None:
    def block_it() -> None:
        _common.block("stop me")

    with pytest.raises(SystemExit) as exc:
        _common.main_wrapper("unit-test", block_it)
    assert exc.value.code == 2


# ---------- session_bootstrap ----------


def test_session_bootstrap_injects_agents_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    # Audit subprocess stubbed to return deterministic output.
    def fake_run_pmagent(args, **kwargs):
        assert "audit" in args
        return 0, json.dumps({"unread_observations": []}), ""

    monkeypatch.setattr(session_bootstrap, "run_pmagent", fake_run_pmagent)

    code, stdout, _ = _run_hook(session_bootstrap, {"cwd": str(tmp_path)}, monkeypatch)
    assert code == 0
    assert "AGENTS.md" in stdout
    assert "workspace-summary.md" in stdout
    assert "observe-audit" in stdout


def test_session_bootstrap_without_data_dir_reports_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_common.resolve_data_dir.__globals__["ENV_DATA_DIR"], raising=False)
    monkeypatch.setattr(_common, "resolve_data_dir", lambda: (_ for _ in ()).throw(RuntimeError("no")))

    code, stdout, _ = _run_hook(session_bootstrap, {}, monkeypatch)
    assert code == 0
    assert "data_dir is not configured" in stdout


def test_session_bootstrap_emits_debate_attention_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    state_path.write_text(
        json.dumps(
            {
                "workspace": "alpha-observe",
                "debates": {
                    "failed_count": 1,
                    "failed_topics": ["2026-04-22-topic-failed"],
                    "completed_awaiting_review_count": 1,
                },
                "debate_review": {
                    "active": False,
                    "awaiting_review_topics": ["2026-04-22-topic-review"],
                    "completed_awaiting_review_count": 1,
                },
                "debate_launch": {
                    "active": True,
                    "reason": "executor missing",
                    "thesis": "Should we ship?",
                    "axis": "speed vs quality",
                    "topic_slug": "should-we-ship",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _set_data_dir_env(monkeypatch, data_dir)

    monkeypatch.setattr(session_bootstrap, "run_pmagent", lambda *args, **kwargs: (0, json.dumps({"unread_observations": []}), ""))

    code, stdout, _ = _run_hook(session_bootstrap, {"cwd": str(tmp_path)}, monkeypatch)
    assert code == 0
    assert "debate_failure_gate" in stdout
    assert "debate_visibility_gate" in stdout
    assert "debate_launch_pending" in stdout


# ---------- state_surface ----------


def test_state_surface_injects_status_and_backlog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    status_payload = {
        "project": "alpha",
        "workspace": "alpha-observe",
        "phase": "clarifying",
        "active_step": "clarifying",
        "next_recommended_step": "answer-question",
    }
    unread_payload = {"count": 3, "ids": ["obs-1", "obs-2", "obs-3"]}

    def fake_run_pmagent(args, **kwargs):
        if args[0] == "status":
            return 0, json.dumps(status_payload), ""
        if args[:2] == ["observe", "unread"]:
            return 0, json.dumps(unread_payload), ""
        return 1, "", ""

    monkeypatch.setattr(state_surface, "run_pmagent", fake_run_pmagent)

    code, stdout, _ = _run_hook(state_surface, {}, monkeypatch)
    assert code == 0
    assert "state-surface" in stdout
    assert "backlog_visibility_gate" in stdout
    assert "3 unread" in stdout


def test_state_surface_no_backlog_no_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    def fake_run_pmagent(args, **kwargs):
        if args[0] == "status":
            return 0, json.dumps({"phase": "clarifying"}), ""
        if args[:2] == ["observe", "unread"]:
            return 0, json.dumps({"count": 0, "ids": []}), ""
        return 1, "", ""

    monkeypatch.setattr(state_surface, "run_pmagent", fake_run_pmagent)
    code, stdout, _ = _run_hook(state_surface, {}, monkeypatch)
    assert code == 0
    assert "backlog_visibility_gate" not in stdout


def test_state_surface_injects_debate_backlog_from_current_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    state_path.write_text(
        json.dumps(
            {
                "workspace": "alpha-observe",
                "phase": "clarifying",
                "debates": {"completed_awaiting_review_count": 1},
                "debate_review": {
                    "active": False,
                    "awaiting_review_topics": ["2026-04-22-topic-a"],
                    "completed_awaiting_review_count": 1,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _set_data_dir_env(monkeypatch, data_dir)

    def fake_run_pmagent(args, **kwargs):
        if args[0] == "status":
            return 0, json.dumps({"phase": "clarifying"}), ""
        if args[:2] == ["observe", "unread"]:
            return 0, json.dumps({"count": 0, "ids": []}), ""
        return 1, "", ""

    monkeypatch.setattr(state_surface, "run_pmagent", fake_run_pmagent)
    code, stdout, _ = _run_hook(state_surface, {}, monkeypatch)
    assert code == 0
    assert "debate_visibility_gate" in stdout
    assert "2026-04-22-topic-a" in stdout


def test_state_surface_injects_debate_failure_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    state_path.write_text(
        json.dumps(
            {
                "workspace": "alpha-observe",
                "phase": "clarifying",
                "debates": {
                    "failed_count": 1,
                    "failed_topics": ["2026-04-22-topic-failed"],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _set_data_dir_env(monkeypatch, data_dir)

    def fake_run_pmagent(args, **kwargs):
        if args[0] == "status":
            return 0, json.dumps({"phase": "clarifying"}), ""
        if args[:2] == ["observe", "unread"]:
            return 0, json.dumps({"count": 0, "ids": []}), ""
        return 1, "", ""

    monkeypatch.setattr(state_surface, "run_pmagent", fake_run_pmagent)
    code, stdout, _ = _run_hook(state_surface, {}, monkeypatch)
    assert code == 0
    assert "debate_failure_gate" in stdout
    assert "2026-04-22-topic-failed" in stdout


# ---------- pre_bash_guard ----------


def _write_transcript(tmp_path: Path, messages: list[dict[str, Any]]) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n",
        encoding="utf-8",
    )
    return path


def test_pre_bash_guard_blocks_unconfirmed_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)
    transcript = _write_transcript(
        tmp_path,
        [
            {"role": "user", "content": "帮我继续推进一下 PRD"},
            {"role": "assistant", "content": "好"},
        ],
    )
    payload = {
        "transcript_path": str(transcript),
        "tool_name": "Bash",
        "tool_input": {
            "command": "pmagent observe accept --workspace alpha-observe --card obs-42"
        },
    }
    code, _, err = _run_hook(pre_bash_guard, payload, monkeypatch)
    assert code == 2
    assert "review_gate" in err


def test_pre_bash_guard_allows_when_card_id_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)
    transcript = _write_transcript(
        tmp_path,
        [
            {"role": "user", "content": "obs-42 接受"},
        ],
    )
    payload = {
        "transcript_path": str(transcript),
        "tool_name": "Bash",
        "tool_input": {
            "command": "pmagent observe accept --workspace alpha-observe --card obs-42"
        },
    }
    code, _, _ = _run_hook(pre_bash_guard, payload, monkeypatch)
    assert code == 0


def test_pre_bash_guard_ignores_unrelated_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pmagent status"},
    }
    code, _, _ = _run_hook(pre_bash_guard, payload, monkeypatch)
    assert code == 0


# ---------- pre_write_guard ----------


def test_pre_write_guard_blocks_candidate_review_prd_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    state_path.write_text(
        json.dumps({"active_step": "candidate-review"}, ensure_ascii=False),
        encoding="utf-8",
    )
    _set_data_dir_env(monkeypatch, data_dir)

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(data_dir / "workspaces" / "alpha-observe" / "prd" / "PRD.md")
        },
    }
    code, _, err = _run_hook(pre_write_guard, payload, monkeypatch)
    assert code == 2
    assert "observation_boundary_gate" in err


def test_pre_write_guard_allows_non_prd_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    state_path.write_text(
        json.dumps({"active_step": "candidate-review"}, ensure_ascii=False),
        encoding="utf-8",
    )
    _set_data_dir_env(monkeypatch, data_dir)

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(
                data_dir / "workspaces" / "alpha-observe" / "candidate-updates" / "accepted" / "x.md"
            )
        },
    }
    code, _, _ = _run_hook(pre_write_guard, payload, monkeypatch)
    assert code == 0


def test_pre_write_guard_allows_when_not_in_candidate_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)  # default active_step is "clarifying"
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(data_dir / "workspaces" / "alpha-observe" / "prd" / "PRD.md")
        },
    }
    code, _, _ = _run_hook(pre_write_guard, payload, monkeypatch)
    assert code == 0


def test_pre_write_guard_blocks_debate_review_prd_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    state_path.write_text(
        json.dumps(
            {
                "debate_review": {
                    "active": True,
                    "awaiting_review_topics": ["topic-a"],
                    "completed_awaiting_review_count": 1,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _set_data_dir_env(monkeypatch, data_dir)

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(data_dir / "workspaces" / "alpha-observe" / "prd" / "PRD.md")
        },
    }
    code, _, err = _run_hook(pre_write_guard, payload, monkeypatch)
    assert code == 2
    assert "debate_boundary_gate" in err


def test_pre_write_guard_blocks_debate_review_requirement_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    state_path.write_text(
        json.dumps(
            {
                "debate_review": {
                    "active": True,
                    "awaiting_review_topics": ["topic-a"],
                    "completed_awaiting_review_count": 1,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _set_data_dir_env(monkeypatch, data_dir)

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(data_dir / "workspaces" / "alpha-observe" / "Requirement.md")
        },
    }
    code, _, err = _run_hook(pre_write_guard, payload, monkeypatch)
    assert code == 2
    assert "debate_boundary_gate" in err


# ---------- post_mutation_check ----------


def test_post_mutation_summary_sync_flags_stale_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    state_path = data_dir / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json"
    os.utime(state_path, (time.time() - 600, time.time() - 600))
    _set_data_dir_env(monkeypatch, data_dir)

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(data_dir / "workspaces" / "alpha-observe" / "workspace-summary.md")
        },
    }
    code, stdout, _ = _run_hook(post_mutation_check, payload, monkeypatch)
    assert code == 0
    assert "summary_sync_gate" in stdout


def test_post_mutation_raw_log_flags_missing_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pmagent clarify answer --answer 'hi'"},
    }
    code, stdout, _ = _run_hook(post_mutation_check, payload, monkeypatch)
    assert code == 0
    assert "phase_raw_logging" in stdout
    assert "clarifying-log.md" in stdout


def test_post_mutation_raw_log_silent_when_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    log = data_dir / "workspaces" / "alpha-observe" / "research" / "research-log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("just now\n", encoding="utf-8")
    _set_data_dir_env(monkeypatch, data_dir)

    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pmagent research note --summary 'x'"},
    }
    code, stdout, _ = _run_hook(post_mutation_check, payload, monkeypatch)
    assert code == 0
    assert "phase_raw_logging" not in stdout


def test_post_mutation_flags_pending_feishu_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    def fake_run_pmagent(args, *, timeout=4.0, env=None):
        assert args[:2] == ["infra", "sync-status"]
        return (
            0,
            json.dumps(
                {
                    "configured": False,
                    "pending_files": ["Requirement.md", "workspace-summary.md"],
                }
            ),
            "",
        )

    monkeypatch.setattr(post_mutation_check, "run_pmagent", fake_run_pmagent)
    payload = {
        "cwd": str(data_dir),
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(data_dir / "workspaces" / "alpha-observe" / "Requirement.md")
        },
    }
    code, stdout, _ = _run_hook(post_mutation_check, payload, monkeypatch)
    assert code == 0
    assert "feishu_sync_pending" in stdout
    assert "lark-cli" in stdout
    assert "PMAGENT_FEISHU_WIKI_PUSH_COMMAND" in stdout


def test_post_mutation_suggests_wiki_push_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    monkeypatch.setattr(
        post_mutation_check,
        "run_pmagent",
        lambda *args, **kwargs: (
            0,
            json.dumps({"configured": True, "pending_files": ["workspace-summary.md"]}),
            "",
        ),
    )
    payload = {
        "cwd": str(data_dir),
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(data_dir / "workspaces" / "alpha-observe" / "workspace-summary.md")
        },
    }
    code, stdout, _ = _run_hook(post_mutation_check, payload, monkeypatch)
    assert code == 0
    assert "Ask the user whether to sync" in stdout
    assert "pmagent infra wiki-push --workspace alpha-observe --json" in stdout


# ---------- response_validator ----------


def test_response_validator_blocks_when_scores_but_no_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _write_transcript(
        tmp_path,
        [
            {"role": "user", "content": "给我一下当前 readiness"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": json.dumps(
                            {
                                "readiness": {
                                    "phase": "clarifying",
                                    "dimensions": {"scope": 0.2, "outcome": 0.3},
                                }
                            }
                        ),
                    }
                ],
            },
            {"role": "assistant", "content": "readiness 大概在 0.25 左右，还需要更多信息。"},
        ],
    )

    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    code, _, err = _run_hook(
        response_validator,
        {"transcript_path": str(transcript), "stop_hook_active": False},
        monkeypatch,
    )
    assert code == 2
    assert "score_visibility" in err


def test_response_validator_allows_when_table_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _write_transcript(
        tmp_path,
        [
            {"role": "user", "content": "score?"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": json.dumps(
                            {"readiness": {"dimensions": {"scope": 0.2}}}
                        ),
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "| 评分项 | 分数 |\n| --- | --- |\n| overall | 0.2 |\n",
            },
        ],
    )
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)

    code, _, _ = _run_hook(
        response_validator,
        {"transcript_path": str(transcript), "stop_hook_active": False},
        monkeypatch,
    )
    assert code == 0


def test_response_validator_skips_when_stop_hook_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)
    code, _, _ = _run_hook(
        response_validator,
        {"transcript_path": "missing.jsonl", "stop_hook_active": True},
        monkeypatch,
    )
    assert code == 0


def test_response_validator_allows_without_score_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _write_transcript(
        tmp_path,
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    data_dir = _mk_data_dir(tmp_path)
    _set_data_dir_env(monkeypatch, data_dir)
    code, _, _ = _run_hook(
        response_validator,
        {"transcript_path": str(transcript), "stop_hook_active": False},
        monkeypatch,
    )
    assert code == 0
