#!/usr/bin/env bash
# Eval harness for kws-codex-plan-executor.

set -euo pipefail

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKILL_DIR="$(dirname "$EVAL_DIR")"
SKILL_VERSION="$(python3 - "$SKILL_DIR/SKILL.md" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'(?m)^[ \t]*version:[ \t]*"([^"]+)"', text)
print(m.group(1) if m else "0.0.0")
PY
)"
BASELINE_FILE="$EVAL_DIR/baselines/v${SKILL_VERSION}.json"

fixtures=()
if [ "$#" -eq 0 ]; then
  while IFS= read -r fixture; do fixtures+=("$fixture"); done < <(find "$EVAL_DIR/fixtures" -name '*.yaml' -type f | sort)
else
  for fixture in "$@"; do
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

mkdir -p "$EVAL_DIR/baselines"
partial="$BASELINE_FILE.partial"
: > "$partial"

python3 "$EVAL_DIR/check_skill_contract.py" --skill "$SKILL_DIR/SKILL.md" >/dev/null
python3 "$EVAL_DIR/check_state_schema.py" >/dev/null
python3 "$EVAL_DIR/check_learning_log.py" >/dev/null
while IFS= read -r parser_fixture; do
  python3 "$EVAL_DIR/check_parse_plan.py" --fixture "$parser_fixture" >/dev/null
done < <(find "$EVAL_DIR/parser-fixtures" -name '*.yaml' -type f | sort)

for fixture_path in "${fixtures[@]}"; do
  fixture_name="$(basename "$fixture_path" .yaml)"
  parent="$(mktemp -d -t "codex-executor-eval-${fixture_name}.XXXXXX")"
  tmpdir="$parent/repo"
  mkdir -p "$tmpdir/.harness"

  python3 - "$fixture_path" "$tmpdir" <<'PY'
import json, os, sys, yaml
fixture_path, tmpdir = sys.argv[1:3]
with open(fixture_path, encoding="utf-8") as fh:
    data = yaml.safe_load(fh) or {}


def expand_workdir(value):
    if isinstance(value, str):
        return value.replace("__WORKDIR__", tmpdir)
    if isinstance(value, list):
        return [expand_workdir(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_workdir(item) for key, item in value.items()}
    return value


for name, content in {
    "plan.md": data.get("plan", "### Task 0: Placeholder\n\n**Files:**\n- Create: docs/example.md\n"),
    "spec.md": data.get("spec", ""),
}.items():
    with open(os.path.join(tmpdir, name), "w", encoding="utf-8") as fh:
        fh.write(content)
for name, content in (data.get("docs") or {}).items():
    path = os.path.join(tmpdir, name)
    os.makedirs(os.path.dirname(path) or tmpdir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
if data.get("initial_state") is not None:
    state_path = os.path.join(tmpdir, ".codex-orchestrator", "state.json")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(expand_workdir(data["initial_state"]), fh, ensure_ascii=False, indent=2)
PY

  (
    cd "$tmpdir"
    git init -q
    git config user.email "eval@example.com"
    git config user.name "eval"
    git add -A
    git commit -q -m "eval bootstrap"
  )

  python3 - "$fixture_path" "$tmpdir" <<'PY'
import os, sys, yaml
fixture_path, tmpdir = sys.argv[1:3]
with open(fixture_path, encoding="utf-8") as fh:
    data = yaml.safe_load(fh) or {}
for name, content in (data.get("dirty_files") or {}).items():
    path = os.path.join(tmpdir, name)
    os.makedirs(os.path.dirname(path) or tmpdir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
PY

  mode="$(python3 - "$fixture_path" <<'PY'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
print(data.get("mode", "interactive"))
PY
)"
  fixture_args="$(python3 - "$fixture_path" <<'PY'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
print(data.get("args", ""))
PY
)"

  prompt="EVAL_RUN: Test the local skill at $SKILL_DIR/SKILL.md. Follow that skill as /kws-codex-plan-executor. Before implementation or clarification, load and follow applicable installed skills, especially using-superpowers; use test-driven-development before feature, bugfix, refactor, or behavior-change implementation. This process is already the codex exec target; for mode=headless, do not launch another nested codex exec, and instead execute locally while writing the required .codex-orchestrator/headless artifacts. Do not ask clarifying questions unless the skill requires a blocker. The harness will run fixture checkers after you finish; do not inspect eval fixture YAML, baseline files, .harness metadata, or expected values, and do not run evals/check_execution.py yourself. Use only plan.md, spec.md, repository files, SKILL.md, references, and scripts needed by the skill. /kws-codex-plan-executor plan=plan.md spec=spec.md mode=$mode $fixture_args"

  set +e
  (
    cd "$tmpdir"
    codex exec \
      --cd "$tmpdir" \
      --sandbox workspace-write \
      --json \
      --output-last-message "$tmpdir/.harness/final.md" \
      "$prompt" \
      > "$tmpdir/.harness/run.jsonl" 2>&1
  )
  codex_status=$?
  set -e

  if [ "$mode" = "prompt" ] || [ "$mode" = "handoff" ]; then
    checker_out="$(python3 "$EVAL_DIR/check_prompt.py" --fixture "$fixture_path" --output "$tmpdir/.harness/final.md" 2>&1)" || checker_status=$?
    checker_status="${checker_status:-0}"
  else
    checker_out="$(python3 "$EVAL_DIR/check_execution.py" --fixture "$fixture_path" --workdir "$tmpdir" --final-output "$tmpdir/.harness/final.md" --run-log "$tmpdir/.harness/run.jsonl" 2>&1)" || checker_status=$?
    checker_status="${checker_status:-0}"
  fi

  python3 - "$partial" "$fixture_name" "$mode" "$codex_status" "$checker_status" "$checker_out" <<'PY'
import json, sys
path, fixture, mode, codex_status, checker_status, checker_out = sys.argv[1:7]
try:
    checks = json.loads(checker_out)
except Exception:
    checks = {"passed": False, "raw": checker_out}
payload = {
    "fixture": fixture,
    "mode": mode,
    "codex_status": int(codex_status),
    "checker_status": int(checker_status),
    "passed": int(codex_status) == 0 and int(checker_status) == 0,
    "checks": checks,
}
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
PY
  unset checker_status
done

jq -s --arg version "$SKILL_VERSION" '{version: $version, date: now | todate, fixtures: .}' "$partial" > "$BASELINE_FILE"
rm -f "$partial"
cat "$BASELINE_FILE"
