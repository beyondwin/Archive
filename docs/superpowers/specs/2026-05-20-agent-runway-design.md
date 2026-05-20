# Design: AgentRunway

Date: 2026-05-20
Status: Approved for implementation planning (A/B/C/D-tier critique patches applied; E-tier defect patches applied; re-approval pending)
Owner: KWS
Revision: 2026-05-20d — E-tier defect patches applied. Fixes pre/post-commit tree extraction primitive (§9.1 now uses `git worktree add --detach` instead of incorrect `git stash`); multi-commit worker output (`commits[]`) with merge/apply cascade (§§6.9, 9.1, 11, 13.4); `shared_append` base reference (wave base commit, not moving `main` HEAD); operational semantics of merge-conflict re-dispatch (§§6.9, 12); semaphore primitive and stale-slot reclamation (§5.2.2); reattach handle reconstruction (§7.1); reviewer status enum, findings rule, and review-round budget separate from failure-retry budget (§11.1); main exec worktree provenance via `git worktree add` (§5.2); cross-workspace collision detection via global registry at `~/.agentrunway/registry.sqlite` (§5.2); orphan verify-worktree reclamation on runner crash (§12). Adds: per-task wall-clock timeout, sandbox tier and LFS in packet (§6.2); `network_egress` allowlist (§7.0); reconcile-step network note (§6.3.1); candidate selection rule for high-risk dual-implementer tasks (§6.5); watchdog wording aligned with polling model (§6.8); `fs_scope` enforcement realism (§15); `serial: false` semantics and `schemas/` subdir (§§5.1, 6.1.5); §14.2 integration tests for the new behaviors. New §16 entries 26–31.
Revision history: 2026-05-20c — A/B/C/D-tier critique patches (workspace-hash canonicalization, branch base policy, dirty-source refusal, submodule/LFS defaults, concurrent-run quota semaphore, `shared_append` grammar, context-ratio denominator, full `WorkerStatus`, reasoning-effort abstraction, configurable AgentLens namespace prefix, review/verification schemas with required checks, cost-extract fallback, deterministic merge-conflict policy, skill→runner control flow, `agentrunway apply` strategies, retention/secrets policy, schema versioning).
Implementation Plan: `docs/superpowers/plans/2026-05-20-agent-runway.md`

## 1. Summary

Build a new greenfield skill and runner, named `agent-runway` (`AgentRunway`),
that executes plan/spec documents using multiple coding-agent runtimes through
one protocol.

This is not a compatibility merge of `kws-codex-plan-executor` and
`kws-claude-multi-agent-executor`. Those systems are reference material only.
The new executor uses a new state model, new runtime adapter contract, and new
AgentLens event namespace.

Core idea:

```text
plan/spec
  -> AgentRunway skill entrypoint
  -> deterministic Python runner
  -> SQLite control plane
  -> task graph + file claims + parallel waves
  -> runtime adapters
  -> isolated worktrees
  -> review / verify / merge queue
  -> AgentLens agentrunway.* observability
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
- No migration layer from old CPE/CME state into AgentRunway state for MVP.
- No web UI in MVP. CLI status and AgentLens visibility come first.
- No direct dependency on Overstory, Bernstein, AWS CLI Agent Orchestrator,
  Codex Orchestrator, Composio Agent Orchestrator, Vibe Kanban, or OpenHands.
  AgentRunway borrows patterns, not code or runtime architecture wholesale.
- No assumption that Codex App `spawn_agent` is always available. It is an
  adapter capability, not the base execution contract.
- No worker direct-write access to AgentLens in MVP. Workers return artifacts to
  the runner; the runner validates, redacts, and emits events.
- No automatic write-back into the source checkout by default. AgentRunway integrates
  changes in an execution worktree first; source checkout application is
  explicit.

## 4. Reference Inputs

AgentRunway should selectively borrow these patterns:

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

### 5.0 Roles & Surfaces

AgentRunway has three execution surfaces. Each has a different lifecycle, state model,
and context budget. Confusing them is the most common source of design drift.

| Surface | Process | LLM | State | Lifetime |
| --- | --- | --- | --- | --- |
| Host session | Claude Code or Codex CLI/App where the user invoked the skill | Yes (host model) | Conversation only | User session |
| Runner | `scripts/agentrunway.py` Python process | No | SQLite + filesystem | Per `agentrunway run` |
| Worker | Adapter-launched CLI/headless session in a worktree | Yes (worker model) | Task packet + worktree | Per task attempt |

Responsibilities:

- **Host session**: invokes the skill, shells out to the runner, surfaces
  status to the user, and applies accepted runs to the source checkout on
  explicit request. It does not own execution state and does not receive worker
  transcripts.
- **Runner**: deterministic scheduling, file claims, worktree lifecycle, merge
  queue, redaction, AgentLens emission. It is the only writer to SQLite and
  AgentLens. It has no LLM and no conversation.
- **Worker**: performs one task attempt in one worktree, returns a result
  envelope. It never writes to SQLite or AgentLens directly.

The context policy in §6.6 governs the **host session**, not the runner. The
runner's state lives in SQLite and does not compact. Workers run to completion
inside their own bounded context; if they exceed it, the watchdog (§6.8)
reacts.

### 5.1 Components

```text
agent-runway/
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
    schemas/
      task_packet.v1.json
      worker_result.v1.json
      review_result.v1.json
      verification_result.v1.json
      event.v1.json
  scripts/
    agentrunway.py
    agentrunway/
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

Source-of-truth policy: this design document is the source of truth for AgentRunway
behavior. Files under `references/` are normative *expansions* of specific
sections (e.g. `runtime-adapters.md` expands §7) but must not contradict the
design. When the runner code, the design doc, and a reference file disagree,
the design doc wins; reference files are updated to match.

### 5.2 Runtime Data Layout

Persistent runtime state lives outside project source:

```text
~/.agentrunway/
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

The target repo worktree remains clean of AgentRunway runtime artifacts. Worker
worktrees contain only normal repo files and git metadata. By default, accepted
changes are integrated into `~/.agentrunway/worktrees/<workspace_id>/<run_id>/main` and
are not applied back to the source checkout unless the user runs
`agentrunway apply --run <run_id>` or sets `apply_to_source=on`.

`~/.agentrunway/worktrees/<workspace_id>/<run_id>/main` is created via `git worktree add
<path> -b agentrunway/<run_id>/main <base_commit_sha>` against the source repo's git
directory (`git rev-parse --git-common-dir`). It shares git objects with the
source checkout, which is load-bearing for `agentrunway apply` (§13.4) — cherry-picking
from this worktree into the source checkout does not require `git fetch` because
the commits are reachable in the same object store. Worker worktrees fork from
`agentrunway/<run_id>/main` the same way. If the source repo is a bare clone or has no
shared git dir reachable from `~/.agentrunway/worktrees/...`, `agentrunway run` halts with
`unreachable_source_git_dir` rather than silently degrading to a clone.

**Global workspace registry.** Per-workspace SQLite (§5.3 `worktree_registry`)
cannot detect collisions *across* workspaces — by definition it lives inside a
workspace. A global registry at `~/.agentrunway/registry.sqlite` maps
`workspace_id → (canonical_inputs_hash, source_git_dir, created_at, last_seen_at)`
and is the authority for "does the computed hash collide with a different repo
identity?" before extending the hash or appending the monotonic suffix. The
global registry is also append-only for `run_id → workspace_id`, so a partial
crash that loses per-workspace SQLite can still locate orphan worktrees for
cleanup. Concurrent writes to the global registry use SQLite's default rollback
journal + `BEGIN IMMEDIATE`; contention is negligible because writes are rare
(workspace creation, run open, run close, cleanup).

`workspace_id` is generated from a canonicalized repo identity:

```text
slug(repo_basename)-sha256(canonical_inputs)[0:10]

