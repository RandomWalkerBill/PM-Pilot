import argparse
import json
import shutil
import uuid
from pathlib import Path

from pmagent import __version__, cli


def _make_test_dir(name: str) -> Path:
    base = Path.cwd() / ".test-workdir"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_init_writes_version_and_preserves_existing_user_data(monkeypatch, capsys):
    data_dir = _make_test_dir("test-init")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    try:
        assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0
        assert (data_dir / ".pmagent-version").read_text(encoding="utf-8") == f"{__version__}\n"
        assert (data_dir / "AGENTS.md").exists()
        assert (data_dir / "CLAUDE.md").exists()
        assert (data_dir / "MEMORY.md").exists()
        assert (data_dir / "GOAL_STATE.md").exists()
        assert (data_dir / "README.md").exists()
        assert (data_dir / "skills" / "README.md").exists()
        assert (data_dir / "skills" / "steps" / "write-prd" / "skill.md").exists()
        assert (data_dir / "templates" / "PRD_TEMPLATE.md").exists()
        assert (data_dir / "templates" / "WORKSPACE_SUMMARY_TEMPLATE.md").exists()
        assert (data_dir / "config" / "agent-workflow.yaml").exists()
        assert (data_dir / "config" / "debate-executors.yaml").exists()
        assert (data_dir / "config" / "executors.yaml").exists()
        assert (data_dir / "config" / "integrations.json").exists()
        assert (data_dir / "config" / "watchlist.json").exists()
        assert (data_dir / ".env").exists()
        assert (data_dir / ".env.example").exists()
        assert (data_dir / ".gitignore").exists()

        workflow_text = (data_dir / "config" / "agent-workflow.yaml").read_text(encoding="utf-8")
        debate_text = (data_dir / "config" / "debate-executors.yaml").read_text(encoding="utf-8")
        agents_text = (data_dir / "AGENTS.md").read_text(encoding="utf-8")
        claude_text = (data_dir / "CLAUDE.md").read_text(encoding="utf-8")
        env_text = (data_dir / ".env").read_text(encoding="utf-8")
        env_example_text = (data_dir / ".env.example").read_text(encoding="utf-8")
        gitignore_text = (data_dir / ".gitignore").read_text(encoding="utf-8")

        assert not (data_dir / "observation").exists()
        assert not any((data_dir / "workspaces").glob("*/observation"))
        assert "PMAgent PM Data runtime config." in env_text
        assert "PMAGENT_DATA_DIR" not in env_text
        assert "BRAVE_SEARCH_API_KEY" not in env_text
        assert "PMAGENT_GITHUB_REMOTE=<github-pm-data-repo-url>" in env_text
        assert "PMAGENT_FEISHU_APP_ID=<feishu-app-id>" in env_text
        assert "PMAGENT_FEISHU_APP_SECRET=<feishu-app-secret>" in env_text
        assert "PMAGENT_FEISHU_BASE_APP_TOKEN=<project-cards-base-app-token>" in env_text
        assert "PMAGENT_FEISHU_CARDS_TABLE_ID=<candidate-cards-table-id>" in env_text
        assert "PMAGENT_FEISHU_WIKI_SPACE_ID=my_library" in env_text
        assert "PMAGENT_FEISHU_WIKI_PUSH_COMMAND=<optional-custom-adapter-command>" in env_text
        assert "PMAgent PM Data runtime config example." in env_example_text
        assert "PMAGENT_FEISHU_BASE_APP_TOKEN=<project-cards-base-app-token>" in env_example_text
        assert ".env" in gitignore_text
        assert "cache/" in gitignore_text
        assert "source_of_truth_hierarchy" in workflow_text
        assert "feishu_sync_contract" in workflow_text
        assert "pmagent infra sync-status --workspace <workspace> --json" in workflow_text
        assert 'default_adapter: "builtin-lark"' in workflow_text
        assert "PMAGENT_FEISHU_WIKI_SPACE_ID" in workflow_text
        assert "PMAGENT_FEISHU_WIKI_PUSH_COMMAND" in workflow_text
        assert "executor_config_path: \"config/debate-executors.yaml\"" in workflow_text
        assert "attacker:" in debate_text
        assert "\"config/agent-workflow.yaml\"" in workflow_text
        assert "workspace_summary_contract" in workflow_text
        assert "skill_navigation" in workflow_text
        assert "recommended_skills_source" in workflow_text
        assert 'default_skill_namespace: "pmagent-local"' in workflow_text
        assert "Never write global Codex/OMX skills into PMAgent recommended_skills" in workflow_text
        assert "skills/steps/dev-readiness/skill.md" in workflow_text
        assert 'execution_owner: "external-agent"' in workflow_text
        assert "skills/steps/dev-run-record/skill.md" in workflow_text
        assert "skills/steps/write-prd/skill.md" in workflow_text
        assert "## 文档定位" in agents_text
        assert "## 文档定位" in claude_text
        assert "candidate-review" in agents_text
        assert "workspace-close" in agents_text
        assert "PMAgent 源码仓库只是 CLI / scaffold" in agents_text
        assert "PM Data 主链路只用本地" in agents_text
        assert "PM Data 主链路只用本地" in claude_text
        assert "## 飞书同步规则" in agents_text
        assert "feishu_sync_pending" in agents_text
        assert "recommended_skills" in agents_text
        assert "## Hard Workflow Gates" in agents_text
        assert "## Agent Determinism Gates" in agents_text
        assert "## Recommended Practices" in agents_text
        assert "gate_index:" in workflow_text
        assert "hard_workflow:" in workflow_text
        assert "agent_determinism:" in workflow_text

        assert not (data_dir / "skills" / "modes" / "zero-to-one" / "skill.md").exists()
        dev_readiness_text = (data_dir / "skills" / "steps" / "dev-readiness" / "skill.md").read_text(encoding="utf-8")
        dev_run_text = (data_dir / "skills" / "steps" / "dev-run-record" / "skill.md").read_text(encoding="utf-8")
        assert "vertical slices" in dev_readiness_text
        assert "external Agent" in dev_readiness_text
        assert "pmagent dev slices" in dev_readiness_text
        assert "pmagent dev readiness" not in dev_readiness_text
        assert "run evidence" in dev_run_text

        scaffold_readme = (data_dir / "README.md").read_text(encoding="utf-8")
        for scaffold_text in (agents_text, claude_text, scaffold_readme):
            assert "pmagent dev readiness" not in scaffold_text
            assert "pmagent dev-readiness" not in scaffold_text

        projects_path = data_dir / "config" / "projects.json"
        projects_path.write_text('{"custom": true}\n', encoding="utf-8")
        workflow_path = data_dir / "config" / "agent-workflow.yaml"
        workflow_path.write_text("custom: true\n", encoding="utf-8")
        custom_skill = data_dir / "skills" / "custom.md"
        custom_skill.write_text("# custom skill\n", encoding="utf-8")
        env_path = data_dir / ".env"
        env_path.write_text("PMAGENT_GITHUB_REMOTE=https://example.invalid/pm-data.git\n", encoding="utf-8")
        env_example_path = data_dir / ".env.example"
        env_example_path.write_text("stale example\n", encoding="utf-8")
        gitignore_path = data_dir / ".gitignore"
        gitignore_path.write_text("custom-ignore\n", encoding="utf-8")

        assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0
        assert projects_path.read_text(encoding="utf-8") == '{"custom": true}\n'
        assert workflow_path.read_text(encoding="utf-8") == "custom: true\n"
        assert custom_skill.read_text(encoding="utf-8") == "# custom skill\n"
        assert env_path.read_text(encoding="utf-8") == "PMAGENT_GITHUB_REMOTE=https://example.invalid/pm-data.git\n"
        assert "PMAgent PM Data runtime config example." in env_example_path.read_text(encoding="utf-8")
        assert gitignore_path.read_text(encoding="utf-8") == "custom-ignore\n"

        captured = capsys.readouterr().out
        assert "SKIP config/projects.json (exists, user data preserved)" in captured
        assert "SKIP .env (exists, user secrets preserved)" in captured
        assert "SKIP .gitignore (exists, user data preserved)" in captured
        assert "Initialized data directory:" in captured
        assert "project-scoped observations/" in captured
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_upgrade_replaces_managed_section_and_preserves_user_section(monkeypatch, capsys):
    data_dir = _make_test_dir("test-upgrade")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    try:
        assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0

        agents_path = data_dir / "AGENTS.md"
        current = agents_path.read_text(encoding="utf-8")
        current = current.replace("PMAGENT:VERSION:0.1.0", "PMAGENT:VERSION:0.0.1", 1)
        current = current.rstrip() + "\n\n- keep me\n"
        agents_path.write_text(current, encoding="utf-8")

        claude_path = data_dir / "CLAUDE.md"
        current_claude = claude_path.read_text(encoding="utf-8")
        current_claude = current_claude.replace("PMAGENT:VERSION:0.1.0", "PMAGENT:VERSION:0.0.1", 1)
        current_claude = current_claude.rstrip() + "\n\n- keep me too\n"
        claude_path.write_text(current_claude, encoding="utf-8")

        assert cli.cmd_upgrade(argparse.Namespace(data_dir=str(data_dir))) == 0

        upgraded = agents_path.read_text(encoding="utf-8")
        upgraded_claude = claude_path.read_text(encoding="utf-8")
        assert "<!-- PMAGENT:VERSION:0.1.0 -->" in upgraded
        assert "- keep me" in upgraded
        assert "<!-- PMAGENT:VERSION:0.1.0 -->" in upgraded_claude
        assert "- keep me too" in upgraded_claude
        assert (data_dir / ".pmagent-version").read_text(encoding="utf-8") == f"{__version__}\n"
        captured = capsys.readouterr().out
        assert "upgrade complete" in captured
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_upgrade_refreshes_mainline_assets_and_preserves_user_added_files(monkeypatch):
    data_dir = _make_test_dir("test-upgrade-refresh")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    try:
        assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0

        stale_paths = [
            data_dir / "README.md",
            data_dir / "GOAL_STATE.md",
            data_dir / ".env.example",
            data_dir / "config" / "agent-workflow.yaml",
            data_dir / "config" / "debate-executors.yaml",
            data_dir / "config" / "executors.yaml",
            data_dir / "config" / "watchlist.json",
            data_dir / "skills" / "README.md",
            data_dir / "templates" / "PRD_TEMPLATE.md",
        ]
        for path in stale_paths:
            path.write_text("stale\n", encoding="utf-8")

        custom_skill = data_dir / "skills" / "custom.md"
        custom_skill.write_text("# custom skill\n", encoding="utf-8")
        custom_template = data_dir / "templates" / "CUSTOM_TEMPLATE.md"
        custom_template.write_text("# custom template\n", encoding="utf-8")
        gitignore_path = data_dir / ".gitignore"
        gitignore_path.write_text(".env\n.env.*\ncustom-cache/\n", encoding="utf-8")

        assert cli.cmd_upgrade(argparse.Namespace(data_dir=str(data_dir))) == 0

        scaffold_root = cli.package_root() / "scaffold"
        package_root = cli.package_root()
        assert (data_dir / "README.md").read_text(encoding="utf-8") == (scaffold_root / "README.md").read_text(encoding="utf-8")
        assert (data_dir / "GOAL_STATE.md").read_text(encoding="utf-8") == (scaffold_root / "GOAL_STATE.md").read_text(encoding="utf-8")
        assert (data_dir / ".env.example").read_text(encoding="utf-8") == (scaffold_root / ".env.example").read_text(encoding="utf-8")
        assert (data_dir / "config" / "agent-workflow.yaml").read_text(encoding="utf-8") == (scaffold_root / "config" / "agent-workflow.yaml").read_text(encoding="utf-8")
        assert (data_dir / "config" / "debate-executors.yaml").read_text(encoding="utf-8") == (scaffold_root / "config" / "debate-executors.yaml").read_text(encoding="utf-8")
        assert (data_dir / "config" / "executors.yaml").read_text(encoding="utf-8") == (scaffold_root / "config" / "executors.yaml").read_text(encoding="utf-8")
        assert (data_dir / "config" / "watchlist.json").read_text(encoding="utf-8") == (scaffold_root / "config" / "watchlist.json").read_text(encoding="utf-8")
        assert (data_dir / "skills" / "README.md").read_text(encoding="utf-8") == (package_root / "skills" / "README.md").read_text(encoding="utf-8")
        assert (data_dir / "templates" / "PRD_TEMPLATE.md").read_text(encoding="utf-8") == (package_root / "templates" / "PRD_TEMPLATE.md").read_text(encoding="utf-8")
        assert "custom-cache/" in gitignore_path.read_text(encoding="utf-8")
        assert "!.env.example" in gitignore_path.read_text(encoding="utf-8")
        assert custom_skill.read_text(encoding="utf-8") == "# custom skill\n"
        assert custom_template.read_text(encoding="utf-8") == "# custom template\n"
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_upgrade_refreshes_changed_managed_section_even_when_version_matches(monkeypatch):
    data_dir = _make_test_dir("test-upgrade-managed-content")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    try:
        assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0
        agents_path = data_dir / "AGENTS.md"
        agents_path.write_text(
            "\n".join(
                [
                    f"<!-- PMAGENT:VERSION:{__version__} -->",
                    "",
                    "<!-- PMAGENT:MANAGED:BEGIN -->",
                    "# stale managed body",
                    "<!-- PMAGENT:MANAGED:END -->",
                    "",
                    "## User Section",
                    "keep me",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        assert cli.cmd_upgrade(argparse.Namespace(data_dir=str(data_dir))) == 0

        upgraded = agents_path.read_text(encoding="utf-8")
        assert "# stale managed body" not in upgraded
        assert "## 飞书同步规则" in upgraded
        assert "## User Section" in upgraded
        assert "keep me" in upgraded
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_upgrade_merges_claude_pmagent_hooks_and_preserves_user_settings(monkeypatch):
    data_dir = _make_test_dir("test-upgrade-claude-hooks")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    try:
        assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0

        settings_path = data_dir / ".claude" / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "permissions": {"allow": ["Bash(ls:*)"]},
                    "hooks": {
                        "SessionStart": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "pmagent hook session_bootstrap",
                                        "timeout": 10,
                                    },
                                    {"type": "command", "command": "echo custom session", "timeout": 1},
                                ],
                            }
                        ],
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "pmagent hook pre_bash_guard",
                                        "timeout": 5,
                                    },
                                    {"type": "command", "command": "echo custom bash", "timeout": 1},
                                ],
                            },
                            {
                                "matcher": "Read",
                                "hooks": [{"type": "command", "command": "echo custom read", "timeout": 1}],
                            },
                        ],
                        "CustomEvent": [
                            {"hooks": [{"type": "command", "command": "echo custom event", "timeout": 1}]}
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        assert cli.cmd_upgrade(argparse.Namespace(data_dir=str(data_dir))) == 0

        upgraded = json.loads(settings_path.read_text(encoding="utf-8"))
        assert upgraded["permissions"] == {"allow": ["Bash(ls:*)"]}

        commands = [
            hook["command"]
            for group in upgraded["hooks"].values()
            for matcher in group
            for hook in matcher.get("hooks", [])
        ]
        assert "echo custom session" in commands
        assert "echo custom bash" in commands
        assert "echo custom read" in commands
        assert "echo custom event" in commands
        assert not any(command.startswith("pmagent hook ") for command in commands)
        assert "python3 -m pmagent.cli hook session_bootstrap || python -m pmagent.cli hook session_bootstrap" in commands
        assert "python3 -m pmagent.cli hook pre_bash_guard || python -m pmagent.cli hook pre_bash_guard" in commands
        assert "python3 -m pmagent.cli hook response_validator || python -m pmagent.cli hook response_validator" in commands
        assert not (data_dir / ".claude" / "settings.pmagent.json").exists()
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_upgrade_skips_unmanaged_existing_file(capsys):
    data_dir = _make_test_dir("test-unmanaged")
    try:
        (data_dir / "AGENTS.md").write_text("# custom\n", encoding="utf-8")
        (data_dir / "MEMORY.md").write_text("# custom\n", encoding="utf-8")

        assert cli.cmd_upgrade(argparse.Namespace(data_dir=str(data_dir))) == 0

        captured = capsys.readouterr().out
        assert "SKIP AGENTS.md (exists, no managed markers - manual migration required)" in captured
        assert "SKIP MEMORY.md (exists, no managed markers - manual migration required)" in captured
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_upgrade_renames_legacy_lowercase_claude_file(monkeypatch):
    data_dir = _make_test_dir("test-claude-rename")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    try:
        assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0
        uppercase = data_dir / "CLAUDE.md"
        lowercase = data_dir / "claude.md"
        uppercase.rename(lowercase)

        assert cli.cmd_upgrade(argparse.Namespace(data_dir=str(data_dir))) == 0

        assert (data_dir / "CLAUDE.md").exists()
        assert "CLAUDE.md" in {path.name for path in data_dir.iterdir()}
        assert "claude.md" not in {path.name for path in data_dir.iterdir()}
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
