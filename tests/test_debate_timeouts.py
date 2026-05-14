from __future__ import annotations

from pathlib import Path

import pytest

from pmagent.debate.orchestrator import (
    ROUND_EXEC_TIMEOUT_SECONDS,
    SYNTHESIS_EXEC_TIMEOUT_SECONDS,
    run_debate,
    validate_round_content,
)
from pmagent.executors import ExecutorResult


def test_default_debate_timeouts_allow_slow_cli_backends():
    assert ROUND_EXEC_TIMEOUT_SECONDS >= 180
    assert SYNTHESIS_EXEC_TIMEOUT_SECONDS >= 180


def test_run_debate_uses_env_timeout_overrides(monkeypatch, tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    (workspace_root / "Requirement.md").write_text("# Requirement\n\nRun a bounded smoke debate.\n", encoding="utf-8")
    topic_dir = workspace_root / "context" / "debates" / "timeout-smoke"
    topic_dir.mkdir(parents=True)

    monkeypatch.setenv("PMAGENT_DEBATE_ROUND_TIMEOUT", "3.5")
    monkeypatch.setenv("PMAGENT_DEBATE_SYNTHESIS_TIMEOUT", "4.5")

    calls: list[float | None] = []

    def fake_runner(
        executor_id: str,
        prompt: str,
        *,
        cwd: Path,
        session_id: str | None = None,
        model: str | None = None,
        schema: dict | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutorResult:
        del executor_id, cwd, session_id, model, schema
        calls.append(timeout_seconds)
        if "Debate 记录整理者" in prompt:
            return ExecutorResult(
                "# Debate Synthesis: topic\n"
                "\n"
                "## Thesis\nShould smoke tests be bounded?\n"
                "\n"
                "## Chosen Axis\nbounded smoke vs broad automation\n"
                "\n"
                "## Convergence\n- both sides want signal\n"
                "\n"
                "## Core Divergences\n"
                "- scope\n"
                "  - Defender 立场: bounded smoke is easier to trust\n"
                "  - Attacker 立场: broad automation finds integration gaps\n"
                "  - 人需要裁决的判断: choose first confidence target\n"
                "\n"
                "## Unexpected Findings\n- timeout controls are part of testability\n"
                "\n"
                "## Acknowledgements / Adjustments\n- keep smoke small\n"
                "\n"
                "## Quality Flags\n- none\n"
                "\n"
                "## Recommended Next Action\nrun the bounded smoke path\n",
                "synth",
            )
        return ExecutorResult(
            "## Core Claim\nclaim\n\n## Arguments\n1. first argument\n2. second argument\n\n## Closing Line\nclose\n",
            "round",
        )

    run_debate(
        topic_dir=topic_dir,
        workspace_root=workspace_root,
        thesis="Should smoke tests be bounded?",
        axis="bounded smoke vs broad automation",
        defender_exec="codex",
        attacker_exec="codex",
        synthesizer_exec="codex",
        round_count=1,
        executor_runner=fake_runner,
    )

    assert calls == [3.5, 3.5, 4.5]


def test_run_debate_marks_failed_when_synthesis_executor_fails(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    (workspace_root / "Requirement.md").write_text("# Requirement\n\nRun a bounded smoke debate.\n", encoding="utf-8")
    topic_dir = workspace_root / "context" / "debates" / "synthesis-failure"
    topic_dir.mkdir(parents=True)

    def fake_runner(
        executor_id: str,
        prompt: str,
        *,
        cwd: Path,
        session_id: str | None = None,
        model: str | None = None,
        schema: dict | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutorResult:
        del executor_id, cwd, session_id, model, schema, timeout_seconds
        if "Debate 记录整理者" in prompt:
            raise RuntimeError("synth timeout")
        return ExecutorResult(
            "## Core Claim\nclaim\n\n## Arguments\n1. first argument\n2. second argument\n\n## Closing Line\nclose\n",
            "round",
        )

    with pytest.raises(RuntimeError, match="synth timeout"):
        run_debate(
            topic_dir=topic_dir,
            workspace_root=workspace_root,
            thesis="Should smoke tests be bounded?",
            axis="bounded smoke vs broad automation",
            defender_exec="codex",
            attacker_exec="codex",
            synthesizer_exec="codex",
            round_count=1,
            executor_runner=fake_runner,
        )

    assert not (topic_dir / "synthesis.md").exists()
    status = (topic_dir / "status.json").read_text(encoding="utf-8")
    signal = (topic_dir / "signal.json").read_text(encoding="utf-8")
    assert '"state": "failed"' in status
    assert "synth timeout" in status
    assert '"event": "failed"' in signal


def test_validate_round_content_accepts_claude_side_effect_markdown_style():
    payload = validate_round_content(
        "# Round 1 — Pro (Defender)\n"
        "\n"
        "## Thesis\n"
        "Markdown artifacts should remain canonical.\n"
        "\n"
        "## Position\n"
        "The orchestrator should normalize useful debate markdown.\n"
        "\n"
        "## Arguments\n"
        "### 1. Markdown artifacts are the canonical output format\n"
        "The design docs say the orchestrator owns artifact layout and review.\n"
        "\n"
        "### 2. Real agents often use subheadings for numbered arguments\n"
        "Rejecting this shape causes avoidable failed foreground runs.\n"
        "\n"
        "## Conclusion\n"
        "Normalize the round into canonical headings instead of failing the topic.\n"
    )

    assert payload["core_claim"]
    assert len(payload["arguments"]) == 2
    assert payload["arguments"][0].startswith("Markdown artifacts are the canonical output format")
    assert payload["closing_line"].startswith("Normalize the round")


def test_run_debate_normalizes_round_files_written_by_tool_using_executor(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    (workspace_root / "Requirement.md").write_text("# Requirement\n\nRun a bounded smoke debate.\n", encoding="utf-8")
    topic_dir = workspace_root / "context" / "debates" / "side-effect-round"
    topic_dir.mkdir(parents=True)
    calls: list[str] = []

    def side_effect_round(side: str) -> str:
        label = "Pro" if side == "pro" else "Con"
        return (
            f"# Round 1 — {label}\n"
            "\n"
            "## Thesis\n"
            "Should smoke tests be bounded?\n"
            "\n"
            "## Position\n"
            f"The {label} side has a concrete position.\n"
            "\n"
            "## Arguments\n"
            "### 1. Markdown artifacts are the canonical output format\n"
            "The orchestrator can normalize useful markdown into its canonical files.\n"
            "\n"
            "### 2. Side-effect files should not strand the debate\n"
            "A valid file written during the call is better evidence than an invalid stdout note.\n"
            "\n"
            "## Conclusion\n"
            f"Use the {label} side's normalized artifact.\n"
        )

    def fake_runner(
        executor_id: str,
        prompt: str,
        *,
        cwd: Path,
        session_id: str | None = None,
        model: str | None = None,
        schema: dict | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutorResult:
        del executor_id, cwd, session_id, model, schema, timeout_seconds
        calls.append(prompt)
        if "Debate 记录整理者" in prompt:
            return ExecutorResult(
                "# Debate Synthesis: side-effect-round\n"
                "\n"
                "## Thesis\nShould smoke tests be bounded?\n"
                "\n"
                "## Chosen Axis\nbounded smoke vs broad automation\n"
                "\n"
                "## Convergence\n- both sides want signal\n"
                "\n"
                "## Core Divergences\n"
                "- scope\n"
                "  - Defender 立场: bounded smoke is easier to trust\n"
                "  - Attacker 立场: broad automation finds integration gaps\n"
                "  - 人需要裁决的判断: choose first confidence target\n"
                "\n"
                "## Unexpected Findings\n- side-effect files can still be normalized\n"
                "\n"
                "## Acknowledgements / Adjustments\n- keep smoke small\n"
                "\n"
                "## Quality Flags\n- none\n"
                "\n"
                "## Recommended Next Action\nrun the bounded smoke path\n",
                "synth",
            )
        if "你必须维护的这一侧" in prompt and len(calls) == 1:
            (topic_dir / "round-1-pro.md").write_text(side_effect_round("pro"), encoding="utf-8")
        else:
            (topic_dir / "round-1-con.md").write_text(side_effect_round("con"), encoding="utf-8")
        return ExecutorResult("Wrote the requested debate round to disk.", "round")

    run_debate(
        topic_dir=topic_dir,
        workspace_root=workspace_root,
        thesis="Should smoke tests be bounded?",
        axis="bounded smoke vs broad automation",
        defender_exec="claude",
        attacker_exec="claude",
        synthesizer_exec="claude",
        round_count=1,
        executor_runner=fake_runner,
    )

    assert len(calls) == 3
    pro = (topic_dir / "round-0-pro.md").read_text(encoding="utf-8")
    con = (topic_dir / "round-0-con.md").read_text(encoding="utf-8")
    assert "## Core Claim" in pro
    assert "## Arguments" in pro
    assert "Markdown artifacts are the canonical output format" in pro
    assert "Use the Pro side's normalized artifact." in pro
    assert "Use the Con side's normalized artifact." in con
    assert (topic_dir / "synthesis.md").exists()
    assert '"state": "completed"' in (topic_dir / "status.json").read_text(encoding="utf-8")


def test_run_debate_retries_failed_attacker_with_defender_executor(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    (workspace_root / "Requirement.md").write_text("# Requirement\n\nRun a bounded smoke debate.\n", encoding="utf-8")
    topic_dir = workspace_root / "context" / "debates" / "fallback-attacker"
    topic_dir.mkdir(parents=True)
    calls: list[str] = []

    def valid_round(label: str) -> ExecutorResult:
        return ExecutorResult(
            f"## Core Claim\n{label} claim\n\n## Arguments\n1. first argument\n2. second argument\n\n## Closing Line\n{label} close\n",
            label,
        )

    def fake_runner(
        executor_id: str,
        prompt: str,
        *,
        cwd: Path,
        session_id: str | None = None,
        model: str | None = None,
        schema: dict | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutorResult:
        del prompt, cwd, session_id, model, schema, timeout_seconds
        calls.append(executor_id)
        if executor_id == "codex":
            raise RuntimeError("codex timeout")
        if len(calls) >= 4:
            return ExecutorResult(
                "# Debate Synthesis: fallback-attacker\n"
                "\n"
                "## Thesis\nArtifact contracts?\n"
                "\n"
                "## Chosen Axis\nstrict vs free\n"
                "\n"
                "## Convergence\n- both sides need reliability\n"
                "\n"
                "## Core Divergences\n"
                "- enforcement\n"
                "  - Defender 立场: strict contracts\n"
                "  - Attacker 立场: autonomy still matters\n"
                "  - 人需要裁决的判断: choose the contract strictness\n"
                "\n"
                "## Unexpected Findings\n- fallback keeps foreground runs bounded\n"
                "\n"
                "## Acknowledgements / Adjustments\n- record fallback evidence\n"
                "\n"
                "## Quality Flags\n- none\n"
                "\n"
                "## Recommended Next Action\nreview the fallback synthesis\n",
                "synth",
            )
        return valid_round(executor_id)

    run_debate(
        topic_dir=topic_dir,
        workspace_root=workspace_root,
        thesis="Artifact contracts?",
        axis="strict vs free",
        defender_exec="claude",
        attacker_exec="codex",
        synthesizer_exec="claude",
        round_count=1,
        executor_runner=fake_runner,
    )

    assert calls == ["claude", "codex", "claude", "claude"]
    assert (topic_dir / "round-0-con.md").exists()
    assert (topic_dir / "synthesis.md").exists()
    assert '"state": "completed"' in (topic_dir / "status.json").read_text(encoding="utf-8")
