# agent-runway

`agent-runway` (`agentrunway`) executes approved Superpowers plans through a deterministic Python runner.

Current source of truth:

- Skill contract: `SKILL.md`
- Operator overview: this `README.md`
- Runtime protocol references: `references/`
- Runtime implementation: `scripts/agentrunway/`
- Three-skill comparison notes: `references/execution-comparison.md`

Historical root `docs/superpowers/...` design and plan files may appear in old
commits or experiment notes, but they are not present in the pruned Archive
checkout and should not be treated as current source.

The runner stores state in SQLite under `~/.agentrunway/runs`, does implementation work in isolated git worktrees under `~/.agentrunway/worktrees`, and emits bounded AgentLens v2 trust events under the `agentrunway.*` namespace. The MVP includes a deterministic local adapter for tests and dry runs plus Claude/Codex process adapter wrappers.

## Quick Start

```bash
python3 skills/agent-runway/scripts/agentrunway.py run --plan plan.md --spec spec.md --planning-only
python3 skills/agent-runway/scripts/agentrunway.py lint-plan --plan plan.md --spec spec.md --json
python3 skills/agent-runway/scripts/agentrunway.py status --run <run_id>
python3 skills/agent-runway/scripts/agentrunway.py summarize --run <run_id> --json
```

Use `--adapter local --fake-success` for deterministic end-to-end smoke runs without model calls.

## Invocation Shortcuts

The internal Python script remains supported, but normal use should go through
the short resolver forms:

```bash
agentrunway run --topic <topic> --adapter codex
agentrunway run --latest --adapter claude
agentrunway status --last
agentrunway summarize --last --json
agentrunway inspect --last --json
agentrunway apply --last
```

`--topic` resolves a complete Superpowers design/plan pair under
`docs/superpowers/specs/` and `docs/superpowers/plans/` when the target
workspace contains those directories. Ambiguous topics fail before dispatch and
print candidates. `--last` is scoped to the current workspace id, not the whole
machine.

## Operations Evidence

Every non-planning run writes a frozen `contract.json`, `artifact_graph.json`,
`coverage.json`, and `events.jsonl` under `~/.agentrunway/runs/<workspace>/<run_id>/`.
The contract records the exact Superpowers spec and plan paths, hashes, parsed
tasks, file claims, acceptance commands, adapter, model profile, and `spec_refs`
coverage.

Use:

```bash
python3 skills/agent-runway/scripts/agentrunway.py summarize --run <run_id> --json
python3 skills/agent-runway/scripts/agentrunway.py status --run <run_id>
python3 skills/agent-runway/scripts/agentrunway.py inspect --run <run_id> --json
python3 skills/agent-runway/scripts/agentrunway.py events --run <run_id> --json
python3 skills/agent-runway/scripts/agentrunway.py resume --run <run_id> --dry-run --json
```

AgentLens emission is best-effort. Local evidence remains authoritative when
AgentLens is disabled or unavailable. When AgentLens is available, AgentRunway
posts raw `agentlens.event.v2` envelopes rather than burying them inside a v1
payload wrapper; the nested payload keeps the AgentRunway run id and the
envelope targets the AgentLens container run id.

Normal host operation should start with `summarize`. The summary is bounded and
contains task counts, blocked tasks, selected candidates, worker durations,
recent events, artifact references, and the next operator action. Use
`inspect --json` only when the summary points to a task or artifact that needs
deep diagnosis.

## Operations Quality Engine

AgentRunway computes a shared diagnosis for `status`, `inspect`, and `resume`.
The diagnosis reports the run state, reason, safe actions, manual actions, and
next operator action. High-risk tasks can produce two implementer candidates;
AgentRunway ranks validated candidates deterministically and emits
`agentrunway.candidate_ranked` evidence explaining the selection.

Gate retries are policy-owned. Reviewer `changes_requested` and verifier
`failed` can retry once when the failure is actionable. Verifier `blocked`,
repeated merge conflicts, file-claim violations, and unsafe recovery states stop
with a manual action instead of guessing.

