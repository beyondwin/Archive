# State And Logging

This document explains the project-local execution state, source snapshots, and
user-local learning log.

## State Files

The canonical state file for one run is:

```text
.codex-orchestrator/runs/<run_id>/state.json
```

The root file:

```text
.codex-orchestrator/state.json
```

is compatibility-only. It may be a latest-state copy or pointer, but it is not
the source of truth when multiple runs exist.

The state schema is documented in
[../references/state-schema.md](../references/state-schema.md) and checked by:

```bash
python3 scripts/validate_state.py .codex-orchestrator/runs/<run_id>/state.json
```

## Run Identity

Execution runs use a `run_id` shaped like:

```text
20260513T142233Z-archive-codex-example-7e884a0-a1b2c3
```

The id includes UTC time, repo slug, branch slug, head hash, and a random
suffix. Timestamp alone is not enough because multiple executors can start in
the same repository at nearly the same time.

## Context Snapshot

Execution modes write:

```text
.codex-orchestrator/runs/<run_id>/context.json
```

The helper is:

```bash
python3 scripts/build_context_snapshot.py \
  --repo-root "$WORKTREE_ABS" \
  --run-id "$RUN_ID" \
  --plan "$PLAN_REL" \
  --spec "${SPEC_REL:-}" \
  --docs "${DOCS_REL:-}" \
  --output "$RUN_DIR/context.json"
```

The snapshot records:

- `schema_version`
- `run_id`
- `workspace`
- `sources[]` with `role`, repo-relative `path`, and SHA-256
- `basis_hash`, derived from the sorted source list

The state file stores:

- `context_snapshot_path`
- `context_basis_hash`

This makes resume and handoff grounded in the actual plan/spec/docs used at
execution start rather than implicit chat memory.

## Lifecycle Outcome

`current_phase` is internal progress. `lifecycle_outcome` is the terminal
handoff result.

Valid outcomes:

- `finished`
- `blocked`
- `failed`
- `userinterlude`
- `askuserQuestion`

`finished` requires a passing `completion_audit`. Non-success outcomes require
a concrete `handoff_reason`.

## Completion Audit

Successful terminal state must include:

```json
{
  "lifecycle_outcome": "finished",
  "handoff_reason": "",
  "completion_audit": {
    "passed": true,
    "prompt_to_artifact_checklist": [
      "Task 0 changed docs/example.md as requested"
    ],
    "verification_evidence": [
      {"command": "pytest tests/example_test.py", "status": "passed"}
    ],
    "open_gaps": [],
    "residual_risk": []
  }
}
```

The checklist maps prompt/plan requirements to artifacts. Verification evidence
records commands or honest substitutes. This prevents a run from claiming
completion solely because a narrow command passed.

## Learning Log

The learning log is user-local and cross-repository:

```text
~/.codex/learning/kws-codex-plan-executor/
  index.jsonl
  runs/<YYYY-MM-DD>/<run_id>/
    meta.json
    events.jsonl
    final.json
```

It is for improving the executor over time. It is not the resume source of
truth and does not replace `.codex-orchestrator/runs/<run_id>/state.json`.

Only `interactive` and `headless` are logging modes. `prompt` and `handoff` do
not log events, though exported prompts must carry the same logging contract for
future execution.

## Learning Helper Lifecycle

Initialize:

```bash
python3 scripts/append_learning_event.py init-run \
  --repo-root "$WORKTREE_ABS" \
  --repo-name "$REPO_NAME" \
  --branch "$BRANCH" \
  --head "$HEAD_SHA" \
  --plan-path "$PLAN_REL" \
  --spec-path "${SPEC_REL:-}" \
  --mode "$MODE"
```

Append a notable event:

```bash
python3 scripts/append_learning_event.py append \
  --run-id "$RUN_ID" \
  --event-json /tmp/kws-codex-plan-executor-event.json \
  --repo-root "$WORKTREE_ABS"
```

Close:

```bash
python3 scripts/append_learning_event.py close-run \
  --run-id "$RUN_ID" \
  --outcome success
```

Valid close outcomes are `success`, `blocked`, `error`, and `unknown`.

## What To Log

Log only notable boundaries:

- `blocker`
- `error`
- `verification_failure`
- `recurring_issue`
- `user_correction`
- `successful_workaround`
- `completion_learning`

Do not log routine task starts, routine completions, ordinary success, full
conversation transcripts, or long raw logs.

## Privacy Rules

Learning events must be redacted and compact.

Allowed:

- repository name
- branch name
- relative plan path
- task id and phase
- relative file paths
- non-secret command names and arguments
- short failure excerpts
- root-cause summary
- proposed skill improvement target

Forbidden:

- secrets, tokens, API keys, cookies, credentials, private keys
- authorization headers
- absolute home paths
- full conversation transcripts
- long raw logs
- bulky file contents
- unrelated user files or unrelated process details

`append_learning_event.py` validates required fields, event enums, run identity,
secret-like strings, and project-local `run_dir`/`state_path` values.

Learning-log failure must not fail the user's primary implementation task. Note
the logging failure briefly, then continue from the execution state.
