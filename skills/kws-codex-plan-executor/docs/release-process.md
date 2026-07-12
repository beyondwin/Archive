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

`integrity-closure-pending` means the current release candidate has audited
fail-closed gaps that are not yet covered by current deterministic evidence.
It preserves the v3 architecture while preventing a stronger readiness claim.

`deterministic-ready` means the current deterministic checks, syntax checks,
patch hygiene, current v3 baseline, and documentation contract pass after the
integrity closure. It does not mean a credentialed model comparison ran.

`paid-live-pending` means the approved live migration matrix has not produced a
successful current report. Version `3.0.1` is deterministic-ready and now
contains the guarded subscription runner, but paid release closeout must not be
claimed merely because that runner exists.

`paid-live-verified` means the exact reviewed subscription ledger is complete,
the unchanged checked-in release gate passes, independent implementation and
report review passes, and the tracked privacy audit passes. Version `3.1.0`
publishes this state with `release_ready=true`; it does not claim observable
account-side USD attribution.

Throughout integrity-closure Tasks 1-12, the exact active tuple is version
`3.0.0`, status `integrity-closure-pending; paid-live-pending`, and
`release_ready=false`. Only the final closure task may change deterministic
status and version after recording current L0-L4, fresh Graphify, and clean
tracked-tree evidence. It must not infer paid readiness from those checks.

The completed deterministic closure publishes version `3.0.1`, status
`deterministic-ready; paid-live-pending`, and `release_ready=false`. This tuple
is backed by the current baseline and the structured L0-L4 evidence in the
verification log; it makes no credentialed-provider claim.

Paid-live closeout requires all of the following:

1. dry-run the exact four-treatment, eight-case manifest and confirm 32 slots,
   25 credentialed calls, and seven expected policy failures;
2. obtain explicit ChatGPT subscription-usage confirmation in the execution
   session, use ChatGPT login, and reject API-key authentication;
3. run `live_model_runner.py start --confirm-subscription-usage` from the exact
   independently reviewed implementation, using a private evidence root outside
   repository inputs;
4. resolve all slots without any timeout, subscription-limit, malformed-output,
   drift, attestation, or evidence blocker, using explicit resume/retry only;
5. aggregate the immutable ledger with `live_model_migration.py
   --billing-mode chatgpt_subscription --confirm-subscription-usage`;
6. preserve the sanitized report as external release evidence and confirm it
   includes every required manifest, fixture, oracle, prompt, model-catalog,
   implementation, and result digest;
7. confirm `release_gate.passed=true` without weakening thresholds;
8. obtain independent review of both the implementation and sanitized report;
9. change release status only in a reviewed follow-up with a fresh verification
   log entry. That entry must state that ChatGPT subscription authentication was
   used and direct USD cost was not observable.

A dry run proves matrix shape and digest binding only. Account-side subscription
or existing-credit attribution is outside the runner's observability, so the
report must use `cost_usd=null` and `cost_observability=unavailable`.

The legacy metered-dollar compatibility path remains bounded by the `$50.00`
hard cap and explicit cost approval. Injected or metered evidence cannot
substitute for the required ChatGPT subscription ledger in this closeout.

The 3.1.0 closeout satisfied this checklist with 25 credentialed calls, seven
expected policy failures, `release_gate.passed=true`, independent review, and a
clean privacy audit. The release-only closeout made no provider calls and did
not alter thresholds, immutable result records, or checkpoint digests.

## V4 tiered proof

The v4 merge gate is `critical_path_live`: two credentialed Sol candidate
slots, seven deterministic policy outcomes, one verified CPE v4 dogfood run,
and one terminal release generation. Its passing label is exactly
`critical-path-live verified`. The 17-call `full_paid_matrix` is optional; in
its absence report exactly `full paid-live certification deferred`.
Historical failed 17-call evidence is lineage context only.

## Deterministic Checklist

```bash
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
python3 scripts/cpe.py --help
git diff --check
```

Baseline updates are explicit and reviewed. Never update a baseline to hide an
unexplained failure. Append the date/timezone, branch/commit, scope, commands,
results, skipped gates, and residual risk to `docs/verification-log.md`.
