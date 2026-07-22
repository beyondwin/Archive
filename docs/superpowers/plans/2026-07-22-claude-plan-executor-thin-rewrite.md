# KWS Claude Plan Executor (CLPE) Thin Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fat `skills/kws-claude-multi-agent-executor` v3 orchestrator with a thin ~400-line launcher `skills/kws-claude-plan-executor` that creates a worktree, launches a headless child Claude session into Superpowers, fail-closed validates the submitted result, and delegates resume to Claude's session store.

**Architecture:** Single stdlib Python script `scripts/clpe.py` with three subcommands (`run` / `resume` / `inspect`). The child `claude -p --output-format stream-json` session owns ALL workflow semantics (task selection, review, retries, subagents); CLPE only maintains the execution environment and verifies submitted facts via git gates. Deterministic evals use a fake `claude` binary on PATH.

**Tech Stack:** Python 3 standard library only, git, bash (evals), `claude` CLI at runtime (never in evals).

**Spec:** `docs/superpowers/specs/2026-07-22-claude-plan-executor-thin-rewrite-design.md` (읽고 시작할 것 — §5 런칭 계약, §6 게이트, §7 분류표가 코드의 근거)

## Global Constraints

- Python 3 표준 라이브러리만. 서드파티 의존성 금지.
- Evals는 순차·네트워크 없음·자격증명 없음·모델 없음. 실제 `claude` 호출 금지 (Task 10의 1회 실측 제외).
- 종료 코드 계약: `completed` 0, `failed` 1, `blocked` 2, `resumable` 3.
- env 스크럽 대상(정확히): `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_ENTRYPOINT` + 접미사 `_API_KEY`/`_TOKEN`/`_SECRET` (단 `ANTHROPIC_` 접두 변수는 보존).
- deny 규칙(정확히): `Bash(git push*)`, `Bash(git merge*)`, `Bash(rm -rf /*)`, `Bash(git reset --hard origin*)`.
- `--bare` 절대 사용 금지 (자식이 Superpowers를 자동 로드해야 함).
- 상태는 `$CLPE_HOME`(기본 `~/.claude`) 아래 `clpe/<run-id>/`, 워크트리는 `worktrees/<run-id>/`. 소스 레포 안에 쓰지 않는다.
- 커밋은 Archive 레포(`/Users/kws/source/private/Archive`)에서 수행. 모든 경로는 레포 루트 기준.
- Superpowers 업스트림 수정 금지. Waygent 소유권 재정의 금지 (skills/AGENTS.md).

**작업 디렉터리:** 모든 태스크는 `/Users/kws/source/private/Archive`에서 수행한다. 새 스킬 루트는 `skills/kws-claude-plan-executor/`이다.

---

### Task 1: Skeleton, result schema, shape validation

**Files:**
- Create: `skills/kws-claude-plan-executor/templates/plan-result.schema.json`
- Create: `skills/kws-claude-plan-executor/scripts/clpe.py`
- Create: `skills/kws-claude-plan-executor/evals/check_units.py`
- Create: `skills/kws-claude-plan-executor/evals/run.sh`

**Interfaces:**
- Produces: `clpe.validate_result_shape(obj) -> list[str]` (빈 리스트 = 통과), 상수 `SCHEMA_PATH`, `EXIT_COMPLETED/EXIT_FAILED/EXIT_BLOCKED/EXIT_RESUMABLE = 0/1/2/3`, `DENY_TOOLS`, `SCRUB_EXACT`, `SCRUB_SUFFIXES`, `MAX_LAUNCHES = 5`, `DEFAULT_TIMEOUT_SECONDS = 3600`, `PROVIDER_BLOCKED` dict.

- [ ] **Step 1: Write the failing test**

`skills/kws-claude-plan-executor/evals/check_units.py`:

```python
#!/usr/bin/env python3
"""Unit evals for clpe.py pure functions."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import clpe


class SchemaFileTest(unittest.TestCase):
    def test_schema_is_valid_json_with_status_enum(self):
        schema = json.loads(clpe.SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["status"]["enum"],
            ["completed", "blocked", "failed"],
        )
        self.assertEqual(
            sorted(schema["required"]),
            ["head_commit", "open_findings", "status", "summary"],
        )


class ResultShapeTest(unittest.TestCase):
    def completed(self):
        return {
            "status": "completed",
            "head_commit": "a" * 40,
            "summary": "done",
            "open_findings": [],
        }

    def test_completed_shape_passes(self):
        self.assertEqual(clpe.validate_result_shape(self.completed()), [])

    def test_non_dict_rejected(self):
        self.assertTrue(clpe.validate_result_shape(["x"]))
        self.assertTrue(clpe.validate_result_shape(None))

    def test_missing_fields_reported(self):
        errors = clpe.validate_result_shape({"status": "completed"})
        self.assertTrue(any("head_commit" in e for e in errors))
        self.assertTrue(any("summary" in e for e in errors))
        self.assertTrue(any("open_findings" in e for e in errors))

    def test_bad_status_and_sha_rejected(self):
        record = self.completed()
        record["status"] = "done"
        record["head_commit"] = "not-a-sha"
        errors = clpe.validate_result_shape(record)
        self.assertTrue(any("status" in e for e in errors))
        self.assertTrue(any("head_commit" in e for e in errors))

    def test_blocked_requires_blocker(self):
        record = self.completed()
        record["status"] = "blocked"
        errors = clpe.validate_result_shape(record)
        self.assertTrue(any("blocker" in e for e in errors))
        record["blocker"] = {"kind": "env", "detail": "docker missing"}
        self.assertEqual(clpe.validate_result_shape(record), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

`skills/kws-claude-plan-executor/evals/run.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/check_units.py"
echo "PASS check_units.py"
echo "1 suite passed"
```

Run: `chmod +x skills/kws-claude-plan-executor/evals/run.sh`

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'clpe'`

- [ ] **Step 3: Write schema + clpe.py constants and validate_result_shape**

`skills/kws-claude-plan-executor/templates/plan-result.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "CLPE plan result",
  "type": "object",
  "additionalProperties": false,
  "required": ["status", "head_commit", "summary", "open_findings"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["completed", "blocked", "failed"]
    },
    "head_commit": {
      "type": "string",
      "pattern": "^[0-9a-f]{7,40}$"
    },
    "summary": {
      "type": "string",
      "minLength": 1
    },
    "open_findings": {
      "type": "array",
      "items": {"type": "string"}
    },
    "blocker": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "detail"],
      "properties": {
        "kind": {"type": "string", "minLength": 1},
        "detail": {"type": "string", "minLength": 1}
      }
    }
  }
}
```

`skills/kws-claude-plan-executor/scripts/clpe.py`:

```python
#!/usr/bin/env python3
"""CLPE - thin Claude plan executor: run / resume / inspect.

CLPE maintains one execution environment and verifies submitted facts.
The child Claude session's Superpowers owns all workflow semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_ROOT / "templates" / "plan-result.schema.json"

SCRUB_EXACT = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT")
SCRUB_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
DENY_TOOLS = (
    "Bash(git push*)",
    "Bash(git merge*)",
    "Bash(rm -rf /*)",
    "Bash(git reset --hard origin*)",
)
DEFAULT_TIMEOUT_SECONDS = 3600
TIMEOUT_CEILING = 7200
MAX_LAUNCHES = 5

EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_RESUMABLE = 3

PROVIDER_BLOCKED = {
    "rate_limit": "provider_usage_blocked",
    "overloaded": "provider_unavailable",
    "server_error": "provider_unavailable",
    "authentication_failed": "provider_auth_blocked",
    "oauth_org_not_allowed": "provider_auth_blocked",
    "billing_error": "provider_auth_blocked",
}

_SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")


def validate_result_shape(obj):
    """Fail-closed shape check for the child's structured_output."""
    if not isinstance(obj, dict):
        return ["structured_output is not an object"]
    errors = []
    for key in ("status", "head_commit", "summary", "open_findings"):
        if key not in obj:
            errors.append(f"missing field: {key}")
    status = obj.get("status")
    if status not in ("completed", "blocked", "failed"):
        errors.append(f"invalid status: {status!r}")
    head = obj.get("head_commit")
    if not isinstance(head, str) or not _SHA_PATTERN.fullmatch(head):
        errors.append("head_commit is not a git sha")
    summary = obj.get("summary")
    if not isinstance(summary, str) or not summary:
        errors.append("summary is empty")
    findings = obj.get("open_findings")
    if not isinstance(findings, list) or any(
        not isinstance(item, str) for item in (findings or [])
    ):
        errors.append("open_findings is not a list of strings")
    if status == "blocked":
        blocker = obj.get("blocker")
        if (
            not isinstance(blocker, dict)
            or not blocker.get("kind")
            or not blocker.get("detail")
        ):
            errors.append("blocked result requires blocker.kind and blocker.detail")
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: PASS (전 테스트 OK)

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): skeleton, result schema, fail-closed shape validation"
```

---

