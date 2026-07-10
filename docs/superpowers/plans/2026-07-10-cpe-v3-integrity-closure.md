# CPE v3 Integrity Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship CPE `3.0.1` as a fail-closed deterministic executor whose completion, task scope, packets, recovery, public output, and release claims are all derived from current immutable evidence.

**Architecture:** Preserve the event-sourced v3 runtime and split its integrity boundary into focused `PlanCompiler`, `PacketStore`, `AttemptController`, `RunKernel`, `CanonicalValidator`, `RecoveryEngine`, and `PublicCLI` responsibilities. Every product write advances a CPE-measured worktree revision; acceptance and typed read-only verdicts are valid only for that revision. Public execution, resume, repair, inspection, and tests use the same manifest, event projection, packet index, and canonical validator.

**Tech Stack:** Python 3.11+, standard library, PyYAML 6.0.3 for eval fixtures, Bash eval harness, Git worktrees and patches, Codex CLI JSONL, JSON/JSONL filesystem artifacts, JSON Schema, Bun repository checks, Graphify.

## Global Constraints

- Source design: `docs/superpowers/specs/2026-07-10-cpe-v3-integrity-closure-design.md`.
- Audit basis: `origin/main` commit `93c7730df45ab661df23f420b7b145e0aa5579df`.
- Preserve the active v3 architecture. Do not restore the removed mutable v2 runtime or interpret, resume, repair, migrate, or rewrite v2 state.
- During Tasks 1-12, CPE `3.0.0` must report `integrity-closure-pending; paid-live-pending` with `release_ready=false`.
- Bump to `3.0.1` and `deterministic-ready; paid-live-pending` only in Task 13 after all L0-L4 checks pass.
- Do not run the paid live matrix. Keep `release_ready=false` without a current approved external report digest.
- Keep CPE independent from Waygent and preserve Sol/high core plus Terra/high read-only scout routing without aliases, fallbacks, profiles, or new model options.
- `RunKernel` is the only writer of manifest indexes, packets, events, evidence indexes, and state snapshots.
- Workers never commit, reset, clean, rewrite history, edit the source checkout, or write durable run artifacts.
- Implementation and repair are the only product-writing roles. Scout, task review, verification, and final review are read-only.
- Every non-empty write-attempt delta advances `worktree_revision`, including failed or out-of-scope writes.
- Only current-revision acceptance, task-review, verification, repository-check, and final-review evidence may authorize completion.
- Execute shared-runtime tasks sequentially. Parallelism is limited to bounded read-only scouts and independent verification commands.
- Use TDD within every task, run the listed focused check before committing, and preserve unrelated user changes.
- During implementation, do not update Graphify until Task 13; then commit Graphify outputs separately so freshness can identify a graph-only commit. The planning-session graph refresh is separate evidence for this plan document.

---

## Context And File Structure

| Path | Responsibility after this plan |
| --- | --- |
| `scripts/cpe_runtime/plan_compiler.py` | Read-only plan/spec/docs compilation and preflight result |
| `scripts/cpe_runtime/packets.py` | Canonical task-packet bytes, digest metadata, and verification |
| `scripts/cpe_runtime/git_delta.py` | HEAD/status/patch snapshot and task-specific scope comparison |
| `scripts/cpe_runtime/attempt_controller.py` | Role policy, packet-bound prompts, provider launch, verdict and delta capture |
| `scripts/cpe_runtime/manifest.py` | Immutable internal input records, packet index, source metadata |
| `scripts/cpe_runtime/events.py` | Writable v3 event vocabulary and historical v3 read compatibility |
| `scripts/cpe_runtime/projector.py` | Pure lifecycle, revision, blocker, attempt, verdict, and artifact projection |
| `scripts/cpe_runtime/kernel.py` | Exclusive initialization, transitions, event append, projection, snapshot |
| `scripts/cpe_runtime/validation.py` | `validate_integrity` and `validate_completion` shared profiles |
| `scripts/cpe_runtime/scheduler.py` | Sequential revision-aware task and final-review loop |
| `scripts/cpe_runtime/reconciliation.py` | Integrity findings without treating healthy incompletion as drift |
| `scripts/cpe_runtime/repair.py` | Evidence-backed compensating events and retry scheduling |
| `scripts/cpe_runtime/public_result.py` | Stable public/headless JSON and exit classification |
| `scripts/cpe_runtime/prompt_export.py` | Collision-safe single-block prompt and handoff export |
| `scripts/cpe.py` | Public run/resume/export router and initialization cleanup |
| `evals/maintained-checks.json` | Explicit maintained eval inventory and production entrypoint evidence |

Existing `scripts/build_task_packet.py`, `scripts/validate_state.py`, `scripts/reconcile_state.py`, `scripts/repair_runs.py`, `scripts/inspect_runs.py`, and `scripts/normalize_cpe_run.py` remain thin public adapters. They must not contain a second runtime implementation.

## Execution Order

- Required sequence: T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12 → T13.
- T2-T10 modify shared runtime modules and must not run concurrently.
- T11 owns eval-harness deletion and rewiring after the replacement public paths exist.
- T12 aligns active documentation while the version remains `3.0.0` pending.
- T13 is the only release gate and the only task allowed to update Graphify or publish `3.0.1` readiness.
- No human approval gate exists inside Tasks 1-13 because paid execution and external writes are out of scope.

---

### Task 1: Downgrade The Unproven 3.0.0 Release Claim

```yaml
id: T1
title: Truthful pending release metadata
owner_boundary: Release metadata and its deterministic contract only
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_release_contract.py
expected: passed=true and release_ready=false with integrity-closure-pending
risks: [Active docs currently claim deterministic readiness from checks that do not exercise the audited failures.]
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/release-process.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/decisions.md`
- Modify: `skills/kws-codex-plan-executor/evals/live-migration/release-status.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_release_contract.py`

**Spec Refs:** S1.1, S1.2, S1.15, S1.17

**Interfaces:**
- Produces the only accepted `3.0.0` status tuple: `("integrity-closure-pending; paid-live-pending", False)`.
- Task 13 replaces this tuple with the `3.0.1` deterministic-ready tuple after L0-L4 evidence exists.

- [ ] **Step 1: Change the release-contract test to require pending integrity state**

Replace the `3.0.0` branch in `check_release_contract.py` with:

```python
if version == "3.0.0":
    expected_status = "integrity-closure-pending; paid-live-pending"
    checks["integrity_closure_is_pending"] = release_status == expected_status
    checks["release_ready_is_false"] = live_status.get("release_ready") is False
    checks["paid_live_is_pending"] = live_status.get("paid_live_status") == "pending"
```

- [ ] **Step 2: Run the contract and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_release_contract.py`

Expected: FAIL because active metadata still says `deterministic-ready; paid-live-pending`.

- [ ] **Step 3: Align all active 3.0.0 metadata**

Set the YAML and JSON values exactly:

```yaml
version: "3.0.0"
release_status: "integrity-closure-pending; paid-live-pending"
```

```json
{
  "version": "3.0.0",
  "deterministic_status": "integrity-closure-pending",
  "paid_live_status": "pending",
  "release_ready": false
}
```

Add one dated `HISTORY.md` note stating that the downgrade is evidence correction, not an architectural rollback.

- [ ] **Step 4: Run the focused release and docs contracts**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_release_contract.py && python3 evals/check_docs_contract.py`

Expected: both commands exit 0 and report `passed=true`.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/docs/release-process.md \
  skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md \
  skills/kws-codex-plan-executor/docs/decisions.md \
  skills/kws-codex-plan-executor/evals/live-migration/release-status.json \
  skills/kws-codex-plan-executor/evals/check_release_contract.py
