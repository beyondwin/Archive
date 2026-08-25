#!/usr/bin/env bash
# v2.19 ablation runner — orchestrates baseline vs experiment runs across fixtures
# and aggregates token/cost deltas.
#
# This script does NOT modify SKILL.md or prompts — it expects the user to have
# checked out the appropriate git ref (baseline branch vs experiment branch) before
# each `--mode` invocation.
#
# Usage:
#   # 1) On baseline branch (v2.18.0):
#   ./run_ablation.sh --mode baseline --fixtures "01,02,03,07"
#
#   # 2) Switch to experiment branch (e.g. v2.19-T1.2):
#   git switch v2.19-T1.2
#   ./run_ablation.sh --mode experiment --label T1.2 --fixtures "01,02,03,07"
#
#   # 3) Compare:
#   ./run_ablation.sh --mode compare --baseline-dir runs/baseline --experiment-dir runs/T1.2
#
# WARNING: --mode baseline and --mode experiment EXECUTE evals/run.sh which dispatches
# Sonnet/Opus subagents and consumes real Anthropic API tokens. Estimated cost:
# $5–$20 per fixture depending on plan size. Run on a small fixture set first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_ROOT="$(cd "$EXP_DIR/../../.." && pwd)"
EVALS_ROOT="$SKILL_ROOT/evals"

MODE=""
LABEL="baseline"
FIXTURES=""
BASELINE_DIR=""
EXPERIMENT_DIR=""
OUTPUT_ROOT="$EXP_DIR/findings/ablation-runs"

usage() {
  sed -n '2,25p' "$0"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --fixtures) FIXTURES="$2"; shift 2 ;;
    --baseline-dir) BASELINE_DIR="$2"; shift 2 ;;
    --experiment-dir) EXPERIMENT_DIR="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

[[ -z "$MODE" ]] && { echo "ERROR: --mode required" >&2; usage; }

run_one_fixture() {
  local fixture_id="$1"
  local out_dir="$2"

  local fixture_file
  fixture_file=$(ls "$EVALS_ROOT/fixtures/${fixture_id}"-*.yaml 2>/dev/null | head -1 || true)
  if [[ -z "$fixture_file" ]]; then
    echo "WARN: fixture ${fixture_id}-*.yaml not found, skipping" >&2
    return
  fi

  echo "==> [${LABEL}] Running fixture ${fixture_id}: $(basename "$fixture_file")"
  mkdir -p "$out_dir/${fixture_id}"

  # NOTE: This is where evals/run.sh would be invoked. Actual invocation is
  # commented out because it triggers real API spend. Uncomment + verify the
  # arg shape against evals/run.sh before running.
  #
  # bash "$EVALS_ROOT/run.sh" \
  #   --fixture "$fixture_file" \
  #   --out "$out_dir/${fixture_id}" \
  #   --label "${LABEL}-${fixture_id}"

  echo "    (eval invocation stubbed — see comment in $0; copy state.json into $out_dir/${fixture_id}/state.json after run)"
}

case "$MODE" in
  baseline|experiment)
    [[ -z "$FIXTURES" ]] && { echo "ERROR: --fixtures required for $MODE mode" >&2; exit 1; }
    mkdir -p "$OUTPUT_ROOT/$LABEL"
    IFS=',' read -ra FIDS <<< "$FIXTURES"
    for fid in "${FIDS[@]}"; do
      run_one_fixture "$fid" "$OUTPUT_ROOT/$LABEL"
    done
    echo ""
    echo "Done. Copy each run's state.json into $OUTPUT_ROOT/$LABEL/<fixture_id>/state.json"
    echo "Then run: $0 --mode compare --baseline-dir $OUTPUT_ROOT/baseline --experiment-dir $OUTPUT_ROOT/$LABEL"
    ;;
  compare)
    [[ -z "$BASELINE_DIR" || -z "$EXPERIMENT_DIR" ]] && {
      echo "ERROR: --baseline-dir and --experiment-dir required for compare mode" >&2
      exit 1
    }
    [[ ! -d "$BASELINE_DIR" || ! -d "$EXPERIMENT_DIR" ]] && {
      echo "ERROR: directories must exist" >&2
      exit 1
    }
    echo "# v2.19 Ablation Report"
    echo ""
    echo "Baseline: $BASELINE_DIR"
    echo "Experiment: $EXPERIMENT_DIR"
    echo ""
    for base_state in "$BASELINE_DIR"/*/state.json; do
      fixture_id=$(basename "$(dirname "$base_state")")
      exp_state="$EXPERIMENT_DIR/${fixture_id}/state.json"
      if [[ ! -f "$exp_state" ]]; then
        echo "WARN: experiment state for ${fixture_id} missing, skipping" >&2
        continue
      fi
      python3 "$SCRIPT_DIR/cost_report.py" \
        --baseline "$base_state" \
        --experiment "$exp_state" \
        --out "$EXPERIMENT_DIR/${fixture_id}/ablation.json"
    done
    ;;
  single)
    [[ -z "$BASELINE_DIR" ]] && { echo "ERROR: --baseline-dir required" >&2; exit 1; }
    for state in "$BASELINE_DIR"/*/state.json; do
      fixture_id=$(basename "$(dirname "$state")")
      python3 "$SCRIPT_DIR/cost_report.py" --state "$state" --label "$LABEL-$fixture_id"
    done
    ;;
  *)
    echo "ERROR: Unknown mode '$MODE'. Use baseline|experiment|compare|single." >&2
    exit 1
    ;;
esac
