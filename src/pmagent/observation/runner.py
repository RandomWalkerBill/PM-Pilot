from __future__ import annotations

import json
import os
import contextlib
import io
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from uuid import uuid4

import yaml

from ..current_state import preview_current_state, preview_project_state, sync_current_state, sync_project_state
from ..executors import ExecutorError, is_inside_agent, resolve_available_backend, run_executor
from .paths import (
    candidate_updates_root,
    maintenance_changelog_root,
    maintenance_consumed_root,
    maintenance_drafts_root,
    observation_file_path,
    prd_root,
    project_observation_files_root,
    project_observation_index_path,
    project_observation_policy_path,
    project_observation_root,
    project_observation_runs_root,
    project_observation_state_path,
    project_root,
    queue_summary_path,
    workspace_root,
    workspace_summary_path,
)
from .profile import (
    SUPPORTED_CADENCES,
    catch_up_due,
    load_profile,
    record_review_outcome,
    reset_cadence_recommendation,
    set_schedule_state,
)
from .scheduler import configure_schedule, delete_schedule
from .sources import load_runtime_env
from .summary_protocol import (
    build_observation_section,
    build_workspace_summary_document,
    inspect_summary,
    replace_observation_section,
    summary_revision,
)
QUEUE_BUCKETS = ("inbox", "accepted", "rejected", "snoozed")

from .cards import _classify_queue, _resolve_prd
from .helpers import (
    _infer_project_for_workspace,
    _observation_section_from_state,
    _project_exists,
    _rel,
    _project_observation_index,
    _project_observation_state,
    _read_json,
    _resolve_project,
    _run_id,
    _sync_observation_summary_from_state,
    _workspace_exists,
    _utc_now,
    _write_json,
    _write_project_observation_index,
    _write_project_observation_state,
    _write_last_run,
)

def _observation_summary_preview(section_body: str, reason: str | None = None) -> str:
    if reason:
        return f"# Observation Summary Preview\n\n> Diagnostic: {reason}\n\n{section_body}\n"
    return section_body + "\n"


def _initial_observation_section(*, workspace: str, enabled: bool, cadence: str) -> str:
    status = "scheduled" if enabled else "manual"
    return "\n".join(
        [
            "## Observation Focus",
            "",
            "<!-- What the observation layer should watch for this workspace. -->",
            "",
            "## Recent Observation",
            "",
            f"- Observation enabled: {'yes' if enabled else 'no'}",
            "- Last run: not started",
            "- Next scheduled run: not scheduled",
            "- Queue summary: inbox=0 accepted=0 rejected=0 snoozed=0",
            "- Needs review: no",
            "- Catch-up needed: no",
            "- Candidate updates: 0",
            "- Important pending signals: none",
            f"- Observation mode: {status}",
            f"- Cadence: {cadence}",
        ]
    )


def _seed_or_update_workspace_summary(*, repo_root: Path, workspace: str, enabled: bool, cadence: str) -> str:
    summary_path = workspace_summary_path(repo_root, workspace)
    observation_section = _initial_observation_section(workspace=workspace, enabled=enabled, cadence=cadence)
    status = inspect_summary(summary_path)
    if status.state == "missing_document":
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            build_workspace_summary_document(workspace=workspace, observation_section=observation_section),
            encoding="utf-8",
        )
        return "created"
    if status.state == "valid":
        replace_observation_section(summary_path, observation_section)
        return "updated"
    return "blocked"


def _write_observation_summary(
    *,
    repo_root: Path,
    workspace: str,
    run_id: str,
    findings_count: int,
    candidate_count: int,
    expected_revision: str,
    state: dict[str, object],
) -> tuple[str, bool, str | None]:
    section = _observation_section_from_state(
        state,
        workspace=workspace,
        run_id=run_id,
        findings_count=findings_count,
        candidate_count=candidate_count,
        status="active",
    )
    summary_path = workspace_summary_path(repo_root, workspace)
    try:
        replace_observation_section(summary_path, section, expected_revision=expected_revision)
        return section, False, None
    except RuntimeError as exc:
        return section, True, str(exc)


def _project_brief(
    *,
    project: str,
    project_text: str,
) -> str:
    parts = [f"project={project}"]
    if project_text.strip():
        parts.append("project_context:\n" + project_text.strip())
    return "\n\n".join(parts)


def _read_context_markdown(path: Path, *, limit: int) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")[:limit].strip("\ufeff")


