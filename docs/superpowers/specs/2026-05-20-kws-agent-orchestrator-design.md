# Design: KWS Agent Orchestrator

Date: 2026-05-20
Status: Approved for implementation planning
Owner: KWS

## 1. Summary

Build a new greenfield skill and runner, named `kws-agent-orchestrator` (`KAO`),
that executes plan/spec documents using multiple coding-agent runtimes through
one protocol.

This is not a compatibility merge of `kws-codex-plan-executor` and
`kws-claude-multi-agent-executor`. Those systems are reference material only.
The new executor uses a new state model, new runtime adapter contract, and new
AgentLens event namespace.

Core idea:

```text
plan/spec
  -> KAO skill entrypoint
  -> deterministic Python runner
  -> SQLite control plane
  -> task graph + file claims + parallel waves
  -> runtime adapters
  -> isolated worktrees
  -> review / verify / merge queue
  -> AgentLens kws.kao.* observability
```

The LLM does task work. The runner decides scheduling, isolation, file
ownership, retries, merge order, and AgentLens emission.

## 2. Goals

- One skill protocol usable from Claude Code, Codex, and future hosts.
- One plan/spec execution model across Claude, Codex, Gemini, Aider, and local
  fallback adapters.
- Low orchestrator context use by storing state in SQLite and giving workers
  small task packets, not whole conversations.
- Deterministic scheduling: dependency graph, file claims, parallel waves, retry
  policy, and merge queue are computed by the runner, not improvised by an LLM.
- Isolated implementation worktrees for every implementation worker.
- AgentLens-first visibility for errors, rejected workers, method-audit issues,
  verification evidence, merge status, and improvement opportunities.
- Superpowers bootstrap required for every orchestrator and worker role.
- Model defaults and overrides are explicit, inspectable, and recorded in state.

## 3. Non-Goals

- No reuse of `kws-cpe.*` or `kws-cme.*` AgentLens namespaces.
- No migration layer from old CPE/CME state into KAO state for MVP.
- No web UI in MVP. CLI status and AgentLens visibility come first.
- No direct dependency on Overstory, Bernstein, AWS CLI Agent Orchestrator,
  Codex Orchestrator, Composio Agent Orchestrator, Vibe Kanban, or OpenHands.
  KAO borrows patterns, not code or runtime architecture wholesale.
- No assumption that Codex App `spawn_agent` is always available. It is an
  adapter capability, not the base execution contract.
- No worker direct-write access to AgentLens in MVP. Workers return artifacts to
  the runner; the runner validates, redacts, and emits events.
- No automatic write-back into the source checkout by default. KAO integrates
  changes in an execution worktree first; source checkout application is
  explicit.

## 4. Reference Inputs

KAO should selectively borrow these patterns:

| Reference | Pattern to Adopt | Avoid |
| --- | --- | --- |
| Overstory | Runtime adapter shape, isolated worktrees, SQLite mail bus, merge queue, web UI direction | Direct dependency, maintenance-mode risk, UI-first complexity |
| AWS CLI Agent Orchestrator | Process supervision, tmux-style worker sessions, skill delivery/prompt injection across runtimes | Hard dependency on tmux/MCP as the core control plane |
| Bernstein | Deterministic Python scheduler, worktree per agent, janitor verification, audit trail | Overbuilt compliance machinery in MVP |
| Codex Orchestrator | Codex CLI worker launching and transcript/cost capture ideas | Claude-orchestrates-Codex one-way topology |
| Composio Agent Orchestrator | PR/CI/review reaction loop | Product-specific GitHub/Linear workflow coupling |
| Vibe Kanban / Claude Squad | Operator UX for multiple worktrees and diff review | Manual-first execution as the core model |
| OpenHands CAID | Dependency graph, JSON task instruction, branch/worktree merge, tests-based verification | OpenHands-specific runtime assumptions |
| Ruah / Shard-like patterns | File ownership claims, bounded retries, DAG execution | Small-project assumptions without enough validation |

## 5. Architecture

### 5.1 Components

