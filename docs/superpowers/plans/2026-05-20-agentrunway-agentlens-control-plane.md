# AgentRunway AgentLens Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AgentRunway the only supported AgentLens executor integration, with `agentrunway.*` observability, operator status, detach/resume/apply/clean hardening, and no CPE/CME integration surface in AgentLens or AgentRunway.

**Architecture:** AgentRunway remains the authoritative execution state machine under `~/.agentrunway`, while AgentLens receives and evaluates runner-validated `agentrunway.*` events. The implementation removes active KWS/CPE/CME observability plans from AgentLens/AgentRunway, adds an AgentLens AgentRunway projection layer, then wires AgentRunway to emit, inspect, recover, and clean runs safely.

**Tech Stack:** Python 3.11+, argparse, Typer, JSON Schema, SQLite, pytest, shell-based fake CLIs, git worktrees.

---

## Scope Check

This plan spans two code surfaces, AgentRunway and AgentLens, but it is one control-plane feature. Each task produces independently testable software:

- Task 1 removes active CPE/CME AgentLens/AgentRunway surfaces.
- Tasks 2-3 teach AgentLens to understand AgentRunway evidence.
- Tasks 4-7 wire AgentRunway emission and operator UX.
- Tasks 8-10 harden recovery, cleanup, and apply.
- Task 11 updates documentation and runs final verification.

CPE/CME skill directories are deliberately out of scope. Do not delete or edit `skills/kws-codex-plan-executor/` or `skills/kws-claude-multi-agent-executor/` unless a later user request targets those skills directly.

## File Structure

### Create

| Path | Responsibility |
|---|---|
| `AgentLens/src/agentlens/evaluator/agentrunway_events.py` | Parse and project `agentrunway.*` events into timeline, gate, retry, blocked, coverage, and observability facts. |
| `AgentLens/tests/unit/test_agentrunway_events.py` | Pure parser/projection tests for AgentRunway event streams. |
| `skills/agent-runway/scripts/agentrunway/agentlens.py` | Best-effort AgentLens CLI emitter for `agentrunway.*` events. |
| `skills/agent-runway/scripts/agentrunway/detach.py` | Foreground command reconstruction and detached process launch. |
| `skills/agent-runway/scripts/agentrunway/retention.py` | Safe cleanup planning and apply logic for old runs/worktrees. |
| `skills/agent-runway/evals/fixtures/fake-bin/agentlens` | Deterministic fake AgentLens CLI for AgentRunway emitter tests. |
| `skills/agent-runway/evals/test_agentlens_cli_emitter.py` | AgentRunway emitter tests with a fake `agentlens` CLI. |
| `skills/agent-runway/evals/test_detach_cli.py` | Deterministic detach command tests. |
| `skills/agent-runway/evals/test_retention_clean.py` | Cleanup classification and dry-run/apply tests. |

### Modify

| Path | Change |
|---|---|
| `AgentLens/src/agentlens/evaluator/engine.py` | Add optional AgentRunway `evidence_coverage` to `eval.json`. |
| `AgentLens/src/agentlens/schema/jsonschema/eval.schema.json` | Allow optional `evidence_coverage` object. |
| `AgentLens/src/agentlens/schema/jsonschema/event.schema.json` | Replace CPE/CME examples in comments with `agentrunway.*`. |
| `AgentLens/src/agentlens/commands/event.py` | Replace CPE/CME help examples with `agentrunway.*`. |
| `AgentLens/src/agentlens/commands/run_open.py` | Replace CPE/CME help examples with AgentRunway wording. |
| `AgentLens/tests/integration/test_event_append.py` | Replace `kws-cme.*` examples with `agentrunway.*`. |
| `AgentLens/tests/integration/test_failure_isolation.py` | Replace namespace isolation cases with `agentrunway.*` and non-KWS namespaces. |
| `AgentLens/tests/integration/test_phase1_smoke.py` | Replace CPE/CME event examples with AgentRunway examples. |
| `AgentLens/tests/unit/test_schema_validation.py` | Replace CPE/CME valid fixtures with AgentRunway valid fixtures. |
| `AgentLens/tests/fixtures/schemas/valid/event_kws_cme_task_started.json` | Rename to `event_agentrunway_run_started.json`. |
| `AgentLens/tests/fixtures/schemas/valid/event_kws_cpe_verification_failed.json` | Rename to `event_agentrunway_verification_result.json`. |
| `AgentLens/tests/fixtures/schemas/valid/run_container.json` | Use `agent.label="agentrunway"` instead of a CPE/CME label. |
| `AgentLens/docs/cli.md` | Remove CPE/CME examples; use AgentRunway examples. |
| `AgentLens/docs/contract.md` | Remove CPE/CME forward-path wording; document AgentRunway namespace examples. |
| `AgentLens/docs/security.md` | Remove CPE/CME orchestration examples where they imply AgentLens support. |
| `skills/agent-runway/scripts/agentrunway/db.py` | Add AgentLens run/status helpers and cleanup query helpers. |
| `skills/agent-runway/scripts/agentrunway/events.py` | Keep redaction and event journal, accept concrete AgentLens CLI emitter. |
| `skills/agent-runway/scripts/agentrunway/invocation.py` | Add `--run-id`, `--type`, `--dry-run`, detach handling, and human output routing. |
| `skills/agent-runway/scripts/agentrunway/runner.py` | Allocate deterministic run ids, wire AgentLens emitter, close AgentLens runs, call clean/retention. |
| `skills/agent-runway/scripts/agentrunway/status.py` | Add next-action and AgentLens health summaries. |
| `skills/agent-runway/scripts/agentrunway/reconciliation.py` | Add `abort_cherry_pick`, `retain_orphan`, and `block` reconciliation actions. |
| `skills/agent-runway/scripts/agentrunway/apply.py` | Return structured conflict/already-applied details. |
| `skills/agent-runway/evals/test_event_journal_agentlens.py` | Extend local journal tests for emitter success. |
| `skills/agent-runway/evals/test_reconciliation.py` | Add reserved-action recovery tests. |
| `skills/agent-runway/evals/test_lifecycle_cli.py` | Cover new CLI flags and human output routing. |
| `skills/agent-runway/evals/test_cli_smoke.py` | Cover `clean --dry-run` and `events --type`. |
| `skills/agent-runway/README.md` | Document AgentRunway-only AgentLens integration and operator flow. |
| `skills/agent-runway/references/agentlens-events.md` | Document `agentrunway.*` event contract. |

### Delete

| Path | Reason |
|---|---|
| `docs/superpowers/plans/2026-05-20-agentlens-kws-common-observability-contract.md` | Replaced by AgentRunway-only control-plane plan; no CPE/CME common contract. |
| `AgentLens/docs/spec/2026-05-20-agentlens-kws-common-observability-contract-design.md` | Replaced by AgentRunway-only control-plane design; no KWS common contract. |

---

## Task 1: Remove Active CPE/CME AgentLens Surfaces

