# CPE Reliability Improvement Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap round 001 of the CPE reliability improvement loop by recording baseline evidence, classifying reliability risks, and producing a bounded next-round backlog without changing CPE behavior.

**Architecture:** This plan implements the approved reliability-loop design as an operational documentation pass. Round 001 is deliberately diagnostic-only: it creates a durable evidence note, runs deterministic checks, records command status output, and decides whether a later behavior-change plan is justified. No CPE script, eval, prompt, state-schema, or runtime contract is changed by this plan.

**Tech Stack:** Markdown docs, existing shell verification commands, existing `skills/kws-codex-plan-executor` eval harness, Git, Graphify freshness inspection when relevant.

---

## Source Design

- Spec: `docs/superpowers/specs/2026-05-31-cpe-reliability-improvement-loop-design.md`
- Target skill: `skills/kws-codex-plan-executor/`
- Change protocol: `skills/kws-codex-plan-executor/references/change-protocol.md`

## Scope

Included:

- Create a round-001 evidence note.
- Run and record deterministic CPE baseline checks.
- Classify observed reliability risks.
- Produce a next-round backlog with at most three evidence-backed candidates.

Excluded:

- Changing CPE behavior.
- Editing CPE scripts, evals, prompt templates, state schema, or baselines.
- Updating Graphify output.
- Rewriting `SKILL.md` for brevity.
- Implementing a selected reliability fix.

If the baseline reveals a concrete reliability defect, this plan records it and
stops. A separate implementation plan should then target that exact defect.

## File Structure

Create:

- `skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md`
  - Records repository state, baseline command results, reliability findings,
    residual risk, and next-round candidates.

Modify:

- No existing files.

Do not modify:

- `skills/kws-codex-plan-executor/SKILL.md`
- `skills/kws-codex-plan-executor/scripts/`
- `skills/kws-codex-plan-executor/evals/`
- `skills/kws-codex-plan-executor/templates/`
- `skills/kws-codex-plan-executor/references/`
- `skills/kws-codex-plan-executor/evals/baselines/`
- `graphify-out/`
- `components/agentlens/`
- Runtime state directories such as `.agentlens/`, `.codex-orchestrator/`,
  `.orchestrator/`, `.superpowers/`, `~/.codex/orchestrator/`, or
  `~/.codex/worktrees/`.

## Task 1: Create The Round-001 Evidence Note

**Files:**

- Create: `skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md`

- [ ] **Step 1: Inspect repository status**

Run from the repository root:

```bash
git status --short --branch --untracked-files=all
```

Expected: exits 0 and prints the current branch plus changed files, if any.

- [ ] **Step 2: Inspect current diff**

Run from the repository root:

```bash
git diff --stat
```

Expected: exits 0. If there are no unstaged changes, the command prints no
file-stat lines.

- [ ] **Step 3: Create the note with observed status and diff**

Create `skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md`.
Use the exact headings below. Fill `Current Worktree State` with the literal
output from Step 1. Fill `Existing Diff Summary` with either the literal output
from Step 2 or the sentence `No unstaged diff was present before round 001.`

````markdown
# CPE Reliability Loop Round 001

## Objective

Run the first diagnostic round of the CPE reliability improvement loop. This
round records baseline evidence and next-round candidates without changing CPE
behavior.

## Current Worktree State

```text
```

## Existing Diff Summary

```text
```

## Baseline Commands

| Command | Status | Evidence |
| --- | --- | --- |
| `cd skills/kws-codex-plan-executor && bash evals/run.sh` | not-run | Baseline command is scheduled for Task 2. |
| `cd skills/kws-codex-plan-executor && python3 -m py_compile scripts/*.py evals/*.py` | not-run | Baseline command is scheduled for Task 2. |
| `cd skills/kws-codex-plan-executor && bash -n evals/run.sh` | not-run | Baseline command is scheduled for Task 2. |
| `git diff --check` | not-run | Baseline command is scheduled for Task 2. |

## Reliability Findings

| Finding | Evidence | Severity | Recommended Next Step |
| --- | --- | --- | --- |
| No finding recorded yet. | Baseline checks have not run yet. | none | Run Task 2. |

