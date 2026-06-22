# CPE Superpowers Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Superpowers compatibility simulation and update CPE to route approved implementation work through the best verified model.

**Architecture:** Keep CPE's stateful infrastructure, but stop treating it as the only implementation loop. A new audit script scores three models and recommends the thin stateful bridge when current Superpowers contracts are present.

**Tech Stack:** Python 3 standard library, existing CPE eval harness, Markdown contracts.

## Global Constraints

- Do not remove existing CPE prompt, handoff, headless, resume, or state validation behavior.
- Preserve deterministic evals and avoid network-dependent tests.
- Keep the compatibility audit read-only.
- Update skill docs and contract checks with behavior changes.
- Use TDD: add failing eval coverage before implementation.

---

### Task 1: Add Compatibility Eval And Simulation Script

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/audit_superpowers_compatibility.py`
- Create: `skills/kws-codex-plan-executor/evals/check_superpowers_compatibility.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Produces: CLI command `python3 scripts/audit_superpowers_compatibility.py --superpowers-root <path> --skill-root <path>`.
- Produces: JSON fields `recommended_direction`, `winner`, `directions`, `required_contracts`, `explanation`, and `passed`.

- [ ] **Step 1: Write the failing eval**

Create `evals/check_superpowers_compatibility.py` with checks that expect:

```python
payload["recommended_direction"] == "thin_stateful_bridge"
payload["directions"]["thin_stateful_bridge"]["rank"] == 1
payload["directions"]["cpe_primary"]["rank"] > 1
payload["directions"]["superpowers_native_only"]["rank"] > 1
payload["required_contracts"]["brainstorming_hard_gate"] is True
payload["required_contracts"]["writing_plans_header"] is True
payload["required_contracts"]["subagent_review_loop"] is True
payload["required_contracts"]["verification_before_completion"] is True
```

Also create a temporary Superpowers fixture missing one required contract and
assert the script exits non-zero with `passed=false`.

- [ ] **Step 2: Run RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_superpowers_compatibility.py
```

Expected: FAIL because `scripts/audit_superpowers_compatibility.py` does not exist.

- [ ] **Step 3: Implement the script**

Create `scripts/audit_superpowers_compatibility.py`:

- Read required Superpowers `SKILL.md` files from `--superpowers-root`.
- Read CPE `SKILL.md`, `README.md`, and key references from `--skill-root`.
- Detect required current Superpowers contracts.
- Score `cpe_primary`, `superpowers_native_only`, and `thin_stateful_bridge`.
- Choose `thin_stateful_bridge` when required contracts exist and CPE stateful contracts remain present.
- Return non-zero when required Superpowers contracts are missing.

- [ ] **Step 4: Run GREEN**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_superpowers_compatibility.py
```

Expected: PASS.

- [ ] **Step 5: Add the eval to the harness**

Add:

```bash
python3 "$EVAL_DIR/check_superpowers_compatibility.py" >/dev/null
```

to `evals/run.sh`.

### Task 2: Update CPE Contract To Thin Stateful Bridge

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/references/mode-contracts.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/docs/how-it-works.md`
- Modify: `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`

**Interfaces:**
- Consumes: Task 1 JSON recommendation.
- Produces: documented routing rule: Superpowers-native execution is preferred for approved interactive implementation plans; CPE remains stateful bridge for audit, prompt/handoff, headless, resume, and fallback.

- [ ] **Step 1: Update contract docs**

Document:

- Run compatibility audit before choosing the execution route when current
  Superpowers skills are available.
- For approved implementation plans in interactive sessions, prefer
  Superpowers `subagent-driven-development` when supported.
- Use CPE's state/task-packet/audit machinery as the durable bridge and
  fallback, not as a competing duplicate loop.
- Keep CPE-owned modes for prompt, handoff, headless, resume, and inspection.

- [ ] **Step 2: Preserve safety boundaries**

Ensure the docs still state:

- no edits on `main`;
- dedicated worktree before edits;
- task execution contract before edits;
- RED/GREEN evidence for behavior changes;
- completion audit and validation before finished outcome.

### Task 3: Verify And Close

**Files:**
- All files touched in Tasks 1-2.

**Interfaces:**
- Consumes: Task 1-2 changes.
- Produces: verification evidence and final commit.

- [ ] **Step 1: Run focused checks**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_superpowers_compatibility.py
python3 evals/check_skill_contract.py --skill SKILL.md
```

- [ ] **Step 2: Run full checks**

Run:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
```

- [ ] **Step 3: Commit**

Run:

```bash
git status --short --branch --untracked-files=all
git add docs/superpowers/specs/2026-06-23-cpe-superpowers-compatibility-design.md docs/superpowers/plans/2026-06-23-cpe-superpowers-compatibility.md skills/kws-codex-plan-executor
git commit -m "feat(cpe): align execution routing with Superpowers"
git status --short --branch --untracked-files=all
```
