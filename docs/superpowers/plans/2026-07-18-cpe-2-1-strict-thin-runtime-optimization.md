# CPE 2.1 Strict Thin Runtime Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release CPE 2.1.0 as a format-3, strict thin sequential execution and audit harness that launches approved Superpowers plans directly, stops redundant retries and same-condition verification, and preserves the existing fail-closed completion contract.

**Architecture:** Keep one immutable input snapshot set and one isolated worktree, then launch one Superpowers-owned controller at a time under immutable run configuration. CPE observes content-free progress and environment facts, executes or reuses caller-selected verification mechanically, classifies transport outcomes, and gates only submitted completion evidence. Delete the model compiler and every semantic plan-mapping consumer instead of replacing it.

**Tech Stack:** Python 3 standard library, Git worktrees, Codex CLI JSONL/structured output, JSON Schema, `unittest`, shell eval runner.

## Global Constraints

- Approved design: `docs/superpowers/specs/2026-07-18-cpe-2-1-strict-thin-runtime-optimization-design.md`.
- Implementation baseline: commit `2a2ef03` (`docs(cpe): design strict thin runtime optimization`).
- CPE owns ordered snapshots, one worktree, bounded controller processes, mechanical receipt validation, fail-closed completion, and fact-only reports.
- Preserve the exact completion gates for `final_review_path`, `final_review_head`, empty `open_finding_ids`, empty `open_obligation_ids`, at least one successful verification, clean exact HEAD, ancestry, and sealed evidence. Ledger review/finding events remain advisory; only the submitted workflow receipt is a CPE gate.
- Superpowers alone owns task mapping, TDD choices, focused/full test selection, review/fix cycles, subagent strategy, and commits.
- Do not edit Superpowers upstream files under `/Users/kws/.codex/skills`.
- Do not add compatibility shims for run-state format 1 or 2. Format 3 must reject them without mutation.
- Do not add a replacement plan parser, verification allowlist, task/source-span mapping, capability registry, review lifecycle, obligation engine, context policy, or cross-run cache.
- The default controller sandbox is `danger-full-access`; the only opt-down is immutable run-creation `workspace-write`.
- CPE must never select a product full suite. The controller supplies the exact verification argv.
- Verification reuse is same-run and same-content only. Never reuse across HEAD changes or a dirty tree.
- One unchanged no-progress timeout stops immediately. Do not add a confirmation slice.
- Do not auto-install, copy, or symlink project dependencies, `.env`, SDK state, `local.properties`, virtual environments, or ignored build state.
- Keep raw provider messages, prompts, diffs, file bodies, and source paths out of progress and transport events.
- Use RED/GREEN with one named test method or class at a time. At the end of each task, run only that task's focused class set once on the resulting HEAD.
- At most one combined task review is allowed per task. Do not create review diff packages or routine re-review loops.
- Do not run `./evals/run.sh` during Tasks 1-6. Run it exactly once on the final clean implementation HEAD in Task 7. If it fails, fix with focused tests, commit a new clean HEAD, and run the full gate once on that new HEAD; never rerun an unchanged failed HEAD.
- Do not push, merge, deploy, publish, or mutate an existing failed CPE run.

## File Map And Ownership

```yaml
runtime:
  - path: skills/kws-codex-plan-executor/scripts/cpe.py
    role: public CLI and internal verification helper CLI
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py
    role: format-3 state, immutable run configuration, budgets
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py
    role: sequential orchestration, recovery, result gates, reports
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
    role: controller command, prompt, process lifecycle, safe JSONL facts
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/progress.py
    role: content-free worktree progress observation and timeout decisions
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/capabilities.py
    role: parent prerequisites and the single lazy loopback probe
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/verification.py
    role: exact verification execution, receipt sealing, same-run reuse
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py
    role: ledger ingestion and accepted evidence sealing
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/result_validation.py
    role: strict child result normalization
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py
    role: fact-derived optimization report
removed:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py
  - path: skills/kws-codex-plan-executor/templates/compiled-run-index.schema.json
schemas:
  - path: skills/kws-codex-plan-executor/templates/plan-result-schema.json
  - path: skills/kws-codex-plan-executor/templates/execution-ledger.schema.json
  - path: skills/kws-codex-plan-executor/templates/optimization-report.schema.json
evals:
  - path: skills/kws-codex-plan-executor/evals/check_runner.py
  - path: skills/kws-codex-plan-executor/evals/check_cli.py
  - path: skills/kws-codex-plan-executor/evals/fake_codex.py
  - path: skills/kws-codex-plan-executor/evals/fixtures/cpe-2-1-retry-forensic.json
docs:
  - path: skills/kws-codex-plan-executor/SKILL.md
  - path: skills/kws-codex-plan-executor/README.md
  - path: skills/README.md
```

## Execution Order

- Tasks 1-7 are sequential because they share `state.py`, `runner.py`, and the two eval modules.
- Do not parallelize edits across these tasks.
- A task is complete only after its focused tests pass, `git diff --check` passes, and its commit exists.
- The only integration review is in Task 7 after all implementation and docs commits.

---

### Task 1: Introduce Format-3 Immutable Runtime Configuration

**Owner boundary:** Define CPE-owned process configuration only. Do not add Superpowers workflow policy.

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Test: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Test: `skills/kws-codex-plan-executor/evals/check_cli.py`

**Interfaces:**

