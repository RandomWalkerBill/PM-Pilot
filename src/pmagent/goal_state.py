from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


CHECK_STATE_PATH = ".pmagent/goal-state-check.json"


@dataclass(frozen=True)
class GoalStateSnapshot:
    exists: bool
    path: Path
    updated_at: str | None
    goals: list[str]
    focus_workspaces: list[str]
    deferred_items: list[str]
    risks: list[str]
    next_actions: list[str]
    empty_template: bool

    @property
    def goal_summary(self) -> str:
        return "; ".join(self.goals[:3])


def goal_state_path(data_dir: Path) -> Path:
    return data_dir / "GOAL_STATE.md"


def goal_state_check_path(data_dir: Path) -> Path:
    return data_dir / CHECK_STATE_PATH


def load_goal_state_snapshot(data_dir: Path) -> GoalStateSnapshot:
    path = goal_state_path(data_dir)
    if not path.exists():
        return GoalStateSnapshot(
            exists=False,
            path=path,
            updated_at=None,
            goals=[],
            focus_workspaces=[],
            deferred_items=[],
            risks=[],
            next_actions=[],
            empty_template=True,
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    sections = _parse_sections(text)
    goals = _section_items(sections, "当前全局目标", "当前目标（1-3 条）", "当前目标")
    focus_workspaces = _focus_workspace_names(sections)
    deferred_items = _table_first_column(sections, "暂不展开")
    risks = _section_items(sections, "当前最大风险", "阻塞与风险")
    next_actions = _section_items(sections, "下一步行动")
    updated_at = _updated_at(sections)
    empty_template = not any([updated_at, goals, focus_workspaces, deferred_items, risks, next_actions])
    return GoalStateSnapshot(
        exists=True,
        path=path,
        updated_at=updated_at,
        goals=goals,
        focus_workspaces=focus_workspaces,
        deferred_items=deferred_items,
        risks=risks,
        next_actions=next_actions,
        empty_template=empty_template,
    )


def build_goal_state_checkpoint(
    data_dir: Path,
    *,
    workspace: str | None = None,
    project: str | None = None,
    today: date | None = None,
) -> dict:
    snapshot = load_goal_state_snapshot(data_dir)
    today = today or date.today()
    rel_path = snapshot.path.relative_to(data_dir).as_posix() if snapshot.path.is_relative_to(data_dir) else str(snapshot.path)
    base = {
        "path": rel_path,
        "exists": snapshot.exists,
        "updated_at": snapshot.updated_at,
        "goals": snapshot.goals,
        "focus_workspaces": snapshot.focus_workspaces,
        "deferred_items": snapshot.deferred_items,
        "goal_summary": snapshot.goal_summary,
        "checkpoint": None,
        "severity": "ok",
        "reason": None,
        "prompt": None,
    }

    if not snapshot.exists:
        return {
            **base,
            "checkpoint": "missing",
            "severity": "required",
            "reason": "GOAL_STATE.md does not exist at the PM Data root.",
            "prompt": "请创建 GOAL_STATE.md，补充当前全局目标、重点 workspace、暂不展开事项和最大风险。",
        }

    if snapshot.empty_template:
        return {
            **base,
            "checkpoint": "empty_template",
            "severity": "required",
            "reason": "GOAL_STATE.md still looks like an empty template.",
            "prompt": "GOAL_STATE.md 仍是空模板。请补充当前最重要的 1-3 个目标、当前重点 workspace、暂不展开事项和最大风险。",
        }

    normalized_workspace = str(workspace or "").strip()
    deferred_match = _matching_item(normalized_workspace, snapshot.deferred_items)
    if normalized_workspace and deferred_match:
        return {
            **base,
            "checkpoint": "workspace_deferred",
            "severity": "warning",
            "reason": f"Active workspace {normalized_workspace} is listed under 暂不展开.",
            "prompt": f"当前 active workspace 是 {normalized_workspace}，但它在 GOAL_STATE.md 的“暂不展开”列表中。请确认这是临时插队，还是要更新 GOAL_STATE。",
        }

    updated_date = _parse_date(snapshot.updated_at)
    check_state = _read_check_state(data_dir)
    if updated_date is None:
        return {
            **base,
            "checkpoint": "missing_updated_at",
            "severity": "notice",
            "reason": "GOAL_STATE.md has content but no parseable Updated At date.",
            "prompt": "请在 GOAL_STATE.md 的 Updated At 下写入日期，便于 PMA 判断每日/每周目标确认节奏。",
        }

    age_days = (today - updated_date).days
    last_weekly = _parse_date(str(check_state.get("last_weekly_confirmed_at") or ""))
    if age_days >= 7 and not _within_days(last_weekly, today, 7):
        return {
            **base,
            "checkpoint": "weekly_review",
            "severity": "notice",
            "reason": f"GOAL_STATE.md was last updated on {updated_date.isoformat()}, at least 7 days ago.",
            "prompt": "本周是否需要更新全局目标锚点？请确认当前目标、重点 project/workspace、暂不展开事项和最大风险。",
        }

    last_daily = _parse_date(str(check_state.get("last_daily_confirmed_at") or ""))
    if age_days > 0 and last_daily != today:
        return {
            **base,
            "checkpoint": "daily_confirm",
            "severity": "notice",
            "reason": f"GOAL_STATE.md Updated At is {updated_date.isoformat()}, not today.",
            "prompt": f"当前 GOAL_STATE 显示优先目标是：{snapshot.goal_summary or '（未写明）'}。今天是否仍沿用这个目标？",
        }

    if normalized_workspace and snapshot.focus_workspaces:
        focused_match = _matching_item(normalized_workspace, snapshot.focus_workspaces)
        if not focused_match:
            return {
                **base,
                "checkpoint": "workspace_not_focused",
                "severity": "notice",
                "reason": f"Active workspace {normalized_workspace} is not listed in 当前重点 Workspaces.",
                "prompt": f"当前 active workspace 是 {normalized_workspace}，但 GOAL_STATE.md 的重点列表没有它。这是临时处理，还是要把它加入当前目标？",
            }

    return base


def _parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return sections


def _section_items(sections: dict[str, list[str]], *names: str) -> list[str]:
    items: list[str] = []
    for name in names:
        for line in sections.get(name, []):
            stripped = line.strip()
            if stripped.startswith("-"):
                value = stripped.lstrip("-").strip()
                if value and not value.startswith("<!--"):
                    items.append(value)
    return items


def _focus_workspace_names(sections: dict[str, list[str]]) -> list[str]:
    for name in ("当前重点 Workspaces", "当前重点 Workspace", "当前重点工作区"):
        values = _table_first_column(sections, name)
        if values:
            return values
    return []


def _table_first_column(sections: dict[str, list[str]], *names: str) -> list[str]:
    values: list[str] = []
    for name in names:
        for line in sections.get(name, []):
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
            if not cells or set(cells[0]) <= {"-", ":"}:
                continue
            first = cells[0]
            if not first or first.lower() in {"workspace", "workspace/project", "project"}:
                continue
            values.append(first)
    return values


def _updated_at(sections: dict[str, list[str]]) -> str | None:
    for line in sections.get("Updated At", []):
        stripped = line.strip()
        if stripped and not stripped.startswith("<!--"):
            return stripped
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(0), "%Y-%m-%d").date()
    except ValueError:
        return None


def _read_check_state(data_dir: Path) -> dict:
    path = goal_state_check_path(data_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    goal_state = payload.get("goal_state")
    return goal_state if isinstance(goal_state, dict) else {}


def _matching_item(needle: str, haystack: list[str]) -> str | None:
    if not needle:
        return None
    for item in haystack:
        if needle == item or needle in item:
            return item
    return None


def _within_days(value: date | None, today: date, days: int) -> bool:
    if value is None:
        return False
    delta = (today - value).days
    return 0 <= delta < days
