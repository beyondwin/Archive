# CPE 2.0 Wave 1 Compiler And Flight Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically compile immutable Superpowers spec/plan snapshots into a source-validated private run index and preserve bounded, trust-labelled execution evidence and optimization reports outside the disposable worktree.

**Architecture:** Add a CPE-owned read-only compiler with a strict schema and source-span validation; do not modify Superpowers or ask the user for a bundle. Add focused evidence and reporting modules, then wire them into the format-2 preparation and plan-acceptance boundaries created by Wave 0.

**Tech Stack:** Python 3 standard library, Codex CLI structured output, JSON Schema draft 2020-12, `unittest`, Git CLI.

## Global Constraints

- Requires accepted Wave 0 HEAD from `2026-07-17-cpe-2-0-wave-0-format-and-safety.md`.
- Design source: `docs/superpowers/specs/2026-07-17-cpe-evidence-driven-execution-optimization-design.md` sections 5-8.
- User input remains `--spec`, `--plan`, and `--workspace`; no public bundle flag.
- Do not modify Superpowers skills, plan generators, templates, or hooks.
- Each compiler attempt uses one Codex turn, no subagents, a `read-only` sandbox, a 300-second timeout, at most 512 KiB input, and at most 1 MiB structured output. One initial attempt plus at most one schema/source repair attempt is allowed.
- Compiler output is derivative; snapshots and operator contract remain authoritative.
- Optional ambiguity becomes `unknown`; repository identity, source commit, ordered plans, and remote policy ambiguity stops before the product controller.
- Do not store the full user prompt, raw Codex JSONL, transcript, source diff, or environment secrets.
- Sealed evidence limits: 128 files per plan, 1 MiB per file, 8 MiB total per plan.
- Report limits: 1 MiB JSON and 1 MiB Markdown.
- Keep deterministic evals model-free by injecting a fake compiler.

---

## File Structure

- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py`: operator contract defaults, compiler cache key, source validation, repair-once service.
- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`: execution ledger validation, bounded ingest, manifest hashing, read-only sealing.
- Create `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`: trust-labelled per-plan/run optimization report generation.
- Create `skills/kws-codex-plan-executor/templates/compiled-run-index.schema.json`: strict internal compiler output.
- Create `skills/kws-codex-plan-executor/templates/execution-ledger.schema.json`: structured task/review/verification observation contract.
- Create `skills/kws-codex-plan-executor/templates/optimization-report.schema.json`: deterministic report contract.
- Modify `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`: reusable structured Codex process boundary and read-only compiler invocation.
- Modify `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`: contract/index paths and digests.
- Modify `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`: preparation, compiler integration, evidence seal, report update.
- Modify `skills/kws-codex-plan-executor/evals/check_runner.py`: compiler/evidence/reporting/integration tests.
- Modify `skills/kws-codex-plan-executor/evals/fake_codex.py`: deterministic compiler mode.
- Modify `skills/kws-codex-plan-executor/README.md`: tracked inventory only; public 2.0 behavior remains unreleased until Wave 4.

### Task 1: Build The Source-Validated Compiled Run Index

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py`
- Create: `skills/kws-codex-plan-executor/templates/compiled-run-index.schema.json`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Test: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**
- Consumes: `StateStore.state["inputs"]`, normalized operator contract, compiler callback.
- Produces: `default_operator_contract(state) -> dict[str, object]`, `compiler_cache_key(state, contract) -> str`, `validate_compiled_index(payload, state, contract) -> dict[str, object]`, `CompiledIndexService.prepare(store) -> Path`.

- [ ] **Step 1: Write RED tests for exact source spans, cache identity, and ambiguity**

Add imports and tests:

```python
from cpe_runtime.compiler import (
    CompiledIndexService,
    compiler_cache_key,
    default_operator_contract,
    validate_compiled_index,
)

def test_compiled_index_requires_exact_plan_source_spans(self) -> None:
    store = self.create_format_two_store("compiler-source")
    contract = default_operator_contract(store.state)
    plan = next(item for item in store.state["inputs"] if item["role"] == "plan")
    payload = {
        "format_version": 2,
        "cache_key": compiler_cache_key(store.state, contract),
        "plans": [{
            "plan_id": "plan-01",
            "source_sha256": plan["sha256"],
            "byte_length": plan["byte_length"],
            "line_count": 1,
            "tasks": [{
                "task_id": "task-01",
                "order": 0,
                "source_line_start": 1,
                "source_line_end": 1,
                "source_text_sha256": "f" * 64,
            }],
            "verifications": [],
            "capabilities": [],
            "coordination_exceptions": [],
            "execution_advisories": [],
            "unknowns": [],
        }],
    }
    with self.assertRaisesRegex(ValueError, "source span digest"):
        validate_compiled_index(payload, store.state, contract)

