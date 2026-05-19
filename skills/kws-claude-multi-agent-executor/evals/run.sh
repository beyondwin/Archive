#!/usr/bin/env bash
# Eval harness for kws-claude-multi-agent-executor.
#
# Usage:
#   ./evals/run.sh                                # run all fixtures
#   ./evals/run.sh fixtures/01-trivial-typo.yaml  # single fixture
#
# Writes per-version baseline to evals/baselines/v<X.Y.Z>.json.
# Reads version from ../SKILL.md frontmatter.

set -euo pipefail

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKILL_DIR="$(dirname "$EVAL_DIR")"
SKILL_VERSION="$(grep '^  version:' "$SKILL_DIR/SKILL.md" | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')"
BASELINE_FILE="$EVAL_DIR/baselines/v${SKILL_VERSION}.json"

mkdir -p "$EVAL_DIR/baselines"
: > "$BASELINE_FILE.partial"

# Deterministic preflight checks — fail fast before running the (expensive)
# fixture loop.
echo "=== Preflight: deterministic checks ==="
# v2.17 cutover (Task 11): check_learning_log.py removed alongside
# scripts/append_learning_event.py. AgentLens parity is verified via
# scripts/compare_agentlens_events.py --self-test instead.
python3 "$SKILL_DIR/scripts/compare_agentlens_events.py" --self-test >/dev/null || {
  echo "FATAL: compare_agentlens_events.py --self-test failed; see output above" >&2
  python3 "$SKILL_DIR/scripts/compare_agentlens_events.py" --self-test >&2
  exit 1
}
python3 "$EVAL_DIR/check_skill_contract.py" --skill "$SKILL_DIR/SKILL.md" >/dev/null || {
  echo "FATAL: check_skill_contract.py failed; see output above" >&2
  python3 "$EVAL_DIR/check_skill_contract.py" --skill "$SKILL_DIR/SKILL.md" >&2
  exit 1
}
# Doc freshness check — non-blocking by default. Set DOC_FRESHNESS_STRICT=1
# to fail the preflight on any drift. See docs/doc-update-protocol.md.
echo "--- Doc freshness (non-blocking by default) ---"
python3 "$EVAL_DIR/check_doc_freshness.py" || {
  if [ "${DOC_FRESHNESS_STRICT:-0}" = "1" ]; then
    echo "FATAL: check_doc_freshness.py failed under DOC_FRESHNESS_STRICT=1" >&2
    exit 1
  fi
  echo "  (above failures reported only; preflight continues — set DOC_FRESHNESS_STRICT=1 to enforce)"
}
echo "=== Preflight passed ==="


