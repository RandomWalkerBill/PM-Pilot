import json
import shutil
import sys
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

import pmagent.cli as cli
import pytest
import yaml
from pmagent import conflicts, exporter, linker, retrieval, weekly
from pmagent.debate.config import resolve_executor_plan
from pmagent.debate import executors as debate_executors
from pmagent.debate.orchestrator import run_debate, validate_round_content, validate_synthesis
from pmagent.executors import ExecutorResult
from pmagent.current_state import preview_current_state, sync_current_state
from pmagent.observation import executor as observation_executor
from pmagent.observation import runner as observation_runner
from pmagent.readiness import QUALITY_LEVELS, advance_clarifying_readiness


@contextmanager
def _workspace_dir(name: str) -> Iterator[Path]:
    root = Path(".tmp-pmagent-data") / "test-artifacts" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root.resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)


@contextmanager
def _argv(argv: list[str]) -> Iterator[None]:
    previous = sys.argv[:]
    sys.argv = argv
    try:
        yield
    finally:
        sys.argv = previous


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _apply_clarify_answer_with_agent_patch(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    answer: str,
    dimension: str | None = None,
    quality: str = "moderate",
) -> dict:
    assert cli.main(["clarify", "--data-dir", str(data_dir), "status", "--json"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    readiness = status_payload["readiness"]
    target_dimension = dimension or "scope"
    if dimension is None:
        next_readiness = dict(readiness)
        next_readiness["dimensions"] = {
            key: QUALITY_LEVELS.get(quality, QUALITY_LEVELS["moderate"])
            for key in readiness.get("dimensions", {})
        }
        next_readiness["gates"] = {
            "non_goals_resolved": True,
            "decision_boundaries_resolved": True,
        }
        values = [
            float(value)
            for key, value in next_readiness["dimensions"].items()
            if key not in {"non_goals", "decision_boundaries"}
        ]
        next_readiness["score"] = round(sum(values) / len(values), 2) if values else 0.0
        next_readiness["summary"] = "Clarifying scores updated."
        next_readiness["threshold"] = float(next_readiness.get("threshold", 0.80) or 0.80)
    else:
        next_readiness = advance_clarifying_readiness(
            readiness,
            answered_dimension=target_dimension,
            quality=quality,
        )
    all_gates_passed = all(bool(value) for value in next_readiness.get("gates", {}).values())
    transition_recommended = all_gates_passed and float(next_readiness.get("score", 0.0) or 0.0) >= float(next_readiness.get("threshold", 0.80) or 0.80)
    readiness_patch = dict(next_readiness)
    if transition_recommended:
        readiness_patch["transition_recommendation"] = {
            "status": "recommended",
            "to_phase": "researching",
            "step_id": "confirm_start_research",
            "reason": "Clarifying is good enough to enter research, but the system should wait for your confirmation before switching phases.",
        }
    else:
        readiness_patch["transition_recommendation"] = None
    patch = {
        "dimensions": readiness_patch["dimensions"],
        "gates": readiness_patch["gates"],
        "score": readiness_patch["score"],
        "summary": readiness_patch["summary"],
        "reason": f"update {target_dimension}",
    }
    patch_path = data_dir / ".tmp-agent-patch.json"
    _write_json(patch_path, patch)
    assert cli.main(
        [
            "clarify",
            "--data-dir",
            str(data_dir),
            "answer",
            "--answer",
            answer,
            "--json",
        ]
    ) == 0
    capsys.readouterr()
    assert cli.main(
        [
            "clarify",
            "--data-dir",
            str(data_dir),
            "set-scores",
            "--patch-file",
            str(patch_path),
            "--json",
        ]
    ) == 0
    return json.loads(capsys.readouterr().out)


def _seed_projects_config(data_dir: Path, *, active_project: str = "demo", active_workspace: str = "demo") -> None:
    _write_json(
        data_dir / "config" / "projects.json",
        {
            "active_project": active_project,
            "active_workspace": active_workspace,
            "projects_root": "projects",
            "workspace_root": "workspaces",
            "projects": {
                active_project: {
                    "description": "demo project",
                    "workspaces": [active_workspace],
                }
            },
        },
    )


def test_retrieve_bm25_uses_active_project_scope(monkeypatch, capsys):
    monkeypatch.setattr(retrieval, "_HAS_JIEBA", False)

    with _workspace_dir("retrieve-bm25") as data_dir:
        _seed_projects_config(data_dir)
        (data_dir / "memory").mkdir(parents=True, exist_ok=True)
        (data_dir / "memory" / "global-note.md").write_text(
            "# Global\n\nObservation memory baseline.\n",
            encoding="utf-8",
        )
        (data_dir / "projects" / "demo" / "strategy").mkdir(parents=True, exist_ok=True)
        (data_dir / "projects" / "demo" / "strategy" / "2026-04-13-demo-strategy.md").write_text(
            "# Demo Strategy\n\n## 核心价值主张\n\nObservation planning and execution.\n",
            encoding="utf-8",
        )
        (data_dir / "workspaces" / "demo" / "context").mkdir(parents=True, exist_ok=True)
        (data_dir / "workspaces" / "demo" / "context" / "2026-04-13-context.md").write_text(
            "# Context\n\nObservation executor details.\n",
            encoding="utf-8",
        )

        with _argv(
                [
                    "pmagent.retrieval",
                    "--repo-root",
                    str(data_dir),
                    "--query",
                    "observation",
                    "--mode",
                    "bm25",
                    "--top-k",
                    "5",
                "--include-memory-index",
            ]
        ):
            assert retrieval.main() == 0

        output = capsys.readouterr().out
        assert "projects/demo/strategy" in output
        assert "workspaces/demo/context" in output
        assert "2026-04-13-demo-strategy.md" in output or "2026-04-13-context.md" in output


def test_preview_current_state_infers_debate_snapshot_from_files():
    with _workspace_dir("debate-current-state") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        debates_root = ws_root / "context" / "debates"
        completed_topic = debates_root / "2026-04-22-topic-a"
        running_topic = debates_root / "2026-04-22-topic-b"
        reviewed_topic = debates_root / "2026-04-22-topic-c"
        failed_topic = debates_root / "2026-04-22-topic-d"
        for topic in (completed_topic, running_topic, reviewed_topic, failed_topic):
            topic.mkdir(parents=True, exist_ok=True)

        _write_json(completed_topic / "status.json", {"state": "completed"})
        _write_json(running_topic / "status.json", {"state": "round-1-running"})
        _write_json(reviewed_topic / "status.json", {"state": "completed"})
        _write_json(reviewed_topic / "review.json", {"status": "accepted"})
        _write_json(failed_topic / "status.json", {"state": "failed"})
        _write_json(failed_topic / "signal.json", {"event": "failed", "action_needed": "inspect_failure"})

        state = preview_current_state(data_dir, workspace)

        assert state["debates"]["active_count"] == 1
        assert state["debates"]["completed_awaiting_review_count"] == 1
        assert state["debates"]["failed_count"] == 1
        assert state["debates"]["failed_topics"] == ["2026-04-22-topic-d"]
        assert state["debates"]["latest_topic"] in {
            "2026-04-22-topic-a",
            "2026-04-22-topic-b",
            "2026-04-22-topic-c",
            "2026-04-22-topic-d",
        }
        assert state["debates"]["latest_failed_topic"] == "2026-04-22-topic-d"
        assert state["debate_review"]["completed_awaiting_review_count"] == 1
        assert state["debate_review"]["awaiting_review_topics"] == ["2026-04-22-topic-a"]


def test_preview_current_state_counts_round_three_running_as_active():
    with _workspace_dir("debate-current-state-round3") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        topic = ws_root / "context" / "debates" / "2026-04-22-topic-round3"
        topic.mkdir(parents=True, exist_ok=True)
        _write_json(topic / "status.json", {"state": "round-3-running"})

        state = preview_current_state(data_dir, workspace)
        assert state["debates"]["active_count"] == 1


def test_preview_current_state_strips_legacy_mode_fields():
    with _workspace_dir("legacy-mode-state") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        state_path = data_dir / "workspaces" / workspace / ".pmagent" / "current-state.json"
        _write_json(
            state_path,
            {
                "mode": "zero-to-one",
                "route_mode": "setup",
                "mode_skill_path": "skills/modes/zero-to-one/skill.md",
                "phase": "clarifying",
                "active_step": "write-requirement",
            },
        )

        state = preview_current_state(data_dir, workspace)

        assert "mode" not in state
        assert "route_mode" not in state
        assert "mode_skill_path" not in state
        assert state["phase"] == "clarifying"
        assert state["recommended_skills"][0]["id"] == "write-requirement"


def test_debate_start_precheck_failure_does_not_create_topic_dir(monkeypatch):
    with _workspace_dir("debate-precheck-failure") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        monkeypatch.setattr(
            "pmagent.cli_debate.precheck_executor_plan",
            lambda plan: [{"role": "defender", "issue": "missing_cli", "message": "defender executor `claude` is not installed or not on PATH"}],
        )

        topic_name = "2026-04-22-should-we-ship"
        with pytest.raises(SystemExit, match="precheck failed"):
            cli.main(
                [
                    "debate",
                    "--data-dir",
                    str(data_dir),
                    "start",
                    "--workspace",
                    workspace,
                    "--thesis",
                    "Should we ship?",
                    "--topic-slug",
                    "should-we-ship",
                    "--axis",
                    "speed vs quality",
                ]
            )

        topic_dir = ws_root / "context" / "debates" / topic_name
        assert not topic_dir.exists()
        state = preview_current_state(data_dir, workspace)
        assert state["debate_launch"]["active"] is True


def test_debate_start_defaults_to_background_worker(monkeypatch, capsys):
    with _workspace_dir("debate-background-start") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        monkeypatch.setattr("pmagent.cli_debate.precheck_executor_plan", lambda plan: [])
        monkeypatch.setattr("pmagent.cli_debate._launch_background_worker", lambda data_dir, workspace, topic_name, topic_dir: 4321)

        def fail_if_called(**kwargs):
            raise AssertionError("run_debate should not run in foreground by default")

        monkeypatch.setattr("pmagent.cli_debate.run_debate", fail_if_called)

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "start",
                "--workspace",
                workspace,
                "--thesis",
                "Should we ship?",
                "--topic-slug",
                "should-we-ship",
                "--axis",
                "speed vs quality",
                "--json",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["state"] == "running"
        assert payload["background"] is True
        assert payload["pid"] == 4321
        topic_dir = ws_root / "context" / "debates" / f"{date.today().isoformat()}-should-we-ship"
        assert (topic_dir / "run.json").exists()
        assert json.loads((topic_dir / "status.json").read_text(encoding="utf-8"))["state"] == "running"


def test_debate_start_syncs_active_topic_before_foreground_worker_completes(monkeypatch, capsys):
    with _workspace_dir("debate-foreground-active-sync") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        def fake_run_debate(**kwargs):
            topic_dir: Path = kwargs["topic_dir"]
            current = json.loads((ws_root / ".pmagent" / "current-state.json").read_text(encoding="utf-8"))
            assert current["debates"]["active_count"] == 1
            (topic_dir / "synthesis.md").write_text("# Debate Synthesis: topic\n", encoding="utf-8")
            _write_json(topic_dir / "status.json", {"state": "completed", "round": 0})
            _write_json(topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})
            return {"round_count": 1}

        monkeypatch.setattr("pmagent.cli_debate.run_debate", fake_run_debate)

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "start",
                "--workspace",
                workspace,
                "--thesis",
                "Should we ship?",
                "--topic-slug",
                "should-we-ship",
                "--axis",
                "speed vs quality",
                "--foreground",
                "--json",
            ]
        ) == 0
        capsys.readouterr()
        current = json.loads((ws_root / ".pmagent" / "current-state.json").read_text(encoding="utf-8"))
        assert current["debates"]["active_count"] == 0
        assert current["debates"]["completed_awaiting_review_count"] == 1


