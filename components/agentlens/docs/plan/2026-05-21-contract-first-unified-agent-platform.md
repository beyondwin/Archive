# Waygent Contract-First Unified Agent Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Waygent contract reconciliation slice that must land before the Rust workspace skeleton.

**Architecture:** This plan keeps the current Python AgentLens and AgentRunway runtime in place and proves the Waygent unified contract there first. It adds a canonical orchestrator event contract, schema-version normalization, local-first event ordering, AgentRunway journal backfill, and deterministic tests so the later Rust `agent-contracts` and `agent-store` crates have a stable source contract to port.

**Tech Stack:** Python 3.12, Typer, JSON Schema Draft 2020-12, pytest, JSONL artifacts, SQLite read index, existing AgentLens and AgentRunway test fixtures.

---

## Source Spec

- Design spec: `AgentLens/docs/spec/2026-05-21-contract-first-unified-agent-platform-design.md`
- Superseded plan until revised: `AgentLens/docs/plan/2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md`

## Scope Boundary

This plan does not create `Cargo.toml`, Rust crates, `apps/lens-web`, or any new Rust code. It does not delete Python sources. It does not rename existing CLI commands. It creates the compatibility contract and verification surface that the Rust skeleton must follow.

## Target File Structure

Create:

```text
AgentLens/src/agentlens/schema/jsonschema/event.v3.schema.json
AgentLens/src/agentlens/schema/jsonschema/run.v3.schema.json
AgentLens/src/agentlens/schema/jsonschema/final.v3.schema.json
AgentLens/src/agentlens/store/normalization.py
AgentLens/src/agentlens/store/agentrunway_journal.py
AgentLens/src/agentlens/commands/import_agentrunway_journal.py
AgentLens/tests/unit/test_unified_contract_schema.py
AgentLens/tests/unit/test_contract_normalization.py
AgentLens/tests/integration/test_import_agentrunway_journal.py
AgentLens/tests/fixtures/schemas/v3/valid/run.json
AgentLens/tests/fixtures/schemas/v3/valid/event.json
AgentLens/tests/fixtures/schemas/v3/valid/final.json
AgentLens/tests/fixtures/schemas/v3/invalid/event_legacy_kws_cpe.json
AgentLens/tests/fixtures/schemas/v3/invalid/event_missing_orchestrator_run_id.json
AgentLens/tests/fixtures/schemas/v3/invalid/event_unbounded_summary.json
```

Modify:

```text
AgentLens/src/agentlens/schema/validate.py
AgentLens/src/agentlens/store/event_query.py
AgentLens/src/agentlens/store/query.py
AgentLens/src/agentlens/commands/events.py
AgentLens/src/agentlens/commands/_format.py
AgentLens/src/agentlens/cli.py
AgentLens/src/agentlens/evaluator/checks.py
AgentLens/src/agentlens/evaluator/engine.py
AgentLens/src/agentlens/evaluator/agentrunway_events.py
AgentLens/src/agentlens/evaluator/agentrunway_v2.py
skills/agent-runway/scripts/agentrunway/events.py
skills/agent-runway/evals/test_agentlens_cli_emitter.py
skills/agent-runway/evals/test_event_journal_agentlens.py
AgentLens/docs/contract.md
AgentLens/docs/cli.md
AgentLens/docs/security.md
AgentLens/docs/plan/README.md
```

Do not modify:

```text
Cargo.toml
crates/
apps/
AgentLens/web/src/
```

## Task 1: Add Unified v3 Contract Schemas

```yaml agentrunway-task
task_id: task_001
title: Add Unified v3 Contract Schemas
risk: high
phase: implementation
dependencies: []
spec_refs: [S1.4, S1.5, S1.10, S1.12]
file_claims:
  - {path: AgentLens/src/agentlens/schema/validate.py, mode: owned}
  - {path: AgentLens/src/agentlens/schema/jsonschema/event.v3.schema.json, mode: owned}
  - {path: AgentLens/src/agentlens/schema/jsonschema/run.v3.schema.json, mode: owned}
  - {path: AgentLens/src/agentlens/schema/jsonschema/final.v3.schema.json, mode: owned}
  - {path: AgentLens/tests/unit/test_unified_contract_schema.py, mode: owned}
  - {path: AgentLens/tests/fixtures/schemas/v3/**, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_unified_contract_schema.py tests/unit/test_schema_v2_validation.py -q
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `AgentLens/src/agentlens/schema/jsonschema/event.v3.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/run.v3.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/final.v3.schema.json`
- Create: `AgentLens/tests/unit/test_unified_contract_schema.py`
- Create: v3 valid and invalid fixtures under `AgentLens/tests/fixtures/schemas/v3/`
- Modify: `AgentLens/src/agentlens/schema/validate.py`

- [ ] **Step 1: Write failing v3 schema tests**

Create `AgentLens/tests/unit/test_unified_contract_schema.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from agentlens.schema import SchemaError, load_schema, validate_doc


