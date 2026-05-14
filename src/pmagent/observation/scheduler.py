from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .profile import SUPPORTED_CADENCES, utc_now


_WINDOWS_CADENCE_ARGS = {
    "weekly": ["/SC", "WEEKLY", "/D", "MON", "/ST", "09:00"],
    "weekday-morning": ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", "09:00"],
    "daily": ["/SC", "DAILY", "/ST", "09:00"],
    "every-12-hours": ["/SC", "HOURLY", "/MO", "12", "/ST", "00:00"],
    "every-6-hours": ["/SC", "HOURLY", "/MO", "6", "/ST", "00:00"],
}

_LAUNCHD_CALENDAR = {
    "weekly": {"Weekday": 1, "Hour": 9, "Minute": 0},
    "weekday-morning": [
        {"Weekday": weekday, "Hour": 9, "Minute": 0}
        for weekday in range(1, 6)
    ],
    "daily": {"Hour": 9, "Minute": 0},
}

_LAUNCHD_INTERVAL_SECONDS = {
    "every-12-hours": 12 * 60 * 60,
    "every-6-hours": 6 * 60 * 60,
}

_SYSTEMD_ON_CALENDAR = {
    "weekly": "Mon 09:00",
    "weekday-morning": "Mon..Fri 09:00",
    "daily": "*-*-* 09:00:00",
}

_SYSTEMD_ON_BOOT_SEC = {
    "every-12-hours": "12h",
    "every-6-hours": "6h",
}


def current_scheduler_platform() -> str:
    if os.name == "nt":
        return "windows-task-scheduler"
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        return "systemd-user"
    return "unsupported"


def sanitize_workspace_name(workspace: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "-", workspace.strip()).strip("-")
    return sanitized or "workspace"


def default_task_name(workspace: str, *, platform: str | None = None) -> str:
    resolved_platform = platform or current_scheduler_platform()
    slug = sanitize_workspace_name(workspace)
    if resolved_platform == "launchd":
        return f"com.pmagent.observe.{slug}"
    return f"pmagent-observe-{slug}"


def build_task_command(repo_root: Path, workspace: str) -> str:
    python_executable = Path(sys.executable).resolve()
    return (
        f'"{python_executable}" -m pmagent.cli observe '
        f'--data-dir "{Path(repo_root).resolve()}" run --project "{workspace}"'
    )


def build_task_argv(repo_root: Path, workspace: str) -> list[str]:
    python_executable = Path(sys.executable).resolve()
    return [
        str(python_executable),
        "-m",
        "pmagent.cli",
        "observe",
        "--data-dir",
        str(Path(repo_root).resolve()),
        "run",
        "--project",
        workspace,
    ]


