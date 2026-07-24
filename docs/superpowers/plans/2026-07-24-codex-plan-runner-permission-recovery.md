# Codex Plan Runner Permission-Free Operation and Bounded Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the incident remediation with non-interactive full-access Codex execution, narrow volatile-ref handling, equivalent-run refusal, two evidence-bounded repair commands, synchronized operations documentation, and final real-Codex proof.

**Architecture:** Treat sandbox mode and approval policy as separate controls: full access removes filesystem mediation while `--ignore-rules`, strict config, and approval-never remove repository approval prompts. Filter only two confirmed volatile Codex ref namespaces, preserve all product refs, reject equivalent active runs under a serialized intent lock, and expose repair only for two exact historical evidence shapes.

**Tech Stack:** uv-managed normal-GIL CPython 3.13 standard library, Git CLI, Codex CLI 0.144.1-compatible argv, existing runner state/lock/artifact APIs, `unittest`, Bun repository verification.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md`.
- Ordered prerequisite: `docs/superpowers/plans/2026-07-24-codex-plan-runner-core-correctness.md` must be complete, independently reviewed, and committed in the same runner worktree.
- The root provider must use `subagent-driven-development`; it coordinates but does not implement task code itself.
- For each task: one file-backed brief, one fresh implementer, RED/GREEN focused TDD, one narrow commit, one file-backed report, one diff package, one separate reviewer, Critical/Important fix loops, and one SDD-ledger update.
- Generate each brief with `/Users/kws/.codex/skills/subagent-driven-development/scripts/task-brief PLAN_FILE N`; name its report by replacing `-brief.md` with `-report.md`. Generate reviewer input with `/Users/kws/.codex/skills/subagent-driven-development/scripts/review-package BASE HEAD`, using the base recorded before dispatch rather than `HEAD~1`.
- Before dispatch, read `.superpowers/sdd/progress.md` when it exists. After clean spec and quality review, append `Task N: complete (commits <base7>..<head7>, review clean)` and never re-dispatch a completed task.
- Do not run implementers in parallel. Use `gpt-5.6-sol` for provider execution, ref integrity, admission, repair, integration review, and final review. `gpt-5.6-terra` is permitted only for mechanical documentation/test-fixture updates.
- Keep the solution light: no generic dirty-state adoption, no generalized run-family manager, no automatic TCC/Keychain approval, no new workspace-write transport, no global privacy subsystem, and no blanket volatile-ref exemption.
- Use `danger-full-access` for this remediation run. Never use `--dangerously-bypass-approvals-and-sandbox` or a hook-trust bypass.
- A repository rule prompt is independent of filesystem sandboxing. Initial and resumed Codex invocations must receive the same non-interactive flags.
- macOS TCC, Keychain, and other host GUI permissions are not auto-approved. Avoid protected GUI paths; if encountered, checkpoint once and classify `host_permission_blocked`.
- Preserve unrelated changes. The runner still does not merge, push, deploy, or repair a historical run unless separately requested.
- Use focused tests during tasks. Run the real-Codex canary once before the final gate. Run only `bun run agent:verify -- --base <merge-base> --head <candidate-head>` as the canonical broad final gate; do not separately run `./evals/run.sh` or `git diff --check`.

---

## Current-Controller Bootstrap Contract

The already-running controller cannot hot-reload provider changes made inside its worktree. Before invoking this ordered two-plan run, the outer controller must create a private, untracked bootstrap directory outside the repository with:

```text
/Users/kws/.codex/plan-runner-bootstrap/20260724-incident-remediation/
├── bin/codex
└── codex-home/auth.json
```

Create the wrapper with `apply_patch`, mode `0o700`, and this exact content:

```sh
#!/bin/sh
set -eu

REAL_CODEX=/opt/homebrew/bin/codex
BOOTSTRAP_CODEX_HOME=/Users/kws/.codex/plan-runner-bootstrap/20260724-incident-remediation/codex-home

if [ "${1-}" = "exec" ]; then
  shift
  CODEX_HOME="$BOOTSTRAP_CODEX_HOME" exec "$REAL_CODEX" exec \
    --ignore-rules \
    --strict-config \
    -c 'approval_policy="never"' \
    "$@"
fi