V3_SCHEMA_NAMES = ["run_v3", "event_v3", "final_v3"]

ROOT = Path(__file__).resolve().parents[2]
VALID = ROOT / "tests" / "fixtures" / "schemas" / "v3" / "valid"
INVALID = ROOT / "tests" / "fixtures" / "schemas" / "v3" / "invalid"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", V3_SCHEMA_NAMES)
def test_v3_schema_loads_and_is_draft_2020_12(name: str) -> None:
    schema = load_schema(name)  # type: ignore[arg-type]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("fixture", "schema_name"),
    [
        ("run.json", "run_v3"),
        ("event.json", "event_v3"),
        ("final.json", "final_v3"),
    ],
)
def test_v3_valid_fixtures_validate(fixture: str, schema_name: str) -> None:
    validate_doc(_load(VALID / fixture), schema_name=schema_name)


def test_v3_schema_inference_uses_namespace_mapping() -> None:
    validate_doc(_load(VALID / "run.json"))
    validate_doc(_load(VALID / "event.json"))
    validate_doc(_load(VALID / "final.json"))


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("event_legacy_kws_cpe.json", "event_type"),
        ("event_missing_orchestrator_run_id.json", "orchestrator_run_id"),
        ("event_unbounded_summary.json", "summary"),
    ],
)
def test_v3_invalid_event_fixtures_raise(fixture: str, expected: str) -> None:
    with pytest.raises(SchemaError) as exc_info:
        validate_doc(_load(INVALID / fixture), schema_name="event_v3")
    assert expected in "\n".join(exc_info.value.errors)
```

- [ ] **Step 2: Add fixture directories and v3 valid fixtures**

Create `AgentLens/tests/fixtures/schemas/v3/valid/event.json`:

```json
{
  "schema": "agentlens.event.v3",
  "event_id": "evt_000001",
  "agentlens_run_id": "agentlens-run-1",
  "orchestrator_run_id": "agentrunway-run-1",
  "producer": {
    "name": "agentrunway",
    "kind": "orchestrator",
    "version": "0.1.0"
  },
  "event_type": "agentrunway.task_result",
  "occurred_at": "2026-05-21T00:00:00Z",
  "sequence": 1,
  "phase": "worker",
  "outcome": "success",
  "severity": "info",
  "trust_impact": "supports_success",
  "summary": "Task completed with bounded evidence.",
  "payload": {
    "task_id": "task_001",
    "status": "completed"
  }
}
```

Create `AgentLens/tests/fixtures/schemas/v3/valid/run.json`:

```json
{
  "schema": "agentlens.run.v3",
  "run_id": "agentlens-run-1",
  "workspace_id": "ws_0000000000000001",
  "parent_run_id": null,
  "started_at": "2026-05-21T00:00:00Z",
  "run_kind": "orchestrator",
  "producer": {
    "name": "agentrunway",
    "kind": "orchestrator",
    "version": "0.1.0"
  },
  "orchestrator_run_id": "agentrunway-run-1",
  "recording": {
    "mode": "minimal",
    "adapter": "agentrunway"
  },
  "trust_contract": {
    "source": "waygent",
    "legacy_namespaces_supported": false,
    "event_schema": "agentlens.event.v3"
  },
  "meta": {}
}
```

Create `AgentLens/tests/fixtures/schemas/v3/valid/final.json`:

```json
{
  "schema": "agentlens.final.v3",
  "run_id": "agentlens-run-1",
  "orchestrator_run_id": "agentrunway-run-1",
  "ended_at": "2026-05-21T00:01:00Z",
  "claimed_outcome": "success",
  "summary": "Run completed with verification evidence.",
  "changed_files": [],
  "verification": [
    {
      "kind": "test",
      "command_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "status": "passed",
      "excerpt": "1 passed"
    }
  ],
  "residual_risks": []
}
```

- [ ] **Step 3: Add invalid v3 fixtures**

Create `AgentLens/tests/fixtures/schemas/v3/invalid/event_legacy_kws_cpe.json`:

```json
{
  "schema": "agentlens.event.v3",
  "event_id": "evt_000001",
  "agentlens_run_id": "agentlens-run-1",
  "orchestrator_run_id": "legacy-run-1",
  "producer": {"name": "kws-cpe", "kind": "orchestrator", "version": "2.20.0"},
  "event_type": "kws-cpe.task_result",
  "occurred_at": "2026-05-21T00:00:00Z",
  "sequence": 1,
  "phase": "worker",
  "outcome": "success",
  "severity": "info",
  "trust_impact": "supports_success",
  "summary": "Legacy namespace is rejected for new runtime events.",
  "payload": {}
}
```

Create `AgentLens/tests/fixtures/schemas/v3/invalid/event_missing_orchestrator_run_id.json` by copying the valid event and removing `orchestrator_run_id`.

Create `AgentLens/tests/fixtures/schemas/v3/invalid/event_unbounded_summary.json` by copying the valid event and setting `summary` to a 1201-character string.

- [ ] **Step 4: Add v3 schemas**

Create the three schema files with these required properties:

- `event.v3.schema.json`: require `schema`, `event_id`, `agentlens_run_id`, `orchestrator_run_id`, `producer`, `event_type`, `occurred_at`, `sequence`, `phase`, `outcome`, `severity`, `trust_impact`, `summary`, and `payload`; reject `kws-cpe.*`, `kws-cme.*`, and `kws.orchestrator.*` event families; allow `agentrunway.*` and `waygent.*`.
- `run.v3.schema.json`: require `run_kind`, `producer`, `orchestrator_run_id`, `recording`, and `trust_contract`.
- `final.v3.schema.json`: use `claimed_outcome` and `orchestrator_run_id`.

Use `additionalProperties: false` at the top level and for `producer`, `recording`, and `trust_contract`.

- [ ] **Step 5: Register v3 schemas in `validate.py`**

Update `SchemaName`, `_SCHEMA_FILES`, and `_NAMESPACE_TO_NAME`:

```python
SchemaName = Literal[
    "run",
    "event",
    "final",
    "eval",
    "manifest",
    "run_v2",
    "event_v2",
    "final_v2",
    "eval_v2",
    "manifest_v2",
    "event_v3",
    "run_v3",
    "final_v3",
    "agentrunway_projection",
    "trust_report",
]
```

Add mappings:

```python
"run_v3": "run.v3.schema.json",
"event_v3": "event.v3.schema.json",
"final_v3": "final.v3.schema.json",
```

Add namespaces:

```python
"agentlens.run.v3": "run_v3",
"agentlens.event.v3": "event_v3",
"agentlens.final.v3": "final_v3",
```

- [ ] **Step 6: Run the targeted schema tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_unified_contract_schema.py tests/unit/test_schema_v2_validation.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/schema/validate.py \
  AgentLens/src/agentlens/schema/jsonschema/event.v3.schema.json \
  AgentLens/src/agentlens/schema/jsonschema/run.v3.schema.json \
  AgentLens/src/agentlens/schema/jsonschema/final.v3.schema.json \
  AgentLens/tests/unit/test_unified_contract_schema.py \
  AgentLens/tests/fixtures/schemas/v3
git commit -m "feat: add unified AgentLens contract schemas"
```

