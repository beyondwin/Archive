# AgentRunway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the greenfield `agent-runway` (`agentrunway`) skill and deterministic Python runner described in `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

**Architecture:** The skill remains thin and delegates execution to a Python runner under `skills/agent-runway/scripts/agentrunway.py`. The runner owns SQLite state, plan/spec parsing, file claims, worktree isolation, runtime adapters, merge gates, AgentLens emission, and CLI lifecycle commands. Workers never write SQLite or AgentLens directly; they operate in isolated worktrees and return bounded JSON artifacts.

**Tech Stack:** Python 3.11+ stdlib (`argparse`, `dataclasses`, `sqlite3`, `json`, `subprocess`, `pathlib`, `hashlib`), git worktrees, pytest, shell-based skill eval runner, optional AgentLens CLI, Markdown Superpowers skill docs.

---

## Scope Check

The design spans a full runner, adapter layer, skill contract, observability, and test harness. This plan keeps the MVP in one sequence because each task creates a testable vertical slice and the feature is one deployable skill. UI, GitHub PR automation, Gemini/Aider production adapters, and AgentLens child runs remain out of scope.

The plan intentionally starts with fake/local adapters and deterministic tests before Claude/Codex wrappers. That keeps the scheduler, merge queue, and safety policies testable without spending model calls.

## File Structure

### Create

| Path | Responsibility |
| --- | --- |
| `skills/agent-runway/SKILL.md` | Thin Superpowers skill entrypoint; parse human invocation shape and instruct host to run `scripts/agentrunway.py`. |
| `skills/agent-runway/README.md` | Operator overview, quick start, lifecycle, and source-of-truth links. |
| `skills/agent-runway/AGENTS.md` | Local instructions for workers maintaining this skill. |
| `skills/agent-runway/references/protocol.md` | Normative role/source-of-truth protocol. |
| `skills/agent-runway/references/model-profiles.md` | Built-in profiles and runtime reasoning mapping. |
| `skills/agent-runway/references/task-packet.md` | Task packet schema explanation and examples. |
| `skills/agent-runway/references/file-claims.md` | File claim modes, conflict rules, and shared append validators. |
| `skills/agent-runway/references/runtime-adapters.md` | Adapter contract and capability negotiation. |
| `skills/agent-runway/references/agentlens-events.md` | `agentrunway.*` event envelope, privacy rules, and failure policy. |
| `skills/agent-runway/references/worktree-policy.md` | Workspace identity, branch naming, dirty-source policy, ignored-file copying. |
| `skills/agent-runway/references/merge-queue.md` | Merge queue states and apply semantics. |
| `skills/agent-runway/references/context-policy.md` | Snapshot, compaction, and rotation behavior. |
| `skills/agent-runway/references/watchdog.md` | Stall detection and action ladder. |
| `skills/agent-runway/references/failure-policy.md` | Failure taxonomy and retry budgets. |
| `skills/agent-runway/references/schemas/task_packet.v1.json` | JSON Schema for worker packets. |
| `skills/agent-runway/references/schemas/worker_result.v1.json` | JSON Schema for implementer results. |
| `skills/agent-runway/references/schemas/review_result.v1.json` | JSON Schema for reviewer results. |
| `skills/agent-runway/references/schemas/verification_result.v1.json` | JSON Schema for verifier results. |
| `skills/agent-runway/references/schemas/event.v1.json` | JSON Schema for AgentRunway AgentLens payloads. |
| `skills/agent-runway/scripts/agentrunway.py` | CLI entrypoint. |
| `skills/agent-runway/scripts/agentrunway/__init__.py` | Package marker and version export. |
| `skills/agent-runway/scripts/agentrunway/__main__.py` | `python -m agentrunway` entrypoint. |
| `skills/agent-runway/scripts/agentrunway/artifacts.py` | Artifact path creation, refs, hashing, excerpt writing. |
| `skills/agent-runway/scripts/agentrunway/config.py` | `agentrunway.yaml` and `~/.agentrunway/global.yaml` loading plus defaults. |
| `skills/agent-runway/scripts/agentrunway/cost.py` | Best-effort runtime cost extraction normalization. |
| `skills/agent-runway/scripts/agentrunway/db.py` | SQLite schema, migrations, repositories, and state transitions. |
| `skills/agent-runway/scripts/agentrunway/events.py` | AgentLens payload building, redaction, and best-effort emission. |
| `skills/agent-runway/scripts/agentrunway/file_claims.py` | Claim parsing, conflict inference, and diff-scope validation. |
| `skills/agent-runway/scripts/agentrunway/git_ops.py` | Git command wrapper, dirty checks, refs, worktree/cherry-pick helpers. |
| `skills/agent-runway/scripts/agentrunway/invocation.py` | CLI argument and skill-style key-value parsing. |
| `skills/agent-runway/scripts/agentrunway/merge_queue.py` | Candidate validation, reviewer/verifier gate state, merge application. |
| `skills/agent-runway/scripts/agentrunway/method_audit.py` | Superpowers/TDD audit verification and waiver checks. |
| `skills/agent-runway/scripts/agentrunway/models.py` | Dataclasses/enums shared by the runner. |
| `skills/agent-runway/scripts/agentrunway/packetizer.py` | Compact worker packet creation and prompt materialization. |
| `skills/agent-runway/scripts/agentrunway/plan_parser.py` | Markdown plan/spec parser with `yaml agentrunway-task` blocks. |
| `skills/agent-runway/scripts/agentrunway/resource_locks.py` | Non-file lock conflict detection and global semaphore helpers. |
| `skills/agent-runway/scripts/agentrunway/result_validation.py` | JSON result schema validation and normalized failure codes. |
| `skills/agent-runway/scripts/agentrunway/runner.py` | Top-level run/resume orchestration loop. |
| `skills/agent-runway/scripts/agentrunway/scheduler.py` | Dependency graph, wave computation, risk ordering. |
| `skills/agent-runway/scripts/agentrunway/status.py` | Status/inspect/events output formatting. |
| `skills/agent-runway/scripts/agentrunway/watchdog.py` | Worker stall classification and action selection. |
| `skills/agent-runway/scripts/agentrunway/worktrees.py` | Workspace id, run id, branch/path registry, ignored-file allowlist. |
| `skills/agent-runway/scripts/agentrunway/adapters/base.py` | Runtime adapter protocol and shared handle/result dataclasses. |
| `skills/agent-runway/scripts/agentrunway/adapters/local.py` | Fake/local adapter for deterministic tests and no-agent dry runs. |
| `skills/agent-runway/scripts/agentrunway/adapters/claude.py` | Claude Code/headless process adapter wrapper. |
| `skills/agent-runway/scripts/agentrunway/adapters/codex.py` | Codex CLI/headless process adapter wrapper. |
| `skills/agent-runway/evals/conftest.py` | Shared pytest fixtures for temp repos and fake adapters. |
| `skills/agent-runway/evals/test_*.py` | Unit/integration tests grouped by subsystem. |
| `skills/agent-runway/evals/fixtures/*` | Minimal plan/spec/repo fixtures for E2E tests. |
| `skills/agent-runway/evals/run.sh` | Test runner used by skill contract checks. |
| `skills/agent-runway/evals/check_skill_contract.py` | Static contract checks for docs, schema refs, and required protocol text. |

### Modify

| Path | Change |
| --- | --- |
| `skills/README.md` | Add `agent-runway` to the local skill catalog if this README lists installed Archive skills. |
| `docs/superpowers/specs/2026-05-20-agent-runway-design.md` | No behavioral edits required. If implementation reveals an approved policy mismatch, update only by adding a dated revision note. |

---

## Phase 1 — Scaffold, Contracts, and Test Harness

### Task 1: Scaffold the Skill and Empty Runner Package

**Files:**
- Create: `skills/agent-runway/SKILL.md`
- Create: `skills/agent-runway/README.md`
- Create: `skills/agent-runway/AGENTS.md`
- Create: `skills/agent-runway/scripts/agentrunway.py`
- Create: `skills/agent-runway/scripts/agentrunway/__init__.py`
- Create: `skills/agent-runway/scripts/agentrunway/__main__.py`
- Create: `skills/agent-runway/evals/run.sh`
- Create: `skills/agent-runway/evals/test_cli_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

Create `skills/agent-runway/evals/test_cli_smoke.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_agentrunway_cli_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip().startswith("agentrunway ")


def test_agentrunway_cli_lists_core_commands() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for command in ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean"):
        assert command in result.stdout
```

- [ ] **Step 2: Run the smoke test and verify it fails**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_cli_smoke.py -v
```

Expected: failure because `scripts/agentrunway.py` does not exist.

- [ ] **Step 3: Create the package entrypoints**

Create `skills/agent-runway/scripts/agentrunway/__init__.py`:

```python
"""AgentRunway runner."""

__version__ = "0.1.0"
```

Create `skills/agent-runway/scripts/agentrunway/__main__.py`:

```python
from __future__ import annotations

from .invocation import main


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `skills/agent-runway/scripts/agentrunway.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agentrunway.invocation import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add the initial invocation module**

Create `skills/agent-runway/scripts/agentrunway/invocation.py`:

```python
from __future__ import annotations

import argparse

from . import __version__


COMMANDS = ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentrunway",
        description="AgentRunway deterministic runner",
    )
    parser.add_argument("--version", action="version", version=f"agentrunway {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.required = False
    for command in COMMANDS:
        sub.add_parser(command, help=f"{command} a AgentRunway run")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(f"agentrunway {args.command}: not implemented")
    return 2
```

- [ ] **Step 5: Add the skill docs skeleton**

Create `skills/agent-runway/SKILL.md`:

```markdown
---
name: agent-runway
description: Execute approved implementation plans through the deterministic AgentRunway Python runner with isolated worktrees, runtime adapters, review/verification gates, and AgentLens `agentrunway.*` observability.
---

# AgentRunway

Use this skill when the user asks to execute an approved plan/spec through AgentRunway or explicitly invokes `agent-runway`.

## Required Bootstrap

1. Invoke/read `using-superpowers` before doing anything else.
2. Confirm the user supplied `plan=<path>` and optional `spec=<path>`.
3. Shell out to `scripts/agentrunway.py`; do not orchestrate workers from conversation context.

## Invocation

```bash
python3 skills/agent-runway/scripts/agentrunway.py run --plan <plan.md> --spec <spec.md>
```

The runner owns scheduling, state, worktrees, runtime adapters, review, verification, merge queue, and AgentLens emission. The host session surfaces the runner summary and uses `agentrunway status --run <run_id>` for follow-up visibility.
```

Create `skills/agent-runway/README.md`:

```markdown
# agent-runway

`agent-runway` (`agentrunway`) executes approved Superpowers plans through a deterministic Python runner.

Source of truth:

- Design: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-20-agent-runway.md`

The runner stores state in SQLite under `~/.agentrunway/runs`, does implementation work in isolated git worktrees under `~/.agentrunway/worktrees`, and emits bounded AgentLens events under the `agentrunway.*` namespace.
```

Create `skills/agent-runway/AGENTS.md`:

```markdown
# AgentRunway Agent Instructions

- Treat `docs/superpowers/specs/2026-05-20-agent-runway-design.md` as the behavioral source of truth.
- Keep the skill thin; put execution logic in `scripts/agentrunway/`.
- Do not let workers write SQLite or AgentLens directly.
- Add or update pytest coverage for every runner behavior change.
- Keep runtime artifacts out of the repo; they belong under `~/.agentrunway/`.
```

- [ ] **Step 6: Add the eval runner and make it executable**

Create `skills/agent-runway/evals/run.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest evals -v
```

Run:

```bash
chmod +x skills/agent-runway/evals/run.sh
```

- [ ] **Step 7: Re-run the smoke tests**

Run:

```bash
cd skills/agent-runway
./evals/run.sh
```

Expected: `test_cli_smoke.py` passes and unimplemented subcommands return exit code `2` only when directly invoked, not during the smoke tests.

- [ ] **Step 8: Commit**

```bash
git add skills/agent-runway
git commit -m "feat: scaffold AgentRunway skill and runner"
```

### Task 2: Add Shared Models, Enums, and Schema Files

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/models.py`
- Create: `skills/agent-runway/references/schemas/task_packet.v1.json`
- Create: `skills/agent-runway/references/schemas/worker_result.v1.json`
- Create: `skills/agent-runway/references/schemas/review_result.v1.json`
- Create: `skills/agent-runway/references/schemas/verification_result.v1.json`
- Create: `skills/agent-runway/references/schemas/event.v1.json`
- Create: `skills/agent-runway/evals/test_models_and_schemas.py`

- [ ] **Step 1: Write failing tests for model constants and schemas**

Create `skills/agent-runway/evals/test_models_and_schemas.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.models import (
    CLAIM_MODES,
    EVENT_SCHEMA,
    OUTCOMES,
    REASONING_LEVELS,
    RESULT_SCHEMA,
    TASK_PACKET_SCHEMA,
)


ROOT = Path(__file__).resolve().parents[1]


def test_schema_constants_match_design() -> None:
    assert TASK_PACKET_SCHEMA == "agentrunway.task_packet.v1"
    assert RESULT_SCHEMA == "agentrunway.worker_result.v1"
    assert EVENT_SCHEMA == "agentrunway.event.v1"


def test_core_enums_cover_mvp_policy() -> None:
    assert CLAIM_MODES == {"owned", "shared_append", "consumes", "read_only", "forbidden"}
    assert OUTCOMES == {"finished", "failed", "blocked", "cancelled", "unknown"}
    assert REASONING_LEVELS == {"lowest", "low", "medium", "high", "highest"}


def test_reference_schema_files_are_valid_json() -> None:
    schema_dir = ROOT / "references" / "schemas"
    expected = {
        "task_packet.v1.json",
        "worker_result.v1.json",
        "review_result.v1.json",
        "verification_result.v1.json",
        "event.v1.json",
    }
    assert {path.name for path in schema_dir.glob("*.json")} == expected
    for path in schema_dir.glob("*.json"):
        data = json.loads(path.read_text())
        assert data["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert data["type"] == "object"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_models_and_schemas.py -v
```

