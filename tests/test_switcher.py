import json
import uuid
from pathlib import Path
import shutil

from pmagent.cli import _do_clear, _do_switch


def _workspace_dir(name: str) -> Path:
    root = Path(".tmp-pmagent-data") / "test-artifacts" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def test_do_switch_and_clear():
    tmp_path = _workspace_dir("switcher")
    try:
        (tmp_path / "config").mkdir()
        (tmp_path / "projects" / "alpha").mkdir(parents=True)
        (tmp_path / "projects" / "beta").mkdir(parents=True)
        (tmp_path / "workspaces" / "wa").mkdir(parents=True)
        (tmp_path / "workspaces" / "wb").mkdir(parents=True)
        (tmp_path / "config" / "projects.json").write_text(
            json.dumps({"active_project": "", "active_workspace": "", "projects": {}}, ensure_ascii=False),
            encoding="utf-8",
        )

        _do_switch(tmp_path, "alpha", "wa")

        settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8"))
        assert settings["files.exclude"]["projects/beta"] is True
        assert settings["files.exclude"]["workspaces/wb"] is True

        config = json.loads((tmp_path / "config" / "projects.json").read_text(encoding="utf-8"))
        assert config["active_project"] == "alpha"
        assert config["active_workspace"] == "wa"

        _do_clear(tmp_path)

        cleared = json.loads((tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8"))
        assert "projects/beta" not in cleared["files.exclude"]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
