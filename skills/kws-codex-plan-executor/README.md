# KWS Codex Plan Executor

Version 2.1.0 publishes format 3 run state for CPE, a small local harness for
approved Superpowers implementation plans. It keeps ordered input snapshots,
one reused isolated worktree, durable run facts, and a bounded resume boundary.
It is not a product orchestrator or a replacement for Superpowers.

## Ownership And Installation

CPE maintains one execution environment and verifies submitted facts.
Superpowers decides what work and verification are correct.

The runner performs a direct Superpowers launch inside its one reused isolated
worktree. It supplies immutable submitted inputs and factual execution context;
Superpowers owns plan interpretation, implementation, tests, reviews, fixes,
subagents, commits, and the decision to perform a final integration review.
Plans and resumes retain the same worktree and use same-HEAD cross-phase reuse
only for identical verification execution facts at the same HEAD.

This tracked directory is the release source of truth. Install the source of
truth with the Codex and Claude Code symlinks in [`../README.md`](../README.md).
Do not copy the skill into tool directories and do not modify Superpowers
upstream.

## Requirements And Commands

- Python 3 standard library
- Git
- `codex` on `PATH`
- a clean Git workspace, absolute readable UTF-8 spec/plan paths, and one or
  more plans

```bash
python3 scripts/cpe.py run \
  --spec /abs/spec-a.md --spec /abs/spec-b.md \
  --plan /abs/plan-01.md --plan /abs/plan-02.md \
  --workspace /abs/repository
python3 scripts/cpe.py run --plan /abs/plan.md --workspace /abs/repository \
  --sandbox workspace-write --controller-slice-seconds 1800
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py resume --run-id RUN_ID --retry-blocked
python3 scripts/cpe.py resume --run-id RUN_ID --retry-failed
python3 scripts/cpe.py inspect --run-id RUN_ID
```

`run` defaults to `danger-full-access` and 1200 seconds. The accepted range is
1200 through 3600 seconds. `--sandbox` and `--controller-slice-seconds` are
immutable run configuration: `resume` cannot replace them. Exit statuses are
`completed` (0), `failed` (1), `blocked` (2), and `checkpointed` (3); `inspect`
is read-only and exits 0 for an existing run.

With `danger-full-access`, writes outside the worktree are not fully observable
or reversible. The launcher removes selected secret variables and its prompt
prohibits remote actions and outside-worktree writes, while Git gates retain
local evidence; those controls are not a sandbox substitute. Choose
`workspace-write` when its narrower boundary fits the approved run.

## Execution And Resume Contract

Inputs are snapshotted before launch. The direct Superpowers child receives the
current plan, all submitted specification snapshots, the run's one reused
isolated worktree, current Git facts, and a strict result shape. CPE does not
compile a plan or reconstruct workflow semantics.

Plain resume produces zero controller launches for an unchanged known
parent-observed capability blocker or unchanged pre-execution worktree blocker.
An unknown blocked run is retried only with `--retry-blocked`; a failed run is
retried only with `--retry-failed`. A timeout can continue only within its
bounded launch and wall-time limits; an unchanged timeout stops without a
follow-up timeout policy.

Transport outcomes are factual and bounded. Provider conditions are classified
as `provider_usage_blocked`, `provider_auth_blocked`, or
`provider_unavailable` and become operator-owned blocked facts. CPE separately
records `controller_spawn_failed`, `controller_transport_failed`,
`controller_result_missing`, `controller_result_invalid`, and
`controller_timed_out`; raw provider messages are not retained as a second
transcript. None of these facts lets CPE choose the semantic recovery work.

## Caller-Selected Verification

CPE never selects or runs a full suite by itself. The approved plan or
Superpowers selects verification. CPE's `verify` command only executes the
exact submitted argv, without shell expansion or a hidden suite selection:

```bash
python3 scripts/cpe.py verify --run-id RUN_ID --command-id unit \
  --phase task --input-digest SHA256 --mutable-input-policy immutable \
  --cwd /abs/worktree -- python3 -m unittest
```

The supplied argv, cwd, `HEAD`, sanitized execution environment, executable
identity, input digest, and mutable-input policy are the execution identity.
Command ID and requested phase are observations. Same-HEAD cross-phase reuse
is allowed only for a successful deterministic receipt with the same identity.
A dirty worktree, changed input digest, changed identity fact, or
`always_execute` policy runs the exact submitted argv again. An untrusted
receipt also falls back to one exact submitted argv execution, not a suite
chosen by CPE.

## Completion And Handoff

CPE completes fail closed: the submitted result must contain safe
`ledger_path` and `final_review_path`, a `final_review_head` equal to the clean
worktree `HEAD`, empty `open_finding_ids` and `open_obligation_ids`, successful
verification outcomes, and valid ancestry. These are submitted facts. CPE does
not infer whether a review lifecycle happened or whether the work is correct.

`results/branch-handoff.json` contains branch, saved worktree, observed `HEAD`,
last-known `HEAD`, accepted plan evidence, and `integration=not_observed`.
It is local factual evidence only and never claims merge, push, deploy,
publication, product acceptance, or observed external integration.

Run state is stored outside the source repository under
`~/.codex/orchestrator/<run-id>/`; the linked worktree is normally
`~/.codex/worktrees/<run-id>/`. An explicit `CODEX_HOME` changes that prefix.

## Verify

Add or update a focused deterministic eval before changing the public contract.
During implementation, run the exact affected tests and static checks. At the
final clean revision, after the externally owned integration review, run the
complete local gate once:

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
```

The deterministic evals are sequential, network-free, credential-free, and
model-free. A retained `evals/fixtures/canvas-direct-run-format2.json` is
historical format 2, non-resumable audit evidence only; it is not active run
state or a current contract.

## Tracked Inventory

```text
README.md
SKILL.md
evals/check_cli.py
evals/check_runner.py
evals/fake_codex.py
evals/fixtures/canvas-direct-run-format2.json
evals/fixtures/canvas-format1-token-forensic.json
evals/fixtures/cpe-2-1-retry-forensic.json
evals/fixtures/gasstation-comparative.json
evals/fixtures/readmates-comparative.json
evals/run.sh
scripts/cpe.py
scripts/cpe_runtime/__init__.py
scripts/cpe_runtime/capabilities.py
scripts/cpe_runtime/evidence.py
scripts/cpe_runtime/launcher.py
scripts/cpe_runtime/progress.py
scripts/cpe_runtime/reporting.py
scripts/cpe_runtime/result_validation.py
scripts/cpe_runtime/runner.py
scripts/cpe_runtime/state.py
scripts/cpe_runtime/verification.py
templates/execution-ledger.schema.json
templates/optimization-report.schema.json
templates/plan-result-schema.json
```
