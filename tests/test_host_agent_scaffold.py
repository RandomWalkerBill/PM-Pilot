"""Tests for the pmagent host-agent config scaffolding + hook CLI."""

from __future__ import annotations

import argparse
import io
import json
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from pmagent import cli


def _make_test_dir(name: str) -> Path:
    base = Path.cwd() / ".test-workdir"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------- hook CLI ----------


def test_hook_cli_list_prints_all_hooks(capsys: pytest.CaptureFixture) -> None:
    rc = cli.cmd_hook(argparse.Namespace(hook_name=None, list_hooks=True))
    assert rc == 0
    captured = capsys.readouterr().out
    expected = {
        "session_bootstrap",
        "state_surface",
        "pre_bash_guard",
        "pre_write_guard",
        "post_mutation_check",
        "response_validator",
    }
    assert expected.issubset(set(captured.split()))


def test_hook_cli_rejects_unknown_hook() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.cmd_hook(argparse.Namespace(hook_name="nope", list_hooks=False))
    assert "unknown hook" in str(exc.value)


def test_hook_cli_dispatches_to_hook_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling the CLI with a valid hook name must actually invoke that hook.

    We wire stdin to an empty payload and point the hook at a throwaway data
    dir so the bootstrap runs its fail-open path to stdout.
    """

    data_dir = _make_test_dir("hook-dispatch")
    monkeypatch.setenv("PMAGENT_DATA_DIR", str(data_dir))
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    out = io.StringIO()
    err = io.StringIO()
    exit_code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.cmd_hook(argparse.Namespace(hook_name="session_bootstrap", list_hooks=False))
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
    assert exit_code == 0
    # session_bootstrap always emits a framed hook block when it runs.
    assert "<pmagent-hook" in out.getvalue()


# ---------- init copies host-agent configs ----------


def test_init_copies_claude_and_codex_scaffold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _make_test_dir("host-agent-copy")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0

    claude_path = data_dir / ".claude" / "settings.json"
    codex_path = data_dir / ".codex" / "config.toml.example"
    assert claude_path.exists(), ".claude/settings.json should be copied into data_dir"
    assert codex_path.exists(), ".codex/config.toml.example should be copied into data_dir"

    claude_cfg = json.loads(claude_path.read_text(encoding="utf-8"))
    hook_section = claude_cfg.get("hooks") or {}
    # All hook event groups must be wired and use Python module execution so
    # Claude Code does not depend on the `pmagent` console script being on PATH.
    assert set(hook_section.keys()) == {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
    }
    bash_commands = [
        entry["command"]
        for group in hook_section.values()
        for matcher in group
        for entry in matcher.get("hooks", [])
    ]
    assert all(cmd.startswith("python3 -m pmagent.cli hook ") for cmd in bash_commands)
    assert all(" || python -m pmagent.cli hook " in cmd for cmd in bash_commands)
    expected_hook_names = {
        "session_bootstrap",
        "state_surface",
        "pre_bash_guard",
        "pre_write_guard",
        "post_mutation_check",
        "response_validator",
    }
    seen = {cmd.split()[-1] for cmd in bash_commands}
    assert expected_hook_names.issubset(seen)

    codex_text = codex_path.read_text(encoding="utf-8")
    assert "pmagent × Codex CLI configuration template" in codex_text
    assert "approval_policy" in codex_text


def test_init_does_not_overwrite_existing_claude_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _make_test_dir("host-agent-preserve")
    # Seed a user-owned .claude/settings.json before init runs.
    user_settings = data_dir / ".claude" / "settings.json"
    user_settings.parent.mkdir(parents=True, exist_ok=True)
    user_payload = {"permissions": {"allow": ["Bash(ls:*)"]}}
    user_settings.write_text(
        json.dumps(user_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0

    # Original user file untouched.
    assert json.loads(user_settings.read_text(encoding="utf-8")) == user_payload

    # pmagent template landed at a sibling path that preserves the suffix.
    sibling = data_dir / ".claude" / "settings.pmagent.json"
    assert sibling.exists()
    sibling_payload = json.loads(sibling.read_text(encoding="utf-8"))
    assert "hooks" in sibling_payload


def test_init_refreshes_codex_example_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _make_test_dir("host-agent-codex-fresh")
    monkeypatch.setattr(cli, "write_global_config", lambda **kwargs: data_dir)
    assert cli.cmd_init(argparse.Namespace(dir=str(data_dir))) == 0
    assert (data_dir / ".codex" / "config.toml.example").exists()
