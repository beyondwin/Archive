# Plan runner 2.0.0 Claude live-provider blocker

## Status

- Confirmed on 2026-07-26.
- Scope: the `2.0.0` provider-backed `ownership` and `interruption` release
  canaries for `kws-claude-plan-runner`.
- Disposition: external provider blocker; do not retry the same Claude live
  canary until the admission condition changes.
- Local integration: explicitly waived by the operator on 2026-07-26. The
  operator acknowledged that Claude cannot currently be used and directed the
  implementation branch to be merged to local `main` with the missing live
  evidence preserved in this record.
- Remote state: no push, pull request, tag, package publication, or deployment.

This is an execution-environment record. It is intentionally separate from
the runner changelogs, which describe product behavior rather than the current
availability of an external subscription.

## Authoritative provider state

The operator confirmed that the Claude subscription used by the local Claude
CLI has ended. A CLI login indication or the presence of a macOS Keychain
credential is therefore not evidence that the provider will admit a real
inference request.

The canary must distinguish these facts:

1. a Claude executable exists;
2. some login or credential material exists;
3. an explicitly approved authentication route is present;
4. the provider admits real inference under a valid subscription or API
   account.

Only the fourth fact can satisfy provider-backed live acceptance. The first
three cannot be promoted to live success.

No token, credential value, provider transcript, prompt, or raw error stream
is recorded in this document.

## Observed release-canary result

At candidate `63fa183ec0818ea5b6fba50e60941220d9ce5955`, the exact command was:

```bash
./scripts/agent/plan-runner-live-canary --provider all --mode ownership
```

The command exited nonzero.

| Provider | Normalized result | Release interpretation |
| --- | --- | --- |
| Codex | `provider_unavailable`; no completed ownership handoff | Not a pass. A separate canary sandbox mismatch was identified and fixed after this candidate. |
| Claude | `recovery_exhausted`; no implemented plan, receipt, or final HEAD | Not a pass. The operator-confirmed ended subscription is the authoritative external blocker. |

The `interruption` scenario was not run at that candidate after `ownership`
failed. No failed or synthetic evidence is treated as a substitute.

## Completed non-live evidence

Before this blocker record:

- the canary unit suite passed;
- the Codex deterministic runner eval passed all 189 tests;
- the Claude deterministic runner eval passed all 108 tests;
- focused contract, credential-minimization, release-metadata, compilation,
  and `git diff --check` checks passed;
- independent review findings were fixed and re-reviewed.

These results validate implementation behavior under deterministic test
providers. They do not prove current Claude inference admission.

## Final pre-merge evidence and operator exception

The final implementation branch candidate is
`81514db5d1480cb5ce76a859da94570c1aa8a8a0`. The local `main` head immediately
before integration is `e4624b0b4157afc23841c70b9ff0c0883b4efabb`.

At the final implementation candidate:

- the Codex-only `ownership` live scenario passed with
  `session_action=two_fresh_plan_sessions`;
- the Codex-only `interruption` live scenario passed with
  `session_action=sigint_then_recorded_resume`;
- the canonical verifier exited zero for candidate
  `81514db5d1480cb5ce76a859da94570c1aa8a8a0`;
- the deterministic Codex runner eval passed 189 tests;
- the deterministic Claude runner eval passed 108 tests;
- the shared parity and cutover suites passed.

The exact required `--provider all` ownership and interruption commands did not
both succeed at the final candidate. Claude ownership and interruption live
success therefore remain missing. The deterministic Claude results and Codex
live results are not substitutes for that evidence.

The operator subsequently directed local integration despite this known
external-provider gap. This is a narrow local-merge exception:

- it does not relabel either missing Claude canary as passed;
- it does not declare the provider-backed release gate complete;
- it does not authorize a push, pull request, tag, package publication, or
  deployment;
- it does not remove the retry conditions below.

## Impact

- Required Claude `ownership` live evidence is missing.
- Required Claude `interruption` live evidence is missing.
- The provider-backed release gate remains incomplete even though Codex live
  evidence and the deterministic canonical verifier passed.
- Local integration is allowed only by the explicit operator exception above.
- A future tag, publication, or claim of complete live-provider acceptance
  still requires the missing Claude evidence or a new explicit operator
  decision for that separate action.
- Earlier duration estimates assumed Claude provider availability and are no
  longer valid.

## Retry policy

Do not repeatedly invoke the same real Claude canary while the admission state
is unchanged. A retry is allowed only after the operator has both a provider
account that admits inference and a canary-compatible, explicitly approved
authentication environment. That may be either:

1. a restored Claude subscription plus an explicitly supplied, authorized
   Claude Code OAuth environment credential; or
2. an approved API-authenticated account plus its explicitly supplied
   authentication environment, such as a valid `ANTHROPIC_API_KEY`.

A restored subscription with only host login or Keychain state is not
sufficient for this canary. Supporting that route would require a separately
reviewed authentication bridge; the canary intentionally does not infer
admission from `claude auth status` or Keychain presence.

After the external condition changes:

1. verify the provider version without exposing credentials;
2. run `ownership` once for both providers at the unchanged candidate HEAD;
3. run `interruption` once for both providers at that same HEAD;
4. require normalized success from both providers;
5. rerun the canonical verifier if the candidate HEAD changed;
6. record the recovered live evidence before any future release publication.

## Secret-handling boundary

- Never print or commit Keychain contents, access tokens, refresh tokens, API
  keys, raw provider streams, or full transcripts.
- `claude auth status` is not an inference-admission probe.
- Credential presence is not subscription evidence.
- A failed live canary remains failed evidence and is never relabeled as a
  deterministic or fake pass.