CODEX_HOME="$BOOTSTRAP_CODEX_HOME" exec "$REAL_CODEX" "$@"
```

Copy only the existing regular private `auth.json` into the bootstrap Codex home, mode `0o600`; do not copy config, rules, logs, history, or MCP state. Capture repository-local Git identity without embedding its value in this plan:

```bash
KPR_GIT_NAME="$(git config --get user.name)"
KPR_GIT_EMAIL="$(git config --get user.email)"
test -n "$KPR_GIT_NAME"
test -n "$KPR_GIT_EMAIL"
```

Launch every initial or external resume of the old controller with the same durable environment:

```bash
PATH="/Users/kws/.codex/plan-runner-bootstrap/20260724-incident-remediation/bin:$PATH" \
GIT_AUTHOR_NAME="$KPR_GIT_NAME" \
GIT_AUTHOR_EMAIL="$KPR_GIT_EMAIL" \
GIT_COMMITTER_NAME="$KPR_GIT_NAME" \
GIT_COMMITTER_EMAIL="$KPR_GIT_EMAIL" \
./skills/kws-codex-plan-runner/scripts/runner run \
  --workspace /Users/kws/source/private/Archive \
  --spec /Users/kws/source/private/Archive/docs/superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md \
  --plan /Users/kws/source/private/Archive/docs/superpowers/plans/2026-07-24-codex-plan-runner-core-correctness.md \
  --plan /Users/kws/source/private/Archive/docs/superpowers/plans/2026-07-24-codex-plan-runner-permission-recovery.md \
  --sandbox danger-full-access
```

Before the real run, use the same environment in a disposable repository to prove one provider start, one SDD collaboration event, one correctly attributed commit, and one completed root result. Keep the bootstrap directory until the remediation run reaches a terminal state. The final candidate canary must bypass this wrapper and call the candidate launcher directly.

## File Map

Modify:

```text
scripts/agent/
├── check-plan-runner-parity
└── fixtures/plan-runner-contract-v1.json

skills/kws-codex-plan-runner/
├── CHANGELOG.md
├── README.md
├── SKILL.md
├── evals/
│   ├── fake_codex.py
│   ├── test_contracts.py
│   ├── test_engine.py
│   ├── test_git_ops.py
│   ├── test_provider.py
│   ├── test_skill_contract.py
│   └── test_storage.py
└── scripts/
    ├── runner.py
    └── plan_runner/
        ├── contracts.py
        ├── engine.py
        ├── git_ops.py
        ├── provider.py
        └── storage.py

docs/operations/
├── 2026-07-24-codex-plan-runner-git-identity-isolation-incident.md
├── 2026-07-24-codex-plan-runner-progress-replay-and-duplicate-run-incident.md
├── 2026-07-24-codex-plan-runner-sandbox-and-volatile-ref-incidents.md
└── 2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md
```

Use this focused-test setup from the repository root:

```bash
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
```

## Task 1: Make Native Codex Execution Full-Access and Non-Interactive

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/provider.py`
- Modify: `scripts/agent/fixtures/plan-runner-contract-v1.json`
- Modify: `skills/kws-codex-plan-runner/evals/test_contracts.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_provider.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`

**Interfaces:**

- Changes: `CodexAdapter.build_argv(request)` applies the same policy to initial and resume invocations.
- Produces: a no-edit CLI capability preflight for required flags; precise `sandbox_capability_blocked` and `host_permission_blocked` classifications.
- Preserves: explicit session resume, model pass-through, helper add-dir, and selected sandbox value.

- [ ] **Step 1: Write failing exact-argv and permission tests**

Require this shared prefix in both initial and resume cases:

```python
[
    "codex",
    "exec",
    "--ignore-user-config",
    "--ignore-rules",
    "--strict-config",
    "-c",
    'approval_policy="never"',
    "--json",
]
```

Add these exact regressions:

- `test_full_access_ignores_repo_rules_and_never_requests_approval`: place a Git-prompt rule in a disposable repository, record fake CLI argv, and assert full access, ignore-rules, approval-never, and zero approval events.
- `test_resume_reuses_exact_noninteractive_flags`: compare the shared prefix of initial and explicit-session resume argv.
- `test_unsupported_required_cli_flag_blocks_before_provider_edits`: make the parse probe reject `--ignore-rules`, then assert no provider launch or worktree mutation.
- `test_workspace_write_helper_denial_is_sandbox_capability_blocked`: return a structured Unix-socket `EPERM` before edits and assert one terminal classification with no unchanged retry.
- `test_tcc_or_keychain_denial_is_host_permission_blocked`: return structured host-permission denial and assert no autonomous approval attempt.
- `test_permission_failure_after_edit_retains_task3_checkpoint`: dirty the worktree before the denial and assert the exact post-provider observation remains durable.