- Consumes: `run --workspace --plan [--spec] [--sandbox] [--controller-slice-seconds]`.
- Produces: `StateStore.create(run_root: Path, run_id: str, source_repository: Path, source_commit: str, worktree: Path, branch: str, specs: Sequence[Path], plans: Sequence[Path], sandbox_mode: str, controller_slice_seconds: int, initial_status: str = "preparing") -> StateStore`.
- Produces: `SequentialRunner.run(workspace: Path, specs: Sequence[Path], plans: Sequence[Path], run_id: str | None = None, sandbox_mode: str = "danger-full-access", controller_slice_seconds: int = 1200) -> dict[str, Any]`.
- Persists exact top-level `run_config`:

```python
{
    "sandbox_mode": "danger-full-access" | "workspace-write",
    "controller_slice_seconds": 1200..3600,
}
```

- Persists these approved per-plan values; the obsolete progress-checkpoint key is removed in Task 3 together with its decision consumer:

```python
{
    "controller_slice_timeout_seconds": run_config["controller_slice_seconds"],
    "plan_wall_budget_seconds": 7200,
    "max_controller_launches": 6,
}
```

**Steps:**

- [ ] Add RED state tests to `SequentialRunnerTest` and a new `Format3StateValidationTests` class that assert format 3, exact `run_config`, default/override values, and rejection of format 1 and 2 without changing the state file bytes.

```python
def test_format_three_persists_immutable_runtime_config(self) -> None:
    store = self.create_store(
        sandbox_mode="workspace-write",
        controller_slice_seconds=1800,
    )
    self.assertEqual(3, store.state["format_version"])
    self.assertEqual(
        {
            "sandbox_mode": "workspace-write",
            "controller_slice_seconds": 1800,
        },
        store.state["run_config"],
    )
    self.assertEqual(6, store.state["plans"][0]["budget"]["max_controller_launches"])
    self.assertEqual(7200, store.state["plans"][0]["budget"]["plan_wall_budget_seconds"])

def test_format_one_and_two_are_rejected_without_mutation(self) -> None:
    for version in (1, 2):
        state_path = self.write_legacy_state(version)
        before = state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "unsupported_legacy_run"):
            StateStore.open(state_path.parent)
        self.assertEqual(before, state_path.read_bytes())
```

- [ ] Run the exact RED methods and confirm failures mention format/config mismatch, not fixture setup:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py \
  SequentialRunnerTest.test_format_three_persists_immutable_runtime_config \
  Format3StateValidationTests.test_format_one_and_two_are_rejected_without_mutation
```

Expected: unittest reports a failure because the runtime still writes format 2 and has no `run_config`; fixture setup succeeds.

- [ ] Change `FORMAT_VERSION`, configuration validation, and creation signatures in `state.py`. Validate booleans as invalid integers and make the state shape exact.

```python
FORMAT_VERSION = 3
DEFAULT_SANDBOX_MODE = "danger-full-access"
DEFAULT_CONTROLLER_SLICE_SECONDS = 1200
MIN_CONTROLLER_SLICE_SECONDS = 1200
MAX_CONTROLLER_SLICE_SECONDS = 3600
SANDBOX_MODES = {"danger-full-access", "workspace-write"}

def validate_run_config(
    *, sandbox_mode: object, controller_slice_seconds: object,
) -> dict[str, object]:
    if sandbox_mode not in SANDBOX_MODES:
        raise ValueError("controller sandbox is invalid")
    if (
        not isinstance(controller_slice_seconds, int)
        or isinstance(controller_slice_seconds, bool)
        or not MIN_CONTROLLER_SLICE_SECONDS
        <= controller_slice_seconds
        <= MAX_CONTROLLER_SLICE_SECONDS
    ):
        raise ValueError("controller slice must be between 1200 and 3600 seconds")
    return {
        "sandbox_mode": sandbox_mode,
        "controller_slice_seconds": controller_slice_seconds,
    }
```

- [ ] Set the approved slice, launch, and wall values in newly created budget dictionaries. Retain the existing `max_progress_checkpoints` key only until Task 3 removes the key and its live consumer atomically; do not document it as a format-3 policy.

- [ ] Add RED CLI tests for default values, explicit opt-down, 1200/3600 inclusive bounds, 1199/3601 rejection, and the absence of sandbox/slice flags from `resume`.

```python
def test_run_runtime_configuration_defaults_bounds_and_persistence(self) -> None:
    default = self.command("run", "--workspace", str(self.repo), "--plan", str(self.plans[0]))
    self.assertEqual(0, default.returncode, default.stdout)
    state = self.only_run_state()
    self.assertEqual("danger-full-access", state["run_config"]["sandbox_mode"])
    self.assertEqual(1200, state["run_config"]["controller_slice_seconds"])
```

- [ ] Wire CLI arguments through `SequentialRunner.run` to `StateStore.create`.

```python
run.add_argument(
    "--sandbox",
    choices=("danger-full-access", "workspace-write"),
    default="danger-full-access",
)
run.add_argument(
    "--controller-slice-seconds",
    type=int,
    default=1200,
)
```

- [ ] Run the focused state/CLI class set once:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py Format3StateValidationTests
python3 evals/check_cli.py SequentialCliTest.test_run_runtime_configuration_defaults_bounds_and_persistence
git diff --check
```

Expected: all named tests `OK`; `git diff --check` has no output.

- [ ] Commit the task.

```bash
git add skills/kws-codex-plan-executor/scripts/cpe.py \
        skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
        skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
        skills/kws-codex-plan-executor/evals/check_runner.py \
        skills/kws-codex-plan-executor/evals/check_cli.py
git commit -m "feat(cpe): add immutable format 3 runtime config"
```

