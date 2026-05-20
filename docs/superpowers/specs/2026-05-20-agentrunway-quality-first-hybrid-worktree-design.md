# Design: AgentRunway Quality-First Hybrid Worktree and Context Control

Date: 2026-05-20
Status: Draft for user review
Owner: KWS
Parent Designs:
- `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
- `docs/superpowers/specs/2026-05-20-agent-runway-production-supervisor-design.md`
- `docs/superpowers/specs/2026-05-20-agentrunway-operations-quality-engine-design.md`

## 1. Summary

AgentRunway should keep its quality-first execution model while reducing
unnecessary worktree growth and host-session context use.

The current production supervisor uses isolated worktrees for implementers,
reviewers, and verifiers. That is safe, but expensive: every retry or gate
creates more git worktrees, more logs, and more state for the host agent to
inspect later. The right improvement is not to remove isolation. The right
improvement is to make isolation role-aware.

Recommended target:

```text
source checkout
  -> run main worktree, persistent for the run
      -> implementer candidate worktrees, persistent until candidate retention policy
      -> reviewer worktree, avoided by default and created only for escalation
      -> verifier worktree, ephemeral and removed after evidence capture
```

The quality rule is load-bearing:

```text
Never reduce worktrees or context in a way that removes evidence needed for
review, verification, merge, resume, or postmortem diagnosis.
```

Host-session context must also become summary-first. The host should not read
raw event logs, stdout, stderr, or full worker prompts during normal operation.
The runner should produce compact, authoritative summaries from SQLite,
artifacts, and git state. Raw logs remain available only for deep inspection.

## 2. Context and Lessons From the Last Run

The 2026-05-20 operations quality work exposed four practical issues:

- Missing or late `run.json` made failed runs hard to inspect even when
  `state.sqlite` and `events.jsonl` contained useful evidence.
- Worker sandbox or artifact-write failures were discovered after dispatch,
  wasting time and producing partially useful but hard-to-merge state.
- Reviewer and verifier visibility depended on the correct candidate base. This
  is now fixed, but the invariant should be explicit and tested.
- The host session spent too much context reconstructing state from raw logs
  and event files. That defeats the AgentRunway design goal that the runner,
  not the chat context, owns execution state.

The existing fixes hardened recovery, but the next slice should make these
constraints first-class:

- Role-aware worktree lifecycle.
- Preflight before dispatch.
- Summary-first host context.
- SQLite fallback for status and inspect.
- Better timing and lifecycle evidence.
- Plan linting before any worker starts.

## 3. External Harness Patterns

This design borrows patterns, not code.

- Superpowers `subagent-driven-development` uses a fresh subagent per task,
  explicitly to avoid inherited context pollution. The controller constructs
  the exact context the worker needs, then performs spec and quality reviews.
- Claude Code subagents are documented as separate context windows for focused
  work. They are useful for log-heavy or search-heavy work because they keep
  the main conversation clean.
- Claude Code worktree guidance treats worktrees as isolation boundaries for
  parallel coding work, while allowing cleanup when a worktree produced no
  changes or only temporary evidence.
- Aider's repo-map approach compresses repository knowledge into a bounded
  map, then opens exact files only when needed. The useful lesson is that the
  controller should not put the whole repository or full logs into the main
  context.
- Cloud coding agents such as GitHub Copilot's cloud agent and OpenHands run
  work in isolated environments and return branch, log, and PR evidence rather
  than full interactive transcripts.

Reference links:

- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/worktrees
- https://code.claude.com/docs/en/agent-teams
- https://aider.chat/docs/repomap.html
- https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent
- https://docs.openhands.dev/openhands/usage/architecture/runtime

## 4. Goals

- Preserve or improve execution quality.
- Keep implementer candidate isolation for every code-changing attempt.
- Use reviewer worktrees only when the review needs full-tree context.
- Use verifier worktrees as ephemeral test sandboxes.
- Merge only through the run main worktree.
- Preserve enough evidence to reproduce decisions after cleanup.
- Keep the host agent's normal context use bounded and small.
- Make `status`, `inspect`, `resume`, and future summaries work even if
  `run.json` is missing or stale.
- Detect obvious adapter, git, and artifact-write failures before worker
  dispatch.
- Make plan errors fail before model calls.

## 5. Non-Goals

- No reduction in review or verification gates.
- No direct merge between worker worktrees.
- No automatic source checkout modification.
- No automatic conflict editing.
- No web dashboard in this slice.
- No dependency on Codex App `spawn_agent` as the base execution primitive.
- No deletion of useful forensic evidence before it is summarized and archived.

## 6. Role-Aware Worktree Strategy

### 6.1 Run Main Worktree

The run main worktree remains persistent for the full run:

```text
~/.agentrunway/worktrees/<workspace_id>/<run_id>/main
```

Responsibilities:

- integration base for accepted candidates;
- only location where candidate commits are cherry-picked together;
- authoritative merge-conflict surface;
- source of commits for explicit `agentrunway apply`.

Rules:

- Create exactly one run main worktree per run.
- Never allow implementer, reviewer, or verifier workers to mutate run main.
- Apply merge candidates into run main in deterministic dependency order.
- If run main has interrupted cherry-pick state, block or resume through a
  reconciliation plan before starting new work.

### 6.2 Implementer Candidate Worktrees

Implementer worktrees stay persistent by default because they are the source of
candidate commits.

```text
workers/<task_id>-implementer-<attempt>/
```

Rules:

- Create one worktree per implementer candidate attempt.
- High-risk tasks keep two independent implementer candidates unless policy
  changes.
- Derive `commits` and `changed_files` from git, not from worker JSON claims.
- Keep selected candidate worktrees until the run is applied or explicitly
  cleaned.
- Convert non-selected candidate worktrees to retained evidence before cleanup:
  `format-patch`, commit list, changed-file list, worker result, stdout/stderr
  excerpts, ranking reason, and method audit.

Why this is still the right amount of worktree creation:

- It protects the user's source checkout.
- It makes candidate comparison real instead of conversational.
- It lets the runner reject scope violations from actual commits.
- It provides a clean cherry-pick path into run main.

### 6.3 Reviewer Execution

Reviewer worktrees should become conditional.

Default reviewer input:

```text
task packet summary
spec refs summary
candidate diff
changed files
worker_result.json
method audit
acceptance commands
previous gate feedback when retrying
```

Default reviewer mode:

```text
diff-review
```

v1 scope note: the supervisor still creates a worker worktree for the reviewer
process in diff mode so the existing `run_worker_attempt` path remains the
single execution primitive. The diff-mode reviewer reads the candidate diff
from its packet context and must not claim full-tree review. A follow-up
slice replaces diff-mode reviewer execution with a no-worktree adapter path;
that is the only way the "no git worktree" target from earlier drafts is
actually achieved. Until that lands, the resource win in this slice comes
from lifecycle-aware retention plus ephemeral verifier cleanup, not from
skipping reviewer worktree creation.

Escalate to a full-tree reviewer worktree when any condition is true:

- task risk is `high`;
- candidate diff is above the configured line threshold;
- candidate changed files include rename, delete, binary, generated, or
  schema/migration files;
- reviewer reports insufficient context;
- task file claims include broad globs;
- policy marks the task as requiring full-tree review;
- previous review and verification disagree.

Rules:

- Reviewer in diff mode cannot claim full-tree review in `review_result.json`.
- Reviewer result must include `review_mode`: `diff` or `full_tree`.
- `needs_context` is a first-class review status. The runner must treat it as
  an explicit escalation request, not a gate failure: on the first occurrence
  for a candidate, the runner re-dispatches a reviewer with `review_mode`
  forced to `full_tree` instead of routing through the standard retry gate.
  Repeated `needs_context` collapses to a normal blocked outcome.
- Full-tree reviewer worktrees are ephemeral unless they uncover a failure
  requiring postmortem retention.

### 6.4 Verifier Execution

Verifier worktrees remain required for tests, but they should be ephemeral.

Rules:

- Create verifier worktree from the selected candidate head.
- Run acceptance commands and targeted tests from that worktree.
- Persist verification evidence before cleanup:
  `verification_result.json`, command list, exit codes, stdout/stderr excerpts,
  test summary, environment summary, candidate commit list, changed files.
- Remove verifier worktree after successful evidence capture unless retention
  policy says to preserve failed worktrees for diagnosis.

This keeps quality high because tests still run on real candidate files. It
reduces disk and state because verification worktrees are not useful merge
sources after evidence is captured.

### 6.5 Retention Policy

Add lifecycle states for worktrees:

```text
active
evidence_archived
retained_for_apply
retained_for_diagnosis
cleanup_eligible
removed
```

Default retention:

| Worktree | Successful run | Blocked or failed run |
| --- | --- | --- |
| run main | retain until apply or clean | retain for diagnosis |
| selected implementer | retain until apply or clean | retain for diagnosis |
| non-selected implementer | archive evidence, then cleanup eligible | retain for short diagnosis window |
| reviewer diff mode | no worktree | no worktree |
| reviewer full-tree | archive evidence, cleanup eligible | retain for short diagnosis window |
| verifier | archive evidence, cleanup eligible | retain for short diagnosis window |

Cleanup must be dry-run by default and must never remove active detached runs.

## 7. Merge Strategy

The merge strategy should stay conservative.

```text
candidate worktree commit
  -> validate result JSON
  -> validate actual changed files
  -> review gate
  -> verification gate
  -> candidate ranking
  -> cherry-pick selected candidate into run main
  -> optional explicit apply into source checkout
