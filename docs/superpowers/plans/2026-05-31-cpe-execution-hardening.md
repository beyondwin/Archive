# CPE Execution Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden `kws-codex-plan-executor` with deterministic prompt cache audits, Graphify freshness audits, and subagent pre-dispatch decisions.

**Architecture:** Add focused Python helpers under `skills/kws-codex-plan-executor/scripts/` and deterministic checks under `skills/kws-codex-plan-executor/evals/`. Keep CPE state authoritative in `~/.codex/orchestrator/<run_id>/state.json`; scripts emit JSON evidence and `validate_state.py` enforces finished-run gates.

**Tech Stack:** Python 3 standard library, Bash eval harness, Markdown skill docs, JSON state.

---

## Scope Check

The approved spec covers three related hardening surfaces inside one skill
package. They are implemented together because they share the same completion
audit and state-validation boundary:

- prompt cache audit evidence,
- Graphify freshness audit evidence,
- dispatch decision evidence.

No Waygent runtime package, Lens package, or legacy Python AgentLens tree is in
scope.

## File Structure

Create:

- `skills/kws-codex-plan-executor/references/cache-strategy.md`
  - Documents stable-prefix/hot-tail rules and marker contract.
- `skills/kws-codex-plan-executor/scripts/audit_prompt_cache.py`
  - Reads checked prompt artifacts and emits stable-prefix hashes, byte counts,
    and dynamic marker violations.
- `skills/kws-codex-plan-executor/scripts/record_cache_observation.py`
  - Appends optional cache-token observations to a state file without treating
    missing provider counters as zero.
- `skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py`
  - Reads `graphify-out/GRAPH_REPORT.md`, compares built commit with HEAD, and
    emits freshness/update-evidence JSON.
- `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
  - Converts the subagent pre-dispatch checklist into a `delegate`,
    `local_fallback`, or `block` JSON decision.
- `skills/kws-codex-plan-executor/evals/check_prompt_cache_audit.py`
- `skills/kws-codex-plan-executor/evals/check_cache_observations.py`
- `skills/kws-codex-plan-executor/evals/check_graphify_freshness.py`
- `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`

Modify:

- `skills/kws-codex-plan-executor/SKILL.md`
- `skills/kws-codex-plan-executor/README.md`
- `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- `skills/kws-codex-plan-executor/HISTORY.md`
- `skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt`
- `skills/kws-codex-plan-executor/references/execution-cycle.md`
- `skills/kws-codex-plan-executor/references/headless-runner.md`
- `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- `skills/kws-codex-plan-executor/references/prompt-export-checklist.md`
- `skills/kws-codex-plan-executor/references/state-schema.md`
- `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- `skills/kws-codex-plan-executor/scripts/validate_state.py`
- `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- `skills/kws-codex-plan-executor/evals/check_skill_contract.py`
- `skills/kws-codex-plan-executor/evals/run.sh`

## Task 1: Prompt Cache Audit

**Files:**

- Create: `skills/kws-codex-plan-executor/references/cache-strategy.md`
- Create: `skills/kws-codex-plan-executor/scripts/audit_prompt_cache.py`
- Create: `skills/kws-codex-plan-executor/evals/check_prompt_cache_audit.py`
- Modify: `skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt`
- Modify: `skills/kws-codex-plan-executor/references/verifier-prompt.md`
- Modify: `skills/kws-codex-plan-executor/references/prompt-export-checklist.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

- [ ] **Step 1: Write the failing prompt cache audit eval**

Create `skills/kws-codex-plan-executor/evals/check_prompt_cache_audit.py` with
these test cases:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_prompt_cache.py"


