# AgentLens KWS Common Observability Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared `kws.orchestrator.event.v1` contract so CPE and CME emit the same AgentLens evidence shape and the evaluator can score evidence coverage consistently.

**Architecture:** AgentLens gets a pure KWS event parser and evidence coverage module that read existing `events.jsonl` data without changing authoritative evaluator status rules. CPE and CME keep separate internal state, but both skill specs and contract checks move their AgentLens emit surface to `kws.orchestrator.*`. Historical `kws-cpe.*` and `kws-cme.*` events remain readable through fallback parsing.

**Tech Stack:** Python 3.11+, Typer, JSON Schema, pytest, Markdown skill specs, bash-compatible AgentLens CLI calls.

---

## Scope Check

The approved design spans three code surfaces: AgentLens evaluator, CPE skill contract, and CME skill contract. This plan keeps them in one sequence because the feature is one contract, but every task is independently testable and commit-sized.

Dashboard projection and rich UI are excluded. The plan ends with CLI/evaluator/skill-contract support plus docs.

## File Structure

### Create

| Path | Responsibility |
|---|---|
| `AgentLens/src/agentlens/evaluator/kws_events.py` | Parse common and legacy KWS events into one normalized observation model; enforce payload safety limits. |
| `AgentLens/src/agentlens/evaluator/coverage.py` | Compute `evidence_coverage` from `EvalContext`, command events, manifests, imports, and KWS observations. |
| `AgentLens/tests/unit/test_kws_events.py` | Unit tests for common-envelope parsing, legacy fallback, outcome mapping, and payload safety. |
| `AgentLens/tests/unit/test_evidence_coverage.py` | Unit tests for coverage dimensions independent of full fixture trees. |
| `AgentLens/src/agentlens/store/kws_orchestrator.py` | Read CPE/CME state directories for explicit backfill imports. |
| `AgentLens/src/agentlens/commands/import_kws_orchestrator.py` | `agentlens import kws-orchestrator` command. |
| `AgentLens/tests/integration/test_import_kws_orchestrator.py` | Backfill importer integration tests. |

### Modify

| Path | Change |
|---|---|
| `AgentLens/src/agentlens/evaluator/engine.py` | Add optional `evidence_coverage` to produced `eval.json`. |
| `AgentLens/src/agentlens/schema/jsonschema/eval.schema.json` | Add optional `evidence_coverage` object; required fields remain unchanged. |
| `AgentLens/tests/unit/test_evaluator_fixtures.py` | Normalize expected fixture comparison for optional coverage or update expected outputs. |
| `AgentLens/tests/integration/test_event_append.py` | Add shared `kws.orchestrator.*` append/query coverage. |
| `AgentLens/src/agentlens/cli.py` | Import and register `import_kws_orchestrator` on the existing `import` Typer group. |
| `AgentLens/docs/contract.md` | Document the common KWS event envelope and coverage field. |
| `AgentLens/docs/cli.md` | Document `agentlens import kws-orchestrator`. |
| `skills/kws-codex-plan-executor/SKILL.md` | Replace CPE emit instructions with shared `kws.orchestrator.*` contract. |
| `skills/kws-codex-plan-executor/references/event-journal.md` | Make the common envelope authoritative for CPE replay evidence. |
| `skills/kws-codex-plan-executor/references/learning-log.md` | Map CPE notable-boundary events to common event names. |
| `skills/kws-codex-plan-executor/references/state-schema.md` | Add `agentlens_status`, `last_agentlens_event_at`, and `emitted_event_count`. |
| `skills/kws-codex-plan-executor/evals/check_skill_contract.py` | Pin the new CPE contract. |
| `skills/kws-claude-multi-agent-executor/SKILL.md` | Replace CME direct emit and candidate-drain instructions with shared `kws.orchestrator.*` contract. |
| `skills/kws-claude-multi-agent-executor/AGENTS.md` | Update outcome and event-schema guidance. |
| `skills/kws-claude-multi-agent-executor/references/learning-log.md` | Make the common envelope authoritative while documenting legacy event fallback. |
| `skills/kws-claude-multi-agent-executor/scripts/compare_agentlens_events.py` | Accept common events and legacy events during parity checks. |
| `skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py` | Pin the new CME contract and reject `--outcome blocked` / `--outcome aborted`. |

---

## Phase 1 — AgentLens Common Parser and Coverage

### Task 1: Add KWS Event Parser

**Files:**
- Create: `AgentLens/src/agentlens/evaluator/kws_events.py`
- Create: `AgentLens/tests/unit/test_kws_events.py`

- [ ] **Step 1: Write failing parser tests**

Add `AgentLens/tests/unit/test_kws_events.py`:

```python
from __future__ import annotations

from agentlens.evaluator.kws_events import (
    COMMON_SCHEMA,
    payload_safety,
    parse_kws_event,
)


def _event(event_type: str, payload: dict) -> dict:
    return {
        "schema": "agentlens.event.v1",
        "event_id": "evt_aaaaaaaaaaaa",
        "run_id": "run_20260101_000000_aaaaaa",
        "ts": "2026-01-01T00:00:01Z",
        "type": event_type,
        "payload": payload,
    }


def test_parse_common_verification_event() -> None:
    payload = {
        "schema": COMMON_SCHEMA,
        "producer": "kws-cpe",
        "producer_run_id": "cpe-1",
        "phase": "verification",
        "event_name": "verification_evidence",
        "task_id": "task_3",
        "outcome": "success",
        "severity": "info",
        "evidence": {
            "kind": "test",
            "command_hash": "sha256:" + "1" * 64,
            "status": "passed",
            "artifact_ref": "state:verification_evidence[0]",
            "summary": "pytest passed",
        },
        "context": {
            "health": "green",
            "handoff_ready": True,
            "residual_risk_count": 0,
            "medium_plus_residual_risk_count": 0,
            "changed_files_count": 2,
            "context_snapshot_ref": "state:context_snapshot_path",
        },
    }
    obs = parse_kws_event(_event("kws.orchestrator.verification_evidence", payload))
    assert obs is not None
    assert obs.kind == "verification_evidence"
    assert obs.producer == "kws-cpe"
    assert obs.outcome == "success"
    assert obs.verification_status == "passed"
    assert obs.evidence_kind == "test"
    assert obs.command_hash == "sha256:" + "1" * 64
    assert obs.payload_safety == "ok"


def test_parse_legacy_kws_cme_event_as_legacy_observation() -> None:
    obs = parse_kws_event(
        _event(
            "kws-cme.context_health",
            {
                "event_type": "context_health",
                "severity": "low",
                "phase": "phase_0",
                "context": {"completed_tasks_count": 3},
            },
        )
    )
    assert obs is not None
    assert obs.producer == "kws-cme"
    assert obs.kind == "context_health"
    assert obs.legacy is True
    assert obs.payload_safety == "ok"


def test_payload_safety_flags_raw_context_and_oversized_payload() -> None:
    raw = {"note": "<permissions instructions> keep this out"}
    assert payload_safety(raw) == "raw_context_detected"
    large = {"summary": "x" * 5000}
    assert payload_safety(large) == "oversized"
```

