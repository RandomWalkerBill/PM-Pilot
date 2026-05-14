from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .executors import ExecutorResult, run_executor


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


ROUND_META_MARKERS = (
    "已切换为",
    "发送辩题",
    "把辩题发来",
    "把材料发来",
    "把材料贴过来",
    "把 defender 的论点",
    "把辩题、立场",
    "你给出命题",
    "你给出辩题",
    "如果你给出",
    "如果给出",
    "我将以 debate 的",
    "我将以 debate 中的",
    "后续我会默认站在",
    "默认站在",
    "后续我会优先攻击对方论证中的",
    "我会优先为该方案建立最强论证",
)


SYNTHESIS_META_MARKERS = (
    "角色定位",
    "当前消息是角色校准",
    "把辩论内容发来",
    "如果你提供辩论原文",
    "我会按“debate 记录整理者”角色工作",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _section_value(text: str, heading: str) -> str:
    pattern = rf"{re.escape(heading)}\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _format_round_markdown(payload: dict) -> str:
    def _clean_field(value: object, *, label: str) -> str:
        text = str(value or "").strip()
        patterns = [
            rf"^#+\s*{re.escape(label)}\s*$",
            rf"^{re.escape(label)}\s*[:：-]?\s*$",
        ]
        changed = True
        while changed and text:
            changed = False
            lines = text.splitlines()
            if not lines:
                break
            head = lines[0].strip()
            for pattern in patterns:
                if re.match(pattern, head, re.IGNORECASE):
                    text = "\n".join(lines[1:]).strip()
                    changed = True
                    break
        return text

    def _clean_argument(value: object) -> str:
        text = _clean_field(value, label="Arguments")
        text = re.sub(r"^\s*\d+\.\s*", "", text)
        return text.strip()

    args = payload.get("arguments")
    if not isinstance(args, list):
        args = []
    lines = [
        "## Core Claim",
        _clean_field(payload.get("core_claim"), label="Core Claim"),
        "",
        "## Arguments",
    ]
    for idx, item in enumerate(args, start=1):
        cleaned = _clean_argument(item)
        if cleaned:
            lines.append(f"{idx}. {cleaned}")
    lines.extend(["", "## Closing Line", _clean_field(payload.get("closing_line"), label="Closing Line")])
    return "\n".join(lines).strip() + "\n"


def _format_synthesis_markdown(payload: dict) -> str:
    convergence = payload.get("convergence")
    if not isinstance(convergence, list):
        convergence = []
    divergences = payload.get("core_divergences")
    if not isinstance(divergences, list):
        divergences = []
    findings = payload.get("unexpected_findings")
    if not isinstance(findings, list):
        findings = []
    acknowledgements = payload.get("acknowledgements")
    if not isinstance(acknowledgements, list):
        acknowledgements = []
    flags = payload.get("quality_flags")
    if not isinstance(flags, list):
        flags = []
    lines = [
        "# Debate Synthesis: topic",
        "",
        "## Thesis",
        str(payload.get("thesis") or "").strip(),
        "",
        "## Chosen Axis",
        str(payload.get("chosen_axis") or "").strip(),
        "",
        "## Convergence",
    ]
    for item in convergence:
        lines.append(f"- {str(item).strip()}")
    if not convergence:
        lines.append("- (none)")
    lines.extend(["", "## Core Divergences"])
    for item in divergences:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"- {str(item.get('title') or '').strip()}",
                f"  - Defender 立场: {str(item.get('defender') or '').strip()}",
                f"  - Attacker 立场: {str(item.get('attacker') or '').strip()}",
                f"  - 人需要裁决的判断: {str(item.get('judgment') or '').strip()}",
            ]
        )
    if not divergences:
        lines.append("- (none)")
    lines.extend(["", "## Unexpected Findings"])
    for item in findings:
        lines.append(f"- {str(item).strip()}")
    if not findings:
        lines.append("- (none)")
    lines.extend(["", "## Acknowledgements / Adjustments"])
    for item in acknowledgements:
        lines.append(f"- {str(item).strip()}")
    if not acknowledgements:
        lines.append("- (none)")
    lines.extend(["", "## Quality Flags"])
    for item in flags:
        lines.append(f"- {str(item).strip()}")
    if not flags:
        lines.append("- (none)")
    lines.extend(["", "## Recommended Next Action", str(payload.get("recommended_next_action") or "").strip()])
    return "\n".join(lines).strip() + "\n"