def test_debate_status_refreshes_current_state_from_topic_files(capsys):
    with _workspace_dir("debate-status-current-state-sync") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        topic_dir = ws_root / "context" / "debates" / "2026-04-22-running-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)
        _write_json(topic_dir / "status.json", {"state": "synthesizing"})
        _write_json(topic_dir / "signal.json", {"event": "round_completed"})
        _write_json(ws_root / ".pmagent" / "current-state.json", {"schema_version": 1, "workspace": workspace, "debates": {"active_count": 0}})

        assert cli.main(["debate", "--data-dir", str(data_dir), "status", "--workspace", workspace, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        current = json.loads((ws_root / ".pmagent" / "current-state.json").read_text(encoding="utf-8"))

        assert payload["count"] == 1
        assert payload["topics"][0]["state"] == "synthesizing"
        assert current["debates"]["active_count"] == 1
        assert current["debates"]["latest_topic"] == "2026-04-22-running-topic"


def test_debate_start_runtime_failure_mentions_debate_executor_config(monkeypatch):
    with _workspace_dir("debate-runtime-config-hint") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        def fake_run_debate(**kwargs):
            raise RuntimeError("model `foo` is unavailable")

        monkeypatch.setattr("pmagent.cli_debate.run_debate", fake_run_debate)

        with pytest.raises(SystemExit, match="config/debate-executors.yaml"):
            cli.main(
                [
                    "debate",
                    "--data-dir",
                    str(data_dir),
                    "start",
                    "--workspace",
                    workspace,
                    "--thesis",
                    "Should we ship?",
                    "--topic-slug",
                    "should-we-ship",
                    "--axis",
                    "speed vs quality",
                    "--pro-exec",
                    "claude",
                    "--con-exec",
                    "claude",
                    "--synth-exec",
                    "claude",
                    "--foreground",
                ]
            )


def test_debate_start_preserves_inner_failed_round_metadata(monkeypatch):
    with _workspace_dir("debate-failure-round-preserved") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        def fake_run_debate(**kwargs):
            topic_dir: Path = kwargs["topic_dir"]
            _write_json(topic_dir / "status.json", {"state": "failed", "round": 1, "error": "inner-fail"})
            _write_json(topic_dir / "signal.json", {"event": "failed", "round": 1, "action_needed": "inspect_failure", "reason": "inner-fail"})
            raise RuntimeError("outer-fail")

        monkeypatch.setattr("pmagent.cli_debate.run_debate", fake_run_debate)

        with pytest.raises(SystemExit):
            cli.main(
                [
                    "debate",
                    "--data-dir",
                    str(data_dir),
                    "start",
                    "--workspace",
                    workspace,
                    "--thesis",
                    "Should we ship?",
                    "--topic-slug",
                    "should-we-ship",
                    "--axis",
                    "speed vs quality",
                    "--pro-exec",
                    "claude",
                    "--con-exec",
                    "claude",
                    "--synth-exec",
                    "claude",
                    "--foreground",
                ]
            )

        topic_dir = ws_root / "context" / "debates" / f"{date.today().isoformat()}-should-we-ship"
        status_payload = json.loads((topic_dir / "status.json").read_text(encoding="utf-8"))
        signal_payload = json.loads((topic_dir / "signal.json").read_text(encoding="utf-8"))
        assert status_payload["round"] == 1
        assert signal_payload["round"] == 1


def test_start_and_resume_surface_pending_debate_review(monkeypatch, capsys):
    with _workspace_dir("debate-start-resume-review") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        topic_dir = ws_root / "context" / "debates" / "2026-04-22-topic-a"
        topic_dir.mkdir(parents=True, exist_ok=True)
        _write_json(topic_dir / "status.json", {"state": "completed"})
        _write_json(topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})

        assert cli.main(["start", "--data-dir", str(data_dir), "--json"]) == 0
        start_payload = json.loads(capsys.readouterr().out)
        assert start_payload["guided_view"] == "debate-review"
        assert start_payload["payload"]["topics"] == ["2026-04-22-topic-a"]

        assert cli.main(["resume", "--data-dir", str(data_dir), "--json"]) == 0
        resume_payload = json.loads(capsys.readouterr().out)
        assert resume_payload["guided_view"] == "debate-review"
        assert resume_payload["payload"]["topics"] == ["2026-04-22-topic-a"]


def test_debate_start_status_show_review_and_resolve(monkeypatch, capsys):
    with _workspace_dir("debate-cli-flow") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")

        def fake_run_debate(**kwargs):
            topic_dir: Path = kwargs["topic_dir"]
            (topic_dir / "synthesis.md").write_text("# Debate Synthesis: topic\n\n## Thesis\nx\n\n## Chosen Axis\ny\n\n## Convergence\n- z\n\n## Core Divergences\n- Defender 立场\n- Attacker 立场\n- 人需要裁决的判断\n\n## Unexpected Findings\n-\n\n## Acknowledgements / Adjustments\n-\n\n## Quality Flags\n-\n\n## Recommended Next Action\n- keep current direction\n", encoding="utf-8")
            _write_json(topic_dir / "status.json", {"state": "completed", "round": 2})
            _write_json(topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})
            _write_json(topic_dir / "context-manifest.json", {"ok": True})
            return {"round_count": 3}

        monkeypatch.setattr("pmagent.cli_debate.run_debate", fake_run_debate)

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "start",
                "--workspace",
                workspace,
                "--thesis",
                "Should we prioritize validation speed or product completeness?",
                "--topic-slug",
                "mvp-vs-complete-experience",
                "--axis",
                "validation speed vs product completeness",
                "--foreground",
                "--json",
            ]
        ) == 0
        start_payload = json.loads(capsys.readouterr().out)
        topic = start_payload["topic"]
        topic_dir = ws_root / "context" / "debates" / topic
        assert topic_dir.exists()
        assert json.loads((topic_dir / "axis.json").read_text(encoding="utf-8"))["chosen_axis"] == "validation speed vs product completeness"

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "status",
                "--workspace",
                workspace,
                "--json",
            ]
        ) == 0
        status_payload = json.loads(capsys.readouterr().out)
        assert status_payload["count"] == 1
        assert status_payload["topics"][0]["topic"] == topic

        synthesis_path = topic_dir / "synthesis.md"
        synthesis_path.write_text("# Synthesis\n\nReady for review.\n", encoding="utf-8")
        (topic_dir / "round-0-pro.md").write_text("# Round 0 Pro\n\nFirst defender round.\n", encoding="utf-8")
        _write_json(topic_dir / "status.json", {"state": "completed"})
        _write_json(topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "show",
                "--workspace",
                workspace,
                "--topic",
                topic,
                "--synthesis",
            ]
        ) == 0
        assert "Ready for review." in capsys.readouterr().out

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "show",
                "--workspace",
                workspace,
                "--topic",
                topic,
                "--round",
                "1",
                "--side",
                "defender",
            ]
        ) == 0
        assert "First defender round." in capsys.readouterr().out

        with pytest.raises(SystemExit, match="1-indexed"):
            cli.main(
                [
                    "debate",
                    "--data-dir",
                    str(data_dir),
                    "show",
                    "--workspace",
                    workspace,
                    "--topic",
                    topic,
                    "--round",
                    "0",
                ]
            )

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "review",
                "--workspace",
                workspace,
                "--topic",
                topic,
                "--json",
            ]
        ) == 0
        review_payload = json.loads(capsys.readouterr().out)
        assert review_payload["debate_review"]["active"] is True
        assert review_payload["debate_review"]["awaiting_review_topics"] == [topic]

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "resolve",
                "--workspace",
                workspace,
                "--topic",
                topic,
                "--accepted",
                "--json",
            ]
        ) == 0
        resolve_payload = json.loads(capsys.readouterr().out)
        assert resolve_payload["status"] == "accepted"
        assert json.loads((topic_dir / "review.json").read_text(encoding="utf-8"))["status"] == "accepted"
        signal_payload = json.loads((topic_dir / "signal.json").read_text(encoding="utf-8"))
        assert signal_payload["action_needed"] is None

        state = preview_current_state(data_dir, workspace)
        assert state["debates"]["completed_awaiting_review_count"] == 0

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "status",
                "--workspace",
                workspace,
                "--topic",
                topic,
                "--json",
            ]
        ) == 0
        topic_status_payload = json.loads(capsys.readouterr().out)
        assert topic_status_payload["topic"]["review_status"] == "accepted"
        assert topic_status_payload["topic"]["action_needed"] is None


def test_debate_review_rejects_resolved_topic(monkeypatch):
    with _workspace_dir("debate-review-rejects-resolved") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        topic_dir = ws_root / "context" / "debates" / "2026-04-22-topic-a"
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "synthesis.md").write_text("# Debate Synthesis: topic\n", encoding="utf-8")
        _write_json(topic_dir / "review.json", {"status": "accepted"})

        with pytest.raises(SystemExit, match="already resolved"):
            cli.main(
                [
                    "debate",
                    "--data-dir",
                    str(data_dir),
                    "review",
                    "--workspace",
                    workspace,
                    "--topic",
                    "2026-04-22-topic-a",
                ]
            )


def test_debate_resolve_only_removes_one_topic_from_review_queue(capsys):
    with _workspace_dir("debate-resolve-single-topic") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        for topic in ("2026-04-22-topic-a", "2026-04-22-topic-b"):
            topic_dir = ws_root / "context" / "debates" / topic
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "synthesis.md").write_text("# Debate Synthesis: topic\n", encoding="utf-8")
            _write_json(topic_dir / "status.json", {"state": "completed"})
            _write_json(topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})

        sync_current_state(
            data_dir,
            workspace,
            patch={"debate_review": {"active": True, "awaiting_review_topics": ["2026-04-22-topic-a", "2026-04-22-topic-b"]}},
            updated_by="test-seed-debate-review",
        )

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "resolve",
                "--workspace",
                workspace,
                "--topic",
                "2026-04-22-topic-a",
                "--accepted",
                "--json",
            ]
        ) == 0
        resolve_payload = json.loads(capsys.readouterr().out)
        assert resolve_payload["debate_review"]["active"] is True
        assert resolve_payload["debate_review"]["awaiting_review_topics"] == ["2026-04-22-topic-b"]


def test_debate_start_force_replaces_failed_topic(monkeypatch, capsys):
    with _workspace_dir("debate-cli-force") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        topic = f"{date.today().isoformat()}-ship-it"
        topic_dir = ws_root / "context" / "debates" / topic
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "stale.txt").write_text("stale", encoding="utf-8")
        _write_json(topic_dir / "status.json", {"state": "failed"})
        _write_json(topic_dir / "signal.json", {"event": "failed", "action_needed": "inspect_failure"})

        def fake_run_debate(**kwargs):
            rerun_topic_dir: Path = kwargs["topic_dir"]
            (rerun_topic_dir / "synthesis.md").write_text(
                "# Debate Synthesis: topic\n\n## Thesis\nShould we ship it?\n\n## Chosen Axis\nspeed vs quality\n\n## Convergence\n- z\n\n## Core Divergences\n- scope\n  - Defender 立场: d\n  - Attacker 立场: a\n  - 人需要裁决的判断: j\n\n## Unexpected Findings\n- f\n\n## Acknowledgements / Adjustments\n- a\n\n## Quality Flags\n- q\n\n## Recommended Next Action\nkeep current direction\n",
                encoding="utf-8",
            )
            _write_json(rerun_topic_dir / "status.json", {"state": "completed", "round": 0})
            _write_json(rerun_topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})
            return {"round_count": 1}

        monkeypatch.setattr("pmagent.cli_debate.run_debate", fake_run_debate)

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "start",
                "--workspace",
                workspace,
                "--thesis",
                "Should we ship it?",
                "--topic-slug",
                "ship-it",
                "--axis",
                "speed vs quality",
                "--force",
                "--foreground",
                "--json",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["topic"] == topic
        assert not (topic_dir / "stale.txt").exists()
        assert (topic_dir / "synthesis.md").exists()


