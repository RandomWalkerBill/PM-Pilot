# Dev Run Record

Record run evidence for one vertical slice:

- command run
- pass/fail/blocked status
- run folder under `dev/runs/<slice>/`
- optional lesson candidate under `dev/lessons/lesson-candidates.jsonl`
- review accepted lesson candidates into `dev/lessons/accepted-lessons.md`

Run:

```text
pmagent dev run-record --slice SL-001 --command "<test command>" --status passed
pmagent dev lesson-review --lesson-id SL-001-run-YYYYMMDDTHHMMSS-001 --status accepted --note "<why>"
```
