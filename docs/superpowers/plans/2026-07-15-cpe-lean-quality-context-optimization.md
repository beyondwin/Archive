# CPE Lean Quality And Context Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Keep the CPE plan controller context small while preserving high-quality Superpowers implementation, review, final verification, and safe plan-level recovery.

**Architecture:** CPE remains one fresh Codex process per approved plan in one durable isolated worktree. The child uses a CPE-specific lean Superpowers contract, writes detailed evidence to worktree files, returns a compact workflow receipt, and requests recovery only through a bounded structured result; CPE validates the receipt and commit but does not become a task mapper, reviewer, fixer, or product-test runner. The launcher filters only final usage totals from Codex JSON events and keeps ordinary diagnostics in the existing bounded stderr log.

**Tech Stack:** Python 3 standard library, Git worktrees, Codex CLI JSONL events, POSIX process groups and advisory locks, shell-based deterministic evals.

## Global Constraints

- Keep the public CLI exactly at run, resume, and inspect.
- Keep state.json at format_version 1 with the current plan record fields.
- Keep the current twelve tracked CPE files; add no runtime module, database, metrics directory, or provider-cost estimator.
- Keep one fresh ephemeral Codex process per plan and one shared isolated worktree for ordered plans.
- Do not modify installed Superpowers skill files.
- CPE must not own task mapping, implementation, task review, fixes, final review, or product verification.
- Task implementers run focused RED/GREEN and affected tests; they do not automatically run the full suite.
- Reviewers consume existing evidence and do not repeat an evidenced verification command.
- The same normalized command must not run twice at the same Git HEAD unless a transient infrastructure failure is explicitly recorded.
- Run the complete deterministic gate once at the final revision, not after every task.
- Preserve exact-HEAD, clean-worktree, ancestry, result isolation, locking, process-group cleanup, bounded logs, and immutable input snapshots.
- Keep evals sequential, standard-library-only, network-free, credential-free, and model-free.
- The complete deterministic gate must remain below fifteen seconds on the development machine, with a target of twelve seconds or less.

---

## Context

- Approved design: docs/superpowers/specs/2026-07-15-cpe-lean-quality-context-optimization-design.md
- CPE entry point: skills/kws-codex-plan-executor/scripts/cpe.py
- Plan launcher: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
- Sequential state machine: skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py
- Durable format-1 state: skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py
- Strict child schema: skills/kws-codex-plan-executor/templates/plan-result-schema.json
- Deterministic fixtures: skills/kws-codex-plan-executor/evals/check_runner.py and evals/fake_codex.py
- Public-contract fixtures: skills/kws-codex-plan-executor/evals/check_cli.py
- Current observed runner-test profile: 26 passing tests, 14.167 seconds in check_runner.py alone; the slowest avoidable case is the numeric-attempt test at 1.471 seconds because it launches three child attempts to test a path-selection rule.
- Existing accepted result files remain readable. Only new completed launches under this contract must include workflow_receipt.

## File Responsibility Map

| File | Responsibility in this change |
|---|---|
| skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py | Lean prompt, recovery-capsule marker, JSON/stdout filtering, stderr logging, attempt usage totals |
| skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py | Result-shape validation, workflow receipt validation, compact capsule creation, conditional retry, attempt-finished metrics |
| skills/kws-codex-plan-executor/templates/plan-result-schema.json | Optional workflow receipt and non-completed recovery fields |
| skills/kws-codex-plan-executor/evals/fake_codex.py | Deterministic workflow artifacts, retry outcomes, recovery marker capture, usage JSON events |
| skills/kws-codex-plan-executor/evals/check_runner.py | Focused runtime, receipt, recovery, usage, safety, and timing coverage |
| skills/kws-codex-plan-executor/evals/check_cli.py | Installed Codex flag and documented-contract coverage |
| skills/kws-codex-plan-executor/README.md | Full operational contract and limitations |
| skills/kws-codex-plan-executor/SKILL.md | Concise invocation and ownership contract |

## Execution Order

- All five tasks are sequential because they edit the same launcher, runner, schema, and fixtures.
- Task 1 restores timing headroom before coverage grows.
- Tasks 2 through 4 each end with focused tests only.
- Task 5 performs the only complete deterministic gate at the final HEAD.
- No additional human approval gate is required; the design and this plan are already approved.

---

### Task 1: Restore Deterministic Eval Timing Headroom

**Files:**

- Modify: skills/kws-codex-plan-executor/evals/check_runner.py

**Interfaces:**

- Consumes: Existing SequentialRunner._initialize_run, _add_new_worktree, _create_or_reconcile_worktree, StateStore.save, and resume contracts.
- Produces: The same 26 behavioral checks with fewer unnecessary child launches and a 0.02-second fixture-only termination grace.

- [ ] **Step 1: Measure the current gate and preserve the timing evidence**

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
/usr/bin/time -p ./evals/run.sh
~~~

Expected: all current tests pass; record real time in the task report. Treat any result above 12 seconds as the failing performance observation for this task. Do not rerun it before editing.

- [ ] **Step 2: Shorten only deterministic fixture waits**

Pass an explicit fixture-only grace to both launcher construction sites in check_runner.py:

~~~python
launcher = CodexLauncher(
    schema_path=ROOT / "templates" / "plan-result-schema.json",
    codex_bin=str(self.fake),
    timeout_seconds=timeout_seconds,
    termination_grace_seconds=0.02,
    environ=environment,
)
~~~

Use the same value inside the start_run_process inline program:

~~~python
launcher = CodexLauncher(
    schema_path=Path(os.environ["CPE_TEST_SCHEMA"]),
    codex_bin=os.environ["CPE_TEST_CODEX"],
    timeout_seconds=5,
    termination_grace_seconds=0.02,
    environ=dict(os.environ),
)
~~~

Change only the timeout-group fixture invocation from 0.4 to 0.2 seconds:

~~~python
result = self.runner(
    timeout_seconds=0.2,
    CPE_FAKE_GRANDCHILD_PID=str(pid_path),
).run(
    workspace=self.repo,
    specs=[],
    plans=[self.plan(1, "timeout_grandchild")],
    run_id="timeout-group",
)
~~~

The fake child writes its PID evidence immediately and polls every 0.05 seconds, so 0.2 seconds still exercises timeout rather than spawn failure.

- [ ] **Step 3: Test initializing reconciliation without launching an unrelated plan child**

Replace the two reconciliation test bodies with direct tests of the reconciliation boundary:

~~~python
def test_reconciles_verified_initializing_worktree(self) -> None:
    runner = self.runner()
    store = runner._initialize_run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "completed")],
        run_id="reconcile-create",
    )
    runner._add_new_worktree(store)

    runner._create_or_reconcile_worktree(store)

    self.assertEqual(store.state["status"], "running")
    self.assertTrue(Path(store.state["worktree"]).is_dir())
    self.assertEqual(
        git(Path(store.state["worktree"]), "rev-parse", "HEAD"),
        store.state["source_commit"],
    )


def test_recreates_absent_initializing_worktree(self) -> None:
    runner = self.runner()
    store = runner._initialize_run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "completed")],
        run_id="recreate-initializing",
    )

    runner._create_or_reconcile_worktree(store)

    self.assertEqual(store.state["status"], "running")
    self.assertTrue(Path(store.state["worktree"]).is_dir())
    self.assertEqual(
        git(Path(store.state["worktree"]), "rev-parse", "HEAD"),
        store.state["source_commit"],
    )
~~~

These tests still distinguish the “verified existing worktree” and “absent worktree” branches. They stop before execution because child completion is already covered by the sequential and resume tests.

- [ ] **Step 4: Construct attempt-ten state directly instead of launching two irrelevant failures**

Replace test_attempts_above_ten_use_numeric_prior_log_identity with:

~~~python
def test_attempts_above_ten_use_numeric_prior_log_identity(self) -> None:
    runner = self.runner()
    store = runner._initialize_run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "failed")],
        run_id="numeric-attempts",
    )
    runner._create_or_reconcile_worktree(store)
    worktree = Path(store.state["worktree"])
    head = git(worktree, "rev-parse", "HEAD")
    result_path = store.root / "results" / "plan-01-attempt-10.json"
    result_path.write_text(
        json.dumps(
            {
                "plan_id": "plan-01",
                "status": "failed",
                "head_commit": head,
                "verification": [],
                "summary": "prepared attempt ten",
            }
        ),
        encoding="utf-8",
    )
    result_path.chmod(0o600)
    for attempt in (9, 10):
        log_path = store.root / "logs" / f"plan-01-attempt-{attempt}.log"
        log_path.write_text(f"attempt {attempt}\n", encoding="utf-8")
        log_path.chmod(0o600)
    plan = store.state["plans"][0]
    plan.update(
        status="failed",
        starting_commit=head,
        attempt_count=10,
        result_path=str(result_path.resolve()),
    )
    store.state["status"] = "failed"
    store.save()

    runner.resume(run_id="numeric-attempts", retry_failed=True)

    prior_log = self.invocations()[-1]["prior_log"]
    self.assertTrue(str(prior_log).endswith("plan-01-attempt-10.log"))
~~~

This leaves one real explicit-retry launch because launch integration matters, while removing the two failures that contributed no evidence to numeric path selection.

- [ ] **Step 5: Run the complete timing gate once for this performance deliverable**

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
/usr/bin/time -p ./evals/run.sh
~~~

Expected: both suites pass, real time is below 15 seconds, and the task report records whether the 12-second target was reached. If the result is between 12 and 15 seconds, proceed; Task 3’s removal of blind failed-result retries provides additional headroom. Do not repeat the command without a code change.

- [ ] **Step 6: Commit**

~~~bash
git add skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "test(cpe): restore deterministic eval headroom"
~~~

---

### Task 2: Add The Lean Plan Contract And Workflow Receipt

**Files:**

- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py
- Modify: skills/kws-codex-plan-executor/templates/plan-result-schema.json
- Modify: skills/kws-codex-plan-executor/evals/fake_codex.py
- Modify: skills/kws-codex-plan-executor/evals/check_runner.py

**Interfaces:**

- Consumes: CodexLauncher._prompt inputs, LaunchResult.payload, current exact-HEAD and clean-worktree handoff checks.
- Produces: Optional schema property workflow_receipt; new completed launches require its exact six fields and two safe worktree-relative artifact paths.

- [ ] **Step 1: Write failing lean-prompt and workflow-receipt tests**

Update test_launcher_command_and_prompt_are_minimal_and_ephemeral so the _prompt call still uses prior_result=None and prior_log=None, then add:

~~~python
self.assertIn("SPECIFICATIONS_REFERENCE_ONLY_IN_ORDER:", prompt)
self.assertIn("Do not preload specification snapshots", prompt)
self.assertIn("focused RED/GREEN", prompt)
self.assertIn("no automatic full-suite run per task", prompt)
self.assertIn("review-package", prompt)
self.assertIn("one consolidated fix subagent", prompt)
self.assertIn("cross-task final review", prompt)
self.assertIn("same normalized verification command", prompt)
self.assertIn("workflow_receipt", prompt)
self.assertLess(len(prompt.encode("utf-8")), 2_400)
~~~

In test_handoff_acceptance_and_result_isolation, after the valid payload assertion and before wrong_head, add:

~~~python
missing_receipt = dict(payload)
missing_receipt.pop("workflow_receipt")
self.assertEqual(
    runner._handoff_error(store, plan, outcome(missing_receipt)),
    "invalid_workflow_receipt",
)

receipt = dict(payload["workflow_receipt"])
duplicate_verification = dict(
    payload,
    workflow_receipt=dict(receipt, duplicate_verification="repeated"),
)
self.assertEqual(
    runner._handoff_error(store, plan, outcome(duplicate_verification)),
    "invalid_workflow_receipt",
)

failed_final_review = dict(
    payload,
    workflow_receipt=dict(receipt, final_review="changes_requested"),
)
self.assertEqual(
    runner._handoff_error(store, plan, outcome(failed_final_review)),
    "invalid_workflow_receipt",
)

outside_artifact = dict(
    payload,
    workflow_receipt=dict(
        receipt,
        final_review_artifact="../outside-review.md",
    ),
)
self.assertEqual(
    runner._handoff_error(store, plan, outcome(outside_artifact)),
    "unsafe_workflow_artifact",
)

worktree = Path(store.state["worktree"])
symlink = worktree / ".superpowers" / "sdd" / "review-link.md"
symlink.symlink_to(worktree / ".superpowers" / "sdd" / "final-review.md")
symlink_artifact = dict(
    payload,
    workflow_receipt=dict(
        receipt,
        final_review_artifact=".superpowers/sdd/review-link.md",
    ),
)
self.assertEqual(
    runner._handoff_error(store, plan, outcome(symlink_artifact)),
    "unsafe_workflow_artifact",
)
symlink.unlink()
~~~

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_launcher_command_and_prompt_are_minimal_and_ephemeral \
  evals.check_runner.SequentialRunnerTest.test_handoff_acceptance_and_result_isolation -v
~~~

Expected: FAIL because the prompt lacks the lean contract and completed fake results lack workflow_receipt.

- [ ] **Step 2: Extend the strict schema with an optional receipt**

Add this property after summary in plan-result-schema.json, including the comma before it:

~~~json
"workflow_receipt": {
  "type": "object",
  "additionalProperties": false,
  "required": [
    "mode",
    "progress_ledger",
    "task_reviews",
    "final_review",
    "final_review_artifact",
    "duplicate_verification"
  ],
  "properties": {
    "mode": {"const": "subagent-driven-lean"},
    "progress_ledger": {"type": "string", "minLength": 1, "maxLength": 500},
    "task_reviews": {"const": "complete"},
    "final_review": {"const": "approved"},
    "final_review_artifact": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500
    },
    "duplicate_verification": {"const": "none"}
  }
}
~~~

Do not add workflow_receipt to the top-level required array. The schema must continue reading historical result files; runner.py requires the receipt only when accepting a new completed attempt.

- [ ] **Step 3: Make the fake child create realistic file-backed evidence**

Add:

~~~python
def workflow_receipt(worktree: Path) -> dict[str, str]:
    evidence = worktree / ".superpowers" / "sdd"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
    (evidence / "progress.md").write_text(
        "Task 1: complete\n",
        encoding="utf-8",
    )
    (evidence / "final-review.md").write_text(
        "Verdict: approved\nFindings: none\n",
        encoding="utf-8",
    )
    return {
        "mode": "subagent-driven-lean",
        "progress_ledger": ".superpowers/sdd/progress.md",
        "task_reviews": "complete",
        "final_review": "approved",
        "final_review_artifact": ".superpowers/sdd/final-review.md",
        "duplicate_verification": "none",
    }
~~~

After constructing payload, add:

~~~python
if status == "completed":
    payload["workflow_receipt"] = workflow_receipt(worktree)
~~~

The nested .gitignore matches the existing Superpowers sdd-workspace helper,
which creates a self-ignoring .superpowers/sdd directory in every repository.
This keeps exact clean-HEAD acceptance meaningful without requiring a
repository-level ignore rule.

- [ ] **Step 4: Add the concise CPE-specific Superpowers overlay**

Change the specification label to:

~~~python
"SPECIFICATIONS_REFERENCE_ONLY_IN_ORDER:",
~~~

Replace the generic workflow lines at the end of _prompt with:

~~~python
[
    "",
    "Discover and follow repository AGENTS.md instructions from root to the edited subtree.",
    "Use superpowers:subagent-driven-development for this approved plan; CPE does not own task mapping or product quality roles.",
    "Do not preload specification snapshots. Read only a referenced section when the plan is ambiguous or conflicts with observed code.",
    "Use task-brief, report files, review-package, task review files, and .superpowers/sdd/progress.md as file-backed handoffs.",
    "Implementers run plan-declared focused RED/GREEN and tests affected by fixes; there is no automatic full-suite run per task.",
    "Reviewers reuse evidenced tests, write full findings to files, and return only verdicts, finding IDs, severities, and artifact paths.",
    "Resolve one task finding set with one consolidated fix subagent, then review only the finding delta and affected evidence.",
    "After all tasks, perform one cross-task final review and one full verification at the final HEAD.",
    "Do not run the same normalized verification command twice at the same HEAD unless a transient failure is recorded.",
    "Keep controller context to task status, commits, one-line test evidence, finding IDs, decisions, and the next action.",
    "For completed, leave a clean worktree, report exact HEAD and successful final verification, and include workflow_receipt.",
    "Return only the fixed schema object as the final response. Do not merge, push, deploy, or modify files outside the worktree.",
]
~~~

This overlay references existing Superpowers helpers; it does not copy their templates into CPE.

- [ ] **Step 5: Validate receipt structure and safe artifact paths**

Replace _RESULT_FIELDS with:

~~~python
_RESULT_REQUIRED_FIELDS = {
    "plan_id",
    "status",
    "head_commit",
    "verification",
    "summary",
}
_RESULT_OPTIONAL_FIELDS = {"workflow_receipt"}
_WORKFLOW_RECEIPT_FIELDS = {
    "mode",
    "progress_ledger",
    "task_reviews",
    "final_review",
    "final_review_artifact",
    "duplicate_verification",
}
~~~

Add these module helpers before SequentialRunner:

~~~python
def _safe_worktree_artifact(worktree: Path, declared: object) -> bool:
    if not isinstance(declared, str) or not declared or len(declared) > 500:
        return False
    relative = Path(declared)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    candidate = worktree
    try:
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                return False
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(worktree.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return resolved.is_file() and not resolved.is_symlink()


def _workflow_receipt_error(
    worktree: Path,
    receipt: object,
) -> str | None:
    if not isinstance(receipt, dict) or set(receipt) != _WORKFLOW_RECEIPT_FIELDS:
        return "invalid_workflow_receipt"
    expected = {
        "mode": "subagent-driven-lean",
        "task_reviews": "complete",
        "final_review": "approved",
        "duplicate_verification": "none",
    }
    if any(receipt.get(name) != value for name, value in expected.items()):
        return "invalid_workflow_receipt"
    for name in ("progress_ledger", "final_review_artifact"):
        if not _safe_worktree_artifact(worktree, receipt.get(name)):
            return "unsafe_workflow_artifact"
    return None
~~~

At the start of _handoff_error, replace exact-field equality with:

~~~python
payload = outcome.payload
if not isinstance(payload, dict):
    return "invalid_result"
fields = set(payload)
if (
    not _RESULT_REQUIRED_FIELDS.issubset(fields)
    or fields - _RESULT_REQUIRED_FIELDS - _RESULT_OPTIONAL_FIELDS
):
    return "invalid_result"
~~~

After exact HEAD and ancestry checks, and before the non-completed early return, add:

~~~python
if payload["status"] == "completed":
    receipt_error = _workflow_receipt_error(
        worktree,
        payload.get("workflow_receipt"),
    )
    if receipt_error is not None:
        return receipt_error
elif "workflow_receipt" in payload:
    return "invalid_result"
~~~

Do not re-run verification or parse review findings. Existing verification and receipt are child-reported evidence mechanically bound to exact clean HEAD.

- [ ] **Step 6: Run only the two focused tests**

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_launcher_command_and_prompt_are_minimal_and_ephemeral \
  evals.check_runner.SequentialRunnerTest.test_handoff_acceptance_and_result_isolation -v
~~~

Expected: 2 tests PASS. Do not run evals/run.sh in this task.

- [ ] **Step 7: Commit**

~~~bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/templates/plan-result-schema.json \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): require lean workflow receipt"
~~~

---

### Task 3: Add Compact Conditional Recovery

**Files:**

- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py
- Modify: skills/kws-codex-plan-executor/templates/plan-result-schema.json
- Modify: skills/kws-codex-plan-executor/evals/fake_codex.py
- Modify: skills/kws-codex-plan-executor/evals/check_runner.py

**Interfaces:**

