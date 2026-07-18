# CPE 2.0 Wave 0 Format And Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the format-version-1 runtime contract with a coherent format-version-2 state/result lifecycle while preserving every existing process, lock, snapshot, Git, and bounded-log safety guarantee.

**Architecture:** Keep the current Python standard-library runner and exact `run --spec --plan --workspace` user input. Change the durable state machine and strict result envelope first, adapt the fake Codex and runner transitions to that contract, and leave compiler, optimization, checkpoint intelligence, and evidence reuse to later waves.

**Tech Stack:** Python 3 standard library, `unittest`, Git CLI, JSON Schema draft 2020-12, Bash.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-17-cpe-evidence-driven-execution-optimization-design.md`.
- Do not invoke CPE recursively from a plan controller; the outer executor already owns the isolated worktree.
- Do not modify Superpowers skills, `writing-plans`, plan templates, or hooks.
- Keep the exact current public forms `run --spec --plan --workspace`, `resume --run-id RUN_ID`, and `inspect --run-id RUN_ID` usable.
- Format-version-1 inspect, resume, migration, and dual-write are out of scope.
- Existing format-version-1 directories must remain untouched and return `unsupported_legacy_run`.
- Preserve POSIX advisory locking, process-group cleanup, two-pipe draining, bounded logs, immutable snapshots, exact clean HEAD, ancestry checks, and no implicit remote mutation.
- Keep `./evals/run.sh` sequential, credential-free, network-free, model-free, and below 15 seconds.
- Intermediate Wave 0 commits are unreleased implementation commits; do not claim public 2.0 completion or update the skill version until Wave 4.

---

## File Structure

- Modify `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`: format-2 state creation, validation, atomic persistence, and typed event base fields.
- Modify `skills/kws-codex-plan-executor/templates/plan-result-schema.json`: strict format-2 child result envelope.
- Modify `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`: format-2 transitions, result normalization, resume, and truthful summary.
- Modify `skills/kws-codex-plan-executor/scripts/cpe.py`: format-2 public exit status mapping.
- Modify `skills/kws-codex-plan-executor/evals/fake_codex.py`: deterministic format-2 controller fixtures.
- Modify `skills/kws-codex-plan-executor/evals/check_runner.py`: state, result, transition, and safety regression tests.
- Modify `skills/kws-codex-plan-executor/evals/check_cli.py`: public status/schema/legacy rejection contract.
- Create `skills/kws-codex-plan-executor/evals/fixtures`: shared sanitized deterministic fixture directory.
- Create `skills/kws-codex-plan-executor/evals/fixtures/canvas-direct-run-format2.json`: sanitized direct-CPE regression evidence derived from the approved design appendix.
- Create `skills/kws-codex-plan-executor/evals/fixtures/readmates-comparative.json`: sanitized non-CPE comparison evidence, labelled comparative only.
- Create `skills/kws-codex-plan-executor/evals/fixtures/gasstation-comparative.json`: sanitized non-CPE comparison evidence, labelled comparative only.

### Task 1: Lock The Format-2 State Contract

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py:16-368`
- Test: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**
- Consumes: absolute UTF-8 spec/plan paths, source repository, source commit, worktree path, branch.
- Produces: `atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None`, `StateStore.create(...) -> StateStore`, `StateStore.open(...) -> StateStore`, `StateStore.append_event(...)`, `state["format_version"] == 2`, run states `preparing|ready|running|checkpointed|blocked|failed|completed`.

- [ ] **Step 1: Write the failing format-2 creation and legacy rejection tests**

Add these methods to `SequentialRunnerTest`:

```python
def test_format_two_state_has_preparation_and_budget_fields(self) -> None:
    source_commit = git(self.repo, "rev-parse", "HEAD")
    store = StateStore.create(
        run_root=self.home / "orchestrator" / "format-two",
        run_id="format-two",
        source_repository=self.repo,
        source_commit=source_commit,
        worktree=self.home / "worktrees" / "format-two",
        branch="codex/format-two",
        specs=[],
        plans=[self.plan(1, "completed")],
    )
    self.assertEqual(store.state["format_version"], 2)
    self.assertEqual(store.state["status"], "preparing")
    self.assertEqual(
        store.state["plans"][0]["budget"],
        {
            "controller_slice_timeout_seconds": 3600,
            "max_progress_checkpoints": 6,
            "plan_wall_budget_seconds": 21600,
            "max_controller_launches": 8,
        },
    )
    self.assertEqual(store.state["plans"][0]["consecutive_no_progress_slices"], 0)
    self.assertEqual(store.state["plans"][0]["progress_checkpoint_count"], 0)
    self.assertIsNone(store.state["plans"][0]["progress_fingerprint"])
    self.assertIsNone(store.state["plans"][0]["environment_fingerprint"])
    self.assertEqual(store.state["plans"][0]["plan_elapsed_seconds"], 0)
    self.assertTrue((store.root / "evidence").is_dir())
    self.assertTrue((store.root / "reports").is_dir())

def test_format_one_state_is_unsupported_without_mutation(self) -> None:
    root = self.home / "orchestrator" / "legacy-format-one"
    root.mkdir(parents=True, mode=0o700)
    state_path = root / "state.json"
    state_path.write_text('{"format_version":1}', encoding="utf-8")
    before = state_path.read_bytes()
    with self.assertRaisesRegex(ValueError, "unsupported_legacy_run"):
        StateStore.open(root)
    self.assertEqual(state_path.read_bytes(), before)

def test_format_two_event_has_bounded_trust_labelled_envelope(self) -> None:
    store = self.create_format_two_store("event-envelope")
    store.append_event(
        "plan.attempt_finished",
        plan_id="plan-01",
        reason_code="child_completed",
        duration_ms=42,
        result="pass",
        evidence_refs=["results/plan-01.json"],
    )
    event = json.loads(store.events_path.read_text(encoding="utf-8").splitlines()[-1])
    self.assertRegex(event["event_id"], r"^[0-9a-f]{32}$")
    self.assertEqual(event["source"], "parent_observed")
    self.assertEqual(event["run_id"], "event-envelope")
    self.assertEqual(event["category"], "plan")
    self.assertEqual(event["action"], "plan.attempt_finished")
```

- [ ] **Step 2: Run the focused tests and confirm the format-1 RED state**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_format_two_state_has_preparation_and_budget_fields \
  evals.check_runner.SequentialRunnerTest.test_format_one_state_is_unsupported_without_mutation -v
```

Expected: FAIL because `StateStore` still emits format 1 and does not create `evidence/` or `reports/`.

- [ ] **Step 3: Implement the format-2 constants and plan record**

Replace the status constants and add the exact defaults in `state.py`:

```python
FORMAT_VERSION = 2
RUN_STATUSES = {
    "preparing",
    "ready",
    "running",
    "checkpointed",
    "completed",
    "blocked",
    "failed",
}
TRUST_LEVELS = {"parent_observed", "child_attested", "derived", "hypothesis"}
PLAN_STATUSES = {
    "pending",
    "running",
    "checkpointed",
    "completed",
    "blocked",
    "failed",
}
DEFAULT_PLAN_BUDGET = {
    "controller_slice_timeout_seconds": 3600,
    "max_progress_checkpoints": 6,
    "plan_wall_budget_seconds": 21_600,
    "max_controller_launches": 8,
}
```

Extract the existing durable-write sequence into the shared helper used by later evidence/report modules:

```python
def atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("private artifact must be a regular file")
        _write_all(descriptor, payload)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
```

Use it from `StateStore.save()` without changing canonical JSON bytes, permissions, or directory-fsync behavior.

Change `StateStore.create` to default to `preparing`, create all private roots, and emit this plan shape:

```python
for name in ("inputs", "results", "logs", "evidence", "reports"):
    _private_directory(run_root / name)

plan_records = [
    {
        "plan_id": record["document_id"],
        "status": "pending",
        "starting_commit": None,
        "accepted_commit": None,
        "attempt_count": 0,
        "controller_launch_count": 0,
        "checkpoint_count": 0,
        "progress_checkpoint_count": 0,
        "consecutive_no_progress_slices": 0,
        "progress_fingerprint": None,
        "environment_fingerprint": None,
        "capability_probe_ids": [],
        "plan_started_at": None,
        "plan_elapsed_seconds": 0,
        "last_known_head": None,
        "result_path": None,
        "budget": dict(DEFAULT_PLAN_BUDGET),
    }
    for record in records
    if record["role"] == "plan"
]
```

Set `format_version` to `FORMAT_VERSION`. In `open`, distinguish old state before calling `_validate`:

```python
version = payload.get("format_version") if isinstance(payload, dict) else None
if version == 1:
    raise ValueError("unsupported_legacy_run")