- [ ] **Step 2: Run the parser tests and verify they fail**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_kws_events.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentlens.evaluator.kws_events'`.

- [ ] **Step 3: Add the parser implementation**

Create `AgentLens/src/agentlens/evaluator/kws_events.py`:

```python
"""Normalize KWS orchestrator events for evaluator coverage."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

COMMON_SCHEMA = "kws.orchestrator.event.v1"
COMMON_PREFIX = "kws.orchestrator."
LEGACY_PREFIXES = ("kws-cpe.", "kws-cpe.learning.", "kws-cme.")
PRODUCERS = {"kws-cpe", "kws-cme"}
OUTCOMES = {"success", "failed", "partial", "cancelled", "unknown"}
PAYLOAD_BYTE_LIMIT = 4096
SUMMARY_CHAR_LIMIT = 512

RAW_CONTEXT_MARKERS = (
    "<permissions instructions>",
    "<app-context>",
    "<environment_context>",
    "AGENTS.md instructions",
    "developer_instructions",
)
ABS_HOME_RE = re.compile(r"(^|[\"'\\s])/(Users|home)/[^\\s\"']+")


PayloadSafety = Literal["ok", "oversized", "raw_context_detected"]


@dataclass(frozen=True)
class KwsObservation:
    producer: str
    kind: str
    phase: str
    outcome: str
    task_id: str | None
    severity: str
    evidence_kind: str | None
    verification_status: str | None
    command_hash: str | None
    context_health: str | None
    residual_risk_count: int
    medium_plus_residual_risk_count: int
    agentlens_status: str | None
    payload_safety: PayloadSafety
    legacy: bool


def normalize_outcome(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    mapping = {
        "finished": "success",
        "ok": "success",
        "blocked": "partial",
        "aborted": "cancelled",
    }
    raw = mapping.get(raw, raw)
    return raw if raw in OUTCOMES else "unknown"


def payload_safety(payload: dict[str, Any]) -> PayloadSafety:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if any(marker in encoded for marker in RAW_CONTEXT_MARKERS):
        return "raw_context_detected"
    if ABS_HOME_RE.search(encoded):
        return "raw_context_detected"
    if len(encoded.encode("utf-8")) > PAYLOAD_BYTE_LIMIT:
        return "oversized"
    return "ok"


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _parse_common(kind: str, payload: dict[str, Any]) -> KwsObservation | None:
    if payload.get("schema") != COMMON_SCHEMA:
        return None
    producer = payload.get("producer")
    if producer not in PRODUCERS:
        return None
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    context = payload.get("context")
    if not isinstance(context, dict):
        context = {}
    summary = evidence.get("summary")
    if isinstance(summary, str) and len(summary) > SUMMARY_CHAR_LIMIT:
        return KwsObservation(
            producer=producer,
            kind=kind,
            phase=str(payload.get("phase") or "execution"),
            outcome=normalize_outcome(payload.get("outcome")),
            task_id=payload.get("task_id") if isinstance(payload.get("task_id"), str) else None,
            severity=str(payload.get("severity") or "info"),
            evidence_kind=evidence.get("kind") if isinstance(evidence.get("kind"), str) else None,
            verification_status=evidence.get("status") if isinstance(evidence.get("status"), str) else None,
            command_hash=evidence.get("command_hash") if isinstance(evidence.get("command_hash"), str) else None,
            context_health=context.get("health") if isinstance(context.get("health"), str) else None,
            residual_risk_count=_int_value(context.get("residual_risk_count")),
            medium_plus_residual_risk_count=_int_value(context.get("medium_plus_residual_risk_count")),
            agentlens_status=payload.get("agentlens_status") if isinstance(payload.get("agentlens_status"), str) else None,
            payload_safety="oversized",
            legacy=False,
        )
    return KwsObservation(
        producer=producer,
        kind=kind,
        phase=str(payload.get("phase") or "execution"),
        outcome=normalize_outcome(payload.get("outcome")),
        task_id=payload.get("task_id") if isinstance(payload.get("task_id"), str) else None,
        severity=str(payload.get("severity") or "info"),
        evidence_kind=evidence.get("kind") if isinstance(evidence.get("kind"), str) else None,
        verification_status=evidence.get("status") if isinstance(evidence.get("status"), str) else None,
        command_hash=evidence.get("command_hash") if isinstance(evidence.get("command_hash"), str) else None,
        context_health=context.get("health") if isinstance(context.get("health"), str) else None,
        residual_risk_count=_int_value(context.get("residual_risk_count")),
        medium_plus_residual_risk_count=_int_value(context.get("medium_plus_residual_risk_count")),
        agentlens_status=payload.get("agentlens_status") if isinstance(payload.get("agentlens_status"), str) else None,
        payload_safety=payload_safety(payload),
        legacy=False,
    )


def _parse_legacy(event_type: str, payload: dict[str, Any]) -> KwsObservation | None:
    if event_type.startswith("kws-cpe."):
        producer = "kws-cpe"
        prefix = "kws-cpe.learning." if event_type.startswith("kws-cpe.learning.") else "kws-cpe."
    elif event_type.startswith("kws-cme."):
        producer = "kws-cme"
        prefix = "kws-cme."
    else:
        return None
    kind = event_type.removeprefix(prefix)
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    return KwsObservation(
        producer=producer,
        kind=str(payload.get("event_type") or kind),
        phase=str(payload.get("phase") or "execution"),
        outcome=normalize_outcome(payload.get("outcome")),
        task_id=None,
        severity=str(payload.get("severity") or "info"),
        evidence_kind=None,
        verification_status=None,
        command_hash=None,
        context_health=context.get("health") if isinstance(context.get("health"), str) else None,
        residual_risk_count=0,
        medium_plus_residual_risk_count=0,
        agentlens_status=None,
        payload_safety=payload_safety(payload),
        legacy=True,
    )


def parse_kws_event(event: dict[str, Any]) -> KwsObservation | None:
    event_type = event.get("type")
    payload = event.get("payload")
    if not isinstance(event_type, str) or not isinstance(payload, dict):
        return None
    if event_type.startswith(COMMON_PREFIX):
        kind = event_type.removeprefix(COMMON_PREFIX)
        return _parse_common(kind, payload)
    if event_type.startswith(LEGACY_PREFIXES):
        return _parse_legacy(event_type, payload)
    return None


__all__ = [
    "COMMON_SCHEMA",
    "KwsObservation",
    "normalize_outcome",
    "parse_kws_event",
    "payload_safety",
]
```

