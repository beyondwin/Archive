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
overall_status=0

python3 "$EVAL_DIR/check_skill_contract.py" --skill "$SKILL_DIR/SKILL.md" >/dev/null
python3 "$EVAL_DIR/check_state_schema.py" >/dev/null
python3 "$EVAL_DIR/check_run_diffs.py" >/dev/null
python3 "$EVAL_DIR/check_state_reconciliation.py" >/dev/null
python3 "$EVAL_DIR/check_context_snapshot.py" >/dev/null
python3 "$EVAL_DIR/check_headless_result.py" >/dev/null
python3 "$EVAL_DIR/check_eval_harness.py" >/dev/null
while IFS= read -r parser_fixture; do
  python3 "$EVAL_DIR/check_parse_plan.py" --fixture "$parser_fixture" >/dev/null
done < <(find "$EVAL_DIR/parser-fixtures" -name '*.yaml' -type f | sort)

for fixture_path in "${fixtures[@]}"; do
  fixture_name="$(basename "$fixture_path" .yaml)"
  parent="$(mktemp -d -t "codex-executor-eval-${fixture_name}.XXXXXX")"
  tmpdir="$parent/repo"
  eval_home="$parent/home"
  mkdir -p "$eval_home"
  mkdir -p "$tmpdir/.harness"
  skill_copy="$tmpdir/.harness/skill-under-test"
  mkdir -p "$(dirname "$skill_copy")"
  cp -R "$SKILL_DIR" "$skill_copy"

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
PY

  (
    cd "$tmpdir"
    git init -q
    git config user.email "eval@example.com"
    git config user.name "eval"
    git add -A
    git commit -q -m "eval bootstrap"
  )

  python3 - "$fixture_path" "$tmpdir" "$eval_home" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

fixture_path, tmpdir, eval_home = sys.argv[1:4]
with open(fixture_path, encoding="utf-8") as fh:
    data = yaml.safe_load(fh) or {}
initial = data.get("initial_state")
if initial is None:
    raise SystemExit(0)

home = eval_home

def expand(value):
    if isinstance(value, str):
        return value.replace("__WORKDIR__", tmpdir).replace("__HOME__", home)
    if isinstance(value, list):
        return [expand(item) for item in value]
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    return value

state = expand(initial)
old_run_id = state.get("run_id") or "resume-latest"
suffix = f"{os.getpid()}"
run_id = f"{old_run_id}-{suffix}"
state["run_id"] = run_id
state["branch"] = f"codex/{run_id}"
state["worktree"] = os.path.join(home, ".codex", "worktrees", run_id)
state["run_dir"] = os.path.join(home, ".codex", "orchestrator", run_id)
state["state_path"] = os.path.join(state["run_dir"], "state.json")
state["context_snapshot_path"] = os.path.join(state["run_dir"], "context.json")

Path(state["run_dir"]).mkdir(parents=True, exist_ok=True)
Path(state["context_snapshot_path"]).write_text(
    json.dumps({"basis_hash": state.get("context_basis_hash")}, indent=2) + "\n",
    encoding="utf-8",
)
Path(state["state_path"]).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
Path(state["worktree"]).parent.mkdir(parents=True, exist_ok=True)
subprocess.run(
    ["git", "worktree", "add", "-q", "-b", state["branch"], state["worktree"], "HEAD"],
    cwd=tmpdir,
    check=True,
)
PY

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
  headless_sandbox="$(python3 - "$fixture_path" <<'PY'
import re
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
args = str(data.get("args", ""))
match = re.search(r"(?:^|\s)headless_sandbox=(workspace-write|read-only)(?:\s|$)", args)
value = match.group(1) if match else data.get("headless_sandbox", "workspace-write")
if value not in {"workspace-write", "read-only"}:
    raise SystemExit(f"invalid headless_sandbox: {value}")
print(value)
PY
)"

  prompt="EVAL_RUN: Test the local skill at $skill_copy/SKILL.md. Follow that copied skill as /kws-codex-plan-executor. For mode=prompt or mode=handoff, do not load implementation-only skills; read SKILL.md, the prompt template, the prompt export checklist, plan.md, and spec.md, then return exactly one fenced text block. Before implementation or clarification, load and follow applicable installed skills, especially using-superpowers; use test-driven-development before feature, bugfix, refactor, or behavior-change implementation and record RED evidence before implementation plus GREEN evidence after the fix. This is not a headless-only rule. This process is already the codex exec target; for mode=headless, do not launch another nested codex exec, and instead execute locally while writing the required CODEX_EVAL_HOME/.codex/orchestrator/<run_id>/ headless artifacts, context.json, state.json, and context_health when CODEX_EVAL_HOME is present. Map headless_sandbox=$headless_sandbox to HEADLESS_SANDBOX=$headless_sandbox. For mode=prompt or mode=handoff, export only: do not create worktrees, state, context snapshots, edit files, execute plan tasks, or enter the TDD implementation loop. Successful completion requires context_health.handoff_ready=true, lifecycle_outcome=finished, and completion_audit.passed=true with prompt_to_artifact_checklist and verification_evidence; blocked/failed outcomes require handoff_reason and context_health.next_action. Do not ask clarifying questions unless the skill requires a blocker. The harness will run fixture checkers after you finish; do not inspect eval fixture YAML, baseline files, .harness metadata, or expected values, and do not run evals/check_execution.py yourself. Use only plan.md, spec.md, repository files, SKILL.md, references, and scripts needed by the copied skill. /kws-codex-plan-executor plan=plan.md spec=spec.md mode=$mode headless_sandbox=$headless_sandbox $fixture_args"

  set +e
  python3 - "$tmpdir" "$prompt" "$eval_home" "$headless_sandbox" <<'PY'
import os
import subprocess
import sys

tmpdir, prompt, eval_home, headless_sandbox = sys.argv[1:5]
timeout = int(os.environ.get("CODEX_EVAL_TIMEOUT_SECONDS", "600"))
log_path = os.path.join(tmpdir, ".harness", "run.jsonl")
final_path = os.path.join(tmpdir, ".harness", "final.md")
env = os.environ.copy()
env["CODEX_EVAL_HOME"] = eval_home
env["HEADLESS_SANDBOX"] = headless_sandbox
cmd = [
    "codex",
    "exec",
    "--cd",
    tmpdir,
    "--sandbox",
    headless_sandbox,
    "--json",
    "--output-last-message",
    final_path,
    prompt,
]
with open(log_path, "w", encoding="utf-8") as log:
    try:
        result = subprocess.run(cmd, cwd=tmpdir, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, env=env)
        raise SystemExit(result.returncode)
    except subprocess.TimeoutExpired:
        log.write(f"\nTIMEOUT after {timeout}s\n")
        raise SystemExit(124)
PY
  codex_status=$?
  set -e

  if [ "$mode" = "prompt" ] || [ "$mode" = "handoff" ]; then
    checker_status=0
    checker_out="$(python3 "$EVAL_DIR/check_prompt.py" --fixture "$fixture_path" --output "$tmpdir/.harness/final.md" 2>&1)" || checker_status=$?
  else
    checker_status=0
    checker_out="$(python3 "$EVAL_DIR/check_execution.py" --fixture "$fixture_path" --workdir "$tmpdir" --final-output "$tmpdir/.harness/final.md" --run-log "$tmpdir/.harness/run.jsonl" 2>&1)" || checker_status=$?
  fi
  if [ "$codex_status" -ne 0 ] || [ "$checker_status" -ne 0 ]; then
    overall_status=1
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
exit "$overall_status"
