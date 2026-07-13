#!/usr/bin/env bash
# Cost-free deterministic eval harness for kws-codex-plan-executor.

set -euo pipefail
umask 077

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKILL_DIR="$(dirname "$EVAL_DIR")"
export CPE_SUPERPOWERS_ROOT="$EVAL_DIR/fixtures/superpowers-capabilities"

# Acceptance workers may inherit a minimal PATH whose python3 cannot import the
# pinned eval dependencies even when a compatible host interpreter exists.
# Select the first interpreter that passes the same dependency preflight used
# by the harness, while preserving the preflight's fail-closed diagnostics when
# no candidate is suitable.
PYTHON_BIN=""
for candidate in \
  "${CPE_EVAL_PYTHON:-}" \
  "$SKILL_DIR/.venv/bin/python3" \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  "$(command -v python3 2>/dev/null || true)" \
  /usr/bin/python3
do
  if [ -n "$candidate" ] && [ -x "$candidate" ] && \
    "$candidate" "$SKILL_DIR/scripts/preflight_dependencies.py" >/dev/null 2>&1
  then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="${CPE_EVAL_PYTHON:-$(command -v python3 2>/dev/null || true)}"
fi
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "no executable Python interpreter found for deterministic evals" >&2
  exit 2
fi

update_baseline=0
if [ "${1:-}" = "--update-baseline" ]; then
  update_baseline=1
  shift
fi
if [ "$#" -ne 0 ]; then
  echo "usage: ./evals/run.sh [--update-baseline]" >&2
  exit 2
fi

REPORT_ROOT="${CODEX_EVAL_HOME:-${TMPDIR:-/tmp}}"
if [ -n "${CODEX_EVAL_HOME:-}" ]; then
  REPORT_ROOT="$REPORT_ROOT/.codex/eval-reports"
fi
mkdir -p "$REPORT_ROOT"
REPORT_DIR="$(mktemp -d "$REPORT_ROOT/kws-codex-plan-executor-eval.XXXXXX")"
chmod 700 "$REPORT_DIR"
EVAL_REPORT="$REPORT_DIR/eval-report.jsonl"
: > "$EVAL_REPORT"
echo "eval report: $EVAL_REPORT"

run_check() {
  local name="$1"
  shift
  "$PYTHON_BIN" "$EVAL_DIR/run_check.py" --report "$EVAL_REPORT" --name "$name" -- "$@"
}

# Dependency and static-contract checks are deliberately outside the maintained
# behavioral inventory. They still run, but the AST anti-stub rule applies to
# the production behavior checks inventoried below.
run_check "preflight_dependencies" "$PYTHON_BIN" "$SKILL_DIR/scripts/preflight_dependencies.py"
run_check "skill_contract" "$PYTHON_BIN" "$EVAL_DIR/check_skill_contract.py" --skill "$SKILL_DIR/SKILL.md"
run_check "docs_contract" "$PYTHON_BIN" "$EVAL_DIR/check_docs_contract.py"
run_check "invocation_args" "$PYTHON_BIN" "$EVAL_DIR/check_invocation_args.py"
run_check "superpowers_compatibility" "$PYTHON_BIN" "$EVAL_DIR/check_superpowers_compatibility.py"

mapfile_supported=1
if ! command -v mapfile >/dev/null 2>&1; then
  mapfile_supported=0
fi
INVENTORY_FILE="${CPE_MAINTAINED_CHECKS:-$EVAL_DIR/maintained-checks.json}"
inventory_lines="$("$PYTHON_BIN" - "$INVENTORY_FILE" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
entries = payload.get("checks")
if not isinstance(entries, list) or not entries:
    raise SystemExit("maintained checks inventory is empty")
paths = []
for entry in entries:
    if not isinstance(entry, dict):
        raise SystemExit("maintained check entry is not an object")
    check = entry.get("path")
    if not isinstance(check, str) or not check.endswith(".py"):
        raise SystemExit("maintained check path is invalid")
    if not entry.get("production_entrypoint") or not entry.get("mutation_assertion"):
        raise SystemExit(f"maintained check metadata is incomplete: {check}")
    paths.append(check)
if len(paths) != len(set(paths)):
    raise SystemExit("maintained check paths are duplicated")
for check in paths:
    if not (path.parent / check).is_file():
        raise SystemExit(f"maintained check is missing: {check}")
print("\n".join(paths))
PY
)"
if [ "$mapfile_supported" -eq 1 ]; then
  mapfile -t maintained_checks <<<"$inventory_lines"