### Task 2: Stream parsing + verdict classification

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py` (append)
- Modify: `skills/kws-claude-plan-executor/evals/check_units.py` (append)

**Interfaces:**
- Consumes: Task 1 constants (`PROVIDER_BLOCKED`, `EXIT_*`), `validate_result_shape`.
- Produces:
  - `clpe.parse_stream(stream_path: Path) -> tuple[str | None, dict | None, list[str]]` — (session_id, 마지막 result 이벤트, 오류 카테고리 리스트)
  - `@dataclass clpe.Observation(launch_kind: str, result_event: dict | None, session_id: str | None, error_categories: list, gate_failures: list, shape_errors: list)`
  - `@dataclass clpe.Verdict(status: str, exit_code: int, detail: str, resumable: bool)`
  - `clpe.classify(obs: Observation) -> Verdict` — 스펙 §7 분류표 구현.

- [ ] **Step 1: Write the failing test** — `check_units.py`에 append:

```python
import tempfile


class ParseStreamTest(unittest.TestCase):
    def write_stream(self, lines):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        handle.write("\n".join(lines) + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_extracts_session_result_and_categories(self):
        path = self.write_stream([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
            "not json at all",
            json.dumps({"type": "system", "subtype": "api_retry",
                        "session_id": "s1", "error": "rate_limit"}),
            json.dumps({"type": "result", "subtype": "success",
                        "session_id": "s1", "total_cost_usd": 0.01}),
        ])
        session_id, result_event, categories = clpe.parse_stream(path)
        self.assertEqual(session_id, "s1")
        self.assertEqual(result_event["subtype"], "success")
        self.assertEqual(categories, ["rate_limit"])

    def test_missing_file_and_garbage_yield_nothing(self):
        session_id, result_event, categories = clpe.parse_stream(
            Path("/nonexistent/stream.jsonl")
        )
        self.assertIsNone(session_id)
        self.assertIsNone(result_event)
        self.assertEqual(categories, [])
        path = self.write_stream(["garbage", "[1,2]"])
        session_id, result_event, categories = clpe.parse_stream(path)
        self.assertIsNone(session_id)
        self.assertIsNone(result_event)


class ClassifyTest(unittest.TestCase):
    def observe(self, **overrides):
        base = dict(
            launch_kind="exited",
            result_event={"type": "result", "subtype": "success",
                          "structured_output": {"status": "completed"}},
            session_id="s1",
            error_categories=[],
            gate_failures=[],
            shape_errors=[],
        )
        base.update(overrides)
        return clpe.Observation(**base)

    def test_spawn_failed(self):
        verdict = clpe.classify(self.observe(launch_kind="spawn_failed",
                                             result_event=None, session_id=None))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("failed", clpe.EXIT_FAILED))

    def test_timed_out_with_session_is_resumable(self):
        verdict = clpe.classify(self.observe(launch_kind="timed_out",
                                             result_event=None))
        self.assertEqual((verdict.status, verdict.exit_code, verdict.resumable),
                         ("resumable", clpe.EXIT_RESUMABLE, True))

    def test_timed_out_without_session_fails(self):
        verdict = clpe.classify(self.observe(launch_kind="timed_out",
                                             result_event=None, session_id=None))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("failed", clpe.EXIT_FAILED))

    def test_no_result_event_is_invalid(self):
        verdict = clpe.classify(self.observe(result_event=None))
        self.assertEqual(verdict.status, "failed")
        self.assertIn("result_invalid", verdict.detail)

    def test_provider_category_beats_missing_result(self):
        verdict = clpe.classify(self.observe(result_event=None,
                                             error_categories=["rate_limit"]))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("blocked", clpe.EXIT_BLOCKED))
        self.assertEqual(verdict.detail, "provider_usage_blocked")

    def test_auth_category_on_error_subtype(self):
        event = {"type": "result", "subtype": "error_during_execution"}
        verdict = clpe.classify(self.observe(result_event=event,
                                             error_categories=["authentication_failed"]))
        self.assertEqual(verdict.detail, "provider_auth_blocked")
        self.assertEqual(verdict.exit_code, clpe.EXIT_BLOCKED)

    def test_max_turns_and_budget_are_resumable(self):
        for subtype in ("error_max_turns", "error_max_budget_usd"):
            event = {"type": "result", "subtype": subtype}
            verdict = clpe.classify(self.observe(result_event=event))
            self.assertEqual((verdict.status, verdict.exit_code),
                             ("resumable", clpe.EXIT_RESUMABLE), subtype)

    def test_success_without_structured_output_fails(self):
        event = {"type": "result", "subtype": "success"}
        verdict = clpe.classify(self.observe(result_event=event))
        self.assertEqual(verdict.status, "failed")
        self.assertIn("without structured_output", verdict.detail)

    def test_shape_errors_fail(self):
        verdict = clpe.classify(self.observe(shape_errors=["missing field: summary"]))
        self.assertEqual(verdict.status, "failed")

    def test_child_reported_failed(self):
        event = {"type": "result", "subtype": "success",
                 "structured_output": {"status": "failed"}}
        verdict = clpe.classify(self.observe(result_event=event))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("failed", clpe.EXIT_FAILED))

    def test_child_blocked_carries_blocker_kind(self):
        event = {"type": "result", "subtype": "success",
                 "structured_output": {"status": "blocked",
                                       "blocker": {"kind": "env_missing_tool",
                                                   "detail": "x"}}}
        verdict = clpe.classify(self.observe(result_event=event))
        self.assertEqual((verdict.status, verdict.exit_code, verdict.detail),
                         ("blocked", clpe.EXIT_BLOCKED, "env_missing_tool"))

    def test_gate_failures_block_completion(self):
        verdict = clpe.classify(self.observe(gate_failures=["worktree not clean"]))
        self.assertEqual(verdict.status, "failed")
        self.assertIn("completion_gate_failed", verdict.detail)

    def test_clean_completion(self):
        verdict = clpe.classify(self.observe())
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("completed", clpe.EXIT_COMPLETED))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: FAIL — `AttributeError: module 'clpe' has no attribute 'parse_stream'`

- [ ] **Step 3: Implement** — `clpe.py`에 append:

```python
def parse_stream(stream_path):
    """Extract (session_id, last result event, error categories) from stream-json."""
    session_id = None
    result_event = None
    categories = []
    try:
        text = Path(stream_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if session_id is None and isinstance(event.get("session_id"), str):
            session_id = event["session_id"]
        if event.get("type") == "system" and isinstance(event.get("error"), str):
            categories.append(event["error"])
        if event.get("type") == "result":
            result_event = event
    return session_id, result_event, categories


@dataclass
class Observation:
    launch_kind: str  # "exited" | "timed_out" | "spawn_failed"
    result_event: dict | None
    session_id: str | None
    error_categories: list
    gate_failures: list
    shape_errors: list


@dataclass
class Verdict:
    status: str  # completed | failed | blocked | resumable
    exit_code: int
    detail: str
    resumable: bool


def classify(obs):
    """Spec §7 classification table. Fail closed on anything unexpected."""
    if obs.launch_kind == "spawn_failed":
        return Verdict("failed", EXIT_FAILED, "controller_spawn_failed", False)
    if obs.launch_kind == "timed_out":
        if obs.session_id:
            return Verdict("resumable", EXIT_RESUMABLE, "timed_out", True)
        return Verdict("failed", EXIT_FAILED, "timed_out_without_session", False)
    provider = next(
        (PROVIDER_BLOCKED[c] for c in obs.error_categories if c in PROVIDER_BLOCKED),
        None,
    )
    resumable = obs.session_id is not None
    event = obs.result_event
    if event is None:
        if provider:
            return Verdict("blocked", EXIT_BLOCKED, provider, False)
        return Verdict("failed", EXIT_FAILED,
                       "result_invalid: no result event", resumable)
    subtype = event.get("subtype")
    if subtype in ("error_max_turns", "error_max_budget_usd"):
        return Verdict("resumable", EXIT_RESUMABLE, str(subtype), resumable)
    if subtype != "success":
        if provider:
            return Verdict("blocked", EXIT_BLOCKED, provider, False)
        return Verdict("failed", EXIT_FAILED,
                       f"result_invalid: subtype={subtype!r}", resumable)
    structured = event.get("structured_output")
    if not structured:
        return Verdict("failed", EXIT_FAILED,
                       "result_invalid: success without structured_output", resumable)
    if obs.shape_errors:
        return Verdict("failed", EXIT_FAILED,
                       "result_invalid: " + "; ".join(obs.shape_errors), resumable)
    status = structured.get("status")
    if status == "blocked":
        return Verdict("blocked", EXIT_BLOCKED,
                       structured["blocker"]["kind"], False)
    if status == "failed":
        return Verdict("failed", EXIT_FAILED, "child_reported_failed", resumable)
    if obs.gate_failures:
        return Verdict("failed", EXIT_FAILED,
                       "completion_gate_failed: " + "; ".join(obs.gate_failures),
                       resumable)
    return Verdict("completed", EXIT_COMPLETED, "completed", False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): stream-json parsing and spec §7 verdict classification"
```

