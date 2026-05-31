# CPE v2.21 Cache-Friendly Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kws-codex-plan-executor` cache-friendlier by stabilizing prompt prefixes, moving dynamic data into task-local payloads, and adding deterministic cache audit coverage.

**Architecture:** Keep CPE Codex-native and state-authoritative. Do not change the default execution mode or copy Claude-specific cache controls. Add prompt boundary markers, a static prompt audit, optional cache observation state, and eval gates that prove dynamic run data stays out of stable prompt prefixes.

**Tech Stack:** Python 3 standard library, Markdown prompt/reference files, JSON state under `~/.codex/orchestrator/<run_id>`, existing CPE eval shell harness.

---

## Scope

This plan implements the v2.21 cache-friendly execution spec in
`skills/kws-codex-plan-executor/docs/experiments/v2.21-cache-friendly-execution/IMPLEMENTATION.md`.

Included:

- Prompt cache strategy reference.
- Stable-prefix/hot-tail markers in checked prompt artifacts.
- Static prompt cache audit script and eval.
- Optional cache observation append script and state validation.
- README, HISTORY, and validation docs updates.
- Deterministic baseline updates.

Excluded:

- Changing `mode=interactive` default.
- Enabling provider-specific cache TTL controls.
- Adding budget caps or cost-based halts.
- Changing task packet semantics.
- Adding new subagent fan-out behavior.

## File Structure

Create:

- `skills/kws-codex-plan-executor/references/cache-strategy.md` - CPE cache model and prompt boundary rules.
- `skills/kws-codex-plan-executor/scripts/audit_prompt_cache.py` - static prompt boundary audit.
- `skills/kws-codex-plan-executor/scripts/record_cache_observation.py` - optional runtime cache telemetry appender.
- `skills/kws-codex-plan-executor/evals/check_prompt_cache_audit.py` - deterministic audit tests.
- `skills/kws-codex-plan-executor/evals/check_cache_observations.py` - deterministic telemetry/state tests.
- `skills/kws-codex-plan-executor/evals/baselines/v2.21.0.json` - cache audit baseline after implementation stabilizes.

Modify:

- `skills/kws-codex-plan-executor/SKILL.md` - add cache strategy invariants and validation matrix entries.
- `skills/kws-codex-plan-executor/HISTORY.md` - add v2.21 entry.
- `skills/kws-codex-plan-executor/README.md` - add design note and validation commands.
- `skills/kws-codex-plan-executor/ARCHITECTURE.md` - mention stable-prefix/hot-tail prompt construction.
- `skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt` - add cache boundary markers and move dynamic tokens behind the boundary.
- `skills/kws-codex-plan-executor/references/headless-runner.md` - state headless is replay-oriented, not cache-optimal.
- `skills/kws-codex-plan-executor/references/verifier-prompt.md` - mark stable verifier instructions separately from dynamic task payload.
- `skills/kws-codex-plan-executor/references/prompt-export-checklist.md` - add cache audit check.
- `skills/kws-codex-plan-executor/references/state-schema.md` - document optional cache fields.
- `skills/kws-codex-plan-executor/references/execution-cycle.md` - require prompt audit before finished outcome.
- `skills/kws-codex-plan-executor/scripts/validate_state.py` - validate optional cache fields.
- `skills/kws-codex-plan-executor/evals/check_state_schema.py` - cover cache field validation.
- `skills/kws-codex-plan-executor/evals/check_skill_contract.py` - check cache strategy contract text.
- `skills/kws-codex-plan-executor/evals/run.sh` - run the new deterministic checks.
- `skills/kws-codex-plan-executor/docs/evals-and-verification.md` - list new checks.
- `skills/kws-codex-plan-executor/docs/state-and-logging.md` - describe cache observations and prompt audit state.

## Acceptance Criteria

- `mode=interactive` remains the default everywhere.
- Stable-prefix blocks in checked templates contain no dynamic markers.
- The audit proves stable-prefix hashes do not change when only hot-tail content changes.
- Finished v2.21 state cannot contain prompt audit violations.
- Pre-v2.21 state files still validate.
- `bash evals/run.sh` passes from `skills/kws-codex-plan-executor`.
- `python3 -m py_compile scripts/*.py evals/*.py` passes from `skills/kws-codex-plan-executor`.
- `git diff --check` passes from the repository root.