```

Rules:

- Worker worktrees never merge into each other.
- Runner never trusts plain-text worker success.
- Runner never uses unverified candidates for merge.
- `merge_ready` is candidate-local until selected.
- Selected candidates are applied to run main in task dependency order.
- Merge conflict in run main does not trigger automatic conflict editing.
- First conflict can produce a conflict-redispatch plan when policy allows it.
- Repeated conflict becomes manual action.

This is safer than task-level shared worktrees. A shared task worktree would
make it harder to compare candidates, harder to reject scope violations, and
easier for retries to contaminate each other.

## 8. Subagent Creation and Management

AgentRunway should manage subagents as leases, not as chat participants.

### 8.1 Worker Lease

Each subagent attempt gets a `worker_lease` row or equivalent DB state:

```json
{
  "worker_id": "task_003-implementer-001",
  "task_id": "task_003",
  "role": "implementer",
  "candidate_id": null,
  "base_commit": "abc123",
  "worktree_path": "...",
  "prompt_path": "...",
  "output_path": "...",
  "started_at": "...",
  "ended_at": null,
  "lease_state": "running"
}
```

Lease rules:

- A worker has exactly one role.
- A worker receives a bounded packet, not the host conversation.
- A worker cannot write SQLite or AgentLens directly.
- A worker result is untrusted until schema, git, file-claim, and gate checks
  pass.
- A retry creates a new lease and new attempt number.
- A stale lease is classified by watchdog before any redispatch.

### 8.2 Context Packets

Packets should be role-specific:

- Implementer packet: objective, file claims, allowed writes, acceptance
  commands, spec slices, dependencies, output schema, previous retry feedback.
- Reviewer packet: task summary, candidate diff, changed files, worker result,
  method audit, acceptance context, review mode.
- Verifier packet: candidate commit, changed files, acceptance commands,
  review status, test focus, output schema.

The packetizer should cap large fields and write overflow to artifact files
referenced by hash/path. A worker can inspect the referenced artifact from its
worktree or artifact directory, but the host agent does not need to load it.

### 8.3 Fresh Context Rule

Every worker starts with fresh context. The runner constructs exactly what the
worker needs:

```text
plan/spec slice
task packet
file claims
role instructions
artifact paths
output schema
retry context, if any
```

The host conversation is not inherited by worker prompts. This matches the
Superpowers subagent pattern and prevents task-local log or file exploration
from polluting the coordinator context.

## 9. Host Context Control

The host should normally see one bounded object:

```text
run_summary.json
```

Required summary fields:

```json
{
  "run_id": "example",
  "status": "blocked",
  "base_commit": "abc123",
  "task_counts": {"merged": 3, "blocked": 1},
  "current_task": "task_004",
  "next_action": "agentrunway inspect --run example --deep task_004",
  "selected_candidates": [],
  "blocked_tasks": [
    {
      "task_id": "task_004",
      "reason": "diff_scope_failed",
      "evidence_refs": ["events:33", "worker:task_004-implementer-001"]
    }
  ],
  "quality_decisions": [],
  "residual_risks": [],
  "artifact_refs": {
    "events": ".../events.jsonl",
    "state": ".../state.sqlite",
    "run": ".../run.json"
  }
}
```

Host-context rules:

- `status` prints only compact state and next action.
- `inspect` prints bounded diagnosis, gate decisions, and evidence refs.
- `inspect --deep` is the only path that opens raw logs.
- `events` defaults to a tail or summary, not the full event stream.
- Worker stdout/stderr is summarized into excerpts and line counts.
- Large diffs are summarized and referenced by artifact path.
- The host never needs to manually reconstruct a run from raw SQLite and JSONL
  unless the summary command itself is broken.

## 10. Operations Improvements Included in This Slice

### 10.1 SQLite Fallback for Missing `run.json`

`status`, `inspect`, and `summarize` should rebuild a partial run view from:

- `state.sqlite`;
- `events.jsonl`;
- known run directory path;
- worktree registry;
- artifact graph when present.

Fallback payloads must say which source fields were reconstructed.

### 10.2 Adapter Preflight

Before dispatch, each runtime adapter should verify:

- CLI exists and can print version/help;
- worktree can write files;
- git commit is possible in worker worktree;
- artifact directory is writable;
- configured sandbox can write `.git/worktrees` and `~/.agentrunway`;
- output artifact path can be created;
- required environment variables are present.

Preflight failure blocks before model calls.

v1 scope note: the first slice covers adapter-binary presence, git identity,
git common-dir access, and write probes for the run directory and worktree
parent. The remaining bullets (sandbox write to `.git/worktrees`, actual
trial commit inside a scratch worktree, env var presence per adapter) are
followups. Track which preflight surface is implemented in the
`PreflightResult` so summaries can note when partial preflight is in
effect.

### 10.3 Plan Lint

Add `agentrunway lint-plan --plan <path> --spec <path>`.

Checks:

- every task block is parseable;
- task ids are unique;
- dependencies exist and have no cycle;
- file claims exist and do not overlap unsafely;
- acceptance commands are present for code-changing tasks;
- high-risk tasks are explicit;
- broad globs require high-risk or explicit justification;
- spec refs are resolvable;
- forbidden paths are not claimed as owned.

### 10.4 Worker Timing

Populate `started_at` and `ended_at` for every worker, reviewer, verifier, and
preflight lease. Current `updated_at` is useful but not enough for duration and
stall diagnosis.

### 10.5 Reviewer and Verifier Visibility Invariant

Add an invariant:

```text
Any reviewer or verifier that claims to inspect candidate files must run from a
base where every candidate changed file exists at the candidate version.
```

Tests should fail if reviewer/verifier worktrees are created from run main
instead of candidate head when full-tree visibility is required.

### 10.6 AgentLens Disabled Notice

When AgentLens is disabled or unavailable, status should explicitly say:

```text
AgentLens disabled; local SQLite and artifacts are authoritative.
```

This prevents operators from treating missing AgentLens events as missing
execution evidence.

## 11. Proposed Files

### Create

| Path | Responsibility |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py` | Role-aware lifecycle decisions, retention state, and cleanup eligibility. |
| `skills/agent-runway/scripts/agentrunway/run_summary.py` | Compact summary builder from SQLite, events, artifacts, and git state. |
| `skills/agent-runway/scripts/agentrunway/preflight.py` | Adapter/git/artifact/sandbox preflight checks. |
| `skills/agent-runway/scripts/agentrunway/plan_lint.py` | Static plan/spec validation before dispatch. |
| `skills/agent-runway/evals/test_worktree_lifecycle.py` | Unit tests for lifecycle and retention policy. |
| `skills/agent-runway/evals/test_run_summary.py` | Summary and SQLite fallback tests. |
| `skills/agent-runway/evals/test_preflight.py` | Preflight success/failure tests. |
| `skills/agent-runway/evals/test_plan_lint.py` | Plan lint tests. |