## Task 2: Add Version-Aware Contract Normalization

```yaml agentrunway-task
task_id: task_002
title: Add Version-Aware Contract Normalization
risk: high
phase: implementation
dependencies: [task_001]
spec_refs: [S1.8, S1.12]
file_claims:
  - {path: AgentLens/src/agentlens/store/normalization.py, mode: owned}
  - {path: AgentLens/src/agentlens/store/event_query.py, mode: owned}
  - {path: AgentLens/src/agentlens/commands/events.py, mode: owned}
  - {path: AgentLens/src/agentlens/store/query.py, mode: shared_append}
  - {path: AgentLens/src/agentlens/commands/_format.py, mode: shared_append}
  - {path: AgentLens/tests/unit/test_contract_normalization.py, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_contract_normalization.py tests/unit/test_event_query.py tests/integration/test_event_append.py -q
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `AgentLens/src/agentlens/store/normalization.py`
- Create: `AgentLens/tests/unit/test_contract_normalization.py`
- Modify: `AgentLens/src/agentlens/store/event_query.py`
- Modify: `AgentLens/src/agentlens/commands/events.py`
- Modify: `AgentLens/src/agentlens/store/query.py`
- Modify: `AgentLens/src/agentlens/commands/_format.py`

- [ ] **Step 1: Write normalization tests**

Create tests proving:

- v1 events expose canonical `event_type`, `occurred_at`, and `agentlens_run_id`;
- v2 events expose canonical `event_type`, `occurred_at`, and `agentlens_run_id`;
- v3 events expose canonical `orchestrator_run_id`;
- v1 final `agent_outcome` and v2/v3 final `claimed_outcome` normalize to one `claimed_outcome`;
- event ordering uses `occurred_at`, then `sequence`, then `agentlens_run_id`.

Use this test shape:

```python
from __future__ import annotations

from agentlens.store.normalization import (
    event_sort_key,
    normalize_event,
    normalize_final,
)


