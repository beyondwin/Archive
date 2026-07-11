# Post-Merge Verification

After merging CPE v3, run the deterministic package checks from the merged
commit and confirm Graphify was refreshed:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
python3 evals/check_docs_contract.py
python3 evals/check_release_contract.py
python3 scripts/cpe.py --help >/tmp/cpe-v3-help.txt
bash -n evals/run.sh

cd ../../..
git diff --check
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran
```

For a cost-free runtime smoke, use a temporary repository and fake provider or
the deterministic execution-runtime check through the public CLI. Confirm that
the maintained eval inventory ran, its expectation oracle stayed isolated from
production scheduler/projector/validator/repair code, product changes occur
only in the isolated worktree, `events.jsonl` replays to the stored projection,
and inspection is byte-preserving. Public success must be one schema-valid
`PublicResult` with exit 0 after canonical completion validation; blocked and
failed paths must exit 1 and 2.

Do not run the credentialed live migration matrix as an implicit post-merge
step. It requires a separate explicit cost approval, the `$50.00` hard cap, and
a preserved report. Until that report passes, keep release status
`paid-live-pending`.
