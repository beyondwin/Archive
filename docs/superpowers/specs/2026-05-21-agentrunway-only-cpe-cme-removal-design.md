# Design: AgentRunway-Only Execution And CPE/CME Removal

Date: 2026-05-21
Status: Approved for implementation planning
Owner: KWS

## 1. Summary

Archive will use AgentRunway as the only execution orchestrator connected to
AgentLens. The older KWS Codex Plan Executor and KWS Claude Multi Agent
Executor paths are not legacy-supported, bridged, backfilled, or kept as
independent forward paths. They are removed from the active repository surface.

The target state is intentionally simple:

- `skills/agent-runway/` is the only plan-execution skill.
- AgentRunway owns scheduling, worktrees, runtime adapters, review,
  verification, recovery, apply, cleanup, and local durable state.
- AgentLens observes runner-validated AgentRunway evidence through the
  `agentrunway.*` event namespace.
- CPE/CME directories, docs, evals, scripts, and active references are removed
  from the repo.
- No `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*` compatibility surface is
  introduced.

This design supersedes the older KWS common observability direction and the
parts of earlier AgentLens/KWS plans that treated CPE or CME as supported
executor integrations.

## 2. Context

The repository currently contains several generations of planning:

- Greenfield AgentRunway design and implementation plans.
- AgentRunway hardening plans for AgentLens control-plane visibility, durable
  orchestration, operations quality, and hybrid scheduler recovery.
- Older AgentLens/KWS plans that mention `kws-cpe`, `kws-cme`, or
  `kws.orchestrator` as executor integration paths.
- Two older skill trees: `skills/kws-codex-plan-executor/` and
  `skills/kws-claude-multi-agent-executor/`.

The new direction is not to unify CPE and CME, and not to preserve them as
legacy execution options. AgentRunway replaces them for new execution work.

There are existing uncommitted changes under `skills/agent-runway/` at the time
of this design. The removal plan must preserve those AgentRunway changes and
must not revert, overwrite, or re-scope them.

## 3. Goals

- Remove CPE/CME skill implementations from the active repository.
- Remove active docs, plans, tests, fixtures, and help text that present CPE/CME
  as current or future executor integrations.
- Make AgentRunway the single documented execution orchestrator for approved
  Superpowers implementation plans.
- Keep AgentLens focused on observing AgentRunway execution evidence through
  `agentrunway.*`.
- Keep AgentRunway local state authoritative and AgentLens downstream.
- Leave no compatibility importer, bridge, fallback parser, or event mapper for
  CPE/CME.
- Produce a clean verification trail proving no active repo surface still
  depends on CPE/CME.

## 4. Non-Goals

- No migration of historical CPE/CME runs.
- No backfill from `.codex-orchestrator`, `.orchestrator`, Claude learning logs,
  Codex learning logs, or other old local run stores.
- No adapter that lets AgentRunway execute old CPE/CME state machines.
- No compatibility aliases for `kws-cpe`, `kws-cme`, or `kws.orchestrator`.
- No deletion of git history.
- No automatic deletion of user-home historical data such as `~/.agentlens`,
  `~/.codex`, or `~/.claude`. Those are outside the repo cleanup scope and may
  contain unrelated user data.
- No broad redesign of AgentLens event schema for generic Claude/Codex capture.
  AgentLens may still ingest non-AgentRunway events for its own capture/importer
  features; only the official execution orchestrator contract is AgentRunway.

## 5. Architecture

The repository should have one execution path:

```text
approved spec/plan
  -> skills/agent-runway/SKILL.md
  -> skills/agent-runway/scripts/agentrunway.py
  -> ~/.agentrunway/runs/<workspace>/<run_id>/
     -> SQLite state
     -> contract.json
     -> events.jsonl
     -> artifact_graph.json
     -> coverage.json
  -> AgentLens
     -> agentrunway.* events
     -> AgentRunway projection and evidence coverage
```

AgentRunway is the source of truth for execution state. AgentLens is an
observation and evaluation layer. Workers never write AgentLens directly; the
runner emits only facts it has validated or accepted.

CPE/CME are not sidecars in this architecture. They are removed inputs.

## 6. Removal Scope

### 6.1 Delete Skill Trees

Delete these directories entirely:

```text
skills/kws-codex-plan-executor/
skills/kws-claude-multi-agent-executor/
```

This includes their `SKILL.md`, docs, references, evals, fixtures, scripts,
templates, experiments, and generated learning materials inside those
directories.

### 6.2 Delete or Rewrite Active AgentLens/KWS Plans

Delete plans/specs whose central purpose is CPE/CME AgentLens integration,
including:

```text
AgentLens/docs/spec/2026-05-19-agentlens-skill-auto-record-design.md
AgentLens/docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md
```

If an older AgentLens document is primarily about another topic but contains a
CPE/CME example, rewrite that example to AgentRunway or remove the example.

If an obsolete `agentlens-kws-common-observability-contract` spec/plan appears
in a future checkout, delete it rather than updating it.

### 6.3 Rewrite AgentRunway Source Of Truth Docs

AgentRunway docs should point to the current AgentRunway-only model:

- `skills/agent-runway/README.md`
- `skills/agent-runway/SKILL.md`
- `skills/agent-runway/AGENTS.md`
- `skills/agent-runway/references/agentlens-events.md`
- current AgentRunway specs/plans under `docs/superpowers/`

These docs must not describe CPE/CME as legacy-supported paths. If mentioned at
all, they should appear only in this removal design or in a brief superseded
note explaining that they were deleted.