def test_optional_compiler_ambiguity_is_preserved_as_unknown(self) -> None:
    store = self.create_format_two_store("compiler-unknown")
    service = CompiledIndexService(
        compile_once=self.fake_compiler_with_unknown("capability:browser"),
    )
    path = service.prepare(store)
    index = json.loads(path.read_text(encoding="utf-8"))
    self.assertEqual(index["plans"][0]["unknowns"], ["capability:browser"])
    self.assertEqual(service.compile_calls, 1)
```

Create test helpers that build a format-2 store from an explicit one-line plan and return compiler payloads whose line digest is computed from that exact snapshot. Do not hash fixture source paths; hash snapshot bytes and selected line text.

- [ ] **Step 2: Run the tests and verify the missing-module RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_compiled_index_requires_exact_plan_source_spans \
  evals.check_runner.SequentialRunnerTest.test_optional_compiler_ambiguity_is_preserved_as_unknown -v
```

Expected: ERROR because `cpe_runtime.compiler` does not exist.

- [ ] **Step 3: Implement the compiler service and exact validation**

Create `compiler.py` with these public definitions:

```python
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .state import StateStore

MAX_COMPILER_INPUT_BYTES = 512 * 1024
MAX_COMPILER_OUTPUT_BYTES = 1024 * 1024
SAFETY_UNKNOWN_PREFIXES = (
    "workspace:",
    "repository:",
    "source_commit:",
    "plan_order:",
    "remote_policy:",
)

CompilerCallback = Callable[[StateStore, dict[str, object], bool], dict[str, object]]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def default_operator_contract(state: dict[str, Any]) -> dict[str, object]:
    return {
        "workspace": state["source_repository"],
        "source_commit": state["source_commit"],
        "plan_ids": [plan["plan_id"] for plan in state["plans"]],
        "completion_scope": "cpe_branch_completed",
        "remote_policy": "forbidden",
        "merge_policy": "external_finisher_only",
    }


def compiler_cache_key(
    state: dict[str, Any],
    contract: dict[str, object],
) -> str:
    material = {
        "format_version": 2,
        "input_sha256": [record["sha256"] for record in state["inputs"]],
        "operator_contract": contract,
        "compiler_schema_version": 1,
        "cpe_version": "2.0",
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(encoded)


def _source_lines(record: dict[str, Any]) -> list[str]:
    payload = Path(record["snapshot_path"]).read_text(encoding="utf-8")
    return payload.splitlines(keepends=True)


def validate_compiled_index(
    payload: dict[str, Any],
    state: dict[str, Any],
    contract: dict[str, object],
) -> dict[str, object]:
    if payload.get("format_version") != 2:
        raise ValueError("compiled index format is invalid")
    if payload.get("cache_key") != compiler_cache_key(state, contract):
        raise ValueError("compiled index cache key is invalid")
    plan_inputs = [record for record in state["inputs"] if record["role"] == "plan"]
    plans = payload.get("plans")
    if not isinstance(plans, list) or len(plans) != len(plan_inputs):
        raise ValueError("compiled plan count is invalid")
    for expected_order, (compiled, record) in enumerate(zip(plans, plan_inputs, strict=True)):
        if compiled.get("plan_id") != f"plan-{expected_order + 1:02d}":
            raise ValueError("compiled plan order is invalid")
        if compiled.get("source_sha256") != record["sha256"]:
            raise ValueError("compiled plan source digest is invalid")
        lines = _source_lines(record)
        for task in compiled.get("tasks", []):
            start = task["source_line_start"]
            end = task["source_line_end"]
            if not 1 <= start <= end <= len(lines):
                raise ValueError("compiled source span is invalid")
            selected = "".join(lines[start - 1:end]).encode("utf-8")
            if _sha256(selected) != task["source_text_sha256"]:
                raise ValueError("compiled source span digest is invalid")
        for exception in compiled.get("coordination_exceptions", []):
            start = exception["source_line_start"]
            end = exception["source_line_end"]
            selected = "".join(lines[start - 1:end]).encode("utf-8")
            if _sha256(selected) != exception["source_text_sha256"]:
                raise ValueError("coordination exception source span digest is invalid")
        unknowns = compiled.get("unknowns", [])
        if any(str(item).startswith(SAFETY_UNKNOWN_PREFIXES) for item in unknowns):
            raise ValueError("compiled safety field is ambiguous")
    return payload


class CompiledIndexService:
    def __init__(self, *, compile_once: CompilerCallback) -> None:
        self.compile_once = compile_once
        self.compile_calls = 0

    def prepare(self, store: StateStore) -> Path:
        contract = default_operator_contract(store.state)
        contract_path = store.root / "operator-contract.json"
        contract_path.write_text(
            json.dumps(contract, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        contract_path.chmod(0o600)
        target = store.root / "compiled-run-index.json"
        if target.is_file():
            cached = json.loads(target.read_text(encoding="utf-8"))
            validate_compiled_index(cached, store.state, contract)
            return target.resolve()
        last_error: ValueError | None = None
        for repair in (False, True):
            self.compile_calls += 1
            candidate = self.compile_once(store, contract, repair)
            try:
                validated = validate_compiled_index(candidate, store.state, contract)
                break
            except ValueError as exc:
                last_error = exc
        else:
            assert last_error is not None
            raise last_error
        encoded = json.dumps(validated, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_COMPILER_OUTPUT_BYTES:
            raise ValueError("compiled index exceeds size limit")
        target.write_bytes(encoded)
        target.chmod(0o600)
        return target.resolve()
```

