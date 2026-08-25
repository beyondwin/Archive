#!/usr/bin/env bash
# Plan Reviewer model-agreement eval (v2.22 §4).
#
# v2.22 migrated the Plan Reviewer from Sonnet to Haiku 4.5
# (claude-haiku-4-5-20251001). Spec §4 risk: Haiku might miss BLOCKERs that
# Sonnet catches. This eval gates that risk — run 20 plan-review fixtures
# through BOTH models and require >= agreement_gate (18/20) verdict agreement
# (each model vs `expected` AND the two models vs each other).
#
# Usage:
#   ./evals/plan-reviewer-rubric/run.sh            # live: dispatch BOTH models, score
#   ./evals/plan-reviewer-rubric/run.sh --dry-run  # offline SHAPE check (no API/SDK)
#
# The --dry-run path uses ONLY stdlib python3 (json) so CI can validate the
# fixture/script shape with no `anthropic` SDK installed and no network.

set -euo pipefail

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"          # evals/plan-reviewer-rubric
EVALS_ROOT="$(dirname "$EVAL_DIR")"                                  # evals/
SKILL_DIR="$(dirname "$EVALS_ROOT")"                                 # skill root
FIXTURE_FILE="$EVAL_DIR/v2.22-haiku-vs-sonnet.json"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "FATAL: unknown argument: $arg (expected: --dry-run)" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# --dry-run: validate SHAPE only. stdlib json, no SDK, no network.
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 1 ]; then
  python3 - "$FIXTURE_FILE" <<'PY'
import json, sys

path = sys.argv[1]
try:
    with open(path) as fh:
        data = json.load(fh)
except FileNotFoundError:
    sys.exit(f"FATAL: fixture file not found: {path}")
except json.JSONDecodeError as e:
    sys.exit(f"FATAL: fixture file does not parse as JSON: {path}: {e}")

if not isinstance(data, dict):
    sys.exit("FATAL: top-level JSON must be an object")

for key in ("model_a", "model_b", "agreement_gate", "fixtures"):
    if key not in data:
        sys.exit(f"FATAL: missing top-level key: {key!r}")

model_a, model_b = data["model_a"], data["model_b"]
if not (isinstance(model_a, str) and model_a.strip()):
    sys.exit("FATAL: model_a must be a non-empty string")
if not (isinstance(model_b, str) and model_b.strip()):
    sys.exit("FATAL: model_b must be a non-empty string")

gate = data["agreement_gate"]
if not isinstance(gate, int):
    sys.exit("FATAL: agreement_gate must be an integer")

fixtures = data["fixtures"]
if not isinstance(fixtures, list):
    sys.exit("FATAL: fixtures must be a list")
if len(fixtures) != 20:
    sys.exit(f"FATAL: expected exactly 20 fixtures, found {len(fixtures)}")

seen = set()
for i, fx in enumerate(fixtures):
    if not isinstance(fx, dict):
        sys.exit(f"FATAL: fixture[{i}] must be an object")
    for key in ("id", "expected"):
        if key not in fx:
            sys.exit(f"FATAL: fixture[{i}] missing key: {key!r}")
    fid = fx["id"]
    if not (isinstance(fid, str) and fid.strip()):
        sys.exit(f"FATAL: fixture[{i}].id must be a non-empty string")
    if fid in seen:
        sys.exit(f"FATAL: duplicate fixture id: {fid!r}")
    seen.add(fid)
    exp = fx["expected"]
    if not isinstance(exp, dict):
        sys.exit(f"FATAL: fixture[{i}] ({fid}) expected must be an object")
    if "status" not in exp:
        sys.exit(f"FATAL: fixture[{i}] ({fid}) expected.status is missing")
    if exp["status"] not in ("PASS", "ISSUES_FOUND"):
        sys.exit(f"FATAL: fixture[{i}] ({fid}) expected.status must be "
                 f"PASS or ISSUES_FOUND, got {exp['status']!r}")

print(f"DRY-RUN OK: {len(fixtures)} fixtures, gate={gate}/{len(fixtures)}")
PY
  exit 0
fi