AgentRunway is the only supported AgentLens executor integration. New
observability events use the `agentrunway.*` namespace. CPE/CME workflows, if
present on disk, are independent legacy skills and are not bridged into
AgentRunway or AgentLens by this package.

## Production Supervisor

`agentrunway run --adapter codex` and `agentrunway run --adapter claude` launch worker
processes through the production supervisor. The runner creates worker worktrees,
writes task packets and prompts, supervises process lifecycle, collects
`worker_result.json`, validates committed changed files against file claims,
runs `review_result` and `verification_result` gates, and cherry-picks accepted
commits into the run main worktree.

The supervisor uses quality-first hybrid worktrees:

- run main is persistent for the run and is the only merge target;
- implementer candidates stay isolated and retained until apply or evidence
  archival;
- reviewer attempts default to diff mode, escalating once to full-tree review
  when the reviewer returns `needs_context` or policy requires full-tree review;
- verifier attempts run from the selected candidate head and become cleanup
  eligible after evidence capture;
- failed or malformed worker worktrees are retained for diagnosis.

## Durable Integration Orchestrator

AgentRunway advances run main as soon as a selected candidate passes review and
verification. Dependent tasks start from the latest run-main checkpoint instead
of the original base commit, so accepted earlier work is visible to later tasks.

The runner records workflow events, activity rows, checkpoint rows, and
decision packets in SQLite with JSON artifacts for audit. These records are the
durable evidence `resume` uses to advance from the last completed activity
instead of replaying worker state.

### Durable Orchestrator Hardening

AgentRunway uses checkpoint evidence, not task status alone, to release
dependent work. `inspect`, `summarize`, and `resume --dry-run` share the same
durable projection for latest checkpoint, ready queue, safe wave, blocked
activity, failure class, and required human decision.

Automatic resume actions execute only through registered durable boundary
handlers. Handler-less write actions block instead of being recorded as
executed. Merge resume applies the verified candidate and writes a checkpoint;
checkpoint verification can reconstruct a missing checkpoint row from completed
merge activity output refs. Human-decision failure classes stop with decision
packets so operators can inspect and decide without rerunning completed
activity work.

Review and verification failures are classified through `FailureClassifier`
into recovery classes such as `needs_rebase`, `needs_full_context`,
`needs_plan_fix`, and `needs_infra_fix`.

Reviewer `changes_requested` and verifier `failed` outcomes create one bounded
implementer redispatch with the gate evidence threaded into the next prompt.
The previous candidate remains in the merge queue with a non-mergeable status;
only a later verifier `passed` outcome can promote a fresh candidate to
`merge_ready`.

Use fake CLI fixtures for deterministic tests:

```bash
PATH="$PWD/evals/fixtures/fake-bin:$PATH" ./evals/run.sh
```

Use real Codex/Claude smoke runs only when the local CLIs are authenticated and
model usage is intended. AgentLens emission is best-effort; runner state and
local event artifacts remain authoritative.

`agentrunway apply --run <run_id>` is explicit. It refuses a dirty source
checkout by default and records applied commits in SQLite. Merge conflict
handling aborts the cherry-pick and records the candidate state for retry or
operator review.

Graphify navigation remains a generated project layer. Completion evidence
should record the `graphify update .` command result rather than checking
`graphify-out/` into this skill package.

### Hybrid Scheduler And Failure Barriers

AgentRunway dispatches work from the durable projection. A task enters a worker
worktree only when dependency checkpoints exist and the task is in the current
safe wave. Independent low/medium-risk tasks can share a safe wave. Shared core
control-flow work, broad claims, high-risk tasks, blocked dependencies, stale
activities, and missing checkpoint repairs serialize or stop dispatch.

Failure classes are scheduling barriers. Human-decision classes stop with a
decision packet, repeated `needs_rebase` stops after one checkpoint redispatch,
and missing resume handlers block instead of recording fake progress.