def _project_context_text(repo_root: Path, project: str) -> str:
    root = _project_exists(repo_root, project)
    parts: list[str] = []
    for rel in ["PROJECT.md", "strategy", "decisions", "background", "research"]:
        path = root / rel
        if path.is_file():
            parts.append(_read_context_markdown(path, limit=4000))
        elif path.is_dir():
            for item in sorted(path.glob("*.md"))[:5]:
                parts.append(_read_context_markdown(item, limit=2000))
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _build_fallback_query_plan(*, project: str, project_text: str) -> list[dict[str, object]]:
    del project_text
    anchor = project.replace("-", " ").replace("_", " ")
    seed = anchor.strip() or project
    return [
        {"kind": "market", "query": f"{seed} competitors product updates", "count": 2, "freshness": "pm"},
        {"kind": "technology", "query": f"{seed} technical implementation updates", "count": 2, "freshness": "pm"},
        {"kind": "community", "query": f"{seed} user community feedback", "count": 2, "freshness": "pm"},
    ]


def build_query_plan(*, repo_root: Path, project: str, project_text: str) -> list[dict[str, object]]:
    from pmagent.retrieval import get_openai_client

    env = load_runtime_env(repo_root)
    client = get_openai_client(env)
    if not client:
        return _build_fallback_query_plan(project=project, project_text=project_text)

    model = os.environ.get("PMAGENT_OBSERVATION_MODEL", "gpt-4.1-mini")
    prompt = (
        "You are generating a compact observation query plan for a PM workspace.\n"
        "Return strict JSON with a top-level `queries` array.\n"
        "Each item must have: `kind`, `query`, `count`, `freshness`.\n"
        "Keep it to at most 4 focused queries. Favor relevance over breadth.\n\n"
        f"{_project_brief(project=project, project_text=project_text)}"
    )
    try:
        response = client.responses.create(model=model, input=prompt)
        text = getattr(response, "output_text", "").strip()
        if not text:
            raise ValueError("empty response")
        payload = json.loads(text)
        queries = payload.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ValueError("missing queries")
        normalized: list[dict[str, object]] = []
        for item in queries[:4]:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query", "")).strip()
            if not query:
                continue
            normalized.append(
                {
                    "kind": str(item.get("kind", "general")),
                    "query": query,
                    "count": int(item.get("count", 4)),
                    "freshness": str(item.get("freshness", "pm")),
                }
            )
        if normalized:
            return normalized
    except Exception:
        pass
    return _build_fallback_query_plan(project=project, project_text=project_text)


def fetch_query_results(*, repo_root: Path, query_plan: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    del repo_root, query_plan
    raise SystemExit(
        "direct Brave observation retrieval has been replaced by Agent-delegated observation; "
        "use `pmagent observe plan`, write raw-findings.jsonl, then run `pmagent observe ingest`."
    )


def _default_recall() -> dict[str, object]:
    return {
        "considered": False,
        "fired": False,
        "trigger_reasons": [],
        "caps_overridden": False,
        "override_reason": None,
        "additional_reads": [],
    }


def _valid_url(value: str) -> bool:
    if not value:
        return True
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_evidence(
    value: object,
    *,
    fallback_title: str,
    fallback_url: str,
    fallback_summary: str,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or fallback_title or "").strip()
            url = str(item.get("url") or fallback_url or "").strip()
            quote_or_summary = str(item.get("quote_or_summary") or item.get("summary") or fallback_summary or "").strip()
            if url and not _valid_url(url):
                raise ValueError(f"invalid evidence url: {url}")
            evidence.append({"title": title, "url": url, "quote_or_summary": quote_or_summary})
    if not evidence and (fallback_title or fallback_url or fallback_summary):
        evidence.append({"title": fallback_title, "url": fallback_url, "quote_or_summary": fallback_summary})
    return evidence


def _normalize_finding(raw: object, *, line_number: int | None = None) -> dict[str, object]:
    if not isinstance(raw, dict):
        location = f" on line {line_number}" if line_number is not None else ""
        raise ValueError(f"finding{location} must be a JSON object")
    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or raw.get("summary") or "").strip()
    if not title and not description:
        location = f" on line {line_number}" if line_number is not None else ""
        raise ValueError(f"finding{location} must include title or description")
    url = str(raw.get("url") or raw.get("source_url") or "").strip()
    if url and not _valid_url(url):
        location = f" on line {line_number}" if line_number is not None else ""
        raise ValueError(f"finding{location} has invalid url: {url}")
    confidence = str(raw.get("confidence") or "medium").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    kind = str(raw.get("kind") or "general").strip() or "general"
    query = str(raw.get("query") or "").strip()
    age = str(raw.get("age") or "").strip()
    evidence = _normalize_evidence(
        raw.get("evidence"),
        fallback_title=title,
        fallback_url=url,
        fallback_summary=description,
    )
    tags_value = raw.get("tags")
    tags = [str(item).strip() for item in tags_value if str(item).strip()] if isinstance(tags_value, list) else []
    if kind not in tags:
        tags.append(kind)
    return {
        "kind": kind,
        "query": query,
        "title": title,
        "url": url,
        "description": description,
        "age": age,
        "evidence": evidence,
        "confidence": confidence,
        "tags": tags,
    }