- Consumes: Prior result path, numeric prior log identity, worktree Git status, .superpowers/sdd/progress.md, and non-completed child payload.
- Produces: _recovery_decision returning (retry, reason, failure_signature, next_strategy); a private recovery JSON file; launcher recovery_path; optional retryable, failure_signature, and next_strategy result fields.

- [ ] **Step 1: Write failing schema, capsule, and retry-policy tests**

Add one fake scenario:

~~~python
"retryable_then_completed",
~~~

Change invocation_number to accept recovery_capsule instead of prior_log and record:

~~~python
{
    "plan_id": plan_id,
    "worktree": str(worktree),
    "number": count,
    "recovery_capsule": recovery_capsule,
}
~~~

Parse the new prompt marker in main:

~~~python
recovery_match = re.search(
    r"^RECOVERY_CAPSULE: (.+)$",
    prompt,
    re.MULTILINE,
)
recovery_capsule = (
    recovery_match.group(1).strip()
    if recovery_match
    else None
)
attempt = invocation_number(
    plan_id,
    worktree,
    recovery_capsule,
)
~~~

For interrupted and retryable first attempts, create ledger evidence:

~~~python
def write_progress(worktree: Path) -> None:
    evidence = worktree / ".superpowers" / "sdd"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
    (evidence / "progress.md").write_text(
        "Task 1: complete (commit 1111111)\n"
        "Task 2: complete (commit 2222222)\n",
        encoding="utf-8",
    )
~~~

Implement deterministic scenario outcomes:

~~~python
elif scenario == "retryable_then_completed":
    if attempt == 1:
        write_progress(worktree)
        status = "failed"
    else:
        head = commit_plan(worktree, plan_id)
        status = "completed"
elif scenario == "interrupted":
    write_progress(worktree)
~~~

After base payload construction and before workflow_receipt, add:

~~~python
if scenario == "retryable_then_completed" and status == "failed":
    payload.update(
        retryable=True,
        failure_signature="verification:test_parser_failed",
        next_strategy="inspect the parser boundary and resume Task 3",
    )
~~~

Replace the numeric attempt assertion added in Task 1:

~~~python
recovery_path = Path(self.invocations()[-1]["recovery_capsule"])
capsule = json.loads(recovery_path.read_text())
self.assertTrue(
    str(capsule["prior_log_path"]).endswith(
        "plan-01-attempt-10.log"
    )
)
~~~

Extend test_initial_plus_one_recovery_attempt_is_the_automatic_limit:

~~~python
calls = self.invocations()
self.assertEqual(len(calls), 2)
capsule = json.loads(Path(calls[1]["recovery_capsule"]).read_text())
self.assertEqual(capsule["completed_tasks"], ["Task 1", "Task 2"])
self.assertEqual(capsule["current_task"], "Task 3")
self.assertEqual(capsule["failure_signature"], "status:interrupted")
self.assertEqual(capsule["prior_status"], "interrupted")
events = [
    json.loads(line)
    for line in (
        self.home
        / "orchestrator"
        / "attempt-limit"
        / "events.jsonl"
    ).read_text().splitlines()
]
self.assertTrue(
    any(
        event["kind"] == "plan.recovery_stopped"
        and event["reason"] == "repeated_failure_signature"
        for event in events
    )
)
~~~

Add:

~~~python
def test_retryable_failure_uses_one_changed_strategy_recovery(self) -> None:
    result = self.runner().run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "retryable_then_completed")],
        run_id="retryable-recovery",
    )
    self.assertEqual(result["status"], "completed")
    self.assertEqual(result["plans"][0]["attempt_count"], 2)
    calls = self.invocations()
    self.assertEqual(len(calls), 2)
    capsule_path = Path(calls[1]["recovery_capsule"])
    self.assertEqual(capsule_path.stat().st_mode & 0o777, 0o600)
    capsule = json.loads(capsule_path.read_text())
    self.assertEqual(
        capsule["failure_signature"],
        "verification:test_parser_failed",
    )
    self.assertEqual(
        capsule["next_strategy"],
        "inspect the parser boundary and resume Task 3",
    )
    self.assertEqual(capsule["dirty_files"], [])


def test_nonretryable_failure_stops_after_one_attempt(self) -> None:
    result = self.runner().run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "failed")],
        run_id="nonretryable",
    )
    self.assertEqual(result["status"], "failed")
    self.assertEqual(result["plans"][0]["attempt_count"], 1)
    self.assertEqual(len(self.invocations()), 1)
~~~

In test_resume_skips_completed_plan_and_continues_current_git_state, add this assertion before resume:

~~~python
self.assertEqual(len(self.invocations()), 2)
~~~

In test_explicit_retry_failed_grants_exactly_one_attempt, update the final
attempt count because the initial non-retryable failure now stops after one
attempt:

~~~python
self.assertEqual(result["plans"][0]["attempt_count"], 2)
~~~

In test_timeout_kills_the_complete_process_group, after asserting two
invocations, add:

~~~python
timeout_calls = self.invocations()
timeout_capsule = json.loads(
    Path(timeout_calls[1]["recovery_capsule"]).read_text()
)
self.assertEqual(timeout_capsule["failure_signature"], "timeout")
self.assertEqual(timeout_capsule["prior_status"], "interrupted")
~~~

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_attempts_above_ten_use_numeric_prior_log_identity \
  evals.check_runner.SequentialRunnerTest.test_initial_plus_one_recovery_attempt_is_the_automatic_limit \
  evals.check_runner.SequentialRunnerTest.test_retryable_failure_uses_one_changed_strategy_recovery \
  evals.check_runner.SequentialRunnerTest.test_nonretryable_failure_stops_after_one_attempt \
  evals.check_runner.SequentialRunnerTest.test_resume_skips_completed_plan_and_continues_current_git_state -v
~~~

Expected: FAIL because RECOVERY_CAPSULE is absent and every initial failure still receives a blind second attempt.

- [ ] **Step 2: Extend the schema for an all-or-none recovery decision**

Add top-level optional properties:

~~~json
"retryable": {"type": "boolean"},
"failure_signature": {
  "type": "string",
  "minLength": 1,
  "maxLength": 256
},
"next_strategy": {
  "type": "string",
  "minLength": 1,
  "maxLength": 1000
}
~~~

Extend _RESULT_OPTIONAL_FIELDS:

~~~python
_RECOVERY_RESULT_FIELDS = {
    "retryable",
    "failure_signature",
    "next_strategy",
}
_RESULT_OPTIONAL_FIELDS = {
    "workflow_receipt",
    *_RECOVERY_RESULT_FIELDS,
}
~~~

In _handoff_error, after basic field validation, enforce:

~~~python
recovery_fields = fields & _RECOVERY_RESULT_FIELDS
if recovery_fields and recovery_fields != _RECOVERY_RESULT_FIELDS:
    return "invalid_result"
if recovery_fields:
    if (
        not isinstance(payload["retryable"], bool)
        or not isinstance(payload["failure_signature"], str)
        or not payload["failure_signature"].strip()
        or len(payload["failure_signature"]) > 256
        or not isinstance(payload["next_strategy"], str)
        or not payload["next_strategy"].strip()
        or len(payload["next_strategy"]) > 1000
        or payload.get("status") == "completed"
    ):
        return "invalid_result"
~~~

Blocked and interrupted results may omit the three fields. A structured retryable product failure must provide all three.

- [ ] **Step 3: Add bounded ledger parsing and private capsule persistence**

Add:

~~~python
_COMPLETED_TASK = re.compile(
    r"^Task\s+([1-9][0-9]*):\s+complete\b",
    re.IGNORECASE | re.MULTILINE,
)


def _ledger_progress(worktree: Path) -> tuple[list[str], str | None]:
    ledger = worktree / ".superpowers" / "sdd" / "progress.md"
    if ledger.is_symlink() or not ledger.is_file():
        return [], None
    try:
        text = ledger.read_bytes()[:65_536].decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return [], None
    numbers = sorted({int(match) for match in _COMPLETED_TASK.findall(text)})
    completed = [f"Task {number}" for number in numbers]
    current = 1
    known = set(numbers)
    while current in known:
        current += 1
    return completed, f"Task {current}"


def _write_private_json(path: Path, payload: dict[str, object]) -> Path:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short write while persisting recovery capsule")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return path.resolve()
~~~

Add a SequentialRunner method:

~~~python
def _create_recovery_capsule(
    self,
    store: StateStore,
    plan: dict[str, Any],
    *,
    current_head: str,
    prior_result: Path,
    prior_log: Path | None,
) -> Path:
    try:
        payload = json.loads(prior_result.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    prior_status = payload.get("status")
    if prior_status not in {"interrupted", "blocked", "failed"}:
        prior_status = (
            plan["status"]
            if plan["status"] in {"interrupted", "blocked", "failed"}
            else "interrupted"
        )
    signature = payload.get("failure_signature")
    if not isinstance(signature, str) or not signature.strip():
        signature = f"status:{prior_status}"
    strategy = payload.get("next_strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        strategy = (
            "resume the first incomplete task from durable evidence "
            "without redispatching completed tasks"
        )
    completed, current = _ledger_progress(Path(store.state["worktree"]))
    dirty = _git(
        Path(store.state["worktree"]),
        "status",
        "--porcelain",
        "--untracked-files=all",
    ).splitlines()[:100]
    target = (
        store.root
        / "results"
        / f"{plan['plan_id']}-attempt-{plan['attempt_count']}-recovery.json"
    )
    return _write_private_json(
        target,
        {
            "plan_id": plan["plan_id"],
            "attempt": plan["attempt_count"],
            "starting_commit": plan["starting_commit"],
            "current_head": current_head,
            "completed_tasks": completed,
            "current_task": current,
            "prior_status": prior_status,
            "failure_signature": signature[:256],
            "next_strategy": strategy[:1000],
            "dirty_files": dirty,
            "prior_result_path": str(prior_result.resolve()),
            "prior_log_path": (
                str(prior_log.resolve()) if prior_log is not None else None
            ),
        },
    )
~~~

The numeric task inference summarizes the existing Superpowers ledger. It does not parse plan prose or create task state in CPE.

- [ ] **Step 4: Replace raw prior markers with one recovery-capsule marker**

Change _prompt and launch signatures from prior_result and prior_log to:

~~~python
recovery_path: Path | None
~~~

Replace both prior marker branches with:

~~~python
if recovery_path is not None:
    lines.append(f"RECOVERY_CAPSULE: {recovery_path}")
~~~

Add this recovery read order to the prompt rules:

~~~python
"On recovery, read the capsule, progress ledger, Git status/log, and current task artifacts in that order; never redispatch a completed ledger task.",
~~~

In _execute, compute prior_result and numeric prior_log as today, then create recovery_path before incrementing attempt_count:

~~~python
recovery_path = (
    self._create_recovery_capsule(
        store,
        plan,
        current_head=current_head,
        prior_result=prior_result,
        prior_log=prior_log,
    )
    if prior_result is not None and previous_attempt > 0
    else None
)
~~~

Pass recovery_path to launcher.launch and remove prior_result and prior_log from that call.

- [ ] **Step 5: Make retry a deterministic decision instead of a fixed second loop**

Add:

~~~python
def _recovery_decision(
    *,
    payload: dict[str, object] | None,
    timed_out: bool,
    previous_signature: str | None,
    automatic_available: bool,
) -> tuple[bool, str, str, str]:
    status = payload.get("status") if payload is not None else None
    if timed_out:
        signature = "timeout"
        strategy = (
            "resume the first incomplete task from durable evidence "
            "after process timeout"
        )
    elif status == "interrupted":
        signature = "status:interrupted"
        strategy = (
            "resume the first incomplete task from durable evidence "
            "after child interruption"
        )
    elif (
        status == "failed"
        and payload is not None
        and payload.get("retryable") is True
    ):
        signature = str(payload["failure_signature"])
        strategy = str(payload["next_strategy"])
    else:
        return False, "not_retryable", "status:failed", ""
    if signature == previous_signature:
        return False, "repeated_failure_signature", signature, strategy
    if not automatic_available:
        return False, "automatic_limit", signature, strategy
    return True, "eligible", signature, strategy
~~~

At entry to each current plan, use:

~~~python
automatic_available = plan["attempt_count"] == 0 and not explicit_retry
operator_attempt = explicit_retry or plan["attempt_count"] > 0
explicit_retry = False
~~~

Launch one attempt unconditionally. After an incomplete valid payload or timeout:

~~~python
previous_signature = None
if prior_result is not None:
    try:
        previous_payload = json.loads(prior_result.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        previous_payload = {}
    if isinstance(previous_payload, dict):
        candidate = previous_payload.get("failure_signature")
        if isinstance(candidate, str) and candidate.strip():
            previous_signature = candidate
        elif previous_payload.get("status") == "interrupted":
            previous_signature = "status:interrupted"

retry, reason, signature, strategy = _recovery_decision(
    payload=outcome.payload,
    timed_out=outcome.timed_out,
    previous_signature=previous_signature,
    automatic_available=automatic_available and not operator_attempt,
)
if retry:
    automatic_available = False
    store.append_event(
        "plan.recovery_scheduled",
        plan_id=plan["plan_id"],
        failure_signature=signature,
        next_strategy=strategy,
    )
    continue
store.append_event(
    "plan.recovery_stopped",
    plan_id=plan["plan_id"],
    reason=reason,
    failure_signature=signature,
)
plan["status"] = "failed"
state["status"] = "failed"
store.save()
store.append_event(
    "plan.failed",
    plan_id=plan["plan_id"],
    attempts=plan["attempt_count"],
)
return self._summary(store)
~~~

Keep blocked as an immediate blocked return before this decision. Keep invalid result, wrong HEAD, broken ancestry, dirty completed handoff, and other integrity failures on the existing fail-closed path. A later operator resume of blocked or interrupted state receives one attempt; resume --retry-failed continues to grant exactly one attempt.

Update _synthetic_result so timeout evidence is an interrupted recovery source:

~~~python
status = "interrupted" if outcome.timed_out else "failed"
payload = {
    "plan_id": plan["plan_id"],
    "status": status,
    "head_commit": observed,
    "verification": [],
    "summary": (
        "child produced no valid result; "
        f"returncode={outcome.returncode}; "
        f"timed_out={outcome.timed_out}; "
        f"log={outcome.log_path}"
    ),
}
if outcome.timed_out:
    payload.update(
        retryable=True,
        failure_signature="timeout",
        next_strategy=(
            "resume the first incomplete task from durable evidence "
            "after process timeout"
        ),
    )
~~~

- [ ] **Step 6: Run the focused recovery matrix**

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_attempts_above_ten_use_numeric_prior_log_identity \
  evals.check_runner.SequentialRunnerTest.test_initial_plus_one_recovery_attempt_is_the_automatic_limit \
  evals.check_runner.SequentialRunnerTest.test_retryable_failure_uses_one_changed_strategy_recovery \
  evals.check_runner.SequentialRunnerTest.test_nonretryable_failure_stops_after_one_attempt \
  evals.check_runner.SequentialRunnerTest.test_resume_skips_completed_plan_and_continues_current_git_state \
  evals.check_runner.SequentialRunnerTest.test_explicit_retry_failed_grants_exactly_one_attempt \
  evals.check_runner.SequentialRunnerTest.test_timeout_kills_the_complete_process_group -v
~~~

Expected: 7 tests PASS. Verify from assertions that failed non-retryable output launches once, timeout/interruption launches at most one recovery, repeated signature stops, and explicit retry adds exactly one attempt. Do not run the full gate.

- [ ] **Step 7: Commit**

~~~bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/templates/plan-result-schema.json \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): make recovery evidence driven"
~~~

---

### Task 4: Filter Usage Metrics Without Retaining JSON Events

**Files:**

- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py
- Modify: skills/kws-codex-plan-executor/evals/fake_codex.py
- Modify: skills/kws-codex-plan-executor/evals/check_runner.py
- Modify: skills/kws-codex-plan-executor/evals/check_cli.py

**Interfaces:**

- Consumes: Newline-delimited Codex stdout JSON with type turn.completed and a usage object.
- Produces: LaunchResult.duration_ms, input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens, and launcher_prompt_bytes; the existing plan.attempt_finished event records those values or null.

- [ ] **Step 1: Write failing parser, stream-isolation, and event tests**

Import the parser in check_runner.py:

~~~python
from cpe_runtime.launcher import CodexLauncher, LaunchResult, _UsageFilter
~~~

Add:

~~~python
def test_usage_filter_keeps_only_bounded_final_totals(self) -> None:
    capture = _UsageFilter()
    capture.feed(
        b'{"type":"item.completed","item":{"text":"RAW_EVENT_SENTINEL"}}\n'
        b'{"type":"turn.completed","usage":{"input_tokens":41,'
    )
    capture.feed(
        b'"cached_input_tokens":31,"output_tokens":7,'
        b'"reasoning_output_tokens":5}}\n'
    )
    capture.finish()
    self.assertEqual(
        capture.usage,
        {
            "input_tokens": 41,
            "cached_input_tokens": 31,
            "output_tokens": 7,
            "reasoning_output_tokens": 5,
        },
    )
    self.assertFalse(hasattr(capture, "events"))

    missing = _UsageFilter()
    missing.feed(b'{"type":"turn.started"}\nnot-json\n')
    missing.finish()
    self.assertEqual(
        missing.usage,
        {
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "reasoning_output_tokens": None,
        },
    )

    oversized = _UsageFilter()
    oversized.feed(b"x" * 70_000 + b"\n")
    oversized.feed(
        b'{"type":"turn.completed","usage":{"input_tokens":3}}\n'
    )
    oversized.finish()
    self.assertEqual(oversized.usage["input_tokens"], 3)
~~~

In the launcher command test, replace assertNotIn("--json", command) with:

~~~python
self.assertIn("--json", command)
~~~

In test_two_plans_execute_sequentially_in_one_worktree, add:

~~~python
events_path = (
    self.home / "orchestrator" / "two-plans" / "events.jsonl"
)
events = [json.loads(line) for line in events_path.read_text().splitlines()]
finished = [
    event for event in events
    if event["kind"] == "plan.attempt_finished"
]
self.assertEqual(len(finished), 2)
for event in finished:
    self.assertGreaterEqual(event["duration_ms"], 0)
    self.assertEqual(event["input_tokens"], 41)
    self.assertEqual(event["cached_input_tokens"], 31)
    self.assertEqual(event["output_tokens"], 7)
    self.assertEqual(event["reasoning_output_tokens"], 5)
    self.assertGreater(event["launcher_prompt_bytes"], 0)
self.assertNotIn("RAW_EVENT_SENTINEL", events_path.read_text())
for call in calls:
    log = (
        self.home
        / "orchestrator"
        / "two-plans"
        / "logs"
        / f"{call['plan_id']}-attempt-1.log"
    )
    self.assertNotIn("RAW_EVENT_SENTINEL", log.read_text())
~~~

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_usage_filter_keeps_only_bounded_final_totals \
  evals.check_runner.SequentialRunnerTest.test_launcher_command_and_prompt_are_minimal_and_ephemeral \
  evals.check_runner.SequentialRunnerTest.test_two_plans_execute_sequentially_in_one_worktree -v
~~~

Expected: FAIL because _UsageFilter and --json do not exist and attempt events have no token fields.

- [ ] **Step 2: Implement a bounded line filter**

Add constants and this class to launcher.py:

~~~python
_JSON_EVENT_LINE_BYTES = 65_536
_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


class _UsageFilter:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._dropping = False
        self.usage: dict[str, int | None] = {
            name: None for name in _USAGE_FIELDS
        }

    def feed(self, chunk: bytes) -> None:
        for segment in chunk.splitlines(keepends=True):
            complete = segment.endswith((b"\n", b"\r"))
            if self._dropping:
                if complete:
                    self._dropping = False
                continue
            self._buffer.extend(segment)
            if len(self._buffer) > _JSON_EVENT_LINE_BYTES:
                self._buffer.clear()
                self._dropping = not complete
                continue
            if complete:
                self._consume(bytes(self._buffer).rstrip(b"\r\n"))
                self._buffer.clear()

    def finish(self) -> None:
        if self._buffer and not self._dropping:
            self._consume(bytes(self._buffer))
        self._buffer.clear()
        self._dropping = False

    def _consume(self, line: bytes) -> None:
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            return
        usage = event.get("usage")
        if not isinstance(usage, dict):
            return
        self.usage = {
            name: (
                value
                if isinstance((value := usage.get(name)), int)
                and not isinstance(value, bool)
                and value >= 0
                else None
            )
            for name in _USAGE_FIELDS
        }
~~~

The only retained content is four integers or null plus at most one bounded partial line.

- [ ] **Step 3: Separate stdout JSON from stderr diagnostics**

Add --json immediately after --ephemeral in _command.

Extend LaunchResult:

~~~python
duration_ms: int
input_tokens: int | None
cached_input_tokens: int | None
output_tokens: int | None
reasoning_output_tokens: int | None
launcher_prompt_bytes: int
~~~

In launch, encode the prompt once and start timing immediately before spawn:

~~~python
prompt_bytes = prompt.encode("utf-8")
started = time.monotonic()
usage = _UsageFilter()
~~~

Spawn with two pipes:

~~~python
process = subprocess.Popen(
    command,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    start_new_session=True,
    env=environment,
    pass_fds=(lock_fd,),
)
~~~

Register each stream with its sink:

~~~python
assert (
    process.stdin is not None
    and process.stdout is not None
    and process.stderr is not None
)
try:
    process.stdin.write(prompt_bytes)
    process.stdin.close()
except BrokenPipeError:
    process.stdin.close()
selector.register(
    process.stdout,
    selectors.EVENT_READ,
    usage.feed,
)
selector.register(
    process.stderr,
    selectors.EVENT_READ,
    log.write,
)
~~~

Replace each event write with:

~~~python
sink = key.data
chunk = os.read(key.fd, 65_536)
if chunk:
    sink(chunk)
else:
    selector.unregister(key.fileobj)
~~~

Replace every single-pipe drain branch with:

~~~python
_drain_registered(selector)
~~~

Change _drain_pipe to accept a byte consumer and add one helper for every
still-registered stream:

~~~python
def _drain_pipe(
    pipe: object,
    consume: Callable[[bytes], None],
) -> None:
    descriptor = pipe.fileno()  # type: ignore[attr-defined]
    while True:
        chunk = os.read(descriptor, 65_536)
        if not chunk:
            return
        consume(chunk)


def _drain_registered(selector: selectors.BaseSelector) -> None:
    for key in list(selector.get_map().values()):
        _drain_pipe(key.fileobj, key.data)
        selector.unregister(key.fileobj)
~~~

Import Callable from typing. In every timeout, normal-exit, and exception
cleanup branch, terminate the process group first when required and then call
_drain_registered(selector). In finally, close both stdout and stderr; after
the normal launch loop, call usage.finish. Return:

Remove the old pipe_open flag entirely. The selector map is the single source
of truth for which streams still require draining.

~~~python
duration_ms = max(0, round((time.monotonic() - started) * 1000))
return LaunchResult(
    payload=payload,
    returncode=returncode,
    timed_out=timed_out,
    forced_cleanup=forced_cleanup,
    discarded_log_bytes=log.discarded_bytes,
    result_path=result_path,
    log_path=log_path,
    duration_ms=duration_ms,
    input_tokens=usage.usage["input_tokens"],
    cached_input_tokens=usage.usage["cached_input_tokens"],
    output_tokens=usage.usage["output_tokens"],
    reasoning_output_tokens=usage.usage["reasoning_output_tokens"],
    launcher_prompt_bytes=len(prompt_bytes),
)
~~~

Update the local LaunchResult constructor in test_handoff_acceptance_and_result_isolation with zero or null values for the six new required fields.

- [ ] **Step 4: Emit deterministic JSON events and keep large logs on stderr**

Before writing the final result in fake_codex.py, emit:

~~~python
print(
    json.dumps(
        {
            "type": "item.completed",
            "item": {"text": "RAW_EVENT_SENTINEL"},
        }
    ),
    flush=True,
)
if scenario != "blocking_completed":
    print(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 41,
                    "cached_input_tokens": 31,
                    "output_tokens": 7,
                    "reasoning_output_tokens": 5,
                },
            }
        ),
        flush=True,
    )
