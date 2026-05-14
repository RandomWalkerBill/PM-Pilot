from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_DEBATE_EXECUTOR_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "defaults": {
        "defender": {"exec": "claude", "model": None},
        "attacker": {"exec": "claude", "model": None},
        "synthesizer": {"exec": "claude", "model": None},
    },
}


def debate_executor_config_path(data_dir: Path) -> Path:
    return data_dir / "config" / "debate-executors.yaml"


def executors_config_path(data_dir: Path) -> Path:
    return data_dir / "config" / "executors.yaml"


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value) if key in merged else value
        return merged
    return patch


def _normalize_debate_defaults(value: Any) -> dict[str, Any]:
    defaults = value if isinstance(value, dict) else {}
    normalized: dict[str, Any] = {}
    for role in ("defender", "attacker", "synthesizer"):
        slot = defaults.get(role)
        if isinstance(slot, str):
            normalized[role] = {"exec": slot, "model": None}
        elif isinstance(slot, dict):
            normalized[role] = {
                "exec": slot.get("exec"),
                "model": slot.get("model"),
            }
        else:
            normalized[role] = {}
    return normalized


def _load_executors_yaml_debate_config(data_dir: Path) -> dict[str, Any] | None:
    path = executors_config_path(data_dir)
    if not path.exists():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        loaded = {}
    if not isinstance(loaded, dict):
        return None
    defaults = loaded.get("defaults", {}) if isinstance(loaded.get("defaults"), dict) else {}
    debate_defaults = _normalize_debate_defaults(defaults.get("debate"))
    return {
        "schema_version": loaded.get("schema_version", 2),
        "defaults": debate_defaults,
    }


def load_debate_executor_config(data_dir: Path) -> dict[str, Any]:
    path = debate_executor_config_path(data_dir)
    if not path.exists():
        shared_config = _load_executors_yaml_debate_config(data_dir)
        if shared_config is not None:
            return _deep_merge(DEFAULT_DEBATE_EXECUTOR_CONFIG, shared_config)
        return dict(DEFAULT_DEBATE_EXECUTOR_CONFIG)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}
    return _deep_merge(DEFAULT_DEBATE_EXECUTOR_CONFIG, loaded)


def resolve_executor_plan(
    data_dir: Path,
    *,
    pro_exec: str | None = None,
    con_exec: str | None = None,
    synth_exec: str | None = None,
    pro_model: str | None = None,
    con_model: str | None = None,
    synth_model: str | None = None,
) -> dict[str, dict[str, Any]]:
    config = load_debate_executor_config(data_dir)
    defaults = config.get("defaults", {}) if isinstance(config.get("defaults"), dict) else {}

    def _slot(name: str, *, cli_exec: str | None, model: str | None) -> dict[str, Any]:
        base = defaults.get(name, {}) if isinstance(defaults.get(name), dict) else {}
        return {
            "exec": cli_exec or base.get("exec"),
            "model": model if model is not None else base.get("model"),
        }

    return {
        "defender": _slot("defender", cli_exec=pro_exec, model=pro_model),
        "attacker": _slot("attacker", cli_exec=con_exec, model=con_model),
        "synthesizer": _slot("synthesizer", cli_exec=synth_exec, model=synth_model),
    }