**Files:**
- Delete: `docs/superpowers/plans/2026-05-20-agentlens-kws-common-observability-contract.md`
- Delete: `AgentLens/docs/spec/2026-05-20-agentlens-kws-common-observability-contract-design.md`
- Modify: `AgentLens/src/agentlens/schema/jsonschema/event.schema.json`
- Modify: `AgentLens/src/agentlens/commands/event.py`
- Modify: `AgentLens/src/agentlens/commands/run_open.py`
- Modify: `AgentLens/tests/integration/test_event_append.py`
- Modify: `AgentLens/tests/integration/test_failure_isolation.py`
- Modify: `AgentLens/tests/integration/test_phase1_smoke.py`
- Modify: `AgentLens/tests/unit/test_event_query.py`
- Modify: `AgentLens/tests/unit/test_schema_validation.py`
- Rename: `AgentLens/tests/fixtures/schemas/valid/event_kws_cme_task_started.json` to `AgentLens/tests/fixtures/schemas/valid/event_agentrunway_run_started.json`
- Rename: `AgentLens/tests/fixtures/schemas/valid/event_kws_cpe_verification_failed.json` to `AgentLens/tests/fixtures/schemas/valid/event_agentrunway_verification_result.json`
- Modify: `AgentLens/tests/fixtures/schemas/valid/run_container.json`
- Modify: `AgentLens/docs/cli.md`
- Modify: `AgentLens/docs/contract.md`
- Modify: `AgentLens/docs/security.md`

- [ ] **Step 1: Write a failing guard test for AgentLens fixture names**

Add this test to `AgentLens/tests/unit/test_schema_validation.py` near the existing valid fixture tests:

```python
def test_agentlens_valid_fixtures_do_not_use_cpe_cme_namespaces() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "schemas" / "valid"
    offenders = []
    for path in fixture_root.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        if "kws-cme" in text or "kws-cpe" in text or "kws.orchestrator" in text:
            offenders.append(path.name)
    assert offenders == []
```

- [ ] **Step 2: Run the guard and verify it fails**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_schema_validation.py::test_agentlens_valid_fixtures_do_not_use_cpe_cme_namespaces -v
```

Expected: FAIL with fixture names that still contain `kws-cme` or `kws-cpe`.

- [ ] **Step 3: Delete the obsolete KWS common plan and spec**

Run:

```bash
git rm docs/superpowers/plans/2026-05-20-agentlens-kws-common-observability-contract.md
git rm AgentLens/docs/spec/2026-05-20-agentlens-kws-common-observability-contract-design.md
```

Expected: both paths are staged as deleted.

- [ ] **Step 4: Rename CPE/CME schema fixtures and replace payloads**

Run:

```bash
git mv AgentLens/tests/fixtures/schemas/valid/event_kws_cme_task_started.json AgentLens/tests/fixtures/schemas/valid/event_agentrunway_run_started.json
git mv AgentLens/tests/fixtures/schemas/valid/event_kws_cpe_verification_failed.json AgentLens/tests/fixtures/schemas/valid/event_agentrunway_verification_result.json
```

Replace `AgentLens/tests/fixtures/schemas/valid/event_agentrunway_run_started.json` with:

```json
{
  "schema": "agentlens.event.v1",
  "event_id": "evt_aaaaaaaaaaaa",
  "run_id": "run_20260101_000000_aaaaaa",
  "ts": "2026-01-01T00:00:00Z",
  "type": "agentrunway.run_started",
  "payload": {
    "schema": "agentrunway.event.v1",
    "agentrunway_run_id": "agentrunway-demo",
    "phase": "run",
    "outcome": "success",
    "summary": "run started"
  }
}
```

Replace `AgentLens/tests/fixtures/schemas/valid/event_agentrunway_verification_result.json` with:

```json
{
  "schema": "agentlens.event.v1",
  "event_id": "evt_bbbbbbbbbbbb",
  "run_id": "run_20260101_000000_aaaaaa",
  "ts": "2026-01-01T00:00:01Z",
  "type": "agentrunway.verification_result",
  "payload": {
    "schema": "agentrunway.event.v1",
    "agentrunway_run_id": "agentrunway-demo",
    "phase": "verification",
    "outcome": "success",
    "summary": "verification passed",
    "task_id": "task_001",
    "status": "passed"
  }
}
```

- [ ] **Step 5: Replace test literals from CPE/CME to AgentRunway**

In AgentLens tests, replace event examples with these exact mappings:

```text
kws-cme.task_started -> agentrunway.worker_dispatched
kws-cme.task_finished -> agentrunway.worker_result
kws-cme.note -> agentrunway.note
kws-cpe.phase_started -> example.phase_started
kws-cpe.phase_finished -> example.phase_finished
kws-cme.phase_0_started -> agentrunway.run_started
kws-cme.phase_2_complete -> agentrunway.run_finished
kws-cme-orchestrator -> agentrunway
kws-cpe-orchestrator -> example-orchestrator
```

Keep namespace-isolation tests, but make them assert `agentrunway.*` does not leak into `example.*`, `claude.*`, or `codex.*`.

- [ ] **Step 6: Update comments and help text**

Edit these strings:

```python
# AgentLens/src/agentlens/commands/event.py
help="event type (e.g. agentrunway.run_started)"
```

```python
# AgentLens/src/agentlens/commands/run_open.py
help="container agent label (e.g. agentrunway)"
```

In `AgentLens/src/agentlens/schema/jsonschema/event.schema.json`, change the `$comment` examples to:

```json
"$comment": "Reserved AgentLens core namespaces must use the locked event-name enum. Executor and importer namespaces such as agentrunway.*, claude.*, and codex.* accept any lower-case dotted token."
```

- [ ] **Step 7: Run focused AgentLens tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_schema_validation.py tests/unit/test_event_query.py tests/integration/test_event_append.py tests/integration/test_failure_isolation.py tests/integration/test_phase1_smoke.py -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add AgentLens docs/superpowers/plans
git commit -m "chore: remove CPE CME AgentLens surfaces"
```

---

## Task 2: Add AgentLens AgentRunway Event Projection

**Files:**
- Create: `AgentLens/src/agentlens/evaluator/agentrunway_events.py`
- Create: `AgentLens/tests/unit/test_agentrunway_events.py`

- [ ] **Step 1: Write failing projection tests**

Create `AgentLens/tests/unit/test_agentrunway_events.py`:

```python
from __future__ import annotations

from agentlens.evaluator.agentrunway_events import (
    parse_agentrunway_event,
    project_agentrunway_events,
)


def _event(type_: str, payload: dict) -> dict:
    return {
        "schema": "agentlens.event.v1",
        "event_id": "evt_aaaaaaaaaaaa",
        "run_id": "run_20260101_000000_aaaaaa",
        "ts": "2026-01-01T00:00:00Z",
        "type": type_,
        "payload": payload,
    }


def test_parse_agentrunway_verification_result() -> None:
    obs = parse_agentrunway_event(
        _event(
            "agentrunway.verification_result",
            {
                "schema": "agentrunway.event.v1",
                "agentrunway_run_id": "ar-1",
                "phase": "verification",
                "outcome": "success",
                "summary": "verification passed",
                "task_id": "task_001",
                "status": "passed",
            },
        )
    )
    assert obs is not None
    assert obs.kind == "verification_result"
    assert obs.task_id == "task_001"
    assert obs.status == "passed"
    assert obs.outcome == "success"
    assert obs.payload_safety == "ok"


def test_projection_counts_gate_retry_and_blocked_refs() -> None:
    projection = project_agentrunway_events(
        [
            _event(
                "agentrunway.run_started",
                {
                    "schema": "agentrunway.event.v1",
                    "agentrunway_run_id": "ar-1",
                    "phase": "run",
                    "outcome": "success",
                    "summary": "started",
                },
            ),
            _event(
                "agentrunway.gate_retry",
                {
                    "schema": "agentrunway.event.v1",
                    "agentrunway_run_id": "ar-1",
                    "phase": "gate",
                    "outcome": "partial",
                    "summary": "retry",
                    "task_id": "task_001",
                    "reason": "verification_failed",
                },
            ),
            _event(
                "agentrunway.run_blocked",
                {
                    "schema": "agentrunway.event.v1",
                    "agentrunway_run_id": "ar-1",
                    "phase": "run",
                    "outcome": "partial",
                    "summary": "blocked",
                    "task_id": "task_001",
                    "spec_refs": ["S1"],
                    "reason": "budget_exhausted",
                },
            ),
        ]
    )
    assert projection["present"] is True
    assert projection["run_id"] == "ar-1"
    assert projection["event_count"] == 3
    assert projection["gate_retries"] == 1
    assert projection["blocked_tasks"] == ["task_001"]
    assert projection["blocked_spec_refs"] == ["S1"]
    assert projection["last_outcome"] == "partial"


def test_projection_ignores_non_agentrunway_namespaces() -> None:
    projection = project_agentrunway_events(
        [
            _event("example.note", {"note": "ignored"}),
            _event("claude.tool_use", {"name": "Read"}),
        ]
    )
    assert projection["present"] is False
    assert projection["event_count"] == 0
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_agentrunway_events.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentlens.evaluator.agentrunway_events'`.

- [ ] **Step 3: Add projection implementation**

Create `AgentLens/src/agentlens/evaluator/agentrunway_events.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

AGENTRUNWAY_PREFIX = "agentrunway."
EVENT_SCHEMA = "agentrunway.event.v1"
OUTCOMES = {"success", "failed", "partial", "cancelled", "unknown"}
PAYLOAD_BYTE_LIMIT = 4096
SUMMARY_CHAR_LIMIT = 1200
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
class AgentRunwayObservation:
    kind: str
    run_id: str | None
    task_id: str | None
    phase: str
    outcome: str
    summary: str
    status: str | None
    reason: str | None
    spec_refs: tuple[str, ...]
    payload_safety: PayloadSafety


def _normal_outcome(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    return raw if raw in OUTCOMES else "unknown"


def _payload_safety(payload: dict[str, Any]) -> PayloadSafety:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if any(marker in encoded for marker in RAW_CONTEXT_MARKERS):
        return "raw_context_detected"
    if ABS_HOME_RE.search(encoded):
        return "raw_context_detected"
    if len(encoded.encode("utf-8")) > PAYLOAD_BYTE_LIMIT:
        return "oversized"
    summary = payload.get("summary")
    if isinstance(summary, str) and len(summary) > SUMMARY_CHAR_LIMIT:
        return "oversized"
    return "ok"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def parse_agentrunway_event(event: dict[str, Any]) -> AgentRunwayObservation | None:
    event_type = event.get("type")
    payload = event.get("payload")
    if not isinstance(event_type, str) or not event_type.startswith(AGENTRUNWAY_PREFIX):
        return None
    if not isinstance(payload, dict):
        return None
    kind = event_type.removeprefix(AGENTRUNWAY_PREFIX)
    return AgentRunwayObservation(
        kind=kind,
        run_id=payload.get("agentrunway_run_id") if isinstance(payload.get("agentrunway_run_id"), str) else None,
        task_id=payload.get("task_id") if isinstance(payload.get("task_id"), str) else None,
        phase=str(payload.get("phase") or "unknown"),
        outcome=_normal_outcome(payload.get("outcome")),
        summary=str(payload.get("summary") or ""),
        status=payload.get("status") if isinstance(payload.get("status"), str) else None,
        reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
        spec_refs=_string_tuple(payload.get("spec_refs")),
        payload_safety=_payload_safety(payload),
    )


def project_agentrunway_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [obs for event in events if (obs := parse_agentrunway_event(event)) is not None]
    blocked_tasks = sorted({obs.task_id for obs in observations if obs.task_id and obs.kind == "run_blocked"})
    blocked_refs = sorted({ref for obs in observations for ref in obs.spec_refs if obs.kind == "run_blocked"})
    unsafe_payloads = [obs.payload_safety for obs in observations if obs.payload_safety != "ok"]
    return {
        "present": bool(observations),
        "run_id": next((obs.run_id for obs in observations if obs.run_id), None),
        "event_count": len(observations),
        "timeline": [
            {
                "kind": obs.kind,
                "phase": obs.phase,
                "task_id": obs.task_id,
                "outcome": obs.outcome,
                "status": obs.status,
                "reason": obs.reason,
            }
            for obs in observations
        ],
        "gate_retries": sum(1 for obs in observations if obs.kind == "gate_retry"),
        "review_results": sum(1 for obs in observations if obs.kind == "review_result"),
        "verification_results": sum(1 for obs in observations if obs.kind == "verification_result"),
        "blocked_tasks": blocked_tasks,
        "blocked_spec_refs": blocked_refs,
        "payload_safety": unsafe_payloads[0] if unsafe_payloads else "ok",
        "last_outcome": observations[-1].outcome if observations else "unknown",
    }


__all__ = [
    "AgentRunwayObservation",
    "parse_agentrunway_event",
    "project_agentrunway_events",
]
```

- [ ] **Step 4: Run projection tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_agentrunway_events.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/evaluator/agentrunway_events.py AgentLens/tests/unit/test_agentrunway_events.py
git commit -m "feat: project AgentRunway events in AgentLens"
```

---

## Task 3: Add AgentRunway Evidence Coverage to AgentLens Eval

**Files:**
- Modify: `AgentLens/src/agentlens/evaluator/engine.py`
- Modify: `AgentLens/src/agentlens/schema/jsonschema/eval.schema.json`
- Modify: `AgentLens/tests/unit/test_agentrunway_events.py`

- [ ] **Step 1: Write failing eval coverage test**

Append to `AgentLens/tests/unit/test_agentrunway_events.py`:

```python
import json
from pathlib import Path

from agentlens.constants import SCHEMA_RUN_V1
from agentlens.evaluator.engine import evaluate