- [ ] **Step 4: Run parser tests and verify they pass**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_kws_events.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add AgentLens/src/agentlens/evaluator/kws_events.py AgentLens/tests/unit/test_kws_events.py
git commit -m "feat(agentlens): parse common KWS orchestrator events"
```

### Task 2: Add Evidence Coverage Computation

**Files:**
- Create: `AgentLens/src/agentlens/evaluator/coverage.py`
- Create: `AgentLens/tests/unit/test_evidence_coverage.py`
- Modify: `AgentLens/src/agentlens/evaluator/engine.py`
- Modify: `AgentLens/src/agentlens/schema/jsonschema/eval.schema.json`

- [ ] **Step 1: Write failing coverage tests**

Add `AgentLens/tests/unit/test_evidence_coverage.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentlens.constants import SCHEMA_EVENT_V1, SCHEMA_FINAL_V1, SCHEMA_RUN_V1
from agentlens.evaluator.checks import EvalContext
from agentlens.evaluator.coverage import compute_evidence_coverage
from agentlens.evaluator.kws_events import COMMON_SCHEMA


def _ctx(events: list[dict], final: dict | None = None, manifest: dict | None = None) -> EvalContext:
    run = {
        "schema": SCHEMA_RUN_V1,
        "run_id": "run_20260101_000000_aaaaaa",
        "workspace_id": "ws_0000000000000000",
        "started_at": "2026-01-01T00:00:00Z",
        "run_kind": "container",
        "agent": {"name": "generic", "mode": "unknown", "label": "kws-cpe-orchestrator"},
        "workspace": {
            "root_label": "workspace",
            "root_hash": "sha256:" + "0" * 64,
            "id_basis": "path",
        },
        "recording": {
            "mode": "minimal",
            "adapter": "agentlens_container",
            "has_transcript": False,
            "transcript_source": "none",
        },
    }
    return EvalContext(
        run=run,
        events=events,
        events_lines=[json.dumps(e) for e in events],
        final=final,
        manifest=manifest,
        run_dir=Path("."),
    )


def _event(event_type: str, payload: dict) -> dict:
    return {
        "schema": SCHEMA_EVENT_V1,
        "event_id": "evt_aaaaaaaaaaaa",
        "run_id": "run_20260101_000000_aaaaaa",
        "ts": "2026-01-01T00:00:01Z",
        "type": event_type,
        "payload": payload,
    }


def test_coverage_sees_test_backed_kws_verification() -> None:
    event = _event(
        "kws.orchestrator.verification_evidence",
        {
            "schema": COMMON_SCHEMA,
            "producer": "kws-cpe",
            "producer_run_id": "cpe-1",
            "phase": "verification",
            "event_name": "verification_evidence",
            "task_id": "task_1",
            "outcome": "success",
            "severity": "info",
            "evidence": {
                "kind": "test",
                "command_hash": "sha256:" + "1" * 64,
                "status": "passed",
                "artifact_ref": "state:verification_evidence[0]",
            },
            "context": {"health": "green", "residual_risk_count": 0, "medium_plus_residual_risk_count": 0},
        },
    )
    coverage = compute_evidence_coverage(_ctx([event]))
    assert coverage["verification_strength"] == "test_backed"
    assert coverage["kws_observability"] == "present"
    assert coverage["canonical_payload_safety"] == "ok"


def test_coverage_flags_legacy_hashless_command_finished() -> None:
    started = _event("command.started", {"command_hash": "sha256:" + "2" * 64})
    finished = _event("command.finished", {"exit_code": 0})
    coverage = compute_evidence_coverage(_ctx([started, finished]))
    assert coverage["command_linkage"] == "legacy_hashless"


def test_coverage_flags_disabled_kws_observability() -> None:
    disabled = _event(
        "kws.orchestrator.run_started",
        {
            "schema": COMMON_SCHEMA,
            "producer": "kws-cme",
            "producer_run_id": "cme-1",
            "phase": "setup",
            "event_name": "run_started",
            "task_id": None,
            "outcome": "unknown",
            "severity": "warn",
            "agentlens_status": "unavailable",
            "evidence": None,
            "context": None,
        },
    )
    coverage = compute_evidence_coverage(_ctx([disabled]))
    assert coverage["kws_observability"] == "disabled"


def test_coverage_marks_explicit_kws_backfill() -> None:
    ctx = _ctx([])
    ctx.run["meta"] = {"import_state": "full", "kws_kind": "cpe"}
    coverage = compute_evidence_coverage(ctx)
    assert coverage["kws_observability"] == "backfilled"
```

- [ ] **Step 2: Run coverage tests and verify they fail**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_evidence_coverage.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentlens.evaluator.coverage'`.

- [ ] **Step 3: Add coverage module**

Create `AgentLens/src/agentlens/evaluator/coverage.py`:

```python
"""Evidence coverage scoring for AgentLens eval output."""
from __future__ import annotations

from typing import Any

from .checks import EvalContext
from .kws_events import KwsObservation, parse_kws_event


def _command_linkage(ctx: EvalContext) -> str:
    started = []
    finished = []
    hashless_finished = 0
    for ev in ctx.events:
        payload = ev.get("payload") if isinstance(ev, dict) else None
        if not isinstance(payload, dict):
            continue
        command_hash = payload.get("command_hash")
        if ev.get("type") == "command.started" and isinstance(command_hash, str):
            started.append(command_hash)
        if ev.get("type") == "command.finished":
            if isinstance(command_hash, str):
                finished.append(command_hash)
            else:
                hashless_finished += 1
    if not started:
        return "none"
    pending = list(started)
    for command_hash in finished:
        if command_hash in pending:
            pending.remove(command_hash)
    if not pending:
        return "full"
    if hashless_finished and len(started) == hashless_finished + len(finished):
        return "legacy_hashless"
    return "missing_finished"


def _observations(ctx: EvalContext) -> list[KwsObservation]:
    return [obs for ev in ctx.events if (obs := parse_kws_event(ev)) is not None]


def _verification_strength(ctx: EvalContext, observations: list[KwsObservation]) -> str:
    evidence_kinds = {obs.evidence_kind for obs in observations if obs.verification_status == "passed"}
    if "test" in evidence_kinds:
        return "test_backed"
    if {"lint", "typecheck", "command"} & evidence_kinds:
        return "direct_command"
    if "manual" in evidence_kinds:
        return "manual"
    if any(obs.kind == "verification_evidence" for obs in observations):
        return "weak"
    final_verification = (ctx.final or {}).get("verification") or []
    if final_verification:
        return "direct_command"
    return "none"


def _manifest_integrity(ctx: EvalContext) -> str:
    if ctx.manifest is None:
        return "missing"
    return "sealed" if ctx.manifest.get("sealed") is True else "mismatch"


def _import_completeness(ctx: EvalContext) -> str:
    meta = ctx.run.get("meta")
    if isinstance(meta, dict) and meta.get("import_state") in {"full", "partial", "unfinalized"}:
        return str(meta["import_state"])
    input_block = ctx.run.get("input")
    if isinstance(input_block, dict) and input_block.get("import_key"):
        return "full" if ctx.final is not None else "unfinalized"
    return "not_imported"


def _payload_safety(observations: list[KwsObservation]) -> str:
    if any(obs.payload_safety == "raw_context_detected" for obs in observations):
        return "raw_context_detected"
    if any(obs.payload_safety == "oversized" for obs in observations):
        return "oversized"
    return "ok"


def _is_kws_backfill(ctx: EvalContext) -> bool:
    meta = ctx.run.get("meta")
    return isinstance(meta, dict) and meta.get("kws_kind") in {"cpe", "cme"}


def _kws_observability(observations: list[KwsObservation], ctx: EvalContext) -> str:
    if _is_kws_backfill(ctx):
        return "backfilled"
    if any(obs.agentlens_status == "unavailable" for obs in observations):
        return "disabled"
    if any(not obs.legacy for obs in observations):
        return "present"
    if observations:
        return "legacy_only"
    label = (ctx.run.get("agent") or {}).get("label") if isinstance(ctx.run.get("agent"), dict) else None
    if isinstance(label, str) and label.startswith(("kws-cpe", "kws-cme")):
        return "missing"
    return "missing"


def compute_evidence_coverage(ctx: EvalContext) -> dict[str, Any]:
    observations = _observations(ctx)
    return {
        "command_linkage": _command_linkage(ctx),
        "verification_strength": _verification_strength(ctx, observations),
        "manifest_integrity": _manifest_integrity(ctx),
        "import_completeness": _import_completeness(ctx),
        "canonical_payload_safety": _payload_safety(observations),
        "kws_observability": _kws_observability(observations, ctx),
    }


__all__ = ["compute_evidence_coverage"]
```