```text
kws-agent-orchestrator/
  SKILL.md
  references/
    protocol.md
    model-profiles.md
    task-packet.md
    file-claims.md
    runtime-adapters.md
    agentlens-events.md
    superpowers-bootstrap.md
    merge-queue.md
    context-policy.md
    worktree-policy.md
    watchdog.md
    failure-policy.md
  scripts/
    kao.py
    kao/
      db.py
      scheduler.py
      plan_parser.py
      packetizer.py
      file_claims.py
      worktrees.py
      merge_queue.py
      agentlens_emit.py
      method_audit.py
      cost.py
      status.py
      context_policy.py
      watchdog.py
      adapters/
        base.py
        claude.py
        codex.py
        gemini.py
        aider.py
        local.py
```

The skill is thin. It validates invocation shape, points the host agent at the
runner, and explains the protocol. The runner is thick. It owns execution
state, scheduling, worker dispatch, and final validation.

### 5.2 Runtime Data Layout

Persistent runtime state lives outside project source:

```text
~/.kao/
  runs/<workspace_id>/<run_id>/
    state.sqlite
    run.json
    packets/
      task_001.implementer.json
      task_001.reviewer.json
      task_001.verifier.json
    artifacts/
      task_001/
        worker_result.json
        diff.patch
        test_excerpt.txt
    prompts/
      task_001.implementer.prompt.txt
    logs/
      runner.log
      worker_<id>.stdout
      worker_<id>.stderr
  worktrees/<workspace_id>/<run_id>/
    main/
    workers/
      task_001-implementer-001/
      task_001-reviewer-001/
      task_001-verifier-001/
```

The target repo worktree remains clean of KAO runtime artifacts. Worker
worktrees contain only normal repo files and git metadata. By default, accepted
changes are integrated into `~/.kao/worktrees/<workspace_id>/<run_id>/main` and
are not applied back to the source checkout unless the user runs
`kao apply --run <run_id>` or sets `apply_to_source=on`.

`workspace_id` is generated from a canonicalized repo identity:

```text
slug(repo_basename)-sha256(realpath(git_root) + remote_url + git_common_dir)[0:10]
```

If the computed directory already exists for a different repo identity, KAO
extends the hash to 16 characters. If it still collides, KAO appends a monotonic
numeric suffix recorded in SQLite. It must never reuse an existing worktree path
unless the stored `run_id`, `workspace_id`, git root, and branch metadata match.

Run IDs use a human-readable slug plus a timestamp and short nonce:

```text
<plan_slug>-YYYYMMDD-HHMMSS-<base32_nonce_5>
```

Worktree branches use a reserved prefix:

```text
kao/<run_id>/main
kao/<run_id>/task_001-implementer-001
kao/<run_id>/task_001-reviewer-001
kao/<run_id>/task_001-verifier-001
```

Before creating a branch or worktree, KAO checks `git show-ref`, `git worktree
list --porcelain`, the filesystem path, and its SQLite registry. Any conflict
causes a new nonce to be generated; KAO does not overwrite existing paths.

Gitignored files are not copied into worktrees by default. Repos may opt in with
`.kao-worktreeinclude`, using `.gitignore`-style patterns. Only ignored files
matching that allowlist may be copied, and tracked files are never duplicated
through this mechanism.

### 5.3 SQLite Control Plane

SQLite is the source of truth for KAO execution. Suggested tables:

| Table | Purpose |
| --- | --- |
| `runs` | Invocation, workspace, plan/spec refs, status, model profile, AgentLens run id |
| `tasks` | Parsed task graph, risk, phase, dependencies, status |
| `task_packets` | Packet hash, prompt path, context refs, allowed/forbidden scopes |
| `file_claims` | `owned`, `shared_append`, `read_only`, `forbidden` claims per task |
| `waves` | Deterministic parallel execution groups |
| `workers` | Runtime, role, model, reasoning, PID/session, lifecycle |
| `messages` | Runner-worker mailbox, normalized from runtime-specific channels |
| `artifacts` | Result JSON, diffs, logs, verification excerpts |
| `merge_queue` | Candidate commits/patches waiting for janitor gates |
| `agentlens_events` | Event emission attempts, timestamps, failures |
| `cost_ledger` | Runtime/model/token/cost observations when available |
| `method_audits` | Superpowers/TDD/review/verification evidence |
| `context_snapshots` | Orchestrator compact/rotation snapshots and resume digests |
| `worktree_registry` | Repo identity, branch, path, run id, lifecycle, cleanup eligibility |
| `resource_locks` | Non-file locks such as ports, databases, browsers, or external APIs |
| `watchdog_events` | Stalls, nudges, compactions, rotations, retries, and cancellations |

