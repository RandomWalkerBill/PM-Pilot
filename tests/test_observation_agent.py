from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from pmagent.executors import ExecutorError, ExecutorResult
from pmagent.observation import cli as observation_cli
from pmagent.observation import runner as observation_runner


def _seed_repo(repo_root: Path, *, project: str = "alpha", workspace: str = "alpha-observe") -> None:
    (repo_root / "config").mkdir(parents=True, exist_ok=True)
    (repo_root / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": project,
                "active_workspace": workspace,
                "projects": {project: {"workspaces": [workspace]}},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_root / "projects" / project).mkdir(parents=True, exist_ok=True)
    (repo_root / "projects" / project / "PROJECT.md").write_text("# Alpha\n\nTrack alpha market changes.\n", encoding="utf-8")
    (repo_root / "workspaces" / workspace / ".pmagent").mkdir(parents=True, exist_ok=True)


def _run_observation(repo_root: Path, *argv: str) -> int:
    return observation_cli.main(["--repo-root", str(repo_root), *argv])


def _finding_line(title: str = "Competitor launch") -> str:
    return json.dumps(
        {
            "kind": "market",
            "query": "alpha market change",
            "title": title,
            "url": "https://example.com/launch",
            "description": "A relevant external signal.",
            "evidence": [
                {
                    "title": "Example source",
                    "url": "https://example.com/launch",
                    "quote_or_summary": "Source summary.",
                }
            ],
            "confidence": "high",
        },
        ensure_ascii=False,
    )


def test_observe_plan_json_creates_run_payload(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    (tmp_path / "projects" / "alpha" / "PROJECT.md").write_text("\ufeff# Alpha\n\nTrack alpha market changes.\n", encoding="utf-8")

    def fake_build_query_plan(**kwargs):
        assert not kwargs["project_text"].startswith("\ufeff")
        return [{"kind": "market", "query": "alpha market", "count": 4, "freshness": "pm"}]

    monkeypatch.setattr(
        observation_runner,
        "build_query_plan",
        fake_build_query_plan,
    )

    assert _run_observation(tmp_path, "plan", "--project", "alpha", "--json") == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["project"] == "alpha"
    assert payload["queries"][0]["query"] == "alpha market"
    assert not payload["context"]["project_summary"].startswith("\ufeff")
    assert payload["findings_path"].endswith("raw-findings.jsonl")
    assert (tmp_path / payload["run_root"] / "query-plan.json").exists()
    assert "observe ingest" in payload["next_command"]


def test_fallback_query_plan_uses_bounded_project_anchor():
    plan = observation_runner._build_fallback_query_plan(
        project="alpha-observe",
        project_text="# Project: alpha-observe\n\nLong markdown should not become the query seed.",
    )

    assert len(plan) == 3
    assert all(item["count"] == 2 for item in plan)
    assert plan[0]["query"] == "alpha observe competitors product updates"
    assert "# Project" not in plan[0]["query"]


def test_ingest_external_writes_project_observations_not_candidate_cards(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    monkeypatch.setattr(
        observation_runner,
        "build_query_plan",
        lambda **_: [{"kind": "market", "query": "alpha market", "count": 4, "freshness": "pm"}],
    )
    plan = observation_runner.plan_only(tmp_path, "alpha")
    findings_path = tmp_path / str(plan["findings_path"])
    findings_path.write_text(_finding_line() + "\n", encoding="utf-8")

    assert _run_observation(
        tmp_path,
        "ingest",
        "--project",
        "alpha",
        "--run-id",
        str(plan["run_id"]),
        "--findings",
        str(plan["findings_path"]),
    ) == 0
    capsys.readouterr()

    obs_root = tmp_path / "observations" / "alpha"
    index_payload = json.loads((obs_root / "index.json").read_text(encoding="utf-8"))
    state_payload = json.loads((obs_root / "state.json").read_text(encoding="utf-8"))
    files = sorted((obs_root / "files").glob("*.json"))

    assert len(index_payload["observation_ids"]) == 1
    assert state_payload["last_run_id"] == plan["run_id"]
    assert state_payload["observation_count"] == 1
    assert len(files) == 1
    assert not (tmp_path / "workspaces" / "alpha-observe" / "candidate-updates" / "inbox").exists()

    assert _run_observation(tmp_path, "review", "--workspace", "alpha-observe", "--json") == 0
    review_payload = json.loads(capsys.readouterr().out)
    assert review_payload["counts"]["inbox"] == 1
    assert review_payload["cards"][0]["title"] == "Competitor launch"
    assert review_payload["cards"][0]["url"] == "https://example.com/launch"


def test_ingest_fallback_evidence_uses_finding_description(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])
    plan = observation_runner.plan_only(tmp_path, "alpha")
    findings_path = tmp_path / str(plan["findings_path"])
    findings_path.write_text(
        json.dumps(
            {
                "kind": "technology",
                "query": "alpha integration",
                "title": "Integration signal",
                "url": "https://example.com/integration",
                "description": "Fallback evidence summary should preserve this description.",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    assert _run_observation(
        tmp_path,
        "ingest",
        "--project",
        "alpha",
        "--run-id",
        str(plan["run_id"]),
        "--findings",
        str(plan["findings_path"]),
    ) == 0
    capsys.readouterr()

    obs_root = tmp_path / "observations" / "alpha"
    observation_id = json.loads((obs_root / "index.json").read_text(encoding="utf-8"))["observation_ids"][0]
    observation_payload = json.loads((obs_root / "files" / f"{observation_id}.json").read_text(encoding="utf-8"))

    assert observation_payload["evidence"][0]["url"] == "https://example.com/integration"
    assert observation_payload["evidence"][0]["quote_or_summary"] == "Fallback evidence summary should preserve this description."


def test_ingest_rejects_invalid_jsonl(tmp_path: Path):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="invalid findings JSONL"):
        _run_observation(tmp_path, "ingest", "--project", "alpha", "--run-id", "run-1", "--findings", str(bad_path))


def test_ingest_rejects_late_write_after_delegated_failure(monkeypatch, tmp_path: Path):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])
    plan = observation_runner.plan_only(tmp_path, "alpha")
    run_root = tmp_path / str(plan["run_root"])
    findings_path = tmp_path / str(plan["findings_path"])
    findings_path.write_text(_finding_line("Late signal") + "\n", encoding="utf-8")
    (run_root / "meta.json").write_text(
        json.dumps(
            {
                "run_id": plan["run_id"],
                "project": "alpha",
                "mode": "agent-delegated-failed",
                "failed_at": "2026-04-24T00:00:00Z",
                "error": "timeout",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="already marked failed"):
        _run_observation(
            tmp_path,
            "ingest",
            "--project",
            "alpha",
            "--run-id",
            str(plan["run_id"]),
            "--findings",
            str(plan["findings_path"]),
        )

    state = json.loads((tmp_path / "observations" / "alpha" / "state.json").read_text(encoding="utf-8"))
    assert state["last_run_id"] is None

    with pytest.raises(SystemExit, match="already marked failed"):
        observation_runner._write_project_observations_from_findings(
            repo_root=tmp_path,
            project="alpha",
            run_id=str(plan["run_id"]),
            started_at="2026-04-24T00:00:01Z",
            findings=[json.loads(_finding_line("Late direct signal"))],
            query_plan=[],
            recall=None,
            mode="agent-ingest",
        )


def test_run_live_inside_agent_outputs_handoff(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: True)
    monkeypatch.setattr(observation_runner, "run_executor", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")))
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])

    assert _run_observation(tmp_path, "run", "--project", "alpha") == 0
    out = capsys.readouterr().out
    assert "agent_handoff_required" in out
    assert "run-observation" in out
    assert "pmagent observe ingest" in out


def test_run_live_inside_agent_supports_json_handoff(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: True)
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])

    assert _run_observation(tmp_path, "run", "--project", "alpha", "--json") == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "handoff_required"
    assert payload["action"] == "agent_handoff_required"
    assert payload["project"] == "alpha"
    assert payload["ingest_command"].startswith("pmagent observe ingest")


