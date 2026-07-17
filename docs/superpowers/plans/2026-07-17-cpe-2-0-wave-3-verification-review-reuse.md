# CPE 2.0 Wave 3: Verification and Review Evidence Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate redundant same-run verification and review work without weakening Superpowers quality gates by making reusable evidence explicit, narrowly keyed, immutable, and invalidated by every decision-relevant change.

**Architecture:** A deterministic verification helper executes commands and writes receipts keyed by exact argv, working directory, HEAD, environment fingerprint, phase, input digest, and mutable-input policy. The runner may reuse only successful same-run receipts whose complete key still matches. Review lifecycle and transition-obligation validators inspect child-produced evidence but do not judge implementation semantics. Coordination telemetry records whether subagent context was scoped efficiently; CPE observes this data and never launches or manages Superpowers subagents itself.

**Tech Stack:** Python 3 standard library, `unittest`, JSON/JSONL, subprocess, SHA-256, existing CPE format-2 state and flight recorder.

## Global Constraints

- Implement only after Waves 0–2 pass their complete eval gates.
- Do not modify Superpowers skills, templates, hooks, or upstream packages.
- Do not make CPE a second semantic reviewer. Superpowers owns task review, final review, fixes, and acceptance.
- Reuse verification only inside one run. Never reuse a receipt from a different `run_id`.
- Reuse only successful receipts. Failed, interrupted, timed-out, partial, or malformed receipts are never cache hits.
- The complete reuse key is `command_id + exact argv digest + cwd + HEAD + environment fingerprint + phase + input digest + mutable-input policy`.
- Any new HEAD, environment, phase, input digest, command spelling, working directory, or mutable-input policy must execute again.
- Commands that declare mutable inputs must execute again unless the policy supplies and validates a decision-complete digest.
- Review reuse means accepting an already-recorded Superpowers review receipt for the same scope and HEAD. It does not mean CPE performs another review.
- `merged_main` is a reserved evidence-key namespace for a separate parent-observed integration receipt. The branch controller and its internal helper cannot claim or execute that phase.
- Default Superpowers implementer/reviewer delegation evidence uses `fork_turns=none`. `fork_turns=all` requires a source-referenced exception recorded by the child.
- Follow the approved [token evidence and observability addendum](../specs/2026-07-17-cpe-2.0-token-evidence-observability-addendum.md): produced artifact bytes, declared context bytes, and model-consumed tokens are distinct measurements and may never be relabelled as one another.
- Review/context telemetry is content-free. Persist only stable class, digest, byte length, scope, and availability metadata; never raw diff bodies, prompts, source bodies, or tool output.
- Aggregate Codex usage may include the controller and nested agents. Do not allocate aggregate tokens to roles unless a provider event supplies independently attributable usage.
- Durable accepted artifacts remain under `~/.codex/orchestrator/<run-id>/`. The helper may write temporary receipts/logs only under the ignored worktree path `.superpowers/sdd/verification/`; Wave 1 bounded ingest validates and seals them into the run root before acceptance. No helper artifact may become a tracked product change.
- Use test-driven development and commit after each task.

---

### Task 1: Add the deterministic verification receipt helper

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/verification.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class VerificationRequest:
    run_id: str
    command_id: str
    argv: tuple[str, ...]
    cwd: Path
    head: str
    environment_fingerprint: str
    phase: Literal["task", "affected", "branch_final", "merged_main"]
    input_digest: str
    deterministic: bool
    mutable_input_policy: Literal["immutable", "digest_complete", "always_execute"]
    required_artifact_paths: tuple[str, ...]
    timeout_seconds: int

@dataclass(frozen=True)
class VerificationReceipt:
    schema_version: int
    receipt_id: str
    run_id: str
    cache_key: str
    request: Mapping[str, object]
    status: Literal["passed", "failed", "timed_out", "interrupted"]
    exit_code: int | None
    started_at: str
    finished_at: str
    stdout_path: str
    stderr_path: str
    stdout_digest: str
    stderr_digest: str
    artifacts: tuple[Mapping[str, object], ...]