if version != FORMAT_VERSION:
    raise ValueError("unsupported_run_format")
```

Replace the old free-form `kind` event with one content-free format-2 envelope while keeping call sites simple:

```python
def append_event(
    self,
    action: str,
    *,
    source: str = "parent_observed",
    **details: object,
) -> None:
    if source not in TRUST_LEVELS:
        raise ValueError("event source is invalid")
    if not action or len(action) > 100:
        raise ValueError("event action must be bounded")
    forbidden = {"prompt", "transcript", "raw_output", "environment", "secret", "token"}
    if forbidden & set(details):
        raise ValueError("event contains forbidden content field")
    event = {
        "event_id": uuid.uuid4().hex,
        "at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "run_id": self.state["run_id"],
        "category": action.split(".", 1)[0],
        "action": action,
        **details,
    }
    encoded = (
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    if len(encoded) > 16_384:
        raise ValueError("event record exceeds the bounded event contract")
    self._append_event_bytes(encoded)
```

`_append_event_bytes` must preserve the existing `O_NOFOLLOW`, regular-file check, append, fsync, and `0600` behavior. Parent lifecycle observations use `parent_observed`; ingested child ledger events keep `child_attested`. A `hypothesis` event cannot drive state transitions.

Update exact field validation, semantic completed-prefix validation, and allowed run/plan pairs for the new statuses. Keep atomic replace, directory fsync, file permissions, and snapshot digest validation unchanged.

- [ ] **Step 4: Run the focused tests and all pre-existing state tests**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_format_two_state_has_preparation_and_budget_fields \
  evals.check_runner.SequentialRunnerTest.test_format_one_state_is_unsupported_without_mutation \
  evals.check_runner.SequentialRunnerTest.test_format_two_event_has_bounded_trust_labelled_envelope \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_impossible_plan_and_run_relationships \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_incomplete_completed_evidence \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_nonpristine_future_plan -v
```

Expected: PASS; state files remain `0600`, run directories remain `0700`, and impossible state combinations still fail closed.

- [ ] **Step 5: Commit the state contract**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): establish format two state"
```

### Task 2: Define The Strict Format-2 Result Envelope

**Files:**
- Modify: `skills/kws-codex-plan-executor/templates/plan-result-schema.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Create: `skills/kws-codex-plan-executor/evals/fixtures`

**Interfaces:**
- Consumes: one plan controller final response.
- Produces: strict nullable-wire fields `checkpoint`, `blocker`, and `workflow_receipt`; verification records with stable command identity.

- [ ] **Step 1: Replace the CLI schema test with a format-2 contract RED**

Change `test_output_schema_is_strict_structured_output_compatible` to assert:

```python
self.assertEqual(set(schema["required"]), set(schema["properties"]))
self.assertEqual(
    schema["properties"]["status"]["enum"],
    ["completed", "checkpointed", "blocked", "failed"],
)
for name in ("checkpoint", "blocker", "workflow_receipt"):
    self.assertEqual(schema["properties"][name]["anyOf"][-1], {"type": "null"})
verification = schema["properties"]["verification"]["items"]
self.assertEqual(
    set(verification["required"]),
    {"command_id", "argv_digest", "phase", "evidence_key", "exit_code", "receipt_path"},
)
```