def _read_findings_jsonl(path: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"failed to read findings JSONL: {path}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            findings.append(_normalize_finding(payload, line_number=line_number))
        except (json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(f"invalid findings JSONL at {path}:{line_number}: {exc}") from exc
    return findings


def _write_findings_jsonl(path: Path, findings: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in findings), encoding="utf-8")


def _guard_failed_delegated_run(run_root: Path, run_id: str) -> None:
    meta_path = run_root / "meta.json"
    existing_meta = _read_json(meta_path) if meta_path.exists() else {}
    if isinstance(existing_meta, dict) and existing_meta.get("mode") == "agent-delegated-failed":
        raise SystemExit(
            "cannot ingest observation findings for a delegated run that is already marked failed; "
            f"run_id={run_id}"
        )


def _load_query_plan_for_run(run_root: Path) -> list[dict[str, object]]:
    path = run_root / "query-plan.json"
    if not path.exists():
        return []
    payload = _read_json(path)
    if isinstance(payload, dict):
        queries = payload.get("queries", [])
        return [item for item in queries if isinstance(item, dict)] if isinstance(queries, list) else []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def plan_only(repo_root: Path, project: str) -> dict[str, object]:
    _project_exists(repo_root, project)
    profile = load_profile(repo_root, project, create=False)
    run_id = _run_id()
    started_at = _utc_now()
    project_text = _project_context_text(repo_root, project)
    queries = build_query_plan(repo_root=repo_root, project=project, project_text=project_text)
    run_root = project_observation_runs_root(repo_root, project) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    findings_path = run_root / "raw-findings.jsonl"
    state = _project_observation_state(repo_root, project)
    focus = profile.get("focus", [])
    keywords = profile.get("keywords", [])
    plan = {
        "schema_version": 1,
        "run_id": run_id,
        "project": project,
        "repo_root": str(repo_root),
        "run_root": _rel(repo_root, run_root),
        "findings_path": _rel(repo_root, findings_path),
        "queries": queries,
        "context": {
            "project_summary": project_text[:4000],
            "observation_focus": focus if isinstance(focus, list) else [],
            "keywords": keywords if isinstance(keywords, list) else [],
            "last_run_id": state.get("last_run_id"),
            "last_run_at": state.get("last_run_at"),
        },
        "next_command": (
            f"pmagent observe ingest --project {project} --run-id {run_id} "
            f"--findings {_rel(repo_root, findings_path)}"
        ),
    }
    _write_json(run_root / "query-plan.json", plan)
    meta = {
        "run_id": run_id,
        "project": project,
        "mode": "plan",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "repo_root": str(repo_root),
        "project_root": str(project_root(repo_root, project)),
        "findings_path": _rel(repo_root, findings_path),
        "query_plan": queries,
    }
    _write_json(run_root / "meta.json", meta)
    return plan


def _write_project_observations_from_findings(
    *,
    repo_root: Path,
    project: str,
    run_id: str,
    started_at: str,
    findings: list[dict[str, object]],
    query_plan: list[dict[str, object]] | None,
    recall: dict[str, object] | None,
    mode: str,
) -> dict[str, object]:
    run_root = project_observation_runs_root(repo_root, project) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    _guard_failed_delegated_run(run_root, run_id)
    if query_plan is not None and not (run_root / "query-plan.json").exists():
        _write_json(run_root / "query-plan.json", query_plan)

    raw_findings_path = run_root / "raw-findings.jsonl"
    _write_findings_jsonl(raw_findings_path, findings)

    observation_ids: list[str] = []
    files_root = project_observation_files_root(repo_root, project)
    files_root.mkdir(parents=True, exist_ok=True)
    for index, finding in enumerate(findings, start=1):
        observation_id = f"obs-{run_id}-{index:02d}"
        observation_ids.append(observation_id)
        evidence = finding.get("evidence") if isinstance(finding.get("evidence"), list) else []
        payload = {
            "schema_version": 1,
            "id": observation_id,
            "project": project,
            "created_at": _utc_now(),
            "kind": finding.get("kind", "general"),
            "title": finding.get("title", ""),
            "summary": finding.get("description", ""),
            "source_url": finding.get("url", ""),
            "evidence": evidence or [{"title": finding.get("title", ""), "url": finding.get("url", "")}],
            "tags": finding.get("tags") if isinstance(finding.get("tags"), list) else [finding.get("kind", "general")],
            "run_id": run_id,
            "age": finding.get("age", ""),
            "query": finding.get("query", ""),
            "confidence": finding.get("confidence", "medium"),
        }
        _write_json(observation_file_path(repo_root, project, observation_id), payload)

    index_payload = _project_observation_index(repo_root, project)
    existing_ids = [str(item) for item in index_payload.get("observation_ids", []) if str(item).strip()]
    existing_set = set(existing_ids)
    index_payload["observation_ids"] = [*existing_ids, *[obs_id for obs_id in observation_ids if obs_id not in existing_set]]
    _write_project_observation_index(repo_root, project, index_payload)

    state_payload = _project_observation_state(repo_root, project)
    state_payload["last_run_id"] = run_id
    state_payload["last_run_at"] = _utc_now()
    state_payload["last_run_status"] = "completed"
    state_payload["observation_count"] = len(index_payload["observation_ids"])
    _write_project_observation_state(repo_root, project, state_payload)

    section_body = json.dumps({"project": project, "new_observation_ids": observation_ids}, ensure_ascii=False, indent=2)
    collision_detected = False
    collision_reason = None
    preview = run_root / "summary-write-preview.md"
    preview.write_text(_observation_summary_preview(section_body, collision_reason), encoding="utf-8")

    meta = {
        "run_id": run_id,
        "project": project,
        "mode": mode,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "repo_root": str(repo_root),
        "project_root": str(project_root(repo_root, project)),
        "bootstrap_required": False,
        "writeback_attempted": True,
        "writeback_permitted": not collision_detected,
        "last_run_updated": True,
        "query_plan": query_plan or [],
        "findings_count": len(findings),
        "observation_ids": observation_ids,
    }
    _write_json(run_root / "meta.json", meta)

    decisions = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "bootstrap": {
            "bootstrap_required": False,
            "bootstrap_actions": [],
            "blocking_conditions": [],
        },
        "recall_escalation": recall or _default_recall(),
        "suppressed_findings": [],
        "observation_file_decisions": observation_ids,
        "writeback_decisions": {
            "summary_write_decision": "written",
            "summary_write_reason": "project observation files and index were updated",
            "collision_detected": collision_detected,
            "collision_reason": collision_reason,
            "last_run_decision": "updated",
            "last_run_reason": "live execution updates project observation state",
        },
        "runtime_non_mutation": {
            "checked_paths": [
                _rel(repo_root, project_observation_index_path(repo_root, project)),
                _rel(repo_root, project_observation_policy_path(repo_root, project)),
                _rel(repo_root, project_observation_state_path(repo_root, project)),
            ],
            "mutated_canonical_paths": [
                _rel(repo_root, project_observation_index_path(repo_root, project)),
                _rel(repo_root, project_observation_state_path(repo_root, project)),
                *[_rel(repo_root, observation_file_path(repo_root, project, obs_id)) for obs_id in observation_ids],
            ],
            "allowed_artifact_paths": [
                _rel(repo_root, run_root / "meta.json"),
                _rel(repo_root, raw_findings_path),
                _rel(repo_root, run_root / "decisions.json"),
                _rel(repo_root, run_root / "query-plan.json"),
                _rel(repo_root, preview),
                _rel(repo_root, project_observation_index_path(repo_root, project)),
                _rel(repo_root, project_observation_state_path(repo_root, project)),
                *[_rel(repo_root, observation_file_path(repo_root, project, obs_id)) for obs_id in observation_ids],
            ],
        },
    }
    _write_json(run_root / "decisions.json", decisions)
    return meta


