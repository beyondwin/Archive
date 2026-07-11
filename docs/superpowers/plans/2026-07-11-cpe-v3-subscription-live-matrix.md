# CPE v3 Subscription Live Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, verify, and run a reproducible 4x8 CPE v3 credentialed-model matrix through ChatGPT subscription authentication, then publish paid-live readiness only if the unchanged release gate passes.

**Architecture:** A checked-in compiler turns the fixed treatment/case registry into a digest-bound 32-slot manifest. A resumable runner executes 25 credentialed Codex calls and records seven Terra policy failures into an external hash-chained evidence ledger; deterministic fixture oracles generate the only accepted result records. The existing aggregator gains an attested subscription evidence mode while retaining the `$50` fail-closed boundary for any metered dollar mode.

**Tech Stack:** Python 3 standard library, Git CLI, app-bundled Codex CLI JSONL mode, JSON Schema, Bash, Bun repository checks, Graphify.

## Global Constraints

- Source design: `docs/superpowers/specs/2026-07-11-cpe-v3-subscription-live-matrix-design.md`.
- Work only in the isolated feature worktree; never edit the source checkout or local `main` directly.
- Apply `using-superpowers` and `test-driven-development` before implementation tasks.
- Use exactly `gpt-5.5/high`, `gpt-5.6-sol/high`, and `gpt-5.6-terra/high` as declared by the current matrix.
- Compile exactly 32 unique slots: 25 credentialed calls and seven Terra policy failures.
- Do not launch a model before Tasks 1-9 pass review and cost-free verification.
- Subscription execution must use ChatGPT authentication and a child environment without `OPENAI_API_KEY` or `OPENAI_ORG_ID`.
- Subscription mode has no `--budget-usd`; it records `cost_usd=null` and token usage instead.
- Do not purchase credits, enable auto top-up, switch to API-key billing, or change account settings.
- Preserve the `$50.00` hard cap for the existing metered-dollar aggregation mode.
- Keep raw live evidence under `~/.codex/evals/cpe-v3-live/`; never commit transcripts, credentials, raw stderr, or absolute home paths.
- Do not weaken release thresholds or update a baseline to hide a failure.
- Keep status `deterministic-ready; paid-live-pending` and `release_ready=false` until a current reviewed report has `release_gate.passed=true`.
- Bind final evidence to the exact implementation commit, manifest digest, and report digest.
- Use `apply_patch` for hand-edited files and preserve unrelated user changes.

## File Structure

### New production-eval modules

- `skills/kws-codex-plan-executor/evals/live_migration/__init__.py` exports the stable live-migration interfaces.
- `skills/kws-codex-plan-executor/evals/live_migration/contracts.py` owns dataclasses, canonical JSON, SHA-256, and schema validation helpers.
- `skills/kws-codex-plan-executor/evals/live_migration/compiler.py` validates the fixed matrix and compiles the immutable 32-slot manifest.
- `skills/kws-codex-plan-executor/evals/live_migration/fixtures.py` materializes one clean Git repository from a checked fixture contract.
- `skills/kws-codex-plan-executor/evals/live_migration/oracle.py` converts measured process, Git, schema, and case facts into one result record.
- `skills/kws-codex-plan-executor/evals/live_migration/ledger.py` owns append-only hash-chained events, atomic projection, slot evidence, and replay.
- `skills/kws-codex-plan-executor/evals/live_migration/runner.py` owns preflight, prompt rendering, Codex launch, timeout, result capture, and resume.
- `skills/kws-codex-plan-executor/evals/live_model_runner.py` is the public start/resume/dry-run CLI.

### New checked contracts

- `skills/kws-codex-plan-executor/evals/live-migration/worker-result-schema.json` constrains the model's final response.
- `skills/kws-codex-plan-executor/evals/live-migration/case-schema.json` constrains checked case contracts.
- `skills/kws-codex-plan-executor/evals/live-migration/fixtures/<case-id>/case.json` defines each case.
- `skills/kws-codex-plan-executor/evals/live-migration/fixtures/<case-id>/repo/` contains only model-visible seed files.
- `skills/kws-codex-plan-executor/evals/live-migration/fixtures/<case-id>/oracle/` contains hidden expected facts and deterministic checks.

### New deterministic checks

- `skills/kws-codex-plan-executor/evals/check_live_matrix_compiler.py` covers counts, digest binding, and policy classification.
- `skills/kws-codex-plan-executor/evals/check_live_matrix_fixtures.py` covers all eight materialized repositories and oracle isolation.
- `skills/kws-codex-plan-executor/evals/check_live_matrix_oracle.py` covers pass/fail result generation and subscription cost semantics.
- `skills/kws-codex-plan-executor/evals/check_live_matrix_ledger.py` covers hash replay, atomicity, resume, and corruption.
- `skills/kws-codex-plan-executor/evals/check_live_model_runner.py` uses a fake Codex binary to cover auth, launch, timeout, and no-duplicate resume.

### Existing files to modify

- `skills/kws-codex-plan-executor/evals/live_model_migration.py` accepts schema-v2 subscription evidence without weakening thresholds.
- `skills/kws-codex-plan-executor/evals/check_live_model_migration.py` adds subscription-mode and malformed evidence checks.
- `skills/kws-codex-plan-executor/evals/fake_codex.py` can emit live-runner JSONL cases and controlled faults.
- `skills/kws-codex-plan-executor/evals/maintained-checks.json` wires the new production-backed checks.
- `skills/kws-codex-plan-executor/evals/check_eval_harness.py` requires the new maintained checks.
- `skills/kws-codex-plan-executor/evals/live-migration/release-status.json` remains pending until the passing report task.
- `skills/kws-codex-plan-executor/SKILL.md`, `README.md`, `ARCHITECTURE.md`, `HISTORY.md`, and focused docs describe the runner and truthful release state.

---

### Task 1: Canonical Contracts And 32-Slot Compiler