git commit -m "fix(cpe): mark v3 integrity closure pending"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_release_contract.py
```

---

### Task 2: Compile Current Plans Before Any Durable Mutation

```yaml
id: T2
title: Read-only PlanCompiler and internal input snapshots
owner_boundary: Plan, spec, docs, capability, and source-input compilation
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_plan_executability_audit.py && python3 evals/check_run_readiness.py
expected: approved integrity plan compiles and every blocking failure leaves run and worktree roots absent
risks: [The current public parser rejects the approved v3 plan shape and preflight audits are not in execute_run.]
```

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/plan_compiler.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/scripts/parse_plan.py`
- Modify: `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`
- Modify: `skills/kws-codex-plan-executor/scripts/audit_superpowers_compatibility.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Create: `skills/kws-codex-plan-executor/evals/parser-fixtures/18-integrity-closure-plan.yaml`
- Create: `skills/kws-codex-plan-executor/evals/parser-fixtures/19-v3-quality-plan.yaml`

**Spec Refs:** S1.6.1, S1.7, S1.11.1, S1.17

**Depends on:** 1

**Interfaces:**
- Produces `CompiledRun(tasks, spec_manifest, sources, source_head, source_status)` as an immutable dataclass.
- Produces `InputSource(role, source_path, sha256, content)`; Task 3 passes these bytes to `RunKernel.initialize`.
- Produces `read_git_basis(workspace) -> tuple[str, tuple[str, ...]]`, `compile_tasks(parsed, spec_manifest) -> tuple[dict[str, object], ...]`, and `snapshot_source_bytes(plan, spec, docs) -> tuple[InputSource, ...]`.
- Each compiled task contains `execution_contract` with allowed/forbidden paths and acceptance command, plus `source_hashes` for plan and selected spec sections.
- The audit adapters export `assert_superpowers_compatible(plan, workspace)` and `assert_plan_executable(plan, spec, workspace)`; success returns `None`, failure raises `CompileBlocked`.
- Raises `CompileBlocked(category, summary, evidence)` without creating a run directory or worktree.

- [ ] **Step 1: Replace constant audit checks with a failing production call**

The focused check must call the public compiler and assert no mutation:

```python
compiled = compile_run(
    plan=repo / "docs/superpowers/plans/2026-07-10-cpe-v3-integrity-closure.md",
    spec=repo / "docs/superpowers/specs/2026-07-10-cpe-v3-integrity-closure-design.md",
    docs=(),
    workspace=repo,
    mode="interactive",
)
assert len(compiled.tasks) == 13
assert compiled.sources[0].role == "plan"
assert not run_root.exists()
assert not worktree_root.exists()
```

Run the same compiler against `docs/superpowers/plans/2026-07-10-cpe-v3-quality-model-routing.md` and its approved design; it must compile 12 tasks instead of repeating the audited `task_1 has no Files block` failure.

- [ ] **Step 2: Run the checks and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_plan_executability_audit.py`

Expected: FAIL because `cpe_runtime.plan_compiler` does not exist.

- [ ] **Step 3: Add immutable compiler types and checks**

Create the module with these public types and entrypoint:

```python
@dataclass(frozen=True)
class InputSource:
    role: str
    source_path: Path
    sha256: str
    content: bytes


@dataclass(frozen=True)
class CompiledRun:
    tasks: tuple[dict[str, object], ...]
    spec_manifest: dict[str, object] | None
    sources: tuple[InputSource, ...]
    source_head: str
    source_status: tuple[str, ...]


class CompileBlocked(ValueError):
    def __init__(self, category: str, summary: str, evidence: dict[str, object]):
        super().__init__(summary)
        self.category = category
        self.summary = summary
        self.evidence = evidence


def compile_run(*, plan: Path, spec: Path | None, docs: tuple[Path, ...], workspace: Path, mode: str) -> CompiledRun:
    head, status = read_git_basis(workspace)
    parsed = parse_plan(plan, workspace, mode)
    spec_manifest = build_spec_manifest(spec) if spec else None
    tasks = compile_tasks(parsed, spec_manifest)
    assert_safe_commands(tasks)
    assert_clean_claimed_scope(status, tasks)
    assert_superpowers_compatible(plan, workspace)
    assert_plan_executable(plan, spec, workspace)
    sources = snapshot_source_bytes(plan, spec, docs)
    return CompiledRun(tuple(tasks), spec_manifest, sources, head, tuple(status))
```

Move `_compile_tasks`, `_check_dirty_scope`, and read-only Git basis logic out of `cpe.py`. Convert both audit scripts to importable functions whose CLI adapters only serialize their return values. Extend `parse_plan.py` to read task-local plain `yaml` `files`, `spec_refs`, and `acceptance` metadata used by the approved quality/model-routing plan while preserving standard `**Files:**` parsing.

- [ ] **Step 4: Add the real-plan golden fixture**

`18-integrity-closure-plan.yaml` must point to this committed plan and assert task IDs `task_1` through `task_13`, explicit file claims, numeric dependencies, and non-empty acceptance commands. `19-v3-quality-plan.yaml` must point to the approved quality/model-routing plan and assert its 12 task-local YAML contracts. The fixture checker must load actual Markdown rather than duplicating either plan as a fixture string.

- [ ] **Step 5: Run focused checks and the parser matrix**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_plan_executability_audit.py && python3 evals/check_run_readiness.py && python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/18-integrity-closure-plan.yaml && python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/19-v3-quality-plan.yaml`

Expected: all three commands exit 0; the real plan compiles to 13 tasks and preflight-blocked cases create no run/worktree paths.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/plan_compiler.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/scripts/parse_plan.py \
  skills/kws-codex-plan-executor/scripts/audit_plan_executability.py \
  skills/kws-codex-plan-executor/scripts/audit_superpowers_compatibility.py \
  skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py \
  skills/kws-codex-plan-executor/evals/check_run_readiness.py \
  skills/kws-codex-plan-executor/evals/parser-fixtures/18-integrity-closure-plan.yaml \
  skills/kws-codex-plan-executor/evals/parser-fixtures/19-v3-quality-plan.yaml
git commit -m "feat(cpe): compile plans before run mutation"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_plan_executability_audit.py && python3 evals/check_run_readiness.py
```

---

### Task 3: Make Task Packets Immutable Runtime Inputs

```yaml
id: T3
title: Canonical PacketStore and manifest packet index
owner_boundary: Packet construction, persistence request, digest verification, and worker reference
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_task_packet.py && python3 evals/check_preflight_dispatch.py
expected: packet mutation blocks dispatch and all roles receive the indexed packet digest
risks: [The runtime packet builder and the legacy CLI builder currently disagree, and the scheduler ignores both packet files.]
```

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/packets.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py`
- Modify: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`

**Spec Refs:** S1.6.2, S1.7, S1.11.1, S1.17

**Depends on:** 2

**Interfaces:**
- Produces `PacketDraft(task_id, relative_path, media_type, sha256, content)`.
- Produces `build_packet(compiled, task) -> PacketDraft` and `verify_packet(run_dir, manifest, task_id) -> PacketDraft`.
- Produces `PACKET_ROLE_POLICY`, the serialized role capabilities imported and enforced by Task 5.
- `RunKernel.initialize` is the sole function allowed to write packet bytes and manifest packet entries.

- [ ] **Step 1: Add packet-consumption and mutation regressions**

Use a packet whose task body contains a unique sentinel:

```python
packet = build_packet(compiled, compiled.tasks[0])
kernel = RunKernel.initialize(run_dir, manifest_draft, compiled.sources, (packet,))
verified = verify_packet(run_dir, load_verified_manifest(run_dir / "run_manifest.json"), packet.task_id)
assert b"PACKET_SENTINEL" in verified.content
(run_dir / verified.relative_path).write_bytes(b"{}\n")
assert verify_packet_errors(run_dir, manifest, packet.task_id) == ["packet_digest_mismatch"]
```

The dispatch check must assert that `WorkerRequest.packet_path` and `packet_sha256` match the manifest entry for implementation, review, verification, repair, and final review.

