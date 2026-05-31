#!/usr/bin/env bash
# Phase Transition merge-vs-split parity eval (v2.22 §6).
#
# v2.22 §2.A2 merged the back-to-back batch Verifier (T1) and Phase Docs
# Updater (T2) into ONE combined two-tool dispatch (role `transition_combined`):
# a single sub-agent turn that issues BOTH `verify_low_batch` and
# `update_phase_docs`, parsed by scripts/dispatch_transition_combined.py into a
# `{verify, docs}` shape. Spec §6 requires the combined dispatch to produce
# output IDENTICAL to the legacy split path (two separate dispatches) on the
# fixture compactions in v2.22-merge-vs-split.json. This eval encodes that
# parity check: each parity fixture asserts combined == split, and an optional
# `parity:false` fixture exercises the mismatch-detection path.
#
# Usage:
#   ./evals/transition-merge/run.sh            # live: run combined + split, compare
#   ./evals/transition-merge/run.sh --dry-run  # offline SHAPE + static parity check
#
# The --dry-run path uses ONLY stdlib python3 (json) so CI can validate the
# fixture/script shape with no `anthropic` SDK installed and no network.

set -euo pipefail

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"          # evals/transition-merge
EVALS_ROOT="$(dirname "$EVAL_DIR")"                                  # evals/
SKILL_DIR="$(dirname "$EVALS_ROOT")"                                 # skill root
FIXTURE_FILE="$EVAL_DIR/v2.22-merge-vs-split.json"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "FATAL: unknown argument: $arg (expected: --dry-run)" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# --dry-run: validate SHAPE + static parity only. stdlib json, no SDK, no network.
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

for key in ("version", "verify_tool", "docs_tool", "fixtures"):
    if key not in data:
        sys.exit(f"FATAL: missing top-level key: {key!r}")

if data["verify_tool"] != "verify_low_batch":
    sys.exit(f"FATAL: verify_tool must be 'verify_low_batch', got {data['verify_tool']!r}")
if data["docs_tool"] != "update_phase_docs":
    sys.exit(f"FATAL: docs_tool must be 'update_phase_docs', got {data['docs_tool']!r}")

fixtures = data["fixtures"]
if not isinstance(fixtures, list):
    sys.exit("FATAL: fixtures must be a list")
if len(fixtures) != 5:
    sys.exit(f"FATAL: expected exactly 5 fixtures, found {len(fixtures)}")

seen = set()
parity_verified = 0
divergence_checked = 0
for i, fx in enumerate(fixtures):
    if not isinstance(fx, dict):
        sys.exit(f"FATAL: fixture[{i}] must be an object")
    for key in ("id", "task_context", "split_expected", "combined_expected"):
        if key not in fx:
            sys.exit(f"FATAL: fixture[{i}] missing key: {key!r}")
    fid = fx["id"]
    if not (isinstance(fid, str) and fid.strip()):
        sys.exit(f"FATAL: fixture[{i}].id must be a non-empty string")
    if fid in seen:
        sys.exit(f"FATAL: duplicate fixture id: {fid!r}")
    seen.add(fid)

    for which in ("split_expected", "combined_expected"):
        block = fx[which]
        if not isinstance(block, dict):
            sys.exit(f"FATAL: fixture[{i}] ({fid}) {which} must be an object")
        for sub in ("verify", "docs"):
            if sub not in block:
                sys.exit(
                    f"FATAL: fixture[{i}] ({fid}) {which} missing key: {sub!r}"
                )

    is_parity = fx.get("parity", True)
    if is_parity is True:
        if fx["combined_expected"] != fx["split_expected"]:
            sys.exit(
                f"FATAL: fixture[{i}] ({fid}) is a parity fixture but "
                "combined_expected != split_expected"
            )
        parity_verified += 1
    elif is_parity is False:
        if fx["combined_expected"] == fx["split_expected"]:
            sys.exit(
                f"FATAL: fixture[{i}] ({fid}) is flagged parity:false but "
                "combined_expected == split_expected (no divergence to detect)"
            )
        divergence_checked += 1
    else:
        sys.exit(
            f"FATAL: fixture[{i}] ({fid}) parity must be a boolean, "
            f"got {is_parity!r}"
        )

if parity_verified < 4:
    sys.exit(
        f"FATAL: expected at least 4 parity fixtures, found {parity_verified}"
    )

print(f"DRY-RUN OK: {len(fixtures)} fixtures, parity verified")
PY
  exit 0
fi