---

### Task 2: Delete The Model Compiler And Launch Superpowers Directly

**Owner boundary:** CPE passes immutable plan/spec snapshots to Superpowers; it does not interpret them.

**Files:**

- Delete: `skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py`
- Delete: `skills/kws-codex-plan-executor/templates/compiled-run-index.schema.json`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`

**Interfaces:**

- Removes: `CompiledIndexService`, `compiler_cache_key`, `default_operator_contract`, `validate_compiled_index`, `CodexLauncher.compiler_request`, and `CodexLauncher.compile_index`.
- Removes state fields: `operator_contract_path`, `operator_contract_sha256`, `compiled_run_index_path`, `compiled_run_index_sha256`.
- Changes constructor to `SequentialRunner(*, codex_home: Path | None = None, launcher: CodexLauncher | None = None)`.
- Changes launcher command to `_command(worktree: Path, result_path: Path, sandbox_mode: str) -> list[str]`.
- Changes launch to accept the saved `sandbox_mode` and no compiled index.

**Steps:**

- [ ] Replace compiler behavior tests with RED ownership-boundary tests: one controller launch per first attempt, no compiler artifacts, no compiler symbols/files, arbitrary caller-selected verification not rejected as undeclared, and no semantic workflow language in the prompt.

```python
def test_run_launches_controller_directly_without_compiler_artifacts(self) -> None:
    result = self.runner("direct").run(
        workspace=self.repo,
        specs=[self.spec],
        plans=[self.plan("completed")],
        run_id="direct",
    )
    self.assertEqual("completed", result["status"])
    root = self.home / "orchestrator" / "direct"
    self.assertEqual(1, fake_codex_launch_count(root))
    self.assertFalse((root / "compiled-run-index.json").exists())
    self.assertFalse((root / "operator-contract.json").exists())

def test_prompt_contains_only_infrastructure_worktree_boundaries(self) -> None:
    prompt = self.launcher_prompt()
    self.assertIn("already isolated", prompt)
    self.assertNotIn("COMPILED_RUN_INDEX", prompt)
    for forbidden in ("task mapping", "delta review", "finding cycle", "subagent count"):
        self.assertNotIn(forbidden, prompt.lower())
```

- [ ] Run the two exact RED methods. Confirm they fail because the compiler is still launched or referenced.

- [ ] Delete both compiler files with `apply_patch`, remove compiler imports and constructor dependency, and make `_initialize_run` transition from `preparing` to `ready` after snapshots are sealed.

```python
store = StateStore.create(
    run_root=run_root,
    run_id=run_id,
    source_repository=repository,
    source_commit=source_commit,
    worktree=worktree,
    branch=branch,
    specs=specs,
    plans=plans,
    sandbox_mode=sandbox_mode,
    controller_slice_seconds=controller_slice_seconds,
    initial_status="ready",
)
store.append_event("run.prepared", preparation="immutable_inputs")
return store
```

- [ ] Remove compiled-index fields from the exact format-3 state validator, `_compiled_plan`, preparation repair/cache flows, inspect advisories, task/source-span consumers, and compiler-derived capability/verification lookups.

- [ ] Update `_command` and `_prompt` to use the saved sandbox and direct snapshots. The prompt must say the worktree is already isolated and ordinary agents reuse it; it may allow another worktree only for an explicit plan requirement such as cross-revision comparison.

```python
def _command(self, worktree: Path, result_path: Path, sandbox_mode: str) -> list[str]:
    return [
        self.codex_bin,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--json",
        "--sandbox",
        sandbox_mode,
        "--add-dir",
        str(_git_common_directory(worktree)),
        "-C",
        str(worktree),
        "--output-schema",
        str(self.schema_path),
        "--output-last-message",
        str(result_path),
        "-",
    ]
```

- [ ] Remove the compiler branch, payload generation, invocation log, and helper functions from `fake_codex.py`. Keep only controller and verification fixture behavior.

- [ ] Remove compiler imports and compiler-only test classes/fixtures from both eval modules. Do not replace deleted semantic assertions with equivalent parser logic.

- [ ] Run focused direct-launch and public CLI tests once:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py \
  SequentialRunnerTest.test_run_launches_controller_directly_without_compiler_artifacts \
  VerificationReuseIntegrationTests.test_prompt_contains_only_infrastructure_worktree_boundaries
python3 evals/check_cli.py \
  SequentialCliTest.test_help_exposes_public_commands_and_internal_verify \
  VerificationCliTests.test_verify_accepts_superpowers_selected_command
git diff --check
```

Expected: named tests `OK`; no compiler import error; diff check is silent.

- [ ] Confirm removal mechanically without running a broad test suite:

```bash
test ! -e skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py
test ! -e skills/kws-codex-plan-executor/templates/compiled-run-index.schema.json
! rg -n "CompiledIndexService|compiled_run_index|compiled-run-index|compiler-attempt|execution_advisories" \
  skills/kws-codex-plan-executor/scripts \
  skills/kws-codex-plan-executor/evals \
  skills/kws-codex-plan-executor/templates
```

Expected: all commands exit 0 and print no matches.

- [ ] Commit the task.

```bash
git add -A -- skills/kws-codex-plan-executor
git commit -m "refactor(cpe): remove semantic plan compiler"
```

---

### Task 3: Observe Dirty-Tree Progress And Stop The First Stalled Slice

**Owner boundary:** Observe durable Git/filesystem facts only; do not interpret task meaning or source content.

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/progress.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

- Produces:

```python
@dataclass(frozen=True)
class WorktreeChangeObservation:
    changed: bool
    digest: str | None
    regular_file_count: int
    total_bytes: int | None
    reason_code: str | None
```

- Produces: `observe_worktree_changes(worktree: Path) -> WorktreeChangeObservation`.

- Extends `ProgressSnapshot` with `worktree_changed: bool` and `worktree_change_digest: str | None`.
- Uses exact bounds: 4,096 files, 16 MiB per regular file, 128 MiB total readable bytes.
- Removes `consecutive_no_progress_slices`, `max_progress_checkpoints`, `first_no_progress_slice`, and `second_no_progress_slice` from state/decision contracts.
- Produces immediate timeout reason `no_progress_timeout`.

**Steps:**

- [ ] Add RED unit tests for clean, tracked edit, deletion, untracked regular file, symlink/over-limit/unreadable inventory, and the guarantee that persisted/event payloads contain only digest/count/reason facts and never paths or bodies.

```python
def test_tracked_and_untracked_content_change_progress_without_leaking_content(self) -> None:
    tracked = self.repo / "tracked-secret-name.txt"
    tracked.write_text("sensitive-body", encoding="utf-8")
    subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "seed"], check=True)
    tracked.write_text("changed-sensitive-body", encoding="utf-8")
    (self.repo / "untracked-secret-name.txt").write_text("other-body", encoding="utf-8")
    observed = observe_worktree_changes(self.repo)
    self.assertTrue(observed.changed)
    self.assertRegex(observed.digest or "", r"^[0-9a-f]{64}$")
    serialized = json.dumps(dataclasses.asdict(observed))
    self.assertNotIn("secret-name", serialized)
    self.assertNotIn("sensitive-body", serialized)
```

- [ ] Add RED decision tests proving a changed timeout continues within six launches/two hours and the first unchanged timeout returns `stop_stalled/no_progress_timeout` with no confirmation launch.

```python
def test_first_unchanged_timeout_stops_immediately(self) -> None:
    decision = decide_checkpoint(
        previous=self.snapshot(),
        current=self.snapshot(),
        timed_out=True,
        controller_launches=1,
        plan_elapsed_seconds=1200,
        budget=CheckpointBudget(max_controller_launches=6, plan_wall_seconds=7200),
    )
    self.assertEqual(("stop_stalled", "no_progress_timeout"),
                     (decision.action, decision.reason_code))
```

- [ ] Run only the new `WorktreeProgressTests` and the exact stalled-timeout method; confirm RED.

- [ ] Implement non-shell Git inventory discovery with `git ls-files --modified --deleted --others --exclude-standard -z`. Hash canonical status/path/content facts internally, reject symlink following with `lstat`, and expose only the dataclass fields.

- [ ] Treat every unsafe or over-limit dirty inventory as `changed=True, digest=None, reason_code="dirty_inventory_unavailable"`. A Git-clean tree remains `changed=False, digest=<canonical-clean-digest>, reason_code=None`.

- [ ] Include the worktree observation in `progress_fingerprint`. Use the digest when available and the changed/unavailable marker otherwise.

```python
payload = {
    "head": snapshot.head,
    "completed_task_ids": _identifier_set(snapshot.completed_task_ids, name="completed task IDs"),
    "current_task_id": snapshot.current_task_id,
    "worktree_changed": snapshot.worktree_changed,
    "worktree_change_digest": snapshot.worktree_change_digest,
}
```

- [ ] Simplify `CheckpointBudget` and the decision table. Completion wins, then launch/wall budgets, then productive timeout, then immediate no-progress stop.

```python
@dataclass(frozen=True)
class CheckpointBudget:
    max_controller_launches: int
    plan_wall_seconds: int

if child_completed:
    return CheckpointDecision("finish", "child_completed", fingerprint)
if controller_launches >= budget.max_controller_launches:
    return CheckpointDecision("stop_budget", "launch_budget_exhausted", fingerprint)
if plan_elapsed_seconds >= budget.plan_wall_seconds:
    return CheckpointDecision("stop_budget", "wall_budget_exhausted", fingerprint)
if timed_out and changed:
    return CheckpointDecision("continue", "productive_timeout", fingerprint)
if timed_out:
    return CheckpointDecision("stop_stalled", "no_progress_timeout", fingerprint)
```

- [ ] Remove obsolete confirmation counters/reasons from state validation, WAL reconciliation, recovery metrics, and tests. Preserve `checkpoint_count` only as an observed child-checkpoint count, not an automatic retry budget.

- [ ] Run the focused classes once:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py \
  WorktreeProgressTests \
  ProgressDecisionTests \
  ProgressRecoveryIntegrationTests.test_first_no_progress_timeout_stops_without_confirmation_launch
git diff --check
```

Expected: all named tests `OK`; the integration fixture captures exactly one 1200-second controller launch.

- [ ] Commit the task.

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/{progress.py,runner.py,state.py,reporting.py} \
        skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): detect dirty progress and stop stalled slices"
```

---

### Task 4: Make Environment Blockers Zero-Launch Until Evidence Or Intent Changes

