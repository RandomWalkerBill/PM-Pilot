from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from shutil import which

from . import ExecutorError, ExecutorResult
from ._subprocess import run_subprocess


CODEX_BACKGROUND_FULL_ACCESS_FLAGS = [
    "--dangerously-bypass-approvals-and-sandbox",
]

CODEX_BACKGROUND_AUTOMATED_FLAGS = [
    "--full-auto",
    "--sandbox",
    "read-only",
]

# `exec resume` does not support --sandbox; use only the approval-mode flags.
CODEX_RESUME_FULL_ACCESS_FLAGS = [
    "--dangerously-bypass-approvals-and-sandbox",
]

CODEX_RESUME_AUTOMATED_FLAGS = [
    "--full-auto",
]


def codex_sessions_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def newest_codex_session(*, after_timestamp: float | None = None, cwd: Path | None = None) -> str | None:
    root = codex_sessions_root()
    if not root.exists():
        return None
    candidates = sorted((p for p in root.rglob("*.jsonl") if p.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if after_timestamp is not None and mtime < after_timestamp:
            continue
        try:
            first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            payload = json.loads(first)
        except (OSError, IndexError, json.JSONDecodeError):
            continue
        if payload.get("type") == "session_meta":
            meta_payload = (payload.get("payload") or {}) if isinstance(payload.get("payload"), dict) else {}
            if cwd is not None:
                transcript_cwd = str(meta_payload.get("cwd") or "")
                if transcript_cwd.replace("\\", "/").lower() != str(cwd).replace("\\", "/").lower():
                    continue
            session_id = meta_payload.get("id")
            if isinstance(session_id, str) and session_id.strip():
                return session_id
    return None


def codex_session_file(session_id: str) -> Path | None:
    root = codex_sessions_root()
    if not root.exists():
        return None
    direct_matches = sorted(root.rglob(f"*{session_id}*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    if direct_matches:
        return direct_matches[0]
    for path in sorted(root.rglob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            payload = json.loads(first)
        except (OSError, IndexError, json.JSONDecodeError):
            continue
        if payload.get("type") != "session_meta":
            continue
        meta_payload = payload.get("payload") or {}
        if isinstance(meta_payload, dict) and meta_payload.get("id") == session_id:
            return path
    return None


def extract_codex_last_message(session_file: Path) -> str:
    try:
        lines = session_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ExecutorError(f"failed to read codex session transcript: {session_file}") from exc
    for raw in reversed(lines):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "response_item":
            payload = item.get("payload") or {}
            if payload.get("type") == "message" and payload.get("role") == "assistant":
                content = payload.get("content")
                if isinstance(content, list):
                    texts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "output_text":
                            text = str(block.get("text") or "").strip()
                            if text:
                                texts.append(text)
                    if texts:
                        return "\n\n".join(texts).strip()
        if item.get("type") == "event_msg":
            payload = item.get("payload") or {}
            if payload.get("type") == "agent_message":
                text = str(payload.get("message") or "").strip()
                if text:
                    return text
    raise ExecutorError(f"unable to extract assistant message from codex transcript: {session_file}")


def _new_temp_path(*, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        return Path(tmp.name)


def run_codex(
    prompt: str,
    *,
    cwd: Path,
    session_id: str | None = None,
    model: str | None = None,
    schema: dict | None = None,
    timeout_seconds: float | None = None,
    trust_all_tools: bool = False,
) -> ExecutorResult:
    executable = which("codex") or "codex"
    schema_path: Path | None = None
    output_path: Path | None = None
    try:
        output_path = _new_temp_path(suffix=".md")
        if session_id:
            argv = [executable, "exec", "resume", session_id]
            argv.extend(CODEX_RESUME_FULL_ACCESS_FLAGS if trust_all_tools else CODEX_RESUME_AUTOMATED_FLAGS)
            argv.append("--skip-git-repo-check")
            if model:
                argv.extend(["--model", model])
            argv.extend(["--output-last-message", str(output_path)])
            argv.append("-")
            content = run_subprocess(argv, cwd=cwd, output_file=output_path, stdin_text=prompt, timeout_seconds=timeout_seconds)
            return ExecutorResult(content=content, session_id=session_id)

        marker = time.time()
        argv = [executable, "exec"]
        argv.extend(CODEX_BACKGROUND_FULL_ACCESS_FLAGS if trust_all_tools else CODEX_BACKGROUND_AUTOMATED_FLAGS)
        argv.append("--skip-git-repo-check")
        if model:
            argv.extend(["--model", model])
        if schema:
            schema_path = _new_temp_path(suffix=".json")
            schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
            argv.extend(["--output-schema", str(schema_path)])
        argv.extend(["--output-last-message", str(output_path)])
        argv.append("-")
        content = run_subprocess(argv, cwd=cwd, output_file=output_path, stdin_text=prompt, timeout_seconds=timeout_seconds)
        discovered = newest_codex_session(after_timestamp=marker, cwd=cwd)
        return ExecutorResult(content=content, session_id=discovered or "")
    finally:
        if schema_path:
            schema_path.unlink(missing_ok=True)
        if output_path:
            output_path.unlink(missing_ok=True)
