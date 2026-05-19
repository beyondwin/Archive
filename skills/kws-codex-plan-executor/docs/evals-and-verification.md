# Evals And Verification

Run deterministic checks before shipping skill changes:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_run_diffs.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

The dynamic harness copies the skill under test into a fixture repository before
running `codex exec`, so target agents cannot mutate the source skill package.