**Owner boundary:** Probe only CPE prerequisites plus lazy `loopback_bind`; unknown project capabilities remain child-attested.

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/capabilities.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/result_validation.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Modify: `skills/kws-codex-plan-executor/templates/plan-result-schema.json`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`

**Interfaces:**

- Produces: `resume --run-id RUN_ID [--retry-blocked | --retry-failed]`.
- Produces: `SequentialRunner.resume(*, run_id: str, retry_blocked: bool = False, retry_failed: bool = False) -> dict[str, Any]`.
- Produces: `observe_parent_prerequisites(worktree: Path, *, sandbox_mode: str) -> Sequence[CapabilityObservation]`.
- Produces: `observe_loopback_bind(*, sandbox_mode: str) -> CapabilityObservation`.

- Child blocker capability uses the existing bounded `resource` field with exact recognized value `loopback_bind`; every other nonempty bounded value is unknown/advisory.
- Persists content-free blocker facts: kind, code, capability/resource, parent fingerprint or null, fingerprint availability, and explicit retry count.

**Steps:**

- [ ] Add RED CLI tests for mutually exclusive retry flags and state-specific validation: blocked requires `--retry-blocked` only when unknown; failed requires `--retry-failed`; flags on other states fail before launch.

- [ ] Add RED integration tests for: parent prerequisite blocked/rechecked, lazy loopback probe after child block only, unchanged known blocker zero-launch, changed known blocker bounded launch, unknown blocker plain-resume zero-launch, and unknown blocker explicit retry exactly one launch.

```python
def test_unknown_child_blocker_requires_explicit_retry_without_launch(self) -> None:
    first = self.run_blocked(resource="browser_visual_evidence")
    before = fake_codex_launch_count(first.run_root)
    stopped = self.runner.resume(run_id=first.run_id)
    self.assertEqual("blocked", stopped["status"])
    self.assertEqual(before, fake_codex_launch_count(first.run_root))
    retried = self.runner.resume(run_id=first.run_id, retry_blocked=True)
    self.assertEqual(before + 1, fake_codex_launch_count(first.run_root))
```

- [ ] Run the new exact methods and confirm RED because plain resume currently relaunches or lacks `--retry-blocked`.

- [ ] Slim `capabilities.py`: retain validation/canonical hashing, implement only `repository_read`, `worktree_write`, `git`, and lazy `loopback_bind`. Delete compiled-plan input and generic task capability mapping.

- [ ] Probe repository read/worktree write/Git before the first controller launch. Use a private temporary regular file inside the CPE worktree for the write probe and remove it in `finally`; do not run package managers or product commands.

- [ ] On a child `blocked` result with `resource == "loopback_bind"`, run the local bind probe once, store the parent-observed fingerprint, and return. On resume, re-probe before controller/verification launch. If unchanged and unavailable, append `resume.stopped_unchanged_blocker` and return.

- [ ] On every unknown child resource, persist the child-attested blocker without inventing a probe. Plain resume appends `resume.stopped_unknown_blocker`; `--retry-blocked` records explicit intent and permits one normal bounded attempt.

- [ ] Update CLI and `resume` validation so `--retry-blocked` and `--retry-failed` are mutually exclusive and consumed only by the matching durable state.

```python
retry = resume.add_mutually_exclusive_group()
retry.add_argument("--retry-blocked", action="store_true")
retry.add_argument("--retry-failed", action="store_true")
```

- [ ] Ensure unchanged blockers stop before these call sites: launcher spawn, verification helper execution, worktree setup beyond parent prerequisite recheck, and any project command. Assert zero counts for all of them in tests.

- [ ] Run the focused blocker classes once:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py CapabilityTests ResumeCapabilityTests
python3 evals/check_cli.py \
  SequentialCliTest.test_resume_retry_flags_are_mutually_exclusive_and_state_specific
git diff --check
```

Expected: all named tests `OK`; zero-launch assertions pass.

- [ ] Commit the task.

```bash
git add skills/kws-codex-plan-executor/scripts/cpe.py \
        skills/kws-codex-plan-executor/scripts/cpe_runtime/{capabilities.py,result_validation.py,runner.py,state.py} \
        skills/kws-codex-plan-executor/templates/plan-result-schema.json \
        skills/kws-codex-plan-executor/evals/{fake_codex.py,check_runner.py,check_cli.py}
git commit -m "feat(cpe): stop unchanged environment blocker retries"
```

---

### Task 5: Re-key Verification By Execution Content And Reuse Across Phases

**Owner boundary:** Execute the exact Superpowers-selected argv or reuse exact evidence; never choose test scope.

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/verification.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Modify: `skills/kws-codex-plan-executor/templates/execution-ledger.schema.json`
- Modify: `skills/kws-codex-plan-executor/templates/optimization-report.schema.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`

**Interfaces:**

- Keeps `command_id` and `phase` in the request/receipt as observations.
- Produces a six-part `verification_cache_key` containing only argv digest, resolved cwd, exact HEAD, sanitized execution-environment fingerprint, input digest, and mutable-input policy.
- Produces: `resolved_executable_identity(argv0: str, *, cwd: Path, environ: Mapping[str, str]) -> dict[str, object]`.
- Produces: `execution_environment_fingerprint(*, environ: Mapping[str, str], sandbox_mode: str, executable_identity: Mapping[str, object]) -> str`.

- Verification result contains `requested_phase`, `executed_phase`, and `reused` truthfully.
- Required artifact identity remains part of receipt revalidation even though artifact paths are not a cache-key label.

**Steps:**

- [ ] Replace the eight-part cache-key test with RED six-part identity tests proving that command ID and phase changes alone preserve the key, while argv/cwd/HEAD/environment/executable/input/policy changes alter it.

