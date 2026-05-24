# Waygent Quality Recovery Context Review Design

- **Date**: 2026-05-24
- **Type**: Brainstorming-approved design spec
- **Status**: Approved design, pending implementation plan
- **Scope**: Waygent intake, task handoff, recovery, completion audit, and
  review evidence

## 1. Goal

Waygent should produce higher-quality work than a direct single-agent
implementation, while using less main-agent context for coordination. The
current failure pattern is the opposite: the coordinator still carries too much
raw context, workers can drift or fail without an integrated recovery loop, and
the runtime can report a finished run even when completion audit evidence is
failed.

This design turns Waygent into an artifact-first controller:

- The main coordinator routes tasks and decisions, not raw file/log payloads.
- Plans that look like Superpowers implementation documents are normalized into
  executable `yaml waygent-task` blocks before worker dispatch.
- Workers get small task packets with explicit file claims, spec slices,
  verification commands, and prior failure evidence.
- Recovery decisions are invoked inside the scheduler, not left as passive
  helper functions.
- A run cannot become `completed` unless the apply-readiness audit is passed.
- Review evidence is required when the run mode requires review.

## 2. Current Evidence

The latest local Waygent run set under the platform run root shows the failure
surface clearly:

- 29 `state.json` files were found.
- 28 runs were `blocked`.
- 1 run was `completed`, but its `completion_audit.status` was `failed`.
- Failure classes observed in event journals:
  - `malformed_result`: 12
  - `verification_failed`: 11
  - `adapter_crashed`: 3
  - `diff_scope_failed`: 3
  - `environment_blocker`: 1
  - `command_not_found`: 1
  - `dependency_missing`: 1

The most recent `memory_second_brain_20260524_081134` run had:

```text
status=completed
lifecycle_outcome=finished
completion_audit.status=failed
```

That state must become impossible. A run with failed audit evidence is not
operator-complete, even when every preceding phase produced some output.

## 3. Design Inputs

### 3.1 Existing Waygent state

Current repo evidence already contains partial building blocks:

- `docs/operations/plan-authoring.md` defines executable
  `yaml waygent-task` shape and safe verification rules.
- `docs/operations/waygent.md` documents deterministic intake recovery that
  writes `artifacts/intake/normalized-plan.md` and
  `artifacts/intake/recovery-report.json`.
- `packages/context-packer/src/specManifest.ts` slices specs by task and falls
  back to the full spec when no mapping exists.
- `packages/context-packer/src/taskPacket.ts` records a packet-level
  `context_budget`, but the status is currently observational.
- `packages/orchestrator/src/recoveryExecutor.ts` exposes
  `nextRecoveryAction`, but the scheduler must use it directly at failure
  boundaries.

### 3.2 External agent-system patterns

The design adopts only patterns that fit Waygent's existing artifact model:

- Claude Code subagents preserve parent context by doing high-volume work in
  their own context and returning a summary. They can also be restricted by
  tool set, model, and worktree isolation:
  <https://code.claude.com/docs/en/sub-agents>
- Codex subagents and non-interactive execution favor structured handoffs,
  explicit workspace state, and machine-readable outputs:
  <https://developers.openai.com/codex/concepts/subagents>
- GitHub Copilot cloud agents use task/session records and reviewable PR
  output as the durable handoff surface:
  <https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent>
- LangGraph handoffs and supervisor patterns separate who owns the next action
  from what context must be passed:
  <https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs>

The key constraint is cost honesty: subagents reduce main-context pressure, but
they do not automatically reduce total token usage. Waygent should measure both
main-context budget and total run cost.

## 4. Stage -1: Intake Auto-Rewrite

### 4.1 Problem

When a user supplies a general Superpowers implementation plan, Waygent can
stop before dispatch with `platform.intake_decision_required` because the plan
does not contain executable `yaml waygent-task` blocks or because a verification
step is classified as unsafe.

The observed operator prompt was:

```text
docs/superpowers/plans/2026-05-24-memory-second-brain.md needs executable
waygent-task YAML blocks, and unsafe verification command candidates must be
replaced with safe commands.
```