The repository-rule fixture must include a Git prompt rule that would trigger without `--ignore-rules`; the fake provider must record zero approval requests.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because current native argv does not ignore repository rules or enforce approval-never.

- [ ] **Step 3: Implement one shared argv prefix and bounded preflight**

Build initial and resumed argv from one function:

```python
def _exec_prefix(self) -> list[str]:
    return [
        self.executable,
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "-c",
        'approval_policy="never"',
        "--json",
    ]
```

Keep `--sandbox request.sandbox`, `--add-dir request.git_common_dir`, optional model, and either `-` or `resume <explicit-session-id> -` after the shared prefix.

Before any mutation-capable provider launch, run a bounded, no-prompt CLI parse probe using the exact required flags and `--help`. Cache success only for the executable identity and version observed in the current controller process. A parse failure blocks with `sandbox_capability_blocked` before provider work.

Classify structured sandbox/helper `EPERM`, `EACCES`, or denied Unix-socket capability as `sandbox_capability_blocked`. Classify macOS TCC, Keychain interaction, or protected GUI resource denial as `host_permission_blocked`. Do not retry either unchanged. If any failure arrives after an edit, preserve the exact Task 3 checkpoint and recommend a fresh session only after the operator resolves the host condition.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS with identical native policy on initial/resume, zero repository-rule approval requests, fail-fast unsupported flags, and checkpointed post-edit permission failures.

- [ ] **Step 5: Self-review and commit**

Confirm that full access does not weaken protected-ref, credential, identity, task, verification, or review gates.

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/provider.py \
  scripts/agent/fixtures/plan-runner-contract-v1.json \
  skills/kws-codex-plan-runner/evals/test_contracts.py \
  skills/kws-codex-plan-runner/evals/test_provider.py \
  skills/kws-codex-plan-runner/evals/test_engine.py
git commit -m "fix(plan-runner): make codex execution noninteractive"
```

## Task 2: Ignore Only Confirmed Volatile Codex Refs

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_git_ops.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`

**Interfaces:**

- Produces: `VOLATILE_REF_POLICY_VERSION = 1`, `is_volatile_ref(refname)`, `protected_refs(path, assigned_branch)`.
- Ignores only: `refs/codex/turn-diff/` and `refs/codex/turn-diff-base/`.
- Preserves: all branches, tags, notes, remotes, unknown `refs/codex/*`, and other refs as protected.

- [ ] **Step 1: Write failing ref-policy tests**

Add:

```python
def test_only_two_confirmed_turn_diff_namespaces_are_volatile(self):
    self.assertTrue(is_volatile_ref("refs/codex/turn-diff/abc"))
    self.assertTrue(is_volatile_ref("refs/codex/turn-diff-base/abc"))
    self.assertFalse(is_volatile_ref("refs/codex/other/abc"))
    self.assertFalse(is_volatile_ref("refs/heads/main"))
    self.assertFalse(is_volatile_ref("refs/tags/v1"))

def test_unknown_codex_ref_is_not_volatile(self):
    self.assertFalse(is_volatile_ref("refs/codex/other/abc"))
```

Also add `test_volatile_churn_does_not_break_resume_or_acceptance`, which mutates both confirmed prefixes between observations, and `test_unknown_codex_ref_and_product_ref_mutation_still_fail_closed`, which separately mutates `refs/codex/other/abc` and `refs/tags/product-test`.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_git_ops.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because current protected-ref snapshots include every Codex turn-diff ref.

- [ ] **Step 3: Centralize the versioned stable-ref view**

Implement:

```python
VOLATILE_REF_POLICY_VERSION = 1
_VOLATILE_REF_PREFIXES = (
    "refs/codex/turn-diff/",
    "refs/codex/turn-diff-base/",
)


def is_volatile_ref(refname: str) -> bool:
    return any(refname.startswith(prefix) for prefix in _VOLATILE_REF_PREFIXES)


def protected_refs(path: Path, assigned_branch: str) -> dict[str, str]:
    return {
        name: sha
        for name, sha in _all_refs(path).items()
        if name != f"refs/heads/{assigned_branch}" and not is_volatile_ref(name)
    }
```

Remove the duplicate engine-side ref filter and use this function for creation, resume, checkpoint safety, acceptance, and repair. Seal `volatile_ref_policy_version` in new immutable run config.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_git_ops.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS for ordinary Desktop turn-diff churn and fail-closed behavior for product and unknown refs.

- [ ] **Step 5: Self-review and commit**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-codex-plan-runner/evals/test_git_ops.py \
  skills/kws-codex-plan-runner/evals/test_engine.py
git commit -m "fix(plan-runner): narrow volatile codex refs"
```

## Task 3: Refuse Equivalent Runs Under One Intent Lock

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_storage.py`

**Interfaces:**

- Produces: `execution_intent_digest` sealed in immutable config and an intent-scoped lock.
- Digest inputs: canonical source repository/common directory, starting commit, ordered spec/plan role+digest list.
- Excludes: sandbox and model.
- Refusal output: existing run ID, status, worktree, branch, and exact recommended `inspect`/`resume` action.

- [ ] **Step 1: Write failing sequential and concurrent admission tests**

Add these exact tests:

- `test_same_inputs_with_different_sandbox_or_model_are_equivalent`: create one resumable run, vary only sandbox/model, and assert refusal with the first run ID.
- `test_terminal_run_does_not_block_a_new_equivalent_run`: mark the first state terminal and assert a new run ID is admitted.
- `test_concurrent_equivalent_creation_admits_at_most_one_run`: release two threads on one barrier and assert one creation plus one `matching_run_exists`.
- `test_same_files_in_different_order_are_not_equivalent`: reverse two plan inputs and assert the digest and admitted run differ.
- `test_refusal_names_existing_run_and_exact_next_command`: assert the bounded JSON response contains the existing branch/worktree and exact status-specific action.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because a UUID and worktree can currently be allocated before equivalent-run admission.

- [ ] **Step 3: Compute intent and serialize admission before run allocation**

Compute:

```python
execution_intent_digest = sha256_json(
    {
        "source_common_dir": str(common_directory),
        "starting_commit": starting_commit,
        "inputs": [
            {"role": item.role, "order": item.order, "sha256": item.sha256}
            for item in ordered_inputs
        ],
    }
)
```

Acquire a private intent lock derived from the digest, scan only bounded valid run roots, and refuse a match in `running`, `recovering`, or `resumable` before UUID, state, branch, worktree, or provider creation. Return a bounded contract response:

```json
{
  "reason": "matching_run_exists",
  "run_id": existing_run_id,
  "status": "resumable",
  "recommended_action": f"./skills/kws-codex-plan-runner/scripts/runner resume --run-id {existing_run_id}"
}
```

For `running` or `recovering`, recommend `inspect`; for `resumable`, recommend `resume`. Ignore terminal and invalid/tampered roots but keep scan bounds and private-root checks.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS with at most one admitted equivalent run and no orphan branch/worktree/state from the refused caller.

- [ ] **Step 5: Self-review and commit**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-codex-plan-runner/evals/test_engine.py \
  skills/kws-codex-plan-runner/evals/test_storage.py
git commit -m "fix(plan-runner): serialize equivalent run admission"
```

## Task 4: Add Two Narrow, Revision-Guarded Repair Commands

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/runner.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_storage.py`

**Interfaces:**

- Adds CLI: `repair --run-id ID --expected-revision N --repair-kind KIND --strategy-note TEXT [--attempt-id ID]`.
- Repair kinds: `volatile-codex-turn-refs`, `unsealed-provider-partial`.
- Produces: immutable repair audit artifact and one compare-and-swap state revision.
- Never produces: generic adoption, automatic reset/rebase, commit rewriting, ref deletion, merge, push, or provider launch.

- [ ] **Step 1: Write failing acceptance and adjacent-rejection tests**

Cover both accepted repair kinds and these exact rejection tests:

- `test_repair_rejects_stale_expected_revision`: advance one state revision before repair and assert no new artifact or state write.
- `test_volatile_repair_rejects_any_product_or_unknown_ref_delta`: mutate a tag and `refs/codex/other/test` in separate subtests.
- `test_partial_repair_rejects_clean_worktree_or_wrong_attempt`: test a clean worktree, unknown attempt, completed attempt, and mismatched mode.
- `test_partial_repair_rejects_branch_ancestry_or_input_drift`: test each proof independently and assert the refusal names the failed proof.
- `test_repair_is_idempotent_only_at_the_recorded_revision`: retry the same command after success and assert stale-revision refusal.
- `test_repair_never_launches_provider_or_mutates_git`: compare adapter call count, HEAD, refs, index, and worktree digest before and after repair.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because the CLI and engine repair API do not exist.

- [ ] **Step 3: Add the exact CLI surface**

Argparse choices:

```python
repair.add_argument("--run-id", required=True)
repair.add_argument("--expected-revision", required=True, type=int)
repair.add_argument(
    "--repair-kind",
    required=True,
    choices=("volatile-codex-turn-refs", "unsealed-provider-partial"),
)
repair.add_argument("--strategy-note", required=True)
repair.add_argument("--attempt-id")
```

Reject an empty/oversized strategy note and an attempt ID on the volatile kind. Require an attempt ID on the partial kind.

- [ ] **Step 4: Implement exact evidence gates**

For `volatile-codex-turn-refs`:

1. require failed integrity state and matching revision;
2. reconstruct the recorded and current ref maps;
3. prove every delta is beneath one of the two confirmed volatile prefixes;
4. prove branch, common directory, ancestry, worktree observation, inputs, and product refs are unchanged;
5. write the before/after/delta/policy/operator-note audit artifact;
6. authorize the versioned stable-ref comparison and transition to `resumable` with a fresh-session action.

For `unsealed-provider-partial`:

1. require matching revision and incomplete recorded mutation-capable attempt;
2. require the exact attempt ID/mode and a currently dirty worktree;
3. prove branch, common directory, ancestry, inputs, and stable refs;
4. record the current observation as `adopted_untrusted_partial`;
5. discard untrusted semantic completion claims and require a fresh session;
6. write the full repair audit and transition to `resumable`.

Use the existing run lock, artifact store, and revision update. If any proof is absent, return a precise refusal without mutating state.

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS for the two accepted shapes and every adjacent rejection.

- [ ] **Step 6: Self-review and commit**

```bash
git add skills/kws-codex-plan-runner/scripts/runner.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-codex-plan-runner/evals/test_engine.py \
  skills/kws-codex-plan-runner/evals/test_storage.py
git commit -m "feat(plan-runner): add bounded incident repair"
```

## Task 5: Synchronize Contracts, Run the Live Canary, and Finalize Evidence

**Files:**

- Modify: `skills/kws-codex-plan-runner/SKILL.md`
- Modify: `skills/kws-codex-plan-runner/README.md`
- Modify: `skills/kws-codex-plan-runner/CHANGELOG.md`
- Modify: `skills/kws-codex-plan-runner/evals/test_skill_contract.py`
- Modify: `scripts/agent/fixtures/plan-runner-contract-v1.json`
- Modify: `scripts/agent/check-plan-runner-parity`
- Modify: the four incident reports listed in Global Constraints
- Modify only if behavior is stale: other files under `docs/operations/`

**Interfaces:**

- Documents: Git identity, checkpoint-before-validation, root result, isolated auth, full-access/no-approval argv, volatile refs, equivalent admission, repairs, and residual host permissions.
- Verifies: candidate launcher without bootstrap shim, one root provider plus one SDD subagent, one correct commit, one helper verification, one root result.
- Produces: exact final candidate HEAD and one canonical `agent:verify` receipt.

- [ ] **Step 1: Write failing contract/documentation assertions**

Extend `test_skill_contract.py` and parity checks to require:

```text
subagent-driven-development
danger-full-access
approval_policy="never"
--ignore-rules
matching_run_exists
volatile-codex-turn-refs
unsealed-provider-partial
bun run agent:verify -- --base
```

Update the versioned fixture with the new failure taxonomy and any sealed policy-version fields.