- [ ] **Step 2: Run focused checks and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_task_packet.py`

Expected: FAIL because packets are not indexed or verified by production runtime.

- [ ] **Step 3: Implement one packet schema and canonical bytes**

Create `packets.py` around this immutable record:

```python
@dataclass(frozen=True)
class PacketDraft:
    task_id: str
    relative_path: str
    media_type: str
    sha256: str
    content: bytes


def canonical_packet_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def packet_draft(task: dict[str, object], sections: list[dict[str, object]]) -> PacketDraft:
    payload = {
        "schema_version": "3.1",
        "task_id": task["id"],
        "task": task,
        "spec_sections": sections,
        "execution_contract": task["execution_contract"],
        "required_methods": ["using-superpowers", "test-driven-development"],
        "role_policy": PACKET_ROLE_POLICY,
        "evidence_requirements": ["git_delta", "acceptance", "task_review", "verification"],
        "source_hashes": task["source_hashes"],
    }
    content = canonical_packet_bytes(payload)
    digest = hashlib.sha256(content).hexdigest()
    return PacketDraft(str(task["id"]), f"artifacts/task-packets/{task['id']}.json", "application/json", digest, content)
```

Define `PACKET_ROLE_POLICY` in the same module with the six exact roles and boolean `read_only`, `verdict_capable`, and `product_write` fields. Task 5 must construct runtime `RolePolicy` values from this mapping rather than create a competing table.

Make `build_task_packet.py` a thin adapter that calls this function. Remove heuristic full-spec mapping and reject absent explicit `spec_refs`.

- [ ] **Step 4: Persist and verify through RunKernel**

Add an initialization helper that opens every packet with `O_CREAT|O_EXCL|O_NOFOLLOW`, fsyncs it, indexes `{task_id,path,media_type,sha256}` in the immutable manifest, and publishes the run directory only after every digest re-verifies. `preflight_dispatch.py` must call `verify_packet` instead of trusting packet-local `sha256` text.

- [ ] **Step 5: Run packet, dispatch, and manifest checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_task_packet.py && python3 evals/check_preflight_dispatch.py && python3 evals/check_manifest_evidence.py`

Expected: all commands exit 0; mutation returns `packet_digest_mismatch` and dispatch never reaches the provider.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/packets.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py \
  skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/scripts/preflight_dispatch.py \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/evals/check_task_packet.py \
  skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
git commit -m "feat(cpe): bind task packets to the run manifest"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_task_packet.py && python3 evals/check_preflight_dispatch.py
```

---

### Task 4: Project Revisions And Typed Blocker Lifecycles

```yaml
id: T4
title: Expanded event vocabulary and pure projection
owner_boundary: Events, state transitions, current revision, blocker history, and replay
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_event_kernel.py && python3 evals/check_cpe_replay.py
expected: replay projects revisions and resolves active blockers without deleting history
risks: [Existing blocker arrays are append-only and blocked task transitions cannot express a retry phase.]
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/events.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/references/event-journal.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_event_kernel.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`

**Spec Refs:** S1.6.4, S1.10, S1.13, S1.17

**Depends on:** 3

**Interfaces:**
- Produces writable events `attempt.started`, `attempt.completed`, `verdict.recorded`, `worktree.revision_recorded`, `blocker.opened`, `blocker.updated`, `blocker.resolved`, and `task.retry_scheduled`.
- Keeps `attempt.recorded` readable for historical v3 events but never emits it on a new run.
- Projects `worktree_revision`, `active_blockers`, `blocker_history`, `verdicts`, and `retry_queue`.

- [ ] **Step 1: Add replay-first failing tests**

Build an event sequence that opens and resolves a blocker, then records a revision:

```python
events = signed_events([
    event("blocker.opened", {"blocker_id": "B1", "category": "verification", "owner": "cpe", "resume_condition": "acceptance passes"}, task_id="T1"),
    event("blocker.resolved", {"blocker_id": "B1", "evidence_refs": [evidence_ref]}, task_id="T1"),
    event("task.retry_scheduled", {"phase": "acceptance", "root_cause_key": "acceptance:1", "worktree_revision": 2}, task_id="T1"),
    event("worktree.revision_recorded", {"from": 2, "to": 3, "patch_sha256": "a" * 64}, task_id="T1"),
])
state = project(manifest, events)
assert state["active_blockers"] == []
assert state["blocker_history"][0]["status"] == "resolved"
assert state["worktree_revision"] == 3
assert state["retry_queue"][0]["phase"] == "acceptance"
```

- [ ] **Step 2: Run the event checks and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_event_kernel.py`

Expected: FAIL with `unknown event type`.

- [ ] **Step 3: Separate writable and read-compatible event sets**

Define exact sets:

```python
WRITABLE_EVENT_TYPES = frozenset({
    "run.status_changed", "task.status_changed", "task.retry_scheduled",
    "attempt.started", "attempt.completed", "verdict.recorded",
    "evidence.attached", "worktree.revision_recorded",
    "blocker.opened", "blocker.updated", "blocker.resolved",
    "repair.applied", "context.updated", "completion.recorded",
})
READ_COMPAT_EVENT_TYPES = WRITABLE_EVENT_TYPES | {"attempt.recorded"}
```

`append_event` accepts only `WRITABLE_EVENT_TYPES`; `validate_chain` and `project` accept `READ_COMPAT_EVENT_TYPES`.

- [ ] **Step 4: Project blockers by ID and validate event payloads**

Use a dictionary while projecting active blockers, append a copy to history on open, update both on update, remove only from active state on resolve, and require resolution evidence. `task.retry_scheduled` must require a valid phase and may transition a blocked task to the phase's entry state without a generic `blocked -> ready` guess.

- [ ] **Step 5: Run replay, schema, and event checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_event_kernel.py && python3 evals/check_state_schema.py && python3 evals/check_cpe_replay.py`

Expected: all commands exit 0; replay parity holds and resolved blockers remain historical only.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/events.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py \
  skills/kws-codex-plan-executor/references/event-journal.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/evals/check_event_kernel.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/evals/check_cpe_replay.py
git commit -m "feat(cpe): project revisions and blocker lifecycle"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_event_kernel.py && python3 evals/check_cpe_replay.py
```

---

### Task 5: Enforce Role Isolation And Typed Verdicts

```yaml
id: T5
title: AttemptController role policy and verdict schema
owner_boundary: Provider request policy, packet-bound prompts, result schema, and verdict consistency
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py && python3 evals/check_fault_injection.py --case verdicts
expected: only read-only review roles can issue valid verdicts and negative evidence cannot report passed
risks: [All current core attempts launch workspace-write and status completed is incorrectly treated as a passed review.]
```

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/attempt_controller.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/worker.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/model_policy.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py`
- Modify: `skills/kws-codex-plan-executor/templates/worker-result-schema.json`
- Modify: `skills/kws-codex-plan-executor/references/verifier-prompt.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_execution_runtime.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_fault_injection.py`

**Spec Refs:** S1.6.3, S1.9, S1.12, S1.17

**Depends on:** 4

**Interfaces:**
- Produces `RolePolicy(read_only, verdict_capable, product_write)` and `ROLE_POLICIES` derived from Task 3's `PACKET_ROLE_POLICY`.
- Extends `WorkerRequest` with `task_id`, `packet_path`, `packet_sha256`, and `worktree_revision`.
- Produces `validate_verdict(payload, role, revision) -> dict[str, object]`.

- [ ] **Step 1: Add failing role and verdict cases**

The check must cover all six roles and these contradictions:

```python
assert ROLE_POLICIES["implementation"] == RolePolicy(False, False, True)
assert ROLE_POLICIES["repair"] == RolePolicy(False, False, True)
assert ROLE_POLICIES["task_review"] == RolePolicy(True, True, False)
assert ROLE_POLICIES["verification"] == RolePolicy(True, True, False)
assert ROLE_POLICIES["final_review"] == RolePolicy(True, True, False)
assert ROLE_POLICIES["scout"] == RolePolicy(True, False, False)