```python
def test_cache_key_uses_six_execution_identity_parts(self) -> None:
    base = self.request(command_id="unit", phase="task")
    self.assertEqual(
        verification_cache_key(base),
        verification_cache_key(self.request(command_id="renamed", phase="branch_final")),
    )
    for field, value in (
        ("argv", (sys.executable, "-c", "print('changed')")),
        ("head", "b" * 40),
        ("input_digest", "2" * 64),
        ("mutable_input_policy", "always_execute"),
    ):
        self.assertNotEqual(verification_cache_key(base),
                            verification_cache_key(self.request(**{field: value})))
```

- [ ] Add RED integration tests for task-to-branch-final reuse, original/requested phase reporting, command-ID-only reuse, dirty-tree forced execution, executable replacement, changed environment, artifact drift, failed/timed-out/nondeterministic/always-execute misses, and no cross-HEAD reuse.

- [ ] Run the two exact cross-phase tests and confirm the old phase/command-ID key makes them RED.

- [ ] Implement executable resolution with `shutil.which(argv0, path=environ.get("PATH"))` for bare names and cwd-relative resolution for path argv. Safely resolve ordinary executable symlinks, require the final target to be a regular executable, and include only the resolved path digest, device/inode, size, mtime-ns, and content SHA-256 inside the fingerprint input.

- [ ] Build the verification child environment once and use the exact same mapping for fingerprinting and `subprocess.Popen`. Remove only process-incidental `PWD`, `OLDPWD`, `SHLVL`, `_`, and `TERM_SESSION_ID`; hash the complete canonical key/value mapping in memory into one digest and never persist individual names or values. The verification process therefore receives exactly the environment represented by the fingerprint; the controller launcher's existing secret filter remains unchanged.

- [ ] Refactor request serialization into identity and observation projections. Cache and index validation use only identity; the sealed receipt keeps original `command_id` and `executed_phase` without being rewritten on reuse.

```python
def _identity_document(request: VerificationRequest) -> dict[str, object]:
    return {
        "schema_version": 2,
        "argv_digest": _argv_digest(request.argv),
        "cwd": str(request.cwd.resolve(strict=True)),
        "head": request.head,
        "execution_environment_fingerprint": request.environment_fingerprint,
        "input_digest": request.input_digest,
        "mutable_input_policy": request.mutable_input_policy,
    }

def _observation_document(request: VerificationRequest) -> dict[str, object]:
    return {
        "command_id": request.command_id,
        "executed_phase": request.phase,
    }
```

- [ ] Remove all plan-declared allowlist checks from `SequentialRunner.verify`. Validate only run identity, cwd inside the active worktree, exact current HEAD, input/policy syntax, argv safety, and environment/executable identity.

- [ ] Before lookup, compute dirty state with `observe_worktree_changes`. Dirty or unavailable inventory skips lookup and index publication, executes once, and returns `reason="dirty_worktree_requires_execution"`.

- [ ] On a valid reuse, return the immutable receipt's `executed_phase`, the new `requested_phase`, `reused=True`, and one avoided execution. Do not append a second executed lifecycle event.

- [ ] Preserve fallback honesty: corrupt/unavailable helper evidence executes once, is recorded `executed_uncached`, has no reusable receipt, and is never indexed.

- [ ] Extend evidence ingestion and report validation for verification requests, executions, reuses, uncached executions, avoided executions, and requested/executed phase counts. Missing counters must never be fabricated from command labels.

- [ ] Run the focused verification classes once:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py VerificationReceiptTests VerificationReuseIntegrationTests
python3 evals/check_cli.py VerificationCliTests
git diff --check
```

Expected: all named tests `OK`; no product full-suite command is introduced by runtime or fixtures.

- [ ] Commit the task.

```bash
git add skills/kws-codex-plan-executor/scripts/cpe.py \
        skills/kws-codex-plan-executor/scripts/cpe_runtime/{verification.py,runner.py,evidence.py,reporting.py} \
        skills/kws-codex-plan-executor/templates/{execution-ledger.schema.json,optimization-report.schema.json} \
        skills/kws-codex-plan-executor/evals/{check_runner.py,check_cli.py}
git commit -m "feat(cpe): reuse exact verification across phases"
```

---

### Task 6: Classify Controller Transport And Report Content-Free Optimization Facts

**Owner boundary:** Record allowlisted controller facts and mechanical outcomes; do not retain raw provider content or change product acceptance.

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Modify: `skills/kws-codex-plan-executor/templates/optimization-report.schema.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Add: `skills/kws-codex-plan-executor/evals/fixtures/cpe-2-1-retry-forensic.json`

**Interfaces:**

- Extends `LaunchResult` with `outcome_code: str | None` and `state_db_warning_count: int`.
- Replaces `_UsageFilter` with `_JsonEventFilter`, which exposes only usage counters and an allowlisted provider outcome code.
- Stable controller outcome codes are exactly:

```python
CONTROLLER_OUTCOME_CODES = {
    "provider_usage_blocked",
    "provider_auth_blocked",
    "provider_unavailable",
    "controller_spawn_failed",
    "controller_transport_failed",
    "controller_result_missing",
    "controller_result_invalid",
    "controller_timed_out",
}
```

- Usage/auth/provider availability become blocked; invalid present result and unrecognized transport failures become failed; timeout still goes through progress/budget logic.

**Steps:**

- [ ] Add RED `_JsonEventFilter` tests using complete, split, oversized, malformed, and raw-message-bearing JSONL lines. Assert only integer usage fields and allowlisted codes survive and no raw string is stored.

- [ ] Add RED launch/runner tests for spawn failure, zero-exit missing result, nonzero missing result, invalid present result, timeout, usage block, auth block, provider unavailable, and repetitive state-db warning count.

