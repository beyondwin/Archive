# CPE v3 Integrity Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the approved CPE v3 integrity-closure design into a trustworthy deterministic executor whose completion, resume, repair, packet, scope, export, and release claims are all backed by current CPE-owned evidence.

**Architecture:** Keep the event-sourced v3 runtime and split its responsibilities into `PlanCompiler`, `PacketStore`, `AttemptController`, `RunKernel`, `CanonicalValidator`, `RecoveryEngine`, and `PublicCLI`. The scheduler will measure Git deltas and revision-bound evidence, while all lifecycle consumers call the same integrity or completion validator. The public eval harness will exercise the CLI with a deterministic fake provider and mutation fixtures instead of deciding outcomes from fixture oracles.

**Tech Stack:** Python 3.11+ standard library, PyYAML already used by parser evals, JSON Schema documents, Bash eval harness, Git worktrees, Graphify, and the existing CPE v3 event journal.

## Global Constraints

- Preserve the event-sourced v3 runtime; do not revive v2, CPE/CME split, legacy Python AgentLens routing, or Waygent integration.
- Do not add model routes, aliases, profiles, or fallbacks; retain Sol/high core and Terra/high read-only scout policy.
- Workers may not run `git commit`, `git reset`, or `git clean`, write run durability files, or touch the source checkout.
- Review, verification, and final review are read-only and cannot issue a `passed` verdict with critical findings or required missing evidence.
- Every non-empty implementation or repair delta increments `worktree_revision`, including an invalid or failed delta; stale evidence cannot satisfy completion.
- Task ownership is determined from CPE-measured Git deltas, not worker-reported `changed_files`.
- Packets are immutable, manifest-indexed, digest-verified, and mandatory inputs for every role.
- `validate_integrity(run_dir)` and `validate_completion(run_dir)` are the only shared validation profiles; scheduler, CLI, reconciliation, repair, inspection, and `validate_state.py` must call them.
- Healthy incomplete runs may pass integrity while failing completion; active blockers and historical blocker entries must remain distinct.
- Export modes create no run/worktree artifacts and emit one collision-free fenced block containing paths and hashes rather than a complete plan body.
- Cost-free L0-L4 gates must pass before changing release metadata to `3.0.1` / `deterministic-ready; paid-live-pending`; paid live remains a separate L5 follow-up.
- Every task ends with the focused test command, `git diff --check`, and an intentional commit.

---

## File Map

The implementation follows existing Python module boundaries and adds only focused modules:

- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py` for typed verdict, blocker, revision, packet, and completion-profile values.
- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/git_delta.py` for CPE-owned worktree basis, actual delta capture, patch storage, and scope checks.
- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py` for plan/spec preflight and immutable input snapshots.
- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/packets.py` for canonical packet bytes, packet index entries, and packet verification.
- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/attempts.py` for role policy, packet delivery, before/after evidence, and worker-result/verdict checks.
- Modify `scripts/cpe.py` to use compiler, packet store, recovery, canonical validation, public result serialization, and safe cleanup.
- Modify `scripts/cpe_runtime/manifest.py` to persist input snapshots, packet index, source/worktree basis, and schema hashes.
- Modify `scripts/cpe_runtime/events.py`, `projector.py`, and `kernel.py` for the new event vocabulary, blocker lifecycle, revision allocation, and transition gates.
- Modify `scripts/cpe_runtime/worker.py` and `model_policy.py` for role-specific read-only boundaries and packet references.
- Modify `scripts/cpe_runtime/scheduler.py` for measured deltas, acceptance/review/verification ordering, repair loops, final-review invalidation, and canonical completion.
- Modify `scripts/cpe_runtime/validation.py`, `reconciliation.py`, `repair.py`, and `inspection.py` so every consumer uses the shared profiles and typed repairs.
- Modify `scripts/cpe_runtime/prompt_export.py`, `templates/fresh-session-prompt.txt`, and `templates/headless-output-schema.json` for public export and headless contracts.
- Modify `scripts/parse_plan.py` and replace `scripts/build_task_packet.py` with compatibility wrappers that route through the new compiler/packet store.
- Create `evals/fake_provider.py`, `evals/check_integrity_contracts.py`, `evals/check_plan_compiler.py`, `evals/check_task_scope_integrity.py`, `evals/check_completion_regressions.py`, `evals/check_public_cli_integration.py`, and `evals/check_release_evidence.py`.
- Replace constant-success logic in `evals/check_cpe_replay.py`, `check_repair_runs.py`, `check_recovery_policy.py`, `check_fault_injection.py`, `check_eval_harness.py`, `check_run_readiness.py`, `check_plan_executability_audit.py`, `check_operational_run_quality.py`, and `check_recent_run_rubric.py` with production-module or public-CLI assertions.
- Add parser and execution fixtures under `evals/parser-fixtures/`, `evals/fixtures/`, `evals/mutations/`, and `evals/golden-cases/`.
- Update `SKILL.md`, `README.md`, `ARCHITECTURE.md`, `HISTORY.md`, all linked state/event/execution/mode/packet/repair/inspection references, release docs, Korean guides, and `docs/verification-log.md`.

---

### Task 1: Establish typed integrity contracts and immutable input snapshots

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Create: `skills/kws-codex-plan-executor/evals/check_integrity_contracts.py`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/integrity-contracts.yaml`

**Interfaces:**
- Consumes: existing task graph, `create_manifest()`, `relative_ref()`, `canonical_hash()`, and `WorkerResult` fields.
- Produces: `Verdict`, `Blocker`, `RevisionEvidence`, `InputSnapshot`, `PacketIndexEntry`, `CompletionProfile`, `canonical_json()`, and `as_dict()` methods consumed by Tasks 2–10.

- [ ] **Step 1: Write the failing contract test**

```python
# evals/check_integrity_contracts.py
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.contracts import Blocker, CompletionProfile, InputSnapshot, RevisionEvidence, Verdict

def main() -> int:
    verdict = Verdict.from_payload(
        {"code": "passed", "findings": [], "missing_evidence": [], "revision": 2, "packet_sha256": "p"},
        role="verification",
    )
    assert verdict.code == "passed"
    assert Verdict.from_payload(
        {"code": "passed", "findings": [{"severity": "critical"}], "missing_evidence": [], "revision": 2, "packet_sha256": "p"},
        role="verification",
    ).code == "inconclusive"
    blocker = Blocker.open("review", "R1", "review changes requested", owner="repair", resume_phase="repair")
    assert blocker.active is True and blocker.history_code == "review"
    evidence = RevisionEvidence("T1", 2, "patch", "packet", "2026-07-10T00:00:00Z", "2026-07-10T00:01:00Z")
    assert evidence.as_dict()["worktree_revision"] == 2
    assert CompletionProfile.INTEGRITY.value == "integrity"
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python3 evals/check_integrity_contracts.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'cpe_runtime.contracts'`.

