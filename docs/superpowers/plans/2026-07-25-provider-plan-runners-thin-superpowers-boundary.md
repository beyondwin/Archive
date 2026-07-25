# Provider Plan Runners Thin Superpowers Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Codex and Claude plan runners small durability wrappers that
hand approved documents to Superpowers unchanged, preserve external execution
facts, and stop reproducing task, review, and fix-loop meaning in Python.

**Architecture:** The runner snapshots readable UTF-8 specs and plans in CLI
order, starts one fresh provider root session per plan, and lets installed
Superpowers own the plan from task discovery through final review. The runner
records only immutable inputs, Git/worktree identity, provider session/process
facts, exact handoff verification receipts, ordered plan handoffs, and terminal
status. Codex and Claude keep independent production implementations and share
only a root version 2 outcome fixture.

**Tech Stack:** Existing uv-managed normal-GIL CPython 3.13 standard-library
runners, Git CLI, Codex JSONL, Claude stream-json, `unittest`, and the existing
Bun repository verifier.

## Global Constraints

- Design source:
  `docs/superpowers/specs/2026-07-25-provider-plan-runners-thin-superpowers-boundary-design.md`.
- Execute this plan directly with Superpowers. Do not ask either runner to
  rewrite itself.
- Do not add a document reviewer, plan parser, task enumerator, finding parser,
  review database, reviewer rubric, or Python implementation-plan interpreter.
- Input validation is limited to safe absolute path handling, readable UTF-8,
  byte length, SHA-256, preserved CLI order, and immutable snapshots.
- Pass approved specs and the current plan to Superpowers unchanged. Earlier
  plans pass forward only as immutable handoffs. The final plan controller gets
  all immutable specs and plans as final-review requirements.
- Superpowers exclusively owns its `progress.md`, task status, implementers,
  TDD, task review, fix rounds, final whole-branch review, and final-review fix
  wave.
- Runner state, packets, provider results, recovery state, and active artifacts
  contain no task IDs/status, findings, severity, obligations, finalization
  controller, or review-fix controller.
- Keep provider result shape minimal:
  `status`, `head_commit`, `summary`, `verification_set_digest`, `blocker`.
- Provider status is only `implemented` or `blocked`. Transport and runtime
  failures remain runner-observed facts.
- Keep one helper declaration path and one helper execution path. Do not create
  separate public APIs for focused, plan, final, review, and retry verification.
- Focused task tests stay inside Superpowers and are not copied into runner
  evidence. The provider declares only the small exact handoff verification set
  needed to accept a plan.
- At the final plan, the helper builds the final exact command union from
  already sealed plan declarations and executes duplicate argv only once at the
  final HEAD.
- New runs use `format_version=2` and `contract_version=2`. Version 1 is
  inspect-only; version 2 never resumes, repairs, migrates, archives, retires,
  deletes, or reinterprets version 1 state.
- Do not add a new version 1 migration or cutover Python program. Use the
  existing runner's read-only `inspect` surface and an operator decision at the
  actual cutover gate.
- Remove `unsealed-provider-partial` from the active version 2 Codex CLI. Keep
  only exact volatile Codex turn-ref repair.
- The integration policy is always `keep`. Never merge, push, create a pull
  request, discard, delete, or clean the product worktree.
- Codex continues to use `--ignore-rules`; public wording must say execpolicy
  rules are not applied. A dirty checkpoint detects drift and is not a backup.
- Keep Codex and Claude production Python independent. Do not create a shared
  runtime module or import the root fixture from production.
- Preserve unrelated user changes, including the three untracked
  `docs/operations/2026-07-24-cpe-*.md` files observed before this plan.
- Use `apply_patch` for tracked edits. Do not modify `.codex/rules/`, provider
  credentials, global skills, or existing run/worktree contents.
- Use focused RED/GREEN tests during tasks. Do not run full deterministic evals
  per task.
- Run exactly two provider-backed canaries at the final candidate: multi-plan
  ownership and interruption/resume.
- Run the repository's canonical
  `bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD` once at the
  final HEAD. Do not separately repeat the full provider evals and parity gate.
- Superpowers performs the implementation reviews required by its own
  workflow. Do not dispatch an extra Python-driven or runner-driven final
  review after Superpowers completes it.

---

## Minimal Runtime Contract

The version 2 packet contains only:

