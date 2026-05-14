import json
import shutil
import subprocess
from pathlib import Path

import pytest

import pmagent.cli as cli


def _json_out(capsys):
    return json.loads(capsys.readouterr().out)


def test_external_agent_dev_slice_to_infra_card_feedback_flow(tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"

    assert cli.main(["init", "--dir", str(data_dir)]) == 0
    capsys.readouterr()

    git = shutil.which("git")
    if git is None:
        pytest.skip("git executable not available")
    subprocess.run([git, "init"], cwd=data_dir, check=True, capture_output=True, text=True)

    assert cli.main(
        [
            "workspace-init",
            "--data-dir",
            str(data_dir),
            "--project",
            "alpha",
            "--workspace",
            "infra",
            "--requirement-summary",
            "Build PM infra flow.",
        ]
    ) == 0
    capsys.readouterr()

    workspace = "alpha-infra"
    prd_dir = data_dir / "workspaces" / workspace / "prd"
    prd_dir.mkdir(parents=True, exist_ok=True)
    (prd_dir / "current.md").write_text(
        "# PRD\n\n## Goal\n\nShip a concrete PM infra integration flow.\n",
        encoding="utf-8",
    )

    dev_root = data_dir / "workspaces" / workspace / "dev"
    slices_root = dev_root / "slices"
    slices_root.mkdir(parents=True, exist_ok=True)
    (dev_root / "dev-plan.md").write_text(
        "# Dev Plan\n\n## Slice Order\n\n1. `SL-001` - PM infra happy path.\n",
        encoding="utf-8",
    )
    (dev_root / "codebases.json").write_text(
        json.dumps({"schema_version": 1, "codebases": [{"id": "pmagent", "vcs": "git"}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    (slices_root / "SL-001.md").write_text(
        "# Slice SL-001: PM infra happy path\n\n"
        "## Goal\n\nShip a vertical slice for PM infra card feedback.\n\n"
        "## Codebase\n\n- codebase_id: pmagent\n- base_commit: test\n- branch: test\n\n"
        "## Owned Paths\n\n- tests/test_concrete_pm_infra_flow.py\n\n"
        "## Commands\n\n- python -m pytest tests/test_concrete_pm_infra_flow.py\n",
        encoding="utf-8",
    )

    assert cli.main(["dev", "--data-dir", str(data_dir), "slices", "--workspace", workspace, "--json"]) == 0
    dev_payload = _json_out(capsys)
    assert dev_payload["slices"] == ["SL-001.md"]

    assert cli.main(
        [
            "dev",
            "--data-dir",
            str(data_dir),
            "run-record",
            "--workspace",
            workspace,
            "--slice",
            "SL-001",
            "--command",
            "python -m pytest tests/test_concrete_pm_infra_flow.py",
            "--status",
            "passed",
            "--lesson",
            "Concrete flow tests should assert artifact handoffs, not only parser availability.",
            "--json",
        ]
    ) == 0
    run_payload = _json_out(capsys)
    assert (data_dir / run_payload["run"] / "commands.jsonl").exists()
    assert (data_dir / run_payload["run"] / "run.json").exists()
    assert (data_dir / run_payload["run"] / "touched-files.json").exists()
    assert (data_dir / run_payload["run"] / "decisions.md").exists()
    assert (data_dir / run_payload["run"] / "blockers.md").exists()
    assert (data_dir / run_payload["lesson_candidates"]).read_text(encoding="utf-8").strip()

    assert cli.main(["dev", "--data-dir", str(data_dir), "lesson-review", "--workspace", workspace, "--json"]) == 0
    lessons_payload = _json_out(capsys)
    lesson_id = lessons_payload["lessons"][0]["lesson_id"]
    assert lessons_payload["inbox_count"] == 1

    assert cli.main(
        [
            "dev",
            "--data-dir",
            str(data_dir),
            "lesson-review",
            "--workspace",
            workspace,
            "--lesson-id",
            lesson_id,
            "--status",
            "accepted",
            "--note",
            "Promote because it protects artifact handoffs.",
            "--json",
        ]
    ) == 0
    lesson_review_payload = _json_out(capsys)
    assert lesson_review_payload["status"] == "accepted"
    assert (data_dir / lesson_review_payload["review_artifact"]).exists()

    assert cli.main(["infra", "--data-dir", str(data_dir), "protocol", "--json"]) == 0
    infra_payload = _json_out(capsys)
    for key in ("protocol_path", "schema_path", "wiki_plan", "github_plan", "manifest"):
        assert (data_dir / infra_payload[key]).exists()
    manifest = json.loads((data_dir / infra_payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["feishu_wiki"]["role"] == "human-readable collaboration mirror"
    assert manifest["feishu_wiki"]["default_adapter"] == "builtin-lark"
    assert manifest["feishu_wiki"]["space_id_env"] == "PMAGENT_FEISHU_WIKI_SPACE_ID"
    assert manifest["feishu_wiki"]["node_mapping"] == "projects/<project>/.pmagent/feishu-wiki-nodes.jsonl"
    assert manifest["feishu_wiki"]["target_hierarchy"] == "<project>/workspaces/<workspace>/<relative-file>"
    assert manifest["feishu_wiki"]["sync_status_command"] == "pmagent infra sync-status --workspace <workspace> --json"
    assert manifest["feishu_wiki"]["manual_push_command"] == "pmagent infra wiki-push --workspace <workspace> --json"
    assert manifest["feishu_base"]["workspace_route_field"] == "target_workspace"
    assert manifest["openclaw"]["reads"] == "GitHub PM Data repository"

    cards_file = tmp_path / "cards.json"
    cards_file.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "card_id": "openclaw-001",
                        "source_type": "efficiency",
                        "source_ref": "openclaw-run-1",
                        "target": {"project": "alpha", "workspace": workspace},
                        "suggestion": {
                            "title": "Review idle slice",
                            "body": "The first slice has run evidence and should be reviewed.",
                            "evidence": f"workspaces/{workspace}/dev/runs/SL-001",
                            "suggested_action": "Review the lesson candidate before promotion.",
                            "urgency": "normal",
                        },
                        "lifecycle": {
                            "status": "inbox",
                            "created_at": "2026-05-02T00:00:00Z",
                            "reviewed_at": None,
                            "review_note": None,
                            "expires_at": None,
                        },
                    },
                    {
                        "card_id": "other-workspace",
                        "source_type": "consistency",
                        "source_ref": "openclaw-run-1",
                        "target": {"project": "alpha", "workspace": "other"},
                        "suggestion": {
                            "title": "Skip",
                            "body": "Wrong workspace.",
                            "evidence": "n/a",
                            "suggested_action": "Ignore.",
                            "urgency": "low",
                        },
                        "lifecycle": {"status": "inbox", "created_at": "2026-05-02T00:00:00Z"},
                    },
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    assert cli.main(
        [
            "infra",
            "--data-dir",
            str(data_dir),
            "pull-cards",
            "--from",
            str(cards_file),
            "--workspace",
            workspace,
            "--json",
        ]
    ) == 0
    pull_payload = _json_out(capsys)
    assert pull_payload["imported"] == [f"workspaces/{workspace}/candidate-updates/inbox/openclaw-001.md"]
    assert pull_payload["skipped_card_ids"] == ["other-workspace"]

    assert cli.main(
        [
            "infra",
            "--data-dir",
            str(data_dir),
            "review-card",
            "--workspace",
            workspace,
            "--card",
            "openclaw-001",
            "--status",
            "accepted",
            "--note",
            "Useful signal.",
            "--json",
        ]
    ) == 0
    review_payload = _json_out(capsys)
    assert review_payload["status"] == "accepted"
    assert review_payload["feedback"] == f"workspaces/{workspace}/candidate-updates/feedback.jsonl"
    feedback = (data_dir / review_payload["feedback"]).read_text(encoding="utf-8")
    assert '"card_id": "openclaw-001"' in feedback
    assert '"status": "accepted"' in feedback

    assert cli.main(["status", "--data-dir", str(data_dir), "--workspace", workspace, "--json"]) == 0
    status_payload = _json_out(capsys)
    assert "mode" not in status_payload
    assert "route_mode" not in status_payload
    assert "mode_skill_path" not in status_payload
    assert status_payload["recommended_skills"]

    assert cli.main(["infra", "--data-dir", str(data_dir), "git-boundary", "--json"]) == 0
    git_payload = _json_out(capsys)
    assert git_payload["is_git_repo"] is True
    assert str(data_dir) in git_payload["pm_data_dir"]
