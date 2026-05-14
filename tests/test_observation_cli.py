import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import shutil
import uuid

import pytest

import pmagent.current_state as current_state_module
from pmagent.observation import cli as observation_cli
from pmagent.current_state import current_state_path, sync_current_state
from pmagent.observation.summary_protocol import build_workspace_summary_document, inspect_summary


@contextmanager
def _workspace_dir(name: str) -> Iterator[Path]:
    root = Path(".tmp-pmagent-data") / "test-artifacts" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root.resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_observation(repo_root: Path, *argv: str) -> int:
    return observation_cli.main(["--repo-root", str(repo_root), *argv])


def _seed_projects_config(repo_root: Path, *, project: str = "alpha", workspace: str = "alpha-observe") -> None:
    config_root = repo_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_project": project,
        "active_workspace": workspace,
        "projects": {
            project: {
                "description": project,
                "workspaces": [workspace],
            }
        },
    }
    (config_root / "projects.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_observation(repo_root: Path, project: str, observation_id: str, *, title: str, summary: str) -> None:
    files_root = repo_root / "observations" / project / "files"
    files_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "id": observation_id,
        "project": project,
        "created_at": "2026-04-15T00:00:00Z",
        "kind": "market",
        "title": title,
        "summary": summary,
        "source_url": f"https://example.com/{observation_id}",
        "evidence": [],
        "tags": ["market"],
        "run_id": "run-1",
    }
    (files_root / f"{observation_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_init_profile_creates_project_observation_scaffold():
    with _workspace_dir("observe-init") as repo_root:
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0
        observation_root = repo_root / "observations" / "alpha"
        assert observation_root.is_dir()
        assert (observation_root / "policy.json").exists()
        assert (observation_root / "state.json").exists()
        assert (observation_root / "index.json").exists()
        assert (observation_root / "files").is_dir()
        assert (observation_root / "runs").is_dir()


def test_parallel_state_sync_keeps_summary_markers_valid():
    with _workspace_dir("parallel-state-sync") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        workspace_root = repo_root / "workspaces" / "alpha-observe"
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "workspace-summary.md").write_text(
            build_workspace_summary_document(workspace="alpha-observe"),
            encoding="utf-8",
        )
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0

        def do_sync(index: int) -> None:
            sync_current_state(
                repo_root,
                "alpha-observe",
                patch={"active_step": f"candidate-review-{index}"},
                updated_by=f"test-{index}",
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(do_sync, range(24)))

        summary_path = workspace_root / "workspace-summary.md"
        assert inspect_summary(summary_path).state == "valid"
        assert json.loads(current_state_path(repo_root, "alpha-observe").read_text(encoding="utf-8"))["workspace"] == "alpha-observe"
        assert not list(workspace_root.rglob("*.lock"))
        assert not list(workspace_root.rglob("*.tmp"))


def test_load_current_state_retries_transient_permission_error(monkeypatch):
    with _workspace_dir("state-read-retry") as repo_root:
        workspace_root = repo_root / "workspaces" / "alpha-observe" / ".pmagent"
        workspace_root.mkdir(parents=True, exist_ok=True)
        state_path = workspace_root / "current-state.json"
        state_path.write_text(json.dumps({"workspace": "alpha-observe"}, ensure_ascii=False), encoding="utf-8")
        original_read_text = Path.read_text
        attempts = {"count": 0}

        def flaky_read_text(self: Path, *args, **kwargs):
            if self == state_path and attempts["count"] == 0:
                attempts["count"] += 1
                raise PermissionError("locked by another process")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)

        state = current_state_module.load_current_state(repo_root, "alpha-observe")
        assert state == {"workspace": "alpha-observe"}
        assert attempts["count"] == 1