```json
{
  "packet_version": 2,
  "mode": "implementation",
  "run_id": "run identity",
  "worktree": "/absolute/assigned/worktree",
  "branch": "assigned branch",
  "starting_commit": "full Git SHA",
  "current_head": "full Git SHA",
  "specifications": [
    {"snapshot_path": "/absolute/spec snapshot", "sha256": "digest"}
  ],
  "current_plan": {
    "index": 0,
    "total": 2,
    "snapshot_path": "/absolute/current plan snapshot",
    "sha256": "digest"
  },
  "implemented_plan_handoffs": [],
  "prior_verification_sets": [],
  "is_final_plan": false,
  "final_review_requirements": null,
  "checkpoint_revision": 1,
  "recovery_context": {},
  "helper": {},
  "integration_policy": "keep"
}
```

Only the final plan packet replaces `final_review_requirements=null` with all
ordered immutable spec and plan snapshots. Earlier packets never expose future
plan paths.

The provider returns only:

```json
{
  "status": "implemented",
  "head_commit": "0123456789abcdef0123456789abcdef01234567",
  "summary": "Bounded handoff summary.",
  "verification_set_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "blocker": null
}
```

or:

```json
{
  "status": "blocked",
  "head_commit": "0123456789abcdef0123456789abcdef01234567",
  "summary": "External authority is required.",
  "verification_set_digest": null,
  "blocker": {
    "kind": "external_authority_required",
    "detail": "Bounded explanation."
  }
}
```

The helper keeps only these semantic operations:

```text
declare_verification
run_verification
```

`declare_verification` seals the current plan's exact commands or a nonempty
no-applicable rationale. For an intermediate plan it returns that plan-set
digest. For the final plan it also derives the ordered, duplicate-free run
union from all sealed plan sets and returns the run-set digest as the accepted
digest. `run_verification` executes a command by accepted digest and index.
`record_liveness` may remain as transport telemetry, but it is not progress.

## File Map

No new production Python module is planned.

Modify the existing files that already own each boundary:

```text
skills/kws-codex-plan-runner/
├── AGENTS.md
├── CHANGELOG.md
├── README.md
├── SKILL.md
├── evals/
│   ├── fake_codex.py
│   ├── test_contracts.py
│   ├── test_engine.py
│   ├── test_evidence.py
│   ├── test_helper.py
│   ├── test_provider.py
│   ├── test_recovery.py
│   ├── test_skill_contract.py
│   └── test_storage.py
├── scripts/
│   ├── runner.py
│   └── plan_runner/
│       ├── contracts.py
│       ├── engine.py
│       ├── evidence.py
│       ├── helper.py
│       ├── provider.py
│       ├── recovery.py
│       └── storage.py
└── templates/plan-result.schema.json

skills/kws-claude-plan-runner/
├── AGENTS.md
├── CHANGELOG.md
├── README.md
├── SKILL.md
├── evals/
│   ├── fake_claude.py
│   ├── test_contracts.py
│   ├── test_engine.py
│   ├── test_evidence.py
│   ├── test_helper.py
│   ├── test_independence.py
│   ├── test_provider.py
│   ├── test_recovery.py
│   ├── test_skill_contract.py
│   └── test_storage.py
├── scripts/
│   ├── runner.py
│   └── plan_runner/
│       ├── contracts.py
│       ├── engine.py
│       ├── evidence.py
│       ├── helper.py
│       ├── provider.py
│       ├── recovery.py
│       └── storage.py
└── templates/plan-result.schema.json

scripts/agent/
├── check-plan-runner-parity.py
├── plan-runner-live-canary.py
├── test_check_plan_runner_parity.py
├── test_plan_runner_live_canary.py
└── fixtures/
    ├── plan-runner-contract-v1.json
    └── plan-runner-parity-v1.json
```

Update the two existing root fixture files in place to version 2 after retaining
their version 1 contents in Git history. Do not create a second fixture family
or a migration fixture framework.

Use the managed interpreter only for focused tests:

```bash
cd /Users/kws/source/private/Archive
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
```

## Task 1: Codex Ownership Cut

**Files:**

- Modify: `skills/kws-codex-plan-runner/templates/plan-result.schema.json`
- Remove:
  `skills/kws-codex-plan-runner/templates/finalization-result.schema.json`
- Remove:
  `skills/kws-codex-plan-runner/templates/final-verification-set.schema.json`
- Modify: `skills/kws-codex-plan-runner/scripts/runner.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/evidence.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/helper.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/provider.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/recovery.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py`
- Modify: the matching Codex focused tests and `fake_codex.py`