```python
def test_nonzero_empty_result_is_transport_failure_not_invalid_product_result(self) -> None:
    result = self.run_scenario("nonzero_empty_result")
    self.assertEqual("failed", result["status"])
    self.assertEqual("controller_transport_failed", result["last_decision_reason"])
```

- [ ] Run the exact event-filter and empty-result tests and confirm RED.

- [ ] Implement safe code normalization from structured event `error.code` only. Map usage/rate-limit codes to `provider_usage_blocked`, authentication codes to `provider_auth_blocked`, and provider overload/unavailable codes to `provider_unavailable`. Ignore `message`, nested raw content, and unknown codes.

- [ ] Classify the process/result matrix after drain:

```python
if spawn_error is not None:
    outcome = "controller_spawn_failed"
elif timed_out:
    outcome = "controller_timed_out"
elif provider_outcome is not None:
    outcome = provider_outcome
elif payload is None and returncode == 0:
    outcome = "controller_result_missing"
elif payload is None:
    outcome = "controller_transport_failed"
else:
    outcome = None
```

- [ ] Keep schema-invalid present payload classification in `runner.py` as `controller_result_invalid`; do not let the launcher interpret product fields.

- [ ] Count known Codex state-database warning patterns only in bounded stderr diagnostics. Persist the count, never the matched line, in the attempt event/report.

- [ ] Extend optimization reporting with exact transport counts and blocker/retry/progress facts while preserving independent known/unknown usage fields, missing duration/reason, aggregate controller+nested scope, metadata-only artifact inventory, and `integration=not_observed` handoff.

- [ ] Add sanitized fixture `cpe-2-1-retry-forensic.json` with schema:

```json
{
  "schema_version": 1,
  "provenance": "sanitized_cpe_observation",
  "observations": [
    {"signal": "unchanged_environment_blocker", "occurrences": 3},
    {"signal": "short_empty_result", "occurrences": 2},
    {"signal": "state_db_warning", "occurrences": 4},
    {"signal": "plain_resume_without_new_evidence", "occurrences": 3}
  ],
  "contains_raw_prompts": false,
  "contains_raw_diffs": false,
  "contains_provider_messages": false
}
```

- [ ] Add fixture regression assertions that the optimized policy would permit zero controller launches for unchanged blockers and classifies empty results without raw content. Keep the fixture advisory; never make it a product acceptance gate.

- [ ] Run the focused transport/report classes once:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py \
  ControllerTransportTests \
  HistoricalEvidenceFixtureTests \
  OptimizationReportObservabilityTests
git diff --check
```

Expected: all named tests `OK`; report/schema parity passes.

- [ ] Commit the task.

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/{launcher.py,runner.py,reporting.py} \
        skills/kws-codex-plan-executor/templates/optimization-report.schema.json \
        skills/kws-codex-plan-executor/evals/check_runner.py \
        skills/kws-codex-plan-executor/evals/fake_codex.py \
        skills/kws-codex-plan-executor/evals/fixtures/cpe-2-1-retry-forensic.json
git commit -m "feat(cpe): classify transport and retry evidence"
```

---

### Task 7: Synchronize The 2.1 Contract, Review Once, And Run One Final Gate

**Owner boundary:** Document the actual thin harness and prove the reduced runtime. Do not add release publication or integration claims.

**Files:**

- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/README.md`
- Modify as cleanup requires: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify as cleanup requires: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Modify as cleanup requires: `skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py`

**Interfaces:**

- Publishes version `2.1.0` and run-state format `3` in skill/docs.
- Documents exact CLI defaults and residual risk of `danger-full-access`.
- Inventory lists every and only tracked CPE runtime/schema/fixture file.
- Branch handoff remains local factual evidence with `integration.status = "not_observed"`.

**Steps:**

- [ ] Update `SKILL.md` and `README.md` to describe direct Superpowers launch, one reused worktree, 1200-second default, immutable sandbox/slice, zero-launch blocker rules, caller-selected verification, same-HEAD cross-phase reuse, transport outcomes, and fail-closed completion.

- [ ] State the ownership rule verbatim in both docs:

```text
CPE maintains one execution environment and verifies submitted facts.
Superpowers decides what work and verification are correct.
```

- [ ] Document the accepted `danger-full-access` residual risk: writes outside the worktree are not fully observable or reversible; prompt/remote prohibitions and Git gates remain but are not a sandbox substitute.

- [ ] Document that CPE never runs a full suite by itself. A full suite observed in a run was selected by the approved plan/Superpowers unless the exact verification helper merely executed that submitted argv.

- [ ] Update `skills/README.md` installation guidance only as necessary. Keep source-of-truth symlinks; do not copy the skill into Codex/Claude directories.

- [ ] Replace old runtime inventory entries and counts. Remove all compiler/schema/format-2/3600-second/confirmation-slice/allowlist claims while retaining historical fixture descriptions as explicitly non-resumable audit evidence.

- [ ] Add or update docs contract tests in `SequentialCliTest` for version, CLI, ownership, inventory, no compiler, no workflow-semantic ownership, no false merge/push/deploy claim, and exact `integration=not_observed` wording.

- [ ] Run the existing focused completion-gate regressions once before the docs commit to prove the refactor retained clean-HEAD, verification-drift, final-review-head, `open_finding_ids`, and `open_obligation_ids` fail-closed behavior without recreating a review lifecycle.

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runner.py \
  EnvelopeRepairTests.test_dirty_head_and_verification_drift_fail_closed \
  EnvelopeRepairTests.test_review_finding_and_obligation_events_are_advisory_for_repair \
  BranchHandoffTests.test_completion_persists_truthful_immutable_handoff_before_state
```

