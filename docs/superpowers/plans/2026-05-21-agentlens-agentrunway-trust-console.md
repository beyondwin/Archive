# AgentLens AgentRunway Trust Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert AgentLens into a no-legacy AgentRunway trust console with v2 schemas, first-class `agentrunway.*` events, deterministic projection artifacts, trust reports, and shared CLI/dashboard surfaces.

**Architecture:** AgentRunway remains the source of truth for execution state and emits runner-validated v2 event envelopes. AgentLens stores v2 run artifacts, builds `agentrunway_projection.json`, builds `trust_report.json`, and exposes the same trust verdict through CLI, API, and dashboard. The implementation deliberately rejects CPE/CME/KWS legacy event namespaces instead of migrating or parsing them.

**Tech Stack:** Python 3, JSON Schema Draft 2020-12, pytest, Typer-style AgentLens commands, FastAPI, React, TypeScript, Vitest, Playwright, AgentRunway fake runtime fixtures.

---

## Scope Check

This plan implements:

- `docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md`

This is a single implementation slice because schema, event emission, projection, trust evaluation, query/API payloads, and dashboard display all share one contract. Splitting schema from trust evaluation would create a temporary state where AgentRunway can emit events that AgentLens cannot judge.

Execution should start from a clean worktree or a separate worktree. The current main checkout may contain unrelated in-progress changes under `skills/agent-runway/`; do not stage, revert, or rewrite those unless they are part of the active task.

## File Structure

- `AgentLens/src/agentlens/schema/validate.py`
  - Generalize schema loading from five v1 names to explicit namespace-to-file mapping for v2 and derived artifacts.
- `AgentLens/src/agentlens/schema/jsonschema/run.v2.schema.json`
  - New run header for AgentRunway trust-console runs.
- `AgentLens/src/agentlens/schema/jsonschema/event.v2.schema.json`
  - New event envelope with `event_type`, `phase`, `outcome`, `severity`, `trust_impact`, evidence refs, artifact refs, and typed payload.
- `AgentLens/src/agentlens/schema/jsonschema/final.v2.schema.json`
  - New final record centered on claimed outcome and summary.
- `AgentLens/src/agentlens/schema/jsonschema/eval.v2.schema.json`
  - New eval record pointing at trust report and projection artifacts.
- `AgentLens/src/agentlens/schema/jsonschema/manifest.v2.schema.json`
  - New manifest record for v2 artifacts.
- `AgentLens/src/agentlens/schema/jsonschema/agentrunway_projection.v1.schema.json`
  - Derived AgentRunway projection artifact schema.
- `AgentLens/src/agentlens/schema/jsonschema/trust_report.v1.schema.json`
  - Derived trust report artifact schema.
- `AgentLens/tests/unit/test_schema_v2_validation.py`
  - Schema loader, valid fixture, invalid fixture, and legacy namespace rejection tests.
- `AgentLens/tests/fixtures/schemas/v2/valid/*.json`
  - v2 and derived-artifact valid fixtures.
- `AgentLens/tests/fixtures/schemas/v2/invalid/*.json`
  - invalid fixtures for legacy namespace and missing envelope fields.
- `AgentLens/src/agentlens/store/writer.py`
  - Validate v2 events by inferred schema rather than forcing the v1 event schema.
- `AgentLens/src/agentlens/store/trust_artifacts.py`
  - Atomic helpers for projection/trust artifact writes and reads.
- `AgentLens/tests/unit/test_trust_artifacts.py`
  - Artifact write/read and malformed artifact behavior.
- `AgentLens/src/agentlens/evaluator/agentrunway_v2.py`
  - Normalize v2 AgentRunway events and build deterministic projection.
- `AgentLens/src/agentlens/evaluator/trust.py`
  - Convert projection into trust report.
- `AgentLens/tests/unit/test_agentrunway_v2_projection.py`
  - Projection determinism, missing evidence, duplicate event, contradiction, and legacy rejection tests.
- `AgentLens/tests/unit/test_trust_report.py`
  - Trusted success, false success, weak retry evidence, blocked missing reason, oversized payload, and projection drift tests.
- `AgentLens/src/agentlens/evaluator/engine.py`
  - Write v2 `eval.json`, `artifacts/agentrunway_projection.json`, and `artifacts/trust_report.json` for v2 runs.
- `skills/agent-runway/scripts/agentrunway/events.py`
  - Build v2 event payloads with a shared envelope.
- `skills/agent-runway/scripts/agentrunway/agentlens.py`
  - Emit v2 events to AgentLens.
- `skills/agent-runway/evals/test_agentlens_v2_events.py`
  - AgentRunway fake emitter contract tests.
- `AgentLens/src/agentlens/store/query.py`
  - Project trust report fields into run rows and details.
- `AgentLens/src/agentlens/commands/_format.py`
  - Expose trust fields in CLI JSON projectors.
- `AgentLens/src/agentlens/commands/show.py`
  - Show trust verdict before timeline-style details.
- `AgentLens/src/agentlens/commands/agentrunway.py`
  - New focused AgentRunway trust report command.
- `AgentLens/src/agentlens/cli.py`
  - Register the new `agentrunway` command.
- `AgentLens/tests/integration/test_trust_console_cli.py`
  - CLI output and command registration tests.
- `AgentLens/src/agentlens/web/routers/runs.py`
  - Include trust report in run list and detail API responses.
- `AgentLens/web/src/api/runs.ts`
  - Add trust report TypeScript types.
- `AgentLens/web/src/components/trust-report-panel.tsx`
  - New dashboard trust summary panel.
- `AgentLens/web/src/components/run-list-table.tsx`
  - Show trust verdict and false-success state.
- `AgentLens/web/src/routes/run-detail.tsx`
  - Lead with trust report before failures/transcript.
- `AgentLens/web/src/components/trust-report-panel.test.tsx`
  - Trust panel rendering tests.
- `AgentLens/web/src/components/run-list-table.test.tsx`
  - False-success row and trust verdict tests.
- `AgentLens/web/src/integration/runs-list-route.test.tsx`
  - Runs list route trust payload test.
- `AgentLens/docs/contract.md`
  - Replace v1-lock framing with v2 Trust Console contract.
- `AgentLens/docs/cli.md`
  - Document trust-first CLI surfaces.
- `AgentLens/docs/dashboard.md`
  - Document dashboard trust-first layout.

---

### Task 0: Preflight And Worktree Guard

```yaml agentrunway-task
task_id: task_000
title: Preflight And Worktree Guard
risk: low
phase: planning
dependencies: []
spec_refs: [2, 4, 12]
file_claims: []
acceptance_commands:
  - git status --short
  - git rev-parse --show-toplevel
required_skills: []
serial: true
```

**Files:**
- Read: `docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md`
- Read: `git status --short`

- [ ] **Step 1: Confirm repository root**

Run:

```bash
git rev-parse --show-toplevel
```

Expected: `/Users/kws/source/private/Archive`.

- [ ] **Step 2: Inspect dirty worktree**

Run:

```bash
git status --short
```

Expected: either a clean worktree or only unrelated pre-existing `skills/agent-runway/*` changes. Do not stage unrelated files. If using a separate execution worktree, record that path in the implementation notes before Task 1.

- [ ] **Step 3: Confirm design source**

Run:

```bash
test -f docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md
```

Expected: exit code `0`.

- [ ] **Step 4: Commit**

No commit is required for this preflight task.

---

### Task 1: Add V2 Schema Loader And Fixtures