SQLite gives the orchestrator low context pressure: every resume can ask the DB
what happened instead of keeping all worker details in conversation.

## 6. Execution Flow

### 6.1 High-Level Flow

```text
1. Parse invocation and model profile.
2. Open KAO run and SQLite DB.
3. Open AgentLens container run.
4. Parse plan/spec into task graph.
5. Build file claims and task packets.
6. Compute deterministic waves.
7. For each wave:
   a. Create worker worktrees.
   b. Dispatch workers through runtime adapters.
   c. Collect worker results.
   d. Validate output schema and method audit.
   e. Check diffs against file claims.
   f. Queue merge candidates.
   g. Run reviewer/verifier janitor gates.
   h. Apply accepted merges to main execution worktree.
8. Run final verification.
9. Emit final AgentLens events and close AgentLens run.
10. Print concise completion or blocked report.
```

### 6.2 Task Packet

Every worker receives a compact packet. It never receives the entire source
conversation by default.

```json
{
  "schema": "kws.kao.task_packet.v1",
  "run_id": "auth-refactor-20260520-151000",
  "task_id": "task_003",
  "role": "implementer",
  "objective": "Implement token refresh retry handling.",
  "spec_refs": [
    {"id": "S2.1", "excerpt_ref": "spec:S2.1"},
    {"id": "S2.4", "excerpt_ref": "spec:S2.4"}
  ],
  "dependencies": ["task_001"],
  "allowed_write_globs": ["src/auth/**", "tests/auth/**"],
  "forbidden_write_globs": [".git/**", "graphify-out/**", "docs/wiki/**"],
  "file_claims": [
    {"path": "src/auth/session.ts", "mode": "owned"},
    {"path": "tests/auth/session.test.ts", "mode": "owned"}
  ],
  "required_skills": ["using-superpowers", "test-driven-development"],
  "acceptance_commands": ["npm test -- tests/auth/session.test.ts"],
  "output_schema": "kws.kao.worker_result.v1",
  "model_assignment": {
    "runtime": "codex",
    "model": "gpt-5.5",
    "reasoning_effort": "high"
  }
}
```

### 6.3 File Claim Modes

| Mode | Meaning |
| --- | --- |
| `owned` | Exactly one active worker may modify the file. |
| `shared_append` | Multiple workers may append non-overlapping entries, e.g. changelog or generated index. Requires post-diff structural check. |
| `read_only` | Worker may inspect but not modify. |
| `forbidden` | Worker must not read or write unless explicitly elevated by the runner. |

Forbidden wins over every other claim. Any out-of-scope diff rejects the worker
result before merge.

### 6.4 Wave Scheduling

The scheduler builds waves from:

- explicit task dependencies,
- inferred dependencies from overlapping `owned` file claims,
- resource keys such as `db`, `port:3000`, or `external-api`,
- risk level,
- user-specified serial markers,
- adapter capability limits.

Two tasks may run in the same wave only when their write scopes, resource keys,
and dependency edges do not conflict.

### 6.5 Parallel Roles

KAO supports the existing multi-agent pattern of separate implementation,
review, verification, and recovery agents. The difference is that the runner,
not a parent prompt, creates these roles from explicit task state.

Default policy:

```yaml
parallelism:
  max_workers: 4
  candidates_per_task: 1
  high_risk_candidates_per_task: 2

review:
  implementer_scope: task
  reviewer_scope: task
  verifier_scope: acceptance_command_or_wave
  recovery_scope: failed_task
```

Meaning:

- Each normal task gets one implementer candidate.
- High-risk tasks may get two implementer candidates for comparison.
- Reviewers inspect task outputs against the task packet, file claims, and
  acceptance criteria.
- Verifiers run acceptance commands at the narrowest useful boundary: task when
  possible, wave when shared dependencies make that more accurate.
- Recovery workers are spawned only for failed tasks with actionable evidence.

Worker identity is persisted with `role`, `task_id`, `candidate_index`,
`attempt`, `runtime`, `model`, `reasoning_effort`, and `parent_worker_id` where
applicable.

### 6.6 Context Policy

KAO treats context pressure as a control-plane problem. The orchestrator should
not accumulate full worker transcripts, full prompts, command output, or raw
diffs. Those live in artifacts and SQLite. The orchestrator sees bounded
digests and artifact references.

Default policy:

```yaml
context_policy:
  compact_at_ratio: 0.65
  rotate_at_ratio: 0.80
  hard_stop_at_ratio: 0.90
  max_inline_worker_summary_chars: 1200
  max_inline_log_excerpt_chars: 4000
  full_transcripts: artifact_only
  orchestration_snapshot: auto
```

The runner maintains a compact orchestration snapshot containing only:

- run status,
- current wave,
- open blockers,
- merge queue state,
- recent decision deltas,
- AgentLens and artifact refs,
- next required action.

If the active host supports native context compaction, the adapter may trigger
it when the compact threshold is crossed. If compaction is not available or the
session remains too large, KAO rotates orchestration into a fresh session using
the latest snapshot. Rotation must not require replaying worker transcripts.

### 6.7 Worker Communication

Workers do not communicate directly with one another in MVP. Any cross-worker
message goes through the SQLite mailbox and is mediated by the runner. The
runner validates the message type, strips oversized or unsafe payloads, stores
the original as an artifact if needed, and forwards only a bounded summary or
artifact reference.

This keeps the execution graph deterministic and prevents a noisy worker from
polluting other workers' context.

### 6.8 Watchdog

The watchdog is part of MVP because unattended multi-agent execution otherwise
stalls silently.

It records and reacts to:

- no heartbeat,
- repeated command loops,
- context overflow or compaction prompts,
- stuck permission prompts,
- timeout without file or commit progress,
- dead process or missing session,
- repeated malformed JSON output.

Default action ladder:

```text
observe -> nudge -> compact or rotate -> retry -> reject/block
```

Watchdog actions are recorded in SQLite and emitted to AgentLens as compact
`kws.kao.watchdog_event` events where useful.

### 6.9 Merge Queue

Implementation workers do not write directly into the main execution worktree.
They produce a commit or patch in their worker worktree. The runner queues it:

```text
worker worktree commit
  -> diff scope validation
  -> review gate
  -> verification gate
  -> dry-run merge/cherry-pick
  -> apply to main execution worktree
  -> record merge_applied
```

Default merge strategy: worker produces one commit; runner cherry-picks that
commit into `~/.kao/worktrees/<workspace_id>/<run_id>/main`. Patch fallback is
allowed when a runtime cannot reliably commit.

## 7. Runtime Adapter Contract

Every runtime adapter implements the same interface:

```python
class RuntimeAdapter:
    def detect(self) -> CapabilityReport: ...
    def prepare_worker(self, packet: TaskPacket) -> PreparedWorker: ...
    def launch_worker(self, prepared: PreparedWorker) -> WorkerHandle: ...
    def poll_worker(self, handle: WorkerHandle) -> WorkerStatus: ...
    def send_message(self, handle: WorkerHandle, message: WorkerMessage) -> None: ...
    def collect_result(self, handle: WorkerHandle) -> WorkerResult: ...
    def cancel_worker(self, handle: WorkerHandle) -> None: ...
    def extract_cost(self, handle: WorkerHandle, result: WorkerResult) -> CostRecord: ...
```

### 7.1 Capability Report

Adapters must declare capabilities. The scheduler uses these to choose safe
routing.

```json
{
  "runtime": "codex",
  "supports_headless": true,
  "supports_app_subagents": true,
  "supports_json_output": true,
  "supports_mid_task_message": false,
  "supports_cost_extract": "best_effort",
  "supports_hard_tool_guard": false,
  "supports_skill_injection": true,
  "supports_worktree": true
}
```

### 7.2 Initial Adapters

| Adapter | MVP Status | Notes |
| --- | --- | --- |
| `claude` | Required | Use Claude Code/headless where available. Can use process supervision and sub-worktrees. |
| `codex` | Required | Prefer stable CLI/headless execution. Codex App `spawn_agent` is optional capability. |
| `local` | Required fallback | Runs task locally in current host session for dry-run or no-agent mode. |
| `gemini` | Later | Add once core scheduler and packet format are stable. |
| `aider` | Later | Useful for patch-oriented tasks; likely limited mid-task control. |

## 8. Model Profiles

Model assignment is first-class state. Defaults must be explicit, printed at run
start, persisted in SQLite, and emitted to AgentLens in `kws.kao.run_started`
and `kws.kao.worker_dispatched`.

### 8.1 Default Profiles