# ---------------------------------------------------------------------------
# Live mode: dispatch each fixture's plan/spec to BOTH models, compare verdicts.
# Requires the `anthropic` SDK + ANTHROPIC_API_KEY (the dispatch script imports
# the SDK lazily). Offline CI must use --dry-run instead.
# ---------------------------------------------------------------------------
if [ ! -f "$FIXTURE_FILE" ]; then
  echo "FATAL: fixture file not found: $FIXTURE_FILE" >&2
  exit 1
fi

MODEL_A="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model_a"])' "$FIXTURE_FILE")"
MODEL_B="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model_b"])' "$FIXTURE_FILE")"
GATE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["agreement_gate"])' "$FIXTURE_FILE")"
N="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["fixtures"]))' "$FIXTURE_FILE")"

WORK="$(mktemp -d -t plan-reviewer-eval.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/orch"
printf '{}\n' > "$WORK/orch/state.json"

# Dispatch one (fixture, model) pair and print the normalized verdict
# (status + sorted blocker/warn categories) as a one-line JSON string.
dispatch_one() {
  local fixture_index="$1" model="$2"
  local ctx="$WORK/ctx_${fixture_index}.json"
  local out="$WORK/out_${fixture_index}_${model//[^A-Za-z0-9]/_}.json"
  # Build the task-context (placeholder values) for this fixture.
  python3 - "$FIXTURE_FILE" "$fixture_index" "$ctx" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
fx = data["fixtures"][int(sys.argv[2])]
ctx = {
    "plan_path": f"{fx['id']}/plan.md",
    "plan_full_text": fx.get("plan", ""),
    "spec_path": f"{fx['id']}/spec.md",
    "spec_full_text": fx.get("spec", ""),
    "risk_levels_yaml": fx.get("risk_levels_yaml", "{}"),
    "spec_manifest_json": fx.get("spec_manifest_json", "{}"),
    "result_json_path": "result.json",
}
json.dump(ctx, open(sys.argv[3], "w"))
PY
  python3 "$SKILL_DIR/scripts/dispatch_via_api.py" \
    --role plan_reviewer \
    --task-context "$ctx" \
    --output "$out" \
    --model "$model" \
    --orch-dir "$WORK/orch" >/dev/null
  # Normalize the reviewer's JSON verdict into a comparable tuple.
  python3 - "$out" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
status = r.get("status", "")
blockers = sorted({i.get("category") for i in r.get("issues", [])
                   if i.get("severity") == "BLOCKER"})
warns = sorted({i.get("category") for i in r.get("issues", [])
                if i.get("severity") == "WARN"})
print(json.dumps({"status": status, "blocker_categories": blockers,
                  "warn_categories": warns}, sort_keys=True))
PY
}

# Expected verdict for a fixture, normalized the same way.
expected_one() {
  local fixture_index="$1"
  python3 - "$FIXTURE_FILE" "$fixture_index" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
exp = data["fixtures"][int(sys.argv[2])]["expected"]
print(json.dumps({
    "status": exp.get("status", ""),
    "blocker_categories": sorted(exp.get("blocker_categories", [])),
    "warn_categories": sorted(exp.get("warn_categories", [])),
}, sort_keys=True))
PY
}

agreements=0
for i in $(seq 0 $((N - 1))); do
  exp="$(expected_one "$i")"
  va="$(dispatch_one "$i" "$MODEL_A")"
  vb="$(dispatch_one "$i" "$MODEL_B")"
  if [ "$va" = "$vb" ] && [ "$va" = "$exp" ]; then
    agreements=$((agreements + 1))
    echo "  fixture[$i]: AGREE"
  else
    echo "  fixture[$i]: DISAGREE  expected=$exp  ${MODEL_A}=$va  ${MODEL_B}=$vb"
  fi
done

echo "SUMMARY: ${agreements}/${N} agreements (gate=${GATE}); model_a=${MODEL_A} model_b=${MODEL_B}"
if [ "$agreements" -lt "$GATE" ]; then
  echo "FAIL: agreement ${agreements} < gate ${GATE}" >&2
  exit 1
fi
echo "PASS: agreement gate met"