canonical_inputs =
  realpath(main_git_dir) + "\n" +
  (remote_url or "")      + "\n" +
  main_branch_ref
```

`main_git_dir` is resolved via `git rev-parse --git-common-dir`, then
`realpath`'d, so the value is identical whether invoked from the main checkout
or any linked worktree. Empty `remote_url` is normalized to the empty string,
not omitted, so local-only repos hash deterministically. `main_branch_ref` is
the symbolic ref of the repo's primary branch (e.g. `refs/heads/main`); it
stabilizes the hash across reclones.

If the computed directory already exists for a different repo identity, AgentRunway
extends the hash to 16 characters. If it still collides, AgentRunway appends a monotonic
numeric suffix recorded in SQLite. It must never reuse an existing worktree path
unless the stored `run_id`, `workspace_id`, git root, and branch metadata match.

Run IDs use a human-readable slug plus a timestamp and short nonce:

```text
<plan_slug>-YYYYMMDD-HHMMSS-<base32_nonce_5>
```

Worktree branches use a reserved prefix:

```text
agentrunway/<run_id>/main
agentrunway/<run_id>/task_001-implementer-001
agentrunway/<run_id>/task_001-reviewer-001
agentrunway/<run_id>/task_001-verifier-001
```

Before creating a branch or worktree, AgentRunway checks `git show-ref`, `git worktree
list --porcelain`, the filesystem path, and its SQLite registry. Any conflict
causes a new nonce to be generated; AgentRunway does not overwrite existing paths.

Gitignored files are not copied into worktrees by default. Repos may opt in with
`.agentrunway-worktreeinclude`, using `.gitignore`-style patterns. Only ignored files
matching that allowlist may be copied, and tracked files are never duplicated
through this mechanism. Files whose path or content matches a configured
secret pattern are excluded from copy even if the allowlist would otherwise
include them.

### 5.2.1 Branch Base, Working-Tree State, Submodules, LFS

**Branch base.** The `agentrunway/<run_id>/main` branch is created from
`runs.base_commit_sha`, recorded at `agentrunway run` start. The default base is the
current `HEAD` of the source checkout. `--base-ref <ref>` overrides. Worker
branches fork from `agentrunway/<run_id>/main` at the start of their wave, so they
see all merges from prior waves.

**Dirty source policy.** If the source checkout has uncommitted or staged
changes, `agentrunway run` refuses by default with a clear error pointing at
`git status`. `--allow-dirty-source` skips the check and records
`runs.allowed_dirty=true`; the dirty changes are *not* carried into the main
AgentRunway worktree.

**Submodules.** Not initialized in worker worktrees by default. Set
`worktree.submodules: init` in `agentrunway.yaml` to opt in. Submodule pointer changes
in worker diffs are treated as `forbidden` unless the task packet declares the
submodule path as `owned`.

**LFS.** Pointer files are checked out as pointers; large objects are not
pulled unless `worktree.lfs: pull`. Workers that need LFS-tracked content must
declare it in the packet so the runner pre-pulls before dispatch.

### 5.2.2 Concurrent Runs and Adapter Quotas

Multiple `agentrunway run` invocations against the same host share runtime API
quotas (Claude/Codex tokens, rate limits). Each run has its own SQLite DB and
worktree, so SQLite is contention-free, but runtime dispatch must coordinate
globally.

A per-runtime semaphore at `~/.agentrunway/locks/<runtime>.sem` caps concurrent worker
dispatches across all runs. Caps are configured in `~/.agentrunway/global.yaml`:

```yaml
runtime_caps:
  claude:
    max_concurrent_workers: 6
  codex:
    max_concurrent_workers: 8
```

**Implementation.** The semaphore is a slot-array file: one fixed-width record
per slot, each holding `(slot_index, holder_pid, agentrunway_run_id, worker_id,
acquired_at)`. Acquire is `fcntl(LOCK_EX)` on a sentinel byte, scan for a free
slot or a slot whose `holder_pid` is no longer alive (POSIX `kill(pid, 0)`
returns `ESRCH`), write the new holder, release the file lock. Release is the
same dance to clear the slot. Stale slots from crashed runners are reclaimed
opportunistically by any subsequent acquirer; an explicit
`agentrunway clean --reclaim-locks` performs the same scan without acquiring. The slot
count equals `max_concurrent_workers`; raising the cap requires `agentrunway clean
--reclaim-locks` because the file is resized on next acquire.

Adapter rate-limit errors are surfaced as retryable transient failures with
exponential backoff up to the watchdog's `retry` budget. Rate-limit retries do
*not* hold a semaphore slot during backoff.

### 5.3 SQLite Control Plane

SQLite is the source of truth for AgentRunway execution. Suggested tables:

| Table | Purpose |
| --- | --- |
| `runs` | Invocation, workspace, plan/spec refs, status, model profile, AgentLens run id |
| `tasks` | Parsed task graph, risk, phase, dependencies, status |
| `task_packets` | Packet hash, prompt path, context refs, allowed/forbidden scopes |
| `file_claims` | `owned`, `shared_append`, `consumes`, `read_only`, `forbidden` claims per task |
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

Column-level schemas (including `waves.base_commit_sha`,
`workers.timeout_seconds`, `workers.reasoning_effort_resolved`,
`merge_queue.applied_commit_shas`, `runs.allowed_dirty`, `runs.base_commit_sha`,
`runs.agentlens_status`) live in `scripts/agentrunway/db.py`. The table above names
purpose, not columns — `db.py` is the source of truth for the SQL schema.

## 6. Execution Flow

### 6.1 High-Level Flow

```text
1. Parse invocation and model profile.
2. Open AgentRunway run and SQLite DB.
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

### 6.1.5 Plan/Spec Format

The runner parses a plan markdown file and an optional spec markdown file.
Both are deterministic inputs: AgentRunway computes SHA-256 over canonicalized bytes
(LF line endings, trailing whitespace stripped) and stores them as
`plan_hash` / `spec_hash` in `runs`.

**Plan file** — markdown with one H2 per task. Each task contains a fenced
```yaml agentrunway-task``` block with required fields:

```yaml
task_id: task_003
title: Token refresh retry handling
risk: medium                # low|medium|high
phase: implementation       # planning|implementation|verification|docs
dependencies: [task_001]
spec_refs: [S2.1, S2.4]
file_claims:
  - {path: src/auth/session.ts, mode: owned}
  - {path: tests/auth/session.test.ts, mode: owned}
  - {path: src/auth/types.ts, mode: consumes}
acceptance_commands:
  - npm test -- tests/auth/session.test.ts
resource_keys: []           # optional, e.g. [db, port:3000, external-api]
required_skills: [test-driven-development]
serial: false               # optional explicit serial marker
wall_clock_timeout_seconds: 1800   # optional; runner default applies if unset
sandbox_tier_required: fs_scope    # optional; defaults to fs_scope (§7.0)
lfs_paths: []                # optional; runner pre-pulls these before dispatch
```

**`serial`** forces the task to run alone in its wave (no parallel siblings) even
when claim/resource analysis would otherwise permit batching. Use for tasks
that race against external state the runner cannot model (e.g. dev-server
restarts, machine-wide caches). The flag is honored by the scheduler in §6.4.