def test_debate_start_with_axis_runs_rounds(monkeypatch, capsys):
    with _workspace_dir("debate-run-rounds") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        (ws_root / "Requirement.md").write_text("# Requirement\n\nNeed a better debate process.\n", encoding="utf-8")

        def fake_run_debate(**kwargs):
            topic_dir: Path = kwargs["topic_dir"]
            for name in [
                "round-0-pro.md",
                "round-0-con.md",
                "round-1-pro.md",
                "round-1-con.md",
                "round-2-pro.md",
                "round-2-con.md",
            ]:
                (topic_dir / name).write_text(f"# {name}\n", encoding="utf-8")
            (topic_dir / "synthesis.md").write_text(
                "# Debate Synthesis: topic\n\n## Thesis\nx\n\n## Chosen Axis\ny\n\n## Convergence\n- z\n\n## Core Divergences\n- Defender 立场\n- Attacker 立场\n- 人需要裁决的判断\n\n## Unexpected Findings\n-\n\n## Acknowledgements / Adjustments\n-\n\n## Quality Flags\n-\n\n## Recommended Next Action\n- keep current direction\n",
                encoding="utf-8",
            )
            _write_json(topic_dir / "status.json", {"state": "completed", "round": 2})
            _write_json(topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})
            _write_json(topic_dir / "context-manifest.json", {"ok": True})
            return {"round_count": 3}

        monkeypatch.setattr("pmagent.cli_debate.run_debate", fake_run_debate)

        assert cli.main(
            [
                "debate",
                "--data-dir",
                str(data_dir),
                "start",
                "--workspace",
                workspace,
                "--thesis",
                "Should we prioritize validation speed or product completeness?",
                "--topic-slug",
                "run-now",
                "--axis",
                "validation speed vs product completeness",
                "--synth-exec",
                "claude",
                "--foreground",
                "--json",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        topic = payload["topic"]
        topic_dir = ws_root / "context" / "debates" / topic
        assert (topic_dir / "round-0-pro.md").exists()
        assert (topic_dir / "round-0-con.md").exists()
        assert (topic_dir / "round-1-pro.md").exists()
        assert (topic_dir / "round-1-con.md").exists()
        assert (topic_dir / "round-2-pro.md").exists()
        assert (topic_dir / "round-2-con.md").exists()
        assert (topic_dir / "synthesis.md").exists()
        assert json.loads((topic_dir / "signal.json").read_text(encoding="utf-8"))["event"] == "completed"
        state = preview_current_state(data_dir, workspace)
        assert state["debates"]["completed_awaiting_review_count"] == 1


def test_run_debate_uses_independent_synthesizer():
    with _workspace_dir("debate-orchestrator") as data_dir:
        workspace_root = data_dir / "workspaces" / "alpha"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
        topic_dir = workspace_root / "context" / "debates" / "2026-04-22-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)

        calls: list[tuple[str, str | None]] = []

        class Result:
            def __init__(self, content: str, session_id: str):
                self.content = content
                self.session_id = session_id

        def fake_runner(executor_id: str, prompt: str, *, cwd: Path, session_id: str | None = None, model: str | None = None, schema: dict | None = None, timeout_seconds: float | None = None):
            calls.append((executor_id, session_id))
            if "Debate 记录整理者" in prompt:
                return Result(
                    "# Debate Synthesis: topic\n\n## Thesis\nShould we prioritize validation speed or product completeness?\n\n## Chosen Axis\nvalidation speed vs product completeness\n\n## Convergence\n- both sides want better product outcomes\n\n## Core Divergences\n- scope\n  - Defender 立场: d\n  - Attacker 立场: a\n  - 人需要裁决的判断: j\n\n## Unexpected Findings\n- f\n\n## Acknowledgements / Adjustments\n- (none)\n\n## Quality Flags\n- (none)\n\n## Recommended Next Action\nkeep current direction\n",
                    "synth",
                )
            return Result("## Core Claim\nclaim\n\n## Arguments\n1. arg1\n2. arg2\n\n## Closing Line\nclose\n", session_id or f"{executor_id}-session")

        result = run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
            defender_exec="claude",
            attacker_exec="codex",
            synthesizer_exec="codex",
            executor_runner=fake_runner,
        )
        assert result["round_count"] == 3
        assert calls[-1][0] == "codex"
        assert (topic_dir / "synthesis.md").exists()


def test_run_debate_cleans_duplicate_round_headings_from_payload():
    with _workspace_dir("debate-clean-round-markdown") as data_dir:
        workspace_root = data_dir / "workspaces" / "alpha"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
        topic_dir = workspace_root / "context" / "debates" / "2026-04-22-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)

        class Result:
            def __init__(self, content: str, session_id: str):
                self.content = content
                self.session_id = session_id

        def fake_runner(executor_id: str, prompt: str, *, cwd: Path, session_id: str | None = None, model: str | None = None, schema: dict | None = None, timeout_seconds: float | None = None):
            if "Debate 记录整理者" in prompt:
                return Result(
                    "# Debate Synthesis: topic\n\n## Thesis\nShould we prioritize validation speed or product completeness?\n\n## Chosen Axis\nvalidation speed vs product completeness\n\n## Convergence\n- shared goal\n\n## Core Divergences\n- priority\n  - Defender 立场: d\n  - Attacker 立场: a\n  - 人需要裁决的判断: j\n\n## Unexpected Findings\n- (none)\n\n## Acknowledgements / Adjustments\n- (none)\n\n## Quality Flags\n- (none)\n\n## Recommended Next Action\nrun next\n",
                    "synth",
                )
            return Result(
                "## Core Claim\n## Core Claim\npmagent should move faster\n\n## Arguments\n## Arguments\n1. first reason\n2. second reason\n\n## Closing Line\n## Closing Line\nship the faster path first\n",
                session_id or "sid",
            )

        run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
            defender_exec="codex",
            attacker_exec="codex",
            synthesizer_exec="codex",
            round_count=1,
            executor_runner=fake_runner,
        )

        round_text = (topic_dir / "round-0-pro.md").read_text(encoding="utf-8")
        assert round_text.count("## Core Claim") == 1
        assert round_text.count("## Arguments") == 1
        assert round_text.count("## Closing Line") == 1
        assert "1. first reason" in round_text
        assert "2. second reason" in round_text


def test_run_debate_round_two_prompt_includes_full_history():
    with _workspace_dir("debate-history") as data_dir:
        workspace_root = data_dir / "workspaces" / "alpha"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
        topic_dir = workspace_root / "context" / "debates" / "2026-04-22-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)

        prompts: list[tuple[str, str]] = []
        responses = [
            "## Core Claim\ndefender round 0\n\n## Arguments\n1. defender arg 0\n\n## Closing Line\ndefender close 0\n",
            "## Core Claim\nattacker round 0\n\n## Arguments\n1. attacker arg 0\n\n## Closing Line\nattacker close 0\n",
            "## Core Claim\ndefender round 1\n\n## Arguments\n1. defender arg 1\n\n## Closing Line\ndefender close 1\n",
            "## Core Claim\nattacker round 1\n\n## Arguments\n1. attacker arg 1\n\n## Closing Line\nattacker close 1\n",
            "## Core Claim\ndefender round 2\n\n## Arguments\n1. defender arg 2\n\n## Closing Line\ndefender close 2\n",
            "## Core Claim\nattacker round 2\n\n## Arguments\n1. attacker arg 2\n\n## Closing Line\nattacker close 2\n",
        ]

        class Result:
            def __init__(self, content: str, session_id: str):
                self.content = content
                self.session_id = session_id

        def fake_runner(executor_id: str, prompt: str, *, cwd: Path, session_id: str | None = None, model: str | None = None, schema: dict | None = None, timeout_seconds: float | None = None):
            prompts.append((executor_id, prompt))
            if "Debate 记录整理者" in prompt:
                return Result(
                    "# Debate Synthesis: topic\n\n## Thesis\nShould we prioritize validation speed or product completeness?\n\n## Chosen Axis\nvalidation speed vs product completeness\n\n## Convergence\n- shared goal\n\n## Core Divergences\n- priority\n  - Defender 立场: d\n  - Attacker 立场: a\n  - 人需要裁决的判断: j\n\n## Unexpected Findings\n- (none)\n\n## Acknowledgements / Adjustments\n- (none)\n\n## Quality Flags\n- (none)\n\n## Recommended Next Action\nrun next\n",
                    "synth",
                )
            return Result(responses[len(prompts) - 1], f"session-{len(prompts)}")

        run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
            defender_exec="claude",
            attacker_exec="claude",
            synthesizer_exec="codex",
            round_count=3,
            executor_runner=fake_runner,
        )

        defender_round_two_prompt = prompts[4][1]
        assert "### Round 0" in defender_round_two_prompt
        assert "### Round 1" in defender_round_two_prompt
        assert "defender round 0" in defender_round_two_prompt
        assert "defender round 1" in defender_round_two_prompt
        assert "attacker round 0" in defender_round_two_prompt
        assert "attacker round 1" in defender_round_two_prompt


def test_run_debate_does_not_write_debug_prompt_raw_meta_artifacts():
    with _workspace_dir("debate-no-debug-artifacts") as data_dir:
        workspace_root = data_dir / "workspaces" / "alpha"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
        topic_dir = workspace_root / "context" / "debates" / "2026-04-22-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)

        class Result:
            def __init__(self, content: str, session_id: str):
                self.content = content
                self.session_id = session_id

        def fake_runner(executor_id: str, prompt: str, *, cwd: Path, session_id: str | None = None, model: str | None = None, schema: dict | None = None, timeout_seconds: float | None = None):
            if "Debate 记录整理者" in prompt:
                return Result(
                    "# Debate Synthesis: topic\n\n## Thesis\nShould we prioritize validation speed or product completeness?\n\n## Chosen Axis\nvalidation speed vs product completeness\n\n## Convergence\n- shared goal\n\n## Core Divergences\n- priority\n  - Defender 立场: d\n  - Attacker 立场: a\n  - 人需要裁决的判断: j\n\n## Unexpected Findings\n- f\n\n## Acknowledgements / Adjustments\n- a\n\n## Quality Flags\n- q\n\n## Recommended Next Action\nrun next\n",
                    "synth",
                )
            return Result("立场摘要：x\n1. 论点\n结论：y\n", session_id or "sid")

        run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
            defender_exec="claude",
            attacker_exec="claude",
            synthesizer_exec="claude",
            round_count=1,
            executor_runner=fake_runner,
        )

        assert (topic_dir / "round-0-pro.md").exists()
        assert (topic_dir / "round-0-con.md").exists()
        assert (topic_dir / "synthesis.md").exists()
        assert not list(topic_dir.glob("*.raw.md"))
        assert not list(topic_dir.glob("*.prompt.md"))
        assert not list(topic_dir.glob("*.meta.json"))


def test_run_debate_retry_prompt_requires_exact_headings():
    with _workspace_dir("debate-retry-headings") as data_dir:
        workspace_root = data_dir / "workspaces" / "alpha"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
        topic_dir = workspace_root / "context" / "debates" / "2026-04-22-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)

        claude_prompts: list[str] = []

        class Result:
            def __init__(self, content: str, session_id: str):
                self.content = content
                self.session_id = session_id

        def fake_runner(executor_id: str, prompt: str, *, cwd: Path, session_id: str | None = None, model: str | None = None, schema: dict | None = None, timeout_seconds: float | None = None):
            if executor_id == "claude":
                claude_prompts.append(prompt)
                if len(claude_prompts) == 1:
                    return Result("立场摘要：x\n1. 论点\n结论：y\n", "claude-1")
                return Result("## Core Claim\nx\n\n## Arguments\n1. 论点\n\n## Closing Line\ny\n", "claude-2")
            return Result(
                "# Debate Synthesis: topic\n\n## Thesis\nShould we prioritize validation speed or product completeness?\n\n## Chosen Axis\nvalidation speed vs product completeness\n\n## Convergence\n- shared goal\n\n## Core Divergences\n- priority\n  - Defender 立场: d\n  - Attacker 立场: a\n  - 人需要裁决的判断: j\n\n## Unexpected Findings\n- (none)\n\n## Acknowledgements / Adjustments\n- (none)\n\n## Quality Flags\n- (none)\n\n## Recommended Next Action\nrun next\n",
                "synth",
            )

        run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
            defender_exec="claude",
            attacker_exec="claude",
            synthesizer_exec="codex",
            round_count=1,
            executor_runner=fake_runner,
        )

        assert len(claude_prompts) >= 2
        assert "## Core Claim" in claude_prompts[0]
        assert "## Arguments" in claude_prompts[0]
        assert "## Closing Line" in claude_prompts[0]
        assert "必须严格使用以下三个 heading" in claude_prompts[1]