### 6.4 Rewrite AgentLens Active Docs and Tests

AgentLens active docs and tests should use AgentRunway examples when discussing
executor observability:

```text
agentrunway.run_started
agentrunway.worker_dispatched
agentrunway.worker_result
agentrunway.review_result
agentrunway.verification_result
agentrunway.gate_retry
agentrunway.merge_ready
agentrunway.merge_conflict
agentrunway.run_blocked
agentrunway.run_finished
```

Remove examples, fixtures, or tests that require these strings:

```text
kws-cpe
kws-cme
kws.orchestrator
```

The AgentLens schema may continue to allow lowercase dotted namespaces for
generic extensibility, but no test or doc should imply that CPE/CME is a
supported executor integration.

## 7. Data Flow

### 7.1 Run Start

1. The host invokes AgentRunway with a plan/spec or topic.
2. AgentRunway resolves inputs, checks state, and creates its local run.
3. AgentRunway opens an AgentLens container run when AgentLens is available.
4. AgentRunway writes `agentrunway.run_started` locally and emits it to
   AgentLens best-effort.

### 7.2 Worker and Gate Flow

1. AgentRunway dispatches workers through runtime adapters.
2. Workers return bounded result artifacts.
3. AgentRunway validates method audit, changed files, task claims, review
   result, verification result, and merge readiness.
4. AgentRunway records accepted facts locally and emits `agentrunway.*` events.

### 7.3 Finish and Recovery

1. AgentRunway records final status in local state.
2. AgentRunway closes AgentLens best-effort.
3. `status`, `inspect`, `summarize`, `resume`, `apply`, and `clean` read
   AgentRunway state, not CPE/CME state.
4. There is no CPE/CME import, replay, or fallback path.

## 8. Error Handling

- AgentLens unavailable: AgentRunway continues and records degraded
  observability locally.
- AgentLens emit failure: AgentRunway records emit failure and continues.
- Deleted CPE/CME invocation: no compatibility shim is provided. The old skill
  names are absent from the repo.
- Documentation references left behind: verification fails until they are
  deleted or rewritten.
- Historical local data: ignored by this plan unless a separate explicit cleanup
  request targets user-home stores.

## 9. Testing Strategy

### 9.1 Removal Guards

Add or update tests/scripts so the active repo fails verification when active
paths contain CPE/CME references. The guard should scan:

```text
AgentLens/src/
AgentLens/tests/
AgentLens/docs/
skills/agent-runway/
docs/superpowers/specs/
docs/superpowers/plans/
```

The guard may exclude this removal design and any generated graph output.

### 9.2 AgentRunway Verification

Run the AgentRunway eval suite after deletion and doc rewrites:

```bash
cd skills/agent-runway
./evals/run.sh
```

Focused tests should cover:

- AgentLens disabled/unavailable behavior.
- AgentLens fake CLI emission.
- `agentrunway.*` local journal records.
- status/inspect/summarize output.
- resume/apply/clean paths that previously overlapped with old executor
  concepts.

### 9.3 AgentLens Verification

Run focused AgentLens tests for schema, event append, query, evaluator, and
AgentRunway projection:

```bash
cd AgentLens
python -m pytest \
  tests/unit/test_agentrunway_events.py \
  tests/unit/test_schema_validation.py \
  tests/unit/test_event_query.py \
  tests/integration/test_event_append.py \
  tests/integration/test_failure_isolation.py \
  tests/integration/test_phase1_smoke.py \
  tests/integration/test_eval_determinism.py \
  -v
```

### 9.4 Repository Verification

Run:

```bash
rg -n "kws-cpe|kws-cme|kws\\.orchestrator" \
  AgentLens/src AgentLens/tests AgentLens/docs \
  skills docs/superpowers/specs docs/superpowers/plans

git diff --check
graphify update .
```

The `rg` command should return no active references except this removal design
while the design is still present. Once implementation is complete, the final
guard can allow only explicit superseded/removal notes, or can require zero
matches if the removal design is moved out of the scanned set.

## 10. Rollout Plan

1. Freeze the new source of truth with this design.
2. Write a new implementation plan that supersedes older AgentRunway/CPE/CME
   plans.
3. Delete CPE/CME skill directories.
4. Delete CPE/CME-specific AgentLens specs/plans.
5. Rewrite AgentLens active examples and fixtures to AgentRunway.
6. Rewrite AgentRunway docs so they do not mention legacy support.
7. Add removal guards.
8. Run AgentRunway evals and AgentLens focused tests.
9. Run `git diff --check`.
10. Run `graphify update .` after code changes.
11. Commit the removal separately from unrelated in-progress AgentRunway code
    changes unless the user explicitly asks to combine them.

## 11. Acceptance Criteria

- `skills/kws-codex-plan-executor/` is deleted.
- `skills/kws-claude-multi-agent-executor/` is deleted.
- No active docs, tests, schemas, help text, or fixtures present CPE/CME as a
  supported or legacy-supported execution path.
- AgentRunway docs describe AgentRunway as the only execution orchestrator.
- AgentLens executor observability examples use `agentrunway.*`.
- There is no CPE/CME importer, bridge, fallback parser, compatibility shim, or
  event mapper.
- AgentRunway evals pass.
- AgentLens focused tests pass.
- `git diff --check` passes.
- `graphify update .` is run after code changes.
- Unrelated pre-existing AgentRunway worktree changes are preserved.