- [ ] **Step 2: Run the schema test and verify it fails against v1**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_cli.SequentialCliTest.test_output_schema_is_strict_structured_output_compatible -v
```

Expected: FAIL because the existing schema exposes recovery triples and two-field verification items.

- [ ] **Step 3: Replace `plan-result-schema.json` with the format-2 shape**

Use these top-level fields and strict status-dependent objects:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "plan_id",
    "status",
    "head_commit",
    "summary",
    "verification",
    "checkpoint",
    "blocker",
    "workflow_receipt"
  ],
  "properties": {
    "plan_id": {"type": "string", "minLength": 1, "maxLength": 128},
    "status": {
      "type": "string",
      "enum": ["completed", "checkpointed", "blocked", "failed"]
    },
    "head_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
    "verification": {
      "type": "array",
      "maxItems": 256,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["command_id", "argv_digest", "phase", "evidence_key", "exit_code", "receipt_path"],
        "properties": {
          "command_id": {"type": "string", "minLength": 1, "maxLength": 128},
          "argv_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
          "phase": {"type": "string", "enum": ["task", "affected", "branch_final", "merged_main"]},
          "evidence_key": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
          "exit_code": {"type": "integer"},
          "receipt_path": {"type": ["string", "null"], "maxLength": 500}
        }
      }
    },
    "checkpoint": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["reason", "progress_fingerprint", "completed_task_ids", "current_task_id"],
          "properties": {
            "reason": {"type": "string", "enum": ["controller_budget", "context_budget", "coordinator_interrupt", "timeout_progress"]},
            "progress_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "completed_task_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128}},
            "current_task_id": {"type": ["string", "null"], "maxLength": 128}
          }
        },
        {"type": "null"}
      ]
    },
    "blocker": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["kind", "code", "resource", "operation", "errno", "retry_condition", "fingerprint"],
          "properties": {
            "kind": {"type": "string", "enum": ["verification_environment", "plan_contract", "operator_owned", "integrity"]},
            "code": {"type": "string", "minLength": 1, "maxLength": 128},
            "resource": {"type": "string", "minLength": 1, "maxLength": 128},
            "operation": {"type": "string", "minLength": 1, "maxLength": 128},
            "errno": {"type": ["string", "null"], "maxLength": 64},
            "retry_condition": {"type": "string", "minLength": 1, "maxLength": 256},
            "fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
          }
        },
        {"type": "null"}
      ]
    },
    "workflow_receipt": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["ledger_path", "final_review_path", "final_review_head", "open_finding_ids", "open_obligation_ids"],
          "properties": {
            "ledger_path": {"type": "string", "minLength": 1, "maxLength": 500},
            "final_review_path": {"type": "string", "minLength": 1, "maxLength": 500},
            "final_review_head": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "open_finding_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128}},
            "open_obligation_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128}}
          }
        },
        {"type": "null"}
      ]
    }
  }
}
```

Update `fake_codex.py` to emit all nullable wire fields and format-2 verification entries:

```python
payload = {
    "plan_id": plan_id,
    "status": status,
    "head_commit": head,
    "summary": f"fake {scenario} attempt {attempt}",
    "verification": (
        [{
            "command_id": "fake-final",
            "argv_digest": "f" * 64,
            "phase": "branch_final",
            "evidence_key": "0" * 64,
            "exit_code": 0,
            "receipt_path": None,
        }]
        if status == "completed"
        else []
    ),
    "checkpoint": None,
    "blocker": None,
    "workflow_receipt": None,
}
```

For completed output, populate the new receipt with `final_review_head=head`; for blocked output, populate `blocker`; for interrupted scenarios, emit `status="checkpointed"` and a checkpoint object.

- [ ] **Step 4: Run schema and fake-output focused tests**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_cli.SequentialCliTest.test_output_schema_is_strict_structured_output_compatible \
  evals.check_runner.SequentialRunnerTest.test_two_plans_execute_sequentially_in_one_worktree -v
```

Expected: schema test PASS; runner test remains RED until Task 3 updates normalization and acceptance.

- [ ] **Step 5: Commit the schema and deterministic producer**

```bash
git add skills/kws-codex-plan-executor/templates/plan-result-schema.json \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_cli.py
git commit -m "feat(cpe): define format two result envelope"
```

### Task 3: Move Runner Transitions To Format 2

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py:208-1042`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py:13-80`
- Test: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Test: `skills/kws-codex-plan-executor/evals/check_cli.py`

**Interfaces:**
- Consumes: normalized format-2 result envelope and `StateStore` format-2 state.
- Produces: public statuses `completed|failed|blocked|checkpointed`, exit codes `0|1|2|3`, truthful `observed_head`/`last_known_head`.

- [ ] **Step 1: Add RED tests for format-2 transitions and missing worktrees**

Add focused tests:

```python
def test_checkpointed_result_is_durable_and_resumable(self) -> None:
    runner = self.runner()
    first = runner.run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "interrupted")],
        run_id="checkpointed",
    )
    self.assertEqual(first["status"], "checkpointed")
    self.assertEqual(first["plans"][0]["status"], "checkpointed")
    resumed = runner.resume(run_id="checkpointed")
    self.assertIn(resumed["status"], {"checkpointed", "completed"})