def test_validate_synthesis_rejects_meta_role_drift():
    with pytest.raises(RuntimeError, match="(thesis must exactly restate|role/meta language)"):
        validate_synthesis(
            """# Debate Synthesis: topic

## Thesis
我会按“Debate 记录整理者”角色工作

## Chosen Axis
角色定位

## Convergence
- 保持中立

## Core Divergences
- 是否参与论证
  - Defender 立场: 你的要求：我是记录整理者
  - Attacker 立场: 辩手角色会主动补充论证
  - 人需要裁决的判断: 采用记录整理者角色

## Unexpected Findings
- 当前消息是角色校准

## Recommended Next Action
把辩论内容发来
""",
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
        )


def test_validate_synthesis_allows_legitimate_provide_phrase():
    validate_synthesis(
        """# Debate Synthesis: topic

## Thesis
Should we prioritize validation speed or product completeness?

## Chosen Axis
validation speed vs product completeness

## Convergence
- shared goal

## Core Divergences
- priority
  - Defender 立场: d
  - Attacker 立场: a
  - 人需要裁决的判断: j

## Unexpected Findings
- f

## Acknowledgements / Adjustments
- a

## Quality Flags
- q

## Recommended Next Action
为 PRD review 提供该辩论的结构化分歧摘要，然后继续裁决。
""",
        thesis="Should we prioritize validation speed or product completeness?",
        axis="validation speed vs product completeness",
    )


def test_validate_synthesis_accepts_heading_style_divergences():
    validate_synthesis(
        """# Debate Synthesis: topic

## Thesis
Should we prioritize validation speed or product completeness?

## Chosen Axis
validation speed vs product completeness

## Convergence
- shared goal

## Core Divergences

### 1. PRD 是 debate 的前提，还是 debate 的产物
Defender 立场：PRD 应该在关键分歧被显化和收敛后再写。
Attacker 立场：PRD 必须先提供一个可攻击的文本锚点。
人需要裁决的判断：PRD 更适合做前提还是沉淀物。

### 2. 澄清阶段应该先暴露分歧还是先形成草案
Defender 立场：先暴露上游分歧。
Attacker 立场：先形成最小草案。
人需要裁决的判断：哪种顺序更能缩短总决策周期。

## Unexpected Findings
- f

## Acknowledgements / Adjustments
- a

## Quality Flags
- q

## Recommended Next Action
先选择 debate 触发规则，再继续推进 PRD。
""",
        thesis="Should we prioritize validation speed or product completeness?",
        axis="validation speed vs product completeness",
    )


def test_validate_round_content_rejects_meta_placeholders():
    with pytest.raises(RuntimeError, match="meta language"):
        validate_round_content(
            """## Core Claim
我将以 Debate 中的 defender 身份回应。

## Arguments
1. 我会优先为该方案建立最强论证。
2. 如果你给出辩题或对方论点，我会直接展开。

## Closing Line
把辩题发来。
"""
        )


def test_run_debate_retries_meta_round_output_once():
    with _workspace_dir("debate-orchestrator-retry") as data_dir:
        workspace_root = data_dir / "workspaces" / "alpha"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
        topic_dir = workspace_root / "context" / "debates" / "2026-04-22-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)

        attacker_calls = 0

        class Result:
            def __init__(self, content: str, session_id: str):
                self.content = content
                self.session_id = session_id

        def fake_runner(executor_id: str, prompt: str, *, cwd: Path, session_id: str | None = None, model: str | None = None, schema: dict | None = None, timeout_seconds: float | None = None):
            nonlocal attacker_calls
            if "Debate 记录整理者" in prompt:
                return Result(
                    "# Debate Synthesis: topic\n\n## Thesis\nShould we prioritize validation speed or product completeness?\n\n## Chosen Axis\nvalidation speed vs product completeness\n\n## Convergence\n- shared goal\n\n## Core Divergences\n- priority\n  - Defender 立场: d\n  - Attacker 立场: a\n  - 人需要裁决的判断: j\n\n## Unexpected Findings\n- (none)\n\n## Acknowledgements / Adjustments\n- (none)\n\n## Quality Flags\n- (none)\n\n## Recommended Next Action\nrun the next step\n",
                    "synth",
                )
            if executor_id == "codex":
                attacker_calls += 1
                if attacker_calls == 1:
                    return Result(
                        "## Core Claim\n我将以 Debate 的 attacker 身份行动。\n\n## Arguments\n1. 后续我会优先攻击对方论证中的隐含前提。\n\n## Closing Line\n发送辩题或对方论点。\n",
                        session_id or "attacker-session",
                    )
                return Result(
                    "## Core Claim\n不应该优先产品完整度。\n\n## Arguments\n1. 当前更需要验证核心假设。\n2. 过早补体验会扩大返工面。\n\n## Closing Line\n先验证再扩体验。\n",
                    session_id or "attacker-session",
                )
            return Result(
                "## Core Claim\n应该优先验证速度。\n\n## Arguments\n1. 越早暴露方向错误越好。\n\n## Closing Line\n先验证。\n",
                session_id or "defender-session",
            )

        result = run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
            defender_exec="claude",
            attacker_exec="codex",
            synthesizer_exec="codex",
            round_count=1,
            executor_runner=fake_runner,
        )

        assert result["round_count"] == 1
        assert attacker_calls == 2
        attacker_text = (topic_dir / "round-0-con.md").read_text(encoding="utf-8")
        assert "发送辩题" not in attacker_text
        assert "不应该优先产品完整度。" in attacker_text


def test_run_debate_writes_synthesis_without_format_validation():
    with _workspace_dir("debate-orchestrator-synthesis-no-validation") as data_dir:
        workspace_root = data_dir / "workspaces" / "alpha"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
        topic_dir = workspace_root / "context" / "debates" / "2026-04-22-topic"
        topic_dir.mkdir(parents=True, exist_ok=True)

        class Result:
            def __init__(self, content: str, session_id: str):
                self.content = content
                self.session_id = session_id

        def fake_runner(executor_id: str, prompt: str, *, cwd: Path, session_id: str | None = None, model: str | None = None, schema: dict | None = None, timeout_seconds: float | None = None):
            if "Debate 记录整理者" in prompt:
                return Result("# not a synthesis\n", "synth")
            return Result("## Core Claim\nclaim\n\n## Arguments\n1. arg1\n\n## Closing Line\nclose\n", session_id or f"{executor_id}-session")

        run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should we prioritize validation speed or product completeness?",
            axis="validation speed vs product completeness",
            defender_exec="claude",
            attacker_exec="codex",
            synthesizer_exec="claude",
            executor_runner=fake_runner,
        )

        status_payload = json.loads((topic_dir / "status.json").read_text(encoding="utf-8"))
        signal_payload = json.loads((topic_dir / "signal.json").read_text(encoding="utf-8"))
        assert status_payload["state"] == "completed"
        assert signal_payload["event"] == "completed"
        assert "synthesis_warning" not in signal_payload
        assert (topic_dir / "synthesis.md").read_text(encoding="utf-8") == "# not a synthesis\n"
        assert not (topic_dir / "synthesis.validation-warning.json").exists()


def test_precheck_executor_plan_rejects_unknown_exec():
    issues = debate_executors.precheck_executor_plan(
        {
            "defender": {"exec": "claude", "model": None},
            "attacker": {"exec": "weirdcli", "model": None},
            "synthesizer": {"exec": "codex", "model": None},
        }
    )
    assert any(item["issue"] == "unsupported_exec" for item in issues)


def test_default_debate_executor_plan_prefers_claude_only(tmp_path: Path):
    plan = resolve_executor_plan(tmp_path)
    assert plan == {
        "defender": {"exec": "claude", "model": None},
        "attacker": {"exec": "claude", "model": None},
        "synthesizer": {"exec": "claude", "model": None},
    }


