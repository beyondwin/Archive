# Design: AgentRunway Production Supervisor

Date: 2026-05-20
Status: Draft for user review
Owner: KWS
Parent Design: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
Parent Plan: `docs/superpowers/plans/2026-05-20-agent-runway.md`

## 1. Summary

Upgrade `agent-runway` (`AgentRunway`) from an MVP runner with local/fake
execution and Codex/Claude command wrappers into a production supervisor for
Codex and Claude workers.

The current MVP already owns plan parsing, SQLite state, deterministic task
packets, file claims, scheduling, worktree creation for the run main branch,
and local fake execution. The gap is worker lifecycle ownership. Today
`--adapter codex` and `--adapter claude` do not launch and supervise real
workers; they only describe command shapes. This design makes the runner the
owner of worker process launch, polling, timeout, result collection, validation,
review, verification, merge, resume, and source-apply behavior.

Core target flow:

```text
plan/spec
  -> AgentRunway runner
  -> SQLite run state
  -> deterministic task waves
  -> worker worktrees
  -> Codex/Claude process adapters
  -> worker_result / review_result / verification_result artifacts
  -> diff and method audit validation
  -> review and verification gates
  -> merge queue cherry-pick into agentrunway/<run_id>/main
  -> optional agentrunway apply into source checkout
```

The host session remains thin. It shells out to `scripts/agentrunway.py`, surfaces
status, and does not coordinate workers from conversation context.

## 2. Goals

- `agentrunway run --adapter codex` launches real Codex CLI workers.
- `agentrunway run --adapter claude` launches real Claude CLI/headless workers.
- Runtime adapters supervise process lifecycle, not just build command arrays.
- Every implementation attempt runs in an isolated worker worktree.
- Worker output is accepted only through validated JSON artifacts and git
  commits.
- File claim scope is enforced against actual committed changed files.
- Reviewer and verifier janitor gates run before merge.
- Merge candidates are cherry-picked into the run main worktree only after
  validation, review, and verification pass.
- Runner crash or host interruption can be resumed from SQLite and filesystem
  state.
- `agentrunway apply --run <run_id>` applies accepted run-main commits into the source
  checkout with conflict-safe rollback behavior.
- AgentLens `agentrunway.*` events reflect runner-validated facts, not untrusted
  worker claims.

## 3. Non-Goals

- No Gemini or Aider production adapter in this phase.
- No web UI.
- No GitHub PR or CI automation.
- No Codex App native `spawn_agent` integration. CLI/headless adapters remain
  the stable execution path.
- No mandatory full OS sandbox/container isolation. `fs_scope` remains
  best-effort: workers run from the worktree and post-run diff checks reject
  committed writes outside allowed claims.
- No automatic source checkout modification. Source apply is explicit.
- No legacy naming compatibility. Pre-AgentRunway skill, CLI, package, state,
  branch, schema, and event surfaces are removed rather than retained as
  aliases.

## 4. Scope Decision

This is the broad production-supervisor approach, not the smaller vertical
slice. It includes Codex and Claude together, plus the supervisor behavior that
makes those adapters reliable enough for plan execution:

- process launch and polling,
- per-runtime semaphores,
- worker worktrees,
- result parsing,
- watchdog,
- review and verification gates,
- merge queue,
- resume,
- apply,
- observability.

The implementation plan may still split this into milestones, but the design
target is the full supervisor.

## 5. Supervisor State Machine

Workers move through explicit states:

```text
queued
  -> worktree_created
  -> dispatched
  -> running
  -> result_collected
  -> validated
  -> queued_for_review
  -> reviewing
  -> verifying
  -> merge_ready
  -> merged
```

Failure states:

```text
adapter_crashed
timeout
stalled
malformed_result
method_audit_failed
diff_scope_failed
merge_conflict
verification_failed
blocked
cancelled
```

The runner records each state transition in SQLite. A terminal task status must
be derived from runner-validated artifacts and git state, not from an adapter's
plain-text success message.

## 6. Runtime Adapter Contract

`RuntimeAdapter` becomes a real lifecycle interface:

```python
prepare(worker_spec) -> WorkerHandle
start(handle) -> WorkerHandle
poll(handle) -> WorkerStatus
collect(handle) -> WorkerResultEnvelope
cancel(handle) -> None
reattach(handle) -> WorkerHandle | None
```

Responsibilities:

- `prepare` creates runtime-specific command metadata, log paths, environment,
  prompt path, output path, timeout, and handle metadata.
- `start` launches the process in the worker worktree and records PID/session
  information.
- `poll` returns normalized process state and heartbeat information.
- `collect` reads stdout, stderr, exit status, worker artifacts, and cost data
  where available.
- `cancel` terminates the process group and records cancellation evidence.
- `reattach` reconstructs a live handle after runner restart if the runtime
  supports it.