---

### Task 3: env scrub, child prompt, argv builder

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py` (append)
- Modify: `skills/kws-claude-plan-executor/evals/check_units.py` (append)

**Interfaces:**
- Produces:
  - `clpe.scrub_env(env: dict) -> dict`
  - `clpe.build_prompt(worktree, plan_snapshot, spec_snapshots, starting_commit, branch) -> str`
  - `clpe.RESUME_PROMPT: str`
  - `clpe.build_argv(prompt, model=None, max_turns=None, resume_session=None) -> list[str]`

- [ ] **Step 1: Write the failing test** — `check_units.py`에 append:

```python
class ScrubEnvTest(unittest.TestCase):
    def test_scrubs_nesting_and_secrets_keeps_anthropic_and_path(self):
        env = {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_CHILD_SESSION": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "GITHUB_API_KEY": "x",
            "MY_TOKEN": "x",
            "DB_SECRET": "x",
            "ANTHROPIC_API_KEY": "keep-me",
            "PATH": "/usr/bin",
            "HOME": "/home/u",
        }
        clean = clpe.scrub_env(env)
        for gone in ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
                     "CLAUDE_CODE_ENTRYPOINT", "GITHUB_API_KEY",
                     "MY_TOKEN", "DB_SECRET"):
            self.assertNotIn(gone, clean)
        self.assertEqual(clean["ANTHROPIC_API_KEY"], "keep-me")
        self.assertEqual(clean["PATH"], "/usr/bin")
        self.assertEqual(clean["HOME"], "/home/u")


class PromptTest(unittest.TestCase):
    def test_prompt_contains_facts_delegation_and_prohibitions(self):
        prompt = clpe.build_prompt(
            worktree="/wt", plan_snapshot="/state/inputs/plan-p.md",
            spec_snapshots=["/state/inputs/spec-0-s.md"],
            starting_commit="a" * 40, branch="clpe/run-1",
        )
        for token in (
            "WORKTREE: /wt",
            "PLAN: /state/inputs/plan-p.md",
            "- /state/inputs/spec-0-s.md",
            f"STARTING_COMMIT: {'a' * 40}",
            "BRANCH: clpe/run-1",
            "superpowers:executing-plans",
            "superpowers:subagent-driven-development",
            "Do not merge, push, deploy",
            "Do not ask the user questions",
        ):
            self.assertIn(token, prompt)

    def test_resume_prompt_repeats_schema_contract_and_prohibitions(self):
        self.assertIn("Continue executing the plan", clpe.RESUME_PROMPT)
        self.assertIn("Do not merge, push, deploy", clpe.RESUME_PROMPT)


