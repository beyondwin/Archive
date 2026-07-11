# CPE v3 Subscription Live Matrix Design

**Status:** Approved

**Date:** 2026-07-11

**Target:** Produce reproducible credentialed-model evidence for CPE v3 without
inventing provider results or treating a dollar estimate as a ChatGPT
subscription control.

## Summary

CPE `3.0.1` is deterministically ready but remains `paid-live-pending`. The
current live-migration package validates a fixed four-treatment, eight-case
matrix and aggregates supplied results, but it deliberately launches no model.
The repository also contains no case fixtures, deterministic oracles, resumable
live runner, or trusted result producer. Therefore the existing command cannot
produce the evidence required to close the live gate.

This design adds a repository-native, resumable subscription live runner. It
executes the three core treatments across all eight cases, executes Terra only
for the one permitted read-only case, and records seven Terra policy rejections
without launching a model. The resulting 25 credentialed calls and seven
policy outcomes form the exact existing 4x8 matrix.

The runner uses Codex authenticated with ChatGPT. It never configures or uses an
OpenAI API key, buys credits, or enables automatic top-up. ChatGPT subscription
usage has no trustworthy dollar meter exposed to this runner, so subscription
evidence records tokens and billing mode while leaving `cost_usd` unknown. The
legacy `$50` hard cap remains fail-closed for any future metered API or purchased
credit mode; it does not limit the approved ChatGPT subscription mode.

## Evidence Basis

The design is based on local `main` at
`4e60e31ae535e1716841e9eb3f9a36bffbde992b` and these current facts:

- `codex login status` reports `Logged in using ChatGPT` when invoked through
  the Codex app-bundled CLI.
- The local Codex model catalog contains `gpt-5.5`, `gpt-5.6-sol`, and
  `gpt-5.6-terra`, each with `high` reasoning support.
- `evals/live_model_migration.py` explicitly states that it never launches
  providers and requires pre-generated `--results-json` evidence.
- The current matrix defines four treatments and eight case names but no case
  inputs, fixture repositories, or expected outcomes.
- The current estimate is 32 slots at `$1.50` each, but only 25 slots require a
  credentialed call because seven Terra outcomes are mandatory policy
  rejections.

## Operator Decisions

The operator approved:

1. implementing the repository-native fixture, runner, oracle, and evidence
   path rather than supplying an external result file;
2. using ChatGPT subscription capacity without the artificial `$50` limit;
3. maximizing coverage by completing the exact approved matrix;
4. not relying on a fabricated USD value for subscription usage.

This approval does not authorize the implementation to purchase credits,
enable auto top-up, switch to API-key billing, or weaken a quality threshold.

## Goals

1. Produce every result in the existing 4x8 contract from a reproducible input
   and an auditable oracle.
2. Execute exactly 25 credentialed model calls and seven fail-closed policy
   outcomes for one complete matrix attempt.
3. Bind model, prompt, fixture, oracle, repository revision, and result digests
   into immutable external evidence.
4. Resume safely after interruption or subscription rate-limit exhaustion
   without repeating completed calls.
5. Measure task success, review accuracy, evidence completeness, repairs,
   regressions, tokens, cache use, latency, attestation, isolation, and drift.
6. Keep subscription usage separate from metered dollar accounting.
7. Change release readiness only after the complete current report passes the
   unchanged quality gate and an independent review.

## Non-Goals

- Replacing the fixed Sol/high core and Terra/high scout runtime policy.
- Adding arbitrary model aliases, fallback routes, or operator-selected models.
- Treating dry-run, synthetic results, or mocked provider output as live
  evidence.
- Running indefinitely or repeating trials solely to consume remaining plan
  capacity.
- Purchasing credits, changing billing settings, or enabling automatic
  top-up.
- Claiming that subscription token usage has zero economic cost.
- Committing raw prompts, full transcripts, credentials, home-directory paths,
  or provider response logs.
- Weakening the existing release thresholds to obtain a passing report.

## Approaches Considered

### Repository-Native Resumable Runner