| Profile | Orchestrator Runtime | Orchestrator Model | Orchestrator Reasoning | Worker Runtime | Worker Model | Worker Reasoning |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-default` | `codex` | `gpt-5.5` | `xhigh` | `codex` | `gpt-5.5` | `high` |
| `claude-default` | `claude` | `opus` | `high` | `claude` | `opus` | `high` |
| `same-host` | host runtime | host default profile | host default profile | same as orchestrator | profile default | profile default |
| `mixed` | explicit | explicit | explicit | scheduler-selected | role profile | role profile |

Interpretation:

- Codex main orchestrator default: GPT-5.5, extra-high reasoning (`xhigh`).
- Codex implementation worker default: GPT-5.5, high reasoning.
- Claude main orchestrator default: Opus, high reasoning.
- Claude implementation worker default: Opus, high reasoning.
- Reviewer, verifier, docs, and recovery workers default to the worker profile
  unless explicitly overridden by role.

### 8.2 Invocation Overrides

The skill invocation should accept concise overrides:

```text
[$kws-agent-orchestrator] plan=plans/auth.md spec=specs/auth.md
  runtime=codex
  model_profile=codex-default
```

Detailed overrides:

```text
orchestrator_runtime=codex
orchestrator_model=gpt-5.5
orchestrator_reasoning=xhigh
worker_runtime=codex
worker_model=gpt-5.5
worker_reasoning=high
```

Claude override example:

```text
orchestrator_runtime=claude
orchestrator_model=opus
orchestrator_reasoning=high
worker_runtime=claude
worker_model=opus
worker_reasoning=high
```

Role-specific override example:

```text
implementer_runtime=codex
implementer_model=gpt-5.5
implementer_reasoning=high
reviewer_runtime=claude
reviewer_model=opus
reviewer_reasoning=high
verifier_runtime=codex
verifier_model=gpt-5.5
verifier_reasoning=high
```

### 8.3 Config File

For repeatability, KAO also reads a repo-local optional config:

```yaml
# kao.yaml
default_profile: codex-default
profiles:
  codex-default:
    orchestrator:
      runtime: codex
      model: gpt-5.5
      reasoning_effort: xhigh
    workers:
      default:
        runtime: codex
        model: gpt-5.5
        reasoning_effort: high
  claude-default:
    orchestrator:
      runtime: claude
      model: opus
      reasoning_effort: high
    workers:
      default:
        runtime: claude
        model: opus
        reasoning_effort: high
```

Precedence:

```text
invocation args > kao.yaml > built-in profile defaults
```

If a runtime cannot honor a requested model or reasoning level, the adapter must
halt before dispatch with a clear `unsupported_model_assignment` blocker. It
must not silently downgrade.

## 9. Superpowers Protocol

All orchestrator and worker roles must bootstrap superpowers.

Required for every role:

```text
1. Invoke/read using-superpowers.
2. Load role-required skills.
3. Do not edit, review, verify, or summarize until bootstrap is complete.
4. Return method_audit evidence.
```

Implementation roles require `test-driven-development` unless the packet marks
the task as docs-only/config-only/generated-only and the runner accepts the
waiver.

Worker result must include:

```json
{
  "method_audit": {
    "using_superpowers": {
      "status": "applied",
      "evidence": "bootstrap completed before role work"
    },
    "required_role_skills": [
      {
        "name": "test-driven-development",
        "status": "applied",
        "red_evidence_ref": "artifact:test-red.txt",
        "green_evidence_ref": "artifact:test-green.txt"
      }
    ],
    "status": "passed"
  }
}
```

Missing or malformed method audit causes `worker_rejected` and
`method_audit_violation`.

## 10. AgentLens Integration

AgentLens is the observability and evaluation layer, not KAO's execution source
of truth.

```text
KAO SQLite DB = execution state
AgentLens = append-only timeline, evidence, failures, evaluation surface
```

### 10.1 Run Lifecycle

At KAO run start:

```bash
agentlens run-open \
  --agent kws-kao-orchestrator \
  --workspace "$WORKTREE_ABS" \
  --meta kao_run_id="$KAO_RUN_ID" \
  --meta plan_hash="$PLAN_HASH" \
  --meta spec_hash="$SPEC_HASH"
```

The returned AgentLens run id is stored in `runs.agentlens_run_id`.

At KAO run close:

```bash
agentlens run-close \
  --run "$AGENTLENS_RUN_ID" \
  --outcome "$OUTCOME" \
  --summary "$SUMMARY"