def verification_cache_key(request: VerificationRequest) -> str: ...
def materialize_helper_descriptor(run_root: Path, cpe_script: Path) -> Path: ...
def execute_verification(evidence_root: Path, request: VerificationRequest) -> VerificationReceipt: ...
def find_reusable_receipt(
    evidence_root: Path, request: VerificationRequest
) -> VerificationReceipt | None: ...
```

- [ ] **Step 1: Write failing cache-key tests**

Create table-driven tests proving each field invalidates reuse independently:

```python
for field, replacement in (
    ("command_id", "lint-v2"),
    ("argv", ("python3", "-m", "unittest", "other")),
    ("cwd", other_cwd),
    ("head", "b" * 40),
    ("environment_fingerprint", "changed"),
    ("phase", "branch_final"),
    ("input_digest", "changed"),
    ("mutable_input_policy", "always_execute"),
):
    changed = dataclasses.replace(base, **{field: replacement})
    self.assertNotEqual(verification_cache_key(base), verification_cache_key(changed))
```

Also prove `run_id` is a same-run lookup boundary rather than cache-key material: changing only `run_id` produces the same content key, but `find_reusable_receipt()` rejects the receipt because its owning run differs. Prove `timeout_seconds`, `deterministic`, and required artifact paths are source-contract/receipt validation fields rather than extra evidence-key dimensions; they may reject reuse but do not change the approved eight-part key.

- [ ] **Step 2: Write failing execution/receipt tests**

Required cases:

- argv is passed as an array with `shell=False`;
- stdout/stderr are bounded and stored under `.superpowers/sdd/verification/logs/`;
- receipt is atomically written under `.superpowers/sdd/verification/receipts/`;
- a passing receipt can be found by the exact same request;
- a failed receipt is never reusable;
- a request whose compiled contract says `deterministic=false` is never reusable;
- `always_execute` is never reusable;
- a missing, symlinked, escaping, or digest-changed required output artifact invalidates reuse;
- a receipt from another evidence root or `run_id` is never reusable;
- malformed or digest-mismatched receipt is ignored and emits a corruption event.
- `materialize_helper_descriptor()` writes `tools/run-and-record.json` with mode `0400`, an absolute argv prefix, and digests of `cpe.py` plus `verification.py`; a symlinked/replaced tool source or descriptor is rejected.

- [ ] **Step 3: Run the focused tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.VerificationReceiptTests -v
```

Expected: missing `cpe_runtime.verification` module.

- [ ] **Step 4: Implement canonical key generation**

The key payload must preserve argv element boundaries:

```python
def verification_cache_key(request: VerificationRequest) -> str:
    payload = {
        "schema_version": 1,
        "command_id": request.command_id,
        "argv_digest": sha256(
            json.dumps(list(request.argv), separators=(",", ":")).encode()
        ).hexdigest(),
        "cwd": str(request.cwd.resolve(strict=True)),
        "head": request.head,
        "environment_fingerprint": request.environment_fingerprint,
        "phase": request.phase,
        "input_digest": request.input_digest,
        "mutable_input_policy": request.mutable_input_policy,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()
```

Validate that `cwd` is inside the active worktree before execution. Do not accept a shell string.

- [ ] **Step 5: Implement bounded execution and immutable receipts**

Use `subprocess.Popen(..., start_new_session=True, shell=False)`, `MAX_VERIFICATION_LOG_BYTES = 1 * 1024 * 1024` independently for stdout and stderr, and the existing process-group termination helpers. After a PASS, resolve at most 64 compiled required artifact paths without symlinks, hash regular files by streaming, and store relative path/byte length/SHA-256 without copying product artifacts. Write stdout/stderr first, fsync them, then atomically publish the receipt. The receipt ID is the SHA-256 of its canonical content excluding `receipt_id`.

Store paths relative to `evidence_root` and reject any path that escapes the verified `.superpowers/sdd/verification/` root after resolution. Receipt source is `child_attested`; file existence, mode, path safety, and digest become `parent_observed` only when CPE later ingests them.

`materialize_helper_descriptor()` uses the shared atomic private writer and stores only:

```json
{
  "schema_version": 1,
  "argv_prefix": ["python3", "/absolute/read-only/path/scripts/cpe.py", "verify"],
  "source_digests": {
    "cpe.py": "0000000000000000000000000000000000000000000000000000000000000000",
    "cpe_runtime/verification.py": "0000000000000000000000000000000000000000000000000000000000000000"
  }
}
```

The descriptor grants no write access to the private run root. `cpe.py verify` revalidates both source digests before running; a mid-run tool update produces `verification_helper_fallback` rather than silently changing cache semantics.

- [ ] **Step 6: Implement strict lookup**

`find_reusable_receipt()` must:

1. return `None` for `always_execute` or `deterministic=false`;
2. compute the complete key;
3. open only the indexed receipt inside the active worktree verification root;
4. validate schema, owning `run_id`, receipt digest, log digests, `status == "passed"`, equality of every key-bearing request field, and the current digest of every required artifact;
5. return the receipt only when all checks pass.

- [ ] **Step 7: Run the focused tests and confirm GREEN**

Run the command from Step 3. Expected: all receipt tests pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/verification.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): record keyed verification evidence"
```

---

### Task 2: Expose a child-callable verification command and reuse exact same-run evidence

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

- Consumes: source-validated compiled verification entries and the active format-2 run/worktree.
- Produces: `cpe.py verify` JSON response, child-attested receipt/ledger evidence, and parent-ingested reuse observations.

**CLI contract:**

```text
cpe.py verify --run-id RUN_ID --command-id ID --phase PHASE
              --input-digest SHA256 --mutable-input-policy POLICY
              --cwd PATH -- COMMAND [ARG ...]
```

This is an internal execution helper used by the child prompt. It is not a general shell wrapper and requires an active run whose worktree contains `--cwd`. The launcher provides the run-private `tools/run-and-record.json` descriptor; its absolute CPE helper path is read-only and digest-bound. The command writes only to the verified ignored `.superpowers/sdd/verification/` subtree, not to the private run root directly.

- [ ] **Step 1: Write failing CLI parsing and trust-boundary tests**

Cover:

- `--` is required before argv;
- empty argv is rejected;
- unknown phase or mutable policy exits with usage code;
- unknown run ID exits without executing;
- cwd outside the saved worktree exits without executing;
- caller-supplied `--head` or environment fingerprint flags are not accepted; the parent derives them from saved state/current worktree;
- command ID, exact argv, phase, and mutable policy must match one source-validated verification entry in `compiled-run-index.json`; undeclared or ambiguous commands are rejected by this helper and may run only as uncached child work;
- `--phase merged_main` is rejected for the active branch controller; it can appear only in a separately validated parent integration receipt;
- exact second invocation returns the first receipt with `reused=true` and does not execute the fixture twice.
- a corrupt cache index triggers one direct execution with `reused=false` and reason `verification_helper_fallback`; it never skips the command.

- [ ] **Step 2: Run the focused CLI tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_cli.VerificationCliTests -v
```

Expected: `verify` is not a recognized command.

- [ ] **Step 3: Add the internal `verify` command**

In `cpe.py`, derive `head` from `git rev-parse HEAD` in the saved worktree and derive the environment fingerprint from the state/capability preflight. Reject a mismatch between current and saved capability evidence rather than accepting a child-provided value. Validate command ID, exact argv, phase, and mutable policy against the current plan's source-validated compiled-index entry. Derive `evidence_root` as `<saved-worktree>/.superpowers/sdd/verification`, create it with mode `0700`, and reject symlink components. Do not grant the child write access to `~/.codex/orchestrator/<run-id>`.

Return one JSON object to stdout:

```json
{
  "schema_version": 1,
  "reused": true,
  "receipt_path": ".superpowers/sdd/verification/receipts/receipt-example.json",
  "status": "passed",
  "cache_key": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

Before execution, call `find_reusable_receipt()`. If no valid receipt exists, call `execute_verification()` and return `reused=false`. If cache lookup fails because its index or receipt is corrupt after the run/worktree/request safety checks have passed, append `verification_helper_fallback`, quarantine only the corrupt index entry, and execute the exact argv once. Path, state, run-ID, or worktree trust-boundary failures remain hard failures and must not fall back to arbitrary execution.

- [ ] **Step 4: Put the helper contract into the child prompt**

Before controller launch, materialize the descriptor and add `VERIFICATION_HELPER_DESCRIPTOR: <run-root>/tools/run-and-record.json` plus the exact invocation pattern to `CodexLauncher._prompt()`. Provide these rules:

- use the helper for deterministic test/lint/build commands declared by the compiled index;
- use a stable command ID from `compiled-run-index.json`;
- use `task`, `affected`, or `branch_final` as the real branch phase; task review delta is not a verification phase, and `merged_main` is parent-integration-only;
- compute the input digest from declared non-git inputs;
- use `always_execute` for mutable external state that cannot be fully digested;
- never claim a cache hit without the helper receipt;
- do not rerun a cached same-key pass merely for reassurance.

If the helper returns `uncached_command_required` because the plan command was ambiguous or undeclared, the controller must execute the exact command once itself, append a `verification.executed_uncached` child-attested ledger event with argv digest/exit code, and set `receipt_path=null`. This evidence may satisfy the plan's structural verification requirement when its exit code is zero, but it is never reusable. The same direct-execution rule applies if the helper binary is unavailable; record reason `verification_helper_fallback`. Helper failure never means verification skip.

Do not change Superpowers' required reviews or final verification semantics.

- [ ] **Step 5: Record reuse decisions in the child ledger, then derive flight-recorder observations**

Append one event per invocation:

```json
{
  "event": "verification.reused",
  "command_id": "unit",
  "phase": "task",
  "cache_key": "0000000000000000000000000000000000000000000000000000000000000000",
  "receipt_id": "0000000000000000000000000000000000000000000000000000000000000000",
  "source": "child_attested"
}
```

Use `verification.executed` for a miss and include duration/status without embedding stdout/stderr content. During Wave 1 ingest, CPE validates the receipt and appends a private `verification.evidence_ingested` event with `source="parent_observed"`; its derived report may then count executed/reused decisions while preserving the original child-attested provenance. CPE must never relabel the command's PASS semantics itself as parent-observed.

- [ ] **Step 6: Run the focused CLI and runner tests and confirm GREEN**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_cli.VerificationCliTests \
  evals.check_runner.VerificationReceiptTests \
  evals.check_runner.VerificationReuseIntegrationTests -v
```

Expected: exact hits avoid process execution; every key mutation executes again.

- [ ] **Step 7: Commit Task 2**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/check_cli.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): reuse exact same-run verification"
```

---

### Task 3: Validate the Superpowers review lifecycle without re-reviewing code

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/review_evidence.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ReviewReceipt:
    review_id: str
    scope: Literal["task", "delta", "whole_branch"]
    base_head: str
    head: str
    task_ids: tuple[str, ...]
    finding_set_id: str | None
    finding_ids: tuple[str, ...]
    evidence_digest: str
    diff_kind: Literal["task", "finding_delta", "whole_branch"]
    diff_artifact_digest: str
    diff_artifact_bytes: int
    review_package_digest: str
    review_package_bytes: int
    disposition: Literal["accepted", "changes_requested"]
    reviewer_attestation_path: str

@dataclass(frozen=True)
class ReviewLifecycleDecision:
    valid: bool
    reason_code: str
    missing_scopes: tuple[str, ...]
    stale_review_ids: tuple[str, ...]

@dataclass(frozen=True)
class FindingFixReceipt:
    fix_id: str
    finding_set_id: str
    source_review_id: str
    before_head: str
    after_head: str
    finding_ids: tuple[str, ...]

def validate_review_receipt(run_root: Path, worktree: Path, receipt: Mapping[str, object]) -> ReviewReceipt: ...
def validate_review_lifecycle(
    *, completed_task_ids: Sequence[str], current_head: str,
    receipts: Sequence[ReviewReceipt], fixes: Sequence[FindingFixReceipt]
) -> ReviewLifecycleDecision: ...
```