def test_evaluate_adds_agentrunway_evidence_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260101_000000_aaaaaa"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema": SCHEMA_RUN_V1,
                "run_id": "run_20260101_000000_aaaaaa",
                "workspace_id": "ws_0000000000000001",
                "started_at": "2026-01-01T00:00:00Z",
                "agent": {"name": "generic", "mode": "unknown", "label": "agentrunway"},
                "workspace": {"root_label": "<workspace>", "root_hash": "sha256:" + "0" * 64, "id_basis": "path"},
                "recording": {"mode": "active", "adapter": "agentlens_container"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "agentlens.event.v1",
                        "event_id": "evt_aaaaaaaaaaaa",
                        "run_id": "run_20260101_000000_aaaaaa",
                        "ts": "2026-01-01T00:00:00Z",
                        "type": "run.started",
                        "payload": {"agent": "generic"},
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "schema": "agentlens.event.v1",
                        "event_id": "evt_bbbbbbbbbbbb",
                        "run_id": "run_20260101_000000_aaaaaa",
                        "ts": "2026-01-01T00:00:01Z",
                        "type": "agentrunway.verification_result",
                        "payload": {
                            "schema": "agentrunway.event.v1",
                            "agentrunway_run_id": "ar-1",
                            "phase": "verification",
                            "outcome": "success",
                            "summary": "passed",
                            "task_id": "task_001",
                            "status": "passed",
                        },
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "final.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.final.v1",
                "run_id": "run_20260101_000000_aaaaaa",
                "finished_at": "2026-01-01T00:00:02Z",
                "agent_outcome": "success",
                "summary": "done",
                "residual_risks": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    doc = evaluate(run_dir)
    assert doc["evidence_coverage"]["agentrunway_observability"] == "present"
    assert doc["evidence_coverage"]["verification_strength"] == "gate_verified"
    assert doc["evidence_coverage"]["payload_safety"] == "ok"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_agentrunway_events.py::test_evaluate_adds_agentrunway_evidence_coverage -v
```

Expected: FAIL because `evidence_coverage` is missing or schema validation rejects it.

- [ ] **Step 3: Add coverage helper to AgentRunway event module**

Append this function to `AgentLens/src/agentlens/evaluator/agentrunway_events.py` and add it to `__all__`:

```python
def build_evidence_coverage(events: list[dict[str, Any]]) -> dict[str, str]:
    projection = project_agentrunway_events(events)
    if not projection["present"]:
        return {
            "agentrunway_observability": "missing",
            "verification_strength": "none",
            "blocked_coverage": "none",
            "payload_safety": "ok",
        }
    verification_results = int(projection["verification_results"])
    blocked_refs = projection["blocked_spec_refs"]
    return {
        "agentrunway_observability": "present",
        "verification_strength": "gate_verified" if verification_results else "not_verified",
        "blocked_coverage": "blocked_refs_present" if blocked_refs else "none",
        "payload_safety": str(projection["payload_safety"]),
    }
```

- [ ] **Step 4: Update eval schema**

In `AgentLens/src/agentlens/schema/jsonschema/eval.schema.json`, add this property under `properties`:

```json
"evidence_coverage": {
  "type": "object",
  "additionalProperties": false,
  "required": [
    "agentrunway_observability",
    "verification_strength",
    "blocked_coverage",
    "payload_safety"
  ],
  "properties": {
    "agentrunway_observability": {
      "type": "string",
      "enum": ["present", "missing"]
    },
    "verification_strength": {
      "type": "string",
      "enum": ["gate_verified", "not_verified", "none"]
    },
    "blocked_coverage": {
      "type": "string",
      "enum": ["blocked_refs_present", "none"]
    },
    "payload_safety": {
      "type": "string",
      "enum": ["ok", "oversized", "raw_context_detected"]
    }
  }
}
```

Do not add it to the top-level `required` list. The field is additive.

- [ ] **Step 5: Wire evaluator output**

In `AgentLens/src/agentlens/evaluator/engine.py`, add this import:

```python
from .agentrunway_events import build_evidence_coverage
```

In `evaluate()`, after the `doc` dict is created and before `atomic_write_json`, add:

```python
    doc["evidence_coverage"] = build_evidence_coverage(ctx.events)
```

In `_minimal_error_eval()`, do not add `evidence_coverage`; load failures should remain minimal.

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_agentrunway_events.py tests/integration/test_eval_determinism.py tests/unit/test_schema_validation.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/evaluator/agentrunway_events.py AgentLens/src/agentlens/evaluator/engine.py AgentLens/src/agentlens/schema/jsonschema/eval.schema.json AgentLens/tests/unit/test_agentrunway_events.py
git commit -m "feat: score AgentRunway evidence coverage"
```

---

## Task 4: Add AgentRunway AgentLens CLI Emitter

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/agentlens.py`
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Modify: `skills/agent-runway/evals/test_event_journal_agentlens.py`
- Create: `skills/agent-runway/evals/test_agentlens_cli_emitter.py`
- Create: `skills/agent-runway/evals/fixtures/fake-bin/agentlens`

- [ ] **Step 1: Write fake AgentLens CLI fixture**

Create `skills/agent-runway/evals/fixtures/fake-bin/agentlens`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _log(payload: dict) -> None:
    log_path = Path(os.environ["AGENTRUNWAY_FAKE_AGENTLENS_LOG"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    if os.environ.get("AGENTRUNWAY_FAKE_AGENTLENS_FAIL") == "1":
        print("fake agentlens failure", file=sys.stderr)
        return 2
    if argv[:1] == ["run-open"]:
        _log({"command": "run-open", "argv": argv})
        print("run_fake_agentlens_000001")
        return 0
    if argv[:2] == ["event", "append"]:
        _log({"command": "event append", "argv": argv})
        return 0
    if argv[:1] == ["run-close"]:
        _log({"command": "run-close", "argv": argv})
        return 0
    print("unsupported fake agentlens command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Run:

```bash
chmod +x skills/agent-runway/evals/fixtures/fake-bin/agentlens
```

- [ ] **Step 2: Write failing emitter tests**

Create `skills/agent-runway/evals/test_agentlens_cli_emitter.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path

from agentrunway.agentlens import AgentLensCliEmitter, open_agentlens_run


def _fake_path(root: Path) -> str:
    fake_bin = Path(__file__).parent / "fixtures" / "fake-bin"
    return f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"


def test_open_agentlens_run_returns_run_id_and_records_command(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "agentlens.jsonl"
    monkeypatch.setenv("PATH", _fake_path(tmp_path))
    monkeypatch.setenv("AGENTRUNWAY_FAKE_AGENTLENS_LOG", str(log_path))
    run_id = open_agentlens_run(repo_root=tmp_path, agentrunway_run_id="ar-1")
    assert run_id == "run_fake_agentlens_000001"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["command"] == "run-open"
    assert "--agent" in records[0]["argv"]
    assert "agentrunway" in records[0]["argv"]


def test_agentlens_cli_emitter_appends_events(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "agentlens.jsonl"
    monkeypatch.setenv("PATH", _fake_path(tmp_path))
    monkeypatch.setenv("AGENTRUNWAY_FAKE_AGENTLENS_LOG", str(log_path))
    emitter = AgentLensCliEmitter(agentlens_run_id="run_fake_agentlens_000001")
    emitter.emit("agentrunway.run_started", {"schema": "agentrunway.event.v1", "summary": "started"})
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["command"] == "event append"
    assert "agentrunway.run_started" in records[0]["argv"]


def test_agentlens_open_failure_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", _fake_path(tmp_path))
    monkeypatch.setenv("AGENTRUNWAY_FAKE_AGENTLENS_LOG", str(tmp_path / "agentlens.jsonl"))
    monkeypatch.setenv("AGENTRUNWAY_FAKE_AGENTLENS_FAIL", "1")
    assert open_agentlens_run(repo_root=tmp_path, agentrunway_run_id="ar-1") is None
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_agentlens_cli_emitter.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `agentrunway.agentlens`.

- [ ] **Step 4: Add AgentLens CLI emitter**

Create `skills/agent-runway/scripts/agentrunway/agentlens.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def agentlens_available() -> bool:
    return shutil.which("agentlens") is not None


def open_agentlens_run(*, repo_root: Path, agentrunway_run_id: str) -> str | None:
    if not agentlens_available():
        return None
    command = [
        "agentlens",
        "run-open",
        "--agent",
        "agentrunway",
        "--workspace",
        str(repo_root),
        "--meta",
        f"agentrunway_run_id={agentrunway_run_id}",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    run_id = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    return run_id or None


class AgentLensCliEmitter:
    def __init__(self, *, agentlens_run_id: str):
        self.agentlens_run_id = agentlens_run_id

    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        command = [
            "agentlens",
            "event",
            "append",
            "--run",
            self.agentlens_run_id,
            "--type",
            event_type,
            "--payload-json",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"agentlens exited {result.returncode}")


def close_agentlens_run(*, agentlens_run_id: str, outcome: str) -> None:
    if not agentlens_available():
        return
    subprocess.run(
        ["agentlens", "run-close", "--run", agentlens_run_id, "--outcome", outcome],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


__all__ = [
    "AgentLensCliEmitter",
    "agentlens_available",
    "close_agentlens_run",
    "open_agentlens_run",
]
```

- [ ] **Step 5: Add DB helpers for AgentLens run state**

In `skills/agent-runway/scripts/agentrunway/db.py`, add:

```python
    def set_run_agentlens(self, run_id: str, *, agentlens_run_id: str | None, status: str) -> None:
        self.conn.execute(
            "UPDATE runs SET agentlens_run_id=?, agentlens_status=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            (agentlens_run_id, status, run_id),
        )
        self.conn.commit()
```

Add this assertion to `skills/agent-runway/evals/test_db.py`:

```python
def test_set_run_agentlens_records_run_id_and_status(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_run(
        run_id="run-1",
        workspace_id="ws",
        repo_root=str(tmp_path),
        plan_path="plan.md",
        spec_path=None,
        plan_hash="hash",
        spec_hash=None,
        base_commit_sha="abc",
        model_profile="default",
    )
    db.set_run_agentlens("run-1", agentlens_run_id="agentlens-1", status="active")
    row = db.get_run("run-1")
    assert row["agentlens_run_id"] == "agentlens-1"
    assert row["agentlens_status"] == "active"
```

- [ ] **Step 6: Run emitter and DB tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_agentlens_cli_emitter.py evals/test_db.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/agentlens.py skills/agent-runway/scripts/agentrunway/db.py skills/agent-runway/evals/test_agentlens_cli_emitter.py skills/agent-runway/evals/test_db.py skills/agent-runway/evals/fixtures/fake-bin/agentlens
git commit -m "feat: add AgentRunway AgentLens CLI emitter"
```

---

## Task 5: Wire AgentLens Emitter into AgentRunway Runs

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/events.py`
- Modify: `skills/agent-runway/evals/test_event_journal_agentlens.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Extend event payload schema tests**

Append to `skills/agent-runway/evals/test_event_journal_agentlens.py`:

```python
class CapturingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))


def test_event_journal_emits_success_to_agentlens(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    emitter = CapturingEmitter()
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=emitter)
    record = journal.record(
        "agentrunway.run_started",
        build_event_payload("run-1", "run", "success", "run started"),
    )
    assert record.status == "agentlens_emitted"
    assert emitter.events[0][0] == "agentrunway.run_started"
    assert emitter.events[0][1]["schema"] == "agentrunway.event.v1"
    assert emitter.events[0][1]["agentrunway_run_id"] == "run-1"
```

- [ ] **Step 2: Update event payload schema**

In `skills/agent-runway/scripts/agentrunway/events.py`, change `build_event_payload()` base payload to:

```python
    payload = {
        "schema": "agentrunway.event.v1",
        "agentrunway_run_id": run_id,
        "phase": phase,
        "outcome": outcome,
        "severity": "info" if outcome == "success" else "warn",
        "summary": summary[:1200],
        "privacy": {"redacted": True, "policy": "home paths and secret-like keys"},
    }
```

Keep the existing `payload.update(extra)` and redaction call.

- [ ] **Step 3: Wire emitter during run creation**

In `skills/agent-runway/scripts/agentrunway/runner.py`, add imports:

```python
from .agentlens import AgentLensCliEmitter, close_agentlens_run, open_agentlens_run
```

After `db.set_run_contract_path(run_id, str(contract_path))`, add:

```python
    agentlens_run_id = None
    agentlens_emitter = None
    if os.environ.get("AGENTRUNWAY_AGENTLENS", "1") != "0":
        agentlens_run_id = open_agentlens_run(repo_root=repo, agentrunway_run_id=run_id)
        if agentlens_run_id:
            db.set_run_agentlens(run_id, agentlens_run_id=agentlens_run_id, status="active")
            agentlens_emitter = AgentLensCliEmitter(agentlens_run_id=agentlens_run_id)
        else:
            db.set_run_agentlens(run_id, agentlens_run_id=None, status="unavailable")
    else:
        db.set_run_agentlens(run_id, agentlens_run_id=None, status="disabled")
```

Change the journal creation to:

```python
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=agentlens_emitter)
```

Before returning a finished run, after `journal.record("agentrunway.run_finished", ...)`, add:

```python
    if agentlens_run_id:
        close_agentlens_run(agentlens_run_id=agentlens_run_id, outcome="success")