This is the approved approach. Fixtures, schemas, deterministic oracles, and
the runner live beside the existing migration evaluator. Sanitized contracts
are versioned; credentialed evidence remains outside Git. It provides the
strongest repeatability and makes future reruns comparable.

### One-Off External Script

A temporary script could produce the required JSON sooner, but its fixture and
judging behavior would not be reviewable with the release contract. It was
rejected because a passing report could not be reproduced confidently.

### Manual Sessions And Human Scoring

Manual execution can inspect nuanced answers, but model, prompt, tokens,
latency, worktree state, and scoring would be inconsistent. It was rejected as
the primary gate. A human may review the final evidence, but deterministic
oracles remain authoritative.

## Architecture

### LiveMatrixCompiler

`LiveMatrixCompiler` combines the checked-in treatment matrix, case registry,
prompt templates, and fixture digests into an immutable execution manifest. It
validates:

- exactly four treatment IDs and eight case IDs;
- exactly 32 unique treatment/case slots;
- 25 `credentialed_call` slots and seven `expected_policy_failure` slots;
- model and reasoning values equal the checked contract;
- every credentialed slot references a fixture, oracle, prompt renderer, and
  output schema;
- every policy-failure slot contains a machine-checkable policy reason.

The compiler does not launch a model. A dry run writes the complete manifest
and reports counts, digests, billing mode, and expected call count.

### FixtureStore

Each case owns a small deterministic Git repository template and a `case.json`
contract. Fixtures use only locally available standard tooling and make no
network calls. Every case declares:

```json
{
  "schema_version": "1",
  "case_id": "single-file implementation",
  "mode": "write",
  "task": "bounded instruction",
  "allowed_paths": ["src/example.py"],
  "forbidden_paths": ["tests/oracle_test.py"],
  "acceptance_command": "python3 -m unittest",
  "oracle": "oracle.py",
  "expected_policy": "core_only"
}
```

The eight fixtures exercise distinct capabilities:

| Case | Fixture and deterministic outcome |
| --- | --- |
| single-file implementation | Implement one pure function; unit tests and allowed-path diff must pass. |
| cross-package implementation | Change two small packages through a documented interface; integration tests and claims must pass. |
| root-cause repair | Diagnose a seeded state-isolation failure and apply the minimal verified repair. |
| defect review | Read-only review of seeded defects; normalized findings must match the required finding set and no file may change. |
| failed-test interpretation | Explain a deterministic failing trace; structured cause, evidence, and next action must match the oracle. |
| security/migration block | Reject a destructive migration request, identify the violated boundary, and make no change. |
| resume/state repair | Repair a synthetic interrupted v3 run through the public repair and validation commands. |
| large read-only exploration | Inspect a generated multi-package tree and return a structured architecture/fact map without writes. |

Oracle tests and files that disclose the expected solution are excluded from
the model-visible prompt. The acceptance command may execute hidden oracle
material only after the model turn ends.

### SubscriptionLiveRunner

The runner invokes the app-bundled Codex CLI directly so a broken unrelated
Homebrew shim cannot select a different binary. Before execution it verifies:

- `codex login status` is authenticated through ChatGPT;
- the exact model catalog contains the required model and `high` reasoning;
- API-key environment variables are removed from the child environment;
- the source checkout and fixture template remain read-only;
- the execution root is outside the repository and newly initialized for this
  live run.

Each credentialed slot receives a fresh copied fixture repository and isolated
Codex home/session directory. The runner invokes one model turn with the
treatment's exact prompt prefix plus the case task, requests the checked output
schema, and captures JSONL events. It sets a per-slot timeout, terminates the
process group on timeout, and never silently retries a completed call.

The seven Terra-ineligible cases do not launch Codex. The runner records a
digest-bound policy result with `expected_policy_failure=true`, the rejected
role, and the matrix-policy digest.

### DeterministicOracle

After each credentialed call, an oracle evaluates provider-independent facts:

- process exit and structured output validity;
- declared model and reasoning attestation from Codex events;
- acceptance command result;
- before/after Git revision, status, and patch digest;
- allowed and forbidden path compliance;
- required read-only behavior;
- normalized expected findings or explanation facts;
- critical regression classification;
- worktree identity and source-fixture drift.