class ArgvTest(unittest.TestCase):
    def test_base_argv_contract(self):
        argv = clpe.build_argv("PROMPT")
        self.assertEqual(argv[0], "claude")
        self.assertEqual(argv[1:3], ["-p", "PROMPT"])
        self.assertNotIn("--bare", argv)
        self.assertIn("stream-json", argv)
        self.assertIn("--verbose", argv)
        self.assertIn("--json-schema", argv)
        self.assertIn(str(clpe.SCHEMA_PATH), argv)
        self.assertIn("bypassPermissions", argv)
        for rule in clpe.DENY_TOOLS:
            self.assertIn(rule, argv)
        self.assertNotIn("--resume", argv)
        self.assertNotIn("--model", argv)
        self.assertNotIn("--max-turns", argv)

    def test_optional_flags(self):
        argv = clpe.build_argv("P", model="opus", max_turns=80,
                               resume_session="sess-1")
        self.assertIn("--model", argv)
        self.assertIn("opus", argv)
        self.assertIn("--max-turns", argv)
        self.assertIn("80", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "sess-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: FAIL — `AttributeError: module 'clpe' has no attribute 'scrub_env'`

- [ ] **Step 3: Implement** — `clpe.py`에 append:

```python
def scrub_env(env):
    """Remove nesting markers and secret-like vars; keep ANTHROPIC_* auth."""
    clean = {}
    for key, value in env.items():
        if key in SCRUB_EXACT:
            continue
        if not key.startswith("ANTHROPIC_") and key.endswith(SCRUB_SUFFIXES):
            continue
        clean[key] = value
    return clean


_PROHIBITIONS = (
    "Do not merge, push, deploy, or modify files outside WORKTREE.\n"
    "Do not ask the user questions; if blocked, return status \"blocked\" "
    "with a blocker object."
)

_SCHEMA_CONTRACT = (
    "Your FINAL response must be only the JSON object matching the enforced "
    "schema (status / head_commit / summary / open_findings / blocker?)."
)


def build_prompt(worktree, plan_snapshot, spec_snapshots, starting_commit, branch):
    spec_lines = "\n".join(f"- {path}" for path in spec_snapshots)
    return (
        f"WORKTREE: {worktree}\n"
        f"PLAN: {plan_snapshot}\n"
        f"SPECIFICATIONS:\n{spec_lines}\n"
        f"STARTING_COMMIT: {starting_commit}\n"
        f"BRANCH: {branch}\n"
        "\n"
        "Execute the approved implementation plan with Superpowers\n"
        "(superpowers:executing-plans). You may dispatch subagents for\n"
        "independent tasks (superpowers:subagent-driven-development) - that\n"
        "choice is yours. Commit work to the current branch.\n"
        "\n"
        f"{_SCHEMA_CONTRACT}\n"
        "\n"
        f"{_PROHIBITIONS}\n"
    )


RESUME_PROMPT = (
    "Continue executing the plan from where the session left off.\n"
    f"{_SCHEMA_CONTRACT}\n\n{_PROHIBITIONS}\n"
)


def build_argv(prompt, model=None, max_turns=None, resume_session=None):
    argv = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--json-schema", str(SCHEMA_PATH),
        "--permission-mode", "bypassPermissions",
    ]
    for rule in DENY_TOOLS:
        argv.extend(["--disallowedTools", rule])
    if resume_session:
        argv.extend(["--resume", resume_session])
    if model:
        argv.extend(["--model", model])
    if max_turns:
        argv.extend(["--max-turns", str(max_turns)])
    return argv
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): env scrub, child prompt facts, claude argv builder"
```

---

### Task 4: git helpers + completion gates

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py` (append)
- Create: `skills/kws-claude-plan-executor/evals/check_gates.py`
- Modify: `skills/kws-claude-plan-executor/evals/run.sh`

**Interfaces:**
- Produces:
  - `clpe.git(args: list[str], cwd) -> subprocess.CompletedProcess` (capture_output, text)
  - `clpe.completion_gates(structured: dict, worktree: Path, starting_commit: str) -> list[str]` — 스펙 §6 게이트 3~6 (clean / HEAD 일치 / 조상성 / open_findings 빈 목록).

- [ ] **Step 1: Write the failing test**

`skills/kws-claude-plan-executor/evals/check_gates.py`:

```python
#!/usr/bin/env python3
"""Completion-gate evals against a real temp git repo."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import clpe


def run_git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


class CompletionGatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clpe-gates-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-b", "main")
        run_git(self.repo, "config", "user.email", "eval@example.com")
        run_git(self.repo, "config", "user.name", "Eval")
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "seed")
        self.start = self.head()
        (self.repo / "work.txt").write_text("work\n", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "work")

    def head(self):
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.repo),
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def structured(self, **overrides):
        base = {"status": "completed", "head_commit": self.head(),
                "summary": "done", "open_findings": []}
        base.update(overrides)
        return base

    def test_clean_matching_completion_passes(self):
        self.assertEqual(
            clpe.completion_gates(self.structured(), self.repo, self.start), []
        )

    def test_dirty_worktree_fails(self):
        (self.repo / "untracked.txt").write_text("x\n", encoding="utf-8")
        failures = clpe.completion_gates(self.structured(), self.repo, self.start)
        self.assertTrue(any("not clean" in f for f in failures))

    def test_head_mismatch_fails(self):
        failures = clpe.completion_gates(
            self.structured(head_commit="deadbeef" * 5), self.repo, self.start
        )
        self.assertTrue(any("head mismatch" in f for f in failures))

    def test_short_sha_prefix_accepted(self):
        failures = clpe.completion_gates(
            self.structured(head_commit=self.head()[:12]), self.repo, self.start
        )
        self.assertEqual(failures, [])

    def test_broken_ancestry_fails(self):
        failures = clpe.completion_gates(
            self.structured(), self.repo, "0" * 40
        )
        self.assertTrue(any("ancestor" in f for f in failures))

    def test_open_findings_fail(self):
        failures = clpe.completion_gates(
            self.structured(open_findings=["unfixed lint"]), self.repo, self.start
        )
        self.assertTrue(any("open_findings" in f for f in failures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

`evals/run.sh` — `echo "1 suite passed"` 줄을 다음으로 교체:

```bash
python3 "$(dirname "$0")/check_gates.py"
echo "PASS check_gates.py"
echo "2 suites passed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_gates.py`
Expected: FAIL — `AttributeError: module 'clpe' has no attribute 'completion_gates'`

- [ ] **Step 3: Implement** — `clpe.py`에 append:

```python
def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)


def completion_gates(structured, worktree, starting_commit):
    """Spec §6 gates 3-6. Returns [] when the completion may be accepted."""
    status = git(["status", "--porcelain"], worktree)
    if status.returncode != 0:
        return [f"git status failed: {status.stderr.strip()}"]
    failures = []
    if status.stdout.strip():
        failures.append("worktree not clean")
    head = git(["rev-parse", "HEAD"], worktree)
    if head.returncode != 0:
        failures.append("git rev-parse HEAD failed")
        return failures
    observed = head.stdout.strip()
    reported = structured.get("head_commit") or ""
    if not observed.startswith(reported):
        failures.append(f"head mismatch: reported {reported}, observed {observed}")
    ancestor = git(["merge-base", "--is-ancestor", starting_commit, "HEAD"],
                   worktree)
    if ancestor.returncode != 0:
        failures.append("starting commit is not an ancestor of HEAD")
    if structured.get("open_findings"):
        failures.append("open_findings not empty")
    return failures
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 skills/kws-claude-plan-executor/evals/check_gates.py && ./skills/kws-claude-plan-executor/evals/run.sh`
Expected: PASS / `2 suites passed`

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): git completion gates (clean/head/ancestry/findings)"
```

---

### Task 5: run-state store

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py` (append)
- Modify: `skills/kws-claude-plan-executor/evals/check_units.py` (append)

**Interfaces:**
- Produces:
  - `clpe.state_home() -> Path` — `$CLPE_HOME` 우선, 기본 `~/.claude`
  - `clpe.run_dir(run_id) -> Path` (= state_home/clpe/run_id), `clpe.worktree_dir(run_id) -> Path` (= state_home/worktrees/run_id)
  - `clpe.derive_run_id(plan_path) -> str` — `<plan-slug>-<YYYYMMDD-HHMMSS>`
  - `clpe.write_json(path, payload)` — tmp+rename 원자적 쓰기
  - `clpe.save_run(record: dict)`, `clpe.load_run(run_id) -> dict | None`
  - `clpe.snapshot_inputs(rdir: Path, plan: Path, specs: list[Path]) -> tuple[Path, list[Path]]`

- [ ] **Step 1: Write the failing test** — `check_units.py`에 append:

```python
import os


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clpe-state-")
        self.addCleanup(self.temp.cleanup)
        self.old_home = os.environ.get("CLPE_HOME")
        os.environ["CLPE_HOME"] = self.temp.name
        def restore():
            if self.old_home is None:
                os.environ.pop("CLPE_HOME", None)
            else:
                os.environ["CLPE_HOME"] = self.old_home
        self.addCleanup(restore)

    def test_paths_derive_from_clpe_home(self):
        self.assertEqual(clpe.state_home(), Path(self.temp.name))
        self.assertEqual(clpe.run_dir("r1"),
                         Path(self.temp.name) / "clpe" / "r1")
        self.assertEqual(clpe.worktree_dir("r1"),
                         Path(self.temp.name) / "worktrees" / "r1")

    def test_derive_run_id_slugs_plan_name(self):
        run_id = clpe.derive_run_id(Path("/tmp/My Plan v2.md"))
        self.assertRegex(run_id, r"^my-plan-v2-\d{8}-\d{6}$")

    def test_save_and_load_round_trip(self):
        record = {"run_id": "r1", "status": "running", "launches": 0}
        clpe.run_dir("r1").mkdir(parents=True)
        clpe.save_run(record)
        self.assertEqual(clpe.load_run("r1"), record)
        self.assertIsNone(clpe.load_run("missing"))

    def test_snapshot_inputs_copies_plan_and_specs(self):
        base = Path(self.temp.name)
        plan = base / "plan.md"
        plan.write_text("# p\n", encoding="utf-8")
        spec = base / "spec.md"
        spec.write_text("# s\n", encoding="utf-8")
        rdir = clpe.run_dir("r2")
        rdir.mkdir(parents=True)
        plan_copy, spec_copies = clpe.snapshot_inputs(rdir, plan, [spec])
        self.assertEqual(plan_copy, rdir / "inputs" / "plan-plan.md")
        self.assertEqual(spec_copies, [rdir / "inputs" / "spec-0-spec.md"])
        self.assertEqual(plan_copy.read_text(encoding="utf-8"), "# p\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: FAIL — `AttributeError: module 'clpe' has no attribute 'state_home'`

- [ ] **Step 3: Implement** — `clpe.py`에 append:

```python
def state_home():
    return Path(os.environ.get("CLPE_HOME", str(Path.home() / ".claude"))).expanduser()


def run_dir(run_id):
    return state_home() / "clpe" / run_id


def worktree_dir(run_id):
    return state_home() / "worktrees" / run_id


def derive_run_id(plan_path):
    slug = re.sub(r"[^a-z0-9]+", "-", Path(plan_path).stem.lower()).strip("-")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{slug or 'plan'}-{stamp}"


def write_json(path, payload):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def save_run(record):
    write_json(run_dir(record["run_id"]) / "run.json", record)


def load_run(run_id):
    try:
        return json.loads((run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def snapshot_inputs(rdir, plan, specs):
    inputs = Path(rdir) / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    plan_copy = inputs / f"plan-{Path(plan).name}"
    shutil.copy2(plan, plan_copy)
    spec_copies = []
    for index, spec in enumerate(specs):
        copy = inputs / f"spec-{index}-{Path(spec).name}"
        shutil.copy2(spec, copy)
        spec_copies.append(copy)
    return plan_copy, spec_copies
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): run-state store under CLPE_HOME with atomic writes"
```

---

### Task 6: launcher with wall-clock timeout

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py` (append)
- Modify: `skills/kws-claude-plan-executor/evals/check_units.py` (append)

**Interfaces:**
- Produces:
  - `@dataclass clpe.LaunchOutcome(kind: str, exit_code: int | None, detail: str)` — kind ∈ `"exited" | "timed_out" | "spawn_failed"`
  - `clpe.launch(argv, cwd, env, timeout_seconds, stream_path) -> LaunchOutcome` — stdout을 stream_path 파일로, 프로세스 그룹 분리, 타임아웃 시 SIGTERM→10초 유예→SIGKILL.

- [ ] **Step 1: Write the failing test** — `check_units.py`에 append:

```python
class LaunchTest(unittest.TestCase):
    def stream_path(self):
        handle = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_exited_captures_stdout(self):
        path = self.stream_path()
        outcome = clpe.launch(
            [sys.executable, "-c", "print('{\"type\":\"result\"}')"],
            cwd=".", env=dict(os.environ), timeout_seconds=30, stream_path=path,
        )
        self.assertEqual((outcome.kind, outcome.exit_code), ("exited", 0))
        self.assertIn('"result"', path.read_text(encoding="utf-8"))

    def test_timeout_kills_process_group(self):
        path = self.stream_path()
        outcome = clpe.launch(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=".", env=dict(os.environ), timeout_seconds=1, stream_path=path,
        )
        self.assertEqual(outcome.kind, "timed_out")

    def test_spawn_failure(self):
        outcome = clpe.launch(
            ["/nonexistent/claude-binary"],
            cwd=".", env=dict(os.environ), timeout_seconds=5,
            stream_path=self.stream_path(),
        )
        self.assertEqual(outcome.kind, "spawn_failed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: FAIL — `AttributeError: module 'clpe' has no attribute 'launch'`

- [ ] **Step 3: Implement** — `clpe.py`에 append:

```python
@dataclass
class LaunchOutcome:
    kind: str  # "exited" | "timed_out" | "spawn_failed"
    exit_code: int | None
    detail: str


def _kill_group(child, signum):
    try:
        os.killpg(os.getpgid(child.pid), signum)
    except (ProcessLookupError, PermissionError):
        pass


def launch(argv, cwd, env, timeout_seconds, stream_path):
    try:
        stream = open(stream_path, "w", encoding="utf-8")
    except OSError as error:
        return LaunchOutcome("spawn_failed", None, str(error))
    with stream:
        try:
            child = subprocess.Popen(
                argv, cwd=str(cwd), env=env, stdout=stream,
                stderr=subprocess.PIPE, text=True, start_new_session=True,
            )
        except OSError as error:
            return LaunchOutcome("spawn_failed", None, str(error))
        try:
            _, stderr = child.communicate(timeout=timeout_seconds)
            return LaunchOutcome("exited", child.returncode,
                                 (stderr or "").strip()[-2000:])
        except subprocess.TimeoutExpired:
            _kill_group(child, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_group(child, signal.SIGKILL)
                child.wait()
            return LaunchOutcome("timed_out", None,
                                 f"timed out after {timeout_seconds}s")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/kws-claude-plan-executor/evals/check_units.py`
Expected: PASS (timeout 테스트가 ~1초 안에 끝나야 함 — 60초 걸리면 kill 실패)

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): process-group launcher with wall-clock timeout"
```

---

### Task 7: `run` command end-to-end with fake claude

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py` (append)
- Create: `skills/kws-claude-plan-executor/evals/fake_claude.py`
- Create: `skills/kws-claude-plan-executor/evals/check_cli.py`
- Modify: `skills/kws-claude-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: Tasks 1–6 전부.
- Produces:
  - `clpe.execute_cycle(record: dict, resume: bool) -> int` (exit code; run.json 갱신, completed 시 handoff.json)
  - `clpe.cmd_run(args) -> int`
  - fake 계약: fake_claude는 `CLPE_FAKE_SCENARIO` env로 행동 결정, `CLPE_FAKE_ARGV_LOG` 파일에 `{"argv","cwd","env_has_claudecode","env_has_entrypoint"}` JSON 라인 append, stream-json 라인을 stdout에 출력. `--resume` 포함 시 `CLPE_FAKE_RESUME_SCENARIO`로 전환.
  - 타임아웃 하한 완화: `CLPE_TIMEOUT_FLOOR` env (기본 1200; evals 전용 1). run 타임아웃 검증은 `[floor, 7200]`.

- [ ] **Step 1: Write fake_claude.py** (테스트 픽스처 — 먼저 작성)

`skills/kws-claude-plan-executor/evals/fake_claude.py`:

```python
#!/usr/bin/env python3
"""Deterministic claude CLI stand-in for CLPE evals."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time


def emit(event):
    print(json.dumps(event), flush=True)


def run_git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def make_commit():
    with open("clpe-fake-change.txt", "a", encoding="utf-8") as handle:
        handle.write("change\n")
    run_git("add", "-A")
    run_git("commit", "-m", "fake: implement plan")
    return run_git("rev-parse", "HEAD").stdout.strip()


def main():
    argv = sys.argv[1:]
    scenario = os.environ.get("CLPE_FAKE_SCENARIO", "completed")
    if "--resume" in argv:
        scenario = os.environ.get("CLPE_FAKE_RESUME_SCENARIO", scenario)
    log_path = os.environ.get("CLPE_FAKE_ARGV_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(json.dumps({
                "argv": argv,
                "cwd": os.getcwd(),
                "env_has_claudecode": "CLAUDECODE" in os.environ,
                "env_has_entrypoint": "CLAUDE_CODE_ENTRYPOINT" in os.environ,
            }) + "\n")
    if scenario == "invalid":
        print("this is not stream json")
        return 1
    emit({"type": "system", "subtype": "init", "session_id": "sess-0001"})
    if scenario == "timeout":
        time.sleep(int(os.environ.get("CLPE_FAKE_SLEEP", "30")))
        return 0
    result = {"type": "result", "subtype": "success",
              "session_id": "sess-0001", "total_cost_usd": 0.01}
    head = run_git("rev-parse", "HEAD").stdout.strip()
    if scenario in ("completed", "completed_dirty", "completed_wrong_head"):
        head = make_commit()
        if scenario == "completed_dirty":
            with open("untracked.txt", "w", encoding="utf-8") as handle:
                handle.write("dirty\n")
        reported = ("deadbeef" * 5 if scenario == "completed_wrong_head" else head)
        result["structured_output"] = {
            "status": "completed", "head_commit": reported,
            "summary": "plan executed", "open_findings": [],
        }
    elif scenario == "failed":
        result["structured_output"] = {
            "status": "failed", "head_commit": head,
            "summary": "could not finish", "open_findings": ["tests failing"],
        }
    elif scenario == "blocked":
        result["structured_output"] = {
            "status": "blocked", "head_commit": head,
            "summary": "blocked on environment", "open_findings": [],
            "blocker": {"kind": "env_missing_tool", "detail": "docker unavailable"},
        }
    elif scenario == "max_turns":
        result["subtype"] = "error_max_turns"
    elif scenario == "rate_limit":
        emit({"type": "system", "subtype": "api_retry",
              "session_id": "sess-0001", "error": "rate_limit"})
        result["subtype"] = "error_during_execution"
    elif scenario == "auth":
        emit({"type": "system", "subtype": "api_retry",
              "session_id": "sess-0001", "error": "authentication_failed"})
        result["subtype"] = "error_during_execution"
    elif scenario == "success_no_structured":
        pass
    else:
        raise SystemExit(f"unknown scenario: {scenario}")
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing e2e test**