def test_run_live_rejects_nested_delegated_observe_run(monkeypatch, tmp_path: Path):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    monkeypatch.setenv("PMAGENT_OBSERVATION_DELEGATED", "1")
    monkeypatch.setattr(observation_runner, "run_executor", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")))

    with pytest.raises(SystemExit, match="nested `pmagent observe run` is not allowed"):
        _run_observation(tmp_path, "run", "--project", "alpha")

    runs_root = tmp_path / "observations" / "alpha" / "runs"
    assert not runs_root.exists() or not any(runs_root.iterdir())


def test_run_live_headless_invokes_agent_and_verifies_ingest(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    previous_env = {
        key: os.environ.get(key)
        for key in ("PMAGENT_OBSERVATION_DELEGATED", "PMAGENT_AGENT_MODE", "PMAGENT_DATA_DIR", "PMAGENT_OBSERVATION_RUN_ID")
    }
    monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: False)
    monkeypatch.setattr(observation_runner, "resolve_available_backend", lambda: "kiro")
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])

    def fake_run_executor(executor_id, prompt, *, cwd, **kwargs):
        assert executor_id == "kiro"
        assert os.environ["PMAGENT_OBSERVATION_DELEGATED"] == "1"
        assert os.environ["PMAGENT_AGENT_MODE"] == "observation"
        assert os.environ["PMAGENT_DATA_DIR"] == str(cwd)
        assert "Do NOT run `pmagent observe run` again" in prompt
        runs_root = cwd / "observations" / "alpha" / "runs"
        run_root = sorted(path for path in runs_root.iterdir() if path.is_dir())[-1]
        run_id = run_root.name
        assert os.environ["PMAGENT_OBSERVATION_RUN_ID"] == run_id
        findings_path = run_root / "raw-findings.jsonl"
        findings_path.write_text(_finding_line("Headless signal") + "\n", encoding="utf-8")
        observation_runner.ingest_external(cwd, "alpha", run_id=run_id, findings_path=findings_path)
        return ExecutorResult(content="done", session_id="sid")

    monkeypatch.setattr(observation_runner, "run_executor", fake_run_executor)

    assert _run_observation(tmp_path, "run", "--project", "alpha") == 0
    out = capsys.readouterr().out
    assert "Agent-delegated observation completed" in out
    state = json.loads((tmp_path / "observations" / "alpha" / "state.json").read_text(encoding="utf-8"))
    assert state["last_run_id"]
    assert state["observation_count"] == 1
    assert {
        key: os.environ.get(key)
        for key in ("PMAGENT_OBSERVATION_DELEGATED", "PMAGENT_AGENT_MODE", "PMAGENT_DATA_DIR", "PMAGENT_OBSERVATION_RUN_ID")
    } == previous_env