**`wall_clock_timeout_seconds`** is the per-task budget enforced by the
watchdog (§6.8). If unset, the runner applies `worker.default_timeout_seconds`
from `agentrunway.yaml` (default `1800`). High-risk tasks may set a higher budget; the
runner records the resolved value on `workers.timeout_seconds`.

Markdown narrative under the H2 (outside the fenced block) is captured into
the task packet's `objective`, truncated to
`max_inline_worker_summary_chars`.

**Spec file** — markdown with H2/H3 anchors. The parser builds a section
manifest keyed by anchor id. `spec_refs: [S2.1]` resolves to the heading whose
slug is `s2-1` or whose first inline token is `S2.1`. The runner stores
`(spec_section_id, content_sha256)` per ref and rejects a task packet whose
referenced spec content changes between plan parse and worker dispatch.

**Determinism guarantee:** given identical `(plan_bytes, spec_bytes,
agentrunway_version, profile)`, the runner produces the same task graph, wave
assignment, and packet hashes. Wave-internal tie-breaking is
`(risk_desc, dependency_count_desc, task_id_asc)`.

Plan parse failures halt before worktree creation (§12) and report the
offending task id and line.

### 6.2 Task Packet

Every worker receives a compact packet. It never receives the entire source
conversation by default.

```json
{
  "schema": "agentrunway.task_packet.v1",
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
  "forbidden_write_globs": [".git/**", "node_modules/**", "**/*.lock", "**/.env*"],
  "file_claims": [
    {"path": "src/auth/session.ts", "mode": "owned"},
    {"path": "tests/auth/session.test.ts", "mode": "owned"}
  ],
  "required_skills": ["using-superpowers", "test-driven-development"],
  "acceptance_commands": ["npm test -- tests/auth/session.test.ts"],
  "output_schema": "agentrunway.worker_result.v1",
  "model_assignment": {
    "runtime": "codex",
    "model": "gpt-5.5",
    "reasoning_effort": "high"
  },
  "sandbox_tier_required": "fs_scope",
  "wall_clock_timeout_seconds": 1800,
  "lfs_paths": [],
  "wave_base_commit_sha": "f0a1c2b3d4e5f6...",
  "candidate_index": 0
}
```

`wave_base_commit_sha` is the commit `agentrunway/<run_id>/main` pointed at when the
wave started; workers must branch from it and `shared_append` validation
(§6.3) measures against it. `candidate_index` distinguishes implementer
candidates when a high-risk task dispatches more than one (§6.5).

### 6.3 File Claim Modes

| Mode | Meaning |
| --- | --- |
| `owned` | Exactly one active worker may modify the file. |
| `shared_append` | Multiple workers may append non-overlapping entries, e.g. changelog or generated index. Requires post-diff structural check. |
| `consumes` | Worker reads the file as part of its task. If any sibling task in the same wave declares the same path as `owned`, the scheduler inserts a dependency edge so the consumer runs after the producer. Out-of-wave reads add no edge. |
| `read_only` | Worker may inspect but must not modify. No scheduling effect; use `consumes` to express read-after-write ordering. |
| `forbidden` | Worker must not read or write unless explicitly elevated by the runner. |

Forbidden wins over every other claim. Any out-of-scope diff rejects the worker
result before merge.

**`shared_append` validation grammar.** The default check is structural and is
performed against the **wave base** — the commit `agentrunway/<run_id>/main` pointed at
when the wave started (recorded in `waves.base_commit_sha` and replicated in
each packet as `wave_base_commit_sha`). Validating against a moving `main` HEAD
would be wrong: as wave merges land, the file changes underneath later workers
in the same wave even though they branched from the same base.

1. No line that exists in the wave-base file may be modified or deleted.
   Diffs are computed against the wave-base file, not the current `main` HEAD.
2. Each worker's appended lines must be disjoint from every other worker's
   appended lines in the same wave (line-set intersection must be empty,
   measured by content hash of normalized lines so that two workers writing the
   same byte-identical line still conflict).
3. The file's existing trailing structure (e.g. JSON array closing bracket,
   YAML document end) must remain syntactically valid after the merge of all
   accepted worker appends from the wave.

The runner enforces these by materializing all candidate appends against the
wave base, applying them in deterministic worker-id order, and rejecting the
wave if any of (1)–(3) fail. Rejection is per-worker when the offending append
is attributable; otherwise the whole `shared_append` file is held out of merge
and the runner emits `agentrunway.blocker` with `severity=warn`.

Repos may register file-specific validators in `agentrunway.yaml`:

```yaml
shared_append:
  - path: CHANGELOG.md
    validator: changelog_section_append
  - path: src/generated/index.ts
    validator: generated_index_append
```

A validator is a function name resolved at runner startup. Missing validators
halt with `unknown_shared_append_validator`. If no validator is configured,
the default structural check applies.

### 6.3.1 Shared Build Artifacts (Lockfiles & Generated Files)

