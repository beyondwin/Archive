# Incident Report: Codex Plan Runner Replaces the Configured Git Email with a Hostname-Derived Fallback

## Document status

| Field | Value |
| --- | --- |
| Status | Confirmed implementation defect; fix not yet implemented |
| Suggested severity | High |
| Affected component | `skills/kws-codex-plan-runner` |
| Affected release | `1.0.0` |
| Runner repository HEAD inspected | `0f657980ccef445b3693180a3cf1a5d8cd67b574` |
| Incident date | 2026-07-24 |
| Evidence reviewed | 2026-07-24 |
| User-visible outcome | Runner-created commit records `kws <kws@kws.local>` instead of configured `kws <coreanim@gmail.com>` |
| Content data-loss status | No content loss observed |
| Git metadata integrity | Incorrect author and committer identity confirmed |
| Remote exposure | No merge or push observed for the affected commit |
| Integration status | `not_observed` |

## Issue title suitable for a tracker

> Codex plan runner loses the operator Git identity in its isolated HOME and silently commits with `user@host.local`

## Executive summary

The Codex plan runner intentionally removes the operator's `HOME` and
`XDG_CONFIG_HOME` before launching the provider, then assigns a run-private
`.codex-child-home`. This protects the provider from inheriting arbitrary user
configuration and credentials.

The isolation is incomplete for Git commit correctness:

1. the configured Git identity exists only in the operator's global
   `$HOME/.gitconfig`;
2. `sanitized_child_env()` removes the operator `HOME` and all incoming
   `GIT_CONFIG_COUNT` overlays;
3. `CodexAdapter.launch()` replaces `HOME` with the empty run-private child
   home;
4. the runner does not capture or explicitly inject `user.name` and
   `user.email`;
5. the real provider executes `git commit` without an explicit identity;
6. Git derives an identity from the operating-system username and hostname;
7. the commit is created as `kws <kws@kws.local>`.

The operator's actual configured identity was:

```text
user.name  = kws
user.email = coreanim@gmail.com
source     = /Users/kws/.gitconfig
```

The affected runner commit was:

```text
commit    6fcb8df4f7d5fc58babdfc50ed2b5504a11bf8ec
author    kws <kws@kws.local>
committer kws <kws@kws.local>
subject   test: lock Calm Craft reference integrity
```

This is a runner-owned environment propagation defect. It is not a
`canvas-clone` repository configuration error, and it is not caused by the
Calm Craft specification or implementation plan.

The safe fix is not to copy the operator's full `.gitconfig` into the isolated
home. The runner should capture the effective identity once, validate and seal
it in immutable run state, pass only that identity into every provider session,
set `user.useConfigOnly=true`, and reject candidate commits whose author or
committer identity does not match the sealed run identity.

## Bottom-line ownership assessment

This incident belongs to `kws-codex-plan-runner`.

The isolation itself is intentional and security-relevant. The defect is that
the runner preserves provider authentication and blocks Git remote mutation,
but does not preserve the minimum non-secret Git configuration required to
produce correctly attributed local commits.

The provider could have supplied `git -c user.name=... -c user.email=...` on
every commit, but that would move a deterministic controller responsibility
into model behavior. The runner owns:

- provider environment construction;
- Git/worktree safety;
- runner-owned local commits;
- immutable execution identity;
- candidate-HEAD validation;
- ready-for-integration evidence.

Correct commit attribution therefore must be enforced by the runner, not left
to the provider prompt.

## User impact

### Confirmed impact

- At least one runner-created local commit has the wrong author email.
- The same commit has the wrong committer email.
- The incorrect email is a hostname-derived fallback, not the user's configured
  email.
- GitHub attribution, contribution statistics, audit records, DCO checks, and
  organization policy checks may treat the commit differently.
- If the commit were later merged and pushed, correcting it would require
  history rewriting or a replacement commit strategy.
- The current runner does not detect the mismatch before reporting plan
  progress.
- The current deterministic fake provider cannot expose this defect because it
  supplies its own test-only identity on every commit.

### Potential impact

Every real provider commit created under the same isolated environment is
exposed until the runner is fixed. The impact is not limited to the observed
Calm Craft commit.

Affected scenarios include:

- a new `run`;
- a plain `resume`;
- `resume --retry-blocked`;
- `resume --retry-failed`;
- review-fix sessions;
- fresh-session recovery;
- later plans executed in the same worktree.

### Containment at incident discovery

The affected commit was local to an isolated runner branch. No merge, push, or
deploy was observed for that commit.

