#!/usr/bin/env bash
# query_run.sh - Read-only no-LLM queries against ARCHIVED state.final.json.
#
# Usage:
#   query_run.sh --run-id <id> <subcommand> [opts]
#   query_run.sh --run-id <date>/<id> <subcommand> [opts]
#   query_run.sh --run-id last <subcommand> [opts]
#   query_run.sh list-runs
#   query_run.sh last [<subcommand>]
#   query_run.sh find <plan-slug> [<subcommand>]
#
# Subcommands: same as query_state.sh, plus list-runs / last / find.
# Reads ~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<id>/artifacts/state.final.json.
# Failover (when state.final.json missing): meta.json for outcome-only queries.
#
# Exit codes: 0 success, 1 state missing, 2 jq parse failure, 3 unknown subcommand.

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUERY_STATE="${SCRIPT_DIR}/query_state.sh"
RUNS_ROOT="${HOME}/.claude/learning/kws-claude-multi-agent-executor/runs"

# Cleanup list for shim worktrees built from state.final.json.
SHIM_DIRS=()
cleanup_shims() {
  local d
  for d in ${SHIM_DIRS[@]+"${SHIM_DIRS[@]}"}; do
    [ -n "${d}" ] && [ -d "${d}" ] && rm -rf "${d}"
  done
}
trap cleanup_shims EXIT

usage() {
  cat <<'EOF' >&2
Usage:
  query_run.sh --run-id <id|date/id|last> <subcommand>
  query_run.sh list-runs
  query_run.sh last [<subcommand>]
  query_run.sh find <plan-slug> [<subcommand>]

Subcommands: current progress cost warn tier-dist quality eta failures outcome
EOF
}

# Resolve a run-id (full id, date/id, or "last") to a run directory absolute path.
# Echoes the run_dir on stdout, or empty + non-zero exit on failure.
resolve_run_dir() {
  local rid="$1"
  if [ -z "${rid}" ]; then
    return 1
  fi
  if [ "${rid}" = "last" ]; then
    # Glob all run dirs, sort reverse, take first.
    local latest
    latest="$(ls -d "${RUNS_ROOT}"/*/*/ 2>/dev/null | sort -r | head -n1)"
    if [ -z "${latest}" ]; then
      return 1
    fi
    echo "${latest%/}"
    return 0
  fi
  # date/id form
  case "${rid}" in
    */*)
      local cand="${RUNS_ROOT}/${rid}"
      if [ -d "${cand}" ]; then
        echo "${cand}"
        return 0
      fi
      return 1
      ;;
  esac
  # Bare id - search under any date dir.
  local match
  match="$(ls -d "${RUNS_ROOT}"/*/"${rid}"/ 2>/dev/null | head -n1)"
  if [ -n "${match}" ]; then
    echo "${match%/}"
    return 0
  fi
  return 1
}

