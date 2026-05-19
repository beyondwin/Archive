#!/usr/bin/env bash
# query_state.sh - Read-only no-LLM queries against a LIVE run's state.json.
#
# Usage:
#   query_state.sh --orch-dir <abs_path> <subcommand> [opts]
#   query_state.sh --run-id <id> <subcommand> [opts]       (forwards to query_run.sh)
#
# Path layout: <abs_path> is the orchestrator state directory at
# ~/.claude/orchestrator/<RUN_ID>/; the script reads <abs_path>/state.json directly.
#
# Subcommands:
#   current      current task + step within task
#   progress     N/M complete + warn + fail + skipped + active
#   cost         totals + by-role + by-model breakdown
#   warn         list WARN tasks with truncated warning text
#   tier-dist    count of PASS / WARN / FAIL / SKIPPED across all plans
#   quality      first-5 mean, last-5 mean, trend direction
#   eta          completed/total * elapsed (projection)
#   failures     tasks with escalation_count>0 or review_retries>0
#
# Exit codes: 0 success, 1 state.json missing, 2 jq parse failure, 3 unknown subcommand.
# All results go to stdout; diagnostics go to stderr.

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  cat <<'EOF' >&2
Usage: query_state.sh --orch-dir <abs_path> <subcommand> [opts]
       query_state.sh --run-id <id> <subcommand> [opts]   (forwards to query_run.sh)

<abs_path> is the orchestrator state dir, e.g. ~/.claude/orchestrator/<RUN_ID>/

Subcommands:
  current  progress  cost  warn  tier-dist  quality  eta  failures
EOF
}

# ---------- shared jq filter library ----------
# Active-tree resolver: returns the per-plan tree (plan_chain[active_plan]) when
# plan_chain exists, else the top-level state (single-plan v2.12 layout).
# We discriminate on `has("plan_chain")`, NOT on the type of active_plan,
# because v2.12 single-plan state can carry a string active_plan (e.g. "plan1").
QS_FILTER_ACTIVE='
  if has("plan_chain") and (.plan_chain | type) == "array" then
    .plan_chain[.active_plan]
  else
    .
  end
'