That containment limits remote impact, but it does not make the metadata
correct. The affected branch must not be treated as integration-ready until
the identity is corrected or the work is recreated under a fixed runner.

## Affected evidence

### Configured operator identity

Command:

```bash
git -C /Users/kws/source/web/canvas-clone \
  config --show-origin --get-regexp '^user\.(name|email)$'
```

Observed output:

```text
file:/Users/kws/.gitconfig user.name kws
file:/Users/kws/.gitconfig user.email coreanim@gmail.com
```

### Affected runner commit

Worktree:

```text
/Users/kws/.codex/worktrees/plan-runner/
  2026-07-24-calm-craft-responsive-reference-integ-097667ba-7bdc-4bd5-a0c5-bb0f70d321c4
```

Command:

```bash
git show -s --format=fuller 6fcb8df4
```

Observed output:

```text
commit 6fcb8df4f7d5fc58babdfc50ed2b5504a11bf8ec
Author:     kws <kws@kws.local>
AuthorDate: Fri Jul 24 20:13:24 2026 +0900
Commit:     kws <kws@kws.local>
CommitDate: Fri Jul 24 20:13:24 2026 +0900

    test: lock Calm Craft reference integrity
```

### Isolated-HOME reproduction without creating a commit

Command:

```bash
HOME=/private/tmp/kpr-nonexistent-home \
XDG_CONFIG_HOME=/private/tmp/kpr-nonexistent-config \
GIT_CONFIG_COUNT=0 \
git -C /Users/kws/source/web/canvas-clone var GIT_AUTHOR_IDENT
```

Observed identity:

```text
kws <kws@kws.local>
```

This reproduces the identity selected by Git when the configured global
identity is hidden.

## Expected behavior

For a run created while the effective source-repository identity is:

```text
kws <coreanim@gmail.com>
```

every runner-owned local commit should have:

```text
author    = kws <coreanim@gmail.com>
committer = kws <coreanim@gmail.com>
```

The identity should remain stable for:

- every plan in the run;
- every provider recovery attempt;
- every review-fix attempt;
- every resume invocation;
- every candidate-HEAD validation.

Changing the host's global Git config after run creation must not silently
change the identity of later commits in the same run.

If a usable identity is unavailable, the runner should fail before launching a
provider or creating a commit. It must not permit Git to invent
`user@host.local`.

## Actual behavior

The provider receives an isolated HOME with no `user.name` or `user.email`.
Git's fallback identity is accepted silently, and the runner validates the
resulting HEAD without checking commit attribution.

The run therefore can contain internally consistent Git objects and still
carry incorrect human identity metadata.

## Incident timeline

### 1. Operator identity was correctly configured

The source repository resolved:

```text
kws <coreanim@gmail.com>
```

Recent commits on `main` also used that author and committer identity.

### 2. Runner created an isolated worktree

The affected run ID was:

```text
2026-07-24-calm-craft-responsive-reference-integ-097667ba-7bdc-4bd5-a0c5-bb0f70d321c4
```

The run started from:

```text
4d0153c3ec347dbdaff32642426c466c5b7a607d
```

### 3. Provider environment discarded the global Git config

`sanitized_child_env()` removed `HOME` and `XDG_CONFIG_HOME`.
`CodexAdapter.launch()` then assigned a new empty run-private HOME.

No Git identity was copied, captured, injected, or sealed.

### 4. Provider completed Task 0 and committed

The provider created:

```text
6fcb8df4f7d5fc58babdfc50ed2b5504a11bf8ec
```

Both author and committer were recorded as:

```text
kws <kws@kws.local>
```

### 5. Mismatch was found by comparing source config and commit metadata

The source config still reported `coreanim@gmail.com`. The affected worktree
also reported the same config when inspected from the operator shell, because
the operator shell uses the normal HOME.

This explains why a post-run `git config` check alone is misleading: the wrong
identity exists only in the already-created commit and in the provider's
isolated execution environment.

## Technical root-cause analysis

### Primary root cause: identity is not part of the run contract

The runner's immutable configuration records:

- input snapshots;
- source repository and commit;
- protected refs;
- sandbox selection;
- model selection;
- runtime identity.

It does not record the Git author/committer identity that provider-created
commits must use.

Because identity is not captured, the controller cannot:

- inject it into fresh sessions;
- preserve it across resume;
- compare candidate commits against it;
- report a mismatch before integration handoff.

### Control flow that removes the configured identity

`scripts/plan_runner/git_ops.py` defines:

```py
_OPERATOR_CONFIG_ROOTS = frozenset(("HOME", "XDG_CONFIG_HOME"))
```