```yaml agentrunway-task
task_id: task_001
title: Add V2 Schema Loader And Fixtures
risk: high
phase: implementation
dependencies: [task_000]
spec_refs: [6, 10.1, 11]
file_claims:
  - {path: AgentLens/src/agentlens/schema/validate.py, mode: owned}
  - {path: AgentLens/src/agentlens/schema/__init__.py, mode: owned}
  - {path: AgentLens/src/agentlens/schema/jsonschema/*.v2.schema.json, mode: owned}
  - {path: AgentLens/src/agentlens/schema/jsonschema/agentrunway_projection.v1.schema.json, mode: owned}
  - {path: AgentLens/src/agentlens/schema/jsonschema/trust_report.v1.schema.json, mode: owned}
  - {path: AgentLens/tests/unit/test_schema_v2_validation.py, mode: owned}
  - {path: AgentLens/tests/fixtures/schemas/v2, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_schema_v2_validation.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `AgentLens/src/agentlens/schema/validate.py`
- Modify: `AgentLens/src/agentlens/schema/__init__.py`
- Create: `AgentLens/src/agentlens/schema/jsonschema/run.v2.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/event.v2.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/final.v2.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/eval.v2.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/manifest.v2.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/agentrunway_projection.v1.schema.json`
- Create: `AgentLens/src/agentlens/schema/jsonschema/trust_report.v1.schema.json`
- Create: `AgentLens/tests/unit/test_schema_v2_validation.py`
- Create: `AgentLens/tests/fixtures/schemas/v2/valid/run.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/valid/event.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/valid/final.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/valid/eval.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/valid/manifest.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/valid/agentrunway_projection.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/valid/trust_report.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/invalid/event_legacy_kws_cpe.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/invalid/event_missing_trust_impact.json`
- Create: `AgentLens/tests/fixtures/schemas/v2/invalid/trust_report_missing_verdict.json`

- [ ] **Step 1: Write failing v2 schema tests**

Create `AgentLens/tests/unit/test_schema_v2_validation.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from agentlens.schema import SchemaError, load_schema, validate_doc

V2_SCHEMA_NAMES = [
    "run_v2",
    "event_v2",
    "final_v2",
    "eval_v2",
    "manifest_v2",
    "agentrunway_projection",
    "trust_report",
]

ROOT = Path(__file__).resolve().parents[2]
VALID = ROOT / "tests" / "fixtures" / "schemas" / "v2" / "valid"
INVALID = ROOT / "tests" / "fixtures" / "schemas" / "v2" / "invalid"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", V2_SCHEMA_NAMES)
def test_v2_schema_loads_and_is_draft_2020_12(name: str) -> None:
    schema = load_schema(name)  # type: ignore[arg-type]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("fixture", "schema_name"),
    [
        ("run.json", "run_v2"),
        ("event.json", "event_v2"),
        ("final.json", "final_v2"),
        ("eval.json", "eval_v2"),
        ("manifest.json", "manifest_v2"),
        ("agentrunway_projection.json", "agentrunway_projection"),
        ("trust_report.json", "trust_report"),
    ],
)
def test_v2_valid_fixtures_pass(fixture: str, schema_name: str) -> None:
    validate_doc(_load(VALID / fixture), schema_name=schema_name)  # type: ignore[arg-type]
    validate_doc(_load(VALID / fixture))


def test_legacy_kws_cpe_event_is_rejected() -> None:
    with pytest.raises(SchemaError):
        validate_doc(_load(INVALID / "event_legacy_kws_cpe.json"), schema_name="event_v2")  # type: ignore[arg-type]


def test_event_missing_trust_impact_is_rejected() -> None:
    with pytest.raises(SchemaError):
        validate_doc(_load(INVALID / "event_missing_trust_impact.json"), schema_name="event_v2")  # type: ignore[arg-type]


def test_trust_report_missing_verdict_is_rejected() -> None:
    with pytest.raises(SchemaError):
        validate_doc(_load(INVALID / "trust_report_missing_verdict.json"), schema_name="trust_report")  # type: ignore[arg-type]
```

- [ ] **Step 2: Run v2 schema tests and verify failure**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_schema_v2_validation.py -v
```

Expected: FAIL because the test file or v2 schema names do not exist.

- [ ] **Step 3: Update schema loader mapping**

Modify `AgentLens/src/agentlens/schema/validate.py` so the schema registry is explicit:

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
    "agentrunway_projection",
    "trust_report",
]

_SCHEMA_FILES: dict[str, str] = {
    "run": "run.schema.json",
    "event": "event.schema.json",
    "final": "final.schema.json",
    "eval": "eval.schema.json",
    "manifest": "manifest.schema.json",
    "run_v2": "run.v2.schema.json",
    "event_v2": "event.v2.schema.json",
    "final_v2": "final.v2.schema.json",
    "eval_v2": "eval.v2.schema.json",
    "manifest_v2": "manifest.v2.schema.json",
    "agentrunway_projection": "agentrunway_projection.v1.schema.json",
    "trust_report": "trust_report.v1.schema.json",
}

_NAMESPACE_TO_NAME: dict[str, str] = {
    "agentlens.run.v1": "run",
    "agentlens.event.v1": "event",
    "agentlens.final.v1": "final",
    "agentlens.eval.v1": "eval",
    "agentlens.manifest.v1": "manifest",
    "agentlens.run.v2": "run_v2",
    "agentlens.event.v2": "event_v2",
    "agentlens.final.v2": "final_v2",
    "agentlens.eval.v2": "eval_v2",
    "agentlens.manifest.v2": "manifest_v2",
    "agentlens.agentrunway_projection.v1": "agentrunway_projection",
    "agentlens.trust_report.v1": "trust_report",
}
```

Change `load_schema()` to read `_SCHEMA_FILES[name]` rather than `f"{name}.schema.json"`.

- [ ] **Step 4: Export the updated schema API**

Modify `AgentLens/src/agentlens/schema/__init__.py` docstring from v1-only wording to:

```python
"""AgentLens schema package.

Re-exports the validation API defined in :mod:`agentlens.schema.validate`.
The registry supports the existing v1 schemas plus the AgentRunway Trust
Console v2 schemas and derived artifact schemas.
"""
```

- [ ] **Step 5: Add v2 event schema**

Create `AgentLens/src/agentlens/schema/jsonschema/event.v2.schema.json` with this shape:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agentlens.dev/schemas/agentlens.event.v2.json",
  "$comment": "AgentRunway Trust Console v2 event envelope.",
  "title": "agentlens.event.v2",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "event_id", "run_id", "event_type", "producer", "occurred_at", "sequence", "phase", "outcome", "severity", "trust_impact", "summary", "payload"],
  "properties": {
    "schema": {"type": "string", "const": "agentlens.event.v2"},
    "event_id": {"type": "string", "pattern": "^evt_[a-z0-9_:-]{6,80}$"},
    "run_id": {"type": "string", "minLength": 1},
    "event_type": {
      "type": "string",
      "pattern": "^agentrunway\\.[a-z][a-z0-9_]*$",
      "not": {"pattern": "^(kws-cpe|kws-cme|kws\\.orchestrator)\\."}
    },
    "producer": {
      "type": "object",
      "additionalProperties": false,
      "required": ["name"],
      "properties": {
        "name": {"type": "string", "const": "agentrunway"},
        "version": {"type": "string"}
      }
    },
    "occurred_at": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$"},
    "sequence": {"type": "integer", "minimum": 0},
    "phase": {"type": "string", "enum": ["run", "contract", "worker", "review", "verification", "retry", "quality", "merge", "resume", "apply", "finish"]},
    "outcome": {"type": "string", "enum": ["success", "failed", "partial", "blocked", "cancelled", "unknown"]},
    "severity": {"type": "string", "enum": ["info", "warn", "error"]},
    "task_id": {"type": "string"},
    "attempt_id": {"type": "string"},
    "candidate_id": {"type": "string"},
    "gate_id": {"type": "string"},
    "evidence_refs": {"type": "array", "items": {"type": "string"}},
    "artifact_refs": {"type": "array", "items": {"type": "string"}},
    "projection_hints": {"type": "object"},
    "trust_impact": {"type": "string", "enum": ["supports_success", "supports_failure", "requires_attention", "neutral", "downgrades_trust"]},
    "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
    "payload": {"type": "object"}
  }
}
```

- [ ] **Step 6: Add run/final/eval/manifest schemas**

