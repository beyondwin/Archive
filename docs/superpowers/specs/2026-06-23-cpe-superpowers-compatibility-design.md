# CPE Superpowers Compatibility Design

## Goal

Validate `skills/kws-codex-plan-executor` against the current Superpowers
workflow and update CPE so it routes execution through the best verified model.

## Current Evidence

The latest Superpowers workflow is now stricter than the original CPE design:

- `brainstorming` owns idea-to-spec work and blocks implementation before
  approved design.
- `writing-plans` owns implementation-plan authoring and requires concrete,
  bite-sized task steps.
- `subagent-driven-development` owns in-session execution with a fresh
  implementer, task review, durable progress ledger, and final review.
- `verification-before-completion` requires fresh evidence before any completion
  claim.

CPE still provides useful execution infrastructure: isolated worktrees,
stateful run records, task packets, prompt/handoff export, headless execution,
deterministic validation, Graphify audit support, and run inspection. Recent
real CPE states show that the deterministic machinery still works, but also
show friction around duplicated orchestration, stale non-terminal state, and
task packet/write-scope drift.

## Candidate Directions

### Direction A: Keep CPE As Primary Executor

CPE remains the main implementation loop and continues to own task dispatch,
state updates, subagent policy, and completion proof.

Trade-off: this preserves existing state guarantees, but duplicates the newer
Superpowers execution loop and makes the skill harder to keep current.

### Direction B: Replace CPE With Superpowers-Native Execution

Users execute plans directly through Superpowers `subagent-driven-development`
or `executing-plans`; CPE only remains for historical prompt/handoff exports.

Trade-off: this matches the newest process, but drops CPE's deterministic
state, prompt, headless, run inspection, and compatibility machinery too
quickly.

### Direction C: Thin Stateful Bridge

CPE becomes a stateful bridge around the Superpowers-native flow:

- Prefer Superpowers-native execution for approved implementation plans when
  the session supports the current Superpowers skills.
- Keep CPE for prompt/handoff export, headless execution, resume/inspection,
  state/audit evidence, task packet generation, and tool-policy fallback.
- Before execution, run a deterministic compatibility simulation that compares
  the available Superpowers contracts and CPE contracts, then records the
  recommended route.
- Preserve CPE's safety gates: no edits on `main`, isolated worktree, task
  contracts, acceptance evidence, state validation, prompt cache audit, and
  Graphify audit when applicable.

This direction keeps CPE's durable infrastructure while reducing duplicate
implementation-loop ownership. It is the preferred target unless the
simulation shows missing Superpowers contracts or unsupported mode needs.

## Simulation Criteria

Each candidate is scored on a 0-5 scale for:

- `superpowers_alignment`: follows current brainstorming, planning, execution,
  review, and verification gates.
- `state_recoverability`: leaves enough durable state to resume, inspect, or
  audit a run after context loss.
- `implementation_quality`: preserves TDD, review, diff, and verification
  gates.
- `operator_cost`: avoids duplicated prompts, unnecessary handoffs, and
  redundant orchestration.
- `mode_coverage`: still supports interactive, headless, prompt, handoff, and
  resume use cases.
- `migration_risk`: can be adopted without breaking existing CPE contracts.

The best model is the highest total score, with `superpowers_alignment`,
`implementation_quality`, and `migration_risk` treated as hard priorities.

## Implementation Scope

Add a deterministic CPE compatibility simulation script and eval:

- `scripts/audit_superpowers_compatibility.py`
- `evals/check_superpowers_compatibility.py`

Update CPE documentation and contracts:

- `SKILL.md`
- `README.md`
- `ARCHITECTURE.md`
- `HISTORY.md`
- `references/mode-contracts.md`
- `references/execution-cycle.md`
- `docs/how-it-works.md`
- `docs/user-guide.ko.md`
- `docs/verification-log.md`

## Acceptance Evidence

The change is complete when:

- The simulation chooses Direction C for the current installed Superpowers
  contract.
- The simulation can explain why Direction A and Direction B lose.
- The eval fails if required Superpowers gates are absent.
- The eval is included in `evals/run.sh`.
- Existing CPE evals still pass.
- Python compile checks and shell syntax checks pass.
- `git diff --check` passes.