## Risk Closure

- Provider cache counters unavailable: closed by optional `cache_observations`
  fields and deterministic prompt audit as the required gate.
- Headless cache confusion: closed by preserving `mode=interactive` as default
  and documenting headless as explicit replay mode.
- Dynamic prefix drift: closed by stable-prefix markers plus
  `audit_prompt_cache.py` failures wired into evals and finished-state checks.
- Hidden instruction loss: closed by keeping role, safety, required-skill, and
  output-schema instructions in the stable prefix while only task/run payloads
  move to the hot tail.
- Unintended auto fan-out: closed by excluding dispatch policy changes and
  retaining task-packet scoped parent review.
- Backward compatibility: closed by optional v2.21 state fields and validator
  coverage for pre-v2.21 state.

## Tasks

### Task 1: Add Cache Strategy Reference

**Files:**

- Create: `skills/kws-codex-plan-executor/references/cache-strategy.md`
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`

- [ ] **Step 1: Create `references/cache-strategy.md`**

Write:

```markdown
# Cache Strategy

CPE treats prompt caching as a prefix-stability problem. The executor does not
assume a provider-specific cache-control API is available.

## Terms

- Stable prefix: role instructions, safety boundaries, required skills, output
  schemas, and invariant checklists.
- Hot tail: plan paths, run ids, timestamps, git status, task text, spec slices,
  changed files, decisions, state paths, and verification evidence.
- Cache-hostile drift: dynamic material before stable material.

## Rules

1. Keep `mode=interactive` as the default.
2. Put stable prefix before hot tail.
3. Do not put `{{...}}` tokens, run ids, state paths, task packet paths,
   timestamps, git status, diffs, decisions, or absolute home paths in stable
   prefix blocks.
4. Use task packets for dynamic task context.
5. Treat provider cache-token counters as optional telemetry.

## Markers

Use these comments in checked prompt templates:

```text
<!-- CPE_CACHE_STABLE_PREFIX_START -->
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
```
```

- [ ] **Step 2: Update `SKILL.md` invariants**

Add one Core Invariant bullet near the context and headless prompt invariants:

```markdown
- Prompt-generating artifacts follow `references/cache-strategy.md`: stable
  role/safety/output-schema content stays before the stable-prefix boundary, and
  run-specific paths, task packets, timestamps, git status, diffs, decisions, and
  other dynamic content stay in the hot tail. `mode=interactive` remains the
  cache-friendlier default; `mode=headless` is explicit and replay-oriented.
```

Add `scripts/audit_prompt_cache.py` to the interactive/headless validation rows.

- [ ] **Step 3: Update README and architecture**

In README validation commands, add:

```bash
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
```

In README Design Notes, add:

```markdown
- `docs/experiments/v2.21-cache-friendly-execution/PLAN.md`
- `docs/experiments/v2.21-cache-friendly-execution/IMPLEMENTATION.md`
```

In `ARCHITECTURE.md`, add:

```markdown
Prompt construction uses a stable-prefix/hot-tail split. Invariant role
instructions and output schemas stay stable; run-specific data is injected via
task packets, state paths, and verification payloads after the stable boundary.
```

- [ ] **Step 4: Update HISTORY**

Under `## Unreleased`, add:

```markdown
- Added v2.21 cache-friendly execution design: stable prompt prefixes, hot-tail
  dynamic payloads, prompt cache audit checks, and optional cache observation
  state.
```

- [ ] **Step 5: Verify docs and contract references**

Run:

```bash
cd skills/kws-codex-plan-executor
test -f references/cache-strategy.md
rg -n "cache-strategy|audit_prompt_cache|v2.21-cache-friendly" SKILL.md README.md ARCHITECTURE.md HISTORY.md
```

Expected: `test` exits 0 and `rg` prints the new references.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/references/cache-strategy.md \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md
git commit -m "docs(cpe): define cache-friendly execution strategy"
```

### Task 2: Implement Prompt Cache Audit

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/audit_prompt_cache.py`
- Create: `skills/kws-codex-plan-executor/evals/check_prompt_cache_audit.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

- [ ] **Step 1: Write failing eval**

Create `evals/check_prompt_cache_audit.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_prompt_cache.py"