def test_missing_worktree_never_reports_source_commit_as_observed_head(self) -> None:
    runner = self.runner()
    result = runner.run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "blocked")],
        run_id="missing-worktree-summary",
    )
    Path(result["worktree"]).rename(self.root / "moved-worktree")
    inspected = runner.inspect(run_id="missing-worktree-summary")
    self.assertIsNone(inspected["observed_head"])
    self.assertEqual(inspected["last_known_head"], result["last_known_head"])
```

- [ ] **Step 2: Run the tests and capture the transition RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_checkpointed_result_is_durable_and_resumable \
  evals.check_runner.SequentialRunnerTest.test_missing_worktree_never_reports_source_commit_as_observed_head -v
```

Expected: FAIL because the runner still emits `interrupted` and aliases `source_commit` as current HEAD.

- [ ] **Step 3: Normalize nullable format-2 fields and update transitions**

Replace the recovery-triple normalization in `_handoff_error` with:

```python
for name in ("checkpoint", "blocker", "workflow_receipt"):
    if payload.get(name) is None:
        payload.pop(name, None)

status = payload.get("status")
if status not in {"completed", "checkpointed", "blocked", "failed"}:
    return "invalid_result"
if status == "completed" and "workflow_receipt" not in payload:
    return "invalid_workflow_receipt"
if status == "checkpointed" and "checkpoint" not in payload:
    return "invalid_checkpoint"
if status == "blocked" and "blocker" not in payload:
    return "invalid_blocker"
```

For a plan-controller result, accept verification phases `task`, `affected`, and `branch_final`. Reject `merged_main` as `invalid_verification_phase`; that phase is reserved in the wire enum for a separate parent-observed integration receipt and cannot be claimed by the branch worker.

Update `_execute` so a format-2 checkpoint persists `plan["status"] = "checkpointed"`, `state["status"] = "checkpointed"`, `plan["last_known_head"] = payload["head_commit"]`, saves, and returns the summary. Do not implement progress-aware automatic continuation yet; Wave 2 owns that policy.

Update `_summary` to report separate values:

```python
worktree = Path(state["worktree"])
observed_head = (
    _git(worktree, "rev-parse", "HEAD")
    if worktree.is_dir()
    else None
)
last_known_head = observed_head
if last_known_head is None and state["plans"]:
    last_known_head = state["plans"][max(0, state["current_plan_index"] - 1)][
        "last_known_head"
    ]
result = {
    "run_id": state["run_id"],
    "status": state["status"],
    "source_commit": state["source_commit"],
    "worktree": state["worktree"],
    "branch": state["branch"],
    "observed_head": observed_head,
    "last_known_head": last_known_head,
    "current_plan_index": state["current_plan_index"],
    "plan_count": len(state["plans"]),
}
```

Set `EXIT_CODES = {"completed": 0, "failed": 1, "blocked": 2, "checkpointed": 3}` in `cpe.py`.

- [ ] **Step 4: Run transition, resume, process, and lock regressions**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_checkpointed_result_is_durable_and_resumable \
  evals.check_runner.SequentialRunnerTest.test_missing_worktree_never_reports_source_commit_as_observed_head \
  evals.check_runner.SequentialRunnerTest.test_resume_skips_completed_plan_and_continues_current_git_state \
  evals.check_runner.SequentialRunnerTest.test_concurrent_resume_does_not_launch_a_second_child \
  evals.check_runner.SequentialRunnerTest.test_timeout_kills_the_complete_process_group -v
```

Expected: PASS; no second child launches under the lock and timeout still cleans the process group.

- [ ] **Step 5: Commit the runner transition**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/check_runner.py \
  skills/kws-codex-plan-executor/evals/check_cli.py
git commit -m "refactor(cpe): adopt format two lifecycle"
```

### Task 4: Reconcile The Full Safety Suite With Format 2

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/canvas-direct-run-format2.json`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/readmates-comparative.json`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/gasstation-comparative.json`
- Review: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`

**Interfaces:**
- Consumes: all format-2 changes from Tasks 1-3.
- Produces: the unchanged process/state safety proof on the new contract.

- [ ] **Step 1: Run the complete deterministic gate once and inventory every failure**