# All-tasks across all plans (multi-plan) OR top-level tasks (single-plan).
QS_FILTER_ALL_TASKS='
  if has("plan_chain") and (.plan_chain | type) == "array" then
    [ .plan_chain[] | (.tasks // {}) | to_entries[] ]
  else
    [ (.tasks // {}) | to_entries[] ]
  end
'

# ---------- arg parse ----------
MODE=""        # "orch-dir" | "run-id"
ORCH_DIR=""
RUN_ID=""
SUBCMD=""
EXTRA_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --orch-dir)
      MODE="orch-dir"
      ORCH_DIR="${2:-}"
      shift 2
      ;;
    --run-id)
      MODE="run-id"
      RUN_ID="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ -z "${SUBCMD}" ]; then
        SUBCMD="$1"
      else
        EXTRA_ARGS+=("$1")
      fi
      shift
      ;;
  esac
done

if [ -z "${MODE}" ]; then
  echo "query_state.sh: must pass --orch-dir <path> or --run-id <id>" >&2
  usage
  exit 3
fi

# Forward --run-id to query_run.sh
if [ "${MODE}" = "run-id" ]; then
  exec "${SCRIPT_DIR}/query_run.sh" --run-id "${RUN_ID}" "${SUBCMD}" ${EXTRA_ARGS+"${EXTRA_ARGS[@]}"}
fi

if [ -z "${ORCH_DIR}" ]; then
  echo "query_state.sh: --orch-dir value is empty" >&2
  exit 3
fi

if [ -z "${SUBCMD}" ]; then
  echo "query_state.sh: missing subcommand" >&2
  usage
  exit 3
fi

STATE="${ORCH_DIR%/}/state.json"
if [ ! -f "${STATE}" ]; then
  echo "query_state.sh: state.json not found at ${STATE}" >&2
  exit 1
fi

# Pre-validate JSON
if ! jq -e . "${STATE}" >/dev/null 2>&1; then
  echo "query_state.sh: failed to parse JSON at ${STATE}" >&2
  exit 2
fi

# ---------- subcommand: current ----------
qs_current() {
  jq -r --argjson af 0 '
    . as $root
    | ($root.current_task // 0) as $ct
    | ($root.current_step_within_task // 0) as $cs
    | "current_task=\($ct) step=\($cs)"
  ' "${STATE}"
}

# ---------- subcommand: progress ----------
qs_progress() {
  jq -r '
    . as $root
    | (if ($root | has("plan_chain")) and (($root.plan_chain // null) | type) == "array"
        then [ $root.plan_chain[] | (.tasks // {}) | to_entries[] ]
        else [ ($root.tasks // {}) | to_entries[] ]
       end) as $entries
    | ($entries | length) as $total
    | ([ $entries[] | select(.value.status == "COMPLETE") ] | length) as $complete
    | ([ $entries[] | select(.value.review_tier == "WARN") ] | length) as $warn
    | ([ $entries[] | select(.value.review_tier == "FAIL") ] | length) as $fail
    | ([ $entries[] | select(.value.status == "SKIPPED") ] | length) as $skipped
    | ([ $entries[] | select(.value.status == "IN_PROGRESS") ] | length) as $active
    | "\($complete)/\($total) COMPLETE | \($warn) WARN | \($fail) FAIL | \($skipped) SKIPPED | \($active) active"
  ' "${STATE}"
}

# ---------- subcommand: cost ----------
qs_cost() {
  jq -r '
    . as $root
    | ($root.cost_ledger // {}) as $cl
    | ($cl.totals // {}) as $t
    | ($t.cost_usd // 0) as $cost
    | ($t.input_tokens // 0) as $in
    | ($t.output_tokens // 0) as $out
    | ($t.cached_read_tokens // 0) as $cr
    | ($t.cached_write_tokens // 0) as $cw
    | ($t.dispatches // 0) as $d
    | "totals: $\($cost | tonumber * 100 | round / 100) | in=\($in) out=\($out) cached_r=\($cr) cached_w=\($cw) dispatches=\($d)"
    , ( ($cl.by_role // {}) | to_entries
        | if length == 0 then "by_role: (none)" else
            "by_role: " + ([ .[] | "\(.key)=$\((.value.cost_usd // 0) | tonumber * 100 | round / 100)" ] | join(" "))
          end )
    , ( ($cl.by_model // {}) | to_entries
        | if length == 0 then "by_model: (none)" else
            "by_model: " + ([ .[] | "\(.key)=$\((.value.cost_usd // 0) | tonumber * 100 | round / 100)" ] | join(" "))
          end )
  ' "${STATE}"
}

# ---------- subcommand: warn ----------
qs_warn() {
  jq -r '
    . as $root
    | (if ($root | has("plan_chain")) and (($root.plan_chain // null) | type) == "array"
        then [ $root.plan_chain[] | { tasks: (.tasks // {}), summaries: (.task_summaries // {}) } ]
        else [ { tasks: ($root.tasks // {}), summaries: ($root.task_summaries // {}) } ]
       end) as $trees
    | [ $trees[] |
          (.tasks | to_entries) as $te
          | (.summaries) as $sum
          | $te[] | select(.value.review_tier == "WARN") |
              { id: .key,
                warnings: ($sum[.key].warnings // []) } ]
    | if length == 0 then "(no WARN tasks)" else
        .[] |
          (.warnings | if length == 0 then "(no warning text)" else
              ([ .[] | tostring ] | join(" / ")) end) as $w
          | (if ($w | length) > 120 then ($w[0:117] + "...") else $w end) as $wt
          | "\(.id): \($wt)"
      end
  ' "${STATE}"
}

# ---------- subcommand: tier-dist ----------
qs_tier_dist() {
  jq -r '
    . as $root
    | (if ($root | has("plan_chain")) and (($root.plan_chain // null) | type) == "array"
        then [ $root.plan_chain[] | (.tasks // {}) | to_entries[] ]
        else [ ($root.tasks // {}) | to_entries[] ]
       end) as $entries
    | ([ $entries[] | select(.value.review_tier == "PASS") ] | length) as $p
    | ([ $entries[] | select(.value.review_tier == "WARN") ] | length) as $w
    | ([ $entries[] | select(.value.review_tier == "FAIL") ] | length) as $f
    | ([ $entries[] | select(.value.status == "SKIPPED") ] | length) as $s
    | "PASS=\($p) WARN=\($w) FAIL=\($f) SKIPPED=\($s)"
  ' "${STATE}"
}

# ---------- subcommand: quality ----------
qs_quality() {
  jq -r '
    . as $root
    | (if ($root | has("plan_chain")) and (($root.plan_chain // null) | type) == "array"
        then [ $root.plan_chain[] | (.quality_trend // [])[] ]
        else ($root.quality_trend // [])
       end) as $qt
    | ($qt | length) as $n
    | if $n == 0 then "quality: (no scores yet)" else
        ($qt[0:5] | (if length > 0 then (add / length) else 0 end)) as $first5
        | ($qt[(if $n >= 5 then $n - 5 else 0 end):] | (if length > 0 then (add / length) else 0 end)) as $last5
        | ($last5 - $first5) as $delta
        | (if $delta > 0.05 then "up"
           elif $delta < -0.05 then "down"
           else "flat" end) as $dir
        | "quality: first5=\($first5 * 100 | round / 100) last5=\($last5 * 100 | round / 100) trend=\($dir) (n=\($n))"
      end
  ' "${STATE}"
}

# ---------- subcommand: eta ----------
qs_eta() {
  jq -r '
    . as $root
    | (if ($root | has("plan_chain")) and (($root.plan_chain // null) | type) == "array"
        then [ $root.plan_chain[] | (.tasks // {}) | to_entries[] ]
        else [ ($root.tasks // {}) | to_entries[] ]
       end) as $entries
    | ($entries | length) as $total
    | ([ $entries[] | select(.value.status == "COMPLETE") ] | length) as $done
    | ($root.timestamps.started_at // null) as $started
    | if $total == 0 or $done == 0 or $started == null then
        "eta: insufficient data (done=\($done)/\($total) started=\($started // "null"))"
      else
        "eta: \($done)/\($total) complete (started=\($started))"
      end
  ' "${STATE}"
}

# ---------- subcommand: failures ----------
qs_failures() {
  jq -r '
    . as $root
    | (if ($root | has("plan_chain")) and (($root.plan_chain // null) | type) == "array"
        then [ $root.plan_chain[] | (.tasks // {}) | to_entries[] ]
        else [ ($root.tasks // {}) | to_entries[] ]
       end) as $entries
    | [ $entries[] | select(((.value.escalation_count // .value.escalations // 0) > 0) or ((.value.review_retries // 0) > 0)) ]
    | if length == 0 then "(no failures)" else
        .[] | "\(.key): esc=\(.value.escalation_count // .value.escalations // 0) retries=\(.value.review_retries // 0) tier=\(.value.review_tier // "?")"
      end
  ' "${STATE}"
}

case "${SUBCMD}" in
  current)   qs_current ;;
  progress)  qs_progress ;;
  cost)      qs_cost ;;
  warn)      qs_warn ;;
  tier-dist) qs_tier_dist ;;
  quality)   qs_quality ;;
  eta)       qs_eta ;;
  failures)  qs_failures ;;
  *)
    echo "query_state.sh: unknown subcommand: ${SUBCMD}" >&2
    usage
    exit 3
    ;;
esac