- [ ] **Step 3: Implement the minimal typed contracts**

```python
# scripts/cpe_runtime/contracts.py
from dataclasses import dataclass
from enum import Enum

class CompletionProfile(str, Enum):
    INTEGRITY = "integrity"
    COMPLETION = "completion"

@dataclass(frozen=True)
class Verdict:
    code: str
    findings: list[dict]
    missing_evidence: list[str]
    revision: int
    packet_sha256: str

    @classmethod
    def from_payload(cls, payload: dict, *, role: str) -> "Verdict":
        code = str(payload.get("code", "inconclusive"))
        if role in {"scout", "implementation", "repair"}:
            raise ValueError("role_cannot_issue_verdict")
        if code == "passed" and (
            any(item.get("severity") == "critical" for item in payload.get("findings", []))
            or payload.get("missing_evidence")
        ):
            code = "inconclusive"
        if code not in {"passed", "changes_requested", "blocked", "inconclusive"}:
            raise ValueError("invalid_verdict")
        return cls(code, list(payload.get("findings", [])), list(payload.get("missing_evidence", [])), int(payload.get("revision", -1)), str(payload.get("packet_sha256", "")))

    def as_dict(self) -> dict:
        return {"code": self.code, "findings": self.findings, "missing_evidence": self.missing_evidence, "worktree_revision": self.revision, "packet_sha256": self.packet_sha256}

@dataclass(frozen=True)
class Blocker:
    category: str
    task_id: str | None
    summary: str
    owner: str
    resume_phase: str
    active: bool = True
    history_code: str = ""

    @classmethod
    def open(cls, category: str, task_id: str | None, summary: str, *, owner: str, resume_phase: str) -> "Blocker":
        return cls(category, task_id, summary, owner, resume_phase, True, category)

@dataclass(frozen=True)
class RevisionEvidence:
    task_id: str
    worktree_revision: int
    worktree_patch_sha256: str
    packet_sha256: str
    started_at: str
    completed_at: str

    def as_dict(self) -> dict:
        return {"task_id": self.task_id, "worktree_revision": self.worktree_revision, "worktree_patch_sha256": self.worktree_patch_sha256, "packet_sha256": self.packet_sha256, "started_at": self.started_at, "completed_at": self.completed_at}

@dataclass(frozen=True)
class InputSnapshot:
    name: str
    source_ref: str
    snapshot_ref: str
    sha256: str

@dataclass(frozen=True)
class PacketIndexEntry:
    task_id: str
    relative_path: str
    media_type: str
    sha256: str
```

Add this helper to `contracts.py` and use it for every digest-bearing payload:

```python
import json

def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
```

Extend `create_manifest()` with `input_snapshots`, `packet_index`, `source_git.worktree_basis`, and `manifest_schema_hash`; `validate_manifest()` must verify every snapshot and indexed packet before accepting a manifest.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python3 evals/check_integrity_contracts.py && python3 -m py_compile scripts/cpe_runtime/contracts.py scripts/cpe_runtime/manifest.py`

Expected: JSON contract assertions pass and Python compilation exits 0.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add scripts/cpe_runtime/contracts.py scripts/cpe_runtime/manifest.py scripts/cpe.py evals/check_integrity_contracts.py evals/fixtures/integrity-contracts.yaml
git diff --cached --check
git commit -m "feat(cpe): add typed integrity contracts"
```

### Task 2: Compile current writing-plans tasks and make packets canonical

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/packets.py`
- Modify: `skills/kws-codex-plan-executor/scripts/parse_plan.py`
- Modify: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Create: `skills/kws-codex-plan-executor/evals/check_plan_compiler.py`
- Create: `skills/kws-codex-plan-executor/evals/parser-fixtures/18-cpe-v3-integrity-plan.yaml`
- Modify: `skills/kws-codex-plan-executor/evals/check_task_packet.py`

**Interfaces:**
- Consumes: `parse_plan()`, `build_spec_manifest()`, `InputSnapshot`, and the approved design/spec at `docs/superpowers/specs/2026-07-10-cpe-v3-integrity-closure-design.md`.
- Produces: `CompiledPlan`, `compile_plan(plan, spec, workspace, mode)`, `PacketStore.create()`, `PacketStore.load_verified()`, and manifest packet entries.

- [ ] **Step 1: Add the failing golden parser and packet tests**

```python
# evals/check_plan_compiler.py
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.compiler import compile_plan
from cpe_runtime.packets import PacketStore

root = Path(__file__).resolve().parents[2]
fixture = yaml.safe_load((root / "evals/parser-fixtures/18-cpe-v3-integrity-plan.yaml").read_text(encoding="utf-8"))
with TemporaryDirectory() as raw:
    workspace = Path(raw); plan = workspace / "plan.md"; spec = workspace / "spec.md"
    plan.write_text(fixture["plan"], encoding="utf-8"); spec.write_text(fixture["spec"], encoding="utf-8")
    compiled = compile_plan(plan, spec, workspace, "headless")
    assert [task.id for task in compiled.tasks] == ["task_1"]
    assert all(task.file_claims and task.acceptance_command and task.spec_refs for task in compiled.tasks)
    packet_dir = workspace / "artifacts" / "task-packets"
    store = PacketStore(packet_dir)
    entries = [store.create(task, compiled.input_snapshots, compiled.spec_sections) for task in compiled.tasks]
    assert entries and all(store.load_verified(entry).task_id == entry.task_id for entry in entries)
```

- [ ] **Step 2: Run the golden test to verify it fails**

Run: `python3 evals/check_plan_compiler.py`

Expected: FAIL because `cpe_runtime.compiler` and `cpe_runtime.packets` do not exist and the current approved v3 plan is not accepted by the public parser.

- [ ] **Step 3: Implement compiler and packet store**

```python
# scripts/cpe_runtime/compiler.py
from dataclasses import dataclass
from pathlib import Path
from .contracts import InputSnapshot, canonical_json
from .manifest import canonical_hash, sha256_file
from parse_plan import parse_plan
from build_spec_manifest import build_manifest

@dataclass(frozen=True)
class CompiledTask:
    id: str
    title: str
    dependencies: tuple[str, ...]
    file_claims: tuple[str, ...]
    spec_refs: tuple[str, ...]
    acceptance_command: str
    prompt: str

@dataclass(frozen=True)
class CompiledPlan:
    tasks: tuple[CompiledTask, ...]
    input_snapshots: tuple[InputSnapshot, ...]
    spec_sections: dict