Create the remaining v2 schemas with these minimum required fields:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$comment": "Use this template per file and set title/schema const.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "run_id"],
  "properties": {
    "schema": {"type": "string"},
    "run_id": {"type": "string", "minLength": 1}
  }
}
```

Then specialize each file:

- `run.v2.schema.json`: require `workspace_id`, `started_at`, `agent`, `workspace`, `recording`; set schema const `agentlens.run.v2`; require `agent.name="agentrunway"` and `recording.adapter="agentrunway"`.
- `final.v2.schema.json`: require `ended_at`, `claimed_outcome`, `summary`; enum `claimed_outcome` to `success`, `failed`, `partial`, `blocked`, `cancelled`, `unknown`.
- `eval.v2.schema.json`: require `evaluated_at`, `trust_report_ref`, `projection_ref`, `trust_verdict`; enum `trust_verdict` to `trusted`, `partially_trusted`, `untrusted`, `blocked`, `degraded`.
- `manifest.v2.schema.json`: require `sealed_at`, `sealed_phase`, `files`, `redaction`; enum `sealed_phase` to `pre_eval`, `final`, `recording_incomplete`.

- [ ] **Step 7: Add derived artifact schemas**

Create `agentrunway_projection.v1.schema.json` requiring:

```json
["schema", "run_id", "status", "tasks", "timeline", "projection_issues", "agentlens_observability"]
```

Create `trust_report.v1.schema.json` requiring:

```json
["schema", "run_id", "claimed_outcome", "trust_verdict", "evidence_strength", "blocking_evidence", "missing_evidence", "residual_risks", "operator_actions", "projection_issues"]
```

Use the exact enum values from the design spec for `trust_verdict` and `evidence_strength`.

- [ ] **Step 8: Add valid and invalid fixtures**

Add valid fixtures matching the snippets in the design spec. The valid event fixture must contain:

```json
{
  "schema": "agentlens.event.v2",
  "event_id": "evt_20260521_000001",
  "run_id": "run_20260521_000000_agent",
  "event_type": "agentrunway.verification_result",
  "producer": {"name": "agentrunway", "version": "0.1.0"},
  "occurred_at": "2026-05-21T00:00:00Z",
  "sequence": 1,
  "phase": "verification",
  "outcome": "success",
  "severity": "info",
  "task_id": "task_001",
  "attempt_id": "attempt_001",
  "evidence_refs": ["events/agentrunway.verification_result.jsonl#1"],
  "artifact_refs": ["coverage.json"],
  "trust_impact": "supports_success",
  "summary": "Verification passed.",
  "payload": {"status": "passed"}
}
```

The invalid legacy fixture must be identical except `event_type` is `kws-cpe.run_finished`.

- [ ] **Step 9: Run schema tests**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_schema_v2_validation.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add AgentLens/src/agentlens/schema AgentLens/tests/unit/test_schema_v2_validation.py AgentLens/tests/fixtures/schemas/v2
git commit -m "feat: add AgentLens v2 trust schemas"
```

---

### Task 2: Add V2 Event And Trust Artifact Writers

```yaml agentrunway-task
task_id: task_002
title: Add V2 Event And Trust Artifact Writers
risk: medium
phase: implementation
dependencies: [task_001]
spec_refs: [6.3, 6.4, 7.1, 9]
file_claims:
  - {path: AgentLens/src/agentlens/store/writer.py, mode: owned}
  - {path: AgentLens/src/agentlens/store/trust_artifacts.py, mode: owned}
  - {path: AgentLens/tests/unit/test_trust_artifacts.py, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_trust_artifacts.py tests/unit/test_writer.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `AgentLens/src/agentlens/store/writer.py`
- Create: `AgentLens/src/agentlens/store/trust_artifacts.py`
- Create: `AgentLens/tests/unit/test_trust_artifacts.py`

- [ ] **Step 1: Write failing writer tests**

Create `AgentLens/tests/unit/test_trust_artifacts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlens.store.trust_artifacts import read_trust_report, write_projection, write_trust_report
from agentlens.store.writer import WriteError, append_event


def _event(event_type: str = "agentrunway.run_started") -> dict:
    return {
        "schema": "agentlens.event.v2",
        "event_id": "evt_20260521_000001",
        "run_id": "run_20260521_000000_agent",
        "event_type": event_type,
        "producer": {"name": "agentrunway"},
        "occurred_at": "2026-05-21T00:00:00Z",
        "sequence": 1,
        "phase": "run",
        "outcome": "success",
        "severity": "info",
        "trust_impact": "neutral",
        "summary": "Run started.",
        "payload": {},
    }


def _projection() -> dict:
    return {
        "schema": "agentlens.agentrunway_projection.v1",
        "run_id": "run_20260521_000000_agent",
        "status": "running",
        "tasks": {},
        "timeline": [],
        "projection_issues": [],
        "agentlens_observability": {"status": "present"},
    }


def _trust_report() -> dict:
    return {
        "schema": "agentlens.trust_report.v1",
        "run_id": "run_20260521_000000_agent",
        "claimed_outcome": "success",
        "trust_verdict": "trusted",
        "evidence_strength": "strong",
        "blocking_evidence": [],
        "missing_evidence": [],
        "residual_risks": [],
        "operator_actions": [],
        "projection_issues": [],
    }


def test_append_event_accepts_v2_event(tmp_path: Path) -> None:
    append_event(tmp_path, _event())

    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["schema"] == "agentlens.event.v2"


def test_append_event_rejects_legacy_kws_namespace(tmp_path: Path) -> None:
    with pytest.raises(WriteError):
        append_event(tmp_path, _event("kws-cpe.run_finished"))


def test_write_and_read_trust_artifacts(tmp_path: Path) -> None:
    projection_path = write_projection(tmp_path, _projection())
    trust_path = write_trust_report(tmp_path, _trust_report())

    assert projection_path == tmp_path / "artifacts" / "agentrunway_projection.json"
    assert trust_path == tmp_path / "artifacts" / "trust_report.json"
    assert read_trust_report(tmp_path)["trust_verdict"] == "trusted"
```

- [ ] **Step 2: Run writer tests and verify failure**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_trust_artifacts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentlens.store.trust_artifacts'`.

- [ ] **Step 3: Make `append_event` infer event schema version**

Modify `AgentLens/src/agentlens/store/writer.py`:

```python
def _schema_name_for_doc(doc: dict[str, Any], fallback: str | None = None) -> str | None:
    schema = doc.get("schema")
    if schema == "agentlens.event.v2":
        return "event_v2"
    if schema == "agentlens.event.v1":
        return "event"
    return fallback
```

Then change `append_event()` validation from:

```python
_validate_or_write_error(payload, schema_name="event")
```

to:

```python
_validate_or_write_error(payload, schema_name=_schema_name_for_doc(payload, "event"))
```

- [ ] **Step 4: Add trust artifact helpers**

Create `AgentLens/src/agentlens/store/trust_artifacts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentlens.store.writer import atomic_write_json


PROJECTION_PATH = Path("artifacts/agentrunway_projection.json")
TRUST_REPORT_PATH = Path("artifacts/trust_report.json")


def write_projection(run_dir: Path, projection: dict[str, Any]) -> Path:
    path = Path(run_dir) / PROJECTION_PATH
    atomic_write_json(path, projection, redact=False)
    return path


def write_trust_report(run_dir: Path, report: dict[str, Any]) -> Path:
    path = Path(run_dir) / TRUST_REPORT_PATH
    atomic_write_json(path, report, redact=False)
    return path


def read_projection(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / PROJECTION_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def read_trust_report(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / TRUST_REPORT_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
```