`sanitized_child_env()` removes those variables:

```py
if key in _OPERATOR_CONFIG_ROOTS:
    continue
```

It also discards any incoming `GIT_CONFIG_COUNT`,
`GIT_CONFIG_KEY_*`, and `GIT_CONFIG_VALUE_*` values, then rebuilds the overlay
with remote push URLs disabled:

```py
for index, remote in enumerate(safe_remotes):
    clean[f"GIT_CONFIG_KEY_{index}"] = f"remote.{remote}.pushurl"
    clean[f"GIT_CONFIG_VALUE_{index}"] = (
        f"disabled://plan-runner/{run_id}/{remote}"
    )
clean["GIT_CONFIG_COUNT"] = str(len(safe_remotes))
```

This is correct for preventing an operator-supplied overlay from bypassing
remote mutation guards. The missing step is adding a controller-owned Git
identity and `user.useConfigOnly=true` to the rebuilt safe overlay.

`scripts/plan_runner/provider.py` then creates the isolated home:

```py
isolated_home = request.output_path.parent / ".codex-child-home"
isolated_config = isolated_home / ".config"
_ensure_private_directory(isolated_home)
_ensure_private_directory(isolated_config)
env["HOME"] = str(isolated_home)
env["XDG_CONFIG_HOME"] = str(isolated_config)
```

At this point:

- the normal `$HOME/.gitconfig` is unreachable through Git's normal global
  config lookup;
- the isolated home has no Git config;
- the safe `GIT_CONFIG_COUNT` overlay contains only disabled push URLs;
- no explicit author or committer environment variables exist.

Git therefore falls back to the operating-system username and hostname.

### Contributing defect 1: Git fallback is not disabled

The child environment does not set:

```text
user.useConfigOnly=true
```

Without this setting, Git is allowed to synthesize an identity from the local
account and hostname.

For an autonomous runner, silent synthesis is unsafe. A missing required
identity should be a deterministic preflight failure.

### Contributing defect 2: inherited identity overrides are not normalized

The sanitizer currently does not explicitly remove or normalize:

```text
EMAIL
GIT_AUTHOR_NAME
GIT_AUTHOR_EMAIL
GIT_AUTHOR_DATE
GIT_COMMITTER_NAME
GIT_COMMITTER_EMAIL
GIT_COMMITTER_DATE
GIT_CONFIG_GLOBAL
GIT_CONFIG_SYSTEM
GIT_CONFIG_NOSYSTEM
```

If some of these variables happen to exist in the operator environment, they
can create a different identity outcome from the observed fallback.

The fix must not merely work for the current environment. It must establish one
controller-owned precedence rule and remove ambient identity drift.

### Contributing defect 3: deterministic fake commits mask the problem

`evals/fake_codex.py` commits with explicit test-only configuration:

```py
subprocess.run(
    [
        "git",
        "-c", "user.name=Plan Runner Parity",
        "-c", "user.email=parity@example.test",
        "commit", "-m", commit_message,
    ],
    check=True,
)
```

This makes deterministic engine tests independent of the provider environment,
but it also means those tests cannot detect missing identity propagation.

The fake provider proves that a commit can be made. It does not prove that a
real provider commit uses the operator's configured identity.

### Contributing defect 4: environment tests assert isolation but not identity

`evals/test_provider.py` verifies:

- credentials are scrubbed;
- `HOME` and `XDG_CONFIG_HOME` point to the isolated home;
- provider authentication survives;
- Git terminal prompting is disabled;
- the push URL override is installed.

It does not assert any author or committer identity.

The test currently expects `GIT_CONFIG_COUNT == "1"` for one remote, proving
that the safe overlay contains only the remote push guard.

### Contributing defect 5: candidate commit metadata is not validated

The runner validates:

- worktree registration;
- branch identity;
- common Git directory;
- candidate ancestry;
- clean/dirty state;
- protected ref stability;
- receipts and candidate HEAD.

No runner source check was found for author or committer identity in the commit
range from `source_commit` to candidate `HEAD`.

Even if environment propagation regresses again, finalization currently has no
second line of defense.

## Five whys

### 1. Why did the commit use `kws@kws.local`?

Git could not see the configured global email and synthesized an identity from
the local username and hostname.

### 2. Why could Git not see the configured email?

The runner removed the operator HOME and launched the provider with an empty
run-private HOME.

### 3. Why was the identity not restored explicitly?

The runner treats authentication, remote mutation defense, worktree identity,
and verification identity as controller contracts, but Git human identity is
not modeled as immutable run input.

