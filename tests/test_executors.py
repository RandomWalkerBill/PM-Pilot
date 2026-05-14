from __future__ import annotations

from pathlib import Path

import pytest

from pmagent import executors
from pmagent.executors import _claude, _codex, _kiro, registry


def test_is_inside_agent_detects_supported_markers(monkeypatch):
    for key in ("KIRO_SESSION", "CLAUDE_CODE", "CODEX_SESSION", "PMAGENT_AGENT_MODE"):
        monkeypatch.delenv("KIRO_SESSION", raising=False)
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CODEX_SESSION", raising=False)
        monkeypatch.delenv("PMAGENT_AGENT_MODE", raising=False)
        monkeypatch.setenv(key, "1")
        assert executors.is_inside_agent() is True


def test_is_inside_agent_false_without_markers(monkeypatch):
    for key in ("KIRO_SESSION", "CLAUDE_CODE", "CODEX_SESSION", "PMAGENT_AGENT_MODE"):
        monkeypatch.delenv(key, raising=False)
    assert executors.is_inside_agent() is False


def test_resolve_available_backend_respects_explicit_kiro_cli(monkeypatch):
    monkeypatch.setenv("PMAGENT_AGENT_BACKEND", "kiro-cli")
    monkeypatch.setattr(registry, "which", lambda command: f"/bin/{command}" if command == "kiro-cli" else None)
    assert executors.resolve_available_backend() == "kiro"


def test_resolve_available_backend_uses_priority(monkeypatch):
    monkeypatch.delenv("PMAGENT_AGENT_BACKEND", raising=False)
    monkeypatch.setattr(registry, "which", lambda command: f"/bin/{command}" if command in {"codex", "claude"} else None)
    assert executors.resolve_available_backend() == "claude"


def test_resolve_available_backend_treats_auto_as_autodetect(monkeypatch):
    monkeypatch.setenv("PMAGENT_AGENT_BACKEND", "auto")
    monkeypatch.setattr(registry, "which", lambda command: f"/bin/{command}" if command == "codex" else None)
    assert executors.resolve_available_backend() == "codex"


def test_precheck_executor_plan_reports_missing_cli(monkeypatch):
    monkeypatch.setattr(registry, "which", lambda command: None)
    issues = executors.precheck_executor_plan({"defender": {"exec": "claude"}})
    assert issues == [
        {
            "role": "defender",
            "issue": "missing_cli",
            "message": "executor `claude` is not installed or not on PATH",
        }
    ]


def test_run_kiro_builds_headless_argv(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    monkeypatch.setattr(_kiro, "which", lambda command: "kiro-cli")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["cwd"] == tmp_path
        return "done"

    monkeypatch.setattr(_kiro, "run_subprocess", fake_run)
    result = _kiro.run_kiro("prompt", cwd=tmp_path, trust_all_tools=True, timeout_seconds=12)
    assert result.content == "done"
    assert calls == [["kiro-cli", "chat", "--no-interactive", "--trust-all-tools", "prompt"]]


def test_run_claude_does_not_bypass_permissions_by_default(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    monkeypatch.setattr(_claude, "which", lambda command: "claude")
    monkeypatch.setattr(_claude.sys, "platform", "linux")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["stdin_text"] == "prompt"
        return "answer"

    monkeypatch.setattr(_claude, "run_subprocess", fake_run)
    result = _claude.run_claude("prompt", cwd=tmp_path, session_id="sid", model="m")
    assert result.content == "answer"
    assert result.session_id == "sid"
    assert calls == [["claude", "-p", "--model", "m", "--resume", "sid"]]


def test_run_claude_bypasses_permissions_only_when_trusted(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    monkeypatch.setattr(_claude, "which", lambda command: "claude")
    monkeypatch.setattr(_claude.sys, "platform", "linux")
    monkeypatch.setenv("PMAGENT_CLAUDE_MAX_TURNS", "7")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["stdin_text"] == "prompt"
        return "answer"

    monkeypatch.setattr(_claude, "run_subprocess", fake_run)
    result = _claude.run_claude("prompt", cwd=tmp_path, session_id="sid", model="m", trust_all_tools=True)
    assert result.content == "answer"
    assert result.session_id == "sid"
    assert calls == [
        [
            "claude",
            "-p",
            "--dangerously-skip-permissions",
            "--max-turns",
            "7",
            "--model",
            "m",
            "--resume",
            "sid",
        ]
    ]


def test_run_codex_fresh_run_uses_output_last_message(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    monkeypatch.setattr(_codex, "which", lambda command: "codex")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["stdin_text"] == "prompt"
        assert kwargs["output_file"].name.endswith(".md")
        return "answer"

    monkeypatch.setattr(_codex, "run_subprocess", fake_run)
    monkeypatch.setattr(_codex, "newest_codex_session", lambda **kwargs: "sid")

    result = _codex.run_codex("prompt", cwd=tmp_path, model="m")
    assert result.content == "answer"
    assert result.session_id == "sid"
    assert calls[0][:8] == [
        "codex",
        "exec",
        "--full-auto",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--model",
        "m",
    ]
    assert "--dangerously-bypass-approvals-and-sandbox" not in calls[0]
    assert calls[0][8] == "--output-last-message"
    assert Path(calls[0][9]).name.endswith(".md")
    assert calls[0][10] == "-"


def test_run_codex_bypasses_sandbox_only_when_trusted(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    monkeypatch.setattr(_codex, "which", lambda command: "codex")
    monkeypatch.setattr(_codex, "newest_codex_session", lambda **kwargs: "sid")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["output_file"].name.endswith(".md")
        return "answer"

    monkeypatch.setattr(_codex, "run_subprocess", fake_run)

    result = _codex.run_codex("prompt", cwd=tmp_path, trust_all_tools=True)
    assert result.content == "answer"
    assert result.session_id == "sid"
    assert calls[0][:4] == [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
    ]


def test_run_codex_resume_does_not_pass_sandbox_flag(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    monkeypatch.setattr(_codex, "which", lambda command: "codex")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["output_file"].name.endswith(".md")
        return "answer"

    monkeypatch.setattr(_codex, "run_subprocess", fake_run)

    result = _codex.run_codex("prompt", cwd=tmp_path, session_id="abc-123")
    assert result.session_id == "abc-123"
    assert calls[0][:4] == ["codex", "exec", "resume", "abc-123"]
    assert "--sandbox" not in calls[0]
    assert "--full-auto" in calls[0]
    assert "--dangerously-bypass-approvals-and-sandbox" not in calls[0]


def test_run_codex_resume_trusted_does_not_pass_sandbox_flag(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    monkeypatch.setattr(_codex, "which", lambda command: "codex")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return "answer"

    monkeypatch.setattr(_codex, "run_subprocess", fake_run)

    _codex.run_codex("prompt", cwd=tmp_path, session_id="abc-123", trust_all_tools=True)
    assert "--sandbox" not in calls[0]
    assert "--dangerously-bypass-approvals-and-sandbox" in calls[0]



    monkeypatch.setattr(registry, "run_kiro", lambda prompt, **kwargs: executors.ExecutorResult(content=prompt, session_id="sid"))
    result = executors.run_executor("kiro-cli", "hello", cwd=tmp_path)
    assert result.content == "hello"
    assert result.session_id == "sid"