- [ ] **Step 5: Run writer tests**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_trust_artifacts.py tests/unit/test_writer.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add AgentLens/src/agentlens/store/writer.py AgentLens/src/agentlens/store/trust_artifacts.py AgentLens/tests/unit/test_trust_artifacts.py
git commit -m "feat: add trust artifact writers"
```

---

### Task 3: Build AgentRunway V2 Projection

```yaml agentrunway-task
task_id: task_003
title: Build AgentRunway V2 Projection
risk: high
phase: implementation
dependencies: [task_001, task_002]
spec_refs: [6.2, 6.3, 7.2, 7.3, 8, 9, 10.2]
file_claims:
  - {path: AgentLens/src/agentlens/evaluator/agentrunway_v2.py, mode: owned}
  - {path: AgentLens/tests/unit/test_agentrunway_v2_projection.py, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_agentrunway_v2_projection.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `AgentLens/src/agentlens/evaluator/agentrunway_v2.py`
- Create: `AgentLens/tests/unit/test_agentrunway_v2_projection.py`

- [ ] **Step 1: Write failing projection tests**

Create `AgentLens/tests/unit/test_agentrunway_v2_projection.py`:

```python
from __future__ import annotations

from agentlens.evaluator.agentrunway_v2 import build_projection


def _event(event_type: str, *, sequence: int, **payload: object) -> dict:
    return {
        "schema": "agentlens.event.v2",
        "event_id": f"evt_20260521_{sequence:06d}",
        "run_id": "run_20260521_000000_agent",
        "event_type": event_type,
        "producer": {"name": "agentrunway"},
        "occurred_at": "2026-05-21T00:00:00Z",
        "sequence": sequence,
        "phase": "verification" if "verification" in event_type else "run",
        "outcome": "success",
        "severity": "info",
        "task_id": payload.pop("task_id", "task_001"),
        "attempt_id": payload.pop("attempt_id", "attempt_001"),
        "trust_impact": payload.pop("trust_impact", "neutral"),
        "summary": payload.pop("summary", event_type),
        "payload": payload,
    }


def test_projection_is_deterministic_and_orders_by_sequence() -> None:
    events = [
        _event("agentrunway.run_finished", sequence=3, status="success"),
        _event("agentrunway.run_started", sequence=1),
        _event("agentrunway.verification_result", sequence=2, status="passed"),
    ]

    first = build_projection(events)
    second = build_projection(list(reversed(events)))

    assert first == second
    assert [item["event_type"] for item in first["timeline"]] == [
        "agentrunway.run_started",
        "agentrunway.verification_result",
        "agentrunway.run_finished",
    ]
    assert first["status"] == "success"
    assert first["tasks"]["task_001"]["verification"]["passed"] == 1


def test_missing_verification_is_projection_issue_for_success() -> None:
    projection = build_projection([
        _event("agentrunway.run_started", sequence=1),
        _event("agentrunway.run_finished", sequence=2, status="success"),
    ])

    assert {
        "code": "missing_verification_pass",
        "severity": "error",
        "summary": "Run claimed success without a passing verification result.",
    } in projection["projection_issues"]


def test_duplicate_event_is_projection_issue() -> None:
    event = _event("agentrunway.run_started", sequence=1)
    projection = build_projection([event, event])

    assert projection["projection_issues"][0]["code"] == "duplicate_event_id"


def test_blocked_run_without_reason_is_projection_issue() -> None:
    projection = build_projection([
        _event("agentrunway.run_blocked", sequence=1, status="blocked", reason=""),
    ])

    assert projection["status"] == "blocked"
    assert projection["projection_issues"][0]["code"] == "missing_blocked_reason"


def test_legacy_event_is_rejected_as_projection_issue() -> None:
    projection = build_projection([
        {"schema": "agentlens.event.v2", "event_type": "kws-cme.run_finished"}
    ])

    assert projection["projection_issues"][0]["code"] == "unsupported_event_type"
```

- [ ] **Step 2: Run projection tests and verify failure**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_agentrunway_v2_projection.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentlens.evaluator.agentrunway_v2'`.

- [ ] **Step 3: Implement projection builder public API**

Create `AgentLens/src/agentlens/evaluator/agentrunway_v2.py` with this public API:

```python
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

SUPPORTED_PREFIX = "agentrunway."
MAX_PAYLOAD_BYTES = 4096


def _issue(code: str, summary: str, *, severity: str = "warn") -> dict[str, str]:
    return {"code": code, "severity": severity, "summary": summary}


def _event_type(event: Mapping[str, Any]) -> str:
    value = event.get("event_type") or event.get("type")
    return value if isinstance(value, str) else ""


def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _payload_oversized(event: Mapping[str, Any]) -> bool:
    try:
        return len(json.dumps(_payload(event), sort_keys=True).encode("utf-8")) > MAX_PAYLOAD_BYTES
    except (TypeError, ValueError):
        return True


def _empty(run_id: str | None = None) -> dict[str, Any]:
    return {
        "schema": "agentlens.agentrunway_projection.v1",
        "run_id": run_id or "",
        "status": "not_started",
        "tasks": {},
        "timeline": [],
        "projection_issues": [],
        "agentlens_observability": {"status": "present"},
        "merge": {"ready": False, "conflicts": []},
        "retry_count": 0,
        "evidence_strength": "strong",
    }
```

Then implement `build_projection(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]` with these rules:

- Sort by `(sequence, occurred_at, event_id)`.
- Reject event types not starting with `agentrunway.` by appending `unsupported_event_type`.
- Track duplicate `event_id` values with `duplicate_event_id`.
- Append timeline entries with `event_type`, `sequence`, `task_id`, `outcome`, `summary`.
- For `verification_result` with `payload.status == "passed"`, increment `tasks[task_id]["verification"]["passed"]`.
- For `gate_retry`, increment top-level `retry_count`.
- For `merge_conflict`, set `merge.ready = False` and append the conflict.
- For `merge_ready`, set `merge.ready = True`.
- For `run_blocked`, set `status = "blocked"` and require a non-empty `payload.reason`.
- For `run_finished`, set `status` from `payload.status` or event `outcome`.
- If final status is `success` and no verification pass exists, append `missing_verification_pass`.
- If payload is oversized, set `evidence_strength = "weak"` and append `oversized_payload`.

- [ ] **Step 4: Run projection tests**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_agentrunway_v2_projection.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add AgentLens/src/agentlens/evaluator/agentrunway_v2.py AgentLens/tests/unit/test_agentrunway_v2_projection.py
git commit -m "feat: project AgentRunway v2 events"
```

---

### Task 4: Add Trust Evaluator And V2 Eval Output

```yaml agentrunway-task
task_id: task_004
title: Add Trust Evaluator And V2 Eval Output
risk: high
phase: implementation
dependencies: [task_002, task_003]
spec_refs: [6.4, 7.4, 9, 10.3, 11]
file_claims:
  - {path: AgentLens/src/agentlens/evaluator/trust.py, mode: owned}
  - {path: AgentLens/src/agentlens/evaluator/engine.py, mode: owned}
  - {path: AgentLens/tests/unit/test_trust_report.py, mode: owned}
  - {path: AgentLens/tests/integration/test_eval_trust_console.py, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_trust_report.py tests/integration/test_eval_trust_console.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `AgentLens/src/agentlens/evaluator/trust.py`
- Modify: `AgentLens/src/agentlens/evaluator/engine.py`
- Create: `AgentLens/tests/unit/test_trust_report.py`
- Create: `AgentLens/tests/integration/test_eval_trust_console.py`

- [ ] **Step 1: Write failing trust tests**

Create `AgentLens/tests/unit/test_trust_report.py`:

```python
from __future__ import annotations

from agentlens.evaluator.trust import build_trust_report


def _projection(**overrides: object) -> dict:
    doc = {
        "schema": "agentlens.agentrunway_projection.v1",
        "run_id": "run_20260521_000000_agent",
        "status": "success",
        "tasks": {"task_001": {"verification": {"passed": 1}}},
        "timeline": [],
        "projection_issues": [],
        "agentlens_observability": {"status": "present"},
        "merge": {"ready": True, "conflicts": []},
        "retry_count": 0,
        "evidence_strength": "strong",
    }
    doc.update(overrides)
    return doc


def test_trusted_success() -> None:
    report = build_trust_report(_projection(), claimed_outcome="success")

    assert report["trust_verdict"] == "trusted"
    assert report["evidence_strength"] == "strong"
    assert report["missing_evidence"] == []


def test_false_success_without_verification_pass() -> None:
    report = build_trust_report(
        _projection(tasks={}, projection_issues=[{"code": "missing_verification_pass", "severity": "error", "summary": "missing"}]),
        claimed_outcome="success",
    )

    assert report["trust_verdict"] == "untrusted"
    assert report["missing_evidence"][0]["code"] == "missing_verification_pass"


def test_weak_retry_evidence_downgrades_success() -> None:
    report = build_trust_report(
        _projection(retry_count=1, projection_issues=[{"code": "weak_retry_evidence", "severity": "warn", "summary": "retry lacks linked evidence"}]),
        claimed_outcome="success",
    )

    assert report["trust_verdict"] == "partially_trusted"
    assert report["residual_risks"][0]["code"] == "weak_retry_evidence"


def test_blocked_without_reason_requires_operator_action() -> None:
    report = build_trust_report(
        _projection(status="blocked", projection_issues=[{"code": "missing_blocked_reason", "severity": "error", "summary": "blocked without reason"}]),
        claimed_outcome="blocked",
    )

    assert report["trust_verdict"] == "blocked"
    assert report["operator_actions"][0]["code"] == "inspect_blocked_run"


def test_oversized_payload_degrades_evidence_strength() -> None:
    report = build_trust_report(
        _projection(evidence_strength="weak", projection_issues=[{"code": "oversized_payload", "severity": "warn", "summary": "payload was oversized"}]),
        claimed_outcome="success",
    )

    assert report["evidence_strength"] == "weak"
    assert report["trust_verdict"] == "partially_trusted"
```

- [ ] **Step 2: Run trust tests and verify failure**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_trust_report.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentlens.evaluator.trust'`.

- [ ] **Step 3: Implement trust evaluator**

Create `AgentLens/src/agentlens/evaluator/trust.py`:

```python
from __future__ import annotations

from typing import Any


ERROR_CODES_AS_MISSING = {"missing_verification_pass", "missing_blocked_reason"}


def _issue_code(issue: dict[str, Any]) -> str:
    value = issue.get("code")
    return value if isinstance(value, str) else "unknown_issue"


def _has_verification_pass(projection: dict[str, Any]) -> bool:
    tasks = projection.get("tasks")
    if not isinstance(tasks, dict):
        return False
    for task in tasks.values():
        if isinstance(task, dict):
            verification = task.get("verification")
            if isinstance(verification, dict) and int(verification.get("passed") or 0) > 0:
                return True
    return False


def build_trust_report(projection: dict[str, Any], *, claimed_outcome: str) -> dict[str, Any]:
    issues = [issue for issue in projection.get("projection_issues", []) if isinstance(issue, dict)]
    missing = [issue for issue in issues if _issue_code(issue) in ERROR_CODES_AS_MISSING]
    residual = [issue for issue in issues if _issue_code(issue) not in ERROR_CODES_AS_MISSING]
    operator_actions: list[dict[str, str]] = []

    status = str(projection.get("status") or "unknown")
    evidence_strength = str(projection.get("evidence_strength") or "adequate")

    if any(_issue_code(issue) == "missing_blocked_reason" for issue in issues):
        operator_actions.append({
            "code": "inspect_blocked_run",
            "summary": "Inspect AgentRunway local state because the blocked run lacks a reason.",
        })

    if status == "blocked" or claimed_outcome == "blocked":
        verdict = "blocked"
    elif claimed_outcome == "success" and not _has_verification_pass(projection):
        verdict = "untrusted"
        if not any(_issue_code(issue) == "missing_verification_pass" for issue in missing):
            missing.append({
                "code": "missing_verification_pass",
                "severity": "error",
                "summary": "Run claimed success without a passing verification result.",
            })
    elif evidence_strength in {"weak", "insufficient"} or residual:
        verdict = "partially_trusted"
    elif claimed_outcome == "success":
        verdict = "trusted"
    else:
        verdict = "degraded"

    return {
        "schema": "agentlens.trust_report.v1",
        "run_id": str(projection.get("run_id") or ""),
        "claimed_outcome": claimed_outcome,
        "trust_verdict": verdict,
        "evidence_strength": evidence_strength,
        "blocking_evidence": [],
        "missing_evidence": missing,
        "residual_risks": residual,
        "operator_actions": operator_actions,
        "projection_issues": issues,
    }
```

- [ ] **Step 4: Integrate v2 eval path**

Modify `AgentLens/src/agentlens/evaluator/engine.py`:

- If `ctx.run["schema"] == "agentlens.run.v2"`, build projection from `ctx.events` with `build_projection`.
- Build trust report from projection and final claimed outcome.
- Write `artifacts/agentrunway_projection.json` and `artifacts/trust_report.json`.
- Write `eval.json` with schema `agentlens.eval.v2`, `trust_report_ref="artifacts/trust_report.json"`, `projection_ref="artifacts/agentrunway_projection.json"`, and `trust_verdict`.
- Keep the existing v1 path only until all old fixtures are converted in Task 8.

Use this helper inside `evaluate()`:

```python
def _evaluate_v2(ctx: EvalContext, run_dir: Path) -> dict[str, Any]:
    projection = build_projection(ctx.events)
    final_doc = ctx.final or {}
    claimed = str(final_doc.get("claimed_outcome") or final_doc.get("agent_outcome") or "unknown")
    report = build_trust_report(projection, claimed_outcome=claimed)
    projection_path = write_projection(run_dir, projection)
    trust_path = write_trust_report(run_dir, report)
    doc = {
        "schema": "agentlens.eval.v2",
        "run_id": ctx.run.get("run_id", run_dir.name),
        "evaluated_at": utc_now_iso(),
        "trust_verdict": report["trust_verdict"],
        "trust_report_ref": str(trust_path.relative_to(run_dir)),
        "projection_ref": str(projection_path.relative_to(run_dir)),
    }
    atomic_write_json(run_dir / "eval.json", doc, redact=False)
    return doc
```

- [ ] **Step 5: Add integration test for v2 eval artifacts**

Create `AgentLens/tests/integration/test_eval_trust_console.py` with a temp run directory containing `run.json`, `events.jsonl`, `final.json`, and `manifest.json` using v2 schemas. Assert:

```python
doc = evaluate(run_dir)
assert doc["schema"] == "agentlens.eval.v2"
assert (run_dir / "artifacts" / "agentrunway_projection.json").is_file()
assert (run_dir / "artifacts" / "trust_report.json").is_file()
assert json.loads((run_dir / "artifacts" / "trust_report.json").read_text())["trust_verdict"] == "trusted"
```

- [ ] **Step 6: Run trust/eval tests**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_trust_report.py tests/integration/test_eval_trust_console.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add AgentLens/src/agentlens/evaluator/trust.py AgentLens/src/agentlens/evaluator/engine.py AgentLens/tests/unit/test_trust_report.py AgentLens/tests/integration/test_eval_trust_console.py
git commit -m "feat: evaluate AgentRunway trust reports"
```

---

### Task 5: Emit V2 Events From AgentRunway

```yaml agentrunway-task
task_id: task_005
title: Emit V2 Events From AgentRunway
risk: high
phase: implementation
dependencies: [task_001, task_002]
spec_refs: [7.1, 8, 9, 10.4]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/events.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/agentlens.py, mode: owned}
  - {path: skills/agent-runway/evals/test_agentlens_v2_events.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_agentlens_v2_events.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/events.py`
- Modify: `skills/agent-runway/scripts/agentrunway/agentlens.py`
- Create: `skills/agent-runway/evals/test_agentlens_v2_events.py`

- [ ] **Step 1: Write failing AgentRunway v2 event tests**

Create `skills/agent-runway/evals/test_agentlens_v2_events.py`:

```python
from __future__ import annotations

from agentrunway.events import build_event_payload


def test_build_event_payload_returns_agentlens_event_v2_envelope() -> None:
    event = build_event_payload(
        "ar-001",
        "verification",
        "success",
        "Verification passed.",
        event_type="agentrunway.verification_result",
        task_id="task_001",
        attempt_id="attempt_001",
        payload={"status": "passed"},
    )

    assert event["schema"] == "agentlens.event.v2"
    assert event["run_id"] == "ar-001"
    assert event["event_type"] == "agentrunway.verification_result"
    assert event["producer"]["name"] == "agentrunway"
    assert event["phase"] == "verification"
    assert event["trust_impact"] == "supports_success"
    assert event["payload"]["status"] == "passed"


def test_build_event_payload_rejects_legacy_namespace() -> None:
    try:
        build_event_payload("ar-001", "finish", "success", "done", event_type="kws-cpe.run_finished")
    except ValueError as exc:
        assert "unsupported AgentRunway event type" in str(exc)
    else:
        raise AssertionError("legacy namespace should fail")


def test_build_event_payload_bounds_oversized_payload() -> None:
    event = build_event_payload(
        "ar-001",
        "worker",
        "partial",
        "large",
        event_type="agentrunway.worker_result",
        payload={"blob": "x" * 10000},
    )

    assert event["payload"].get("payload_truncated") is True
    assert event["trust_impact"] == "downgrades_trust"
```

- [ ] **Step 2: Run AgentRunway v2 event tests and verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_agentlens_v2_events.py -v
```

Expected: FAIL because `build_event_payload()` still returns the older payload-only shape.

- [ ] **Step 3: Update AgentRunway event builder**

Modify `skills/agent-runway/scripts/agentrunway/events.py`:

```python
EVENT_SCHEMA_V2 = "agentlens.event.v2"


def _trust_impact(outcome: str, payload: dict[str, Any]) -> str:
    if payload.get("payload_truncated"):
        return "downgrades_trust"
    if outcome == "success":
        return "supports_success"
    if outcome in {"failed", "blocked"}:
        return "supports_failure"
    if outcome == "partial":
        return "requires_attention"
    return "neutral"
```

Change `build_event_payload()` signature to accept `event_type`, `task_id`, `attempt_id`, `candidate_id`, `gate_id`, `evidence_refs`, `artifact_refs`, and `payload`. Return the v2 envelope:

```python
{
    "schema": EVENT_SCHEMA_V2,
    "event_id": f"evt_{run_id}_{event_type.replace('.', '_')}",
    "run_id": run_id,
    "event_type": event_type,
    "producer": {"name": "agentrunway"},
    "occurred_at": utc_now_iso_like_string,
    "sequence": int(extra.pop("sequence", 0)),
    "phase": phase,
    "outcome": outcome,
    "severity": "error" if outcome in {"failed", "blocked"} else ("warn" if outcome == "partial" else "info"),
    "task_id": task_id,
    "attempt_id": attempt_id,
    "candidate_id": candidate_id,
    "gate_id": gate_id,
    "evidence_refs": list(evidence_refs or []),
    "artifact_refs": list(artifact_refs or []),
    "trust_impact": _trust_impact(outcome, bounded_payload),
    "summary": summary[:1200],
    "payload": bounded_payload,
}
```

Omit optional keys whose value is `None` so the schema accepts the event.

- [ ] **Step 4: Update AgentLens CLI emitter call**

Modify `skills/agent-runway/scripts/agentrunway/agentlens.py` so `emit()` sends the v2 event document rather than a payload-only document:

```python
def emit(self, event_type: str, payload: dict[str, Any]) -> None:
    target_run = self.agentlens_run_id or str(payload.get("run_id") or "")
    if not target_run:
        raise AgentLensEmitError("missing AgentLens run id")
    event_doc = dict(payload)
    event_doc["event_type"] = event_doc.get("event_type") or event_type
    raw = json.dumps(event_doc, ensure_ascii=False, sort_keys=True)
    ...
```

Keep `run-open` best-effort behavior. AgentLens failure must not stop AgentRunway.

- [ ] **Step 5: Run AgentRunway event tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_agentlens_v2_events.py -v
```

Expected: PASS.

- [ ] **Step 6: Run focused AgentRunway fake emission regression**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_runner_production_e2e.py -k agentlens -v
```

Expected: PASS. If existing in-progress AgentRunway changes affect this test, record the failure and do not revert unrelated edits.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/events.py skills/agent-runway/scripts/agentrunway/agentlens.py skills/agent-runway/evals/test_agentlens_v2_events.py
git commit -m "feat: emit AgentRunway v2 trust events"
```

---

### Task 6: Expose Trust Report Through CLI And API

```yaml agentrunway-task
task_id: task_006
title: Expose Trust Report Through CLI And API
risk: medium
phase: implementation
dependencies: [task_004]
spec_refs: [7.5, 8.3, 10.5, 11]
file_claims:
  - {path: AgentLens/src/agentlens/store/query.py, mode: owned}
  - {path: AgentLens/src/agentlens/commands/_format.py, mode: owned}
  - {path: AgentLens/src/agentlens/commands/show.py, mode: owned}
  - {path: AgentLens/src/agentlens/commands/agentrunway.py, mode: owned}
  - {path: AgentLens/src/agentlens/cli.py, mode: owned}
  - {path: AgentLens/src/agentlens/web/routers/runs.py, mode: owned}
  - {path: AgentLens/tests/integration/test_trust_console_cli.py, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/integration/test_trust_console_cli.py tests/integration/test_web_e2e_run_detail.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `AgentLens/src/agentlens/store/query.py`
- Modify: `AgentLens/src/agentlens/commands/_format.py`
- Modify: `AgentLens/src/agentlens/commands/show.py`
- Create: `AgentLens/src/agentlens/commands/agentrunway.py`
- Modify: `AgentLens/src/agentlens/cli.py`
- Modify: `AgentLens/src/agentlens/web/routers/runs.py`
- Create: `AgentLens/tests/integration/test_trust_console_cli.py`

- [ ] **Step 1: Write failing CLI/API tests**

Create `AgentLens/tests/integration/test_trust_console_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentlens.cli import app


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")


def _seed_run(home: Path) -> str:
    run_id = "run_20260521_000000_agent"
    run_dir = home / "runs" / "ws_0123456789abcdef" / run_id
    _write_json(run_dir / "run.json", {
        "schema": "agentlens.run.v2",
        "run_id": run_id,
        "workspace_id": "ws_0123456789abcdef",
        "started_at": "2026-05-21T00:00:00Z",
        "agent": {"name": "agentrunway", "mode": "cli"},
        "workspace": {"root_label": "<workspace>", "root_hash": "sha256:" + "1" * 64, "id_basis": "git"},
        "recording": {"mode": "minimal", "adapter": "agentrunway"},
    })
    _write_json(run_dir / "final.json", {
        "schema": "agentlens.final.v2",
        "run_id": run_id,
        "ended_at": "2026-05-21T00:01:00Z",
        "claimed_outcome": "success",
        "summary": "done",
    })
    _write_json(run_dir / "manifest.json", {
        "schema": "agentlens.manifest.v2",
        "run_id": run_id,
        "sealed_at": "2026-05-21T00:01:01Z",
        "sealed_phase": "final",
        "files": [],
        "redaction": {"absolute_paths": "masked", "secret_like_values": "masked", "full_prompts": "not_stored", "full_command_output": "excerpted"},
    })
    _write_json(run_dir / "artifacts" / "trust_report.json", {
        "schema": "agentlens.trust_report.v1",
        "run_id": run_id,
        "claimed_outcome": "success",
        "trust_verdict": "trusted",
        "evidence_strength": "strong",
        "blocking_evidence": [],
        "missing_evidence": [],
        "residual_risks": [],
        "operator_actions": [],
        "projection_issues": [],
    })
    return run_id


def test_agentrunway_command_outputs_trust_report(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))

    result = CliRunner().invoke(app, ["agentrunway", run_id, "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_id"] == run_id
    assert payload["trust_verdict"] == "trusted"
```

- [ ] **Step 2: Run CLI test and verify failure**

Run:

```bash
cd AgentLens && python -m pytest tests/integration/test_trust_console_cli.py -v
```

Expected: FAIL because the `agentrunway` command does not exist.

- [ ] **Step 3: Add query trust projection**

Modify `AgentLens/src/agentlens/store/query.py`:

```python
from agentlens.store.trust_artifacts import read_trust_report


def _read_trust_report_for_row(home: Path, row: dict[str, Any]) -> dict[str, Any] | None:
    run_id = row.get("run_id")
    workspace_id = row.get("workspace_id")
    if not isinstance(run_id, str) or not isinstance(workspace_id, str):
        return None
    run_dir = _runs_root(home) / workspace_id / run_id
    return read_trust_report(run_dir)
```

Add `trust_report`, `trust_verdict`, and `evidence_strength` to run rows when a trust report exists.

- [ ] **Step 4: Add CLI projector keys**

Modify `AgentLens/src/agentlens/commands/_format.py`:

```python
_TRUST_KEYS: tuple[str, ...] = (
    "trust_verdict",
    "evidence_strength",
    "trust_report",
)
```

In `project_run_row()` and `project_show()`, carry these keys with `None` defaults:

```python
for key in _TRUST_KEYS:
    out[key] = row.get(key)
```

- [ ] **Step 5: Add `agentlens agentrunway` command**

Create `AgentLens/src/agentlens/commands/agentrunway.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import typer

from agentlens.store.query import get_run
from agentlens.store.trust_artifacts import read_trust_report
from agentlens.store.paths import agentlens_home


def _run_dir(home: Path, run_id: str, workspace_id: str) -> Path:
    return home / "runs" / workspace_id / run_id


def agentrunway(run_id: str, format: str = typer.Option("text", "--format")) -> None:
    home = agentlens_home()
    row = get_run(home, run_id)
    if not row:
        raise typer.BadParameter(f"run not found: {run_id}")
    report = read_trust_report(_run_dir(home, run_id, str(row.get("workspace_id"))))
    if report is None:
        raise typer.BadParameter(f"trust report not found for run: {run_id}")
    if format == "json":
        typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return
    typer.echo(f"{report['run_id']}  {report['claimed_outcome']}  {report['trust_verdict']}  {report['evidence_strength']}")
```

Register it in `AgentLens/src/agentlens/cli.py`:

```python
from agentlens.commands.agentrunway import agentrunway

app.command(name="agentrunway")(agentrunway)
```

- [ ] **Step 6: Add API trust payload**

Modify `AgentLens/src/agentlens/web/routers/runs.py` so `_detail_payload()` adds:

```python
trust_report = read_trust_report(run_dir)
payload["trust_report"] = trust_report
payload["trust_verdict"] = (trust_report or {}).get("trust_verdict")
payload["evidence_strength"] = (trust_report or {}).get("evidence_strength")
```

Also add the same `trust_verdict` and `evidence_strength` to list rows in `list_runs()`.

- [ ] **Step 7: Run CLI/API tests**

Run:

```bash
cd AgentLens && python -m pytest tests/integration/test_trust_console_cli.py tests/integration/test_web_e2e_run_detail.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add AgentLens/src/agentlens/store/query.py AgentLens/src/agentlens/commands/_format.py AgentLens/src/agentlens/commands/show.py AgentLens/src/agentlens/commands/agentrunway.py AgentLens/src/agentlens/cli.py AgentLens/src/agentlens/web/routers/runs.py AgentLens/tests/integration/test_trust_console_cli.py
git commit -m "feat: expose AgentRunway trust reports"
```

---

### Task 7: Add Dashboard Trust Console UI

```yaml agentrunway-task
task_id: task_007
title: Add Dashboard Trust Console UI
risk: medium
phase: implementation
dependencies: [task_006]
spec_refs: [7.6, 10.5, 11]
file_claims:
  - {path: AgentLens/web/src/api/runs.ts, mode: owned}
  - {path: AgentLens/web/src/components/trust-report-panel.tsx, mode: owned}
  - {path: AgentLens/web/src/components/trust-report-panel.test.tsx, mode: owned}
  - {path: AgentLens/web/src/components/run-list-table.tsx, mode: owned}
  - {path: AgentLens/web/src/components/run-list-table.test.tsx, mode: shared_append}
  - {path: AgentLens/web/src/routes/run-detail.tsx, mode: owned}
  - {path: AgentLens/web/src/integration/runs-list-route.test.tsx, mode: shared_append}
acceptance_commands:
  - cd AgentLens/web && npx vitest run src/components/trust-report-panel.test.tsx src/components/run-list-table.test.tsx src/integration/runs-list-route.test.tsx
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `AgentLens/web/src/api/runs.ts`
- Create: `AgentLens/web/src/components/trust-report-panel.tsx`
- Create: `AgentLens/web/src/components/trust-report-panel.test.tsx`
- Modify: `AgentLens/web/src/components/run-list-table.tsx`
- Modify: `AgentLens/web/src/components/run-list-table.test.tsx`
- Modify: `AgentLens/web/src/routes/run-detail.tsx`
- Modify: `AgentLens/web/src/integration/runs-list-route.test.tsx`

- [ ] **Step 1: Add TypeScript trust types**

Modify `AgentLens/web/src/api/runs.ts`:

```ts
export type TrustVerdict = "trusted" | "partially_trusted" | "untrusted" | "blocked" | "degraded";
export type EvidenceStrength = "strong" | "adequate" | "weak" | "insufficient";

export type TrustIssue = {
  code: string;
  severity?: string;
  summary: string;
};

export type TrustReport = {
  schema: "agentlens.trust_report.v1";
  run_id: string;
  claimed_outcome: string;
  trust_verdict: TrustVerdict;
  evidence_strength: EvidenceStrength;
  blocking_evidence: TrustIssue[];
  missing_evidence: TrustIssue[];
  residual_risks: TrustIssue[];
  operator_actions: TrustIssue[];
  projection_issues: TrustIssue[];
};
```

Add to `RunRow`:

```ts
trust_verdict: TrustVerdict | null;
evidence_strength: EvidenceStrength | null;
```

Add to `RunDetail`:

```ts
trust_verdict: TrustVerdict | null;
evidence_strength: EvidenceStrength | null;
trust_report: TrustReport | null;
```

- [ ] **Step 2: Write failing trust panel test**

Create `AgentLens/web/src/components/trust-report-panel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";

import { TrustReportPanel } from "./trust-report-panel";
import type { TrustReport } from "@/api/runs";

const report: TrustReport = {
  schema: "agentlens.trust_report.v1",
  run_id: "run_20260521_000000_agent",
  claimed_outcome: "success",
  trust_verdict: "untrusted",
  evidence_strength: "weak",
  blocking_evidence: [],
  missing_evidence: [{ code: "missing_verification_pass", summary: "Run claimed success without verification." }],
  residual_risks: [],
  operator_actions: [],
  projection_issues: [],
};

it("shows trust verdict before evidence lists", () => {
  render(<TrustReportPanel report={report} />);

  expect(screen.getByText("Trust verdict")).toBeInTheDocument();
  expect(screen.getByText("untrusted")).toBeInTheDocument();
  expect(screen.getByText("missing_verification_pass")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run panel test and verify failure**

Run:

```bash
cd AgentLens/web && npx vitest run src/components/trust-report-panel.test.tsx
```

Expected: FAIL because `trust-report-panel.tsx` does not exist.

- [ ] **Step 4: Implement `TrustReportPanel`**

Create `AgentLens/web/src/components/trust-report-panel.tsx`:

```tsx
import type { TrustIssue, TrustReport } from "@/api/runs";
import { Badge } from "@/components/ui/badge";

function issueList(title: string, issues: TrustIssue[]) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-normal text-zinc-500">{title}</div>
      {issues.length === 0 ? (
        <div className="mt-2 text-sm text-zinc-500">None</div>
      ) : (
        <div className="mt-2 divide-y divide-zinc-100 rounded-md border border-zinc-200 bg-white">
          {issues.map((issue) => (
            <div key={`${issue.code}-${issue.summary}`} className="px-3 py-2 text-sm">
              <div className="font-mono text-xs text-zinc-700">{issue.code}</div>
              <div className="mt-1 text-zinc-700">{issue.summary}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function TrustReportPanel({ report }: { report: TrustReport | null | undefined }) {
  if (!report) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-500">
        Trust report unavailable.
      </div>
    );
  }
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="grid gap-3 text-sm md:grid-cols-3">
        <div>
          <div className="text-xs text-zinc-500">Claimed outcome</div>
          <div className="mt-1 font-medium text-zinc-950">{report.claimed_outcome}</div>
        </div>
        <div>
          <div className="text-xs text-zinc-500">Trust verdict</div>
          <div className="mt-1"><Badge tone={report.trust_verdict === "trusted" ? "success" : "danger"}>{report.trust_verdict}</Badge></div>
        </div>
        <div>
          <div className="text-xs text-zinc-500">Evidence strength</div>
          <div className="mt-1 font-medium text-zinc-950">{report.evidence_strength}</div>
        </div>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {issueList("Missing evidence", report.missing_evidence)}
        {issueList("Blocking evidence", report.blocking_evidence)}
        {issueList("Residual risks", report.residual_risks)}
        {issueList("Operator actions", report.operator_actions)}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Put trust panel first on run detail**

Modify `AgentLens/web/src/routes/run-detail.tsx`:

```tsx
import { TrustReportPanel } from "@/components/trust-report-panel";
```

Place this immediately after `OutcomeEvalPills`:

```tsx
<div className="mt-4">
  <TrustReportPanel report={detail.trust_report} />
</div>
```

- [ ] **Step 6: Add trust verdict to run list**

Modify `AgentLens/web/src/components/run-list-table.tsx`:

- Add a `Trust` column after `Eval`.
- Render `run.trust_verdict || EM_DASH`.
- Change false-success logic to:

```ts
function isFalseSuccess(run: RunRow): boolean {
  return run.agent_outcome === "success" && (run.eval_status === "failed" || run.trust_verdict === "untrusted");
}
```

- [ ] **Step 7: Run dashboard tests**

Run:

```bash
cd AgentLens/web && npx vitest run src/components/trust-report-panel.test.tsx src/components/run-list-table.test.tsx src/integration/runs-list-route.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add AgentLens/web/src/api/runs.ts AgentLens/web/src/components/trust-report-panel.tsx AgentLens/web/src/components/trust-report-panel.test.tsx AgentLens/web/src/components/run-list-table.tsx AgentLens/web/src/components/run-list-table.test.tsx AgentLens/web/src/routes/run-detail.tsx AgentLens/web/src/integration/runs-list-route.test.tsx
git commit -m "feat: show AgentRunway trust console"
```

---

### Task 8: Remove Legacy Assumptions And Update Docs

```yaml agentrunway-task
task_id: task_008
title: Remove Legacy Assumptions And Update Docs
risk: medium
phase: implementation
dependencies: [task_001, task_004, task_006, task_007]
spec_refs: [3, 4, 10.1, 11, 12]
file_claims:
  - {path: AgentLens/docs/contract.md, mode: owned}
  - {path: AgentLens/docs/cli.md, mode: owned}
  - {path: AgentLens/docs/dashboard.md, mode: owned}
  - {path: AgentLens/tests/unit/test_schema_v2_validation.py, mode: shared_append}
  - {path: AgentLens/tests/unit/test_no_legacy_kws_namespaces.py, mode: owned}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_no_legacy_kws_namespaces.py tests/unit/test_schema_v2_validation.py -v
  - rg -n "kws-cpe|kws-cme|kws\\.orchestrator" AgentLens/src AgentLens/tests AgentLens/docs skills/agent-runway docs/superpowers/specs docs/superpowers/plans
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `AgentLens/docs/contract.md`
- Modify: `AgentLens/docs/cli.md`
- Modify: `AgentLens/docs/dashboard.md`
- Modify: `AgentLens/tests/unit/test_schema_v2_validation.py`
- Create: `AgentLens/tests/unit/test_no_legacy_kws_namespaces.py`

- [ ] **Step 1: Add legacy namespace guard test**

Create `AgentLens/tests/unit/test_no_legacy_kws_namespaces.py`:

```python
from __future__ import annotations

from pathlib import Path

FORBIDDEN = ("kws-cpe", "kws-cme", "kws.orchestrator")
ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [
    ROOT / "src",
    ROOT / "tests",
    ROOT / "docs",
    ROOT.parent / "skills" / "agent-runway",
    ROOT.parent / "docs" / "superpowers" / "plans",
]
ALLOWLIST = {
    ROOT.parent / "docs" / "superpowers" / "specs" / "2026-05-21-agentrunway-only-cpe-cme-removal-design.md",
    ROOT.parent / "docs" / "superpowers" / "specs" / "2026-05-21-agentlens-agentrunway-trust-console-design.md",
    ROOT.parent / "docs" / "superpowers" / "plans" / "2026-05-21-agentlens-agentrunway-trust-console.md",
}


def test_active_surfaces_do_not_reference_legacy_kws_namespaces() -> None:
    hits: list[str] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path in ALLOWLIST or path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".map"}:
                continue
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for token in FORBIDDEN:
                if token in text:
                    hits.append(f"{path}: {token}")
    assert hits == []
```

- [ ] **Step 2: Run guard test and verify failure**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_no_legacy_kws_namespaces.py -v
```

Expected: FAIL if active docs/tests still contain legacy namespace references outside allowlisted removal/design/plan files.

- [ ] **Step 3: Update docs**

Edit:

- `AgentLens/docs/contract.md`
- `AgentLens/docs/cli.md`
- `AgentLens/docs/dashboard.md`

Use this framing in all three:

```markdown
AgentLens Trust Console uses the AgentLens v2 run contract for AgentRunway
evidence. `agentrunway.*` is the only first-class execution event family.
CPE/CME/KWS legacy namespaces are not runtime inputs and are not compatibility
targets.
```

Replace v1-lock statements that apply to the active Trust Console path with v2 contract wording. Keep historical notes only if they are explicitly labeled as superseded.

- [ ] **Step 4: Run guard and schema tests**

Run:

```bash
cd AgentLens && python -m pytest tests/unit/test_no_legacy_kws_namespaces.py tests/unit/test_schema_v2_validation.py -v
```

Expected: PASS.

- [ ] **Step 5: Run direct legacy scan**

Run:

```bash
rg -n "kws-cpe|kws-cme|kws\\.orchestrator" AgentLens/src AgentLens/tests AgentLens/docs skills/agent-runway docs/superpowers/specs docs/superpowers/plans
```

Expected: only the allowlisted design/plan files mention those strings.

- [ ] **Step 6: Commit**

Run:

```bash
git add AgentLens/docs/contract.md AgentLens/docs/cli.md AgentLens/docs/dashboard.md AgentLens/tests/unit/test_no_legacy_kws_namespaces.py AgentLens/tests/unit/test_schema_v2_validation.py
git commit -m "docs: document AgentLens v2 trust console"
```

---

### Task 9: Final Verification And Graph Update

```yaml agentrunway-task
task_id: task_009
title: Final Verification And Graph Update
risk: medium
phase: verification
dependencies: [task_001, task_002, task_003, task_004, task_005, task_006, task_007, task_008]
spec_refs: [10, 11, 12]
file_claims:
  - {path: graphify-out, mode: generated}
acceptance_commands:
  - cd AgentLens && python -m pytest tests/unit/test_schema_v2_validation.py tests/unit/test_trust_artifacts.py tests/unit/test_agentrunway_v2_projection.py tests/unit/test_trust_report.py tests/integration/test_eval_trust_console.py tests/integration/test_trust_console_cli.py -v
  - cd AgentLens/web && npx vitest run src/components/trust-report-panel.test.tsx src/components/run-list-table.test.tsx src/integration/runs-list-route.test.tsx
  - cd skills/agent-runway && python -m pytest evals/test_agentlens_v2_events.py -v
  - git diff --check
  - graphify update .
required_skills: [verification-before-completion]
serial: true
```

**Files:**
- Modify: `graphify-out/*` if `graphify update .` changes generated graph files

- [ ] **Step 1: Run focused AgentLens Python tests**

Run:

```bash
cd AgentLens && python -m pytest \
  tests/unit/test_schema_v2_validation.py \
  tests/unit/test_trust_artifacts.py \
  tests/unit/test_agentrunway_v2_projection.py \
  tests/unit/test_trust_report.py \
  tests/integration/test_eval_trust_console.py \
  tests/integration/test_trust_console_cli.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run focused dashboard tests**

Run:

```bash
cd AgentLens/web && npx vitest run \
  src/components/trust-report-panel.test.tsx \
  src/components/run-list-table.test.tsx \
  src/integration/runs-list-route.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run focused AgentRunway tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_agentlens_v2_events.py -v
```

Expected: PASS.

- [ ] **Step 4: Run whitespace validation**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 5: Update graph**

Run:

```bash
graphify update .
```

Expected: command completes successfully. If graph output changes, include `graphify-out/` changes in the final verification commit.

- [ ] **Step 6: Inspect final status**

Run:

```bash
git status --short
```

Expected: only in-scope AgentLens, AgentRunway, docs, test, and graph files are modified.

- [ ] **Step 7: Commit**

Run:

```bash
git add AgentLens skills/agent-runway docs/superpowers/plans/2026-05-21-agentlens-agentrunway-trust-console.md graphify-out
git commit -m "feat: add AgentLens AgentRunway trust console"
```

If earlier tasks were already committed task-by-task, use this step only for graph/docs verification residue. Do not squash unrelated user changes.