`skills/kws-claude-plan-executor/evals/check_cli.py`:

```python
#!/usr/bin/env python3
"""Public CLI contract evals for clpe.py, driven by fake_claude.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "clpe.py"
FAKE = ROOT / "evals" / "fake_claude.py"


class CliFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clpe-cli-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "eval@example.com")
        self._git("config", "user.name", "Eval")
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "seed")
        self.plan = base / "demo plan.md"
        self.plan.write_text("# plan\n", encoding="utf-8")
        self.spec = base / "spec.md"
        self.spec.write_text("# spec\n", encoding="utf-8")
        self.home = base / "clpe-home"
        fakebin = base / "fakebin"
        fakebin.mkdir()
        wrapper = fakebin / "claude"
        wrapper.write_text(
            f"#!/usr/bin/env bash\nexec {sys.executable} '{FAKE}' \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        self.argv_log = base / "argv.jsonl"
        self.env = dict(os.environ)
        self.env.update({
            "CLPE_HOME": str(self.home),
            "PATH": f"{fakebin}:{self.env['PATH']}",
            "CLPE_FAKE_ARGV_LOG": str(self.argv_log),
            "CLPE_TIMEOUT_FLOOR": "1",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
        })

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=str(self.repo), check=True,
                       capture_output=True, text=True)

    def clpe(self, *extra, scenario="completed", resume_scenario=None,
             fake_sleep=None):
        env = dict(self.env)
        env["CLPE_FAKE_SCENARIO"] = scenario
        if resume_scenario:
            env["CLPE_FAKE_RESUME_SCENARIO"] = resume_scenario
        if fake_sleep:
            env["CLPE_FAKE_SLEEP"] = fake_sleep
        return subprocess.run([sys.executable, str(CLI), *extra],
                              env=env, capture_output=True, text=True)

    def run_plan(self, *extra, **kwargs):
        return self.clpe(
            "run", "--spec", str(self.spec), "--plan", str(self.plan),
            "--workspace", str(self.repo), "--timeout-seconds", "60",
            *extra, **kwargs,
        )

    def only_run_record(self):
        runs = list((self.home / "clpe").glob("*/run.json"))
        self.assertEqual(len(runs), 1)
        return json.loads(runs[0].read_text(encoding="utf-8"))

    def argv_lines(self):
        return [json.loads(line) for line in
                self.argv_log.read_text(encoding="utf-8").splitlines()]


class RunCommandTest(CliFixture):
    def test_completed_run(self):
        result = self.run_plan()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        record = self.only_run_record()
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["session_id"], "sess-0001")
        self.assertEqual(record["launches"], 1)
        self.assertAlmostEqual(record["total_cost_usd"], 0.01)
        handoff = json.loads(
            (self.home / "clpe" / record["run_id"] / "handoff.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(handoff["integration"], "not_observed")
        self.assertEqual(handoff["branch"], f"clpe/{record['run_id']}")

    def test_launch_contract_observed_by_child(self):
        self.run_plan()
        line = self.argv_lines()[0]
        argv = line["argv"]
        self.assertNotIn("--bare", argv)
        self.assertIn("stream-json", argv)
        for rule in ("Bash(git push*)", "Bash(git merge*)",
                     "Bash(rm -rf /*)", "Bash(git reset --hard origin*)"):
            self.assertIn(rule, argv)
        self.assertFalse(line["env_has_claudecode"])
        self.assertFalse(line["env_has_entrypoint"])
        record = self.only_run_record()
        self.assertEqual(line["cwd"], record["worktree"])
        prompt = argv[argv.index("-p") + 1]
        self.assertIn("WORKTREE:", prompt)
        self.assertIn("superpowers:executing-plans", prompt)

    def test_exit_codes_by_scenario(self):
        for scenario, code, status in (
            ("failed", 1, "failed"),
            ("blocked", 2, "blocked"),
            ("success_no_structured", 1, "failed"),
            ("invalid", 1, "failed"),
            ("completed_dirty", 1, "failed"),
            ("completed_wrong_head", 1, "failed"),
            ("max_turns", 3, "resumable"),
            ("rate_limit", 2, "blocked"),
            ("auth", 2, "blocked"),
        ):
            with self.subTest(scenario=scenario):
                fixture = self.__class__("setUp")
                fixture.setUp()
                result = fixture.run_plan(scenario=scenario)
                self.assertEqual(result.returncode, code,
                                 f"{scenario}: {result.stdout}{result.stderr}")
                self.assertEqual(fixture.only_run_record()["status"], status)
                fixture.temp.cleanup()

    def test_dirty_workspace_halts_before_worktree(self):
        (self.repo / "dirty.txt").write_text("x\n", encoding="utf-8")
        result = self.run_plan()
        self.assertEqual(result.returncode, 2)
        self.assertIn("dirty_workspace", result.stdout)
        self.assertFalse((self.home / "worktrees").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

`evals/run.sh` — `echo "2 suites passed"` 줄을 다음으로 교체:

```bash
python3 "$(dirname "$0")/check_cli.py"
echo "PASS check_cli.py"
echo "3 suites passed"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_cli.py`
Expected: FAIL — clpe.py에 서브커맨드가 없어 `argparse` 오류 또는 `cmd_run` 부재

- [ ] **Step 4: Implement** — `clpe.py`에 append (main은 Task 9에서 완성하지만, 여기서 `run`만 있는 최소 argparse를 포함):

```python
def _timeout_floor():
    return int(os.environ.get("CLPE_TIMEOUT_FLOOR", "1200"))