```

AgentLens outcome mapping:

| KAO Outcome | AgentLens Outcome |
| --- | --- |
| `finished` | `success` |
| `failed` | `failed` |
| `blocked` | `partial` |
| `cancelled` | `cancelled` |
| unknown/ambiguous | `unknown` |

### 10.2 Event Namespace

KAO uses only the new namespace:

```text
kws.kao.run_started
kws.kao.task_planned
kws.kao.file_claimed
kws.kao.wave_started
kws.kao.worker_dispatched
kws.kao.superpowers_bootstrapped
kws.kao.worker_result
kws.kao.review_result
kws.kao.verification_result
kws.kao.merge_queued
kws.kao.merge_applied
kws.kao.worker_rejected
kws.kao.method_audit_violation
kws.kao.context_snapshot
kws.kao.watchdog_event
kws.kao.blocker
kws.kao.run_finished
```

No `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*` events are emitted by KAO.

### 10.3 Payload Envelope

All KAO events use a compact payload:

```json
{
  "schema": "kws.kao.event.v1",
  "kao_run_id": "auth-refactor-20260520-151000",
  "phase": "implementation",
  "task_id": "task_003",
  "worker_id": "worker_007",
  "runtime": "codex",
  "role": "implementer",
  "model": "gpt-5.5",
  "reasoning_effort": "high",
  "outcome": "success",
  "severity": "info",
  "summary": "Implemented token refresh retry handling.",
  "evidence": {
    "kind": "test",
    "status": "passed",
    "command_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "artifact_ref": "kao://runs/archive-a13f9c2b/auth-refactor-20260520-151000/artifacts/task_003/test_excerpt.txt"
  },
  "privacy": {
    "absolute_paths": "redacted",
    "full_prompts": "not_stored",
    "full_command_output": "excerpted"
  }
}
```

Rules:

- No raw full prompt.
- No full command output.
- No absolute home paths.
- No secret-like values.
- Use hashes and artifact refs for large evidence.
- Payload summary should stay small enough for fast AgentLens queries.

### 10.4 Worker Emission Rule

Workers do not call AgentLens directly in MVP. They write result JSON and
candidate events to the run artifact directory. The runner validates and emits.

This keeps:

- one writer policy,
- redaction centralized,
- event schemas consistent,
- failed workers from polluting AgentLens with untrusted payloads.

Worker child runs are configurable. The MVP default is parent-only: one
AgentLens run per KAO execution, with `task_id` and `worker_id` distinguishing
worker events. If `agentlens_child_runs=on`, KAO may open child runs for workers
after parent-only emission is stable. Child run failures follow the same
best-effort policy and must never block execution.

### 10.5 AgentLens Failure Policy

AgentLens failure must never stop KAO execution.

The runner records emit attempts in SQLite:

| Field | Meaning |
| --- | --- |
| `agentlens_status` | `enabled`, `disabled`, `degraded` |
| `agentlens_run_id` | Container run id or null |
| `last_agentlens_event_at` | Last successful emit timestamp |
| `failed_emit_count` | Count of failed emits |
| `first_emit_error` | Short redacted error |

All CLI calls are best-effort:

```bash
agentlens event append ... 2>/dev/null || true
```

## 11. Worker Output Schema

Worker results are machine-readable first:

```json
{
  "schema": "kws.kao.worker_result.v1",
  "worker_id": "worker_007",
  "task_id": "task_003",
  "role": "implementer",
  "status": "success",
  "changed_files": ["src/auth/session.ts", "tests/auth/session.test.ts"],
  "commit": "abc1234",
  "summary": "Implemented retry handling.",
  "commands_run": [
    {
      "command_hash": "sha256:...",
      "kind": "test",
      "status": "passed",
      "excerpt_ref": "artifact:test_excerpt.txt"
    }
  ],
  "method_audit": {
    "using_superpowers": {"status": "applied"},
    "status": "passed"
  },
  "residual_risks": []
}
```

Malformed output is a worker failure, not a runner failure. The runner may retry
with a stricter prompt once, then reject.

## 12. Failure Handling

| Failure | Runner Action |
| --- | --- |
| Plan parse fails | Halt before worktree creation; emit blocker if AgentLens run exists |
| Unsupported model assignment | Halt before dispatch |
| Worker timeout | Cancel worker, record failure, retry within budget |
| Worker malformed JSON | Retry once with schema reminder; then reject |
| Missing superpowers audit | Reject worker; emit method audit violation |
| Out-of-scope diff | Reject worker; do not merge |
| Merge conflict | Rebase/retry once if deterministic; else serialize dependent task or halt |
| Verification failure | Return to implementer retry if root cause clear; else halt with evidence |
| AgentLens unavailable | Continue with `agentlens_status=degraded` |
| SQLite write failure | Halt; execution state is unsafe |
| Worktree creation failure | Halt; do not run in source checkout |
| Worktree or branch name collision | Generate a new nonce; halt if registry metadata is inconsistent |
| Context threshold crossed | Snapshot, compact if supported, rotate if needed |
| Stuck permission prompt | Nudge or cancel according to adapter policy; never auto-approve destructive operations |
| Budget exceeded | Emit warning by default; pause only when `budget_action=pause` |

Retry budgets:

- implementation worker: 2 retries by default,
- reviewer/verifier: 1 retry for infra/malformed output,
- merge conflict repair: 1 deterministic retry,
- same root cause repeated 3 times: halt.

## 13. CLI Surface

Skill invocation:

```text
[$kws-agent-orchestrator] plan=plans/auth.md spec=specs/auth.md
```

Runner equivalent:

```bash
python3 scripts/kao.py run \
  --plan plans/auth.md \
  --spec specs/auth.md \
  --model-profile codex-default
