# CPE Human-Readable Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add human-readable task packet views, hot-tail task summaries, markdown golden-case evals, verification bundle evidence, and advisory residual-risk classes to CPE without weakening the existing machine contracts.

**Architecture:** Keep task packet JSON and `state.json` as the source of truth. Add generated markdown and summary fields as derived, optional surfaces under `~/.codex/orchestrator/<run_id>/`, then validate claimed output with deterministic Python evals. Extend completion evidence and normalized replay with structured classes while preserving existing acceptance, reconciliation, and state validation gates.

**Tech Stack:** Python 3 stdlib, Bash eval harness, Markdown fixtures, existing CPE scripts under `skills/kws-codex-plan-executor`, existing docs under `skills/kws-codex-plan-executor/docs` and `references`.

## Global Constraints

- Do not introduce `--dangerously-bypass-approvals-and-sandbox` or dangerous skip execution.
- Do not store CPE runtime state in the implementation repo.
- Do not make markdown views the source of truth.
- Do not use one-line summaries to replace task completion, dispatch decision, or verification evidence.
- Do not add LLM judge or external API key dependencies to the default deterministic eval gate.
- Do not use PR risk scoring as a merge gate, finished gate, or release-blocker source of truth.
- Preserve `completion_audit.passed`, `validate_state.py`, `reconcile_state.py`, and acceptance command semantics.
- Generated task packet views must live under `~/.codex/orchestrator/<run_id>/task_packets/` during real runs.
- Older states without the new optional fields must remain valid.

---

## File Structure

- Create `skills/kws-codex-plan-executor/scripts/render_task_packet_view.py`
  - Responsibility: load one task packet JSON, validate the required packet fields for rendering, and write a deterministic markdown view.
- Create `skills/kws-codex-plan-executor/evals/check_task_packet_view.py`
  - Responsibility: exercise the renderer against valid, missing-acceptance, full-spec-fallback, and malformed packet cases.
- Create `skills/kws-codex-plan-executor/evals/check_context_summary.py`
  - Responsibility: validate optional `next_task_summary` and `context_health.hot_tail_summaries` behavior through `validate_state.py`.
- Create `skills/kws-codex-plan-executor/evals/check_markdown_golden_cases.py`
  - Responsibility: parse operator-readable markdown cases and assert required sections plus expected decisions.
- Create `skills/kws-codex-plan-executor/evals/check_verification_bundle.py`
  - Responsibility: validate structured `verification_bundle` evidence through `validate_state.py`.
- Create `skills/kws-codex-plan-executor/evals/golden-cases/*.md`
  - Responsibility: store readable policy regression cases for dirty worktree, resume ambiguity, unsafe verification, subagent fallback, and packet view parity.
- Modify `skills/kws-codex-plan-executor/scripts/validate_state.py`
  - Responsibility: accept the new residual-risk classes, validate optional task packet view path/hash, validate one-line summaries, and validate structured verification bundle evidence.
- Modify `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
  - Responsibility: expose verification evidence classes and hot-tail summary counts in normalized replay.
- Modify `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
  - Responsibility: cover replay output for verification bundle classes and summary counts.
- Modify `skills/kws-codex-plan-executor/evals/run.sh`
  - Responsibility: run the new deterministic checks.
- Modify `skills/kws-codex-plan-executor/SKILL.md`
  - Responsibility: document runtime invariants for generated task views, summaries, verification bundle evidence, and advisory risk classes.
- Modify `skills/kws-codex-plan-executor/README.md`, `skills/kws-codex-plan-executor/docs/state-and-logging.md`, `skills/kws-codex-plan-executor/docs/evals-and-verification.md`, `skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md`, `skills/kws-codex-plan-executor/docs/verification-log.md`, `skills/kws-codex-plan-executor/HISTORY.md`, and `skills/kws-codex-plan-executor/ARCHITECTURE.md`
  - Responsibility: keep operator docs, coverage docs, and change history aligned with runtime behavior.

## Task 1: Human Task Packet View Renderer

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/render_task_packet_view.py`
- Create: `skills/kws-codex-plan-executor/evals/check_task_packet_view.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: task packet JSON produced by `scripts/build_task_packet.py`.
- Produces: `render_packet_view(packet: dict) -> str`, `sha256_text(text: str) -> str`, and a CLI accepting `--task-packet` plus `--output`.

- [ ] **Step 1: Write the failing renderer eval**

Create `skills/kws-codex-plan-executor/evals/check_task_packet_view.py` with this content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_task_packet_view.py"


def base_packet() -> dict:
    return {
        "schema_version": "1",
        "task_id": "task_0",
        "task_title": "Render packet",
        "task_body": "Build the human-readable packet renderer.",
        "files": ["skills/kws-codex-plan-executor/scripts/render_task_packet_view.py"],
        "acceptance": {
            "has_acceptance_criteria": True,
            "command": "python3 evals/check_task_packet_view.py",
            "source": "plan.acceptance",
            "honest_substitute_allowed": False,
        },
        "spec": {
            "mode": "slice",
            "section_ids": ["S1"],
            "fallback_used": False,
        },
        "decisions_register": {"included": [{"id": "dec_1"}], "omitted_count": 0},
        "write_policy": {
            "allowed_write_globs": ["skills/kws-codex-plan-executor/scripts/render_task_packet_view.py"],
            "forbidden_write_globs": [".git/**", "graphify-out/**"],
        },
        "unit_manifest": {
            "forbidden_write_globs": [".git/**", "graphify-out/**"],
        },
        "context_budget": {
            "estimated_chars": 1200,
            "max_chars": 60000,
            "status": "green",
        },
    }