def ingest_external(repo_root: Path, project: str, *, run_id: str, findings_path: Path) -> int:
    _project_exists(repo_root, project)
    load_profile(repo_root, project, create=False)
    resolved_findings_path = findings_path if findings_path.is_absolute() else repo_root / findings_path
    run_root = project_observation_runs_root(repo_root, project) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    _guard_failed_delegated_run(run_root, run_id)
    findings = _read_findings_jsonl(resolved_findings_path)
    query_plan = _load_query_plan_for_run(run_root)
    started_at = _utc_now()
    meta = _write_project_observations_from_findings(
        repo_root=repo_root,
        project=project,
        run_id=run_id,
        started_at=started_at,
        findings=findings,
        query_plan=query_plan,
        recall=_default_recall(),
        mode="agent-ingest",
    )
    _clear_delegation_lock(repo_root, project, run_id=run_id)
    print(f"Observation findings ingested for project={project}")
    print(f"run_id={run_id}")
    print(f"findings_count={meta['findings_count']}")
    print(f"observation_files_created={len(meta['observation_ids'])}")
    print(f"artifacts_root={run_root}")
    return 0

def _summary_bootstrap_requirements(summary_state: str) -> tuple[list[str], list[str]]:
    if summary_state == "missing_document":
        return ["missing_workspace_summary"], ["workspace summary missing"]
    if summary_state == "invalid_markers":
        return ["invalid_summary_markers"], ["workspace summary markers invalid"]
    return [], []