The strict JSON schema must mirror these fields and reject additional properties. Add exact sub-schemas for task spans, verification source spans, capability references, `unknowns` strings, `execution_advisories`, and `coordination_exceptions`. Each verification entry contains a unique `command_id`, exact argv array, allowed branch phases, a `deterministic` boolean, mutable-input policy, at most 64 worktree-relative required artifact paths, and exact source line start/end/digest. If the plan expresses a command only as ambiguous shell prose, preserve it as an `unknown` and do not authorize cached helper execution for it. `execution_advisories` may contain only `split_or_checkpoint_required` and `handoff_to_waygent`; advisories are derivative guidance and never bypass the approved hard budgets or automatically start another orchestrator. A coordination exception contains `task_id`, `role`, `fork_turns` fixed to `all`, exact source line start/end/digest, and a bounded reason code. It is the only later authority for accepting `fork_turns=all` telemetry.

The compiler emits `split_or_checkpoint_required` when source-backed task/coordination scope is likely to exceed the default slice/checkpoint/wall/launch budget. It may emit `handoff_to_waygent` only when source spans jointly require host-resource control, a moving integration target, and long multi-agent coordination. Unknown task count keeps default budgets and no fabricated advisory.

Before the compiler callback, sum the exact snapshot byte lengths plus canonical operator-contract bytes and reject input above `MAX_COMPILER_INPUT_BYTES`. The compiler may never truncate authoritative input to fit.

Extend format-2 state with `operator_contract_path`, `operator_contract_sha256`, `compiled_run_index_path`, and `compiled_run_index_sha256`, all initially `None` and validated as private regular files when present.

- [ ] **Step 4: Run source-validation, cache, and state tests**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_compiled_index_requires_exact_plan_source_spans \
  evals.check_runner.SequentialRunnerTest.test_optional_compiler_ambiguity_is_preserved_as_unknown \
  evals.check_runner.SequentialRunnerTest.test_snapshots_preserve_spec_and_plan_order -v
```

Expected: PASS; a second `prepare` call reuses the exact index without incrementing compiler calls.

- [ ] **Step 5: Commit the compiler domain contract**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/templates/compiled-run-index.schema.json \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): compile private run indexes"
```

### Task 2: Add The Bounded Read-Only Compiler Launcher

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Test: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**
- Consumes: run root, immutable snapshots, operator contract, compiled-index schema.
- Produces: `CodexLauncher.compile_index(store, contract, repair) -> dict[str, object]` using `read-only`, no `--add-dir`, one turn, and the existing bounded process lifecycle.

- [ ] **Step 1: Write a RED command/prompt test for compiler isolation**

