# Codex Plan Runner Core Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Codex provider attempt identity-safe, checkpoint-first, auth-capable, and valid only after a completed root turn without broadening the runner into a general recovery platform.

**Architecture:** Seal the repository Git identity into immutable run state, inject only that identity into the child environment, and validate every candidate commit. Persist the post-provider Git observation before parsing or trusting semantic output. Preserve the operator's effective `CODEX_HOME` so installed authentication and Superpowers remain discoverable while user config and repository rules stay ignored, and separate root lifecycle completion from collaboration-event noise.

**Tech Stack:** uv-managed normal-GIL CPython 3.13 standard library, Git CLI, Codex CLI JSONL, `unittest`, existing content-addressed runner state.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md`.
- Incident sources:
  - `docs/operations/2026-07-24-codex-plan-runner-git-identity-isolation-incident.md`
  - `docs/operations/2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md`
  - `docs/operations/2026-07-24-codex-plan-runner-progress-replay-and-duplicate-run-incident.md`
  - `docs/operations/2026-07-24-codex-plan-runner-sandbox-and-volatile-ref-incidents.md`
- This is ordered plan 1 of 2. Do not begin the permission/recovery plan until this plan is fully implemented and reviewed.
- Execute this plan directly from the current root session with `subagent-driven-development`. Do not use the current `kws-codex-plan-runner` to orchestrate its own fixes.
- Superpowers owns task decomposition, implementer dispatch, TDD, task review, and the SDD ledger. The runner implementation must not mirror individual subagent state or infer completion from collaboration events.
- The root controller coordinates but does not implement task code itself.
- Resolve this plan's Superpowers v6.2.0 workspace with `/bin/bash /Users/kws/.codex/skills/subagent-driven-development/scripts/sdd-workspace PLAN_FILE`. Use only its `progress.md`, whose first line identifies this plan. Treat an old flat `.superpowers/sdd/progress.md` as foreign state and leave it untouched.
- For each task: create a file-backed task brief, dispatch one fresh implementer, require RED/GREEN TDD and a narrow commit, collect a file-backed report, build a diff package from the recorded base commit, dispatch a separate reviewer, use the bounded v6.2.0 fix loop for every Critical or Important finding, then update this plan's SDD ledger.
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
- For fix rounds 1 through 3, resume the original implementer with `followup_task`. For rounds 4 and 5, dispatch a fresh, more capable implementer and provide the full task context, original report, latest review, and current diff package. After every round, use the scoped `re-review-prompt.md` and a fix-range review package. Stop after five rounds for controller adjudication: continue when the remaining item is non-load-bearing, but mark the plan blocked when correctness, safety, or an acceptance criterion remains unresolved.
- Do not run implementers in parallel. Use `gpt-5.6-terra` only for mechanical tests/docs and `gpt-5.6-sol` for Git integrity, state recovery, provider lifecycle, auth, non-trivial reviews, and final review.
- Git commits, file-backed task reports, focused test output, review verdicts, and the final direct-SDD handoff are authoritative for this implementation; the SDD ledger is recovery context only.
- Follow the v6.2.0 `writing-good-tests.md` guidance: runtime tests must prove observable behavior and fail for the intended reason. Source-string assertions are allowed only for an explicit public documentation or CLI vocabulary contract.
- Keep production code standard-library-only. Do not add a secrets scanner, transcript auditor, generic successor graph, run-family UI, or receipt optimizer.
- Preserve unrelated user changes and use `apply_patch` for tracked edits.
- Use only focused tests in this plan. Do not run `./evals/run.sh`, `git diff --check`, or `bun run agent:verify`; the canonical broad gate is reserved for the final candidate in ordered plan 2.
- Every task commit must include behavior, focused tests, and any directly affected contract fixture together.

---

## File Map

Modify:

```text
scripts/agent/fixtures/plan-runner-contract-v1.json

skills/kws-codex-plan-runner/
├── evals/
│   ├── fake_codex.py
│   ├── test_contracts.py
│   ├── test_engine.py
│   ├── test_git_ops.py
│   ├── test_provider.py
│   └── test_storage.py
└── scripts/plan_runner/
    ├── contracts.py
    ├── engine.py
    ├── git_ops.py
    ├── provider.py
    └── storage.py