### 4. Why did tests not fail?

The deterministic fake provider supplies `Plan Runner Parity
<parity@example.test>` directly on every commit, while provider-environment
tests do not check the real commit identity path.

### 5. Why was the bad commit accepted?

Candidate validation checks Git topology and tree/receipt integrity, but not
author and committer metadata.

## Security and privacy constraints for the fix

### Do not copy the full `.gitconfig`

The global Git config may contain:

- credential helpers;
- conditional includes;
- aliases that execute commands;
- custom hooks paths;
- signing keys and signing programs;
- remote URL rewrites;
- proxy settings;
- filesystem paths;
- organization-specific configuration.

Copying it into `.codex-child-home` would undo the runner's credential
minimization and configuration-isolation boundary.

### Do not expose unrelated provider credentials

The Git identity fix must not weaken existing scrubbing of:

- SSH agents and askpass helpers;
- cloud credentials;
- GitHub/GitLab tokens;
- database passwords;
- arbitrary credential paths;
- operator-supplied Git config overlays.

### Do not rely only on a prompt instruction

A prompt such as “use `coreanim@gmail.com` for commits” is insufficient:

- prompts are not an execution boundary;
- fresh sessions may not preserve informal context;
- provider behavior is not a durable source of correctness;
- commit creation may occur in scripts or tools without model awareness.

The environment and final candidate validation must enforce the contract.

### Treat the email as local execution metadata

The email is already part of Git commit objects. If it is also stored in
runner state:

- keep state under the existing private run-state permissions;
- do not add it to provider logs beyond what Git commands inherently reveal;
- do not include it in unrelated public artifacts;
- use a digest in verification receipts when cleartext is not needed.

## Required target invariant

For every commit in:

```text
source_commit..candidate_head
```

the following must be true unless a future explicit, immutable per-run override
contract is introduced:

```text
author.name     == sealed_git_identity.name
author.email    == sealed_git_identity.email
committer.name  == sealed_git_identity.name
committer.email == sealed_git_identity.email
```

The same sealed identity must be used by:

- initial implementation;
- session resume;
- fresh-session fallback;
- retry-blocked recovery;
- retry-failed recovery;
- review fixes;
- later ordered plans.

The runner must never accept hostname-derived fallback identity.

## Proposed implementation

### P0: model Git identity explicitly

Add a standard-library-only immutable type, for example:

```py
@dataclass(frozen=True)
class GitIdentity:
    name: str
    email: str

    def __post_init__(self) -> None:
        for label, value in (("name", self.name), ("email", self.email)):
            if (
                not isinstance(value, str)
                or not value.strip()
                or "\x00" in value
                or "\n" in value
                or "\r" in value
            ):
                raise ValueError(f"Git {label} is invalid")
```

Use bounded lengths, but do not impose an unnecessarily narrow email regex.
Git permits identities that are broader than common web-form email syntax.

### P0: capture the configured identity before HOME isolation

At `run` creation, before the provider environment is sanitized:

```bash
git -C WORKSPACE config --get user.name
git -C WORKSPACE config --get user.email
```

The lookup must run in the source repository so repository-local and
conditional include rules resolve the same way Git normally resolves them.

Requirements:

- capture exact effective `user.name` and `user.email`;
- require both to be non-empty and NUL/newline-free;
- fail before worktree/provider creation if either is missing;
- do not use Git's hostname fallback as the captured value;
- do not read or serialize the entire Git config.

Suggested failure:

```json
{
  "status": "blocked",
  "reason_code": "git_identity_unavailable",
  "detail": "configured Git user.name and user.email are required"
}
```

Whether the status is `blocked` or invalid invocation should be fixed by the
runner contract, but it must be deterministic and occur before model work.

### P0: seal identity in immutable run state

Add:

```json
{
  "immutable_config": {
    "git_identity": {
      "name": "kws",
      "email": "coreanim@gmail.com"
    }
  }
}
```

The identity becomes part of the state digest and input/recovery contract.

On resume:

- use the stored identity;
- do not re-read a changed host config and silently switch identity;
- validate the stored shape before provider launch;
- include the identity digest in finalization metadata.

### P0: inject only the safe identity into the child environment

Extend `sanitized_child_env()` to accept `GitIdentity`.

First remove ambient identity/config overrides:

```text
EMAIL
GIT_AUTHOR_NAME
GIT_AUTHOR_EMAIL
GIT_AUTHOR_DATE
GIT_COMMITTER_NAME
GIT_COMMITTER_EMAIL
GIT_COMMITTER_DATE
GIT_CONFIG_GLOBAL
GIT_CONFIG_SYSTEM
GIT_CONFIG_NOSYSTEM
```

