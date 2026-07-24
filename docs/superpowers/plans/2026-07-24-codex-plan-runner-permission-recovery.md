# Codex Plan Runner Permission-Free Operation and Bounded Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the incident remediation with non-interactive full-access Codex execution, narrow volatile-ref handling, equivalent-run refusal, two evidence-bounded repair commands, synchronized operations documentation, and final real-Codex proof.

**Architecture:** Treat sandbox mode and approval policy as separate controls: full access removes filesystem mediation while `--ignore-rules`, strict config, and approval-never remove repository approval prompts. Filter only two confirmed volatile Codex ref namespaces, preserve all product refs, reject equivalent active runs under a serialized intent lock, and expose repair only for two exact historical evidence shapes.

**Tech Stack:** uv-managed normal-GIL CPython 3.13 standard library, Git CLI, Codex CLI 0.144.1-compatible argv, existing runner state/lock/artifact APIs, `unittest`, Bun repository verification.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md`.
- Ordered prerequisite: `docs/superpowers/plans/2026-07-24-codex-plan-runner-core-correctness.md` must be complete, independently reviewed, and committed in the same direct-SDD worktree.
- Execute this plan directly from the current root session with `subagent-driven-development`. Do not use the current `kws-codex-plan-runner` to orchestrate its own fixes.
- Superpowers owns task decomposition, implementer dispatch, TDD, task review, and the SDD ledger. The runner remains a thin boundary wrapper and must not mirror individual subagent state.
- The root controller coordinates but does not implement task code itself.
- Resolve this plan's Superpowers v6.2.0 workspace with `/bin/bash /Users/kws/.codex/skills/subagent-driven-development/scripts/sdd-workspace PLAN_FILE`. Use only its `progress.md`, whose first line identifies this plan. Treat an old flat `.superpowers/sdd/progress.md` as foreign state and leave it untouched.
- For each task: one file-backed brief, one fresh implementer, RED/GREEN focused TDD, one narrow commit, one file-backed report, one diff package, one separate reviewer, the bounded v6.2.0 Critical/Important fix loop, and one plan-scoped SDD-ledger update.
- The installed v6.2.0 helper files may lack executable mode. Never chmod or rewrite the global skill. Invoke helpers through `/bin/bash`, and pass explicit output paths so `task-brief` and `review-package` do not internally execute a non-executable sibling helper:

  ```bash
  SDD_SCRIPTS=/Users/kws/.codex/skills/subagent-driven-development/scripts
  PLAN_WORKSPACE="$(/bin/bash "$SDD_SCRIPTS/sdd-workspace" "$PLAN_FILE")"
  BRIEF="$PLAN_WORKSPACE/task-${TASK_NUMBER}-brief.md"
  PACKAGE="$PLAN_WORKSPACE/review-${BASE:0:7}..${HEAD:0:7}.diff"
  /bin/bash "$SDD_SCRIPTS/task-brief" "$PLAN_FILE" "$TASK_NUMBER" "$BRIEF"
  /bin/bash "$SDD_SCRIPTS/review-package" "$PLAN_FILE" "$BASE" "$HEAD" "$PACKAGE"
  ```

  Name the implementer report by replacing `-brief.md` with `-report.md`, and always use the base recorded before dispatch rather than `HEAD~1`.
- After clean spec and quality review, append the standard `Task N: complete (commits <base7>..<head7>, review clean)` entry to this plan's ledger and never re-dispatch a completed task.
- For fix rounds 1 through 3, resume the original implementer with `followup_task`. For rounds 4 and 5, dispatch a fresh, more capable implementer with full task and review context. After each round, use the scoped `re-review-prompt.md` and a fix-range review package. Stop after five rounds for controller adjudication: continue when the remainder is non-load-bearing, but block when correctness, safety, or an acceptance criterion remains unresolved.
- Do not run implementers in parallel. Use `gpt-5.6-sol` for provider execution, ref integrity, admission, repair, integration review, and final review. `gpt-5.6-terra` is permitted only for mechanical documentation/test-fixture updates.
- Follow the v6.2.0 `writing-good-tests.md` guidance: runtime tests must prove observable behavior and fail for the intended reason. Source-string assertions are limited to the explicit public skill, README, changelog, and CLI vocabulary contract.
- Keep the solution light: no generic dirty-state adoption, no generalized run-family manager, no automatic TCC/Keychain approval, no new workspace-write transport, no global privacy subsystem, and no blanket volatile-ref exemption.
- Use `danger-full-access` for the disposable candidate canary. The implementation itself runs directly in the current approved full-access SDD session. Never use `--dangerously-bypass-approvals-and-sandbox` or a hook-trust bypass.
- A repository rule prompt is independent of filesystem sandboxing. Initial and resumed Codex invocations must receive the same non-interactive flags.
- macOS TCC, Keychain, and other host GUI permissions are not auto-approved. Avoid protected GUI paths; if encountered, checkpoint once and classify `host_permission_blocked`.
- Normal execution stays entirely inside Superpowers. The runner changes strategy only after an external boundary failure: preserve the latest checkpoint, classify the observed state, change one relevant strategy dimension, and resume the same goal. It must not repeat an unchanged failure or replace Superpowers' internal task/review loop.
- Recoverable unexpected failures do not create user approval checkpoints. The runner continues autonomously through a bounded resume, fresh-root review, or alternate verification route. It stops only when external authority is required or identity, ref, path, digest, state, or a load-bearing acceptance invariant cannot be established safely.
- Preserve unrelated changes. The runner still does not merge, push, deploy, or repair a historical run unless separately requested.
- Use focused tests during tasks. Run the real-Codex canary once before the final gate. Run only `bun run agent:verify -- --base <merge-base> --head <candidate-head>` as the canonical broad final gate; do not separately run `./evals/run.sh` or `git diff --check`.

---

## Direct SDD Execution Contract

The already-running controller cannot hot-reload provider changes made inside
its own worktree. Do not create a PATH shim, bootstrap Codex home, or parallel
runner state to work around that limitation.

Execute both ordered plans directly with `subagent-driven-development` in one
isolated worktree. The candidate launcher is the system under test only after
the focused runtime tasks and reviews are complete. Its one disposable canary
uses a minimal Superpowers task, one SDD subagent, one commit, and one helper
verification. A canary failure returns to the single affected focused TDD task;
it does not start another full implementation run.

Inside a candidate run, the wrapper is a strategic recovery shell, not a second
workflow engine. It lets Superpowers run normally, observes only the root
session, Git checkpoints, and declared evidence, and intervenes only when an
external boundary fails. Each intervention must name the evidence, the changed
strategy, and the condition for returning to the normal Superpowers path.

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
- Ignores only: `refs/codex/turn-diffs/captures/` and `refs/codex/turn-diffs/checkpoints/`.
- Preserves: all branches, tags, notes, remotes, unknown `refs/codex/*`, and other refs as protected.

- [ ] **Step 1: Write failing ref-policy tests**

Add:

```python
def test_only_two_confirmed_turn_diff_namespaces_are_volatile(self):
    self.assertTrue(is_volatile_ref("refs/codex/turn-diffs/captures/abc"))
    self.assertTrue(is_volatile_ref("refs/codex/turn-diffs/checkpoints/abc"))
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
    "refs/codex/turn-diffs/captures/",
    "refs/codex/turn-diffs/checkpoints/",
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
- `test_failed_or_ready_equivalent_run_is_not_replayed`: cover retryable failed, known repairable integrity failure, unknown integrity failure, and `ready_for_integration`; assert each points to the existing run or fails closed without allocating a new run.
- `test_concurrent_equivalent_creation_admits_at_most_one_run`: release two threads on one barrier and assert one creation plus one `matching_run_exists`.
- `test_same_files_in_different_order_are_not_equivalent`: reverse two plan inputs and assert the digest and admitted run differ.
- `test_refusal_names_existing_run_and_exact_next_command`: cover `running`, `recovering`, `resumable`, `blocked`, retryable `failed`, known repairable failure, and `ready_for_integration`; assert the bounded response contains the existing branch/worktree and the design's exact status-specific action.
- `test_matching_tampered_root_fails_closed`: leave the intent digest readable but invalidate the matching state and assert no UUID, branch, worktree, or provider is created.

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

Acquire a private intent lock derived from the digest and scan bounded run
roots before UUID, state, branch, worktree, or provider creation. A valid match
in any current run status is handled through the design's state-specific action
instead of creating another run. If a bounded root exposes the same intent
digest but fails full state validation, preserve it and fail closed rather than
ignoring it. Return a bounded contract response:

```json
{
  "reason": "matching_run_exists",
  "run_id": existing_run_id,
  "status": "resumable",
  "recommended_action": f"./skills/kws-codex-plan-runner/scripts/runner resume --run-id {existing_run_id}"
}
```

Use this exact action policy:

| Existing state | Action |
| --- | --- |
| `running` or `recovering` | `inspect --run-id ID` |
| `resumable` | `resume --run-id ID` |
| `blocked` | fix the named blocker, then `resume --run-id ID --retry-blocked` |
| retryable `failed` | `resume --run-id ID --retry-failed --strategy-note TEXT` |
| known repairable integrity failure | the exact revision-guarded `repair` command from Task 4 |
| `ready_for_integration` | `inspect --run-id ID` |
| matching but invalid, tampered, or unproven state | preserve evidence and fail closed |

Unrelated invalid roots that do not claim the same intent remain ignored within
the existing scan bounds and private-root checks.

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

- Documents: Git identity, checkpoint-before-validation, root result, effective Codex-home and Superpowers discovery, full-access/no-approval argv, volatile refs, equivalent admission, strategic external-failure recovery, repairs, and residual host permissions.
- Verifies: candidate launcher as the system under test rather than the implementation controller, with one root provider, one SDD subagent, one correct commit, one helper verification, and one root result.
- Produces: exact final candidate HEAD and one canonical direct `agent:verify` result.

- [ ] **Step 1: Write failing contract/documentation assertions**

Extend `test_skill_contract.py` and parity checks to require:

```text
subagent-driven-development
thin wrapper
Superpowers v6.2.0
strategic recovery shell
danger-full-access
approval_policy="never"
--ignore-rules
matching_run_exists
volatile-codex-turn-refs
unsealed-provider-partial
bun run agent:verify -- --base
```

Update the versioned fixture with the new failure taxonomy and any sealed policy-version fields. Require the public contract to say that Superpowers owns SDD task orchestration and the runner does not mirror individual subagent state.

- [ ] **Step 2: Run focused contract tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_skill_contract.py -v
./scripts/agent/check-plan-runner-parity
```

Expected: FAIL until runtime vocabulary, skill contract, docs, and fixture agree.

- [ ] **Step 3: Update the public runner contract**

Update `SKILL.md`, `README.md`, and `CHANGELOG.md` with exact commands and boundaries. State that:

- Superpowers owns task decomposition, SDD dispatch, TDD, task review, and its ledger;
- the runner owns immutable inputs, one worktree, root launch/resume, checkpoint-before-result handling, and final evidence;
- collaboration events are bounded activity signals, not a second task database;
- the effective `CODEX_HOME` remains visible so installed authentication and Superpowers are available, while `--ignore-user-config` and `--ignore-rules` keep execution deterministic;
- Superpowers v6.2.0 owns its plan-scoped workspace, task briefs, review packages, bounded fix loop, and workspace cleanup; the runner does not parse or migrate those internals;
- unexpected external errors trigger a bounded evidence-based strategy change and autonomous resume of the same goal; the wrapper blocks only for missing authority or an unprovable load-bearing invariant;
- the only volatile refs are `refs/codex/turn-diffs/captures/` and `refs/codex/turn-diffs/checkpoints/`;
- recovery remains limited to the state-specific actions and two repair kinds in this plan.

- [ ] **Step 4: Run focused contract tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_skill_contract.py -v
./scripts/agent/check-plan-runner-parity
```

Expected: PASS with runtime, fixture, skill, README, and changelog aligned on the thin-wrapper contract.

- [ ] **Step 5: Self-review and commit the public contract**

```bash
git add skills/kws-codex-plan-runner/SKILL.md \
  skills/kws-codex-plan-runner/README.md \
  skills/kws-codex-plan-runner/CHANGELOG.md \
  skills/kws-codex-plan-runner/evals/test_skill_contract.py \
  scripts/agent/fixtures/plan-runner-contract-v1.json \
  scripts/agent/check-plan-runner-parity
git commit -m "docs(plan-runner): document thin wrapper contract"
```

- [ ] **Step 6: Run one minimal disposable real-Codex canary**

Create a disposable repository outside the Archive worktree. Invoke the candidate launcher directly, but only as the system under test, with:

```text
danger-full-access
approval_policy="never"
--ignore-rules
one minimal Superpowers task
one v6.2.0 plan-scoped SDD workspace
one root provider
one SDD subagent
one correctly attributed commit
one focused helper verification
one completed root turn
one final structured result
```

Assert that the installed Superpowers workflow is discovered through the effective `CODEX_HOME`, the task runs in the v6.2.0-compatible plan-scoped workspace, public helper signatures and cleanup work, the runner never parses that workspace as product state, zero approval prompts occur, no Archive product ref changes, no merge/push/deploy occurs, and the disposable candidate is clean. Judge compatibility by those capabilities rather than an exact version-string equality check. Do not compare two full workflows or run another Archive implementation. If the CLI or Superpowers public workflow has drifted incompatibly, stop before uncontrolled edits with the exact unsupported flag or capability classification; update only the affected focused TDD task and re-review it.

- [ ] **Step 7: Update incident and operations documentation with observed evidence**

For each of the four incident reports:

1. preserve the original forensic evidence;
2. link the design and both implementation plans;
3. record the implementation commit range;
4. map the incident to its focused regressions;
5. record the observed candidate live-canary result;
6. name the canonical final verification command;
7. state any deliberate residual boundary.

At implementation start, enumerate the actual operations library with
`rg --files docs/operations | sort`, then review every resulting file against
the final behavior. Change only a file whose command or behavior is made stale
by this implementation. In the task report, record one disposition for every
file: `updated: <reason>` or `reviewed-no-change: <reason>`. If a file exists
only as unrelated concurrent or untracked work outside the assigned worktree,
inspect it read-only and record `reviewed-no-change` without copying or staging
it. Do not perform unrelated wording cleanup.

- [ ] **Step 8: Verify documentation after the canary evidence is recorded**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_skill_contract.py -v
./scripts/agent/check-plan-runner-parity
bun run scripts/agent/check-markdown-links.ts \
  skills/kws-codex-plan-runner/SKILL.md \
  skills/kws-codex-plan-runner/README.md \
  docs/operations
```

Expected: PASS with the actual canary outcome and operations dispositions recorded.

- [ ] **Step 9: Commit the incident evidence**

```bash
git add \
  docs/operations/2026-07-24-codex-plan-runner-git-identity-isolation-incident.md \
  docs/operations/2026-07-24-codex-plan-runner-progress-replay-and-duplicate-run-incident.md \
  docs/operations/2026-07-24-codex-plan-runner-sandbox-and-volatile-ref-incidents.md \
  docs/operations/2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md
git commit -m "docs(plan-runner): close incident remediation evidence"
```

If Step 7 changed another already tracked operations guide, add that exact path
to the command. Never stage the whole directory or copy an unrelated untracked
document into the candidate.

- [ ] **Step 10: Inspect the reported historical run read-only**

Compare its exact state/revision/worktree/refs against the two repair contracts. If one matches, report the exact `repair` command but do not execute it. If neither matches, report the missing proof and leave it untouched.

## Final Whole-Branch Review and Canonical Gate

- [ ] Build one whole-branch diff package by calling `review-package PLAN_FILE BRANCH_START_HEAD CANDIDATE_HEAD EXPLICIT_OUTPUT` through `/bin/bash` as defined in Global Constraints.
- [ ] Dispatch a fresh `gpt-5.6-sol` reviewer with the approved design, both plans, four incident reports, Git history for the already-cleaned Plan 1 workspace, this plan's ledger and task reports, review packages, focused test evidence, and live-canary evidence.
- [ ] Review against `code_review.md`, the root `AGENTS.md`, and the skill-local `AGENTS.md`.
- [ ] Fix and re-review every Critical or Important finding. Rerun only affected focused tests after fixes.
- [ ] Confirm all four Plan 1 task commits and all five Plan 2 task commits exist, this plan's ledger identifies this plan on its first line and contains exactly one clean entry for Task 1 through Task 5, and the worktree is clean.
- [ ] Execute this canonical gate directly from the SDD worktree:

```bash
MERGE_BASE="$(git merge-base HEAD "$(git rev-parse --verify origin/main)")"
CANDIDATE_HEAD="$(git rev-parse HEAD)"
bun run agent:verify -- --base "$MERGE_BASE" --head "$CANDIDATE_HEAD"
```

Expected: PASS. This selected gate supplies the runner deterministic eval and repository diff check. Do not separately invoke `./evals/run.sh` or `git diff --check`.

- [ ] If final review or a canary repair changes candidate HEAD, invalidate the prior candidate evidence and run the canonical gate once at the replacement final HEAD.
- [ ] Record final HEAD, exact canonical command/result, focused tests, canary result, review verdicts, changed operations docs, skipped opt-in evidence, residual risks, and local-versus-remote state.
- [ ] After final review and canonical evidence are clean, delete only this plan's SDD workspace. Preserve all durable evidence in Git and leave old flat or unrelated plan workspaces untouched.
- [ ] Finish as `ready_for_integration`; do not merge, push, deploy, or execute historical repair.