def run_renderer(root: Path, packet: dict) -> tuple[subprocess.CompletedProcess[str], str]:
    packet_path = root / "packet.json"
    output_path = root / "packet.md"
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--task-packet", str(packet_path), "--output", str(output_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    text = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
    return result, text


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="cpe-task-view-") as temp:
        root = Path(temp)
        result, text = run_renderer(root, base_packet())
        checks["renders_core_sections"] = (
            result.returncode == 0
            and "# Task task_0: Render packet" in text
            and "## 읽을 파일" in text
            and "## 작업" in text
            and "## AC" in text
            and "## 검증" in text
            and "## 금지사항" in text
            and "python3 evals/check_task_packet_view.py" in text
            and ".git/**" in text
            and "decisions included: 1" in text
        )
        if not checks["renders_core_sections"]:
            failures.append("renderer should produce all required human-view sections")

        missing_acceptance = base_packet()
        missing_acceptance["acceptance"]["command"] = None
        missing_acceptance["acceptance"]["honest_substitute_allowed"] = True
        result, text = run_renderer(root, missing_acceptance)
        checks["missing_acceptance_is_explicit"] = (
            result.returncode == 0 and "honest substitute required" in text
        )
        if not checks["missing_acceptance_is_explicit"]:
            failures.append("missing acceptance command should render an explicit honest-substitute marker")

        fallback = base_packet()
        fallback["spec"]["mode"] = "full"
        fallback["spec"]["section_ids"] = ["*"]
        fallback["spec"]["fallback_used"] = True
        result, text = run_renderer(root, fallback)
        checks["full_spec_fallback_visible"] = result.returncode == 0 and "full spec fallback" in text
        if not checks["full_spec_fallback_visible"]:
            failures.append("full-spec fallback should be visible in the markdown view")

        malformed = base_packet()
        del malformed["write_policy"]
        result, text = run_renderer(root, malformed)
        checks["malformed_packet_fails"] = result.returncode != 0 and "write_policy" in result.stderr
        if not checks["malformed_packet_fails"]:
            failures.append("malformed packet should fail with the missing field name")

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the new eval to verify it fails**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet_view.py
```

Expected: FAIL because `scripts/render_task_packet_view.py` does not exist.

- [ ] **Step 3: Implement the renderer**

Create `skills/kws-codex-plan-executor/scripts/render_task_packet_view.py` with this content:

```python
#!/usr/bin/env python3
"""Render a task packet JSON file as a deterministic human-readable markdown view."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {
    "task_id",
    "task_title",
    "task_body",
    "files",
    "acceptance",
    "spec",
    "write_policy",
    "context_budget",
}


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_packet(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        die(f"task packet is not readable: {path}: {exc}")
    except json.JSONDecodeError as exc:
        die(f"task packet is invalid JSON: {path}: {exc}")
    if not isinstance(payload, dict):
        die("task packet must be a JSON object")
    missing = sorted(REQUIRED_TOP_LEVEL.difference(payload))
    if missing:
        die(f"task packet missing field(s): {', '.join(missing)}")
    return payload


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def bullet_list(items: list[str], fallback: str) -> str:
    values = items or [fallback]
    return "\n".join(f"- {item}" for item in values)


def acceptance_lines(acceptance: dict[str, Any]) -> tuple[list[str], list[str]]:
    command = acceptance.get("command")
    source = acceptance.get("source", "unknown")
    if isinstance(command, str) and command.strip():
        return [f"source: {source}"], [command.strip()]
    return ["missing acceptance command"], ["honest substitute required"]


def render_packet_view(packet: dict[str, Any]) -> str:
    acceptance = packet.get("acceptance")
    spec = packet.get("spec")
    write_policy = packet.get("write_policy")
    budget = packet.get("context_budget")
    decisions = packet.get("decisions_register") if isinstance(packet.get("decisions_register"), dict) else {}
    unit_manifest = packet.get("unit_manifest") if isinstance(packet.get("unit_manifest"), dict) else {}
    if not isinstance(acceptance, dict):
        die("task packet acceptance must be an object")
    if not isinstance(spec, dict):
        die("task packet spec must be an object")
    if not isinstance(write_policy, dict):
        die("task packet write_policy must be an object")
    if not isinstance(budget, dict):
        die("task packet context_budget must be an object")

    files = list_strings(packet.get("files"))
    forbidden = list_strings(write_policy.get("forbidden_write_globs"))
    for item in list_strings(unit_manifest.get("forbidden_write_globs")):
        if item not in forbidden:
            forbidden.append(item)
    ac_lines, verification_lines = acceptance_lines(acceptance)
    section_ids = list_strings(spec.get("section_ids"))
    fallback_note = "- warning: full spec fallback" if spec.get("fallback_used") is True else "- warning: none"
    included_decisions = decisions.get("included") if isinstance(decisions.get("included"), list) else []

    lines = [
        f"# Task {packet.get('task_id')}: {packet.get('task_title') or '(untitled)'}",
        "",
        "## 읽을 파일",
        bullet_list(files, "no files declared"),
        "",
        "## 작업",
        str(packet.get("task_body") or "").strip() or "missing task body",
        "",
        "## AC",
        bullet_list(ac_lines, "missing acceptance criteria"),
        "",
        "## 검증",
        bullet_list(verification_lines, "honest substitute required"),
        "",
        "## 금지사항",
        bullet_list(forbidden, "no forbidden globs declared"),
        "",
        "## Context Notes",
        f"- spec sections: {', '.join(section_ids) if section_ids else 'missing'}",
        f"- context budget: {budget.get('status', 'unknown')}, {budget.get('estimated_chars', 'unknown')}/{budget.get('max_chars', 'unknown')}",
        f"- decisions included: {len(included_decisions)}",
        fallback_note,
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-packet", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    packet = load_packet(Path(args.task_packet).expanduser())
    text = render_packet_view(packet)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(json.dumps({"path": str(output), "sha256": sha256_text(text)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add the eval to the harness**

Modify `skills/kws-codex-plan-executor/evals/run.sh` by inserting this line after `check_task_packet.py`:

```bash
python3 "$EVAL_DIR/check_task_packet_view.py" >/dev/null
```

- [ ] **Step 5: Run the focused eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet_view.py
```

Expected: PASS with JSON containing `"passed": true`.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/render_task_packet_view.py \
  skills/kws-codex-plan-executor/evals/check_task_packet_view.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat: render CPE task packet human view"
```

## Task 2: State Validation for Views and Hot-Tail Summaries

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Create: `skills/kws-codex-plan-executor/evals/check_context_summary.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: optional task fields `task_packet_view_path`, `task_packet_view_sha256`, `next_task_summary`; optional `context_health.hot_tail_summaries`.
- Produces: validator errors for malformed claimed view output and invalid summaries.

- [ ] **Step 1: Write the failing summary eval**

Create `skills/kws-codex-plan-executor/evals/check_context_summary.py` with this content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from check_state_schema import base_state


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"


def run_validator(state: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="cpe-summary-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(state_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    valid = base_state()
    valid["tasks"]["task_0"]["next_task_summary"] = "Rendered task_0 view and validated summary storage."
    valid["context_health"]["hot_tail_summaries"] = [
        {"task_id": "task_0", "summary": "Rendered task_0 view and validated summary storage."}
    ]
    result = run_validator(valid)
    checks["one_line_summary_passes"] = result.returncode == 0
    if not checks["one_line_summary_passes"]:
        failures.append("valid one-line summaries should pass: " + (result.stderr or result.stdout))

    multiline = base_state()
    multiline["tasks"]["task_0"]["next_task_summary"] = "line one\nline two"
    result = run_validator(multiline)
    checks["multiline_summary_fails"] = result.returncode != 0 and "next_task_summary must be one line" in (
        result.stderr + result.stdout
    )
    if not checks["multiline_summary_fails"]:
        failures.append("multiline next_task_summary should fail")

    forbidden = base_state()
    forbidden["tasks"]["task_0"]["next_task_summary"] = "Wrote BEGIN FULL PROMPT into the summary."
    result = run_validator(forbidden)
    checks["forbidden_summary_pattern_fails"] = result.returncode != 0 and "forbidden durable-output pattern" in (
        result.stderr + result.stdout
    )
    if not checks["forbidden_summary_pattern_fails"]:
        failures.append("forbidden durable-output markers should fail in summaries")

    bad_hot_tail = base_state()
    bad_hot_tail["context_health"]["hot_tail_summaries"] = [{"task_id": "task_9", "summary": "Unknown task."}]
    result = run_validator(bad_hot_tail)
    checks["unknown_hot_tail_task_fails"] = result.returncode != 0 and "hot_tail_summaries" in (
        result.stderr + result.stdout
    )
    if not checks["unknown_hot_tail_task_fails"]:
        failures.append("hot-tail summary should reference a known task id")

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the new eval to verify it fails**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_context_summary.py
```

Expected: FAIL because `validate_state.py` does not yet reject multiline or forbidden summary content.

- [ ] **Step 3: Add validator helpers**

Modify `skills/kws-codex-plan-executor/scripts/validate_state.py` near the constants by adding:

```python
FORBIDDEN_DURABLE_OUTPUT_PATTERNS = {
    "sk-": "sk-",
    "absolute_home_path": "/Users/",
    "full_prompt": "BEGIN FULL PROMPT",
}
```

Add these helpers after `_has_substantive_value`:

```python
def _forbidden_durable_patterns(value: str) -> list[str]:
    return [
        name
        for name, needle in FORBIDDEN_DURABLE_OUTPUT_PATTERNS.items()
        if needle in value
    ]


def _validate_one_line_summary(field: str, value: object, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string when present")
        return
    if "\n" in value or "\r" in value:
        errors.append(f"{field} must be one line")
    markers = _forbidden_durable_patterns(value)
    if markers:
        errors.append(f"{field} contains forbidden durable-output pattern(s): {', '.join(markers)}")
```

- [ ] **Step 4: Validate task summaries and hot-tail summaries**

In `_validate_tasks`, after the `files_declared` type check, insert:

```python
        _validate_one_line_summary(f"{task_id}: next_task_summary", task.get("next_task_summary"), errors)
        view_path = task.get("task_packet_view_path")
        if view_path is not None:
            if not isinstance(view_path, str) or not view_path.strip():
                errors.append(f"{task_id}: task_packet_view_path must be a non-empty string when present")
            elif "/.codex/orchestrator/" not in view_path:
                errors.append(f"{task_id}: task_packet_view_path must live under .codex/orchestrator")
        view_hash = task.get("task_packet_view_sha256")
        if view_hash is not None:
            if not isinstance(view_hash, str) or len(view_hash) != 64:
                errors.append(f"{task_id}: task_packet_view_sha256 must be a 64-character sha256 string")
```

In `_validate_context_health`, after list checks for `open_questions` and `known_assumptions`, insert:

```python
    hot_tail = health.get("hot_tail_summaries")
    if hot_tail is not None:
        if not isinstance(hot_tail, list):
            errors.append("context_health.hot_tail_summaries must be a list when present")
        else:
            tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
            for index, item in enumerate(hot_tail):
                prefix = f"context_health.hot_tail_summaries[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                task_id = item.get("task_id")
                if task_id not in tasks:
                    errors.append(f"{prefix}.task_id must reference a known task")
                _validate_one_line_summary(f"{prefix}.summary", item.get("summary"), errors)
```

- [ ] **Step 5: Add state-schema coverage for task packet view fields**

In `skills/kws-codex-plan-executor/evals/check_state_schema.py`, add a check near the other v2.20/v2.22 field checks:

```python
    task_view_fields = base_state()
    task_view_fields["tasks"]["task_0"]["task_packet_view_path"] = (
        f"{task_view_fields['run_dir']}/task_packets/task_0.md"
    )
    task_view_fields["tasks"]["task_0"]["task_packet_view_sha256"] = "a" * 64
    result = run_validator(script, task_view_fields)
    checks["task_packet_view_fields_pass"] = result.returncode == 0
    if not checks["task_packet_view_fields_pass"]:
        failures.append("valid task packet view path/hash fields should pass: " + (result.stderr or result.stdout))
```

- [ ] **Step 6: Add the summary eval to the harness**

Modify `skills/kws-codex-plan-executor/evals/run.sh` by inserting this line after `check_state_schema.py`:

```bash
python3 "$EVAL_DIR/check_context_summary.py" >/dev/null
```

- [ ] **Step 7: Run focused validation**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_context_summary.py
python3 evals/check_state_schema.py
```

Expected: both PASS with JSON containing `"passed": true`.

- [ ] **Step 8: Commit Task 2**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_context_summary.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat: validate CPE task summaries"
```

## Task 3: Markdown Golden-Case Eval Layer

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/check_markdown_golden_cases.py`
- Create: `skills/kws-codex-plan-executor/evals/golden-cases/dirty-related-block.md`
- Create: `skills/kws-codex-plan-executor/evals/golden-cases/resume-ambiguous-block.md`
- Create: `skills/kws-codex-plan-executor/evals/golden-cases/unsafe-verification-block.md`
- Create: `skills/kws-codex-plan-executor/evals/golden-cases/subagent-local-fallback.md`
- Create: `skills/kws-codex-plan-executor/evals/golden-cases/task-packet-human-view.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: markdown files with `Scenario`, `Input`, `Must`, `Must Not`, `Expected Decision`, and `Expected Risk` sections.
- Produces: deterministic pass/fail output for readable policy cases.

- [ ] **Step 1: Add the golden-case parser eval**

Create `skills/kws-codex-plan-executor/evals/check_markdown_golden_cases.py` with this content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


CASE_DIR = Path(__file__).resolve().parent / "golden-cases"
REQUIRED_SECTIONS = ["Scenario", "Input", "Must", "Must Not", "Expected Decision", "Expected Risk"]
EXPECTED_CASES = {
    "dirty-related-block.md": ("block", "dirty_related_worktree"),
    "resume-ambiguous-block.md": ("block", "resume_ambiguity"),
    "unsafe-verification-block.md": ("block", "unsafe_verification"),
    "subagent-local-fallback.md": ("local_fallback", "subagent_policy_fallback"),
    "task-packet-human-view.md": ("render", "human_view_parity"),
}


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    for filename, expected in EXPECTED_CASES.items():
        path = CASE_DIR / filename
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        sections = parse_sections(text)
        missing = [section for section in REQUIRED_SECTIONS if not sections.get(section)]
        key = filename.removesuffix(".md")
        checks[f"{key}_sections_present"] = not missing
        if missing:
            failures.append(f"{filename} missing section(s): {', '.join(missing)}")
            continue
        decision, risk = expected
        checks[f"{key}_expected_decision"] = sections["Expected Decision"].strip() == decision
        checks[f"{key}_expected_risk"] = sections["Expected Risk"].strip() == risk
        if not checks[f"{key}_expected_decision"]:
            failures.append(f"{filename} expected decision should be {decision}")
        if not checks[f"{key}_expected_risk"]:
            failures.append(f"{filename} expected risk should be {risk}")
        for section_name in ("Must", "Must Not"):
            bullet_count = sum(1 for line in sections[section_name].splitlines() if line.strip().startswith("- "))
            checks[f"{key}_{section_name.lower().replace(' ', '_')}_has_bullets"] = bullet_count >= 2
            if bullet_count < 2:
                failures.append(f"{filename} {section_name} should contain at least two bullets")

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add the five markdown cases**

Create the five files with the content below.

`skills/kws-codex-plan-executor/evals/golden-cases/dirty-related-block.md`:

```md
# dirty-related-block

## Scenario
The source checkout has dirty changes in files claimed by the next task.

## Input
- mode: interactive
- dirty_files:
  - path: src/auth/session.ts
    relation: related

## Must
- stop before edits
- report related dirty worktree blocker

## Must Not
- create completion_audit.passed=true
- classify related dirty files as unrelated

## Expected Decision
block

## Expected Risk
dirty_related_worktree
```

`skills/kws-codex-plan-executor/evals/golden-cases/resume-ambiguous-block.md`:

```md
# resume-ambiguous-block

## Scenario
resume=latest finds more than one active state file for the requested plan.

## Input
- mode: interactive
- resume: latest
- active_runs: 2

## Must
- stop before selecting a run
- ask which run id or state path to resume

## Must Not
- infer the newest run silently
- mutate stale run state before operator choice

## Expected Decision
block

## Expected Risk
resume_ambiguity
```

`skills/kws-codex-plan-executor/evals/golden-cases/unsafe-verification-block.md`:

```md
# unsafe-verification-block

## Scenario
A task has no acceptance command and the proposed substitute cannot prove the requested behavior.

## Input
- mode: headless
- acceptance_command: null
- substitute: echo done

## Must
- report unsafe verification substitute
- keep lifecycle_outcome away from finished

## Must Not
- mark completion_audit.passed=true
- treat echo done as product verification

## Expected Decision
block

## Expected Risk
unsafe_verification
```

`skills/kws-codex-plan-executor/evals/golden-cases/subagent-local-fallback.md`:

```md
# subagent-local-fallback

## Scenario
subagents=on is active but the tool policy requires explicit user delegation intent.

## Input
- mode: interactive
- subagents: on
- explicit_user_delegation_request: false

## Must
- run locally when dispatch selects local_fallback
- record subagent_strategy.mode=local_fallback with a concrete reason

## Must Not
- spawn a worker without an allowed policy
- leave completed write-capable task without subagent_strategy

## Expected Decision
local_fallback

## Expected Risk
subagent_policy_fallback
```

`skills/kws-codex-plan-executor/evals/golden-cases/task-packet-human-view.md`:

```md
# task-packet-human-view

## Scenario
A generated task packet view is included in handoff or subagent hot-tail context.

## Input
- task_packet: task_0.json
- view: task_0.md

## Must
- preserve files, task body, AC, verification, and forbidden globs
- show full-spec fallback when packet.spec.fallback_used=true

## Must Not
- treat markdown view as source of truth
- omit machine packet fields needed by dispatch or validation

## Expected Decision
render

## Expected Risk
human_view_parity
```

- [ ] **Step 3: Add the eval to the harness**

Modify `skills/kws-codex-plan-executor/evals/run.sh` by inserting this line near the other static checks:

```bash
python3 "$EVAL_DIR/check_markdown_golden_cases.py" >/dev/null
```

- [ ] **Step 4: Run the golden-case eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_markdown_golden_cases.py
```

Expected: PASS with JSON containing `"passed": true`.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/evals/check_markdown_golden_cases.py \
  skills/kws-codex-plan-executor/evals/golden-cases \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "test: add CPE markdown golden cases"
```

## Task 4: Verification Bundle Evidence and Advisory Risk Classes

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Create: `skills/kws-codex-plan-executor/evals/check_verification_bundle.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: structured `completion_audit.verification_evidence` objects with `class=verification_bundle`.
- Produces: validation for bundle `name`, `commands`, `status`, and `required`; broader advisory residual risk classes.

- [ ] **Step 1: Write the failing verification bundle eval**

Create `skills/kws-codex-plan-executor/evals/check_verification_bundle.py` with this content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from check_state_schema import base_state


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"


def run_validator(state: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="cpe-bundle-") as temp:
        path = Path(temp) / "state.json"
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def bundle() -> dict:
    return {
        "class": "verification_bundle",
        "name": "cpe_skill_change",
        "commands": ["./evals/run.sh", "python3 -m py_compile scripts/*.py evals/*.py", "bash -n evals/run.sh"],
        "status": "passed",
        "required": False,
    }


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    valid = base_state()
    valid["completion_audit"]["verification_evidence"].append(bundle())
    result = run_validator(valid)
    checks["valid_bundle_passes"] = result.returncode == 0
    if not checks["valid_bundle_passes"]:
        failures.append("valid verification bundle should pass: " + (result.stderr or result.stdout))

    missing_name = base_state()
    bad = bundle()
    del bad["name"]
    missing_name["completion_audit"]["verification_evidence"].append(bad)
    result = run_validator(missing_name)
    checks["bundle_missing_name_fails"] = result.returncode != 0 and "verification_bundle.name" in (
        result.stderr + result.stdout
    )
    if not checks["bundle_missing_name_fails"]:
        failures.append("verification bundle missing name should fail")

    empty_commands = base_state()
    bad = bundle()
    bad["commands"] = []
    empty_commands["completion_audit"]["verification_evidence"].append(bad)
    result = run_validator(empty_commands)
    checks["bundle_empty_commands_fails"] = result.returncode != 0 and "verification_bundle.commands" in (
        result.stderr + result.stdout
    )
    if not checks["bundle_empty_commands_fails"]:
        failures.append("verification bundle with empty commands should fail")

    advisory_risk = base_state()
    advisory_risk["completion_audit"]["residual_risk"] = [
        {
            "owner": "operator",
            "class": "test_scope_gap",
            "summary": "No API-key LLM judge was run; deterministic parser and policy checks passed.",
            "blocks_release": False,
        }
    ]
    result = run_validator(advisory_risk)
    checks["new_advisory_risk_class_passes"] = result.returncode == 0
    if not checks["new_advisory_risk_class_passes"]:
        failures.append("new advisory residual risk class should pass: " + (result.stderr or result.stdout))

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the eval to verify it fails**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_verification_bundle.py
```

Expected: FAIL because `test_scope_gap` is not yet an accepted residual risk class and bundle fields are not validated.

- [ ] **Step 3: Extend residual risk classes**

In `skills/kws-codex-plan-executor/scripts/validate_state.py`, extend `VALID_RESIDUAL_RISK_CLASSES` to include:

```python
    "environment_gap",
    "test_scope_gap",
    "third_party_drift",
    "manual_review_needed",
    "known_executor_debt",
```

Keep existing classes so older states remain valid.

- [ ] **Step 4: Add verification evidence validation**

Add this helper after `_validate_residual_risk_items`:

```python
def _validate_verification_evidence_items(evidence: list[object], errors: list[str]) -> None:
    for index, item in enumerate(evidence):
        prefix = f"completion_audit.verification_evidence[{index}]"
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"{prefix} string must be non-empty")
            continue
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be a string or object")
            continue
        evidence_class = item.get("class")
        if evidence_class is not None and not isinstance(evidence_class, str):
            errors.append(f"{prefix}.class must be a string when present")
        status = item.get("status")
        if status is not None and status not in {"passed", "failed", "skipped", "blocked"}:
            errors.append(f"{prefix}.status invalid")
        if evidence_class == "verification_bundle":
            if not _has_substantive_value(item.get("name")):
                errors.append(f"{prefix}.verification_bundle.name is required")
            commands = item.get("commands")
            if not isinstance(commands, list) or not any(isinstance(command, str) and command.strip() for command in commands):
                errors.append(f"{prefix}.verification_bundle.commands must contain at least one command")
            if item.get("status") not in {"passed", "failed", "skipped", "blocked"}:
                errors.append(f"{prefix}.verification_bundle.status is required")
            if "required" in item and not isinstance(item.get("required"), bool):
                errors.append(f"{prefix}.verification_bundle.required must be a boolean when present")
```

In `_validate_completion_audit`, after confirming `evidence` is a non-empty list, call:

```python
            _validate_verification_evidence_items(evidence, errors)
```

- [ ] **Step 5: Add the eval to the harness**

Modify `skills/kws-codex-plan-executor/evals/run.sh` by inserting:

```bash
python3 "$EVAL_DIR/check_verification_bundle.py" >/dev/null
```

- [ ] **Step 6: Run focused validation**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_verification_bundle.py
python3 evals/check_state_schema.py
```

Expected: both PASS with JSON containing `"passed": true`.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_verification_bundle.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat: validate CPE verification bundles"
```

## Task 5: Normalized Replay Coverage

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`

**Interfaces:**
- Consumes: `completion_audit.verification_evidence`, task summaries, and `context_health.hot_tail_summaries`.
- Produces: normalized fields `verification_evidence_classes`, `verification_bundle_names`, `task_summary_count`, and `hot_tail_summary_count`.

- [ ] **Step 1: Add failing replay expectations**

Modify `skills/kws-codex-plan-executor/evals/check_cpe_replay.py` so `finished_state()` includes:

```python
            "verification_evidence": [
                "python3 evals/check_task_packet.py",
                {
                    "class": "verification_bundle",
                    "name": "cpe_skill_change",
                    "commands": ["./evals/run.sh"],
                    "status": "passed",
                    "required": False,
                },
            ],
```

Also add task and context summary fields to the returned state:

```python
        "context_health": {
            "hot_tail_summaries": [
                {"task_id": "task_1", "summary": "Rendered task packet view."}
            ]
        },
        "tasks": {"task_1": {"fallback_spec_used": True, "next_task_summary": "Rendered task packet view."}},
```

Extend the `finished_yellow_replay_normalizes` check with:

```python
            and replay.get("verification_evidence_classes") == ["verification_bundle"]
            and replay.get("verification_bundle_names") == ["cpe_skill_change"]
            and replay.get("task_summary_count") == 1
            and replay.get("hot_tail_summary_count") == 1
```

- [ ] **Step 2: Run replay eval to verify it fails**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_cpe_replay.py
```

Expected: FAIL because normalized replay does not yet emit the new fields.

- [ ] **Step 3: Implement replay helpers**

In `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`, add:

```python
def verification_evidence_classes(audit: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in audit.get("verification_evidence", []):
        if isinstance(item, dict) and isinstance(item.get("class"), str) and item["class"] not in result:
            result.append(item["class"])
    return result


def verification_bundle_names(audit: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in audit.get("verification_evidence", []):
        if (
            isinstance(item, dict)
            and item.get("class") == "verification_bundle"
            and isinstance(item.get("name"), str)
            and item["name"] not in result
        ):
            result.append(item["name"])
    return result


def task_summary_count(tasks: dict[str, Any]) -> int:
    return sum(
        1
        for task in tasks.values()
        if isinstance(task, dict) and isinstance(task.get("next_task_summary"), str) and task["next_task_summary"].strip()
    )


def hot_tail_summary_count(state: dict[str, Any]) -> int:
    health = state.get("context_health") if isinstance(state.get("context_health"), dict) else {}
    summaries = health.get("hot_tail_summaries")
    if not isinstance(summaries, list):
        return 0
    return sum(1 for item in summaries if isinstance(item, dict) and isinstance(item.get("summary"), str) and item["summary"].strip())
```

Add these keys to the `normalize()` return object:

```python
        "verification_evidence_classes": verification_evidence_classes(completion),
        "verification_bundle_names": verification_bundle_names(completion),
        "task_summary_count": task_summary_count(tasks),
        "hot_tail_summary_count": hot_tail_summary_count(state),
```

- [ ] **Step 4: Run replay eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_cpe_replay.py
```

Expected: PASS with JSON containing `"passed": true`.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py \
  skills/kws-codex-plan-executor/evals/check_cpe_replay.py
git commit -m "feat: normalize CPE human harness evidence"
```

## Task 6: Runtime Contract and Operator Documentation

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md`

**Interfaces:**
- Consumes: behavior implemented in Tasks 1-5.
- Produces: updated operator contracts and docs for generated packet views, summaries, markdown golden cases, bundle evidence, and advisory risk classes.

- [ ] **Step 1: Update `SKILL.md` core invariants**

In `skills/kws-codex-plan-executor/SKILL.md`, add these bullets under Core Invariants after the task packet/context health bullets:

```markdown
- Task packet human views are generated derivatives of task packet JSON. They
  may be included in handoff, prompt hot-tail, and subagent task context, but
  the JSON packet and state remain authoritative.
- Completed tasks may record `next_task_summary` as a one-line hot-tail hint.
  This summary never replaces structured task status, verification evidence,
  dispatch decisions, or completion audit state.
- Completion audit verification evidence may include structured
  `class=verification_bundle` entries for project-level command bundles. These
  entries classify evidence and do not replace per-task acceptance commands.
- Structured residual risk classes are advisory readability metadata. They
  cannot override `completion_audit.passed`, state validation, or release
  blocker rules.
```

- [ ] **Step 2: Update validation matrix**

In `SKILL.md` Validation Matrix, add `task packet human view evidence when generated`, `markdown golden-case evals when policy cases change`, and `verification bundle evidence when project-level bundles are used` to the `interactive` and `headless` rows.

- [ ] **Step 3: Update README validation list**

In `skills/kws-codex-plan-executor/README.md`, add these lines to the validation command block:

```bash
python3 evals/check_task_packet_view.py
python3 evals/check_context_summary.py
python3 evals/check_markdown_golden_cases.py
python3 evals/check_verification_bundle.py
```

Add a short paragraph after the task packet paragraph:

```markdown
Task packet human views are generated markdown derivatives for operators,
handoff recipients, and subagents. The JSON packet remains the source of truth;
the markdown view must preserve files, task body, AC, verification, forbidden
globs, context budget, and full-spec fallback warnings.
```

- [ ] **Step 4: Update state schema docs**

In `references/state-schema.md`, add examples for `task_packet_view_path`, `task_packet_view_sha256`, `next_task_summary`, `context_health.hot_tail_summaries`, `verification_bundle`, and the advisory residual risk classes from the spec.

- [ ] **Step 5: Update execution cycle docs**

In `references/execution-cycle.md`, add a step after task packet creation:

```markdown
When task packets are present, generate task packet human views under
`$RUN_DIR/task_packets/*.md` before prompt, handoff, or subagent context uses
them. Treat these views as derived readability artifacts only.
```

Add a finalization note:

```markdown
When using project-level verification bundles, record them as structured
`completion_audit.verification_evidence` objects with
`class=verification_bundle`; keep acceptance command evidence separate.
```

- [ ] **Step 6: Update eval docs**

In `docs/evals-and-verification.md` and `docs/eval-coverage-cpe.md`, add the four new checks and list the five markdown golden cases.

- [ ] **Step 7: Run docs grep checks**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
rg -n "task_packet_view|next_task_summary|verification_bundle|golden-cases|test_scope_gap" SKILL.md README.md references docs evals scripts
```

Expected: output includes the updated runtime docs, eval docs, eval files, and validator/replay code.

- [ ] **Step 8: Commit Task 6**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md
git commit -m "docs: document CPE human harness surfaces"
```

## Task 7: Closeout, Baseline, History, and Full Verification

**Files:**
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `skills/kws-codex-plan-executor/evals/baselines/v2.24.0.json` only if `./evals/run.sh --update-baseline` reports an intentional deterministic baseline change

**Interfaces:**
- Consumes: all previous task changes.
- Produces: final verification evidence and documented release note for the implementation.

- [ ] **Step 1: Update history and architecture**

Add a `v2.24.x` unreleased-style entry to `HISTORY.md`:

```markdown
## v2.24.x - Human-readable harness surfaces

- Added generated task packet markdown views for handoff, prompt, and subagent readability.
- Added optional one-line completed-task summaries for hot-tail context.
- Added markdown golden-case evals for operator-readable policy regressions.
- Added structured verification bundle evidence and advisory residual risk classes.
- Extended normalized replay to summarize bundle classes and summary counts.
```

In `ARCHITECTURE.md`, add a short paragraph to the task packet/state section:

```markdown
Human-readable task views are generated from task packet JSON and stored with
orchestration artifacts. They improve operator and subagent readability but do
not participate as source-of-truth state. State validation only trusts the JSON
packet, task state, and completion audit fields.
```

- [ ] **Step 2: Run focused evals**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet_view.py
python3 evals/check_context_summary.py
python3 evals/check_markdown_golden_cases.py
python3 evals/check_verification_bundle.py
python3 evals/check_cpe_replay.py
python3 evals/check_state_schema.py
```

Expected: every command prints JSON with `"passed": true`.

- [ ] **Step 3: Run full CPE eval harness**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
```

Expected: exit 0. If the harness reports a baseline mismatch, inspect the partial output. Only run `./evals/run.sh --update-baseline` when the diff is caused by intentional deterministic output changes from this plan.

- [ ] **Step 4: Run syntax checks**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Expected: both commands exit 0.

- [ ] **Step 5: Run repository checks**

Run:

```bash
cd /Users/kws/source/private/Archive
bun run check
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 6: Handle Graphify evidence**

Run:

```bash
cd /Users/kws/source/private/Archive
python3 scripts/check_graphify_freshness.py --repo-root /Users/kws/source/private/Archive --output /tmp/cpe-human-harness-graphify-before.json
```

Expected: if the command reports stale Graphify because docs/runtime structure changed, run:

```bash
graphify update .
python3 scripts/check_graphify_freshness.py --repo-root /Users/kws/source/private/Archive --update-ran --output /tmp/cpe-human-harness-graphify-after.json
```

If `graphify-out/` remains ignored or unchanged, record the command output in `docs/verification-log.md` instead of staging ignored artifacts.

- [ ] **Step 7: Update verification log**

Add a dated entry to `skills/kws-codex-plan-executor/docs/verification-log.md` with the exact commands from Steps 2-6 and their pass/fail status. Include honest notes for any skipped command and the reason.

- [ ] **Step 8: Commit closeout docs and optional baseline**

Run:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
git add skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/docs/verification-log.md
```

If a baseline update was intentionally produced, also run:

```bash
git add skills/kws-codex-plan-executor/evals/baselines/v2.24.0.json
```

Commit:

```bash
git commit -m "docs: record CPE human harness verification"
```

## Final Review Checklist

- [ ] `scripts/render_task_packet_view.py` is deterministic and has no external dependencies.
- [ ] Markdown task views are generated artifacts and never replace task packet JSON.
- [ ] `next_task_summary` and `hot_tail_summaries` reject multiline content and forbidden durable-output markers.
- [ ] Markdown golden cases have all required sections and expected decision/risk fields.
- [ ] Verification bundle evidence is structured and remains separate from acceptance command evidence.
- [ ] New advisory residual-risk classes pass validation but cannot bypass `blocks_release=true` rules.
- [ ] Normalized replay includes verification evidence classes, bundle names, task summary count, and hot-tail summary count.
- [ ] `./evals/run.sh`, `python3 -m py_compile scripts/*.py evals/*.py`, `bash -n evals/run.sh`, `bun run check`, and `git diff --check` pass or have explicit honest blockers recorded.