```

Status:

```bash
python3 scripts/kao.py status --run <run_id>
python3 scripts/kao.py inspect --run <run_id> --task task_003
python3 scripts/kao.py events --run <run_id>
python3 scripts/kao.py resume --run <run_id>
python3 scripts/kao.py cancel --run <run_id>
python3 scripts/kao.py apply --run <run_id>
python3 scripts/kao.py clean --older-than 7d --successful
```

## 14. Testing Strategy

### 14.1 Unit Tests

- Invocation parser.
- Model profile precedence.
- Runtime capability negotiation.
- Plan parser.
- Spec section manifest builder.
- File claim conflict detection.
- Wave scheduler.
- Task packet builder.
- Worker result schema validation.
- Method audit validation.
- AgentLens payload redaction and best-effort failure handling.
- Merge queue state machine.
- Worktree naming, branch collision detection, and registry consistency.
- Context snapshot generation and rotation thresholds.
- Resource lock conflict detection.
- Watchdog stall classification.

### 14.2 Integration Tests

- Fake runtime adapter executes two independent tasks in parallel.
- Fake runtime adapter produces out-of-scope diff; runner rejects it.
- Fake runtime adapter omits superpowers evidence; runner rejects it.
- Merge queue applies two disjoint commits.
- Merge conflict forces serialization or blocker.
- AgentLens unavailable; run still finishes with degraded observability.
- Model override is persisted and reflected in worker packets.
- Resume after runner crash continues from SQLite state.
- Worktree naming collision produces a new nonce without overwriting existing
  paths.
- Context threshold creates a snapshot and resumes without worker transcript
  replay.
- Resource lock conflict serializes otherwise independent tasks.
- Watchdog rejects a stalled worker after the configured action ladder.

### 14.3 End-to-End Fixtures

Minimum fixtures:

| Fixture | Purpose |
| --- | --- |
| `01-single-doc-task` | No code changes, docs-only TDD waiver |
| `02-two-independent-code-tasks` | Parallel wave and merge queue |
| `03-overlapping-file-claims` | Forced serialization |
| `04-worker-method-audit-missing` | Hard rejection |
| `05-verification-failure-retry` | Retry path |
| `06-agentlens-unavailable` | Non-blocking observability |
| `07-model-profile-overrides` | Codex/Claude profile assignment |
| `08-resume-after-crash` | SQLite resume |
| `09-worktree-name-collision` | Safe unique path and branch generation |
| `10-context-rotation` | Snapshot-based resume without full transcript |
| `11-resource-lock-serialization` | Non-file lock scheduling |
| `12-watchdog-stalled-worker` | Nudge/rotate/retry/reject lifecycle |

## 15. MVP Scope

MVP includes:

- `kws-agent-orchestrator` skill.
- Python runner.
- SQLite control plane.
- Claude adapter.
- Codex adapter.
- Local fake adapter for tests.
- Task packet builder.
- File claim validator.
- Deterministic wave scheduler.
- Isolated worktree creation.
- Merge queue.
- Reviewer/verifier janitor gates.
- Superpowers method audit enforcement.
- AgentLens `kws.kao.*` emission.
- CLI status/inspect/resume.
- Explicit `apply_to_source=off` default with `kao apply --run <run_id>`.
- Worktree naming collision avoidance and registry checks.
- `.kao-worktreeinclude` for opt-in ignored-file copying.
- Context snapshot, compaction, and rotation policy.
- Watchdog for stalled workers and context overflow.
- SQLite-mediated worker communication.
- Resource locks for non-file shared resources.
- Cleanup and retention commands.

MVP excludes:

- Web UI.
- GitHub PR automation.
- Linear/Jira integration.
- Cloud execution.
- HMAC/signed audit cards.
- Legacy CPE/CME state import.
- Gemini/Aider production adapters.
- AgentLens child-run implementation as a required path. The setting is
  accepted by design, but parent-only must be stable first.

## 16. Approved Policy Decisions

These decisions are accepted for implementation planning:

1. **Canonical name:** `kws-agent-orchestrator`, alias `kao`.
2. **MVP host targets:** Claude Code and Codex CLI/App hosts, with CLI/headless
   adapters as the stable execution path.
3. **Codex App `spawn_agent`:** optional optimization only; correctness must not
   depend on it.
4. **Default runtime behavior:** same runtime as orchestrator unless the user
   explicitly sets `worker_runtime=mixed` or a role-specific override.
5. **Worker AgentLens child runs:** configurable; default parent-only.
6. **UI timing:** no KAO web UI in MVP.
7. **Merge strategy:** worker commit plus cherry-pick; patch apply fallback.
8. **High-risk approval:** autonomous by default; halt for destructive
   operations, missing acceptance criteria, and out-of-repo file claims.
9. **Budget policy:** support `budget=<amount>` and
   `budget_action=warn|pause|off`; default `warn`.
10. **Superpowers failure policy:** hard reject for all roles, including
    read-only reviewer and verifier roles.
11. **Config file name:** `kao.yaml`.
12. **Legacy observability:** no CPE/CME event emission or state import in MVP.
13. **Source checkout policy:** default `apply_to_source=off`; explicit apply
    required.
14. **Worktree naming:** use workspace identity hashing, run nonce, branch/path
    registry, and collision checks before creation.
15. **Worktree env copying:** `.kao-worktreeinclude` opt-in only.
16. **Watchdog:** included in MVP for context overflow, stalled workers, dead
    sessions, permission prompts, and repeated malformed output.
17. **Context management:** bounded summaries, artifact refs, snapshots,
    compaction, and rotation thresholds are part of MVP.
18. **Inter-worker communication:** runner-mediated SQLite mailbox only.
19. **Audit integrity:** artifact hashes in MVP; HMAC signed audit chain later.
20. **Cleanup/retention:** successful worktrees retained 7 days by default;
    failed or blocked worktrees retained 30 days by default.
21. **Resource locks:** non-file resource keys participate in scheduling.

## 17. Design Rationale

The most important design choice is to keep orchestration deterministic. If the
parent agent decides task splitting, worker routing, merge order, and retries
from conversation context, the system repeats the weaknesses of existing
single-skill orchestrators. A small runner with a SQLite control plane gives the
system stable state, replayability, and low context use.

The second key choice is to treat runtime adapters as replaceable. Claude,
Codex, Gemini, and Aider differ in model controls, session management, JSON
output reliability, cost extraction, and mid-task messaging. KAO should not hide
those differences; it should negotiate capabilities and halt when a requested
profile cannot be honored.

The third key choice is to put AgentLens behind the runner, not the workers.
AgentLens becomes a reliable view of what the runner accepted as true, not a
dumping ground for untrusted worker claims.

The fourth key choice is to make worktree isolation the default. Workers write
in isolated checkouts, accepted commits land in the execution worktree, and the
source checkout is modified only through an explicit apply step.

The fifth key choice is to control context by architecture rather than by
cleanup. The orchestrator receives bounded state digests and artifact
references. Full transcripts, prompts, logs, and diffs stay outside the parent
conversation.

## 18. Approval Criteria

This design is ready for implementation planning when:

- The user approves the greenfield KAO direction.
- The default model profiles are accepted.
- The approved policy decisions in section 16 are accepted.
- The implementation plan scopes MVP only, leaving UI and additional adapters
  for later phases.