# ---------------------------------------------------------------------------
# Live mode: for each fixture run BOTH the combined dispatch and the split
# dispatch, then assert the combined {verify, docs} deep-equals the split
# {verify, docs} for parity fixtures (and differs for any parity:false fixture).
# Requires the `anthropic` SDK + ANTHROPIC_API_KEY (dispatch scripts import the
# SDK lazily). Offline CI must use --dry-run instead.
# ---------------------------------------------------------------------------
if [ ! -f "$FIXTURE_FILE" ]; then
  echo "FATAL: fixture file not found: $FIXTURE_FILE" >&2
  exit 1
fi

N="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["fixtures"]))' "$FIXTURE_FILE")"
MODEL="${TRANSITION_MODEL:-claude-sonnet-4-5-20250929}"

WORK="$(mktemp -d -t transition-merge-eval.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/orch"
printf '{}\n' > "$WORK/orch/state.json"

# Run the combined dispatch for one fixture; print its normalized {verify, docs}
# JSON on one line. Shells out to dispatch_transition_combined.py (which delegates
# to dispatch_via_api.py with role=transition_combined).
combined_one() {
  local idx="$1"
  local ctx="$WORK/ctx_${idx}.json"
  python3 - "$FIXTURE_FILE" "$idx" "$ctx" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
fx = data["fixtures"][int(sys.argv[2])]
json.dump(fx["task_context"], open(sys.argv[3], "w"))
PY
  python3 - "$SKILL_DIR" "$ctx" "$WORK/orch" "$MODEL" "$idx" <<'PY'
import json, sys, os
sk_root, ctx_path, orch_dir, model, idx = sys.argv[1:6]
sys.path.insert(0, os.path.join(sk_root, "scripts"))
import dispatch_transition_combined as dtc  # lazy SDK
task_context = json.load(open(ctx_path))
result = dtc.dispatch_combined_via_api(
    task_context=task_context, model=model, orch_dir=orch_dir,
    sk_root=sk_root, plan_idx="0", compaction_idx=idx,
)
print(json.dumps({"verify": result.get("verify"), "docs": result.get("docs")},
                 sort_keys=True))
PY
}

# Run the legacy SPLIT path for one fixture: two separate dispatches
# (verify_low_batch, then update_phase_docs) via dispatch_via_api.py, assembled
# into the same {verify, docs} shape. Print normalized JSON on one line.
split_one() {
  local idx="$1"
  local ctx="$WORK/ctx_${idx}.json"
  local vout="$WORK/verify_${idx}.json"
  local dout="$WORK/docs_${idx}.json"
  python3 "$SKILL_DIR/scripts/dispatch_via_api.py" \
    --role verifier --task-context "$ctx" --output "$vout" \
    --model "$MODEL" --orch-dir "$WORK/orch" >/dev/null
  python3 "$SKILL_DIR/scripts/dispatch_via_api.py" \
    --role docs_updater --task-context "$ctx" --output "$dout" \
    --model "$MODEL" --orch-dir "$WORK/orch" >/dev/null
  python3 - "$vout" "$dout" <<'PY'
import json, sys
verify = json.load(open(sys.argv[1]))
docs = json.load(open(sys.argv[2]))
print(json.dumps({"verify": verify, "docs": docs}, sort_keys=True))
PY
}

# Expected parity flag for a fixture (true unless explicitly parity:false).
parity_flag() {
  local idx="$1"
  python3 - "$FIXTURE_FILE" "$idx" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
fx = data["fixtures"][int(sys.argv[2])]
print("true" if fx.get("parity", True) else "false")
PY
}

fixture_id() {
  local idx="$1"
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fixtures"][int(sys.argv[2])]["id"])' \
    "$FIXTURE_FILE" "$idx"
}

violations=0
for i in $(seq 0 $((N - 1))); do
  fid="$(fixture_id "$i")"
  parity="$(parity_flag "$i")"
  combined="$(combined_one "$i")"
  split="$(split_one "$i")"
  if [ "$parity" = "true" ]; then
    if [ "$combined" = "$split" ]; then
      echo "  fixture[$i] ($fid): PARITY OK (combined == split)"
    else
      echo "  fixture[$i] ($fid): PARITY VIOLATION  combined=$combined  split=$split" >&2
      violations=$((violations + 1))
    fi
  else
    if [ "$combined" != "$split" ]; then
      echo "  fixture[$i] ($fid): DIVERGENCE OK (combined != split, as expected)"
    else
      echo "  fixture[$i] ($fid): EXPECTED DIVERGENCE MISSING (combined == split)" >&2
      violations=$((violations + 1))
    fi
  fi
done

echo "SUMMARY: ${N} fixtures checked; ${violations} parity violation(s)"
if [ "$violations" -gt 0 ]; then
  echo "FAIL: ${violations} parity violation(s)" >&2
  exit 1
fi
echo "PASS: combined dispatch matches split path on all parity fixtures"
