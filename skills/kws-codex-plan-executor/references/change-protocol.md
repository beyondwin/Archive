# Change Protocol

Before editing CPE:

1. Add or update a deterministic eval and confirm the intended failure.
2. Keep runtime, prompt/export templates, `SKILL.md`, focused references, and
   operator docs aligned in the same change.
3. Preserve the immutable manifest/event/evidence boundary and make all
   consumers use the shared v3 validator.
4. Do not change paid-live release status without a current approved live
   report and verification-log entry.
5. Run the narrow checks, then the package gates:

```bash
./evals/run.sh
python3 evals/check_docs_contract.py
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
git diff --check
```

For structural changes, refresh Graphify and verify freshness. Before staging,
inspect `git status --short --branch --untracked-files=all` and preserve
unrelated user changes.
