import argparse
import json
import sys
from pathlib import Path

import pytest

import pmagent.infra as infra
from pmagent.infra import cmd_infra


def test_infra_protocol_writes_openclaw_contract(tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    data_dir.mkdir()
    (data_dir / "config").mkdir()
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": "alpha-discovery",
                "projects": {"alpha": {"workspaces": ["alpha-discovery"]}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="protocol",
        project=None,
        workspace=None,
        json=False,
    )

    assert cmd_infra(args) == 0

    protocol_path = data_dir / "config" / "openclaw-advisor-protocol.md"
    schema_path = data_dir / "config" / "candidate-card.schema.json"
    manifest_path = data_dir / "config" / "pm-infra-protocol.json"
    assert protocol_path.exists()
    assert schema_path.exists()
    assert manifest_path.exists()

    protocol_text = protocol_path.read_text(encoding="utf-8")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "OpenClaw is the advisor runtime" in protocol_text
    assert "pmagent infra protocol" in protocol_text
    assert "Project: `alpha`" in protocol_text
    assert "Workspace: `alpha-discovery`" in protocol_text
    assert "target_workspace" in protocol_text
    assert schema["title"] == "PMAgent Candidate Card"
    assert "behavior_analysis" in schema["properties"]["source_type"]["enum"]
    assert "source_ref" in schema["required"]
    assert "evidence" in schema["properties"]["suggestion"]["required"]

    out = capsys.readouterr().out
    assert "protocol_path=config/openclaw-advisor-protocol.md" in out
    assert "schema_path=config/candidate-card.schema.json" in out
    assert "manifest=config/pm-infra-protocol.json" in out


def test_infra_auth_guide_outputs_minimal_scopes(capsys):
    args = argparse.Namespace(
        data_dir=None,
        subcommand="auth-guide",
        profile="pma-feishu",
        app_id="cli_approved",
        brand="lark",
        json=True,
    )

    assert cmd_infra(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["app_id"] == "cli_approved"
    assert "wiki:node:create" in payload["minimal_scopes"]
    assert "base:app:create" in payload["minimal_scopes"]
    assert "offline_access" in payload["minimal_scopes"]
    assert "lark-cli auth login --scope" in payload["commands"]["login"]
    assert "Do not run auth login without --scope" in " ".join(payload["notes"])


def test_infra_wiki_push_tracks_pending_human_readable_files(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.delenv("PMAGENT_FEISHU_WIKI_PUSH_COMMAND", raising=False)
    monkeypatch.setattr(infra, "_lark_cli_available", lambda: False)
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    ws_root = data_dir / "workspaces" / workspace
    (data_dir / "config").mkdir(parents=True)
    (ws_root / ".pmagent").mkdir(parents=True)
    (ws_root / "Requirement.md").write_text("# Requirement\n\nInitial.\n", encoding="utf-8")
    (ws_root / "workspace-summary.md").write_text("# Summary\n\nInitial.\n", encoding="utf-8")
    (ws_root / ".pmagent" / "current-state.json").write_text("{}\n", encoding="utf-8")
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    status_args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="sync-status",
        project=None,
        workspace=None,
        command=None,
        json=True,
    )
    assert cmd_infra(status_args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["configured"] is False
    assert status["pending_files"] == ["Requirement.md", "workspace-summary.md"]

    script = tmp_path / "push.py"
    log = tmp_path / "feishu-push.log"
    script.write_text(
        "import pathlib, sys\n"
        "log = pathlib.Path(sys.argv[1])\n"
        "line = sys.argv[2] + '|' + sys.argv[3] + '\\n'\n"
        "log.write_text((log.read_text(encoding='utf-8') if log.exists() else '') + line, encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script}" "{log}" "{{relative}}" "{{workspace}}"'
    push_args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="wiki-push",
        project=None,
        workspace=workspace,
        command=command,
        dry_run=False,
        all=False,
        json=True,
    )
    assert cmd_infra(push_args) == 0
    pushed = json.loads(capsys.readouterr().out)
    assert pushed["pushed"] == ["Requirement.md", "workspace-summary.md"]
    assert (data_dir / pushed["ledger"]).exists()
    assert "Requirement.md|alpha-discovery" in log.read_text(encoding="utf-8")

    status_args.command = command
    assert cmd_infra(status_args) == 0
    synced = json.loads(capsys.readouterr().out)
    assert synced["configured"] is True
    assert synced["pending_files"] == []

    (ws_root / "Requirement.md").write_text("# Requirement\n\nChanged.\n", encoding="utf-8")
    assert cmd_infra(status_args) == 0
    changed = json.loads(capsys.readouterr().out)
    assert changed["pending_files"] == ["Requirement.md"]


def test_infra_wiki_push_defaults_to_builtin_lark_adapter(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.delenv("PMAGENT_FEISHU_WIKI_PUSH_COMMAND", raising=False)
    monkeypatch.setattr(infra, "_lark_cli_available", lambda: True)
    monkeypatch.setattr(infra, "_lark_cli_config_available", lambda data_dir: True)
    monkeypatch.setattr(infra.sys, "executable", "python")
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    ws_root = data_dir / "workspaces" / workspace
    (data_dir / "config").mkdir(parents=True)
    (ws_root / ".pmagent").mkdir(parents=True)
    (ws_root / "Requirement.md").write_text("# Requirement\n\nInitial.\n", encoding="utf-8")
    (data_dir / ".env").write_text("PMAGENT_FEISHU_WIKI_SPACE_ID=spc123\n", encoding="utf-8")
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}}
            }
        )
        + "\n",
        encoding="utf-8",
    )

    status_args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="sync-status",
        project=None,
        workspace=None,
        command=None,
        json=True,
    )
    assert cmd_infra(status_args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["configured"] is True
    assert status["adapter"] == "builtin-lark"
    assert status["command_source"] == "builtin-lark"
    assert status["space_id"] == "spc123"
    assert status["pending_files"] == ["Requirement.md"]

    push_args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="wiki-push",
        project=None,
        workspace=workspace,
        command=None,
        dry_run=True,
        all=False,
        json=True,
    )
    assert cmd_infra(push_args) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["adapter"] == "builtin-lark"
    assert planned["command_source"] == "builtin-lark"
    assert planned["space_id"] == "spc123"
    assert planned["planned"][0]["relative"] == "Requirement.md"
    assert "pmagent.ops.lark_wiki_push" in planned["planned"][0]["command"]
    assert "--space-id spc123" in planned["planned"][0]["command"]


