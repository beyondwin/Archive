# CPE Eval Baseline Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `skills/kws-codex-plan-executor/evals/run.sh` verify by default without modifying tracked baseline files, while requiring `--update-baseline` for intentional baseline writes.

**Architecture:** Keep the existing deterministic eval harness and fixture runners intact. Add an explicit baseline mode to `run.sh`: default mode builds a temporary result and compares it to the tracked baseline while ignoring top-level `date`; update mode writes the generated result, and fixture-subset update mode replaces only executed fixture entries.

**Tech Stack:** Bash, Python 3 inline helper blocks, JSON, `jq`, existing CPE deterministic evals.

## Global Constraints

- Scope is limited to `skills/kws-codex-plan-executor`.
- Do not reduce deterministic checks, parser fixture checks, prompt fixture checks, or execution fixture checks.
- Default `./evals/run.sh` must not modify `evals/baselines/v<version>.json`.
- `./evals/run.sh --update-baseline` is the only intended path that writes tracked baseline JSON.
- Baseline comparison ignores top-level `date` but compares fixture list, mode, runner/checker status, passed flag, and checks payload.
- Fixture-subset update must replace only executed fixture entries and preserve unexecuted fixture entries plus top-level version.
- Keep baseline JSON schema recognizable: top-level `version`, `date`, and `fixtures`.
- Do not reintroduce dynamic model evals.
- Preserve existing user changes in the working tree.

---

## File Structure

- Modify `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
  - Static contract checks for the new harness behavior.
  - Owns detection of `--update-baseline`, default compare mode, mismatch guidance, and subset update preservation markers.
- Modify `skills/kws-codex-plan-executor/evals/run.sh`
  - Parse `--update-baseline` before fixture arguments.
  - Continue running all existing deterministic checks and fixture runners.
  - Write generated fixture result to a temp result file, not directly to the tracked baseline.
  - Compare generated result with baseline by default.
  - Write full or subset baseline only when `--update-baseline` is present.
- Modify `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
  - Document default verification and explicit baseline update flow.
- Modify `skills/kws-codex-plan-executor/HISTORY.md`
  - Add an unreleased entry for the baseline update behavior.

---