def mark_failed(topic_dir: Path, *, reason: str, round_idx: int | None = None, draft_text: str | None = None) -> None:
    if draft_text:
        write_text(topic_dir / "synthesis.md.draft", draft_text)
    write_json(
        topic_dir / "status.json",
        {
            "state": "failed",
            "round": round_idx,
            "started_at": utc_now_iso(),
            "completed_at": utc_now_iso(),
            "error": reason,
        },
    )
    write_json(
        topic_dir / "signal.json",
        {
            "event": "failed",
            "topic": topic_dir.name,
            "round": round_idx,
            "action_needed": "inspect_failure",
            "reason": reason,
            "completed_at": utc_now_iso(),
        },
    )


MAX_CONTEXT_TOTAL_CHARS = 12000
MAX_CONTEXT_SECTION_CHARS = 3500


def _truncate_context_text(text: str, *, limit: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    head = max(int(limit * 0.7), 1)
    tail = max(limit - head - 48, 0)
    omitted = max(len(cleaned) - head - tail, 0)
    if tail <= 0:
        return cleaned[:limit].rstrip() + f"\n...[truncated {len(cleaned) - limit} chars]..."
    return (
        cleaned[:head].rstrip()
        + f"\n...[truncated {omitted} chars]...\n"
        + cleaned[-tail:].lstrip()
    )


def build_context_blob(workspace_root: Path, thesis: str, axis: str) -> str:
    requirement = read_text(workspace_root / "Requirement.md")
    summary = read_text(workspace_root / "workspace-summary.md")
    strategy_root = workspace_root / "strategy"
    research_root = workspace_root / "research"
    strategy_files = sorted(strategy_root.glob("*.md")) if strategy_root.exists() else []
    research_files = sorted(research_root.glob("*.md")) if research_root.exists() else []
    sections = [("Thesis", thesis.strip()), ("Chosen Axis", axis.strip())]
    if requirement.strip():
        sections.append(("Requirement.md", requirement.strip()))
    if summary.strip():
        sections.append(("workspace-summary.md", summary.strip()))
    if strategy_files:
        sections.append((f"Latest strategy file ({strategy_files[-1].name})", read_text(strategy_files[-1]).strip()))
    if research_files:
        sections.append((f"Latest research file ({research_files[-1].name})", read_text(research_files[-1]).strip()))

    rendered: list[str] = []
    total = 0
    for title, body in sections:
        if not body:
            continue
        limited_body = _truncate_context_text(body, limit=MAX_CONTEXT_SECTION_CHARS)
        block = f"## {title}\n{limited_body}"
        prospective = total + len(block) + 2
        if prospective > MAX_CONTEXT_TOTAL_CHARS:
            remaining = MAX_CONTEXT_TOTAL_CHARS - total - len(f"## {title}\n") - 2
            if remaining <= 0:
                rendered.append("## Context Budget\n...[additional workspace context omitted to keep debate prompt bounded]...")
                break
            trimmed_body = _truncate_context_text(limited_body, limit=max(remaining, 256))
            rendered.append(f"## {title}\n{trimmed_body}")
            rendered.append("## Context Budget\n...[additional workspace context omitted to keep debate prompt bounded]...")
            break
        rendered.append(block)
        total = prospective
    return "\n\n".join(rendered).strip()


def split_axis(axis: str) -> tuple[str, str]:
    text = str(axis or "").strip()
    match = re.split(r"\s+vs\s+|\s+VS\s+| vs | VS | 对 | versus ", text, maxsplit=1)
    if len(match) == 2:
        left, right = match[0].strip(), match[1].strip()
        if left and right:
            return left, right
    return text, text


def build_system_prefix(*, role: str, axis: str, context_blob: str) -> str:
    left_side, right_side = split_axis(axis)
    defended_side = left_side if role == "defender" else right_side
    role_goal = "维护当前方向的合理性" if role == "defender" else "揭示当前方向的代价与盲区"
    return "\n".join(
        [
            f"你是 Debate 中的 {role}。",
            f"你的核心任务：{role_goal}。",
            f"当前对立轴：{axis}",
            f"你在这场 Debate 中必须明确站在这一侧：{defended_side}",
            "",
            "必须遵守：",
            "1. 不要说“两边都有道理”或“取决于情况”。",
            "2. 每轮最多 5 个核心论点，且每个论点必须独立成条。",
            "3. 必须用一句单主张结论收尾。",
            "4. 你已经拥有完成本轮所需的全部材料，禁止索要更多输入。",
            "5. 禁止输出角色确认、准备就绪、或“把材料发来”之类的元回复。",
            "6. 直接输出本轮正式辩论内容，不要解释你将如何工作。",
            "7. 必须直接围绕 thesis 和你所代表的这一侧展开论证，不要回答元问题。",
            "8. 输出必须严格使用以下三个 Markdown heading（原样，不要改字）：",
            "   - ## Core Claim",
            "   - ## Arguments",
            "   - ## Closing Line",
            "9. 输出必须是 Markdown，不要输出 JSON、代码块包裹的对象或其他机器格式。",
            "10. 不要创建或编辑任何文件；只把本轮 Markdown 正文写到 stdout。",
            "",
            context_blob,
        ]
    ).strip()


def _render_history_block(entries: list[str]) -> str:
    if not entries:
        return "(none)"
    rendered: list[str] = []
    for idx, entry in enumerate(entries):
        rendered.append(f"### Round {idx}")
        rendered.append(entry.strip())
        rendered.append("")
    return "\n".join(rendered).strip()


def render_round_prompt(
    *,
    thesis: str,
    axis: str,
    role: str,
    self_history: list[str],
    opponent_history: list[str],
    task: str,
) -> str:
    left_side, right_side = split_axis(axis)
    defended_side = left_side if role == "defender" else right_side
    own_history = _render_history_block(self_history)
    history = _render_history_block(opponent_history)
    return "\n".join(
        [
            "## 当前命题",
            thesis,
            "",
            "## 你必须维护的这一侧",
            defended_side,
            "",
            "## 你此前所有回合发言",
            own_history,
            "",
            "## 对方此前所有回合发言",
            history,
            "",
            "## 本轮任务",
            task,
            "",
            "## 输出要求",
            "直接给出本轮正式辩论内容。",
            "不要索要更多信息。",
            "不要输出角色介绍。",
            "不要说“把辩题发来”“把材料贴过来”“我会如何回应”。",
            "不要创建或编辑任何文件；只把本轮 Markdown 正文写到 stdout。",
            "如果这是 Round 0 且目前没有对方发言，你仍必须独立完成这一侧的完整论证，不要等待额外材料。",
            "输出必须是 Markdown，不要输出 JSON、字典、数组或代码块包裹的结构。",
            "必须严格使用以下三个 heading（原样，不要改字）：",
            "## Core Claim",
            "## Arguments",
            "## Closing Line",
            "其中：",
            "- `## Arguments` 下必须是 2 到 5 条编号论点（如不足 2 条至少也要 1 条）",
            "- 每条论点只表达一个点，不要把多条挤进同一个字符串",
        ]
    ).strip()


def _quality_flags(text: str) -> list[str]:
    flags: list[str] = []
    lowered = text.lower()
    hedging_markers = ("两边都有道理", "取决于情况", "可以结合", "也有道理", "it depends")
    if any(marker in text or marker in lowered for marker in hedging_markers):
        flags.append("hedging")
    return flags


ROUND_SECTION_LABELS = {
    "## Core Claim": ["Core Claim", "Thesis", "Position", "立场摘要", "核心主张", "主张", "立场"],
    "## Arguments": ["Arguments", "理由", "论点", "核心论点", "Reasons"],
    "## Closing Line": ["Closing Line", "Conclusion", "结论", "收束", "总结", "结语"],
}


SYNTHESIS_SECTION_LABELS = {
    "## Thesis": ["Thesis", "命题"],
    "## Chosen Axis": ["Chosen Axis", "Axis", "对立轴"],
    "## Convergence": ["Convergence", "收敛点", "共识"],
    "## Core Divergences": ["Core Divergences", "分歧点", "核心分歧"],
    "## Unexpected Findings": ["Unexpected Findings", "意外发现"],
    "## Acknowledgements / Adjustments": ["Acknowledgements / Adjustments", "Acknowledgements", "Adjustments", "修正记录"],
    "## Quality Flags": ["Quality Flags", "质量标记"],
    "## Recommended Next Action": ["Recommended Next Action", "Next Action", "下一步建议"],
}


ROUND_EXEC_TIMEOUT_SECONDS = 180
SYNTHESIS_EXEC_TIMEOUT_SECONDS = 180


def _timeout_seconds(env_name: str, default: int) -> float:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return value if value > 0 else float(default)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        inner = re.sub(r"^```[^\n]*\n?", "", stripped)
        inner = re.sub(r"\n?```$", "", inner)
        return inner.strip()
    return text


def _canonicalize_markdown_sections(text: str, section_labels: dict[str, list[str]]) -> str:
    normalized_lines: list[str] = []
    for raw_line in _strip_code_fences(text).replace("\r\n", "\n").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            normalized_lines.append("")
            continue
        replaced = False
        for canonical, labels in section_labels.items():
            for label in labels:
                escaped = re.escape(label)
                if re.fullmatch(rf"#+\s*{escaped}\s*", stripped, re.IGNORECASE) or re.fullmatch(
                    rf"{escaped}\s*[:：-]?\s*", stripped, re.IGNORECASE
                ):
                    normalized_lines.append(canonical)
                    replaced = True
                    break
                inline = re.fullmatch(rf"(?:#+\s*)?{escaped}\s*[:：-]\s*(.+)", stripped, re.IGNORECASE)
                if inline:
                    normalized_lines.append(canonical)
                    normalized_lines.append(inline.group(1).strip())
                    replaced = True
                    break
            if replaced:
                break
        if not replaced:
            normalized_lines.append(raw_line.rstrip())
    return "\n".join(normalized_lines).strip()


def _collect_named_sections(text: str, canonical_sections: list[str]) -> tuple[dict[str, str], list[str]]:
    sections: dict[str, list[str]] = {heading: [] for heading in canonical_sections}
    current: str | None = None
    unassigned: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped in canonical_sections:
            current = stripped
            continue
        if current is None:
            if stripped:
                unassigned.append(raw_line.rstrip())
            continue
        sections[current].append(raw_line.rstrip())
    compact = {heading: "\n".join(lines).strip() for heading, lines in sections.items()}
    return compact, unassigned


def _extract_argument_items(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        marker = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", stripped)
        if marker:
            if current:
                items.append(" ".join(part for part in current if part).strip())
            current = [marker.group(1).strip()]
            continue
        heading_marker = re.match(r"^#{3,6}\s+(?:\d+[.)]?\s*)?(.+)$", stripped)
        if heading_marker:
            if current:
                items.append(" ".join(part for part in current if part).strip())
            current = [heading_marker.group(1).strip()]
            continue
        if current:
            if not stripped:
                continue
            if re.match(r"^#+\s+", stripped):
                continue
            current.append(stripped)
    if current:
        items.append(" ".join(part for part in current if part).strip())
    return [item for item in items if item]


def _paragraphs_from_lines(lines: list[str]) -> list[str]:
    text = "\n".join(lines).strip()
    if not text:
        return []
    return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


def _first_non_list_text(text: str) -> str:
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if re.match(r"^(?:[-*]|\d+[.)])\s+", stripped):
            continue
        return stripped
    return ""


def _last_non_list_text(text: str) -> str:
    for raw_line in reversed(text.splitlines()):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if re.match(r"^(?:[-*]|\d+[.)])\s+", stripped):
            continue
        return stripped
    return ""


def _parse_round_markdown(text: str) -> dict[str, object]:
    canonical = _canonicalize_markdown_sections(text, ROUND_SECTION_LABELS)
    section_map, unassigned_lines = _collect_named_sections(
        canonical,
        ["## Core Claim", "## Arguments", "## Closing Line"],
    )
    core_claim = _first_non_list_text(section_map["## Core Claim"]) or section_map["## Core Claim"].strip()
    closing_line = _last_non_list_text(section_map["## Closing Line"]) or section_map["## Closing Line"].strip()
    arguments = _extract_argument_items(section_map["## Arguments"])

    unassigned_blocks = _paragraphs_from_lines(unassigned_lines)
    non_list_blocks = [block for block in unassigned_blocks if not re.match(r"^(?:[-*]|\d+[.)])\s+", block)]

    if not core_claim and non_list_blocks:
        core_claim = non_list_blocks[0]
    if not arguments:
        arguments = _extract_argument_items(canonical)
    if not arguments and len(non_list_blocks) > 2:
        arguments = non_list_blocks[1:-1]
    if not arguments and len(non_list_blocks) == 2:
        arguments = [non_list_blocks[1]]
    if not closing_line:
        if len(non_list_blocks) > 1:
            closing_line = non_list_blocks[-1]
        elif core_claim:
            closing_line = core_claim

    payload = {
        "core_claim": core_claim.strip(),
        "arguments": [item.strip() for item in arguments if item.strip()],
        "closing_line": closing_line.strip(),
    }
    return payload


def validate_round_content(text: str) -> dict[str, object]:
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in ROUND_META_MARKERS):
        raise RuntimeError("round output drifted into role/meta language instead of direct argumentation")

    payload = _parse_round_markdown(text)
    missing: list[str] = []
    if not str(payload.get("core_claim") or "").strip():
        missing.append("## Core Claim")
    if not isinstance(payload.get("arguments"), list) or not payload.get("arguments"):
        missing.append("## Arguments")
    if not str(payload.get("closing_line") or "").strip():
        missing.append("## Closing Line")
    if missing:
        raise RuntimeError(f"round output missing sections: {', '.join(missing)}")
    return payload


def _normalize_list_items(text: str) -> list[str]:
    items = _extract_argument_items(text)
    if items:
        return items
    return [line.strip("-* \t") for line in text.splitlines() if line.strip()]


def _parse_core_divergences(text: str) -> list[dict[str, str]]:
    divergences: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        top_level = re.match(r"^[-*]\s+(.+)$", stripped)
        heading_level = re.match(r"^#{1,6}\s+(.+)$", stripped)
        numbered_level = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        title_match = top_level or heading_level or numbered_level
        if title_match and not any(token in stripped for token in ("Defender", "Attacker", "裁决")):
            if current:
                divergences.append(current)
            title = title_match.group(1).strip()
            title = re.sub(r"^\d+[.)]\s*", "", title).strip()
            current = {"title": title, "defender": "", "attacker": "", "judgment": ""}
            continue
        if current is None:
            continue
        defender = re.match(r"^(?:[-*]\s+)?Defender\s*立场[:：]\s*(.+)$", stripped)
        attacker = re.match(r"^(?:[-*]\s+)?Attacker\s*立场[:：]\s*(.+)$", stripped)
        judgment = re.match(r"^(?:[-*]\s+)?人需要裁决的判断[:：]\s*(.+)$", stripped)
        if defender:
            current["defender"] = defender.group(1).strip()
        elif attacker:
            current["attacker"] = attacker.group(1).strip()
        elif judgment:
            current["judgment"] = judgment.group(1).strip()
    if current:
        divergences.append(current)
    return [item for item in divergences if item.get("title")]


def _parse_synthesis_markdown(text: str) -> dict[str, object]:
    canonical = _canonicalize_markdown_sections(text, SYNTHESIS_SECTION_LABELS)
    section_order = list(SYNTHESIS_SECTION_LABELS.keys())
    section_map, unassigned_lines = _collect_named_sections(canonical, section_order)
    if unassigned_lines and not section_map["## Core Divergences"] and any(
        token in "\n".join(unassigned_lines) for token in ("Defender", "Attacker", "裁决")
    ):
        section_map["## Core Divergences"] = "\n".join(unassigned_lines).strip()

    payload = {
        "thesis": section_map["## Thesis"].strip(),
        "chosen_axis": section_map["## Chosen Axis"].strip(),
        "convergence": _normalize_list_items(section_map["## Convergence"]),
        "core_divergences": _parse_core_divergences(section_map["## Core Divergences"]),
        "unexpected_findings": _normalize_list_items(section_map["## Unexpected Findings"]),
        "acknowledgements": _normalize_list_items(section_map["## Acknowledgements / Adjustments"]),
        "quality_flags": _normalize_list_items(section_map["## Quality Flags"]),
        "recommended_next_action": section_map["## Recommended Next Action"].strip(),
    }
    return payload


def _build_round_retry_prompt(*, original_prompt: str, reason: str) -> str:
    return (
        f"{original_prompt}\n\n"
        "## 上一版输出不合格，请立刻重写\n"
        f"问题：{reason}\n"
        "重写要求：\n"
        "- 直接输出正式辩论内容\n"
        "- 不要角色确认，不要索要辩题或材料\n"
        "- 如果没有对方发言，也必须独立完成本侧论证\n"
        "- 保持原有立场，不要改成中立总结\n"
        "- 如果上一版内容基本可用，请只重排格式，不要新增或删除核心观点\n"
        "- 不要输出 JSON、字典、数组或代码块包裹的结构\n"
        "- 必须严格使用以下三个 heading（原样，不要改字）：\n"
        "  ## Core Claim\n"
        "  ## Arguments\n"
        "  ## Closing Line\n"
    ).strip()


def _round_side_suffix(raw_artifact_base: Path) -> str | None:
    suffix = raw_artifact_base.name.rsplit("-", 1)[-1].strip()
    return suffix if suffix in {"pro", "con"} else None


def _candidate_round_artifacts(raw_artifact_base: Path, *, since: float) -> list[Path]:
    side = _round_side_suffix(raw_artifact_base)
    if side is None:
        return []
    candidates: dict[Path, float] = {}
    expected = raw_artifact_base.with_suffix(".md")
    search_paths = [expected]
    if raw_artifact_base.parent.exists():
        search_paths.extend(raw_artifact_base.parent.glob(f"round-*-{side}.md"))
    for path in search_paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < since - 2.0:
            continue
        candidates[path.resolve()] = stat.st_mtime
    return sorted(candidates, key=lambda item: candidates[item], reverse=True)


def _round_content_from_side_effect_artifact(raw_artifact_base: Path, *, since: float) -> str | None:
    for path in _candidate_round_artifacts(raw_artifact_base, since=since):
        raw_text = read_text(path)
        try:
            payload = validate_round_content(raw_text)
        except RuntimeError:
            continue
        return _format_round_markdown(payload)
    return None


def _execute_round_side(
    *,
    executor_runner: Callable[..., ExecutorResult],
    executor_id: str,
    prompt: str,
    cwd: Path,
    session_id: str | None,
    model: str | None,
    raw_artifact_base: Path,
    fallback_executor_id: str | None = None,
    fallback_model: str | None = None,
) -> tuple[str, str | None]:
    candidates: list[tuple[str, str | None, str | None]] = [(executor_id, model, session_id)]
    if fallback_executor_id and fallback_executor_id != executor_id:
        candidates.append((fallback_executor_id, fallback_model, None))

    last_error: Exception | None = None
    for candidate_executor_id, candidate_model, candidate_session_id in candidates:
        current_prompt = prompt
        current_session_id = candidate_session_id
        for attempt in range(2):
            attempt_started_at = time.time()
            try:
                result = executor_runner(
                    candidate_executor_id,
                    current_prompt,
                    cwd=cwd,
                    session_id=current_session_id,
                    model=candidate_model,
                    schema=None,
                    timeout_seconds=_timeout_seconds("PMAGENT_DEBATE_ROUND_TIMEOUT", ROUND_EXEC_TIMEOUT_SECONDS),
                )
            except Exception as exc:  # noqa: BLE001
                artifact_content = _round_content_from_side_effect_artifact(
                    raw_artifact_base,
                    since=attempt_started_at,
                )
                if artifact_content is not None:
                    return artifact_content, current_session_id
                last_error = exc
                break
            raw_text = result.content
            current_session_id = result.session_id
            try:
                payload = validate_round_content(raw_text)
                content = _format_round_markdown(payload)
                return content, current_session_id
            except RuntimeError as exc:
                artifact_content = _round_content_from_side_effect_artifact(
                    raw_artifact_base,
                    since=attempt_started_at,
                )
                if artifact_content is not None:
                    return artifact_content, current_session_id
                last_error = exc
                if attempt == 0:
                    current_prompt = _build_round_retry_prompt(original_prompt=prompt, reason=str(exc))
                    continue
                break
    if last_error is not None:
        raise last_error
    raise RuntimeError("round execution failed without explicit error")


def build_synthesis_prompt(*, thesis: str, axis: str, round_records: list[dict[str, object]]) -> str:
    lines = [
        "你是 Debate 记录整理者，不是辩手。",
        "你的任务不是判断谁赢了，而是输出结构化 Markdown synthesis。",
        "你已经拥有完成 synthesis 所需的全部材料。",
        "禁止索要更多输入。",
        "禁止输出角色确认、准备说明或解释过程。",
        "禁止输出 JSON、字典、数组或代码块包裹的结构。",
        "禁止把 Thesis / Chosen Axis 写成角色说明、任务说明或元信息。",
        "Thesis 字段必须逐字等于给定 Thesis。",
        "Chosen Axis 字段必须逐字等于给定 Chosen Axis。",
        "Recommended Next Action 必须基于已有 debate 材料，不得要求用户重新提供辩论内容。",
        "输出必须直接从 `# Debate Synthesis:` 开始。",
        "必须包含以下 section：",
        "## Thesis",
        "## Chosen Axis",
        "## Convergence",
        "## Core Divergences",
        "## Unexpected Findings",
        "## Acknowledgements / Adjustments",
        "## Quality Flags",
        "## Recommended Next Action",
        "",
        "每个 Core Divergences 条目必须包含：",
        "- Defender 立场",
        "- Attacker 立场",
        "- 人需要裁决的判断",
        "",
        "输入如下：",
        f"Thesis: {thesis}",
        f"Chosen Axis: {axis}",
        "",
    ]
    for record in round_records:
        lines.append(f"### Round {record['round']} / Defender")
        lines.append(str(record["defender"]))
        lines.append("")
        lines.append(f"### Round {record['round']} / Attacker")
        lines.append(str(record["attacker"]))
        flags = record.get("flags") or []
        if flags:
            lines.append("")
            lines.append(f"### Round {record['round']} / Flags")
            lines.append(", ".join(str(item) for item in flags))
        lines.append("")
    return "\n".join(lines).strip()


def validate_synthesis(text: str, *, thesis: str, axis: str) -> dict[str, object]:
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in SYNTHESIS_META_MARKERS):
        raise RuntimeError("synthesis drifted into role/meta language instead of debate conclusions")

    payload = _parse_synthesis_markdown(text)
    required_sections = []
    if not str(payload.get("thesis") or "").strip():
        required_sections.append("## Thesis")
    if not str(payload.get("chosen_axis") or "").strip():
        required_sections.append("## Chosen Axis")
    if not isinstance(payload.get("convergence"), list) or not payload.get("convergence"):
        required_sections.append("## Convergence")
    if not isinstance(payload.get("core_divergences"), list) or not payload.get("core_divergences"):
        required_sections.append("## Core Divergences")
    if not isinstance(payload.get("unexpected_findings"), list) or not payload.get("unexpected_findings"):
        required_sections.append("## Unexpected Findings")
    if not str(payload.get("recommended_next_action") or "").strip():
        required_sections.append("## Recommended Next Action")
    if required_sections:
        raise RuntimeError(f"synthesis missing sections: {', '.join(required_sections)}")
    thesis_value = str(payload.get("thesis") or "").strip()
    if _normalize_text(thesis_value) != _normalize_text(thesis):
        raise RuntimeError("synthesis thesis must exactly restate the debate thesis")
    axis_value = str(payload.get("chosen_axis") or "").strip()
    if _normalize_text(axis_value) != _normalize_text(axis):
        raise RuntimeError("synthesis chosen axis must exactly restate the chosen axis")
    for item in payload.get("core_divergences", []):
        if not isinstance(item, dict):
            raise RuntimeError("synthesis divergences must contain Defender / Attacker / 人需要裁决的判断")
        if not item.get("defender") or not item.get("attacker") or not item.get("judgment"):
            raise RuntimeError("synthesis divergences must contain Defender / Attacker / 人需要裁决的判断")
    recommended = str(payload.get("recommended_next_action") or "").strip()
    material_request_markers = (
        "请提供辩论材料",
        "请把辩论内容发来",
        "把辩论内容发来",
        "请提供辩论内容",
    )
    if any(marker in recommended for marker in material_request_markers):
        raise RuntimeError("synthesis next action must build on the existing debate instead of requesting materials again")
    return payload


