import uuid
from pathlib import Path
import shutil

import pytest

import pmagent.paths as paths
from pmagent.paths import expand_path


def _workspace_dir(name: str) -> Path:
    root = Path(".tmp-pmagent-data") / "test-artifacts" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def test_expand_path_resolves_path() -> None:
    target = _workspace_dir("expand-path")
    try:
        assert expand_path(target) == target.resolve()
    finally:
        shutil.rmtree(target, ignore_errors=True)


def test_write_global_config_and_resolve_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = _workspace_dir("config")
    try:
        config_home = tmp_path / ".pmagent"
        config_path = config_home / "config.yaml"
        data_dir = tmp_path / "pm-data"

        monkeypatch.setattr(paths, "CONFIG_HOME", config_home)
        monkeypatch.setattr(paths, "CONFIG_PATH", config_path)
        monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)

        written = paths.write_global_config(data_dir=data_dir)

        assert written == config_path
        assert config_path.exists()
        assert paths.resolve_data_dir() == data_dir.resolve()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
