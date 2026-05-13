# Learning Log

Execution-only learning events from `kws-claude-multi-agent-executor`. Records
notable boundaries from a real orchestrator run so the skill itself can be
improved over time. **This is not the resume source of truth** — that is
`state.json` inside the worktree. The learning log lives outside any project
repository because the learning target is the skill, not a specific repo.

## Storage layout

Per-run sharded directory under user-local storage:

```text
~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/
├── meta.json          # one per run; written by init-run, updated by close-run
└── events.jsonl       # zero or more JSON lines; one per notable boundary
```

This sits alongside Claude Code's other user-local data (`~/.claude/projects/`,
`~/.claude/tasks/`, `~/.claude/sessions/`).

The `run_id` format:

```text
<UTC-compact-timestamp>-<session_short>-<pid>
example: 20260513T143321Z-188042f4-48211
```

- `<UTC-compact-timestamp>` = `YYYYMMDDTHHMMSSZ`
- `<session_short>` = first 8 hex chars of `$CLAUDE_SESSION_ID`, or `nosession`
- `<pid>` = orchestrator process id

Concurrent runs in the same repository write to distinct run directories —
no file locking required.

## Single-writer contract

**The orchestrator is the only process that invokes the helper.** Sub-agents
do **NOT** call the helper directly. They prepare event candidate JSON files
under:

```text
<worktree>/.orchestrator/learning_events/<task_id>-<role>.json
```

The orchestrator reads candidate files, validates them with the helper's
`append` subcommand, and is responsible for the entire learning-log lifecycle.

This contract has two consequences:

1. **No env propagation puzzle** — `MAE_LEARNING_RUN_ID` only needs to flow
   to `claude -p` subprocesses the orchestrator spawns itself (Plan Reviewer
   / Verifier / Docs Updater / Resume Chain), and even those subprocesses
   never call the helper.
2. **Atomic single-writer per run** — no `flock`, no oversized-line races.

## Event types

Record only notable boundaries. Do not record routine task starts, routine
task completions, or ordinary success.

| Event type | Trigger |
|---|---|
| `blocker` | Plan/spec/baseline missing or invalid; dirty worktree blocking Phase 0; ambiguous Resume Chain state |
| `error` | Skill procedure failure independent of project code (state.json corrupt, worktree creation failed, hook denied) |
| `verification_failure` | Verifier returns FAIL (per-task MID/HIGH or batch LOW) |
| `reviewer_warn_or_fail` | Combined Reviewer tier WARN or FAIL (SPEC<0.85 OR QUALITY<0.75) |
| `escalation` | Sub-agent returns ESCALATE (see `references/escalation-playbook.md` for category-to-severity mapping) |
| `recurring_issue` | The same `ISSUE_KEY` appears again after a retry |
| `user_correction` | The user corrects scope, allowed files, assumptions, or direction |
| `parallel_dispatch_failure` | A P2 wave's sub-worktree dispatch fails or merge-back conflicts |
| `successful_workaround` | A root-cause-based recovery reveals a reusable executor improvement |
| `completion_learning` | Final completion produces an actionable executor-improvement observation (NOT routine completion) |

## meta.json schema

Written once by `init-run`, updated by `close-run`. Example:

```json
{
  "schema_version": "1",
  "run_id": "20260513T143321Z-188042f4-48211",
  "skill": "kws-claude-multi-agent-executor",
  "skill_version": "2.8.0",
  "host": "kws-mac.local",
  "pid": 48211,
  "session_id": "188042f4-d69e-45d2-91ad-91ad91ad91ad",
  "session_ids": ["188042f4-d69e-45d2-91ad-91ad91ad91ad"],
  "repo": { "name": "Archive", "branch": "feature/x", "remote_hash": null },
  "plan_path": "docs/superpowers/plans/<plan>.md",
  "spec_path": "docs/superpowers/specs/<spec>.md",
  "worktree_path": "/abs/path/to/worktree",
  "started_at": "2026-05-13T14:33:21Z",
  "ended_at": "2026-05-13T15:02:11Z",
  "outcome": "success",
  "event_count": 3
}
```

`outcome` values: `success` | `blocked` | `aborted` | `unknown`.

`session_ids[]` grows when a Resume Chain handoff continues the run in a new
Claude session — `append-session-id` appends the new UUID, preserving "one
plan execution = one run record."

## events.jsonl schema

One compact JSON object per line. Example:

```json
{
  "schema_version": "1",
  "event_id": "a1b2c3d4e5f6g7h8",
  "run_id": "20260513T143321Z-188042f4-48211",
  "timestamp": "2026-05-13T14:35:12.482910Z",
  "skill": "kws-claude-multi-agent-executor",
  "skill_version": "2.8.0",
  "phase": "phase_1",
  "risk_tier": "MID",
  "event_type": "reviewer_warn_or_fail",
  "severity": "medium",
  "execution": {
    "task_id": "task_3",
    "wave": 2,
    "compaction_index": 1,
    "issue_key": "review_retry_quality_low"
  },
  "scores": {"spec_score": 0.82, "quality_score": 0.71, "tier": "WARN"},
  "subagent": {
    "role": "reviewer",
    "model": "sonnet",
    "dispatch": "agent_tool"
  },
  "summary": "Combined Reviewer returned WARN; quality_score below 0.75.",
  "context": {
    "user_intent": "Add JSON config parsing.",
    "agent_expectation": "Reviewer would PASS.",
    "actual_outcome": "WARN tier.",
    "root_cause": "Happy-path tests only.",
    "evidence": [
      {"kind": "relative_path", "value": "src/config.py"},
      {"kind": "issue_key", "value": "review_retry_quality_low"}
    ]
  },
  "improvement": {
    "target": "references/reviewer-prompt.md",
    "proposal": "Cite specific missing test category.",
    "experiment_link": null
  },
  "privacy": {"redacted": true, "notes": "Worktree path relativized."}
}
```

### Field values

`phase`: `phase_0` | `phase_1` | `phase_transition` | `phase_2`

`risk_tier`: `LOW` | `MID` | `HIGH` | `null` (for orchestrator-level events)

`severity`:
- `low` — useful improvement signal, no execution risk
- `medium` — caused retry, scope correction, verification fix, or handled escalation
- `high` — blocked execution, risked wrong files, exposed a contract gap, required user intervention

`subagent.role`: `implementer` | `reviewer` | `verifier` | `documenter` | `plan_reviewer` | `orchestrator`

`subagent.dispatch`: `agent_tool` | `claude_p` | `orchestrator`

`subagent.model`: `sonnet` | `opus` | `haiku` | `unknown`

`scores` is present only for events with quality data (always for
`reviewer_warn_or_fail`).

`improvement.experiment_link` is optional — set to a path under
`docs/experiments/...` when the event connects to an existing experiment.

## Redaction rules

Store enough context for a future agent to improve the skill **without
re-reading the original sub-agent transcripts**. Do not store bulky or
sensitive content.

Not allowed:

- Do not store secrets, tokens, API keys, cookies, credentials, private keys,
  or authorization headers.
- Do not store full conversation transcripts. Sub-agent transcripts live at
  `~/.claude/projects/<encoded-cwd>/<session_uuid>.jsonl` and
  `~/.claude/tasks/<uuid>/` — reference them by `session_id` (already in
  `meta.json`) rather than duplicating their content.
- Do not store long raw logs. Use a short excerpt (≤ 400 chars) or a
  relative path pointer.
- Do not store absolute home paths such as `/Users/<name>/...`.
- Do not store absolute worktree paths such as
  `/Users/<name>/.../worktrees/<branch>/<file>`. Relativize to the worktree
  root and store as `<file>` relative path. The worktree path lives once in
  `meta.json`, not per-event.
- Do not store large file contents.
- Do not store unrelated user files or unrelated process details.

Allowed:

- repository name + branch
- relative plan/spec path
- task id, wave, compaction_index, issue_key, phase
- relative file paths
- command names + arguments that do not expose secrets
- short failure excerpt (≤ 400 chars)
- root-cause summary
- proposed improvement target (file path inside the skill package)

If a field cannot be safely summarized, omit it or replace with a short
redacted summary before writing the candidate.

The helper enforces these by rejecting unsafe values and relativizing
absolute paths under `--repo-root`.

## Helper interface

`scripts/append_learning_event.py` has four subcommands.

### `init-run`

Creates the run directory and writes `meta.json`. Echoes the `run_id` to
stdout. Idempotent on `(session_id, repo_name, plan_path)` — if an open
run already exists with the same identity, returns its `run_id`.

```bash
RUN_ID=$(python3 scripts/append_learning_event.py init-run \
  --repo-root "$WORKTREE_ABS" \
  --repo-name Archive \
  --branch feature/x \
  --plan-path docs/superpowers/plans/X.md \
  --spec-path docs/superpowers/specs/X.md \
  --session-id "$CLAUDE_SESSION_ID")
export MAE_LEARNING_RUN_ID="$RUN_ID"
```

### `append`

Validates and writes one event line. If the run directory does not exist
(init-run was skipped), creates it with `outcome=unknown` (self-heal).
Rejects an event whose `run_id` field does not match `--run-id`.

```bash
python3 scripts/append_learning_event.py append \
  --run-id "$MAE_LEARNING_RUN_ID" \
  --event-json <worktree>/.orchestrator/learning_events/task_3-reviewer.json \
  --repo-root "$WORKTREE_ABS"
```

`--dry-run` validates and prints the sanitized event without writing.

### `close-run`

