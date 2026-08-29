# CPE as a Lightweight Superpowers Wrapper

## Conclusion

CPE should be a lightweight durable wrapper around Superpowers, not a second
workflow engine.

The selected boundary is:

```text
CPE
  - creates and reuses one isolated worktree
  - preserves RUN_ID, branch, inputs, process state, and resume facts
  - launches Codex with the approved plan and explicit authority note
  - records controller outcomes
  - validates a clean local branch handoff

Superpowers / subagent-driven-development
  - reads and executes the plan
  - creates task briefs
  - dispatches implementers and reviewers
  - runs TDD and focused verification
  - creates authorized checkpoint commits
  - maintains task progress
  - resolves findings and performs final review
```

CPE must not duplicate task planning, task review, progress semantics, or test
selection.

## Why direct SDD starts naturally

`subagent-driven-development` already defines the complete execution loop:

1. read the approved plan;
2. dispatch a fresh implementer for one task;
3. run TDD and commit the task;
4. dispatch an independent reviewer;
5. fix and re-review findings;
6. record the completed task in `.superpowers/sdd/progress.md`;
7. continue without waiting for routine user approval;
8. run a whole-branch review at the end.

When used directly, the current controller also retains the user's authority
and surrounding context.

CPE currently launches a new ephemeral controller with a small reconstructed
prompt. The child does not automatically inherit the outer conversation. CPE
then requires additional CPE-specific files that ordinary Superpowers does not
own.

That extra contract is where the affected run failed.

## Affected run

| Field | Value |
| --- | --- |
| Run ID | `cpe-4e9bd86b31dc47e6` |
| Branch | `codex/cpe-4e9bd86b31dc47e6` |
| Worktree | `/Users/kws/.codex/worktrees/cpe-4e9bd86b31dc47e6` |
| Source and observed HEAD | `4d0153c3ec347dbdaff32642426c466c5b7a607d` |
| Attempts launched | `1` |
| Current status | `failed` |
| Accepted commit | none |

Attempt 1 implemented and verified Task 0, but two wrapper-specific contracts
stopped the run.

### 1. Duplicate progress ledger

Superpowers uses:

```text
.superpowers/sdd/progress.md
```

CPE additionally required:

```text
.superpowers/sdd/execution-ledger.jsonl
```

The child wrote a legacy summary shape. CPE's strict validator rejected it.
`resume --retry-failed` then validated the same malformed file before allowing
the child to continue, so recovery became circular.

The validator was not the core mistake. Requiring a generic Superpowers child
to hand-write a second task-progress protocol was.

### 2. Mutable helper binding

Local commit `9f375943` added an exact-digest ledger quarantine and passed the
ledger schema and authority profile to the child. It was merged into local
Archive `main` by `792b87a6`.

The exact invalid ledger was safely quarantined. The next resume still stopped
before attempt 2 with:

```text
verification.helper_unavailable_no_request
detail=verification helper descriptor was replaced
```

The run's verification helper was sealed against the installed CPE source.
Fixing CPE changed that source and invalidated the active run.

An isolated worktree contains an experimental `recover-helper` follow-up, but
its complete eval was interrupted. It is unaccepted and should not become the
architecture.

## Lightweight fix

### 1. Launch Superpowers explicitly

The child prompt should say exactly which workflow owns execution:

```text
Use subagent-driven-development for this approved plan.
Resume from .superpowers/sdd/progress.md and Git history.
Do not stop between ordinary tasks.
```

The prompt should provide:

- saved worktree;
- immutable spec and plan paths;
- starting and current commit;
- previous attempt result or recovery note;
- one small authority note;
- final result schema.

It should not describe or recreate the SDD task loop.

### 2. Use one progress owner

Remove `execution-ledger.jsonl` from the required child contract.

Superpowers remains the only task-progress owner through:

- `.superpowers/sdd/progress.md`;
- task reports and review packages;
- Git checkpoint commits.

CPE may read the progress file and Git history for diagnostics, but it must not
translate or validate task semantics before launching a resume.

CPE's own private `events.jsonl` remains valid because it records only wrapper
facts:

- run and attempt started;
- process returned or timed out;
- provider unavailable;
- observed HEAD;
- child result accepted or rejected;
- run checkpointed, blocked, failed, or completed.

The child never writes this private event stream.

### 3. Pass a small authority note

The outer controller should create one short immutable authority file at run
creation. It does not need a large capability framework.

Example:

```json
{
  "implementation": true,
  "local_checkpoint_commits": true,
  "evidence_gated_approvals": true,
  "outside_worktree_writes": false,
  "merge": false,
  "push": false,
  "deploy": false,
  "history_rewrite": false
}
```

The child receives the file path on every launch. Missing permissions remain
false. Local implementation permission never implies remote permission.

### 4. Make resume tolerant of child scratch files

Before a resume, CPE should validate only wrapper-owned invariants:

- same RUN_ID;
- same saved worktree and branch;
- current HEAD descends from the recorded base;
- immutable spec, plan, and authority note are unchanged;
- no conflicting live controller;
- remaining launch and wall-time budget.

Malformed or stale `.superpowers/sdd/*` scratch files must not prevent the next
Superpowers controller from launching. The controller can inspect the
worktree, Git history, and progress file and repair its own workflow artifacts.