This is recoverable without user input when the intended tasks, file claims, and
safe verification commands are inferable.

### 4.2 Behavior

Waygent adds a pre-preflight normalization stage:

1. Parse Superpowers-style task headings, task checklists, file references,
   fenced shell blocks, and explicit verification sections.
2. Build candidate `waygent-task` blocks with:
   - `id`
   - `title`
   - `dependencies`
   - `file_claims`
   - `risk`
   - `verify`
3. Build a package script catalog from local `package.json` files.
4. Normalize verification commands into a safe allowlist.
5. Move implementation-only commands into task instructions, not `verify`.
6. Write:
   - `artifacts/intake/normalized-plan.md`
   - `artifacts/intake/recovery-report.json`
7. Continue into normal preflight when all blockers are resolved.

### 4.3 Safe verification normalization

Allowed verification commands are:

- Declared package scripts such as `npm run build`, `npm run validate`,
  `npm run memory:validate`, and `npm test`.
- Existing repo defaults such as `bun run check`, `bun test <path>`, and
  `git diff --check`.
- Test runners with explicit read-only intent, such as `node --test`.
- Project-native checks such as `./gradlew test` when the project uses Gradle.

Implementation-only commands are removed from `verify` and preserved in task
instructions:

- Dependency install commands: `npm install`, `bun install`, `pnpm install`.
- Mutating generator commands unless the generated files are explicitly owned.
- Formatting commands in write mode.
- `git add`, `git commit`, `graphify update .`, and apply-like mutation steps.

Waygent still stops for user decision on:

- Destructive commands.
- Path escapes outside the source checkout.
- Multiple plausible plan/spec candidates with equal confidence.
- File-claim mismatch that would allow unclaimed writes.
- Source-mutating work with no usable verification command.

### 4.4 Regression fixture

Add a regression fixture based on the `memory_second_brain` plan shape:

- Input: prose Superpowers implementation plan with task headings.
- Expected output: executable `yaml waygent-task` blocks.
- Expected verification commands: `npm test ...`, `npm run memory:validate`,
  `npm run build`, and `npm run validate`.
- Expected decision behavior: no user prompt unless a destructive or ambiguous
  command is present.

## 5. Stage 0: Coordinator Context Budget

### 5.1 Principle

The Waygent coordinator should hold only routing context:

- User goal.
- Current run constraints.
- Task graph.
- File claims and ownership.
- Spec section ids and hashes.
- Worker summaries.
- Blocking evidence references.
- Decisions and review outcomes.

Raw logs, full files, worker transcripts, patch bodies, and large verification
outputs stay in artifacts and Lens projections. They are loaded lazily only by
the specialist that needs them.

### 5.2 Task packet contract

Every worker receives a task packet with:

```json
{
  "task_packet_path": "artifacts/context/task_3.packet.json",
  "task_id": "task_3",
  "owned_files": ["packages/..."],
  "read_only_files": ["docs/..."],
  "allowed_tools": ["read", "edit", "bash:verify-only"],
  "verify_commands": ["bun run check", "bun test packages/..."],
  "spec_sections_used": ["stage_b_recovery_loop_integration"],
  "previous_failure_refs": ["artifacts/recovery/task_3_attempt_1.json"],
  "return_schema": "runway.worker_result.v2"
}
```

The coordinator prompt points to `task_packet_path` and includes a compact
summary. It does not inline the entire packet when the packet is above budget.

### 5.3 Budget gates

Promote packet `context_budget.status` from observational metadata to a gate:

- `green`: dispatch normally.
- `yellow`: dispatch with a warning event and digest raw artifacts first.
- `red`: do not dispatch. Shrink the packet before the worker starts.

Red packet recovery order:

1. Keep only task-owned files and direct dependencies.
2. Replace full logs with verification digests.
3. Replace full spec with mapped spec sections.
4. Add prior failure summaries instead of full transcripts.
5. If still red, create `context_missing` decision evidence.

New events:

- `context.packet_budget_evaluated`
- `handoff.created`
- `subagent.started`
- `subagent.completed`
- `verification.digest_created`
- `runway.spec_slice_fallback_triggered`
- `platform.chain_advanced`

### 5.4 Prompt layout

Provider prompts use a stable static prefix and dynamic payload suffix:

- Static prefix: Waygent worker contract, output schema, tool boundaries,
  policy rules.
- Dynamic suffix: task packet path, task id, spec section ids, prior failure
  summaries, and verification commands.

This improves prompt-cache reuse while keeping task-specific payloads small and
auditable.

## 6. Stage A: Apply-Ready Completion Gate

### 6.1 Invariant

`state.status=completed` and `lifecycle_outcome=finished` are allowed only when
all of the following are true:

- `completion_audit.status=passed`.
- Every required task is verified.
- Every verified task has a valid apply-ready checkpoint reference.
- Combined apply evidence exists and passed.
- Reconciliation passed.
- `completion_audit.residual_risk` is empty.
- Required review evidence exists for the selected run mode.
- Required method evidence exists or has an explicit allowlisted waiver.

The state pair `completed + completion_audit.status=failed` is invalid.

### 6.2 Enforcement points

Enforce the invariant at every terminal write path:

- End of orchestrator run.
- Resume path.
- Verify path that can update readiness.
- Apply path.
- State reconciliation.
- Scenario harness finalization.

If any path attempts to write the invalid pair, Waygent writes:

```text
event_type=platform.invariant_violation
failure_class=terminal_rejected
reason=completed_with_failed_completion_audit
```

The terminal state remains `blocked` or `failed`, not `completed`.

## 7. Stage B: Recovery Loop Integration

### 7.1 Problem

`nextRecoveryAction` exists, but the scheduler must call it as part of the
task lifecycle. Recovery policy that only exists as a utility function does not
improve live run quality.

### 7.2 Failure classes

The integrated recovery loop handles:

- `malformed_result`
- `verification_failed`
- `adapter_crashed`
- `missing_checkpoint`
- `artifact_missing`
- `diff_scope_failed`
- `dependency_missing`
- `environment_blocker`
- `context_missing`
- `insufficient_context`
- `review_changes_requested`

### 7.3 Recovery record

Each recovery attempt appends to `state.recovery[]`:

```json
{
  "task_id": "task_3",
  "failure_class": "malformed_result",
  "action": "retry_with_strict_prompt",
  "attempt_number": 2,
  "max_attempts": 2,
  "automatic": true,
  "prior_summary": "Worker returned prose outside the JSON fence.",
  "result": "succeeded",
  "evidence_refs": ["artifacts/recovery/task_3_attempt_2.json"]
}
```

### 7.4 Retry boundaries

Recovery retries from safe boundaries only:

- Worker malformed output: retry the same task with strict output suffix.
- Verification failure: provide verification digest and retry the task.
- Adapter crash: retry the same provider once, then request decision or switch
  only if policy allows it.
- Missing checkpoint: regenerate checkpoint evidence when the worktree exists;
  otherwise request decision.
- Review changes requested: return to repair and re-review.

Recovery never lowers the Stage A completion gate.

### 7.5 Context-missing ladder

When a worker reports `NEEDS_CONTEXT` or the runtime detects a red packet:

1. Retry with mapped spec slice.
2. Retry with spec slice plus failure evidence.
3. Retry with dependency checkpoint summaries.
4. Retry with full spec fallback and emit
   `runway.spec_slice_fallback_triggered`.
5. Request operator decision.

Full-spec fallback is a controlled exception, not the default handoff mode.

## 8. Stage C: Review And Method Evidence

### 8.1 Superpowers advantages to preserve

Waygent should adopt the parts of the Superpowers / subagent-driven workflow
that improve quality:

- Fresh worker context per task.
- Controller-curated context instead of each subagent reading the full plan.
- Two-stage review:
  1. Spec compliance review.
  2. Code quality review.