# Pull plan_slug (basename of plan_path minus .md) from meta.json. Echo "?" on miss.
plan_slug_for() {
  local run_dir="$1"
  local meta="${run_dir}/meta.json"
  if [ ! -f "${meta}" ]; then
    echo "?"
    return 0
  fi
  jq -r '
    (.plan_path // "")
    | if . == "" then "?" else
        (split("/") | .[-1]) | (sub("\\.md$"; ""))
      end
  ' "${meta}" 2>/dev/null || echo "?"
}

outcome_for() {
  local run_dir="$1"
  local meta="${run_dir}/meta.json"
  if [ ! -f "${meta}" ]; then
    echo "?"
    return 0
  fi
  jq -r '.outcome // "?"' "${meta}" 2>/dev/null || echo "?"
}

date_for() {
  # date is the parent dir name of the run dir under runs/
  local run_dir="$1"
  local d
  d="$(dirname "${run_dir}")"
  basename "${d}"
}

run_id_for() {
  basename "$1"
}

# Echo absolute state.final.json path or empty.
state_final_for() {
  local run_dir="$1"
  local p="${run_dir}/artifacts/state.final.json"
  if [ -f "${p}" ]; then
    echo "${p}"
  fi
}

# Build a temporary worktree-shaped dir from a state.final.json so we can reuse
# query_state.sh logic. Caller responsible for cleanup.
build_shim_worktree() {
  local state_path="$1"
  local tmp
  tmp="$(mktemp -d -t qrun.XXXXXX)"
  mkdir -p "${tmp}/.orchestrator"
  cp "${state_path}" "${tmp}/.orchestrator/state.json"
  echo "${tmp}"
}

# Forward a subcommand against a resolved run_dir.
run_subcmd_on_dir() {
  local run_dir="$1"
  local sub="$2"
  shift 2
  local sf
  sf="$(state_final_for "${run_dir}")"
  if [ "${sub}" = "outcome" ]; then
    outcome_for "${run_dir}"
    return 0
  fi
  if [ -z "${sf}" ]; then
    # Failover: only outcome works without state.final.json.
    echo "query_run.sh: state.final.json missing for $(run_id_for "${run_dir}"); only 'outcome' subcommand available" >&2
    exit 1
  fi
  local shim
  shim="$(build_shim_worktree "${sf}")"
  # Append to global cleanup list (avoid trap-local unbound-var issues under set -u).
  SHIM_DIRS+=("${shim}")
  "${QUERY_STATE}" --worktree "${shim}" "${sub}" "$@"
}

cmd_list_runs() {
  # Enumerate up to last 20 runs reverse chronological.
  if [ ! -d "${RUNS_ROOT}" ]; then
    echo "(no runs found at ${RUNS_ROOT})"
    return 0
  fi
  local dirs
  dirs="$(ls -d "${RUNS_ROOT}"/*/*/ 2>/dev/null | sort -r | head -n20 || true)"
  if [ -z "${dirs}" ]; then
    echo "(no runs)"
    return 0
  fi
  local d rid date slug oc
  while IFS= read -r d; do
    [ -z "${d}" ] && continue
    d="${d%/}"
    rid="$(run_id_for "${d}")"
    date="$(date_for "${d}")"
    slug="$(plan_slug_for "${d}")"
    oc="$(outcome_for "${d}")"
    printf '%s  %s  %s  %s\n' "${date}" "${rid}" "${slug}" "${oc}"
  done <<<"${dirs}"
}

cmd_last() {
  local sub="${1:-outcome}"
  shift || true
  local rd
  if ! rd="$(resolve_run_dir last)"; then
    echo "query_run.sh: no runs found" >&2
    exit 1
  fi
  if [ "${sub}" = "outcome" ]; then
    local date slug oc
    date="$(date_for "${rd}")"
    slug="$(plan_slug_for "${rd}")"
    oc="$(outcome_for "${rd}")"
    echo "last ($(run_id_for "${rd}"), ${date}, ${slug}): ${oc}"
    return 0
  fi
  if [ "${sub}" = "cost" ]; then
    # Spec A4 single-line format.
    local sf
    sf="$(state_final_for "${rd}")"
    if [ -z "${sf}" ]; then
      echo "query_run.sh: state.final.json missing; cannot compute cost" >&2
      exit 1
    fi
    local date slug oc
    date="$(date_for "${rd}")"
    slug="$(plan_slug_for "${rd}")"
    oc="$(outcome_for "${rd}")"
    jq -r --arg date "${date}" --arg slug "${slug}" --arg oc "${oc}" '
      (.cost_ledger // {}) as $cl
      | ($cl.totals.cost_usd // 0) as $total
      | ($cl.by_role // {}) as $br
      | ($cl.by_model // {}) as $bm
      | (($br.implementer.cost_usd // 0)) as $imp
      | (($br.reviewer.cost_usd // 0)) as $rev
      | (($br.verifier.cost_usd // 0)) as $ver
      | (($bm.sonnet.cost_usd // 0)) as $son
      | (($bm.opus.cost_usd // 0)) as $opu
      | (if $total > 0 then ($imp / $total * 100 | floor) else 0 end) as $impP
      | (if $total > 0 then ($rev / $total * 100 | floor) else 0 end) as $revP
      | (if $total > 0 then ($ver / $total * 100 | floor) else 0 end) as $verP
      | "last (\($date), \($slug), \($oc)): $\($total * 100 | round / 100) total | implementer \($impP)% (sonnet $\($son * 100 | round / 100), opus $\($opu * 100 | round / 100)) | reviewer \($revP)% | verifier \($verP)%"
    ' "${sf}"
    return 0
  fi
  run_subcmd_on_dir "${rd}" "${sub}" "$@"
}

cmd_find() {
  local slug="${1:-}"
  if [ -z "${slug}" ]; then
    echo "query_run.sh: find requires <plan-slug>" >&2
    exit 3
  fi
  shift
  local sub="${1:-outcome}"
  shift || true
  if [ ! -d "${RUNS_ROOT}" ]; then
    echo "(no runs)"
    return 0
  fi
  local dirs
  dirs="$(ls -d "${RUNS_ROOT}"/*/*/ 2>/dev/null | sort -r || true)"
  local found=0
  local d
  while IFS= read -r d; do
    [ -z "${d}" ] && continue
    d="${d%/}"
    local match_slug
    match_slug="$(plan_slug_for "${d}")"
    if [ "${match_slug}" = "${slug}" ]; then
      found=1
      printf '=== %s/%s (%s) ===\n' "$(date_for "${d}")" "$(run_id_for "${d}")" "$(outcome_for "${d}")"
      if [ "${sub}" = "outcome" ]; then
        outcome_for "${d}"
      else
        # Don't exit on a single failure; print and continue.
        (run_subcmd_on_dir "${d}" "${sub}" "$@") || true
      fi
    fi
  done <<<"${dirs}"
  if [ "${found}" -eq 0 ]; then
    echo "(no runs match slug=${slug})"
  fi
}

# ---------- arg parse ----------
MODE=""
RUN_ID=""
SUBCMD=""
EXTRA_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
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

if [ -z "${MODE}" ] && [ -z "${SUBCMD}" ]; then
  usage
  exit 3
fi

if [ "${MODE}" = "run-id" ]; then
  if [ -z "${SUBCMD}" ]; then
    SUBCMD="outcome"
  fi
  if [ -z "${RUN_ID}" ]; then
    echo "query_run.sh: --run-id value is empty" >&2
    exit 3
  fi
  RD=""
  if ! RD="$(resolve_run_dir "${RUN_ID}")"; then
    echo "query_run.sh: could not resolve run-id: ${RUN_ID}" >&2
    exit 1
  fi
  case "${SUBCMD}" in
    outcome)
      outcome_for "${RD}"
      ;;
    list-runs)
      echo "query_run.sh: list-runs takes no --run-id" >&2
      exit 3
      ;;
    current|progress|cost|warn|tier-dist|quality|eta|failures)
      run_subcmd_on_dir "${RD}" "${SUBCMD}" ${EXTRA_ARGS+"${EXTRA_ARGS[@]}"}
      ;;
    *)
      echo "query_run.sh: unknown subcommand: ${SUBCMD}" >&2
      usage
      exit 3
      ;;
  esac
  exit 0
fi

# No --run-id: standalone verb dispatch.
case "${SUBCMD}" in
  list-runs)
    cmd_list_runs
    ;;
  last)
    cmd_last ${EXTRA_ARGS+"${EXTRA_ARGS[@]}"}
    ;;
  find)
    cmd_find ${EXTRA_ARGS+"${EXTRA_ARGS[@]}"}
    ;;
  outcome|current|progress|cost|warn|tier-dist|quality|eta|failures)
    # Implicit "last <subcmd>"
    cmd_last "${SUBCMD}" ${EXTRA_ARGS+"${EXTRA_ARGS[@]}"}
    ;;
  *)
    echo "query_run.sh: unknown subcommand: ${SUBCMD}" >&2
    usage
    exit 3
    ;;
esac