fixtures=()
if [ $# -eq 0 ]; then
  while IFS= read -r f; do fixtures+=("$f"); done < <(ls "$EVAL_DIR/fixtures"/*.yaml | sort)
else
  # Accept three forms: absolute path, path relative to $EVAL_DIR ("fixtures/01.yaml"),
  # or path relative to cwd (preferred for tab-completion).
  for f in "$@"; do
    if [ -f "$f" ]; then
      fixtures+=("$(cd "$(dirname "$f")" && pwd -P)/$(basename "$f")")
    elif [ -f "$EVAL_DIR/$f" ]; then
      fixtures+=("$EVAL_DIR/$f")
    else
      echo "FATAL: fixture not found: $f (tried as-is and as $EVAL_DIR/$f)" >&2
      exit 1
    fi
  done
fi

run_one_fixture() {
  local fixture_path="$1"
  local fixture_name
  fixture_name="$(basename "$fixture_path" .yaml)"
  echo "=== Running fixture: $fixture_name ==="

  # Per-fixture isolated parent — the skill creates worktrees at
  # <repo>/../worktrees/, so multiple fixtures sharing $TMPDIR would all
  # write to the same `<TMPDIR>/worktrees/` and collide. Give each fixture
  # its own private parent so `<parent>/worktrees/` is isolated.
  local parent
  parent="$(mktemp -d -t "mae-eval-parent-${fixture_name}.XXXXXX")"
  local tmpdir="$parent/repo"
  mkdir -p "$tmpdir"
  echo "tmpdir: $tmpdir"

  # Parse fixture YAML — we only need a handful of fields.
  # Tolerate yq absent by using python -c with PyYAML if available.
  local parse_py
  parse_py="$(cat <<PY
import sys, yaml, json, os
with open(sys.argv[1]) as fh:
    d = yaml.safe_load(fh)
os.makedirs(sys.argv[2], exist_ok=True)
with open(os.path.join(sys.argv[2], "plan.md"), "w") as fh:
    fh.write(d["plan"])
with open(os.path.join(sys.argv[2], "spec.md"), "w") as fh:
    fh.write(d["spec"])
# extra_files (e.g., fixture 04's plan2.md + spec2.md) — write each name→content pair
for name, content in (d.get("extra_files") or {}).items():
    target = os.path.join(sys.argv[2], name)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w") as fh:
        fh.write(content)
with open(os.path.join(sys.argv[2], "_meta.json"), "w") as fh:
    json.dump({k: d[k] for k in ("name","description","bootstrap","invocation","expected","cost_budget") if k in d}, fh)
PY
)"
  python3 -c "$parse_py" "$fixture_path" "$tmpdir"

  # Bootstrap + gitignore harness scratch BEFORE the first commit so they
  # never appear as untracked → no "dirty tree" gate trip during Phase 0 Step 1.
  ( cd "$tmpdir" && git init -q && git config user.email "eval@example.com" && git config user.name "eval" )
  cat > "$tmpdir/.gitignore" <<'GI'
# Harness-managed artifacts — never committed
_meta.json
bootstrap.log
run.jsonl
judge_input.txt
.harness/
GI
  mkdir -p "$tmpdir/.harness"
  local bootstrap
  bootstrap="$(jq -r '.bootstrap // empty' "$tmpdir/_meta.json")"
  if [ -n "$bootstrap" ]; then
    ( cd "$tmpdir" && bash -euxc "$bootstrap" ) 2>&1 | tee "$tmpdir/.harness/bootstrap.log"
  fi
  ( cd "$tmpdir" && git add -A && git commit -q -m "eval bootstrap" || true )

  # Invoke skill headless.
  # Eval framing preamble — required because v2.6.0 description says
  # "single-session execution is preferable for ≤5-task plans" and Claude
  # will honestly act on that, bypassing the orchestrator if the plan looks
  # trivial. This eval explicitly tests the orchestrator behavior, so we
  # signal that intent up front.
  local invocation
  invocation="$(jq -r '.invocation // ""' "$tmpdir/_meta.json")"
  local eval_preamble="EVAL_RUN: This is an automated regression test of the kws-claude-multi-agent-executor skill. Execute the skill exactly as written — do not substitute direct edits for the orchestrator workflow, do not ask clarifying questions, do not bypass steps based on perceived task triviality. The eval is scored on BOTH outcome correctness AND skill adherence (worktree created, state.json populated, sub-agent commits visible)."
  local start_ts
  start_ts="$(date +%s)"
  # Per-fixture isolated AgentLens home so adherence detection scans only
  # events emitted by THIS fixture, never the user's main DB. Inherited by
  # the headless claude child via the environment.
  local agentlens_home="$tmpdir/.harness/agentlens"
  mkdir -p "$agentlens_home"
  ( cd "$tmpdir" && AGENTLENS_HOME="$agentlens_home" \
    claude -p --dangerously-skip-permissions \
      --output-format stream-json --verbose \
      "${eval_preamble}

/kws-claude-multi-agent-executor plan=plan.md spec=spec.md mode=interactive $invocation" \
      > .harness/run.jsonl 2>&1 ) || true
  local end_ts
  end_ts="$(date +%s)"
  local wall_min
  wall_min=$(( (end_ts - start_ts) / 60 ))

  # Token usage from stream-json (sum of input + output across all events)
  local total_tokens
  total_tokens="$(jq -s '[.[] | select(.type=="usage") | (.input_tokens // 0) + (.output_tokens // 0)] | add // 0' "$tmpdir/.harness/run.jsonl" 2>/dev/null || echo 0)"

  # Capture artifacts.
  local state_file
  state_file="$(ls -t "$tmpdir"/../worktrees/*/.orchestrator/state.json "$tmpdir"/.claude/worktrees/*/.orchestrator/state.json 2>/dev/null | head -1 || true)"
  local task_statuses=""
  local git_log=""
  local files_changed=""
  if [ -n "$state_file" ] && [ -f "$state_file" ]; then
    task_statuses="$(jq '.tasks' "$state_file" 2>/dev/null || echo '{}')"
    files_changed="$(jq -r '[.tasks[].files // []] | flatten | unique | join("\n")' "$state_file" 2>/dev/null || echo '')"
    local worktree_path
    worktree_path="$(dirname "$(dirname "$state_file")")"
    git_log="$(git -C "$worktree_path" log --oneline -n 30 2>/dev/null || echo '')"
  fi

  # Test outcome (best effort — only if fixture set test_after).
  local test_after
  test_after="$(jq -r '.expected.test_after // empty' "$tmpdir/_meta.json")"
  local test_output=""
  if [ -n "$test_after" ] && [ -n "$state_file" ]; then
    test_output="$( cd "$(dirname "$(dirname "$state_file")")" && bash -c "$test_after" 2>&1 || true )"
  fi

  # Build judge input.
  local diff_tail=""
  local wt=""
  if [ -n "$state_file" ]; then
    wt="$(dirname "$(dirname "$state_file")")"
    diff_tail="$(git -C "$wt" diff HEAD~5..HEAD 2>/dev/null | tail -200 || echo '')"
  fi

  # Run rubric.py for deterministic correctness measurement (only if fixture has rubric block).
  local rubric_results="(no rubric block in fixture)"
  local rubric_pass_rate="null"
  if [ -n "$wt" ] && jq -e '.expected.rubric' "$tmpdir/_meta.json" >/dev/null 2>&1; then
    local rubric_file="$tmpdir/.harness/rubric.json"
    if python3 "$EVAL_DIR/rubric.py" --fixture "$fixture_path" --workdir "$wt" --output "$rubric_file" 2>"$tmpdir/.harness/rubric.err"; then
      rubric_results="$(cat "$rubric_file")"
      rubric_pass_rate="$(jq -r '.summary.pass_rate // "null"' "$rubric_file")"
    else
      rubric_results="$(printf 'rubric runner failed: %s' "$(cat "$tmpdir/.harness/rubric.err" 2>/dev/null || echo '(no stderr)')")"
    fi
  fi
  echo "  rubric pass_rate: $rubric_pass_rate"

  # Learning-log adherence check (v2.17+) — detect whether the orchestrator
  # actually executed the Phase 0 boundary emit step that publishes
  # `kws-cme.phase_0_started` to AgentLens. Pre-v2.17 evals grepped run.jsonl
  # for a `LEARNING_LOG_INIT:` marker; the AgentLens cutover (Task 11)
  # removed that helper. The equivalent AgentLens query against the
  # per-fixture isolated AGENTLENS_HOME is now authoritative.
  local llog_marker_count=0
  local agentlens_bin
  agentlens_bin="$(command -v agentlens 2>/dev/null || true)"
  if [ -n "$agentlens_bin" ] && [ -d "$agentlens_home/runs" ]; then
    llog_marker_count="$(AGENTLENS_HOME="$agentlens_home" "$agentlens_bin" events \
        --type 'kws-cme.phase_0_started' 2>/dev/null | wc -l | tr -d ' ' || echo 0)"
  fi
  local adherence
  if [ -z "$agentlens_bin" ]; then
    adherence="unknown (agentlens CLI not on PATH — install AgentLens to enable adherence detection)"
  elif [ "$llog_marker_count" -gt 0 ]; then
    adherence="yes (AgentLens event emitted)"
  else
    adherence="no (Phase 0 boundary emit skipped)"
  fi
  echo "  learning_log_adherence: $adherence (events=$llog_marker_count)"

  local judge_prompt
  judge_prompt="$(python3 -c '
import sys, json
template = open(sys.argv[1]).read()
meta = json.load(open(sys.argv[2]))
subs = {
    "fixture_name": sys.argv[3],
    "fixture_description": (meta.get("description") or "").strip(),
    "cost_budget_wallclock_minutes": str((meta.get("cost_budget") or {}).get("wallclock_minutes", 30)),
    "cost_budget_tokens": str((meta.get("cost_budget") or {}).get("tokens", 500000)),
    "wall_time": sys.argv[4],
    "total_tokens": sys.argv[5],
}
for k, v in subs.items():
    template = template.replace("{" + k + "}", v)
sys.stdout.write(template)
' "$EVAL_DIR/judge.md" "$tmpdir/_meta.json" "$fixture_name" "$wall_min" "$total_tokens")"

  # Append captured payloads as substitution (multi-line — write to temp file).
  local judge_input="$tmpdir/.harness/judge_input.txt"
  {
    printf '%s\n' "$judge_prompt"
    printf '\n\n### ACTUAL DATA (replaces placeholders if any remained):\n'
    printf '\n#### fixture_expected_yaml\n%s\n' "$(jq -r '.expected' "$tmpdir/_meta.json")"
    printf '\n#### rubric_results (deterministic — authoritative for correctness)\n%s\n' "$rubric_results"
    printf '\n#### captured_task_statuses\n%s\n' "$task_statuses"
    printf '\n#### captured_git_log\n%s\n' "$git_log"
    printf '\n#### captured_files_changed\n%s\n' "$files_changed"
    printf '\n#### captured_test_output\n%s\n' "$test_output"
    printf '\n#### captured_diff_tail\n%s\n' "$diff_tail"
  } > "$judge_input"

  local judge_out
  judge_out="$(claude -p --dangerously-skip-permissions "$(cat "$judge_input")" 2>/dev/null || echo '{"fixture":"'"$fixture_name"'","scores":{"correctness":0,"spec_compliance":0,"code_quality":0,"cost_efficiency":0},"mean":0,"passed":false,"notes":"judge invocation failed"}')"

  # Extract JSON object from judge output.
  local judge_json
  judge_json="$(printf '%s' "$judge_out" | sed -n '/^{/,/^}$/p' | head -200 || echo '{}')"
  if ! printf '%s' "$judge_json" | jq -e . >/dev/null 2>&1; then
    judge_json='{"fixture":"'"$fixture_name"'","scores":{"correctness":0,"spec_compliance":0,"code_quality":0,"cost_efficiency":0},"mean":0,"passed":false,"notes":"judge output unparseable"}'
  fi

  printf '%s\n' "$judge_json" >> "$BASELINE_FILE.partial"
  echo "=== Fixture $fixture_name scored: $(printf '%s' "$judge_json" | jq -r '.mean') ==="
}

for f in "${fixtures[@]}"; do
  run_one_fixture "$f"
done

# Aggregate baseline.
jq -s '{version: "'"$SKILL_VERSION"'", date: now | todate, fixtures: .}' "$BASELINE_FILE.partial" > "$BASELINE_FILE"
rm -f "$BASELINE_FILE.partial"
echo "=== Baseline written: $BASELINE_FILE ==="
jq '.fixtures | map({fixture, mean, passed})' "$BASELINE_FILE"
