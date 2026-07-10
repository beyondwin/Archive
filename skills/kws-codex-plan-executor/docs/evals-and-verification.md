# Evals And Verification

Install the pinned eval dependency in an isolated environment, then run:

```bash
python3 -m pip install -r requirements-eval.txt
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_docs_contract.py
git diff --check
```

The active deterministic suite exercises dependency reporting, fixed routing,
override rejection, manifest/evidence integrity, event replay, execution,
validation parity, reconciliation, safe repair, inspection, recent-run metrics,
fault injection, migration planning, Superpowers capability checks, and release
metadata. The legacy static YAML execution-fixture loop is disabled in the v3
harness; a green deterministic run must not be described as paid live-model
evidence.

Release status is `deterministic-ready; paid-live-pending`. The live matrix has
four treatments and eight cases. It is opt-in, capped at `$50.00`, and requires
the operator's explicit approval in the session that incurs cost:

```bash
python3 evals/live_model_migration.py \
  --confirm-live-cost --budget-usd 50 \
  --output /tmp/cpe-v3-live-report.json
```

Until that report exists and `release_gate.passed=true`, paid release closeout
has not passed. A dry run proves matrix shape and budget enforcement only.