- Code-quality review does not run until spec compliance passes.
- Implementer statuses are explicit:
  - `DONE`
  - `DONE_WITH_CONCERNS`
  - `NEEDS_CONTEXT`
  - `BLOCKED`
- `review_changes_requested` returns to repair and re-review until approved or
  blocked by policy.
- Model and reasoning effort scale by task risk.
- A whole-run final review runs after all tasks and before completion audit.

### 8.2 Review packet

Reviewers receive a compact review packet:

```json
{
  "task_id": "task_3",
  "diff_summary_ref": "artifacts/review/task_3.diff-summary.md",
  "task_packet_hash": "sha256:...",
  "spec_sections_used": ["stage_b_recovery_loop_integration"],
  "decisions": ["decision_2"],
  "verification_evidence_refs": ["artifacts/verify/task_3.json"],
  "context_sufficiency": "green"
}
```

Reviewers must decide both:

- Does the implementation satisfy the spec sections it was assigned?
- Was the context sufficient for the worker to make the change safely?

### 8.3 Required evidence

When run mode requires review, `completion_audit.review_evidence` must contain:

- Task-level spec compliance result.
- Task-level code quality result.
- Final whole-run review result.
- Repair/re-review chain when changes were requested.

An empty `review_evidence` blocks apply readiness.

## 9. Quality Model

Waygent quality must be measured against direct implementation on four axes:

| Axis | Direct implementation risk | Waygent target |
|---|---|---|
| Context | Main agent reads everything and loses focus. | Main coordinator reads summaries and evidence refs only. |
| Drift | One agent can silently reinterpret the plan. | File claims, spec sections, and review packets bind every task. |
| Recovery | Failures are manually interpreted in chat. | Scheduler invokes recovery policy and records attempts. |
| Completion | Human may see "done" before audit is valid. | Completion requires passed audit and review evidence. |

Waygent is allowed to cost more total tokens than a direct implementation when
the work is high-risk or parallel, but it must provide better isolation,
evidence, and review quality. For small tightly coupled tasks, the runtime
should prefer single-agent or low-parallelism execution.

## 10. Acceptance Criteria

### 10.1 Unit tests

- Intake rewrite converts a Superpowers-style plan into executable
  `yaml waygent-task` blocks.
- Safe verification normalization keeps declared scripts and rejects mutating
  commands from `verify`.
- Red task-packet budget blocks dispatch and emits shrink/fallback evidence.
- `completed + failed audit` cannot be written by any terminal path.
- Scheduler invokes `nextRecoveryAction` for recoverable task failures.
- Review-required mode blocks apply readiness when `review_evidence` is empty.

### 10.2 Integration scenarios

- A task fails with `malformed_result`, retries with strict output instructions,
  verifies, checkpoints, passes review, and completes with passed audit.
- A task reports `NEEDS_CONTEXT`; Waygent walks the context ladder before asking
  for an operator decision.
- A memory-second-brain-style plan with general Superpowers prose normalizes and
  runs preflight without asking the user for safe verification command edits.
- A run that reaches verified tasks but failed completion audit remains blocked
  and surfaces the exact residual risk.

### 10.3 Verification commands for implementation plan

The implementation plan should use the smallest proving command per task, with
these full-run defaults:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
git diff --check
```

Targeted tests should be added around intake normalization, context packet
budgeting, recovery scheduler integration, completion audit invariants, and
review evidence gating.

## 11. Out Of Scope

- Reintroducing the legacy Python AgentLens tree.
- Replacing the TypeScript Lens projection path.
- Building a new external multi-agent framework.
- Treating subagents as a cost reduction guarantee.
- Making full-spec handoff the default.

## 12. Implementation Planning Notes

The implementation plan should decompose this design into sequential stages:

1. Intake auto-rewrite hardening and fixture.
2. Context packet gate and handoff event surface.
3. Completion invariant enforcement.
4. Scheduler recovery-loop integration.
5. Review evidence requirement and final review packet.

Each stage should include an executable `yaml waygent-task` block with file
claims and safe verification commands. The plan must avoid verification
commands that mutate tracked files.