try:
    validate_verdict({
        "status": "passed",
        "findings": [{"severity": "critical", "summary": "false completion"}],
        "missing_evidence": [],
        "worktree_revision": 2,
    }, "task_review", 2)
except WorkerError as exc:
    assert str(exc) == "passed verdict conflicts with critical findings"
else:
    raise AssertionError("critical findings must reject a passed verdict")
```

Also assert `blocked` requires `owner` and `resume_condition`, while `inconclusive` requires `next_evidence_action`.

- [ ] **Step 2: Run the focused check and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py`

Expected: FAIL because `RolePolicy` and typed verdict validation do not exist.

- [ ] **Step 3: Implement exact role policy and request validation**

Create the controller foundation:

```python
@dataclass(frozen=True)
class RolePolicy:
    read_only: bool
    verdict_capable: bool
    product_write: bool


ROLE_POLICIES = {
    role: RolePolicy(
        bool(policy["read_only"]),
        bool(policy["verdict_capable"]),
        bool(policy["product_write"]),
    )
    for role, policy in PACKET_ROLE_POLICY.items()
}


def validate_role_request(role: str, request: WorkerRequest) -> RolePolicy:
    policy = ROLE_POLICIES[role]
    if request.read_only != policy.read_only or request.verdict_capable != policy.verdict_capable:
        raise WorkerError("worker request violates role policy")
    if not request.packet_path or len(request.packet_sha256) != 64:
        raise WorkerError("worker request is not packet-bound")
    return policy
```

`Worker.run` must derive the sandbox from this policy and reject caller-supplied conflicts. Rename the active model-policy attempt kind from `review` to `task_review`; keep `review` only as historical input normalization and route both names to Sol/high without changing the fixed model surface.

- [ ] **Step 4: Replace status-only review semantics with typed verdicts**

Update the JSON schema so verdict roles return:

```json
{
  "verdict": {
    "status": "passed",
    "findings": [],
    "missing_evidence": [],
    "worktree_revision": 2
  }
}
```

`implementation`, `repair`, and `scout` require `verdict: null`. Review roles require a non-null verdict. Validate contradictions in Python even if JSON Schema passes. Store the normalized verdict with `verdict.recorded`; never infer it from worker `status`.

- [ ] **Step 5: Bind every prompt to packet and revision**

Build prompt input with exact fields:

```python
def packet_prompt(request: WorkerRequest, instruction: str) -> str:
    return json.dumps({
        "task_id": request.task_id,
        "packet_path": request.packet_path,
        "packet_sha256": request.packet_sha256,
        "worktree_revision": request.worktree_revision,
        "instruction": instruction,
    }, ensure_ascii=False, sort_keys=True)
```

The prompt must not inline a second task body or full spec.

- [ ] **Step 6: Run role, model, and verdict checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py && python3 evals/check_model_policy.py && python3 evals/check_fault_injection.py --case verdicts`

Expected: all commands exit 0; review launchers are read-only and contradictory verdicts fail closed.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/attempt_controller.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/worker.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/model_policy.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py \
  skills/kws-codex-plan-executor/templates/worker-result-schema.json \
  skills/kws-codex-plan-executor/references/verifier-prompt.md \
  skills/kws-codex-plan-executor/evals/check_execution_runtime.py \
  skills/kws-codex-plan-executor/evals/check_fault_injection.py
git commit -m "feat(cpe): enforce role policy and typed verdicts"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py && python3 evals/check_fault_injection.py --case verdicts
```

---

### Task 6: Measure Every Write From The Real Git Delta

```yaml
id: T6
title: Revision-bound Git delta and task scope enforcement
owner_boundary: Worktree snapshots, cumulative patch evidence, revision allocation, and per-task scope
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_run_diffs.py && python3 evals/check_fault_injection.py --case scope
expected: cross-task writes and HEAD changes block before review while every non-empty delta advances revision
risks: [Worker-reported changed_files can hide edits and final union-scope validation cannot identify the responsible task.]
```

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/git_delta.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/attempt_controller.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/scripts/check_run_diffs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_diffs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_fault_injection.py`

**Spec Refs:** S1.8, S1.11.2, S1.17, S1.18

**Depends on:** 5

**Interfaces:**
- Produces `GitSnapshot(head, files, cumulative_patch_sha256)` and `GitDelta(changed_files, patch_sha256, patch_bytes, head_changed)`.
- Produces `capture_snapshot(worktree)`, `capture_binary_patch(worktree, changed_files)`, `diff_snapshots(before, after, worktree)`, and `scope_errors(delta, allowed, forbidden)`.
- `AttemptController.run_write_attempt` emits `worktree.revision_recorded` before evaluating scope or acceptance.

- [ ] **Step 1: Add a two-task ownership regression**

Create tracked `owned-a.txt` and `owned-b.txt`. Let T1's implementation change `owned-b.txt` while reporting only `owned-a.txt`, then assert:

```python
result = run_tasks(task_graph, fake_worker, kernel)
state = load_projected_state(run_dir)
assert result["status"] == "blocked"
assert state["worktree_revision"] == 1
assert state["active_blockers"][0]["category"] == "policy_violation"
assert state["active_blockers"][0]["root_cause_key"] == "task_scope:T1:owned-b.txt"
assert not any(v["status"] == "passed" for v in state["verdicts"])
```

Add a second case where a write attempt runs `git commit`; it must set `head_changed=True`, advance revision, and block.

- [ ] **Step 2: Run scope checks and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_fault_injection.py --case scope`

Expected: FAIL because the scheduler trusts worker `changed_files` and validates only final union scope.

- [ ] **Step 3: Implement full-tree boundary snapshots**

Use tracked plus untracked paths and hash file bytes, symlink targets, or a deletion marker:

```python
@dataclass(frozen=True)
class GitSnapshot:
    head: str
    files: tuple[tuple[str, str], ...]
    cumulative_patch_sha256: str


@dataclass(frozen=True)
class GitDelta:
    changed_files: tuple[str, ...]
    patch_sha256: str
    patch_bytes: bytes
    head_changed: bool


def diff_snapshots(before: GitSnapshot, after: GitSnapshot, worktree: Path) -> GitDelta:
    before_map = dict(before.files)
    after_map = dict(after.files)
    changed = tuple(sorted(path for path in before_map.keys() | after_map.keys() if before_map.get(path) != after_map.get(path)))
    patch = capture_binary_patch(worktree, changed)
    return GitDelta(changed, hashlib.sha256(patch).hexdigest(), patch, before.head != after.head)
```

Do not use mtime. Include untracked files in both snapshots and patch evidence. `scope_errors` must use `pathlib.PurePosixPath.match` plus exact path equality, return sorted `forbidden_write:<path>` before `unclaimed_write:<path>`, and add `worktree_head_changed` whenever `head_changed` is true.

- [ ] **Step 4: Record revision before policy decisions**

For every non-empty `GitDelta`, write immutable patch evidence, emit `worktree.revision_recorded` with `from`, `to`, `task_id`, `attempt_id`, `changed_files`, and digest, then validate current-task allowed and forbidden globs. Worker `changed_files` is stored only as diagnostic comparison.

- [ ] **Step 5: Run diff, event, and fault checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_run_diffs.py && python3 evals/check_event_kernel.py && python3 evals/check_fault_injection.py --case scope`

Expected: all commands exit 0; out-of-scope and HEAD-changing attempts block at revision 1 before review.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/git_delta.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/attempt_controller.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py \
  skills/kws-codex-plan-executor/scripts/check_run_diffs.py \
  skills/kws-codex-plan-executor/evals/check_run_diffs.py \
  skills/kws-codex-plan-executor/evals/check_fault_injection.py
git commit -m "feat(cpe): enforce task scope from git deltas"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_run_diffs.py && python3 evals/check_fault_injection.py --case scope
```

---

### Task 7: Make One Validator Authorize Every Completion