**Produces:**

- version 2 state with no `task_ledger` or `finalization`;
- plan records with `handoff_digest: str | None`;
- minimal plan result schema;
- one implementation controller per plan and no other provider mode;
- helper-sealed plan verification and final run union;
- version 1 read-only inspect and precise execution rejection;
- public Superpowers preflight limited to `SKILL.md`, `sdd-workspace`,
  `task-brief`, and `review-package`.

- [ ] **Step 1: Write the narrow RED tests**

Add tests that prove observable boundary behavior:

```python
def test_two_plans_need_only_two_root_controllers(self):
    code = self.run_two_plan_success()
    self.assertEqual(code, ExitCode.READY)
    self.assertEqual(
        [packet["mode"] for packet in self.packets],
        ["implementation", "implementation"],
    )

def test_runner_never_stores_superpowers_workflow_meaning(self):
    state = self.state()
    self.assertNotIn("task_ledger", state)
    self.assertNotIn("finalization", state)
    self.assertTrue(all("task_ledger" not in packet for packet in self.packets))
    self.assertFalse(any(
        session["mode"] in {"finalization", "final_review_fix"}
        for session in state["sessions"]
    ))
```

Also prove:

- two consecutive plans may both use `Task 1` and `Task 2` without any label
  entering state or packets;
- intermediate acceptance requires clean exact HEAD, ancestry, identity,
  protected refs, declared set, and successful receipts;
- final acceptance requires the helper-derived run union at final HEAD;
- a HEAD change invalidates receipts without launching a review controller;
- version 1 inspect does not change state bytes or metadata;
- version 1 resume/repair returns `legacy_contract_requires_v1_runner`;
- private prompt/template filename removal does not block preflight;
- missing one of the four public Superpowers capabilities blocks precisely.

- [ ] **Step 2: Run the selected tests and verify RED**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-runner
"$PYTHON_313" -m unittest \
  evals.test_contracts.ContractVocabularyTest.test_runtime_matches_versioned_test_contract \
  evals.test_storage.StateStoreTest.test_version_two_state_contains_no_superpowers_workflow_state \
  evals.test_helper.HelperProtocolTest.test_plan_and_run_verification_use_one_helper_path \
  evals.test_provider.CodexProviderTest.test_private_sdd_layout_is_not_capability_contract \
  evals.test_recovery.RecoveryPolicyTest.test_fixed_resume_then_fresh_then_exhaustion \
  evals.test_engine.EngineTest.test_two_plans_use_two_root_controllers_and_final_plan_closes_run \
  evals.test_engine.EngineTest.test_version_one_is_inspect_only \
  -v
```

Expected: failures point to the old task ledger, finalization path, review-fix
mode, private prompt preflight, and task/finding-based recovery.

- [ ] **Step 3: Make the smallest production change**

Perform deletions before adding replacements:

1. remove task fields, task validators, finding fields, finding validators,
   finalization state, finalization/fix prompts, packets, sessions, attempts,
   and result schema;
2. change both version constants to `2`, add only `handoff_digest` to plan
   state, and keep version 1 inspection shallow and read-only;
3. replace helper `declare_final_set`/`verify_final` and runner-owned focused
   evidence with `declare_verification`/`run_verification`;
4. let the helper derive the final union from referenced plan declarations;
5. let `_accept_implemented` close the final run directly;
6. reduce recovery progress to Git tree digest, successful receipt digests, and
   plan handoff digests;
7. allow one healthy explicit resume, then one fresh session, then exhaust the
   unchanged failure signature;
8. remove `unsealed-provider-partial` from the active CLI;
9. reduce `_REQUIRED_SDD_PATHS` to the four public capabilities.

Do not add a new module, document parser, result interpreter, review adapter,
or migration engine.

- [ ] **Step 4: Run Codex focused GREEN tests**

Run the same command from Step 2.

Expected: all selected tests pass without a real provider.

- [ ] **Step 5: Commit**

```bash
cd /Users/kws/source/private/Archive
git add -- \
  skills/kws-codex-plan-runner/templates/plan-result.schema.json \
  skills/kws-codex-plan-runner/templates/finalization-result.schema.json \
  skills/kws-codex-plan-runner/templates/final-verification-set.schema.json \
  skills/kws-codex-plan-runner/scripts/runner.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/evidence.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/helper.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/provider.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/recovery.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-codex-plan-runner/evals/fake_codex.py \
  skills/kws-codex-plan-runner/evals/test_contracts.py \
  skills/kws-codex-plan-runner/evals/test_storage.py \
  skills/kws-codex-plan-runner/evals/test_evidence.py \
  skills/kws-codex-plan-runner/evals/test_helper.py \
  skills/kws-codex-plan-runner/evals/test_provider.py \
  skills/kws-codex-plan-runner/evals/test_recovery.py \
  skills/kws-codex-plan-runner/evals/test_engine.py