```

Responsibilities:

- `git_ops.py`: bounded Git identity, child Git environment, candidate identity validation.
- `storage.py`: validation of the new immutable identity and checkpoint records.
- `engine.py`: preflight sealing, provider-attempt checkpoint ordering, resume authority.
- `provider.py`: effective Codex-home preservation, capability preflight, and root-turn/result lifecycle.
- `contracts.py`: precise failure reasons used by the new fail-closed paths.
- `fake_codex.py`: deterministic dirty/invalid/collaboration lifecycle fixtures.

Use this focused-test setup from the repository root:

```bash
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
```

## Task 1: Seal, Inject, and Validate Git Identity

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_git_ops.py`

**Interfaces:**

- Produces: `GitIdentity`, `configured_git_identity(path)`, `GitIdentity.as_dict()`, `GitIdentity.from_mapping(value)`, `validate_commit_identities(worktree, starting_commit, candidate_head, identity)`.
- Changes: `sanitized_child_env(source_env, provider_auth_prefixes, remotes, run_id, git_identity)` always sets author/committer identity and a non-interactive Git config overlay.
- Preserves: remote push blocking, credential scrubbing, exact worktree/common-directory checks.

- [ ] **Step 1: Write failing identity and sanitizer tests**

Add tests equivalent to:

```python
def test_configured_identity_is_bounded_and_required(self):
    self.assertEqual(
        configured_git_identity(self.repository),
        GitIdentity(name="Runner Test", email="runner@example.test"),
    )
    git("config", "--unset", "user.email", cwd=self.repository)
    with self.assertRaisesRegex(RuntimeError, "configured Git identity"):
        configured_git_identity(self.repository)

def test_child_environment_injects_only_sealed_identity(self):
    env = sanitized_child_env(
        {
            "PATH": "/usr/bin",
            "GIT_AUTHOR_NAME": "Ambient",
            "GIT_AUTHOR_EMAIL": "ambient@example.test",
            "GIT_CONFIG_COUNT": "99",
        },
        provider_auth_prefixes=("OPENAI_",),
        remotes=("origin",),
        run_id="run-1",
        git_identity=GitIdentity("Sealed Name", "sealed@example.test"),
    )
    self.assertEqual(env["GIT_AUTHOR_NAME"], "Sealed Name")
    self.assertEqual(env["GIT_COMMITTER_EMAIL"], "sealed@example.test")
    self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
    self.assertEqual(env["GCM_INTERACTIVE"], "Never")
    self.assertEqual(env["GIT_CONFIG_COUNT"], "5")

def test_candidate_commit_identity_must_match_sealed_identity(self):
    workspace = GitWorkspace.create(
        source=self.source,
        worktree=self.worktree,
        branch=self.branch,
    )
    git("-c", "user.name=Wrong", "-c", "user.email=wrong@example.test",
        "commit", "--allow-empty", "-m", "wrong", cwd=workspace.worktree)
    with self.assertRaisesRegex(RuntimeError, "commit identity mismatch"):
        validate_commit_identities(
            workspace.worktree,
            self.start,
            git("rev-parse", "HEAD", cwd=workspace.worktree).stdout.decode().strip(),
            GitIdentity("Runner Test", "runner@example.test"),
        )
```

- [ ] **Step 2: Run the focused file and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_git_ops.py -v
```

Expected: FAIL because `GitIdentity`, identity loading, and candidate validation do not exist and the sanitizer still trusts ambient identity.

- [ ] **Step 3: Implement the bounded identity contract**

Implement this shape in `git_ops.py`:

```python
MAX_GIT_IDENTITY_BYTES = 1024


@dataclass(frozen=True)
class GitIdentity:
    name: str
    email: str

    def __post_init__(self) -> None:
        for label, value in (("name", self.name), ("email", self.email)):
            if (
                not isinstance(value, str)
                or value != value.strip()
                or not value
                or len(value.encode("utf-8")) > MAX_GIT_IDENTITY_BYTES
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError(f"invalid Git identity {label}")

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "email": self.email}

    @classmethod
    def from_mapping(cls, value: object) -> "GitIdentity":
        if not isinstance(value, dict) or set(value) != {"name", "email"}:
            raise ValueError("invalid sealed Git identity")
        return cls(name=value["name"], email=value["email"])


