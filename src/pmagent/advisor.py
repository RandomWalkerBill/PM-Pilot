from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CARD_FIELD_NAMES: dict[str, str] = {
    "card_id": "card_id",
    "source_type": "source_type",
    "source_ref": "source_ref",
    "target_project": "target_project",
    "target_workspace": "target_workspace",
    "title": "title",
    "body": "body",
    "evidence": "evidence",
    "suggested_action": "suggested_action",
    "urgency": "urgency",
    "status": "status",
    "created_at": "created_at",
    "reviewed_at": "reviewed_at",
    "review_note": "review_note",
    "expires_at": "expires_at",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


CARD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PMAgent Candidate Card",
    "type": "object",
    "required": ["card_id", "source_type", "source_ref", "target", "suggestion", "lifecycle"],
    "properties": {
        "card_id": {"type": "string"},
        "source_type": {
            "type": "string",
            "enum": ["external_observation", "behavior_analysis", "cross_project", "efficiency", "consistency"],
        },
        "source_ref": {"type": "string"},
        "target": {
            "type": "object",
            "required": ["project", "workspace"],
            "properties": {"project": {"type": "string"}, "workspace": {"type": "string"}},
        },
        "suggestion": {
            "type": "object",
            "required": ["title", "body", "evidence", "suggested_action", "urgency"],
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "evidence": {"type": "string"},
                "suggested_action": {"type": "string"},
                "urgency": {"type": "string", "enum": ["high", "normal", "low"]},
            },
        },
        "lifecycle": {
            "type": "object",
            "required": ["status", "created_at"],
            "properties": {
                "status": {"type": "string", "enum": ["inbox", "accepted", "rejected", "snoozed", "expired"]},
                "created_at": {"type": "string"},
                "reviewed_at": {"type": ["string", "null"]},
                "review_note": {"type": ["string", "null"]},
                "expires_at": {"type": ["string", "null"]},
            },
        },
    },
}


def _protocol_markdown(*, project: str | None, workspace: str | None) -> str:
    return "\n".join(
        [
            "# OpenClaw Advisor Protocol",
            "",
            f"- Generated at: `{_utc_now()}`",
            f"- Project: `{project or '<project>'}`",
            f"- Workspace: `{workspace or '<workspace>'}`",
            "",
            "## Contract",
            "",
            "OpenClaw is the advisor runtime. `pmagent` does not deploy or trigger OpenClaw.",
            "`pmagent infra protocol` writes this contract and is the only CLI entrypoint for PM Infra protocol generation.",
            "",
            "## Data Directory Boundary",
            "",
            "- The PM Data directory must be created by `pmagent init --dir <data_dir>`.",
            "- That PM Data directory is the Git/GitHub repository OpenClaw reads.",
            "- The `pmagent` source checkout is only the CLI/tool repository and must not be used as the PM Data Git repository.",
            "- OpenClaw must clone or pull the PM Data GitHub repository, not the `pmagent` source repository.",
            "",
            "OpenClaw responsibilities:",
            "",
            "1. Clone or pull the GitHub PM Data repository configured for this PM Data directory.",
            "2. Read PM Data from Git only: `projects/`, `workspaces/`, `.pmagent`, `observations/`, and `candidate-updates/`.",
            "3. Analyze process, behavior, efficiency, consistency, cross-project reuse, and external-observation context.",
            "4. Write each suggestion as one row in the Project Cards Base.",
            "5. On the next run, read card status/review_note from Base and use it for calibration.",
            "",
            "`pmagent` responsibilities:",
            "",
            "1. Push the PM Data directory to GitHub.",
            "2. Publish human-readable Markdown artifacts to Feishu Wiki.",
            "3. Pull `status=inbox` rows from Feishu Base into `candidate-updates/inbox`.",
            "4. Let the user review cards through the existing candidate-review flow.",
            "5. Write `accepted` / `rejected` / `snoozed`, `reviewed_at`, and `review_note` back to Base.",
            "",
            "## Cards Base Fields",
            "",
            "The JSON schema is the canonical exchange envelope. Feishu Base rows use the flat field names below.",
            "",
            "| Field | Meaning |",
            "|---|---|",
            *[f"| `{field}` | Candidate Card `{key}` |" for key, field in CARD_FIELD_NAMES.items()],
            "",
            "## Required Row Semantics",
            "",
            "- `status` must be `inbox` for cards that PMAgent should pull.",
            "- `target_workspace` must exactly match the PMAgent workspace id.",
            "- `card_id` must be stable and unique within the Project Cards Base.",
            "- `suggested_action` must be advisory, not executable code.",
            "- `evidence` should name Git paths and, where possible, commit hashes or file hashes.",
            "",
            "## Example Card JSON",
            "",
            "```json",
            json.dumps(
                {
                    "card_id": "advisor-20260502-001",
                    "source_type": "efficiency",
                    "source_ref": "openclaw-run-20260502",
                    "target": {"project": project or "demo-project", "workspace": workspace or "demo-workspace"},
                    "suggestion": {
                        "title": "Workspace has been idle in clarifying",
                        "body": "The workspace has stayed in clarifying longer than its recent project baseline.",
                        "evidence": "workspaces/demo-workspace/.pmagent/current-state.json and git commit timeline",
                        "suggested_action": "Review scope blockers and either answer the open question or move to PRD drafting.",
                        "urgency": "normal",
                    },
                    "lifecycle": {
                        "status": "inbox",
                        "created_at": _utc_now(),
                        "reviewed_at": None,
                        "review_note": None,
                        "expires_at": None,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
        ]
    )


def write_protocol(data_dir: Path, *, project: str | None = None, workspace: str | None = None) -> dict[str, str]:
    config_root = data_dir / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    protocol_path = config_root / "openclaw-advisor-protocol.md"
    schema_path = config_root / "candidate-card.schema.json"
    protocol_path.write_text(_protocol_markdown(project=project, workspace=workspace), encoding="utf-8")
    schema_path.write_text(json.dumps(CARD_SCHEMA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "protocol_path": protocol_path.relative_to(data_dir).as_posix(),
        "schema_path": schema_path.relative_to(data_dir).as_posix(),
    }