Runtime-specific behavior:

- Codex uses `codex exec` as the stable path. It is treated as non-reattachable;
  retries start fresh from the current run-main branch.
- Claude uses the available headless CLI command, currently shaped around
  `claude -p`. If a session id or equivalent handle is available, the adapter
  records it and can attempt reattach.
- Both runtimes write stdout/stderr to runner-owned log files.
- Both runtimes receive the same task packet and output contract.
- Both runtimes are required to write the expected JSON artifact to the output
  path supplied by the runner.

## 7. Worker Worktree Flow

Each task attempt receives its own branch and worktree:

```text
source checkout
  -> agentrunway/<run_id>/main
    -> agentrunway/<run_id>/<task_id>-implementer-001
    -> agentrunway/<run_id>/<task_id>-reviewer-001
    -> agentrunway/<run_id>/<task_id>-verifier-001
```

Implementation attempt flow:

1. Runner creates `agentrunway/<run_id>/main` from the selected base commit.
2. Runner computes the current wave base commit.
3. Runner creates a worker branch/worktree from that wave base.
4. Runner writes task packet and prompt artifacts.
5. Adapter launches Codex or Claude in the worker worktree.
6. Worker edits claimed files and creates one or more git commits.
7. Worker writes `worker_result.json` to the output path.
8. Runner collects logs, result JSON, commits, and changed file list.
9. Runner validates schema, method audit, commit existence, and diff scope.
10. Runner queues an accepted candidate for review.

The runner never trusts changed file lists from the worker result alone. It
derives committed changed files from git and compares them with file claims.

## 8. Merge Queue

Merge candidates contain:

- task id,
- worker id,
- worker branch,
- ordered commit list,
- changed files derived from git,
- validation status,
- review status,
- verification status,
- merge attempt count.

Only candidates with valid result schema, passing method audit, in-scope diffs,
approved review, and passed verification can enter `merge_ready`.

Merge application uses cherry-pick into `agentrunway/<run_id>/main` in deterministic
task/wave order. If cherry-pick conflicts:

1. Abort the cherry-pick.
2. Mark the attempt `merge_conflict`.
3. Re-dispatch the task once against the updated run-main branch.
4. If the retry conflicts again, mark the task blocked with
   `recurring_merge_conflict`.

Discarded conflicting attempts remain as artifacts but do not contribute
commits to run main.

## 9. Reviewer Gate

Reviewer workers run after an implementation candidate passes runner validation
and before merge. They are read-only by policy and receive:

- task packet,
- relevant spec slices,
- candidate diff,
- worker result summary,
- acceptance commands list.

Reviewer output schema:

```json
{
  "schema": "agentrunway.review_result.v1",
  "worker_id": "task_001-reviewer-001",
  "task_id": "task_001",
  "reviewed_worker_id": "task_001-implementer-001",
  "status": "approved",
  "checks": [],
  "findings": [],
  "method_audit": {}
}
```

Rules:

- `approved` with non-empty findings is invalid.
- `changes_requested` consumes review-round budget and re-dispatches an
  implementer attempt with reviewer findings.
- `rejected` blocks the task unless an explicit recovery policy applies.

## 10. Verifier Gate

Verifier workers run in a clean verification worktree after review passes and
before merge. They receive:

- task packet,
- candidate commit list,
- changed file list,
- acceptance commands,
- relevant test instructions.

Verifier output schema:

```json
{
  "schema": "agentrunway.verification_result.v1",
  "worker_id": "task_001-verifier-001",
  "task_id": "task_001",
  "status": "passed",
  "checks": [],
  "method_audit": {}
}
```

Rules:

- Only `passed` can move the candidate to `merge_ready`.
- `failed` records evidence and may re-dispatch implementer once if the failure
  is actionable.
- `blocked` stops the task with evidence.
- Command output is stored as bounded excerpts with redaction.

## 11. Watchdog and Retry Policy

The watchdog is runner-driven polling, not a worker-trusted heartbeat system.
It considers:

- process liveness,
- wall-clock runtime,
- stdout/stderr mtime,
- output artifact presence,
- adapter-reported heartbeat if available,
- retry counts,
- review-round budget.

Actions:

```text
observe -> nudge/log -> cancel -> retry -> recovery worker -> blocked
```

Defaults:

- implementation timeout: use task `timeout_seconds`, else
  `worker.default_timeout_seconds`, else 1800 seconds,
- adapter crash retry: one fresh attempt,
- timeout retry: one fresh attempt,
- merge conflict retry: one fresh attempt from updated run main,
- review changes-requested rounds: one by default,
- recurring failure after budget exhaustion: blocked.

Retries must create new worker ids and new worktrees. The runner does not reuse
dirty worker worktrees for retried attempts.

## 12. Resume

`agentrunway resume --run <run_id>` restores from SQLite, `run.json`, git refs, and
filesystem artifacts.