def launchd_plist_path(task_name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{task_name}.plist"


def launchd_domain_target() -> str:
    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        return f"gui/{getuid()}"
    return "gui/0"


def systemd_user_dir() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "systemd" / "user"


def systemd_service_path(task_name: str) -> Path:
    return systemd_user_dir() / f"{task_name}.service"


def systemd_timer_path(task_name: str) -> Path:
    return systemd_user_dir() / f"{task_name}.timer"


def _ensure_supported_cadence(cadence: str, *, platform: str) -> None:
    if cadence == "manual":
        raise SystemExit("manual cadence cannot be scheduled")
    if cadence not in SUPPORTED_CADENCES:
        raise SystemExit(f"unsupported observation cadence: {cadence}")
    if platform == "windows-task-scheduler" and cadence not in _WINDOWS_CADENCE_ARGS:
        raise SystemExit(f"unsupported cadence for Windows Task Scheduler: {cadence}")
    if platform == "launchd" and cadence not in (*_LAUNCHD_CALENDAR.keys(), *_LAUNCHD_INTERVAL_SECONDS.keys()):
        raise SystemExit(f"unsupported cadence for launchd: {cadence}")
    if platform == "systemd-user" and cadence not in (*_SYSTEMD_ON_CALENDAR.keys(), *_SYSTEMD_ON_BOOT_SEC.keys()):
        raise SystemExit(f"unsupported cadence for systemd user timer: {cadence}")


def configure_windows_task(
    repo_root: Path,
    workspace: str,
    *,
    cadence: str,
    task_name: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, str]:
    _ensure_supported_cadence(cadence, platform="windows-task-scheduler")
    resolved_task_name = task_name or default_task_name(workspace, platform="windows-task-scheduler")
    command = build_task_command(repo_root, workspace)
    argv = [
        "schtasks",
        "/Create",
        "/F",
        "/TN",
        resolved_task_name,
        "/TR",
        command,
        *(_WINDOWS_CADENCE_ARGS[cadence]),
    ]
    result = runner(argv, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"failed to configure observation task '{resolved_task_name}': {detail}")

    return {
        "platform": "windows-task-scheduler",
        "task_name": resolved_task_name,
        "command": command,
        "plist_path": None,
        "last_configured_at": utc_now(),
    }


def delete_windows_task(
    task_name: str | None,
    *,
    runner: Any = subprocess.run,
) -> None:
    if not task_name:
        return

    argv = ["schtasks", "/Delete", "/F", "/TN", task_name]
    result = runner(argv, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        lowered = detail.lower()
        if "cannot find the file specified" in lowered or "cannot find the task" in lowered:
            return
        raise SystemExit(f"failed to delete observation task '{task_name}': {detail}")


def _launchd_payload(task_name: str, repo_root: Path, workspace: str, command: str, cadence: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "Label": task_name,
        "ProgramArguments": build_task_argv(repo_root, workspace),
        "RunAtLoad": True,
        "StandardOutPath": str(Path.home() / "Library" / "Logs" / f"{task_name}.out.log"),
        "StandardErrorPath": str(Path.home() / "Library" / "Logs" / f"{task_name}.err.log"),
    }
    if cadence in _LAUNCHD_CALENDAR:
        payload["StartCalendarInterval"] = _LAUNCHD_CALENDAR[cadence]
    else:
        payload["StartInterval"] = _LAUNCHD_INTERVAL_SECONDS[cadence]
    return payload


def configure_launchd_task(
    repo_root: Path,
    workspace: str,
    *,
    cadence: str,
    task_name: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, str]:
    _ensure_supported_cadence(cadence, platform="launchd")
    resolved_task_name = task_name or default_task_name(workspace, platform="launchd")
    command = build_task_command(repo_root, workspace)
    plist_path = launchd_plist_path(resolved_task_name)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _launchd_payload(resolved_task_name, repo_root, workspace, command, cadence)
    plist_path.write_bytes(plistlib.dumps(payload))

    runner(["launchctl", "bootout", launchd_domain_target(), str(plist_path)], capture_output=True, text=True)
    result = runner(
        ["launchctl", "bootstrap", launchd_domain_target(), str(plist_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"failed to configure launchd observation task '{resolved_task_name}': {detail}")

    return {
        "platform": "launchd",
        "task_name": resolved_task_name,
        "command": command,
        "plist_path": str(plist_path),
        "last_configured_at": utc_now(),
    }


def delete_launchd_task(
    task_name: str | None,
    *,
    plist_path: str | None = None,
    runner: Any = subprocess.run,
) -> None:
    if not task_name:
        return

    resolved_plist_path = Path(plist_path) if plist_path else launchd_plist_path(task_name)
    runner(["launchctl", "bootout", launchd_domain_target(), str(resolved_plist_path)], capture_output=True, text=True)
    if resolved_plist_path.exists():
        resolved_plist_path.unlink()


def _systemd_service_text(task_name: str, repo_root: Path, workspace: str) -> str:
    argv = build_task_argv(repo_root, workspace)
    exec_start = " ".join(f'"{part}"' if " " in part else part for part in argv)
    return "\n".join(
        [
            "[Unit]",
            f"Description=PM Agent observation run for {workspace}",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={exec_start}",
            "",
        ]
    )


def _systemd_timer_text(task_name: str, cadence: str) -> str:
    lines = [
        "[Unit]",
        f"Description=PM Agent observation schedule for {task_name}",
        "",
        "[Timer]",
        "Persistent=true",
    ]
    if cadence in _SYSTEMD_ON_CALENDAR:
        lines.append(f"OnCalendar={_SYSTEMD_ON_CALENDAR[cadence]}")
    else:
        lines.append(f"OnBootSec={_SYSTEMD_ON_BOOT_SEC[cadence]}")
        lines.append(f"OnUnitActiveSec={_SYSTEMD_ON_BOOT_SEC[cadence]}")
    lines.extend(
        [
            f"Unit={task_name}.service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
    return "\n".join(lines)


def configure_systemd_user_task(
    repo_root: Path,
    workspace: str,
    *,
    cadence: str,
    task_name: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, str]:
    _ensure_supported_cadence(cadence, platform="systemd-user")
    resolved_task_name = task_name or default_task_name(workspace, platform="systemd-user")
    command = build_task_command(repo_root, workspace)
    service_path = systemd_service_path(resolved_task_name)
    timer_path = systemd_timer_path(resolved_task_name)
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(_systemd_service_text(resolved_task_name, repo_root, workspace), encoding="utf-8")
    timer_path.write_text(_systemd_timer_text(resolved_task_name, cadence), encoding="utf-8")

    for argv in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", f"{resolved_task_name}.timer"],
    ):
        result = runner(argv, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise SystemExit(f"failed to configure systemd user timer '{resolved_task_name}': {detail}")

    return {
        "platform": "systemd-user",
        "task_name": resolved_task_name,
        "command": command,
        "plist_path": None,
        "unit_path": str(service_path),
        "timer_path": str(timer_path),
        "last_configured_at": utc_now(),
    }


def delete_systemd_user_task(
    task_name: str | None,
    *,
    unit_path: str | None = None,
    timer_path: str | None = None,
    runner: Any = subprocess.run,
) -> None:
    if not task_name:
        return

    runner(["systemctl", "--user", "disable", "--now", f"{task_name}.timer"], capture_output=True, text=True)
    runner(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    resolved_unit = Path(unit_path) if unit_path else systemd_service_path(task_name)
    resolved_timer = Path(timer_path) if timer_path else systemd_timer_path(task_name)
    if resolved_unit.exists():
        resolved_unit.unlink()
    if resolved_timer.exists():
        resolved_timer.unlink()
    runner(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)


def configure_schedule(
    repo_root: Path,
    workspace: str,
    *,
    cadence: str,
    task_name: str | None = None,
    platform: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, str]:
    resolved_platform = platform or current_scheduler_platform()
    if resolved_platform == "windows-task-scheduler":
        return configure_windows_task(
            repo_root,
            workspace,
            cadence=cadence,
            task_name=task_name,
            runner=runner,
        )
    if resolved_platform == "launchd":
        return configure_launchd_task(
            repo_root,
            workspace,
            cadence=cadence,
            task_name=task_name,
            runner=runner,
        )
    if resolved_platform == "systemd-user":
        return configure_systemd_user_task(
            repo_root,
            workspace,
            cadence=cadence,
            task_name=task_name,
            runner=runner,
        )
    raise SystemExit(
        "observation scheduling is currently supported on Windows Task Scheduler, macOS launchd, and lightweight Linux systemd user timers"
    )


def delete_schedule(
    task_name: str | None,
    *,
    platform: str | None = None,
    plist_path: str | None = None,
    unit_path: str | None = None,
    timer_path: str | None = None,
    runner: Any = subprocess.run,
) -> None:
    resolved_platform = platform or current_scheduler_platform()
    if resolved_platform == "windows-task-scheduler":
        delete_windows_task(task_name, runner=runner)
        return
    if resolved_platform == "launchd":
        delete_launchd_task(task_name, plist_path=plist_path, runner=runner)
        return
    if resolved_platform == "systemd-user":
        delete_systemd_user_task(task_name, unit_path=unit_path, timer_path=timer_path, runner=runner)
        return
    return