```python
def test_compiler_launcher_is_read_only_bounded_and_has_no_git_add_dir(self) -> None:
    launcher = self.runner().launcher
    request = launcher.compiler_request(
        run_root=self.root,
        snapshot_paths=[self.plan(1, "completed")],
        contract_path=self.root / "operator-contract.json",
        result_path=self.root / "compiled-result.json",
        repair=False,
    )
    self.assertIn("read-only", request.command)
    self.assertNotIn("--add-dir", request.command)
    self.assertIn("--ephemeral", request.command)
    self.assertEqual(request.timeout_seconds, 300)
    self.assertIn("Do not modify files", request.prompt)
    self.assertIn("Do not spawn subagents", request.prompt)
```

- [ ] **Step 2: Run the launcher test and confirm the missing interface**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_compiler_launcher_is_read_only_bounded_and_has_no_git_add_dir -v
```

Expected: FAIL because `compiler_request` is not defined.

- [ ] **Step 3: Extract a behavior-preserving structured process request**

Add the request type:

```python
@dataclass(frozen=True)
class StructuredLaunchRequest:
    command: list[str]
    cwd: Path
    prompt: str
    result_path: Path
    log_path: Path
    timeout_seconds: float
```

Move the existing selector, two-pipe drain, usage filter, process-group cleanup, result read, and bounded-log body into `_launch_structured(request, lock_fd)`. Keep the body byte-for-byte equivalent except that it reads values from `request`. Make `launch(...)` build a workspace-write request and delegate to that helper.

Add `compiler_request(...)` and `compile_index(...)`. A repair request receives the immutable first output path and its validation error code; it does not rely on conversational memory:

```python
def compiler_request(
    self,
    *,
    run_root: Path,
    snapshot_paths: Sequence[Path],
    contract_path: Path,
    result_path: Path,
    repair: bool,
    previous_output_path: Path | None,
    previous_error_code: str | None,
) -> StructuredLaunchRequest:
    schema = self.schema_path.parent / "compiled-run-index.schema.json"
    attempt = 2 if repair else 1
    log_path = run_root / "logs" / f"compiler-attempt-{attempt}.log"
    command = [
        self.executable,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--json",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(result_path),
        "-C",
        str(run_root),
        "-",
    ]
    prompt = "\n".join([
        "Compile immutable CPE input snapshots into the strict run-index schema.",
        "Do not modify files, execute Git mutations, access the network, or spawn subagents.",
        f"OPERATOR_CONTRACT: {contract_path}",
        f"REPAIR_PREVIOUS_OUTPUT: {'yes' if repair else 'no'}",
        f"PREVIOUS_OUTPUT_PATH: {previous_output_path or 'none'}",
        f"PREVIOUS_ERROR_CODE: {previous_error_code or 'none'}",
        "SNAPSHOTS:",
        *(f"- {path}" for path in snapshot_paths),
        "Return only the strict schema object.",
        "",
    ])
    return StructuredLaunchRequest(
        command=command,
        cwd=run_root,
        prompt=prompt,
        result_path=result_path,
        log_path=log_path,
        timeout_seconds=300.0,
    )
```

`compile_index` calls `_launch_structured`, requires exit 0 and a dictionary payload, enforces the 1 MiB result limit, and returns the payload. Preserve an invalid first output as `results/compiler-attempt-1.json` with mode `0400`; the second attempt reads that file and writes `results/compiler-attempt-2.json`. Never overwrite the first attempt. Update fake Codex to detect `compiled-run-index.schema.json` in arguments and emit a valid exact-span index without touching Git or worktree files.

- [ ] **Step 4: Run compiler isolation and all process lifecycle tests**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_compiler_launcher_is_read_only_bounded_and_has_no_git_add_dir \
  evals.check_runner.SequentialRunnerTest.test_timeout_and_exception_paths_drain_both_pipes \
  evals.check_runner.SequentialRunnerTest.test_timeout_kills_the_complete_process_group \
  evals.check_runner.SequentialRunnerTest.test_completed_child_with_live_descendant_is_rejected_and_cleaned -v
```

Expected: PASS; both compiler and plan launches retain process-group and bounded-pipe behavior.

