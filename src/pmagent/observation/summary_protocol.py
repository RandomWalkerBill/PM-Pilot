from __future__ import annotations

import hashlib
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


CORE_BEGIN = "<!-- PMAGENT:SUMMARY:CORE:BEGIN -->"
CORE_END = "<!-- PMAGENT:SUMMARY:CORE:END -->"
OBS_BEGIN = "<!-- PMAGENT:SUMMARY:OBSERVATION:BEGIN -->"
OBS_END = "<!-- PMAGENT:SUMMARY:OBSERVATION:END -->"
SUMMARY_MARKERS = (CORE_BEGIN, CORE_END, OBS_BEGIN, OBS_END)
SUMMARY_REQUIRED_HEADINGS = (
    "## Current Goal",
    "## Current State",
    "## Current PRD",
    "## Readiness Overview",
    "## Recent Observation",
)


@dataclass(frozen=True)
class SummaryStatus:
    state: str
    reason: str


def _lock_timeout_seconds() -> float:
    raw = os.environ.get("PMAGENT_STATE_LOCK_TIMEOUT", "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return 10.0


@contextmanager
def _summary_write_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.time() + _lock_timeout_seconds()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > max(_lock_timeout_seconds() * 3, 30.0)
            except OSError:
                stale = False
            if stale:
                lock_path.unlink(missing_ok=True)
                continue
            if time.time() >= deadline:
                raise RuntimeError(f"timed out waiting for workspace summary lock: {lock_path}")
            time.sleep(0.05)
            continue
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_text_with_retry(path: Path) -> str:
    deadline = time.time() + _lock_timeout_seconds()
    last_error: Exception | None = None
    while True:
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError as exc:
            last_error = exc
            if time.time() >= deadline:
                raise last_error
            time.sleep(0.05)


def inspect_summary(path: Path) -> SummaryStatus:
    if not path.exists():
        return SummaryStatus("missing_document", "workspace-summary.md is missing")

    text = _read_text_with_retry(path)
    counts = {marker: text.count(marker) for marker in SUMMARY_MARKERS}
    if any(count != 1 for count in counts.values()):
        return SummaryStatus("invalid_markers", "summary markers are missing, duplicated, or malformed")

    positions = [text.find(marker) for marker in SUMMARY_MARKERS]
    if positions != sorted(positions):
        return SummaryStatus("invalid_markers", "summary markers are out of order")

    heading_counts = {heading: len(re.findall(rf"(?m)^{re.escape(heading)}\s*$", text)) for heading in SUMMARY_REQUIRED_HEADINGS}
    duplicated = [heading for heading, count in heading_counts.items() if count != 1]
    if duplicated:
        return SummaryStatus(
            "invalid_headings",
            "summary headings are missing or duplicated: " + ", ".join(duplicated),
        )

    return SummaryStatus("valid", "summary markers are valid")


def build_observation_section(
    *,
    workspace: str,
    run_id: str,
    findings_count: int,
    candidate_count: int,
    status: str,
    enabled: bool | None = None,
    cadence: str | None = None,
    next_scheduled_run: str | None = None,
    queue_summary: str | None = None,
    needs_review: bool | None = None,
    catch_up_needed: bool | None = None,
) -> str:
    mode = "scheduled" if enabled else "manual"
    return "\n".join(
        [
            "## Observation Focus",
            "",
            "<!-- What this workspace should keep watching over time. -->",
            "",
            "## Recent Observation",
            "",
            f"- Observation enabled: {'yes' if enabled else 'no'}" if enabled is not None else "- Observation enabled:",
            f"- Observation mode: {mode}" if enabled is not None else "- Observation mode:",
            f"- Cadence: {cadence or ''}".rstrip(),
            f"- Last run: {run_id}",
            f"- Next scheduled run: {next_scheduled_run or 'not scheduled'}",
            f"- Queue summary: {queue_summary or 'inbox=0 accepted=0 rejected=0 snoozed=0'}",
            f"- Needs review: {'yes' if needs_review else 'no'}" if needs_review is not None else "- Needs review:",
            f"- Catch-up needed: {'yes' if catch_up_needed else 'no'}" if catch_up_needed is not None else "- Catch-up needed:",
            f"- Candidate updates: {candidate_count}",
            f"- workspace: {workspace}",
            f"- findings_count: {findings_count}",
            f"- status: {status}",
        ]
    )


def build_workspace_summary_document(*, workspace: str, observation_section: str | None = None) -> str:
    return build_workspace_summary_document_with_core(
        workspace=workspace,
        core_section=None,
        observation_section=observation_section,
    )


def build_workspace_summary_document_with_core(
    *,
    workspace: str,
    core_section: str | None = None,
    observation_section: str | None = None,
) -> str:
    core_body = core_section or "\n".join(
        [
            "## Current Goal",
            "",
            "<!-- Fill this in from Requirement / user intent. -->",
            "",
            "## Business Context / Current Scope",
            "",
            "- Current scope:",
            "- Business context:",
            "",
            "## Current State",
            "",
            "- Phase: `clarifying`",
            "- Active step:",
            "- Pending user decision:",
            "- Next recommended step:",
            "",
            "## Current PRD",
            "",
            "- Exists: `no`",
            "- Canonical path:",
            "- Current scope:",
            "",
            "## Current Understanding",
            "",
            "<!-- Current validated conclusions distilled from requirement/research/context/decisions. -->",
            "",
            "## Key Decisions",
            "",
            "<!-- Link decision records rather than copying full text. -->",
            "",
            "## Open Questions",
            "",
            "<!-- Questions that still affect direction, PRD scope, or execution readiness. -->",
            "",
            "## Readiness Overview",
            "",
            "- Readiness phase:",
            "- Readiness score:",
            "- Blocking gates:",
            "- Readiness summary:",
            "",
            "## Important Links",
            "",
            "- Requirement: `Requirement.md`",
            "- Research:",
            "- Decisions:",
            "- PRD:",
        ]
    )
    observation_body = observation_section or "\n".join(
        [
            "## Observation Focus",
            "",
            "<!-- What the observation layer should watch for this workspace. -->",
            "",
            "## Recent Observation",
            "",
            "- Observation enabled: no",
            "- Observation mode: manual",
            "- Cadence: manual",
            "- Last run: not started",
            "- Next scheduled run: not scheduled",
            "- Queue summary: inbox=0 accepted=0 rejected=0 snoozed=0",
            "- Needs review: no",
            "- Catch-up needed: no",
            "- Candidate updates: 0",
            "- Important pending signals: none",
        ]
    )
    return "\n".join(
        [
            f"# Workspace Summary: {workspace}",
            "",
            "> This file is the compressed current-state entry point for agents and observation executors.",
            "> It does not replace `Requirement.md`, `research/`, `context/`, `decisions/`, or `prd/`.",
            "",
            CORE_BEGIN,
            core_body.rstrip(),
            CORE_END,
            "",
            OBS_BEGIN,
            observation_body.rstrip(),
            OBS_END,
            "",
        ]
    )


def summary_revision(path: Path) -> str:
    return hashlib.sha256(_read_text_with_retry(path).encode("utf-8")).hexdigest()


def replace_observation_section(
    path: Path,
    section_body: str,
    *,
    expected_revision: str | None = None,
) -> None:
    with _summary_write_lock(path):
        text = _read_text_with_retry(path)
        if expected_revision is not None:
            current_revision = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if current_revision != expected_revision:
                raise RuntimeError("workspace summary revision changed before writeback")
        start = text.find(OBS_BEGIN)
        end = text.find(OBS_END)
        if start == -1 or end == -1 or start > end:
            raise ValueError("invalid observation summary markers")

        updated = (
            text[: start + len(OBS_BEGIN)]
            + "\n"
            + section_body.rstrip()
            + "\n"
            + text[end:]
        )
        _atomic_write_text(path, updated)


def _sync_prefixed_line(lines: list[str], prefix: str, value: str) -> list[str]:
    replacement = f"{prefix}{value}"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = replacement
            return lines
    lines.append(replacement)
    return lines


def sync_core_section_from_state(path: Path, state: dict[str, Any]) -> None:
    with _summary_write_lock(path):
        text = _read_text_with_retry(path)
        start = text.find(CORE_BEGIN)
        end = text.find(CORE_END)
        if start == -1 or end == -1 or start > end:
            raise ValueError("invalid core summary markers")

        body = text[start + len(CORE_BEGIN):end].strip("\n")
        lines = body.splitlines()

        phase = state.get("phase") or ""
        active_step = state.get("active_step") or ""
        pending = state.get("pending_user_decision") or ""
        next_reason = None
        next_step = state.get("next_recommended_step")
        if isinstance(next_step, dict):
            next_reason = next_step.get("reason")
        artifacts = state.get("artifacts", {})
        prd = artifacts.get("prd", {}) if isinstance(artifacts, dict) else {}
        prd_status = str(prd.get("status") or "absent")
        prd_exists = "yes" if prd_status != "absent" else "no"
        canonical_path = prd.get("canonical_path") or ""
        readiness = state.get("readiness", {})
        readiness_phase = readiness.get("phase") if isinstance(readiness, dict) else None
        readiness_score = readiness.get("score") if isinstance(readiness, dict) else None
        readiness_summary = readiness.get("summary") if isinstance(readiness, dict) else None
        readiness_gates = readiness.get("gates") if isinstance(readiness, dict) else {}
        if isinstance(readiness_gates, dict):
            failing_gates = sorted(key for key, value in readiness_gates.items() if not value)
            blocking_gates = ", ".join(failing_gates) if failing_gates else "none"
        else:
            blocking_gates = "unknown"

        _sync_prefixed_line(lines, "- Phase: ", f"`{phase}`" if phase else "")
        _sync_prefixed_line(lines, "- Active step: ", f"`{active_step}`" if active_step else "")
        _sync_prefixed_line(lines, "- Pending user decision: ", f"`{pending}`" if pending else "")
        _sync_prefixed_line(lines, "- Next recommended step: ", str(next_reason or ""))
        _sync_prefixed_line(lines, "- Exists: ", f"`{prd_exists}`")
        _sync_prefixed_line(lines, "- Canonical path: ", str(canonical_path))
        _sync_prefixed_line(lines, "- Readiness phase: ", str(readiness_phase or ""))
        _sync_prefixed_line(lines, "- Readiness score: ", str(readiness_score if readiness_score is not None else ""))
        _sync_prefixed_line(lines, "- Blocking gates: ", blocking_gates)
        _sync_prefixed_line(lines, "- Readiness summary: ", str(readiness_summary or ""))

        updated = text[: start + len(CORE_BEGIN)] + "\n" + "\n".join(lines).rstrip() + "\n" + text[end:]
        _atomic_write_text(path, updated)
