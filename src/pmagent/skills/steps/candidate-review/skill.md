# Candidate Review

## Purpose

Review unread project observation items before mainline work resumes.

## When to use

- Session resume / continue detects unread project observation items
- `pmagent observe audit` reports unread observation ids for the active workspace
- The user explicitly asks to review pending observation items

## Not a top-level mode

`candidate-review` is a **resume-time review step**, not a mode and not a primary phase.
It temporarily pauses the current mainline step, processes pending observation items, then hands
control back to the main workflow.

## Reads

- `workspaces/<workspace>/workspace-summary.md`
- `workspaces/<workspace>/.pmagent/current-state.json`
- `observations/<project>/index.json`

## Writes

- `candidate-updates/accepted/`
- `candidate-updates/rejected/`
- `candidate-updates/snoozed/`
- `candidate-updates/queue-summary.json`
- `workspace-summary.md`
- `.pmagent/current-state.json`

## Procedure

1. Run / read `pmagent observe audit --workspace <workspace> --run-catch-up --json`
2. Surface backlog notice to the user before continuing mainline work
3. Review unread observation items with the user
4. Accept / reject / snooze only after explicit user confirmation
5. At the end of the review round, if a cadence recommendation is present, explicitly ask the user whether cadence should change
6. Return to the main workflow

## Cadence policy

- Decide cadence changes **after the review round**, not per-card
- Only call `pmagent observe set-cadence ... --confirm-cadence` after the user agrees