git commit -m "refactor(codex-runner): enforce thin superpowers boundary"
```

## Task 2: Claude Independent Parity Cut

**Files:**

- Modify/remove the Claude equivalents listed in Task 1.
- Modify: `skills/kws-claude-plan-runner/evals/test_independence.py`
- Modify: `skills/kws-claude-plan-runner/evals/fake_claude.py`

**Produces:**

- the same version 2 external behavior as Codex;
- no shared production runtime;
- preserved Claude UUID, stream-json, nested-session scrubbing, and
  `--disallowedTools` behavior.

- [ ] **Step 1: Write Claude RED tests**

Use the Task 1 outcome assertions against Claude and add:

```python
def test_claude_runtime_remains_independent(self):
    for path in CLAUDE_PRODUCTION_PYTHON:
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("kws-codex-plan-runner", source)
        self.assertNotIn("scripts/agent/fixtures", source)

def test_each_plan_gets_one_fresh_uuid(self):
    self.run_two_plan_success()
    sessions = [
        item["session_id"]
        for item in self.state()["sessions"]
        if item["mode"] == "implementation"
    ]
    self.assertEqual(len(sessions), 2)
    self.assertEqual(len(set(sessions)), 2)
```

Prove the same minimal result, final run union, v1 inspect-only boundary, and
Git/receipt/handoff recovery facts independently.

- [ ] **Step 2: Run the selected tests and verify RED**

```bash
cd /Users/kws/source/private/Archive/skills/kws-claude-plan-runner
"$PYTHON_313" -m unittest \
  evals.test_contracts.ContractPrimitivesTest.test_runtime_matches_versioned_test_contract \
  evals.test_storage.DurableClaudeStateTest.test_version_two_state_contains_no_superpowers_workflow_state \
  evals.test_helper.ParentHelperTest.test_plan_and_run_verification_use_one_helper_path \
  evals.test_recovery.RecoveryBehaviorTest.test_fixed_resume_then_fresh_then_exhaustion \
  evals.test_engine.EngineTest.test_two_plans_use_two_root_controllers_and_final_plan_closes_run \
  evals.test_engine.EngineTest.test_version_one_is_inspect_only \
  evals.test_independence.IndependentRuntimeTest.test_runtime_imports_no_codex_or_root_contract_module \
  -v
```

Expected: failures expose the Claude task/finalization replica and old recovery
facts.

- [ ] **Step 3: Apply the same external semantics independently**

Use the existing Claude files and provider transport. Do not copy/import Codex
production code. Remove the same workflow replicas, keep the same two helper
semantics, and preserve Claude-native session behavior.

- [ ] **Step 4: Run Claude focused GREEN tests**

Run the same command from Step 2.

Expected: all selected tests pass with no Codex or root-fixture production
dependency.

- [ ] **Step 5: Commit**

```bash
cd /Users/kws/source/private/Archive
git add -- \
  skills/kws-claude-plan-runner/templates/plan-result.schema.json \
  skills/kws-claude-plan-runner/templates/finalization-result.schema.json \
  skills/kws-claude-plan-runner/templates/final-verification-set.schema.json \
  skills/kws-claude-plan-runner/scripts/runner.py \
  skills/kws-claude-plan-runner/scripts/plan_runner/contracts.py \
  skills/kws-claude-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-claude-plan-runner/scripts/plan_runner/evidence.py \
  skills/kws-claude-plan-runner/scripts/plan_runner/helper.py \
  skills/kws-claude-plan-runner/scripts/plan_runner/provider.py \
  skills/kws-claude-plan-runner/scripts/plan_runner/recovery.py \
  skills/kws-claude-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-claude-plan-runner/evals/fake_claude.py \
  skills/kws-claude-plan-runner/evals/test_contracts.py \
  skills/kws-claude-plan-runner/evals/test_storage.py \
  skills/kws-claude-plan-runner/evals/test_evidence.py \
  skills/kws-claude-plan-runner/evals/test_helper.py \
  skills/kws-claude-plan-runner/evals/test_provider.py \
  skills/kws-claude-plan-runner/evals/test_recovery.py \
  skills/kws-claude-plan-runner/evals/test_engine.py \
  skills/kws-claude-plan-runner/evals/test_independence.py
