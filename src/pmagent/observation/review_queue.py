from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import candidate_updates_root


QUEUE_BUCKETS = ("inbox", "accepted", "rejected", "snoozed")


def _rel(repo_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.relative_to(repo_root).as_posix()


def _parse_card_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                return meta if isinstance(meta, dict) else {}, parts[2].strip()
            except Exception:
                return {}, text
    return {}, text


def candidate_card_paths(repo_root: Path, workspace: str, bucket: str = "inbox") -> list[Path]:
    root = candidate_updates_root(repo_root, workspace) / bucket
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*.md") if path.is_file())


def candidate_card_ids(repo_root: Path, workspace: str, bucket: str = "inbox") -> list[str]:
    ids: list[str] = []
    for path in candidate_card_paths(repo_root, workspace, bucket):
        meta, _ = _parse_card_frontmatter(path)
        card_id = str(meta.get("card_id") or meta.get("observation_id") or path.stem).strip()
        if card_id:
            ids.append(card_id)
    return ids


def candidate_card_counts(repo_root: Path, workspace: str) -> dict[str, int]:
    return {bucket: len(candidate_card_paths(repo_root, workspace, bucket)) for bucket in QUEUE_BUCKETS}


def candidate_card_exists(repo_root: Path, workspace: str, card_id: str, slug: str) -> bool:
    root = candidate_updates_root(repo_root, workspace)
    for bucket in QUEUE_BUCKETS:
        for path in candidate_card_paths(repo_root, workspace, bucket):
            if path.stem == slug:
                return True
            meta, _ = _parse_card_frontmatter(path)
            if str(meta.get("card_id") or meta.get("observation_id") or "").strip() == card_id:
                return True
    return False


def _markdown_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _first_heading(body: str, default: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            return line[3:].strip() or default
        if line.startswith("# ") and line[2:].strip() not in {"Candidate Card", "Candidate Update"}:
            return line[2:].strip()
    return default


def _summary_from_body(body: str, sections: dict[str, str]) -> str:
    for key in ("Summary", "Body"):
        text = sections.get(key, "").strip()
        if text:
            return text
    suggested = sections.get("Suggested Action", "").strip()
    evidence = sections.get("Evidence", "").strip()
    if suggested:
        return suggested
    if evidence:
        return evidence
    cleaned = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#")).strip()
    return cleaned


def parse_candidate_card(repo_root: Path, path: Path) -> dict[str, Any]:
    meta, body = _parse_card_frontmatter(path)
    card_id = str(meta.get("card_id") or meta.get("observation_id") or path.stem).strip()
    title = str(meta.get("title") or "").strip() or _first_heading(body, card_id)
    sections = _markdown_sections(body)
    return {
        "card": card_id,
        "title": title,
        "kind": str(meta.get("source_type") or meta.get("kind") or "candidate_card"),
        "source": "candidate-updates",
        "source_type": str(meta.get("source_type") or meta.get("kind") or ""),
        "source_ref": str(meta.get("source_ref") or meta.get("observation_id") or ""),
        "status": str(meta.get("status") or path.parent.name or "inbox"),
        "urgency": str(meta.get("urgency") or "normal"),
        "summary": _summary_from_body(body, sections),
        "body": body,
        "suggested_action": sections.get("Suggested Action", ""),
        "evidence": sections.get("Evidence", ""),
        "file": _rel(repo_root, path),
    }