Expected: `ModuleNotFoundError` or missing schema file failure.

- [ ] **Step 3: Implement shared dataclasses and constants**

Create `skills/agent-runway/scripts/agentrunway/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


AGENTRUNWAY_VERSION = "0.1.0"
TASK_PACKET_SCHEMA = "agentrunway.task_packet.v1"
RESULT_SCHEMA = "agentrunway.worker_result.v1"
REVIEW_SCHEMA = "agentrunway.review_result.v1"
VERIFICATION_SCHEMA = "agentrunway.verification_result.v1"
EVENT_SCHEMA = "agentrunway.event.v1"

CLAIM_MODES = {"owned", "shared_append", "consumes", "read_only", "forbidden"}
OUTCOMES = {"finished", "failed", "blocked", "cancelled", "unknown"}
AGENTLENS_OUTCOMES = {"success", "failed", "partial", "cancelled", "unknown"}
REASONING_LEVELS = {"lowest", "low", "medium", "high", "highest"}


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    REVIEWING = "reviewing"
    VERIFYING = "verifying"
    MERGED = "merged"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class FileClaim:
    path: str
    mode: Literal["owned", "shared_append", "consumes", "read_only", "forbidden"]


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    title: str
    risk: Literal["low", "medium", "high"]
    phase: str
    dependencies: tuple[str, ...]
    spec_refs: tuple[str, ...]
    file_claims: tuple[FileClaim, ...]
    acceptance_commands: tuple[str, ...]
    resource_keys: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()
    serial: bool = False
    objective: str = ""
    line: int = 0


@dataclass(frozen=True)
class ModelAssignment:
    runtime: str
    model: str
    reasoning_effort: str
    reasoning_effort_resolved: str | None = None


@dataclass(frozen=True)
class TaskPacket:
    schema: str
    run_id: str
    task_id: str
    role: str
    objective: str
    spec_refs: tuple[dict[str, str], ...]
    dependencies: tuple[str, ...]
    allowed_write_globs: tuple[str, ...]
    forbidden_write_globs: tuple[str, ...]
    file_claims: tuple[FileClaim, ...]
    required_skills: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    output_schema: str
    model_assignment: ModelAssignment


@dataclass
class WorkerResult:
    schema: str
    worker_id: str
    task_id: str
    role: str
    status: str
    changed_files: list[str]
    commit: str | None
    summary: str
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    method_audit: dict[str, Any] = field(default_factory=dict)
    residual_risks: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Add minimal JSON Schemas**

Create `skills/agent-runway/references/schemas/task_packet.v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agentrunway.task_packet.v1",
  "type": "object",
  "required": ["schema", "run_id", "task_id", "role", "objective", "file_claims", "required_skills", "acceptance_commands", "output_schema", "model_assignment"],
  "properties": {
    "schema": {"const": "agentrunway.task_packet.v1"},
    "run_id": {"type": "string", "minLength": 1},
    "task_id": {"type": "string", "minLength": 1},
    "role": {"enum": ["implementer", "reviewer", "verifier", "recovery"]},
    "objective": {"type": "string"},
    "spec_refs": {"type": "array"},
    "dependencies": {"type": "array", "items": {"type": "string"}},
    "allowed_write_globs": {"type": "array", "items": {"type": "string"}},
    "forbidden_write_globs": {"type": "array", "items": {"type": "string"}},
    "file_claims": {"type": "array"},
    "required_skills": {"type": "array", "items": {"type": "string"}},
    "acceptance_commands": {"type": "array", "items": {"type": "string"}},
    "output_schema": {"const": "agentrunway.worker_result.v1"},
    "model_assignment": {"type": "object"}
  }
}
```

Create `skills/agent-runway/references/schemas/worker_result.v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agentrunway.worker_result.v1",
  "type": "object",
  "required": ["schema", "worker_id", "task_id", "role", "status", "changed_files", "summary", "method_audit"],
  "properties": {
    "schema": {"const": "agentrunway.worker_result.v1"},
    "worker_id": {"type": "string"},
    "task_id": {"type": "string"},
    "role": {"enum": ["implementer", "reviewer", "verifier", "recovery"]},
    "status": {"enum": ["success", "failed", "blocked", "malformed"]},
    "changed_files": {"type": "array", "items": {"type": "string"}},
    "commit": {"type": ["string", "null"]},
    "summary": {"type": "string", "maxLength": 1200},
    "commands_run": {"type": "array"},
    "method_audit": {"type": "object"},
    "residual_risks": {"type": "array", "items": {"type": "string"}}
  }
}
```

Create `skills/agent-runway/references/schemas/review_result.v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agentrunway.review_result.v1",
  "type": "object",
  "required": ["schema", "worker_id", "task_id", "reviewed_worker_id", "status", "checks", "findings", "method_audit"],
  "properties": {
    "schema": {"const": "agentrunway.review_result.v1"},
    "worker_id": {"type": "string"},
    "task_id": {"type": "string"},
    "reviewed_worker_id": {"type": "string"},
    "status": {"enum": ["approved", "rejected", "blocked"]},
    "checks": {"type": "array", "minItems": 1},
    "findings": {"type": "array"},
    "method_audit": {"type": "object"}
  }
}
```

Create `skills/agent-runway/references/schemas/verification_result.v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agentrunway.verification_result.v1",
  "type": "object",
  "required": ["schema", "worker_id", "task_id", "status", "checks", "method_audit"],
  "properties": {
    "schema": {"const": "agentrunway.verification_result.v1"},
    "worker_id": {"type": "string"},
    "task_id": {"type": "string"},
    "status": {"enum": ["passed", "failed", "blocked"]},
    "checks": {"type": "array", "minItems": 1},
    "method_audit": {"type": "object"}
  }
}
```

Create `skills/agent-runway/references/schemas/event.v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agentrunway.event.v1",
  "type": "object",
  "required": ["schema", "agentrunway_run_id", "phase", "outcome", "severity", "summary", "privacy"],
  "properties": {
    "schema": {"const": "agentrunway.event.v1"},
    "agentrunway_run_id": {"type": "string"},
    "phase": {"type": "string"},
    "task_id": {"type": ["string", "null"]},
    "worker_id": {"type": ["string", "null"]},
    "runtime": {"type": ["string", "null"]},
    "role": {"type": ["string", "null"]},
    "model": {"type": ["string", "null"]},
    "reasoning_effort": {"type": ["string", "null"]},
    "outcome": {"enum": ["success", "failed", "partial", "cancelled", "unknown"]},
    "severity": {"enum": ["info", "warn", "error"]},
    "summary": {"type": "string", "maxLength": 1200},
    "evidence": {"type": ["object", "null"]},
    "privacy": {"type": "object"}
  }
}
```

- [ ] **Step 5: Re-run tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_models_and_schemas.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/models.py skills/agent-runway/references/schemas skills/agent-runway/evals/test_models_and_schemas.py
git commit -m "feat: add AgentRunway data contracts"
```

### Task 3: Implement CLI Invocation Parsing and Model Profile Resolution

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Create: `skills/agent-runway/scripts/agentrunway/config.py`
- Create: `skills/agent-runway/evals/test_invocation_and_config.py`

- [ ] **Step 1: Write failing invocation/config tests**

Create `skills/agent-runway/evals/test_invocation_and_config.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.config import BuiltinProfiles, load_effective_config, resolve_reasoning
from agentrunway.invocation import parse_key_value_invocation, parse_run_args


def test_parse_skill_key_value_invocation() -> None:
    parsed = parse_key_value_invocation(
        "plan=plans/auth.md spec=specs/auth.md runtime=codex worker_reasoning=high"
    )
    assert parsed["plan"] == "plans/auth.md"
    assert parsed["spec"] == "specs/auth.md"
    assert parsed["runtime"] == "codex"
    assert parsed["worker_reasoning"] == "high"


def test_parse_run_args_defaults_to_codex_profile() -> None:
    args = parse_run_args(["run", "--plan", "p.md", "--spec", "s.md"])
    assert args.plan == Path("p.md")
    assert args.spec == Path("s.md")
    assert args.model_profile == "codex-default"
    assert args.apply_to_source is False


def test_config_precedence_invocation_over_agentrunway_yaml(tmp_path: Path) -> None:
    (tmp_path / "agentrunway.yaml").write_text(
        "default_profile: claude-default\n"
        "profiles:\n"
        "  custom:\n"
        "    orchestrator: {runtime: codex, model: gpt-5.5, reasoning_effort: highest}\n",
        encoding="utf-8",
    )
    cfg = load_effective_config(tmp_path, {"model_profile": "codex-default"})
    assert cfg.default_profile == "codex-default"


def test_reasoning_resolution_maps_xhigh_alias() -> None:
    assert resolve_reasoning("codex", "xhigh") == ("highest", "xhigh")
    assert resolve_reasoning("claude", "highest") == ("highest", "high")


def test_builtin_profiles_are_explicit() -> None:
    profiles = BuiltinProfiles.default()
    assert profiles["codex-default"].orchestrator.runtime == "codex"
    assert profiles["codex-default"].orchestrator.reasoning_effort == "highest"
    assert profiles["claude-default"].workers["default"].runtime == "claude"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_invocation_and_config.py -v
```

Expected: import errors for `config.py` and missing parser functions.

- [ ] **Step 3: Implement config dataclasses and defaults**

Create `skills/agent-runway/scripts/agentrunway/config.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ModelAssignment


@dataclass(frozen=True)
class ModelProfile:
    orchestrator: ModelAssignment
    workers: dict[str, ModelAssignment] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectiveConfig:
    default_profile: str
    profiles: dict[str, ModelProfile]
    runtime_caps: dict[str, int]
    agentlens_namespace_prefix: str = "agentrunway"
    apply_to_source: bool = False


class BuiltinProfiles:
    @staticmethod
    def default() -> dict[str, ModelProfile]:
        return {
            "codex-default": ModelProfile(
                orchestrator=ModelAssignment("codex", "gpt-5.5", "highest"),
                workers={"default": ModelAssignment("codex", "gpt-5.5", "high")},
            ),
            "claude-default": ModelProfile(
                orchestrator=ModelAssignment("claude", "opus", "high"),
                workers={"default": ModelAssignment("claude", "opus", "high")},
            ),
            "same-host": ModelProfile(
                orchestrator=ModelAssignment("host", "default", "medium"),
                workers={"default": ModelAssignment("host", "default", "medium")},
            ),
        }


def _parse_simple_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        text = path.read_text(encoding="utf-8")
        if text.strip().startswith("{"):
            return json.loads(text)
        data: dict[str, Any] = {}
        for line in text.splitlines():
            if ":" in line and not line.startswith(" "):
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip() or {}
        return data
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def resolve_reasoning(runtime: str, requested: str) -> tuple[str, str]:
    portable = "highest" if requested == "xhigh" else requested
    if portable not in {"lowest", "low", "medium", "high", "highest"}:
        raise ValueError(f"unsupported reasoning_effort: {requested}")
    table = {
        "codex": {"lowest": "low", "low": "medium", "medium": "medium", "high": "high", "highest": "xhigh"},
        "claude": {"lowest": "low", "low": "low", "medium": "medium", "high": "high", "highest": "high"},
        "local": {"lowest": "n/a", "low": "n/a", "medium": "n/a", "high": "n/a", "highest": "n/a"},
        "host": {"lowest": "default", "low": "default", "medium": "default", "high": "default", "highest": "default"},
    }
    runtime_map = table.get(runtime)
    if runtime_map is None:
        raise ValueError(f"unsupported runtime for reasoning resolution: {runtime}")
    return portable, runtime_map[portable]


def load_effective_config(repo_root: Path, invocation: dict[str, Any]) -> EffectiveConfig:
    local = _parse_simple_yaml(repo_root / "agentrunway.yaml")
    global_cfg = _parse_simple_yaml(Path.home() / ".agentrunway" / "global.yaml")
    default_profile = str(
        invocation.get("model_profile")
        or local.get("default_profile")
        or "codex-default"
    )
    caps_raw = global_cfg.get("runtime_caps") if isinstance(global_cfg.get("runtime_caps"), dict) else {}
    runtime_caps = {
        "claude": int(caps_raw.get("claude", {}).get("max_concurrent_workers", 6)) if isinstance(caps_raw.get("claude"), dict) else 6,
        "codex": int(caps_raw.get("codex", {}).get("max_concurrent_workers", 8)) if isinstance(caps_raw.get("codex"), dict) else 8,
    }
    return EffectiveConfig(
        default_profile=default_profile,
        profiles=BuiltinProfiles.default(),
        runtime_caps=runtime_caps,
        agentlens_namespace_prefix=str(local.get("agentlens", {}).get("namespace_prefix", "agentrunway"))
        if isinstance(local.get("agentlens"), dict)
        else "agentrunway",
        apply_to_source=bool(invocation.get("apply_to_source", False)),
    )
```

- [ ] **Step 4: Implement CLI parse functions**

Modify `skills/agent-runway/scripts/agentrunway/invocation.py`:

```python
from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from . import __version__


COMMANDS = ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean")


def parse_key_value_invocation(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in shlex.split(text):
        if "=" not in token:
            raise ValueError(f"expected key=value token, got {token!r}")
        key, value = token.split("=", 1)
        if not key or not value:
            raise ValueError(f"empty key or value in token {token!r}")
        values[key] = value
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentrunway", description="AgentRunway deterministic runner")
    parser.add_argument("--version", action="version", version=f"agentrunway {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="start a AgentRunway run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--spec", type=Path)
    run.add_argument("--model-profile", default="codex-default")
    run.add_argument("--base-ref", default="HEAD")
    run.add_argument("--allow-dirty-source", action="store_true")
    run.add_argument("--detach", action="store_true")
    run.add_argument("--apply-to-source", action="store_true")

    for command in ("status", "inspect", "events", "resume", "cancel", "apply"):
        cmd = sub.add_parser(command, help=f"{command} a AgentRunway run")
        cmd.add_argument("--run", required=True)
    clean = sub.add_parser("clean", help="clean retained AgentRunway artifacts")
    clean.add_argument("--older-than", default="7d")
    clean.add_argument("--successful", action="store_true")
    return parser


def parse_run_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(f"agentrunway {args.command}: not implemented")
    return 2
```