def compile_plan(plan: Path, spec: Path | None, workspace: Path, mode: str) -> CompiledPlan:
    parsed = parse_plan(plan, workspace, mode)
    manifest = build_manifest(spec) if spec else {"sections": {}}
    available = set(manifest.get("sections", {}))
    tasks = []
    for item in parsed["tasks"]:
        refs = tuple(item.get("spec_refs") or ())
        if spec and not refs: raise ValueError(f"missing_explicit_spec_mapping: {item['id']}")
        if set(refs) - available: raise ValueError(f"unknown_spec_refs: {item['id']}")
        command = str(item.get("acceptance_command") or "").strip()
        if not command: raise ValueError(f"acceptance_command_missing: {item['id']}")
        tasks.append(CompiledTask(str(item["id"]), str(item.get("title", item["id"])), tuple(item.get("depends_on") or ()), tuple(item.get("files") or ()), refs, command, str(item.get("body") or item["id"])))
    snapshots = [InputSnapshot("plan", str(plan), "artifacts/inputs/plan.md", sha256_file(plan))]
    if spec: snapshots.append(InputSnapshot("spec", str(spec), "artifacts/inputs/spec.md", sha256_file(spec)))
    return CompiledPlan(tuple(tasks), tuple(snapshots), manifest.get("sections", {}))
```

Implement `materialize_input_snapshots(run_dir, compiled, plan, spec)` beside `compile_plan()`; copy the exact plan/spec bytes to each `InputSnapshot.snapshot_ref` with exclusive create, fsync the files and directory, and verify the copied SHA-256 before returning. `cpe.py` must call this before publishing the manifest and pass only snapshot refs to packet construction. Implement `PacketStore.create()` by canonicalizing the exact task, selected spec sections, execution contract, required methods, role policy, evidence requirements, and source hashes; write with exclusive create under `artifacts/task-packets/`; return `PacketIndexEntry`. `load_verified()` must reject missing, unindexed, changed, or duplicate packet IDs. Make `build_task_packet.py` call `PacketStore` or emit an explicit `legacy_packet_builder_removed` error; no heuristic fallback may be used by `cpe.py`.

Extend `parse_plan.py` to accept both the current writing-plans shape (a `### Task N` heading followed by a plain fenced `yaml` task body) and explicit `````yaml waygent-task````` blocks, while preserving fence/comment hiding for unrelated examples. Parse `files`, `dependencies`, `spec_refs`, and `acceptance` from the YAML body, require `spec_refs` when a spec is present, and include the task body's exact source line range in the compiled task. Add the approved current plan shape as parser fixture 18 with expected IDs, files, dependencies, spec refs, and acceptance commands.

Create fixture 18 with this exact input and oracle:

````yaml
plan: |
  # Integrity fixture

  ### Task 1: Write target

  ```yaml
  id: T1
  title: Write target
  dependencies: []
  files:
    - path: target.txt
      mode: owned
  spec_refs: [S1]
  acceptance:
    - command: test -f target.txt
      expected: passed
  ```
spec: |
  # S1 Integrity target

  The task must create target.txt.
expected:
  files: [target.txt]
  depends_on: {task_1: []}
  spec_refs: {task_1: [S1]}
  acceptance_commands: {task_1: test -f target.txt}
````

- [ ] **Step 4: Run parser, packet, and compiler checks**

Run: `python3 evals/check_plan_compiler.py && python3 evals/check_task_packet.py && python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/18-cpe-v3-integrity-plan.yaml`

Expected: all commands exit 0; the golden plan compiles without `no Files block` and every packet digest verifies.

- [ ] **Step 5: Commit the compiler and packet boundary**

```bash
git add scripts/cpe_runtime/compiler.py scripts/cpe_runtime/packets.py scripts/parse_plan.py scripts/build_task_packet.py scripts/cpe.py evals/check_plan_compiler.py evals/check_task_packet.py evals/parser-fixtures/18-cpe-v3-integrity-plan.yaml
git diff --cached --check
git commit -m "feat(cpe): compile plans and verify immutable packets"
```

### Task 3: Capture real Git deltas and enforce role boundaries

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/git_delta.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/attempts.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/worker.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/model_policy.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py`
- Create: `skills/kws-codex-plan-executor/evals/check_task_scope_integrity.py`
- Create: `skills/kws-codex-plan-executor/evals/mutations/cross-task-write.json`

**Interfaces:**
- Consumes: `CompiledTask`, verified packet refs, `WorkerRequest`, current worktree HEAD/status, and `RevisionEvidence`.
- Produces: `WorktreeBasis`, `GitDelta`, `capture_basis()`, `capture_delta()`, `assert_scope()`, `AttemptController.run()`, and monotonic `worktree_revision` events.

- [ ] **Step 1: Write failing scope and role tests**

```python
# evals/check_task_scope_integrity.py
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.git_delta import capture_basis, capture_delta, assert_scope