### Task 1: Add Harness Contract Coverage

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_eval_harness.py`

**Interfaces:**
- Consumes: `run.sh` text loaded as `run_sh`.
- Produces: New checks in the existing JSON payload:
  - `supports_update_baseline_option: bool`
  - `default_compares_baseline: bool`
  - `default_does_not_write_baseline_directly: bool`
  - `mismatch_guides_update_command: bool`
  - `subset_update_preserves_unexecuted_fixtures: bool`
  - `update_refuses_failed_fixture_results: bool`

- [ ] **Step 1: Write the failing static contract checks**

Replace the body of `main()` in `skills/kws-codex-plan-executor/evals/check_eval_harness.py` with this version, preserving the imports and module docstring:

```python
def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    run_sh = (skill_dir / "evals" / "run.sh").read_text(encoding="utf-8")
    check_execution = (skill_dir / "evals" / "check_execution.py").read_text(encoding="utf-8")
    checks: dict[str, bool] = {}
    failures: list[str] = []

    checks["aggregates_fixture_failures"] = "overall_status=0" in run_sh and "overall_status=1" in run_sh
    if not checks["aggregates_fixture_failures"]:
        failures.append("run.sh should aggregate fixture failures into a non-zero final status")

    checks["exits_with_aggregate_status"] = 'exit "$overall_status"' in run_sh
    if not checks["exits_with_aggregate_status"]:
        failures.append("run.sh should exit with the aggregate fixture status")

    checks["isolates_state_home"] = "CODEX_EVAL_HOME" in run_sh and "Path.home()" not in run_sh
    if not checks["isolates_state_home"]:
        failures.append("run.sh should use an eval-specific home for state fixtures, not the real home")

    checks["execution_checker_uses_eval_home"] = "CODEX_EVAL_HOME" in check_execution and "Path.home()" not in check_execution
    if not checks["execution_checker_uses_eval_home"]:
        failures.append("check_execution.py should locate state under CODEX_EVAL_HOME when present")

    checks["maps_headless_sandbox"] = "headless_sandbox" in run_sh and "HEADLESS_SANDBOX" in run_sh
    if not checks["maps_headless_sandbox"]:
        failures.append("run.sh should map headless_sandbox to HEADLESS_SANDBOX for the target process")

    checks["prompt_export_fast_path"] = "For mode=prompt or mode=handoff, do not load implementation-only skills" in run_sh
    if not checks["prompt_export_fast_path"]:
        failures.append("run.sh should keep prompt/handoff evals on an export-only fast path")

    checks["static_execution_runner"] = "static_execution_runner.py" in run_sh and 'mode" != "prompt"' in run_sh
    if not checks["static_execution_runner"]:
        failures.append("run.sh should use the deterministic static runner for execution fixtures")

    checks["static_prompt_runner"] = "static_prompt_runner.py" in run_sh
    if not checks["static_prompt_runner"]:
        failures.append("run.sh should use the deterministic static runner for prompt fixtures")

    checks["supports_update_baseline_option"] = "--update-baseline" in run_sh and "update_baseline=0" in run_sh
    if not checks["supports_update_baseline_option"]:
        failures.append("run.sh should support an explicit --update-baseline option")

    checks["default_compares_baseline"] = "compare_baseline" in run_sh and "baseline mismatch:" in run_sh
    if not checks["default_compares_baseline"]:
        failures.append("run.sh should compare generated results against the tracked baseline by default")

    checks["default_does_not_write_baseline_directly"] = (
        "generated_baseline=" in run_sh
        and '>"$BASELINE_FILE"' not in run_sh
        and '> "$BASELINE_FILE"' not in run_sh
    )
    if not checks["default_does_not_write_baseline_directly"]:
        failures.append("run.sh default path should not write directly to the tracked baseline file")

    checks["mismatch_guides_update_command"] = "./evals/run.sh --update-baseline" in run_sh
    if not checks["mismatch_guides_update_command"]:
        failures.append("baseline mismatch output should tell operators to run ./evals/run.sh --update-baseline")

    checks["subset_update_preserves_unexecuted_fixtures"] = (
        "merge_subset_baseline" in run_sh
        and "existing_by_fixture" in run_sh
        and "generated_by_fixture" in run_sh
    )
    if not checks["subset_update_preserves_unexecuted_fixtures"]:
        failures.append("fixture subset baseline updates should preserve unexecuted fixture entries")

    checks["update_refuses_failed_fixture_results"] = (
        "refusing to update baseline because eval checks failed" in run_sh
        and 'if [ "$overall_status" -ne 0 ]' in run_sh
    )
    if not checks["update_refuses_failed_fixture_results"]:
        failures.append("--update-baseline should not write baseline output when fixture checks failed")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1
```

- [ ] **Step 2: Run the focused contract check and confirm RED**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_eval_harness.py
```

Expected: FAIL. The JSON should include `passed: false` and failures for `--update-baseline`, default baseline comparison, mismatch guidance, subset update preservation, and refusing failed fixture updates.

- [ ] **Step 3: Commit the failing contract test**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/evals/check_eval_harness.py
git commit -m "test(cpe): require explicit eval baseline updates"
```

---

### Task 2: Implement Default Compare and Explicit Baseline Update

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes:
  - Existing fixture arguments.
  - New optional flag: `--update-baseline`.
- Produces:
  - `generated_baseline` temp JSON with top-level `version`, `date`, and `fixtures`.
  - Default compare behavior through `compare_baseline`.
  - Update behavior through `write_full_baseline` and `merge_subset_baseline`.

- [ ] **Step 1: Add argument parsing for update mode**

Insert this block after `BASELINE_FILE="$EVAL_DIR/baselines/v${SKILL_VERSION}.json"` and before `fixtures=()`:

```bash
update_baseline=0
fixture_args=()
for arg in "$@"; do
  case "$arg" in
    --update-baseline)
      update_baseline=1
      ;;
    *)
      fixture_args+=("$arg")
      ;;
  esac
