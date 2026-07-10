# Post-Merge Verification

After merging CPE v3, run the deterministic package checks from the merged
commit and confirm Graphify was refreshed:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
python3 evals/check_docs_contract.py
python3 evals/check_release_contract.py
bash -n evals/run.sh

cd ../../..
git diff --check
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran
```

For a cost-free runtime smoke, use a temporary repository and fake provider or
the deterministic execution-runtime check. Confirm that product changes occur
only in the isolated worktree, `events.jsonl` replays to the stored projection,
and inspection is byte-preserving.

Do not run the credentialed live migration matrix as an implicit post-merge
step. It requires a separate explicit cost approval, the `$50.00` hard cap, and
a preserved report. Until that report passes, keep release status
`paid-live-pending`.
