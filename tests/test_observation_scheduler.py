import json
import plistlib
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from pmagent.observation import cli as observation_cli
from pmagent.observation import scheduler as observation_scheduler
from pmagent.observation.profile import load_profile, record_review_outcome


@contextmanager
def _workspace_dir(name: str) -> Iterator[Path]:
    root = Path(".tmp-pmagent-data") / "test-artifacts" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root.resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run_observation(repo_root: Path, *argv: str) -> int:
    return observation_cli.main(["--repo-root", str(repo_root), *argv])


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_projects_config(repo_root: Path, *, project: str = "alpha", workspace: str = "alpha-observe") -> None:
    config_root = repo_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_project": project,
        "active_workspace": workspace,
        "projects": {
            project: {
                "description": project,
                "workspaces": [workspace],
            }
        },
    }
    (config_root / "projects.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_enable_creates_project_observation_state(monkeypatch):
    with _workspace_dir("observe-enable") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --project {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert _run_observation(repo_root, "enable", "--project", "alpha", "--cadence", "daily", "--confirm-cadence") == 0

        policy = _read_json(repo_root / "observations" / "alpha" / "policy.json")
        state = _read_json(repo_root / "observations" / "alpha" / "state.json")
        assert policy["enabled"] is True
        assert policy["cadence"] == "daily"
        assert policy["decision_status"] == "enabled"
        assert state["project"] == "alpha"
        assert "enabled" not in state
        assert "cadence" not in state


def test_legacy_state_cannot_override_enabled_policy(monkeypatch):
    with _workspace_dir("observe-policy-state-layer") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --project {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert _run_observation(repo_root, "enable", "--project", "alpha", "--cadence", "daily", "--confirm-cadence") == 0
        state_path = repo_root / "observations" / "alpha" / "state.json"
        legacy_state = _read_json(state_path)
        legacy_state["enabled"] = False
        legacy_state["cadence"] = "manual"
        state_path.write_text(json.dumps(legacy_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        profile = load_profile(repo_root, "alpha", create=True)
        assert profile["enabled"] is True
        assert profile["cadence"] == "daily"

        record_review_outcome(repo_root, "alpha", "accepted")
        policy = _read_json(repo_root / "observations" / "alpha" / "policy.json")
        state = _read_json(state_path)
        assert policy["enabled"] is True
        assert policy["cadence"] == "daily"
        assert policy["decision_status"] == "enabled"
        assert "enabled" not in state
        assert "cadence" not in state


def test_enable_requires_confirm_cadence():
    with _workspace_dir("observe-enable-confirm") as repo_root:
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        with pytest.raises(SystemExit, match="confirm"):
            _run_observation(repo_root, "enable", "--project", "alpha", "--cadence", "daily")


def test_status_reports_project_observation_snapshot_as_json(monkeypatch, capsys):
    with _workspace_dir("observe-status") as repo_root:
        _seed_projects_config(repo_root, project="alpha", workspace="alpha-observe")
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_root / "workspaces" / "alpha-observe").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --project {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )

        assert _run_observation(repo_root, "enable", "--project", "alpha", "--cadence", "daily", "--confirm-cadence") == 0
        capsys.readouterr()

        assert _run_observation(repo_root, "status", "--project", "alpha", "--workspace", "alpha-observe", "--json") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["project"] == "alpha"
        assert payload["workspace"] == "alpha-observe"
        assert payload["enabled"] is True
        assert payload["cadence"] == "daily"
        assert "workspace_tracking" in payload


def test_set_cadence_updates_project_policy(monkeypatch):
    with _workspace_dir("observe-set-cadence") as repo_root:
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)

        calls: list[str] = []

        def fake_configure(repo_root, workspace, cadence, task_name=None, platform=None):
            calls.append(cadence)
            return {
                "platform": "windows-task-scheduler",
                "task_name": task_name or f"pmagent-observe-{workspace}",
                "command": f"python -m pmagent.cli observe run --project {workspace}",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            }

        monkeypatch.setattr("pmagent.observation.executor.configure_schedule", fake_configure)

        assert _run_observation(repo_root, "enable", "--project", "alpha", "--cadence", "daily", "--confirm-cadence") == 0
        assert _run_observation(repo_root, "set-cadence", "--project", "alpha", "--cadence", "every-6-hours", "--confirm-cadence") == 0

        policy = _read_json(repo_root / "observations" / "alpha" / "policy.json")
        assert policy["cadence"] == "every-6-hours"
        assert calls == ["daily", "every-6-hours"]


def test_disable_removes_project_schedule(monkeypatch):
    with _workspace_dir("observe-disable") as repo_root:
        (repo_root / "projects" / "alpha").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            "pmagent.observation.executor.configure_schedule",
            lambda repo_root, workspace, cadence, task_name=None, platform=None: {
                "platform": "windows-task-scheduler",
                "task_name": "pmagent-observe-alpha",
                "command": "python -m pmagent.cli observe run --project alpha",
                "plist_path": None,
                "unit_path": None,
                "timer_path": None,
                "last_configured_at": "2026-04-13T00:00:00Z",
            },
        )
        deleted: list[str] = []
        monkeypatch.setattr(
            "pmagent.observation.executor.delete_schedule",
            lambda task_name, platform=None, plist_path=None, unit_path=None, timer_path=None: deleted.append(task_name),
        )

        assert _run_observation(repo_root, "enable", "--project", "alpha", "--cadence", "daily", "--confirm-cadence") == 0
        assert _run_observation(repo_root, "disable", "--project", "alpha") == 0

        policy = _read_json(repo_root / "observations" / "alpha" / "policy.json")
        assert deleted == ["pmagent-observe-alpha"]
        assert policy["enabled"] is False
        assert policy["cadence"] == "manual"
        assert policy["decision_status"] == "manual"


def test_configure_launchd_task_writes_plist(monkeypatch):
    with _workspace_dir("launchd-task") as repo_root:
        calls: list[list[str]] = []

        def fake_runner(argv, capture_output=True, text=True):
            calls.append(argv)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        plist_dir = repo_root / "LaunchAgents"
        monkeypatch.setattr(observation_scheduler, "launchd_plist_path", lambda task_name: plist_dir / f"{task_name}.plist")

        metadata = observation_scheduler.configure_schedule(
            repo_root,
            "demo",
            cadence="daily",
            platform="launchd",
            runner=fake_runner,
        )

        plist_path = Path(metadata["plist_path"])
        assert plist_path.exists()
        payload = plistlib.loads(plist_path.read_bytes())
        assert payload["Label"] == "com.pmagent.observe.demo"
        assert payload["ProgramArguments"][-2:] == ["--project", "demo"]
        assert payload["StartCalendarInterval"] == {"Hour": 9, "Minute": 0}
        assert any(call[:2] == ["launchctl", "bootstrap"] for call in calls)


def test_delete_launchd_task_removes_plist(monkeypatch):
    with _workspace_dir("launchd-delete") as repo_root:
        plist_dir = repo_root / "LaunchAgents"
        plist_path = plist_dir / "com.pmagent.observe.demo.plist"
        plist_dir.mkdir(parents=True, exist_ok=True)
        plist_path.write_bytes(b"plist")
        calls: list[list[str]] = []

        def fake_runner(argv, capture_output=True, text=True):
            calls.append(argv)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        observation_scheduler.delete_schedule(
            "com.pmagent.observe.demo",
            platform="launchd",
            plist_path=str(plist_path),
            runner=fake_runner,
        )

        assert not plist_path.exists()
        assert any(call[:2] == ["launchctl", "bootout"] for call in calls)


def test_configure_systemd_user_task_writes_unit_and_timer(monkeypatch):
    with _workspace_dir("systemd-task") as repo_root:
        calls: list[list[str]] = []

        def fake_runner(argv, capture_output=True, text=True):
            calls.append(argv)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        systemd_dir = repo_root / "systemd-user"
        monkeypatch.setattr(observation_scheduler, "systemd_user_dir", lambda: systemd_dir)

        metadata = observation_scheduler.configure_schedule(
            repo_root,
            "demo",
            cadence="daily",
            platform="systemd-user",
            runner=fake_runner,
        )

        service_path = Path(metadata["unit_path"])
        timer_path = Path(metadata["timer_path"])
        assert service_path.exists()
        assert timer_path.exists()
        assert "ExecStart=" in service_path.read_text(encoding="utf-8")
        timer_text = timer_path.read_text(encoding="utf-8")
        assert "OnCalendar=*-*-* 09:00:00" in timer_text
        assert any(call[:3] == ["systemctl", "--user", "daemon-reload"] for call in calls)
        assert any(call[:4] == ["systemctl", "--user", "enable", "--now"] for call in calls)


def test_delete_systemd_user_task_removes_unit_and_timer(monkeypatch):
    with _workspace_dir("systemd-delete") as repo_root:
        systemd_dir = repo_root / "systemd-user"
        service_path = systemd_dir / "pmagent-observe-demo.service"
        timer_path = systemd_dir / "pmagent-observe-demo.timer"
        systemd_dir.mkdir(parents=True, exist_ok=True)
        service_path.write_text("service", encoding="utf-8")
        timer_path.write_text("timer", encoding="utf-8")
        calls: list[list[str]] = []

        def fake_runner(argv, capture_output=True, text=True):
            calls.append(argv)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        observation_scheduler.delete_schedule(
            "pmagent-observe-demo",
            platform="systemd-user",
            unit_path=str(service_path),
            timer_path=str(timer_path),
            runner=fake_runner,
        )

        assert not service_path.exists()
        assert not timer_path.exists()
        assert any(call[:4] == ["systemctl", "--user", "disable", "--now"] for call in calls)
