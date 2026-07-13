---
name: kws-codex-plan-executor
description: Use when executing one or many approved Superpowers implementation plans as a durable schema-4 queue with fresh bounded Codex roles, interruption recovery, and multi-document coverage.
metadata:
  version: "4.0.0"
  updated_at: "2026-07-13"
---

# KWS Codex Plan Executor

CPE 4 is a durable, non-LLM queue for large approved Superpowers programs. Use
direct Superpowers for bounded same-session work. Use CPE when execution must
survive context compaction, process interruption, multiple days, or several
specification and plan documents.

CPE owns immutable snapshots, dependency state, one isolated worktree, bounded
child launch, durable events, authority waiting, resume, inspection, and final
revision binding. Fresh Codex roles own mapping, TDD implementation, focused
tests, code review, investigation, fixes, document coverage audits, and final
integration. No long-lived model controller retains the run history.

## Commands

At least one plan is required. Spec and plan flags repeat; program-plan appears
at most once. Paths must be absolute.

    python3 scripts/cpe.py run \
      --spec /abs/spec-a.md --spec /abs/spec-b.md \
      --plan /abs/plan-a.md --plan /abs/plan-b.md \
      --program-plan /abs/program.md --workspace /abs/repo

    python3 scripts/cpe.py resume --run-id RUN_ID
    python3 scripts/cpe.py resume --run-id RUN_ID \
      --authority-id AUTHORITY_ID --authority-answer ANSWER
    python3 scripts/cpe.py resume --run-id RUN_ID --refresh-inputs
    python3 scripts/cpe.py inspect --run-id RUN_ID

    python3 scripts/cpe.py export \
      --spec /abs/spec.md --plan /abs/plan.md \
      --workspace /abs/repo --mode prompt
    python3 scripts/cpe.py export \
      --plan /abs/plan.md --workspace /abs/repo --mode handoff

Run and resume execute. Inspect is read-only. Export only renders text; it
creates no run root or worktree.

## Fresh Role Ownership

- Document mappers read one immutable document each and emit exact references.
- The program mapper composes the task, coverage, dependency, and authority
  graph without resolving conflicts by CLI order.
- Task agents use Superpowers TDD and focused verification, commit one clean
  handoff, and exit.
- Reviewers inspect the exact task diff and do not repeat an identical focused
  test at the same revision.
- Investigators and consolidated fix agents change strategy for ordinary
  failures while preserving evidence.
- Document auditors check one source document against relevant briefs, reports,
  reviews, and diff slices.
- The Program Final Integrator reviews the whole program, runs the single final
  verification, and owns the terminal quality artifact.
- An integration fix invalidates affected audits and final evidence.

Only one write-capable role runs at a time. Every successful writer handoff is
commit-bound and must leave the tracked worktree clean.

## Standing Autonomy And Authority

The queue continues through product defects, test failures, review findings,
technical choices, safe refactors, recoverable local setup problems, and
interrupted children. The tie-break order is: approved requirements, repository
architecture, smallest reversible change, lowest operational risk, strongest
testability, then least new machinery. Nontrivial choices are appended to the
autonomy ledger.

Waiting for the user is allowed only for these six authority codes:

- credential_required
- external_side_effect
- destructive_outside_worktree
- authoritative_document_conflict
- material_scope_expansion
- legal_security_policy_authority

An authority answer must be one offered option. It is appended as a durable
event; the original packet is not rewritten.

## Durable Boundary

CPE snapshots every input before child launch and stores private state beneath
CODEX_HOME/orchestrator/RUN_ID. The isolated worktree is beneath
CODEX_HOME/worktrees/RUN_ID. The run manifest, input snapshots, artifact index,
hash-chained event stream, autonomy ledger, reports, reviews, verification
evidence, and terminal result are file-backed.

Resume validates the manifest, event head and chain, selected map publication,
worktree identity, and recorded commits before continuing the first nonterminal
item. Completed work is not redispatched. Source changes affect a run only
through explicit --refresh-inputs, which creates a new immutable generation.

A terminal completed status means the terminal integration artifact exists at
the exact worktree revision. That artifact separately records its quality
verdict, verification command and exit status, auditor verdicts, and
limitations.

Schema-3 run directories are never rewritten. Inspect returns a bounded
read-only summary; resume returns legacy_run_requires_historical_cpe. Git
history contains the historical implementation.

## Verification

The complete deterministic suite is standard-library-only, network-free,
credential-free, and bounded to six checks:

    ./evals/run.sh
    python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
    bash -n evals/run.sh
    python3 scripts/cpe.py --help
    python3 scripts/cpe.py run --help
    python3 scripts/cpe.py export --help

The six checks cover contracts, mapping, queue execution, final closure,
recovery, and CLI/export behavior. The development-machine target is under 60
seconds.

## References

- Architecture: ARCHITECTURE.md
- Usage and artifacts: README.md
- State and replay: references/state-schema.md
- Execution cycle: references/execution-cycle.md
- Verification: docs/evals-and-verification.md
- Risks: docs/risks-limitations-deferrals.md
- Change protocol: references/change-protocol.md