done
```

Then change the fixture selection block from using `"$#"` and `"$@"` to this exact form:

```bash
fixtures=()
if [ "${#fixture_args[@]}" -eq 0 ]; then
  while IFS= read -r fixture; do fixtures+=("$fixture"); done < <(find "$EVAL_DIR/fixtures" -name '*.yaml' -type f | sort)
else
  for fixture in "${fixture_args[@]}"; do
    if [ -f "$fixture" ]; then
      fixtures+=("$(cd "$(dirname "$fixture")" && pwd -P)/$(basename "$fixture")")
    elif [ -f "$EVAL_DIR/$fixture" ]; then
      fixtures+=("$EVAL_DIR/$fixture")
    else
      echo "fixture not found: $fixture" >&2
      exit 1
    fi
  done
fi
```

- [ ] **Step 2: Write the generated baseline to a temp file**

Replace the final baseline-write block:

```bash
jq -s --arg version "$SKILL_VERSION" '{version: $version, date: now | todate, fixtures: .}' "$partial" > "$BASELINE_FILE"
rm -f "$partial"
cat "$BASELINE_FILE"
exit "$overall_status"
```

with:

```bash
generated_baseline="$(mktemp -t "codex-executor-baseline-${SKILL_VERSION}.XXXXXX.json")"
jq -s --arg version "$SKILL_VERSION" '{version: $version, date: now | todate, fixtures: .}' "$partial" > "$generated_baseline"
rm -f "$partial"
```

- [ ] **Step 3: Add baseline compare and update helpers**

Immediately after the new `generated_baseline` block, add this helper section:

```bash
compare_baseline() {
  local expected="$1"
  local actual="$2"
  python3 - "$expected" "$actual" <<'PY'
import json
import sys
from pathlib import Path

expected_path = Path(sys.argv[1])
actual_path = Path(sys.argv[2])
if not expected_path.is_file():
    print(f"baseline missing: {expected_path}", file=sys.stderr)
    raise SystemExit(1)

try:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = json.loads(actual_path.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    print(f"baseline JSON parse failed: {exc}", file=sys.stderr)
    raise SystemExit(1)

expected_compare = dict(expected)
actual_compare = dict(actual)
expected_compare.pop("date", None)
actual_compare.pop("date", None)

expected_by_fixture = {item.get("fixture"): item for item in expected_compare.get("fixtures", [])}
actual_fixtures = actual_compare.get("fixtures", [])
subset_expected = []
for item in actual_fixtures:
    fixture = item.get("fixture")
    if fixture not in expected_by_fixture:
        print(f"baseline missing fixture: {fixture}", file=sys.stderr)
        raise SystemExit(1)
    subset_expected.append(expected_by_fixture[fixture])

expected_compare["fixtures"] = subset_expected
if expected_compare != actual_compare:
    print(f"baseline mismatch: {expected_path}", file=sys.stderr)
    raise SystemExit(1)
PY
}

write_full_baseline() {
  local source="$1"
  local target="$2"
  cp "$source" "$target"
}

merge_subset_baseline() {
  local existing="$1"
  local generated="$2"
  local target="$3"
  python3 - "$existing" "$generated" "$target" <<'PY'
import json
import sys
from pathlib import Path

existing_path = Path(sys.argv[1])
generated_path = Path(sys.argv[2])
target_path = Path(sys.argv[3])
existing = json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.is_file() else {}
generated = json.loads(generated_path.read_text(encoding="utf-8"))

existing_fixtures = existing.get("fixtures", [])
generated_fixtures = generated.get("fixtures", [])
existing_by_fixture = {
    item.get("fixture"): item
    for item in existing_fixtures
    if isinstance(item, dict) and item.get("fixture")
}
generated_by_fixture = {
    item.get("fixture"): item
    for item in generated_fixtures
    if isinstance(item, dict) and item.get("fixture")
}

merged_fixtures = []
seen = set()
for item in existing_fixtures:
    fixture = item.get("fixture") if isinstance(item, dict) else None
    if fixture in generated_by_fixture:
        merged_fixtures.append(generated_by_fixture[fixture])
        seen.add(fixture)
    else:
        merged_fixtures.append(item)

for fixture, item in generated_by_fixture.items():
    if fixture not in seen and fixture not in existing_by_fixture:
        merged_fixtures.append(item)

payload = {
    "version": existing.get("version") or generated.get("version"),
    "date": generated.get("date"),
    "fixtures": merged_fixtures,
}
target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}
```

- [ ] **Step 4: Add final mode branching**

After the helper section, add:

```bash
if [ "$update_baseline" -eq 1 ] && [ "$overall_status" -ne 0 ]; then
  echo "refusing to update baseline because eval checks failed" >&2
  cat "$generated_baseline"
  rm -f "$generated_baseline"
  exit "$overall_status"
fi

if [ "$update_baseline" -eq 1 ]; then
  if [ "${#fixture_args[@]}" -eq 0 ]; then
    write_full_baseline "$generated_baseline" "$BASELINE_FILE"
  else
    merge_subset_baseline "$BASELINE_FILE" "$generated_baseline" "$BASELINE_FILE"
  fi
  cat "$BASELINE_FILE"
else
  if ! compare_baseline "$BASELINE_FILE" "$generated_baseline"; then
    echo "Run ./evals/run.sh --update-baseline after reviewing the changed eval output." >&2
    rm -f "$generated_baseline"
    exit 1
  fi
  cat "$generated_baseline"
fi

rm -f "$generated_baseline"
exit "$overall_status"
```

- [ ] **Step 5: Run the focused contract check and confirm GREEN**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_eval_harness.py
```

Expected: PASS with JSON containing `"passed": true`.

- [ ] **Step 6: Run shell syntax check**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
bash -n evals/run.sh
```

Expected: no output and exit status 0.

- [ ] **Step 7: Commit run.sh behavior**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/evals/run.sh skills/kws-codex-plan-executor/evals/check_eval_harness.py
git commit -m "fix(cpe): make eval baseline updates explicit"
```

---

### Task 3: Update Operator Docs and History

**Files:**
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`

**Interfaces:**
- Consumes: New `run.sh` behavior from Task 2.
- Produces: User-facing instructions for default verification and intentional baseline update.

- [ ] **Step 1: Update eval verification docs**

In `skills/kws-codex-plan-executor/docs/evals-and-verification.md`, after the command block that lists deterministic checks, insert this paragraph:

```markdown
`./evals/run.sh` is the default full harness verification command. It builds a
temporary generated baseline and compares it with `evals/baselines/v<version>.json`
while ignoring the top-level `date` field, but it does not update the tracked
baseline file. When fixture output intentionally changes, review the generated
output and then run `./evals/run.sh --update-baseline` to update the baseline.
Focused fixture runs such as `./evals/run.sh fixtures/01-prompt-only.yaml`
compare only the executed fixture entries; focused update runs replace only
those fixture entries and preserve unexecuted fixtures.
```

- [ ] **Step 2: Update unreleased history**

In `skills/kws-codex-plan-executor/HISTORY.md`, under `## 2.23.0 - Unreleased`, add this bullet:

```markdown
- Changed `evals/run.sh` so default verification compares against the tracked
  baseline without rewriting it; intentional baseline updates now require
  `--update-baseline`, and focused fixture updates preserve unexecuted fixture
  entries.
```

- [ ] **Step 3: Run docs diff check**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --check -- skills/kws-codex-plan-executor/docs/evals-and-verification.md skills/kws-codex-plan-executor/HISTORY.md
```

Expected: no output and exit status 0.

- [ ] **Step 4: Commit docs and history**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/docs/evals-and-verification.md skills/kws-codex-plan-executor/HISTORY.md
git commit -m "docs(cpe): document explicit eval baseline updates"
```

---

### Task 4: Verify Full Harness Behavior and Close Out

**Files:**
- Verify only: `skills/kws-codex-plan-executor/evals/run.sh`
- Verify only: `skills/kws-codex-plan-executor/evals/baselines/v2.22.0.json`
- Verify only: `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
- Verify only: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Verify only: `skills/kws-codex-plan-executor/HISTORY.md`

**Interfaces:**
- Consumes: All changes from Tasks 1-3.
- Produces: Final verification evidence and a clean intended diff.

- [ ] **Step 1: Run Python compile check**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
```

Expected: no output and exit status 0.

- [ ] **Step 2: Run shell syntax check**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
bash -n evals/run.sh
```

Expected: no output and exit status 0.

- [ ] **Step 3: Prove default harness does not dirty the baseline**

First capture the current baseline hash:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
before_hash="$(shasum -a 256 evals/baselines/v2.22.0.json | awk '{print $1}')"
./evals/run.sh
after_hash="$(shasum -a 256 evals/baselines/v2.22.0.json | awk '{print $1}')"
test "$before_hash" = "$after_hash"
```

Expected: `./evals/run.sh` exits 0, and the final `test` exits 0.

- [ ] **Step 4: Prove explicit update path still works**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh --update-baseline fixtures/01-prompt-only.yaml
python3 - <<'PY'
import json
from pathlib import Path

path = Path("evals/baselines/v2.22.0.json")
data = json.loads(path.read_text(encoding="utf-8"))
fixtures = data.get("fixtures", [])
names = [item.get("fixture") for item in fixtures]
assert "01-prompt-only" in names
assert "02-no-spark" in names
assert len(fixtures) >= 2
PY
```

Expected: both commands exit 0. If this intentionally changes only the baseline `date` or the `01-prompt-only` fixture entry, keep the change only if the refreshed baseline is desired for this branch; otherwise restore the pre-step baseline content before final commit.

- [ ] **Step 5: Run diff hygiene**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: no output and exit status 0.

- [ ] **Step 6: Inspect final intended diff**

Run:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
git diff -- skills/kws-codex-plan-executor/evals/run.sh skills/kws-codex-plan-executor/evals/check_eval_harness.py skills/kws-codex-plan-executor/docs/evals-and-verification.md skills/kws-codex-plan-executor/HISTORY.md
```

Expected: intended files only for this plan. Existing unrelated dirty files from before this plan, such as `skills/kws-codex-plan-executor/SKILL.md`, `skills/kws-codex-plan-executor/evals/baselines/v2.22.0.json`, or `skills/kws-codex-plan-executor/references/subagent-run-store.md`, must not be reverted or silently included unless the user explicitly expands scope.

- [ ] **Step 7: Commit final verification cleanup if needed**

If Task 4 produced intended documentation or harness cleanup not yet committed, commit only those intended files:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/evals/run.sh skills/kws-codex-plan-executor/evals/check_eval_harness.py skills/kws-codex-plan-executor/docs/evals-and-verification.md skills/kws-codex-plan-executor/HISTORY.md
git commit -m "chore(cpe): verify eval baseline update flow"
```

If there are no uncommitted intended files, do not create an empty commit.

---

## Self-Review Notes

- Spec coverage: default verification, explicit `--update-baseline`, fixture subset compare/update, mismatch guidance, docs, history, and verification commands are each covered by a task.
- Placeholder scan: the plan contains no deferred implementation markers; every code-changing step includes concrete code or exact text.
- Type and name consistency: `update_baseline`, `fixture_args`, `generated_baseline`, `compare_baseline`, `write_full_baseline`, `merge_subset_baseline`, `existing_by_fixture`, and `generated_by_fixture` are introduced before use and match the harness checks.