```

- [ ] **Step 4: Add production e2e assertion with fake AgentLens**

In `skills/agent-runway/evals/test_runner_production_e2e.py`, add a small local-adapter smoke test:

```python
def test_run_emits_to_fake_agentlens(git_repo: Path, isolated_home: Path, monkeypatch) -> None:
    plan, spec = _write_plan(git_repo, path="src/agentlens_emit.py")
    log_path = git_repo / "agentlens.jsonl"
    fake_bin = Path(__file__).parent / "fixtures" / "fake-bin"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["AGENTRUNWAY_FAKE_AGENTLENS_LOG"] = str(log_path)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "agentrunway.py"),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--adapter",
            "local",
            "--fake-success",
        ],
        cwd=git_repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert any(record["command"] == "run-open" for record in records)
    assert any("agentrunway.run_started" in record["argv"] for record in records if record["command"] == "event append")
```

Use existing imports in the file; add `import os`, `import subprocess`, and `import sys` if absent.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd skills/agent-runway
PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_event_journal_agentlens.py evals/test_agentlens_cli_emitter.py evals/test_runner_production_e2e.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/events.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_event_journal_agentlens.py skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: emit AgentRunway runs to AgentLens"
```

---

## Task 6: Improve AgentRunway Status, Inspect, and Events UX

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/status.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Modify: `skills/agent-runway/evals/test_artifact_graph_status.py`
- Modify: `skills/agent-runway/evals/test_lifecycle_cli.py`

- [ ] **Step 1: Add next-action tests**

Append to `skills/agent-runway/evals/test_artifact_graph_status.py`:

```python
from agentrunway.status import next_operator_action


def test_next_operator_action_for_blocked_and_finished() -> None:
    assert next_operator_action({"status": "finished"}, {"failed": 0}) == "apply or inspect artifacts"
    assert next_operator_action({"status": "blocked"}, {"failed": 0}) == "inspect blocked tasks and run resume --dry-run"
    assert next_operator_action({"status": "running"}, {"failed": 2}) == "inspect AgentLens failures and continue monitoring"
```

