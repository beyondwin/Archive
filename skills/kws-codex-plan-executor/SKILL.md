---
name: kws-codex-plan-executor
description: Use when approved Superpowers implementation plans must run in fixed order and survive process interruption.
metadata:
  version: "2.1.1"
  updated_at: "2026-07-24"
---

# KWS Codex Plan Executor

Version 2.1.1 publishes format 3 run state for a thin, local execution
harness. Use CPE only for approved Superpowers plans that need durable ordered
execution and resume. For bounded work that does not need a durable run, use a
direct Superpowers launch in the current worktree.

## Ownership And Launch Boundary

CPE maintains one execution environment and verifies submitted facts.
Superpowers decides what work and verification are correct.

CPE snapshots the submitted inputs, creates one reused isolated worktree, and
launches Codex directly into Superpowers in that worktree. The launcher passes
paths and current Git facts, but does not compile a plan or choose a task,
review, fix, test, subagent, commit, or release workflow. A later plan and a
resume use the same worktree unless the approved plan itself requires a
cross-revision comparison.

```bash
python3 scripts/cpe.py run \
  --document /abs/design.md --document /abs/implementation.md \
  --workspace /abs/repository \
  --superpowers-skill subagent-driven-development
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py inspect --run-id RUN_ID
```

`run` defaults to `danger-full-access` and a 1200 seconds controller slice.
`--sandbox workspace-write` is the available opt-down. The controller slice
may be set from 1200 through 3600 seconds; both sandbox and slice are persisted
as immutable run configuration, so `resume` does not accept replacements.

The accepted `danger-full-access` residual risk is that writes outside the
worktree are not fully observable or reversible; prompt and remote prohibitions
plus Git gates remain, but are not a sandbox substitute. The child prompt also
prohibits merge, push, deploy, and writes outside its worktree; that is a guard,
not proof of complete containment.

## Verification And Completion

CPE never selects or runs a full suite by itself. Superpowers or the approved
plan chooses verification. Caller-selected verification uses the optional
`verify` command, which only executes the
exact submitted argv, without a shell; it does not expand a command into a
full-suite policy. Caller-selected verification records its submitted command,
working directory, input digest, mutable-input policy, execution environment,
and executable identity.

Successful deterministic verification can use same-HEAD cross-phase reuse at
the same HEAD:
the phase and command ID are observations, while the same exact submitted argv,
working directory, `HEAD`, environment, executable identity, input digest, and
policy form the execution identity. Dirty worktree state, changed input digest,
changed identity facts, or an always-execute policy requires a new execution.
If receipt facts cannot be trusted, CPE executes the exact submitted argv once
and records the result instead of treating it as reusable success.

Completion is fail closed. A completed child result must submit safe
`ledger_path` and `final_review_path`, a `final_review_head` equal to the clean
worktree `HEAD`, empty `open_finding_ids` and `open_obligation_ids`, successful
verification outcomes, and valid ancestry. CPE validates these facts without
inferring a review lifecycle or deciding whether the submitted review is good.

The completed branch handoff records the branch, observed and last-known
`HEAD`, accepted evidence references, and `integration=not_observed`. It must
not claim merge, push, deploy, publication, or product acceptance.

## Resume And Transport Facts

Known unchanged parent-observed capability blockers and known unchanged
pre-execution worktree blockers produce zero controller launches on plain
resume. An unknown blocked run requires `--retry-blocked`; a failed run requires
`--retry-failed`. A timeout may resume only while its bounded launch and wall
time budgets allow it; an unchanged timeout stops without a follow-up timeout
policy.

If a failed run's latest terminal fact is exactly
`execution_ledger_invalid`, `recover-ledger` can quarantine only the exact
caller-digested invalid ledger under the run root. It rejects valid ledgers,
symlinks, changed digests, accepted ledger history, non-matching failures, and
busy runs. The named authority profile is then recorded durably and transmitted
only on the resumed run; it authorizes local implementation, checkpoint
commits, and evidence-gated approval decisions inside the saved CPE worktree.
It does not authorize outside-worktree writes or remote actions. Resume the
same run with `--retry-failed` after recovery.

The launcher records classified transport outcomes without retaining raw
provider messages. `provider_usage_blocked`, `provider_auth_blocked`, and
`provider_unavailable` become operator-owned blocked facts. Spawn, transport,
missing-result, and invalid-result outcomes are recorded distinctly, including
`controller_transport_failed`; timeouts are `controller_timed_out`. These
transport facts report what happened and do not give CPE authority to select a
recovery workflow.

## Local Installation And Verification

The tracked `skills/kws-codex-plan-executor/` directory is the source of truth.
Install it for Codex and Claude Code with symlinks from `skills/README.md`; do
not copy this skill into either tool directory and do not edit Superpowers
upstream.

For a behavior change, add a focused deterministic eval first. The complete
local gate is `./evals/run.sh`; use it only at the final clean revision after
the externally owned integration review. During a change, run the focused test
and applicable static checks. Evals are sequential, network-free,
credential-free, and model-free.