def _preview_reason(summary_state: str, summary_reason: str, queue_state: str, queue_reason: str) -> str | None:
    if summary_state != "valid":
        return summary_reason
    if queue_state != "valid":
        return queue_reason
    return None



def run_dry_run(repo_root: Path, workspace: str) -> int:
    _workspace_exists(repo_root, workspace)
    project = _infer_project_for_workspace(repo_root, workspace)
    _project_exists(repo_root, project)
    load_profile(repo_root, project, create=True)

    run_id = _run_id()
    started_at = _utc_now()
    summary_path = workspace_summary_path(repo_root, workspace)
    summary_status = inspect_summary(summary_path)
    queue_status = _classify_queue(repo_root, workspace)
    prd_path, prd_mode = _resolve_prd(repo_root, workspace)

    bootstrap_actions = list(queue_status.bootstrap_actions)
    blocking_conditions = list(queue_status.blocking_conditions)
    summary_actions, summary_conditions = _summary_bootstrap_requirements(summary_status.state)
    bootstrap_actions.extend(summary_actions)
    blocking_conditions.extend(summary_conditions)
    bootstrap_required = bool(bootstrap_actions)

    run_root = project_observation_runs_root(repo_root, project) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    raw_findings = run_root / 'raw-findings.jsonl'
    raw_findings.write_text('', encoding='utf-8')

    preview_reason = _preview_reason(summary_status.state, summary_status.reason, queue_status.state, queue_status.reason)
    preview = run_root / 'summary-write-preview.md'
    preview.write_text(_observation_summary_preview('{}', preview_reason), encoding='utf-8')

    checked_paths = [_rel(repo_root, summary_path), _rel(repo_root, queue_summary_path(repo_root, workspace))]
    if prd_path:
        checked_paths.append(_rel(repo_root, prd_path))

    meta = {
        'run_id': run_id,
        'workspace': workspace,
        'project': project,
        'mode': 'dry-run',
        'started_at': started_at,
        'completed_at': _utc_now(),
        'repo_root': str(repo_root),
        'workspace_root': str(workspace_root(repo_root, workspace)),
        'resolved_prd_path': _rel(repo_root, prd_path),
        'prd_resolution_mode': prd_mode,
        'summary_state': summary_status.state,
        'queue_state': queue_status.state,
        'bootstrap_required': bootstrap_required,
        'writeback_attempted': False,
        'writeback_permitted': False,
        'last_run_updated': False,
    }
    _write_json(run_root / 'meta.json', meta)
    decisions = {
        'schema_version': 1,
        'run_id': run_id,
        'mode': 'dry-run',
        'bootstrap': {
            'bootstrap_required': bootstrap_required,
            'bootstrap_actions': bootstrap_actions,
            'blocking_conditions': blocking_conditions,
        },
        'recall_escalation': {
            'considered': False, 'fired': False, 'trigger_reasons': [], 'caps_overridden': False, 'override_reason': None, 'additional_reads': []
        },
        'suppressed_findings': [],
        'observation_file_decisions': [],
        'writeback_decisions': {
            'summary_write_decision': 'preview_only' if summary_status.state == 'valid' else 'blocked',
            'summary_write_reason': preview_reason or 'dry-run preview generated',
            'collision_detected': False,
            'collision_reason': None,
            'last_run_decision': 'unchanged',
            'last_run_reason': 'dry-run must not mutate project observation state',
        },
        'runtime_non_mutation': {
            'checked_paths': checked_paths,
            'mutated_canonical_paths': [],
            'allowed_artifact_paths': [
                _rel(repo_root, run_root / 'meta.json'),
                _rel(repo_root, raw_findings),
                _rel(repo_root, run_root / 'decisions.json'),
                _rel(repo_root, preview),
            ],
        },
    }
    _write_json(run_root / 'decisions.json', decisions)

    print(f'Dry-run observation artifacts created for workspace={workspace}')
    print(f'run_id={run_id}')
    print(f'summary_state={summary_status.state}')
    print(f'queue_state={queue_status.state}')
    print(f'bootstrap_required={bootstrap_required}')
    print(f'artifacts_root={run_root}')
    return 0