def _halt(reason, detail, exit_code):
    print(json.dumps({"halt": reason, "detail": detail}))
    return exit_code


def execute_cycle(record, resume):
    record["launches"] += 1
    if resume:
        prompt = RESUME_PROMPT
        resume_session = record["session_id"]
    else:
        prompt = build_prompt(record["worktree"], record["plan"],
                              record["specs"], record["starting_commit"],
                              record["branch"])
        resume_session = None
    argv = build_argv(prompt, model=record.get("model"),
                      max_turns=record.get("max_turns"),
                      resume_session=resume_session)
    stream_path = run_dir(record["run_id"]) / f"stream-{record['launches']:02d}.jsonl"
    outcome = launch(argv, cwd=record["worktree"],
                     env=scrub_env(dict(os.environ)),
                     timeout_seconds=record["timeout_seconds"],
                     stream_path=stream_path)
    session_id, result_event, categories = parse_stream(stream_path)
    if session_id:
        record["session_id"] = session_id
    structured = (result_event or {}).get("structured_output")
    shape_errors = validate_result_shape(structured) if structured else []
    gate_failures = []
    if (result_event and result_event.get("subtype") == "success"
            and structured and not shape_errors
            and structured.get("status") == "completed"):
        gate_failures = completion_gates(structured, Path(record["worktree"]),
                                         record["starting_commit"])
    verdict = classify(Observation(
        launch_kind=outcome.kind,
        result_event=result_event,
        session_id=record["session_id"],
        error_categories=categories,
        gate_failures=gate_failures,
        shape_errors=shape_errors,
    ))
    if result_event and isinstance(result_event.get("total_cost_usd"),
                                   (int, float)):
        record["total_cost_usd"] = round(
            record["total_cost_usd"] + result_event["total_cost_usd"], 6)
    record.update({"status": verdict.status, "exit_code": verdict.exit_code,
                   "detail": verdict.detail, "resumable": verdict.resumable})
    save_run(record)
    if verdict.status == "completed":
        head = git(["rev-parse", "HEAD"], record["worktree"]).stdout.strip()
        write_json(run_dir(record["run_id"]) / "handoff.json", {
            "run_id": record["run_id"], "branch": record["branch"],
            "worktree": record["worktree"], "head": head,
            "integration": "not_observed",
        })
    print(json.dumps({
        "run_id": record["run_id"], "status": verdict.status,
        "detail": verdict.detail, "session_id": record["session_id"],
        "worktree": record["worktree"], "branch": record["branch"],
        "launches": record["launches"],
        "total_cost_usd": record["total_cost_usd"],
    }, indent=2))
    return verdict.exit_code


def cmd_run(args):
    workspace = Path(args.workspace).resolve()
    plan = Path(args.plan).resolve()
    specs = [Path(item).resolve() for item in args.spec]
    timeout_seconds = args.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    if not _timeout_floor() <= timeout_seconds <= TIMEOUT_CEILING:
        return _halt("invalid_timeout",
                     f"{timeout_seconds} not in [{_timeout_floor()}, {TIMEOUT_CEILING}]",
                     EXIT_FAILED)
    for path in [plan, *specs]:
        try:
            path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return _halt("unreadable_input", f"{path}: {error}", EXIT_FAILED)
    status = git(["status", "--porcelain"], workspace)
    if status.returncode != 0:
        return _halt("not_a_git_workspace", status.stderr.strip(), EXIT_FAILED)
    if status.stdout.strip():
        return _halt("dirty_workspace", "commit or stash changes first",
                     EXIT_BLOCKED)
    run_id = derive_run_id(plan)
    rdir = run_dir(run_id)
    rdir.mkdir(parents=True, exist_ok=False)
    plan_copy, spec_copies = snapshot_inputs(rdir, plan, specs)
    worktree = worktree_dir(run_id)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    added = git(["worktree", "add", "-b", f"clpe/{run_id}", str(worktree)],
                workspace)
    if added.returncode != 0:
        return _halt("worktree_add_failed", added.stderr.strip(), EXIT_FAILED)
    starting = git(["rev-parse", "HEAD"], worktree).stdout.strip()
    record = {
        "run_id": run_id,
        "workspace": str(workspace),
        "worktree": str(worktree),
        "branch": f"clpe/{run_id}",
        "starting_commit": starting,
        "plan": str(plan_copy),
        "specs": [str(copy) for copy in spec_copies],
        "model": args.model,
        "max_turns": args.max_turns,
        "timeout_seconds": timeout_seconds,
        "launches": 0,
        "session_id": None,
        "status": "running",
        "exit_code": None,
        "detail": None,
        "resumable": False,
        "total_cost_usd": 0.0,
    }
    save_run(record)
    return execute_cycle(record, resume=False)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clpe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="launch a new plan run")
    run_parser.add_argument("--spec", action="append", required=True)
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--workspace", required=True)
    run_parser.add_argument("--model")
    run_parser.add_argument("--max-turns", type=int, dest="max_turns")
    run_parser.add_argument("--timeout-seconds", type=int,
                            dest="timeout_seconds")
    args = parser.parse_args(argv)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 skills/kws-claude-plan-executor/evals/check_cli.py && ./skills/kws-claude-plan-executor/evals/run.sh`
Expected: PASS / `3 suites passed`

- [ ] **Step 6: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): run command e2e with fake claude and fail-closed verdicts"
```

---

