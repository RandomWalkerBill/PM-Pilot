import json
from pathlib import Path

from pmagent.ops import lark_wiki_push


def _make_node_payload(node_token: str, obj_token: str, url: str) -> dict:
    return {
        "ok": True,
        "data": {
            "node_token": node_token,
            "obj_token": obj_token,
            "url": url,
        },
    }


def test_lark_wiki_push_reuses_existing_node_mapping(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    node_counter = {"n": 0}

    def fake_run_json(args: list[str], *, input_text: str | None = None):
        calls.append(args)
        if args[:2] == ["wiki", "+node-create"]:
            node_counter["n"] += 1
            n = node_counter["n"]
            return _make_node_payload(
                f"wikcn_node_{n}",
                f"docx_token_{n}",
                f"https://example.invalid/wiki/node_{n}",
            )
        if args[:2] == ["docs", "+update"]:
            return {"data": {"revision_id": 1}}
        raise AssertionError(f"unexpected call: {args}")

    monkeypatch.setattr(lark_wiki_push, "_run_json", fake_run_json)
    data_dir = tmp_path / "pm-data"
    workspace = "alpha-discovery"
    file_path = data_dir / "workspaces" / workspace / "Requirement.md"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("# Requirement\n\nInitial.\n", encoding="utf-8")

    first = lark_wiki_push.push_file_to_wiki(
        file_path=file_path,
        relative="Requirement.md",
        workspace=workspace,
        space_id="my_library",
        data_dir=data_dir,
    )
    second = lark_wiki_push.push_file_to_wiki(
        file_path=file_path,
        relative="Requirement.md",
        workspace=workspace,
        space_id="my_library",
        data_dir=data_dir,
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["obj_token"] == first["obj_token"]
    # node create: 1 for workspace root + 1 for the doc = 2 total, second push reuses both
    assert [call[:2] for call in calls].count(["wiki", "+node-create"]) == 2
    assert [call[:2] for call in calls].count(["docs", "+update"]) == 2

    log_path = data_dir / "workspaces" / workspace / ".pmagent" / "feishu-wiki-nodes.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [row["created"] for row in rows] == [True, False]


def test_lark_wiki_push_creates_folder_hierarchy(monkeypatch, tmp_path: Path):
    """Files in subdirectories should get a parent folder node created first."""
    calls: list[list[str]] = []
    node_counter = {"n": 0}

    def fake_run_json(args: list[str], *, input_text: str | None = None):
        calls.append(list(args))
        if args[:2] == ["wiki", "+node-create"]:
            node_counter["n"] += 1
            n = node_counter["n"]
            return _make_node_payload(f"wikcn_{n}", f"obj_{n}", f"https://example.invalid/wiki/{n}")
        if args[:2] == ["docs", "+update"]:
            return {"data": {"revision_id": 1}}
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr(lark_wiki_push, "_run_json", fake_run_json)
    data_dir = tmp_path / "pm-data"
    workspace = "my-workspace"
    file_path = data_dir / "workspaces" / workspace / "research" / "notes.md"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("# Notes\n\nContent.\n", encoding="utf-8")

    result = lark_wiki_push.push_file_to_wiki(
        file_path=file_path,
        relative="research/notes.md",
        workspace=workspace,
        space_id="my_library",
        data_dir=data_dir,
    )

    assert result["created"] is True

    node_create_calls = [c for c in calls if c[:2] == ["wiki", "+node-create"]]
    # 1: workspace root, 2: research folder, 3: the doc
    assert len(node_create_calls) == 3

    # Workspace root uses --space-id
    assert "--space-id" in node_create_calls[0]

    # Research folder uses --parent-node-token (under workspace root)
    assert "--parent-node-token" in node_create_calls[1]
    # Research folder title should mirror the local directory name.
    assert "research" in node_create_calls[1]

    # Doc node uses --parent-node-token (under research folder)
    assert "--parent-node-token" in node_create_calls[2]

    # Folder cache should be persisted
    cache_path = data_dir / "workspaces" / workspace / ".pmagent" / "feishu-wiki-folders.json"
    assert cache_path.exists()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert f"__root__/{workspace}" in cache
    assert f"{workspace}/research" in cache


def test_lark_wiki_push_uses_project_workspace_hierarchy(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    node_counter = {"n": 0}

    def fake_run_json(args: list[str], *, input_text: str | None = None):
        calls.append(list(args))
        if args[:2] == ["wiki", "+node-create"]:
            node_counter["n"] += 1
            n = node_counter["n"]
            return _make_node_payload(f"wikcn_{n}", f"obj_{n}", f"https://example.invalid/wiki/{n}")
        if args[:2] == ["docs", "+update"]:
            return {"data": {"revision_id": 1}}
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr(lark_wiki_push, "_run_json", fake_run_json)
    data_dir = tmp_path / "pm-data"
    project = "alpha"
    workspace = "alpha-discovery"
    file_path = data_dir / "workspaces" / workspace / "prd" / "v1.md"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("# PRD\n\nContent.\n", encoding="utf-8")

    result = lark_wiki_push.push_file_to_wiki(
        file_path=file_path,
        relative="prd/v1.md",
        project=project,
        workspace=workspace,
        space_id="my_library",
        data_dir=data_dir,
    )

    assert result["project"] == project
    node_create_calls = [c for c in calls if c[:2] == ["wiki", "+node-create"]]
    assert len(node_create_calls) == 5
    assert node_create_calls[0][-2:] == ["--space-id", "my_library"]
    assert project in node_create_calls[0]
    assert "workspaces" in node_create_calls[1]
    assert workspace in node_create_calls[2]
    assert "prd" in node_create_calls[3]

    cache_path = data_dir / "projects" / project / ".pmagent" / "feishu-wiki-folders.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert f"project/{project}" in cache
    assert f"project/{project}/workspaces" in cache
    assert f"project/{project}/workspaces/{workspace}" in cache
    assert f"project/{project}/workspaces/{workspace}/prd" in cache

    log_path = data_dir / "projects" / project / ".pmagent" / "feishu-wiki-nodes.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["project"] == project
    assert rows[-1]["workspace"] == workspace


def test_lark_wiki_push_uses_project_scope_as_project_sibling(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    node_counter = {"n": 0}

    def fake_run_json(args: list[str], *, input_text: str | None = None):
        calls.append(list(args))
        if args[:2] == ["wiki", "+node-create"]:
            node_counter["n"] += 1
            n = node_counter["n"]
            return _make_node_payload(f"wikcn_{n}", f"obj_{n}", f"https://example.invalid/wiki/{n}")
        if args[:2] == ["docs", "+update"]:
            return {"data": {"revision_id": 1}}
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr(lark_wiki_push, "_run_json", fake_run_json)
    data_dir = tmp_path / "pm-data"
    project = "alpha"
    workspace = "alpha-discovery"
    file_path = data_dir / "projects" / project / "research" / "market.md"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("# Market\n\nContent.\n", encoding="utf-8")

    result = lark_wiki_push.push_file_to_wiki(
        file_path=file_path,
        relative="research/market.md",
        project=project,
        workspace=workspace,
        scope="project",
        space_id="my_library",
        data_dir=data_dir,
    )

    assert result["scope"] == "project"
    node_create_calls = [c for c in calls if c[:2] == ["wiki", "+node-create"]]
    assert len(node_create_calls) == 3
    assert project in node_create_calls[0]
    assert "workspaces" not in node_create_calls[1]
    assert "research" in node_create_calls[1]

    cache_path = data_dir / "projects" / project / ".pmagent" / "feishu-wiki-folders.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert f"project/{project}" in cache
    assert f"project/{project}/research" in cache
    assert f"project/{project}/workspaces" not in cache


def test_lark_wiki_push_reuses_project_node_from_infra(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    def fake_run_json(args: list[str], *, input_text: str | None = None):
        calls.append(list(args))
        if args[:2] == ["wiki", "+node-create"]:
            return _make_node_payload("created_node", "created_obj", "https://example.invalid/wiki/created")
        if args[:2] == ["docs", "+update"]:
            return {"data": {"revision_id": 1}}
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr(lark_wiki_push, "_run_json", fake_run_json)
    data_dir = tmp_path / "pm-data"
    project = "alpha"
    workspace = "alpha-discovery"
    infra_path = data_dir / "projects" / project / ".pmagent" / "feishu-infra.json"
    infra_path.parent.mkdir(parents=True)
    infra_path.write_text(json.dumps({"project_node_token": "existing_project_node"}), encoding="utf-8")
    file_path = data_dir / "workspaces" / workspace / "Requirement.md"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("# Requirement\n\nContent.\n", encoding="utf-8")

    lark_wiki_push.push_file_to_wiki(
        file_path=file_path,
        relative="Requirement.md",
        project=project,
        workspace=workspace,
        space_id="my_library",
        data_dir=data_dir,
    )

    node_create_calls = [c for c in calls if c[:2] == ["wiki", "+node-create"]]
    assert len(node_create_calls) == 3
    assert project not in node_create_calls[0]
    assert "workspaces" in node_create_calls[0]
    assert ["--parent-node-token", "existing_project_node"] == node_create_calls[0][-2:]


def test_lark_wiki_push_reuses_folder_cache(monkeypatch, tmp_path: Path):
    """Second file in the same folder should not recreate the folder node."""
    calls: list[list[str]] = []
    node_counter = {"n": 0}

    def fake_run_json(args: list[str], *, input_text: str | None = None):
        calls.append(list(args))
        if args[:2] == ["wiki", "+node-create"]:
            node_counter["n"] += 1
            n = node_counter["n"]
            return _make_node_payload(f"wikcn_{n}", f"obj_{n}", f"https://example.invalid/wiki/{n}")
        if args[:2] == ["docs", "+update"]:
            return {"data": {"revision_id": 1}}
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr(lark_wiki_push, "_run_json", fake_run_json)
    data_dir = tmp_path / "pm-data"
    workspace = "my-workspace"

    for name in ("a.md", "b.md"):
        fp = data_dir / "workspaces" / workspace / "decisions" / name
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f"# {name}\n\nContent.\n", encoding="utf-8")
        lark_wiki_push.push_file_to_wiki(
            file_path=fp,
            relative=f"decisions/{name}",
            workspace=workspace,
            space_id="my_library",
            data_dir=data_dir,
        )

    node_create_calls = [c for c in calls if c[:2] == ["wiki", "+node-create"]]
    # 1: workspace root, 2: decisions folder, 3: a.md doc, 4: b.md doc
    # (workspace root and decisions folder NOT recreated for b.md)
    assert len(node_create_calls) == 4


def test_docs_update_uses_command_flag(monkeypatch, tmp_path: Path):
    """docs +update must use v2 API flags: --command/--doc-format/--content, not --mode/--markdown."""
    calls: list[list[str]] = []

    def fake_run_json(args: list[str], *, input_text: str | None = None):
        calls.append(list(args))
        if args[:2] == ["wiki", "+node-create"]:
            return _make_node_payload("wikcn_x", "obj_x", "https://example.invalid/wiki/x")
        if args[:2] == ["docs", "+update"]:
            return {"data": {"revision_id": 1}}
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr(lark_wiki_push, "_run_json", fake_run_json)
    data_dir = tmp_path / "pm-data"
    workspace = "ws"
    fp = data_dir / "workspaces" / workspace / "Requirement.md"
    fp.parent.mkdir(parents=True)
    fp.write_text("# Req\n\nContent.\n", encoding="utf-8")

    lark_wiki_push.push_file_to_wiki(
        file_path=fp,
        relative="Requirement.md",
        workspace=workspace,
        space_id="my_library",
        data_dir=data_dir,
    )

    update_calls = [c for c in calls if c[:2] == ["docs", "+update"]]
    assert len(update_calls) == 1
    update_args = update_calls[0]
    # v2 API flags
    assert "--api-version" in update_args
    assert "v2" in update_args
    assert "--command" in update_args
    assert "overwrite" in update_args
    assert "--doc-format" in update_args
    assert "markdown" in update_args
    assert "--content" in update_args
    assert "-" in update_args
    # v1 flags must NOT be present
    assert "--mode" not in update_args
    assert "--markdown" not in update_args