def test_run_live_treats_executor_timeout_as_success_when_ingest_verified(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: False)
    monkeypatch.setattr(observation_runner, "resolve_available_backend", lambda: "claude")
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])

    def fake_run_executor(executor_id, prompt, *, cwd, **kwargs):
        del executor_id, prompt, kwargs
        run_root = sorted((cwd / "observations" / "alpha" / "runs").iterdir())[-1]
        findings_path = run_root / "raw-findings.jsonl"
        findings_path.write_text(_finding_line("Timeout but ingested") + "\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            observation_runner.ingest_external(cwd, "alpha", run_id=run_root.name, findings_path=findings_path)
        raise ExecutorError("claude.CMD timed out after 90s")

    monkeypatch.setattr(observation_runner, "run_executor", fake_run_executor)

    assert _run_observation(tmp_path, "run", "--project", "alpha", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert "timed out" in payload["executor_warning"]

    run_root = tmp_path / "observations" / "alpha" / "runs" / payload["run_id"]
    meta = json.loads((run_root / "meta.json").read_text(encoding="utf-8"))
    state = json.loads((tmp_path / "observations" / "alpha" / "state.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "agent-ingest"
    assert "failed_at" not in meta
    assert meta["completion_observed_after_executor_error"] is True
    assert state["last_run_id"] == payload["run_id"]


def test_run_live_parent_ingests_raw_findings_after_executor_timeout(monkeypatch, tmp_path: Path, capsys):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    capsys.readouterr()
    monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: False)
    monkeypatch.setattr(observation_runner, "resolve_available_backend", lambda: "claude")
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])
    monkeypatch.setenv("PMAGENT_OBSERVATION_TIMEOUT_GRACE", "0")

    def fake_run_executor(executor_id, prompt, *, cwd, **kwargs):
        del executor_id, prompt, kwargs
        run_root = sorted((cwd / "observations" / "alpha" / "runs").iterdir())[-1]
        findings_path = run_root / "raw-findings.jsonl"
        findings_path.write_text(_finding_line("Raw-only timeout") + "\n", encoding="utf-8")
        raise ExecutorError("claude.CMD timed out after 90s")

    monkeypatch.setattr(observation_runner, "run_executor", fake_run_executor)

    assert _run_observation(tmp_path, "run", "--project", "alpha", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["findings_count"] == 1
    assert "timed out" in payload["executor_warning"]

    run_root = tmp_path / "observations" / "alpha" / "runs" / payload["run_id"]
    meta = json.loads((run_root / "meta.json").read_text(encoding="utf-8"))
    state = json.loads((tmp_path / "observations" / "alpha" / "state.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "agent-ingest"
    assert meta["parent_ingested_after_executor_error"] is True
    assert state["last_run_id"] == payload["run_id"]


def test_run_live_marks_failed_when_executor_timeout_has_no_ingest(monkeypatch, tmp_path: Path):
    _seed_repo(tmp_path)
    assert _run_observation(tmp_path, "init-profile", "--project", "alpha") == 0
    monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: False)
    monkeypatch.setattr(observation_runner, "resolve_available_backend", lambda: "claude")
    monkeypatch.setattr(observation_runner, "build_query_plan", lambda **_: [])
    monkeypatch.setenv("PMAGENT_OBSERVATION_TIMEOUT_GRACE", "0")
    monkeypatch.setattr(
        observation_runner,
        "run_executor",
        lambda *args, **kwargs: (_ for _ in ()).throw(ExecutorError("claude.CMD timed out after 90s")),
    )

    with pytest.raises(SystemExit, match="timed out"):
        _run_observation(tmp_path, "run", "--project", "alpha")

    run_root = sorted((tmp_path / "observations" / "alpha" / "runs").iterdir())[-1]
    meta = json.loads((run_root / "meta.json").read_text(encoding="utf-8"))
    state = json.loads((tmp_path / "observations" / "alpha" / "state.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "agent-delegated-failed"
    assert "agent observation verification failed" in meta["error"]
    assert state["last_run_id"] is None
