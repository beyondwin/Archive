#!/usr/bin/env bash
# Behavioral tests for query_state.sh active-tree resolution.
#
# Guards against silent corruption at the v2.12 single-plan / v2.13 plan_chain
# schema boundary: a multi-plan run with active_plan=1 must read tasks from
# plan_chain[1], NOT from top-level state.tasks. Hard-coding the wrong path
# diverges plan-level forensics from execution reality — see SKILL.md
# "Active-tree resolution (v2.13)" rule and the `QS_FILTER_ACTIVE` jq prelude.
#
# Exit 0 on all pass, 1 on any failure.

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUERY_STATE="${SCRIPT_DIR}/query_state.sh"

if [ ! -x "${QUERY_STATE}" ]; then
  echo "FATAL: ${QUERY_STATE} not executable" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

pass=0
fail=0

assert_eq() {
  # assert_eq <label> <expected> <actual>
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [ "${expected}" = "${actual}" ]; then
    pass=$((pass + 1))
    echo "  PASS  ${label}"
  else
    fail=$((fail + 1))
    echo "  FAIL  ${label}" >&2
    echo "        expected: ${expected}" >&2
    echo "        actual:   ${actual}" >&2
  fi
}

make_worktree() {
  # make_worktree <name> <state_json_content>
  # Returns absolute path to the orchestrator state dir on stdout.
  # (Named make_worktree for historical reasons; in v2.18 layout this is
  # actually the <orch_dir>, a sibling of the worktree under ~/.claude/.)
  local name="$1"
  local content="$2"
  local od="${tmpdir}/${name}"
  mkdir -p "${od}"
  printf '%s' "${content}" > "${od}/state.json"
  printf '%s' "${od}"
}

# ---------- Case 1: single-plan (v2.12 layout, no plan_chain) ----------
# Top-level tasks: 2 COMPLETE / 1 WARN / 0 FAIL / 0 SKIPPED.
echo "Case 1: single-plan (top-level)"
wt1=$(make_worktree "single-plan" '{
  "schema_version": "2",
  "tasks": {
    "1": {"status": "COMPLETE", "review_tier": "PASS"},
    "2": {"status": "COMPLETE", "review_tier": "WARN"},
    "3": {"status": "IN_PROGRESS", "review_tier": null}
  },
  "task_summaries": {"2": {"warnings": ["minor style nit"]}},
  "quality_trend": [0.7, 0.8, 0.9]
}')
out1=$("${QUERY_STATE}" --orch-dir "${wt1}" progress)
assert_eq "single-plan progress aggregates top-level tasks" \
  "2/3 COMPLETE | 1 WARN | 0 FAIL | 0 SKIPPED | 1 active" \
  "${out1}"

# ---------- Case 2: multi-plan, active_plan=0 ----------
# plan_chain[0]: 1 COMPLETE / 1 IN_PROGRESS
# plan_chain[1]: 1 COMPLETE (DIFFERENT data — proves we aggregate across all,
#   NOT just the active plan; per current query_state.sh contract, `progress`
#   walks every plan_chain[*].tasks).
echo "Case 2: multi-plan active_plan=0"
wt2=$(make_worktree "multi-active-0" '{
  "schema_version": "2",
  "active_plan": 0,
  "plan_chain": [
    {"index": 0, "tasks": {
      "1": {"status": "COMPLETE", "review_tier": "PASS"},
      "2": {"status": "IN_PROGRESS", "review_tier": null}
    }, "task_summaries": {}, "quality_trend": [0.8]},
    {"index": 1, "tasks": {
      "1": {"status": "COMPLETE", "review_tier": "FAIL"}
    }, "task_summaries": {}, "quality_trend": []}
  ]
}')
out2=$("${QUERY_STATE}" --orch-dir "${wt2}" progress)
assert_eq "multi-plan progress aggregates across all plans (active=0)" \
  "2/3 COMPLETE | 0 WARN | 1 FAIL | 0 SKIPPED | 1 active" \
  "${out2}"

tier2=$("${QUERY_STATE}" --orch-dir "${wt2}" tier-dist)
assert_eq "multi-plan tier-dist aggregates across all plans" \
  "PASS=1 WARN=0 FAIL=1 SKIPPED=0" \
  "${tier2}"

# ---------- Case 3: multi-plan, active_plan=1 (CRITICAL silent-corruption guard) ----------
# Same shape as Case 2 but active_plan=1. If the resolver hardcoded top-level
# .tasks (the silent-corruption hazard), aggregations would be wrong because
# top-level .tasks is empty / absent.
echo "Case 3: multi-plan active_plan=1"
wt3=$(make_worktree "multi-active-1" '{
  "schema_version": "2",
  "active_plan": 1,
  "plan_chain": [
    {"index": 0, "tasks": {
      "1": {"status": "COMPLETE", "review_tier": "PASS"},
      "2": {"status": "COMPLETE", "review_tier": "PASS"}
    }, "task_summaries": {}, "quality_trend": [0.9, 0.85]},
    {"index": 1, "tasks": {
      "1": {"status": "COMPLETE", "review_tier": "WARN"},
      "2": {"status": "IN_PROGRESS", "review_tier": null}
    }, "task_summaries": {"1": {"warnings": ["plan2-warn"]}}, "quality_trend": [0.7]}
  ]
}')
out3=$("${QUERY_STATE}" --orch-dir "${wt3}" progress)
assert_eq "multi-plan progress sees plan_chain[1] data (active=1)" \
  "3/4 COMPLETE | 1 WARN | 0 FAIL | 0 SKIPPED | 1 active" \
  "${out3}"

warn3=$("${QUERY_STATE}" --orch-dir "${wt3}" warn)
case "${warn3}" in
  *"plan2-warn"*) assert_eq "multi-plan warn surfaces plan_chain[1] warnings" "found" "found" ;;
  *) assert_eq "multi-plan warn surfaces plan_chain[1] warnings" "found" "missing: ${warn3}" ;;
esac

# ---------- Case 4: quality trend aggregates across plans ----------
# plan_chain[0].quality_trend = [0.9, 0.85], plan_chain[1].quality_trend = [0.7]
# concatenated: [0.9, 0.85, 0.7] → first5 = (0.9+0.85+0.7)/3 ≈ 0.82, last5 same.
echo "Case 4: quality aggregates across plan_chain"
qual3=$("${QUERY_STATE}" --orch-dir "${wt3}" quality)
case "${qual3}" in
  *"n=3"*) assert_eq "quality trend includes scores from every plan" "n=3" "n=3" ;;
  *) assert_eq "quality trend includes scores from every plan" "n=3" "missing: ${qual3}" ;;
esac

# ---------- Case 5: plan_chain with NON-ARRAY value falls back to top-level ----------
# Defensive guard: SKILL.md prose says discriminator is `has("plan_chain")` AND
# array shape. A malformed state.json with plan_chain=null must NOT crash.
echo "Case 5: plan_chain=null falls back to top-level"
wt5=$(make_worktree "plan-chain-null" '{
  "schema_version": "2",
  "plan_chain": null,
  "tasks": {"1": {"status": "COMPLETE", "review_tier": "PASS"}}
}')
out5=$("${QUERY_STATE}" --orch-dir "${wt5}" progress 2>&1) || true
assert_eq "plan_chain=null does not crash; reads top-level" \
  "1/1 COMPLETE | 0 WARN | 0 FAIL | 0 SKIPPED | 0 active" \
  "${out5}"

# ---------- summary ----------
echo
echo "Results: ${pass} passed, ${fail} failed"
if [ "${fail}" -gt 0 ]; then
  exit 1
fi