The required lifecycle is:

1. one task review receipt for each completed task;
2. exactly one consolidated fix receipt for each distinct `finding_set_id` that requested changes;
3. a delta review covering each fix receipt's `after_head` and finding set;
4. one whole-branch full review on the final HEAD.

CPE validates receipt presence, scope, identifiers, path safety, and HEAD alignment. It does not inspect code to decide whether a finding is correct.

- [ ] **Step 1: Write failing review lifecycle tests**

Required cases:

- every task covered + final whole-branch receipt on current HEAD: valid;
- missing task review: invalid `missing_task_review`;
- whole-branch review on old HEAD: invalid `stale_whole_branch_review`;
- fixes after review without delta receipt: invalid `missing_delta_review`;
- two fix receipts for the same finding set: the second is invalid `duplicate_fix_cycle`;
- a new finding set opened by a delta review may have its own consolidated fix and delta review;
- two reviews with identical scope, base HEAD, head, task IDs, and evidence digest: valid evidence but the second is reported as `redundant_review_receipt` for efficiency metrics;
- review package and diff metadata are bound to safe worktree-relative regular files before acceptance, with digest and byte length verified by the parent;
- `scope=task|delta|whole_branch` must map respectively to `diff_kind=task|finding_delta|whole_branch`;
- the same diff digest repeated for the same scope/base/head is counted as redundant payload evidence;
- finding-delta and whole-branch receipts with different kinds are not collapsed even if incidental metadata matches;
- raw diff bodies are not copied into sealed evidence; base/head, reconstruction command identity, digest, and byte length are retained instead;
- reviewer attestation path outside run root/worktree or through a symlink: rejected;
- child prose without a receipt: not accepted as review evidence.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.ReviewEvidenceTests -v
```

Expected: missing review evidence module.

- [ ] **Step 3: Implement strict receipt and lifecycle validation**

Store accepted review receipts in `evidence/reviews/<review-id>.json` and fix receipts in `evidence/reviews/<fix-id>.json`; store only references in the execution ledger. Validate identifier uniqueness, finding-set linkage, exact base/head/task/evidence coverage, one fix per finding set, and a matching delta review after each fix. Before sealing the receipt, validate each declared review package/diff artifact as a safe worktree-relative regular file and record its SHA-256 and byte length. Do not copy raw diff snapshots into durable evidence: preserve base/head, diff kind, digest, byte length, and a stable reconstruction command identifier. Return structured missing/stale sets; do not produce natural-language semantic findings.

- [ ] **Step 4: Derive review efficiency metrics**

Add these report fields from events/receipts:

```json
{
  "task_reviews": 4,
  "delta_reviews": 1,
  "whole_branch_reviews": 1,
  "redundant_review_receipts": 0,
  "consolidated_fix_cycles": 1,
  "review_package_bytes": 48192,
  "review_diff_bytes": 32768,
  "review_diff_bytes_by_kind": {
    "task": 8192,
    "finding_delta": 4096,
    "whole_branch": 20480
  },
  "duplicate_review_diff_digests": 0
}
```

If a second same-scope, same-HEAD receipt appears, retain it as evidence but count it as redundant. Do not automatically delete it. Artifact-byte counters are payload-pressure observations, not token totals and not semantic review-quality signals.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run the command from Step 2. Expected: all lifecycle tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/review_evidence.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): validate review evidence lifecycle"
```

---

### Task 4: Persist transition obligations and coordination telemetry

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/obligations.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/coordination.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class TransitionObligation:
    obligation_id: str
    opened_by_task_id: str
    must_close_by_task_id: str
    description: str
    status: Literal["open", "satisfied", "waived"]
    closure_evidence_id: str | None
    waiver_reason: str | None