with TemporaryDirectory() as raw:
    root = Path(raw); subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=root, check=True)
    (root / "a.txt").write_text("a\n"); (root / "b.txt").write_text("b\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True); subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    basis = capture_basis(root, revision=0)
    (root / "a.txt").write_text("changed\n"); (root / "b.txt").write_text("cross-task\n")
    delta = capture_delta(root, basis, revision=1)
    assert set(delta.changed_files) == {"a.txt", "b.txt"}
    assert assert_scope(delta, ("a.txt",), ()) == ["diff_scope_violation:b.txt"]
```

- [ ] **Step 2: Run the scope test to verify it fails**

Run: `python3 evals/check_task_scope_integrity.py`

Expected: FAIL because actual per-attempt Git delta capture does not exist.

- [ ] **Step 3: Implement measured delta capture and attempt controller**

```python
# scripts/cpe_runtime/git_delta.py
from dataclasses import dataclass
import hashlib, subprocess
from pathlib import Path

@dataclass(frozen=True)
class WorktreeBasis:
    head: str
    status: tuple[str, ...]
    patch_sha256: str
    revision: int

@dataclass(frozen=True)
class GitDelta:
    before: WorktreeBasis
    after_head: str
    changed_files: tuple[str, ...]
    patch_sha256: str
    patch_text: str
    worktree_revision: int

def _run(root: Path, *argv: str) -> str:
    result = subprocess.run(["git", *argv], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return result.stdout

def _status(root: Path) -> tuple[str, ...]:
    return tuple(line for line in _run(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines() if line)

def capture_basis(root: Path, *, revision: int) -> WorktreeBasis:
    status = _status(root)
    patch = _run(root, "diff", "--binary", "--no-ext-diff", "HEAD")
    return WorktreeBasis(_run(root, "rev-parse", "HEAD").strip(), status, hashlib.sha256(patch.encode()).hexdigest(), revision)

def capture_delta(root: Path, before: WorktreeBasis, *, revision: int) -> GitDelta:
    status = _status(root)
    tracked_patch = _run(root, "diff", "--binary", "--no-ext-diff", "HEAD")
    untracked = [line[3:] for line in status if line[:2] == "??" and len(line) >= 4]
    untracked_parts = []
    for path in untracked:
        result = subprocess.run(["git", "diff", "--binary", "--no-ext-diff", "--no-index", "/dev/null", path], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        untracked_parts.append(result.stdout)
    patch = tracked_patch + "".join(untracked_parts)
    files = tuple(sorted(line[3:].split(" -> ")[-1] for line in status if len(line) >= 4))
    return GitDelta(before, _run(root, "rev-parse", "HEAD").strip(), files, hashlib.sha256(patch.encode()).hexdigest(), patch, revision)

def assert_scope(delta: GitDelta, allowed: tuple[str, ...], forbidden: tuple[str, ...]) -> list[str]:
    def matches(path: str, pattern: str) -> bool: return path == pattern or path.startswith(pattern.rstrip("/") + "/")
    errors = [f"diff_scope_violation:{path}" for path in delta.changed_files if not any(matches(path, p) for p in allowed)]
    errors += [f"forbidden_write:{path}" for path in delta.changed_files if any(matches(path, p) for p in forbidden)]
    return sorted(errors)
```

`AttemptController` must record basis before every implementation/repair, invoke `WorkerRequest` with the verified packet reference and role-specific sandbox, capture the delta afterward, store the patch under `artifacts/patches/`, increment revision for every non-empty delta, and reject worker-reported `changed_files` as an authority. Add post-process checks that a worker attempted `git commit`, `git reset`, `git clean`, or durable-run writes; classify the attempt as `policy_violation` and block it. Review, verification, and final-review requests must carry `read_only=True`, while implementation/repair requests must carry `verdict_capable=False`.

- [ ] **Step 4: Run the measured-delta tests**

Run: `python3 evals/check_task_scope_integrity.py && python3 -m py_compile scripts/cpe_runtime/git_delta.py scripts/cpe_runtime/attempts.py scripts/cpe_runtime/worker.py`

Expected: cross-task files are reported from actual status, patch digests are stable, and role policy rejects verdicts from write roles.

- [ ] **Step 5: Commit the attempt boundary**

```bash
git add scripts/cpe_runtime/git_delta.py scripts/cpe_runtime/attempts.py scripts/cpe_runtime/worker.py scripts/cpe_runtime/model_policy.py scripts/cpe_runtime/scheduler.py evals/check_task_scope_integrity.py evals/mutations/cross-task-write.json
git diff --cached --check
git commit -m "feat(cpe): enforce measured task scope and role policy"
```

### Task 4: Extend the event kernel and projection for revisions and blocker lifecycle

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/events.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_event_kernel.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
- Create: `skills/kws-codex-plan-executor/evals/mutations/event-chain.json`

**Interfaces:**
- Consumes: `Transition`, `Blocker`, `Verdict`, `RevisionEvidence`, and `GitDelta` from Tasks 1 and 3.
- Produces: event types `attempt.started`, `attempt.completed`, `verdict.recorded`, `worktree.revision_recorded`, `blocker.opened`, `blocker.updated`, `blocker.resolved`, `task.retry_scheduled`, and `context.updated`; projected `active_blockers`, `blocker_history`, `worktree_revision`, `attempts`, `verdicts`, `repairs`, and `completion_audit`.

- [ ] **Step 1: Add failing replay assertions**

```python
# Extend evals/check_event_kernel.py
assert "worktree.revision_recorded" in EVENT_TYPES
assert "blocker.resolved" in EVENT_TYPES
state = project(manifest, events)
assert state["worktree_revision"] == 2
assert state["active_blockers"] == []
assert state["blocker_history"][0]["category"] == "verification"
```

- [ ] **Step 2: Run the replay tests to verify they fail**

Run: `python3 evals/check_event_kernel.py && python3 evals/check_cpe_replay.py`

Expected: FAIL because the current event vocabulary and projection only expose one undifferentiated `blockers` list and no revision/verdict events.

- [ ] **Step 3: Implement typed event validation and projection**

Add the event names to `EVENT_TYPES`. In `projector.initial_state()` add:

```python
"worktree_revision": 0,
"active_blockers": [],
"blocker_history": [],
"verdicts": [],
"completion_audit": None,
```

In `apply_event()` implement these exact transitions:

```python
if typ == "worktree.revision_recorded":
    revision = int(payload["worktree_revision"])
    if revision != state["worktree_revision"] + 1:
        raise ValueError("revision_not_monotonic")
    state["worktree_revision"] = revision
elif typ == "verdict.recorded":
    state["verdicts"].append(payload)
elif typ == "blocker.opened":
    blocker = dict(payload); blocker["active"] = True
    state["active_blockers"].append(blocker); state["blocker_history"].append(blocker)
elif typ == "blocker.updated":
    state["blocker_history"].append(dict(payload))
elif typ == "blocker.resolved":
    blocker_id = payload["blocker_id"]
    state["active_blockers"] = [item for item in state["active_blockers"] if item.get("blocker_id") != blocker_id]
    state["blocker_history"].append(dict(payload))
```

In `Kernel._validate_transition()`, reject revision gaps, verdicts without an indexed packet/current revision, `passed` verdicts with critical findings/missing evidence, task completion with any active blocker, and completion without canonical completion validation. Keep hash-chain and atomic snapshot behavior unchanged.

- [ ] **Step 4: Run event, replay, and schema checks**

Run: `python3 evals/check_event_kernel.py && python3 evals/check_cpe_replay.py && python3 evals/check_state_schema.py`

Expected: all replayed projections are deterministic, revision gaps fail closed, and resolved blockers are absent from `active_blockers` but present in `blocker_history`.

- [ ] **Step 5: Commit the kernel state model**

```bash
git add scripts/cpe_runtime/events.py scripts/cpe_runtime/projector.py scripts/cpe_runtime/kernel.py scripts/cpe_runtime/contracts.py evals/check_event_kernel.py evals/check_cpe_replay.py evals/mutations/event-chain.json
git diff --cached --check
git commit -m "feat(cpe): add revision and blocker lifecycle events"
```

### Task 5: Rebuild scheduler execution and fail-closed completion

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Create: `skills/kws-codex-plan-executor/evals/check_completion_regressions.py`
- Create: `skills/kws-codex-plan-executor/evals/mutations/negative-review.json`
- Create: `skills/kws-codex-plan-executor/evals/mutations/final-review-write.json`

**Interfaces:**
- Consumes: `AttemptController`, verified packets, revision events, and `validate_completion()` from earlier tasks.
- Produces: task loop ordering `acceptance → task_review → verification`, bounded repair re-entry, final-review invalidation, and public completion only after canonical validation.

- [ ] **Step 1: Write the two false-completion regression tests**

```python
# evals/check_completion_regressions.py
from pathlib import Path
import json, subprocess, sys, tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from cpe_runtime.kernel import Kernel, Transition
from cpe_runtime.manifest import create_manifest, write_manifest
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.worker import WorkerResult
from cpe import _create_worktree, _task_packets

TASKS = [{"id": "T1", "title": "target", "dependencies": [], "file_claims": ["target.txt"], "spec_refs": [], "acceptance_command": "test -f target.txt", "prompt": "implement target"}]

class ScriptedWorker:
    def __init__(self, case: str): self.case = case
    def run(self, request):
        if request.attempt_kind == "implementation":
            (request.worktree / "target.txt").write_text("good\n")
        if self.case == "final-review-write" and request.attempt_kind == "final_review":
            (request.worktree / "target.txt").write_text("bad\n")
        critical = self.case == "critical-review" and request.attempt_kind in {"task_review", "final_review"}
        verdict = {"code": "inconclusive" if critical else "passed", "findings": [{"severity": "critical"}] if critical else [], "missing_evidence": ["verification"] if critical else [], "revision": 1, "packet_sha256": ""}
        payload = {"status": "completed", "summary": "scripted", "changed_files": [], "findings": verdict["findings"], "evidence_refs": [], "missing_evidence": verdict["missing_evidence"], "verification": [], "verdict": verdict}
        return WorkerResult("completed", payload, {"verified": True, "actual_model": "gpt-5.6-sol", "actual_reasoning": "high"}, {}, 1, "scripted")

def run_case(case: str) -> dict:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); run_dir = root / "run"; worktree = root / "worktree"; pricing = root / "pricing.json"; pricing.write_text("{}\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True); (root / "target.txt").write_text("base\n"); subprocess.run(["git", "add", "."], cwd=root, check=True); subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        _create_worktree(root, worktree, f"regression-{case}"); run_dir.mkdir()
        manifest = create_manifest(f"regression-{case}", "headless", root, worktree, root / "target.txt", None, TASKS, pricing, source_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip())
        write_manifest(run_dir / "run_manifest.json", manifest); _task_packets(run_dir, TASKS, None, None)
        kernel = Kernel(run_dir); kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        result = run_tasks(TASKS, ScriptedWorker(case), kernel)
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root, check=True)
        return result

negative = run_case("critical-review")
assert negative["status"] != "completed"
final_write = run_case("final-review-write")
assert final_write["status"] != "completed"
```

- [ ] **Step 2: Run the regressions to verify they fail**

Run: `python3 evals/check_completion_regressions.py`

Expected: FAIL because the current scheduler trusts completed worker status and does not rerun canonical completion after final-review changes.

- [ ] **Step 3: Implement the fail-closed task loop**

Replace the current scheduler branch with this control contract:

```python
delta = controller.run_write_attempt(task, "implementation")
if delta.errors:
    return block(task, "implementation", delta.errors)
acceptance_ok, acceptance = run_acceptance(task, worktree, kernel, revision=delta.worktree_revision)
if not acceptance_ok:
    return schedule_repair(task, "verification", acceptance)
review = controller.run_read_only(task, "task_review", revision=delta.worktree_revision)
if review.verdict.code != "passed":
    return schedule_repair(task, "review", review.verdict.as_dict())
verification = controller.run_read_only(task, "verification", revision=delta.worktree_revision)
if verification.verdict.code != "passed":
    return schedule_repair(task, "verification", verification.verdict.as_dict())
kernel.transition(Transition("task.status_changed", {"from": "verifying", "to": "completed"}, task_id=task.id))
```

After every repair delta, increment the revision and rerun acceptance, task review, and verification. Final review must be read-only; a non-passed verdict opens a repair phase, invalidates all prior revision-bound acceptance/verdict/repository evidence, and loops back to repository commands. Before `completion.recorded`, call `validate_completion(run_dir)` and reject zero exit unless it passes. The validator must inspect verdict codes, current revision, packet digest, active blockers, actual final diff, final-review evidence, and indexed audit evidence instead of only artifact presence.

- [ ] **Step 4: Run public completion regressions and existing runtime checks**

Run: `python3 evals/check_completion_regressions.py && python3 evals/check_execution_runtime.py && python3 evals/check_validation_consumer_parity.py`

Expected: negative review, missing verification, final-review writes, and stale revisions return blocked/failed structured output; no false completed run is emitted.

- [ ] **Step 5: Commit the scheduler and completion gate**

```bash
git add scripts/cpe_runtime/scheduler.py scripts/cpe_runtime/validation.py scripts/cpe.py evals/check_completion_regressions.py evals/mutations/negative-review.json evals/mutations/final-review-write.json
git diff --cached --check
git commit -m "fix(cpe): make completion evidence fail closed"
```

### Task 6: Implement deterministic resume, blocker resolution, and safe repair

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/recovery.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/inspection.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_repair_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recovery_policy.py`
- Create: `skills/kws-codex-plan-executor/evals/mutations/blocked-resume.json`

**Interfaces:**
- Consumes: active/history blockers, `task.retry_scheduled`, revision evidence, `validate_integrity()`, and `validate_completion()`.
- Produces: `RecoveryEngine.resume_action()`, `RepairPlan.expected_projection_delta`, typed categories, and safe repair results with `applied` determined by replayed state.

- [ ] **Step 1: Add failing blocked-resume and no-op-repair tests**

```python
# Extend evals/check_recovery_policy.py
action = RecoveryEngine().resume_action({"lifecycle": "blocked", "tasks": {"T1": {"status": "blocked"}}, "active_blockers": [{"category": "verification", "resume_phase": "repair"}]})
assert action.phase == "repair"

# Extend evals/check_repair_runs.py
result = apply_repair(run_dir, "mark_stale_attempt_interrupted", details={"attempt_id": "T1.implementation.1"})
assert result["applied"] is False
assert "projection_delta_missing" in result["errors"]
```

- [ ] **Step 2: Run recovery tests to verify they fail**

Run: `python3 evals/check_recovery_policy.py && python3 evals/check_repair_runs.py`

Expected: FAIL with the current `blocked → ready` task mismatch and unconditional `repair.applied` behavior.

- [ ] **Step 3: Implement phase-aware recovery**

```python
# scripts/cpe_runtime/recovery.py
from dataclasses import dataclass

@dataclass(frozen=True)
class ResumeAction:
    phase: str
    reason: str
    blocker_id: str | None

class RecoveryEngine:
    def resume_action(self, state: dict) -> ResumeAction:
        blockers = state.get("active_blockers", [])
        if any(item.get("category") == "operator_review" for item in blockers):
            return ResumeAction("blocked", "operator_action_required", None)
        if state.get("last_interrupted_role") == "implementation":
            return ResumeAction("implementation", "interrupted_attempt", None)
        if state.get("last_failed_phase") in {"acceptance", "review", "verification", "final_review"}:
            return ResumeAction("repair", "failed_or_changed_evidence", None)
        return ResumeAction("verification", "recheck_current_revision", None)
```

`resume_run()` must validate manifest/event/packet/evidence digests first, append `blocker.resolved` plus `task.retry_scheduled` with an explicit phase, transition the task from its actual current state, and invoke only that phase. It must never force a blocked task to `ready` without a retry event. `repair.py` must allow snapshot/report rebuild, provable stale-attempt interruption, unique hash-valid evidence reconnection, blocker resolution, and bounded retry scheduling only; every action declares `expected_projection_delta`, compares replayed `before`/`after`, and returns `applied=false` while keeping the blocker active if the delta is absent. Reconciliation must classify healthy incomplete runs as integrity-clean but completion-ineligible, and any event/manifest/packet/evidence mutation as blocking drift.

- [ ] **Step 4: Run resume, repair, and reconciliation checks**

Run: `python3 evals/check_recovery_policy.py && python3 evals/check_repair_runs.py && python3 evals/check_state_reconciliation.py && python3 evals/check_inspect_runs.py`

Expected: blocked tasks resume at explicit phases, resolved blockers remain in history, no-op repairs stay unapplied, v2 state stays immutable, and scheduler/validator/reconciler classifications agree.

- [ ] **Step 5: Commit recovery behavior**

```bash
git add scripts/cpe_runtime/recovery.py scripts/cpe.py scripts/cpe_runtime/projector.py scripts/cpe_runtime/reconciliation.py scripts/cpe_runtime/repair.py scripts/cpe_runtime/inspection.py evals/check_repair_runs.py evals/check_recovery_policy.py evals/mutations/blocked-resume.json
git diff --cached --check
git commit -m "fix(cpe): add phase-aware resume and safe repair"
```

### Task 7: Make public export and headless output contractual

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_export.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/public_output.py`
- Modify: `skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt`
- Modify: `skills/kws-codex-plan-executor/templates/headless-output-schema.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_prompt.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_headless_result.py`
- Create: `skills/kws-codex-plan-executor/evals/check_public_cli_integration.py`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/export-nested-fences.yaml`

**Interfaces:**
- Consumes: compiled input snapshots, verified packet index, `ValidationReport`, and `headless-output-schema.json`.
- Produces: `render_export_bundle(prompt, workspace, refs)`, `build_public_result()`, stable structured failures, and one collision-free export block.

- [ ] **Step 1: Add failing export/headless tests**

```python
# evals/check_public_cli_integration.py
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.prompt_export import render_export_bundle

payload = "nested ```\nCPE_PROMPT\n```text"
out = render_export_bundle(payload, Path("/tmp/workspace"), {"plan": "artifacts/inputs/plan.md", "plan_sha256": "abc"})
lines = out.splitlines()
fence = lines[0][:-4]
assert lines[-1] == fence and len(fence) >= 4
assert "nested ```" in out
assert lines[-2] != "CPE_PROMPT"
assert "artifacts/inputs/plan.md" in out
```

- [ ] **Step 2: Run export tests to verify they fail**

Run: `python3 evals/check_public_cli_integration.py && python3 evals/check_headless_result.py`

Expected: FAIL because export currently embeds the entire plan, uses a fixed outer fence and `CPE_PROMPT` delimiter, and the public run path has no schema-backed result builder.

- [ ] **Step 3: Implement collision-free export and public result serialization**

```python
# scripts/cpe_runtime/prompt_export.py
import re, shlex
from .model_policy import CORE_ROUTE, launcher_argv

def _delimiter(prompt: str) -> str:
    base = "CPE_PROMPT"
    candidate = base
    index = 1
    while re.search(rf"(?m)^{re.escape(candidate)}$", prompt):
        candidate = f"{base}_{index}"; index += 1
    return candidate

def _fence(prompt: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", prompt)), default=0)
    return "`" * max(3, longest + 1)

def render_export_bundle(prompt: str, workspace: Path, refs: dict[str, str]) -> str:
    delimiter = _delimiter(prompt)
    fence = _fence(prompt)
    command = shlex.join(launcher_argv(CORE_ROUTE, workspace, sandbox="workspace-write"))
    body = f"{command} <<'{delimiter}'\n{prompt.rstrip()}\n{delimiter}\n"
    return f"{fence}text\n{body}{fence}\n"
```

Change `export_plan()` to compile and snapshot only for validation in memory, then include plan/spec/doc relative paths and hashes in the handoff body. Do not create a run directory, worktree, packet, or state file. Add `public_output.py` with `build_public_result(status, run_id, state_path, summary, changed_files, verification, open_gaps, residual_risk, context_artifacts, next_action, blocker=None, failure_decision=None)` and validate it against the tracked JSON schema before printing. Expected runtime failures must return JSON and a nonzero exit code without a traceback.

- [ ] **Step 4: Run export, schema, and CLI checks**

Run: `python3 evals/check_public_cli_integration.py && python3 evals/check_headless_result.py && python3 evals/check_prompt.py --fixture evals/fixtures/export-nested-fences.yaml --output /tmp/cpe-export-output.md`

Expected: exactly one outer fenced block is emitted, inner fences and delimiter collisions survive, exported output contains only paths/hashes, and every headless result validates against the JSON schema.

- [ ] **Step 5: Commit public contracts**

```bash
git add scripts/cpe.py scripts/cpe_runtime/prompt_export.py scripts/cpe_runtime/public_output.py templates/fresh-session-prompt.txt templates/headless-output-schema.json evals/check_prompt.py evals/check_headless_result.py evals/check_public_cli_integration.py evals/fixtures/export-nested-fences.yaml
git diff --cached --check
git commit -m "fix(cpe): make export and headless output contractual"
```

### Task 8: Unify integrity/completion validation across every consumer

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/inspection.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/reconcile_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_validation_consumer_parity.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_verification_bundle.py`
- Create: `skills/kws-codex-plan-executor/evals/check_release_evidence.py`

**Interfaces:**
- Consumes: event projection, packet index, revision evidence, Git delta records, typed verdicts, and public output schema.
- Produces: `validate_integrity(run_dir)`, `validate_completion(run_dir)`, stable `ValidationReport.profile`, and consumer parity assertions.

- [ ] **Step 1: Add failing profile and parity tests**

```python
# Extend evals/check_validation_consumer_parity.py
integrity = validate_integrity(run_dir)
completion = validate_completion(run_dir)
assert integrity.profile == "integrity"
assert completion.profile == "completion"
assert integrity.passed is True
assert completion.passed is False
assert completion.errors == ["completion_ineligible_incomplete_tasks"]
```

- [ ] **Step 2: Run parity tests to verify they fail**

Run: `python3 evals/check_validation_consumer_parity.py && python3 evals/check_run_readiness.py && python3 evals/check_verification_bundle.py`

Expected: FAIL because only `validate_run()` exists and the current consumers duplicate incomplete completion rules.

- [ ] **Step 3: Implement the two shared profiles**

Refactor `ValidationReport` to include `profile`, and implement:

```python
def validate_integrity(run_dir: Path) -> ValidationReport:
    checks = _run_schema_manifest_event_snapshot_artifact_packet_scope_checks(run_dir)
    return _report("integrity", checks)

def validate_completion(run_dir: Path) -> ValidationReport:
    report = validate_integrity(run_dir)
    checks = dict(report.checks or {})
    checks["completion"] = _completion_errors(run_dir, checks)
    errors = _dedupe(code for values in checks.values() for code in values)
    return ValidationReport("completion", not errors, errors, report.warnings, checks)

def validate_run(run_dir: Path) -> ValidationReport:
    return validate_completion(run_dir)
```

`validate_integrity()` must check supported schema, manifest/input/packet hashes, event chain, replay parity, snapshot, evidence refs, worktree identity, every recorded revision delta, task-specific scope, attempt roles, and packet delivery for any lifecycle. `validate_completion()` additionally checks all tasks completed, every passed acceptance/review/verification/final-review artifact is bound to the current revision and packet digest, no active blockers, repository commands on the final revision, complete audit, and canonical output. `reconcile_state.py`, `repair_runs.py`, `inspect_runs.py`, and `validate_state.py` must select the profile explicitly and serialize the same error codes.

- [ ] **Step 4: Run all consumer parity checks**

Run: `python3 evals/check_validation_consumer_parity.py && python3 evals/check_run_readiness.py && python3 evals/check_verification_bundle.py && python3 evals/check_release_evidence.py`

Expected: healthy incomplete runs pass integrity but not completion; all consumers report the same error list; stale evidence, packet tampering, scope violations, and final-review writes fail completion.

- [ ] **Step 5: Commit canonical validation**

```bash
git add scripts/cpe_runtime/validation.py scripts/cpe_runtime/reconciliation.py scripts/cpe_runtime/repair.py scripts/cpe_runtime/inspection.py scripts/validate_state.py scripts/reconcile_state.py evals/check_validation_consumer_parity.py evals/check_run_readiness.py evals/check_verification_bundle.py evals/check_release_evidence.py
git diff --cached --check
git commit -m "fix(cpe): unify integrity and completion validation"
```

### Task 9: Replace self-fulfilling evals with public-CLI and mutation coverage

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/fake_provider.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Modify: `skills/kws-codex-plan-executor/evals/static_execution_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/static_prompt_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_repair_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recovery_policy.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_fault_injection.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`
- Create: `skills/kws-codex-plan-executor/evals/mutations/packet-tamper.json`
- Create: `skills/kws-codex-plan-executor/evals/mutations/evidence-tamper.json`
- Create: `skills/kws-codex-plan-executor/evals/mutations/stale-revision.json`

**Interfaces:**
- Consumes: public `cpe.py run/resume/export`, deterministic fake-provider boundary, separate fixture inputs, and canonical validators.
- Produces: real behavior checks for every wired eval and a meta-check that fails if a checker returns a constant success payload without invoking a production path.

- [ ] **Step 1: Add failing meta-eval and public integration assertions**

```python
# evals/check_eval_harness.py
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
for name in ("check_fault_injection.py", "check_repair_runs.py", "check_cpe_replay.py"):
    tree = ast.parse((ROOT / "evals" / name).read_text(encoding="utf-8"))
    source = (ROOT / "evals" / name).read_text(encoding="utf-8")
    assert "print(json.dumps({\"passed\": True" not in source)
    assert any(isinstance(node, (ast.Call, ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
```

- [ ] **Step 2: Run the meta-eval to verify it fails**

Run: `python3 evals/check_eval_harness.py`

Expected: FAIL because the current wired checkers contain literal `passed: true` payloads and static runners read fixture expectations to decide outcomes.

- [ ] **Step 3: Implement fake-provider boundary and real fixture assertions**

Implement `fake_provider.py` as a provider callable that receives `WorkerRequest` and returns a result based only on explicit scenario input passed by the test, never on expected output fields:

```python
def provider_for(case: str):
    def provider(request, argv):
        if case == "cross-task-write":
            (request.worktree / "other-task.txt").write_text("unauthorized\n")
        elif case == "critical-review" and request.attempt_kind in {"task_review", "final_review"}:
            return {"status": "completed", "summary": "critical finding", "changed_files": [], "findings": [{"severity": "critical"}], "evidence_refs": [], "missing_evidence": ["verification"], "verification": [], "_provider_metadata": {"model": "gpt-5.6-sol", "reasoning": "high", "trusted_source": "fake"}}
        return completed_result_for(request.attempt_kind)
    return provider
```

Change execution fixtures so they provide input actions (`provider_case`, initial files, interruption phase, mutation action) separately from oracle assertions (`must_block`, expected files, expected status). The runner must call the public CLI with `CPE_FAKE_PROVIDER_CASE`, capture actual run artifacts, then check state and output. It may not read expected status to decide whether to create a file, block, resume, or report success. Rewrite each previously constant-success checker to invoke a production module, public CLI, or actual mutation fixture. `check_eval_harness.py` must AST-scan for constant-success bodies and ensure each wired name appears in the maintained manifest.

- [ ] **Step 4: Run the full evaluator and mutation suite**

Run: `./evals/run.sh`

Expected: all maintained checks pass with real subprocess/public-CLI evidence; injected negative review, final-review write, cross-task write, packet/evidence tamper, stale revision, blocked resume, event corruption, and no-op repair cases fail closed. The report must include command, duration, status, and return code for every check.

- [ ] **Step 5: Commit evaluator hardening**

```bash
git add evals/fake_provider.py evals/run.sh evals/static_execution_runner.py evals/static_prompt_runner.py evals/check_cpe_replay.py evals/check_repair_runs.py evals/check_recovery_policy.py evals/check_fault_injection.py evals/check_eval_harness.py evals/check_run_readiness.py evals/check_plan_executability_audit.py evals/check_operational_run_quality.py evals/check_recent_run_rubric.py evals/mutations
git diff --cached --check
git commit -m "test(cpe): exercise integrity through public CLI"
```

### Task 10: Align documentation, release evidence, and final L0-L4 closeout

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/docs/how-it-works.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md`
- Modify: `skills/kws-codex-plan-executor/docs/release-process.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/mental-model.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/post-merge-verification.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/event-journal.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/mode-contracts.md`
- Modify: `skills/kws-codex-plan-executor/references/headless-result-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/headless-runner.md`
- Modify: `skills/kws-codex-plan-executor/references/prompt-export-checklist.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_docs_contract.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_release_contract.py`
- Modify: `skills/kws-codex-plan-executor/evals/live-migration/release-status.json`
- Modify: `skills/kws-codex-plan-executor/evals/baselines/v3.0.0.json`

**Interfaces:**
- Consumes: final public behavior and L0-L4 eval report from Tasks 1–9.
- Produces: truthful `3.0.0` closure status, release-evidence validation bound to final commit and command results, current operator docs, and a reproducible closeout bundle.

- [ ] **Step 1: Add failing release-evidence assertions**

```python
# evals/check_release_evidence.py
import json
from pathlib import Path

payload = json.loads(Path("docs/verification-log.md").read_text(encoding="utf-8").split("## 2026-07-10 Asia/Seoul", 1)[1].split("## ", 1)[0].replace("```json", "").replace("```", ""))
assert payload["version"] == "3.0.0"
assert payload["release_status"] == "integrity-closure-pending; paid-live-pending"
assert payload["final_commit"]
assert all(item["returncode"] == 0 for item in payload["commands"])
assert payload["paid_live"]["status"] == "pending"
```

- [ ] **Step 2: Run the release check to verify it fails**

Run: `python3 evals/check_release_evidence.py`

Expected: FAIL because the current release docs call 3.0.0 deterministic-ready and the verification log is not bound to the final green commit/command results.

- [ ] **Step 3: Update docs and release metadata from evidence**

Document the runtime contract with these exact statuses:

```text
3.0.0: integrity-closure-pending; paid-live-pending; release_ready=false
3.0.1: deterministic-ready; paid-live-pending; release_ready=false
```

Update `SKILL.md`, README, history, release docs, Korean guides, state/event/packet/repair references, and eval coverage so they describe packet digests, revision-bound evidence, active/history blockers, read-only reviews, phase-aware resume, public export, and canonical completion. Change `check_release_contract.py` to require the current version, final commit, command return codes, Graphify freshness, skipped paid gates, and residual risk; a date string alone must not pass. Keep `release-status.json` at deterministic pending until the final L0-L4 report exists. Do not claim paid quality, cost, or context reduction.

- [ ] **Step 4: Run the complete L0-L4 closeout bundle**

Run:

```bash
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
python3 evals/check_release_evidence.py
bun run check
git diff --check
graphify update .
python3 scripts/check_graphify_freshness.py --repo-root . --update-ran --output /tmp/cpe-v3-integrity-graphify.json
git status --short --branch --untracked-files=all
```

Expected: every command exits 0, public result schemas pass, Graphify reports `fresh=true`, the tracked tree is clean, the verification log names the final implementation commit, and paid live remains explicitly pending. If Graphify changes tracked outputs, commit the design/code change first and then make a graph-only refresh commit so freshness evidence points at the final tree.

- [ ] **Step 5: Commit documentation and release closeout**

```bash
git add SKILL.md README.md ARCHITECTURE.md HISTORY.md docs references evals/check_docs_contract.py evals/check_release_contract.py evals/check_release_evidence.py evals/live-migration/release-status.json evals/baselines/v3.0.0.json
git diff --cached --check
git commit -m "docs(cpe): record integrity closure release evidence"
graphify update .
git add graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git diff --cached --check
git commit -m "docs(graphify): refresh final CPE integrity map"
```

---

## Cross-Task Verification Matrix

| Design requirement | Implementing tasks | Required proof |
| --- | --- | --- |
| Current writing-plans parser and explicit spec mapping | 1–2 | `check_plan_compiler.py`, parser fixture 18 |
| Immutable inputs and manifest/packet hashes | 1–2, 8 | `check_integrity_contracts.py`, packet tamper mutation |
| Read/write role separation and no worker commits | 3, 5, 9 | `check_task_scope_integrity.py`, policy mutation |
| Actual task-specific Git scope | 3, 5, 8 | cross-task write mutation fails closed |
| Revision-bound acceptance and verdicts | 1, 4–5, 8 | stale-revision and final-review-write mutations |
| Typed verdicts and missing-evidence blocking | 1, 4–5 | critical-review regression |
| Blocker history versus active blockers | 4, 6, 8 | blocked resume/recovery checks |
| Phase-aware resume and projected repair delta | 6, 8–9 | blocked-resume and no-op-repair fixtures |
| Canonical validator consumer parity | 5, 6, 8 | integrity passes while completion fails; parity check |
| Public run/resume/export/headless contracts | 5–7, 9 | public CLI integration and schema checks |
| Real eval behavior and fault injection | 9 | `run.sh` report plus meta-eval |
| Truthful release state and fresh Graphify | 10 | release-evidence check and L0-L4 closeout |

## Execution Order and Checkpoints

1. Execute Tasks 1–4 first; stop if typed state, packet, or event replay contracts are not deterministic.
2. Execute Task 5 only after measured delta and revision events are available; its regressions are the P0 release gate.
3. Execute Tasks 6–8 as one recovery/consumer checkpoint; no repair or CLI success claim is valid before this checkpoint passes.
4. Execute Task 9 only after public run/resume/export paths are stable; the eval harness must test those paths rather than bypass them.
5. Execute Task 10 last; update release metadata from the final command outputs and make Graphify the final graph-only commit.

## Plan Self-Review

- Spec coverage: all seven architecture components, revision evidence, typed verdicts, packet integrity, task scope, blocker lifecycle, repair delta, export/headless contracts, L0-L5 release policy, docs impact, and 23 acceptance criteria map to at least one task or the cross-task matrix.
- Completeness scan: every task has exact files, test names, commands, expected outcomes, and commit commands, with no unresolved action marker.
- Type consistency: `CompiledTask` feeds `PacketStore`, `WorktreeBasis`/`GitDelta` feed `AttemptController`, `RevisionEvidence` feeds events and validators, `ValidationReport.profile` feeds all consumers, and `ResumeAction` feeds CLI recovery.
- Scope check: the approved spec intentionally groups compiler, runtime integrity, recovery, public contracts, evals, and release docs into one integrity-closure release; each task still produces a focused, independently testable boundary.