Worker self-report never overrides these facts. Ambiguous or missing evidence
fails the slot. Review accuracy uses exact normalized finding IDs, not prose
similarity or an LLM judge.

### EvidenceLedger

Live evidence is stored under:

```text
~/.codex/evals/cpe-v3-live/<run_id>/
  manifest.json
  events.jsonl
  state.json
  slots/<treatment>/<case>/
    invocation.json
    codex-events.jsonl
    final-output.json
    oracle.json
    stderr.log
  results.json
  report.json
```

`manifest.json` is immutable after creation. `events.jsonl` is append-only and
hash-chained. `state.json` is an atomic projection used for progress and
resume. Slot evidence is written to a temporary directory and atomically
renamed only after the oracle finishes. `results.json` is generated solely
from completed slot evidence.

Raw logs remain external and may contain model text. The committed verification
log stores only the run ID, implementation commit, UTC timestamp, report and
manifest SHA-256 digests, aggregate metrics, gate result, and residual risks.

### ResumeController

Resume rebuilds state from the manifest and event ledger, validates every
completed slot digest, and schedules only missing or explicitly failed slots.
An interrupted in-progress slot is marked abandoned and requires explicit
`--retry-failed`; it is never mistaken for completion. Rate-limit or plan-limit
errors stop the run cleanly with `subscription_limit_reached` so the same run
can continue after reset.

The default complete-matrix command performs no statistical repetitions. It
maximizes the approved coverage contract rather than consuming subscription
capacity without a predeclared experimental purpose.

## Billing And Usage Contract

The runner supports two distinct accounting modes:

### `chatgpt_subscription`

- requires ChatGPT login attestation;
- rejects API-key authentication;
- does not require or enforce `--budget-usd`;
- records input, cached-input, and output tokens from Codex events;
- records `cost_usd=null` and `cost_observability=unavailable`;
- never modifies credit or auto-top-up settings;
- stops on any usage-limit or billing-required error.

The runner cannot prove which account-side subscription or existing-credit
bucket OpenAI consumed. The operator's account settings remain an external
billing boundary. The report must say this explicitly.

### Metered Dollar Mode

Metered API or purchased-credit execution is not implemented by this change.
The existing `$50.00` maximum remains the fail-closed contract for that future
mode. Removing the subscription-mode dollar estimate must not remove this
safety boundary or imply authorization for metered spending.

## Prompt Isolation

`gpt55_current` and `sol_current` receive the exact historical prompt fixture.
`sol_v3` receives the current fresh-session template rendered with fixture
paths and hashes. `terra_scout` receives a generated read-only prompt containing
the same evidence and output requirements without verdict or write authority.

All treatments receive the same case task and visible repository content. They
do not receive oracle source, expected solution text, another treatment's
output, or previous slot context. Dynamic absolute paths are placed only in the
hot tail so stable prompt prefixes remain cacheable.

## Result Schema

Each of the 32 result records contains:

```json
{
  "schema_version": "2",
  "run_id": "cpe-v3-live-...",
  "treatment_id": "sol_v3",
  "case_id": "single-file implementation",
  "outcome_kind": "credentialed_call",
  "expected_policy_failure": false,
  "task_completed": true,
  "first_pass_success": true,
  "review_accurate": true,
  "evidence_complete": true,
  "repairs": 0,
  "critical_regression": false,
  "context_tokens": 0,
  "cache_tokens": 0,
  "output_tokens": 0,
  "latency_ms": 0,
  "billing_mode": "chatgpt_subscription",
  "cost_usd": null,
  "model_attested": true,
  "worktree_isolated": true,
  "drift_free": true,
  "evidence_sha256": "..."
}
```

Policy-failure records use `outcome_kind=expected_policy_failure`, contain no
provider usage metrics, and cite the matrix-policy digest. The aggregator
excludes those records from quality-rate denominators exactly as it does now.

## Release Gate

The existing quality thresholds remain unchanged:

- no Sol v3 critical regressions;
- Sol v3 task completion does not regress from the GPT-5.5 baseline;
- all core-treatment model attestations are present;
- Sol v3 worktree isolation and drift-free rates are 100%;
- Sol v3 reduces context tokens by at least 25% from GPT-5.5.

The live closeout additionally requires:

- the exact 32-slot manifest and results set;
- 25 credentialed calls and seven expected policy failures;
- all fixture, oracle, prompt, model-catalog, implementation, and result
  digests present;
- no unresolved timeout, rate-limit, malformed-output, or evidence blocker;
- `release_gate.passed=true` from the checked-in aggregator;
- independent review of the implementation and sanitized report;
- current deterministic gates, Graphify freshness, and clean tracked state.

If any requirement fails, the release remains
`deterministic-ready; paid-live-pending` with `release_ready=false`. Thresholds
must not be edited in the same change merely to turn a failure green.

After a passing current report, a reviewed follow-up may publish the exact
tuple `deterministic-ready; paid-live-verified` with `release_ready=true` and a
compatible minor version. The verification log must state that the evidence
used ChatGPT subscription authentication and that direct USD cost was not
observable.

## Failure Handling

- Missing ChatGPT login or required model: block before the first call.
- API-key authentication detected: block before the first call.
- Subscription limit reached: preserve evidence and stop resumably.
- Timeout: terminate the process group and record a retry-required blocker.
- Malformed output: fail the slot; never infer fields from prose.
- Missing model or token attestation: fail evidence completeness.
- Fixture or oracle digest mismatch: block the whole run.
- Source checkout or template drift: block and preserve the evidence.
- Acceptance failure or forbidden write: record the measured failure.
- Report aggregation failure: keep live status pending.

## Deterministic Verification

Implementation must add cost-free tests for:

1. exact 25-call and seven-policy-outcome compilation;
2. fixture and oracle digest validation;
3. API-key and wrong-auth rejection;
4. ChatGPT subscription mode without a dollar estimate;
5. metered mode retaining the `$50` fail-closed boundary;
6. subprocess timeout and process-group termination;
7. partial-run replay and resume without duplicate calls;
8. corrupted, duplicate, missing, and stale slot evidence;
9. hidden-oracle and prompt-isolation enforcement;
10. deterministic success and failure scoring for every fixture;
11. `cost_usd=null` acceptance only for attested subscription evidence;
12. release rejection for incomplete or synthetic evidence;
13. sanitized report digest binding to the current implementation commit;
14. unchanged quality thresholds and paid-pending behavior before a passing
    live report.

The full closeout verification remains:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
python3 scripts/cpe.py --help
cd ../..
bun run check
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran --output /tmp/cpe-v3-live-graphify.json
git diff --check
```

## Documentation Impact

Implementation must inspect and align:

- `skills/kws-codex-plan-executor/SKILL.md`
- `skills/kws-codex-plan-executor/README.md`
- `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- `skills/kws-codex-plan-executor/docs/release-process.md`
- `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- `skills/kws-codex-plan-executor/docs/decisions.md`
- `skills/kws-codex-plan-executor/docs/verification-log.md`
- `skills/kws-codex-plan-executor/HISTORY.md`

The design-only commit does not change the current `3.0.1` release tuple. A
later implementation commit may add the runner while status remains pending;
only evidence produced from that exact reviewed implementation can authorize
the final release-state commit.

## Acceptance Criteria

The work is complete only when:

1. deterministic tests prove the runner, fixtures, oracles, ledger, resume,
   billing boundary, and release gate;
2. a dry run produces the exact 32-slot manifest without provider calls;
3. one resumable live run produces all 25 credentialed and seven policy
   outcomes from the reviewed implementation commit;
4. the aggregator reports `release_gate.passed=true` without threshold edits;
5. external evidence and committed sanitized digests agree;
6. independent implementation and evidence reviews report no blocking finding;
7. the full repository verification matrix passes on the final commit;
8. release metadata states exactly what was proven and retains any account-side
   billing observability limitation as residual risk.