```yaml
id: T7
title: Canonical integrity and completion validation profiles
owner_boundary: Manifest, packet, event, replay, evidence, revision, verdict, worktree, and completion truth
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_validation_consumer_parity.py && python3 evals/check_fault_injection.py --case completion
expected: healthy running runs pass integrity, incomplete runs fail completion, and every consumer returns the same codes
risks: [Kernel, scheduler, validator, reconciliation, and inspector currently duplicate weaker completion rules.]
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/inspection.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_validation_consumer_parity.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_verification_bundle.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_fault_injection.py`

**Spec Refs:** S1.6.5, S1.11.3, S1.14.2, S1.17

**Depends on:** 6

**Interfaces:**
- Produces `validate_integrity(run_dir, candidate_state=None) -> ValidationReport`.
- Produces `validate_completion(run_dir, candidate_state=None) -> ValidationReport`.
- Produces internal `_validate(run_dir, check_names, candidate_state) -> ValidationReport`, which is the only check dispatcher.
- Keeps `validate_run` as a compatibility adapter: completed lifecycle uses completion profile; every other lifecycle uses integrity profile.

- [ ] **Step 1: Add the reproduced false-completion regression**

Construct a run where task review has a critical finding, verification has missing evidence, and final review changes accepted content. Assert:

```python
integrity = validate_integrity(run_dir)
completion = validate_completion(run_dir)
assert integrity.passed is True
assert completion.passed is False
assert "current_revision_task_review_not_passed" in completion.errors
assert "current_revision_verification_not_passed" in completion.errors
assert "current_revision_repository_check_missing" in completion.errors
```

The same run must return the same ordered codes from the standalone validator, kernel completion transition, reconciliation, repair planning, and inspector.

- [ ] **Step 2: Run parity and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_validation_consumer_parity.py`

Expected: FAIL because `validate_integrity` and `validate_completion` do not exist.

- [ ] **Step 3: Implement shared check groups and two profiles**

Use one ordered registry:

```python
INTEGRITY_CHECKS = (
    "schema", "manifest", "packets", "event_chain", "snapshot_replay",
    "artifacts", "worktree_identity", "attempt_structure", "git_scope",
)
COMPLETION_CHECKS = INTEGRITY_CHECKS + (
    "task_states", "current_revision_acceptance", "current_revision_verdicts",
    "repository_checks", "active_blockers", "completion_audit",
)


def validate_integrity(run_dir: Path, candidate_state: dict | None = None) -> ValidationReport:
    return _validate(run_dir, INTEGRITY_CHECKS, candidate_state)


def validate_completion(run_dir: Path, candidate_state: dict | None = None) -> ValidationReport:
    return _validate(run_dir, COMPLETION_CHECKS, candidate_state)
```

Each evidence check must require matching `worktree_revision`, `worktree_patch_sha256`, and `packet_sha256`. Stale evidence is a warning in integrity and an error in completion.

- [ ] **Step 4: Remove duplicate kernel completion logic**

Delete `_completion_ready`. Before appending `run.status_changed -> completed`, project the candidate state and require `validate_completion(..., candidate_state=state).passed`. `completion.recorded` may be appended only when its indexed evidence already passes the same profile.

- [ ] **Step 5: Port or delete v2-only validator checks**

Rewrite `check_validate_state_modular_parity.py` and `check_verification_bundle.py` against real v3 run directories and canonical evidence refs. Remove assertions for v1 mutable-state fields rather than weakening the v3 validator.

- [ ] **Step 6: Run validator and mutation checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_validation_consumer_parity.py && python3 evals/check_validate_state_modular_parity.py && python3 evals/check_verification_bundle.py && python3 evals/check_fault_injection.py --case completion`

Expected: all commands exit 0 and all consumers report identical ordered codes.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/inspection.py \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_validation_consumer_parity.py \
  skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py \
  skills/kws-codex-plan-executor/evals/check_verification_bundle.py \
  skills/kws-codex-plan-executor/evals/check_fault_injection.py
git commit -m "feat(cpe): centralize integrity and completion validation"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_validation_consumer_parity.py && python3 evals/check_fault_injection.py --case completion
```

---

### Task 8: Rebuild The Scheduler Around Current-Revision Evidence

```yaml
id: T8
title: Fail-closed task, repair, repository-check, and final-review loop
owner_boundary: Sequential orchestration from packet verification through canonical completion
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py && python3 evals/check_operational_run_quality.py
expected: acceptance precedes read-only verdicts and final-review repairs rerun every downstream gate
risks: [Current task completion accepts any completed review status and final review runs after tasks are irreversibly marked complete.]
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/attempt_controller.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_execution_runtime.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`

**Spec Refs:** S1.9, S1.11.2, S1.11.3, S1.17

**Depends on:** 7

**Interfaces:**
- Produces `run_task_cycle(task, controller, kernel) -> TaskCycleResult`.
- Produces `run_repository_checks(manifest, revision) -> tuple[EvidenceRef, ...]`.
- Produces `next_phase(state, task_id) -> str` and `route_verdict(verdict) -> str`; both reject unknown values instead of guessing.
- `run_tasks` returns completed only after a final `validate_completion` pass and revalidates before return.

- [ ] **Step 1: Add phase-order and invalidation regressions**

Record provider calls and assert the order:

```python
assert calls == [
    "implementation", "acceptance", "task_review", "verification",
    "repository_checks", "final_review",
]
```

In a second case, final review returns `changes_requested`; repair writes revision 2. Assert revision-1 acceptance, task-review, verification, repository-check, and final-review evidence are stale and the full ordered suffix runs again for revision 2.

- [ ] **Step 2: Run execution checks and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py`

Expected: FAIL because current order is review before acceptance and final-review writes are not repaired or revalidated.

- [ ] **Step 3: Implement the task cycle as an explicit phase loop**

Use exact phase dispatch:

```python
@dataclass(frozen=True)
class TaskCycleResult:
    status: str
    worktree_revision: int


def route_verdict(verdict: dict[str, object]) -> str:
    status = verdict["status"]
    if status == "changes_requested":
        return "repair"
    if status in {"blocked", "inconclusive"}:
        return "blocked"
    raise ValueError(f"unsupported non-passing verdict: {status}")


def run_task_cycle(task: dict[str, object], controller: AttemptController, kernel: Kernel) -> TaskCycleResult:
    phase = next_phase(kernel.state(), str(task["id"]))
    while True:
        if phase in {"implementation", "repair"}:
            controller.run_write_attempt(task, phase)
            phase = "acceptance"
        elif phase == "acceptance":
            controller.run_acceptance(task)
            phase = "task_review"
        elif phase == "task_review":
            verdict = controller.run_verdict(task, "task_review")
            phase = "verification" if verdict["status"] == "passed" else route_verdict(verdict)
        elif phase == "verification":
            verdict = controller.run_verdict(task, "verification")
            if verdict["status"] == "passed":
                return TaskCycleResult("completed", kernel.state()["worktree_revision"])
            phase = route_verdict(verdict)
        else:
            raise ValueError(f"unsupported task phase: {phase}")
```

`route_verdict` maps only `changes_requested -> repair`; `blocked` and `inconclusive` open typed blockers.

- [ ] **Step 4: Make final review repairable and revision-bound**

Run repository checks, then whole-diff final review. A non-passed final verdict must not append completion. `changes_requested` findings require task IDs, schedule repair for those tasks, and loop back through acceptance, task review, verification, repository checks, and final review.

- [ ] **Step 5: Build completion audit only from current indexed evidence**

Filter by final `worktree_revision` and exact packet digests. Append `completion.recorded`, call `validate_completion`, request the terminal transition, call `validate_completion` again, then return exit-success data.

- [ ] **Step 6: Run execution, quality, and validator checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py && python3 evals/check_operational_run_quality.py && python3 evals/check_recent_run_rubric.py && python3 evals/check_validation_consumer_parity.py`

Expected: all commands exit 0 and the two phase-order cases match their exact call sequences.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/attempt_controller.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py \
  skills/kws-codex-plan-executor/evals/check_execution_runtime.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py \
  skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py
git commit -m "feat(cpe): gate scheduling on current evidence"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py && python3 evals/check_operational_run_quality.py
```

