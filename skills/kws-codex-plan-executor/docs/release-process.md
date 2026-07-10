# Release Process

`SKILL.md` `metadata.version` is the package version source of truth.
`metadata.release_status`, `HISTORY.md`, the matching current baseline, and the
verification log describe readiness and must not imply stronger evidence than
was actually produced.

## Versioning

- `major`: incompatible state, invocation, runtime, or output contract.
- `minor`: compatible public behavior or optional evidence surface.
- `patch`: compatible bug fix.
- `no bump`: docs or verification-log maintenance that changes no behavior or
  public metadata.

## CPE v3 Closeout States

`deterministic-ready` means the current deterministic checks, syntax checks,
patch hygiene, current v3 baseline, and documentation contract pass. It does
not mean a credentialed model comparison ran.

`paid-live-pending` means the approved live migration matrix has not produced a
successful current report. The `3.0.0` version may remain visible as a release
candidate, but paid release closeout must not be claimed.

Paid closeout requires all of the following:

1. show four treatments, eight cases, and the `$50.00` hard cap;
2. obtain explicit cost approval in the execution session;
3. run `live_model_migration.py --confirm-live-cost --budget-usd 50`;
4. preserve the report as external release evidence;
5. confirm `release_gate.passed=true` without weakening thresholds;
6. change release status only in a reviewed follow-up with a fresh verification
   log entry.

A dry run proves matrix shape and budget enforcement only.

## Deterministic Checklist

```bash
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
git diff --check
```

Baseline updates are explicit and reviewed. Never update a baseline to hide an
unexplained failure. Append the date/timezone, branch/commit, scope, commands,
results, skipped gates, and residual risk to `docs/verification-log.md`.
