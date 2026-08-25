# Plan Reviewer — Haiku vs Sonnet agreement eval (v2.22 §4)

v2.22 migrated the Plan Reviewer (Phase 0 Step 6.5) from Sonnet to Haiku 4.5
(`claude-haiku-4-5-20251001`). The Plan Reviewer runs a **mechanical** rubric
(see `../../references/plan-reviewer-prompt.md`), so Haiku should match Sonnet on
binary verdicts. Spec §4 flags the risk that Haiku misses a BLOCKER that Sonnet
would catch.

## What this gates

Run all 20 fixtures through **both** `model_a` (Haiku) and `model_b` (Sonnet).
A fixture **agrees** only when both models produce the same normalized verdict
*and* that verdict matches the fixture's `expected`. The gate requires
`agreements >= agreement_gate` (**18/20**); below that, the live run exits
non-zero and the Haiku migration should be reconsidered.

The verdict is normalized to `{status, blocker_categories[], warn_categories[]}`
where category lists are the sorted, de-duplicated `issues[].category` values
split by `severity` (BLOCKER vs WARN). This ignores wording/ordering differences
and compares only the mechanically meaningful decision.

## Running

```bash
# Live: dispatch BOTH models, score agreement (needs the `anthropic` SDK +
# ANTHROPIC_API_KEY; dispatches via ../../scripts/dispatch_via_api.py).
./run.sh

# Offline SHAPE check — no API, no SDK, no network. stdlib python3 (json) only.
# This is the CI gate and the TDD "test" for the harness itself.
./run.sh --dry-run
# -> DRY-RUN OK: 20 fixtures, gate=18/20
```

## Fixture schema

Top-level (`v2.22-haiku-vs-sonnet.json`):

```json
{
  "version": "2.22",
  "model_a": "claude-haiku-4-5-20251001",
  "model_b": "claude-sonnet-4-6",
  "agreement_gate": 18,
  "fixtures": [ /* exactly 20 */ ]
}
```

Each fixture:

| field         | meaning                                                              |
| ------------- | ------------------------------------------------------------------- |
| `id`          | unique slug, e.g. `pr-01`                                            |
| `description` | one line — the plan defect under test, or `clean`                   |
| `plan`        | minimal plan markdown excerpt the reviewer judges                   |
| `spec`        | minimal spec markdown excerpt                                       |
| `risk_levels_yaml`   | optional — `task_N: LOW/MID/HIGH` lines                       |
| `spec_manifest_json` | optional — rendered `spec_manifest` for manifest-rubric cases |
| `expected`    | `{status, blocker_categories[], warn_categories[]}` ground truth     |

`expected.status` is `PASS` or `ISSUES_FOUND`. Categories use the rubric's real
names: BLOCKER — `missing_ac`, `contract_mismatch`, `naming_drift`,
`dep_inconsistency`, `missing_files`, `out_of_repo`, `spec_manifest_invalid_ref`;
WARN — `resource_key_collision`, `spec_manifest_fallback_used`,
`spec_manifest_unused_section`. Fixtures are deliberately unambiguous so a
Haiku/Sonnet agreement test measures model parity, not fixture ambiguity.
