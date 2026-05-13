# Risks, Limitations, And Deferrals

This document lists known risks and intentional tradeoffs. It should be updated
when a future change removes a limitation or accepts a new one.

## Current Risks

### Contract Drift

Risk: `SKILL.md`, prompt templates, references, and evals can diverge.

Mitigation:

- `evals/check_skill_contract.py` scans hard invariant tokens across surfaces.
- Runtime docs keep detailed contracts in `references/`.
- Behavior changes should update deterministic checks in the same patch.

Residual risk: token checks can miss semantic drift when wording changes but
meaning changes subtly.

### False Completion

Risk: an agent reports success after a narrow command passes but misses a plan
requirement.

Mitigation:

- `lifecycle_outcome=finished` requires `completion_audit.passed=true`.
- `lifecycle_outcome=finished` requires healthy `context_health` with
  `handoff_ready=true` and non-red status.
- The audit must include `prompt_to_artifact_checklist` and
  `verification_evidence`.
- `check_execution.py` verifies this for successful execution fixtures.

Residual risk: the audit can still be low quality if an agent writes vague
checklist items. Future work should add stronger audit-content checks.

### Source Snapshot Staleness

Risk: `context.json` captures source hashes before edits, but source documents
can change later.

Mitigation:

- The snapshot records hashes and basis hash for resume comparison.
- Handoff prompts should point future agents to the snapshot and live files.

Residual risk: there is no automatic mismatch blocker yet when plan/spec/docs
change after snapshot creation.

### Context Health Quality

Risk: `context_health` can be mechanically valid but too optimistic if an agent
marks `green` without recording real next-action or open-question detail.

Mitigation:

- `validate_state.py` checks shape, status enum, handoff readiness, and finished
  outcome consistency.
- `evals/check_skill_contract.py` keeps the context-health contract visible in
  runtime references and prompt export.

Residual risk: semantic quality still depends on agent judgment. Future checks
should compare `next_action` against current task, lifecycle outcome, and open
blockers.

### Hidden Markdown Edge Cases

Risk: Markdown parsing can still miss uncommon syntax forms.

Mitigation:

- Parser blanks fenced code, HTML comments, and indented code.
- Fixtures cover hidden tasks, hidden files, visible parsing after fences, and
  dependency cycles.

Residual risk: nested or malformed Markdown can still surprise a line-based
parser. The parser is intentionally simple and conservative.

### Dirty Worktree Misclassification

Risk: declared `Files` blocks can be incomplete, so a dirty related file might
look unrelated.

Mitigation:

- Dirty classification happens only after plan parsing.
- Mid/high-risk tasks should upgrade risk when implementation touches files
  outside declared blocks.
- Final summaries must report changed files and residual risk.

Residual risk: the executor relies on the plan's file declarations and agent
judgment for indirect dependencies.

### Learning Log Privacy

Risk: durable user-local learning logs can accidentally capture sensitive
context.

Mitigation:

- Event helper rejects secret-like strings and absolute home paths.
- Logging is limited to notable boundaries.
- Full transcripts, long logs, and bulky source contents are forbidden.

Residual risk: no static redactor catches every possible secret. Agents must
still summarize conservatively before appending events.

### Headless Fresh-Process Behavior

Risk: headless `codex exec` may not inherit parent session context, skills, or
assumptions.

Mitigation:

- Headless prompts explicitly bootstrap applicable skills.
- The target process is told not to launch nested `codex exec`.
- Required artifacts live under `.codex-orchestrator/runs/<run_id>/`.

Residual risk: model/tool availability can differ by environment, and fixture
runs can be slower or flaky because they execute real Codex sessions.

## Intentional Deferrals

### No Full OMX Runtime

`oh-my-codex` inspired several contracts, but this skill does not import its
tmux, HUD, hook, or team runtime. Those are product/runtime choices and would
make the skill less portable inside Codex App.

### No Default Parallel Workers

Parallel subagents remain opt-in. This avoids accidental parallel writes,
reduces merge conflict risk, and keeps state ownership simple.

### No Mandatory Full QA Matrix For Every Task

The high-risk matrix applies to high-risk tasks only. Low-risk work should not
pay the cost of adversarial checks that do not change confidence.

### No Plan Authoring Gate

This skill executes a provided `plan=`. It may reject an unsafe or incomplete
plan, but it does not own plan creation. Plan-writing and plan-review skills are
separate workflows.

### No Repository-Local Learning Database

Learning events live under `~/.codex/learning/`, not the target repository. The
repository contains execution state and artifacts, while cross-project process
learning remains user-local.

### No Automatic Version Bump For Docs-Only Changes

Behavior changes must update version/history/package metadata. Pure
maintenance docs may avoid a version bump when they do not change runtime,
prompt export, scripts, or eval behavior.

## Known Gaps Worth Considering

- Add an eval that checks `completion_audit` quality, not only presence.
- Add a resume-time warning when `context.json` source hashes differ from live
  plan/spec/docs files.
- Add a small script that prints the active run summary from
  `.codex-orchestrator/runs/<run_id>/state.json`.
- Add a docs link checker for this package's relative Markdown links.
- Add fixtures for malformed fences, nested comments, and mixed Korean/English
  plan headings.
- Add a redaction test corpus with representative command output patterns.