---

### Task 9: Resume And Repair Through Evidence-Backed Events

```yaml
id: T9
title: RecoveryEngine resume and safe compensating repairs
owner_boundary: Integrity reconciliation, retry phase selection, blocker resolution, and provable repair effects
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_repair_runs.py && python3 evals/check_recovery_policy.py && python3 evals/check_state_reconciliation.py
expected: blocked tasks resume at an evidence-derived phase and no-op repairs report applied=false
risks: [Current resume changes only the run lifecycle and generic repair events do not alter attempt or evidence projections.]
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/scripts/reconcile_state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/repair_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_repair_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recovery_policy.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_reconciliation.py`

**Spec Refs:** S1.6.6, S1.12, S1.13, S1.17

**Depends on:** 8

**Interfaces:**
- Produces `ResumeDecision(action, phase, blocker_id, evidence_refs)`.
- Produces `select_resume(state, integrity_report) -> ResumeDecision`.
- `apply_repair` requires `expected_projection_delta` and returns `applied=false` unless replay produces it.

- [ ] **Step 1: Reproduce blocked resume and no-op repair failures**

Create a task blocked after verification and assert:

```python
decision = select_resume(state, validate_integrity(run_dir))
assert decision.phase == "acceptance"
assert resume_run(run_id, worker=fake_worker) == 0
assert load_projected_state(run_dir)["tasks"]["T1"]["status"] == "completed"
```

For a generic stale-attempt repair with no matching active attempt:

```python
result = apply_repair(run_dir, "mark_stale_attempt_interrupted", details={"attempt_id": "missing"})
assert result["applied"] is False
assert result["reason"] == "expected_projection_delta_not_observed"
```

- [ ] **Step 2: Run recovery checks and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_recovery_policy.py`

Expected: FAIL with the existing `task transition from mismatch` reproduction.

- [ ] **Step 3: Distinguish incomplete integrity from drift**

`reconcile` must call `validate_integrity`, classify a healthy running or blocked run as `clean_incomplete`, and reserve `blocking_drift` for invalid hashes, chain, replay, packet, evidence, worktree identity, or policy state.

- [ ] **Step 4: Select retry phases from indexed evidence**

Implement this deterministic matrix:

```python
RESUME_PHASES = {
    "implementation_interrupted": "implementation",
    "acceptance_failed": "repair",
    "task_review_changes_requested": "repair",
    "verification_interrupted": "acceptance",
    "verification_failed": "repair",
}
```

Unresolved operator blockers remain blocked. Missing worktrees open `workspace_precondition`. Invalid manifest, event, packet, or evidence digests reject resume without mutation.

- [ ] **Step 5: Apply repairs only through typed events and verify projection delta**

Snapshot rebuild may replace only `state.json`. Evidence reconnection requires one unique hash-valid artifact. Blocker resolution requires indexed evidence. Stale attempt interruption targets one active attempt. After events append, replay and compare the declared fields before returning `applied=true`.

- [ ] **Step 6: Correct public reconcile syntax and structured failures**

Support exactly the documented command:

```bash
python3 scripts/reconcile_state.py --run-dir RUN_DIR --check
```

Keep `--state` as a compatibility alias for a v3 `state.json` path; reject v2 with `unsupported_schema`.

- [ ] **Step 7: Run recovery, reconciliation, and validator parity**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_repair_runs.py && python3 evals/check_recovery_policy.py && python3 evals/check_state_reconciliation.py && python3 evals/check_validation_consumer_parity.py`

Expected: all commands exit 0; blocked resume completes, no-op repair reports false, and consumers agree.

- [ ] **Step 8: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/scripts/reconcile_state.py \
  skills/kws-codex-plan-executor/scripts/repair_runs.py \
  skills/kws-codex-plan-executor/evals/check_repair_runs.py \
  skills/kws-codex-plan-executor/evals/check_recovery_policy.py \
  skills/kws-codex-plan-executor/evals/check_state_reconciliation.py
git commit -m "feat(cpe): resume through evidence-backed recovery"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_repair_runs.py && python3 evals/check_recovery_policy.py && python3 evals/check_state_reconciliation.py
```

---

### Task 10: Stabilize Public Run, Headless, And Export Contracts

```yaml
id: T10
title: PublicCLI initialization, structured result, and collision-safe export
owner_boundary: Public arguments, initialization cleanup, JSON serialization, exit codes, prompt and handoff output
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_headless_result.py && python3 evals/check_prompt.py --real-plan
expected: public CLI uses canonical validation, headless matches schema, export is one block, and export creates no run artifacts
risks: [Current export embeds full nested-fence content and expected runtime failures can escape as tracebacks.]
```

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/public_result.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_export.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt`
- Modify: `skills/kws-codex-plan-executor/templates/headless-output-schema.json`
- Modify: `skills/kws-codex-plan-executor/references/headless-result-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/prompt-export-checklist.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_headless_result.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_prompt.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_invocation_args.py`

**Spec Refs:** S1.6.7, S1.11.1, S1.12, S1.14.3, S1.17

**Depends on:** 9

**Interfaces:**
- Produces `PublicResult` with `as_dict()` and `exit_code()`; blocked and failed results use the same schema rather than a second failure type.
- Produces `render_export_bundle(template, refs, workspace) -> str` with a content-derived heredoc delimiter and outer fence.
- `execute_run` and `resume_run` call `validate_completion` immediately before returning exit 0.

- [ ] **Step 1: Add public subprocess regressions**

Use a temporary `PATH` whose `codex` executable emits deterministic JSONL and schema-valid result JSON. Invoke `scripts/cpe.py`, not scheduler helpers. Cover success, preflight block, packet tamper, blocked resume, and completion validation failure.

For export, use the real plan containing nested code fences and assert:

```python
before = artifact_paths(codex_home)
result = run_cpe("export", real_plan, real_spec)
after = artifact_paths(codex_home)
assert result.returncode == 0
assert markdown_fence_count(result.stdout) == 2
assert heredoc_delimiter_is_unique(result.stdout)
assert "gpt-5.6-sol" not in exported_prompt_body(result.stdout)
assert before == after
```

- [ ] **Step 2: Run the public checks and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_headless_result.py`

Expected: FAIL because public output does not satisfy the tracked schema.

- [ ] **Step 3: Implement one public result shape**

Create:

```python
@dataclass(frozen=True)
class PublicResult:
    status: str
    run_id: str | None
    state_path: str | None
    summary: str
    changed_files: tuple[str, ...]
    verification: tuple[dict[str, object], ...]
    open_gaps: tuple[str, ...]
    residual_risk: tuple[str, ...]
    context_artifacts: dict[str, str | None]
    next_action: str
    blocker: dict[str, object] | None = None
    failure_decision: dict[str, object] | None = None

    def exit_code(self) -> int:
        return 0 if self.status == "success" else 1 if self.status == "blocked" else 2
```

Allowed failure categories are exactly `preflight`, `environment`, `transient`, `implementation`, `review`, `verification`, `policy_violation`, `state_integrity`, and `operator_review`. Update JSON Schema conditionals so success requires non-null run and state paths, blocked requires `blocker`, and failed requires `failure_decision`.

- [ ] **Step 4: Make initialization publish atomically and clean only owned paths**

Compile first. Stage input and packet bytes in a private sibling directory. Create the isolated worktree. Call `RunKernel.initialize` to fsync and rename the run directory. On failure, remove only a worktree whose branch, path, run ID, and source HEAD match the just-created values; never remove a pre-existing path.

- [ ] **Step 5: Render a collision-safe single export block**

Use deterministic helpers:

```python
def heredoc_delimiter(payload: str) -> str:
    base = "CPE_" + hashlib.sha256(payload.encode()).hexdigest()[:16].upper()
    candidate = base
    counter = 0
    while candidate in payload.splitlines():
        counter += 1
        candidate = f"{base}_{counter}"
    return candidate