def validate_transition_obligations(
    *, obligations: Sequence[TransitionObligation],
    compiled_task_ids: Sequence[str],
    completed_task_ids: Sequence[str],
    next_task_id: str | None,
    finishing: bool,
    valid_evidence_ids: AbstractSet[str],
) -> tuple[bool, tuple[str, ...]]: ...
```

**Coordination event shape:**

```json
{
  "schema_version": 1,
  "event": "coordination.spawn",
  "plan_index": 0,
  "task_id": "T3",
  "role": "implementer",
  "depth": 1,
  "fork_turns": "none",
  "source_context_refs": [
    {
      "class": "task_brief",
      "path": ".superpowers/sdd/task-3-brief.md",
      "sha256": "1111111111111111111111111111111111111111111111111111111111111111"
    },
    {
      "class": "review_diff",
      "path": ".superpowers/sdd/review-base..head.diff",
      "sha256": "2222222222222222222222222222222222222222222222222222222222222222"
    },
    {
      "class": "implementer_report",
      "path": ".superpowers/sdd/task-3-report.md",
      "sha256": "3333333333333333333333333333333333333333333333333333333333333333"
    }
  ],
  "context_ref_count": 3,
  "context_ref_bytes": 48192,
  "context_measurement_kind": "declared_refs_not_provider_ingestion",
  "context_classes": {
    "task_brief": 1,
    "review_diff": 1,
    "implementer_report": 1
  },
  "source": "child_attested"
}
```

Supported event names: `coordination.spawn`, `coordination.wait`, `coordination.list`, `coordination.send`, `coordination.followup`, `coordination.finish`, and `coordination.compaction`.

`source_context_refs` exists only in the child worktree event used for parent validation. Each entry contains exactly `class`, safe relative `path`, and SHA-256. After resolving and observing byte length, durable coordination telemetry retains digest/class/byte metadata and discards the raw path.

**Coordination interfaces:**

```python
@dataclass(frozen=True)
class CoordinationObservation:
    event: str
    plan_index: int
    task_id: str | None
    role: str | None
    depth: int | None
    fork_turns: str | None
    duration_ms: int | None
    context_ref_count: int | None
    context_ref_bytes: int | None
    context_measurement_kind: Literal[
        "declared_refs_not_provider_ingestion", "unavailable"
    ]
    context_classes: Mapping[str, int] | None
    usage_scope: Literal["controller_and_nested_agents_aggregate"]
    usage_attribution: Literal["parent_observed", "child_attested", "unavailable"]
    usage_attribution_unavailable_reason: str | None
    source: Literal["parent_observed", "child_attested"]

def extract_coordination_observation(
    codex_event: Mapping[str, object], *, plan_index: int
) -> CoordinationObservation | None: ...
def reconcile_coordination_observations(
    *, parent: Sequence[CoordinationObservation],
    child: Sequence[CoordinationObservation]
) -> tuple[CoordinationObservation, ...]: ...
```

- [ ] **Step 1: Write failing obligation tests**

Prove:

- an open obligation whose `must_close_by_task_id` is already completed blocks the next task transition;
- an obligation with `must_close_by_task_id="__finish__"` permits task transitions but blocks finish;
- a satisfied `closure_evidence_id` must resolve to an accepted, digest-validated evidence record;
- `opened_by_task_id` and `must_close_by_task_id` must exist in compiled task order (or deadline is `__finish__`), and the deadline cannot precede the opening task;
- waived obligations require a non-empty parent-observed waiver reason and event;
- obligations survive checkpoint/resume and cannot be dropped from the execution ledger.

- [ ] **Step 2: Write failing coordination telemetry tests**

Prove:

- implementer and reviewer events default to `fork_turns=none`;
- `fork_turns=all` without an exact compiled-index coordination exception is counted as `unjustified_full_context_fork`;
- `fork_turns=all` is accepted only when task ID, role, source span digest, and reason code match a source-validated `coordination_exceptions` entry in `compiled-run-index.json`;
- depth, role, task ID, duration, wait/list/send/followup counts, and compaction counts survive checkpoint/resume;
- telemetry never changes plan success/failure by itself in 2.0.
- supported Codex JSONL coordination metadata becomes `parent_observed` without storing raw JSONL/content;
- when the event stream omits a field, the value remains `child_attested` or unknown with an explicit unavailable reason;
- a parent/child mismatch keeps the parent observation and records a data-quality warning rather than silently merging counts.
- context refs accept only safe worktree-relative regular files classified as `task_brief`, `implementer_report`, `review_package`, `review_diff`, `finding_delta`, `progress_ledger`, `spec_slice`, `plan_slice`, or `other_bounded`;
- parent metadata observation records digest and byte length without persisting file bodies;
- produced SDD inventory and declared context refs remain separate counters;
- missing declared context metadata remains unavailable rather than zero;
- aggregate usage without agent-scoped provider events records `usage_attribution=unavailable` and reason `provider_event_not_agent_scoped`;
- child-estimated role usage cannot alter parent-observed aggregate usage.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.TransitionObligationTests \
  evals.check_runner.CoordinationTelemetryTests -v
```