Run:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
```

Expected: any failures are only stale format-1 fixture expectations or a real regression exposed by the migration; record the exact failing test names in the task report.

- [ ] **Step 2: Add sanitized provenance fixtures for the three source cases**

Create content-free JSON fixtures from the approved design appendices, not from copied transcripts or full results.

```bash
mkdir -p skills/kws-codex-plan-executor/evals/fixtures
```

`canvas-direct-run-format2.json` must declare `provenance="direct_cpe"`, the two sanitized run IDs `cpe-d783e575720a4f81` and `cpe-96f171c004ac49b8`, and these stable observations:

```json
{
  "schema_version": 1,
  "provenance": "direct_cpe",
  "sanitized": true,
  "observations": [
    {"signal": "slice_timeout", "occurrences": 5, "duration_seconds_each": 3600},
    {"signal": "head_advanced_between_timeouts", "plans": ["plan-01", "plan-02"]},
    {"signal": "repeated_environment_blocker", "capabilities": ["loopback_bind"]},
    {"signal": "envelope_only_retry", "reason_codes": ["unsafe_workflow_artifact", "invalid_result"]},
    {"signal": "worktree_local_receipt_lost_after_cleanup", "occurrences": 1}
  ]
}
```

`readmates-comparative.json` must declare `provenance="direct_codex_goal_comparative"`, `count_as_cpe_metrics=false`, plan bytes `92251`, plan lines `1745`, tasks `15`, duration minutes `643`, compactions `3`, root spawns `22`, root waits `785`, and full-context spawns `8`.

`gasstation-comparative.json` must declare `provenance="non_cpe_comparative"`, `count_as_cpe_metrics=false`, plan lines `2167`, tasks `8`, `existing_dirty_worktree=true`, and required capabilities `android_sdk`, `adb`, `avd`, `emulator`, and `writable_cache`.

Add `HistoricalEvidenceFixtureTests` that reject unknown provenance, assert comparative cases never enter CPE efficiency totals, and assert none of the three files contains `prompt`, `transcript`, `raw_log`, `source_diff`, `token`, `password`, or absolute home paths.

- [ ] **Step 3: Update stale fixtures without weakening assertions**

For every format-1 fixture, replace old status/recovery fields with the format-2 equivalents. Preserve the existing assertion intent. For example:

```python
self.assertEqual(persisted["format_version"], 2)
self.assertEqual(persisted["status"], "checkpointed")
self.assertEqual(persisted["plans"][0]["status"], "checkpointed")
self.assertEqual(persisted["plans"][0]["checkpoint_count"], 0)
```

Do not mock or delete these real-process cases:

- timeout process-group cleanup
- keyboard interrupt and SIGTERM cleanup
- coordinator-loss lock inheritance
- concurrent resume exclusion
- completed child with live descendant
- two-pipe drain
- bounded log compaction

- [ ] **Step 4: Run fixture, static syntax, and complete gates at the reconciled HEAD**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.HistoricalEvidenceFixtureTests -v
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
./evals/run.sh
```

Expected: both suites PASS, 0 failures, wall time below 15 seconds.

- [ ] **Step 5: Review Wave 0 against the design and commit fixture reconciliation**

Use `code_review.md` and verify:

- format-version-1 is rejected, not migrated;
- format-version-1 directories are not modified;
- current CLI inputs remain unchanged;
- process and Git safety coverage remains real where required;
- no compiler, optimization, capability, or evidence-reuse behavior leaked into Wave 0.

Then commit:

```bash
git add skills/kws-codex-plan-executor/evals/check_runner.py \
  skills/kws-codex-plan-executor/evals/check_cli.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/fixtures/canvas-direct-run-format2.json \
  skills/kws-codex-plan-executor/evals/fixtures/readmates-comparative.json \
  skills/kws-codex-plan-executor/evals/fixtures/gasstation-comparative.json
git commit -m "test(cpe): preserve safety on format two"
```

## Execution Order

- Sequential/shared-core tasks: Task 1 -> Task 2 -> Task 3 -> Task 4.
- Parallel-safe work: none; every task changes the shared state/result contract.
- Human approval gates: none; the design and no-legacy decision are approved.

## Final Verification

From `skills/kws-codex-plan-executor`:

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
```

Expected: all commands exit 0, all deterministic tests pass, and the eval gate remains below 15 seconds.

From repository root:

```bash
git diff --check
git status --short --branch --untracked-files=all
```

Expected: no whitespace errors; only intentional Wave 0 commits exist in the isolated implementation worktree.

## Review

Use `code_review.md`. Report findings first. Wave 0 closes only when format 2 is internally coherent and every existing low-level safety guarantee still has direct evidence.