def test_normalize_v1_event_to_canonical_fields() -> None:
    event = normalize_event({
        "schema": "agentlens.event.v1",
        "event_id": "evt_aaa",
        "run_id": "run-v1",
        "ts": "2026-05-21T00:00:00Z",
        "type": "agentrunway.run_started",
        "payload": {"run_id": "ar-1"},
    })
    assert event["agentlens_run_id"] == "run-v1"
    assert event["orchestrator_run_id"] == "ar-1"
    assert event["event_type"] == "agentrunway.run_started"
    assert event["occurred_at"] == "2026-05-21T00:00:00Z"


def test_normalize_final_uses_claimed_outcome() -> None:
    assert normalize_final({"schema": "agentlens.final.v1", "agent_outcome": "success"})["claimed_outcome"] == "success"
    assert normalize_final({"schema": "agentlens.final.v2", "claimed_outcome": "failed"})["claimed_outcome"] == "failed"


def test_event_sort_key_uses_sequence_after_occurred_at() -> None:
    later_sequence = normalize_event({
        "schema": "agentlens.event.v3",
        "event_id": "evt_000002",
        "agentlens_run_id": "run",
        "orchestrator_run_id": "orch",
        "event_type": "agentrunway.task_result",
        "occurred_at": "2026-05-21T00:00:00Z",
        "sequence": 2,
        "producer": {"name": "agentrunway", "kind": "orchestrator", "version": "0.1.0"},
        "phase": "worker",
        "outcome": "success",
        "severity": "info",
        "trust_impact": "supports_success",
        "summary": "later",
        "payload": {},
    })
    earlier_sequence = {**later_sequence, "sequence": 1, "event_id": "evt_000001"}
    assert sorted([later_sequence, earlier_sequence], key=event_sort_key)[0]["sequence"] == 1
```

- [ ] **Step 2: Implement `normalization.py`**

Create `AgentLens/src/agentlens/store/normalization.py` with:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agentlens.time import parse_iso


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) and value else default


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    schema = _as_str(event.get("schema"), "agentlens.event.v1")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if schema == "agentlens.event.v1":
        event_type = _as_str(event.get("type"))
        occurred_at = _as_str(event.get("ts"))
        agentlens_run_id = _as_str(event.get("run_id"))
        orchestrator_run_id = _as_str(payload.get("run_id") or payload.get("agentrunway_run_id"), agentlens_run_id)
        sequence = event.get("sequence", 0)
    else:
        event_type = _as_str(event.get("event_type") or event.get("type"))
        occurred_at = _as_str(event.get("occurred_at") or event.get("ts"))
        agentlens_run_id = _as_str(event.get("agentlens_run_id") or event.get("run_id"))
        orchestrator_run_id = _as_str(event.get("orchestrator_run_id") or payload.get("run_id") or payload.get("agentrunway_run_id"), agentlens_run_id)
        sequence = event.get("sequence", 0)
    normalized = dict(event)
    normalized["event_type"] = event_type
    normalized["occurred_at"] = occurred_at
    normalized["agentlens_run_id"] = agentlens_run_id
    normalized["orchestrator_run_id"] = orchestrator_run_id
    normalized["sequence"] = int(sequence) if isinstance(sequence, int) else 0
    return normalized


def normalize_final(final: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(final, dict):
        return {"claimed_outcome": "unknown"}
    normalized = dict(final)
    normalized["claimed_outcome"] = _as_str(final.get("claimed_outcome") or final.get("agent_outcome"), "unknown")
    return normalized


def event_sort_key(event: dict[str, Any]) -> tuple[datetime, int, str, str]:
    normalized = normalize_event(event)
    try:
        occurred = parse_iso(normalized.get("occurred_at", ""))
    except (TypeError, ValueError):
        occurred = datetime.min.replace(tzinfo=timezone.utc)
    return (
        occurred,
        int(normalized.get("sequence") or 0),
        _as_str(normalized.get("agentlens_run_id")),
        _as_str(normalized.get("event_id")),
    )


def event_type(event: dict[str, Any]) -> str:
    return _as_str(normalize_event(event).get("event_type"))


def event_occurred_at(event: dict[str, Any]) -> str:
    return _as_str(normalize_event(event).get("occurred_at"))
```

- [ ] **Step 3: Update event query helpers**

Change `filter_since`, `glob_type_match` call sites, and `merge_events_by_ts_run` to use `normalize_event`, `event_sort_key`, and canonical `event_type`. Preserve existing v1 behavior.

- [ ] **Step 4: Update `agentlens events` command**

In `AgentLens/src/agentlens/commands/events.py`, filter against:

```python
from agentlens.store.normalization import event_type
```

Then replace `e.get("type", "")` with `event_type(e)` for both one-shot and follow mode filtering.

- [ ] **Step 5: Normalize final outcomes in query and formatting**