- [ ] **Step 2: Implement next action and richer formatting**

In `skills/agent-runway/scripts/agentrunway/status.py`, add:

```python
def next_operator_action(run_json: dict[str, Any], agentlens: dict[str, Any]) -> str:
    if int(agentlens.get("failed", 0) or 0) > 0:
        return "inspect AgentLens failures and continue monitoring"
    status = str(run_json.get("status") or "unknown")
    if status == "finished":
        return "apply or inspect artifacts"
    if status == "blocked":
        return "inspect blocked tasks and run resume --dry-run"
    if status in {"created", "running"}:
        return "continue monitoring"
    if status == "cancelled":
        return "inspect events before restarting"
    return "inspect run state"
```

In `build_inspect_payload()`, add `"next_action": next_operator_action(run_json, db.agentlens_summary())` and avoid calling `db.agentlens_summary()` twice by storing it in a local variable.

Update `format_inspect_payload()` to include `next_action=<value>`.

- [ ] **Step 3: Add events type filter tests**

Append to `skills/agent-runway/evals/test_lifecycle_cli.py`:

```python
def test_events_command_accepts_type_filter() -> None:
    parser = build_parser()
    args = parser.parse_args(["events", "--run", "run-1", "--type", "agentrunway.gate_retry"])
    assert args.command == "events"
    assert args.type == "agentrunway.gate_retry"
```

- [ ] **Step 4: Add `--type` and human output routing**

In `skills/agent-runway/scripts/agentrunway/invocation.py`, add `cmd.add_argument("--type")` for the `events` command only:

```python
        if command == "events":
            cmd.add_argument("--type")
```

Change the events dispatch to:

```python
        elif args.command == "events":
            payload = runner.events(resolve_run_alias(repo_root, args.run, bool(args.last)), type_filter=args.type)
```

At the print point, keep JSON for now. Human formatting for events can remain JSON because event streams are machine-oriented; `status` and `inspect` carry operator summaries.

- [ ] **Step 5: Filter events in runner**

In `skills/agent-runway/scripts/agentrunway/runner.py`, change:

```python
def events(run_id: str) -> dict[str, Any]:
```

to:

```python
def events(run_id: str, *, type_filter: str | None = None) -> dict[str, Any]:
```

and replace the return with:

```python
    events = db.list_events()
    if type_filter:
        events = [event for event in events if event["event_type"] == type_filter]
    return {"run_id": run_id, "events": events, "agentlens": db.agentlens_summary()}
```

- [ ] **Step 6: Run UX tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_artifact_graph_status.py evals/test_lifecycle_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/status.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_artifact_graph_status.py skills/agent-runway/evals/test_lifecycle_cli.py
git commit -m "feat: improve AgentRunway operator status"
```

---

## Task 7: Implement Deterministic Detach Launch

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/detach.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Create: `skills/agent-runway/evals/test_detach_cli.py`

- [ ] **Step 1: Write failing detach command tests**

Create `skills/agent-runway/evals/test_detach_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.detach import build_detached_argv


def test_build_detached_argv_removes_detach_and_adds_run_id(tmp_path: Path) -> None:
    argv = build_detached_argv(
        executable="python3",
        script=tmp_path / "agentrunway.py",
        original_args=[
            "run",
            "--plan",
            "plan.md",
            "--spec",
            "spec.md",
            "--adapter",
            "codex",
            "--detach",
        ],
        run_id="run-fixed",
    )
    assert argv[:3] == ["python3", str(tmp_path / "agentrunway.py"), "run"]
    assert "--detach" not in argv
    assert argv[-2:] == ["--run-id", "run-fixed"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_detach_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `agentrunway.detach`.

- [ ] **Step 3: Add detach helper**

Create `skills/agent-runway/scripts/agentrunway/detach.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def build_detached_argv(*, executable: str, script: Path, original_args: list[str], run_id: str) -> list[str]:
    cleaned = [arg for arg in original_args if arg != "--detach"]
    return [executable, str(script), *cleaned, "--run-id", run_id]


def launch_detached(*, argv: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    finally:
        stdout.close()
        stderr.close()
    return int(proc.pid)


def current_executable() -> str:
    return sys.executable


__all__ = ["build_detached_argv", "current_executable", "launch_detached"]
```

- [ ] **Step 4: Allocate fixed run ids for detach**

In `skills/agent-runway/scripts/agentrunway/runner.py`, add:

```python
def allocate_run_id(repo: Path, plan: Path) -> str:
    base_run_id = f"{_slug(plan.stem)}-{_now_stamp()}-{_nonce()}"
    return next_available_run_id(repo, base_run_id)
```

In `run(args)`, replace the current `base_run_id` and `run_id` lines with:

```python
    run_id = args.run_id if getattr(args, "run_id", None) else allocate_run_id(repo, plan)
```

- [ ] **Step 5: Add hidden `--run-id` and detach dispatch**

In `skills/agent-runway/scripts/agentrunway/invocation.py`, add:

```python
    run.add_argument("--run-id")
```

At the start of the `if args.command == "run":` branch, after resolving plan/spec and before `runner.run(args)`, add:

```python
            if args.detach and not args.run_id:
                from .detach import build_detached_argv, current_executable, launch_detached
                run_id = runner.allocate_run_id(repo_root, args.plan)
                args.run_id = run_id
                log_dir = repo_root / ".agentrunway-detached"
                argv = build_detached_argv(
                    executable=current_executable(),
                    script=Path(__file__).resolve().parents[1] / "agentrunway.py",
                    original_args=sys.argv[1:] if argv is None else argv,
                    run_id=run_id,
                )
                pid = launch_detached(
                    argv=argv,
                    cwd=repo_root,
                    stdout_path=log_dir / f"{run_id}.stdout.log",
                    stderr_path=log_dir / f"{run_id}.stderr.log",
                )
                write_last_run(repo_root, run_id)
                payload = {
                    "run_id": run_id,
                    "status": "detached",
                    "pid": pid,
                    "stdout": str(log_dir / f"{run_id}.stdout.log"),
                    "stderr": str(log_dir / f"{run_id}.stderr.log"),
                }
            else:
                payload = runner.run(args)
                if isinstance(payload, dict) and payload.get("run_id"):
                    write_last_run(repo_root, str(payload["run_id"]))
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
```

This block intentionally returns early so the normal final print does not duplicate detached output.

- [ ] **Step 6: Run detach tests and CLI smoke**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_detach_cli.py evals/test_cli_smoke.py evals/test_lifecycle_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/detach.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_detach_cli.py
git commit -m "feat: detach AgentRunway runs"
```

---

## Task 8: Expand Resume Reconciliation Actions

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/reconciliation.py`
- Modify: `skills/agent-runway/evals/test_reconciliation.py`

- [ ] **Step 1: Write failing recovery action tests**

Append to `skills/agent-runway/evals/test_reconciliation.py`:

```python
def test_plan_reconciliation_detects_interrupted_cherry_pick(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    main = tmp_path / "main"
    git_dir = main / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "CHERRY_PICK_HEAD").write_text("abc\n", encoding="utf-8")
    (run_dir / "run.json").parent.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"main_worktree": str(main)}), encoding="utf-8")
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)
    assert plan["actions"][0]["action"] == "abort_cherry_pick"
    assert plan["actions"][0]["target"] == str(main)


def test_plan_reconciliation_blocks_stalled_worker_after_retry_event(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt",
        reasoning_effort="medium",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="branch",
        state="stalled",
        handle_json={},
    )
    db.insert_event(
        event_type="agentrunway.resume_action",
        payload={"target": "task_001-implementer-001", "action": "retry"},
        status="agentlens_disabled",
    )
    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)
    assert plan["actions"][0]["action"] == "block"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_reconciliation.py::test_plan_reconciliation_detects_interrupted_cherry_pick evals/test_reconciliation.py::test_plan_reconciliation_blocks_stalled_worker_after_retry_event -v
```

Expected: FAIL because actions are not emitted.

- [ ] **Step 3: Add cherry-pick detection**

In `skills/agent-runway/scripts/agentrunway/reconciliation.py`, add:

```python
def _run_json(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _cherry_pick_head(main_worktree: Path) -> Path:
    direct = main_worktree / ".git" / "CHERRY_PICK_HEAD"
    if direct.exists():
        return direct
    git_file = main_worktree / ".git"
    if git_file.is_file():
        text = git_file.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            git_dir = Path(text.removeprefix("gitdir:").strip())
            return git_dir / "CHERRY_PICK_HEAD"
    return direct
```

At the beginning of `plan_reconciliation()`, add:

```python
    run_json = _run_json(run_dir)
    main_worktree = Path(str(run_json.get("main_worktree", "")))
    if main_worktree and _cherry_pick_head(main_worktree).exists():
        actions.append(
            {
                "target": str(main_worktree),
                "action": "abort_cherry_pick",
                "reason": "interrupted_cherry_pick",
                "writes": True,
            }
        )
```

- [ ] **Step 4: Add block-after-retry-budget detection**

In `plan_reconciliation()`, inside the worker loop after the terminal-state skip, add:

```python
        if state == "stalled" and _resume_action_exists(db, str(worker["worker_id"]), "retry"):
            actions.append(
                {
                    "target": worker["worker_id"],
                    "action": "block",
                    "reason": "retry_budget_exhausted",
                    "writes": True,
                }
            )
            continue
```

- [ ] **Step 5: Apply new actions idempotently**

In `apply_reconciliation_plan()`, add branches:

```python
        elif action["action"] == "abort_cherry_pick":
            target_path = Path(target)
            if _cherry_pick_head(target_path).exists():
                import subprocess

                subprocess.run(["git", "cherry-pick", "--abort"], cwd=target_path, check=False)
                _record_resume_action(
                    db,
                    str(plan["run_id"]),
                    target,
                    "abort_cherry_pick",
                    "partial",
                    "aborted interrupted cherry-pick",
                )
        elif action["action"] == "block":
            worker = db.get_worker(target)
            db.set_worker_state(target, "blocked")
            db.set_task_status(str(worker["task_id"]), "blocked")
            _record_resume_action(
                db,
                str(plan["run_id"]),
                target,
                "block",
                "partial",
                "blocked exhausted retry",
            )
```

- [ ] **Step 6: Run reconciliation tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_reconciliation.py evals/test_resume_apply.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/reconciliation.py skills/agent-runway/evals/test_reconciliation.py
git commit -m "feat: expand AgentRunway resume reconciliation"
```

---

## Task 9: Implement Safe Retention Cleanup

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/retention.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Create: `skills/agent-runway/evals/test_retention_clean.py`
- Modify: `skills/agent-runway/evals/test_cli_smoke.py`

- [ ] **Step 1: Write failing retention tests**

Create `skills/agent-runway/evals/test_retention_clean.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentrunway.retention import parse_age, plan_cleanup


def _run(root: Path, name: str, status: str, days_old: int) -> Path:
    run_dir = root / "runs" / "ws" / name
    run_dir.mkdir(parents=True)
    created = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": name, "status": status, "created_at": created}),
        encoding="utf-8",
    )
    return run_dir