def configured_git_identity(path: Path) -> GitIdentity:
    name = _output(_git(path, ("config", "--get", "user.name")), "Git user.name").decode().rstrip("\n")
    email = _output(_git(path, ("config", "--get", "user.email")), "Git user.email").decode().rstrip("\n")
    return GitIdentity(name=name, email=email)
```

Update the child overlay to set these exact keys before remote push-block entries:

```python
safe_config = (
    ("user.name", git_identity.name),
    ("user.email", git_identity.email),
    ("user.useConfigOnly", "true"),
    ("commit.gpgSign", "false"),
)
env["GIT_AUTHOR_NAME"] = git_identity.name
env["GIT_AUTHOR_EMAIL"] = git_identity.email
env["GIT_COMMITTER_NAME"] = git_identity.name
env["GIT_COMMITTER_EMAIL"] = git_identity.email
env["GIT_TERMINAL_PROMPT"] = "0"
env["GCM_INTERACTIVE"] = "Never"
```

Validate `%H%x00%an%x00%ae%x00%cn%x00%ce` for every commit in `starting_commit..candidate_head`; reject malformed output or any author/committer mismatch.

- [ ] **Step 4: Run the focused test and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_git_ops.py -v
```

Expected: PASS, including missing identity, control-character, inherited identity, signing suppression, and candidate mismatch cases.

- [ ] **Step 5: Self-review and commit**

Check that identity values are sealed exactly, not normalized after sealing, and that no `HOME`, credential, or signing source can override them.

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py \
  skills/kws-codex-plan-runner/evals/test_git_ops.py
git commit -m "fix(plan-runner): seal provider git identity"
```

## Task 2: Make Identity an Immutable Run and Acceptance Contract

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/provider.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_provider.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_storage.py`

**Interfaces:**

- Consumes: Task 1 `GitIdentity`, `configured_git_identity`, and `validate_commit_identities`.
- Changes: `ProviderRequest.git_identity`; `immutable_config["git_identity"]`.
- Guarantees: missing identity blocks before run-state/worktree/provider mutation; every initial/resume/final-review-fix request uses the sealed identity; every candidate acceptance validates its full new commit range.

- [ ] **Step 1: Write failing composition tests**

Cover these exact test cases:

- `test_missing_git_identity_blocks_before_state_worktree_or_provider`: unset `user.email`, call `create_run`, then assert no adapter call, run root, branch, or worktree exists.
- `test_identity_is_sealed_and_passed_to_every_provider_request`: inspect initial, resumed, and review-fix requests and compare all three to `GitIdentity("Engine Test", "engine@example.test")`.
- `test_candidate_with_wrong_committer_identity_fails_closed`: make the scripted adapter commit with `Wrong <wrong@example.test>` and assert `state_integrity_failed` plus no plan acceptance.
- `test_tampered_immutable_git_identity_is_rejected_on_open`: rewrite the test state fixture with an empty email, recompute only the outer fixture checksum, and assert state validation rejects it before adapter launch.

In `test_provider.py`, construct `ProviderRequest` with:

```python
git_identity=GitIdentity("Runner Test", "runner@example.test")
```

Assert initial and resumed requests receive the same identity and no request derives it from isolated `HOME`.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because run state and provider requests do not carry the sealed identity and acceptance does not inspect commit authorship.

- [ ] **Step 3: Seal identity before creating mutable run artifacts**

In `PlanRunner.create_run`, add the identity to the existing immutable mapping:

```python
git_identity = configured_git_identity(source_path)
immutable_config["git_identity"] = git_identity.as_dict()
```

This call must occur before run ID allocation, `StateStore.create`, branch creation, or worktree creation.

In state validation, require exactly:

```python
GitIdentity.from_mapping(immutable_config.get("git_identity"))
```

Build every `ProviderRequest` from:

```python
git_identity=GitIdentity.from_mapping(state["immutable_config"]["git_identity"])
```

After `require_clean_ancestor()` and before accepting an implemented plan or final candidate, call:

```python
validate_commit_identities(
    workspace.worktree,
    state["starting_commit"],
    candidate_head,
    GitIdentity.from_mapping(state["immutable_config"]["git_identity"]),
)
```

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS with the identity sealed once and enforced across implementation, resume, review-fix, and final acceptance.

- [ ] **Step 5: Self-review and commit**

Verify that an old state without the new immutable field fails closed unless a later explicit narrow repair authorizes it; do not silently infer identity during normal resume.

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/provider.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-codex-plan-runner/evals/test_engine.py \
  skills/kws-codex-plan-runner/evals/test_provider.py \
  skills/kws-codex-plan-runner/evals/test_storage.py
git commit -m "fix(plan-runner): enforce immutable commit identity"
```

## Task 3: Checkpoint Every Mutation-Capable Provider Attempt Before Validation

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Modify: `scripts/agent/fixtures/plan-runner-contract-v1.json`
- Modify: `skills/kws-codex-plan-runner/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_contracts.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_storage.py`

**Interfaces:**

- Produces: durable `attempt["post_provider_worktree"]`; bounded `failure["partial_worktree"]` when a safe dirty state exists.
- Produces: one small root-level next-strategy selector with only `resume_root`, `fresh_root_full_diff`, and `block` outcomes; it does not model SDD tasks.
- Changes: provider outcome checkpoint happens before semantic result validation in implementation and final-review-fix flows.
- Adds precise failure reasons: `provider_result_invalid`, `provider_stream_malformed`, `provider_stream_oversized`.
- Preserves: exact branch/common-directory/product-ref integrity remains mandatory before any dirty state becomes resumable.

- [ ] **Step 1: Write failing dirty-result regressions**

Add deterministic fake scenarios and these exact tests:

- `test_dirty_invalid_result_is_checkpointed_before_failure`: write `partial.txt`, emit a completed root turn and schema-invalid result, then assert the observation is durable before the failure revision.
- `test_dirty_malformed_stream_is_checkpointed_before_failure`: write `partial.txt`, emit malformed JSONL, then assert `provider_stream_malformed` and the exact dirty observation.
- `test_dirty_oversized_stream_is_checkpointed_before_failure`: write `partial.txt`, emit one line over the configured cap, then assert `provider_stream_oversized` and the exact dirty observation.
- `test_final_review_fix_failure_uses_the_same_checkpoint_order`: enter review-fix mode, dirty the worktree, emit an invalid result, and assert the same checkpoint fields and fresh-session action.
- `test_dirty_checkpoint_rejects_branch_or_product_ref_drift`: mutate the assigned branch or a protected test ref after editing and assert integrity failure without resumable adoption.
- `test_clean_transport_loss_resumes_root_once_then_changes_strategy`: retain an explicit session ID at a clean checkpoint, assert one `resume_root`, repeat the same transport failure, and assert `fresh_root_full_diff` rather than an unchanged retry.
- `test_safe_dirty_failure_uses_fresh_root_without_user_checkpoint`: preserve a safe dirty observation and assert the next action is a fresh root reviewing the complete diff with no routine approval state.
- `test_external_authority_or_unsafe_identity_blocks`: assert auth/host-permission requirements and identity/ref/path/digest drift choose `block` with a precise reason instead of being relabeled recoverable.

Each accepted dirty checkpoint must use the repository's existing
`WorktreeObservation` as its canonical identity. Capture one observation and
assert exact equality for its current fields:

```python
observation = workspace.observe()
{
    "head": observation.head,
    "branch": observation.branch,
    "porcelain_digest": observation.porcelain_digest,
    "tree_digest": observation.tree_digest,
    "clean": False,
}
```

and must prove that resume starts a fresh session from that exact observation rather than replaying the prior provider attempt.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because result validation currently runs before durable post-provider observation.

- [ ] **Step 3: Add one checkpoint helper and preserve evidence on failure**

Implement one engine helper with this behavior:

```python
def _checkpoint_provider_attempt(
    self,
    store: StateStore,
    workspace: GitWorkspace,
    *,
    attempt_id: str,
    outcome: ProviderOutcome,
    mode: str,
) -> dict[str, object]:
    workspace.require_identity()
    observation = workspace.observe()
    payload = dataclasses.asdict(observation)
    with store.update() as state:
        attempt = self._require_attempt(state, attempt_id)
        attempt["completed"] = True
        attempt["outcome"] = outcome.kind
        attempt["provider_code"] = outcome.provider_code
        attempt["session_id"] = outcome.session_id
        attempt["post_provider_worktree"] = payload
        if observation.dirty:
            state["failure"] = {
                **(state.get("failure") or {}),
                "partial_worktree": payload,
                "partial_attempt_id": attempt_id,
                "partial_mode": mode,
                "next_session_action": "fresh_session",
            }
    return payload