Use `normalize_final(final_doc)` where run rows and detail payloads derive outcome. Keep emitted key `agent_outcome` for `/api/v1` and existing CLI snapshots, but source it from canonical `claimed_outcome` when v2/v3 final docs are present.

- [ ] **Step 6: Run targeted tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_contract_normalization.py tests/unit/test_event_query.py tests/integration/test_event_append.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/store/normalization.py \
  AgentLens/src/agentlens/store/event_query.py \
  AgentLens/src/agentlens/commands/events.py \
  AgentLens/src/agentlens/store/query.py \
  AgentLens/src/agentlens/commands/_format.py \
  AgentLens/tests/unit/test_contract_normalization.py
git commit -m "feat: normalize AgentLens contract versions"
```

## Task 3: Make Evaluator And Projection Version-Aware

```yaml agentrunway-task
task_id: task_003
title: Make Evaluator And Projection Version-Aware
risk: high
phase: implementation
dependencies: [task_002]
spec_refs: [S1.8, S1.12]
file_claims:
  - {path: AgentLens/src/agentlens/evaluator/checks.py, mode: owned}
  - {path: AgentLens/src/agentlens/evaluator/engine.py, mode: owned}
  - {path: AgentLens/src/agentlens/evaluator/agentrunway_events.py, mode: owned}
  - {path: AgentLens/src/agentlens/evaluator/agentrunway_v2.py, mode: owned}
  - {path: AgentLens/tests/unit/test_agentrunway_events.py, mode: shared_append}
  - {path: AgentLens/tests/unit/test_evaluator_checks.py, mode: shared_append}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_agentrunway_events.py tests/unit/test_evaluator_checks.py tests/integration/test_eval_determinism.py -q
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `AgentLens/src/agentlens/evaluator/checks.py`
- Modify: `AgentLens/src/agentlens/evaluator/engine.py`
- Modify: `AgentLens/src/agentlens/evaluator/agentrunway_events.py`
- Modify: `AgentLens/src/agentlens/evaluator/agentrunway_v2.py`
- Modify tests listed above

- [ ] **Step 1: Add failing evaluator tests**

Add tests that cover:

- `check_schema_valid` validates `agentlens.run.v2` and `agentlens.final.v2` by inference, not hard-coded v1 schema names.
- AgentRunway v2 projection sorts by `occurred_at` and `sequence`.
- v3 events are accepted by the AgentRunway projector when `event_type` is `agentrunway.*`.
- `kws-cpe.*` and `kws-cme.*` produce legacy namespace projection issues.

- [ ] **Step 2: Update schema validation checks**

In `check_schema_valid`, replace hard-coded schema names:

```python
validate_doc(ctx.run, schema_name="run")
```

with:

```python
validate_doc(ctx.run)
```

Apply the same inference rule to `final` and `manifest`. Keep event line validation through `validate_event_line` so v1/v2/v3 event schemas are inferred per line.

- [ ] **Step 3: Normalize final outcome in `engine.py`**

Where evaluator logic reads `final["agent_outcome"]`, call `normalize_final(final_doc)["claimed_outcome"]`. Keep `agentlens.eval.v1` output for v1 run trees unless a separate eval schema migration task changes it.

- [ ] **Step 4: Fix AgentRunway event sorting**

In `agentrunway_events.py`, replace sorting on raw `ts` with `event_sort_key(event)` from `normalization.py`.

- [ ] **Step 5: Keep projection issues explicit**

In `agentrunway_v2.py`, treat these as legacy:

```python
("kws-cpe.", "kws-cme.", "kws.orchestrator.")
```

Do not mark `waygent.*` as legacy. It is reserved for the future single orchestrator path.

- [ ] **Step 6: Run evaluator tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_agentrunway_events.py tests/unit/test_evaluator_checks.py tests/integration/test_eval_determinism.py -q
```

Expected: all tests pass and deterministic eval snapshots remain stable except for intended normalized outcome fields.

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/evaluator/checks.py \
  AgentLens/src/agentlens/evaluator/engine.py \
  AgentLens/src/agentlens/evaluator/agentrunway_events.py \
  AgentLens/src/agentlens/evaluator/agentrunway_v2.py \
  AgentLens/tests/unit/test_agentrunway_events.py \
  AgentLens/tests/unit/test_evaluator_checks.py
git commit -m "feat: evaluate normalized AgentLens contracts"
```

## Task 4: Make AgentRunway Event Journal Local-First

```yaml agentrunway-task
task_id: task_004
title: Make AgentRunway Event Journal Local-First
risk: high
phase: implementation
dependencies: [task_003]
spec_refs: [S1.7, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/events.py, mode: owned}
  - {path: skills/agent-runway/evals/test_event_journal_agentlens.py, mode: owned}
  - {path: skills/agent-runway/evals/test_agentlens_cli_emitter.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_event_journal_agentlens.py evals/test_agentlens_cli_emitter.py -q
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/events.py`
- Modify: `skills/agent-runway/evals/test_event_journal_agentlens.py`
- Modify: `skills/agent-runway/evals/test_agentlens_cli_emitter.py`