def test_newest_codex_session_filters_by_cwd(tmp_path: Path, monkeypatch):
    sessions_root = tmp_path / ".codex" / "sessions" / "2026" / "04" / "22"
    sessions_root.mkdir(parents=True, exist_ok=True)
    wanted_cwd = tmp_path / "wanted"
    other_cwd = tmp_path / "other"
    wanted_cwd.mkdir(parents=True, exist_ok=True)
    other_cwd.mkdir(parents=True, exist_ok=True)

    a = sessions_root / "rollout-a.jsonl"
    b = sessions_root / "rollout-b.jsonl"
    a.write_text(json.dumps({"type": "session_meta", "payload": {"id": "sid-a", "cwd": str(other_cwd)}}) + "\n", encoding="utf-8")
    b.write_text(json.dumps({"type": "session_meta", "payload": {"id": "sid-b", "cwd": str(wanted_cwd)}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(debate_executors, "_codex_sessions_root", lambda: sessions_root.parent.parent.parent)

    found = debate_executors._newest_codex_session(after_timestamp=0.0, cwd=wanted_cwd)
    assert found == "sid-b"


def test_run_executor_codex_reads_output_last_message(monkeypatch, tmp_path: Path):
    sessions_root = tmp_path / ".codex" / "sessions" / "2026" / "04" / "22"
    sessions_root.mkdir(parents=True, exist_ok=True)
    session_id = "019db46b-0f77-7fc3-8aa6-bfd9901bb46c"
    session_file = sessions_root / f"rollout-2026-04-22T17-00-08-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"id": session_id}}),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "HELLO FROM CODEX"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(debate_executors, "_codex_sessions_root", lambda: sessions_root.parent.parent.parent)
    monkeypatch.setattr(debate_executors, "which", lambda name: f"C:/fake/{name}.cmd")

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        argv = list(args[0])
        captured["argv"] = argv
        captured["input"] = kwargs.get("input")
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        output_path.write_text("HELLO FROM CODEX", encoding="utf-8")
        return Completed()

    monkeypatch.setattr(debate_executors.subprocess, "run", fake_run)
    monkeypatch.setattr(debate_executors, "_newest_codex_session", lambda after_timestamp=None, cwd=None: session_id)

    result = debate_executors.run_executor("codex", "hello\nworld", cwd=tmp_path)
    assert result.session_id == session_id
    assert result.content == "HELLO FROM CODEX"
    assert list(captured["argv"])[-1] == "-"
    assert captured["input"] == "hello\nworld"
    assert "--output-last-message" in list(captured["argv"])
    assert "--dangerously-bypass-approvals-and-sandbox" not in list(captured["argv"])


def test_run_executor_timeout_raises_clear_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(debate_executors, "which", lambda name: f"C:/fake/{name}.cmd")

    def fake_run(*args, **kwargs):
        raise debate_executors.subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(debate_executors.subprocess, "run", fake_run)

    with pytest.raises(debate_executors.DebateExecutorError, match="timed out"):
        debate_executors.run_executor("claude", "hello", cwd=tmp_path, timeout_seconds=12)


def test_run_executor_codex_resume_omits_output_schema(monkeypatch, tmp_path: Path):
    sessions_root = tmp_path / ".codex" / "sessions" / "2026" / "04" / "22"
    sessions_root.mkdir(parents=True, exist_ok=True)
    session_id = "019db46b-0f77-7fc3-8aa6-bfd9901bb46c"
    session_file = sessions_root / f"rollout-2026-04-22T17-00-08-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"id": session_id}}),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "HELLO AGAIN"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(debate_executors, "_codex_sessions_root", lambda: sessions_root.parent.parent.parent)
    monkeypatch.setattr(debate_executors, "which", lambda name: f"C:/fake/{name}.cmd")

    recorded_argv: list[str] = []
    recorded_input: str | None = None

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, *args, **kwargs):
        nonlocal recorded_argv
        recorded_argv = list(argv)
        output_path = Path(recorded_argv[recorded_argv.index("--output-last-message") + 1])
        output_path.write_text("HELLO AGAIN", encoding="utf-8")
        return Completed()

    monkeypatch.setattr(debate_executors.subprocess, "run", fake_run)

    result = debate_executors.run_executor(
        "codex",
        "hello",
        cwd=tmp_path,
        session_id=session_id,
        schema={"type": "object"},
    )
    assert result.session_id == session_id
    assert result.content == "HELLO AGAIN"
    assert "--output-schema" not in recorded_argv
    assert "--output-last-message" in recorded_argv
    assert recorded_argv[-1] == "-"
    assert "--dangerously-bypass-approvals-and-sandbox" not in recorded_argv


def test_run_executor_claude_uses_full_access_flags(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(debate_executors, "which", lambda name: f"C:/fake/{name}.cmd")

    recorded_argv: list[str] = []
    recorded_input: str | None = None

    class Completed:
        returncode = 0
        stdout = "HELLO FROM CLAUDE"
        stderr = ""

    def fake_run(argv, *args, **kwargs):
        nonlocal recorded_argv, recorded_input
        recorded_argv = list(argv)
        recorded_input = kwargs.get("input")
        return Completed()

    monkeypatch.setattr(debate_executors.subprocess, "run", fake_run)

    result = debate_executors.run_executor(
        "claude",
        "hello",
        cwd=tmp_path,
        schema={"type": "object"},
    )
    assert result.content == "HELLO FROM CLAUDE"
    assert recorded_input == "hello"
    assert "hello" not in recorded_argv
    assert "--dangerously-skip-permissions" not in recorded_argv
    assert "--json-schema" in recorded_argv


def test_claude_executor_auto_sets_git_bash_env_on_windows(monkeypatch, tmp_path: Path):
    git_root = tmp_path / "Git"
    git_cmd = git_root / "cmd"
    git_bin = git_root / "bin"
    git_cmd.mkdir(parents=True, exist_ok=True)
    git_bin.mkdir(parents=True, exist_ok=True)
    (git_cmd / "git.exe").write_text("", encoding="utf-8")
    bash_path = git_bin / "bash.exe"
    bash_path.write_text("", encoding="utf-8")

    def fake_which(name: str):
        if name == "claude":
            return "C:/fake/claude.cmd"
        if name == "git":
            return str(git_cmd / "git.exe")
        return None

    monkeypatch.setattr(debate_executors.sys, "platform", "win32")
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr(debate_executors, "which", fake_which)

    captured_env: dict[str, str] = {}

    class Completed:
        returncode = 0
        stdout = "HELLO"
        stderr = ""

    def fake_run(argv, *args, **kwargs):
        nonlocal captured_env
        captured_env = kwargs.get("env") or {}
        return Completed()

    monkeypatch.setattr(debate_executors.subprocess, "run", fake_run)

    result = debate_executors.run_executor("claude", "hello", cwd=tmp_path)
    assert result.content == "HELLO"
    assert captured_env["CLAUDE_CODE_GIT_BASH_PATH"] == str(bash_path)


def test_claude_precheck_reports_missing_git_bash_on_windows(monkeypatch):
    monkeypatch.setattr(debate_executors.sys, "platform", "win32")
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr(debate_executors, "which", lambda name: "C:/fake/claude.cmd" if name == "claude" else None)
    monkeypatch.setattr(debate_executors, "_discover_git_bash", lambda: None)

    issues = debate_executors.precheck_executor_plan({"defender": {"exec": "claude", "model": None}})
    assert any(item["issue"] == "missing_git_bash" for item in issues)


def test_next_and_review_surface_pending_debate_review(capsys):
    with _workspace_dir("debate-review-routing") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        (data_dir / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        topic_dir = ws_root / "context" / "debates" / "2026-04-22-topic-a"
        topic_dir.mkdir(parents=True, exist_ok=True)
        _write_json(topic_dir / "status.json", {"state": "completed"})
        _write_json(topic_dir / "signal.json", {"event": "completed", "action_needed": "review_synthesis"})
        sync_current_state(
            data_dir,
            workspace,
            patch={
                "phase": "clarifying",
                "active_step": "write-requirement",
                "pending_user_decision": "scope-confirmation",
            },
            updated_by="test-seed-observation-checkpoint",
        )

        assert cli.main(["next", "--data-dir", str(data_dir), "--json"]) == 0
        next_payload = json.loads(capsys.readouterr().out)
        assert next_payload["view"] == "debate-review"
        assert next_payload["payload"]["topics"] == ["2026-04-22-topic-a"]

        assert cli.main(["review", "--data-dir", str(data_dir), "--json"]) == 0
        review_payload = json.loads(capsys.readouterr().out)
        assert review_payload["view"] == "debate-review"
        assert review_payload["payload"]["topics"] == ["2026-04-22-topic-a"]


def test_next_and_review_surface_failed_debate_before_normal_flow(monkeypatch, capsys):
    with _workspace_dir("debate-failure-routing") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        topic_dir = ws_root / "context" / "debates" / "2026-04-22-topic-failed"
        topic_dir.mkdir(parents=True, exist_ok=True)
        _write_json(topic_dir / "status.json", {"state": "failed"})
        _write_json(topic_dir / "signal.json", {"event": "failed", "action_needed": "inspect_failure"})
        monkeypatch.setattr("pmagent.cli_routing._observation_checkpoint_payload", lambda data_dir, payload: None)

        assert cli.main(["next", "--data-dir", str(data_dir), "--json"]) == 0
        next_payload = json.loads(capsys.readouterr().out)
        assert next_payload["view"] == "debate-failure"
        assert next_payload["payload"]["topics"] == ["2026-04-22-topic-failed"]

        assert cli.main(["review", "--data-dir", str(data_dir), "--json"]) == 0
        review_payload = json.loads(capsys.readouterr().out)
        assert review_payload["view"] == "debate-failure"
        assert review_payload["payload"]["topics"] == ["2026-04-22-topic-failed"]


def test_next_and_resume_surface_debate_launch_pending(monkeypatch, capsys):
    with _workspace_dir("debate-launch-routing") as data_dir:
        workspace = "alpha-observe"
        _seed_projects_config(data_dir, active_project="alpha", active_workspace=workspace)
        ws_root = data_dir / "workspaces" / workspace
        (ws_root / ".pmagent").mkdir(parents=True, exist_ok=True)
        (ws_root / "workspace-summary.md").write_text("# summary\n", encoding="utf-8")
        sync_current_state(
            data_dir,
            workspace,
            patch={
                "debate_launch": {
                    "active": True,
                    "reason": "defender executor `claude` is not installed or not on PATH",
                    "thesis": "Should we ship?",
                    "axis": "speed vs quality",
                    "topic_slug": "should-we-ship",
                    "executors": {"defender": {"exec": "claude", "model": None}},
                    "config_path": "config/debate-executors.yaml",
                }
            },
            updated_by="test-debate-launch-pending",
        )
        monkeypatch.setattr("pmagent.cli_routing._observation_checkpoint_payload", lambda data_dir, payload: None)

        assert cli.main(["next", "--data-dir", str(data_dir), "--json"]) == 0
        next_payload = json.loads(capsys.readouterr().out)
        assert next_payload["view"] == "debate-launch"
        assert next_payload["payload"]["topic_slug"] == "should-we-ship"

        assert cli.main(["resume", "--data-dir", str(data_dir), "--json"]) == 0
        resume_payload = json.loads(capsys.readouterr().out)
        assert resume_payload["guided_view"] == "debate-launch"
        assert resume_payload["payload"]["topic_slug"] == "should-we-ship"


def test_linker_update_links_is_bidirectional():
    with _workspace_dir("linker-links") as data_dir:
        source = data_dir / "workspaces" / "demo" / "prd" / "current.md"
        target = data_dir / "projects" / "demo" / "strategy" / "2026-04-13-demo-strategy.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# PRD\n\n## Related links\n\n", encoding="utf-8")
        target.write_text("# Strategy\n\n## Related links\n\n", encoding="utf-8")

        added, modified = linker.update_links(
            data_dir,
            "workspaces/demo/prd/current.md",
            ["projects/demo/strategy/2026-04-13-demo-strategy.md"],
        )

        assert added >= 1
        assert modified >= 1
        assert "`projects/demo/strategy/2026-04-13-demo-strategy.md`" in source.read_text(encoding="utf-8")
        assert "`workspaces/demo/prd/current.md`" in target.read_text(encoding="utf-8")


def test_conflicts_all_reports_likely_conflict(monkeypatch, capsys):
    monkeypatch.setattr(conflicts, "llm_judge_conflict", lambda *args, **kwargs: None)

    with _workspace_dir("conflicts-all") as data_dir:
        decisions_dir = data_dir / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)
        (decisions_dir / "2026-04-13-allow-automation.md").write_text(
            "# Decision A\n\n## 核心主张\n\n我们支持 automation policy for PM workflow.\n",
            encoding="utf-8",
        )
        (decisions_dir / "2026-04-13-block-automation.md").write_text(
            "# Decision B\n\n## 核心主张\n\n我们反对 automation policy for PM workflow.\n",
            encoding="utf-8",
        )

        with _argv(
            [
                "pmagent.conflicts",
                "--repo-root",
                str(data_dir),
                "--all",
                "--threshold",
                "0.1",
            ]
        ):
            conflicts.main()

        output = capsys.readouterr().out
        assert "2026-04-13-allow-automation.md" in output
        assert "2026-04-13-block-automation.md" in output
        assert "冲突" in output

def test_cli_conflicts_returns_zero_when_module_main_returns_none(monkeypatch):
    monkeypatch.setattr("pmagent.conflicts.main", lambda: None)

    with _workspace_dir("conflicts-cli-return") as data_dir:
        assert cli.main(["conflicts", "--data-dir", str(data_dir), "--all"]) == 0


def test_export_uses_active_project_and_increments_versions(capsys):
    with _workspace_dir("export-active-project") as data_dir:
        _seed_projects_config(data_dir)
        project_root = data_dir / "projects" / "demo"
        workspace_root = data_dir / "workspaces" / "demo"
        (project_root / "strategy").mkdir(parents=True, exist_ok=True)
        (project_root / "decisions").mkdir(parents=True, exist_ok=True)
        (project_root / "memory").mkdir(parents=True, exist_ok=True)
        (workspace_root / "prd").mkdir(parents=True, exist_ok=True)
        (workspace_root / "exports" / "v1").mkdir(parents=True, exist_ok=True)

        (project_root / "strategy" / "2026-04-13-demo-strategy.md").write_text(
            "# Demo Strategy\n\n## 核心价值主张\n\nShip observation support.\n",
            encoding="utf-8",
        )
        (project_root / "decisions" / "2026-04-13-demo-decision.md").write_text(
            "# Demo Decision\n\n## 决策\n\nKeep governance explicit.\n",
            encoding="utf-8",
        )
        (project_root / "memory" / "2026-04-13-demo-memory.md").write_text(
            "# Demo Memory\n\n## 核心主张\n\nObservation matters.\n",
            encoding="utf-8",
        )
        (workspace_root / "prd" / "current.md").write_text("# PRD\n\nCurrent content.\n", encoding="utf-8")

        with _argv(["pmagent.exporter", "--repo-root", str(data_dir)]):
            assert exporter.main() == 0

        output = capsys.readouterr().out
        export_root = workspace_root / "exports" / "v2"
        assert export_root.is_dir()
        assert (export_root / "PRD.md").exists()
        assert (export_root / "DEV_CONTEXT.md").exists()
        assert (export_root / "MANIFEST.md").exists()
        assert "exports\\v2" in output or "exports/v2" in output
        manifest = (export_root / "MANIFEST.md").read_text(encoding="utf-8")
        assert "`workspaces\\demo`" in manifest or "`workspaces/demo`" in manifest


def test_weekly_generates_report_quality_log_and_reindex_call(monkeypatch, capsys):
    recorded_calls: list[tuple[str, list[str]]] = []

    def fake_run_module_main(module, argv):
        recorded_calls.append((module.__name__, list(argv)))
        if module.__name__.endswith("conflicts"):
            out_index = argv.index("--out") + 1
            Path(argv[out_index]).write_text("# Conflict Report\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(weekly, "_run_module_main", fake_run_module_main)

    with _workspace_dir("weekly-routine") as data_dir:
        (data_dir / "memory" / "persona").mkdir(parents=True, exist_ok=True)
        (data_dir / "memory" / "global").mkdir(parents=True, exist_ok=True)
        (data_dir / "memory" / "persona" / "2026-04-13-note.md").write_text("# Persona\n", encoding="utf-8")
        (data_dir / "memory" / "global" / "2026-04-13-note.md").write_text("# Global\n", encoding="utf-8")

        assert weekly.main(["--repo-root", str(data_dir)]) == 0

        output = capsys.readouterr().out
        reports_dir = data_dir / "ops" / "weekly-reports"
        quality_dir = data_dir / "ops" / "quality-log"
        report_files = list(reports_dir.glob("*-conflict-report.md"))
        quality_files = list(quality_dir.glob("*-quality-review.md"))

        assert len(report_files) == 1
        assert len(quality_files) == 1
        assert "PM Agent weekly routine" in output
        assert any(name.endswith("conflicts") for name, _ in recorded_calls)
        assert any(name.endswith("linker") for name, _ in recorded_calls)
        linker_call = next(argv for name, argv in recorded_calls if name.endswith("linker"))
        assert "--all-projects" in linker_call
        assert "--reindex" in linker_call


def test_workspace_init_scaffolds_project_workspace_and_observation(monkeypatch):
    with _workspace_dir("workspace-init") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--description",
                "Alpha project",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--keywords",
                "alpha",
                "market",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0

        project_root = data_dir / "projects" / "alpha"
        workspace_root = data_dir / "workspaces" / "alpha-observe"
        assert (project_root / "PROJECT.md").exists()
        assert (workspace_root / "Requirement.md").exists()
        assert not (workspace_root / "context-log.md").exists()
        assert (workspace_root / "workspace-summary.md").exists()
        assert (workspace_root / ".pmagent" / "current-state.json").exists()
        assert (workspace_root / "candidate-updates").is_dir()
        assert (workspace_root / "maintenance").is_dir()

        config = json.loads((data_dir / "config" / "projects.json").read_text(encoding="utf-8"))
        assert config["active_project"] == "alpha"
        assert config["active_workspace"] == "alpha-observe"
        assert "alpha-observe" in config["projects"]["alpha"]["workspaces"]
        assert config["projects"]["alpha"]["keywords"] == ["alpha", "market"]

        requirement_text = (workspace_root / "Requirement.md").read_text(encoding="utf-8")
        summary_text = (workspace_root / "workspace-summary.md").read_text(encoding="utf-8")
        current_state = json.loads((workspace_root / ".pmagent" / "current-state.json").read_text(encoding="utf-8"))
        assert "Track market changes for alpha." in requirement_text
        assert "Track market changes for alpha." in summary_text
        assert "Current Mode:" not in summary_text
        assert "Confirm the initial scope, non-goals, and delivery boundaries before expanding downstream artifacts." in summary_text
        assert "## Readiness Overview" in summary_text
        assert "- Readiness phase: clarifying" in summary_text
        assert "- Blocking gates: decision_boundaries_resolved, non_goals_resolved" in summary_text
        assert "Observation mode: scheduled" in summary_text
        assert "Cadence: daily" in summary_text
        assert current_state["project"] == "alpha"
        assert current_state["workspace"] == "alpha-observe"
        assert "mode" not in current_state
        assert current_state["phase"] == "clarifying"
        assert current_state["active_step"] == "write-requirement"
        assert current_state["recommended_skills"][0]["id"] == "write-requirement"
        assert current_state["observation"]["enabled"] is True
        assert current_state["observation"]["cadence"] == "daily"
        assert current_state["next_recommended_step"]["id"] == "clarify_scope"
        assert current_state["readiness"]["phase"] == "clarifying"
        assert "target_dimension" not in current_state["readiness"]
        assert current_state["readiness"]["score"] == 0.0


def test_workspace_init_text_output_includes_status_block(monkeypatch, capsys):
    with _workspace_dir("workspace-init-text-guided") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        text = capsys.readouterr().out
        assert "Initialized workspace scaffold: project=alpha, workspace=alpha-observe" in text


def test_workspace_init_normalizes_workspace_name_with_project_prefix(monkeypatch):
    with _workspace_dir("workspace-init-normalize-name") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--confirm-cadence",
            ]
        ) == 0

        assert (data_dir / "workspaces" / "alpha-observe").exists()
        config = json.loads((data_dir / "config" / "projects.json").read_text(encoding="utf-8"))
        assert config["active_workspace"] == "alpha-observe"
        assert "alpha-observe" in config["projects"]["alpha"]["workspaces"]


def test_workspace_init_to_observation_maintenance_flow(monkeypatch, capsys):
    with _workspace_dir("workspace-flow") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        monkeypatch.setattr(
            observation_executor,
            "build_query_plan",
            lambda **_: [{"kind": "market", "query": "alpha market change", "count": 1, "freshness": "pm"}],
        )
        monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: False)
        monkeypatch.setattr(observation_runner, "resolve_available_backend", lambda: "kiro")

        def fake_run_executor(executor_id, prompt, *, cwd, **kwargs):
            assert executor_id == "kiro"
            runs_root = cwd / "observations" / "alpha" / "runs"
            run_root = sorted(path for path in runs_root.iterdir() if path.is_dir())[-1]
            run_id = run_root.name
            findings_path = run_root / "raw-findings.jsonl"
            findings_path.write_text(
                json.dumps(
                    {
                        "kind": "market",
                        "query": "alpha market change",
                        "title": "Alpha competitor launch",
                        "url": "https://example.com/alpha-launch",
                        "description": "New workflow feature",
                        "age": "1d",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            observation_runner.ingest_external(cwd, "alpha", run_id=run_id, findings_path=findings_path)
            return ExecutorResult(content="done", session_id="sid")

        monkeypatch.setattr(observation_runner, "run_executor", fake_run_executor)

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Watch external changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0

        assert cli.main(
            [
                "prd",
                "--data-dir",
                str(data_dir),
                "init-draft",
            ]
        ) == 0
        capsys.readouterr()

        assert cli.main(
            [
                "observe",
                "--data-dir",
                str(data_dir),
                "run",
                "--workspace",
                "alpha-observe",
            ]
        ) == 0
        capsys.readouterr()

        assert cli.main(
            [
                "observe",
                "--data-dir",
                str(data_dir),
                "audit",
                "--workspace",
                "alpha-observe",
                "--json",
            ]
        ) == 0
        audit_payload = json.loads(capsys.readouterr().out)
        assert audit_payload["queue_counts"]["inbox"] == 1

        inbox_card = audit_payload["inbox_cards"][0]
        assert cli.main(
            [
                "observe",
                "--data-dir",
                str(data_dir),
                "accept",
                "--workspace",
                "alpha-observe",
                "--card",
                inbox_card,
            ]
        ) == 0

        assert cli.main(
            [
                "observe",
                "--data-dir",
                str(data_dir),
                "set-cadence",
                "--workspace",
                "alpha-observe",
                "--cadence",
                "weekly",
                "--confirm-cadence",
            ]
        ) == 0

        assert cli.main(
            [
                "observe",
                "--data-dir",
                str(data_dir),
                "draft-maintenance",
                "--workspace",
                "alpha-observe",
            ]
        ) == 0
        workspace_root = data_dir / "workspaces" / "alpha-observe"
        prd_path = workspace_root / "prd" / "current.md"
        prd_text_before = prd_path.read_text(encoding="utf-8")
        assert cli.main(
            [
                "observe",
                "--data-dir",
                str(data_dir),
                "apply-maintenance",
                "--workspace",
                "alpha-observe",
            ]
        ) == 0

        observation_policy = json.loads((data_dir / "observations" / "alpha" / "policy.json").read_text(encoding="utf-8"))
        observation_state = json.loads((data_dir / "observations" / "alpha" / "state.json").read_text(encoding="utf-8"))
        prd_text = (workspace_root / "prd" / "current.md").read_text(encoding="utf-8")
        queue_summary = json.loads((workspace_root / "candidate-updates" / "queue-summary.json").read_text(encoding="utf-8"))
        consumed_cards = list((workspace_root / "maintenance" / "consumed-cards").glob("*.md"))
        changelogs = list((workspace_root / "maintenance" / "changelog").glob("*.md"))

        assert observation_policy["cadence"] == "weekly"
        assert "cadence" not in observation_state
        assert "enabled" not in observation_state
        assert prd_text == prd_text_before
        assert "## Maintenance Update" not in prd_text
        assert queue_summary["counts"]["accepted"] == 0
        assert len(consumed_cards) == 1
        assert len(changelogs) == 1


def test_next_prompts_observation_opt_in_after_workspace_init(monkeypatch, capsys):
    with _workspace_dir("observation-opt-in-init") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
            ]
        ) == 0
        capsys.readouterr()

        assert cli.main(["next", "--data-dir", str(data_dir), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["view"] == "observe-status"
        assert payload["payload"]["decision_status"] == "unresolved"
        checkpoint = payload["payload"]["decision_checkpoint"]
        assert checkpoint["checkpoint"] == "workspace-init"
        assert checkpoint["id"] == "confirm_observation_policy"
        assert checkpoint["enable_command"].endswith("--confirm-cadence")
        assert checkpoint["disable_command"] == "pmagent observe disable --project alpha"


def test_next_rechecks_observation_policy_before_prd_if_still_unresolved(monkeypatch, capsys):
    with _workspace_dir("observation-opt-in-pre-prd") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
            ]
        ) == 0
        capsys.readouterr()

        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "researching",
                "active_step": "do-research",
                "pending_user_decision": None,
                "next_recommended_step": {
                    "id": "write_prd",
                    "reason": "Research readiness is strong enough to move into PRD drafting.",
                },
            },
            updated_by="test-pre-prd-observation-checkpoint",
        )

        assert cli.main(["next", "--data-dir", str(data_dir), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["view"] == "observe-status"
        checkpoint = payload["payload"]["decision_checkpoint"]
        assert checkpoint["checkpoint"] == "pre-prd"
        assert checkpoint["id"] == "confirm_observation_policy"


def test_status_next_and_resume_use_current_state(monkeypatch, capsys):
    with _workspace_dir("status-next-resume") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        capsys.readouterr()

        assert cli.main(["status", "--data-dir", str(data_dir), "--json"]) == 0
        status_payload = json.loads(capsys.readouterr().out)
        assert status_payload["guided_view"] == "status"
        assert status_payload["workspace"] == "alpha-observe"
        assert status_payload["project"] == "alpha"
        assert "mode" not in status_payload["payload"]
        assert status_payload["payload"]["phase"] == "clarifying"
        assert status_payload["next_recommended_step"]["id"] == "clarify_scope"
        assert status_payload["payload"]["readiness"]["phase"] == "clarifying"
        assert "target_dimension" not in status_payload["payload"]["readiness"]
        assert "dimensions" in status_payload["payload"]["readiness"]
        assert "prompt" not in status_payload["payload"]["readiness"]
        assert status_payload["recommended_skills"][0]["id"] == "write-requirement"
        assert status_payload["suggested_command"] == "pmagent clarify status"
        assert status_payload["phase_status_command"] == "pmagent clarify status --workspace alpha-observe --json"

        assert cli.main(["status", "--data-dir", str(data_dir)]) == 0
        status_text = capsys.readouterr().out
        assert "状态概览" in status_text
        assert "Readiness 评分表" in status_text
        assert "| 评分项 | 分数 |" in status_text
        assert "- workspace: alpha-observe" in status_text

        assert cli.main(["next", "--data-dir", str(data_dir), "--json"]) == 0
        next_payload = json.loads(capsys.readouterr().out)
        assert next_payload["guided_view"] == "next"
        assert next_payload["workspace"] == "alpha-observe"
        assert next_payload["next_recommended_step"]["id"] == "clarify_scope"
        assert "scope" in next_payload["next_recommended_step"]["reason"].lower()
        assert next_payload["suggested_command"] == "pmagent clarify status"
        assert next_payload["phase_status_command"] == "pmagent clarify status --workspace alpha-observe --json"

        assert cli.main(["switch", "--data-dir", str(data_dir), "--clear"]) == 0
        capsys.readouterr()
        assert cli.main(
            [
                "resume",
                "--data-dir",
                str(data_dir),
                "--workspace",
                "alpha-observe",
                "--json",
            ]
        ) == 0
        resume_payload = json.loads(capsys.readouterr().out)
        assert resume_payload["guided_view"] == "resume"
        assert resume_payload["workspace"] == "alpha-observe"
        assert resume_payload["project"] == "alpha"
        assert resume_payload["next_recommended_step"]["id"] == "clarify_scope"
        assert resume_payload["phase_status_command"] == "pmagent clarify status --workspace alpha-observe --json"


def test_clarify_status_and_answer_advance_readiness(monkeypatch, capsys):
    with _workspace_dir("clarify-flow") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        capsys.readouterr()

        assert cli.main(["clarify", "--data-dir", str(data_dir), "status", "--json"]) == 0
        status_payload = json.loads(capsys.readouterr().out)
        assert status_payload["readiness"]["phase"] == "clarifying"
        assert "target_dimension" not in status_payload
        assert "prompt" not in status_payload["readiness"]
        assert status_payload["phase_status_command"] == "pmagent clarify status --workspace alpha-observe --json"

        answer_payload = _apply_clarify_answer_with_agent_patch(
            data_dir,
            capsys,
            answer="这轮最小范围只覆盖竞品变化跟踪。\n\n不做自动生成 PRD，先保留人工确认。",
        )
        assert answer_payload["readiness"]["phase"] == "clarifying"
        assert answer_payload["next_recommended_step"]["id"] == "continue_clarifying"

        log_text = (data_dir / "workspaces" / "alpha-observe" / "context" / "clarifying-log.md").read_text(encoding="utf-8")
        assert "response" in log_text
        assert "最小范围只覆盖竞品变化跟踪" in log_text
        assert "不做自动生成 PRD，先保留人工确认。" in log_text


def test_clarify_recommends_research_before_switching_phase(monkeypatch, capsys):
    with _workspace_dir("clarify-transition") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
            ]
        ) == 0
        capsys.readouterr()

        answers = {
            "scope": "首版只覆盖竞品变化跟踪和摘要，不做自动投递。",
            "constraints": "必须保留人工确认，不能自动外投或自动改 PRD。",
            "non_goals": "这轮不做自动生成简历，不做自动发送邮件。",
            "decision_boundaries": "涉及外发、发帖、改 PRD 的动作都必须先问用户。",
            "outcome": "用户输入跟踪对象后，系统输出结构化变化摘要和下一步建议。",
            "intent": "这轮核心是更快发现求职产品变化，减少人工筛查成本。",
            "context": "当前已知背景是用户会周期性跟踪竞品和求职流程变化。",
        }
        for dimension, answer in answers.items():
            _apply_clarify_answer_with_agent_patch(
                data_dir,
                capsys,
                dimension=dimension,
                answer=answer,
            )

        # Under the unified 0.8 threshold, one pass over each dimension is not
        # enough. Keep deepening the weakest thread until the workflow can
        # recommend switching into research.
        for _ in range(12):
            _apply_clarify_answer_with_agent_patch(
                    data_dir,
                    capsys,
                    answer="进一步补充：把范围、限制、成功结果和边界说明得更具体，确保进入 research 前已经足够稳定。",
                    quality="strong",
                )
            assert cli.main(["status", "--data-dir", str(data_dir), "--json"]) == 0
            interim_payload = json.loads(capsys.readouterr().out)
            if interim_payload["payload"]["pending_user_decision"] == "confirm-start-research":
                break

        assert cli.main(["status", "--data-dir", str(data_dir), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        readiness = payload["payload"]["readiness"]
        assert payload["payload"]["phase"] == "clarifying"
        assert payload["payload"]["pending_user_decision"] == "confirm-start-research"
        assert payload["next_recommended_step"]["id"] == "confirm_start_research"
        assert payload["suggested_command"] == "pmagent research start --workspace alpha-observe --json"
        assert readiness["transition_recommendation"]["to_phase"] == "researching"
        assert readiness["score"] >= readiness["threshold"]


def test_research_start_confirms_transition_without_writing_research_log(monkeypatch, capsys):
    with _workspace_dir("research-start-transition") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
            ]
        ) == 0
        capsys.readouterr()

        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "clarifying",
                "active_step": "confirm-transition",
                "pending_user_decision": "confirm-start-research",
                "next_recommended_step": {
                    "id": "confirm_start_research",
                    "reason": "Clarifying is sufficiently grounded. Confirm research start.",
                },
                "readiness": {
                    "phase": "clarifying",
                    "score": 0.88,
                    "threshold": 0.8,
                    "ready": True,
                    "gates": {
                        "non_goals_resolved": True,
                        "decision_boundaries_resolved": True,
                    },
                    "transition_recommendation": {
                        "status": "recommended",
                        "to_phase": "researching",
                        "step_id": "confirm_start_research",
                        "reason": "Clarifying is sufficiently grounded.",
                    },
                },
            },
            updated_by="test",
        )

        assert cli.main(["research", "--data-dir", str(data_dir), "status", "--workspace", "alpha-observe", "--json"]) == 0
        preview_payload = json.loads(capsys.readouterr().out)
        assert preview_payload["preview"] is True
        assert preview_payload["start_command"] == "pmagent research start --workspace alpha-observe --json"

        assert cli.main(["research", "--data-dir", str(data_dir), "start", "--workspace", "alpha-observe", "--json"]) == 0
        start_payload = json.loads(capsys.readouterr().out)
        assert start_payload["status"] == "started"
        assert start_payload["phase"] == "researching"
        assert start_payload["pending_user_decision"] is None
        assert start_payload["next_recommended_step"]["id"] == "continue_research"
        assert not (data_dir / "workspaces" / "alpha-observe" / "research" / "research-log.md").exists()

        assert cli.main(["status", "--data-dir", str(data_dir), "--workspace", "alpha-observe", "--json"]) == 0
        status_payload = json.loads(capsys.readouterr().out)
        assert status_payload["payload"]["phase"] == "researching"
        assert status_payload["payload"]["updated_by"] == "research-start"