def _render_agent_handoff(plan: dict[str, object]) -> str:
    payload = {
        "action": "agent_handoff_required",
        "skill": "run-observation",
        "plan": plan,
        "ingest_command": plan.get("next_command"),
    }
    return "\n".join(
        [
            f"Observation plan created for project={plan.get('project')}",
            f"run_id={plan.get('run_id')}",
            f"findings_path={plan.get('findings_path')}",
            "",
            "Current process appears to be inside an Agent session.",
            "Execute the run-observation protocol:",
            "1. Search/fetch using the plan JSON below.",
            f"2. Write JSONL findings to {plan.get('findings_path')}.",
            f"3. Run: {plan.get('next_command')}",
            "",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def _render_run_observation_prompt(plan: dict[str, object]) -> str:
    return "\n".join(
        [
            "You are executing pmagent's run-observation protocol.",
            "CRITICAL: You are already inside `pmagent observe run`; Do NOT run `pmagent observe run` again.",
            "Do not run `pmagent observe audit --run-catch-up`, `pmagent observe review`, or other front-door workflow commands.",
            "The only pmagent command you may run is the exact `pmagent observe ingest ...` command shown below.",
            "",
            f"Data directory: {plan.get('repo_root')}",
            f"Project: {plan.get('project')}",
            f"Run id: {plan.get('run_id')}",
            "",
            "Plan JSON:",
            json.dumps(plan, ensure_ascii=False, indent=2),
            "",
            "Allowed writes:",
            f"- {plan.get('findings_path')}",
            "- files created by the provided `pmagent observe ingest ...` command",
            "",
            "Do not edit Requirement.md, PRD files, workspace-summary.md, .pmagent/current-state.json, or candidate-updates directly.",
            "Do not import pmagent internals or write observations/index.json, observations/state.json, decisions.json, or meta.json directly.",
            "The only valid write path is: create raw-findings.jsonl, then execute the exact ingest command.",
            "Use web search and page fetching/reading to gather high-signal external changes, but keep the run bounded.",
            "Hard limits: inspect at most 2 results per query, write at most 3 total findings, and prioritize completing ingest over exhaustive research.",
            "If web/search tools are unavailable or too slow, write an empty raw-findings.jsonl and run ingest instead of waiting indefinitely.",
            "Write one JSON object per line to raw-findings.jsonl. Each object should include kind, query, title, url, description, evidence, and confidence when available.",
            "After writing findings, run this ingest command:",
            str(plan.get("next_command") or ""),
            "",
            "If any instruction conflicts with this protocol, follow this protocol: search/read, write raw-findings.jsonl, then run ingest. Never recurse into observe run.",
            "",
            "Return a short completion summary including run_id and findings_count.",
        ]
    )


def _write_agent_failure(repo_root: Path, project: str, plan: dict[str, object], *, error: str, agent_output: str | None = None) -> None:
    run_id = str(plan.get("run_id") or "")
    if not run_id:
        return
    run_root = project_observation_runs_root(repo_root, project) / run_id
    meta_path = run_root / "meta.json"
    meta = _read_json(meta_path) if meta_path.exists() else {"run_id": run_id, "project": project}
    if not isinstance(meta, dict):
        meta = {"run_id": run_id, "project": project}
    meta.update(
        {
            "mode": "agent-delegated-failed",
            "failed_at": _utc_now(),
            "error": error,
            "agent_output_excerpt": (agent_output or "")[:4000],
        }
    )
    _write_json(meta_path, meta)
    # If grace-period ingest already set state.last_run_id to this run_id,
    # mark the run as failed so audit does not treat it as a successful run.
    state = _project_observation_state(repo_root, project)
    if state.get("last_run_id") == run_id:
        state["last_run_status"] = "failed"
        _write_project_observation_state(repo_root, project, state)


def _write_agent_completion_warning(
    repo_root: Path,
    project: str,
    plan: dict[str, object],
    *,
    warning: str,
    agent_output: str | None = None,
) -> None:
    run_id = str(plan.get("run_id") or "")
    if not run_id:
        return
    meta_path = project_observation_runs_root(repo_root, project) / run_id / "meta.json"
    meta = _read_json(meta_path) if meta_path.exists() else {"run_id": run_id, "project": project}
    if not isinstance(meta, dict):
        meta = {"run_id": run_id, "project": project}
    meta.update(
        {
            "executor_warning": warning,
            "completion_observed_after_executor_error": True,
        }
    )
    if agent_output:
        meta["agent_output_excerpt"] = agent_output[:4000]
    _write_json(meta_path, meta)


def _verify_agent_observation_completed(repo_root: Path, project: str, plan: dict[str, object]) -> dict[str, object]:
    run_id = str(plan.get("run_id") or "")
    if not run_id:
        raise SystemExit("agent observation verification failed: missing run_id in plan")
    run_root = project_observation_runs_root(repo_root, project) / run_id
    required = [run_root / "raw-findings.jsonl", run_root / "meta.json", run_root / "decisions.json"]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise SystemExit("agent observation verification failed; missing artifacts: " + ", ".join(str(path) for path in missing))
    meta = _read_json(run_root / "meta.json")
    if not isinstance(meta, dict):
        raise SystemExit("agent observation verification failed: meta.json is not a JSON object")
    if meta.get("mode") == "agent-delegated-failed":
        raise SystemExit("agent observation verification failed: run is already marked failed")
    state = _project_observation_state(repo_root, project)
    if state.get("last_run_id") != run_id:
        raise SystemExit(
            "agent observation verification failed: "
            f"state.last_run_id={state.get('last_run_id')} does not match run_id={run_id}"
        )
    observation_ids = [str(item) for item in meta.get("observation_ids", []) if str(item).strip()] if isinstance(meta.get("observation_ids"), list) else []
    if observation_ids:
        index = _project_observation_index(repo_root, project)
        index_ids = {str(item) for item in index.get("observation_ids", []) if str(item).strip()} if isinstance(index.get("observation_ids"), list) else set()
        missing_ids = [item for item in observation_ids if item not in index_ids]
        if missing_ids:
            raise SystemExit(
                "agent observation verification failed: index.json is missing observation ids: "
                + ", ".join(missing_ids)
            )
    return meta


DEFAULT_OBSERVATION_AGENT_TIMEOUT_SECONDS = 150.0
DEFAULT_OBSERVATION_TIMEOUT_GRACE_SECONDS = 45.0


def _observation_timeout_seconds(explicit: float | None) -> float:
    if explicit is not None and explicit > 0:
        return float(explicit)
    raw = os.environ.get("PMAGENT_OBSERVATION_AGENT_TIMEOUT", "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_OBSERVATION_AGENT_TIMEOUT_SECONDS


def _observation_timeout_grace_seconds() -> float:
    raw = os.environ.get("PMAGENT_OBSERVATION_TIMEOUT_GRACE", "").strip()
    if raw:
        try:
            value = float(raw)
            if value >= 0:
                return value
        except ValueError:
            pass
    return DEFAULT_OBSERVATION_TIMEOUT_GRACE_SECONDS


def _try_parent_ingest_after_executor_error(
    repo_root: Path,
    project: str,
    plan: dict[str, object],
    *,
    warning: str,
    agent_output: str | None = None,
) -> bool:
    """Recover when an external agent produced raw findings but timed out before ingest."""

    run_id = str(plan.get("run_id") or "")
    raw_findings = repo_root / str(plan.get("findings_path") or "")
    if not run_id or not str(plan.get("findings_path") or ""):
        return False

    deadline = time.time() + _observation_timeout_grace_seconds()
    while True:
        try:
            raw_ready = raw_findings.exists() and raw_findings.stat().st_size > 0
        except OSError:
            raw_ready = False
        if raw_ready:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    ingest_external(repo_root, project, run_id=run_id, findings_path=raw_findings)
                _verify_agent_observation_completed(repo_root, project, plan)
                _write_agent_completion_warning(
                    repo_root,
                    project,
                    plan,
                    warning=warning,
                    agent_output=agent_output,
                )
                meta_path = project_observation_runs_root(repo_root, project) / run_id / "meta.json"
                meta = _read_json(meta_path)
                if isinstance(meta, dict):
                    meta["parent_ingested_after_executor_error"] = True
                    _write_json(meta_path, meta)
                return True
            except SystemExit:
                pass
            except Exception:  # noqa: BLE001
                pass
        if time.time() >= deadline:
            return False
        time.sleep(1.0)


def _delegation_lock_path(repo_root: Path, project: str) -> Path:
    return project_observation_root(repo_root, project) / "delegated-run.lock.json"


def _clear_delegation_lock(repo_root: Path, project: str, *, run_id: str | None = None) -> None:
    lock_path = _delegation_lock_path(repo_root, project)
    if not lock_path.exists():
        return
    if run_id:
        payload = _read_json(lock_path)
        if isinstance(payload, dict) and payload.get("run_id") not in {None, run_id}:
            return
    lock_path.unlink(missing_ok=True)


def _active_delegation_lock(repo_root: Path, project: str, *, timeout_seconds: float) -> dict[str, object] | None:
    lock_path = _delegation_lock_path(repo_root, project)
    if not lock_path.exists():
        return None
    stale_after = max(timeout_seconds * 2, 600.0)
    try:
        age = datetime.now(timezone.utc).timestamp() - lock_path.stat().st_mtime
    except OSError:
        age = 0.0
    if age > stale_after:
        lock_path.unlink(missing_ok=True)
        return None
    payload = _read_json(lock_path)
    return payload if isinstance(payload, dict) else {"path": str(lock_path)}


def _write_delegation_lock(repo_root: Path, project: str, plan: dict[str, object], *, timeout_seconds: float) -> None:
    lock_path = _delegation_lock_path(repo_root, project)
    _write_json(
        lock_path,
        {
            "schema_version": 1,
            "project": project,
            "run_id": plan.get("run_id"),
            "created_at": _utc_now(),
            "timeout_seconds": timeout_seconds,
            "findings_path": plan.get("findings_path"),
            "next_command": plan.get("next_command"),
            "reason": "observation delegation in progress; nested observe run is blocked",
        },
    )


def _render_lock_error(lock: dict[str, object]) -> str:
    run_id = str(lock.get("run_id") or "unknown")
    next_command = str(lock.get("next_command") or "pmagent observe ingest ...")
    return (
        "nested `pmagent observe run` is blocked because an observation delegation is already active "
        f"for run_id={run_id}. Write raw-findings.jsonl and run `{next_command}` instead."
    )


def run_live(repo_root: Path, project: str, *, as_json: bool = False, timeout_seconds: float | None = None) -> int:
    _project_exists(repo_root, project)
    load_profile(repo_root, project, create=False)
    resolved_timeout = _observation_timeout_seconds(timeout_seconds)
    if os.environ.get("PMAGENT_OBSERVATION_DELEGATED") == "1":
        raise SystemExit(
            "nested `pmagent observe run` is not allowed during delegated observation; "
            "write raw-findings.jsonl and run `pmagent observe ingest` instead."
        )
    active_lock = _active_delegation_lock(repo_root, project, timeout_seconds=resolved_timeout)
    if active_lock is not None:
        raise SystemExit(_render_lock_error(active_lock))
    plan = plan_only(repo_root, project)
    _write_delegation_lock(repo_root, project, plan, timeout_seconds=resolved_timeout)

    if is_inside_agent():
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "handoff_required",
                        "action": "agent_handoff_required",
                        "project": project,
                        "run_id": plan.get("run_id"),
                        "findings_path": plan.get("findings_path"),
                        "ingest_command": plan.get("next_command"),
                        "plan": plan,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(_render_agent_handoff(plan))
        return 0

    agent_output: str | None = None
    executor_warning: str | None = None
    try:
        backend = resolve_available_backend()
        delegated_env = {
            "PMAGENT_OBSERVATION_DELEGATED": "1",
            "PMAGENT_AGENT_MODE": "observation",
            "PMAGENT_DATA_DIR": str(repo_root),
            "PMAGENT_OBSERVATION_RUN_ID": str(plan.get("run_id") or ""),
        }
        previous_env = {key: os.environ.get(key) for key in delegated_env}
        os.environ.update(delegated_env)
        try:
            result = run_executor(
                backend,
                _render_run_observation_prompt(plan),
                cwd=repo_root,
                timeout_seconds=resolved_timeout,
                trust_all_tools=True,
            )
        finally:
            for key, previous in previous_env.items():
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous
        agent_output = result.content
        _verify_agent_observation_completed(repo_root, project, plan)
    except ExecutorError as exc:
        verification_error: SystemExit | None = None
        try:
            _verify_agent_observation_completed(repo_root, project, plan)
        except SystemExit as verify_exc:
            verification_error = verify_exc
        if verification_error is None:
            executor_warning = str(exc)
            _write_agent_completion_warning(
                repo_root,
                project,
                plan,
                warning=executor_warning,
                agent_output=agent_output,
            )
        else:
            if _try_parent_ingest_after_executor_error(
                repo_root,
                project,
                plan,
                warning=str(exc),
                agent_output=agent_output,
            ):
                executor_warning = str(exc)
            else:
                _write_agent_failure(
                    repo_root,
                    project,
                    plan,
                    error=f"{exc}; {verification_error}",
                    agent_output=agent_output,
                )
                _clear_delegation_lock(repo_root, project, run_id=str(plan.get("run_id") or ""))
                raise SystemExit(str(exc)) from exc
    except SystemExit as exc:
        _write_agent_failure(repo_root, project, plan, error=str(exc), agent_output=agent_output)
        _clear_delegation_lock(repo_root, project, run_id=str(plan.get("run_id") or ""))
        raise

    run_id = str(plan.get("run_id"))
    _clear_delegation_lock(repo_root, project, run_id=run_id)
    run_root = project_observation_runs_root(repo_root, project) / run_id
    meta = _read_json(run_root / "meta.json")
    findings_count = meta.get("findings_count", 0) if isinstance(meta, dict) else 0
    observation_ids = meta.get("observation_ids", []) if isinstance(meta, dict) else []
    payload = {
        "status": "completed",
        "project": project,
        "run_id": run_id,
        "findings_count": findings_count,
        "observation_files_created": len(observation_ids) if isinstance(observation_ids, list) else 0,
        "artifacts_root": str(run_root).replace("\\", "/"),
    }
    if executor_warning:
        payload["executor_warning"] = executor_warning
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Agent-delegated observation completed for project={project}")
        if executor_warning:
            print(f"executor_warning={executor_warning}")
        print(f"run_id={run_id}")
        print(f"findings_count={findings_count}")
        print(f"observation_files_created={payload['observation_files_created']}")
        print(f"artifacts_root={run_root}")
    return 0