- [ ] **Step 4: Wire coverage into evaluator output**

Modify `AgentLens/src/agentlens/evaluator/engine.py`:

```python
from .coverage import compute_evidence_coverage
```

Add `evidence_coverage` to the normal `doc` produced in `evaluate()`:

```python
    doc: dict[str, Any] = {
        "schema": SCHEMA_EVAL_V1,
        "run_id": ctx.run.get("run_id", run_dir.name),
        "evaluated_at": utc_now_iso(),
        "status": status,
        "agent_outcome": agent_outcome,
        "checks": [r.to_dict() for r in sorted_results],
        "failures": [f.to_dict() for f in sorted_failures],
        "evidence_coverage": compute_evidence_coverage(ctx),
    }
```

Leave `_minimal_error_eval()` without `evidence_coverage`; load failures have no usable `EvalContext`.

- [ ] **Step 5: Extend eval schema**

Modify `AgentLens/src/agentlens/schema/jsonschema/eval.schema.json` by adding this optional property under `properties`:

```json
    "evidence_coverage": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "command_linkage",
        "verification_strength",
        "manifest_integrity",
        "import_completeness",
        "canonical_payload_safety",
        "kws_observability"
      ],
      "properties": {
        "command_linkage": {
          "type": "string",
          "enum": ["full", "legacy_hashless", "missing_finished", "none"]
        },
        "verification_strength": {
          "type": "string",
          "enum": ["test_backed", "direct_command", "manual", "weak", "none"]
        },
        "manifest_integrity": {
          "type": "string",
          "enum": ["sealed", "missing", "mismatch"]
        },
        "import_completeness": {
          "type": "string",
          "enum": ["not_imported", "full", "partial", "unfinalized"]
        },
        "canonical_payload_safety": {
          "type": "string",
          "enum": ["ok", "oversized", "raw_context_detected"]
        },
        "kws_observability": {
          "type": "string",
          "enum": ["present", "legacy_only", "backfilled", "missing", "disabled"]
        }
      }
    }
```