Lockfiles (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`,
`poetry.lock`, `uv.lock`, `Gemfile.lock`, `go.sum`) and other auto-generated
files (`*.generated.ts`, codegen output) are nearly always touched by any task
that adds or upgrades a dependency. Treating them as `owned` forces every such
task to serialize, defeating wave parallelism.

AgentRunway handles them with two mechanisms:

1. **Reconcile step.** After each wave's accepted merges land in main, the
   runner runs a configured reconcile command (e.g. `npm install
   --package-lock-only`, `cargo generate-lockfile`) in the main execution
   worktree. The resulting lockfile delta is committed by the runner as a
   wave reconcile commit, not attributed to any worker.

2. **Resource lock fallback.** If reconcile is not available for a stack,
   tasks that touch dependencies must declare `resource_keys: [lockfile:<id>]`
   so the scheduler serializes them within a wave.

Defaults are configured in `agentrunway.yaml`:

```yaml
lockfiles:
  - path: package-lock.json
    reconcile: npm install --package-lock-only --ignore-scripts
  - path: Cargo.lock
    reconcile: cargo generate-lockfile
```

If a worker's diff modifies a registered lockfile path directly, the runner
strips that file from the merge candidate before applying and lets the
reconcile step regenerate it. Stripping is recorded in artifacts so the
worker's intent is preserved as evidence.

**Network policy.** Reconcile commands run in the **runner's** process inside
the main execution worktree, not in a worker sandbox. They therefore use the
host's normal network egress; `net_blocked` (§7.0) applies only to workers.
If a reconcile command itself needs network (e.g. `npm install
--package-lock-only` contacting the registry) and the host has no outbound
connectivity, reconcile fails and the runner emits `agentrunway.blocker` with
`severity=error` and the affected lockfile path. Configure offline reconcile
(e.g. `--offline`) in `agentrunway.yaml` if the project supports it.

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

AgentRunway supports the existing multi-agent pattern of separate implementation,
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

**Multi-candidate selection.** When `candidates_per_task > 1` (default for
`high_risk_candidates_per_task`), the runner dispatches N implementer
candidates in parallel and selects one winner before queueing for review. The
selection rule is deterministic:

1. Drop any candidate whose worker result fails schema validation, method
   audit, or diff-scope check.
2. Drop any candidate whose acceptance commands fail (re-executed by the
   runner per §9.1).
3. Among survivors, choose by `(diff_size_lines_asc, command_runtime_ms_asc,
   candidate_index_asc)`. Smallest correct diff wins; ties broken by faster
   acceptance run, then by candidate index.
4. If no candidates survive, the task is marked `failed_all_candidates` and
   queued for the recovery role (not retried directly).

The losing candidates' artifacts are retained per §16 entry 20 so reviewers
can inspect them; their commits are not cherry-picked.

### 6.6 Context Policy

AgentRunway treats context pressure as a control-plane problem. The orchestrator should
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

**Ratio denominator.** Ratios are over the *host session's* effective
context window, reported by the host adapter via
`reported_context_usage` (§7.2). When the host reports `token_count`, the
ratio is `used_tokens / context_window_tokens`. When `message_count`, it is
`used_messages / max_messages`. When `none`, the host falls back to a
time/turn heuristic: compact at 50 turns since session start, rotate at 100,
hard-stop at 120. The fallback is recorded as `context_policy.mode=heuristic`
in SQLite.

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
session remains too large, AgentRunway rotates orchestration into a fresh session using
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

- no advance in `WorkerStatus.last_activity_ts` for the configured stall
  window (`worker.stall_seconds`, default `300`) while
  `phase_hint != "thinking"`, or for `worker.thinking_stall_seconds`
  (default `1200`) while `phase_hint == "thinking"`,
- repeated command loops (same `last_tool` ≥ N times with no diff progress),
- context overflow or compaction prompts (heuristic on `pending_prompt_text`),
- stuck permission prompts (`state == "awaiting_input"` past
  `worker.prompt_response_seconds`),
- wall-clock budget exceeded (`workers.timeout_seconds`),
- dead process or missing session (`state == "lost"`),
- repeated malformed JSON output across retries.

Workers do not emit heartbeats; "heartbeat" in earlier drafts was shorthand
for adapter-polled `last_activity_ts` advancement. The watchdog ticks on a
runner-side timer (default `5s`) and inspects each live worker via
`poll_worker(handle)`; it never assumes the worker is alive without a fresh
`WorkerStatus`.

Default action ladder:

```text
observe -> nudge -> compact or rotate -> retry -> reject/block
```

Watchdog actions are recorded in SQLite and emitted to AgentLens as compact
`agentrunway.watchdog_event` events where useful.

### 6.9 Merge Queue

Implementation workers do not write directly into the main execution worktree.
They produce one or more commits (or a patch fallback) on their worker branch.
The runner queues the commit sequence:

```text
worker worktree commit(s)
  -> diff scope validation (against wave base)
  -> review gate
  -> verification gate
  -> dry-run cherry-pick of the full commit sequence
  -> apply to main execution worktree
  -> record merge_applied with applied_commit_shas[]
```

Default merge strategy: worker produces one or more commits (e.g. TDD red/green
commits); the runner cherry-picks them in order from the worker branch onto
`~/.agentrunway/worktrees/<workspace_id>/<run_id>/main`, preserving authorship and
commit messages. The full sequence is recorded in
`worker_result.commits[]` (§11) and `merge_queue.applied_commit_shas[]`. If
any commit in the sequence conflicts, the entire sequence is aborted (no
partial merges); see §12 for the recovery path. Patch fallback is allowed when
a runtime cannot reliably commit; it is collapsed to a single synthetic commit
attributed to the worker.

## 7. Runtime Adapter Contract

### 7.0 Worker Sandbox Tier

Diff-scope validation catches what a worker *committed*, not what a worker
*did*. A worker can exfiltrate via `curl`, write absolute paths under `~`, or
mutate state outside the worktree without leaving any tracked diff. AgentRunway
mitigates this via a declared sandbox tier per adapter, negotiated at dispatch.

| Tier | Process isolation | Filesystem | Network | Notes |
| --- | --- | --- | --- | --- |
| `unsandboxed` | Inherits host | Full | Full | Dev/dry-run only; emits `agentrunway.blocker` with `severity=warn` per run. |
| `fs_scope` | Same UID, chdir + path allowlist | Restricted to worktree + repo-declared allowlist | Full | Default for hosts without OS sandbox. Enforced by adapter wrapper that rejects absolute paths outside the allowlist before exec. |
| `net_blocked` | Same UID | `fs_scope` | Blocked except declared egress (see `network_egress` below) | Default when `worktree.network: blocked` is set in `agentrunway.yaml`. |
| `full_sandbox` | OS sandbox (`bwrap`, `sandbox-exec`, container) | Mounted worktree only | Per-policy | Required for `risk: high` tasks unless explicitly waived. |

Each adapter reports its **maximum** supported tier in
`CapabilityReport.sandbox_tier_max`. The packet declares
`sandbox_tier_required`. If `required > max`, the runner halts with
`unsupported_sandbox_tier` before dispatch — never silently downgrades.

Secrets passthrough: environment variables are not forwarded to workers by
default. `agentrunway.yaml` declares an allowlist:

```yaml
secrets_passthrough:
  - GITHUB_TOKEN
  - DATABASE_URL
```

Allowlisted values are injected as environment variables in the worker
process only; they are never written into prompts, packets, or artifacts.
The runner redacts any literal match of a passthrough value from worker
stdout/stderr before persisting to artifacts.

Network egress allowlist for `net_blocked` is declared in `agentrunway.yaml`:

```yaml
worktree:
  network: blocked          # blocked | full
network_egress:
  - host: registry.npmjs.org
    ports: [443]
  - host: api.anthropic.com
    ports: [443]
  - host: api.openai.com
    ports: [443]
```

Enforcement is adapter-dependent. Adapters that support OS sandboxing
(`bwrap`, `sandbox-exec`, container runtimes) translate the allowlist into
the underlying mechanism. Adapters that cannot enforce egress at the OS
level report `sandbox_tier_max < net_blocked`; if the packet requires
`net_blocked` and the adapter cannot supply it, dispatch halts with
`unsupported_sandbox_tier` rather than running unprotected.

### 7.1 Adapter Interface

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
    def reattach_worker(self, handle: WorkerHandle) -> WorkerHandle: ...
```

`WorkerStatus` must provide enough signal for the watchdog (§6.8) to
distinguish stalled work from long thinking:

```python
@dataclass
class WorkerStatus:
    state: Literal["starting", "running", "awaiting_input", "completed",
                   "failed", "lost"]
    last_activity_ts: float          # monotonic time of last stdout/stderr/tool event
    phase_hint: Literal["thinking", "tool_call", "writing", "idle", "unknown"]
    tokens_used: int | None          # if reported_context_usage == token_count
    last_tool: str | None
    pending_prompt_text: str | None  # raw text if `state == awaiting_input`
```

The watchdog uses `last_activity_ts` for stall detection, `phase_hint` to
suppress false positives during long reasoning, and `pending_prompt_text` to
classify permission prompts. Adapters that cannot supply a field set it to
`None` or `"unknown"` — never fabricate.

`reattach_worker` is invoked on resume when `supports_reattach=true`. The
runner has no live `WorkerHandle` in memory after a crash; it constructs a
**partial handle** from persisted SQLite state — `(pid, session_id, runtime,
worker_id, worktree_path, started_at, packet_hash)` — and hands that to the
adapter. The adapter validates that the process is still alive (`kill(pid, 0)`
plus optional session ping), that `worktree_path` exists and is owned by the
expected `agentrunway_run_id`, and that the session's `packet_hash` (if reported)
matches the persisted one. On success it returns a live `WorkerHandle` and
resumes polling; on failure it raises `ReattachFailed` and the runner falls
back to cancel-and-retry, charging the attempt against the retry budget.
Reattach never re-prompts the worker — if the session's reply has already
been emitted to stdout before reattach, the adapter must surface it via
`collect_result` without re-running the worker.

### 7.2 Capability Report

Adapters must declare capabilities. The scheduler uses these to choose safe
routing and to halt cleanly when a packet requires a capability the runtime
cannot satisfy.

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
  "supports_worktree": true,
  "supports_reattach": false,
  "sandbox_tier_max": "fs_scope",
  "reported_context_usage": "token_count"
}
```

`supports_reattach`: when true, the adapter can resume polling and result
collection against a worker process that outlived a runner crash, keyed by
`(pid, session_id, worktree_path)` persisted in SQLite. When false, the
runner cancels orphaned workers on resume and retries within budget.

`sandbox_tier_max`: highest sandbox tier (§7.0) this runtime can run a
worker under on this host.

`reported_context_usage`: how the adapter measures worker context pressure
for the watchdog — `token_count`, `message_count`, or `none`.

### 7.3 Initial Adapters

| Adapter | MVP Status | Notes |
| --- | --- | --- |
| `claude` | Required | Use Claude Code/headless where available. Can use process supervision and sub-worktrees. |
| `codex` | Required | Prefer stable CLI/headless execution. Codex App `spawn_agent` is optional capability. |
| `local` | Required fallback | Runs task locally in current host session for dry-run or no-agent mode. |
| `gemini` | Later | Add once core scheduler and packet format are stable. |
| `aider` | Later | Useful for patch-oriented tasks; likely limited mid-task control. |

## 8. Model Profiles

Model assignment is first-class state. Defaults must be explicit, printed at run
start, persisted in SQLite, and emitted to AgentLens in `agentrunway.run_started`
and `agentrunway.worker_dispatched`.

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
[$agent-runway] plan=plans/auth.md spec=specs/auth.md
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

For repeatability, AgentRunway also reads a repo-local optional config:

```yaml
# agentrunway.yaml
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
invocation args > agentrunway.yaml > built-in profile defaults
```

If a runtime cannot honor a requested model or reasoning level, the adapter must
halt before dispatch with a clear `unsupported_model_assignment` blocker. It
must not silently downgrade.

### 8.4 Reasoning-Effort Abstraction

`reasoning_effort` is an abstract level resolved per runtime by the adapter.
The portable values are:

```text
lowest | low | medium | high | highest
```

`xhigh` (used in §8.1's `codex-default` profile) is an alias for `highest`
during the Codex GPT-5.5 rollout window. Adapter mapping table:

| Abstract | Codex (GPT-5.5) | Claude (Opus) | Local |
| --- | --- | --- | --- |
| `lowest` | `low` | `low` | n/a |
| `low` | `medium` | `low` | n/a |
| `medium` | `medium` | `medium` | n/a |
| `high` | `high` | `high` | n/a |
| `highest` | `xhigh` | `high` (max) | n/a |

If the runtime cannot honor `highest` (e.g. Claude lacks an `xhigh` tier),
the adapter selects the closest supported level and records the mapping in
`workers.reasoning_effort_resolved`. Mapping is **not** silent downgrade: the
runner emits `agentrunway.worker_dispatched` with both requested and resolved
levels. Refusal (halt with `unsupported_model_assignment`) is reserved for
values the adapter cannot map at all.

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

### 9.1 Runner-Side Verification of Method Audit

Method audit fields are worker self-reports — an LLM can fabricate
`red_evidence_ref` and `green_evidence_ref` content. The runner must not
trust them at face value. After a worker returns:

1. For each `commands_run` entry tagged `kind: test`, the runner re-executes
   the command against two ephemeral checkouts of the worker's commit
   sequence (§11 `worker_result.commits[]`):

   ```bash
   # post-commit tree: last commit in the sequence
   git worktree add --detach \
     ~/.agentrunway/runs/.../verify/<task_id>/post \
     <commits[-1]>

   # pre-commit tree: parent of the first commit in the sequence
   git worktree add --detach \
     ~/.agentrunway/runs/.../verify/<task_id>/pre \
     <commits[0]>^
   ```

   Pre-commit must fail; post-commit must pass. Mismatch →
   `method_audit_violation`. The two verify worktrees are isolated from each
   other and from any other concurrent verification (a separate path under
   the run dir), so parallel verifications never race. Both are removed via
   `git worktree remove` once the check completes, pass or fail. `git stash`
   is **not** used for this — stash operates on working-tree changes, not
   on committed state, and would not give a clean pre-commit tree.

2. Evidence artifacts are re-hashed; the runner computes `command_hash` from
   the actual executed command and rejects packets where the worker's
   reported hash diverges.
3. For docs-only/config-only/generated-only waivers, the runner verifies the
   diff actually matches the waiver scope before accepting `status: applied`
   without test evidence.

This deterministic re-check is the only mechanism that converts self-reported
audit into trusted evidence. Re-execution uses the same `sandbox_tier` and
`acceptance_commands` from the packet; it does not call any LLM.

## 10. AgentLens Integration

AgentLens is the observability and evaluation layer, not AgentRunway's execution source
of truth.

```text
AgentRunway SQLite DB = execution state
AgentLens = append-only timeline, evidence, failures, evaluation surface
```

### 10.1 Run Lifecycle

At AgentRunway run start:

```bash
agentlens run-open \
  --agent kws-agentrunway-orchestrator \
  --workspace "$WORKTREE_ABS" \
  --meta agentrunway_run_id="$AGENTRUNWAY_RUN_ID" \
  --meta plan_hash="$PLAN_HASH" \
  --meta spec_hash="$SPEC_HASH"
