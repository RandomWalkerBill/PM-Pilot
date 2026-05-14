# Run Observation

## Purpose

Use the host Agent's web search and page-reading capability to execute a pmagent Observation plan, then hand validated raw findings back to `pmagent observe ingest`.

This skill is an execution protocol for Observation retrieval. It is not a top-level mode and it must not bypass candidate review or maintenance governance.

## Inputs

- Project name
- Plan JSON from `pmagent observe plan --project <project> --json` or from `pmagent observe run`
- Run root under `observations/<project>/runs/<run_id>/`
- Findings path, normally `observations/<project>/runs/<run_id>/raw-findings.jsonl`
- Ingest command, normally `pmagent observe ingest --project <project> --run-id <run_id> --findings <path>`

## Reads

- `observations/<project>/runs/<run_id>/query-plan.json`
- `projects/<project>/...`
- Workspace summaries only as context when needed

## Writes

Direct writes are limited to:

- `observations/<project>/runs/<run_id>/raw-findings.jsonl`

All canonical Observation mutations must happen through:

```bash
pmagent observe ingest --project <project> --run-id <run_id> --findings <path>
```

## Must not write directly

- `Requirement.md`
- `prd/**`
- `candidate-updates/**`
- `workspace-summary.md`
- `.pmagent/current-state.json`
- `observations/<project>/index.json`
- `observations/<project>/state.json`

## Raw findings JSONL format

Write one JSON object per line. Minimum useful shape:

```json
{
  "kind": "market",
  "query": "search query used",
  "title": "Source or finding title",
  "url": "https://example.com/source",
  "description": "Short grounded summary of the signal and why it may matter.",
  "age": "2d",
  "evidence": [
    {
      "title": "Source title",
      "url": "https://example.com/source",
      "quote_or_summary": "Short evidence summary grounded in the fetched page."
    }
  ],
  "confidence": "medium"
}
```

Rules:

- `title` or `description` must be non-empty.
- URLs must be `http` or `https` when present.
- `confidence` should be `low`, `medium`, or `high`.
- Prefer fewer high-signal findings over many weak snippets.

## Procedure

1. Read the plan JSON and identify `run_id`, `project`, `queries`, `findings_path`, and `next_command`.
2. Search using the provided query hints.
3. Fetch/read high-relevance pages before writing findings.
4. Add follow-up searches when the first results are ambiguous or low-recall.
5. Write `raw-findings.jsonl` at the plan's `findings_path`.
6. Run the plan's `next_command` exactly, unless paths need shell escaping for the host environment.
7. Report `run_id`, `findings_count`, and any important gaps.

Do **not** run `pmagent observe run` from inside this skill. That command is the parent dispatcher and recursively launching it can create process storms. Do **not** run `pmagent observe audit --run-catch-up` either; this bounded skill only performs retrieval plus `observe ingest`.

## Output expectation

End with a short summary:

- `run_id`
- `findings_count`
- ingest command status
- notable skipped/low-confidence areas