- [ ] **Step 6: Run tests and update evaluator fixture expected outputs**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_evidence_coverage.py tests/unit/test_kws_events.py tests/unit/test_evaluator_fixtures.py -v
```

Expected before fixture updates: coverage tests pass; fixture byte-equality tests fail because `expected_eval.json` lacks `evidence_coverage`.

For each `AgentLens/tests/fixtures/*_run/expected_eval.json`, run `evaluate()` against a copied fixture and update the expected file with the new optional `evidence_coverage`. Keep the existing `status`, `checks`, and `failures` values unchanged.

- [ ] **Step 7: Run focused test set**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_kws_events.py tests/unit/test_evidence_coverage.py tests/unit/test_evaluator_fixtures.py tests/unit/test_schema_validation.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add AgentLens/src/agentlens/evaluator/coverage.py AgentLens/src/agentlens/evaluator/engine.py AgentLens/src/agentlens/schema/jsonschema/eval.schema.json AgentLens/tests/unit/test_evidence_coverage.py AgentLens/tests/fixtures
git commit -m "feat(agentlens): add evaluator evidence coverage"
```

### Task 3: Add Shared KWS Event Append Coverage

**Files:**
- Modify: `AgentLens/tests/integration/test_event_append.py`

- [ ] **Step 1: Add failing integration test for common event namespace**

Append this test to `AgentLens/tests/integration/test_event_append.py`:

```python
def test_event_append_accepts_common_kws_orchestrator_event(
    runner: CliRunner, workspace: Path
) -> None:
    run_id = _open_run(runner, agent="kws-cpe-orchestrator")
    run_dir = _resolve_run_dir(workspace, run_id)
    payload = {
        "schema": "kws.orchestrator.event.v1",
        "producer": "kws-cpe",
        "producer_run_id": "cpe-1",
        "phase": "verification",
        "event_name": "verification_evidence",
        "task_id": "task_1",
        "outcome": "success",
        "severity": "info",
        "evidence": {
            "kind": "test",
            "command_hash": "sha256:" + "3" * 64,
            "status": "passed",
            "artifact_ref": "state:verification_evidence[0]",
        },
        "context": {
            "health": "green",
            "handoff_ready": True,
            "residual_risk_count": 0,
            "medium_plus_residual_risk_count": 0,
        },
    }
    result = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws.orchestrator.verification_evidence",
            "--payload-json",
            json.dumps(payload),
        ],
    )
    assert result.exit_code == 0, result.stderr
    events = _read_events(run_dir)
    assert events[-1]["type"] == "kws.orchestrator.verification_evidence"
    assert events[-1]["payload"]["schema"] == "kws.orchestrator.event.v1"
```

- [ ] **Step 2: Run the integration test**

Run:

```bash
cd AgentLens
python -m pytest tests/integration/test_event_append.py::test_event_append_accepts_common_kws_orchestrator_event -v
```

Expected: pass. If it fails, inspect `AgentLens/src/agentlens/schema/jsonschema/event.schema.json`; the namespace pattern must accept `kws.orchestrator.verification_evidence`.

- [ ] **Step 3: Commit Task 3**

```bash
git add AgentLens/tests/integration/test_event_append.py
git commit -m "test(agentlens): cover common KWS event append"
```

---

## Phase 2 — CPE Contract Migration

### Task 4: Update CPE AgentLens Contract Text

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/references/event-journal.md`
- Modify: `skills/kws-codex-plan-executor/references/learning-log.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`

- [ ] **Step 1: Update CPE event journal**

Replace the first sentence of `skills/kws-codex-plan-executor/references/event-journal.md` with:

```markdown
Replay evidence is emitted to AgentLens under the shared `kws.orchestrator.EVENT_NAME` namespace using payload schema `kws.orchestrator.event.v1`.
```

Add this contract block after the source-of-truth paragraph:

```markdown
Common payload envelope:

```json
{
  "schema": "kws.orchestrator.event.v1",
  "producer": "kws-cpe",
  "producer_run_id": "cpe-20260520-001",
  "phase": "setup|execution|verification|handoff|final",
  "event_name": "run_started|context_health|task_started|task_finished|verification_evidence|blocker|run_finished",
  "task_id": "task_3",
  "outcome": "success|failed|partial|cancelled|unknown",
  "severity": "info|warn|error",
  "evidence": {
    "kind": "test|lint|typecheck|review|manual|state_check|command",
    "command_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "status": "passed|failed|skipped",
    "artifact_ref": "state:verification_evidence[0]"
  },
  "context": {
    "health": "green|yellow|red",
    "handoff_ready": true,
    "residual_risk_count": 0,
    "medium_plus_residual_risk_count": 0,
    "changed_files_count": 2
  }
}
```
```

- [ ] **Step 2: Update CPE learning-log lifecycle**

In `skills/kws-codex-plan-executor/references/learning-log.md`, replace the `agentlens event append` example with:

```bash
PAYLOAD="$(jq -nc \
  --arg producer_run_id "$RUN_ID" \
  --arg event_name "$EVENT_NAME" \
  --arg phase "$PHASE" \
  --arg outcome "$AGENTLENS_OUTCOME" \
  --arg severity "$SEVERITY" \
  '{
    schema:"kws.orchestrator.event.v1",
    producer:"kws-cpe",
    producer_run_id:$producer_run_id,
    phase:$phase,
    event_name:$event_name,
    task_id:null,
    outcome:$outcome,
    severity:$severity,
    evidence:null,
    context:null
  }')"
[ -n "${ORCH_RUN_ID:-}" ] && agentlens event append --run "$ORCH_RUN_ID" --type "kws.orchestrator.${EVENT_NAME}" --payload-json "$PAYLOAD" 2>/dev/null || true
```

Keep the CPE mapping:

```markdown
- `finished -> success`
- `blocked -> partial`
- `failed -> failed`
- `cancelled -> cancelled`
```

- [ ] **Step 3: Add CPE state fields**

In `skills/kws-codex-plan-executor/references/state-schema.md`, add these fields to the run-level state section:

```markdown
AgentLens observability fields:

- `agentlens_orchestration_run`: string|null. AgentLens container run id returned by `agentlens run-open`.
- `agentlens_status`: `active|unavailable|error`. `unavailable` means the CLI was absent or `run-open` returned no id.
- `last_agentlens_event_at`: string|null. UTC timestamp of the last successful best-effort event append known to the orchestrator.
- `emitted_event_count`: integer. Best-effort count of common `kws.orchestrator.*` events attempted after `run-open`.
```

- [ ] **Step 4: Update CPE SKILL.md overview**

In `skills/kws-codex-plan-executor/SKILL.md`, replace the existing `kws-cpe.task_finished` and `kws-cpe.learning.completion_learning` contract bullets with:

```markdown
- Execution runs maintain replay evidence through AgentLens events under the shared `kws.orchestrator.EVENT_NAME` namespace. Payloads use `schema="kws.orchestrator.event.v1"` and `producer="kws-cpe"`. State remains authoritative; AgentLens events are bounded observability data.
- At run init the orchestrator opens an AgentLens run with `agentlens run-open --agent kws-cpe-orchestrator --workspace "$WORKTREE_ABS" --meta plan="$PLAN_PATH"`, persists the returned id as `agentlens_orchestration_run`, and records `agentlens_status=active`. If no id is returned, it records `agentlens_status=unavailable` and proceeds.
- Every AgentLens event call is guarded by `[ -n "${ORCH_RUN_ID:-}" ]` and suffixed with `2>/dev/null || true`; AgentLens failures never block plan execution.
```

- [ ] **Step 5: Run CPE contract eval and inspect failures**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md
```

Expected before Task 5: failures mention old `kws-cpe.*` expectations and missing common envelope checks.

- [ ] **Step 6: Commit Task 4**

```bash
git add skills/kws-codex-plan-executor/SKILL.md skills/kws-codex-plan-executor/references/event-journal.md skills/kws-codex-plan-executor/references/learning-log.md skills/kws-codex-plan-executor/references/state-schema.md
git commit -m "docs(cpe): adopt common KWS AgentLens contract"
```

### Task 5: Update CPE Contract Eval

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_skill_contract.py`

- [ ] **Step 1: Replace old CPE AgentLens checks**

In `skills/kws-codex-plan-executor/evals/check_skill_contract.py`, replace the `agentlens_replay_contract` and `learning_log_lifecycle` checks with:

```python
        "learning_log_lifecycle": all(
            token in learning
            for token in (
                "agentlens event append",
                "run-close",
                "kws.orchestrator.",
                "kws.orchestrator.event.v1",
                "producer:\"kws-cpe\"",
            )
        ),
        "agentlens_replay_contract": "kws.orchestrator.EVENT_NAME" in event_journal
        and "kws.orchestrator.event.v1" in event_journal
        and "producer" in event_journal
        and "State remains authoritative" in event_journal,
        "agentlens_status_contract": all(
            token in runtime
            for token in (
                "agentlens_status",
                "active|unavailable|error",
                "last_agentlens_event_at",
                "emitted_event_count",
            )
        ),
```

- [ ] **Step 2: Update banned legacy runtime tokens**

Keep `events.jsonl`, old helper names, and learning directory entries banned. Do not ban `kws-cpe.` because historical compatibility prose may mention it. Add a positive check that new runtime text contains `kws.orchestrator.`.

- [ ] **Step 3: Run CPE contract eval**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md
```

Expected: JSON output has `"passed": true`.

- [ ] **Step 4: Commit Task 5**

```bash
git add skills/kws-codex-plan-executor/evals/check_skill_contract.py
git commit -m "test(cpe): pin common AgentLens observability contract"
```

---

## Phase 3 — CME Contract Migration

### Task 6: Update CME AgentLens Contract Text and Outcome Mapping

**Files:**
- Modify: `skills/kws-claude-multi-agent-executor/SKILL.md`
- Modify: `skills/kws-claude-multi-agent-executor/AGENTS.md`
- Modify: `skills/kws-claude-multi-agent-executor/references/learning-log.md`

- [ ] **Step 1: Update AGENTS outcome guidance**

In `skills/kws-claude-multi-agent-executor/AGENTS.md`, replace the AgentLens outcome sentence with:

```markdown
After the common observability cutover, the canonical "did this run finish cleanly?" signal is the AgentLens `run-close --outcome` value using AgentLens outcomes (`success|failed|partial|cancelled|unknown`). Map CME local `blocked -> partial` and `aborted -> cancelled` before calling `run-close`.
```

- [ ] **Step 2: Update CME run-open unavailable state guidance**

In `skills/kws-claude-multi-agent-executor/SKILL.md`, extend the `ORCH_RUN_ID` empty branch prose:

```markdown
If `ORCH_RUN_ID` is empty, set `agentlens_orchestration_run` to `null`, `agentlens_status` to `"unavailable"`, `last_agentlens_event_at` to `null`, and `emitted_event_count` to `0` in state. If a later AgentLens call fails while a run id exists, preserve the run id and set `agentlens_status` to `"error"` only in the next successful state write.
```

- [ ] **Step 3: Replace direct CME event examples**

For each direct legacy block such as `agentlens event append --type "kws-cme.phase_0_started"` in `skills/kws-claude-multi-agent-executor/SKILL.md`, update the type to its mapped `kws.orchestrator.*` name and describe the common payload envelope.

Use these mappings:

```text
kws-cme.phase_0_started -> kws.orchestrator.run_started
kws-cme.task_completed -> kws.orchestrator.task_finished
kws-cme.context_health -> kws.orchestrator.context_health
kws-cme.compaction -> kws.orchestrator.context_health
kws-cme.blocker -> kws.orchestrator.blocker
kws-cme.phase_2_complete -> kws.orchestrator.run_finished
```

- [ ] **Step 4: Fix CME run-close examples**

Replace every CME `agentlens run-close --outcome blocked` with:

```bash
agentlens run-close --run "$ORCH_RUN_ID" --outcome partial 2>/dev/null || true
```

Replace every CME `agentlens run-close --outcome aborted` with:

```bash
agentlens run-close --run "$ORCH_RUN_ID" --outcome cancelled 2>/dev/null || true
```

Keep success as:

```bash
agentlens run-close --run "$ORCH_RUN_ID" --outcome success 2>/dev/null || true
```

- [ ] **Step 5: Update CME learning-log cutover banner**

In `skills/kws-claude-multi-agent-executor/references/learning-log.md`, add this paragraph near the top:

```markdown
Common observability contract: v2.18+ emits AgentLens events under `kws.orchestrator.EVENT_NAME` with payload `schema="kws.orchestrator.event.v1"` and `producer="kws-cme"`. Historical event names such as `kws-cme.context_health` remain readable for old runs and parity tooling, but new runs use the common namespace.
```

- [ ] **Step 6: Run CME contract eval and inspect failures**

Run:

```bash
python3 skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py --skill skills/kws-claude-multi-agent-executor/SKILL.md
```

Expected before Task 7: failures mention old `kws-cme.*` expectations and blocked/aborted outcome checks.

- [ ] **Step 7: Commit Task 6**

```bash
git add skills/kws-claude-multi-agent-executor/SKILL.md skills/kws-claude-multi-agent-executor/AGENTS.md skills/kws-claude-multi-agent-executor/references/learning-log.md
git commit -m "docs(cme): adopt common KWS AgentLens contract"
```

### Task 7: Update CME Contract Eval and Parity Script

**Files:**
- Modify: `skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py`
- Modify: `skills/kws-claude-multi-agent-executor/scripts/compare_agentlens_events.py`

- [ ] **Step 1: Update CME contract checks**

In `skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py`, update AgentLens tokens:

```python
COMMON_AGENTLENS_TOKENS = [
    "ORCH_RUN_ID",
    "agentlens run-open",
    "agentlens event append",
    "agentlens run-close",
    "kws.orchestrator.",
    "kws.orchestrator.event.v1",
    'producer="kws-cme"',
]
```

Update the exit-path check to require AgentLens-allowed outcomes:

```python
    record(
        "skill_md_describes_agentlens_allowed_exit_paths",
        all(token in skill_text for token in [
            "--outcome success",
            "--outcome partial",
            "--outcome cancelled",
        ])
        and "--outcome blocked" not in skill_text
        and "--outcome aborted" not in skill_text,
        "SKILL.md must map CME blocked->partial and aborted->cancelled before run-close",
    )
```

- [ ] **Step 2: Update parity script event normalization**

In `skills/kws-claude-multi-agent-executor/scripts/compare_agentlens_events.py`, add a normalization helper:

```python
COMMON_EVENT_MAP = {
    "kws-cme.phase_0_started": "kws.orchestrator.run_started",
    "kws-cme.task_completed": "kws.orchestrator.task_finished",
    "kws-cme.context_health": "kws.orchestrator.context_health",
    "kws-cme.compaction": "kws.orchestrator.context_health",
    "kws-cme.blocker": "kws.orchestrator.blocker",
    "kws-cme.phase_2_complete": "kws.orchestrator.run_finished",
}


def normalize_agentlens_event_type(event_type: str) -> str:
    return COMMON_EVENT_MAP.get(event_type, event_type)
```

Use `normalize_agentlens_event_type()` before comparing event types from old and new streams.

- [ ] **Step 3: Run CME eval and parity self-test**

Run:

```bash
python3 skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py --skill skills/kws-claude-multi-agent-executor/SKILL.md
python3 skills/kws-claude-multi-agent-executor/scripts/compare_agentlens_events.py --self-test
```

Expected: both commands exit 0.

- [ ] **Step 4: Commit Task 7**

```bash
git add skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py skills/kws-claude-multi-agent-executor/scripts/compare_agentlens_events.py
git commit -m "test(cme): pin common AgentLens observability contract"
```

---

## Phase 4 — KWS Backfill Importer

### Task 8: Add KWS Orchestrator State Reader

**Files:**
- Create: `AgentLens/src/agentlens/store/kws_orchestrator.py`
- Create: `AgentLens/tests/unit/test_kws_orchestrator_store.py`

- [ ] **Step 1: Write failing store tests**

Create `AgentLens/tests/unit/test_kws_orchestrator_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentlens.store.kws_orchestrator import load_kws_state, summarize_kws_state


def test_load_cpe_state_and_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "cpe"
    run_dir.mkdir()
    state = {
        "run_id": "cpe-1",
        "agentlens_status": "unavailable",
        "lifecycle_outcome": "finished",
        "completion_audit": {
            "verification_evidence": [
                {"command": "pytest", "status": "passed", "evidence": "3 passed"}
            ],
            "residual_risk": [],
        },
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    loaded = load_kws_state(run_dir)
    summary = summarize_kws_state("cpe", loaded)
    assert summary["producer"] == "kws-cpe"
    assert summary["producer_run_id"] == "cpe-1"
    assert summary["agentlens_status"] == "unavailable"
    assert summary["outcome"] == "success"
    assert summary["verification_count"] == 1


def test_load_state_rejects_missing_state_json(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    try:
        load_kws_state(missing)
    except FileNotFoundError as exc:
        assert "state.json" in str(exc)
    else:
        raise AssertionError("load_kws_state must reject a directory without state.json")
```

- [ ] **Step 2: Run store tests and verify they fail**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_kws_orchestrator_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentlens.store.kws_orchestrator'`.

- [ ] **Step 3: Implement state reader**

Create `AgentLens/src/agentlens/store/kws_orchestrator.py`:

```python
"""Read bounded summaries from KWS orchestrator state directories."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from agentlens.evaluator.kws_events import normalize_outcome


Kind = Literal["cpe", "cme"]


def load_kws_state(run_dir: Path) -> dict[str, Any]:
    state_path = Path(run_dir) / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"state.json not found under {run_dir}")
    parsed = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"state.json under {run_dir} is not a JSON object")
    return parsed


def _producer(kind: Kind) -> str:
    return "kws-cpe" if kind == "cpe" else "kws-cme"


def _producer_run_id(state: dict[str, Any]) -> str:
    for key in ("run_id", "id", "session_id"):
        value = state.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _verification_count(state: dict[str, Any]) -> int:
    audit = state.get("completion_audit")
    if isinstance(audit, dict):
        evidence = audit.get("verification_evidence")
        if isinstance(evidence, list):
            return len(evidence)
    evidence = state.get("verification_evidence")
    if isinstance(evidence, list):
        return len(evidence)
    return 0


def _residual_risk_count(state: dict[str, Any]) -> int:
    audit = state.get("completion_audit")
    if isinstance(audit, dict):
        risks = audit.get("residual_risk") or audit.get("residual_risks")
        if isinstance(risks, list):
            return len(risks)
    risks = state.get("residual_risk") or state.get("residual_risks")
    if isinstance(risks, list):
        return len(risks)
    return 0


def summarize_kws_state(kind: Kind, state: dict[str, Any]) -> dict[str, Any]:
    local_outcome = state.get("lifecycle_outcome") or state.get("outcome")
    return {
        "producer": _producer(kind),
        "producer_run_id": _producer_run_id(state),
        "agentlens_status": state.get("agentlens_status") if isinstance(state.get("agentlens_status"), str) else None,
        "outcome": normalize_outcome(local_outcome),
        "verification_count": _verification_count(state),
        "residual_risk_count": _residual_risk_count(state),
    }


__all__ = ["load_kws_state", "summarize_kws_state"]
```

- [ ] **Step 4: Run store tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_kws_orchestrator_store.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 8**

```bash
git add AgentLens/src/agentlens/store/kws_orchestrator.py AgentLens/tests/unit/test_kws_orchestrator_store.py
git commit -m "feat(agentlens): read KWS orchestrator state summaries"
```

### Task 9: Add `agentlens import kws-orchestrator`

**Files:**
- Create: `AgentLens/src/agentlens/commands/import_kws_orchestrator.py`
- Create: `AgentLens/tests/integration/test_import_kws_orchestrator.py`
- Modify: `AgentLens/src/agentlens/cli.py`
- Modify: `AgentLens/docs/cli.md`

- [ ] **Step 1: Write failing importer integration test**

Create `AgentLens/tests/integration/test_import_kws_orchestrator.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_import_kws_orchestrator_creates_container_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    home = tmp_path / "agentlens_home"
    home.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    run_dir = tmp_path / "cpe-run"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "cpe-1",
                "agentlens_status": "unavailable",
                "lifecycle_outcome": "finished",
                "completion_audit": {
                    "verification_evidence": [{"command": "pytest", "status": "passed"}],
                    "residual_risk": [],
                },
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["import", "kws-orchestrator", "--kind", "cpe", "--run-dir", str(run_dir)],
    )
    assert result.exit_code == 0, result.stderr
    run_id = result.stdout.strip()
    assert run_id.startswith("run_")
    matches = list((home / "runs").glob(f"*/{run_id}/events.jsonl"))
    assert len(matches) == 1
    run_path = matches[0].parent
    events = [json.loads(line) for line in matches[0].read_text(encoding="utf-8").splitlines()]
    assert any(ev["type"] == "kws.orchestrator.run_finished" for ev in events)
    assert (run_path / "artifacts" / "import_report.json").is_file()
    assert (run_path / "final.json").is_file()
    assert (run_path / "eval.json").is_file()
    assert (run_path / "manifest.json").is_file()