CPE still fails closed on:

- missing or replaced worktree;
- branch/history divergence;
- changed immutable inputs;
- live owner conflict;
- unsafe final handoff;
- provider/auth/platform blockers.

### 5. Keep verification inside Superpowers

Remove the run-critical verification-helper descriptor.

Superpowers already selects and runs:

- RED/GREEN tests;
- focused regressions;
- task verification;
- branch verification;
- independent reviews.

CPE only needs the final structured result to reference the task ledger and
final review, and it should validate:

- paths are safe and inside the worktree;
- final review HEAD equals current HEAD;
- worktree is clean;
- accepted HEAD descends from the base;
- findings and obligations are empty;
- the child reports successful verification outcomes.

The outer supervisor remains responsible for canonical branch/release
verification after the CPE handoff. This matches the existing local-main
closeout boundary.

### 6. Keep runtime upgrades simple

An active run should not be coupled to a digest of every installed CPE Python
file.

Use a small `runtime_contract_version` in run state. Resume is allowed when the
installed runtime declares compatibility with that version.

If a future incompatible format is required, fail with
`runtime_contract_incompatible` and provide one narrow migration command.
Do not add a recovery command for every helper or descriptor.

## Minimal production changes

| File | Change |
| --- | --- |
| `scripts/cpe_runtime/launcher.py` | Explicitly invoke SDD and pass the authority note |
| `scripts/cpe_runtime/runner.py` | Stop gating resume on child task-ledger validation |
| `scripts/cpe_runtime/state.py` | Store authority digest and `runtime_contract_version` |
| `scripts/cpe_runtime/result_validation.py` | Keep only final handoff fields |
| `scripts/cpe_runtime/verification.py` | Remove run-critical helper source binding |
| `scripts/cpe.py` | Add an authority-file input; keep run/resume/inspect simple |
| `README.md`, `SKILL.md` | Document the thin wrapper boundary |

No plan compiler, task database, ledger append API, workflow adapter framework,
or Superpowers modification is required.

## Suggested result contract

The child result can remain small:

```json
{
  "status": "completed",
  "head_commit": "40-hex",
  "summary": "Tasks 0-18 complete",
  "progress_path": ".superpowers/sdd/progress.md",
  "final_review_path": ".superpowers/sdd/final-review.md",
  "open_finding_ids": [],
  "open_obligation_ids": [],
  "verification": [
    {
      "command": "npm run verify:branch -- --base BASE --head HEAD",
      "exit_code": 0,
      "evidence_path": ".artifacts/..."
    }
  ]
}
```

CPE validates containment, cleanliness, HEAD, ancestry, and field shape. It
does not reimplement whether a task review was correct.

## Minimal tests

### Launch

- Prompt names `subagent-driven-development`.
- Prompt passes spec, plan, worktree, Git facts, recovery note, and authority
  path.
- Prompt never claims an authority absent from the note.
- Prompt retains merge/push/deploy/outside-worktree prohibitions.

### Resume

- A malformed `execution-ledger.jsonl` does not block a controller launch.
- Existing `.superpowers/sdd/progress.md` and Git commits are preserved.
- A checkpointed child resumes in the same worktree and RUN_ID.
- Changed branch, base ancestry, immutable input, or live owner still blocks.

### Completion

- Dirty handoff fails.
- Wrong HEAD or ancestry fails.
- Unsafe progress/review/evidence paths fail.
- Open findings or obligations fail.
- A clean valid handoff completes.

### Compatibility

- Installed source edits do not invalidate an active compatible run.
- A declared incompatible runtime version stops with one actionable reason.
- Provider/auth/timeout behavior and process cleanup remain unchanged.

### Live canary

- Create one small multi-task plan.
- Confirm implementer, reviewer, fix, and final-review turns occur.
- Stop after a checkpoint and resume the same RUN_ID.
- Complete with a clean branch handoff.
- Then recover `cpe-4e9bd86b31dc47e6` and reverify Task 0 before continuing.

## What not to build

Do not add:

- a CPE task compiler;
- a second task ledger;
- a CPE-owned review workflow;
- a generic event protocol for every Superpowers action;
- source-digest binding for every helper file;
- one recovery command per artifact;
- a copy of the parent transcript;
- modifications to Superpowers upstream;
- relaxed final clean-worktree or ancestry gates.

## Immediate recommendation

1. Preserve `cpe-4e9bd86b31dc47e6`.
2. Do not merge the experimental `recover-helper` changes.
3. Implement the thin-wrapper changes above with focused RED/GREEN tests.
4. Run a small SDD canary through CPE.
5. Resume the affected run only after the canary proves same-RUN_ID checkpoint
   and review behavior.
6. Until then, use direct `subagent-driven-development` for long approved
   implementation plans.

## Final decision

CPE's value is durable execution infrastructure:

```text
worktree + RUN_ID + process lifecycle + resume + clean branch handoff
```

Superpowers already provides the semantic development workflow:

```text
task brief + implementer + TDD + reviewer + fixes + progress + final review
```

The fix is to connect those two layers with a small authority note and a small
result envelope, not to build another orchestration protocol between them.