Then rebuild the runner-owned `GIT_CONFIG_COUNT` overlay with:

```text
user.name=<sealed name>
user.email=<sealed email>
user.useConfigOnly=true
remote.<name>.pushurl=disabled://plan-runner/<run-id>/<remote>
```

Example:

```py
safe_config = [
    ("user.name", identity.name),
    ("user.email", identity.email),
    ("user.useConfigOnly", "true"),
    *[
        (
            f"remote.{remote}.pushurl",
            f"disabled://plan-runner/{run_id}/{remote}",
        )
        for remote in safe_remotes
    ],
]
for index, (key, value) in enumerate(safe_config):
    clean[f"GIT_CONFIG_KEY_{index}"] = key
    clean[f"GIT_CONFIG_VALUE_{index}"] = value
clean["GIT_CONFIG_COUNT"] = str(len(safe_config))
```

Using the rebuilt config overlay has these advantages:

- it applies to every Git subprocess in the provider session;
- it does not copy credential helpers, includes, aliases, or hooks;
- it composes with the existing disabled push URLs;
- `user.useConfigOnly=true` turns a missing identity into a hard failure.

The implementation may additionally set the four explicit author/committer
environment variables, but it must establish one documented precedence rule
and test ambient override removal. Do not allow the source shell's
`GIT_AUTHOR_*` values to override the sealed run identity accidentally.

### P0: validate every candidate commit

Before accepting a provider's implemented result and again before final
handoff, inspect every new commit:

```bash
git log \
  --format='%H%x00%an%x00%ae%x00%cn%x00%ce' \
  SOURCE_COMMIT..CANDIDATE_HEAD
```

Reject:

- author name mismatch;
- author email mismatch;
- committer name mismatch;
- committer email mismatch;
- malformed or missing metadata;
- a candidate range that cannot be parsed exactly.

Suggested failure:

```json
{
  "status": "failed",
  "reason_code": "git_identity_mismatch",
  "detail": "candidate commit identity does not match the sealed run identity"
}
```

The failure report should include commit IDs and which field mismatched, but
should avoid unnecessarily echoing email values into broad logs.

### P0: preserve recovery correctness

Identity validation must not mutate Git history automatically.

When a mismatched commit is found:

- do not amend it automatically;
- do not reset the worktree;
- do not rewrite a protected ref;
- do not mark the run ready;
- record exact mismatch evidence;
- require an authorized correction path or a fresh run under the fixed runner.

This keeps Git metadata repair separate from the runner's normal autonomous
implementation authority.

### P1: define legacy-state behavior

Release `1.0.0` state does not contain `immutable_config.git_identity`.

Choose and document one migration rule:

1. **Fail closed:** old runs cannot resume with the fixed runner and report
   `git_identity_contract_missing`; or
2. **Bounded migration:** capture identity once only if the run is still at
   `source_commit`, has no new commits, has no provider-created dirty work, and
   has no sealed evidence that depends on commit identity.

Do not retrofit identity silently when a legacy run already contains commits.
For the observed `6fcb8df4` run, the existing mismatch must remain visible.

### P1: expose identity in inspect output safely

`inspect` should report enough information to diagnose the run:

```json
{
  "git_identity": {
    "name": "kws",
    "email_digest": "<sha256>"
  }
}
```

Cleartext email may remain in private state while concise inspect output uses a
digest or redacted form.

### P1: document the boundary

Update `SKILL.md`, `README.md`, and `CHANGELOG.md` to state:

- the provider uses an isolated HOME;
- the runner captures only effective Git name/email;
- arbitrary Git config is not copied;
- identity is stable across resume;
- missing identity fails before provider launch;
- candidate commit identity is verified before handoff.

## Required deterministic regression tests

### `evals/test_git_ops.py`

Add tests proving:

1. operator `HOME` and `XDG_CONFIG_HOME` remain stripped;
2. ambient `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, `EMAIL`, and alternate global
   config paths are stripped or normalized;
3. the rebuilt overlay contains exact `user.name`, `user.email`, and
   `user.useConfigOnly=true`;
4. remote push URLs remain disabled;
5. `GIT_CONFIG_COUNT` accounts for identity entries plus every remote;
6. control characters in name/email are rejected;
7. secrets, credential helpers, and unrelated config are not copied;
8. `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` under an empty
   isolated HOME resolve to the sealed identity;
9. a Git commit made using only the sanitized environment records the sealed
   author and committer;
10. removing either identity value with `user.useConfigOnly=true` causes the
    commit to fail instead of generating `user@host.local`.

### `evals/test_provider.py`

Extend the fake environment record and assertions to prove:

- isolated HOME is still used;
- provider authentication remains available;
- helper variables remain available;
- the exact identity overlay reaches initial and resumed sessions;
- a fresh-session fallback receives the same identity;
- ambient identity variables cannot override the sealed identity.

The existing expectation:

```py
self.assertEqual(record["env"]["GIT_CONFIG_COUNT"], "1")
```

must be updated to include the three identity entries and the remote push
guard.

### `evals/fake_codex.py`

Add at least one scenario that commits without:

```text
-c user.name=...
-c user.email=...
```

Then assert the environment, rather than the fake provider, supplies the exact
identity.

The existing explicit `Plan Runner Parity <parity@example.test>` path may
remain for tests that intentionally need a fixed synthetic identity, but it
must not be the only commit path.

### `evals/test_engine.py`

Add tests proving:

- run creation seals the effective identity;
- missing `user.name` or `user.email` fails before worktree/provider creation;
- host config changes after run creation do not change resume identity;
- initial, recovery, review-fix, and later-plan commits use the same identity;
- a fake provider that explicitly commits with another identity is rejected;
- mismatch detection happens before `implemented` or
  `ready_for_integration`;
- candidate-HEAD changes invalidate identity-derived final evidence;
- a legacy state with commits and no identity does not migrate silently.

### `evals/test_storage.py`

Add shape and integrity tests for:

- immutable `git_identity`;
- missing name/email;
- empty or control-character values;
- state-digest tampering;
- resume compatibility policy.

### Live Codex canary

The deterministic gate cannot prove real CLI compatibility by itself.

Run a bounded, explicit live canary that:

1. uses a temporary local Git repository;
2. configures a non-fallback test identity in that repository;
3. starts the real Codex provider through the runner;
4. asks it to create one local commit;
5. verifies exact author and committer name/email;
6. verifies the child HOME remains isolated;
7. verifies remote push remains disabled;
8. does not merge, push, or deploy.

The canary should use a non-sensitive test identity such as:

```text
Plan Runner Canary <plan-runner-canary@example.test>
```

Offline eval success must not be reported as proof of this live path.

## Acceptance criteria

### Identity capture

- [ ] `run` captures effective repository `user.name` and `user.email` before
  HOME isolation.
- [ ] Missing identity fails before model work.
- [ ] Hostname-derived fallback cannot be captured as an implicit default.
- [ ] Identity is included in immutable state and state digest.

### Environment isolation

- [ ] Provider HOME remains run-private.
- [ ] Full `.gitconfig` is not copied.
- [ ] Credential helpers, includes, aliases, hooks, and signing configuration
  are not imported.
- [ ] Existing credential scrubbing still passes.
- [ ] Remote push URL guards still pass.
- [ ] `user.useConfigOnly=true` is enforced.

### Commit correctness

- [ ] A real provider commit uses the sealed author name/email.
- [ ] A real provider commit uses the sealed committer name/email.
- [ ] Initial, resumed, recovered, review-fix, and later-plan sessions agree.
- [ ] Ambient environment changes cannot alter the identity.
- [ ] Host config changes after run creation cannot alter the identity.

### Candidate validation

- [ ] Every commit in `source_commit..candidate_head` is checked.
- [ ] Any author or committer mismatch fails closed.
- [ ] A mismatch cannot reach `implemented`.
- [ ] A mismatch cannot reach `ready_for_integration`.
- [ ] Failure evidence identifies the offending commit without broad secret
  disclosure.

### Regression evidence

- [ ] Focused Git environment tests pass.
- [ ] Provider environment tests pass.
- [ ] Engine and storage tests pass.
- [ ] Full `./evals/run.sh` passes exactly once at final candidate HEAD.
- [ ] An explicit live Codex commit canary passes.
- [ ] `SKILL.md`, `README.md`, and `CHANGELOG.md` describe the new contract.

## Current affected-run handling

### Affected commit

```text
6fcb8df4f7d5fc58babdfc50ed2b5504a11bf8ec
```

### What must not happen automatically

Do not automatically:

- amend the commit;
- reset the runner branch;
- rebase the branch;
- rewrite the runner state;
- modify protected refs;
- merge or push the branch;
- declare its existing evidence valid after rewriting the commit.

Changing author or committer metadata changes the commit hash. Any receipt,
review, candidate-HEAD record, or artifact bound to the old hash becomes stale.

### Safe correction options

After explicit history-rewrite authority, choose one:

1. amend/rebuild the affected local commit with the correct identity, then
   invalidate and regenerate all evidence at the new HEAD; or
2. preserve the affected run as incident evidence and recreate the work under
   a fixed runner.

The second option is safer when the affected run is already blocked or its
state/evidence cannot be reconciled.

### Active-run warning

Any active run started before this fix should be treated as exposed even if it
has not committed yet. Before accepting its handoff:

```bash
git log \
  --format='%H | author=%an <%ae> | committer=%cn <%ce>' \
  SOURCE_COMMIT..HEAD