- [ ] **Step 5: Commit compiler launch isolation**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): launch bounded read only compilers"
```

### Task 3: Seal Bounded Execution Evidence

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`
- Create: `skills/kws-codex-plan-executor/templates/execution-ledger.schema.json`
- Test: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**
- Consumes: worktree `.superpowers/sdd/execution-ledger.jsonl`, plan ID, accepted HEAD.
- Produces: `append_execution_event(...)`, `validate_execution_ledger(...)`, `ingest_plan_evidence(...) -> dict[str, object]`, sealed `evidence/<plan-id>/evidence-manifest.json`.

- [ ] **Step 1: Write RED tests for trust levels, size limits, symlinks, and cleanup survival**

```python
def test_plan_evidence_survives_worktree_removal(self) -> None:
    worktree = self.root / "evidence-worktree"
    ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    append_execution_event(
        ledger,
        {
            "event_id": "event-1",
            "source": "child_attested",
            "plan_id": "plan-01",
            "category": "task",
            "action": "completed",
            "result": "pass",
            "evidence_refs": [],
        },
    )
    manifest = ingest_plan_evidence(
        run_root=self.root / "run",
        worktree=worktree,
        plan_id="plan-01",
        accepted_head="1" * 40,
    )
    shutil.rmtree(worktree)
    archived = self.root / "run" / "evidence" / "plan-01"
    self.assertEqual(manifest["accepted_head"], "1" * 40)
    self.assertTrue((archived / "execution-ledger.jsonl").is_file())
    self.assertEqual((archived / "execution-ledger.jsonl").stat().st_mode & 0o777, 0o400)
```

Add sibling tests that reject a symlinked ledger, 129 files, one file over 1 MiB, and aggregate content over 8 MiB.

The strict execution-ledger schema is created in this wave for all later waves. Its base required fields are `schema_version=1`, `event_id`, `source`, `plan_id`, `category`, `action`, `result`, and `evidence_refs`; it rejects additional properties outside the selected category variant. Supported categories are `task`, `review`, `finding_fix`, `verification`, `capability`, `checkpoint`, `blocker`, `obligation`, and `coordination`. Category variants add only their stable identifiers/digests/durations; no variant accepts prompt text, transcript text, source bodies, raw environment values, or raw stdout/stderr.

Add schema tests for one valid event per category plus rejection of duplicate event IDs, unknown categories/actions, unknown properties, invalid trust levels, absolute/escaping evidence references, and child events that claim `source="parent_observed"`. Worktree ledger producers may emit `child_attested` or `hypothesis`; CPE creates `parent_observed` and `derived` events in the private run root.

- [ ] **Step 2: Run the evidence tests and confirm the missing-module RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_plan_evidence_survives_worktree_removal -v
```

Expected: ERROR because `cpe_runtime.evidence` does not exist.

- [ ] **Step 3: Implement bounded ledger append and evidence sealing**

Create `evidence.py` with these constants and public functions:

```python
MAX_EVIDENCE_FILES = 128
MAX_EVIDENCE_FILE_BYTES = 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 8 * 1024 * 1024
TRUST_LEVELS = {"parent_observed", "child_attested", "derived", "hypothesis"}