- [ ] **Step 1: Write failing local-first ordering test**

Add a fake emitter that raises after the local event should be written:

```python
class FailingEmitter:
    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        raise RuntimeError("agentlens offline")
```

Assert that:

- `events.jsonl` contains the event;
- the DB outbox status is `agentlens_failed`;
- the local event payload contains `agentlens_error`;
- the raised emitter does not make `EventJournal.record()` raise.

- [ ] **Step 2: Reorder `EventJournal.record()`**

Change event persistence order to:

1. insert pending row;
2. build redacted local payload;
3. append v2 envelope to `events.jsonl`;
4. attempt external AgentLens emission;
5. update DB row status and error.

Keep the local JSONL event id stable by using the DB event id for both local and external envelopes.

- [ ] **Step 3: Preserve bounded payload behavior**

Keep `_bound_payload`, redaction, and v2 envelope construction. Do not let external AgentLens failure change the local `events.jsonl` line into invalid JSON.

- [ ] **Step 4: Run AgentRunway event tests**

Run:

```bash
cd skills/agent-runway
PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_event_journal_agentlens.py evals/test_agentlens_cli_emitter.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/events.py \
  skills/agent-runway/evals/test_event_journal_agentlens.py \
  skills/agent-runway/evals/test_agentlens_cli_emitter.py
git commit -m "fix: persist AgentRunway events before external emit"
```

## Task 5: Add AgentRunway Journal Backfill Import

```yaml agentrunway-task
task_id: task_005
title: Add AgentRunway Journal Backfill Import
risk: high
phase: implementation
dependencies: [task_004]
spec_refs: [S1.7, S1.9.1, S1.12]
file_claims:
  - {path: AgentLens/src/agentlens/store/agentrunway_journal.py, mode: owned}
  - {path: AgentLens/src/agentlens/commands/import_agentrunway_journal.py, mode: owned}
  - {path: AgentLens/src/agentlens/cli.py, mode: shared_append}
  - {path: AgentLens/tests/integration/test_import_agentrunway_journal.py, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/integration/test_import_agentrunway_journal.py tests/integration/test_event_append.py -q
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `AgentLens/src/agentlens/store/agentrunway_journal.py`
- Create: `AgentLens/src/agentlens/commands/import_agentrunway_journal.py`
- Create: `AgentLens/tests/integration/test_import_agentrunway_journal.py`
- Modify: `AgentLens/src/agentlens/cli.py`

- [ ] **Step 1: Write failing import tests**

Create a temp AgentRunway run directory containing local `events.jsonl` with two `agentlens.event.v2` events. Assert that:

- `agentlens import agentrunway-journal --path <run_dir>` creates or updates an AgentLens run;
- duplicate import does not duplicate events;
- events are de-duplicated by `(producer.name, orchestrator_run_id, sequence)`;
- imported events validate through `validate_event_line`;
- import works when `agentlens_emit_health.last_status` is `agentlens_failed`.

- [ ] **Step 2: Implement journal reader**

Create `AgentLens/src/agentlens/store/agentrunway_journal.py` with pure helpers:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentlens.store.normalization import normalize_event


def read_agentrunway_events(run_dir: Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "events.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        events.append(normalize_event(event))
    return events


def dedupe_key(event: dict[str, Any]) -> tuple[str, str, int]:
    producer = event.get("producer") if isinstance(event.get("producer"), dict) else {}
    return (
        str(producer.get("name") or ""),
        str(event.get("orchestrator_run_id") or ""),
        int(event.get("sequence") or 0),
    )
```

- [ ] **Step 3: Implement Typer import command**

Create `AgentLens/src/agentlens/commands/import_agentrunway_journal.py` with a Typer app command named `agentrunway-journal`. The command accepts:

```text
--path <agentrunway-run-dir>
--run <agentlens-run-id optional>
--dry-run
```

Behavior:

- read the local AgentRunway journal;
- find or create an AgentLens container run for the `orchestrator_run_id`;
- append missing events through `append_event`;
- print JSON summary with `imported`, `skipped`, `run_id`, and `source_path_label`;
- never print absolute home paths.

- [ ] **Step 4: Register the import subcommand**

In `AgentLens/src/agentlens/cli.py`, import the new command module and attach it to the existing `import` Typer group.

- [ ] **Step 5: Run import tests**

Run:

```bash
cd AgentLens
python -m pytest tests/integration/test_import_agentrunway_journal.py tests/integration/test_event_append.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/store/agentrunway_journal.py \
  AgentLens/src/agentlens/commands/import_agentrunway_journal.py \
  AgentLens/src/agentlens/cli.py \
  AgentLens/tests/integration/test_import_agentrunway_journal.py
git commit -m "feat: import AgentRunway local journals"
```

## Task 6: Update API And CLI Read Models For Normalized Contracts

```yaml agentrunway-task
task_id: task_006
title: Update API And CLI Read Models For Normalized Contracts
risk: medium
phase: implementation
dependencies: [task_005]
spec_refs: [S1.8, S1.12]
file_claims:
  - {path: AgentLens/src/agentlens/web/routers/runs.py, mode: owned}
  - {path: AgentLens/src/agentlens/web/routers/meta.py, mode: owned}
  - {path: AgentLens/src/agentlens/commands/_format.py, mode: shared_append}
  - {path: AgentLens/tests/integration/test_web_e2e_run_detail.py, mode: shared_append}
  - {path: AgentLens/tests/integration/test_web_e2e_meta.py, mode: shared_append}
  - {path: AgentLens/tests/integration/test_format_json_snapshot.py, mode: shared_append}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/integration/test_web_e2e_run_detail.py tests/integration/test_web_e2e_meta.py tests/integration/test_format_json_snapshot.py -q
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: web routers and JSON format projectors
- Modify: integration tests listed above

- [ ] **Step 1: Add failing API tests for v2/v3 normalized output**

Seed v2 or v3 run fixtures and assert:

- detail endpoint returns canonical `agent_outcome` for `/api/v1` compatibility;
- payload also includes `claimed_outcome` when source final uses v2/v3;
- `/api/v1/runs/{run_id}/events` returns valid NDJSON for v2/v3 events;
- `/api/v1/meta` includes `supported_run_schemas` and `supported_event_schemas`.

- [ ] **Step 2: Update run detail projection**

Use `normalize_final(final_doc)` in `_detail_payload`. Preserve existing `/api/v1` keys, and add these additive keys:

```python
payload["claimed_outcome"] = normalized_final["claimed_outcome"]
payload["schema_versions"] = {
    "run": run_doc.get("schema"),
    "final": final_doc.get("schema"),
    "events": "mixed",
}
```

- [ ] **Step 3: Update meta endpoint**

Return additive schema support metadata:

```json
{
  "supported_run_schemas": ["agentlens.run.v1", "agentlens.run.v2", "agentlens.run.v3"],
  "supported_event_schemas": ["agentlens.event.v1", "agentlens.event.v2", "agentlens.event.v3"],
  "supported_final_schemas": ["agentlens.final.v1", "agentlens.final.v2", "agentlens.final.v3"]
}
```

- [ ] **Step 4: Run API and snapshot tests**

Run:

```bash
cd AgentLens
python -m pytest tests/integration/test_web_e2e_run_detail.py tests/integration/test_web_e2e_meta.py tests/integration/test_format_json_snapshot.py -q
```

Expected: all tests pass. If snapshots change because additive keys are emitted, update only the affected golden files and mention that in the commit message body.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/runs.py \
  AgentLens/src/agentlens/web/routers/meta.py \
  AgentLens/src/agentlens/commands/_format.py \
  AgentLens/tests/integration/test_web_e2e_run_detail.py \
  AgentLens/tests/integration/test_web_e2e_meta.py \
  AgentLens/tests/integration/test_format_json_snapshot.py \
  AgentLens/tests/fixtures/format_snapshots
git commit -m "feat: expose normalized AgentLens contract metadata"
```

## Task 7: Update Contract Documentation

```yaml agentrunway-task
task_id: task_007
title: Update Contract Documentation
risk: medium
phase: documentation
dependencies: [task_006]
spec_refs: [S1.10, S1.13]
file_claims:
  - {path: AgentLens/docs/contract.md, mode: owned}
  - {path: AgentLens/docs/cli.md, mode: owned}
  - {path: AgentLens/docs/security.md, mode: owned}
  - {path: AgentLens/docs/plan/README.md, mode: owned}
acceptance_commands:
  - git diff --check
  - rg -n "agent\\.event\\.v1|kws-cpe\\.|kws-cme\\." AgentLens/docs/contract.md AgentLens/docs/cli.md AgentLens/docs/security.md AgentLens/docs/plan/README.md
required_skills: []
serial: true
```

**Files:**
- Modify: `AgentLens/docs/contract.md`
- Modify: `AgentLens/docs/cli.md`
- Modify: `AgentLens/docs/security.md`
- Modify: `AgentLens/docs/plan/README.md`

- [ ] **Step 1: Document contract version authority**

In `contract.md`, add a section explaining:

- v1 remains compatibility;
- v2 remains AgentRunway Trust Console compatibility;
- v3 is the unified pre-Rust contract;
- `agent.*` runtime schema names are not accepted;
- old `kws-cpe.*` and `kws-cme.*` are legacy import labels only.