def test_requirement_md_is_not_mutated_on_clarifying_to_research_transition(monkeypatch, capsys):
    """Requirement.md is owned by the external Agent. CLI must not mutate it on phase transitions.
    """
    with _workspace_dir("requirement-sync-transition") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
            ]
        ) == 0
        capsys.readouterr()

        requirement_path = data_dir / "workspaces" / "alpha-observe" / "Requirement.md"
        before = requirement_path.read_text(encoding="utf-8")

        for dimension, answer in {
            "scope": "首版只覆盖竞品变化跟踪和摘要，不做自动投递。",
            "constraints": "必须保留人工确认，不能自动外投或自动改 PRD。",
            "non_goals": "这轮不做自动生成简历，不做自动发送邮件。",
            "decision_boundaries": "涉及外发、发帖、改 PRD 的动作都必须先问用户。",
            "outcome": "用户输入跟踪对象后，系统输出结构化变化摘要和下一步建议。",
            "intent": "这轮核心是更快发现求职产品变化，减少人工筛查成本。",
            "context": "当前已知背景是用户会周期性跟踪竞品和求职流程变化。",
        }.items():
            _apply_clarify_answer_with_agent_patch(
                data_dir,
                capsys,
                dimension=dimension,
                answer=answer,
            )

        # Explicitly trigger the clarifying -> researching transition.
        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "researching",
                "active_step": "do-research",
                "pending_user_decision": None,
                "next_recommended_step": {
                    "id": "continue_research",
                    "reason": "Research has started; gather evidence and refine direction.",
                },
            },
            updated_by="test-transition",
        )

        after = requirement_path.read_text(encoding="utf-8")
        # Requirement.md must remain whatever the workspace-init wrote / Agent edited.
        # CLI must not have rewritten any section based on clarifying-log content.
        assert after == before
        # Sanity: workspace-init's seed content (TL;DR) is still there.
        assert "Track market changes for alpha." in after
        # Old sync history line must NOT appear.
        assert "Requirement sync (clarifying-to-researching)" not in after