```

The returned AgentLens run id is stored in `runs.agentlens_run_id`.

At AgentRunway run close:

```bash
agentlens run-close \
  --run "$AGENTLENS_RUN_ID" \
  --outcome "$OUTCOME" \
  --summary "$SUMMARY"
```

AgentLens outcome mapping:

| AgentRunway Outcome | AgentLens Outcome |
| --- | --- |
| `finished` | `success` |
| `failed` | `failed` |
| `blocked` | `partial` |
| `cancelled` | `cancelled` |
| unknown/ambiguous | `unknown` |

### 10.2 Event Namespace

The namespace prefix is configurable. Default is `agentrunway`; override via
`agentlens.namespace_prefix` in `agentrunway.yaml` for users with a different
identity. The suffix after the prefix is fixed by AgentRunway and listed below.

AgentRunway uses only the new namespace:

```text
agentrunway.run_started
agentrunway.task_planned
agentrunway.file_claimed
agentrunway.wave_started
agentrunway.worker_dispatched
agentrunway.superpowers_bootstrapped
agentrunway.worker_result
agentrunway.review_result
agentrunway.verification_result
agentrunway.merge_queued
agentrunway.merge_applied
agentrunway.worker_rejected
agentrunway.method_audit_violation
agentrunway.context_snapshot
agentrunway.watchdog_event
agentrunway.blocker
agentrunway.run_finished
```

No `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*` events are emitted by AgentRunway.

### 10.3 Payload Envelope

All AgentRunway events use a compact payload:

```json
{
  "schema": "agentrunway.event.v1",
  "agentrunway_run_id": "auth-refactor-20260520-151000",
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
    "command_hash": "sha256:5e2c8b3d1a7f4e90c6b2d8e1f0a9c3b7d4e6f2a8c1b5d9e0a7f3c2b6d8e1f4a0",
    "artifact_ref": "agentrunway://runs/archive-a13f9c2b/auth-refactor-20260520-151000/artifacts/task_003/test_excerpt.txt"
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
AgentLens run per AgentRunway execution, with `task_id` and `worker_id` distinguishing
worker events. If `agentlens_child_runs=on`, AgentRunway may open child runs for workers
after parent-only emission is stable. Child run failures follow the same
best-effort policy and must never block execution.

### 10.5 AgentLens Failure Policy

AgentLens failure must never stop AgentRunway execution.

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
  "schema": "agentrunway.worker_result.v1",
  "worker_id": "worker_007",
  "task_id": "task_003",
  "role": "implementer",
  "status": "success",
  "changed_files": ["src/auth/session.ts", "tests/auth/session.test.ts"],
  "commits": ["abc1234", "def5678"],
  "branch": "agentrunway/auth-refactor-20260520-151000/task_003-implementer-001",
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

`commits` is an ordered list (oldest first) of SHAs on the worker's branch
since the wave base. A worker that follows TDD typically produces two:
red-test commit then green-implementation commit. Single-commit workers
still use the array (length 1). The merge queue (§6.9) cherry-picks the
sequence as a unit; method-audit re-execution (§9.1) extracts pre-commit
state from `commits[0]^` and post-commit state from `commits[-1]`; `agentrunway
apply --strategy cherry-pick` (§13.4) iterates over each entry.

Malformed output is a worker failure, not a runner failure. The runner may retry
with a stricter prompt once, then reject.

### 11.1 Review Result Schema

Reviewers are LLMs and may rubber-stamp. To make review evidence checkable,
the reviewer's result must conform to a separate schema and list concrete
checks with per-check evidence. "All good" with no checks is rejected.

```json
{
  "schema": "agentrunway.review_result.v1",
  "worker_id": "worker_009",
  "task_id": "task_003",
  "reviewed_worker_id": "worker_007",
  "status": "approved",
  "checks": [
    {"id": "scope",      "status": "pass", "evidence_ref": "artifact:scope.diff.txt"},
    {"id": "tests",      "status": "pass", "evidence_ref": "artifact:test_run.txt"},
    {"id": "regressions","status": "pass", "evidence_ref": "artifact:regress_grep.txt"},
    {"id": "claims",     "status": "pass", "evidence_ref": "artifact:claims_check.json"},
    {"id": "secrets",    "status": "pass", "evidence_ref": "artifact:secret_scan.txt"}
  ],
  "findings": [],
  "method_audit": { "using_superpowers": {"status": "applied"}, "status": "passed" }
}
```

`status` is an enum: `approved | changes_requested | rejected`. Semantics:

- `approved` — all required checks pass; `findings` MUST be empty. The
  worker's commits are eligible for merge after verification.
- `changes_requested` — at least one finding with `severity ∈ {block,
  warn}`; `findings` MUST be non-empty. The worker is sent back for retry
  within a **separate review-round budget** of `1` round by default
  (`review.max_rounds` in `agentrunway.yaml`), independent of the implementer
  retry budget in §12. A review round does *not* consume one of the
  implementer's 2 failure retries — those are reserved for malformed
  output, timeouts, and infra failures. The two budgets compose: an
  implementer may consume both review rounds and then up to 2 failure
  retries before the task is queued for recovery. Findings are forwarded
  in the retry packet. If the reviewer returns `changes_requested` again
  after the review budget is exhausted, the runner treats it as
  `rejected` and queues recovery.
- `rejected` — irrecoverable problem (scope violation, fabricated audit,
  unaddressable design issue); `findings` MUST be non-empty. No retry; the
  task is queued for the recovery role.

Each finding has `{id, severity, summary, evidence_ref}` with
`severity ∈ {block, warn, info}`. A reviewer returning `approved` with any
non-empty `findings`, or `changes_requested`/`rejected` with empty
`findings`, is rejected as `review_result_malformed`.

Required check ids and accepted status values are enforced by the runner.
A reviewer that returns `status: approved` while any required check is
`unknown` or absent is rejected as `review_result_malformed`. The runner
hashes each `evidence_ref` artifact and persists the hash so reviews are
tamper-evident within the local trust boundary.

### 11.2 Verification Result Schema

`agentrunway.verification_result.v1` follows the same shape as review but with
verification-specific check ids (`acceptance_commands_passed`,
`no_new_lints`, `no_new_typescript_errors`, etc.) defined per language stack
in `agentrunway.yaml`.

## 12. Failure Handling

| Failure | Runner Action |
| --- | --- |
| Plan parse fails | Halt before worktree creation; emit blocker if AgentLens run exists |
| Unsupported model assignment | Halt before dispatch |
| Worker timeout | Cancel worker, record failure, retry within budget |
| Runner crash mid-wave | On resume, reattach surviving workers if `supports_reattach=true`; else cancel orphans and retry within budget |
| Host session crash, runner alive | Runner continues to completion; on next host invocation, `agentrunway status --run <id>` resumes visibility |
| Unsupported sandbox tier | Halt before dispatch with `unsupported_sandbox_tier`; never silently downgrade |
| Worker malformed JSON | Retry once with schema reminder; then reject |
| Missing superpowers audit | Reject worker; emit method audit violation |
| Out-of-scope diff | Reject worker; do not merge |
| Merge conflict | Auto-resolve is never attempted. The runner aborts the cherry-pick sequence (no partial merges), discards the worker branch's commits from this wave, and schedules a *re-implementation* of the same task in a new follow-up wave whose base is the current `agentrunway/<run_id>/main` HEAD (i.e. post-conflict). The re-implementation gets a fresh packet, fresh worker, and `attempt += 1`. It is a re-dispatch, not a re-cherry-pick. If the same task hits a merge conflict on its retry, the runner halts with `recurring_merge_conflict` and surfaces the conflicting paths plus both attempts' diffs as artifacts. |
| Verification failure | Return to implementer retry if root cause clear; else halt with evidence |
| AgentLens unavailable | Continue with `agentlens_status=degraded` |
| SQLite write failure | Halt; execution state is unsafe |
| Worktree creation failure | Halt; do not run in source checkout |
| Orphan verify worktree (§9.1) | On runner crash between `git worktree add --detach` and `git worktree remove`, the verify worktree is left behind. The global registry (§5.2) records each verify-worktree path on creation; `agentrunway clean` and `agentrunway resume` both scan the registry, prune entries whose owner run is no longer live, and `git worktree remove --force` the orphans. |
| Worktree or branch name collision | Generate a new nonce; halt if registry metadata is inconsistent |
| Dirty source checkout at `agentrunway run` | Halt with `dirty_source_checkout` unless `--allow-dirty-source` set |
| Context threshold crossed | Snapshot, compact if supported, rotate if needed |
| Stuck permission prompt | Nudge or cancel according to adapter policy; never auto-approve destructive operations |
| Budget exceeded | Emit warning by default; pause only when `budget_action=pause` |
| Cost extract unavailable | Record `cost_extract=missing` per worker; if `budget_action != off` and >50% of workers in a run lack cost data, emit `agentrunway.blocker` with `severity=warn` once and continue (budget enforcement falls back to token-count estimates if reported, else disabled for the run) |
| Adapter rate limit / transient API error | Exponential backoff, count against retry budget |
| Runtime API quota exhausted | Pause new dispatches for the affected runtime; surface `runtime_quota_exhausted`; resume on operator action |

Retry budgets:

- implementation worker: 2 retries by default,
- reviewer/verifier: 1 retry for infra/malformed output,
- merge conflict repair: 1 deterministic retry,
- same root cause repeated 3 times: halt.

## 13. CLI Surface

### 13.1 Skill → Runner Control Flow

The host LLM invokes the skill; the skill body instructs the host to shell
out to the runner. The runner executes synchronously in a separate process.
The host does **not** stream worker transcripts. It reads only:

1. The runner's stdout summary (one line per wave start/finish, plus the
   final report).