```yaml waygent-task
id: T1
title: Canonical Contracts And 32-Slot Compiler
dependencies: []
spec_refs: ["S1.7.1", "S1.8", "S1.10", "S1.13"]
operator_reviewed: true
operator_decision: Approved repository-native live-migration implementation; credentialed model calls remain forbidden before T10.
file_claims:
  - skills/kws-codex-plan-executor/evals/live_migration/__init__.py
  - skills/kws-codex-plan-executor/evals/live_migration/contracts.py
  - skills/kws-codex-plan-executor/evals/live_migration/compiler.py
  - skills/kws-codex-plan-executor/evals/check_live_matrix_compiler.py
  - skills/kws-codex-plan-executor/evals/live-migration/cases.json
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_live_matrix_compiler.py
```

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/live_migration/__init__.py`
- Create: `skills/kws-codex-plan-executor/evals/live_migration/contracts.py`
- Create: `skills/kws-codex-plan-executor/evals/live_migration/compiler.py`
- Create: `skills/kws-codex-plan-executor/evals/check_live_matrix_compiler.py`
- Modify: `skills/kws-codex-plan-executor/evals/live-migration/cases.json`

**Interfaces:**
- Consumes: existing `matrix.json`, `cases.json`, `current-v2-prompt.txt`, and `templates/fresh-session-prompt.txt`.
- Produces: `sha256_bytes(data: bytes) -> str`, `canonical_json(payload: object) -> bytes`, `load_registry(eval_dir: Path) -> tuple[tuple[Treatment, ...], tuple[CaseRef, ...]]`, and `compile_manifest(eval_dir: Path, billing_mode: str, implementation_commit: str, created_at: str, run_id: str) -> dict[str, object]`.

- [ ] **Step 1: Write the failing compiler check**

Create `check_live_matrix_compiler.py` with a `main()` that imports
`compile_manifest`, compiles `chatgpt_subscription`, and asserts:

```python
manifest = compile_manifest(
    eval_dir=Path(__file__).resolve().parent,
    billing_mode="chatgpt_subscription",
    implementation_commit="a" * 40,
    created_at="2026-07-11T00:00:00Z",
    run_id="cpe-v3-live-test",
)
slots = manifest["slots"]
checks = {
    "schema": manifest["schema_version"] == "cpe-live-manifest.v2",
    "slot_count": len(slots) == 32,
    "unique_keys": len({(x["treatment_id"], x["case_id"]) for x in slots}) == 32,
    "credentialed_count": sum(x["outcome_kind"] == "credentialed_call" for x in slots) == 25,
    "policy_count": sum(x["outcome_kind"] == "expected_policy_failure" for x in slots) == 7,
    "subscription_has_no_dollar_budget": "budget_usd" not in manifest,
    "manifest_digest": len(manifest["manifest_sha256"]) == 64,
}
```

Mutate one treatment model, reorder one case, and change one prompt byte in
temporary copies; each mutation must raise `LiveMigrationContractError`.

- [ ] **Step 2: Run the check to verify RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_live_matrix_compiler.py
```

Expected: exit nonzero with `ModuleNotFoundError: No module named 'live_migration'`.

- [ ] **Step 3: Implement canonical types and JSON helpers**

In `contracts.py`, define immutable dataclasses and fail-closed helpers:

```python
@dataclass(frozen=True)
class Treatment:
    id: str
    model: str
    reasoning: str
    prompt: str

@dataclass(frozen=True)
class CaseRef:
    id: str
    slug: str

@dataclass(frozen=True, order=True)
class SlotKey:
    treatment_id: str
    case_id: str

class LiveMigrationContractError(ValueError):
    pass

def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
```

Change `cases.json` from string entries to exact ID/slug objects while
preserving order:

```json
{
  "schema_version": "2",
  "cases": [
    {"id": "single-file implementation", "slug": "single-file-implementation"},
    {"id": "cross-package implementation", "slug": "cross-package-implementation"},
    {"id": "root-cause repair", "slug": "root-cause-repair"},
    {"id": "defect review", "slug": "defect-review"},
    {"id": "failed-test interpretation", "slug": "failed-test-interpretation"},
    {"id": "security/migration block", "slug": "security-migration-block"},
    {"id": "resume/state repair", "slug": "resume-state-repair"},
    {"id": "large read-only exploration", "slug": "large-read-only-exploration"}
  ]
}
```

- [ ] **Step 4: Implement registry validation and manifest compilation**

In `compiler.py`, use exact constant tuples for treatments and cases. Compile
treatment-major/case-minor slots. Set `outcome_kind` to
`expected_policy_failure` only when treatment is `terra_scout` and case is not
`large read-only exploration`. Hash the manifest before adding
`manifest_sha256`:

```python
body = {
    "schema_version": "cpe-live-manifest.v2",
    "run_id": run_id,
    "created_at": created_at,
    "implementation_commit": implementation_commit,
    "billing_mode": billing_mode,
    "treatment_count": 4,
    "case_count": 8,
    "credentialed_call_count": 25,
    "expected_policy_failure_count": 7,
    "inputs": input_digests,
    "slots": slots,
}
return {**body, "manifest_sha256": sha256_bytes(canonical_json(body))}
```

Reject billing modes other than `chatgpt_subscription` and
`metered_dollar`. Require `budget_usd <= 50.0` only for `metered_dollar`.

- [ ] **Step 5: Run GREEN and existing migration check**

Run:

```bash
python3 evals/check_live_matrix_compiler.py
python3 evals/check_live_model_migration.py
python3 -m py_compile evals/live_migration/*.py evals/check_live_matrix_compiler.py
```

Expected: all commands exit 0 and the compiler check prints a JSON object with
all checks `true`.

- [ ] **Step 6: Commit Task 1**

```bash
git add skills/kws-codex-plan-executor/evals/live_migration \
  skills/kws-codex-plan-executor/evals/live-migration/cases.json \
  skills/kws-codex-plan-executor/evals/check_live_matrix_compiler.py
git commit -m "test(cpe): compile the live matrix contract"
```

---

### Task 2: Eight Deterministic Fixture Repositories