git commit -m "refactor(claude-runner): enforce thin superpowers boundary"
```

## Task 3: Root Parity and Honest Public Contract

**Files:**

- Modify: `scripts/agent/check-plan-runner-parity.py`
- Modify: `scripts/agent/test_check_plan_runner_parity.py`
- Modify: `scripts/agent/fixtures/plan-runner-contract-v1.json`
- Modify: `scripts/agent/fixtures/plan-runner-parity-v1.json`
- Modify: both runner `AGENTS.md`, `SKILL.md`, `README.md`, `CHANGELOG.md`, and
  `evals/test_skill_contract.py`

**Produces:**

- active root fixtures updated in place to version 2;
- parity over external boundary outcomes only;
- docs that describe actual `--ignore-rules`, checkpoint, integration, and
  version 1 limits.

- [ ] **Step 1: Write parity RED tests**

The normalized parity output is limited to:

```python
{
    "exit": exit_code,
    "status": state["status"],
    "plan_statuses": [plan["status"] for plan in state["plans"]],
    "handoff_heads": ordered_handoff_heads,
    "verification_set_digest": accepted_digest,
    "required_receipt_count": receipt_count,
    "session_action": external_recovery_action,
    "integration": state["integration"],
}
```

Delete task status, finalization, review receipt, finding, provider-private
session, and stream comparisons.

- [ ] **Step 2: Run parity/doc tests and verify RED**

```bash
cd /Users/kws/source/private/Archive
"$PYTHON_313" -m unittest \
  scripts/agent/test_check_plan_runner_parity.py \
  skills/kws-codex-plan-runner/evals/test_skill_contract.py \
  skills/kws-claude-plan-runner/evals/test_skill_contract.py \
  skills/kws-claude-plan-runner/evals/test_independence.py \
  -v
```

- [ ] **Step 3: Update parity and docs without adding runtime behavior**

Change the existing fixtures to version 2 and keep old contents recoverable
through Git history. Public docs must say:

- specs/plans are immutable inputs handed to Superpowers, not reviewed by the
  runner;
- Superpowers owns all engineering workflow meaning;
- only exact external facts are runner-owned;
- every plan starts fresh, with one healthy resume and one fresh fallback;
- final plan owns the single whole-run review;
- integration policy is `keep`;
- version 1 is inspect-only;
- Codex execpolicy rules are disabled by `--ignore-rules`;
- dirty checkpointing detects drift but cannot restore files.

- [ ] **Step 4: Run parity/doc GREEN tests**

Run the same command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add \
  scripts/agent/check-plan-runner-parity.py \
  scripts/agent/test_check_plan_runner_parity.py \
  scripts/agent/fixtures/plan-runner-contract-v1.json \
  scripts/agent/fixtures/plan-runner-parity-v1.json \
  skills/kws-codex-plan-runner/AGENTS.md \
  skills/kws-codex-plan-runner/SKILL.md \
  skills/kws-codex-plan-runner/README.md \
  skills/kws-codex-plan-runner/CHANGELOG.md \
  skills/kws-codex-plan-runner/evals/test_skill_contract.py \
  skills/kws-claude-plan-runner/AGENTS.md \
  skills/kws-claude-plan-runner/SKILL.md \
  skills/kws-claude-plan-runner/README.md \
  skills/kws-claude-plan-runner/CHANGELOG.md \
  skills/kws-claude-plan-runner/evals/test_skill_contract.py
git commit -m "docs(plan-runners): publish version 2 thin boundary"
```

## Task 4: Two Canaries, Cutover Gate, and Final Evidence

**Files:**

- Modify only if needed:
  `scripts/agent/plan-runner-live-canary.py`
- Modify only if needed:
  `scripts/agent/test_plan_runner_live_canary.py`

**Produces:**

- multi-plan ownership proof;
- interruption/resume proof;
- read-only version 1 decision record immediately before integration;
- one canonical final verifier result.

- [ ] **Step 1: Add only the missing canary assertions**

Reuse the existing disposable repository, provider environment, signal,
timeout, and bounded-output helpers. Do not build a second canary framework.

Ownership acceptance:

```text
two plans use the same Task 1/Task 2 labels
both plans create distinct commits
two fresh plan sessions exist
prior handoff remains an ancestor
no task/finding/finalization state exists
final run union and branch handoff share one clean HEAD
integration=not_observed
```