def test_unread_and_mark_read_operate_on_workspace_tracking(capsys):
    with _workspace_dir("observe-unread") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe").mkdir(parents=True, exist_ok=True)
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0
        capsys.readouterr()

        _write_observation(repo_root, "alpha", "obs-1", title="Signal one", summary="first summary")
        _write_observation(repo_root, "alpha", "obs-2", title="Signal two", summary="second summary")
        (repo_root / "observations" / "alpha" / "index.json").write_text(
            json.dumps(
                {"schema_version": 1, "project": "alpha", "observation_ids": ["obs-1", "obs-2"], "updated_at": "2026-04-15T00:00:00Z"},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        assert _run_observation(repo_root, "unread", "--workspace", "alpha-observe", "--json") == 0
        unread_payload = json.loads(capsys.readouterr().out)
        assert unread_payload["project"] == "alpha"
        assert unread_payload["unread_observation_ids"] == ["obs-1", "obs-2"]

        assert _run_observation(repo_root, "mark-read", "--workspace", "alpha-observe", "--ids", "obs-1", "--json") == 0
        mark_payload = json.loads(capsys.readouterr().out)
        tracking = mark_payload["tracking"]
        assert tracking["seen_observation_ids"] == ["obs-1"]

        assert _run_observation(repo_root, "unread", "--workspace", "alpha-observe", "--json") == 0
        unread_again = json.loads(capsys.readouterr().out)
        assert unread_again["unread_observation_ids"] == ["obs-2"]


def test_review_payload_uses_unread_project_observations(monkeypatch, capsys):
    with _workspace_dir("observe-review") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe" / "prd").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe" / "prd" / "current.md").write_text("# PRD\n", encoding="utf-8")
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0
        assert _run_observation(repo_root, "bootstrap-workspace", "--workspace", "alpha-observe") == 0
        (repo_root / "workspaces" / "alpha-observe" / "workspace-summary.md").write_text(
            build_workspace_summary_document(workspace="alpha-observe"),
            encoding="utf-8",
        )
        capsys.readouterr()
        for relative_path in ("observations/alpha/policy.json", "observations/alpha/state.json"):
            path = repo_root / relative_path
            payload = _read_json(path)
            payload["enabled"] = True
            payload["cadence"] = "daily"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        _write_observation(repo_root, "alpha", "obs-1", title="Competitor launch", summary="A new competitor feature is live.")
        (repo_root / "observations" / "alpha" / "index.json").write_text(
            json.dumps(
                {"schema_version": 1, "project": "alpha", "observation_ids": ["obs-1"], "updated_at": "2026-04-15T00:00:00Z"},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        assert _run_observation(repo_root, "review", "--workspace", "alpha-observe", "--json") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["workspace"] == "alpha-observe"
        assert payload["project"] == "alpha"
        assert payload["counts"]["inbox"] == 1
        assert payload["cards"][0]["card"] == "obs-1"
        assert payload["cards"][0]["title"] == "Competitor launch"
        assert payload["candidate_review"]["inbox_count"] == 1
        current = _read_json(repo_root / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json")
        assert current["observation"]["queue"]["inbox"] == 1
        assert current["observation"]["needs_review"] is True
        summary = (repo_root / "workspaces" / "alpha-observe" / "workspace-summary.md").read_text(encoding="utf-8")
        assert "- Observation enabled: yes" in summary
        assert "- Cadence: daily" in summary
        assert "- Queue summary: inbox=1 accepted=0 rejected=0 snoozed=0" in summary
        assert "- Needs review: yes" in summary
        assert "- Candidate updates: 1" in summary


def test_review_and_maintenance_text_outputs_render_score_tables(capsys):
    with _workspace_dir("observe-review-text") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe" / "prd").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe" / "prd" / "current.md").write_text("# PRD\n", encoding="utf-8")
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0
        assert _run_observation(repo_root, "bootstrap-workspace", "--workspace", "alpha-observe") == 0
        capsys.readouterr()

        _write_observation(repo_root, "alpha", "obs-1", title="Competitor launch", summary="A new competitor feature is live.")
        (repo_root / "observations" / "alpha" / "index.json").write_text(
            json.dumps(
                {"schema_version": 1, "project": "alpha", "observation_ids": ["obs-1"], "updated_at": "2026-04-15T00:00:00Z"},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        assert _run_observation(repo_root, "review", "--workspace", "alpha-observe") == 0
        review_text = capsys.readouterr().out
        assert "Readiness 评分表" not in review_text
        assert "Candidate Review 聚合评分表" not in review_text
        assert "Candidate Review 单卡列表" in review_text
        assert "| card | title | kind |" in review_text
        assert "Competitor launch" in review_text

        assert _run_observation(repo_root, "accept", "--workspace", "alpha-observe", "--card", "obs-1") == 0
        capsys.readouterr()
        assert _run_observation(repo_root, "draft-maintenance", "--workspace", "alpha-observe") == 0
        capsys.readouterr()

        assert _run_observation(repo_root, "maintenance-status", "--workspace", "alpha-observe") == 0
        maintenance_text = capsys.readouterr().out
        assert "Maintenance 概览" in maintenance_text
        assert "Maintenance 评分表" not in maintenance_text
        assert "| accepted_count | 1 |" in maintenance_text


def test_accept_marks_observation_seen_and_creates_workspace_artifact(capsys):
    with _workspace_dir("observe-accept") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe").mkdir(parents=True, exist_ok=True)
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0
        assert _run_observation(repo_root, "bootstrap-workspace", "--workspace", "alpha-observe") == 0
        capsys.readouterr()

        _write_observation(repo_root, "alpha", "obs-1", title="Signal one", summary="first summary")
        (repo_root / "observations" / "alpha" / "index.json").write_text(
            json.dumps(
                {"schema_version": 1, "project": "alpha", "observation_ids": ["obs-1"], "updated_at": "2026-04-15T00:00:00Z"},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        assert _run_observation(repo_root, "accept", "--workspace", "alpha-observe", "--card", "obs-1") == 0
        accepted_file = repo_root / "workspaces" / "alpha-observe" / "candidate-updates" / "accepted" / "obs-1.md"
        assert accepted_file.exists()
        state = _read_json(repo_root / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json")
        assert "obs-1" in state["observation_tracking"]["seen_observation_ids"]
        assert state["next_recommended_step"]["id"] == "draft_maintenance"

        assert _run_observation(repo_root, "audit", "--workspace", "alpha-observe", "--json") == 0
        capsys.readouterr()
        state = _read_json(repo_root / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json")
        assert state["phase"] == "maintaining"
        assert state["next_recommended_step"]["id"] == "draft_maintenance"

        assert _run_observation(repo_root, "review", "--workspace", "alpha-observe", "--json") == 0
        review_payload = json.loads(capsys.readouterr().out)
        assert review_payload["next_recommended_step"]["id"] == "draft_maintenance"

        assert _run_observation(repo_root, "unread", "--workspace", "alpha-observe", "--json") == 0
        capsys.readouterr()
        state = _read_json(repo_root / "workspaces" / "alpha-observe" / ".pmagent" / "current-state.json")
        assert state["next_recommended_step"]["id"] == "draft_maintenance"


def test_run_live_writes_project_level_observation_files(monkeypatch):
    with _workspace_dir("observe-live") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0

        from pmagent.executors import ExecutorResult
        from pmagent.observation import runner as observation_runner

        monkeypatch.setattr(
            observation_runner,
            "build_query_plan",
            lambda **_: [],
        )
        monkeypatch.setattr(observation_runner, "is_inside_agent", lambda: False)
        monkeypatch.setattr(observation_runner, "resolve_available_backend", lambda: "kiro")

        def fake_run_executor(executor_id, prompt, *, cwd, **kwargs):
            runs_root = cwd / "observations" / "alpha" / "runs"
            run_root = sorted(path for path in runs_root.iterdir() if path.is_dir())[-1]
            findings_path = run_root / "raw-findings.jsonl"
            findings_path.write_text(
                json.dumps(
                    {
                        "kind": "market",
                        "query": "alpha market change",
                        "title": "Competitor launch",
                        "url": "https://example.com/launch",
                        "description": "New capability",
                        "age": "2d",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            observation_runner.ingest_external(cwd, "alpha", run_id=run_root.name, findings_path=findings_path)
            return ExecutorResult(content="done", session_id="sid")

        monkeypatch.setattr(observation_runner, "run_executor", fake_run_executor)

        assert _run_observation(repo_root, "run", "--project", "alpha") == 0

        obs_root = repo_root / "observations" / "alpha"
        runs = sorted((obs_root / "runs").iterdir())
        assert runs
        run_root = runs[-1]
        meta = _read_json(run_root / "meta.json")
        index_payload = _read_json(obs_root / "index.json")
        state_payload = _read_json(obs_root / "state.json")
        files = sorted((obs_root / "files").glob("*.json"))

        assert meta["project"] == "alpha"
        assert meta["findings_count"] == 1
        assert len(index_payload["observation_ids"]) == 1
        assert state_payload["observation_count"] == 1
        assert len(files) == 1


def test_run_rejects_removed_dry_run_flag():
    with _workspace_dir("observe-no-dry-run") as repo_root:
        with pytest.raises(SystemExit):
            _run_observation(repo_root, "run", "--project", "alpha", "--dry-run")


def test_executor_facade_exports_run_dry_run():
    from pmagent.observation import executor as observation_executor

    assert hasattr(observation_executor, "run_dry_run")
    assert "run_dry_run" in observation_executor.__all__


def test_audit_run_catch_up_invokes_runner(monkeypatch, capsys):
    with _workspace_dir("observe-catch-up") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe").mkdir(parents=True, exist_ok=True)
        assert _run_observation(repo_root, "init-profile", "--project", "alpha") == 0
        assert _run_observation(repo_root, "bootstrap-workspace", "--workspace", "alpha-observe") == 0
        capsys.readouterr()

        state_path = repo_root / "observations" / "alpha" / "state.json"
        state_payload = _read_json(state_path)
        state_payload["enabled"] = True
        state_payload["cadence"] = "daily"
        state_payload["last_run_at"] = "2026-04-10T00:00:00Z"
        state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        policy_path = repo_root / "observations" / "alpha" / "policy.json"
        policy_payload = _read_json(policy_path)
        policy_payload["enabled"] = True
        policy_payload["cadence"] = "daily"
        policy_payload["catch_up_policy"] = "auto"
        policy_path.write_text(json.dumps(policy_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        calls: list[tuple[Path, str]] = []
        monkeypatch.setattr(
            "pmagent.observation.executor.run_live",
            lambda repo_root, project: calls.append((repo_root, project)) or 0,
        )

        assert _run_observation(repo_root, "audit", "--workspace", "alpha-observe", "--run-catch-up", "--json") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["catch_up_performed"] is True
        assert calls == [(repo_root, "alpha")]