```

- [ ] **Step 2: Run importer test and verify it fails**

Run:

```bash
cd AgentLens
python -m pytest tests/integration/test_import_kws_orchestrator.py -v
```

Expected: Typer reports no such command `kws-orchestrator`.

- [ ] **Step 3: Implement importer command**

Create `AgentLens/src/agentlens/commands/import_kws_orchestrator.py`:

```python
"""``agentlens import kws-orchestrator`` — backfill CPE/CME state into AgentLens."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import typer

from agentlens.commands.import_claude_session import import_app
from agentlens.constants import DEFAULT_MODE, SCHEMA_EVENT_V1, SCHEMA_FINAL_V1, SCHEMA_RUN_V1
from agentlens.evaluator.engine import evaluate
from agentlens.ids import compute_workspace_id, make_event_id, make_run_id
from agentlens.importers.artifacts import write_artifact_json
from agentlens.store import manifest, sqlite_index
from agentlens.store.kws_orchestrator import load_kws_state, summarize_kws_state
from agentlens.store.paths import agentlens_home
from agentlens.store.paths import run_dir as build_run_dir
from agentlens.store.writer import append_event, write_final, write_run_meta
from agentlens.time import utc_now_iso


def _root_hash(path: Path) -> str:
    return "sha256:" + sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def _payload(summary: dict, event_name: str) -> dict:
    return {
        "schema": "kws.orchestrator.event.v1",
        "producer": summary["producer"],
        "producer_run_id": summary["producer_run_id"],
        "phase": "final" if event_name == "run_finished" else "setup",
        "event_name": event_name,
        "task_id": None,
        "outcome": summary["outcome"],
        "severity": "warn" if summary.get("agentlens_status") == "unavailable" else "info",
        "agentlens_status": summary.get("agentlens_status"),
        "evidence": {
            "kind": "state_check",
            "command_hash": None,
            "status": "passed" if summary["verification_count"] else "skipped",
            "artifact_ref": "artifacts/import_report.json",
        },
        "context": {
            "health": None,
            "handoff_ready": None,
            "residual_risk_count": summary["residual_risk_count"],
            "medium_plus_residual_risk_count": 0,
            "changed_files_count": None,
            "context_snapshot_ref": None,
        },
    }


@import_app.command("kws-orchestrator")
def import_kws_orchestrator(
    kind: str = typer.Option(..., "--kind", help="KWS state kind: cpe or cme"),
    run_dir: Path = typer.Option(..., "--run-dir", help="Path containing state.json"),
) -> None:
    if kind not in {"cpe", "cme"}:
        raise typer.BadParameter("--kind must be cpe or cme")
    run_dir = run_dir.expanduser().resolve()
    state = load_kws_state(run_dir)
    summary = summarize_kws_state(kind, state)
    workspace_id, basis, ws_meta = compute_workspace_id(run_dir)
    run_id = make_run_id()
    target_dir = build_run_dir(workspace_id, run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    run_doc = {
        "schema": SCHEMA_RUN_V1,
        "run_id": run_id,
        "workspace_id": workspace_id,
        "started_at": utc_now_iso(),
        "run_kind": "container",
        "agent": {
            "name": "generic",
            "mode": "unknown",
            "label": f"{summary['producer']}-orchestrator-backfill",
        },
        "workspace": {
            "root_label": "kws-orchestrator-run",
            "root_hash": _root_hash(run_dir),
            "id_basis": basis,
        },
        "recording": {
            "mode": DEFAULT_MODE,
            "adapter": "agentlens_kws_orchestrator_import",
            "has_transcript": False,
            "transcript_source": "none",
        },
        "meta": {"import_state": "full", "kws_kind": kind},
    }
    if "git_remote_hash" in ws_meta:
        run_doc["workspace"]["git_remote_hash"] = ws_meta["git_remote_hash"]
    if "git_branch" in ws_meta:
        run_doc["workspace"]["git_branch"] = ws_meta["git_branch"]
    write_run_meta(target_dir, run_doc)

    for event_name in ("run_started", "run_finished"):
        append_event(
            target_dir,
            {
                "schema": SCHEMA_EVENT_V1,
                "event_id": make_event_id(),
                "run_id": run_id,
                "ts": utc_now_iso(),
                "type": f"kws.orchestrator.{event_name}",
                "payload": _payload(summary, event_name),
            },
        )

    write_artifact_json(
        target_dir / "artifacts" / "import_report.json",
        {
            "source": "kws-orchestrator",
            "kind": kind,
            "source_path_hash": _root_hash(run_dir),
            "summary": summary,
        },
    )
    write_final(
        target_dir,
        {
            "schema": SCHEMA_FINAL_V1,
            "run_id": run_id,
            "ended_at": utc_now_iso(),
            "agent_outcome": summary["outcome"],
            "summary": "Backfilled KWS orchestrator state.",
            "changed_files": [],
            "verification": [],
            "residual_risks": [],
        },
    )
    manifest.seal(target_dir, "pre_eval")
    evaluate(target_dir)
    manifest.seal(target_dir, "final")
    conn = sqlite_index.init_db(agentlens_home())
    try:
        sqlite_index.index_run(conn, target_dir)
    finally:
        conn.close()
    typer.echo(run_id)


__all__ = ["import_kws_orchestrator"]
```

- [ ] **Step 4: Register the importer**

Modify `AgentLens/src/agentlens/cli.py`:

```python
from .commands import import_kws_orchestrator as import_kws_orchestrator_cmd  # noqa: F401
```

The import side effect registers the command on `import_app`.

- [ ] **Step 5: Run importer tests**

Run:

```bash
cd AgentLens
python -m pytest tests/integration/test_import_kws_orchestrator.py tests/unit/test_kws_orchestrator_store.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Document the importer**

Add to `AgentLens/docs/cli.md`:

```markdown
### `agentlens import kws-orchestrator`

Backfills bounded CPE/CME orchestrator state into an AgentLens container run.

```bash
agentlens import kws-orchestrator --kind cpe --run-dir ~/.codex/orchestrator/run_20260520_120000
agentlens import kws-orchestrator --kind cme --run-dir ~/.claude/orchestrator/run_20260520_120000
```

The importer reads `state.json`, emits common `kws.orchestrator.*` events, and writes `artifacts/import_report.json`. It does not copy raw headless logs, prompts, or transcripts.
```

- [ ] **Step 7: Commit Task 9**

```bash
git add AgentLens/src/agentlens/commands/import_kws_orchestrator.py AgentLens/src/agentlens/cli.py AgentLens/docs/cli.md AgentLens/tests/integration/test_import_kws_orchestrator.py
git commit -m "feat(agentlens): import KWS orchestrator state"
```

---

## Phase 5 — Documentation, Verification, and Graph Refresh

### Task 10: Update AgentLens Contract Docs

**Files:**
- Modify: `AgentLens/docs/contract.md`
- Modify: `AgentLens/docs/security.md`
- Modify: `AgentLens/docs/spec/2026-05-20-agentlens-kws-common-observability-contract-design.md`

- [ ] **Step 1: Add contract documentation**

In `AgentLens/docs/contract.md`, add a section named `KWS Common Observability Events` with:

```markdown
KWS orchestrators emit semantic evidence under `kws.orchestrator.EVENT_NAME`.
The payload schema is `kws.orchestrator.event.v1`; AgentLens stores it as an opaque event payload and validates the common envelope in evaluator coverage code. CPE uses `producer="kws-cpe"` and CME uses `producer="kws-cme"`.

The event payload is bounded: no raw prompt, no raw transcript, no long command output, no secrets, and no absolute home paths.
```

- [ ] **Step 2: Add security documentation**

In `AgentLens/docs/security.md`, add:

```markdown
KWS common observability events are summary-only. The KWS emit helpers and AgentLens coverage parser reject oversized payloads and obvious raw context markers. AgentLens does not crawl `~/.codex/orchestrator` or `~/.claude/orchestrator` automatically; backfill requires an explicit `agentlens import kws-orchestrator` command.
```

- [ ] **Step 3: Run doc sanity checks**

Run:

```bash
rg -n "kws-cpe\\.learning|kws-cpe\\.task_|kws-cme\\.context_health|--outcome blocked|--outcome aborted" AgentLens/docs skills/kws-codex-plan-executor skills/kws-claude-multi-agent-executor
```

Expected: matches are only in historical-compatibility paragraphs. Any runtime instruction match must be edited to the common namespace or AgentLens outcome mapping.

- [ ] **Step 4: Commit Task 10**

```bash
git add AgentLens/docs/contract.md AgentLens/docs/security.md AgentLens/docs/spec/2026-05-20-agentlens-kws-common-observability-contract-design.md
git commit -m "docs: document KWS common AgentLens contract"
```

### Task 11: Run Full Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run AgentLens focused tests**

Run:

```bash
cd AgentLens
python -m pytest \
  tests/unit/test_kws_events.py \
  tests/unit/test_evidence_coverage.py \
  tests/unit/test_evaluator_fixtures.py \
  tests/unit/test_schema_validation.py \
  tests/integration/test_event_append.py \
  tests/integration/test_import_kws_orchestrator.py \
  -v
```

Expected: all tests pass.

- [ ] **Step 2: Run KWS skill contract evals**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md
python3 skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py --skill skills/kws-claude-multi-agent-executor/SKILL.md
python3 skills/kws-claude-multi-agent-executor/scripts/compare_agentlens_events.py --self-test
```

Expected: all commands exit 0 and report passing checks.

- [ ] **Step 3: Run broader AgentLens tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit tests/integration -v
```

Expected: all tests pass. If unrelated web e2e tests require unavailable browser assets, record the exact failing command and run the focused tests from Step 1 as the required gate for this change.

- [ ] **Step 4: Refresh graphify after code edits**

Run:

```bash
graphify update .
```

Expected: command exits 0 and refreshes `graphify-out/`.

- [ ] **Step 5: Commit graph refresh if it changed generated graph files**

Run:

```bash
git status --short graphify-out
```

If files changed, commit them:

```bash
git add graphify-out
git commit -m "chore: refresh graph after KWS AgentLens contract"
```

- [ ] **Step 6: Final status**

Run:

```bash
git status --short
```

Expected: clean working tree.