```

Use the repository's existing state update API and exact observation serializer rather than adding an alternate state writer.

Call the helper immediately after every mutation-capable provider launch and Git identity/protected-ref safety check, before `_validated_plan_result`, finalization-result parsing, or failure classification. Update `_fail_closed` so it merges bounded checkpoint fields instead of overwriting them.

Allow dirty resume only for the explicit sealed outcomes introduced here plus `controller_stopped`; reject observation drift, wrong attempt ID, wrong mode, branch/ref drift, or a clean/dirty mismatch.

Add one table-driven selector after checkpointing:

- choose `resume_root` once when the checkpoint is clean, an explicit root
  session exists, and the failed boundary is transport-only;
- choose `fresh_root_full_diff` for a safe dirty checkpoint, a lost session, or
  the same clean transport boundary after its one resume;
- choose `block` only when new external authority is required or identity, ref,
  path, digest, state, or a load-bearing acceptance invariant is unsafe.

Record the selected action and the previous failed strategy in the existing
attempt/failure payload; do not add a workflow graph or SDD-task database. A
fresh root receives the exact checkpoint and failure evidence and returns to
the normal Superpowers path.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS for all dirty invalid/malformed/oversized cases, review-fix composition, exact resume, changed-strategy recovery, approval-free safe continuation, and unsafe-ref rejection.

- [ ] **Step 5: Self-review and commit**

Confirm that “checkpointed” never means “trusted”: semantic completion still requires a valid result, clean candidate, ancestry, protected refs, identity, task ledger, and evidence.

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  scripts/agent/fixtures/plan-runner-contract-v1.json \
  skills/kws-codex-plan-runner/evals/fake_codex.py \
  skills/kws-codex-plan-runner/evals/test_contracts.py \
  skills/kws-codex-plan-runner/evals/test_engine.py \
  skills/kws-codex-plan-runner/evals/test_storage.py
git commit -m "fix(plan-runner): checkpoint provider mutations first"
```

## Task 4: Preserve Codex Capabilities and Require a Completed Root Turn

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/provider.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Modify: `skills/kws-codex-plan-runner/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_provider.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`

**Interfaces:**

- Produces: an effective-Codex-home resolver and preflight that preserve the existing `CODEX_HOME` without copying it into runner state.
- Changes: provider stream parsing returns a precise stream error and `root_turn_completed`; structured output is accepted only after the root turn completes.
- Preserves: environment-based OpenAI credentials, bounded stderr, immediate session-ID callback, and collaboration activity accounting without storing a second per-subagent task model.

- [ ] **Step 1: Write failing capability and lifecycle tests**

Add these exact tests:

- `test_effective_codex_home_preserves_auth_and_superpowers_discovery`: point `CODEX_HOME` at a fixture containing a fake auth marker and the required SDD entrypoint, launch the fake executable, and assert both remain visible through the original path.
- `test_environment_token_auth_still_uses_effective_codex_home_for_superpowers`: supply `OPENAI_API_KEY=test-token`, omit file-backed auth, and assert the required SDD entrypoint remains discoverable.
- `test_missing_auth_or_sdd_capability_fails_before_child_launch`: independently omit authentication and the required SDD workflow, then assert `provider_auth_blocked` or `provider_capability_blocked` without child launch.
- `test_child_does_not_copy_codex_home_into_runner_state`: include config, rules, session history, and logs beside the fixture skill, then assert no Codex-home content appears under runner artifacts.
- `test_child_argv_ignores_user_config_and_repository_rules`: assert initial and resumed argv contain `--ignore-user-config` and `--ignore-rules`.
- `test_subagent_completion_does_not_replace_root_completion`: emit a collaboration completion before root completion and assert no result is accepted at that point.
- `test_result_without_completed_root_turn_is_transport_failure`: write a valid result file but omit root `turn.completed`; assert `controller_transport_failed`.
- `test_root_and_collaboration_events_accept_one_root_final_result`: interleave collaboration events, complete the root turn, and assert exactly one structured root result is accepted.

These tests must exercise observable launch behavior rather than merely search source text for flag or path strings.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because the isolated child home currently hides installed Superpowers and result acceptance does not require an unambiguous completed root turn.

- [ ] **Step 3: Preserve the effective Codex home and preflight capabilities**

Resolve the effective operator `CODEX_HOME` before replacing `HOME`. Pass that existing path to the child so installed authentication and Superpowers skills remain discoverable. Do not copy or mirror auth, config, rules, skills, session history, logs, or MCP state into runner state.

Preserve the existing environment-token allowlist. Before implementation edits, prove that an allowed authentication route exists and that the required Superpowers v6.2.0 SDD entrypoints are readable. Classify missing authentication as `provider_auth_blocked` and missing SDD capability as `provider_capability_blocked`. Keep `--ignore-user-config` and `--ignore-rules` on initial and resumed invocations so preserving `CODEX_HOME` does not re-enable operator config or repository execpolicy behavior.

- [ ] **Step 4: Track root lifecycle separately from collaboration events**

Return a structured parse result equivalent to:

```python
@dataclass(frozen=True)
class StreamSummary:
    session_id: str | None
    provider_code: str | None
    root_turn_completed: bool
    stream_error: str | None
```

Map malformed JSONL and per-line overflow separately. Refresh activity for valid root and collaboration lifecycle events, but only a root `turn.completed` authorizes `_read_result()`. A subagent completion, commentary item, or result-shaped collaboration event must never substitute for the root final result. Do not persist or reconstruct individual SDD subagent state in runner state; Superpowers task reports and the SDD ledger remain opaque workflow evidence.

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS for file and token auth discovery, Superpowers discovery, absent-capability rejection, config/rules isolation, root/subagent interleaving, malformed stream, oversized stream, resume, and structured result validation.

- [ ] **Step 6: Self-review and commit**

Ensure error messages never include auth or skill content, that missing/invalid auth classifies as `provider_auth_blocked`, and that missing Superpowers classifies as `provider_capability_blocked` rather than prompting.

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/provider.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-codex-plan-runner/evals/fake_codex.py \
  skills/kws-codex-plan-runner/evals/test_provider.py \
  skills/kws-codex-plan-runner/evals/test_engine.py
git commit -m "fix(plan-runner): preserve capabilities and root results"
```

## Plan 1 Completion Review

- [ ] Build one whole-plan diff package by calling `review-package PLAN_FILE PLAN_START_HEAD CURRENT_HEAD EXPLICIT_OUTPUT` through `/bin/bash` as defined in Global Constraints.
- [ ] Dispatch a fresh `gpt-5.6-sol` reviewer against the approved design, this plan, all four incident reports, and the diff package.
- [ ] Fix and re-review every Critical or Important finding; rerun only affected focused test files.
- [ ] Confirm the worktree is clean and all four task commits are present.
- [ ] Confirm this plan's ledger identifies this plan on its first line and contains exactly one clean entry for each of Task 1 through Task 4.
- [ ] Record exact HEAD, focused test commands/results, reviewer verdicts, residual findings, and ordered-plan handoff in the SDD ledger.
- [ ] After the final review is clean, delete only this plan's SDD workspace. Preserve the implementation and review history in Git; do not delete the second plan's workspace or any old flat ledger.
- [ ] Continue directly to `2026-07-24-codex-plan-runner-permission-recovery.md`; do not merge, push, deploy, or run the canonical broad gate.
