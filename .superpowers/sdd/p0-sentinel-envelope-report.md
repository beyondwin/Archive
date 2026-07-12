# P0 Sentinel + Launch Envelope Repair

## Outcome

The v4 quality matrix is now risk-first and byte-sealed. Its immutable manifest
names `sol_v4_candidate/security/migration block` as the qualified sentinel,
independent of slot order. Each of 17 credentialed slots binds one
domain-separated `LaunchEnvelopeV4` and one separate runner-owned
`OracleBindingV4`; seven Terra policy slots remain no-call. The runner reopens
the content-addressed artifacts immediately before launch and streams the exact
sealed prompt/schema bytes. Prompt, schema, source, fixture, task, case, route,
model, reasoning, sandbox, envelope, or oracle drift fails closed before the
provider. Result, prompt binding, slot index/evidence, completion event, and
aggregate share `envelope_sha256`; release validation rejects substitution.

## RED / GREEN

- RED: `python3 evals/check_quality_matrix_v4.py` failed at
  `KeyError: qualified_sentinel` before implementation.
- GREEN: focused quality, ledger, oracle, live-runner, v4 E2E, and release
  validator checks passed with production fakes. Actual stdin and
  `--output-schema` bytes matched their sealed artifacts; a semantic sentinel
  failure stopped at one fake provider invocation and resume added none.

## Commit

One integrated commit contains this report and the structural repair; base was
`499804b0b362a2e506049f86190bc309e7cf70b3`.

## Findings / Residual / Judgment

Root cause was split authority: the compiler stored digests while the runner
reassembled launch bytes, and sentinel selection used the first pending slot.
No paid/live/provider/network/model call was made. The predecessor digest-only
privacy import, top-level blocked contract, Sol/Terra high-only routing, and
initial-plus-one-corrected cap remain intact. Residual risk is limited to the
still-unauthorized real subscription sentinel/dogfood; judgment: structurally
ready for the single fresh independent review, not authorized for Task 11,
live dogfood, main, or remote operations.