def run_audit(skill_root: Path) -> tuple[int, dict]:
    out = skill_root / "audit.json"
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--skill-root", str(skill_root), "--output", str(out)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(out.read_text()) if out.exists() else {"stderr": proc.stderr}
    return proc.returncode, payload


def write_template(root: Path, body: str) -> None:
    (root / "templates").mkdir()
    (root / "references").mkdir()
    (root / "templates" / "fresh-session-prompt.txt").write_text(body)
    for name in ["headless-runner.md", "verifier-prompt.md", "prompt-export-checklist.md"]:
        (root / "references" / name).write_text(body)


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_template(
            root,
            """<!-- CPE_CACHE_STABLE_PREFIX_START -->
stable output schema
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
{{STATE_PATH}}
""",
        )
        code, report = run_audit(root)
        if code != 0 or not report.get("passed"):
            failures.append("valid template should pass")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_template(
            root,
            """<!-- CPE_CACHE_STABLE_PREFIX_START -->
stable {{STATE_PATH}}
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
tail
""",
        )
        code, report = run_audit(root)
        if code == 0 or report.get("passed"):
            failures.append("dynamic marker inside stable prefix should fail")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        before = """<!-- CPE_CACHE_STABLE_PREFIX_START -->
stable output schema
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
task one
"""
        after = before.replace("task one", "task two with more dynamic text")
        write_template(root, before)
        _, first = run_audit(root)
        first_hash = first["templates"][0]["stable_prefix_sha256"]
        write_template(root, after)
        _, second = run_audit(root)
        second_hash = second["templates"][0]["stable_prefix_sha256"]
        if first_hash != second_hash:
            failures.append("hot-tail-only changes must not change stable hash")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("prompt cache audit checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run eval and confirm RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_prompt_cache_audit.py
```

Expected: FAIL because `scripts/audit_prompt_cache.py` does not exist.

- [ ] **Step 3: Implement audit script**

Create `scripts/audit_prompt_cache.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


START = "<!-- CPE_CACHE_STABLE_PREFIX_START -->"
END = "<!-- CPE_CACHE_STABLE_PREFIX_END -->"
HOT = "<!-- CPE_CACHE_HOT_TAIL_START -->"
CHECKED = [
    "templates/fresh-session-prompt.txt",
    "references/headless-runner.md",
    "references/verifier-prompt.md",
    "references/prompt-export-checklist.md",
]
DYNAMIC_PATTERNS = [
    re.compile(r"{{[^}]+}}"),
    re.compile(r"<(?:run_id|state_path|task_packet[^>]*)>"),
    re.compile(r"\bgit status\b", re.I),
    re.compile(r"\b(timestamp|date)\b", re.I),
    re.compile(r"/Users/"),
]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit_file(root: Path, rel: str) -> dict:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    missing = [marker for marker in [START, END, HOT] if marker not in text]
    stable = ""
    violations = []
    if not missing:
        start = text.index(START) + len(START)
        end = text.index(END)
        hot = text.index(HOT)
        if end < start or hot < end:
            violations.append("marker_order")
        else:
            stable = text[start:end]
            for pattern in DYNAMIC_PATTERNS:
                if pattern.search(stable):
                    violations.append(pattern.pattern)
    return {
        "id": Path(rel).stem,
        "path": rel,
        "stable_prefix_sha256": sha(stable),
        "stable_prefix_bytes": len(stable.encode("utf-8")),
        "hot_tail_bytes": max(len(text.encode("utf-8")) - len(stable.encode("utf-8")), 0),
        "dynamic_marker_violations": violations,
        "missing_markers": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.skill_root)
    templates = [audit_file(root, rel) for rel in CHECKED if (root / rel).exists()]
    passed = all(not item["missing_markers"] and not item["dynamic_marker_violations"] for item in templates)
    report = {"schema_version": "1", "templates": templates, "passed": passed}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run eval and confirm GREEN**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_prompt_cache_audit.py
```

Expected: PASS with `prompt cache audit checks passed`.

- [ ] **Step 5: Wire eval harness**

Add to `evals/run.sh` deterministic checks section:

```bash
python3 evals/check_prompt_cache_audit.py
```

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/audit_prompt_cache.py \
  skills/kws-codex-plan-executor/evals/check_prompt_cache_audit.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "test(cpe): add prompt cache audit"
```

### Task 3: Annotate Prompt Templates And References

**Files:**

- Modify: `skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt`
- Modify: `skills/kws-codex-plan-executor/references/headless-runner.md`
- Modify: `skills/kws-codex-plan-executor/references/verifier-prompt.md`
- Modify: `skills/kws-codex-plan-executor/references/prompt-export-checklist.md`

- [ ] **Step 1: Add stable/hot-tail markers to `fresh-session-prompt.txt`**

Wrap the invariant bootstrap rules with:

```text
<!-- CPE_CACHE_STABLE_PREFIX_START -->
```

and:

```text
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
```

Move every `{{...}}` placeholder below `CPE_CACHE_HOT_TAIL_START`.

- [ ] **Step 2: Add markers to reference prompts**

For each checked reference file, add the stable-prefix markers around invariant
role/output/checklist text, and put task/run-specific examples after
`CPE_CACHE_HOT_TAIL_START`.

- [ ] **Step 3: Run audit**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 scripts/audit_prompt_cache.py --skill-root . --output /tmp/cpe-cache-audit.json
cat /tmp/cpe-cache-audit.json
```

Expected: `"passed": true` and empty `dynamic_marker_violations` for all checked
templates.

- [ ] **Step 4: Run prompt export checks**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_prompt.py
python3 evals/check_prompt_cache_audit.py
```

Expected: both pass. If `check_prompt.py` requires fixture args, use the same
fixture invocation already documented in `evals/run.sh`.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt \
  skills/kws-codex-plan-executor/references/headless-runner.md \
  skills/kws-codex-plan-executor/references/verifier-prompt.md \
  skills/kws-codex-plan-executor/references/prompt-export-checklist.md
git commit -m "docs(cpe): mark stable prompt prefixes"
```

### Task 4: Add Optional Cache Observation State

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/record_cache_observation.py`
- Create: `skills/kws-codex-plan-executor/evals/check_cache_observations.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`

- [ ] **Step 1: Write failing eval**

Create `evals/check_cache_observations.py` with tests for:

```text
- appending input/output-only usage succeeds.
- absent cache counters become null.
- negative token counts fail.
- finished state with prompt_audit.dynamic_marker_violations fails validation.
- pre-v2.21 state without cache fields still validates.
```

- [ ] **Step 2: Run eval and confirm RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_cache_observations.py
```

Expected: FAIL because `record_cache_observation.py` and validator support do
not exist yet.

- [ ] **Step 3: Implement observation appender**

Create `scripts/record_cache_observation.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


TOKEN_FIELDS = ("input_tokens", "cached_read_tokens", "cached_write_tokens", "output_tokens")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--usage-json", required=True)
    args = parser.parse_args()

    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    usage = json.loads(args.usage_json)
    observation = {
        "observed_at": now(),
        "source": args.source,
        "unit": args.unit,
        "mode": args.mode,
        "model": usage.get("model") or "unknown",
        "notes": usage.get("notes") or "",
    }
    for field in TOKEN_FIELDS:
        value = usage.get(field)
        if value is None:
            observation[field] = None
        elif isinstance(value, int) and value >= 0:
            observation[field] = value
        else:
            raise SystemExit(f"error: {field} must be a non-negative integer or null")
    state.setdefault("cache_observations", []).append(observation)
    state.setdefault("timestamps", {})["updated_at"] = now()
    atomic_write(state_path, state)
    print(state_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Extend `validate_state.py`**

Add validation helpers:

```python
VALID_CACHE_STRATEGY_MODES = {"interactive-default", "headless-explicit", "prompt-export", "handoff-export"}
VALID_PROVIDER_CACHE_CONTROL = {"unavailable", "available-unused", "available-enabled", "unknown"}
```

Validate:

```text
- cache_strategy is an object when present.
- cache_strategy.mode is valid.
- provider_cache_control is valid.
- cache_observations is a list when present.
- token fields are int >= 0 or null.
- prompt_audit.dynamic_marker_violations is empty when lifecycle_outcome=finished.
```

- [ ] **Step 5: Document state fields**

Add the JSON snippets from `IMPLEMENTATION.md` to
`references/state-schema.md` and summarize them in `docs/state-and-logging.md`.

- [ ] **Step 6: Run evals**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_cache_observations.py
python3 evals/check_state_schema.py
python3 -m py_compile scripts/*.py evals/*.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/record_cache_observation.py \
  skills/kws-codex-plan-executor/evals/check_cache_observations.py \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md
git commit -m "feat(cpe): record optional cache observations"
```

### Task 5: Add Completion Gate And Baseline

**Files:**

- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/prompt-export-checklist.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Create: `skills/kws-codex-plan-executor/evals/baselines/v2.21.0.json`

- [ ] **Step 1: Add execution-cycle gate**

In `references/execution-cycle.md`, add before final validation:

```markdown
Before setting `lifecycle_outcome=finished`, run
`scripts/audit_prompt_cache.py --skill-root . --output "$RUN_DIR/prompt_audit.json"`
and store the passed report summary in `state.prompt_audit`. A failed prompt
audit blocks a finished outcome because it means stable prompt prefixes contain
dynamic material.
```

- [ ] **Step 2: Add prompt export checklist item**

Add:

```markdown
- Run the prompt cache audit and confirm exported prompt changes do not move
  dynamic `{{...}}` values into the stable-prefix block.
```

- [ ] **Step 3: Wire `evals/run.sh`**

Ensure deterministic checks include:

```bash
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
```

- [ ] **Step 4: Add baseline**

Create `evals/baselines/v2.21.0.json` after a green deterministic run. Include:

```json
{
  "version": "2.21.0",
  "cache_audit": {
    "passed": true,
    "dynamic_marker_violations": []
  }
}
```

If the harness writes richer fixture results, preserve that generated structure
and add the `cache_audit` object rather than replacing fixture data.

- [ ] **Step 5: Run full deterministic verification**

Run:

```bash
cd skills/kws-codex-plan-executor
bash evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/references/prompt-export-checklist.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/evals/run.sh \
  skills/kws-codex-plan-executor/evals/baselines/v2.21.0.json
git commit -m "test(cpe): gate completion on prompt cache audit"
```

### Task 6: Final Documentation And Graphify

**Files:**

- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `graphify-out/` generated outputs when tracked by the repository.

- [ ] **Step 1: Record verification evidence**

Append a v2.21 section to `docs/verification-log.md`:

```markdown
## v2.21 Cache-Friendly Execution

- `python3 evals/check_prompt_cache_audit.py`
- `python3 evals/check_cache_observations.py`
- `python3 evals/check_skill_contract.py --skill SKILL.md`
- `python3 evals/check_state_schema.py`
- `python3 -m py_compile scripts/*.py evals/*.py`
- `bash evals/run.sh`
- `git diff --check`
```

- [ ] **Step 2: Refresh graphify**

From the repository root, run:

```bash
git rev-parse HEAD
graphify update .
```

Expected: graphify completes without API cost. If `graphify-out/` is ignored,
record in the completion audit that graphify was refreshed but generated outputs
were not tracked.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git status --short --branch --untracked-files=all
git diff -- skills/kws-codex-plan-executor
git diff --check
```

Expected: only v2.21 cache-friendly execution files and intended generated
graphify outputs are changed; no `.DS_Store`, runtime state, or secrets appear.

- [ ] **Step 4: Commit**

```bash
git add -A -- skills/kws-codex-plan-executor ':(exclude)**/.DS_Store'
git add graphify-out || true
git commit -m "docs(cpe): document v2.21 cache-friendly execution"
```

## Self-Review Checklist

- [ ] Every requirement in `IMPLEMENTATION.md` maps to at least one task above.
- [ ] No task changes `mode=interactive` default.
- [ ] No task adds provider-specific TTL control.
- [ ] New scripts are deterministic and standard-library only.
- [ ] Pre-v2.21 state compatibility is preserved.
- [ ] All commands use paths under `skills/kws-codex-plan-executor` or the repo root.
