# CPE Reliability Improvement Loop Design

## Summary

This design defines a reusable Codex goal prompt for improving
`kws-codex-plan-executor` through a reliability-first, evidence-based loop.

The goal is not to make the skill shorter for its own sake. The goal is to keep
the executor's quality contracts intact while repeatedly measuring real failure
or drag points, selecting one small improvement, validating it with deterministic
checks, and recording what should happen next.

## Objective

Run a long-term improvement loop for the Archive repo's
`kws-codex-plan-executor` skill.

The primary success metric is execution reliability:

- plan execution starts from the right workspace and plan inputs.
- implementation happens in a dedicated non-conflicting worktree.
- task scope is explicit before edits.
- state, context snapshots, context health, and completion audits stay valid.
- blocker and resume behavior is deterministic.
- eval coverage catches regressions before the skill contract changes.

Efficiency improvements are allowed only when they do not weaken these
reliability contracts.

## Design Principles

1. Reliability is the top-level constraint.

   Worktree isolation, task contracts, state/context records, completion audits,
   drift reconciliation, prompt cache audits, Graphify audits, and required
   skill/TDD gates must not be removed or softened to reduce prompt size.

2. Improve only from evidence.

   Each round must begin with current repository status, relevant diffs, and a
   baseline check. Improvements should address observed failures, ambiguity,
   schema drift, repeated verification drag, context overpacking, or missing
   audit evidence.

3. Keep each round small.

   A round may propose multiple candidates, but it should select at most one
   low-risk improvement to implement. Broader rewrites require a separate
   design and plan.

4. Preserve existing work.

   The Archive checkout often contains active changes. Each round must inspect
   the current diff before selecting scope and must not revert unrelated user
   work.

## Prompt Structure

The Codex goal prompt has five sections:

- `Goal`: a single reliability-first objective.
- `Context`: workspace, target skill, required docs, and repository rules.
- `Non-negotiable boundaries`: CPE contracts that cannot be weakened.
- `Loop`: baseline, classify, select, implement, verify, and record.
- `Final response format`: a short evidence-oriented report.

## Codex Goal Prompt

```text
Goal: Run a long-term reliability-first improvement loop for the Archive repo's `kws-codex-plan-executor` skill.

Context:
- Workspace: `/Users/kws/source/private/Archive`
- Primary target: `skills/kws-codex-plan-executor/`
- Follow root `AGENTS.md`.
- Before changing the skill, read:
  - `skills/kws-codex-plan-executor/SKILL.md`
  - `skills/kws-codex-plan-executor/references/change-protocol.md`
  - `skills/kws-codex-plan-executor/README.md`
  - `skills/kws-codex-plan-executor/ARCHITECTURE.md`
  - relevant experiment docs under `skills/kws-codex-plan-executor/docs/experiments/`
- Preserve existing user changes. Start with `git status --short --branch --untracked-files=all` and inspect any existing diff before deciding scope.

Primary objective:
Improve the execution reliability of `kws-codex-plan-executor` through a repeatable, evidence-based loop. Reliability means plan execution, resume behavior, state/context integrity, worktree isolation, blocker handling, completion audit, and deterministic eval coverage. Efficiency improvements are allowed only when they do not weaken reliability contracts.

Non-negotiable boundaries:
- Do not remove or weaken CPE core contracts:
  - 5-line `TASK EXECUTION CONTRACT`
  - dedicated non-conflicting worktree under `~/.codex/worktrees/`
  - orchestration state under `~/.codex/orchestrator/`
  - dirty-worktree classification
  - task file-scope enforcement
  - context snapshot and context health
  - completion audit
  - drift reconciliation
  - prompt cache audit
  - Graphify audit when applicable
  - subagent dispatch evidence when applicable
  - required skill/TDD gates for implementation work
- Do not use `--dangerously-bypass-approvals-and-sandbox`.
- Do not recreate legacy `components/agentlens/`.
- Do not route new active work through historical AgentRunway naming except for read-compatibility docs/code.
- Do not broadly rewrite `SKILL.md` for brevity unless deterministic tests prove the removed text is redundant with another enforced contract.
- Do not inspect eval fixture expected values or harness metadata when acting as the target executor.

Loop for each improvement round:
1. Baseline:
   - Inspect git status and current diff.
   - Run the smallest relevant deterministic checks first.
   - Prefer:
     - `cd skills/kws-codex-plan-executor && bash evals/run.sh`
     - `cd skills/kws-codex-plan-executor && python3 -m py_compile scripts/*.py evals/*.py`
     - `cd skills/kws-codex-plan-executor && bash -n evals/run.sh`
     - repo root: `git diff --check`
   - If the whole suite is too expensive, run a focused subset and clearly record why.

2. Classify:
   - Identify reliability failures, flaky behavior, ambiguous blockers, state/schema drift, resume ambiguity, missing evidence, or unnecessary execution drag.
   - Separate reliability issues from pure cost/context-size issues.
   - Do not patch until a concrete root cause or measurable improvement target is identified.

3. Select:
   - Propose at most 1-3 candidate improvements.
   - Choose one low-risk improvement for the current round.
   - The chosen improvement must have explicit acceptance evidence.

4. Implement:
   - Follow `references/change-protocol.md`.
   - Add or update deterministic eval coverage before or alongside behavior changes.
   - Keep edits scoped to CPE files and directly related docs.
   - Update `HISTORY.md`, `README.md`, `ARCHITECTURE.md`, references, templates, and baselines when the behavior contract changes.

5. Verify:
   - Re-run the focused failing checks.
   - Re-run broader CPE evals if behavior or schema changed.
   - Run `python3 -m py_compile scripts/*.py evals/*.py`.
   - Run `bash -n evals/run.sh`.
   - Run `git diff --check`.
   - If repository instructions require Graphify after meaningful code or documentation structure changes, run `graphify update .` and record whether tracked or ignored outputs changed.

6. Record:
   - Summarize measured baseline, chosen improvement, files changed, verification evidence, and residual risk.
   - Add a short next-round backlog with 1-3 evidence-backed candidates.
   - Do not claim the run is finished if validation is failing unless the failure is explicitly documented as an external blocker or honest substitute.

Final response format:
- Baseline checked:
- Improvement selected:
- Changes made:
- Verification:
- Residual risk:
- Next round candidates:
```

## Expected Use

Use this prompt when starting a dedicated Codex goal whose job is to keep
improving CPE over multiple rounds. It is appropriate when the desired outcome
is operational maturity, not a single feature.

The first round should usually be diagnostic-heavy. If the checkout already has
active CPE changes, the agent should classify those changes before suggesting
new ones.

## Out Of Scope

- Rewriting CPE into a different orchestrator.
- Recreating the legacy Python AgentLens tree.
- Moving active Waygent work back to AgentRunway naming.
- Removing required safety gates for prompt brevity.
- Treating token reduction as success when reliability evidence gets weaker.

## Review Checklist

- The prompt makes reliability the primary objective.
- The prompt preserves existing CPE contracts.
- The loop requires baseline evidence before implementation.
- The loop limits each round to one low-risk improvement.
- The output format forces verification and residual risk reporting.
