# Codex Plan Runner Core Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Codex provider attempt identity-safe, checkpoint-first, auth-capable, and valid only after a completed root turn without broadening the runner into a general recovery platform.

**Architecture:** Seal the repository Git identity into immutable run state, inject only that identity into an isolated child environment, and validate every candidate commit. Persist the post-provider Git observation before parsing or trusting semantic output. Keep Codex authentication narrowly provisioned into the isolated home, and separate root lifecycle completion from collaboration-event noise.

**Tech Stack:** uv-managed normal-GIL CPython 3.13 standard library, Git CLI, Codex CLI JSONL, `unittest`, existing content-addressed runner state.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md`.
- Incident sources:
  - `docs/operations/2026-07-24-codex-plan-runner-git-identity-isolation-incident.md`
  - `docs/operations/2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md`
  - `docs/operations/2026-07-24-codex-plan-runner-progress-replay-and-duplicate-run-incident.md`
  - `docs/operations/2026-07-24-codex-plan-runner-sandbox-and-volatile-ref-incidents.md`
- This is ordered plan 1 of 2. Do not begin the permission/recovery plan until this plan is fully implemented and reviewed.
- The root provider must use `subagent-driven-development`; it coordinates but does not implement task code itself.
- For each task: create a file-backed task brief, dispatch one fresh implementer, require RED/GREEN TDD and a narrow commit, collect a file-backed report, build a diff package from the recorded base commit, dispatch a separate reviewer, fix and re-review every Critical or Important finding, then update the SDD ledger.
- Generate each brief with `/Users/kws/.codex/skills/subagent-driven-development/scripts/task-brief PLAN_FILE N`; name its report by replacing `-brief.md` with `-report.md`. Generate reviewer input with `/Users/kws/.codex/skills/subagent-driven-development/scripts/review-package BASE HEAD`, using the base recorded before dispatch rather than `HEAD~1`.
- Before dispatch, read `.superpowers/sdd/progress.md` when it exists. After clean spec and quality review, append `Task N: complete (commits <base7>..<head7>, review clean)` and never re-dispatch a completed task.
- Do not run implementers in parallel. Use `gpt-5.6-terra` only for mechanical tests/docs and `gpt-5.6-sol` for Git integrity, state recovery, provider lifecycle, auth, non-trivial reviews, and final review.
- Runner state, Git commits, focused test output, and final receipts are authoritative; the SDD ledger is recovery context only.
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
- `provider.py`: isolated auth provisioning and root-turn/result lifecycle.
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

Each accepted dirty checkpoint must assert exact equality for:

```python
{
    "branch": workspace.branch,
    "head": git("rev-parse", "HEAD", cwd=workspace.worktree).strip(),
    "tracked_digest": workspace.observe().tracked_digest,
    "staged_digest": workspace.observe().staged_digest,
    "untracked_digest": workspace.observe().untracked_digest,
    "dirty": True,
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
    payload = observation.as_dict()
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

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_contracts.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_storage.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS for all dirty invalid/malformed/oversized cases, review-fix composition, exact resume, and unsafe-ref rejection.

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

## Task 4: Provision Narrow Auth and Require a Completed Root Turn

**Files:**

- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/provider.py`
- Modify: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Modify: `skills/kws-codex-plan-runner/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_provider.py`
- Modify: `skills/kws-codex-plan-runner/evals/test_engine.py`

**Interfaces:**

- Produces: `_provision_codex_auth(source_env, isolated_codex_home)`.
- Changes: provider stream parsing returns a precise stream error and `root_turn_completed`; structured output is accepted only after the root turn completes.
- Preserves: environment-based OpenAI credentials, bounded stderr, immediate session-ID callback, and collaboration activity accounting.

- [ ] **Step 1: Write failing auth and lifecycle tests**

Add these exact tests:

- `test_isolated_codex_home_copies_only_private_regular_auth_file`: create a private source `auth.json` plus `config.toml`, launch the fake executable, and assert only auth exists under the child Codex home.
- `test_environment_token_auth_requires_no_file_copy`: supply `OPENAI_API_KEY=test-token`, omit source auth, and assert launch succeeds without an auth file.
- `test_symlink_or_oversized_auth_file_fails_closed`: exercise a symlink and a file of `1_048_577` bytes and assert `provider_auth_blocked` without child launch.
- `test_subagent_completion_does_not_replace_root_completion`: emit a collaboration completion before root completion and assert no result is accepted at that point.
- `test_result_without_completed_root_turn_is_transport_failure`: write a valid result file but omit root `turn.completed`; assert `controller_transport_failed`.
- `test_root_and_collaboration_events_accept_one_root_final_result`: interleave collaboration events, complete the root turn, and assert exactly one structured root result is accepted.

The file-backed test must assert mode `0o600`, no copied `config.toml` or rules, and `CODEX_HOME` pointing at the isolated directory.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL because isolated home currently hides file-backed auth and result acceptance does not require an unambiguous completed root turn.

- [ ] **Step 3: Implement narrow auth provisioning**

Use the configured source `CODEX_HOME` when present, otherwise the explicit user Codex directory already resolved by the controller. Accept only a same-owner, non-symlink, regular `auth.json` no larger than 1 MiB. Copy it atomically to:

```python
isolated_codex_home / "auth.json"
```

with directory mode `0o700` and file mode `0o600`. Do not copy config, rules, session history, logs, or MCP state. If an allowed environment token is already present, no auth file is required.

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

Map malformed JSONL and per-line overflow separately. Refresh activity for valid root and collaboration lifecycle events, but only a root `turn.completed` authorizes `_read_result()`. A subagent completion, commentary item, or result-shaped collaboration event must never substitute for the root final result.

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_provider.py -v
"$PYTHON_313" skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: PASS for file auth, token auth, invalid auth rejection, root/subagent interleaving, malformed stream, oversized stream, resume, and structured result validation.

- [ ] **Step 6: Self-review and commit**

Ensure error messages never include auth content and that missing/invalid auth classifies as `provider_auth_blocked` rather than prompting.

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/provider.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-codex-plan-runner/evals/fake_codex.py \
  skills/kws-codex-plan-runner/evals/test_provider.py \
  skills/kws-codex-plan-runner/evals/test_engine.py
git commit -m "fix(plan-runner): harden auth and root results"
```

## Plan 1 Completion Review

- [ ] Build one whole-plan diff package from the plan start commit to current HEAD.
- [ ] Dispatch a fresh `gpt-5.6-sol` reviewer against the approved design, this plan, all four incident reports, and the diff package.
- [ ] Fix and re-review every Critical or Important finding; rerun only affected focused test files.
- [ ] Confirm the worktree is clean and all four task commits are present.
- [ ] Record exact HEAD, focused test commands/results, reviewer verdicts, residual findings, and ordered-plan handoff in the SDD ledger.
- [ ] Continue directly to `2026-07-24-codex-plan-runner-permission-recovery.md`; do not merge, push, deploy, or run the canonical broad gate.