2. `agentrunway status --run <run_id>` on demand.

This keeps the host's context usage proportional to the report size, not to
worker output size. For very long runs the user may detach (`Ctrl+Z`/`bg`
or invoke with `--detach`) and reattach later via `agentrunway status`.

### 13.2 Invocation

Skill invocation:

```text
[$agent-runway] plan=plans/auth.md spec=specs/auth.md
```

Runner equivalent:

```bash
python3 scripts/agentrunway.py run \
  --plan plans/auth.md \
  --spec specs/auth.md \
  --model-profile codex-default \
  [--base-ref HEAD] \
  [--allow-dirty-source] \
  [--detach]
```

### 13.3 Status and Lifecycle

```bash
python3 scripts/agentrunway.py status --run <run_id>
python3 scripts/agentrunway.py inspect --run <run_id> --task task_003
python3 scripts/agentrunway.py events --run <run_id>
python3 scripts/agentrunway.py resume --run <run_id>
python3 scripts/agentrunway.py cancel --run <run_id>
python3 scripts/agentrunway.py apply --run <run_id> [--strategy cherry-pick|merge|patch]
python3 scripts/agentrunway.py clean --older-than 7d --successful
```

`agentrunway status` prints: run id, plan slug, current wave, per-task state
(pending/dispatched/reviewing/verifying/merged/failed/blocked), open blockers,
merge queue depth, AgentLens link. It must fit in ~30 lines for a typical
multi-wave run.