def test_research_status_and_note_update_research_readiness(monkeypatch, capsys):
    with _workspace_dir("research-flow") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        capsys.readouterr()

        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "researching",
                "active_step": "do-research",
            },
            updated_by="test",
        )

        assert cli.main(["research", "--data-dir", str(data_dir), "status", "--json"]) == 0
        status_payload = json.loads(capsys.readouterr().out)
        assert status_payload["readiness"]["phase"] == "researching"
        assert status_payload["phase_status_command"] == "pmagent research status --workspace alpha-observe --json"
        assert "prompt" not in status_payload["readiness"]

        assert cli.main(
            [
                "research",
                "--data-dir",
                str(data_dir),
                "note",
                "--title",
                "Competitor launch",
                "--summary",
                "Found a new competitor launch with evidence relevant to this workspace.",
                "--source",
                "https://example.com/launch",
                "--json",
            ]
        ) == 0
        note_payload = json.loads(capsys.readouterr().out)
        assert note_payload["workspace"] == "alpha-observe"
        assert note_payload["readiness"]["phase"] == "researching"
        assert note_payload["next_recommended_step"]["id"] == "continue_research"
        log_text = (data_dir / "workspaces" / "alpha-observe" / "research" / "research-log.md").read_text(encoding="utf-8")
        assert "Competitor launch" in log_text
        assert "https://example.com/launch" in log_text
        assert "Found a new competitor launch with evidence relevant to this workspace." in log_text


def test_route_start_and_prd_status_surface_guided_handoff(monkeypatch, capsys):
    with _workspace_dir("route-start-prd") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        capsys.readouterr()

        workspace_root = data_dir / "workspaces" / "alpha-observe"
        (workspace_root / "research").mkdir(parents=True, exist_ok=True)
        (workspace_root / "research" / "2026-04-14-research.md").write_text("# Research\n\nEvidence.\n", encoding="utf-8")
        (workspace_root / "strategy").mkdir(parents=True, exist_ok=True)
        (workspace_root / "strategy" / "2026-04-14-strategy.md").write_text("# Strategy\n\nDirection.\n", encoding="utf-8")
        (workspace_root / "decisions").mkdir(parents=True, exist_ok=True)
        (workspace_root / "decisions" / "2026-04-14-decision.md").write_text("# Decision\n\nKeep focus.\n", encoding="utf-8")
        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "researching",
                "active_step": "do-research",
                "next_recommended_step": {
                    "id": "write_prd",
                    "reason": "Research evidence is sufficient; proceed into PRD drafting.",
                },
            },
            updated_by="test",
        )

        assert cli.main(["route", "--data-dir", str(data_dir), "--json"]) == 0
        route_payload = json.loads(capsys.readouterr().out)
        assert route_payload["guided_view"] == "route"
        assert route_payload["navigation_state"] == "ready"
        assert [item["id"] for item in route_payload["recommended_skills"]] == ["do-research", "write-prd"]
        assert route_payload["handoff_hint"] == "research -> PRD"
        assert route_payload["suggested_command"] == "pmagent prd status"

        assert cli.main(["start", "--data-dir", str(data_dir), "--json"]) == 0
        start_payload = json.loads(capsys.readouterr().out)
        assert start_payload["guided_view"] == "prd-status"
        assert start_payload["navigation_state"] == "ready"
        assert start_payload["next_recommended_step"]["id"] == "write_prd"
        assert start_payload["suggested_command"] == "pmagent prd status"

        assert cli.main(["prd", "--data-dir", str(data_dir), "status", "--json"]) == 0
        prd_payload = json.loads(capsys.readouterr().out)
        assert prd_payload["guided_view"] == "prd-status"
        assert prd_payload["payload"]["prd_status"] == "absent"
        assert "readiness" not in prd_payload["payload"]
        assert prd_payload["next_recommended_step"]["id"] == "write_prd"
        assert cli.main(["start", "--data-dir", str(data_dir)]) == 0
        start_text = capsys.readouterr().out
        assert "Readiness 评分表" not in start_text
        assert "- prd_status: absent" in start_text