def append_execution_event(path: Path, event: dict[str, object]) -> None:
    if event.get("source") not in TRUST_LEVELS:
        raise ValueError("execution event trust level is invalid")
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    if len(line.encode("utf-8")) > 16_384:
        raise ValueError("execution event is too large")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("execution ledger must be a regular file")
        os.write(descriptor, line.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_execution_ledger(path: Path, *, expected_plan_id: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
        if len(line) > 16_384:
            raise ValueError(f"execution event {line_number} is too large")
        event = json.loads(line)
        validate_execution_event_schema(event)
        if event["plan_id"] != expected_plan_id:
            raise ValueError("execution event plan identity is invalid")
        if event["event_id"] in seen_ids:
            raise ValueError("execution event id is duplicated")
        seen_ids.add(event["event_id"])
        events.append(event)
    return events


def ingest_plan_evidence(
    *,
    run_root: Path,
    worktree: Path,
    plan_id: str,
    accepted_head: str,
) -> dict[str, object]:
    source_root = worktree / ".superpowers" / "sdd"
    candidates = [source_root / "execution-ledger.jsonl"]
    target_root = run_root / "evidence" / plan_id
    target_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    files: list[dict[str, object]] = []
    total = 0
    for source in candidates:
        if source.is_symlink() or not source.is_file():
            raise ValueError("required evidence is missing or redirected")
        payload = source.read_bytes()
        if len(payload) > MAX_EVIDENCE_FILE_BYTES:
            raise ValueError("evidence file exceeds size limit")
        total += len(payload)
        if total > MAX_EVIDENCE_TOTAL_BYTES:
            raise ValueError("evidence bundle exceeds size limit")
        target = target_root / source.name
        target.write_bytes(payload)
        target.chmod(0o400)
        files.append({
            "path": target.name,
            "byte_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    manifest = {
        "format_version": 2,
        "plan_id": plan_id,
        "accepted_head": accepted_head,
        "files": files,
        "total_byte_length": total,
    }
    manifest_path = target_root / "evidence-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    manifest_path.chmod(0o400)
    return manifest
```

Call `validate_execution_ledger` before accepting references. Expand `candidates` only with schema-validated ledger-referenced files, enforce 128-file and aggregate limits before copying, reject traversal/symlinks, and remove a partially created target directory on any failure. Copy to a private staging directory, fsync files and directories, atomically rename it to `evidence/<plan-id>`, then seal accepted files and the manifest to `0400`.

- [ ] **Step 4: Run evidence safety tests**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_plan_evidence_survives_worktree_removal \
  evals.check_runner.SequentialRunnerTest.test_existing_capsule_rejects_unsafe_mode_and_symlink \
  evals.check_runner.SequentialRunnerTest.test_large_log_retains_only_a_bounded_tail -v
```

Expected: PASS; evidence and log limits remain independent.

- [ ] **Step 5: Commit evidence sealing**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py \
  skills/kws-codex-plan-executor/templates/execution-ledger.schema.json \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): seal bounded execution evidence"
```

### Task 4: Generate Trust-Labelled Optimization Reports And Integrate Preparation

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Create: `skills/kws-codex-plan-executor/templates/optimization-report.schema.json`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Test: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**
- Consumes: state, `events.jsonl`, sealed evidence manifests, compiler service.
- Produces: `build_optimization_report(...) -> dict[str, object]`, `write_optimization_reports(...) -> tuple[Path, Path]`, automatic `reports/optimization-report.{json,md}`.

- [ ] **Step 1: Write RED tests for lower-bound usage, trust labels, and automatic preparation**

```python
def test_report_marks_missing_usage_as_lower_bound(self) -> None:
    report = build_optimization_report(
        run_id="report-lower-bound",
        events=[
            {"action": "plan.attempt_finished", "source": "parent_observed", "duration_ms": 1000, "input_tokens": 41},
            {"action": "plan.attempt_finished", "source": "parent_observed", "duration_ms": 2000, "input_tokens": None},
        ],
        findings=[{
            "signal": "timeout",
            "source": "derived",
            "evidence_refs": ["events.jsonl:2"],
        }],
    )
    self.assertEqual(report["usage"]["observed_input_tokens"], 41)
    self.assertEqual(report["usage"]["unknown_attempt_count"], 1)
    self.assertEqual(report["usage"]["total_kind"], "lower_bound")
    self.assertEqual(report["findings"][0]["source"], "derived")

def test_run_prepares_index_before_worktree_and_reports_after_plan(self) -> None:
    runner = self.runner_with_fake_compiler()
    result = runner.run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "completed")],
        run_id="prepared-run",
    )
    root = self.home / "orchestrator" / "prepared-run"
    self.assertEqual(result["status"], "completed")
    self.assertTrue((root / "compiled-run-index.json").is_file())
    self.assertTrue((root / "evidence" / "plan-01" / "evidence-manifest.json").is_file())
    self.assertTrue((root / "reports" / "optimization-report.json").is_file())
```

- [ ] **Step 2: Run both tests and confirm the missing reporting/integration RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_report_marks_missing_usage_as_lower_bound \
  evals.check_runner.SequentialRunnerTest.test_run_prepares_index_before_worktree_and_reports_after_plan -v
```

Expected: ERROR because reporting and integrated preparation are not defined.

- [ ] **Step 3: Implement report generation and runner wiring**

Create `reporting.py` with:

```python
MAX_REPORT_BYTES = 1024 * 1024


def build_optimization_report(
    *,
    run_id: str,
    events: list[dict[str, object]],
    findings: list[dict[str, object]],
) -> dict[str, object]:
    observed = 0
    unknown = 0
    duration = 0
    for event in events:
        if event.get("action") != "plan.attempt_finished":
            continue
        duration += int(event.get("duration_ms") or 0)
        tokens = event.get("input_tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool):
            observed += tokens
        else:
            unknown += 1
    return {
        "format_version": 2,
        "run_id": run_id,
        "usage": {
            "observed_input_tokens": observed,
            "unknown_attempt_count": unknown,
            "total_kind": "exact" if unknown == 0 else "lower_bound",
        },
        "duration_ms": duration,
        "findings": findings,
    }


def write_optimization_reports(
    *,
    reports_root: Path,
    report: dict[str, object],
) -> tuple[Path, Path]:
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("optimization report exceeds size limit")
    json_path = reports_root / "optimization-report.json"
    md_path = reports_root / "optimization-report.md"
    atomic_private_write(json_path, encoded)
    md = render_optimization_markdown(report)
    if len(md.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("optimization markdown exceeds size limit")
    atomic_private_write(md_path, md.encode("utf-8"))
    return json_path, md_path
```

`atomic_private_write` must use a sibling temporary regular file, `0600`, fsync, `os.replace`, and parent-directory fsync. Derivative Markdown failure remains non-authoritative; JSON report failure is recorded and fails the report update without corrupting the prior report.

The Markdown renderer must include symptom/signal, source trust level, impact, action, outcome, recurrence, lower-bound usage, recommendation, and evidence references without embedding raw logs.

In `SequentialRunner.__init__`, inject `CompiledIndexService`; default it to a service backed by `self.launcher.compile_index`. In `_initialize_run`, persist snapshots and state first, prepare the index, store its path/digest, transition `preparing -> ready`, then create the worktree. If optional fields are unknown, continue. If safety fields fail validation, return failed without a plan-controller launch.

Pass `COMPILED_RUN_INDEX` and `EXECUTION_LEDGER` markers in the plan prompt. On completed plan, call `ingest_plan_evidence` before sealing the result or advancing state. After every terminal plan result and at run completion, rebuild both report files. A Markdown-render failure appends `report.derivative_failed` and preserves product completion; JSON/state/evidence failure fails closed.

Extend completed fake-controller scenarios to create a valid `.superpowers/sdd/execution-ledger.jsonl` containing one `task`, one `review`, and one `verification` child-attested event with unique IDs and safe evidence references. Create the referenced tiny receipt files as regular files inside that directory. This keeps the integrated eval model-free while exercising the real schema, ingest, hash, and seal path.

- [ ] **Step 4: Run focused integration and the complete gate**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_report_marks_missing_usage_as_lower_bound \
  evals.check_runner.SequentialRunnerTest.test_run_prepares_index_before_worktree_and_reports_after_plan \
  evals.check_runner.SequentialRunnerTest.test_two_plans_execute_sequentially_in_one_worktree -v
./evals/run.sh
```

Expected: focused tests PASS; full gate PASS below 15 seconds with fake compiler calls only.

- [ ] **Step 5: Update tracked inventory and commit Wave 1 integration**

Add every new module and schema to README `Tracked Inventory`; do not change the public version or claim Wave 2-4 behavior. Then commit:

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/compiler.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/templates/compiled-run-index.schema.json \
  skills/kws-codex-plan-executor/templates/execution-ledger.schema.json \
  skills/kws-codex-plan-executor/templates/optimization-report.schema.json \
  skills/kws-codex-plan-executor/evals/check_runner.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/README.md
git commit -m "feat(cpe): record compiled execution evidence"
```

## Execution Order

- Sequential/shared-core tasks: Task 1 -> Task 2 -> Task 3 -> Task 4.
- Parallel-safe work: schema drafting may be reviewed in parallel after its producing task commits; implementation remains sequential.
- Human approval gates: none.

## Final Verification

From `skills/kws-codex-plan-executor`:

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py run --help
python3 scripts/cpe.py inspect --help
```

Expected: all commands exit 0; compiler tests use only fake Codex; gate stays below 15 seconds.

From repository root:

```bash
git diff --check
git status --short --branch --untracked-files=all
```

Expected: clean tracked worktree after commits and no runtime artifacts under the repository.

## Review

Use `code_review.md`. Reject any implementation that makes the compiled index authoritative, stores the raw user prompt/transcript, writes evidence outside the private run root, or adds a user-authored bundle requirement.