```

If any mismatch exists, do not integrate that branch.

## Rollout plan

### Phase 1: RED tests

- Add sanitized-environment identity tests.
- Add an environment-owned fake commit path.
- Add engine capture/resume/mismatch tests.
- Add storage contract tests.
- Confirm the tests fail on release `1.0.0`.

### Phase 2: identity capture and injection

- Add `GitIdentity`.
- Capture it at run creation.
- Seal it in immutable state.
- Rebuild the safe Git config overlay.
- Enforce `user.useConfigOnly=true`.
- Preserve the identity across resume and recovery.

### Phase 3: candidate-range validation

- Audit all new commit author/committer fields.
- Fail before plan acceptance on mismatch.
- Re-audit before final handoff.
- Bind the identity digest to final evidence.

### Phase 4: documentation and deterministic gate

- Update skill documentation and changelog.
- Run focused evals during implementation.
- Run `./evals/run.sh` exactly once at final candidate HEAD.

### Phase 5: live canary

- Run the real provider in a temporary local repository.
- Verify exact metadata.
- Verify push denial and isolated HOME.
- Record the canary separately from deterministic evidence.

### Phase 6: affected-run disposition

- Inventory all unintegrated runner commits created before the fix.
- Identify incorrect author/committer metadata.
- Obtain explicit authority before rewriting any local history.
- Regenerate candidate-HEAD-bound evidence after any rewrite.

## Risk analysis

### Risk: copying too much Git configuration

Mitigation:

- capture only effective name/email;
- keep isolated HOME;
- use a controller-owned config overlay;
- test that credential helpers, includes, hooks, aliases, signing configuration,
  and URL rewrites are absent.

### Risk: ambient environment overrides sealed identity

Mitigation:

- scrub author/committer/email variables;
- establish one documented precedence rule;
- validate every candidate commit.

### Risk: identity changes midway through a run

Mitigation:

- seal identity at run creation;
- use stored identity on resume;
- include it in the state digest;
- reject state tampering.

### Risk: legitimate intentional alternate authors

The current runner advertises runner-owned local commits and has no explicit
alternate-author contract.

Mitigation:

- require a future explicit CLI/state contract for alternate authors;
- do not infer alternate authors from ambient variables;
- keep the default strict and deterministic.

### Risk: final validation rewrites history implicitly

Mitigation:

- validation is read-only;
- mismatch causes fail-closed status;
- repair requires separate explicit authority;
- all old candidate-bound evidence is invalid after a rewrite.

### Risk: cleartext email in state

Mitigation:

- preserve existing private state permissions;
- expose only a digest/redaction in concise inspect output;
- do not place cleartext identity in unrelated public artifacts.

## Relevant source files

### Production

| File | Relevant responsibility |
| --- | --- |
| `skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py` | Environment sanitization, Git worktree identity, disabled push URL overlay |
| `skills/kws-codex-plan-runner/scripts/plan_runner/provider.py` | Provider launch and isolated HOME construction |
| `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py` | Run creation, immutable config, provider-result and finalization acceptance |
| `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py` | State shape and integrity |
| `skills/kws-codex-plan-runner/scripts/runner.py` | Public run/resume/inspect boundary |

### Tests

| File | Gap or required coverage |
| --- | --- |
| `skills/kws-codex-plan-runner/evals/test_git_ops.py` | Sanitizer currently tests secrets/push guards, not sealed Git identity |
| `skills/kws-codex-plan-runner/evals/test_provider.py` | Isolated HOME asserted without author/committer propagation |
| `skills/kws-codex-plan-runner/evals/fake_codex.py` | Explicit parity identity masks the real environment gap |
| `skills/kws-codex-plan-runner/evals/test_engine.py` | No run-level identity capture/resume/mismatch contract |
| `skills/kws-codex-plan-runner/evals/test_storage.py` | No immutable Git identity state contract |

### Documentation

| File | Required update |
| --- | --- |
| `skills/kws-codex-plan-runner/SKILL.md` | Advertise isolated but stable Git identity |
| `skills/kws-codex-plan-runner/README.md` | Explain capture, failure, resume, and security boundaries |
| `skills/kws-codex-plan-runner/CHANGELOG.md` | Record the fix and compatibility behavior |

## Copy-ready concise issue description

### Description

The runner launches Codex with a run-private HOME after stripping the operator
HOME and Git config overlays. It preserves auth and blocks remote pushes, but
does not propagate the configured Git `user.name`/`user.email`. Real provider
commits therefore fall back to `user@host.local`.

Observed:

```text
configured: kws <coreanim@gmail.com>
committed:  kws <kws@kws.local>
commit:     6fcb8df4f7d5fc58babdfc50ed2b5504a11bf8ec
```

### Expected

Capture the effective source-repository identity once, seal it in immutable run
state, inject only that identity into every provider session, enforce
`user.useConfigOnly=true`, and validate all candidate commits before
implementation/final acceptance.

### Actual

`sanitized_child_env()` removes HOME, `CodexAdapter.launch()` points HOME to an
empty directory, and Git silently derives `kws@kws.local`.

### Root cause

Git identity is not modeled as controller-owned immutable run input.
Deterministic fake commits always pass their own test identity, masking the
real provider path.

### Required fix

1. Capture and validate repository `user.name`/`user.email` before provider
   launch.
2. Seal them in immutable state.
3. Scrub ambient author/committer overrides.
4. Add `user.name`, `user.email`, and `user.useConfigOnly=true` to the safe
   child Git overlay.
5. Preserve the identity across resume/recovery/review/later plans.
6. Reject candidate commits whose author or committer differs.
7. Add environment-owned fake commit tests plus a real Codex canary.
8. Do not copy the full `.gitconfig`.

## Final assessment

The incorrect `kws@kws.local` attribution is a reproducible
`kws-codex-plan-runner` defect caused by the interaction of correct HOME
isolation and missing Git identity propagation.

The fix must preserve both sides of the contract:

- keep arbitrary operator Git configuration and credentials out of the child;
- preserve the exact configured human identity for every runner-owned commit.

Passing the identity explicitly and validating the resulting commit range is
the minimum correctness-preserving solution. Copying the full global config,
relying on provider prompts, or accepting Git's hostname fallback would leave
the incident unresolved.

## Remediation closeout (2026-07-25)

**Status:** resolved within the approved lightweight boundary.

The original forensic record above remains unchanged. The implemented contract
is defined by the [approved remediation design](../superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md),
the [core-correctness plan](../superpowers/plans/2026-07-24-codex-plan-runner-core-correctness.md),
and the [permission/recovery plan](../superpowers/plans/2026-07-24-codex-plan-runner-permission-recovery.md).
The implementation range is inclusive from `3c93a09e` through `c3a30f61`.

Focused regressions cover configured identity capture and bounds, child
environment sealing, signing suppression, candidate author/committer
validation, immutable-state tamper rejection, and initial/resumed provider
identity reuse in `evals/test_git_ops.py`, `evals/test_storage.py`,
`evals/test_provider.py`, and `evals/test_engine.py`.

The disposable candidate canary completed one SDD task and produced commit
`1773ba770e2b69d975675762cd3b466592a30dd6` with both author and committer
`Candidate Runner Canary <candidate-runner-canary@example.test>`. Finalization
reviewed that same clean HEAD with no findings or open obligations, and the run
reached `ready_for_integration`. No merge, push, or deploy occurred.

The canonical final deterministic gate is:

```bash
bun run agent:verify -- --base "$MERGE_BASE" --head "$CANDIDATE_HEAD"
```

The deliberate residual boundary remains narrow: the runner does not copy the
operator's full Git configuration and does not infer alternate authors from
ambient variables. A future alternate-author workflow requires a separate
explicit contract.

## Whole-review hardening addendum (2026-07-25)

Follow-up runtime commit `1248ab56` closes two identity-adjacent gaps without
expanding the runner's ownership. Controller Git inspection and provider
subprocesses now remove Git routing variables such as `GIT_DIR`,
`GIT_WORK_TREE`, `GIT_INDEX_FILE`, object/common-directory overrides,
namespaces, replace refs, and quarantine paths before resolving repository
state. A real two-repository regression proves that ambient routing cannot
redirect controller or provider operations.

The same focused suite now covers author-only and committer-only mismatches
independently. Both remain integrity failures; successful configured-identity
coverage does not stand in for either asymmetric case.