def test_infra_wiki_push_reads_space_id_from_integrations(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.delenv("PMAGENT_FEISHU_WIKI_PUSH_COMMAND", raising=False)
    monkeypatch.delenv("PMAGENT_FEISHU_WIKI_SPACE_ID", raising=False)
    monkeypatch.setattr(infra, "_lark_cli_available", lambda: True)
    monkeypatch.setattr(infra, "_lark_cli_config_available", lambda data_dir: True)
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    ws_root = data_dir / "workspaces" / workspace
    (data_dir / "config").mkdir(parents=True)
    (ws_root / ".pmagent").mkdir(parents=True)
    (ws_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
    (data_dir / "config" / "integrations.json").write_text(
        json.dumps({"feishu": {"wiki_space_id": "spc_from_config"}}) + "\n",
        encoding="utf-8",
    )
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}}
            }
        )
        + "\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="sync-status",
        project=None,
        workspace=None,
        command=None,
        json=True,
    )
    assert cmd_infra(args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["space_id"] == "spc_from_config"


def test_infra_bootstrap_adopts_existing_base(tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    (data_dir / "projects" / "alpha").mkdir(parents=True)
    (data_dir / "config").mkdir(parents=True)

    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="bootstrap",
        project="alpha",
        base_token="bas123",
        table_id="tbl123",
        adopt_existing_base=True,
        dry_run=False,
        json=True,
    )

    assert cmd_infra(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "adopted"
    mapping_path = data_dir / payload["mapping"]
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert mapping["cards_base_app_token"] == "bas123"
    assert mapping["cards_table_id"] == "tbl123"
    assert mapping["cards_base_status"] == "adopted"


def test_infra_bootstrap_creates_project_wiki_base_and_fields(monkeypatch, tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    data_dir.mkdir()
    (data_dir / ".env").write_text("PMAGENT_FEISHU_WIKI_SPACE_ID=spc123\n", encoding="utf-8")
    calls: list[list[str]] = []

    monkeypatch.setattr(infra, "_lark_cli_available", lambda: True)
    monkeypatch.setattr(infra, "_lark_cli_config_available", lambda data_dir: True)

    def fake_lark(data_dir: Path, args: list[str]):
        calls.append(list(args))
        if args[:2] == ["wiki", "+node-create"]:
            return {"data": {"node_token": "wik_project"}}
        if args[:2] == ["base", "+base-create"]:
            return {"data": {"app_token": "bas_created", "node_token": "wik_base"}}
        if args[:2] == ["base", "+table-create"]:
            return {"data": {"table_id": "tbl_created"}}
        if args[:2] == ["base", "+field-list"]:
            return {"data": {"items": []}}
        if args[:2] == ["base", "+field-create"]:
            field = json.loads(args[args.index("--json") + 1])
            return {"data": {"field_id": field["name"]}}
        raise AssertionError(f"unexpected call: {args}")

    monkeypatch.setattr("pmagent.infra._run_lark_cli_json", fake_lark)

    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="bootstrap",
        project="alpha",
        base_token=None,
        table_id=None,
        adopt_existing_base=False,
        dry_run=False,
        json=True,
    )

    assert cmd_infra(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["infra"]["project_node_token"] == "wik_project"
    assert payload["infra"]["cards_base_app_token"] == "bas_created"
    assert payload["infra"]["cards_table_id"] == "tbl_created"
    field_calls = [call for call in calls if call[:2] == ["base", "+field-create"]]
    assert len(field_calls) == len(infra.BASE_CARD_FIELDS)
    assert any(call[:2] == ["base", "+base-create"] for call in calls)
    assert all("--json" in call for call in field_calls)
    assert all("--as" in call and call[call.index("--as") + 1] == "user" for call in calls if call[0] == "base")


def test_infra_bootstrap_dry_run_plans_without_lark_calls(monkeypatch, tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    data_dir.mkdir()
    (data_dir / ".env").write_text("PMAGENT_FEISHU_WIKI_SPACE_ID=spc123\n", encoding="utf-8")

    monkeypatch.setattr(infra, "_lark_cli_available", lambda: True)
    monkeypatch.setattr(infra, "_lark_cli_config_available", lambda data_dir: True)

    def fail_lark(data_dir: Path, args: list[str]):
        raise AssertionError(f"dry-run should not call lark-cli: {args}")

    monkeypatch.setattr("pmagent.infra._run_lark_cli_json", fail_lark)

    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="bootstrap",
        project="alpha",
        base_token=None,
        table_id=None,
        adopt_existing_base=False,
        dry_run=True,
        json=True,
    )

    assert cmd_infra(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["wiki_space_id"] == "spc123"
    assert payload["planned"][1]["step"] == "create_cards_base"
    assert payload["planned"][3]["fields"][0]["name"] == "card_id"
    assert not (data_dir / payload["mapping"]).exists()


def test_pull_cards_from_base_uses_project_infra_mapping(monkeypatch, tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    (data_dir / "workspaces" / workspace).mkdir(parents=True)
    (data_dir / "projects" / "alpha" / ".pmagent").mkdir(parents=True)
    (data_dir / "projects" / "alpha" / ".pmagent" / "feishu-infra.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": "alpha",
                "cards_base_app_token": "bas_from_project",
                "cards_table_id": "tbl_from_project",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_lark(data_dir: Path, args: list[str]):
        calls.append(list(args))
        return {"records": []}

    monkeypatch.setattr("pmagent.infra._run_lark_cli_json", fake_lark)
    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="pull-cards",
        from_file=None,
        from_base=True,
        base_token=None,
        table_id=None,
        project=None,
        workspace=None,
        json=True,
    )

    assert cmd_infra(args) == 0
    capsys.readouterr()
    record_list = calls[0]
    assert record_list[record_list.index("--base-token") + 1] == "bas_from_project"
    assert record_list[record_list.index("--table-id") + 1] == "tbl_from_project"


def test_infra_wiki_status_includes_human_readable_dev_artifacts(tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    ws_root = data_dir / "workspaces" / workspace
    (data_dir / "config").mkdir(parents=True)
    (ws_root / ".pmagent").mkdir(parents=True)
    (ws_root / "Requirement.md").write_text("# Requirement\n", encoding="utf-8")
    (ws_root / "dev" / "slices").mkdir(parents=True)
    (ws_root / "dev" / "dev-plan.md").write_text("# Dev Plan\n", encoding="utf-8")
    (ws_root / "dev" / "slices" / "SL-001.md").write_text("# Slice\n", encoding="utf-8")
    run_root = ws_root / "dev" / "runs" / "SL-001" / "run-20260502"
    run_root.mkdir(parents=True)
    (run_root / "diff-summary.md").write_text("# Diff\n", encoding="utf-8")
    (run_root / "run.json").write_text("{}\n", encoding="utf-8")
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="sync-status",
        project=None,
        workspace=None,
        command=None,
        json=True,
    )

    assert cmd_infra(args) == 0
    status = json.loads(capsys.readouterr().out)

    assert "dev/dev-plan.md" in status["pending_files"]
    assert "dev/slices/SL-001.md" in status["pending_files"]
    assert "dev/runs/SL-001/run-20260502/diff-summary.md" in status["pending_files"]
    assert "dev/runs/SL-001/run-20260502/run.json" not in status["pending_files"]


def test_infra_pull_cards_requires_evidence(tmp_path: Path):
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "workspaces" / workspace).mkdir(parents=True)
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cards_file = tmp_path / "cards.json"
    cards_file.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "card_id": "missing-evidence",
                        "source_type": "efficiency",
                        "source_ref": "run-1",
                        "target": {"project": "alpha", "workspace": workspace},
                        "suggestion": {
                            "title": "Missing evidence",
                            "body": "This should fail.",
                            "suggested_action": "Add evidence.",
                            "urgency": "normal",
                        },
                        "lifecycle": {"status": "inbox", "created_at": "2026-05-02T00:00:00Z"},
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="pull-cards",
        from_file=str(cards_file),
        project=None,
        workspace=workspace,
        json=True,
    )

    with pytest.raises(SystemExit, match="suggestion.evidence"):
        cmd_infra(args)


def test_infra_pull_cards_from_feishu_base(monkeypatch, tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "workspaces" / workspace).mkdir(parents=True)
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}}
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_lark(data_dir_arg: Path, args: list[str]):
        assert data_dir_arg == data_dir
        assert args[:2] == ["base", "+record-list"]
        return {
            "records": [
                {
                    "record_id": "rec001",
                    "fields": {
                        "card_id": "openclaw-base-001",
                        "source_type": "efficiency",
                        "source_ref": "openclaw-run-e2e",
                        "target_project": "alpha",
                        "target_workspace": workspace,
                        "title": "Base card",
                        "body": "Imported from Feishu Base.",
                        "evidence": "workspaces/alpha-discovery/dev/runs/SL-001/diff-summary.md",
                        "suggested_action": "Review the imported card.",
                        "urgency": "normal",
                        "status": "inbox",
                        "created_at": "2026-05-03T00:00:00Z",
                    },
                }
            ]
        }

    monkeypatch.setattr("pmagent.infra._run_lark_cli_json", fake_lark)
    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="pull-cards",
        from_base=True,
        from_file=None,
        base_token="app_token",
        table_id="tbl001",
        project=None,
        workspace=workspace,
        json=True,
    )

    assert cmd_infra(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["source"] == "feishu-base"
    assert payload["read_records"] == 1
    assert payload["imported"] == [f"workspaces/{workspace}/candidate-updates/inbox/openclaw-base-001.md"]


def test_infra_push_feedback_to_feishu_base(monkeypatch, tmp_path: Path, capsys):
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    feedback_root = data_dir / "workspaces" / workspace / "candidate-updates"
    feedback_root.mkdir(parents=True)
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "config" / "projects.json").write_text(
        json.dumps(
            {
                "active_project": "alpha",
                "active_workspace": workspace,
                "projects": {"alpha": {"workspaces": [workspace]}}
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (feedback_root / "feedback.jsonl").write_text(
        json.dumps(
            {
                "card_id": "openclaw-base-001",
                "status": "accepted",
                "review_note": "Looks actionable.",
                "reviewed_at": "2026-05-03T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_lark(_data_dir_arg: Path, args: list[str]):
        calls.append(args)
        if args[:2] == ["base", "+record-list"]:
            return {"records": [{"record_id": "rec001", "fields": {"card_id": "openclaw-base-001"}}]}
        if args[:2] == ["base", "+record-upsert"]:
            return {"record": {"record_id": "rec001"}, "updated": True}
        raise AssertionError(args)

    monkeypatch.setattr("pmagent.infra._run_lark_cli_json", fake_lark)
    args = argparse.Namespace(
        data_dir=str(data_dir),
        subcommand="push-feedback",
        workspace=workspace,
        base_token="app_token",
        table_id="tbl001",
        json=True,
    )

    assert cmd_infra(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["updated"] == ["openclaw-base-001"]
    upsert = calls[-1]
    assert upsert[:2] == ["base", "+record-upsert"]
    assert "--record-id" in upsert
    patch = json.loads(upsert[upsert.index("--json") + 1])
    assert patch["status"] == "accepted"
    assert patch["review_note"] == "Looks actionable."
