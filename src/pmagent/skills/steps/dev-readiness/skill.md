# Dev Readiness

External Agent protocol for turning a stable PRD into implementation-facing PM Data artifacts and vertical slices.

## Role

You, the external Agent, perform the product-to-engineering judgment. PMAgent CLI must not infer slice semantics or generate placeholder slices for you.

## Read

- `Requirement.md`
- `prd/current.md` or the latest `prd/*.md`
- `decisions/`
- `research/`
- `workspace-summary.md`
- existing `dev/` artifacts, if any

## Write

- `dev/dev-plan.md`
- `dev/codebases.json`
- `dev/slices/SL-*.md`
- `dev/qa/` only when QA strategy is already concrete
- `workspace-summary.md` status/navigation updates

## Output Contract

`dev/dev-plan.md` must include:

- product goal and source PRD
- implementation boundaries and non-goals
- domain language that engineering must preserve
- module risks and integration risks
- test strategy
- slice order
- first AFK slice
- HITL questions, if any

Each `dev/slices/SL-*.md` must include:

- goal and user story
- what to build
- acceptance criteria
- public behavior tests
- codebase id
- base commit
- branch and worktree path, or an explicit reason they are not created yet
- owned paths and shared paths
- commands
- out-of-scope work

## Rules

- A slice must be user-visible, deliverable, and verifiable end to end; do not split by database/API/frontend layers.
- Register codebases in `dev/codebases.json`; PMAgent stores links and evidence, not source code.
- Do not ask the PMAgent CLI to generate dev readiness output. Use `pmagent dev slices --workspace <workspace> --json` only to inspect existing slice artifacts.
- After a development Agent executes a slice, record evidence with `pmagent dev run-record --slice <slice-id> --command "<command>" --status passed|failed|blocked`.
- Lesson candidates come from the development Agent at execution time and stay reviewable; they do not auto-promote to permanent rules.