Interruption acceptance:

```text
SIGINT makes the provider process group quiescent
runner returns resumable with an exact unchanged dirty checkpoint
resume prefers the recorded healthy session
Superpowers does not replay the completed first task
final handoff is clean and receipt-bound
dirty-tree drift fails before another provider launch
```

- [ ] **Step 2: Run the canary harness tests**

```bash
cd /Users/kws/source/private/Archive
"$PYTHON_313" -m unittest \
  scripts.agent.test_plan_runner_live_canary.SessionAndRunnerOutcomeTests.test_multi_plan_ownership_scenario \
  scripts.agent.test_plan_runner_live_canary.SessionAndRunnerOutcomeTests.test_interruption_resume_scenario \
  -v
```

Expected: pass without network access.

- [ ] **Step 3: Commit a canary change only when Step 1 changed files**

```bash
git add \
  scripts/agent/plan-runner-live-canary.py \
  scripts/agent/test_plan_runner_live_canary.py
git commit -m "test(plan-runners): prove thin boundary canaries"
```

If the existing harness already proves both scenarios after Tasks 1–3, do not
create a canary commit.

- [ ] **Step 4: Record the version 1 cutover decision without mutation**

Immediately before integration, enumerate existing version 1 run directories
and use each version 1 runner's `inspect --run-id` command. Record only provider,
run ID, state SHA-256, status, and the operator's explicit
`complete_with_v1_runner`, `retain_as_historical_evidence`, or
`retire_with_separate_authorization` decision in the git-ignored
`.superpowers/provider-plan-runners-v2-cutover/` directory.

Do not perform completion or retirement from this task. If a nonterminal run
lacks a decision, keep the version 2 branch unintegrated and report the exact
cutover blocker; implementation work remains complete and preserved.

- [ ] **Step 5: Run exactly the approved provider-backed canaries**

```bash
./scripts/agent/plan-runner-live-canary \
  --provider all \
  --mode ownership

./scripts/agent/plan-runner-live-canary \
  --provider all \
  --mode interruption
```

Expected: bounded pass output. If provider auth, usage, or runtime access is
unavailable, report live evidence as unavailable; do not convert it into
deterministic success.

- [ ] **Step 6: Run the canonical final gate once**

```bash
MERGE_BASE="$(git merge-base main HEAD)"
CANDIDATE_HEAD="$(git rev-parse HEAD)"
bun run agent:verify -- --base "$MERGE_BASE" --head "$CANDIDATE_HEAD"
```

Expected: exit `0`. This one command owns the final Codex eval, Claude eval,
parity, contract, Markdown, and diff checks.

## Blind-Spot Checks

These are acceptance checks, not new subsystems:

- Conflicting documents: Superpowers returns `blocked`; Python does not resolve
  prose conflicts.
- Missing private Superpowers prompt files: runner continues when the public
  entrypoint and helpers are present.
- Missing public Superpowers capability: runner blocks before provider launch.
- Lost provider conversation: unchanged worktree plus Superpowers ledger is the
  recovery source; Python does not recreate task state.
- Lost Superpowers scratch workspace: runner preserves Git/worktree evidence
  and starts fresh; it does not invent completed tasks from commits.
- Same task labels in multiple plans: invisible to runner state and therefore
  unable to collide.
- Final-plan scope: all specs/plans appear only in final-review requirements,
  not as future-plan execution targets.
- Duplicate verification commands: exact argv/cwd/input/deadline duplicates run
  once at final HEAD; non-identical commands are preserved.
- No-applicable verification: requires one bounded rationale and produces no
  synthetic command.
- HEAD changes: invalidate receipts only; never trigger a runner review.
- Provider output loss after commit: exact clean HEAD and helper artifacts allow
  bounded reconciliation without replaying a completed plan.
- Dirty interruption: permits unchanged-tree reuse but makes no restoration
  promise.
- v1 state: inspect-only, never auto-migrated or used as v2 recovery context.
- Live canary failure: does not create another implementation workflow; return
  to the one affected task and its focused test.

## Execution Order

- Task 1 → Task 2 → Task 3 → Task 4.
- No parallel implementation: the external fixture changes after both provider
  runtimes are independently green.
- No routine human checkpoint during Tasks 1–3.
- Human authority is needed only for exact version 1 cutover decisions,
  unavailable provider access, and later integration.
