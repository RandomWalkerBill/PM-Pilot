from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import shutil
import uuid

import pytest

import pmagent.cli as cli
from pmagent.cli import build_parser


@contextmanager
def _workspace_dir(name: str) -> Iterator[Path]:
    root = Path(".tmp-pmagent-data") / "test-artifacts" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root.resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cli_has_canonical_front_door_subcommands():
    parser = build_parser()
    subparsers_action = next(
        action for action in parser._actions if getattr(action, "choices", None)
    )
    expected = {
        "init",
        "upgrade",
        "status",
        "route",
        "review",
        "start",
        "next",
        "resume",
        "clarify",
        "research",
        "prd",
        "workspace-init",
        "switch",
        "workspace-close",
        "skills-sync",
        "infra",
        "dev",
        "observe",
        "debate",
    }
    assert expected.issubset(set(subparsers_action.choices))


def test_workspace_init_bootstraps_project_infra_by_default(monkeypatch):
    calls = []

    def fake_bootstrap(data_dir, *, project, fail_open):
        calls.append({"data_dir": Path(data_dir), "project": project, "fail_open": fail_open})
        return {"status": "ready"}

    monkeypatch.setattr("pmagent.infra.bootstrap_project_infra", fake_bootstrap)
    with _workspace_dir("workspace-init-infra-bootstrap") as data_dir:
        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-discovery",
                "--confirm-cadence",
            ]
        ) == 0

    assert calls == [{"data_dir": data_dir, "project": "alpha", "fail_open": True}]


def test_workspace_init_can_skip_project_infra_bootstrap(monkeypatch):
    calls = []

    def fake_bootstrap(data_dir, *, project, fail_open):
        calls.append(project)
        return {"status": "ready"}

    monkeypatch.setattr("pmagent.infra.bootstrap_project_infra", fake_bootstrap)
    with _workspace_dir("workspace-init-no-infra-bootstrap") as data_dir:
        assert cli.main(
            [
                "workspace-init",
                "--data-dir",
                str(data_dir),
                "--project",
                "alpha",
                "--workspace",
                "alpha-discovery",
                "--confirm-cadence",
                "--no-infra-bootstrap",
            ]
        ) == 0

    assert calls == []


def test_cmd_observe_requires_subcommand():
    with pytest.raises(SystemExit, match="observe requires a subcommand"):
        cli.cmd_observe(cli.argparse.Namespace(data_dir=None, observe_argv=[]))


def test_cmd_observe_forwards_repo_root_before_remainder(monkeypatch):
    observed = {}

    def fake_main(argv):
        observed["argv"] = argv
        return 0

    from pmagent.observation import cli as observation_cli

    monkeypatch.setattr(observation_cli, "main", fake_main)
    with _workspace_dir("observe-forward") as repo_root:
        args = cli.argparse.Namespace(
            data_dir=str(repo_root / "pm-data"),
            observe_argv=["run", "--workspace", "demo"],
        )

        assert cli.cmd_observe(args) == 0
        assert observed["argv"] == [
            "--repo-root",
            str((repo_root / "pm-data").resolve()),
            "run",
            "--workspace",
            "demo",
        ]


def test_cmd_observe_forwards_plain_remainder(monkeypatch):
    observed = {}

    def fake_main(argv):
        observed["argv"] = argv
        return 0

    from pmagent.observation import cli as observation_cli

    monkeypatch.setattr(observation_cli, "main", fake_main)
    args = cli.argparse.Namespace(
        data_dir=None,
        observe_argv=["init-profile", "--workspace", "demo"],
    )

    assert cli.cmd_observe(args) == 0
    assert observed["argv"] == ["init-profile", "--workspace", "demo"]


def test_observe_misplaced_data_dir_fails_after_top_level_remainder_boundary():
    with _workspace_dir("observe-misplaced-top-level") as repo_root:
        with pytest.raises(SystemExit):
            cli.main(["observe", "run", "--data-dir", str(repo_root), "--workspace", "demo"])


def test_switch_outputs_include_status_block(capsys):
    with _workspace_dir("switch-guided-output") as data_dir:
        (data_dir / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (data_dir / "workspaces" / "alpha-observe").mkdir(parents=True, exist_ok=True)
        (data_dir / "config").mkdir(parents=True, exist_ok=True)
        (data_dir / "config" / "projects.json").write_text(
            '{\n  "active_project": "",\n  "active_workspace": "",\n  "projects": {"alpha": {"description": "Alpha", "workspaces": ["alpha-observe"]}}\n}\n',
            encoding="utf-8",
        )

        assert cli.main(["switch", "--data-dir", str(data_dir), "--list"]) == 0
        list_text = capsys.readouterr().out
        assert "alpha" in list_text
        assert "workspace: alpha-observe" in list_text

        assert cli.main(["switch", "--data-dir", str(data_dir), "alpha", "alpha-observe"]) == 0
        switch_text = capsys.readouterr().out
        assert "switched to project=alpha, workspace=alpha-observe" in switch_text

        assert cli.main(["switch", "--data-dir", str(data_dir), "--clear"]) == 0
        clear_text = capsys.readouterr().out
        assert "cleared project isolation" in clear_text


def test_normalize_workspace_name_uses_project_prefix():
    assert cli._normalize_workspace_name("alpha", None) == "alpha-discovery"
    assert cli._normalize_workspace_name("alpha", "") == "alpha-discovery"
    assert cli._normalize_workspace_name("alpha", "alpha") == "alpha-discovery"
    assert cli._normalize_workspace_name("alpha", "observe") == "alpha-observe"
    assert cli._normalize_workspace_name("alpha", "alpha-observe") == "alpha-observe"


def test_parser_accepts_status_flags_and_clarify_set_scores_flags():
    parser = build_parser()

    status_args = parser.parse_args(["status", "--next-only"])
    assert status_args.next_only is True

    detail_args = parser.parse_args(["status", "--detail"])
    assert detail_args.detail is True

    clarify_args = parser.parse_args(
        [
            "clarify",
            "set-scores",
            "--patch-file",
            "scores.json",
        ]
    )
    assert str(clarify_args.patch_file).endswith("scores.json")


def test_parser_rejects_removed_legacy_top_level_commands():
    parser = build_parser()
    help_text = parser.format_help()

    assert "advisor" not in help_text
    assert "prd-status" not in help_text
    assert "dev-readiness" not in help_text

    with pytest.raises(SystemExit):
        parser.parse_args(["prd-status"])
    with pytest.raises(SystemExit):
        parser.parse_args(["advisor", "protocol"])
    with pytest.raises(SystemExit):
        parser.parse_args(["dev-readiness"])


def test_parser_rejects_dev_readiness_cli_generator():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["dev", "readiness", "--workspace", "alpha-e2e", "--json"])

    args = parser.parse_args(["dev", "slices", "--workspace", "alpha-e2e", "--json"])
    assert args.command == "dev"
    assert args.subcommand == "slices"
    assert args.workspace == "alpha-e2e"


def test_debate_start_requires_axis():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["debate", "start", "--thesis", "x"])


def test_debate_start_accepts_force_flag():
    parser = build_parser()
    args = parser.parse_args(["debate", "start", "--thesis", "x", "--axis", "a vs b", "--force"])
    assert args.force is True


def test_debate_start_defaults_to_three_rounds():
    parser = build_parser()
    args = parser.parse_args(["debate", "start", "--thesis", "x", "--axis", "a vs b"])
    assert args.rounds == 3