else
  maintained_checks=()
  while IFS= read -r check; do maintained_checks+=("$check"); done <<<"$inventory_lines"
fi
for check in "${maintained_checks[@]}"; do
  run_check "maintained:${check%.py}" "$PYTHON_BIN" "$EVAL_DIR/$check"
done

run_check "eval_harness" "$PYTHON_BIN" "$EVAL_DIR/check_eval_harness.py" --inventory "$INVENTORY_FILE"
run_check "v4_release_evidence_validator" "$PYTHON_BIN" "$EVAL_DIR/check_cpe_v4_release_evidence.py"
run_check "subscription_live_matrix_dry_run" "$PYTHON_BIN" "$EVAL_DIR/live_model_runner.py" \
  dry-run --matrix v4 --billing-mode chatgpt_subscription --output "$REPORT_DIR/subscription-live-matrix-plan.json"
while IFS= read -r parser_fixture; do
  run_check "parse_plan:$(basename "$parser_fixture")" "$PYTHON_BIN" "$EVAL_DIR/check_parse_plan.py" --fixture "$parser_fixture"
done < <(find "$EVAL_DIR/parser-fixtures" -name '*.yaml' -type f | sort)

SKILL_VERSION="$("$PYTHON_BIN" - "$SKILL_DIR/SKILL.md" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r'(?m)^[ \t]*version:[ \t]*"([^"]+)"', text)
print(match.group(1) if match else "0.0.0")
PY
)"
BASELINE_FILE="$EVAL_DIR/baselines/v${SKILL_VERSION}.json"
CURRENT_BASELINE="$REPORT_DIR/current-baseline.json"
INVENTORY_SCHEMA="$($PYTHON_BIN - "$INVENTORY_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("schema_version", ""))
PY
)"
"$PYTHON_BIN" - "$EVAL_REPORT" "$SKILL_VERSION" "$CURRENT_BASELINE" <<'PY'
import json, pathlib, sys
report, version, output = map(pathlib.Path, (sys.argv[1], sys.argv[2], sys.argv[3]))
records = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines() if line.strip()]
payload = {
    "schema_version": "maintained-evals.v1",
    "version": str(version),
    "checks": [{"name": item.get("name"), "exit_code": item.get("returncode")} for item in records],
    "paid_execution": "skipped_not_approved",
}
output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
if [ "$update_baseline" -eq 1 ]; then
  mkdir -p "$(dirname "$BASELINE_FILE")"
  cp "$CURRENT_BASELINE" "$BASELINE_FILE"
elif [ "$INVENTORY_SCHEMA" != "4" ] && [ -f "$BASELINE_FILE" ] && grep -q '"schema_version": "maintained-evals.v1"' "$BASELINE_FILE"; then
  "$PYTHON_BIN" - "$BASELINE_FILE" "$CURRENT_BASELINE" <<'PY'
import json, sys
expected = json.load(open(sys.argv[1], encoding="utf-8"))
actual = json.load(open(sys.argv[2], encoding="utf-8"))
for field in ("schema_version", "version", "paid_execution"):
    if expected.get(field) != actual.get(field):
        raise SystemExit(f"maintained eval baseline differs at {field}; review and run --update-baseline")

expected_checks = {item["name"]: item["exit_code"] for item in expected.get("checks", [])}
actual_checks = {item["name"]: item["exit_code"] for item in actual.get("checks", [])}
legacy_migration = expected_checks.pop("live_model_migration", None)
if legacy_migration is not None:
    expected_checks["maintained:check_live_model_migration"] = legacy_migration
if any(actual_checks.get(name) != exit_code for name, exit_code in expected_checks.items()):
    raise SystemExit("maintained eval baseline differs; an established check is missing or changed")
if any(exit_code != 0 for exit_code in actual_checks.values()):
    raise SystemExit("maintained eval baseline contains a failing current check")

ALLOWED_T8_ADDITIONS = {
    "maintained:check_live_matrix_compiler",
    "maintained:check_live_matrix_fixtures",
    "maintained:check_live_matrix_ledger",
    "maintained:check_live_matrix_oracle",
    "maintained:check_live_model_runner",
    "subscription_live_matrix_dry_run",
}
additions = set(actual_checks) - set(expected_checks)
if additions not in (set(), ALLOWED_T8_ADDITIONS):
    raise SystemExit(
        "unexpected maintained eval baseline expansion: " + ", ".join(sorted(additions))
    )
PY
else
  echo "legacy fixture baseline ignored; Task 13 will generate a maintained-evals baseline" >&2
fi
cat "$CURRENT_BASELINE"