~~~

Move the large_log bytes from stdout to stderr:

~~~python
sys.stderr.buffer.write(b"x" * 2_200_000)
sys.stderr.buffer.write(b"CPE_FINAL_LOG_MARKER\n")
sys.stderr.flush()
~~~

Leave blocking_completed without a turn.completed event. Its existing successful concurrent tests prove missing usage is non-blocking.

- [ ] **Step 5: Record filtered metrics on the existing event**

Extend only plan.attempt_finished:

~~~python
duration_ms=outcome.duration_ms,
input_tokens=outcome.input_tokens,
cached_input_tokens=outcome.cached_input_tokens,
output_tokens=outcome.output_tokens,
reasoning_output_tokens=outcome.reasoning_output_tokens,
launcher_prompt_bytes=outcome.launcher_prompt_bytes,
~~~

Do not add fields to state.json, result files, inspect output, or a new metrics artifact.

In check_cli.py, add --json to the installed flag tuple:

~~~python
for flag in (
    "--ephemeral",
    "--ignore-user-config",
    "--json",
    "--output-schema",
    "--output-last-message",
):
~~~

- [ ] **Step 6: Run only the focused parser and existing integration cases**

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_usage_filter_keeps_only_bounded_final_totals \
  evals.check_runner.SequentialRunnerTest.test_launcher_command_and_prompt_are_minimal_and_ephemeral \
  evals.check_runner.SequentialRunnerTest.test_two_plans_execute_sequentially_in_one_worktree \
  evals.check_runner.SequentialRunnerTest.test_concurrent_resume_does_not_launch_a_second_child \
  evals.check_runner.SequentialRunnerTest.test_large_log_retains_only_a_bounded_tail -v
~~~

Expected: 5 tests PASS. The completed blocking fixture has null usage without affecting acceptance, the raw sentinel is absent from log and events, and the large stderr tail remains bounded. Do not run the full gate.

- [ ] **Step 7: Commit**

~~~bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py \
  skills/kws-codex-plan-executor/evals/check_cli.py
git commit -m "feat(cpe): record filtered attempt usage"
~~~

---