- [ ] **Step 2: Document new import command**

In `cli.md`, document:

```bash
agentlens import agentrunway-journal --path <run-dir>
agentlens import agentrunway-journal --path <run-dir> --dry-run
```

Include the de-duplication key: `(producer.name, orchestrator_run_id, sequence)`.

- [ ] **Step 3: Document privacy and backfill behavior**

In `security.md`, clarify that AgentRunway local journal backfill imports bounded, redacted event envelopes only. It must not import full transcripts or absolute home paths.

- [ ] **Step 4: Update plan README**

Mark this plan as the current executable plan for contract reconciliation and keep the Rust skeleton plan blocked until this plan is complete.

- [ ] **Step 5: Run doc hygiene checks**

Run:

```bash
git diff --check
rg -n "agent\\.event\\.v1|kws-cpe\\.|kws-cme\\." AgentLens/docs/contract.md AgentLens/docs/cli.md AgentLens/docs/security.md AgentLens/docs/plan/README.md
```

Expected: `git diff --check` passes. The `rg` command may find references only in sections that explicitly say those names are rejected or legacy.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/docs/contract.md AgentLens/docs/cli.md AgentLens/docs/security.md AgentLens/docs/plan/README.md
git commit -m "docs: document unified AgentLens contract reconciliation"
```

## Task 8: Run Full Contract Reconciliation Verification

```yaml agentrunway-task
task_id: task_008
title: Run Full Contract Reconciliation Verification
risk: medium
phase: verification
dependencies: [task_007]
spec_refs: [S1.9, S1.12]
file_claims:
  - {path: AgentLens/docs/plan/2026-05-21-contract-first-unified-agent-platform.md, mode: shared_append}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_unified_contract_schema.py tests/unit/test_contract_normalization.py tests/unit/test_agentrunway_events.py tests/unit/test_evaluator_checks.py tests/integration/test_import_agentrunway_journal.py tests/integration/test_web_e2e_meta.py tests/integration/test_web_e2e_run_detail.py -q
  - cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" ./evals/run.sh
  - git diff --check
required_skills: [verification-before-completion]
serial: true
```

**Files:**
- Modify: `AgentLens/docs/plan/2026-05-21-contract-first-unified-agent-platform.md` only if verification notes need to be appended

- [ ] **Step 1: Run AgentLens targeted contract suite**

Run:

```bash
cd AgentLens
python -m pytest \
  tests/unit/test_unified_contract_schema.py \
  tests/unit/test_contract_normalization.py \
  tests/unit/test_agentrunway_events.py \
  tests/unit/test_evaluator_checks.py \
  tests/integration/test_import_agentrunway_journal.py \
  tests/integration/test_web_e2e_meta.py \
  tests/integration/test_web_e2e_run_detail.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 2: Run AgentRunway deterministic evals**

Run:

```bash
cd skills/agent-runway
PATH="$PWD/evals/fixtures/fake-bin:$PATH" ./evals/run.sh
```

Expected: eval suite exits 0.

- [ ] **Step 3: Run repository diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output and exit 0.

- [ ] **Step 4: Confirm Rust skeleton remains untouched**

Run:

```bash
test ! -f Cargo.toml
test ! -d crates
test ! -d apps
```

Expected: all commands exit 0 because this plan is contract reconciliation only.

- [ ] **Step 5: Commit final verification note if needed**

If a verification note was appended to this plan, commit it:

```bash
git add AgentLens/docs/plan/2026-05-21-contract-first-unified-agent-platform.md
git commit -m "docs: record contract reconciliation verification"
```

If no file changed, do not create an empty commit.

## Final Verification Checklist

Run these before marking the plan complete:

```bash
cd AgentLens
python -m pytest tests/unit/test_unified_contract_schema.py tests/unit/test_contract_normalization.py tests/unit/test_agentrunway_events.py tests/unit/test_evaluator_checks.py tests/integration/test_import_agentrunway_journal.py tests/integration/test_web_e2e_meta.py tests/integration/test_web_e2e_run_detail.py -q

cd ../skills/agent-runway
PATH="$PWD/evals/fixtures/fake-bin:$PATH" ./evals/run.sh

cd ../..
git diff --check
test ! -f Cargo.toml
test ! -d crates
test ! -d apps
```

Expected:

- AgentLens targeted contract suite passes.
- AgentRunway deterministic evals pass.
- `git diff --check` reports no whitespace errors.
- Rust workspace skeleton is still absent until the follow-up Rust plan.

## Follow-Up After This Plan

After this plan lands, revise `2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md` so its `agent-contracts` crate ports these canonical `agentlens.*` contracts instead of introducing `agent.*` schemas.