Updates `meta.json` with `ended_at`, `outcome`, and the final `event_count`.
**Must be called from every orchestrator exit path** (success / blocked /
aborted). Idempotent.

```bash
python3 scripts/append_learning_event.py close-run \
  --run-id "$MAE_LEARNING_RUN_ID" \
  --outcome success
```

`--outcome` allowed values: `success` | `blocked` | `aborted` | `unknown`.

### `append-session-id`

Appends a new session UUID to `meta.session_ids[]` without changing
`started_at`. Called by the chained orchestrator after a Resume Chain
handoff. Idempotent.

```bash
python3 scripts/append_learning_event.py append-session-id \
  --run-id "$MAE_LEARNING_RUN_ID" \
  --session-id "$CLAUDE_SESSION_ID"
```

## Runtime flow

```
Phase 0 setup ──▶ init-run (capture run_id; export MAE_LEARNING_RUN_ID)
              │
Phase 0–2 ────▶ orchestrator reads sub-agent candidate JSON from
              │   <worktree>/.orchestrator/learning_events/ and calls append
              │
Resume Chain ─▶ chained orchestrator: append-session-id (NOT init-run)
              │
Phase 2 final ▶ close-run --outcome success
ESCALATE halt ▶ close-run --outcome blocked
User abort ──▶ close-run --outcome aborted
```

### Phase 0 init-run

Right after worktree setup, after the working tree is verified clean:

```bash
RUN_ID=$(python3 .../append_learning_event.py init-run \
  --repo-root "$WORKTREE_ABS" \
  --repo-name "$(basename $(git rev-parse --show-toplevel))" \
  --branch "$(git -C $WORKTREE_ABS branch --show-current)" \
  --plan-path "$PLAN_PATH" \
  --spec-path "$SPEC_PATH" \
  --session-id "$CLAUDE_SESSION_ID")
export MAE_LEARNING_RUN_ID="$RUN_ID"
```

`MAE_LEARNING_RUN_ID` is propagated to:
- Resume Chain handoff (`env MAE_LEARNING_RUN_ID="$MAE_LEARNING_RUN_ID" nohup claude -p ...`)
- Any sub-process that needs to know the active run (currently: only the
  Resume Chain handoff)

Agent-tool sub-agents (Implementer / Reviewer) do not need the env var — they
write candidate files, never call the helper.

### Phase 1 / Transition / 2 emit path

When a sub-agent surfaces a notable boundary, it writes a candidate JSON to
`<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`. The
orchestrator reads candidates after each cycle step and invokes `append`.

If no event is needed, no file is written — no `append` call is made.

### Phase 2 exit closure

The orchestrator wraps the entire flow with a structured exit. The single
exit point calls `close-run` with the appropriate outcome:

- Phase 2 success → `--outcome success`
- ESCALATE that halts → `--outcome blocked`
- User abort / hook denial / HEADLESS_HALTED → `--outcome aborted`

Hard crash / unhandled exception is unreachable from the closure; the
residual `outcome=unknown` is honest in that case.

### Resume Chain handoff

When `compaction_points ≥ 2 AND complete ≥ 8`, the orchestrator spawns a new
`claude -p` subprocess via:

```bash
env MAE_LEARNING_RUN_ID="$MAE_LEARNING_RUN_ID" \
  nohup claude -p --session-id "$RESUME_UUID" --dangerously-skip-permissions ...
```

The departing orchestrator does NOT call `close-run`. The chained orchestrator
calls `append-session-id` immediately after startup (NOT `init-run`).

If the chained orchestrator finds `MAE_LEARNING_RUN_ID` unset, it logs a
warning and proceeds without learning-log support rather than fragmenting
the run record by calling `init-run`.

## Failure policy

**Learning-log failure must never fail the primary plan execution.**

If helper validation fails:
- log the failure briefly in the orchestrator's running notes
- continue execution per the original state, not the logging failure
- do not weaken any blocker, verification, or retry rule

If the log path cannot be written:
- preserve the candidate under `<worktree>/.orchestrator/raw/` if that
  directory exists
- mention the write failure in the checkpoint or final summary
- do not retry indefinitely

If an event contains unsafe content:
- the helper rejects it with a clear message
- the sub-agent or orchestrator summarizes the field and retries
- never weaken redaction to make a candidate pass

## Why this is distinct from state.json

| Aspect | `state.json` (per worktree) | learning log (user-local) |
|---|---|---|
| Purpose | Resume the current run | Improve the skill across runs |
| Scope | One plan execution | All executions ever |
| Survives close-run? | Until worktree removed | Yes — designed to outlive worktrees |
| Sensitive content | Allowed (project-local) | Forbidden (cross-project) |
| Required for execution | Yes | No (failure must not block) |
| Schema | v2 (state shape) | v1 (event shape) |

The learning log is purely an **observation layer**. The skill's correctness
does not depend on it.