### Modify

| Path | Change |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/models.py` | Add review mode, worktree lifecycle states, and timing fields as needed. |
| `skills/agent-runway/scripts/agentrunway/db.py` | Persist lifecycle, worker timing, and summary source metadata. |
| `skills/agent-runway/scripts/agentrunway/supervisor.py` | Create worktrees according to role-aware policy. |
| `skills/agent-runway/scripts/agentrunway/runner.py` | Call preflight, summary updates, and lifecycle archival points. |
| `skills/agent-runway/scripts/agentrunway/packetizer.py` | Add role-specific packet caps and artifact refs for large context. |
| `skills/agent-runway/scripts/agentrunway/status.py` | Render summary-first status and AgentLens-disabled notice. |
| `skills/agent-runway/scripts/agentrunway/invocation.py` | Add `summarize` and `lint-plan` commands. |
| `skills/agent-runway/scripts/agentrunway/retention.py` | Clean lifecycle-aware worktrees without losing evidence. |
| `skills/agent-runway/README.md` | Document hybrid worktree policy and summary-first operations. |
| `skills/agent-runway/references/context-policy.md` | Document host context budget and deep-inspect path. |
| `skills/agent-runway/references/worktree-policy.md` | Document role-aware worktree lifecycle. |
| `skills/agent-runway/references/watchdog.md` | Include worker timing and stale lease rules. |

## 12. Implementation Slices

### Slice 1: Plan Lint and Preflight

Goal: fail before worker dispatch when the run cannot succeed.

Acceptance:

- `lint-plan` catches missing task blocks, bad dependencies, unsafe file claims,
  missing acceptance commands, and unresolved spec refs.
- `preflight` catches adapter command, git commit, artifact write, and sandbox
  write failures before model calls.
- Existing run behavior is unchanged when lint and preflight pass.

### Slice 2: Summary-First Status

Goal: reduce host context use without losing diagnosis quality.

Acceptance:

- `summarize --run` returns bounded JSON.
- `status` and `inspect` use summary data instead of forcing raw event reads.
- Missing `run.json` can be partially reconstructed from SQLite and events.
- Raw logs are available only through explicit deep inspection.

### Slice 3: Worker Timing and Lease Evidence

Goal: make worker lifecycle diagnosis precise.

Acceptance:

- every worker row has `started_at` and terminal `ended_at` when applicable;
- durations appear in summary;
- stale leases can be diagnosed without reading raw logs;
- tests cover success, failure, timeout, and missing-result leases.

### Slice 4: Hybrid Worktree Lifecycle

Goal: keep implementer isolation, reduce reviewer/verifier residue.

Acceptance:

- implementer candidates still get independent persistent worktrees;
- reviewer default mode uses diff/evidence only;
- reviewer escalates to full-tree ephemeral worktree on policy triggers;
- verifier uses candidate-head ephemeral worktree and archives evidence;
- lifecycle-aware cleanup preserves patch/evidence before removing worktrees.

### Slice 5: Quality Escalation Policy

Goal: ensure worktree reduction never reduces quality.

Acceptance:

- high-risk tasks trigger full-tree review or explicit policy override;
- large diffs trigger full-tree review;
- reviewer `needs_context` triggers one full-tree escalation;
- verification still runs real commands against candidate files;
- summary records when and why escalation happened.

### Slice 6: Documentation and Operator UX

Goal: make the new behavior understandable and hard to misuse.

Acceptance:

- README explains role-aware worktree lifecycle;
- context policy explains normal summary mode vs deep inspect;
- status output clearly says local evidence is authoritative when AgentLens is
  disabled;
- retention docs explain what evidence remains after cleanup.

## 13. Testing Strategy

Unit tests:

- lifecycle decision table;
- summary builder with full and missing `run.json`;
- plan lint edge cases;
- preflight failures;
- packet size caps and artifact refs;
- review escalation policy.

Integration tests:

- fake Codex implementer produces candidate, reviewer diff mode approves,
  verifier ephemeral worktree tests candidate file, merge succeeds;
- high-risk task produces two implementer worktrees and full-tree review;
- reviewer `needs_context` escalates to full-tree mode once;
- verifier worktree is removed after evidence capture in successful run;
- non-selected implementer evidence is archived before cleanup;
- failed run keeps enough worktree/evidence for diagnosis;
- `summarize --run` stays bounded even with large events and stdout.

Regression tests:

- reviewer/verifier candidate-head visibility;
- moving base branch cannot contaminate changed-file validation;
- missing `run.json` still produces useful `status` and `inspect`;
- AgentLens disabled does not hide local evidence.

## 14. Risks and Mitigations

Risk: diff-only review misses context-sensitive bug.

Mitigation: high-risk, large diff, schema/migration, rename/delete, broad glob,
and reviewer `needs_context` all escalate to full-tree review.

Risk: ephemeral verifier cleanup removes evidence needed later.

Mitigation: cleanup happens only after verification artifacts, command output
excerpts, candidate commit list, changed files, and environment summary are
persisted.

Risk: summary hides important failure detail.

Mitigation: summary includes evidence refs and `inspect --deep` can open raw
logs for a selected task or worker.

Risk: lifecycle cleanup deletes worktrees before source apply.

Mitigation: selected implementer and run main are retained until apply or
explicit cleanup. Cleanup dry-run remains the default.

Risk: preflight slows every run.

Mitigation: preflight is cheap compared with model calls and prevents more
expensive partial failures.

## 15. Operator Defaults

Recommended defaults:

```text
reviewer_default_mode = diff
reviewer_full_tree_for_high_risk = true
reviewer_full_tree_diff_line_threshold = 400
verifier_worktree_lifecycle = ephemeral
non_selected_candidate_retention = archive_patch_then_cleanup
failed_worktree_retention = retain_for_diagnosis_window
summary_event_tail = 20
summary_stdout_excerpt_lines = 80
deep_inspect_required_for_raw_logs = true
```

These defaults favor quality before efficiency: risky work still gets richer
review, and verification always runs against real files.

## 16. Implementation Audit Notes (2026-05-20)

A code audit against `skills/agent-runway/scripts/agentrunway/` produced the
following invariants and known gaps. These should be preserved across future
slices; ignoring them silently re-introduces the issues this design exists
to prevent.

### 16.1 Worktree Registry Wiring

`db.py` already declares the `worktree_registry` table, but no production code
populates it. Adding lifecycle setters without a `register_worktree` call site
inside `supervisor.run_worker_attempt` leaves both the lifecycle policy and
the lifecycle-aware retention path as dead code. The lifecycle slice must
include the registration wiring, not only the setter helpers, or the
hybrid-worktree behavior is unobservable in the database.

### 16.2 Reviewer Diff-Mode Worktree Still Created in v1

This slice does not actually remove reviewer worktrees. The reviewer process
still runs through `run_worker_attempt`, which always creates a worker
worktree. The diff-mode contribution in v1 is the `review_mode` field, the
escalation policy, and the prompt restriction against claiming full-tree
findings. The disk and process savings expected from "no git worktree" land
only when a no-worktree reviewer adapter path is implemented in a follow-up
slice. The design body §6.3 has been updated to say this explicitly.

### 16.3 Runner-Side `needs_context` Escalation

Accepting `needs_context` in `validate_review_result` is necessary but not
sufficient. The runner's review branch in `runner.py` currently routes any
non-`approved` status through `gate_retry_decision`, so a literal compliance
with the schema change would still treat `needs_context` as a normal retry
or terminal block. The reviewer lifecycle slice must add a one-shot
re-dispatch path that forces `review_mode="full_tree"` and bypasses the
implementer retry gate. Repeated `needs_context` then collapses to a block.

### 16.4 Summary `selected_candidates` Semantics

The summary builder draft enumerates all candidates with status in
`{merge_ready, merged}`. That is the merge-queue projection, not the
ranking-selected candidate. For multi-candidate (high-risk) tasks this would
report both implementer candidates as "selected." The summary must either
read the `agentrunway.candidate_ranked` event payload and project the
`selected_candidate_id`, or filter to `status == "merged"` once merging is
the only source of truth for selection. Either choice is fine; doing
neither is wrong.

### 16.5 Missing `state.sqlite` Side Effect in Summarize

When `run.json` is missing and `state.sqlite` is also missing, the
reconstruction fallback returns a `state_db` string that points at a
non-existent file. Callers (`summarize`, `status`, `inspect`) then call
`AgentRunwayDb.open`, which creates an empty SQLite file as a side effect.
This conflicts with the goal that summary commands are read-only diagnostic
tools. Summarize must short-circuit when the SQLite file does not exist and
return a clearly-labeled "no recoverable state" payload instead of
materializing an empty database.

### 16.6 Pre-existing Defects Out of Scope

These defects are visible from the audit but are not in this slice's path.
They should be tracked separately rather than absorbed by a hybrid-worktree
PR that already has a wide blast radius:

- `runner.cancel()` rewrites `run.json` with `status="cancelled"` but never
  calls `db.set_run_status(run_id, "cancelled")`. The DB drifts from the
  on-disk run document.
- `format_run_status` does not yet expose the AgentLens disabled notice as a
  structured field on the status payload, only inside the rendered string.
  Downstream tools that consume the JSON cannot detect "AgentLens disabled"
  without parsing the human-readable suffix.
- Adapter handle JSON is passed to `db.update_worker_handle` as a dict in
  some adapters and as a JSON string in others; this is not a regression
  introduced by this slice but should be normalized when the timing slice
  touches `mark_worker_started`.

## 17. Final Recommendation

Use AgentRunway's current worktree-per-implementer model as the foundation.
Do not replace it with a shared task worktree. Shared task worktrees would make
candidate comparison and scope rejection weaker.

Change the model from "worktree for every role attempt" to:

```text
candidate worktrees for code-producing implementers,
conditional full-tree reviewer worktrees,
ephemeral verifier worktrees,
summary-first host control.
```

This is the best tradeoff for AgentRunway's stated priority: quality first,
then context and resource reduction.