### Task 5: Document The Contract And Run The Single Final Gate

**Files:**

- Modify: skills/kws-codex-plan-executor/README.md
- Modify: skills/kws-codex-plan-executor/SKILL.md
- Modify: skills/kws-codex-plan-executor/evals/check_cli.py

**Interfaces:**

- Consumes: Final launcher, runner, result schema, and eval behavior from Tasks 1 through 4.
- Produces: CPE skill version 1.2.0 and a documented lean-quality, recovery, usage, compatibility, and verification contract.

- [ ] **Step 1: Make the documentation contract test fail**

Replace the version assertion and extend the phrase list in test_skill_docs_match_hardened_public_contract:

~~~python
self.assertIn('version: "1.2.0"', skill)
for phrase in (
    "process group",
    "bounded",
    "run_busy",
    "initializing",
    "workflow receipt",
    "recovery capsule",
    "focused",
    "final HEAD",
    "usage",
    "Change Protocol",
):
    self.assertIn(phrase, skill + readme)
~~~

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_cli.SequentialCliTest.test_skill_docs_match_hardened_public_contract -v
~~~

Expected: FAIL because SKILL.md is version 1.1.0 and the new contract is not documented.

- [ ] **Step 2: Update the concise skill contract**

Set:

~~~yaml
metadata:
  version: "1.2.0"
  updated_at: "2026-07-15"
~~~

Replace the retry and ownership explanation with text that states all of the following:

- CPE launches one fresh plan controller and Superpowers owns task execution, review, fixes, cross-task final review, final verification, and commits.
- The controller uses file-backed briefs, reports, review packages, review files, and the progress ledger; compact returns stay in controller context.
- Task workers run focused verification, reviewers reuse evidence, and full verification runs once at final HEAD.
- Completed output requires the workflow receipt plus exact clean HEAD and successful verification.
- Recovery uses one private recovery capsule and occurs automatically only for interruption or retryable structured failure; blocked, non-retryable, integrity, and repeated-signature outcomes stop.
- Attempt-finished events may contain aggregate usage totals, which are not claimed as a root-versus-subagent split.

Keep the command examples and public exit behavior unchanged.

- [ ] **Step 3: Update README as the full source of truth**

Update these sections:

1. State And Results: document the optional result properties, completed-only workflow receipt requirement, safe relative artifact validation, historical readability, and unchanged format-1 state.
2. Operational Safety: document stdout JSON filtering, bounded stderr logs, and no retained raw JSON event transcript.
3. Completion, Failure, And Recovery: replace “initial plus one automatic attempt” with the conditional table from the design; document private capsule fields and resume semantics.
4. Add Lean Superpowers Contract: focused task verification, file-backed handoffs, consolidated fixes, delta review, one cross-task final review, one final full verification, and command/HEAD deduplication.
5. Limitations: receipt remains child-reported evidence; usage totals can aggregate root and subagents; a weak approved plan returns a plan-contract blocker instead of triggering invented broad tests.
6. Change Protocol: preserve the fifteen-second ceiling and twelve-second target.
7. Verify: state that evals/run.sh is the only complete behavioral gate and should run once at the final revision.

Do not claim that CPE independently proves review quality or root-controller token usage.

- [ ] **Step 4: Run the focused documentation test**

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_cli.SequentialCliTest.test_skill_docs_match_hardened_public_contract -v
~~~

Expected: 1 test PASS.

- [ ] **Step 5: Commit documentation before final verification**

~~~bash
git add \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/evals/check_cli.py
git commit -m "docs(cpe): document lean quality execution"
~~~

- [ ] **Step 6: Perform one whole-branch review**

Use one whole-branch review package from the design base commit through current HEAD. The reviewer checks only:

- cross-task interface consistency between launcher, runner, schema, fake child, and docs;
- unchanged public CLI and format-1 state;
- exact-HEAD, clean-worktree, process, locking, and log safety regressions;
- unresolved Critical or Important findings;
- accidental CPE ownership of task mapping, implementation, review, fixes, or product verification.

The reviewer must reuse the task reports and focused test evidence. It must not replay each task review or run the full gate. If it finds Critical or Important issues, resolve the entire finding set in one fix pass, run only affected tests, perform a delta review, and commit before Step 7.

- [ ] **Step 7: Run the complete final verification once at final HEAD**

Record final HEAD first:

~~~bash
cd /Users/kws/source/private/Archive
git rev-parse HEAD
~~~

Run:

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
/usr/bin/time -p ./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
cd /Users/kws/source/private/Archive
git diff --check
git status --short --branch --untracked-files=all
~~~

Expected:

- both deterministic suites pass;
- eval real time is below 15 seconds, with 12 seconds or less reported as the target outcome;
- Python compilation and shell syntax checks exit 0;
- all four help commands exit 0 and expose only current commands and flags;
- git diff --check prints nothing;
- the worktree is clean on the expected implementation branch.

Do not rerun an identical command at the same HEAD unless its first observation was an explicitly recorded transient infrastructure failure. If any code or documentation changes after this step, the final HEAD changed and the complete final verification must be run once at that new HEAD.

## Verification Ownership Summary

| Stage | Evidence owner | Allowed verification |
|---|---|---|
| Task 1 | Performance-task implementer | One pre-change timed gate and one post-change timed gate because timing is the deliverable |
| Task 2 | Receipt-task implementer | Two named runner tests |
| Task 3 | Recovery-task implementer | Seven named recovery and safety tests |
| Task 4 | Usage-task implementer | Five named parser and stream tests |
| Task 5 before commit | Documentation-task implementer | One named docs test |
| Final HEAD | Plan controller | One whole-branch review, then the complete gate once |

## Acceptance Trace

| Design requirement | Implemented by |
|---|---|
| Lazy specification reads and compact controller context | Task 2 prompt contract |
| File-backed briefs, reports, diffs, reviews, and ledger | Task 2 prompt and receipt |
| No task-level automatic full suite | Task 2 prompt; Task 5 docs |
| Reviewer evidence reuse, consolidated fixes, delta review | Task 2 prompt; Task 5 docs |
| Cross-task final review and one final verification | Task 2 prompt; Task 5 Steps 6-7 |
| No repeated command at one HEAD | Task 2 prompt; Task 5 final-run rule |
| Completed tasks not redispatched | Task 3 ledger capsule and recovery prompt |
| Conditional retry and repeated-signature stop | Task 3 decision helper and matrix |
| Valid workflow receipt bound to exact clean HEAD | Task 2 schema and runner validation |
| Filtered usage without raw event retention | Task 4 parser and stream separation |
| State format, CLI, process safety, inventory unchanged | Global constraints and Task 5 review |
| Below-15-second gate and 12-second target | Task 1 optimization and Task 5 timed gate |