- [ ] **Step 5: Re-run tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_invocation_and_config.py evals/test_cli_smoke.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/config.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/evals/test_invocation_and_config.py
git commit -m "feat: parse AgentRunway invocation and profiles"
```

## Phase 2 — State, Parsing, and Scheduling

### Task 4: Add SQLite Control Plane

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/db.py`
- Create: `skills/agent-runway/evals/test_db.py`

- [ ] **Step 1: Write failing DB tests**

Create `skills/agent-runway/evals/test_db.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import TaskSpec


def test_db_initializes_required_tables(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    tables = db.table_names()
    for table in (
        "runs",
        "tasks",
        "task_packets",
        "file_claims",
        "waves",
        "workers",
        "messages",
        "artifacts",
        "merge_queue",
        "agentlens_events",
        "cost_ledger",
        "method_audits",
        "context_snapshots",
        "worktree_registry",
        "resource_locks",
        "watchdog_events",
    ):
        assert table in tables


def test_create_run_and_task_round_trip(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_run(
        run_id="run-1",
        workspace_id="repo-abc123",
        repo_root="/repo",
        plan_path="plan.md",
        spec_path="spec.md",
        plan_hash="sha256:1",
        spec_hash="sha256:2",
        base_commit_sha="abc",
        model_profile="codex-default",
    )
    task = TaskSpec(
        task_id="task_001",
        title="Add parser",
        risk="medium",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(),
        acceptance_commands=("pytest",),
    )
    db.upsert_task(task)
    assert db.get_run("run-1")["status"] == "created"
    assert db.get_task("task_001")["title"] == "Add parser"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentrunway.db'`.

- [ ] **Step 3: Implement DB initialization and repositories**

