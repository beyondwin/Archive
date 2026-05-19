# Learning Log

> **v2.17 cutover banner (Task 11)**
>
> The legacy helper `scripts/append_learning_event.py` and its per-run sharded
> storage under `~/.claude/learning/kws-claude-multi-agent-executor/runs/...`
> were REMOVED in v2.17. AgentLens is now the sole event sink: every event the
> orchestrator emits is published as `kws-cme.<event_type>` via
> `agentlens event append --run "$ORCH_RUN_ID" --type kws-cme.<...>`.
>
> What still applies from this document:
>
> - **Event taxonomy and candidate-file schema** (sections "Event types" below).
>   Sub-agents still write candidate JSON to
>   `<orch_dir>/learning_events/<task_id>-<role>.json`; the
>   orchestrator now publishes each to AgentLens as `kws-cme.<event_type>`
>   instead of calling the deleted helper.
> - **Field semantics**: `event_type`, `severity`, `phase`, `execution`,
>   `subagent`, `context`, `improvement`, `privacy`. AgentLens preserves the
>   candidate JSON as the event payload, so every field documented below is
>   queryable via `agentlens events --type 'kws-cme.<event_type>'`.
>
> What no longer applies (read as historical reference for pre-v2.17 runs only):
>
> - The "Storage layout" `~/.claude/learning/.../runs/<date>/<run_id>/` paths.
> - The `meta.json` / `events.jsonl` / `final.json` files and the precedence
>   rules around them.
> - Every `scripts/append_learning_event.py` subcommand reference (`init-run`,
>   `append`, `close-run`, `append-session-id`, `resolve-outcome`).
> - The `MAE_LEARNING_RUN_ID` environment variable.
>
> Replacements:
>
> | Pre-v2.17 | v2.17+ |
> |-----------|--------|
> | `append_learning_event.py init-run ...` | `agentlens run-open --agent kws-cme-orchestrator ...` at Phase -1 step b |
> | `append_learning_event.py append --event-json <cand>` | `agentlens event append --type "kws-cme.$(jq -r .event_type <cand>)" --payload-json "@<cand>"` |
> | `append_learning_event.py close-run --outcome <X>` | `agentlens run-close --outcome <X>` |
> | `append_learning_event.py resolve-outcome --run-id <id>` | `agentlens runs --filter id=<id>` |
> | `MAE_LEARNING_RUN_ID` | `ORCH_RUN_ID` (propagated to chained children as `AGENTLENS_PARENT_RUN_ID`) |
> | `~/.claude/learning/.../events.jsonl` | `agentlens events --run <id> --type 'kws-cme.*'` |
>
> Parity verification on historical runs that retain a legacy `events.jsonl`
> alongside an AgentLens stream: `python3 scripts/compare_agentlens_events.py
> <legacy_events.jsonl> <agentlens_run_dir>`. The script also has a
> `--self-test` mode that exercises six synthetic cases without any real run.

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

## Source of truth for terminal outcome

Precedence (highest first):

1. `runs/<date>/<run_id>/final.json` — written by `close-run`. Authoritative once present.
2. `runs/<date>/<run_id>/meta.json` — mirrors `final.json` outcome when close-run runs; remains `unknown` until then.
3. `index.jsonl` — start records by default. **As of v2.11**, `close-run` rewrites the matching row's `outcome` field atomically. Older runs prior to this change still have stale `index.jsonl` entries; use `resolve-outcome` to query.

Use `scripts/append_learning_event.py resolve-outcome --run-id <id>` instead of reading `index.jsonl` directly when reporting on closed runs.

A run with `event_count == 0` AND `final.outcome == "success"` is **normal** for routine successful work — learning events are notable-boundary-only, not routine task logs.

## Single-writer contract

**The orchestrator is the only process that invokes the helper.** Sub-agents
do **NOT** call the helper directly. They prepare event candidate JSON files
under:

```text
<orch_dir>/learning_events/<task_id>-<role>.json
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
| `context_health` (v2.10) | Passive observation of context-management state — emitted by the orchestrator at Phase Transition T3 (after each compaction) and at Resume Chain chained-orchestrator startup. **No thresholds, no actions** — the type exists to collect data before deciding whether context drift signals need policy. |

### `context_health` (v2.10) — passive observation contract

**Producer**: orchestrator only (NOT sub-agents). Sub-agents do not have visibility into compaction boundaries or chain handoffs.

**Emit points** (both unconditional — no severity escalation):
1. Phase Transition T3, after the compaction completes and state has been written.
2. Resume Chain chained orchestrator startup, immediately after `append-session-id`.

**Severity**: always `low`. This event is informational; it is not a failure signal.

**Required `context` fields** (beyond the baseline `user_intent` / `agent_expectation` / `actual_outcome` / `root_cause` / `evidence` schema, which remain required for shape consistency):

| Field | Source | Meaning |
|---|---|---|
| `compaction_index` | `state.last_compaction_after_task` derived index, or `-1` for chain-handoff snapshots | Which compaction this snapshot is at |
| `completed_tasks_count` | count of `state.tasks[*].status == "COMPLETE"` (or `state.plan2_state.tasks` when `active_plan == "plan2"`) | How much progress has been made |
| `resume_chain_handoffs` | `len(state.meta.session_ids) - 1`, or 0 if unset | How many chain handoffs have already occurred |

**Optional `context` fields** (include when introspectable, omit otherwise):

- `risk_distribution`: object mapping `LOW`/`MID`/`HIGH` → count of completed tasks at that tier
- `verifier_retry_total`: sum of `verifier_retries` across completed tasks
- `review_retry_total`: sum of `review_retries` across completed tasks
- `quality_trend_mean`: mean of `state.quality_trend` if non-empty
- `drift_signals`: array of free-form strings describing observations (e.g., `"three consecutive WARN tasks"`)

**`improvement` field**: set `target` to `references/learning-log.md` (self-reference — the eventual improvement target is the schema itself, once we know which fields matter), `proposal` to `"Aggregate context_health events to derive empirical thresholds."`, `experiment_link` to `null`.

**Goodhart warning**: do NOT use these counters to alter orchestrator behavior (e.g., force compaction earlier, refuse new dispatches). The v2.10 contract is observation-only. Behavior changes require a follow-on experiment under `docs/experiments/v2.10-context-health/` after ≥ 2 weeks of real-run data.

### Optional fields (v2.11)

- `context.root_cause_category`: one of `docker_oom`, `gradle_daemon_disappearance`, `gradle_metaspace`, `node_heap_oom`, `service_unreachable`, `other`. Set when ENV_BLOCKER triage from `references/escalation-playbook.md` identifies a category. Absent or `other` means uncategorized.

<!-- for_next_tasks: Task 2 will add the source-of-truth section for verification_failure elsewhere in this file. This subsection is an optional-field extension within the verification_failure event-type, not a replacement for the full event-type description. -->

## meta.json schema

Written once by `init-run`, updated by `close-run`. Example:

```json
{
  "schema_version": "1",
  "run_id": "20260513T143321Z-188042f4-48211",
  "skill": "kws-claude-multi-agent-executor",
  "skill_version": "2.10.2",
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
  "skill_version": "2.10.2",
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
  --event-json <orch_dir>/learning_events/task_3-reviewer.json \
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
              │   <orch_dir>/learning_events/ and calls append
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
`<orch_dir>/learning_events/<task_id>-<role>.json`. The
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
- preserve the candidate under `<orch_dir>/raw/` if that
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