Expected: missing obligations module and telemetry ingestion.

- [ ] **Step 4: Implement obligation validation**

Persist obligations in `evidence/obligations.json` and reference their digest in state. Before advancing each task boundary reported by the execution ledger and before the final completed transition, compare `must_close_by_task_id` with the completed/current task IDs. On failure, transition to `checkpointed` with reason `open_transition_obligations`; do not launch another child automatically.

The parent may confirm evidence or record an explicit waiver. The child cannot self-waive an obligation.

- [ ] **Step 5: Add child telemetry instructions and bounded ingestion**

The launcher prompt must tell the Superpowers worker to append coordination events whenever it uses subagents. The child chooses and runs its Superpowers workflow; CPE only supplies an append-only event path and validates events afterward.

Extend the existing JSONL usage filter with a content-free coordination callback. `coordination.py` may accept only stable event type, agent ID digest, task ID, role, depth, `fork_turns`, duration, operation count, context class counts, context reference count/bytes, and explicit measurement/attribution availability. Discard prompts, messages, tool arguments/results, raw paths, and unknown event bodies immediately. Resolve child-declared safe relative context refs inside the owned worktree, observe regular-file digest and byte length, then retain only stable digest/class/byte metadata. If the Codex stream does not expose coordination metadata, append `coordination.telemetry_unavailable` with reason `provider_event_not_available` and use validated child-attested ledger events without upgrading their trust.

At every checkpoint and plan acceptance, create a metadata-only `.superpowers/sdd` production inventory: files/bytes by stable artifact class, largest file bytes, review diff files/bytes by diff kind, duplicate digest count when already available, and whether produced inventory exceeds the Wave 1 sealing limits. Inventory above the limits is advisory; referenced evidence still obeys the existing fail-closed sealing contract. Do not read file bodies solely to estimate tokens and do not delete artifacts automatically.

Ingestion limits:

- maximum 2048 coordination events per plan;
- maximum 16 KiB per event;
- reject unknown keys and unsupported roles/events;
- never copy full prompts, transcripts, or secrets into telemetry.

- [ ] **Step 6: Add coordination efficiency derivation**

Derive:

```json
{
  "coordination": {
    "spawns": 4,
    "max_depth": 2,
    "fork_turns": {"none": 4, "all": 0},
    "unjustified_full_context_forks": 0,
    "wait_calls": 2,
    "list_calls": 1,
    "send_calls": 0,
    "followup_calls": 1,
    "compactions": 0,
    "duration_seconds": 842,
    "declared_context_refs": 12,
    "declared_context_bytes": 193536,
    "context_measurement_kind": "declared_refs_not_provider_ingestion",
    "usage_scope": "controller_and_nested_agents_aggregate",
    "usage_attribution": "unavailable",
    "usage_attribution_unavailable_reason": "provider_event_not_agent_scoped",
    "produced_artifacts": {
      "files": 37,
      "bytes": 712704,
      "review_diff_files": 8,
      "review_diff_bytes": 524288,
      "sealed_evidence_limit_exceeded": false
    }
  }
}
```

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run the command from Step 3. Expected: all obligation and telemetry tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/obligations.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/coordination.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): persist obligations and coordination evidence"
```

---

### Task 5: Integrate reuse policy, documentation, and the complete gate

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**

- Consumes: verification, review, finding-fix, obligation, and coordination receipts from Tasks 1–4.
- Produces: structural plan/final transition gates, derived efficiency totals, and one complete Wave 3 integration gate.

- [ ] **Step 1: Gate plan transitions on structural evidence only**

Before advancing to the next plan:

1. validate the result receipt;
2. validate required task/delta review and consolidated-fix receipt structure;
3. validate obligations whose `must_close_by_task_id` deadline has been reached;
4. persist the current progress fingerprint and evidence digests;
5. transition atomically.

Before final completion, additionally require a whole-branch review on the current HEAD, required `branch_final` verification receipts, and all obligations due by `__finish__`.

If a valid exact-key receipt already exists, accept it. If its key differs, require execution through the helper. Never substitute a CPE semantic review.

- [ ] **Step 2: Add an end-to-end reuse test**

The fixture must perform this sequence:

1. run task verification and record a pass;
2. request the same task verification again and reuse it;
3. create a new commit;
4. request the same command and prove it executes because HEAD changed;
5. record task and delta review receipts;
6. create a final whole-branch review receipt;
7. satisfy a transition obligation;
8. finish successfully.

Assert the final report contains:

```json
{
  "verification_executions": 2,
  "verification_reuses": 1,
  "verification_launches_avoided": 1,
  "redundant_review_receipts": 0,
  "open_transition_obligations": 0
}
```

- [ ] **Step 3: Document the no-duplicate-work contract**

Explain:

- focused task verification is not a substitute for final whole-branch verification;
- exact same-run evidence can be reused only with the complete cache key;
- CPE validates review receipts but never re-reviews code;
- CPE records coordination patterns but does not orchestrate Superpowers subagents;
- `fork_turns=none` is the default because the plan, source refs, and task prompt are the intended context boundary;
- produced artifact bytes, declared context bytes, and provider token usage are separate measurements;
- raw diff snapshots are not sealed; review receipts preserve reconstructable base/head plus digest/byte metadata;
- aggregate controller usage is not allocated to implementer/reviewer roles without agent-scoped provider evidence;
- mutable external inputs default to execution, not reuse.

- [ ] **Step 4: Run focused Wave 3 tests**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.VerificationReceiptTests \
  evals.check_runner.VerificationReuseIntegrationTests \
  evals.check_runner.ReviewEvidenceTests \
  evals.check_runner.TransitionObligationTests \
  evals.check_runner.CoordinationTelemetryTests \
  evals.check_runner.EvidenceReuseEndToEndTests \
  evals.check_cli.VerificationCliTests -v
```

Expected: all Wave 3 cases pass.

- [ ] **Step 5: Run the complete CPE gate once**

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
```

Expected: every runner and CLI test passes. This is the one whole-wave full-suite execution.

- [ ] **Step 6: Run hygiene and inspect artifacts**

```bash
git diff --check
git status --short --branch --untracked-files=all
```

Expected: no whitespace errors and no repository runtime artifacts. Symlink rejection is proven inside disposable focused fixtures; do not scan or mutate unrelated historical run roots.

- [ ] **Step 7: Commit Task 5**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "docs(cpe): define evidence reuse boundaries"
```

---

## Wave 3 Done When

- The verification helper writes immutable, bounded, digest-checked receipts.
- Exact same-run successful evidence can be reused only when every key dimension matches.
- New HEAD, environment, phase, input, argv, cwd, or mutable policy forces execution.
- Failed, partial, cross-run, corrupt, and mutable-external receipts are never reused.
- Superpowers review receipts are structurally validated without a second CPE semantic review.
- Task, delta, and whole-branch review scopes align with their declared HEAD/task coverage.
- Transition obligations survive resume and block the correct boundary until satisfied or parent-waived.
- Coordination telemetry reveals context-fork and subagent overhead without controlling Superpowers.
- Review receipts bind diff kind, digest, and byte length without sealing raw diff bodies.
- Produced SDD inventory and declared context refs are reported separately and are never labelled as consumed tokens.
- Missing context or per-agent usage attribution is explicit rather than coerced to zero.
- The complete CPE eval suite and `git diff --check` pass.