def test_parse_age_accepts_days_and_hours() -> None:
    assert parse_age("14d").total_seconds() == 14 * 24 * 60 * 60
    assert parse_age("6h").total_seconds() == 6 * 60 * 60


def test_plan_cleanup_classifies_old_successful_run(tmp_path: Path) -> None:
    _run(tmp_path, "old-success", "finished", 30)
    _run(tmp_path, "new-success", "finished", 1)
    plan = plan_cleanup(home=tmp_path, older_than="14d", successful=True)
    assert [item["run_id"] for item in plan["candidates"]] == ["old-success"]
    assert plan["writes"] is False
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_retention_clean.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `agentrunway.retention`.

- [ ] **Step 3: Implement retention planner**

Create `skills/agent-runway/scripts/agentrunway/retention.py`:

```python
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def parse_age(value: str) -> timedelta:
    number = int(value[:-1])
    unit = value[-1]
    if unit == "d":
        return timedelta(days=number)
    if unit == "h":
        return timedelta(hours=number)
    raise ValueError(f"unsupported age: {value}")


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _run_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads((path / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def plan_cleanup(*, home: Path, older_than: str, successful: bool) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - parse_age(older_than)
    candidates: list[dict[str, Any]] = []
    runs_root = home / "runs"
    if not runs_root.exists():
        return {"writes": False, "candidates": []}
    for run_dir in sorted(runs_root.glob("*/*")):
        if not run_dir.is_dir():
            continue
        data = _run_json(run_dir)
        status = str(data.get("status") or "unknown")
        if successful and status not in {"finished", "planning_only"}:
            continue
        created = _parse_time(data.get("created_at") or data.get("started_at"))
        if created > cutoff:
            continue
        candidates.append(
            {
                "kind": "run_dir",
                "run_id": str(data.get("run_id") or run_dir.name),
                "path": str(run_dir),
                "status": status,
                "reason": f"older_than_{older_than}",
            }
        )
    return {"writes": False, "candidates": candidates}


def apply_cleanup(plan: dict[str, Any]) -> dict[str, Any]:
    removed: list[dict[str, Any]] = []
    for item in plan.get("candidates", []):
        path = Path(str(item["path"]))
        if item.get("kind") == "run_dir" and path.exists():
            shutil.rmtree(path)
            removed.append(dict(item))
    return {"writes": True, "removed": removed}


__all__ = ["apply_cleanup", "parse_age", "plan_cleanup"]
```

- [ ] **Step 4: Wire clean command dry-run**

In `skills/agent-runway/scripts/agentrunway/invocation.py`, add:

```python
    clean.add_argument("--dry-run", action="store_true", default=True)
    clean.add_argument("--apply", action="store_true")
```

Change the clean dispatch to:

```python
        elif args.command == "clean":
            payload = runner.clean(args.older_than, successful=args.successful, dry_run=not bool(args.apply))
```

In `skills/agent-runway/scripts/agentrunway/runner.py`, change `clean` to:

```python
def clean(older_than: str, *, successful: bool, dry_run: bool = True) -> dict[str, Any]:
    from .retention import apply_cleanup, plan_cleanup

    plan = plan_cleanup(home=agentrunway_home(), older_than=older_than, successful=successful)
    if dry_run:
        return plan
    return apply_cleanup(plan)
```

- [ ] **Step 5: Add CLI smoke for clean flags**

