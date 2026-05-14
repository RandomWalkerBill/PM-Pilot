from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import (
    project_observation_policy_path,
    project_observation_root,
    project_observation_state_path,
)


CADENCE_ORDER = (
    "weekly",
    "weekday-morning",
    "daily",
    "every-12-hours",
    "every-6-hours",
)
SUPPORTED_CADENCES = ("manual", *CADENCE_ORDER)

POLICY_KEYS = {
    "schema_version",
    "project",
    "enabled",
    "cadence",
    "decision_status",
    "last_confirmed_at",
    "confirmation_source",
    "catch_up_policy",
    "focus",
    "keywords",
    "preferred_domains",
    "excluded_domains",
    "updated_at",
}

_CADENCE_INTERVALS = {
    "manual": None,
    "weekly": timedelta(days=7),
    "weekday-morning": timedelta(days=1),
    "daily": timedelta(days=1),
    "every-12-hours": timedelta(hours=12),
    "every-6-hours": timedelta(hours=6),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_scheduler_platform() -> str:
    if os.name == "nt":
        return "windows-task-scheduler"
    if sys.platform == "darwin":
        return "launchd"
    return "unsupported"


def default_policy(project: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": project,
        "enabled": False,
        "cadence": "manual",
        "decision_status": "unresolved",
        "last_confirmed_at": None,
        "confirmation_source": None,
        "catch_up_policy": "audit",
        "focus": ["market", "technology", "community"],
        "keywords": [],
        "preferred_domains": [],
        "excluded_domains": [],
        "updated_at": utc_now(),
    }


def default_state(project: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": project,
        "created_at": utc_now(),
        "scheduler": {
            "platform": _default_scheduler_platform(),
            "task_name": None,
            "command": None,
            "last_configured_at": None,
            "plist_path": None,
            "unit_path": None,
            "timer_path": None,
        },
        "review_stats": {
            "accepted": 0,
            "rejected": 0,
            "snoozed": 0,
            "total_reviewed": 0,
            "last_reviewed_at": None,
        },
        "cadence_recommendation": {
            "status": "stable",
            "suggested_cadence": None,
            "reason": None,
            "updated_at": None,
        },
        "cadence_history": [],
        "last_run_id": None,
        "last_run_at": None,
        "next_scheduled_run_at": None,
        "observation_count": 0,
        "updated_at": utc_now(),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix=".tmp.", suffix=".json")
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _merge_defaults(value: Any, default: Any) -> Any:
    if isinstance(default, dict):
        source = value if isinstance(value, dict) else {}
        merged: dict[str, Any] = {}
        for key, default_value in default.items():
            merged[key] = _merge_defaults(source.get(key), default_value)
        for key, existing in source.items():
            if key not in merged:
                merged[key] = existing
        return merged
    if isinstance(default, list):
        return value if isinstance(value, list) else copy.deepcopy(default)
    return default if value is None else value


def _split_profile(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = {key: profile.get(key) for key in POLICY_KEYS}
    state = {key: value for key, value in profile.items() if key not in POLICY_KEYS}
    if "schema_version" not in state:
        state["schema_version"] = 1
    if "project" not in state:
        state["project"] = profile.get("project")
    if "updated_at" not in state:
        state["updated_at"] = utc_now()
    return policy, state


def save_profile(repo_root: Path, project: str, profile: dict[str, Any]) -> dict[str, Any]:
    root = project_observation_root(repo_root, project)
    root.mkdir(parents=True, exist_ok=True)
    policy, state = _split_profile(profile)
    policy["updated_at"] = utc_now()
    state["updated_at"] = utc_now()
    _write_json(project_observation_policy_path(repo_root, project), policy)
    _write_json(project_observation_state_path(repo_root, project), state)
    return load_profile(repo_root, project, create=True)


def mark_policy_decision(
    profile: dict[str, Any],
    *,
    decision_status: str,
    confirmation_source: str | None,
) -> dict[str, Any]:
    if decision_status not in {"unresolved", "manual", "enabled"}:
        raise SystemExit(f"unsupported observation decision status: {decision_status}")
    profile["decision_status"] = decision_status
    profile["confirmation_source"] = confirmation_source
    profile["last_confirmed_at"] = utc_now() if decision_status != "unresolved" else None
    return profile


def load_profile(repo_root: Path, project: str, *, create: bool = False) -> dict[str, Any]:
    policy_path = project_observation_policy_path(repo_root, project)
    state_path = project_observation_state_path(repo_root, project)
    default_policy_payload = default_policy(project)
    default_state_payload = default_state(project)

    if not policy_path.exists() or not state_path.exists():
        if not create:
            missing = policy_path if not policy_path.exists() else state_path
            raise SystemExit(f"observation profile does not exist: {missing}")
        profile = _merge_defaults({}, default_policy_payload)
        profile.update(_merge_defaults({}, default_state_payload))
        return save_profile(repo_root, project, profile)

    raw_policy = _read_json(policy_path)
    raw_state = _read_json(state_path)
    # Legacy/buggy state.json files may contain policy-owned keys such as
    # enabled/cadence. Never let runtime state override user-confirmed policy.
    state_without_policy = {key: value for key, value in raw_state.items() if key not in POLICY_KEYS}
    policy = _merge_defaults(raw_policy, default_policy_payload)
    state = _merge_defaults(state_without_policy, default_state_payload)
    profile = dict(policy)
    profile.update(state)
    if policy != raw_policy or state != raw_state:
        save_profile(repo_root, project, profile)
    return profile


def cadence_step_up(cadence: str) -> str:
    if cadence not in CADENCE_ORDER:
        return cadence
    index = CADENCE_ORDER.index(cadence)
    return CADENCE_ORDER[min(index + 1, len(CADENCE_ORDER) - 1)]


def cadence_step_down(cadence: str) -> str:
    if cadence not in CADENCE_ORDER:
        return cadence
    index = CADENCE_ORDER.index(cadence)
    return CADENCE_ORDER[max(index - 1, 0)]


def update_cadence_recommendation(profile: dict[str, Any]) -> dict[str, Any]:
    cadence = str(profile.get("cadence", "manual"))
    stats = profile.setdefault("review_stats", {})
    recommendation = profile.setdefault("cadence_recommendation", {})

    accepted = int(stats.get("accepted", 0))
    rejected = int(stats.get("rejected", 0))
    snoozed = int(stats.get("snoozed", 0))
    total = int(stats.get("total_reviewed", accepted + rejected + snoozed))
    passive = rejected + snoozed

    status = "stable"
    suggested_cadence = None
    reason = None

    if cadence in CADENCE_ORDER and total >= 3:
        acceptance_ratio = accepted / total if total else 0.0
        passive_ratio = passive / total if total else 0.0

        if acceptance_ratio >= 0.6:
            candidate = cadence_step_up(cadence)
            if candidate != cadence:
                status = "increase"
                suggested_cadence = candidate
                reason = "recent reviews accepted many candidate items; consider increasing observation cadence"
        elif passive_ratio >= 0.8:
            candidate = cadence_step_down(cadence)
            if candidate != cadence:
                status = "decrease"
                suggested_cadence = candidate
                reason = "recent reviews rejected or snoozed most candidate items; consider reducing observation cadence"

    recommendation.update(
        {
            "status": status,
            "suggested_cadence": suggested_cadence,
            "reason": reason,
            "updated_at": utc_now(),
        }
    )
    return recommendation


def record_review_outcome(repo_root: Path, project: str, outcome: str) -> dict[str, Any]:
    if outcome not in {"accepted", "rejected", "snoozed"}:
        raise SystemExit(f"unsupported review outcome: {outcome}")

    profile = load_profile(repo_root, project, create=True)
    stats = profile.setdefault("review_stats", {})
    stats[outcome] = int(stats.get(outcome, 0)) + 1
    stats["total_reviewed"] = int(stats.get("total_reviewed", 0)) + 1
    stats["last_reviewed_at"] = utc_now()
    update_cadence_recommendation(profile)
    save_profile(repo_root, project, profile)
    return profile


def set_schedule_state(
    repo_root: Path,
    project: str,
    *,
    enabled: bool,
    cadence: str,
    scheduler: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    if cadence not in SUPPORTED_CADENCES:
        raise SystemExit(f"unsupported observation cadence: {cadence}")

    profile = load_profile(repo_root, project, create=True)
    current_cadence = str(profile.get("cadence", "manual"))
    profile["enabled"] = enabled
    profile["cadence"] = cadence

    scheduler_state = profile.setdefault("scheduler", {})
    if scheduler:
        scheduler_state.update(scheduler)
    scheduler_state["last_configured_at"] = utc_now()
    if not enabled:
        scheduler_state["command"] = None

    if current_cadence != cadence or reason:
        profile.setdefault("cadence_history", []).append(
            {
                "at": utc_now(),
                "cadence": cadence,
                "enabled": enabled,
                "reason": reason,
            }
        )

    update_cadence_recommendation(profile)
    save_profile(repo_root, project, profile)
    return profile


def reset_cadence_recommendation(repo_root: Path, project: str, reason: str) -> dict[str, Any]:
    profile = load_profile(repo_root, project, create=True)
    profile["cadence_recommendation"] = {
        "status": "stable",
        "suggested_cadence": None,
        "reason": reason,
        "updated_at": utc_now(),
    }
    save_profile(repo_root, project, profile)
    return profile


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cadence_interval(cadence: str) -> timedelta | None:
    return _CADENCE_INTERVALS.get(cadence)


def catch_up_due(profile: dict[str, Any], last_run: dict[str, Any] | None) -> bool:
    if not profile.get("enabled"):
        return False

    interval = cadence_interval(str(profile.get("cadence", "manual")))
    if interval is None:
        return False

    updated_at = None
    if isinstance(last_run, dict):
        updated_at = last_run.get("updated_at")
    last_seen = parse_utc(updated_at)
    if last_seen is None:
        scheduler = profile.get("scheduler") or {}
        last_seen = parse_utc(scheduler.get("last_configured_at"))
    if last_seen is None:
        return True

    return datetime.now(timezone.utc) - last_seen >= interval