def run_debate(
    *,
    topic_dir: Path,
    workspace_root: Path,
    thesis: str,
    axis: str,
    defender_exec: str,
    attacker_exec: str,
    synthesizer_exec: str,
    defender_model: str | None = None,
    attacker_model: str | None = None,
    synthesizer_model: str | None = None,
    round_count: int = 3,
    executor_runner: Callable[..., ExecutorResult] | None = None,
) -> dict[str, object]:
    executor_runner = executor_runner or run_executor
    context_blob = build_context_blob(workspace_root, thesis, axis)
    defender_prefix = build_system_prefix(role="defender", axis=axis, context_blob=context_blob)
    attacker_prefix = build_system_prefix(role="attacker", axis=axis, context_blob=context_blob)

    defender_session_id: str | None = None
    attacker_session_id: str | None = None
    round_records: list[dict[str, object]] = []

    base_tasks = [
        "Round 0：独立陈述立场。你看不到对方内容。",
        "Round 1：指出对方 Round 0 中最弱的一条假设或论据，并给出反驳。",
        "Round 2：围绕最无法调和的那个分歧点给出最终聚焦立场。",
    ]
    actual_rounds = max(int(round_count), 1)
    tasks = base_tasks + [
        "继续围绕最无法调和的那个分歧点推进，不要扩大战线，只压缩核心判断。"
        for _ in range(max(0, actual_rounds - len(base_tasks)))
    ]
    defender_history: list[str] = []
    attacker_history: list[str] = []

    for idx in range(actual_rounds):
        task = tasks[idx]
        defender_prompt = defender_prefix + "\n\n" + render_round_prompt(
            thesis=thesis,
            axis=axis,
            role="defender",
            self_history=defender_history,
            opponent_history=attacker_history,
            task=task,
        )
        try:
            defender_content, defender_session_id = _execute_round_side(
                executor_runner=executor_runner,
                executor_id=defender_exec,
                prompt=defender_prompt,
                cwd=workspace_root,
                session_id=None,
                model=defender_model,
                raw_artifact_base=topic_dir / f"round-{idx}-pro",
                fallback_executor_id=synthesizer_exec if synthesizer_exec != defender_exec else None,
                fallback_model=synthesizer_model if synthesizer_exec != defender_exec else None,
            )
            write_text(topic_dir / f"round-{idx}-pro.md", defender_content)

            attacker_prompt = attacker_prefix + "\n\n" + render_round_prompt(
                thesis=thesis,
                axis=axis,
                role="attacker",
                self_history=attacker_history,
                opponent_history=defender_history,
                task=task,
            )
            attacker_content, attacker_session_id = _execute_round_side(
                executor_runner=executor_runner,
                executor_id=attacker_exec,
                prompt=attacker_prompt,
                cwd=workspace_root,
                session_id=None,
                model=attacker_model,
                raw_artifact_base=topic_dir / f"round-{idx}-con",
                fallback_executor_id=defender_exec if defender_exec != attacker_exec else None,
                fallback_model=defender_model if defender_exec != attacker_exec else None,
            )
            write_text(topic_dir / f"round-{idx}-con.md", attacker_content)
        except Exception as exc:  # noqa: BLE001
            mark_failed(topic_dir, reason=str(exc), round_idx=idx)
            raise

        defender_flags = _quality_flags(defender_content)
        attacker_flags = _quality_flags(attacker_content)
        round_records.append(
            {
                "round": idx,
                "defender": defender_content,
                "attacker": attacker_content,
                "flags": [*defender_flags, *attacker_flags],
            }
        )
        defender_history.append(defender_content)
        attacker_history.append(attacker_content)

        write_json(
            topic_dir / "status.json",
            {
                "state": f"round-{idx + 1}-running" if idx < actual_rounds - 1 else "synthesizing",
                "round": idx + 1 if idx < actual_rounds - 1 else idx,
                "started_at": utc_now_iso(),
                "completed_at": None,
            },
        )
        write_json(
            topic_dir / "signal.json",
            {
                "event": "round_completed",
                "topic": topic_dir.name,
                "round": idx,
                "action_needed": None,
            },
        )

    synthesis_prompt = build_synthesis_prompt(thesis=thesis, axis=axis, round_records=round_records)
    try:
        try:
            synthesis_result = executor_runner(
                synthesizer_exec,
                synthesis_prompt,
                cwd=workspace_root,
                session_id=None,
                model=synthesizer_model,
                schema=None,
                timeout_seconds=_timeout_seconds("PMAGENT_DEBATE_SYNTHESIS_TIMEOUT", SYNTHESIS_EXEC_TIMEOUT_SECONDS),
            )
        except Exception as primary_exc:  # noqa: BLE001
            if synthesizer_exec == defender_exec:
                raise
            try:
                synthesis_result = executor_runner(
                    defender_exec,
                    synthesis_prompt,
                    cwd=workspace_root,
                    session_id=None,
                    model=defender_model,
                    schema=None,
                    timeout_seconds=_timeout_seconds("PMAGENT_DEBATE_SYNTHESIS_TIMEOUT", SYNTHESIS_EXEC_TIMEOUT_SECONDS),
                )
            except Exception as fallback_exc:  # noqa: BLE001
                raise RuntimeError(f"{primary_exc}; fallback synthesizer `{defender_exec}` failed: {fallback_exc}") from fallback_exc
        synthesis_content = synthesis_result.content.strip() + "\n"
        write_text(topic_dir / "synthesis.md", synthesis_content)
    except Exception as exc:  # noqa: BLE001
        draft_text = None
        if "synthesis_result" in locals():
            draft_text = synthesis_result.content
        mark_failed(topic_dir, reason=str(exc), round_idx=actual_rounds - 1, draft_text=draft_text)
        raise
    write_json(
        topic_dir / "status.json",
        {
            "state": "completed",
            "round": actual_rounds - 1,
            "started_at": utc_now_iso(),
            "completed_at": utc_now_iso(),
        },
    )
    write_json(
        topic_dir / "signal.json",
        {
            "event": "completed",
            "topic": topic_dir.name,
            "action_needed": "review_synthesis",
            "completed_at": utc_now_iso(),
        },
    )
    return {
        "defender_session_id": defender_session_id,
        "attacker_session_id": attacker_session_id,
        "round_count": actual_rounds,
    }