def outer_fence(payload: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", payload)), default=2)
    return "`" * max(3, longest + 1)
```

Render only the stable template plus plan/spec/docs paths and hashes. Do not embed full source contents or model IDs in the prompt body.

- [ ] **Step 6: Validate immediately before public success**

After scheduler completion, call `validate_completion(run_dir)`. Convert any failure to `status=failed`, category `state_integrity`, and exit 2. Apply the same rule to already-completed resume.

- [ ] **Step 7: Run public CLI, prompt, headless, and argument checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_headless_result.py && python3 evals/check_prompt.py --real-plan && python3 evals/check_invocation_args.py`

Expected: all commands exit 0; public success matches schema, nested export is one block, and no export artifact appears.

- [ ] **Step 8: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/public_result.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_export.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt \
  skills/kws-codex-plan-executor/templates/headless-output-schema.json \
  skills/kws-codex-plan-executor/references/headless-result-schema.md \
  skills/kws-codex-plan-executor/references/prompt-export-checklist.md \
  skills/kws-codex-plan-executor/evals/check_headless_result.py \
  skills/kws-codex-plan-executor/evals/check_prompt.py \
  skills/kws-codex-plan-executor/evals/check_invocation_args.py
git commit -m "feat(cpe): stabilize public execution contracts"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_headless_result.py && python3 evals/check_prompt.py --real-plan
```

---

### Task 11: Replace Self-Fulfilling And Constant-Success Evals

```yaml
id: T11
title: Public CLI integration harness and maintained eval inventory
owner_boundary: Deterministic fake provider, fixture-oracle separation, maintained check wiring, and anti-stub enforcement
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_eval_harness.py && ./evals/run.sh
expected: every maintained check executes production or public behavior and the complete deterministic harness passes
risks: [Nine wired checks return literal success and fixture runners read expected outcomes to decide their behavior.]
```

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/maintained-checks.json`
- Create: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Create: `skills/kws-codex-plan-executor/evals/public_cli_fixture_runner.py`
- Create: `skills/kws-codex-plan-executor/evals/public-cli-cases.json`
- Create: `skills/kws-codex-plan-executor/evals/public-cli-oracles.json`
- Create: `skills/kws-codex-plan-executor/evals/check_public_cli_integration.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Modify: `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_repair_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recovery_policy.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_fault_injection.py`
- Delete: `skills/kws-codex-plan-executor/evals/static_execution_runner.py`
- Delete: `skills/kws-codex-plan-executor/evals/static_prompt_runner.py`
- Delete: `skills/kws-codex-plan-executor/evals/check_context_summary.py`
- Delete: `skills/kws-codex-plan-executor/evals/check_decisions_register.py`

**Spec Refs:** S1.14.1, S1.14.2, S1.14.3, S1.14.4, S1.17

**Depends on:** 10

**Interfaces:**
- `public_cli_fixture_runner.py` reads only `public-cli-cases.json` and invokes `scripts/cpe.py` through subprocess.
- `check_public_cli_integration.py` reads result artifacts plus `public-cli-oracles.json`; the runner cannot import or read the oracle.
- `maintained-checks.json` records check path, production module or public command, and required mutation assertion.

- [ ] **Step 1: Write anti-stub and oracle-isolation checks**

Parse every maintained Python check with `ast` and require a production import or subprocess invocation of `scripts/cpe.py`. Reject a `main` function whose only observable action is printing a literal payload and returning zero.

Run the fixture runner under a file-open guard and assert the oracle path is denied:

```python
assert runner_inputs == {cases_path}
assert oracles_path not in opened_paths
assert every_case_invoked_public_cpe(trace)
assert every_mutation_case_failed_closed(results)
```

- [ ] **Step 2: Run the meta-check and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_eval_harness.py`

Expected: FAIL and list the nine constant-success checks plus the two self-fulfilling runners.

- [ ] **Step 3: Build the deterministic fake Codex boundary**

`fake_codex.py` must parse the real launcher arguments, read stdin, verify packet path and digest, emit documented Codex JSONL envelopes, and write schema-valid last-message JSON. Its behavior comes from case input passed through a dedicated environment file; expected status and expected changed files live only in the oracle file.

- [ ] **Step 4: Replace the fixture harness with public subprocess runs**

For each case, initialize a temporary Git repo and `CODEX_HOME`, copy `fake_codex.py` to `bin/codex`, prepend `bin` to `PATH`, and invoke public `run`, `resume`, `export`, validate, reconcile, or repair commands. Preserve stdout, stderr, exit code, run ID, state path, and tracked/untracked diffs as checker inputs.

- [ ] **Step 5: Replace or remove every stale check**

Rewrite the nine named checks to call production modules or the public integration runner. Delete the v2-only context-summary and mutable decisions-register checks because those active surfaces no longer exist. Keep the already ported dispatch, validator parity, and verification bundle checks wired.

- [ ] **Step 6: Wire the maintained inventory before fixtures**

`run.sh` must load `maintained-checks.json`, execute each entry through `run_check.py`, fail on missing or duplicate paths, then run the public fixture integration. Do not redirect checker output or read oracle data inside the runner.

- [ ] **Step 7: Run the meta-check and complete deterministic harness**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_eval_harness.py && python3 evals/check_public_cli_integration.py && ./evals/run.sh`

Expected: all commands exit 0; no maintained check is a constant-success stub and all mutation cases fail closed.

- [ ] **Step 8: Commit**

```bash
git add -A -- skills/kws-codex-plan-executor/evals
git commit -m "test(cpe): exercise integrity through public CLI"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_eval_harness.py && ./evals/run.sh
```

---

### Task 12: Align Active Documentation With The Integrity Runtime

```yaml
id: T12
title: Runtime, operator, Korean guide, and command documentation alignment
owner_boundary: Active skill behavior documentation while release remains 3.0.0 pending
acceptance: cd skills/kws-codex-plan-executor && python3 evals/check_docs_contract.py && python3 evals/check_skill_contract.py --skill SKILL.md
expected: active docs describe one packet, validator, resume, repair, command, and release contract with no removed behavior
risks: [Existing docs advertise an invalid reconcile command and readiness unsupported by final evidence.]
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/event-journal.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/mode-contracts.md`
- Modify: `skills/kws-codex-plan-executor/references/drift-reconciliation.md`
- Modify: `skills/kws-codex-plan-executor/references/subagent-run-store.md`
- Modify: `skills/kws-codex-plan-executor/docs/how-it-works.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/mental-model.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/release-process.md`
- Modify: `skills/kws-codex-plan-executor/docs/decisions.md`
- Modify: `skills/kws-codex-plan-executor/docs/human-readable-harness-flow.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/post-merge-verification.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_docs_contract.py`

**Spec Refs:** S1.15, S1.16, S1.17

**Depends on:** 11

**Interfaces:**
- Active docs use the same event names, result fields, role names, repair actions, and public commands as production.
- Version remains `3.0.0` and status remains integrity-closure-pending throughout this task.

- [ ] **Step 1: Make docs contract enumerate active paths and exact commands**

Add checks for:

```python
required_commands = {
    "python3 scripts/cpe.py run",
    "python3 scripts/cpe.py resume",
    "python3 scripts/cpe.py export",
    "python3 scripts/reconcile_state.py --run-dir RUN_DIR --check",
    "python3 scripts/repair_runs.py --run-dir RUN_DIR --dry-run",
}
for command in required_commands:
    assert command in active_docs
assert "deterministic-ready; paid-live-pending" not in version_300_docs
assert "integrity-closure-pending; paid-live-pending" in version_300_docs
```

- [ ] **Step 2: Run docs contract and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_docs_contract.py`

Expected: FAIL on stale release and reconcile text or missing revision/verdict semantics.

- [ ] **Step 3: Update architecture and contract references**

Document the seven components, internal input snapshots, packet index, revision evidence, typed verdicts, active blocker/history split, integrity/completion validator profiles, task/final-review loops, and public JSON exit behavior. Mark historical v3 `attempt.recorded` as read compatibility only.

- [ ] **Step 4: Update operator and Korean guides**

Explain that `blocked` is resumable only when its evidence-derived phase is known, repair can return `applied=false`, review roles are read-only, and paid live remains separate. Use the exact working reconcile and repair commands.

- [ ] **Step 5: Remove active references to deleted harness paths**

Replace `static_execution_runner.py`, `static_prompt_runner.py`, mutable decision-register, and context-summary references with public CLI fixture and immutable event/evidence terminology. Historical experiment documents remain unchanged.

- [ ] **Step 6: Run docs, skill, and help contracts**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_docs_contract.py && python3 evals/check_skill_contract.py --skill SKILL.md && python3 scripts/cpe.py --help >/tmp/cpe-v3-help.txt`

Expected: all commands exit 0 and active docs still report `3.0.0` integrity closure pending.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/references \
  skills/kws-codex-plan-executor/docs \
  skills/kws-codex-plan-executor/evals/check_docs_contract.py
git commit -m "docs(cpe): align v3 integrity runtime contracts"
```

Verification:

```bash
cd skills/kws-codex-plan-executor && python3 evals/check_docs_contract.py && python3 evals/check_skill_contract.py --skill SKILL.md
```

---

### Task 13: Verify L0-L4 And Release 3.0.1

```yaml
id: T13
title: Final implementation evidence, 3.0.1 metadata, and Graphify closeout
owner_boundary: Cost-free release evidence, version transition, baseline, verification log, and graph freshness
acceptance: cd skills/kws-codex-plan-executor && ./evals/run.sh && python3 evals/check_release_contract.py && cd ../.. && bun run check && git diff --check
expected: deterministic gates pass, paid live stays pending, Graphify is fresh, and the tracked worktree is clean
risks: [A release log can pass today with an old failing run because the contract validates strings instead of current evidence fields.]
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/release-process.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/decisions.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `skills/kws-codex-plan-executor/evals/live-migration/release-status.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_release_contract.py`
- Create: `skills/kws-codex-plan-executor/evals/baselines/v3.0.1.json`
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`

**Spec Refs:** S1.14.5, S1.15, S1.17, S1.19

**Depends on:** 12

**Interfaces:**
- Publishes version `3.0.1`, status `deterministic-ready; paid-live-pending`, and `release_ready=false`.
- Verification log records the pre-release implementation commit, commands, exit codes, counts, skipped paid gate, and residual risk.

- [ ] **Step 1: Capture the implementation commit and run L0-L4 before metadata changes**

```bash
IMPLEMENTATION_COMMIT="$(git rev-parse HEAD)"
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
cd ../..
bun run check
git diff --check
```

Expected: every command exits 0; release contract still validates `3.0.0` pending state.

- [ ] **Step 2: Update release contract before changing metadata**

Add a `3.0.1` branch requiring:

```python
checks["version_is_301"] = version == "3.0.1"
checks["deterministic_ready"] = release_status == "deterministic-ready; paid-live-pending"
checks["paid_live_pending"] = live_status.get("paid_live_status") == "pending"
checks["release_ready_false"] = live_status.get("release_ready") is False
checks["implementation_commit_recorded"] = verification.get("implementation_commit") == expected_commit
checks["all_cost_free_commands_passed"] = all(item.get("exit_code") == 0 for item in verification.get("commands", []))
```

- [ ] **Step 3: Set 3.0.1 metadata and write current verification evidence**

Set active metadata exactly:

```yaml
version: "3.0.1"
release_status: "deterministic-ready; paid-live-pending"
```

The latest verification-log entry must include `implementation_commit`, ISO timestamp, each L0-L4 command and exit code, eval passing count, Bun `820`-style dynamic passing count from current output, Graphify pending until Step 7, `paid_live=skipped_not_approved`, and residual risk `paid live migration gate pending`. Do not hard-code a passing count from an older run.

- [ ] **Step 4: Generate and review the 3.0.1 deterministic baseline**

Run: `cd skills/kws-codex-plan-executor && ./evals/run.sh --update-baseline`

Expected: `evals/baselines/v3.0.1.json` is created from current public checks. Inspect it for zero failed maintained checks and no paid execution result.

- [ ] **Step 5: Run the release candidate bundle again**

Run: `cd skills/kws-codex-plan-executor && ./evals/run.sh && python3 evals/check_release_contract.py && python3 evals/check_docs_contract.py && cd ../.. && bun run check && git diff --check`

Expected: all commands exit 0 under `3.0.1`; paid live remains pending and `release_ready=false`.

- [ ] **Step 6: Commit the release evidence**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/docs/release-process.md \
  skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md \
  skills/kws-codex-plan-executor/docs/decisions.md \
  skills/kws-codex-plan-executor/docs/verification-log.md \
  skills/kws-codex-plan-executor/evals/live-migration/release-status.json \
  skills/kws-codex-plan-executor/evals/check_release_contract.py \
  skills/kws-codex-plan-executor/evals/baselines/v3.0.1.json
git commit -m "release(cpe): publish deterministic integrity 3.0.1"
```

- [ ] **Step 7: Refresh Graphify from the release commit**

```bash
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran --output /tmp/cpe-v3-integrity-graphify.json
git add graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git diff --cached --check
git commit -m "docs(graphify): refresh map for CPE 3.0.1"
```

Expected: freshness JSON reports `fresh=true`; only standard Graphify outputs are committed.

- [ ] **Step 8: Verify the graph-only commit and clean tree**

```bash
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran --output /tmp/cpe-v3-integrity-graphify-final.json
git diff --check
git status --short --branch --untracked-files=all
```

Expected: `fresh=true`, `graph_only_commit_after_update=true`, no diff errors, and no tracked or untracked changes.

Verification:

```bash
cd skills/kws-codex-plan-executor && ./evals/run.sh && python3 evals/check_release_contract.py && cd ../.. && bun run check && git diff --check
```

---

## Spec Coverage Matrix

| Design requirement | Implemented by |
| --- | --- |
| Truthful pending and 3.0.1 release state | T1, T13 |
| PlanCompiler and pre-mutation preflight | T2 |
| Internal immutable input snapshots | T2, T3 |
| Manifest-indexed mandatory task packets | T3 |
| RunKernel-only durable writes | T3, T4, T7 |
| Revision and blocker event model | T4 |
| Read-only roles and typed verdicts | T5 |
| Real per-attempt Git delta and scope | T6 |
| Integrity and completion validator profiles | T7 |
| Current-revision task and final-review loop | T8 |
| Evidence-backed resume, reconciliation, and repair | T9 |
| Structured public/headless output and safe export | T10 |
| Public-CLI integration, mutation tests, anti-stub gate | T11 |
| Active documentation alignment | T12 |
| L0-L4 closeout and Graphify freshness | T13 |
| Paid live remains a separately approved gate | T1, T12, T13 |

## Completion Review Checklist

- [ ] Every task's focused verification command passed before its commit.
- [ ] No active worker path can commit, reset, clean, or write durable run state.
- [ ] The approved plan parses through public CPE with 13 tasks and explicit spec mappings.
- [ ] The reproduced false completion, blocked resume, cross-task write, packet mutation, headless mismatch, and no-op repair cases all fail closed.
- [ ] `validate_integrity` and `validate_completion` return consistent codes across scheduler, kernel, CLI, reconciliation, repair, and inspection.
- [ ] No maintained eval is a literal-success stub or reads its oracle to decide behavior.
- [ ] `3.0.1` release metadata is no stronger than current deterministic evidence.
- [ ] Paid live was not executed and `release_ready=false` remains recorded.
- [ ] Graphify reports fresh from the release commit and the final graph-only commit is clean.
- [ ] `code_review.md` was applied to the final diff before merge or PR creation.