Resume rules:

- Terminal tasks (`merged`, `blocked`, `cancelled`) are not changed.
- Running Codex workers are polled by PID if still alive; if dead and no valid
  result exists, they are retried because Codex is non-reattachable.
- Running Claude workers attempt adapter reattach if session metadata exists;
  if reattach fails, they are retried.
- A valid result artifact without a recorded DB transition is reconciled
  forward.
- A cherry-pick in progress is aborted and its candidate is returned to queue.
- Orphan worker worktrees are compared with DB state and either reclaimed or
  retained as diagnostic artifacts.

Resume must be idempotent. Running it twice should not duplicate workers,
merge commits, or review attempts.

## 13. Apply to Source Checkout

`agentrunway apply --run <run_id>` applies accepted run-main commits to the source
checkout.

Strategies:

1. `cherry-pick` default: apply accepted commits in recorded order.
2. `patch` fallback: apply a generated patch when cherry-pick cannot be used
   but the patch applies cleanly.
3. `merge` explicit: merge the run-main branch only when requested.

Safety rules:

- Dirty source checkout is refused by default.
- Conflict aborts and restores the checkout to the pre-apply state.
- Applied commit ids and strategy are written to SQLite.
- A second `agentrunway apply` is idempotent and reports already-applied commits.

## 14. Observability and Artifacts

Runner-owned event types:

```text
agentrunway.run_started
agentrunway.worker_dispatched
agentrunway.worker_result
agentrunway.worker_rejected
agentrunway.review_result
agentrunway.verification_result
agentrunway.merge_applied
agentrunway.run_finished
```

Local artifact layout:

```text
~/.agentrunway/runs/<workspace_id>/<run_id>/
  state.sqlite
  run.json
  packets/
  prompts/
  logs/
    worker_<worker_id>.stdout.log
    worker_<worker_id>.stderr.log
  artifacts/
    <task_id>/<worker_id>/
      worker_result.json
      review_result.json
      verification_result.json
      diff.patch
      test_excerpt.txt
```

Redaction applies before writing AgentLens payloads and before preserving
stdout/stderr excerpts in long-lived artifacts. Home paths become `~`, and
secret-like keys such as `token`, `api_key`, `secret`, and `password` are
replaced with `[REDACTED]`.

AgentLens is best-effort. If unavailable, the runner records a local event
artifact and continues unless the user explicitly configured AgentLens as
required.

## 15. Testing Strategy

Production adapter tests must not require real model calls by default. Tests
place fake `codex` and `claude` binaries at the front of `PATH`; those binaries
exercise the same process adapter path and write deterministic commits/results.

Required eval scenarios:

- fake Codex CLI writes a commit and worker result; runner merges it.
- fake Claude CLI writes a commit and worker result; runner merges it.
- malformed `worker_result.json` is rejected.
- nonzero process exit becomes `adapter_crashed`.
- timeout becomes `timeout`.
- out-of-scope committed diff becomes `diff_scope_failed`.
- merge conflict causes one re-dispatch, then blocks on recurring conflict.
- reviewer `changes_requested` triggers an implementer retry.
- verifier `failed` triggers retry or blocked status according to policy.
- resume from `running` state does not duplicate workers.
- `agentrunway apply` refuses dirty source checkout.
- AgentLens unavailable records local event evidence and does not stop the run.

Real Codex/Claude smoke tests should be opt-in because they spend model
capacity and depend on local CLI authentication.

## 16. Acceptance Criteria

- `agentrunway run --adapter codex` uses the Codex process adapter path, not
  `LocalAdapter`.
- `agentrunway run --adapter claude` uses the Claude process adapter path, not
  `LocalAdapter`.
- Worker stdout/stderr are saved in runner logs.
- Worker result JSON is parsed from a runner-specified output path.
- Git-derived changed files are validated against file claims.
- In-scope candidate commits are cherry-picked into run main only after review
  and verification pass.
- Resume is idempotent for interrupted runs.
- Apply is explicit and conflict-safe.
- Existing local fake adapter tests continue to pass.
- New fake Codex/Claude adapter evals pass without network or model calls.

## 17. Implementation Notes

The implementation should preserve the current MVP API where practical. The
largest expected changes are:

- expand `adapters/base.py` from one-shot `run()` to lifecycle methods,
- add a shared process supervision helper,
- update `codex.py` and `claude.py` to implement the lifecycle contract,
- teach `runner.py` to create worker worktrees and drive the state machine,
- extend `db.py` for attempts, handles, logs, retries, review, verification,
  and applied commits,
- extend `merge_queue.py` for candidate status and conflict retry,
- implement real `agentrunway apply`,
- add fake CLI fixtures for deterministic adapter tests.

The deterministic `--adapter local --fake-success` smoke path should remain so
tests stay fast and repeatable.