## Residual Risk

- Residual risk has not been assessed because baseline checks have not run yet.

## Next Round Candidates

| Candidate | Evidence | Why Next Round |
| --- | --- | --- |
| No candidate recorded yet. | Baseline checks have not run yet. | Run Task 2 before selecting candidates. |
````

- [ ] **Step 4: Verify note formatting**

Run from the repository root:

```bash
git diff --check -- skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md
```

Expected: exits 0 with no output.

- [ ] **Step 5: Commit the note scaffold**

Run from the repository root:

```bash
git add skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md
git commit -m "docs(cpe): start reliability loop round"
```

Expected: commit succeeds and stages only the round-001 note.

## Task 2: Run Baseline Checks

**Files:**

- Modify: `skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md`

- [ ] **Step 1: Run the deterministic CPE eval suite**

Run:

```bash
cd skills/kws-codex-plan-executor && bash evals/run.sh
```

Expected for a healthy baseline: exits 0. If it passes, record:

```markdown
| `cd skills/kws-codex-plan-executor && bash evals/run.sh` | pass | All deterministic CPE evals passed. |
```

If it fails, record the failing eval name and the shortest useful error line.

- [ ] **Step 2: Run Python compile verification**

Run:

```bash
cd skills/kws-codex-plan-executor && python3 -m py_compile scripts/*.py evals/*.py
```

Expected for a healthy baseline: exits 0. If it passes, record:

```markdown
| `cd skills/kws-codex-plan-executor && python3 -m py_compile scripts/*.py evals/*.py` | pass | Python scripts and evals compiled. |
```

If it fails, record the exact Python file and error message.

- [ ] **Step 3: Run shell syntax verification**

Run:

```bash
cd skills/kws-codex-plan-executor && bash -n evals/run.sh
```

Expected for a healthy baseline: exits 0. If it passes, record:

```markdown
| `cd skills/kws-codex-plan-executor && bash -n evals/run.sh` | pass | Eval shell harness syntax is valid. |
```

If it fails, record the exact shell syntax error.

- [ ] **Step 4: Run patch hygiene**

Run from the repository root:

```bash
git diff --check
```

Expected for a healthy baseline: exits 0. If it passes, record:

```markdown
| `git diff --check` | pass | No whitespace or conflict-marker errors. |
```

If it fails, record each reported path and line.

- [ ] **Step 5: Replace the baseline command table**

In `ROUND-001.md`, replace the four `not-run` rows with the concrete status
rows from Steps 1-4. Allowed status values are `pass`, `fail`, and
`skipped-with-reason`.

- [ ] **Step 6: Commit baseline evidence**

Run from the repository root:

```bash
git add skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md
git commit -m "docs(cpe): record reliability loop baseline"
```

Expected: commit succeeds and stages only the round-001 note.

## Task 3: Classify Reliability Findings

**Files:**

- Modify: `skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md`

- [ ] **Step 1: Classify baseline result**

Use this severity scale:

```text
critical: CPE execution contract can report success with invalid state, invalid worktree use, or missing completion evidence.
high: deterministic evals fail, resume/blocker behavior is ambiguous, or required state/context evidence can drift silently.
medium: verification is valid but incomplete, expensive, or unclear for operators.
low: documentation wording or next-round observability can improve without changing behavior.
none: no reliability concern found in this round.
```

- [ ] **Step 2: Update findings when all baseline checks pass**

If all four baseline commands pass, replace the default finding row with:

```markdown
| No baseline reliability failure found. | `evals/run.sh`, `py_compile`, `bash -n`, and `git diff --check` passed. | none | Keep round 001 diagnostic-only and use next round for targeted stress scenarios. |
```

- [ ] **Step 3: Update findings when any baseline check fails**

If any baseline command fails, add one row per failure using this format:

```markdown
| Deterministic CPE eval failure. | `bash evals/run.sh` failed in `check_execution.py` with state validation error. | high | Create a focused implementation plan for the failing state validation path. |
```

Use the real command, eval name, and error summary from Task 2.

- [ ] **Step 4: Update residual risk**

If all baseline checks pass, set:

```markdown
## Residual Risk

- Round 001 did not run live CPE execution, resume, or subagent dispatch. The
  next round should add a targeted stress scenario instead of changing behavior
  from a clean baseline alone.
```

If any baseline check fails, set:

```markdown
## Residual Risk

- Round 001 found at least one baseline failure. CPE behavior should not be
  changed broadly until the failing command has a focused root-cause plan.
```

- [ ] **Step 5: Commit findings**

Run from the repository root:

```bash
git add skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md
git commit -m "docs(cpe): classify reliability loop findings"
```

Expected: commit succeeds and stages only the round-001 note.

## Task 4: Produce Next-Round Backlog

**Files:**

- Modify: `skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md`

- [ ] **Step 1: Add backlog when baseline checks pass**

If all baseline checks pass, replace `Next Round Candidates` with:

```markdown
## Next Round Candidates

| Candidate | Evidence | Why Next Round |
| --- | --- | --- |
| Add a replay fixture for ambiguous `resume=latest` selection. | Round 001 baseline passed, so the next useful reliability signal should stress a known stop-rule boundary rather than change production behavior. | Requires a focused fixture/eval plan. |
| Add a fixture that verifies finished runs cannot retain unreviewed subagent records. | The SKILL contract requires reviewed completed subagent records before finished outcome. | Requires inspecting current `check_execution.py` coverage before editing. |
| Add an operator-facing failure summary check for completion audit blockers. | Round 001 did not test final-report clarity when validation fails. | Requires a focused expected-output fixture. |
```

- [ ] **Step 2: Add backlog when baseline checks fail**

If any baseline check fails, replace `Next Round Candidates` with one to three
rows derived from the failures. Use this exact style:

```markdown
## Next Round Candidates

| Candidate | Evidence | Why Next Round |
| --- | --- | --- |
| Fix failing state validation baseline. | `bash evals/run.sh` failed in `check_state_schema.py` with a missing required field. | Needs a focused implementation plan and RED/GREEN eval workflow. |
```

- [ ] **Step 3: Verify note formatting**

Run from the repository root:

```bash
git diff --check -- skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md
```

Expected: exits 0 with no output.

- [ ] **Step 4: Commit next-round backlog**

Run from the repository root:

```bash
git add skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md
git commit -m "docs(cpe): define reliability loop backlog"
```

Expected: commit succeeds and stages only the round-001 note.

## Task 5: Final Verification And Report

**Files:**

- No file changes required unless final status reveals the round note was not
  committed.

- [ ] **Step 1: Verify final patch hygiene**

Run from the repository root:

```bash
git diff --check
```

Expected: exits 0.

- [ ] **Step 2: Inspect final status**

Run from the repository root:

```bash
git status --short --branch --untracked-files=all
```

Expected: exits 0. The only changes from this plan should be committed
`ROUND-001.md` changes. Any remaining files should be reported as pre-existing
or unrelated.

- [ ] **Step 3: Final response**

Respond with this shape. Copy command statuses from the `Baseline Commands`
table in `ROUND-001.md`; use `pass`, `fail`, or `skipped-with-reason`.

```markdown
Baseline checked:
- `cd skills/kws-codex-plan-executor && bash evals/run.sh`: copy status from `ROUND-001.md`
- `cd skills/kws-codex-plan-executor && python3 -m py_compile scripts/*.py evals/*.py`: copy status from `ROUND-001.md`
- `cd skills/kws-codex-plan-executor && bash -n evals/run.sh`: copy status from `ROUND-001.md`
- `git diff --check`: copy status from `ROUND-001.md`

Improvement selected:
- Diagnostic-only round. No CPE behavior change was selected in this plan.

Changes made:
- Created `skills/kws-codex-plan-executor/docs/experiments/reliability-loop/ROUND-001.md`.

Verification:
- `git diff --check`: copy final status from Task 5 Step 1

Residual risk:
- Summarize the residual risk recorded in `ROUND-001.md`.

Next round candidates:
- List the one to three candidates recorded in `ROUND-001.md`.
```

Do not claim the long-term reliability loop is complete. Claim only that round
001 was bootstrapped and recorded.