Expected: all three methods pass; nonempty receipt arrays are rejected while advisory ledger events do not become CPE workflow policy.

- [ ] Run only docs/static checks before the final implementation review:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_cli.py \
  SequentialCliTest.test_skill_docs_match_hardened_public_contract \
  SequentialCliTest.test_readme_inventory_covers_every_tracked_runtime_module \
  SequentialCliTest.test_thin_audit_docs_and_release_inventory_match_runtime
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: all named tests `OK`; diff check is silent.

- [ ] Run a stale runtime-scope scan. Runtime and schema sources must have no removed compiler, allowlist, or confirmation-slice symbols; tests may mention those strings only in negative assertions and historical fixtures remain audit-only.

```bash
! rg -n "compiled-run-index|CompiledIndexService|compiled_run_index|first_no_progress_slice|second_no_progress_slice" \
  skills/kws-codex-plan-executor/scripts \
  skills/kws-codex-plan-executor/templates
rg -n "compiler|allowlist|format 2|3600" \
  skills/kws-codex-plan-executor/{SKILL.md,README.md,evals} \
  --glob '!evals/fixtures/canvas-direct-run-format2.json'
```

Expected: the first scan exits 0 with no output; manually inspected matches from the second scan are negative assertions, explicit unsupported-history notes, or stale items to remove before continuing.

- [ ] Run an unused-surface/inventory scan without executing the full gate:

```bash
python3 -m py_compile \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/*.py \
  skills/kws-codex-plan-executor/evals/*.py
bash -n skills/kws-codex-plan-executor/evals/run.sh
git ls-files skills/kws-codex-plan-executor | sort
git status --short --branch --untracked-files=all
```

Expected: compile/shell checks are silent; inventory has no compiler/schema; only intended plan changes are present.

- [ ] Commit docs and cleanup so the integration review examines a clean HEAD.

```bash
git add -A -- skills/kws-codex-plan-executor skills/README.md
git commit -m "docs(cpe): publish strict thin 2.1 contract"
git status --short --branch --untracked-files=all
```

Expected: working tree is clean.

- [ ] Perform exactly one final integration review using `code_review.md` against `2a2ef03..HEAD`. Review correctness, regression risk, verification, scope, privacy, and observability. Do not create a diff package and do not start a routine re-review.

```bash
git diff --stat 2a2ef03..HEAD
git diff --check 2a2ef03..HEAD
git diff 2a2ef03..HEAD -- \
  skills/kws-codex-plan-executor \
  skills/README.md
```

Expected: either no findings, or a bounded list of findings tied to the approved 2.1 contract.

- [ ] If the one integration review finds an in-scope defect, add one focused RED test, implement the smallest fix, run only that test/class once, and commit. Record unrelated hardening as backlog; do not perform a second integration review.

- [ ] Confirm the final implementation HEAD is clean, then run the complete CPE gate exactly once:

```bash
cd /Users/kws/source/private/Archive
git status --porcelain --untracked-files=all
git rev-parse HEAD
cd skills/kws-codex-plan-executor
./evals/run.sh
```

Expected: first command prints nothing; `check_runner.py` passes, `check_cli.py` passes, and the script ends with `2 suites passed`.

- [ ] If and only if that full gate fails, record the failed HEAD and output once, diagnose with the exact failing test/class, fix and commit a new clean HEAD, then run `./evals/run.sh` once on the new HEAD. Never repeat it on the unchanged failed HEAD.

- [ ] Produce the final local handoff with commit range, exact focused/full verification evidence, final review outcome, remaining residual risks, branch name, observed HEAD, last-known HEAD, and `integration=not_observed`. Do not claim CPE acceptance for any older failed controller run and do not push or merge.

## Final Acceptance Matrix

| Requirement | Proving task/evidence |
|---|---|
| Format 3 only; format 1/2 immutable rejection | Task 1 state tests |
| Default `danger-full-access`, opt-down, immutable 1200-3600 slice | Task 1 CLI/state tests |
| No compiler call, schema, mapping, allowlist, or advisory | Task 2 direct-launch tests and removal scan |
| Same worktree and infrastructure-only prompt | Task 2 launcher tests |
| Dirty tracked/untracked work is progress without content leakage | Task 3 progress tests |
| First unchanged timeout stops; changed timeout bounded by 6/7200 | Task 3 decision/integration tests |
| Known unchanged and unknown plain-resume blockers launch nothing | Task 4 blocker tests |
| Unknown blocker requires `--retry-blocked`; failed requires `--retry-failed` | Task 4 CLI/integration tests |
| Same-run exact verification reuses across command ID/phase labels | Task 5 receipt and CLI tests |
| HEAD/dirty/cwd/argv/executable/env/input/policy/artifact/failure invalidation | Task 5 invalidation matrix |
| CPE never selects a full suite | Task 5 source/fixture inspection and docs contract |
| Safe transport/provider classification without raw message retention | Task 6 transport tests |
| Honest usage/reuse/blocker/artifact/handoff reporting | Task 6 report/schema tests |
| Existing clean HEAD, ancestry, review, findings, obligations, verification, evidence gates preserved | Task 7 final full gate and integration review |
| No unused removed-scope files/imports/docs entries | Task 7 compile, inventory, and stale-scope scans |
| One final review and one final clean-HEAD full gate | Task 7 recorded evidence |
| No push/merge/deploy/publish | Final local handoff |