In `skills/agent-runway/evals/test_cli_smoke.py`, extend the clean command assertion to include:

```python
    args = parser.parse_args(["clean", "--older-than", "14d", "--successful", "--apply"])
    assert args.command == "clean"
    assert args.apply is True
```

- [ ] **Step 6: Run retention tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_retention_clean.py evals/test_cli_smoke.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/retention.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_retention_clean.py skills/agent-runway/evals/test_cli_smoke.py
git commit -m "feat: clean retained AgentRunway runs"
```

---

## Task 10: Harden Apply Conflict Reporting

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/apply.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_resume_apply.py`

- [ ] **Step 1: Write failing conflict detail test**

Append to `skills/agent-runway/evals/test_resume_apply.py`:

```python
def test_apply_reports_already_applied_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "a@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "A"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, stdout=subprocess.PIPE)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    result = apply_commits_to_source(repo, (sha,), already_applied=(sha,))
    assert result == []
```

- [ ] **Step 2: Run test and verify current behavior**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_resume_apply.py::test_apply_reports_already_applied_commits -v
```

Expected: PASS if already-applied behavior exists. If it fails, continue with Step 3 and make it pass.

- [ ] **Step 3: Add structured conflict details**

In `skills/agent-runway/scripts/agentrunway/apply.py`, make conflict errors include the failing commit:

```python
class ApplyConflictError(RuntimeError):
    def __init__(self, commit: str, message: str):
        super().__init__(message)
        self.commit = commit
        self.message = message
```

In the cherry-pick failure branch, raise:

```python
            raise ApplyConflictError(commit, result.stderr.strip() or result.stdout.strip() or "cherry-pick failed")
```

In `skills/agent-runway/scripts/agentrunway/runner.py`, update `apply()`:

```python
    try:
        applied = apply_commits_to_source(
            Path(data["repo_root"]),
            tuple(commits),
            strategy=strategy,
            already_applied=already_applied,
        )
    except Exception as exc:
        return {
            "run_id": run_id,
            "status": data.get("status"),
            "applied": False,
            "error": str(exc),
            "already_applied": list(already_applied),
        }
```

- [ ] **Step 4: Run apply tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_resume_apply.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/apply.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_resume_apply.py
git commit -m "feat: report AgentRunway apply conflicts"
```

---

## Task 11: Documentation, Contracts, and Final Verification

**Files:**
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/SKILL.md`
- Modify: `skills/agent-runway/references/agentlens-events.md`
- Modify: `skills/agent-runway/evals/check_skill_contract.py`
- Modify: `AgentLens/docs/cli.md`
- Modify: `AgentLens/docs/contract.md`
- Modify: `docs/superpowers/specs/2026-05-20-agentrunway-agentlens-control-plane-design.md`

- [ ] **Step 1: Update AgentRunway README operator section**

In `skills/agent-runway/README.md`, add this paragraph under Operations Evidence:

```markdown
AgentRunway is the only supported AgentLens executor integration. New
observability events use the `agentrunway.*` namespace. CPE/CME workflows, if
present on disk, are independent legacy skills and are not bridged into
AgentRunway or AgentLens by this package.
```

- [ ] **Step 2: Update AgentLens event reference**

Replace `skills/agent-runway/references/agentlens-events.md` with:

````markdown
# AgentLens Events

AgentRunway records runner-validated facts locally before attempting AgentLens
emission. The local event journal and SQLite outbox are authoritative.

Supported event namespace:

```text
agentrunway.*
```

Core event types:

- `agentrunway.run_started`
- `agentrunway.contract_created`
- `agentrunway.worker_dispatched`
- `agentrunway.worker_result`
- `agentrunway.review_dispatched`
- `agentrunway.review_result`
- `agentrunway.verification_dispatched`
- `agentrunway.verification_result`
- `agentrunway.gate_retry`
- `agentrunway.merge_ready`
- `agentrunway.merge_conflict`
- `agentrunway.run_finished`
- `agentrunway.run_blocked`

Payloads use `schema="agentrunway.event.v1"` and include
`agentrunway_run_id`, `phase`, `outcome`, `severity`, `summary`, and bounded
event-specific fields. AgentLens emission is best effort; failed emission must
not stop plan execution.
````

- [ ] **Step 3: Pin docs in skill contract**

In `skills/agent-runway/evals/check_skill_contract.py`, add required terms:

```python
required_terms = {
    "agentrunway.*",
    "agentrunway.event.v1",
    "AgentRunway is the only supported AgentLens executor integration",
}
```

Read `README.md` and `references/agentlens-events.md` in the check, and assert each term appears in at least one of them.

- [ ] **Step 4: Update AgentLens docs**

In `AgentLens/docs/cli.md` and `AgentLens/docs/contract.md`, replace CPE/CME examples with:

```bash
agentlens run-open --agent agentrunway --workspace "$PWD"
agentlens event append --run "$RUN_ID" --type agentrunway.run_started --payload-json '{"schema":"agentrunway.event.v1","summary":"started"}'
agentlens events --run "$RUN_ID" --type 'agentrunway.*'
```

Do not mention `kws-cpe`, `kws-cme`, or `kws.orchestrator` as supported forward paths in these AgentLens docs.

- [ ] **Step 5: Run contract and doc checks**

Run:

```bash
cd skills/agent-runway
python3 evals/check_skill_contract.py
cd ../..
rg -n "kws-cme|kws-cpe|kws\\.orchestrator" AgentLens/src AgentLens/tests AgentLens/docs/cli.md AgentLens/docs/contract.md skills/agent-runway
```

Expected:

- `check_skill_contract.py` exits 0.
- `rg` exits 1 with no matches in those active AgentLens/AgentRunway paths.

- [ ] **Step 6: Run full verification**

Run:

```bash
cd skills/agent-runway && ./evals/run.sh
cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
cd skills/agent-runway && bash -n evals/run.sh
cd skills/agent-runway && python3 evals/check_skill_contract.py
cd AgentLens && python -m pytest tests/unit/test_agentrunway_events.py tests/unit/test_schema_validation.py tests/unit/test_event_query.py tests/integration/test_event_append.py tests/integration/test_failure_isolation.py tests/integration/test_phase1_smoke.py tests/integration/test_eval_determinism.py -v
git diff --check HEAD
graphify update .
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway AgentLens docs/superpowers/specs/2026-05-20-agentrunway-agentlens-control-plane-design.md
git commit -m "docs: document AgentRunway AgentLens control plane"
```

---

## Final Verification

Before marking the implementation complete, run:

```bash
cd skills/agent-runway && ./evals/run.sh
cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
cd skills/agent-runway && bash -n evals/run.sh
cd skills/agent-runway && python3 evals/check_skill_contract.py
cd AgentLens && python -m pytest tests/unit/test_agentrunway_events.py tests/unit/test_schema_validation.py tests/unit/test_event_query.py tests/integration/test_event_append.py tests/integration/test_failure_isolation.py tests/integration/test_phase1_smoke.py tests/integration/test_eval_determinism.py -v
git diff --check HEAD
graphify update .
```

Expected:

- AgentRunway evals pass.
- AgentLens focused tests pass.
- py_compile and shell syntax checks pass.
- `git diff --check HEAD` reports no whitespace errors.
- `graphify update .` exits 0 after code changes.