def run_audit(root: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = root / "audit.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--skill-root", str(root), "--output", str(output)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def write_template(root: Path, text: str) -> None:
    path = root / "templates" / "fresh-session-prompt.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    refs = root / "references"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "verifier-prompt.md").write_text(text, encoding="utf-8")


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-cache-audit-") as temp:
        root = Path(temp)
        write_template(root, "plain prompt without markers\n")
        result, data = run_audit(root)
        checks["missing_markers_fail"] = result.returncode != 0 and data.get("passed") is False
        if not checks["missing_markers_fail"]:
            failures.append("templates without cache markers should fail")

    with tempfile.TemporaryDirectory(prefix="cpe-cache-audit-") as temp:
        root = Path(temp)
        write_template(
            root,
            "<!-- CPE_CACHE_STABLE_PREFIX_START -->\n"
            "Stable instructions {{STATE_PATH}}\n"
            "<!-- CPE_CACHE_STABLE_PREFIX_END -->\n"
            "<!-- CPE_CACHE_HOT_TAIL_START -->\n"
            "Dynamic tail\n",
        )
        result, data = run_audit(root)
        violations = json.dumps(data.get("dynamic_marker_violations", []), ensure_ascii=False)
        checks["dynamic_placeholder_in_stable_prefix_fails"] = (
            result.returncode != 0 and "{{STATE_PATH}}" in violations
        )
        if not checks["dynamic_placeholder_in_stable_prefix_fails"]:
            failures.append("dynamic placeholder inside stable prefix should fail")

    with tempfile.TemporaryDirectory(prefix="cpe-cache-audit-") as temp:
        root = Path(temp)
        before = (
            "<!-- CPE_CACHE_STABLE_PREFIX_START -->\n"
            "Stable instructions\n"
            "<!-- CPE_CACHE_STABLE_PREFIX_END -->\n"
            "<!-- CPE_CACHE_HOT_TAIL_START -->\n"
            "Task one\n"
        )
        write_template(root, before)
        result_one, first = run_audit(root)
        write_template(root, before.replace("Task one", "Task two with a different run id"))
        result_two, second = run_audit(root)
        name = "templates/fresh-session-prompt.txt"
        checks["hot_tail_change_keeps_stable_hash"] = (
            result_one.returncode == 0
            and result_two.returncode == 0
            and first["stable_prefix_hashes"][name] == second["stable_prefix_hashes"][name]
        )
        if not checks["hot_tail_change_keeps_stable_hash"]:
            failures.append("hot-tail-only changes should not alter stable-prefix hash")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the failing eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_prompt_cache_audit.py
```

Expected: FAIL because `scripts/audit_prompt_cache.py` does not exist.

- [ ] **Step 3: Create the cache strategy reference**

Create `skills/kws-codex-plan-executor/references/cache-strategy.md`:

````markdown
# Cache Strategy

CPE treats prompt caching as a prefix-stability problem. The executor does not
assume a provider-specific cache-control API is available.

## Terms

- Stable prefix: role instructions, safety boundaries, required skills, output
  schemas, and invariant checklists.
- Hot tail: plan paths, run ids, state paths, timestamps, git status, task
  packets, changed files, diffs, decisions, verification output, and retry
  context.
- Cache-hostile drift: dynamic material inserted before stable prompt content.

## Rules

1. Keep `mode=interactive` as the default.
2. Put stable prefix before hot tail.
3. Do not put run ids, state paths, task packet paths, timestamps, git status,
   diffs, decisions, or absolute home paths in stable prefix blocks.
4. Put task/run payloads in the hot tail.
5. Treat provider cache-token counters as optional telemetry.

## Markers

Checked prompt artifacts use:

```text
<!-- CPE_CACHE_STABLE_PREFIX_START -->
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
```

All dynamic `{{...}}` placeholders belong after the stable-prefix end marker
unless they are explicitly allowlisted by `scripts/audit_prompt_cache.py`.
````

- [ ] **Step 4: Implement `audit_prompt_cache.py`**

Create `skills/kws-codex-plan-executor/scripts/audit_prompt_cache.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


START = "<!-- CPE_CACHE_STABLE_PREFIX_START -->"
END = "<!-- CPE_CACHE_STABLE_PREFIX_END -->"
HOT = "<!-- CPE_CACHE_HOT_TAIL_START -->"
CHECKED_FILES = (
    "templates/fresh-session-prompt.txt",
    "references/verifier-prompt.md",
)
ALLOWLISTED_PLACEHOLDERS = {"{{STATIC_SKILL_NAME}}", "{{STATIC_OUTPUT_SCHEMA_NAME}}"}
DYNAMIC_PATTERNS = (
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"\bSTATE_PATH\b|\bRUN_ID\b|\bTASK_PACKET\b|\bGIT_STATUS\b"),
    re.compile(r"~?/\.codex/(?:orchestrator|worktrees)/"),
    re.compile(r"\bgit status\b|\bgit diff\b|\bgraphify update\b"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_prefix(path: Path) -> tuple[str | None, list[dict]]:
    text = path.read_text(encoding="utf-8")
    violations: list[dict] = []
    if text.count(START) != 1:
        violations.append({"file": str(path), "kind": "marker_count", "marker": START, "count": text.count(START)})
    if text.count(END) != 1:
        violations.append({"file": str(path), "kind": "marker_count", "marker": END, "count": text.count(END)})
    if text.count(HOT) != 1:
        violations.append({"file": str(path), "kind": "marker_count", "marker": HOT, "count": text.count(HOT)})
    if violations:
        return None, violations
    start = text.index(START) + len(START)
    end = text.index(END)
    hot = text.index(HOT)
    if not start <= end < hot:
        violations.append({"file": str(path), "kind": "marker_order", "detail": "stable prefix must end before hot tail"})
        return None, violations
    prefix = text[start:end]
    for pattern in DYNAMIC_PATTERNS:
        for match in pattern.finditer(prefix):
            token = match.group(0)
            if token in ALLOWLISTED_PLACEHOLDERS:
                continue
            violations.append({"file": str(path), "kind": "dynamic_marker", "token": token})
    return prefix, violations


def audit(skill_root: Path) -> dict:
    stable_prefix_hashes: dict[str, str] = {}
    stable_prefix_bytes: dict[str, int] = {}
    dynamic_marker_violations: list[dict] = []
    missing_files: list[str] = []
    for relative in CHECKED_FILES:
        path = skill_root / relative
        if not path.is_file():
            missing_files.append(relative)
            continue
        prefix, violations = stable_prefix(path)
        dynamic_marker_violations.extend(
            {**item, "file": relative} for item in violations
        )
        if prefix is not None:
            encoded = prefix.encode("utf-8")
            stable_prefix_hashes[relative] = hashlib.sha256(encoded).hexdigest()
            stable_prefix_bytes[relative] = len(encoded)
    passed = not dynamic_marker_violations and not missing_files
    return {
        "schema_version": "1",
        "checked_at": now_iso(),
        "passed": passed,
        "stable_prefix_hashes": stable_prefix_hashes,
        "stable_prefix_bytes": stable_prefix_bytes,
        "dynamic_marker_violations": dynamic_marker_violations,
        "missing_files": missing_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit CPE prompt cache boundaries.")
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit(Path(args.skill_root).resolve())
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Add prompt cache markers to checked artifacts**

Edit `templates/fresh-session-prompt.txt` and `references/verifier-prompt.md` so
the invariant instructions come first:

```markdown
<!-- CPE_CACHE_STABLE_PREFIX_START -->

[existing invariant role, safety, execution, output-schema, and skill-bootstrap
instructions]

<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->

[existing plan paths, state paths, task paths, workspace paths, git status,
dynamic checklist values, and `{{...}}` template tokens]
```

Move every existing dynamic `{{...}}` placeholder below
`CPE_CACHE_HOT_TAIL_START`.

- [ ] **Step 6: Run GREEN checks for Task 1**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_prompt_cache_audit.py
python3 scripts/audit_prompt_cache.py --skill-root . --output /tmp/cpe-prompt-audit.json
python3 -m py_compile scripts/audit_prompt_cache.py evals/check_prompt_cache_audit.py
```

Expected: all commands pass, and `/tmp/cpe-prompt-audit.json` has
`"passed": true`.

- [ ] **Step 7: Wire Task 1 into the eval harness**

Add this line near the other deterministic checks in `evals/run.sh`:

```bash
python3 "$EVAL_DIR/check_prompt_cache_audit.py" >/dev/null
```

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
bash -n evals/run.sh
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/references/cache-strategy.md \
  skills/kws-codex-plan-executor/scripts/audit_prompt_cache.py \
  skills/kws-codex-plan-executor/evals/check_prompt_cache_audit.py \
  skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt \
  skills/kws-codex-plan-executor/references/verifier-prompt.md \
  skills/kws-codex-plan-executor/references/prompt-export-checklist.md \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "test(cpe): add prompt cache audit"
```

## Task 2: Cache Observation State

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/record_cache_observation.py`
- Create: `skills/kws-codex-plan-executor/evals/check_cache_observations.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

- [ ] **Step 1: Write the failing cache observation eval**

Create `evals/check_cache_observations.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "scripts" / "record_cache_observation.py"
VALIDATOR = ROOT / "scripts" / "validate_state.py"


def run_validator(payload: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="cpe-cache-state-") as temp:
        path = Path(temp) / "state.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run([sys.executable, str(VALIDATOR), str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-cache-state-") as temp:
        state_path = Path(temp) / "state.json"
        state = check_state_schema.v220_state()
        state_path.write_text(json.dumps(state), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(RECORDER),
                "--state",
                str(state_path),
                "--unit",
                "task_0",
                "--mode",
                "interactive",
                "--model",
                "gpt-5",
                "--input-tokens",
                "1000",
                "--output-tokens",
                "200",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        data = json.loads(state_path.read_text(encoding="utf-8"))
        observation = data.get("cache_observations", [{}])[-1]
        checks["recorder_appends_null_cache_counters"] = (
            result.returncode == 0
            and observation.get("cached_read_tokens") is None
            and observation.get("cached_write_tokens") is None
        )
        if not checks["recorder_appends_null_cache_counters"]:
            failures.append("missing cache counters should be stored as null")

    valid = check_state_schema.v220_state()
    valid["cache_strategy"] = {
        "mode": "interactive-default",
        "stable_prefix_policy": "static-first-hot-tail",
        "provider_cache_control": "unavailable",
        "prompt_audit_version": "1",
    }
    valid["cache_observations"] = []
    valid["prompt_audit"] = {
        "last_checked_at": "2026-05-31T00:00:00Z",
        "stable_prefix_hashes": {"templates/fresh-session-prompt.txt": "a" * 64},
        "stable_prefix_bytes": {"templates/fresh-session-prompt.txt": 100},
        "dynamic_marker_violations": [],
    }
    result = run_validator(valid)
    checks["valid_cache_fields_pass"] = result.returncode == 0
    if not checks["valid_cache_fields_pass"]:
        failures.append("valid optional cache fields should pass: " + (result.stderr or result.stdout))

    invalid = dict(valid)
    invalid["prompt_audit"] = dict(valid["prompt_audit"])
    invalid["prompt_audit"]["dynamic_marker_violations"] = [{"file": "templates/fresh-session-prompt.txt"}]
    result = run_validator(invalid)
    checks["finished_prompt_audit_violations_fail"] = result.returncode != 0 and "prompt_audit.dynamic_marker_violations" in (result.stderr + result.stdout)
    if not checks["finished_prompt_audit_violations_fail"]:
        failures.append("finished state with prompt audit violations should fail")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the failing eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_cache_observations.py
```

Expected: FAIL because `record_cache_observation.py` and validator support do
not exist.

- [ ] **Step 3: Implement `record_cache_observation.py`**

Create `scripts/record_cache_observation.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


TOKEN_FIELDS = ("input_tokens", "cached_read_tokens", "cached_write_tokens", "output_tokens")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_token(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("token counts must be non-negative")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Append optional cache token observation to CPE state.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--source", default="codex-metadata")
    parser.add_argument("--input-tokens")
    parser.add_argument("--cached-read-tokens")
    parser.add_argument("--cached-write-tokens")
    parser.add_argument("--output-tokens")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    observation = {
        "observed_at": now_iso(),
        "source": args.source,
        "unit": args.unit,
        "mode": args.mode,
        "model": args.model,
        "input_tokens": parse_token(args.input_tokens),
        "cached_read_tokens": parse_token(args.cached_read_tokens),
        "cached_write_tokens": parse_token(args.cached_write_tokens),
        "output_tokens": parse_token(args.output_tokens),
        "notes": args.notes,
    }
    state.setdefault("cache_observations", []).append(observation)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(observation, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add cache validation to `validate_state.py`**

Add constants near the existing validation constants:

```python
VALID_CACHE_STRATEGY_MODES = {"interactive-default", "headless-explicit", "prompt-export", "handoff-export"}
VALID_PROVIDER_CACHE_CONTROL = {"unavailable", "available-unused", "available-enabled", "unknown"}
TOKEN_FIELDS = {"input_tokens", "cached_read_tokens", "cached_write_tokens", "output_tokens"}
```

Add function before `validate()`:

```python
def _validate_cache_fields(data: dict, errors: list[str]) -> None:
    strategy = data.get("cache_strategy")
    if strategy is not None:
        if not isinstance(strategy, dict):
            errors.append("cache_strategy must be an object")
        else:
            if strategy.get("mode") not in VALID_CACHE_STRATEGY_MODES:
                errors.append(f"cache_strategy.mode must be one of {sorted(VALID_CACHE_STRATEGY_MODES)}")
            if strategy.get("provider_cache_control") not in VALID_PROVIDER_CACHE_CONTROL:
                errors.append(f"cache_strategy.provider_cache_control must be one of {sorted(VALID_PROVIDER_CACHE_CONTROL)}")
            for key in ("stable_prefix_policy", "prompt_audit_version"):
                if key in strategy and not _has_substantive_value(strategy.get(key)):
                    errors.append(f"cache_strategy.{key} must be non-empty")

    observations = data.get("cache_observations", [])
    if observations is not None:
        if not isinstance(observations, list):
            errors.append("cache_observations must be a list")
        else:
            for index, observation in enumerate(observations):
                prefix = f"cache_observations[{index}]"
                if not isinstance(observation, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                for key in ("observed_at", "source", "unit", "mode", "model"):
                    if not _has_substantive_value(observation.get(key)):
                        errors.append(f"{prefix}.{key} must be non-empty")
                if _parse_ts(observation.get("observed_at")) is None:
                    errors.append(f"{prefix}.observed_at must be an ISO timestamp")
                for key in sorted(TOKEN_FIELDS):
                    value = observation.get(key)
                    if value is not None and (not isinstance(value, int) or value < 0):
                        errors.append(f"{prefix}.{key} must be a non-negative integer or null")

    prompt_audit = data.get("prompt_audit")
    if prompt_audit is not None:
        if not isinstance(prompt_audit, dict):
            errors.append("prompt_audit must be an object")
        else:
            if _parse_ts(prompt_audit.get("last_checked_at")) is None:
                errors.append("prompt_audit.last_checked_at must be an ISO timestamp")
            for key in ("stable_prefix_hashes", "stable_prefix_bytes"):
                if key in prompt_audit and not isinstance(prompt_audit[key], dict):
                    errors.append(f"prompt_audit.{key} must be an object")
            violations = prompt_audit.get("dynamic_marker_violations")
            if violations is not None and not isinstance(violations, list):
                errors.append("prompt_audit.dynamic_marker_violations must be a list")
            if data.get("lifecycle_outcome") == "finished" and violations:
                errors.append("prompt_audit.dynamic_marker_violations must be empty when lifecycle_outcome is finished")
```

Call it in `validate()` after `_validate_command_observations(data, errors)`:

```python
    _validate_cache_fields(data, errors)
```

- [ ] **Step 5: Run GREEN checks for Task 2**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_cache_observations.py
python3 evals/check_state_schema.py
python3 -m py_compile scripts/record_cache_observation.py scripts/validate_state.py evals/check_cache_observations.py evals/check_state_schema.py
```

Expected: all commands pass.

- [ ] **Step 6: Wire Task 2 into docs and harness**

Add to `evals/run.sh`:

```bash
python3 "$EVAL_DIR/check_cache_observations.py" >/dev/null
```

Add cache state fields to `references/state-schema.md` and
`docs/state-and-logging.md` using the JSON shape from the approved spec.

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
bash -n evals/run.sh
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/record_cache_observation.py \
  skills/kws-codex-plan-executor/evals/check_cache_observations.py \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat(cpe): record cache observations"
```

## Task 3: Graphify Freshness Audit

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py`
- Create: `skills/kws-codex-plan-executor/evals/check_graphify_freshness.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

- [ ] **Step 1: Write the failing Graphify eval**

Create `evals/check_graphify_freshness.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_graphify_freshness.py"


def init_repo(repo: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Eval\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def write_report(repo: Path, commit: str) -> None:
    out = repo / "graphify-out"
    out.mkdir()
    (out / "GRAPH_REPORT.md").write_text(
        "# Graph Report\n\n## Graph Freshness\n- Built from commit: `" + commit[:8] + "`\n",
        encoding="utf-8",
    )


def run_check(repo: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "report.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--output", str(output), *extra],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-graphify-") as temp:
        repo = Path(temp)
        head = init_repo(repo)
        write_report(repo, head)
        result, data = run_check(repo)
        checks["fresh_report_passes"] = result.returncode == 0 and data.get("fresh") is True
        if not checks["fresh_report_passes"]:
            failures.append("fresh graph report should pass")

    with tempfile.TemporaryDirectory(prefix="cpe-graphify-") as temp:
        repo = Path(temp)
        init_repo(repo)
        write_report(repo, "0" * 40)
        result, data = run_check(repo)
        checks["stale_report_detected"] = result.returncode != 0 and data.get("fresh") is False and data.get("update_required") is True
        if not checks["stale_report_detected"]:
            failures.append("stale graph report should require update")

    with tempfile.TemporaryDirectory(prefix="cpe-graphify-") as temp:
        repo = Path(temp)
        init_repo(repo)
        result, data = run_check(repo)
        checks["missing_report_classified"] = result.returncode == 0 and data.get("graphify_present") is False and data.get("warnings")
        if not checks["missing_report_classified"]:
            failures.append("missing graph report should be classified as a warning")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the failing eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_graphify_freshness.py
```

Expected: FAIL because `scripts/check_graphify_freshness.py` does not exist.

- [ ] **Step 3: Implement `check_graphify_freshness.py`**

Create `scripts/check_graphify_freshness.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BUILT_RE = re.compile(r"Built from commit:\s*`?([0-9a-fA-F]{7,40})`?")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_head(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def is_ignored(repo: Path, path: Path) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(repo))], cwd=repo)
    return result.returncode == 0


def changed_outputs(repo: Path) -> bool:
    result = subprocess.run(["git", "status", "--short", "--", "graphify-out"], cwd=repo, text=True, stdout=subprocess.PIPE)
    return bool(result.stdout.strip())


def check(repo: Path, graph_report: Path, update_ran: bool) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    head = git_head(repo)
    if not graph_report.is_file():
        warnings.append("graphify report not found")
        return {
            "schema_version": "1",
            "checked_at": now_iso(),
            "graph_report": str(graph_report.relative_to(repo)) if graph_report.is_absolute() else str(graph_report),
            "graphify_present": False,
            "built_commit": None,
            "head_commit": head,
            "fresh": None,
            "update_required": False,
            "update_evidence": {"command": "graphify update .", "ran": update_ran, "tracked_outputs_changed": False, "ignored_outputs_note": ""},
            "warnings": warnings,
            "errors": errors,
        }
    text = graph_report.read_text(encoding="utf-8")
    match = BUILT_RE.search(text)
    built = match.group(1) if match else None
    if not built:
        errors.append("Built from commit not found")
    fresh = bool(built and head.startswith(built))
    ignored = is_ignored(repo, repo / "graphify-out")
    tracked_changed = changed_outputs(repo)
    note = "graphify-out is ignored; update evidence is command-only" if ignored and update_ran else ""
    if not fresh and not update_ran:
        errors.append("graphify report is stale and update evidence is missing")
    return {
        "schema_version": "1",
        "checked_at": now_iso(),
        "graph_report": str(graph_report.relative_to(repo)),
        "graphify_present": True,
        "built_commit": built,
        "head_commit": head,
        "fresh": fresh,
        "update_required": not fresh,
        "update_evidence": {
            "command": "graphify update .",
            "ran": update_ran,
            "tracked_outputs_changed": tracked_changed,
            "ignored_outputs_note": note,
        },
        "warnings": warnings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Graphify report freshness.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--graph-report")
    parser.add_argument("--update-ran", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    report_path = Path(args.graph_report).resolve() if args.graph_report else repo / "graphify-out" / "GRAPH_REPORT.md"
    report = check(repo, report_path, args.update_ran)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add Graphify validation to `validate_state.py`**

Add function:

```python
def _validate_graphify_audit(data: dict, errors: list[str]) -> None:
    audit = data.get("graphify_audit")
    if audit is None:
        return
    if not isinstance(audit, dict):
        errors.append("graphify_audit must be an object")
        return
    if audit.get("schema_version") != "1":
        errors.append("graphify_audit.schema_version must be 1")
    for key in ("graphify_present", "update_required"):
        if key in audit and not isinstance(audit[key], bool):
            errors.append(f"graphify_audit.{key} must be a boolean")
    if audit.get("fresh") is not None and not isinstance(audit.get("fresh"), bool):
        errors.append("graphify_audit.fresh must be a boolean or null")
    for key in ("warnings", "errors"):
        if key in audit and not isinstance(audit[key], list):
            errors.append(f"graphify_audit.{key} must be a list")
    if data.get("lifecycle_outcome") == "finished" and audit.get("errors"):
        errors.append("graphify_audit.errors must be empty when lifecycle_outcome is finished")
```

Call it in `validate()` after `_validate_cache_fields(data, errors)`.

- [ ] **Step 5: Run GREEN checks for Task 3**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_graphify_freshness.py
python3 evals/check_state_schema.py
python3 -m py_compile scripts/check_graphify_freshness.py scripts/validate_state.py evals/check_graphify_freshness.py
```

Expected: all commands pass.

- [ ] **Step 6: Wire Graphify docs and harness**

Add to `evals/run.sh`:

```bash
python3 "$EVAL_DIR/check_graphify_freshness.py" >/dev/null
```

Update `references/execution-cycle.md` so the Graphify step runs:

```bash
python3 scripts/check_graphify_freshness.py --repo-root "$WORKTREE_ABS" --output "$RUN_DIR/graphify_audit.json"
```

When `graphify update .` was run after code or documentation-structure changes,
the documented command becomes:

```bash
graphify update .
python3 scripts/check_graphify_freshness.py --repo-root "$WORKTREE_ABS" --update-ran --output "$RUN_DIR/graphify_audit.json"
```

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
bash -n evals/run.sh
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  skills/kws-codex-plan-executor/evals/check_graphify_freshness.py \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat(cpe): audit graphify freshness"
```

## Task 4: Subagent Pre-Dispatch Decisions

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Create: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

- [ ] **Step 1: Write the failing dispatch eval**

Create `evals/check_preflight_dispatch.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preflight_dispatch.py"


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)
    (repo / "docs").mkdir()
    (repo / "docs/example.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/example.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def write_packet(path: Path, files: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task": {"id": "task_0", "files": files},
                "write_policy": {
                    "allowed_write_globs": ["docs/example.md"],
                    "forbidden_write_globs": [".git/**", "graphify-out/**"],
                },
            }
        ),
        encoding="utf-8",
    )


def run_dispatch(repo: Path, state_path: Path, packet_path: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "dispatch.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(state_path),
            "--task-id",
            "task_0",
            "--task-packet",
            str(packet_path),
            "--repo-root",
            str(repo),
            "--write-scope",
            "docs/example.md",
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(check_state_schema.v220_state()), encoding="utf-8")
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["clean_task_delegates"] = result.returncode == 0 and data.get("decision") == "delegate"
        if not checks["clean_task_delegates"]:
            failures.append("clean task packet should delegate")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "docs/example.md").write_text("dirty\n", encoding="utf-8")
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(check_state_schema.v220_state()), encoding="utf-8")
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["dirty_overlap_blocks"] = result.returncode != 0 and data.get("decision") == "block"
        if not checks["dirty_overlap_blocks"]:
            failures.append("dirty overlap should block dispatch")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the failing eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
```

Expected: FAIL because `scripts/preflight_dispatch.py` does not exist.

- [ ] **Step 3: Implement `preflight_dispatch.py`**

Create `scripts/preflight_dispatch.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path


def git_changed(repo: Path) -> set[str]:
    files: set[str] = set()
    for args in (["diff", "--name-only", "HEAD"], ["ls-files", "--others", "--exclude-standard"]):
        result = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        files.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return files


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def decision_payload(task_id: str, decision: str, reason: str, write_scope: list[str], failed: list[str]) -> dict:
    mode = "delegated" if decision == "delegate" else "local_fallback"
    return {
        "schema_version": "1",
        "task_id": task_id,
        "decision": decision,
        "reason": reason,
        "write_scope": write_scope,
        "failed_prerequisites": failed,
        "state_updates": {
            "subagent_strategy": {
                "mode": mode,
                "reason": reason,
                "run_ids": [],
            }
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide CPE subagent pre-dispatch readiness.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task-packet", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--write-scope", action="append", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    state_path = Path(args.state)
    failed: list[str] = []
    decision = "delegate"
    reason = "all pre-dispatch prerequisites passed"
    write_scope = args.write_scope

    packet_path = Path(args.task_packet)
    packet = {}
    if not packet_path.is_file():
        failed.append("task_packet_missing")
    else:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

    state = {}
    if not state_path.is_file():
        failed.append("state_missing")
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("subagents_requested") is not True:
            failed.append("subagents_not_requested")

    policy = packet.get("write_policy") if isinstance(packet, dict) else {}
    allowed = policy.get("allowed_write_globs") if isinstance(policy, dict) else []
    forbidden = policy.get("forbidden_write_globs") if isinstance(policy, dict) else []
    if not allowed:
        failed.append("allowed_write_globs_empty")
    for scope in write_scope:
        if allowed and not matches_any(scope, allowed):
            failed.append("write_scope_outside_allowed")
        if forbidden and matches_any(scope, forbidden):
            failed.append("write_scope_matches_forbidden")

    dirty = git_changed(repo)
    dirty_overlap = sorted(path for path in dirty if matches_any(path, write_scope))
    if dirty_overlap:
        failed.append("dirty_overlap:" + ",".join(dirty_overlap))
        decision = "block"
        reason = "dirty files overlap delegated write scope"

    if failed and decision != "block":
        decision = "local_fallback"
        reason = failed[0]

    payload = decision_payload(args.task_id, decision, reason, write_scope, failed)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if decision in {"delegate", "local_fallback"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add dispatch decision validation to `validate_state.py`**

Add function:

```python
def _validate_dispatch_decisions(data: dict, errors: list[str]) -> None:
    decisions = data.get("dispatch_decisions", [])
    if decisions is None:
        return
    if not isinstance(decisions, list):
        errors.append("dispatch_decisions must be a list")
        return
    for index, item in enumerate(decisions):
        prefix = f"dispatch_decisions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if item.get("decision") not in {"delegate", "local_fallback", "block"}:
            errors.append(f"{prefix}.decision must be delegate, local_fallback, or block")
        if not _has_substantive_value(item.get("reason")):
            errors.append(f"{prefix}.reason must be non-empty")
        if not isinstance(item.get("failed_prerequisites", []), list):
            errors.append(f"{prefix}.failed_prerequisites must be a list")
        if data.get("lifecycle_outcome") == "finished" and item.get("decision") == "block":
            errors.append(f"{prefix}: block decision cannot remain in finished state")
```

Call it in `validate()` after `_validate_graphify_audit(data, errors)`.

- [ ] **Step 5: Run GREEN checks for Task 4**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
python3 -m py_compile scripts/preflight_dispatch.py scripts/validate_state.py evals/check_preflight_dispatch.py
```

Expected: all commands pass.

- [ ] **Step 6: Wire dispatch docs and harness**

Add to `evals/run.sh`:

```bash
python3 "$EVAL_DIR/check_preflight_dispatch.py" >/dev/null
```

Update `references/pre-dispatch-pipeline.md` so step 1 runs:

```bash
python3 scripts/preflight_dispatch.py \
  --state "$STATE_PATH" \
  --task-id "$TASK_ID" \
  --task-packet "$CURRENT_TASK_PACKET_PATH" \
  --repo-root "$WORKTREE_ABS" \
  --write-scope "$WRITE_SCOPE" \
  --output "$RUN_DIR/dispatch-$TASK_ID.json"
```

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
bash -n evals/run.sh
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/preflight_dispatch.py \
  skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat(cpe): preflight subagent dispatch"
```

## Task 5: Contract, Docs, and Finished-Run Gates

**Files:**

- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_skill_contract.py`

- [ ] **Step 1: Extend `check_skill_contract.py` with RED assertions**

Add checks to the `checks = { ... }` dictionary:

```python
"cache_strategy_contract": all(
    token in runtime
    for token in (
        "references/cache-strategy.md",
        "scripts/audit_prompt_cache.py",
        "stable prefix",
        "hot tail",
        "prompt_audit.dynamic_marker_violations",
    )
),
"graphify_audit_contract": all(
    token in runtime
    for token in (
        "scripts/check_graphify_freshness.py",
        "graphify_audit",
        "Built from commit",
        "graphify update .",
    )
),
"preflight_dispatch_contract": all(
    token in runtime
    for token in (
        "scripts/preflight_dispatch.py",
        "delegate",
        "local_fallback",
        "block",
        "dispatch_decisions",
    )
),
```

- [ ] **Step 2: Run the failing skill contract**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py --skill SKILL.md
```

Expected: FAIL with missing cache/Graphify/dispatch contract checks.

- [ ] **Step 3: Update `SKILL.md`**

Add Core Invariants:

```markdown
- Prompt-generating artifacts follow `references/cache-strategy.md`. Stable
  role, safety, required-skill, and output-schema content stays before the
  stable-prefix boundary; run-specific paths, task packets, timestamps, git
  status, diffs, decisions, and verification evidence stay in the hot tail.
  Finished runs cannot retain non-empty
  `prompt_audit.dynamic_marker_violations`.
- Graphify-aware repositories record `graphify_audit` evidence using
  `scripts/check_graphify_freshness.py`. If `graphify update .` is required
  after code or meaningful documentation-structure changes, the completion
  audit records whether the command ran and whether tracked or ignored outputs
  changed.
- Subagent pre-dispatch decisions use `scripts/preflight_dispatch.py` before
  spawning for eligible write-capable tasks. The decision is one of `delegate`,
  `local_fallback`, or `block`; `local_fallback` reasons flow into task
  `subagent_strategy.reason`, and `block` decisions cannot be carried into a
  finished lifecycle outcome.
```

Add validation matrix entries:

```markdown
| `interactive` | existing checks plus prompt cache audit, Graphify audit when applicable, and dispatch decision evidence for write-capable subagent tasks |
| `headless` | existing checks plus prompt cache audit, Graphify audit when applicable, and dispatch decision evidence for write-capable subagent tasks |
```

- [ ] **Step 4: Update README, architecture, history, and docs**

Add to README validation commands:

```bash
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
```

Add to `ARCHITECTURE.md`:

```markdown
Prompt construction uses a stable-prefix/hot-tail split. The stable prefix
contains invariant execution rules; task/run payloads live in the hot tail and
are audited by `scripts/audit_prompt_cache.py`.

Graphify freshness and subagent dispatch readiness are represented as JSON
evidence. State remains authoritative; helper outputs are accepted only after
state validation and parent review.
```

Add to `HISTORY.md` under `## Unreleased`:

```markdown
- Added execution hardening for prompt cache boundaries, optional cache
  observations, Graphify freshness audits, and deterministic subagent
  pre-dispatch decisions.
```

- [ ] **Step 5: Run GREEN contract and docs checks**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_prompt_cache_audit.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
bash -n evals/run.sh
```

Expected: all commands pass.

- [ ] **Step 6: Commit Task 5**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/evals/check_skill_contract.py
git commit -m "docs(cpe): document execution hardening gates"
```

## Task 6: Full Verification and Graphify Refresh

**Files:**

- Modify: `skills/kws-codex-plan-executor/evals/baselines/v2.21.0.json`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`

- [ ] **Step 1: Run the deterministic suite**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
python3 evals/check_local_env_preflight.py
python3 evals/check_invocation_args.py
python3 evals/check_inspect_runs.py
python3 evals/check_decisions_register.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
bash evals/run.sh
```

Expected: all commands pass. `bash evals/run.sh` may update
`evals/baselines/v2.21.0.json`; review that diff before staging it.

- [ ] **Step 2: Run Graphify update after code/docs changes**

Run:

```bash
cd /Users/kws/source/private/Archive
graphify update .
```

Expected: command exits 0. If `graphify-out/` is tracked, `GRAPH_REPORT.md` and
`graph.json` may change. If it is ignored in another checkout, record the
successful command in the completion summary.

- [ ] **Step 3: Run repository whitespace check**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: PASS with no output.

- [ ] **Step 4: Update verification log**

Append a new dated section to
`skills/kws-codex-plan-executor/docs/verification-log.md`:

````markdown
## 2026-05-31

Scope:

- Prompt cache boundary audit and optional cache observations.
- Graphify freshness audit evidence.
- Deterministic subagent pre-dispatch decision evidence.

Commands:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
python3 evals/check_local_env_preflight.py
python3 evals/check_invocation_args.py
python3 evals/check_inspect_runs.py
python3 evals/check_decisions_register.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
bash evals/run.sh
git diff --check
```

Result:

- Deterministic evals: pass.
- Python compile and shell syntax: pass.
- Dynamic/static eval harness: pass.
- Graphify update: pass.
````

- [ ] **Step 5: Inspect final diff scope**

Run:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
git diff --stat
git diff --name-only
```

Expected: changed files are limited to `skills/kws-codex-plan-executor/`,
`graphify-out/`, and intentional eval baseline files. Unrelated untracked files
remain unstaged.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "chore(cpe): verify execution hardening"
```

## Final Review Checklist

- [ ] Every new script has a deterministic eval.
- [ ] `validate_state.py` accepts old state without new optional fields.
- [ ] Finished state rejects prompt audit violations.
- [ ] Finished state rejects Graphify audit errors when present.
- [ ] Finished state rejects carried `dispatch_decisions[].decision=block`.
- [ ] `subagents=on` remains subagent-first and task-packet scoped.
- [ ] `mode=interactive` remains the default.
- [ ] AgentLens remains best-effort.
- [ ] No runtime artifacts are written into the repository worktree.
- [ ] `graphify update .` has been run after implementation changes.
- [ ] `git diff --check` passes.

## Self-Review

Spec coverage:

- Prompt cache stability is covered by Tasks 1, 2, 5, and 6.
- Graphify freshness evidence is covered by Tasks 3, 5, and 6.
- Subagent pre-dispatch decision automation is covered by Tasks 4, 5, and 6.
- Backward-compatible state validation is covered by Tasks 2, 3, and 4.
- Documentation and final verification are covered by Tasks 5 and 6.

Placeholder scan:

- The plan contains concrete file paths, commands, expected outcomes, JSON
  shapes, and code skeletons for new scripts and evals.

Type consistency:

- Cache fields use `cache_strategy`, `cache_observations`, and `prompt_audit`.
- Graphify fields use `graphify_audit`.
- Dispatch fields use `dispatch_decisions`, `delegate`, `local_fallback`, and
  `block`.