Create `skills/agent-runway/scripts/agentrunway/db.py`:

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import AGENTRUNWAY_VERSION, TaskSpec


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  repo_root TEXT NOT NULL,
  plan_path TEXT NOT NULL,
  spec_path TEXT,
  plan_hash TEXT NOT NULL,
  spec_hash TEXT,
  base_commit_sha TEXT NOT NULL,
  model_profile TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'created',
  allowed_dirty INTEGER NOT NULL DEFAULT 0,
  apply_to_source INTEGER NOT NULL DEFAULT 0,
  agentlens_run_id TEXT,
  agentlens_status TEXT NOT NULL DEFAULT 'disabled',
  agentrunway_version TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  risk TEXT NOT NULL,
  phase TEXT NOT NULL,
  dependencies_json TEXT NOT NULL,
  spec_refs_json TEXT NOT NULL,
  acceptance_commands_json TEXT NOT NULL,
  resource_keys_json TEXT NOT NULL,
  required_skills_json TEXT NOT NULL,
  serial INTEGER NOT NULL,
  objective TEXT NOT NULL,
  line INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS task_packets (task_id TEXT PRIMARY KEY, packet_hash TEXT NOT NULL, prompt_path TEXT NOT NULL, packet_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS file_claims (task_id TEXT NOT NULL, path TEXT NOT NULL, mode TEXT NOT NULL, PRIMARY KEY(task_id, path, mode));
CREATE TABLE IF NOT EXISTS waves (wave_index INTEGER NOT NULL, task_id TEXT NOT NULL, PRIMARY KEY(wave_index, task_id));
CREATE TABLE IF NOT EXISTS workers (worker_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, role TEXT NOT NULL, runtime TEXT NOT NULL, model TEXT NOT NULL, reasoning_effort TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT, direction TEXT NOT NULL, message_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, worker_id TEXT, kind TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS merge_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, worker_id TEXT NOT NULL, commit_sha TEXT, patch_path TEXT, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agentlens_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS cost_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT, runtime TEXT, model TEXT, tokens_input INTEGER, tokens_output INTEGER, cost_usd REAL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS method_audits (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT NOT NULL, task_id TEXT NOT NULL, status TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS context_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS worktree_registry (path TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, run_id TEXT NOT NULL, branch TEXT NOT NULL, lifecycle TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS resource_locks (run_id TEXT NOT NULL, resource_key TEXT NOT NULL, task_id TEXT NOT NULL, PRIMARY KEY(run_id, resource_key, task_id));
CREATE TABLE IF NOT EXISTS watchdog_events (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT, action TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
"""


class AgentRunwayDb:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path) -> "AgentRunwayDb":
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        db = cls(conn)
        db.conn.executescript(SCHEMA_SQL)
        db.conn.commit()
        return db

    def table_names(self) -> set[str]:
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(row["name"]) for row in rows}

    def create_run(self, **fields: Any) -> None:
        payload = {
            "run_id": fields["run_id"],
            "workspace_id": fields["workspace_id"],
            "repo_root": fields["repo_root"],
            "plan_path": fields["plan_path"],
            "spec_path": fields.get("spec_path"),
            "plan_hash": fields["plan_hash"],
            "spec_hash": fields.get("spec_hash"),
            "base_commit_sha": fields["base_commit_sha"],
            "model_profile": fields["model_profile"],
            "allowed_dirty": int(bool(fields.get("allowed_dirty", False))),
            "apply_to_source": int(bool(fields.get("apply_to_source", False))),
            "agentrunway_version": AGENTRUNWAY_VERSION,
        }
        self.conn.execute(
            """
            INSERT INTO runs (run_id, workspace_id, repo_root, plan_path, spec_path, plan_hash, spec_hash, base_commit_sha, model_profile, allowed_dirty, apply_to_source, agentrunway_version)
            VALUES (:run_id, :workspace_id, :repo_root, :plan_path, :spec_path, :plan_hash, :spec_hash, :base_commit_sha, :model_profile, :allowed_dirty, :apply_to_source, :agentrunway_version)
            """,
            payload,
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def upsert_task(self, task: TaskSpec) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tasks
              (task_id, title, risk, phase, dependencies_json, spec_refs_json, acceptance_commands_json, resource_keys_json, required_skills_json, serial, objective, line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.title,
                task.risk,
                task.phase,
                json.dumps(list(task.dependencies)),
                json.dumps(list(task.spec_refs)),
                json.dumps(list(task.acceptance_commands)),
                json.dumps(list(task.resource_keys)),
                json.dumps(list(task.required_skills)),
                int(task.serial),
                task.objective,
                task.line,
            ),
        )
        for claim in task.file_claims:
            self.conn.execute(
                "INSERT OR REPLACE INTO file_claims (task_id, path, mode) VALUES (?, ?, ?)",
                (task.task_id, claim.path, claim.mode),
            )
        self.conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return dict(row)
```

- [ ] **Step 4: Re-run DB tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_db.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/db.py skills/agent-runway/evals/test_db.py
git commit -m "feat: add AgentRunway sqlite control plane"
```

### Task 5: Implement Plan and Spec Parser

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/plan_parser.py`
- Create: `skills/agent-runway/evals/test_plan_parser.py`

- [ ] **Step 1: Write failing parser tests**

Create `skills/agent-runway/evals/test_plan_parser.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agentrunway.plan_parser import PlanParseError, canonical_hash, parse_plan, parse_spec_manifest


PLAN = """# Auth Plan

## Task 1: Token refresh retry

```yaml agentrunway-task
task_id: task_001
title: Token refresh retry
risk: medium
phase: implementation
dependencies: []
spec_refs: [S2.1]
file_claims:
  - {path: src/auth/session.ts, mode: owned}
  - {path: tests/auth/session.test.ts, mode: owned}
acceptance_commands:
  - npm test -- tests/auth/session.test.ts
resource_keys: []
required_skills: [test-driven-development]
serial: false
```

Implement bounded retry behavior.
"""


def test_parse_plan_extracts_task_block(tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text(PLAN, encoding="utf-8")
    tasks = parse_plan(path)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id == "task_001"
    assert task.title == "Token refresh retry"
    assert task.file_claims[0].path == "src/auth/session.ts"
    assert task.required_skills == ("test-driven-development",)
    assert "bounded retry" in task.objective


def test_parse_plan_rejects_missing_agentrunway_task_block(tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text("## Task 1: Missing\n\nNo block\n", encoding="utf-8")
    with pytest.raises(PlanParseError, match="missing agentrunway-task"):
        parse_plan(path)


def test_spec_manifest_resolves_numbered_refs(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("## S2.1 Retry Policy\n\nRetry twice.\n\n### S2.2 Timeout\n\nStop.\n", encoding="utf-8")
    manifest = parse_spec_manifest(spec)
    assert manifest["S2.1"].heading == "S2.1 Retry Policy"
    assert manifest["S2.1"].content_sha256.startswith("sha256:")


def test_canonical_hash_ignores_trailing_space_and_crlf(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("one  \r\ntwo\r\n", encoding="utf-8")
    b.write_text("one\ntwo\n", encoding="utf-8")
    assert canonical_hash(a) == canonical_hash(b)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_plan_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentrunway.plan_parser'`.

- [ ] **Step 3: Implement parser**

Create `skills/agent-runway/scripts/agentrunway/plan_parser.py`:

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import CLAIM_MODES, FileClaim, TaskSpec


class PlanParseError(ValueError):
    pass


@dataclass(frozen=True)
class SpecSection:
    ref: str
    heading: str
    anchor: str
    content: str
    content_sha256: str


TASK_HEADING_RE = re.compile(r"^##\s+(Task\s+\d+:.+)$", re.MULTILINE)
BLOCK_RE = re.compile(r"```yaml agentrunway-task\n(.*?)\n```", re.DOTALL)
SPEC_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)


def _canonical_bytes(path: Path) -> bytes:
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).encode("utf-8")


def canonical_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(path)).hexdigest()


def _parse_scalar(value: str) -> Any:
    raw = value.strip()
    if raw in {"true", "false"}:
        return raw == "true"
    if raw.startswith("[") and raw.endswith("]"):
        body = raw[1:-1].strip()
        return [] if not body else [item.strip().strip("'\"") for item in body.split(",")]
    return raw.strip("'\"")


def _parse_block(block: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if value.strip():
                data[key] = _parse_scalar(value)
                i += 1
                continue
            items: list[Any] = []
            i += 1
            while i < len(lines) and lines[i].startswith("  - "):
                item = lines[i][4:].strip()
                if item.startswith("{") and item.endswith("}"):
                    pairs: dict[str, str] = {}
                    for part in item[1:-1].split(","):
                        k, v = part.split(":", 1)
                        pairs[k.strip()] = v.strip().strip("'\"")
                    items.append(pairs)
                else:
                    items.append(item.strip("'\""))
                i += 1
            data[key] = items
            continue
        raise PlanParseError(f"cannot parse agentrunway-task line: {line}")
    return data


def _objective_after(section: str) -> str:
    match = BLOCK_RE.search(section)
    if match is None:
        return ""
    objective = section[match.end():].strip()
    return re.sub(r"\s+", " ", objective)


def parse_plan(path: Path) -> list[TaskSpec]:
    text = path.read_text(encoding="utf-8")
    headings = list(TASK_HEADING_RE.finditer(text))
    if not headings:
        raise PlanParseError("plan has no Task headings")
    tasks: list[TaskSpec] = []
    for index, heading in enumerate(headings):
        start = heading.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[start:end]
        block_match = BLOCK_RE.search(section)
        if block_match is None:
            raise PlanParseError(f"missing agentrunway-task block under {heading.group(1)}")
        data = _parse_block(block_match.group(1))
        required = ["task_id", "title", "risk", "phase", "dependencies", "spec_refs", "file_claims", "acceptance_commands"]
        missing = [key for key in required if key not in data]
        if missing:
            raise PlanParseError(f"{data.get('task_id', heading.group(1))} missing required fields: {', '.join(missing)}")
        claims = []
        for raw_claim in data["file_claims"]:
            mode = raw_claim["mode"]
            if mode not in CLAIM_MODES:
                raise PlanParseError(f"{data['task_id']} has invalid claim mode {mode}")
            claims.append(FileClaim(path=raw_claim["path"], mode=mode))
        tasks.append(
            TaskSpec(
                task_id=str(data["task_id"]),
                title=str(data["title"]),
                risk=str(data["risk"]),  # validated by scheduler tests
                phase=str(data["phase"]),
                dependencies=tuple(data["dependencies"]),
                spec_refs=tuple(data["spec_refs"]),
                file_claims=tuple(claims),
                acceptance_commands=tuple(data["acceptance_commands"]),
                resource_keys=tuple(data.get("resource_keys", [])),
                required_skills=tuple(data.get("required_skills", [])),
                serial=bool(data.get("serial", False)),
                objective=_objective_after(section),
                line=text[:start].count("\n") + 1,
            )
        )
    return tasks


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_spec_manifest(path: Path | None) -> dict[str, SpecSection]:
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    matches = list(SPEC_HEADING_RE.finditer(text))
    manifest: dict[str, SpecSection] = {}
    for index, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        first_token = heading.split()[0] if heading.split() else _slug(heading)
        ref = first_token if re.match(r"^[A-Z]\d+(\.\d+)*$", first_token) else _slug(heading)
        digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest[ref] = SpecSection(ref=ref, heading=heading, anchor=_slug(heading), content=content, content_sha256=digest)
    return manifest
```

- [ ] **Step 4: Re-run parser tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_plan_parser.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/plan_parser.py skills/agent-runway/evals/test_plan_parser.py
git commit -m "feat: parse AgentRunway plan and spec inputs"
```

### Task 6: Implement File Claims, Resource Locks, and Wave Scheduler

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/file_claims.py`
- Create: `skills/agent-runway/scripts/agentrunway/resource_locks.py`
- Create: `skills/agent-runway/scripts/agentrunway/scheduler.py`
- Create: `skills/agent-runway/evals/test_scheduler.py`

- [ ] **Step 1: Write failing scheduler tests**

Create `skills/agent-runway/evals/test_scheduler.py`:

```python
from __future__ import annotations

from agentrunway.file_claims import claims_conflict
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.scheduler import build_waves


def task(
    task_id: str,
    claims: tuple[FileClaim, ...],
    deps: tuple[str, ...] = (),
    resources: tuple[str, ...] = (),
    risk: str = "medium",
    serial: bool = False,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk=risk,
        phase="implementation",
        dependencies=deps,
        spec_refs=(),
        file_claims=claims,
        acceptance_commands=("pytest",),
        resource_keys=resources,
        serial=serial,
    )


def test_owned_claims_conflict_same_path() -> None:
    assert claims_conflict(FileClaim("a.py", "owned"), FileClaim("a.py", "owned"))
    assert claims_conflict(FileClaim("a.py", "forbidden"), FileClaim("a.py", "read_only"))
    assert not claims_conflict(FileClaim("a.py", "read_only"), FileClaim("a.py", "read_only"))


def test_consumes_claim_waits_for_same_wave_owner() -> None:
    producer = task("task_001", (FileClaim("a.py", "owned"),), risk="low")
    consumer = task("task_002", (FileClaim("a.py", "consumes"),), risk="high")
    waves = build_waves([consumer, producer], max_workers=4)
    assert waves == [["task_001"], ["task_002"]]


def test_independent_tasks_share_wave_ordered_by_risk_then_id() -> None:
    a = task("task_001", (FileClaim("a.py", "owned"),), risk="low")
    b = task("task_002", (FileClaim("b.py", "owned"),), risk="high")
    c = task("task_003", (FileClaim("c.py", "owned"),), risk="medium")
    assert build_waves([a, b, c], max_workers=4) == [["task_002", "task_003", "task_001"]]


def test_resource_key_conflict_serializes_tasks() -> None:
    a = task("task_001", (FileClaim("a.py", "owned"),), resources=("port:3000",))
    b = task("task_002", (FileClaim("b.py", "owned"),), resources=("port:3000",))
    waves = build_waves([a, b], max_workers=4)
    assert waves == [["task_001"], ["task_002"]]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_scheduler.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement claim conflict logic**

Create `skills/agent-runway/scripts/agentrunway/file_claims.py`:

```python
from __future__ import annotations

from .models import FileClaim


def claims_conflict(a: FileClaim, b: FileClaim) -> bool:
    if a.path != b.path:
        return False
    if "forbidden" in {a.mode, b.mode}:
        return True
    if a.mode == "read_only" and b.mode == "read_only":
        return False
    if "owned" in {a.mode, b.mode}:
        return True
    if a.mode == "shared_append" and b.mode == "shared_append":
        return False
    if "consumes" in {a.mode, b.mode} and "shared_append" in {a.mode, b.mode}:
        return True
    return False


def task_claims_conflict(left: tuple[FileClaim, ...], right: tuple[FileClaim, ...]) -> bool:
    return any(claims_conflict(a, b) for a in left for b in right)
```

Create `skills/agent-runway/scripts/agentrunway/resource_locks.py`:

```python
from __future__ import annotations


def resources_conflict(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return bool(set(left) & set(right))
```

- [ ] **Step 4: Implement deterministic wave scheduler**

Create `skills/agent-runway/scripts/agentrunway/scheduler.py`:

```python
from __future__ import annotations

from collections import defaultdict

from .file_claims import task_claims_conflict
from .models import TaskSpec
from .resource_locks import resources_conflict


RISK_RANK = {"high": 3, "medium": 2, "low": 1}


def _inferred_edges(tasks: list[TaskSpec]) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {task.task_id: set(task.dependencies) for task in tasks}
    by_id = {task.task_id: task for task in tasks}
    ordered = sorted(tasks, key=lambda task: task.task_id)
    for later in ordered:
        for earlier in ordered:
            if earlier.task_id == later.task_id:
                continue
            if earlier.task_id > later.task_id:
                continue
            owner_paths = {claim.path for claim in earlier.file_claims if claim.mode == "owned"}
            consume_paths = {claim.path for claim in later.file_claims if claim.mode == "consumes"}
            if owner_paths & consume_paths:
                edges[later.task_id].add(earlier.task_id)
    missing = {dep for deps in edges.values() for dep in deps if dep not in by_id}
    if missing:
        raise ValueError(f"unknown task dependencies: {', '.join(sorted(missing))}")
    return edges


def _can_join_wave(candidate: TaskSpec, wave_tasks: list[TaskSpec]) -> bool:
    if candidate.serial:
        return not wave_tasks
    for existing in wave_tasks:
        if existing.serial:
            return False
        if task_claims_conflict(candidate.file_claims, existing.file_claims):
            return False
        if resources_conflict(candidate.resource_keys, existing.resource_keys):
            return False
    return True


def build_waves(tasks: list[TaskSpec], max_workers: int) -> list[list[str]]:
    by_id = {task.task_id: task for task in tasks}
    edges = _inferred_edges(tasks)
    remaining = set(by_id)
    completed: set[str] = set()
    waves: list[list[str]] = []
    while remaining:
        ready = [by_id[task_id] for task_id in remaining if edges[task_id] <= completed]
        if not ready:
            blocked = ", ".join(sorted(remaining))
            raise ValueError(f"cyclic or unsatisfied dependencies among: {blocked}")
        ready.sort(key=lambda task: (-RISK_RANK.get(task.risk, 0), -len(edges[task.task_id]), task.task_id))
        wave: list[TaskSpec] = []
        for candidate in ready:
            if len(wave) >= max_workers:
                break
            if _can_join_wave(candidate, wave):
                wave.append(candidate)
        if not wave:
            wave = [ready[0]]
        wave_ids = [task.task_id for task in wave]
        waves.append(wave_ids)
        completed.update(wave_ids)
        remaining.difference_update(wave_ids)
    return waves
```

- [ ] **Step 5: Re-run scheduler tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_scheduler.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/file_claims.py skills/agent-runway/scripts/agentrunway/resource_locks.py skills/agent-runway/scripts/agentrunway/scheduler.py skills/agent-runway/evals/test_scheduler.py
git commit -m "feat: schedule AgentRunway task waves"
```

## Phase 3 — Git, Worktrees, Packets, and Artifacts

### Task 7: Implement Git Operations and Worktree Identity

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/git_ops.py`
- Create: `skills/agent-runway/scripts/agentrunway/worktrees.py`
- Create: `skills/agent-runway/evals/conftest.py`
- Create: `skills/agent-runway/evals/test_worktrees.py`

- [ ] **Step 1: Write failing worktree tests**

Create `skills/agent-runway/evals/conftest.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agentrunway@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "AgentRunway Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo
```

Create `skills/agent-runway/evals/test_worktrees.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agentrunway.git_ops import Git, DirtySourceError
from agentrunway.worktrees import build_run_id, compute_workspace_id


def test_workspace_id_is_stable_from_linked_worktree(git_repo: Path, tmp_path: Path) -> None:
    git = Git(git_repo)
    linked = tmp_path / "linked"
    git.run("worktree", "add", str(linked), "main")
    assert compute_workspace_id(git_repo) == compute_workspace_id(linked)


def test_dirty_source_refuses_by_default(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(DirtySourceError):
        Git(git_repo).ensure_clean()


def test_run_id_contains_slug_timestamp_and_nonce() -> None:
    run_id = build_run_id("docs/plans/Auth Refactor.md", now="20260520-151000", nonce="abc12")
    assert run_id == "auth-refactor-20260520-151000-abc12"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_worktrees.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement git wrapper**

Create `skills/agent-runway/scripts/agentrunway/git_ops.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


class DirtySourceError(GitError):
    pass


class Git:
    def __init__(self, cwd: Path):
        self.cwd = cwd

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise GitError(result.stderr.strip() or result.stdout.strip())
        return result

    def output(self, *args: str) -> str:
        return self.run(*args).stdout.strip()

    def repo_root(self) -> Path:
        return Path(self.output("rev-parse", "--show-toplevel")).resolve()

    def common_dir(self) -> Path:
        raw = self.output("rev-parse", "--git-common-dir")
        path = Path(raw)
        if not path.is_absolute():
            path = self.cwd / path
        return path.resolve()

    def head(self) -> str:
        return self.output("rev-parse", "HEAD")

    def primary_branch_ref(self) -> str:
        result = self.run("symbolic-ref", "refs/remotes/origin/HEAD", check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().removeprefix("refs/remotes/origin/")
        return self.output("symbolic-ref", "HEAD")

    def remote_url(self) -> str:
        result = self.run("config", "--get", "remote.origin.url", check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def ensure_clean(self) -> None:
        status = self.output("status", "--porcelain")
        if status:
            raise DirtySourceError("dirty_source_checkout")
```

- [ ] **Step 4: Implement workspace identity**

Create `skills/agent-runway/scripts/agentrunway/worktrees.py`:

```python
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .git_ops import Git


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "agentrunway-run"


def compute_workspace_id(repo_path: Path) -> str:
    git = Git(repo_path)
    root = git.repo_root()
    basename = _slug(root.name)
    canonical_inputs = "\n".join(
        [
            str(git.common_dir()),
            git.remote_url(),
            git.primary_branch_ref(),
        ]
    )
    digest = hashlib.sha256(canonical_inputs.encode("utf-8")).hexdigest()[:10]
    return f"{basename}-{digest}"


def build_run_id(plan_path: str, now: str, nonce: str) -> str:
    stem = Path(plan_path).stem
    return f"{_slug(stem)}-{now}-{nonce}"
```

- [ ] **Step 5: Re-run worktree tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_worktrees.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/git_ops.py skills/agent-runway/scripts/agentrunway/worktrees.py skills/agent-runway/evals/conftest.py skills/agent-runway/evals/test_worktrees.py
git commit -m "feat: identify AgentRunway workspaces"
```

### Task 8: Implement Artifacts and Task Packet Builder

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/artifacts.py`
- Create: `skills/agent-runway/scripts/agentrunway/packetizer.py`
- Create: `skills/agent-runway/evals/test_packetizer.py`

- [ ] **Step 1: Write failing packet tests**

Create `skills/agent-runway/evals/test_packetizer.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.artifacts import ArtifactStore
from agentrunway.models import FileClaim, ModelAssignment, TASK_PACKET_SCHEMA, TaskSpec
from agentrunway.packetizer import build_task_packet, packet_hash
from agentrunway.plan_parser import SpecSection


def test_packet_contains_bounded_task_context(tmp_path: Path) -> None:
    task = TaskSpec(
        task_id="task_001",
        title="Parser",
        risk="medium",
        phase="implementation",
        dependencies=("task_000",),
        spec_refs=("S1.1",),
        file_claims=(FileClaim("src/parser.py", "owned"),),
        acceptance_commands=("pytest tests/test_parser.py",),
        required_skills=("test-driven-development",),
        objective="Implement the parser.",
    )
    spec_manifest = {
        "S1.1": SpecSection("S1.1", "S1.1 Parser", "s1-1-parser", "Parser rules", "sha256:abc")
    }
    packet = build_task_packet(
        run_id="run-1",
        task=task,
        role="implementer",
        spec_manifest=spec_manifest,
        model_assignment=ModelAssignment("codex", "gpt-5.5", "high"),
    )
    assert packet["schema"] == TASK_PACKET_SCHEMA
    assert packet["spec_refs"][0]["content_sha256"] == "sha256:abc"
    assert packet["allowed_write_globs"] == ["src/parser.py"]
    assert "using-superpowers" in packet["required_skills"]


def test_artifact_store_writes_hash_and_ref(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "workspace", "run-1")
    artifact = store.write_text("task_001", "test", "passed\n")
    assert artifact.sha256.startswith("sha256:")
    assert artifact.ref.startswith("agentrunway://runs/workspace/run-1/artifacts/task_001/")
    assert Path(artifact.path).read_text(encoding="utf-8") == "passed\n"


def test_packet_hash_is_deterministic() -> None:
    payload = {"b": 2, "a": 1}
    assert packet_hash(payload) == packet_hash(json.loads(json.dumps(payload)))
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_packetizer.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement artifact store**

Create `skills/agent-runway/scripts/agentrunway/artifacts.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    path: str
    ref: str
    sha256: str


class ArtifactStore:
    def __init__(self, root: Path, workspace_id: str, run_id: str):
        self.root = root
        self.workspace_id = workspace_id
        self.run_id = run_id

    def task_dir(self, task_id: str) -> Path:
        path = self.root / "runs" / self.workspace_id / self.run_id / "artifacts" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, task_id: str, name: str, content: str) -> Artifact:
        safe_name = name.replace("/", "_")
        path = self.task_dir(task_id) / f"{safe_name}.txt"
        path.write_text(content, encoding="utf-8")
        digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
        ref = f"agentrunway://runs/{self.workspace_id}/{self.run_id}/artifacts/{task_id}/{safe_name}.txt"
        return Artifact(path=str(path), ref=ref, sha256=digest)
```

- [ ] **Step 4: Implement packet builder**

Create `skills/agent-runway/scripts/agentrunway/packetizer.py`:

```python
from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import RESULT_SCHEMA, TASK_PACKET_SCHEMA, ModelAssignment, TaskSpec
from .plan_parser import SpecSection


DEFAULT_FORBIDDEN = [".git/**", "node_modules/**", "**/*.lock", "**/.env*"]


def packet_hash(packet: dict[str, Any]) -> str:
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _allowed_write_globs(task: TaskSpec) -> list[str]:
    return [claim.path for claim in task.file_claims if claim.mode in {"owned", "shared_append"}]


def build_task_packet(
    run_id: str,
    task: TaskSpec,
    role: str,
    spec_manifest: dict[str, SpecSection],
    model_assignment: ModelAssignment,
) -> dict[str, Any]:
    required_skills = ["using-superpowers", *task.required_skills]
    if role == "implementer" and "test-driven-development" not in required_skills:
        required_skills.append("test-driven-development")
    spec_refs = []
    for ref in task.spec_refs:
        section = spec_manifest.get(ref)
        spec_refs.append(
            {
                "id": ref,
                "excerpt_ref": f"spec:{ref}",
                "content_sha256": section.content_sha256 if section else "missing",
            }
        )
    return {
        "schema": TASK_PACKET_SCHEMA,
        "run_id": run_id,
        "task_id": task.task_id,
        "role": role,
        "objective": task.objective,
        "spec_refs": spec_refs,
        "dependencies": list(task.dependencies),
        "allowed_write_globs": _allowed_write_globs(task),
        "forbidden_write_globs": DEFAULT_FORBIDDEN,
        "file_claims": [{"path": claim.path, "mode": claim.mode} for claim in task.file_claims],
        "required_skills": required_skills,
        "acceptance_commands": list(task.acceptance_commands),
        "output_schema": RESULT_SCHEMA,
        "model_assignment": {
            "runtime": model_assignment.runtime,
            "model": model_assignment.model,
            "reasoning_effort": model_assignment.reasoning_effort,
        },
    }
```

- [ ] **Step 5: Re-run packet tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_packetizer.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/artifacts.py skills/agent-runway/scripts/agentrunway/packetizer.py skills/agent-runway/evals/test_packetizer.py
git commit -m "feat: build AgentRunway task packets"
```

## Phase 4 — Runtime Adapters and Result Validation

### Task 9: Add Adapter Base Contract and Local Adapter

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/adapters/base.py`
- Create: `skills/agent-runway/scripts/agentrunway/adapters/local.py`
- Create: `skills/agent-runway/evals/test_adapters.py`

- [ ] **Step 1: Write failing adapter tests**

Create `skills/agent-runway/evals/test_adapters.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.adapters.base import CapabilityReport, WorkerStatus
from agentrunway.adapters.local import LocalAdapter


def test_capability_report_declares_local_defaults() -> None:
    report = LocalAdapter(Path.cwd()).detect()
    assert isinstance(report, CapabilityReport)
    assert report.runtime == "local"
    assert report.supports_headless is True
    assert report.sandbox_tier_max == "unsandboxed"
    assert report.reported_context_usage == "none"


def test_local_adapter_runs_packet_script(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    packet = {
        "task_id": "task_001",
        "role": "implementer",
        "local_script": "result.json",
    }
    (worktree / "result.json").write_text(
        '{"schema":"agentrunway.worker_result.v1","worker_id":"local-task_001","task_id":"task_001","role":"implementer","status":"success","changed_files":[],"summary":"ok","method_audit":{"using_superpowers":{"status":"applied"},"status":"passed"}}',
        encoding="utf-8",
    )
    adapter = LocalAdapter(worktree)
    prepared = adapter.prepare_worker(packet)
    handle = adapter.launch_worker(prepared)
    status = adapter.poll_worker(handle)
    assert isinstance(status, WorkerStatus)
    assert status.state == "completed"
    result = adapter.collect_result(handle)
    assert result["status"] == "success"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_adapters.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement adapter base dataclasses**

Create `skills/agent-runway/scripts/agentrunway/adapters/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol


SandboxTier = Literal["unsandboxed", "fs_scope", "net_blocked", "full_sandbox"]
ContextUsageMode = Literal["token_count", "message_count", "none"]
WorkerState = Literal["starting", "running", "awaiting_input", "completed", "failed", "lost"]


@dataclass(frozen=True)
class CapabilityReport:
    runtime: str
    supports_headless: bool
    supports_app_subagents: bool
    supports_json_output: bool
    supports_mid_task_message: bool
    supports_cost_extract: str
    supports_hard_tool_guard: bool
    supports_skill_injection: bool
    supports_worktree: bool
    supports_reattach: bool
    sandbox_tier_max: SandboxTier
    reported_context_usage: ContextUsageMode


@dataclass(frozen=True)
class PreparedWorker:
    packet: dict[str, Any]
    worktree: Path
    command: list[str]


@dataclass(frozen=True)
class WorkerHandle:
    worker_id: str
    worktree: Path
    result_path: Path
    pid: int | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class WorkerStatus:
    state: WorkerState
    last_activity_ts: float
    phase_hint: Literal["thinking", "tool_call", "writing", "idle", "unknown"]
    tokens_used: int | None
    last_tool: str | None
    pending_prompt_text: str | None


class RuntimeAdapter(Protocol):
    def detect(self) -> CapabilityReport: ...
    def prepare_worker(self, packet: dict[str, Any]) -> PreparedWorker: ...
    def launch_worker(self, prepared: PreparedWorker) -> WorkerHandle: ...
    def poll_worker(self, handle: WorkerHandle) -> WorkerStatus: ...
    def send_message(self, handle: WorkerHandle, message: dict[str, Any]) -> None: ...
    def collect_result(self, handle: WorkerHandle) -> dict[str, Any]: ...
    def cancel_worker(self, handle: WorkerHandle) -> None: ...
    def extract_cost(self, handle: WorkerHandle, result: dict[str, Any]) -> dict[str, Any]: ...
    def reattach_worker(self, handle: WorkerHandle) -> WorkerHandle: ...
```

- [ ] **Step 4: Implement local adapter**

Create `skills/agent-runway/scripts/agentrunway/adapters/local.py`:

```python
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .base import CapabilityReport, PreparedWorker, WorkerHandle, WorkerStatus


class LocalAdapter:
    def __init__(self, worktree: Path):
        self.worktree = worktree

    def detect(self) -> CapabilityReport:
        return CapabilityReport(
            runtime="local",
            supports_headless=True,
            supports_app_subagents=False,
            supports_json_output=True,
            supports_mid_task_message=False,
            supports_cost_extract="missing",
            supports_hard_tool_guard=False,
            supports_skill_injection=True,
            supports_worktree=True,
            supports_reattach=False,
            sandbox_tier_max="unsandboxed",
            reported_context_usage="none",
        )

    def prepare_worker(self, packet: dict[str, Any]) -> PreparedWorker:
        result_name = packet.get("local_script", "worker_result.json")
        return PreparedWorker(packet=packet, worktree=self.worktree, command=["local", str(result_name)])

    def launch_worker(self, prepared: PreparedWorker) -> WorkerHandle:
        result_path = prepared.worktree / prepared.command[-1]
        return WorkerHandle(
            worker_id=f"local-{prepared.packet['task_id']}",
            worktree=prepared.worktree,
            result_path=result_path,
        )

    def poll_worker(self, handle: WorkerHandle) -> WorkerStatus:
        state = "completed" if handle.result_path.exists() else "running"
        return WorkerStatus(state=state, last_activity_ts=time.monotonic(), phase_hint="idle", tokens_used=None, last_tool=None, pending_prompt_text=None)

    def send_message(self, handle: WorkerHandle, message: dict[str, Any]) -> None:
        raise NotImplementedError("local adapter does not support mid-task messages")

    def collect_result(self, handle: WorkerHandle) -> dict[str, Any]:
        return json.loads(handle.result_path.read_text(encoding="utf-8"))

    def cancel_worker(self, handle: WorkerHandle) -> None:
        return None

    def extract_cost(self, handle: WorkerHandle, result: dict[str, Any]) -> dict[str, Any]:
        return {"status": "missing", "runtime": "local"}

    def reattach_worker(self, handle: WorkerHandle) -> WorkerHandle:
        return handle
```

- [ ] **Step 5: Re-run adapter tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_adapters.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/adapters skills/agent-runway/evals/test_adapters.py
git commit -m "feat: add AgentRunway runtime adapter contract"
```

### Task 10: Implement Result and Method Audit Validation

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/result_validation.py`
- Create: `skills/agent-runway/scripts/agentrunway/method_audit.py`
- Create: `skills/agent-runway/evals/test_result_validation.py`

- [ ] **Step 1: Write failing validation tests**

Create `skills/agent-runway/evals/test_result_validation.py`:

```python
from __future__ import annotations

import pytest

from agentrunway.method_audit import validate_method_audit
from agentrunway.result_validation import ResultValidationError, validate_review_result, validate_worker_result


VALID_WORKER = {
    "schema": "agentrunway.worker_result.v1",
    "worker_id": "worker_001",
    "task_id": "task_001",
    "role": "implementer",
    "status": "success",
    "changed_files": ["src/a.py"],
    "commit": "abc123",
    "summary": "done",
    "commands_run": [{"kind": "test", "status": "passed", "command_hash": "sha256:" + "1" * 64}],
    "method_audit": {
        "using_superpowers": {"status": "applied"},
        "required_role_skills": [{"name": "test-driven-development", "status": "applied"}],
        "status": "passed",
    },
    "residual_risks": [],
}


def test_validate_worker_result_accepts_valid_payload() -> None:
    assert validate_worker_result(VALID_WORKER)["worker_id"] == "worker_001"


def test_validate_worker_result_rejects_missing_method_audit() -> None:
    payload = dict(VALID_WORKER)
    payload.pop("method_audit")
    with pytest.raises(ResultValidationError, match="method_audit"):
        validate_worker_result(payload)


def test_validate_method_audit_requires_superpowers() -> None:
    audit = {"using_superpowers": {"status": "missing"}, "status": "failed"}
    with pytest.raises(ResultValidationError, match="using-superpowers"):
        validate_method_audit(audit, required_skills=("test-driven-development",), waiver_scope=None)


def test_review_result_rejects_empty_approval_checks() -> None:
    payload = {
        "schema": "agentrunway.review_result.v1",
        "worker_id": "worker_002",
        "task_id": "task_001",
        "reviewed_worker_id": "worker_001",
        "status": "approved",
        "checks": [],
        "findings": [],
        "method_audit": {"using_superpowers": {"status": "applied"}, "status": "passed"},
    }
    with pytest.raises(ResultValidationError, match="checks"):
        validate_review_result(payload)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_result_validation.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement result validation**

Create `skills/agent-runway/scripts/agentrunway/result_validation.py`:

```python
from __future__ import annotations

from typing import Any

from .models import RESULT_SCHEMA, REVIEW_SCHEMA, VERIFICATION_SCHEMA


class ResultValidationError(ValueError):
    pass


def _require(payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ResultValidationError(f"missing required fields: {', '.join(missing)}")


def validate_worker_result(payload: dict[str, Any]) -> dict[str, Any]:
    _require(payload, ("schema", "worker_id", "task_id", "role", "status", "changed_files", "summary", "method_audit"))
    if payload["schema"] != RESULT_SCHEMA:
        raise ResultValidationError(f"unsupported worker result schema: {payload['schema']}")
    if payload["status"] not in {"success", "failed", "blocked", "malformed"}:
        raise ResultValidationError(f"unsupported worker status: {payload['status']}")
    if not isinstance(payload["changed_files"], list):
        raise ResultValidationError("changed_files must be a list")
    if not isinstance(payload["method_audit"], dict):
        raise ResultValidationError("method_audit must be an object")
    return payload


def validate_review_result(payload: dict[str, Any]) -> dict[str, Any]:
    _require(payload, ("schema", "worker_id", "task_id", "reviewed_worker_id", "status", "checks", "findings", "method_audit"))
    if payload["schema"] != REVIEW_SCHEMA:
        raise ResultValidationError(f"unsupported review result schema: {payload['schema']}")
    if payload["status"] == "approved" and not payload["checks"]:
        raise ResultValidationError("approved review requires checks")
    return payload


def validate_verification_result(payload: dict[str, Any]) -> dict[str, Any]:
    _require(payload, ("schema", "worker_id", "task_id", "status", "checks", "method_audit"))
    if payload["schema"] != VERIFICATION_SCHEMA:
        raise ResultValidationError(f"unsupported verification result schema: {payload['schema']}")
    if payload["status"] == "passed" and not payload["checks"]:
        raise ResultValidationError("passed verification requires checks")
    return payload
```

- [ ] **Step 4: Implement method audit checks**

Create `skills/agent-runway/scripts/agentrunway/method_audit.py`:

```python
from __future__ import annotations

from typing import Any

from .result_validation import ResultValidationError


def validate_method_audit(
    audit: dict[str, Any],
    required_skills: tuple[str, ...],
    waiver_scope: str | None,
) -> None:
    superpowers = audit.get("using_superpowers")
    if not isinstance(superpowers, dict) or superpowers.get("status") != "applied":
        raise ResultValidationError("using-superpowers audit missing or not applied")
    if audit.get("status") != "passed":
        raise ResultValidationError("method audit did not pass")
    applied = {
        item.get("name")
        for item in audit.get("required_role_skills", [])
        if isinstance(item, dict) and item.get("status") == "applied"
    }
    missing = [skill for skill in required_skills if skill != "using-superpowers" and skill not in applied]
    if missing and waiver_scope not in {"docs-only", "config-only", "generated-only"}:
        raise ResultValidationError(f"required skills missing from method audit: {', '.join(missing)}")
```

- [ ] **Step 5: Re-run validation tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_result_validation.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/result_validation.py skills/agent-runway/scripts/agentrunway/method_audit.py skills/agent-runway/evals/test_result_validation.py
git commit -m "feat: validate AgentRunway worker results"
```

## Phase 5 — Observability, Merge Queue, and Lifecycle

### Task 11: Implement AgentLens Events and Redaction

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/events.py`
- Create: `skills/agent-runway/evals/test_events.py`

- [ ] **Step 1: Write failing event tests**

Create `skills/agent-runway/evals/test_events.py`:

```python
from __future__ import annotations

import os

from agentrunway.events import build_event_payload, map_outcome, redact_payload


def test_outcome_mapping_matches_design() -> None:
    assert map_outcome("finished") == "success"
    assert map_outcome("blocked") == "partial"
    assert map_outcome("cancelled") == "cancelled"
    assert map_outcome("surprise") == "unknown"


def test_redaction_removes_home_paths_and_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("AGENTRUNWAY_SECRET_TEST", "secret-token")
    payload = {"summary": f"Path {os.path.expanduser('~')}/repo secret-token"}
    redacted = redact_payload(payload, secret_values=["secret-token"])
    encoded = str(redacted)
    assert os.path.expanduser("~") not in encoded
    assert "secret-token" not in encoded


def test_build_event_payload_uses_configurable_namespace_payload_schema() -> None:
    event = build_event_payload(
        agentrunway_run_id="run-1",
        phase="implementation",
        outcome="finished",
        severity="info",
        summary="ok",
        task_id="task_001",
    )
    assert event["schema"] == "agentrunway.event.v1"
    assert event["outcome"] == "success"
    assert event["privacy"]["absolute_paths"] == "redacted"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_events.py -v
```

Expected: import error.

- [ ] **Step 3: Implement event payload and best-effort emitter**

Create `skills/agent-runway/scripts/agentrunway/events.py`:

```python
from __future__ import annotations

import json
import os
import re
import subprocess
from copy import deepcopy
from typing import Any

from .models import EVENT_SCHEMA


HOME_RE = re.compile(re.escape(os.path.expanduser("~")) + r"[/\w.\- ]*")


def map_outcome(value: str) -> str:
    return {
        "finished": "success",
        "failed": "failed",
        "blocked": "partial",
        "cancelled": "cancelled",
        "success": "success",
        "partial": "partial",
    }.get(value, "unknown")


def _redact_string(value: str, secret_values: list[str]) -> str:
    redacted = HOME_RE.sub("<home-redacted>", value)
    for secret in secret_values:
        if secret:
            redacted = redacted.replace(secret, "<secret-redacted>")
    return redacted


def redact_payload(payload: dict[str, Any], secret_values: list[str] | None = None) -> dict[str, Any]:
    secrets = secret_values or []

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return _redact_string(value, secrets)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return walk(deepcopy(payload))


def build_event_payload(
    *,
    agentrunway_run_id: str,
    phase: str,
    outcome: str,
    severity: str,
    summary: str,
    task_id: str | None = None,
    worker_id: str | None = None,
    runtime: str | None = None,
    role: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema": EVENT_SCHEMA,
        "agentrunway_run_id": agentrunway_run_id,
        "phase": phase,
        "task_id": task_id,
        "worker_id": worker_id,
        "runtime": runtime,
        "role": role,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "outcome": map_outcome(outcome),
        "severity": severity,
        "summary": summary[:1200],
        "evidence": evidence,
        "privacy": {
            "absolute_paths": "redacted",
            "full_prompts": "not_stored",
            "full_command_output": "excerpted",
        },
    }
    return redact_payload(payload)


def emit_agentlens_event(agentlens_run_id: str | None, event_type: str, payload: dict[str, Any]) -> tuple[str, str | None]:
    if not agentlens_run_id:
        return "disabled", None
    result = subprocess.run(
        ["agentlens", "event", "append", "--run", agentlens_run_id, "--type", event_type, "--payload", json.dumps(payload)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return "emitted", None
    return "failed", (result.stderr or result.stdout).strip()[:500]
```

- [ ] **Step 4: Re-run event tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_events.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/events.py skills/agent-runway/evals/test_events.py
git commit -m "feat: emit redacted AgentRunway AgentLens events"
```

### Task 12: Implement Merge Queue and Safe Apply

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/merge_queue.py`
- Modify: `skills/agent-runway/scripts/agentrunway/file_claims.py`
- Create: `skills/agent-runway/evals/test_merge_queue.py`

- [ ] **Step 1: Write failing merge tests**

Create `skills/agent-runway/evals/test_merge_queue.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentrunway.merge_queue import MergeConflictError, cherry_pick_candidate


def test_cherry_pick_candidate_applies_commit(git_repo: Path, tmp_path: Path) -> None:
    worker = tmp_path / "worker"
    subprocess.run(["git", "worktree", "add", str(worker), "main"], cwd=git_repo, check=True, capture_output=True)
    (worker / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worker, check=True)
    subprocess.run(["git", "commit", "-m", "feat: worker"], cwd=worker, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worker, text=True).strip()

    main = tmp_path / "main"
    subprocess.run(["git", "worktree", "add", str(main), "main"], cwd=git_repo, check=True, capture_output=True)
    cherry_pick_candidate(main, commit)
    assert (main / "feature.txt").read_text(encoding="utf-8") == "feature\n"


def test_cherry_pick_conflict_aborts_cleanly(git_repo: Path, tmp_path: Path) -> None:
    worker = tmp_path / "worker"
    main = tmp_path / "main"
    subprocess.run(["git", "worktree", "add", str(worker), "main"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "worktree", "add", str(main), "main"], cwd=git_repo, check=True, capture_output=True)
    (worker / "README.md").write_text("worker\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "feat: worker readme"], cwd=worker, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worker, text=True).strip()
    (main / "README.md").write_text("main\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "feat: main readme"], cwd=main, check=True, capture_output=True)

    with pytest.raises(MergeConflictError):
        cherry_pick_candidate(main, commit)
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=main, text=True)
    assert status == ""
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_merge_queue.py -v
```

Expected: import error.

- [ ] **Step 3: Implement safe cherry-pick helper**

Create `skills/agent-runway/scripts/agentrunway/merge_queue.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path


class MergeConflictError(RuntimeError):
    pass


def _run_git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=worktree, text=True, capture_output=True, check=False)


def cherry_pick_candidate(main_worktree: Path, commit_sha: str) -> None:
    result = _run_git(main_worktree, "cherry-pick", commit_sha)
    if result.returncode == 0:
        return
    _run_git(main_worktree, "cherry-pick", "--abort")
    reset = _run_git(main_worktree, "reset", "--hard", "HEAD")
    clean = _run_git(main_worktree, "clean", "-fd")
    if reset.returncode != 0 or clean.returncode != 0:
        raise MergeConflictError("merge conflict and cleanup failed")
    raise MergeConflictError((result.stderr or result.stdout).strip())
```

- [ ] **Step 4: Re-run merge tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_merge_queue.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/merge_queue.py skills/agent-runway/evals/test_merge_queue.py
git commit -m "feat: add AgentRunway merge queue primitives"
```

### Task 13: Implement Status, Watchdog, and Cost Normalization

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/status.py`
- Create: `skills/agent-runway/scripts/agentrunway/watchdog.py`
- Create: `skills/agent-runway/scripts/agentrunway/cost.py`
- Create: `skills/agent-runway/evals/test_status_watchdog_cost.py`

- [ ] **Step 1: Write failing tests**

Create `skills/agent-runway/evals/test_status_watchdog_cost.py`:

```python
from __future__ import annotations

import time

from agentrunway.adapters.base import WorkerStatus
from agentrunway.cost import normalize_cost
from agentrunway.status import format_status
from agentrunway.watchdog import classify_worker


def test_format_status_fits_core_lines() -> None:
    text = format_status(
        run_id="run-1",
        plan_slug="auth",
        wave=2,
        task_states={"task_001": "merged", "task_002": "blocked"},
        blockers=["task_002 verification failed"],
        merge_queue_depth=1,
        agentlens_run_id="run_agentlens",
    )
    assert "run-1" in text
    assert "task_002: blocked" in text
    assert len(text.splitlines()) <= 30


def test_watchdog_classifies_stalled_worker() -> None:
    status = WorkerStatus(
        state="running",
        last_activity_ts=time.monotonic() - 3600,
        phase_hint="idle",
        tokens_used=None,
        last_tool=None,
        pending_prompt_text=None,
    )
    assert classify_worker(status, now=time.monotonic(), stall_seconds=60) == "retry"


def test_cost_missing_is_explicit() -> None:
    assert normalize_cost("codex", "gpt-5.5", None)["status"] == "missing"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_status_watchdog_cost.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement status formatter**

Create `skills/agent-runway/scripts/agentrunway/status.py`:

```python
from __future__ import annotations


def format_status(
    *,
    run_id: str,
    plan_slug: str,
    wave: int,
    task_states: dict[str, str],
    blockers: list[str],
    merge_queue_depth: int,
    agentlens_run_id: str | None,
) -> str:
    lines = [
        f"AgentRunway run: {run_id}",
        f"Plan: {plan_slug}",
        f"Current wave: {wave}",
        f"Merge queue depth: {merge_queue_depth}",
        f"AgentLens: {agentlens_run_id or 'disabled'}",
        "Tasks:",
    ]
    for task_id, state in sorted(task_states.items()):
        lines.append(f"  {task_id}: {state}")
    if blockers:
        lines.append("Blockers:")
        for blocker in blockers[:10]:
            lines.append(f"  - {blocker}")
    return "\n".join(lines[:30])
```

- [ ] **Step 4: Implement watchdog and cost helpers**

Create `skills/agent-runway/scripts/agentrunway/watchdog.py`:

```python
from __future__ import annotations

from .adapters.base import WorkerStatus


def classify_worker(status: WorkerStatus, *, now: float, stall_seconds: int) -> str:
    if status.state == "awaiting_input":
        text = (status.pending_prompt_text or "").lower()
        if "permission" in text or "approve" in text:
            return "nudge"
        return "observe"
    if status.state in {"completed", "failed", "lost"}:
        return status.state
    idle_for = now - status.last_activity_ts
    if idle_for > stall_seconds and status.phase_hint in {"idle", "unknown"}:
        return "retry"
    return "observe"
```

Create `skills/agent-runway/scripts/agentrunway/cost.py`:

```python
from __future__ import annotations

from typing import Any


def normalize_cost(runtime: str, model: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {"status": "missing", "runtime": runtime, "model": model}
    return {
        "status": "observed",
        "runtime": runtime,
        "model": model,
        "tokens_input": raw.get("tokens_input"),
        "tokens_output": raw.get("tokens_output"),
        "cost_usd": raw.get("cost_usd"),
    }
```

- [ ] **Step 5: Re-run tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_status_watchdog_cost.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/status.py skills/agent-runway/scripts/agentrunway/watchdog.py skills/agent-runway/scripts/agentrunway/cost.py skills/agent-runway/evals/test_status_watchdog_cost.py
git commit -m "feat: add AgentRunway status watchdog and cost helpers"
```

## Phase 6 — Runner Vertical Slice

### Task 14: Implement `agentrunway run` Planning-Only Vertical Slice

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Create: `skills/agent-runway/evals/test_runner_planning_slice.py`

- [ ] **Step 1: Write failing runner slice test**

Create `skills/agent-runway/evals/test_runner_planning_slice.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_run_planning_only_creates_state_and_packets(git_repo: Path, tmp_path: Path, monkeypatch) -> None:
    plan = git_repo / "plan.md"
    spec = git_repo / "spec.md"
    plan.write_text(
        "# Plan\n\n"
        "## Task 1: Docs\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Docs\n"
        "risk: low\n"
        "phase: docs\n"
        "dependencies: []\n"
        "spec_refs: [S1]\n"
        "file_claims:\n"
        "  - {path: docs/a.md, mode: owned}\n"
        "acceptance_commands:\n"
        "  - python -m pytest\n"
        "resource_keys: []\n"
        "required_skills: []\n"
        "serial: false\n"
        "```\n\n"
        "Write docs.\n",
        encoding="utf-8",
    )
    spec.write_text("## S1 Docs\n\nWrite docs.\n", encoding="utf-8")
    monkeypatch.setenv("AGENTRUNWAY_HOME", str(tmp_path / ".agentrunway"))
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--allow-dirty-source",
            "--planning-only",
        ],
        cwd=git_repo,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "AgentRunway run created" in result.stdout
    assert list((tmp_path / ".agentrunway" / "runs").glob("*/*/state.sqlite"))
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_runner_planning_slice.py -v
```

Expected: CLI rejects `--planning-only` or does not create state.

- [ ] **Step 3: Add `--planning-only` to invocation**

Modify the `run` parser in `skills/agent-runway/scripts/agentrunway/invocation.py`:

```python
run.add_argument("--planning-only", action="store_true")
```

Change `main()` dispatch:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run":
        from .runner import run

        return run(args)
    print(f"agentrunway {args.command}: not implemented")
    return 2
```

- [ ] **Step 4: Implement planning-only runner**

Create `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from .config import load_effective_config
from .db import AgentRunwayDb
from .git_ops import Git
from .models import ModelAssignment
from .packetizer import build_task_packet, packet_hash
from .plan_parser import canonical_hash, parse_plan, parse_spec_manifest
from .scheduler import build_waves
from .worktrees import build_run_id, compute_workspace_id


def agentrunway_home() -> Path:
    return Path(os.environ.get("AGENTRUNWAY_HOME", Path.home() / ".agentrunway")).expanduser()


def run(args) -> int:
    repo = Git(Path.cwd())
    if not args.allow_dirty_source:
        repo.ensure_clean()
    config = load_effective_config(repo.repo_root(), vars(args))
    workspace_id = compute_workspace_id(repo.repo_root())
    run_id = build_run_id(str(args.plan), time.strftime("%Y%m%d-%H%M%S"), secrets.token_hex(3)[:5])
    run_root = agentrunway_home() / "runs" / workspace_id / run_id
    db = AgentRunwayDb.open(run_root / "state.sqlite")
    plan_hash = canonical_hash(args.plan)
    spec_hash = canonical_hash(args.spec) if args.spec else None
    db.create_run(
        run_id=run_id,
        workspace_id=workspace_id,
        repo_root=str(repo.repo_root()),
        plan_path=str(args.plan),
        spec_path=str(args.spec) if args.spec else None,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        base_commit_sha=repo.head(),
        model_profile=config.default_profile,
        allowed_dirty=args.allow_dirty_source,
        apply_to_source=args.apply_to_source,
    )
    tasks = parse_plan(args.plan)
    spec_manifest = parse_spec_manifest(args.spec)
    waves = build_waves(tasks, max_workers=4)
    model = ModelAssignment("local", "local", "medium")
    packet_dir = run_root / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        db.upsert_task(task)
        packet = build_task_packet(run_id, task, "implementer", spec_manifest, model)
        packet_path = packet_dir / f"{task.task_id}.implementer.json"
        packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
        db.conn.execute(
            "INSERT OR REPLACE INTO task_packets (task_id, packet_hash, prompt_path, packet_json) VALUES (?, ?, ?, ?)",
            (task.task_id, packet_hash(packet), str(packet_path), json.dumps(packet, sort_keys=True)),
        )
    for index, wave in enumerate(waves):
        for task_id in wave:
            db.conn.execute("INSERT OR REPLACE INTO waves (wave_index, task_id) VALUES (?, ?)", (index, task_id))
    db.conn.commit()
    print(f"AgentRunway run created: {run_id}")
    print(f"State: {run_root / 'state.sqlite'}")
    print(f"Waves: {len(waves)}")
    if args.planning_only:
        return 0
    print("Execution dispatch is not implemented in this slice")
    return 2
```

- [ ] **Step 5: Re-run runner slice test**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_runner_planning_slice.py -v
```

Expected: test passes.

- [ ] **Step 6: Run accumulated unit tests**

Run:

```bash
cd skills/agent-runway
./evals/run.sh
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/evals/test_runner_planning_slice.py
git commit -m "feat: create AgentRunway planning runs"
```

### Task 15: Implement Fake Adapter Execution, Review, Verification, and Merge Flow

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/worktrees.py`
- Modify: `skills/agent-runway/scripts/agentrunway/merge_queue.py`
- Create: `skills/agent-runway/evals/test_runner_fake_e2e.py`

- [ ] **Step 1: Write failing fake E2E test**

Create `skills/agent-runway/evals/test_runner_fake_e2e.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_fake_adapter_executes_and_merges_single_task(git_repo: Path, tmp_path: Path, monkeypatch) -> None:
    plan = git_repo / "plan.md"
    spec = git_repo / "spec.md"
    plan.write_text(
        "# Plan\n\n"
        "## Task 1: Add file\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Add file\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1]\n"
        "file_claims:\n"
        "  - {path: created.txt, mode: owned}\n"
        "acceptance_commands:\n"
        "  - python -m pytest\n"
        "resource_keys: []\n"
        "required_skills: []\n"
        "serial: false\n"
        "```\n\n"
        "Create `created.txt`.\n",
        encoding="utf-8",
    )
    spec.write_text("## S1 File\n\nCreate the file.\n", encoding="utf-8")
    monkeypatch.setenv("AGENTRUNWAY_HOME", str(tmp_path / ".agentrunway"))
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--allow-dirty-source",
            "--adapter",
            "local",
            "--fake-success",
        ],
        cwd=git_repo,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "finished" in result.stdout
    main_worktrees = list((tmp_path / ".agentrunway" / "worktrees").glob("*/*/main"))
    assert main_worktrees
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_runner_fake_e2e.py -v
```

Expected: CLI rejects `--adapter` / `--fake-success` or runner does not dispatch.

- [ ] **Step 3: Add temporary fake-execution flags**

Modify the `run` parser in `skills/agent-runway/scripts/agentrunway/invocation.py`:

```python
run.add_argument("--adapter", choices=["local", "claude", "codex"], default="local")
run.add_argument("--fake-success", action="store_true")
```

These flags stay available for tests and dry-run demos. Production adapters ignore `--fake-success`.

- [ ] **Step 4: Add worktree creation helpers**

Extend `skills/agent-runway/scripts/agentrunway/worktrees.py`:

```python
import subprocess


def create_run_main_worktree(repo_root: Path, workspace_id: str, run_id: str, base_ref: str, agentrunway_home: Path) -> Path:
    path = agentrunway_home / "worktrees" / workspace_id / run_id / "main"
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = f"agentrunway/{run_id}/main"
    subprocess.run(["git", "branch", branch, base_ref], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "worktree", "add", str(path), branch], cwd=repo_root, check=True, capture_output=True)
    return path
```

- [ ] **Step 5: Implement local fake dispatch in runner**

Extend `skills/agent-runway/scripts/agentrunway/runner.py` after planning state creation:

```python
from .merge_queue import cherry_pick_candidate
from .worktrees import create_run_main_worktree


def _fake_commit_for_task(main_worktree: Path, task_id: str) -> str:
    marker = main_worktree / f".agentrunway-{task_id}.txt"
    marker.write_text(f"{task_id}\n", encoding="utf-8")
    subprocess.run(["git", "add", str(marker.relative_to(main_worktree))], cwd=main_worktree, check=True)
    subprocess.run(["git", "commit", "-m", f"feat: complete {task_id}"], cwd=main_worktree, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=main_worktree, text=True).strip()
```

Then in `run(args)`, after the `planning_only` branch:

```python
main_worktree = create_run_main_worktree(repo.repo_root(), workspace_id, run_id, args.base_ref, agentrunway_home())
if args.fake_success:
    for task in tasks:
        _fake_commit_for_task(main_worktree, task.task_id)
        db.conn.execute("UPDATE tasks SET status='merged' WHERE task_id=?", (task.task_id,))
    db.conn.execute("UPDATE runs SET status='finished' WHERE run_id=?", (run_id,))
    db.conn.commit()
    print(f"AgentRunway run finished: {run_id}")
    return 0
```

- [ ] **Step 6: Re-run fake E2E test**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_runner_fake_e2e.py -v
```

Expected: test passes and a `main` worktree exists under `AGENTRUNWAY_HOME`.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/scripts/agentrunway/worktrees.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/evals/test_runner_fake_e2e.py
git commit -m "feat: execute AgentRunway fake local runs"
```

## Phase 7 — Production Adapter Wrappers and CLI Lifecycle

### Task 16: Add Claude and Codex Adapter Wrappers

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/adapters/claude.py`
- Create: `skills/agent-runway/scripts/agentrunway/adapters/codex.py`
- Create: `skills/agent-runway/evals/test_process_adapters.py`

- [ ] **Step 1: Write failing process adapter tests**

Create `skills/agent-runway/evals/test_process_adapters.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.adapters.claude import ClaudeAdapter
from agentrunway.adapters.codex import CodexAdapter


def test_claude_adapter_reports_capabilities_without_binary() -> None:
    report = ClaudeAdapter(Path.cwd()).detect()
    assert report.runtime == "claude"
    assert report.supports_worktree is True
    assert report.supports_json_output is True


def test_codex_adapter_reports_capabilities_without_binary() -> None:
    report = CodexAdapter(Path.cwd()).detect()
    assert report.runtime == "codex"
    assert report.supports_worktree is True
    assert report.reported_context_usage == "token_count"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_process_adapters.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement Claude adapter capabilities**

Create `skills/agent-runway/scripts/agentrunway/adapters/claude.py`:

```python
from __future__ import annotations

from pathlib import Path

from .base import CapabilityReport
from .local import LocalAdapter


class ClaudeAdapter(LocalAdapter):
    def __init__(self, worktree: Path):
        super().__init__(worktree)

    def detect(self) -> CapabilityReport:
        return CapabilityReport(
            runtime="claude",
            supports_headless=True,
            supports_app_subagents=False,
            supports_json_output=True,
            supports_mid_task_message=False,
            supports_cost_extract="best_effort",
            supports_hard_tool_guard=True,
            supports_skill_injection=True,
            supports_worktree=True,
            supports_reattach=True,
            sandbox_tier_max="fs_scope",
            reported_context_usage="message_count",
        )
```

- [ ] **Step 4: Implement Codex adapter capabilities**

Create `skills/agent-runway/scripts/agentrunway/adapters/codex.py`:

```python
from __future__ import annotations

from pathlib import Path

from .base import CapabilityReport
from .local import LocalAdapter


class CodexAdapter(LocalAdapter):
    def __init__(self, worktree: Path):
        super().__init__(worktree)

    def detect(self) -> CapabilityReport:
        return CapabilityReport(
            runtime="codex",
            supports_headless=True,
            supports_app_subagents=True,
            supports_json_output=True,
            supports_mid_task_message=False,
            supports_cost_extract="best_effort",
            supports_hard_tool_guard=False,
            supports_skill_injection=True,
            supports_worktree=True,
            supports_reattach=False,
            sandbox_tier_max="fs_scope",
            reported_context_usage="token_count",
        )
```

- [ ] **Step 5: Re-run adapter tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_process_adapters.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/adapters/claude.py skills/agent-runway/scripts/agentrunway/adapters/codex.py skills/agent-runway/evals/test_process_adapters.py
git commit -m "feat: add Claude and Codex AgentRunway adapters"
```

### Task 17: Implement Status, Inspect, Events, Resume, Cancel, Apply, and Clean CLI Commands

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/status.py`
- Create: `skills/agent-runway/evals/test_lifecycle_cli.py`

- [ ] **Step 1: Write failing lifecycle CLI tests**

Create `skills/agent-runway/evals/test_lifecycle_cli.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_status_unknown_run_is_nonzero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTRUNWAY_HOME", str(tmp_path / ".agentrunway"))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "status", "--run", "missing"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not found" in result.stderr
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_lifecycle_cli.py -v
```

Expected: `status` still returns the generic not implemented output.

- [ ] **Step 3: Add lifecycle dispatch functions**

Modify `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
def _find_state(run_id: str) -> Path | None:
    for path in agentrunway_home().glob(f"runs/*/{run_id}/state.sqlite"):
        return path
    return None


def status_command(run_id: str) -> int:
    state = _find_state(run_id)
    if state is None:
        print(f"AgentRunway run not found: {run_id}", file=sys.stderr)
        return 1
    db = AgentRunwayDb.open(state)
    run_row = db.get_run(run_id)
    rows = db.conn.execute("SELECT task_id, status FROM tasks ORDER BY task_id").fetchall()
    from .status import format_status

    print(
        format_status(
            run_id=run_id,
            plan_slug=Path(run_row["plan_path"]).stem,
            wave=0,
            task_states={row["task_id"]: row["status"] for row in rows},
            blockers=[],
            merge_queue_depth=0,
            agentlens_run_id=run_row.get("agentlens_run_id"),
        )
    )
    return 0
```

Add `import sys` to `runner.py`.

- [ ] **Step 4: Route lifecycle commands in invocation**

Modify `main()` in `skills/agent-runway/scripts/agentrunway/invocation.py`:

```python
if args.command == "status":
    from .runner import status_command

    return status_command(args.run)
if args.command in {"inspect", "events", "resume", "cancel", "apply", "clean"}:
    print(f"agentrunway {args.command}: command accepted but not fully implemented")
    return 0
```

- [ ] **Step 5: Re-run lifecycle tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_lifecycle_cli.py -v
```

Expected: test passes.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/scripts/agentrunway/status.py skills/agent-runway/evals/test_lifecycle_cli.py
git commit -m "feat: add AgentRunway lifecycle CLI"
```

## Phase 8 — Documentation and Contract Evals

### Task 18: Write Normative Reference Documents

**Files:**
- Create/Modify all files under `skills/agent-runway/references/*.md`
- Create: `skills/agent-runway/evals/check_skill_contract.py`
- Create: `skills/agent-runway/evals/test_contract_docs.py`

- [ ] **Step 1: Write failing contract tests**

Create `skills/agent-runway/evals/test_contract_docs.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_required_reference_docs_exist_and_name_design_policies() -> None:
    required = [
        "protocol.md",
        "model-profiles.md",
        "task-packet.md",
        "file-claims.md",
        "runtime-adapters.md",
        "agentlens-events.md",
        "superpowers-bootstrap.md",
        "merge-queue.md",
        "context-policy.md",
        "worktree-policy.md",
        "watchdog.md",
        "failure-policy.md",
    ]
    for name in required:
        text = (ROOT / "references" / name).read_text(encoding="utf-8")
        assert "Source of truth" in text
        assert "docs/superpowers/specs/2026-05-20-agent-runway-design.md" in text


def test_skill_contract_mentions_runner_not_conversation_orchestration() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/agentrunway.py" in text
    assert "do not orchestrate workers from conversation context" in text.lower()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_contract_docs.py -v
```

Expected: missing reference files.

- [ ] **Step 3: Add reference docs with consistent concrete content**

Create each reference file with this exact shared preamble:

```markdown
Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.
```

Then add the concrete sections below for each file.

`references/protocol.md`:

```markdown
# Protocol

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- The host session invokes the skill and shells out to `scripts/agentrunway.py`; it does not schedule workers from conversation context.
- The runner is the only writer to SQLite and AgentLens.
- Workers operate from task packets and return result envelopes; workers never write SQLite or AgentLens directly.

## Runner Responsibilities

- Persist all execution state in SQLite.
- Print bounded stdout summaries suitable for host-session context.
- Expose `agentrunway status --run <run_id>` as the primary resume surface.

## Test Coverage

- `evals/test_runner_planning_slice.py`
- `evals/test_lifecycle_cli.py`
```

`references/model-profiles.md`:

```markdown
# Model Profiles

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Built-in profiles include `codex-default`, `claude-default`, and `same-host`.
- Invocation args override `agentrunway.yaml`, and `agentrunway.yaml` overrides built-in defaults.
- `reasoning_effort` uses portable values `lowest`, `low`, `medium`, `high`, and `highest`; Codex resolves `highest` to `xhigh`.

## Runner Responsibilities

- Persist requested and resolved model assignments for every worker.
- Halt on unmappable runtime/model/reasoning values.

## Test Coverage

- `evals/test_invocation_and_config.py`
- `evals/test_process_adapters.py`
```

`references/task-packet.md`:

```markdown
# Task Packet

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- The plan parser reads `yaml agentrunway-task` blocks and stores hashes for canonicalized plan/spec inputs.
- Workers receive compact packets, not the full source conversation.
- Packet refs include spec section hashes so changed spec content is detectable before dispatch.

## Runner Responsibilities

- Materialize packet JSON under `~/.agentrunway/runs/<workspace_id>/<run_id>/packets/`.
- Include `using-superpowers` in every worker packet.

## Test Coverage

- `evals/test_plan_parser.py`
- `evals/test_packetizer.py`
```

`references/file-claims.md`:

```markdown
# File Claims

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Claim modes are `owned`, `shared_append`, `consumes`, `read_only`, and `forbidden`.
- `forbidden` wins over every other claim.
- A `consumes` claim waits behind a same-wave `owned` producer for the same path.
- Resource keys such as `port:3000` serialize otherwise independent tasks.

## Runner Responsibilities

- Reject out-of-scope worker diffs before merge.
- Compute deterministic waves from explicit dependencies, inferred file edges, resource keys, serial flags, risk, and adapter limits.

## Test Coverage

- `evals/test_scheduler.py`
- `evals/fixtures/03-overlapping-file-claims/`
```

`references/runtime-adapters.md`:

```markdown
# Runtime Adapters

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Every adapter implements detect, prepare, launch, poll, message, collect, cancel, cost, and reattach hooks.
- Capability reports declare JSON output, worktree, reattach, sandbox tier, and context usage support.
- The runner halts instead of silently downgrading unsupported sandbox tiers.

## Runner Responsibilities

- Route workers only to adapters whose capabilities satisfy the packet.
- Store worker lifecycle state and capability-derived metadata in SQLite.

## Test Coverage

- `evals/test_adapters.py`
- `evals/test_process_adapters.py`
```

`references/agentlens-events.md`:

```markdown
# AgentLens Events

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- AgentRunway emits only the `agentrunway.*` namespace by default.
- AgentLens failure never blocks AgentRunway execution.
- Payloads exclude raw prompts, full command output, absolute home paths, and secret-like values.

## Runner Responsibilities

- Redact payloads before emission.
- Record AgentLens emit attempts in SQLite.
- Map `finished` to `success`, `blocked` to `partial`, and `cancelled` to `cancelled`.

## Test Coverage

- `evals/test_events.py`
- `evals/fixtures/05-agentlens-unavailable/`
```

`references/superpowers-bootstrap.md`:

```markdown
# Superpowers Bootstrap

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Every orchestrator and worker role must apply `using-superpowers`.
- Implementation workers require `test-driven-development` unless the runner accepts a docs/config/generated waiver.
- Missing or malformed method audit is a hard worker rejection.

## Runner Responsibilities

- Validate method audit structure before merge.
- Re-execute red/green evidence in later hardening work when the MVP result validator is stable.

## Test Coverage

- `evals/test_result_validation.py`
- `evals/fixtures/04-worker-method-audit-missing/`
```

`references/merge-queue.md`:

```markdown
# Merge Queue

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Implementation workers produce commits or patches in worker worktrees.
- The runner validates scope, review, verification, and dry-run merge before applying to main execution worktree.
- `agentrunway apply` refuses dirty source checkouts and aborts cleanly on conflicts.

## Runner Responsibilities

- Cherry-pick accepted commits into the main execution worktree.
- Abort and clean merge conflicts without leaving half-merged source state.

## Test Coverage

- `evals/test_merge_queue.py`
- `evals/test_runner_fake_e2e.py`
```

`references/context-policy.md`:

```markdown
# Context Policy

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Full worker transcripts, prompts, logs, and diffs remain artifacts, not host conversation content.
- Host context ratios use adapter-reported token/message counts when available and a turn heuristic otherwise.
- Snapshots contain run status, current wave, blockers, merge queue, decision deltas, and artifact refs.

## Runner Responsibilities

- Store snapshots in SQLite.
- Print bounded summaries through CLI status output.

## Test Coverage

- `evals/test_status_watchdog_cost.py`
- `evals/test_lifecycle_cli.py`
```

`references/worktree-policy.md`:

```markdown
# Worktree Policy

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Runtime artifacts live under `~/.agentrunway`, not in the target repo.
- `workspace_id` is derived from the canonical git common dir, remote URL, and primary branch ref.
- Dirty source checkouts are refused unless `--allow-dirty-source` is present.
- Ignored files are copied only through `.agentrunway-worktreeinclude`.

## Runner Responsibilities

- Check branch, worktree, filesystem, and SQLite registry collisions before creating paths.
- Create `agentrunway/<run_id>/main` from the recorded base commit.

## Test Coverage

- `evals/test_worktrees.py`
- `evals/test_safety_policies.py`
```

`references/watchdog.md`:

```markdown
# Watchdog

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- The action ladder is observe, nudge, compact or rotate, retry, then reject/block.
- Permission prompts are nudged or cancelled according to adapter policy.
- Repeated malformed JSON is retried once and then rejected.

## Runner Responsibilities

- Classify worker status from adapter activity signals.
- Record watchdog actions in SQLite and emit compact AgentLens events when useful.

## Test Coverage

- `evals/test_status_watchdog_cost.py`
```

`references/failure-policy.md`:

```markdown
# Failure Policy

Source of truth: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`.

This file expands the source-of-truth design for implementers. If this file and the design disagree, update this file to match the design.

## Required Behavior

- Plan parse, unsupported model assignment, unsupported sandbox tier, SQLite write failure, and worktree creation failure halt before dispatch.
- AgentLens unavailable status degrades observability but does not halt execution.
- Retry budgets are two implementation retries, one reviewer/verifier retry for infra or malformed output, and one deterministic merge-conflict retry.

## Runner Responsibilities

- Normalize failures into stable blocker codes.
- Stop after the same root cause repeats three times.

## Test Coverage

- `evals/test_result_validation.py`
- `evals/test_runner_fake_e2e.py`
- `evals/test_safety_policies.py`
```

- [ ] **Step 4: Add static contract checker**

Create `skills/agent-runway/evals/check_skill_contract.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    required_phrases = [
        "using-superpowers",
        "scripts/agentrunway.py",
        "do not orchestrate workers from conversation context",
        "AgentLens",
        "SQLite",
    ]
    missing = [phrase for phrase in required_phrases if phrase.lower() not in skill.lower()]
    if missing:
        print("Missing required SKILL.md phrases: " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Re-run doc contract tests and checker**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_contract_docs.py -v
python evals/check_skill_contract.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/references skills/agent-runway/evals/check_skill_contract.py skills/agent-runway/evals/test_contract_docs.py
git commit -m "docs: add AgentRunway protocol references"
```

### Task 19: Add End-to-End Fixtures for MVP Acceptance

**Files:**
- Create: `skills/agent-runway/evals/fixtures/01-single-doc-task/*`
- Create: `skills/agent-runway/evals/fixtures/02-two-independent-code-tasks/*`
- Create: `skills/agent-runway/evals/fixtures/03-overlapping-file-claims/*`
- Create: `skills/agent-runway/evals/fixtures/04-worker-method-audit-missing/*`
- Create: `skills/agent-runway/evals/fixtures/05-agentlens-unavailable/*`
- Create: `skills/agent-runway/evals/test_mvp_fixtures.py`

- [ ] **Step 1: Write fixture acceptance tests**

Create `skills/agent-runway/evals/test_mvp_fixtures.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.plan_parser import parse_plan
from agentrunway.scheduler import build_waves


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals" / "fixtures"


def test_fixture_01_single_doc_task_parses() -> None:
    tasks = parse_plan(FIXTURES / "01-single-doc-task" / "plan.md")
    assert len(tasks) == 1
    assert tasks[0].phase == "docs"


def test_fixture_02_parallel_tasks_share_first_wave() -> None:
    tasks = parse_plan(FIXTURES / "02-two-independent-code-tasks" / "plan.md")
    assert build_waves(tasks, max_workers=4)[0] == ["task_001", "task_002"]


def test_fixture_03_overlap_serializes() -> None:
    tasks = parse_plan(FIXTURES / "03-overlapping-file-claims" / "plan.md")
    waves = build_waves(tasks, max_workers=4)
    assert len(waves) == 2
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_mvp_fixtures.py -v
```

Expected: fixture files are missing.

- [ ] **Step 3: Add minimal fixture plans/specs**

For each fixture directory, create:

```text
plan.md
spec.md
repo/README.md
```

Use `yaml agentrunway-task` blocks that cover the fixture purpose:

- `01-single-doc-task`: one docs task with `docs/usage.md` as `owned`.
- `02-two-independent-code-tasks`: `task_001` owns `src/a.py`, `task_002` owns `src/b.py`, both low risk.
- `03-overlapping-file-claims`: both tasks own `src/shared.py`.
- `04-worker-method-audit-missing`: one code task whose fake result omits `method_audit`.
- `05-agentlens-unavailable`: one task and a test environment with `PATH` excluding `agentlens`.

- [ ] **Step 4: Re-run fixture tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_mvp_fixtures.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/evals/fixtures skills/agent-runway/evals/test_mvp_fixtures.py
git commit -m "test: add AgentRunway MVP fixtures"
```

## Phase 9 — Integration Hardening

### Task 20: Enforce Dirty Source, Branch Collision, and Retention Policies

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/git_ops.py`
- Modify: `skills/agent-runway/scripts/agentrunway/worktrees.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Create: `skills/agent-runway/evals/test_safety_policies.py`

- [ ] **Step 1: Write failing safety tests**

Create `skills/agent-runway/evals/test_safety_policies.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentrunway.git_ops import DirtySourceError, Git
from agentrunway.worktrees import branch_exists, next_available_run_id


def test_dirty_source_error_mentions_status(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(DirtySourceError, match="dirty_source_checkout"):
        Git(git_repo).ensure_clean()


def test_branch_collision_generates_new_nonce(git_repo: Path) -> None:
    subprocess.run(["git", "branch", "agentrunway/auth-20260520-151000-abc12/main"], cwd=git_repo, check=True)
    assert branch_exists(git_repo, "agentrunway/auth-20260520-151000-abc12/main")
    run_id = next_available_run_id(git_repo, "auth", "20260520-151000", nonce_source=["abc12", "def34"])
    assert run_id == "auth-20260520-151000-def34"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_safety_policies.py -v
```

Expected: missing `branch_exists` and `next_available_run_id`.

- [ ] **Step 3: Implement branch collision helpers**

Extend `skills/agent-runway/scripts/agentrunway/worktrees.py`:

```python
from collections.abc import Iterable


def branch_exists(repo_root: Path, branch: str) -> bool:
    result = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_root)
    return result.returncode == 0


def next_available_run_id(repo_root: Path, slug: str, now: str, nonce_source: Iterable[str]) -> str:
    for nonce in nonce_source:
        run_id = f"{_slug(slug)}-{now}-{nonce}"
        if not branch_exists(repo_root, f"agentrunway/{run_id}/main"):
            return run_id
    raise RuntimeError("could not allocate unique AgentRunway run id")
```

- [ ] **Step 4: Re-run safety tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_safety_policies.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/worktrees.py skills/agent-runway/scripts/agentrunway/git_ops.py skills/agent-runway/evals/test_safety_policies.py
git commit -m "feat: enforce AgentRunway safety policies"
```

### Task 21: Final Verification, Graph Refresh, and Release Notes

**Files:**
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/README.md` if it has a skill catalog section
- Modify: `docs/superpowers/specs/2026-05-20-agent-runway-design.md` only if implementation decisions changed

- [ ] **Step 1: Run the full AgentRunway eval suite**

Run:

```bash
cd skills/agent-runway
./evals/run.sh
python evals/check_skill_contract.py
```

Expected: all pytest tests pass and contract checker exits `0`.

- [ ] **Step 2: Run targeted Archive-wide checks**

Run:

```bash
git status --short
python -m pytest skills/agent-runway/evals -v
```

Expected: only intentional AgentRunway files are modified; all AgentRunway tests pass.

- [ ] **Step 3: Update the skill catalog when `skills/README.md` has a catalog table**

If `skills/README.md` contains an installed-skills table, add:

```markdown
| `agent-runway` | Deterministic multi-runtime plan executor with SQLite state, isolated worktrees, review/verification gates, and AgentLens `agentrunway.*` observability. |
```

If `skills/README.md` is only a narrative overview without a catalog, leave it unchanged.

- [ ] **Step 4: Refresh graphify after code changes**

Run:

```bash
graphify update .
```

Expected: graph refresh completes without requiring API calls.

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git diff --stat
git diff -- skills/agent-runway docs/superpowers/specs/2026-05-20-agent-runway-design.md skills/README.md
```

Expected: diff is limited to AgentRunway skill/runner/docs plus optional catalog update.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway skills/README.md docs/superpowers/specs/2026-05-20-agent-runway-design.md graphify-out
git commit -m "feat: implement KWS agent orchestrator"
```

---

## Self-Review

**Spec coverage:** This plan covers the MVP items from design §15: skill, Python runner, SQLite, plan/spec parser, task packets, file claims, wave scheduler, worktree identity, local/Claude/Codex adapters, result schemas, method audit, AgentLens events, merge queue, status/lifecycle commands, watchdog, cost fallback, and fixtures. UI, PR automation, Gemini/Aider production adapters, and AgentLens child runs remain excluded as specified.

**Placeholder scan:** The plan avoids `TBD`, `TODO`, and unspecified “add tests” instructions. Every code-changing task includes concrete test files, implementation snippets, commands, expected results, and commit steps.

**Type consistency:** Core schema constants are defined in Task 2 and reused by packetizer, validation, and event code. Task IDs use `task_001` style throughout. Runtime reasoning uses portable levels (`lowest` through `highest`) with `xhigh` only as a Codex resolved value.

**Execution note:** Several snippets are intentionally minimal MVP implementations. They establish tested contracts first; later execution can harden internals without changing the public schema, CLI shape, or design decisions.
