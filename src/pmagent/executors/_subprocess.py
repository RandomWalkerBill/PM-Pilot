from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from . import ExecutorError


_ORIGINAL_SUBPROCESS_RUN = subprocess.run


def _timeout_label(timeout_seconds: float | None) -> int:
    return int(timeout_seconds or 0)


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if sys.platform.startswith("win"):
        try:
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            return
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        process.kill()
    except OSError:
        pass


def _run_with_subprocess_run(
    argv: list[str],
    *,
    cwd: Path,
    stdin_text: str | None,
    timeout_seconds: float | None,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:  # noqa: PERF203
        raise ExecutorError(f"executor not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExecutorError(f"executor `{argv[0]}` timed out after {_timeout_label(timeout_seconds)}s") from exc


def run_subprocess(
    argv: list[str],
    *,
    cwd: Path,
    output_file: Path | None = None,
    stdin_text: str | None = None,
    timeout_seconds: float | None = None,
    extra_env: dict[str, str] | None = None,
) -> str:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    # Several tests monkeypatch subprocess.run through the compatibility facade.
    # Preserve that hook while using a process-tree-aware implementation in real
    # execution so CLI wrappers cannot leave descendants holding stdout/stderr
    # pipes open past the timeout.
    if subprocess.run is not _ORIGINAL_SUBPROCESS_RUN:
        completed = _run_with_subprocess_run(
            argv,
            cwd=cwd,
            stdin_text=stdin_text,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = completed.returncode
    else:
        creationflags = 0
        start_new_session = False
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            start_new_session = True
        try:
            process = subprocess.Popen(  # noqa: S603
                argv,
                cwd=str(cwd),
                stdin=subprocess.PIPE if stdin_text is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except FileNotFoundError as exc:  # noqa: PERF203
            raise ExecutorError(f"executor not found: {argv[0]}") from exc

        try:
            stdout, stderr = process.communicate(input=stdin_text, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _kill_process_tree(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise ExecutorError(f"executor `{argv[0]}` timed out after {_timeout_label(timeout_seconds)}s") from exc
        returncode = int(process.returncode or 0)

    if returncode != 0:
        detail = stderr.strip() or stdout.strip()
        raise ExecutorError(f"executor `{argv[0]}` failed with code {returncode}: {detail}")
    if output_file is not None:
        try:
            return output_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ExecutorError(f"failed to read executor output file: {output_file}") from exc
    return stdout.strip()