### 13.4 `agentrunway apply` Semantics

`apply` copies the accepted run from
`~/.agentrunway/worktrees/<workspace_id>/<run_id>/main` into the user's source
checkout. Defaults:

- `--strategy cherry-pick` (default): cherry-picks each accepted worker's
  full `commits[]` sequence (in worker order, then wave reconcile commits)
  onto the source checkout's current HEAD, preserving authorship and commit
  messages. A worker's sequence is applied atomically — if cherry-pick of
  any commit in a worker's sequence conflicts, `apply` aborts the entire
  sequence before modifying the working tree (per the conflict-handling
  rule below), not just the offending commit.
- `--strategy merge`: produces a merge commit from `agentrunway/<run_id>/main`.
- `--strategy patch`: writes a single combined patch to stdout for review.

Conflict handling: on conflict, `apply` stops *before* modifying the working
tree (uses `--no-commit` + abort), prints the conflicting paths, and exits
non-zero. The source checkout is never left in a half-merged state by AgentRunway.

`apply` refuses if the source checkout is dirty unless `--allow-dirty-target`
is set.

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
- Host session crashes mid-run: runner continues to completion; reattaching
  via `agentrunway status` shows accurate final state.
- Dirty source checkout: `agentrunway run` halts unless `--allow-dirty-source` set.
- Lockfile reconcile: two tasks add dependencies in the same wave; runner
  strips per-worker lockfile writes and applies a single reconcile commit.
- `shared_append` validator rejects an overlapping append from two workers.
- Method-audit deterministic re-execution catches a fabricated green
  evidence file (post-commit tree actually fails the test).
- SQLite concurrency: two `agentrunway run` invocations against unrelated repos
  proceed without contention; same-runtime quota semaphore caps total
  concurrent workers.
- Reasoning-effort mapping: requesting `highest` on a runtime that maxes at
  `high` resolves to `high` and emits the resolved value, not a halt.
- Review result with no `checks` array is rejected as
  `review_result_malformed`.
- Review result with `status: approved` and non-empty `findings`, or
  `status: changes_requested` / `rejected` with empty `findings`, is
  rejected as `review_result_malformed`.
- Multi-commit worker sequence: a worker produces two commits and the
  cherry-pick of the second commit conflicts; the runner aborts the entire
  sequence (no partial merges) and triggers the merge-conflict re-dispatch
  path in §12.
- Method-audit verify worktrees: `git worktree add --detach` extracts
  pre-commit (`commits[0]^`) and post-commit (`commits[-1]`) trees,
  re-executes the test, and confirms pre fails / post passes. A worker
  whose pre-commit tree also passes the test is rejected as fabricated
  red evidence.
- Multi-candidate selection: three candidates dispatched, one fails
  acceptance, two survive with different diff sizes; the smaller diff
  wins; the loser's artifacts are retained and discoverable.
- Merge conflict → re-dispatch: a worker's accepted commits conflict at
  cherry-pick; the runner re-dispatches the *same task* with a fresh
  packet whose `wave_base_commit_sha` is post-conflict main. The retry
  worker produces new commits; no commits from the discarded attempt are
  merged. A second conflict on the retry halts with
  `recurring_merge_conflict`.
- Stale semaphore slot: a runner crashes while holding a runtime slot; a
  subsequent acquirer detects the dead `holder_pid` and reclaims the
  slot without operator intervention.
- `agentrunway clean --reclaim-locks` reclaims slots for dead holders without
  acquiring a fresh slot.

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

- `agent-runway` skill.
- Python runner.
- SQLite control plane.
- Claude adapter.
- Codex adapter.
- Local fake adapter for tests.
- Plan/spec markdown parser with `agentrunway-task` block schema and content hashing.
- Task packet builder.
- File claim validator with `owned` / `shared_append` / `consumes` /
  `read_only` / `forbidden` modes.
- Deterministic wave scheduler with documented tie-breaking.
- Isolated worktree creation.
- Worker sandbox tier negotiation (`fs_scope` default; halt on
  `unsupported_sandbox_tier`). MVP enforcement of `fs_scope` is layered and
  explicitly **best-effort, not a security boundary**: (a) the adapter
  wrapper chdir's the worker process into the worktree before exec and
  rejects absolute-path arguments outside the allowlist at exec time; (b)
  post-run diff-scope validation (§6.9) rejects any committed write outside
  the allowed globs. Workers that ship their own bash/file tools (Claude
  Code, Codex CLI) can still *read* outside the worktree via those tools;
  the diff-scope check catches *writes* that landed in the commit but does
  not catch ephemeral side effects (writing to `/tmp`, contacting external
  services). True isolation requires `full_sandbox` (OS sandbox via
  `bwrap`/`sandbox-exec`/container) which remains opt-in. This limitation
  is documented in `references/runtime-adapters.md` and surfaced in
  `agentrunway.run_started` payloads as `sandbox_enforcement=best_effort` when
  `fs_scope` is used.
- Secrets passthrough allowlist with stdout/stderr redaction.
- Merge queue.
- Lockfile reconcile step per wave with `agentrunway.yaml` configuration.
- Reviewer/verifier janitor gates.
- Superpowers method audit enforcement with runner-side deterministic
  re-execution of red/green evidence.