- [ ] **Step 2: Run focused contract tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_skill_contract.py -v
./scripts/agent/check-plan-runner-parity
```

Expected: FAIL until runtime vocabulary, skill contract, docs, and fixture agree.

- [ ] **Step 3: Update skill and operations documentation**

Update `SKILL.md`, `README.md`, and `CHANGELOG.md` with exact commands and boundaries. For each of the four incident reports:

1. preserve the original forensic evidence;
2. link the design and both implementation plans;
3. record the implementation commit range;
4. map the incident to its focused regressions;
5. record the candidate live-canary result;
6. name the canonical final verification command;
7. state any deliberate residual boundary.

Review every remaining `docs/operations/` file against the final behavior:

```text
state-root-migration.md
codex-best-loop.md
codex-local-setup.md
plan-authoring.md
verification.md
recovery.md
2026-07-24-cpe-execution-ledger-invalid-and-authority-loss-incident.md
waygent.md
```

Change only a file whose command or behavior is made stale by this implementation. In the task report, record one disposition for every file: `updated: <reason>` or `reviewed-no-change: <reason>`. Do not perform unrelated wording cleanup.

- [ ] **Step 4: Run focused contract tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_skill_contract.py -v
./scripts/agent/check-plan-runner-parity
```

Expected: PASS with runtime, fixture, skill, README, changelog, and incident reports aligned.

- [ ] **Step 5: Self-review and commit documentation**

```bash
git add skills/kws-codex-plan-runner/SKILL.md \
  skills/kws-codex-plan-runner/README.md \
  skills/kws-codex-plan-runner/CHANGELOG.md \
  skills/kws-codex-plan-runner/evals/test_skill_contract.py \
  scripts/agent/fixtures/plan-runner-contract-v1.json \
  scripts/agent/check-plan-runner-parity \
  docs/operations
git commit -m "docs(plan-runner): close incident remediation contracts"
```

- [ ] **Step 6: Run one disposable real-Codex canary without the bootstrap wrapper**

Create a disposable repository outside the Archive worktree. Invoke the candidate launcher directly with:

```text
danger-full-access
approval_policy="never"
--ignore-rules
one root provider
one SDD subagent
one correctly attributed commit
one focused helper verification
one completed root turn
one final structured result
```

Assert zero approval prompts, no mutation to Archive product refs, no merge/push/deploy, and a clean disposable candidate. If the CLI has drifted from 0.144.1, stop before uncontrolled edits with the exact unsupported flag or classification; update implementation only through a focused TDD task amendment and re-review.

- [ ] **Step 7: Inspect the reported historical run read-only**

Compare its exact state/revision/worktree/refs against the two repair contracts. If one matches, report the exact `repair` command but do not execute it. If neither matches, report the missing proof and leave it untouched.

## Final Whole-Branch Review and Canonical Gate

- [ ] Build one whole-branch diff package from the run starting commit to candidate HEAD.
- [ ] Dispatch a fresh `gpt-5.6-sol` reviewer with the approved design, both plans, four incident reports, SDD ledger, task reports, review packages, focused test evidence, and live-canary evidence.
- [ ] Review against `code_review.md`, the root `AGENTS.md`, and the skill-local `AGENTS.md`.
- [ ] Fix and re-review every Critical or Important finding. Rerun only affected focused tests after fixes.
- [ ] Confirm every plan task is marked done, every required commit exists, and the worktree is clean.
- [ ] Start the runner's fresh finalization session at the final candidate HEAD.
- [ ] Execute exactly:

```bash
MERGE_BASE="$(git merge-base HEAD "$(git rev-parse --verify origin/main)")"
CANDIDATE_HEAD="$(git rev-parse HEAD)"
bun run agent:verify -- --base "$MERGE_BASE" --head "$CANDIDATE_HEAD"
```

Expected: PASS. This selected gate supplies the runner deterministic eval and repository diff check. Do not separately invoke `./evals/run.sh` or `git diff --check`.

- [ ] If final review changes candidate HEAD, invalidate the prior candidate receipt and run the canonical gate once at the replacement final HEAD.
- [ ] Record final HEAD, exact canonical command/result, focused tests, canary result, review verdicts, changed operations docs, skipped opt-in evidence, residual risks, and local-versus-remote state.
- [ ] Finish as `ready_for_integration`; do not merge, push, deploy, or execute historical repair.
