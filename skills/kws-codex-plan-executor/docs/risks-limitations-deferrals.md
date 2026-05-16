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
- Terminal `finished` state must include `context_health.last_checked_at` that
  is not older than `timestamps.updated_at`.
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

### Run Health Liveness

Risk: an interrupted executor can leave `meta.json` with `ended_at=null` and no
`final.json`, making an inactive run look active. Conversely, a healthy active
run can look dead if a reporter treats the short-lived helper pid as executor
liveness.

Mitigation:

- `scripts/check_learning_log_health.py` resolves terminal `final.json` first,
  then project-local state, then learning-log metadata.
- `meta.helper_pid` and legacy `meta.pid` are reported only as helper-process
  diagnostics.
- Old inactive project state reports `stale_candidate`, not terminal failure.
- Missing worktrees, missing project state, and dirty active worktrees are
  explicit diagnostics.
- The report is diagnostic and read-only; it does not mutate user-local logs or
  project state.

Residual risk: the reporter cannot prove a Codex session is currently running.
It reports persisted state and git evidence, so a clean worktree with old
active state can still be ambiguous and should be treated as `stale_candidate`.

### Local Environment Preflight

Risk: a fresh isolated worktree may lack ignored machine-local files or install
state that the original checkout needs for baseline verification.

Mitigation:

- Execution guidance requires a post-worktree, pre-baseline local environment
  preflight.
- Android `local.properties`, package manager install state, Docker daemon and
  memory, and intentional `.env` absence are called out explicitly.
- Agents must ask, report, or record an honest substitute before copying ignored
  files.

Residual risk: the policy detects and explains missing local state; it does not
automatically copy files because those files can contain private paths or
secrets.

### Verification Resource Serialization

Risk: parallel verification commands can share mutable outputs and collide,
especially Gradle Test XML/result directories in one worktree.

Mitigation:

- Execution guidance defines resource keys for Gradle, Node, Docker, and
  browser/E2E commands.
- Commands with identical resource keys run serially, and state may record the
  serialization reason.

Residual risk: resource-key serialization is guidance unless a future scheduler
enforces it mechanically.

### Unit Manifest Enforcement Boundary

Risk: the new unit manifest can describe a strict write/tool policy, but Codex
skills cannot intercept every low-level file operation through a custom hook.

Mitigation:

- State validation checks manifest shape and terminal requirements.
- The task contract remains mandatory before edits.
- A post-diff checker compares changed files against contract and manifest
  write globs.

Residual risk: violations are detected by contract and diff review, not blocked
at the instant of every write.

### Event Journal Duplication

Risk: a project-local event journal can look redundant next to state and the
user-local learning log.

Mitigation:

- State remains the source of truth.
- The event journal is replayable project-local execution evidence.
- The learning log remains user-local cross-repo process learning.

Residual risk: agents may over-log routine events unless references and evals
keep the journal vocabulary compact.

### Drift Repair Overreach

Risk: automatic repair could mask real source or state mismatches.

Mitigation:

- Repair mode is explicit.
- Safe repairs are limited to mechanical pointer, timestamp, and sequence
  drift.
- Source hash mismatch, missing manifests, unresolved carried acceptance, and
  journal run-id mismatch are blocking.

Residual risk: future repair types must stay conservative or they can weaken
resume safety.

### Headless Fresh-Process Behavior

Risk: headless `codex exec` may not inherit parent session context, skills, or
assumptions.

Mitigation:

- Headless prompts explicitly bootstrap applicable skills.
- The target process is told not to launch nested `codex exec`.
- Required artifacts live under `.codex-orchestrator/runs/<run_id>/`.

Residual risk: model/tool availability can differ by environment, and fixture
runs can be slower or flaky because they execute real Codex sessions.

### Subagent Record Trust Boundary

Risk: delegated work can be mistaken for reviewed parent work if subagent output
is accepted at face value.

Mitigation:

- Subagent records are opt-in and require `subagents_requested=true`.
- Completed records must include `changed_files` and `review_status`.
- Finished runs cannot carry running or unreviewed subagent records.
- `changed_files` must match declared `write_scope`.
- Overlap with the current task write scope requires an explicit rationale.

Residual risk: the validator proves record shape and obvious scope violations;
the parent executor must still inspect diffs and run final verification.

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

### No SQLite Runtime From GSD-2

GSD-2's SQLite-backed runtime is intentionally not adopted. The executor keeps
per-run JSON state as the authority and uses JSONL only as evidence.

### No Dashboard Or Daemon

The GSD-2 dashboard, daemon, Studio, MCP server, and extension runtime are not
part of this skill. They would increase operational surface area without
improving portable Codex execution.

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