- AgentLens `agentrunway.*` emission.
- CLI status/inspect/resume.
- Adapter `supports_reattach` negotiation on resume after runner crash.
- Explicit `apply_to_source=off` default with `agentrunway apply --run <run_id>`.
- Worktree naming collision avoidance and registry checks.
- `.agentrunway-worktreeinclude` for opt-in ignored-file copying.
- Context snapshot, compaction, and rotation policy (host session only).
- Watchdog for stalled workers and context overflow.
- SQLite-mediated worker communication.
- Resource locks for non-file shared resources.
- Cleanup and retention commands with secret-aware redaction on disk.
- Review/verification result schemas (`agentrunway.review_result.v1`,
  `agentrunway.verification_result.v1`) with required per-check evidence.
- Reasoning-effort abstraction and per-runtime mapping table.
- Per-runtime concurrency semaphore at `~/.agentrunway/locks/<runtime>.sem`.
- `--allow-dirty-source` / `--base-ref` / `--detach` invocation flags.
- `agentrunway apply` with `cherry-pick` / `merge` / `patch` strategies and
  conflict-safe abort.
- Schema versioning policy (§19) with `agentrunway_version` and `schema_version`
  recorded per SQLite row.

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

1. **Canonical name:** `AgentRunway`; filesystem skill name `agent-runway`;
   CLI and Python package identifier `agentrunway`.
2. **MVP host targets:** Claude Code and Codex CLI/App hosts, with CLI/headless
   adapters as the stable execution path.
3. **Codex App `spawn_agent`:** optional optimization only; correctness must not
   depend on it.
4. **Default runtime behavior:** same runtime as orchestrator unless the user
   explicitly sets `worker_runtime=mixed` or a role-specific override.
5. **Worker AgentLens child runs:** configurable; default parent-only.
6. **UI timing:** no AgentRunway web UI in MVP.
7. **Merge strategy:** worker commit plus cherry-pick; patch apply fallback.
8. **High-risk approval:** autonomous by default; halt for destructive
   operations, missing acceptance criteria, and out-of-repo file claims.
9. **Budget policy:** support `budget=<amount>` and
   `budget_action=warn|pause|off`; default `warn`.
10. **Superpowers failure policy:** hard reject for all roles, including
    read-only reviewer and verifier roles.
11. **Config file name:** `agentrunway.yaml`.
12. **Legacy observability:** no CPE/CME event emission or state import in MVP.
13. **Source checkout policy:** default `apply_to_source=off`; explicit apply
    required.
14. **Worktree naming:** use workspace identity hashing, run nonce, branch/path
    registry, and collision checks before creation.
15. **Worktree env copying:** `.agentrunway-worktreeinclude` opt-in only.
16. **Watchdog:** included in MVP for context overflow, stalled workers, dead
    sessions, permission prompts, and repeated malformed output.
17. **Context management:** bounded summaries, artifact refs, snapshots,
    compaction, and rotation thresholds are part of MVP.
18. **Inter-worker communication:** runner-mediated SQLite mailbox only.
19. **Audit integrity:** SHA-256 artifact hashes recorded in SQLite provide
    *tamper-evidence within the local trust boundary* (corruption or
    accidental modification is detectable). They are not a cryptographic
    integrity guarantee: any actor with write access to `~/.agentrunway` can rewrite
    both the artifact and its hash. External integrity (HMAC chain, append-
    only remote store) is post-MVP.
20. **Cleanup/retention:** successful worktrees retained 7 days by default;
    failed or blocked worktrees retained 30 days by default. Retention
    applies to worker stdout/stderr and prompts as well; the same redaction
    rules that protect AgentLens (§10.3) apply to on-disk artifacts so that
    secrets are not retained for the full retention window in cleartext.
21. **Resource locks:** non-file resource keys participate in scheduling.
22. **Reasoning-effort:** abstract levels (`lowest`..`highest`) mapped per
    runtime; mapping is recorded, not silent.
23. **Concurrent runs:** per-runtime semaphore caps global concurrent
    worker dispatch; SQLite per run is contention-free.
24. **Branch base / dirty source:** base from `HEAD` by default; refuse to
    run on dirty source unless `--allow-dirty-source`.
25. **Reviewer/verifier:** must return concrete per-check evidence;
    empty-check approvals are rejected.
26. **Global workspace registry:** `~/.agentrunway/registry.sqlite` is the
    cross-workspace authority for collision detection and orphan-worktree
    discovery. Per-workspace SQLite is not sufficient on its own.
27. **Reviewer status enum:** `approved | changes_requested | rejected`.
    `approved` requires `findings: []`; the other two require non-empty
    `findings`. Each finding carries `{id, severity, summary, evidence_ref}`.
28. **Multi-candidate selection (high-risk):** deterministic ranking by
    `(diff_size_lines_asc, command_runtime_ms_asc, candidate_index_asc)`
    over candidates that pass schema, audit, scope, and acceptance checks.
    Losing candidates' artifacts are retained for inspection.
29. **Per-task wall-clock timeout:** plan tasks may set
    `wall_clock_timeout_seconds`; the runner default is
    `worker.default_timeout_seconds` (1800s). The watchdog enforces it.
30. **Merge-conflict resolution policy:** on cherry-pick conflict, the
    runner discards the worker's commits and re-dispatches the *task* with
    a fresh worker against the post-conflict `agentrunway/<run_id>/main`. This is
    a deliberate trade — re-running the implementation costs tokens but
    preserves determinism (no LLM-driven conflict resolution, no manual
    intervention loop). A second conflict halts the run with
    `recurring_merge_conflict`. The discarded attempt's artifacts are
    retained per §16 entry 20 for inspection.
31. **Review-round budget:** reviewer-driven `changes_requested` rounds
    are budgeted separately from implementer failure retries (default
    `review.max_rounds: 1`). The two budgets compose; review exhaustion
    promotes `changes_requested` to `rejected` and queues recovery.

## 17. Design Rationale

The most important design choice is to keep orchestration deterministic. If the
parent agent decides task splitting, worker routing, merge order, and retries
from conversation context, the system repeats the weaknesses of existing
single-skill orchestrators. A small runner with a SQLite control plane gives the
system stable state, replayability, and low context use.

The second key choice is to treat runtime adapters as replaceable. Claude,
Codex, Gemini, and Aider differ in model controls, session management, JSON
output reliability, cost extraction, and mid-task messaging. AgentRunway should not hide
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

- The user approves the greenfield AgentRunway direction.
- The default model profiles are accepted.
- The approved policy decisions in section 16 are accepted.
- The implementation plan scopes MVP only, leaving UI and additional adapters
  for later phases.

## 19. Schema Versioning Policy

AgentRunway declares versioned schemas for every cross-component data shape:

| Schema | Version |
| --- | --- |
| `agentrunway.task_packet` | `v1` |
| `agentrunway.worker_result` | `v1` |
| `agentrunway.review_result` | `v1` |
| `agentrunway.verification_result` | `v1` |
| `agentrunway.event` | `v1` |

Evolution rules:

1. **Additive changes** (new optional fields, new enum values that
   non-validating consumers can ignore) do not bump the version. Producers
   must default unspecified fields. Consumers must tolerate unknown fields.
2. **Required-field changes**, **removed fields**, or **semantic shifts**
   (e.g. changing `status` value meaning) require a new major version
   (`v2`). Old and new are accepted in parallel for at least one minor AgentRunway
   release.
3. **Deprecation** is announced via a `agentrunway.blocker` event with
   `severity=warn` on first encounter per run.
4. The runner records `agentrunway_version` and per-schema `schema_version` on every
   SQLite row so historical runs remain replayable against their original
   semantics.

Schema files live under `references/schemas/<name>.<version>.json` and are
hashed into the runner build; mismatch between code and schema file halts at
startup.