### Task 8: `resume` command

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py`
- Modify: `skills/kws-claude-plan-executor/evals/check_cli.py` (append)

**Interfaces:**
- Consumes: `execute_cycle(record, resume=True)`, `load_run`, `MAX_LAUNCHES`.
- Produces: `clpe.cmd_resume(args) -> int`. 가드 순서: unknown run → 1 / already completed → 0 (no-op, 런칭 없음) / session 없음 → 1 / launches ≥ MAX_LAUNCHES → 2 / timeout 재지정 검증 → 실행.

- [ ] **Step 1: Write the failing test** — `check_cli.py`에 append:

```python
class ResumeCommandTest(CliFixture):
    def run_then_resume(self, scenario, resume_scenario, run_kwargs=None):
        result = self.run_plan(scenario=scenario, **(run_kwargs or {}))
        record = self.only_run_record()
        resume = self.clpe("resume", "--run-id", record["run_id"],
                           scenario=scenario, resume_scenario=resume_scenario)
        return result, resume, record["run_id"]

    def test_max_turns_then_resume_to_completion(self):
        first, resume, run_id = self.run_then_resume("max_turns", "completed")
        self.assertEqual(first.returncode, 3)
        self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)
        record = self.only_run_record()
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["launches"], 2)
        lines = self.argv_lines()
        self.assertEqual(len(lines), 2)
        resume_argv = lines[1]["argv"]
        self.assertEqual(resume_argv[resume_argv.index("--resume") + 1],
                         "sess-0001")
        self.assertIn("Continue executing the plan",
                      resume_argv[resume_argv.index("-p") + 1])

    def test_timeout_then_resume(self):
        first = self.run_plan("--timeout-seconds", "2", scenario="timeout",
                              fake_sleep="30")
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        record = self.only_run_record()
        self.assertEqual(record["status"], "resumable")
        self.assertEqual(record["detail"], "timed_out")
        self.assertEqual(record["session_id"], "sess-0001")
        resume = self.clpe("resume", "--run-id", record["run_id"],
                           scenario="timeout", resume_scenario="completed")
        self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)

    def test_resume_of_completed_run_is_noop(self):
        self.run_plan()
        run_id = self.only_run_record()["run_id"]
        resume = self.clpe("resume", "--run-id", run_id)
        self.assertEqual(resume.returncode, 0)
        self.assertIn("already_completed", resume.stdout)
        self.assertEqual(len(self.argv_lines()), 1)  # no second launch

    def test_resume_without_session_fails(self):
        self.run_plan(scenario="invalid")
        run_id = self.only_run_record()["run_id"]
        resume = self.clpe("resume", "--run-id", run_id)
        self.assertEqual(resume.returncode, 1)
        self.assertIn("no_session_to_resume", resume.stdout)

    def test_launch_budget_exhaustion_blocks(self):
        self.run_plan(scenario="max_turns")
        record = self.only_run_record()
        record["launches"] = 5
        run_json = self.home / "clpe" / record["run_id"] / "run.json"
        run_json.write_text(json.dumps(record), encoding="utf-8")
        resume = self.clpe("resume", "--run-id", record["run_id"])
        self.assertEqual(resume.returncode, 2)
        self.assertIn("launch_budget_exhausted", resume.stdout)

    def test_unknown_run_id_fails(self):
        resume = self.clpe("resume", "--run-id", "nope")
        self.assertEqual(resume.returncode, 1)
        self.assertIn("unknown_run", resume.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_cli.py`
Expected: FAIL — `resume` 서브커맨드 없음 (argparse error, exit 2 ≠ 기대값)

- [ ] **Step 3: Implement** — `clpe.py`의 `main` 위에 `cmd_resume` 추가, `main`에 서브커맨드 배선:

```python
def cmd_resume(args):
    record = load_run(args.run_id)
    if record is None:
        return _halt("unknown_run", args.run_id, EXIT_FAILED)
    if record["status"] == "completed":
        print(json.dumps({"noop": "already_completed",
                          "run_id": args.run_id}))
        return EXIT_COMPLETED
    if not record.get("session_id"):
        return _halt("no_session_to_resume", "start a new run", EXIT_FAILED)
    if record["launches"] >= MAX_LAUNCHES:
        return _halt("launch_budget_exhausted",
                     f"max {MAX_LAUNCHES} launches", EXIT_BLOCKED)
    if args.timeout_seconds:
        if not _timeout_floor() <= args.timeout_seconds <= TIMEOUT_CEILING:
            return _halt(
                "invalid_timeout",
                f"{args.timeout_seconds} not in "
                f"[{_timeout_floor()}, {TIMEOUT_CEILING}]",
                EXIT_FAILED)
        record["timeout_seconds"] = args.timeout_seconds
    return execute_cycle(record, resume=True)
```

`main()`의 `args = parser.parse_args(argv)` 앞에 추가:

```python
    resume_parser = sub.add_parser("resume", help="resume an interrupted run")
    resume_parser.add_argument("--run-id", required=True, dest="run_id")
    resume_parser.add_argument("--timeout-seconds", type=int,
                               dest="timeout_seconds")
```

그리고 `return cmd_run(args)` 를 다음으로 교체:

```python
    if args.command == "run":
        return cmd_run(args)
    return cmd_resume(args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 skills/kws-claude-plan-executor/evals/check_cli.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): session-delegated resume with fail-closed guards"
```

---

### Task 9: `inspect` command + final CLI assembly

**Files:**
- Modify: `skills/kws-claude-plan-executor/scripts/clpe.py`
- Modify: `skills/kws-claude-plan-executor/evals/check_cli.py` (append)

**Interfaces:**
- Produces: `clpe.cmd_inspect(args) -> int` — run.json을 그대로 출력(읽기 전용), 존재하면 0, 없으면 1.

- [ ] **Step 1: Write the failing test** — `check_cli.py`에 append:

```python
class InspectCommandTest(CliFixture):
    def test_inspect_prints_run_record(self):
        self.run_plan()
        run_id = self.only_run_record()["run_id"]
        argv_count_before = len(self.argv_lines())
        result = self.clpe("inspect", "--run-id", run_id)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["run_id"], run_id)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(self.argv_lines()), argv_count_before)  # read-only

    def test_inspect_unknown_run(self):
        result = self.clpe("inspect", "--run-id", "nope")
        self.assertEqual(result.returncode, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/kws-claude-plan-executor/evals/check_cli.py`
Expected: FAIL — `inspect` 서브커맨드 없음

- [ ] **Step 3: Implement** — `cmd_resume` 아래에 추가:

```python
def cmd_inspect(args):
    record = load_run(args.run_id)
    if record is None:
        return _halt("unknown_run", args.run_id, EXIT_FAILED)
    print(json.dumps(record, indent=2, sort_keys=True))
    return EXIT_COMPLETED
```

`main()`에 서브파서와 분기 추가 (resume 분기 위):

```python
    inspect_parser = sub.add_parser("inspect", help="read-only run state dump")
    inspect_parser.add_argument("--run-id", required=True, dest="run_id")
```

분기 교체:

```python
    if args.command == "run":
        return cmd_run(args)
    if args.command == "resume":
        return cmd_resume(args)
    return cmd_inspect(args)
```

- [ ] **Step 4: Run the full gate**

Run: `./skills/kws-claude-plan-executor/evals/run.sh && python3 -m py_compile skills/kws-claude-plan-executor/scripts/clpe.py skills/kws-claude-plan-executor/evals/*.py && bash -n skills/kws-claude-plan-executor/evals/run.sh`
Expected: `3 suites passed`, py_compile/bash -n 무음 성공

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "feat(clpe): inspect command and complete CLI assembly"
```

---

### Task 10: SKILL.md + README.md + 과금 실측

**Files:**
- Create: `skills/kws-claude-plan-executor/SKILL.md`
- Create: `skills/kws-claude-plan-executor/README.md`
- Create: `skills/kws-claude-plan-executor/AGENTS.md`

**Interfaces:**
- Consumes: 확정된 CLI 계약 (Tasks 7–9).
- Produces: 스킬 진입 문서. SKILL.md frontmatter `version: "1.0.0"`.

- [ ] **Step 1: Write SKILL.md**

`skills/kws-claude-plan-executor/SKILL.md`:

```markdown
---
name: kws-claude-plan-executor
description: Use when an approved Superpowers implementation plan must run autonomously in an isolated worktree via a headless child Claude session, with fail-closed completion verification and session-delegated resume.
metadata:
  version: "1.0.0"
  updated_at: "2026-07-22"
---

# KWS Claude Plan Executor (CLPE)

CLPE is a thin local harness for approved Superpowers implementation plans.
CLPE maintains one execution environment and verifies submitted facts. The
child Claude session's Superpowers decides what work, verification, and
parallelism are correct — including whether to dispatch its own subagents.
CLPE never compiles a plan, selects a task, computes review tiers, or judges
quality. It replaced the v3 multi-agent orchestrator (archived at
`archive/kws-claude-multi-agent-executor-v3/`).

## Commands

```bash
python3 scripts/clpe.py run \
  --spec /abs/spec.md --plan /abs/plan.md \
  --workspace /abs/repository \
  [--model opus|sonnet|fable] [--max-turns N] [--timeout-seconds 1200..7200]
python3 scripts/clpe.py resume --run-id RUN_ID [--timeout-seconds N]
python3 scripts/clpe.py inspect --run-id RUN_ID
```

Exit codes: `completed` 0, `failed` 1, `blocked` 2, `resumable` 3.
State lives under `~/.claude/clpe/<run-id>/` (override with `CLPE_HOME`);
the worktree is `~/.claude/worktrees/<run-id>/`. Nothing is written inside
the source repository. The worktree is never auto-deleted.

## Launch contract

`run` requires a clean git workspace and readable UTF-8 inputs. It snapshots
the plan and specs, creates one worktree + branch `clpe/<run-id>`, scrubs
`CLAUDECODE` / `CLAUDE_CODE_CHILD_SESSION` / `CLAUDE_CODE_ENTRYPOINT` and
secret-suffixed env vars (keeping `ANTHROPIC_*`), and launches:

`claude -p <facts+delegation prompt> --output-format stream-json --verbose
--json-schema templates/plan-result.schema.json
--permission-mode bypassPermissions --disallowedTools <git push/merge, rm -rf /,
reset --hard origin>`

stream-json (not json) is load-bearing: the first init event yields the
session id early, so a timed-out run remains resumable. There is no `--bare`;
the child auto-loads Superpowers. CLPE imposes the wall-clock timeout itself
(SIGTERM the process group, then SIGKILL).

The prompt prohibitions (no merge/push/deploy/outside-worktree writes) are a
guard, not a sandbox substitute. Accepted residual risk: under
bypassPermissions, writes outside the worktree are not fully observable or
reversible; deny rules and the git gates below are the remaining controls.

## Fail-closed completion

A run is `completed` only if ALL hold: envelope subtype is `success` AND
`structured_output` is present; the child reports `status=completed`; the
worktree is clean; the reported `head_commit` matches `git rev-parse HEAD`;
`merge-base --is-ancestor <starting_commit> HEAD` passes; `open_findings` is
empty. `handoff.json` records branch/head facts and `integration=not_observed`
— it never claims merge, push, deploy, or product acceptance.

Provider conditions are classified from stream error categories
(`rate_limit`/`overloaded` → usage/unavailable blocked;
`authentication_failed`/`billing_error` → auth blocked) and become
operator-owned blocked facts. `error_max_turns`, `error_max_budget_usd`, and
harness timeouts are `resumable` (exit 3).

## Resume

Resume is delegated to Claude Code's session store: CLPE re-invokes
`claude -p --resume <session_id>` with the same schema and verification.
Resume never relaxes the completion gates. A run without a captured session
id cannot resume — start a new run. Launches are bounded (max 5 per run).

## Verify

For any behavior change, add a focused deterministic eval first, then run the
complete local gate at the final clean revision:

```bash
./evals/run.sh
python3 -m py_compile scripts/clpe.py evals/*.py
```

Evals are sequential, network-free, credential-free, and model-free
(`fake_claude.py` stands in for the CLI).
```

- [ ] **Step 2: Write README.md**

`skills/kws-claude-plan-executor/README.md`:

```markdown
# KWS Claude Plan Executor (CLPE)

Version 1.0.0. A ~400-line launcher for approved Superpowers implementation
plans on the `claude` CLI. Ownership boundary (same as CPE): CLPE maintains
one execution environment and verifies submitted facts; the child session's
Superpowers owns plan interpretation, implementation, tests, reviews,
subagents, and commits.

Design spec:
`docs/superpowers/specs/2026-07-22-claude-plan-executor-thin-rewrite-design.md`.
Predecessor (fat v3 orchestrator): `archive/kws-claude-multi-agent-executor-v3/`.

## Requirements

- Python 3 standard library, Git, `claude` on PATH
- a clean Git workspace and absolute readable UTF-8 spec/plan paths

## Usage

```bash
python3 scripts/clpe.py run --spec /abs/spec.md --plan /abs/plan.md \
  --workspace /abs/repository
python3 scripts/clpe.py resume --run-id RUN_ID
python3 scripts/clpe.py inspect --run-id RUN_ID
```

Exit codes: 0 completed / 1 failed / 2 blocked / 3 resumable. Run state:
`~/.claude/clpe/<run-id>/` (`CLPE_HOME` overrides the prefix); worktree:
`~/.claude/worktrees/<run-id>/`, branch `clpe/<run-id>`.

See SKILL.md for the launch contract, fail-closed completion gates, failure
classification, and resume semantics.

## Tracked inventory

```text
AGENTS.md
README.md
SKILL.md
evals/check_cli.py
evals/check_gates.py
evals/check_units.py
evals/fake_claude.py
evals/run.sh
scripts/clpe.py
templates/plan-result.schema.json
```

## Verify

```bash
./evals/run.sh
python3 -m py_compile scripts/clpe.py evals/*.py
bash -n evals/run.sh
```
```

`skills/kws-claude-plan-executor/AGENTS.md`:

```markdown
# Claude Plan Executor Agent Instructions

- Preserve the thin launcher boundary: CLPE maintains the environment and
  verifies submitted facts; the child session's Superpowers owns all
  workflow semantics. Do not add task mapping, review tiers, or quality
  policy back into CLPE.
- Python standard library only; evals stay network-free and model-free.
- Run `./evals/run.sh` before claiming executor changes are complete.
```

- [ ] **Step 3: 과금 경로 실측 (라이브 1회 — evals 아님)**

실제 `claude` CLI가 있고 네트워크가 가능할 때만:

```bash
claude -p "Reply with exactly: OK" --output-format json --model haiku
```

봉투의 `total_cost_usd`를 확인하고, 실행 직후 구독 사용량(예: claude.ai 사용량 표시 또는 콘솔 크레딧 잔액)이 움직였는지로 과금처를 판정한다. SKILL.md의 "## Launch contract" 절 끝에 다음 중 **관측 결과에 맞는 한 줄**을 추가한다:

- 구독 과금 확인 시: `Billing (measured 2026-07-22): headless \`claude -p\` bills against the subscription (OAuth) on this machine.`
- 크레딧 과금 확인 시: `Billing (measured 2026-07-22): headless \`claude -p\` bills metered API credits on this machine — budget accordingly with --max-turns.`
- 실측 불가 시(오프라인 등): `Billing: not yet measured on this machine; official docs say headless CLI preserves subscription (OAuth) billing, while a 2025 local experiment observed credit billing. Verify once with a short run.`

같은 실행으로 스펙 §13의 `--json-schema` 상호작용도 함께 관찰한다: `structured_output` 필드가 봉투에 있으면 추가 조치 없음. (없으면 스펙 §13의 결과 파일 대안을 이슈로 기록만 — 이 플랜 범위에서 구현하지 않는다.) 스펙 §13의 나머지 실측 항목(워크트리 cwd에서 어느 `.claude/` 프로젝트 설정이 로드되는지)은 첫 실전 run에서 관찰해 SKILL.md에 한 줄로 기록한다 — CLPE는 워크트리에 설정을 심지 않으므로 동작에는 영향 없다.

- [ ] **Step 4: Verify docs render and inventory matches**

Run: `ls skills/kws-claude-plan-executor skills/kws-claude-plan-executor/evals skills/kws-claude-plan-executor/scripts skills/kws-claude-plan-executor/templates`
Expected: README.md tracked inventory와 파일 목록 일치

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-plan-executor
git commit -m "docs(clpe): SKILL.md, README, AGENTS instructions, billing note"
```

---

### Task 11: v3 아카이브 + 심링크 + skills/README.md 갱신

**Files:**
- Move: `skills/kws-claude-multi-agent-executor/` → `archive/kws-claude-multi-agent-executor-v3/`
- Modify: `skills/README.md`
- Symlinks (레포 밖): `~/.claude/skills/`, `~/.codex/skills/`

**Interfaces:**
- Consumes: 완성된 `skills/kws-claude-plan-executor/`.

- [ ] **Step 1: Archive v3**

```bash
mkdir -p archive
git mv skills/kws-claude-multi-agent-executor archive/kws-claude-multi-agent-executor-v3
```

- [ ] **Step 2: Update skills/README.md**

스킬 표에서 `kws-claude-multi-agent-executor` 행을 다음으로 교체:

```markdown
| [`kws-claude-plan-executor`](./kws-claude-plan-executor/) | 승인된 Superpowers 구현 계획을 헤드리스 자식 Claude 세션으로 자율 실행하는 얇은 런처. fail-closed 완료 검증 + 세션 위임 재개. v3 오케스트레이터는 `archive/kws-claude-multi-agent-executor-v3/`에 보존. |
```

Claude Code 심링크 블록에서:

```bash
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-multi-agent-executor" \
        ~/.claude/skills/kws-claude-multi-agent-executor
```

를 다음으로 교체:

```bash
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-plan-executor" \
        ~/.claude/skills/kws-claude-plan-executor
```

Codex 심링크 블록도 동일하게 `kws-claude-multi-agent-executor` → `kws-claude-plan-executor` 로 교체.

- [ ] **Step 3: Update the live symlinks**

```bash
ARCHIVE_REPO=/Users/kws/source/private/Archive
rm ~/.claude/skills/kws-claude-multi-agent-executor
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-plan-executor" \
        ~/.claude/skills/kws-claude-plan-executor
if [ -d ~/.codex/skills ]; then
  rm -f ~/.codex/skills/kws-claude-multi-agent-executor
  ln -sfn "$ARCHIVE_REPO/skills/kws-claude-plan-executor" \
          ~/.codex/skills/kws-claude-plan-executor
fi
ls -l ~/.claude/skills/ | grep -E 'kws-|waygent'
```

Expected: `kws-claude-plan-executor` 심링크가 레포를 가리키고, 옛 이름 심링크는 사라짐.

- [ ] **Step 4: Verify nothing else references the old skill path as active**

Run: `grep -rn "kws-claude-multi-agent-executor" --include="*.md" skills/ docs/superpowers/specs/2026-07-22-claude-plan-executor-thin-rewrite-design.md | grep -v archive`
Expected: 스펙 문서의 이력 서술(교체 대상 언급)만 남고, `skills/` 아래 활성 참조 없음.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: archive CME v3, register kws-claude-plan-executor as active skill"
```

---

### Task 12: Final gate

**Files:** 없음 (검증 전용)

- [ ] **Step 1: Run the complete local gate at the final clean revision**

```bash
cd /Users/kws/source/private/Archive
./skills/kws-claude-plan-executor/evals/run.sh
python3 -m py_compile skills/kws-claude-plan-executor/scripts/clpe.py \
  skills/kws-claude-plan-executor/evals/*.py
bash -n skills/kws-claude-plan-executor/evals/run.sh
git status --porcelain
```

Expected: `3 suites passed`, 컴파일 무음 성공, working tree clean.

- [ ] **Step 2: Smoke the CLI surface**

```bash
python3 skills/kws-claude-plan-executor/scripts/clpe.py inspect --run-id smoke-none
```

Expected: `{"halt": "unknown_run", ...}` 출력, exit 1 (echo $? 로 확인).

- [ ] **Step 3: Report**

최종 보고에 포함: 커밋 목록, evals 결과, 심링크 상태(`ls -l ~/.claude/skills/`), Task 10 Step 3 과금 실측 결과(또는 미실측 사유).