```yaml waygent-task
id: T2
title: Eight Deterministic Fixture Repositories
dependencies: ["T1"]
spec_refs: ["S1.7.2", "S1.13"]
operator_reviewed: true
operator_decision: Approved deterministic live-migration fixtures; credentialed model calls remain forbidden before T10.
file_claims:
  - skills/kws-codex-plan-executor/evals/live-migration/case-schema.json
  - skills/kws-codex-plan-executor/evals/live-migration/fixtures/**
  - skills/kws-codex-plan-executor/evals/live_migration/fixtures.py
  - skills/kws-codex-plan-executor/evals/check_live_matrix_fixtures.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_live_matrix_fixtures.py
```

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/live-migration/case-schema.json`
- Create: `skills/kws-codex-plan-executor/evals/live-migration/fixtures/*/case.json`
- Create: `skills/kws-codex-plan-executor/evals/live-migration/fixtures/*/repo/**`
- Create: `skills/kws-codex-plan-executor/evals/live-migration/fixtures/*/oracle/**`
- Create: `skills/kws-codex-plan-executor/evals/live_migration/fixtures.py`
- Create: `skills/kws-codex-plan-executor/evals/check_live_matrix_fixtures.py`

**Interfaces:**
- Consumes: `CaseRef`, fixture root, and a destination directory.
- Produces: `load_case(eval_dir: Path, case: CaseRef) -> dict[str, object]`, `materialize_fixture(eval_dir: Path, case: CaseRef, destination: Path) -> MaterializedFixture`, where `MaterializedFixture` contains `repo`, `oracle_dir`, `contract`, `seed_commit`, and `fixture_sha256`.

- [ ] **Step 1: Write the failing fixture check**

The check iterates all eight `CaseRef` values, materializes each into a
temporary directory, and asserts:

```python
assert fixture.repo.joinpath(".git").is_dir()
assert len(fixture.seed_commit) == 40
assert fixture.contract["case_id"] == case.id
assert fixture.contract["mode"] in {"write", "read_only"}
assert fixture.contract["acceptance_command"]
assert not fixture.repo.joinpath("oracle").exists()
assert not any(fixture.repo.rglob("expected*.json"))
assert subprocess.run(
    fixture.contract["baseline_command"],
    cwd=fixture.repo,
    shell=True,
    check=False,
).returncode == fixture.contract["baseline_exit_code"]
```

Also assert every fixture digest changes when a model-visible seed byte or
hidden oracle byte is mutated in a temporary copy.

- [ ] **Step 2: Run the check to verify RED**

Run `python3 evals/check_live_matrix_fixtures.py`.

Expected: exit nonzero because `live_migration.fixtures` does not exist.

- [ ] **Step 3: Add case schema and exact case contracts**

The schema requires `case_id`, `slug`, `mode`, `task`, `allowed_paths`,
`forbidden_paths`, `baseline_command`, `baseline_exit_code`,
`acceptance_command`, `oracle_kind`, and `expected_policy`.

Use these exact outcomes:

| Slug | Mode | Baseline | Acceptance | Oracle kind |
| --- | --- | --- | --- | --- |
| `single-file-implementation` | write | unit test exits 1 | unit test exits 0 | `command_and_diff` |
| `cross-package-implementation` | write | integration test exits 1 | integration test exits 0 | `command_and_diff` |
| `root-cause-repair` | write | state isolation test exits 1 | full test exits 0 | `command_and_diff` |
| `defect-review` | read_only | seeded review detector exits 1 | Git clean | `finding_ids` |
| `failed-test-interpretation` | read_only | deterministic test exits 1 | Git clean | `fact_ids` |
| `security-migration-block` | read_only | destructive request fixture exists | Git clean | `block_ids` |
| `resume-state-repair` | write | public validator exits 1 | public validator exits 0 | `command_and_diff` |
| `large-read-only-exploration` | read_only | fact index check exits 0 | Git clean | `fact_ids` |

All repository programs use Python standard library only. Put hidden required
IDs in `oracle/expected.json`; never copy that directory into the model-visible
repository.

- [ ] **Step 4: Implement fixture loading and materialization**

`materialize_fixture` must copy only `repo/`, initialize Git, configure the
fixture identity, commit the seed, run the baseline command, and return the
combined digest of `case.json`, all `repo/` bytes, and all `oracle/` bytes.
Reject symlinks, absolute paths, `..` segments, executable acceptance strings
containing network clients, and a baseline exit code mismatch.

Define the returned type exactly:

```python
@dataclass(frozen=True)
class MaterializedFixture:
    repo: Path
    oracle_dir: Path
    contract: dict[str, object]
    seed_commit: str
    fixture_sha256: str
```

- [ ] **Step 5: Run fixture GREEN**

Run:

```bash
python3 evals/check_live_matrix_fixtures.py
python3 -m py_compile evals/live_migration/fixtures.py evals/check_live_matrix_fixtures.py
git diff --check
```

Expected: eight fixtures pass, hidden oracle leakage count is zero, and all
commands exit 0.

- [ ] **Step 6: Commit Task 2**

```bash
git add skills/kws-codex-plan-executor/evals/live-migration/case-schema.json \
  skills/kws-codex-plan-executor/evals/live-migration/fixtures \
  skills/kws-codex-plan-executor/evals/live_migration/fixtures.py \
  skills/kws-codex-plan-executor/evals/check_live_matrix_fixtures.py
git commit -m "test(cpe): add deterministic live matrix fixtures"
```

---

### Task 3: Provider-Independent Deterministic Oracle

```yaml waygent-task
id: T3
title: Provider-Independent Deterministic Oracle
dependencies: ["T2"]
spec_refs: ["S1.7.4", "S1.10", "S1.13"]
operator_reviewed: true
operator_decision: Approved provider-independent live-migration oracle; quality thresholds must remain unchanged.
file_claims:
  - skills/kws-codex-plan-executor/evals/live-migration/worker-result-schema.json
  - skills/kws-codex-plan-executor/evals/live_migration/oracle.py
  - skills/kws-codex-plan-executor/evals/check_live_matrix_oracle.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_live_matrix_oracle.py
```

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/live-migration/worker-result-schema.json`
- Create: `skills/kws-codex-plan-executor/evals/live_migration/oracle.py`
- Create: `skills/kws-codex-plan-executor/evals/check_live_matrix_oracle.py`

**Interfaces:**
- Consumes: `MaterializedFixture`, slot manifest entry, Codex process record, parsed JSONL events, final output, before/after Git facts, and oracle files.
- Produces: `evaluate_slot(slot: dict[str, object], fixture: MaterializedFixture, process: ProcessEvidence, output: dict[str, object], events: list[dict[str, object]]) -> dict[str, object]` and `policy_failure_result(slot: dict[str, object], manifest_sha256: str) -> dict[str, object]`.

- [ ] **Step 1: Write the failing oracle check**

Build one passing and one failing `ProcessEvidence` for every `oracle_kind`.
Assert the passing records use schema `cpe-live-result.v2`, subscription records
contain `cost_usd is None`, forbidden writes set `critical_regression=True`, and
missing model or usage events set `evidence_complete=False`.

Assert `policy_failure_result` rejects a non-Terra slot and produces no token,
latency, or cost fields for a valid Terra-ineligible slot.

- [ ] **Step 2: Run the check to verify RED**

Run `python3 evals/check_live_matrix_oracle.py`.

Expected: exit nonzero because `live_migration.oracle` does not exist.

- [ ] **Step 3: Define the model output schema**

Require this closed object shape:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["status", "summary", "finding_ids", "fact_ids", "block_ids", "changed_files"],
  "properties": {
    "status": {"enum": ["completed", "blocked"]},
    "summary": {"type": "string", "minLength": 1},
    "finding_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "fact_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "block_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "changed_files": {"type": "array", "items": {"type": "string"}, "uniqueItems": true}
  }
}
```

- [ ] **Step 4: Implement measured scoring**

Define `ProcessEvidence` as:

```python
@dataclass(frozen=True)
class ProcessEvidence:
    exit_code: int
    latency_ms: int
    timed_out: bool
    retry_count: int
    tracked_diff: str
    cached_diff: str
    untracked_files: tuple[str, ...]
    changed_files: tuple[str, ...]
    acceptance_exit_code: int
    model: str | None
    reasoning_effort: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    source_drift: bool
    oracle_drift: bool
```

Compute:

```python
task_completed = process.exit_code == 0 and acceptance_passed and output_valid
first_pass_success = task_completed and process.retry_count == 0
review_accurate = normalized_ids == required_ids
evidence_complete = all((model_attested, usage_attested, git_evidence, output_valid))
critical_regression = forbidden_write or source_drift or oracle_drift
```

For read-only cases, require clean tracked, cached, and untracked status. For
write cases, require every changed path to be allowed and every forbidden path
to remain unchanged. Use exact set equality for finding/fact/block IDs.

- [ ] **Step 5: Run oracle GREEN**

Run:

```bash
python3 evals/check_live_matrix_oracle.py
python3 -m py_compile evals/live_migration/oracle.py evals/check_live_matrix_oracle.py
```

Expected: all oracle checks print `true` and exit 0.

- [ ] **Step 6: Commit Task 3**

```bash
git add skills/kws-codex-plan-executor/evals/live-migration/worker-result-schema.json \
  skills/kws-codex-plan-executor/evals/live_migration/oracle.py \
  skills/kws-codex-plan-executor/evals/check_live_matrix_oracle.py
git commit -m "test(cpe): score live slots with deterministic oracles"
```

---

### Task 4: Immutable Evidence Ledger And Replay

```yaml waygent-task
id: T4
title: Immutable Evidence Ledger And Replay
dependencies: ["T3"]
spec_refs: ["S1.7.5", "S1.12", "S1.13"]
operator_reviewed: true
operator_decision: Approved external live-migration evidence ledger with hash-chain and atomic projection boundaries.
file_claims:
  - skills/kws-codex-plan-executor/evals/live_migration/ledger.py
  - skills/kws-codex-plan-executor/evals/check_live_matrix_ledger.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_live_matrix_ledger.py
```

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/live_migration/ledger.py`
- Create: `skills/kws-codex-plan-executor/evals/check_live_matrix_ledger.py`

**Interfaces:**
- Consumes: immutable manifest and per-slot evidence payloads.
- Produces: `create_run(root: Path, manifest: dict[str, object]) -> LiveRun`, `append_event(run: LiveRun, event_type: str, payload: dict[str, object]) -> dict[str, object]`, `commit_slot(run: LiveRun, key: SlotKey, files: dict[str, bytes], result: dict[str, object]) -> None`, and `replay_run(run_dir: Path) -> dict[str, object]`.

- [ ] **Step 1: Write the failing ledger check**

Create a run in a temporary root, append `run_started`, commit one slot, replay,
and assert sequence, previous hash, event hash, slot digest, and projection.
Then mutate one event byte, one slot file, manifest content, and state content;
each mutation must be rejected or rebuilt from valid source evidence.

Simulate interruption by leaving `slots/.partial-*`; replay must ignore it and
report the slot missing.

- [ ] **Step 2: Run the check to verify RED**

Run `python3 evals/check_live_matrix_ledger.py`.

Expected: exit nonzero because `live_migration.ledger` does not exist.

- [ ] **Step 3: Implement append-only events and atomic projection**

Use this event envelope:

```python
body = {
    "schema_version": "cpe-live-event.v1",
    "sequence": previous_sequence + 1,
    "timestamp": timestamp,
    "type": event_type,
    "payload": payload,
    "previous_sha256": previous_sha256,
}
event = {**body, "event_sha256": sha256_bytes(canonical_json(body))}
```

Define the stable ledger handle:

```python
@dataclass(frozen=True)
class LiveRun:
    run_dir: Path
    manifest: dict[str, object]
    manifest_sha256: str
```

Append canonical bytes, flush, and `os.fsync`. Write state to a sibling temp
file, flush and fsync, then use `os.replace`. Never edit an existing slot
directory. `commit_slot` writes a partial directory, fsyncs files, creates a
digest index, atomically renames it, then appends `slot_completed`.

- [ ] **Step 4: Implement replay validation**

Replay verifies manifest digest first, then strict event sequence and hash
chain, then every completed slot index and result digest. Derive
`pending_slots`, `completed_slots`, `failed_slots`, `active_slot`, and
`lifecycle_outcome`. Treat state mismatch as rebuildable projection drift; treat
manifest, event, or slot mismatch as blocking integrity drift.

- [ ] **Step 5: Run ledger GREEN**

Run:

```bash
python3 evals/check_live_matrix_ledger.py
python3 -m py_compile evals/live_migration/ledger.py evals/check_live_matrix_ledger.py
```

Expected: replay, mutation, partial-write, and state-rebuild checks pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add skills/kws-codex-plan-executor/evals/live_migration/ledger.py \
  skills/kws-codex-plan-executor/evals/check_live_matrix_ledger.py
git commit -m "feat(cpe): persist live matrix evidence safely"
```

---

### Task 5: ChatGPT Subscription Runner And Prompt Isolation

```yaml waygent-task
id: T5
title: ChatGPT Subscription Runner And Prompt Isolation
dependencies: ["T4"]
spec_refs: ["S1.7.3", "S1.8.1", "S1.9", "S1.12"]
operator_reviewed: true
operator_decision: Approved ChatGPT-authenticated live-migration runner implementation; real model launch remains forbidden before T10.
file_claims:
  - skills/kws-codex-plan-executor/evals/live_migration/runner.py
  - skills/kws-codex-plan-executor/evals/live_model_runner.py
  - skills/kws-codex-plan-executor/evals/check_live_model_runner.py
  - skills/kws-codex-plan-executor/evals/fake_codex.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_live_model_runner.py
```

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/live_migration/runner.py`
- Create: `skills/kws-codex-plan-executor/evals/live_model_runner.py`
- Create: `skills/kws-codex-plan-executor/evals/check_live_model_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`

**Interfaces:**
- Consumes: compiled manifest, fixtures, ledger, deterministic oracle, Codex binary path, and evidence root.
- Produces: `preflight_codex(codex_bin: Path, env: Mapping[str, str]) -> CodexAttestation`, `render_prompt(slot: dict[str, object], fixture: MaterializedFixture, eval_dir: Path) -> str`, `run_slot(context: RunContext, slot: dict[str, object]) -> dict[str, object]`, and CLI commands `dry-run`, `start`, and `resume`.

- [ ] **Step 1: Extend fake Codex and write the failing runner check**

Add fake commands for `login status`, `debug models`, and `exec --json`. The
fake `exec` reads a case payload, optionally writes allowed files, writes the
schema-valid final output, and emits:

```json
{"type":"thread.started","model":"gpt-5.6-sol","reasoning_effort":"high"}
{"type":"turn.started"}
{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":25,"output_tokens":20,"reasoning_output_tokens":5}}
```

`check_live_model_runner.py` must cover ChatGPT login success, API-key env
stripping, wrong login rejection, missing model rejection, exact launcher
arguments, hidden oracle exclusion, and one successful slot.

- [ ] **Step 2: Run the runner check to verify RED**

Run `python3 evals/check_live_model_runner.py`.

Expected: exit nonzero because `live_model_runner.py` and runner interfaces do
not exist.

- [ ] **Step 3: Implement preflight and child environment**

Resolve the CLI from explicit `--codex-bin`, defaulting on macOS to
`/Applications/ChatGPT.app/Contents/Resources/codex`. Run `login status` and
require the exact phrase `Logged in using ChatGPT`. Run `debug models`, parse
JSON, and require every matrix model with `high` support.

Create the child environment without copying or relocating auth material. Reuse
the preflight-attested home and rely on `--ephemeral` for session isolation:

```python
child_env = dict(os.environ)
for name in ("OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
    child_env.pop(name, None)
child_env["CODEX_HOME"] = str(attestation.codex_home)
```

Define preflight and execution context types:

```python
@dataclass(frozen=True)
class CodexAttestation:
    binary: Path
    codex_home: Path
    version: str
    login_kind: str
    catalog_sha256: str
    models: tuple[str, ...]

@dataclass(frozen=True)
class RunContext:
    run: LiveRun
    eval_dir: Path
    codex: CodexAttestation
    child_env: dict[str, str]
    slot_timeout_seconds: int
    retry_failed: bool
```

Record only booleans and digests for removed variables; never record values.
Reject an empty or unauthenticated `CODEX_HOME`; never copy `auth.json`, keychain
material, or another credential artifact into a slot directory.

- [ ] **Step 4: Implement prompt rendering and Codex launch**

Render historical prompt bytes unchanged for `gpt55_current` and
`sol_current`. Render the stable v3 prefix plus fixture-specific hot tail for
`sol_v3`. Generate a read-only scout prefix for Terra. Append the same case
task, allowed/forbidden paths, acceptance command name, and output contract to
all eligible treatments. Never include `oracle_dir` or expected IDs.

Invoke:

```python
argv = [
    str(codex_bin), "exec", "--json", "--ephemeral",
    "--model", str(slot["model"]),
    "-c", 'model_reasoning_effort="high"',
    "--sandbox", "workspace-write" if fixture.contract["mode"] == "write" else "read-only",
    "-C", str(fixture.repo),
    "--output-schema", str(worker_schema),
    "--output-last-message", str(last_message),
    "-",
]
```

Use `start_new_session=True`, send the prompt on stdin, capture stdout JSONL and
stderr separately, and enforce the configured timeout.

- [ ] **Step 5: Implement public CLI without live-by-default behavior**

The CLI requires explicit subcommands:

```text
live_model_runner.py dry-run --billing-mode chatgpt_subscription --output FILE
live_model_runner.py start --billing-mode chatgpt_subscription --confirm-subscription-usage --evidence-root DIR
live_model_runner.py resume --run-dir DIR --confirm-subscription-usage [--retry-failed]
```

`dry-run` never calls preflight or Codex. `start` requires
`--confirm-subscription-usage`; it creates the immutable run then processes
slots sequentially. Policy-failure slots are committed without calling Codex.
Print one final JSON object containing run ID, run directory, counts, status,
and next action.

- [ ] **Step 6: Run runner GREEN**

Run:

```bash
python3 evals/check_live_model_runner.py
python3 evals/live_model_runner.py dry-run \
  --billing-mode chatgpt_subscription \
  --output /tmp/cpe-v3-subscription-live-plan.json
python3 -m py_compile evals/live_model_runner.py evals/live_migration/*.py evals/fake_codex.py
```

Expected: fake-run checks pass; dry output reports 32 slots, 25 credentialed
calls, seven policy failures, and no `budget_usd`.

- [ ] **Step 7: Commit Task 5**

```bash
git add skills/kws-codex-plan-executor/evals/live_migration/runner.py \
  skills/kws-codex-plan-executor/evals/live_model_runner.py \
  skills/kws-codex-plan-executor/evals/check_live_model_runner.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py
git commit -m "feat(cpe): run the live matrix with ChatGPT auth"
```

---

### Task 6: Timeout, Limit Stop, And No-Duplicate Resume

```yaml waygent-task
id: T6
title: Timeout, Limit Stop, And No-Duplicate Resume
dependencies: ["T5"]
spec_refs: ["S1.7.6", "S1.12", "S1.13"]
operator_reviewed: true
operator_decision: Approved resumable live-migration recovery and timeout behavior; evidence deletion and silent retries remain forbidden.
file_claims:
  - skills/kws-codex-plan-executor/evals/live_migration/runner.py
  - skills/kws-codex-plan-executor/evals/live_model_runner.py
  - skills/kws-codex-plan-executor/evals/fake_codex.py
  - skills/kws-codex-plan-executor/evals/check_live_model_runner.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_live_model_runner.py
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/live_migration/runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/live_model_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_live_model_runner.py`

**Interfaces:**
- Consumes: Task 5 runner and Task 4 replay state.
- Produces: `terminate_process_group(process: subprocess.Popen[bytes], grace_seconds: float) -> None`, `classify_stop(exit_code: int, stderr: str) -> str`, and deterministic resume selection.

- [ ] **Step 1: Add RED fault cases**

Add fake behaviors for sleep past timeout, exit 75 with `usage limit reached`,
malformed JSONL, malformed last output, missing usage, wrong model attestation,
forbidden write, and mid-slot interruption.

Assert timeout kills the process group, limit stop records
`subscription_limit_reached`, resume skips every completed slot, failed slots
require `--retry-failed`, and a second resume never duplicates a slot key.

- [ ] **Step 2: Run the targeted check to verify RED**

Run `python3 evals/check_live_model_runner.py`.

Expected: newly added timeout, limit, and resume assertions fail.

- [ ] **Step 3: Implement stop classification and process cleanup**

On timeout, send `SIGTERM` to the child process group, wait the configured
grace period, then send `SIGKILL` only if still alive. Classify stderr using a
small exact pattern set:

```python
LIMIT_PATTERNS = (
    "usage limit reached",
    "rate limit reached",
    "additional credits required",
    "billing required",
)
```

Do not classify authentication, schema, fixture, or Git errors as resumable
subscription limits.

- [ ] **Step 4: Implement replay-driven resume**

Select pending slots from `replay_run`. When `--retry-failed` is absent, stop
before a failed slot and print its key. When present, append `slot_retry_started`
with the prior attempt digest and create a new attempt directory. Keep only one
accepted result per slot; the result index points to the newest successful
attempt and preserves older failed evidence.

- [ ] **Step 5: Run fault GREEN**

Run:

```bash
python3 evals/check_live_model_runner.py
python3 evals/check_live_matrix_ledger.py
python3 -m py_compile evals/live_model_runner.py evals/live_migration/*.py
```

Expected: all interruption, replay, and no-duplicate checks pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add skills/kws-codex-plan-executor/evals/live_migration/runner.py \
  skills/kws-codex-plan-executor/evals/live_model_runner.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_live_model_runner.py
git commit -m "fix(cpe): make live matrix runs resumable"
```

---

### Task 7: Subscription Evidence Aggregation And Unchanged Quality Gate

```yaml waygent-task
id: T7
title: Subscription Evidence Aggregation And Unchanged Quality Gate
dependencies: ["T6"]
spec_refs: ["S1.8", "S1.10", "S1.11"]
operator_reviewed: true
operator_decision: Approved subscription evidence aggregation while preserving the metered-dollar hard cap and unchanged quality thresholds.
file_claims:
  - skills/kws-codex-plan-executor/evals/live_model_migration.py
  - skills/kws-codex-plan-executor/evals/check_live_model_migration.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_live_model_migration.py
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/live_model_migration.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_live_model_migration.py`

**Interfaces:**
- Consumes: schema-v1 metered result fixtures and schema-v2 ledger-generated subscription results.
- Produces: `validate_result_record(record: dict[str, object], expected_policy: bool, evidence_source: str) -> None`, nullable aggregate `cost_usd`, token aggregates, and the existing `release_gate` thresholds unchanged.

- [ ] **Step 1: Add RED subscription aggregation tests**

Generate 32 schema-v2 records with `billing_mode=chatgpt_subscription`,
`cost_usd=None`, unique evidence digests, 25 credentialed outcomes, and seven
policy outcomes. Assert aggregation passes with `metrics.*.cost_usd is None`.

Add mutations for a numeric subscription cost, missing digest, duplicate key,
policy record with usage, credentialed record without usage, synthetic evidence
source, and mixed billing modes; each must fail.

Snapshot the existing threshold object and assert exact equality:

```python
EXPECTED_THRESHOLDS = {
    "critical_regressions": 0,
    "task_success_regression_allowed": False,
    "core_model_attestation_rate": 1.0,
    "worktree_isolation_rate": 1.0,
    "drift_free_rate": 1.0,
    "minimum_context_token_reduction": 0.25,
}
```

- [ ] **Step 2: Run the migration check to verify RED**

Run `python3 evals/check_live_model_migration.py`.

Expected: subscription records fail because the current `as_number` rejects
`None` cost values.

- [ ] **Step 3: Implement evidence-source-specific validation**

Keep the current `--budget-usd` and `$50` behavior for
`evidence_source=metered_injected_results`. Add a subscription aggregation path
that requires:

```python
record["schema_version"] == "cpe-live-result.v2"
record["billing_mode"] == "chatgpt_subscription"
record["cost_usd"] is None
len(record["evidence_sha256"]) == 64
```

Sum context, cache, output, and latency. Set treatment `cost_usd=None` for the
subscription report. Exclude expected policy failures from all metric
denominators and usage totals.

- [ ] **Step 4: Update CLI aggregation modes**

Support:

```text
--billing-mode metered_dollar --confirm-live-cost --budget-usd 50 --results-json FILE
--billing-mode chatgpt_subscription --confirm-subscription-usage --results-json FILE
```

Reject cross-mode flags and keep dry-run provider-free. Subscription mode must
not accept `--budget-usd`; metered mode must still reject `50.01`.

- [ ] **Step 5: Run GREEN and mutation checks**

Run:

```bash
python3 evals/check_live_model_migration.py
python3 evals/check_live_matrix_oracle.py
python3 -m py_compile evals/live_model_migration.py evals/check_live_model_migration.py
```

Expected: legacy and subscription paths pass; all malformed evidence mutations
fail closed; threshold snapshot remains exact.

- [ ] **Step 6: Commit Task 7**

```bash
git add skills/kws-codex-plan-executor/evals/live_model_migration.py \
  skills/kws-codex-plan-executor/evals/check_live_model_migration.py
git commit -m "feat(cpe): aggregate subscription live evidence"
```

---

### Task 8: Maintained Eval Wiring And Public Dry-Run Integration

```yaml waygent-task
id: T8
title: Maintained Eval Wiring And Public Dry-Run Integration
dependencies: ["T7"]
spec_refs: ["S1.11", "S1.13"]
file_claims:
  - skills/kws-codex-plan-executor/evals/maintained-checks.json
  - skills/kws-codex-plan-executor/evals/check_eval_harness.py
  - skills/kws-codex-plan-executor/evals/run.sh
  - skills/kws-codex-plan-executor/evals/check_release_contract.py
acceptance:
  - cd skills/kws-codex-plan-executor && ./evals/run.sh
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/maintained-checks.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Modify: `skills/kws-codex-plan-executor/evals/check_release_contract.py`

**Interfaces:**
- Consumes: Tasks 1-7 deterministic check entrypoints.
- Produces: maintained inventory coverage and a release contract that rejects incomplete, stale, synthetic, or unbound live reports.

- [ ] **Step 1: Add RED inventory requirements**

Add these names to `REQUIRED_MAINTAINED` in `check_eval_harness.py` before
editing inventory:

```python
"check_live_matrix_compiler.py",
"check_live_matrix_fixtures.py",
"check_live_matrix_oracle.py",
"check_live_matrix_ledger.py",
"check_live_model_runner.py",
```

Update `check_release_contract.py` tests to require a passing live report's
implementation commit and report digest to match release-status and the latest
verification block.

- [ ] **Step 2: Run RED**

Run:

```bash
python3 evals/check_eval_harness.py --inventory evals/maintained-checks.json
python3 evals/check_release_contract.py
```

Expected: inventory fails with five omitted checks; release contract test fails
because current pending metadata has no passing live evidence fields.

- [ ] **Step 3: Wire maintained checks with production entrypoints**

Append five inventory objects. Use `live_migration.compiler`,
`live_migration.fixtures`, `live_migration.oracle`, `live_migration.ledger`, and
`live_migration.runner` as `production_entrypoint` values. Give each a concrete
mutation assertion matching its check.

Keep `run.sh` baseline field `paid_execution=skipped_not_approved` while status
is pending; change it only in Task 11 after current paid evidence passes.

- [ ] **Step 4: Make release contract conditional on truthful state**

When `release_ready=false`, require paid evidence status `pending` and no live
report digest. When `release_ready=true`, require exact status
`deterministic-ready; paid-live-verified`, evidence status `passed`, billing mode
`chatgpt_subscription`, current version, a 40-character implementation commit,
64-character manifest/report digests, and matching latest verification fields.

- [ ] **Step 5: Run integration GREEN**

Run:

```bash
python3 evals/check_eval_harness.py --inventory evals/maintained-checks.json
python3 evals/check_release_contract.py
./evals/run.sh
```

Expected: all maintained checks and the full cost-free harness pass; no real
Codex model is invoked.

- [ ] **Step 6: Commit Task 8**

```bash
git add skills/kws-codex-plan-executor/evals/maintained-checks.json \
  skills/kws-codex-plan-executor/evals/check_eval_harness.py \
  skills/kws-codex-plan-executor/evals/run.sh \
  skills/kws-codex-plan-executor/evals/check_release_contract.py
git commit -m "test(cpe): maintain subscription live runner coverage"
```

---

### Task 9: Pending Runner Release Docs, Version, Baseline, And Independent Review

```yaml waygent-task
id: T9
title: Pending Runner Release Docs Version Baseline And Independent Review
dependencies: ["T8"]
spec_refs: ["S1.11", "S1.14"]
file_claims:
  - skills/kws-codex-plan-executor/SKILL.md
  - skills/kws-codex-plan-executor/README.md
  - skills/kws-codex-plan-executor/ARCHITECTURE.md
  - skills/kws-codex-plan-executor/HISTORY.md
  - skills/kws-codex-plan-executor/docs/evals-and-verification.md
  - skills/kws-codex-plan-executor/docs/release-process.md
  - skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md
  - skills/kws-codex-plan-executor/docs/decisions.md
  - skills/kws-codex-plan-executor/docs/verification-log.md
  - skills/kws-codex-plan-executor/evals/baselines/v3.0.1.json
  - skills/kws-codex-plan-executor/evals/baselines/v3.1.0.json
  - graphify-out/**
acceptance:
  - cd skills/kws-codex-plan-executor && ./evals/run.sh && python3 evals/check_release_contract.py && python3 evals/check_docs_contract.py
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/release-process.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/decisions.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Create: `skills/kws-codex-plan-executor/evals/baselines/v3.1.0.json`
- Delete: `skills/kws-codex-plan-executor/evals/baselines/v3.0.1.json`

**Interfaces:**
- Consumes: reviewed Tasks 1-8 and current cost-free output.
- Produces: version `3.1.0` with status still `deterministic-ready; paid-live-pending`, truthful subscription runner documentation, and one current maintained baseline.

- [ ] **Step 1: Update version and pending documentation**

Bump `metadata.version` to `3.1.0` because the live runner is a compatible
optional evidence surface. Keep `metadata.release_status` unchanged. Document
the exact dry-run/start/resume commands, 25/7 split, external evidence path,
nullable cost, subscription account observability limitation, no API keys, and
metered `$50` boundary.

Add a `3.1.0` HISTORY entry marked
`deterministic-ready; paid-live-pending`. State that code availability does not
equal a passing credentialed report.

- [ ] **Step 2: Run current cost-free verification and update baseline**

Run:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh --update-baseline
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py evals/live_migration/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
python3 scripts/cpe.py --help
cd ../..
bun run check
git diff --check
```

Expected: all commands pass, exactly one `v3.1.0.json` baseline exists, and
paid live remains pending.

- [ ] **Step 3: Append the pre-live verification entry**

Record date/timezone, branch, current implementation commit candidate, every
command and exit code, maintained passing count, Bun passing count, Graphify
pending until after structure update, `paid_live=approved_not_started`, and
residual risk `credentialed matrix has not run`.

- [ ] **Step 4: Refresh Graphify in a graph-only commit**

Run:

```bash
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran --output /tmp/cpe-v3-live-runner-graphify.json
git diff --check
```

Commit product and docs first:

```bash
git add skills/kws-codex-plan-executor
git commit -m "release(cpe): prepare subscription live runner"
```

Then commit only Graphify output:

```bash
git add graphify-out
git commit -m "docs(graphify): map subscription live runner"
```

- [ ] **Step 5: Run independent spec and code review**

Use `code_review.md` against the design, this plan, and `main...HEAD`. Require
separate findings for spec compliance and code quality. Resolve every P0/P1/P2
finding with a failing regression check, minimal fix, fresh targeted tests, and
review again. Do not start live execution with an unresolved blocking finding.

- [ ] **Step 6: Re-run the full pre-live matrix on the reviewed commit**

Run the same commands from Step 2 plus Graphify freshness. Record the exact
reviewed implementation commit. Expected: clean tracked tree, all gates green,
status pending, and no model calls yet.

---

### Task 10: Execute And Resume The Credentialed Subscription Matrix

```yaml waygent-task
id: T10
title: Execute And Resume The Credentialed Subscription Matrix
dependencies: ["T9"]
spec_refs: ["S1.3", "S1.7.3", "S1.7.6", "S1.8.1", "S1.15"]
file_claims:
  - skills/kws-codex-plan-executor/evals/live_model_runner.py
  - skills/kws-codex-plan-executor/evals/live_model_migration.py
  - skills/kws-codex-plan-executor/evals/live-migration/release-status.json
operator_reviewed: true
operator_decision: Approved for ChatGPT subscription live execution without the artificial dollar estimate; API-key billing, credit purchase, and auto-top-up changes remain forbidden.
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/live_model_runner.py dry-run --billing-mode chatgpt_subscription --output /tmp/cpe-v3-subscription-live-plan.json
```

**Files:**
- External write: `~/.codex/evals/cpe-v3-live/<run_id>/**`
- No tracked source edit until the report is final and reviewed.

**Interfaces:**
- Consumes: exact reviewed Task 9 implementation commit and ChatGPT-authenticated app-bundled Codex CLI.
- Produces: immutable manifest, 32 complete slot results, sanitized `results.json`, and `report.json` with `release_gate.passed` or exact failures.

- [ ] **Step 1: Generate and inspect the final dry plan**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/live_model_runner.py dry-run \
  --billing-mode chatgpt_subscription \
  --implementation-commit "$(git rev-parse HEAD)" \
  --output /tmp/cpe-v3-subscription-live-plan.json
```

Verify with `jq` that treatment count is 4, case count is 8, slot count is 32,
credentialed call count is 25, policy count is seven, billing mode is
`chatgpt_subscription`, and `budget_usd` is absent.

- [ ] **Step 2: Verify account and binary preflight without a model call**

Run:

```bash
/Applications/ChatGPT.app/Contents/Resources/codex login status
/Applications/ChatGPT.app/Contents/Resources/codex debug models > /tmp/cpe-v3-model-catalog.json
jq -e '[.models[].slug] | contains(["gpt-5.5","gpt-5.6-sol","gpt-5.6-terra"])' \
  /tmp/cpe-v3-model-catalog.json
```

Expected: ChatGPT login is reported and `jq` exits 0. Do not print environment
variable values or account billing data.

- [ ] **Step 3: Start the approved subscription run**

Run:

```bash
env -u OPENAI_API_KEY -u OPENAI_ORG_ID -u OPENAI_PROJECT_ID \
python3 evals/live_model_runner.py start \
  --billing-mode chatgpt_subscription \
  --confirm-subscription-usage \
  --codex-bin /Applications/ChatGPT.app/Contents/Resources/codex \
  --evidence-root "$HOME/.codex/evals/cpe-v3-live" \
  --slot-timeout-seconds 900
```

Expected: the command prints the run ID and progresses sequentially. Preserve
the run directory from the final JSON output.

- [ ] **Step 4: Resume until the exact matrix reaches a terminal state**

If the process is interrupted or reports `subscription_limit_reached`, keep
the run directory unchanged and later run:

```bash
env -u OPENAI_API_KEY -u OPENAI_ORG_ID -u OPENAI_PROJECT_ID \
python3 evals/live_model_runner.py resume \
  --run-dir "$RUN_DIR" \
  --confirm-subscription-usage \
  --codex-bin /Applications/ChatGPT.app/Contents/Resources/codex \
  --slot-timeout-seconds 900
```

Use `--retry-failed` only after inspecting the failed slot's oracle and error
classification. Never delete evidence or restart a new run to hide a failed
slot.

- [ ] **Step 5: Aggregate the completed evidence**

When all 32 slots are complete, run:

```bash
python3 evals/live_model_migration.py \
  --billing-mode chatgpt_subscription \
  --confirm-subscription-usage \
  --results-json "$RUN_DIR/results.json" \
  --output "$RUN_DIR/report.json"
```

Expected: report generation succeeds. A nonzero exit with a valid report is a
real quality-gate failure, not a harness failure.

- [ ] **Step 6: Validate report and preserve exact outcome**

Run a local validation script that asserts manifest/result/report digests,
implementation commit, 32 unique keys, 25 credentialed calls, seven policy
failures, model attestations, and nullable subscription cost. Record
`release_gate.passed`, failures, metrics, and SHA-256 digests. Do not edit the
report.

If `release_gate.passed=false`, stop release closeout, append a truthful failure
entry in Task 11, retain pending status, and plan fixes from the measured
failure. Do not change thresholds or result fields.

---

### Task 11: Evidence Review, Release Closeout, And Main Integration

```yaml waygent-task
id: T11
title: Evidence Review Release Closeout And Main Integration
dependencies: ["T10"]
spec_refs: ["S1.11", "S1.14", "S1.15"]
operator_reviewed: true
operator_decision: Approved evidence-driven release closeout and local main integration only after every deterministic and credentialed gate passes.
file_claims:
  - skills/kws-codex-plan-executor/evals/live-migration/release-status.json
  - skills/kws-codex-plan-executor/SKILL.md
  - skills/kws-codex-plan-executor/README.md
  - skills/kws-codex-plan-executor/HISTORY.md
  - skills/kws-codex-plan-executor/docs/evals-and-verification.md
  - skills/kws-codex-plan-executor/docs/release-process.md
  - skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md
  - skills/kws-codex-plan-executor/docs/decisions.md
  - skills/kws-codex-plan-executor/docs/verification-log.md
  - skills/kws-codex-plan-executor/evals/run.sh
  - skills/kws-codex-plan-executor/evals/baselines/v3.1.0.json
  - graphify-out/**
acceptance:
  - cd skills/kws-codex-plan-executor && ./evals/run.sh && python3 evals/check_release_contract.py && python3 evals/check_docs_contract.py
```

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/live-migration/release-status.json`
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/release-process.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/decisions.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Modify: `skills/kws-codex-plan-executor/evals/baselines/v3.1.0.json`

**Interfaces:**
- Consumes: reviewed `report.json`, exact report/manifest digests, and current implementation commit from Task 10.
- Produces: either truthful pending metadata with failure evidence or exact verified tuple `deterministic-ready; paid-live-verified`, `release_ready=true`.

- [ ] **Step 1: Independently review sanitized live evidence**

Review manifest, slot indexes, oracle results, aggregate report, implementation
commit binding, and release thresholds. Confirm raw transcript content and home
paths are absent from tracked changes. Treat missing or ambiguous evidence as a
blocking finding.

- [ ] **Step 2: Add RED release-contract expectations for the measured outcome**

For a passing report, update the deterministic release fixture first so
`check_release_contract.py` expects exact billing mode, implementation commit,
manifest digest, report digest, and `release_ready=true`. Run it and observe RED
against pending metadata.

For a failing report, add a regression assertion that the recorded failure
keeps `release_ready=false`; run it and observe RED until the failure summary is
recorded.

- [ ] **Step 3: Update release metadata truthfully**

Only for `release_gate.passed=true`, set:

```yaml
release_status: "deterministic-ready; paid-live-verified"
```

and update `release-status.json` with:

```json
{
  "status": "released",
  "deterministic_status": "deterministic-ready",
  "paid_live_status": "verified",
  "release_ready": true,
  "paid_live_evidence": {
    "status": "passed",
    "billing_mode": "chatgpt_subscription",
    "implementation_commit": "40-hex",
    "manifest_sha256": "64-hex",
    "report_sha256": "64-hex",
    "cost_usd": null,
    "cost_observability": "unavailable"
  }
}
```

Use actual values, not the literal examples. If the gate failed, keep the
pending tuple and record the exact failure IDs and report digest instead.

- [ ] **Step 4: Append final structured verification evidence**

Add a new first JSON block with schema `cpe-release-verification.v1`, version
`3.1.0`, current implementation commit, release commit candidate, timestamp,
all cost-free commands and exit codes, maintained and Bun passing counts,
Graphify evidence, live run ID, 25/7 counts, billing mode, report and manifest
digests, gate result, and residual risks. Do not overwrite earlier history.

- [ ] **Step 5: Run full final verification**

Run:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh --update-baseline
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py evals/live_migration/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
python3 scripts/cpe.py --help
cd ../..
bun run check
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran --output /tmp/cpe-v3-subscription-live-final-graphify.json
git diff --check
```

Expected: every command exits 0, Graphify reports `fresh=true`, the baseline
matches `3.1.0`, and the tracked tree contains only intended release changes.

- [ ] **Step 6: Commit release state and Graphify separately**

```bash
git add skills/kws-codex-plan-executor
git commit -m "release(cpe): publish subscription live evidence"
git add graphify-out
git commit -m "docs(graphify): refresh subscription live release map"
```

- [ ] **Step 7: Final review and merged-main verification**

Use `code_review.md` for one final `main...HEAD` review. Resolve every blocking
finding and rerun affected checks. Then fast-forward local `main` only if the
branch is based on current `main`; otherwise rebase or merge `main` into the
feature worktree without rewriting user work and rerun the full matrix.

After integration, create a temporary `main` worktree, run the entire Step 5
cost-free verification again, verify the report digest still binds to the
implementation commit, confirm the merged worktree is clean, and only then
remove the feature worktree and branch. Do not rerun paid calls merely because
the graph-only or release-evidence commit changed HEAD.

## Execution Order

- Sequential shared-core tasks: Tasks 1-9.
- Credentialed external gate: Task 10 only after Task 9 independent review and
  clean cost-free verification.
- Release gate: Task 11 only after Task 10 has a complete validated report.
- Parallel-safe work: read-only review of fixture contracts and documentation
  impact may run alongside cost-free checks, but no two workers may edit the
  same worktree or live evidence ledger.
- Human approval gates: the current session already approved ChatGPT
  subscription usage without the artificial `$50` limit. Any switch to API-key
  billing, credit purchase, auto top-up, new model, repetition count, or weaker
  threshold requires new explicit approval.

## Verification

### Targeted cost-free checks

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_live_matrix_compiler.py
python3 evals/check_live_matrix_fixtures.py
python3 evals/check_live_matrix_oracle.py
python3 evals/check_live_matrix_ledger.py
python3 evals/check_live_model_runner.py
python3 evals/check_live_model_migration.py
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
```

### Package and repository checks

```bash
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py evals/live_migration/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
cd ../..
bun run check
git diff --check
```

### Structural documentation check

```bash
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran --output /tmp/cpe-v3-subscription-live-graphify.json
```

### Credentialed evidence check

The only accepted live proof is the complete Task 10 run generated from the
reviewed implementation commit. A dry run, fake provider test, hand-edited
`results.json`, partial matrix, or report from another commit is not an honest
substitute.

## Review

Use `code_review.md` after every task-sized commit group and before Task 10,
Task 11, and local-main integration. Findings must lead with correctness,
regression risk, verification, scope control, privacy, and evidence integrity.
No live execution or release transition may proceed with a P0, P1, or P2
finding unresolved.