def test_prd_init_draft_creates_canonical_prd_and_updates_state(monkeypatch, capsys):
    with _workspace_dir("prd-init-draft") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        capsys.readouterr()
        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "researching",
                "active_step": "do-research",
                "next_recommended_step": {
                    "id": "write_prd",
                    "reason": "Research evidence is sufficient; proceed into PRD drafting.",
                },
            },
            updated_by="test",
        )

        assert cli.main(["prd", "--data-dir", str(data_dir), "init-draft", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["guided_view"] == "prd-init-draft"
        assert payload["workspace"] == "alpha-observe"
        assert payload["payload"]["prd_path"].endswith("workspaces/alpha-observe/prd/current.md")
        assert payload["next_recommended_step"]["id"] == "challenge_prd"
        assert (data_dir / "workspaces" / "alpha-observe" / "prd" / "current.md").exists()

        assert cli.main(["prd", "--data-dir", str(data_dir), "init-draft"]) == 0
        init_draft_text = capsys.readouterr().out
        assert "Readiness 评分表" not in init_draft_text
        assert "- workspace: alpha-observe" in init_draft_text
        assert "- prd_path: workspaces/alpha-observe/prd/current.md" in init_draft_text

        assert cli.main(["prd", "--data-dir", str(data_dir), "review", "--json"]) == 0
        review_payload = json.loads(capsys.readouterr().out)
        assert review_payload["guided_view"] == "prd-review"
        assert review_payload["workspace"] == "alpha-observe"
        assert review_payload["payload"]["prd_status"] == "active"
        assert "readiness" not in review_payload["payload"]
        assert any(option["id"] == "challenge_prd" for option in review_payload["payload"]["downstream_options"])

        assert cli.main(["prd", "--data-dir", str(data_dir), "review"]) == 0
        review_text = capsys.readouterr().out
        assert "Readiness 评分表" not in review_text
        assert "- prd_status: active" in review_text
        assert "- option: challenge_prd" in review_text

        assert cli.main(["prd", "--data-dir", str(data_dir), "challenge", "--json"]) == 0
        challenge_payload = json.loads(capsys.readouterr().out)
        assert challenge_payload["guided_view"] == "prd-challenge"
        assert challenge_payload["workspace"] == "alpha-observe"
        assert challenge_payload["payload"]["challenge_skill_path"] == "skills/steps/challenge-prd/skill.md"
        assert any("scope" in item.lower() for item in challenge_payload["payload"]["checklist"])

        assert cli.main(["prd", "--data-dir", str(data_dir), "challenge"]) == 0
        challenge_text = capsys.readouterr().out
        assert "Readiness 评分表" not in challenge_text
        assert "- challenge_skill_path: skills/steps/challenge-prd/skill.md" in challenge_text
        assert "- checklist: Check whether the current scope still matches the stated goals and non-goals." in challenge_text

        assert cli.main(["review", "--data-dir", str(data_dir), "--json"]) == 0
        generic_review_payload = json.loads(capsys.readouterr().out)
        assert generic_review_payload["view"] == "prd-review"
        assert generic_review_payload["navigation_state"] == "ready"
        assert generic_review_payload["payload"]["workspace"] == "alpha-observe"

        assert cli.main(["review", "--data-dir", str(data_dir)]) == 0
        generic_review_text = capsys.readouterr().out
        assert "Readiness 评分表" not in generic_review_text
        assert "- prd_status: active" in generic_review_text


def test_review_routes_to_phase_specific_surface(monkeypatch, capsys):
    with _workspace_dir("generic-review") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        capsys.readouterr()

        assert cli.main(["review", "--data-dir", str(data_dir), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["view"] == "clarify-status"
        assert payload["navigation_state"] == "ready"
        assert payload["recommended_skills"][0]["id"] == "write-requirement"
        assert payload["payload"]["readiness"]["phase"] == "clarifying"
        assert "target_dimension" not in payload["payload"]


def test_route_and_start_without_active_workspace_return_setup_guidance(capsys):
    with _workspace_dir("route-setup") as data_dir:
        _seed_projects_config(data_dir, active_project="", active_workspace="")
        assert cli.main(["route", "--data-dir", str(data_dir), "--json"]) == 0
        route_payload = json.loads(capsys.readouterr().out)
        assert route_payload["navigation_state"] == "setup"
        assert route_payload["recommended_skills"][0]["id"] == "workspace-init"
        assert route_payload["handoff_hint"] == "setup -> workspace-init"
        assert route_payload["next_recommended_step"]["id"] == "workspace_init"
        assert route_payload["suggested_command"] == "pmagent workspace-init --project <project> --workspace <workspace>"

        assert cli.main(["start", "--data-dir", str(data_dir), "--json"]) == 0
        start_payload = json.loads(capsys.readouterr().out)
        assert start_payload["navigation_state"] == "setup"
        assert start_payload["next_recommended_step"]["id"] == "workspace_init"

        assert cli.main(["status", "--data-dir", str(data_dir), "--json"]) == 0
        status_payload = json.loads(capsys.readouterr().out)
        assert status_payload["navigation_state"] == "setup"

        assert cli.main(["next", "--data-dir", str(data_dir), "--json"]) == 0
        next_payload = json.loads(capsys.readouterr().out)
        assert next_payload["next_recommended_step"]["id"] == "workspace_init"

        assert cli.main(["resume", "--data-dir", str(data_dir), "--json"]) == 0
        resume_payload = json.loads(capsys.readouterr().out)
        assert resume_payload["navigation_state"] == "setup"
        assert cli.main(["review", "--data-dir", str(data_dir), "--json"]) == 0
        review_payload = json.loads(capsys.readouterr().out)
        assert review_payload["navigation_state"] == "setup"
        assert cli.main(["prd", "--data-dir", str(data_dir), "status", "--json"]) == 0
        prd_payload = json.loads(capsys.readouterr().out)
        assert prd_payload["navigation_state"] == "setup"


def test_route_uses_project_prefixed_workspace_name_when_project_is_known(capsys):
    with _workspace_dir("route-project-prefix") as data_dir:
        _seed_projects_config(data_dir, active_project="job-hunt-agent", active_workspace="")
        assert cli.main(["route", "--data-dir", str(data_dir), "--project", "job-hunt-agent", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["navigation_state"] == "setup"
        assert "--workspace job-hunt-agent-discovery" in payload["suggested_command"]


def test_start_can_bootstrap_new_workspace_directly(monkeypatch, capsys):
    with _workspace_dir("start-bootstrap") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "start",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--confirm-cadence",
                "--json",
            ]
        ) == 0
        output = capsys.readouterr().out
        payload = json.loads(output[output.find("{"):])
        assert payload["guided_view"] == "observe-status"
        assert payload["workspace"] == "alpha-observe"
        assert payload["navigation_state"] == "ready"
        assert payload["payload"]["decision_status"] == "unresolved"
        assert payload["payload"]["decision_checkpoint"]["checkpoint"] == "workspace-init"
        assert (data_dir / "workspaces" / "alpha-observe" / "Requirement.md").exists()


def test_status_uses_research_readiness_when_phase_is_researching(monkeypatch, capsys):
    with _workspace_dir("status-research-readiness") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
                "--observation-cadence",
                "daily",
                "--enable-observation",
                "--confirm-cadence",
            ]
        ) == 0
        capsys.readouterr()

        workspace_root = data_dir / "workspaces" / "alpha-observe"
        (workspace_root / "research").mkdir(parents=True, exist_ok=True)
        (workspace_root / "research" / "2026-04-14-research.md").write_text("# Research\n\nEvidence.\n", encoding="utf-8")
        (workspace_root / "strategy").mkdir(parents=True, exist_ok=True)
        (workspace_root / "strategy" / "2026-04-14-strategy.md").write_text("# Strategy\n\nDirection.\n", encoding="utf-8")
        (workspace_root / "decisions").mkdir(parents=True, exist_ok=True)
        (workspace_root / "decisions" / "2026-04-14-decision.md").write_text("# Decision\n\nKeep focus.\n", encoding="utf-8")

        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "researching",
                "active_step": "do-research",
                "next_recommended_step": {
                    "id": "write_strategy",
                    "reason": "Research evidence is accumulating; refine direction and acceptance criteria next.",
                },
            },
            updated_by="test",
        )

        assert cli.main(["status", "--data-dir", str(data_dir), "--workspace", "alpha-observe", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["payload"]["phase"] == "researching"
        assert payload["payload"]["readiness"]["phase"] == "researching"
        assert "target_dimension" not in payload["payload"]["readiness"]
        assert payload["payload"]["readiness"]["dimensions"]["evidence_coverage"] == 0.0
        assert payload["payload"]["readiness"]["dimensions"]["decision_confidence"] == 0.0


def test_status_next_only_and_detail_preserve_front_door_semantics(monkeypatch, capsys):
    with _workspace_dir("status-flags") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
            ]
        ) == 0
        capsys.readouterr()

        assert cli.main(["status", "--data-dir", str(data_dir), "--next-only", "--json"]) == 0
        next_payload = json.loads(capsys.readouterr().out)
        assert next_payload["view"] == "observe-status"
        assert next_payload["payload"]["decision_checkpoint"]["checkpoint"] == "workspace-init"

        assert cli.main(["status", "--data-dir", str(data_dir), "--detail", "--json"]) == 0
        detail_payload = json.loads(capsys.readouterr().out)
        assert detail_payload["view"] == "observe-status"
        assert detail_payload["payload"]["decision_status"] == "unresolved"


def test_status_detail_routes_across_research_and_delivery_views(monkeypatch, capsys):
    with _workspace_dir("status-detail-matrix") as data_dir:
        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --workspace {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-observe",
                "--requirement-summary",
                "Track market changes for alpha.",
            ]
        ) == 0
        capsys.readouterr()

        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "researching",
                "active_step": "do-research",
                "next_recommended_step": {
                    "id": "continue_research",
                    "reason": "Keep collecting evidence.",
                },
            },
            updated_by="test",
        )
        assert cli.main(["status", "--data-dir", str(data_dir), "--detail", "--json"]) == 0
        research_payload = json.loads(capsys.readouterr().out)
        assert research_payload["view"] == "research-status"

        sync_current_state(
            data_dir,
            "alpha-observe",
            patch={
                "phase": "delivery",
                "active_step": "write-prd",
                "next_recommended_step": {
                    "id": "challenge_prd",
                    "reason": "Challenge the PRD before export.",
                },
            },
            updated_by="test",
        )
        assert cli.main(["status", "--data-dir", str(data_dir), "--detail", "--json"]) == 0
        delivery_payload = json.loads(capsys.readouterr().out)
        assert delivery_payload["view"] == "prd-review"


def test_workspace_init_requires_confirm_cadence_for_scheduled_observation():
    with _workspace_dir("workspace-init-confirm") as data_dir:
        with pytest.raises(SystemExit, match="enable_observation|enable-observation"):
            cli.main(
                [
                    "workspace-init",
                    "--data-dir",
                    str(data_dir),
                    "--project",
                    "alpha",
                    "--workspace",
                    "alpha-observe",
                    "--requirement-summary",
                    "Track market changes for alpha.",
                    "--observation-cadence",
                    "daily",
                ]
            )


def test_workspace_init_rejects_enable_observation_with_manual_cadence():
    with _workspace_dir("workspace-init-manual-enable") as data_dir:
        with pytest.raises(SystemExit, match="enable-observation requires a scheduled"):
            cli.main(
                [
                    "workspace-init",
                    "--data-dir",
                    str(data_dir),
                    "--project",
                    "alpha",
                    "--workspace",
                    "alpha-observe",
                    "--requirement-summary",
                    "Track market changes for alpha.",
                    "--observation-cadence",
                    "manual",
                    "--enable-observation",
                    "--confirm-cadence",
                ]
            )
