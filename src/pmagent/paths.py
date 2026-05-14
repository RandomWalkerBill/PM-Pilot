from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


ENV_DATA_DIR = "PMAGENT_DATA_DIR"
CONFIG_HOME = Path.home() / ".pmagent"
CONFIG_PATH = CONFIG_HOME / "config.yaml"
DEFAULT_DATA_DIR = Path.home() / "pmagent-data"


def package_root() -> Path:
    return Path(__file__).resolve().parent


def expand_path(value: str | os.PathLike[str] | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser().resolve()


def load_global_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or CONFIG_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def resolve_config_path() -> Path:
    return CONFIG_PATH


def resolve_data_dir(cli_arg: str | os.PathLike[str] | None = None) -> Path:
    explicit = expand_path(cli_arg)
    if explicit is not None:
        return explicit

    env_value = expand_path(os.environ.get(ENV_DATA_DIR))
    if env_value is not None:
        return env_value

    config = load_global_config()
    config_value = expand_path(config.get("data_dir"))
    if config_value is not None:
        return config_value

    raise RuntimeError(
        "PM Agent data directory is not configured. Run `pmagent init` or set PMAGENT_DATA_DIR."
    )


def write_global_config(*, data_dir: Path, extra: dict[str, Any] | None = None) -> Path:
    CONFIG_HOME.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"data_dir": str(data_dir.expanduser())}
    if extra:
        payload.update(extra)
    CONFIG_PATH.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return CONFIG_PATH
