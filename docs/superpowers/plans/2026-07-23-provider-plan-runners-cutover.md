# Provider Plan Runners Live Validation and Cutover Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove both greenfield runners against the installed provider CLIs,
remove the two legacy plan executors only after a fail-closed zero-use audit,
and install each new skill only in its matching provider home without changing
legacy run evidence or the Claude multi-agent executor.

**Architecture:** Two self-locating root tools complete the transition. The
live-canary tool exercises explicit provider session continuity and a
two-plan end-to-end runner flow in disposable repositories. The cutover tool
performs a read-only audit of exact legacy processes and durable states, treats
every nonterminal state as continuable unless its exact digest is explicitly
abandoned, and applies only verified symlink changes. Git source removal occurs
in the isolated implementation branch after successful canaries and a zero
audit; installed symlink cutover occurs only after that candidate is integrated
into `main`.

**Tech Stack:** uv-managed normal-GIL CPython 3.13 standard library, POSIX
launchers, Git CLI, Codex CLI, Claude Code CLI, `unittest`, Bun/TypeScript
repository verification.

## Global Constraints

- Execute after
  `docs/superpowers/plans/2026-07-23-codex-quality-first-plan-runner.md` and
  `docs/superpowers/plans/2026-07-23-claude-quality-first-plan-runner.md`.
- Design source:
  `docs/superpowers/specs/2026-07-23-quality-first-provider-plan-runners-design.md`.
- Do not migrate, rewrite, delete, or normalize any state below
  `~/.codex/orchestrator/` or `~/.claude/clpe/`.
- Do not kill a legacy process.
- Do not infer abandonment from process absence, age, failure, or a broken
  installed link.
- Treat legacy CPE states other than `completed` and legacy CLPE states other
  than `completed` as continuable until explicitly abandoned with the exact
  state SHA-256.
- Re-audit immediately before every destructive source or symlink change.
- Preserve `skills/kws-claude-multi-agent-executor/`, its installed links, its
  verification scope, and all of its state.
- Install `kws-codex-plan-runner` only in `~/.codex/skills/` and
  `kws-claude-plan-runner` only in `~/.claude/skills/`.
- Use the preinstalled uv-managed normal-GIL CPython `>=3.13,<3.14`; never
  download Python during a runner, canary, audit, or apply command.
- The live canary may call provider services. Unit tests and repository
  verification remain credential-free and model-free.
- Never print prompts, raw provider streams, credentials, or full transcripts.
- Source deletion is limited to the two tracked legacy skill directories.
  Installed-link removal is limited to exact verified symlinks.
- Use `apply_patch` for tracked edits. Do not use broad recursive deletion.

---

## File Structure

Create:

```text
scripts/agent/
├── plan-runner-cutover
├── plan-runner-cutover.py
├── plan-runner-live-canary
├── plan-runner-live-canary.py
├── test_plan_runner_cutover.py
└── test_plan_runner_live_canary.py
```

Modify:

```text
AGENTS.md
CLAUDE.md
skills/README.md
scripts/agent/contract.ts
scripts/agent/check-contract.test.ts
scripts/agent/verification-map.ts
scripts/agent/verification-map.test.ts
```

Remove only after the zero gate:

```text
skills/kws-codex-plan-executor/
skills/kws-claude-plan-executor/
```

Do not modify or remove:

```text
skills/kws-claude-multi-agent-executor/
```

## Task 1: Managed Runtime and Live Provider Canary Harness

**Files:**

- Create: `scripts/agent/plan-runner-live-canary`
- Create: `scripts/agent/plan-runner-live-canary.py`
- Create: `scripts/agent/test_plan_runner_live_canary.py`

**Interfaces:**

- Public command:
  `./scripts/agent/plan-runner-live-canary --provider codex|claude|all
  --mode session|runner|all`.
- Output: one bounded JSON object per probe with provider, mode, status,
  provider version, session action, final HEAD when applicable, and elapsed
  seconds.
- Exit `0`: every requested probe passed; exit `3`: provider authentication,
  access, or managed runtime is unavailable; exit `4`: a real canary failed;
  exit `64`: invalid invocation.

- [ ] **Step 1: Write failing launcher and command-construction tests**

`test_plan_runner_live_canary.py` must cover:

- both launchers resolve their physical directory from an unrelated current
  directory;
- the root launcher uses exactly
  `uv python find --managed-python --no-python-downloads --no-project
  --no-config --resolve-links 3.13`;
- neither launcher contains `uv run`, `uv python install`, or `python3`;
- Codex session probe initial argv uses `codex exec --json`, an inline bounded
  output schema, a disposable `--cd`, and no `--ephemeral`;
- Codex continuation uses the captured explicit session ID with
  `codex exec resume` and never `--last`;
- Claude initial probe uses a generated UUID with `claude -p --output-format
  stream-json --verbose --session-id`;
- Claude continuation uses `--resume <exact-uuid>` and never `--continue`;
- process groups receive TERM then bounded KILL on a command deadline;
- parser output contains no prompt, raw stream, token, or credential value;
- fake provider outcomes classify unavailable authentication as blocked and
  malformed or discontinuous session results as failed.

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  scripts/agent/test_plan_runner_live_canary.py -v
```

Expected: FAIL because the launchers and harness do not exist.

- [ ] **Step 2: Implement both self-locating launchers**

`scripts/agent/plan-runner-live-canary` uses the same POSIX launcher contract
as both provider skills: exact no-download `uv python find`, absolute sibling
`.py` path, and `exec`. Mark it executable.

At Python startup, validate CPython `>=3.13,<3.14`, normal GIL, resolved
`sys.executable`, architecture, and `uv --version`. A missing runtime exits
blocked before creating a repository or starting a provider.

- [ ] **Step 3: Implement explicit-session probes**

For each provider:

1. create a disposable Git repository and commit one seed file;
2. send a short first prompt that returns a schema-constrained random nonce and
   asks the provider to remember it without modifying the repository;
3. capture the explicit provider session ID from the native stream;
4. invoke the provider's explicit resume form with a second prompt that must
   return the same nonce;
5. verify exact ID continuity, unchanged Git HEAD, and a clean worktree;
6. emit only the bounded normalized result.

Use a command-specific 600-second deadline for each provider invocation. A
deadline is not a total canary budget.

- [ ] **Step 4: Implement two-plan runner canaries**

For each provider:

1. create a disposable repository with a minimal deterministic test command;
2. create two immutable spec documents and two ordered plan documents;
3. make plan 1 add a tested `alpha` behavior and plan 2 add a tested `beta`
   behavior;
4. invoke the provider-matching public `scripts/runner` with repeated
   `--spec` and `--plan`;
5. require exit `0`, `ready_for_integration`, two `implemented` plans, distinct
   plan sessions, a separate finalization session, all declared final commands
   successful at the same final HEAD, approved whole-branch review, clean
   worktree, and `integration=not_observed`;
6. run `inspect` and require the same terminal facts without mutation.

Set temporary provider-specific state and worktree homes through the runner's
test-supported dependency injection or environment overrides. Never write
canary state into the operator's normal run directories.

- [ ] **Step 5: Run offline canary tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  scripts/agent/test_plan_runner_live_canary.py -v
bash -n scripts/agent/plan-runner-live-canary
```

Expected: PASS without real provider calls.

- [ ] **Step 6: Commit the canary harness**

```bash
chmod +x scripts/agent/plan-runner-live-canary
git add scripts/agent/plan-runner-live-canary \
  scripts/agent/plan-runner-live-canary.py \
  scripts/agent/test_plan_runner_live_canary.py
git commit -m "test: add live provider plan runner canaries"
```

## Task 2: Fail-Closed Legacy Audit and Symlink Apply Tool

**Files:**

- Create: `scripts/agent/plan-runner-cutover`
- Create: `scripts/agent/plan-runner-cutover.py`
- Create: `scripts/agent/test_plan_runner_cutover.py`

**Interfaces:**

- Audit:
  `./scripts/agent/plan-runner-cutover audit --repo /absolute/archive
  --output /absolute/audit.json [--abandonment-file /absolute/file.json]`.
- Apply:
  `./scripts/agent/plan-runner-cutover apply --repo /absolute/archive
  --audit-report /absolute/audit.json
  [--abandonment-file /absolute/file.json]`.
- Recoverable ignored-cache cleanup:
  `./scripts/agent/plan-runner-cutover quarantine-legacy-caches
  --repo /absolute/archive --audit-report /absolute/audit.json`.
- Exit `0`: zero blockers and, for `apply`, exact link changes completed;
  exit `3`: runtime or legacy-run blocker; exit `64`: invalid path or
  invocation; exit `65`: report, state, or symlink integrity failure.

- [ ] **Step 1: Write failing audit-state tests**

Use disposable homes and synthetic process snapshots to cover:

- CPE `~/.codex/orchestrator/<run-id>/state.json`: only `completed` is
  terminal; `pending`, `running`, `checkpointed`, `blocked`, `failed`,
  malformed, unreadable, or unknown states block;
- CLPE `~/.claude/clpe/<run-id>/run.json`: only `completed` is terminal;
  `running`, `resumable`, `blocked`, `failed`, `resumable=true`, malformed,
  unreadable, or unknown states block;
- a missing state root is allowed and an empty root is allowed;
- the audit hashes every observed state file without modifying its bytes,
  timestamps, ownership, or mode;
- `ps -axo pid=,ppid=,pgid=,command=` entries that reference the exact legacy
  skill roots, `scripts/cpe.py`, `scripts/clpe.py`, or their installed legacy
  symlink paths block;
- similarly named unrelated commands do not block;
- process absence never makes nonterminal state safe;
- active process presence always blocks, even when its state says completed.

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  scripts/agent/test_plan_runner_cutover.py -v
```

Expected: FAIL because the cutover tool does not exist.

- [ ] **Step 2: Write explicit-abandonment tests**

The optional abandonment file is immutable JSON:

```json
{
  "format_version": 1,
  "runs": [
    {
      "provider": "codex",
      "run_id": "exact-run-id",
      "state_sha256": "64 lowercase hex characters",
      "reason": "operator explicitly abandoned this legacy run"
    }
  ]
}
```

Tests must reject duplicate entries, unknown providers, unsafe run IDs, missing
or vague reasons, digest mismatch, state changes after audit, and abandonment
of a run with a live matching process. An abandonment entry suppresses only
the exact nonterminal state digest; it never deletes or edits that state.

- [ ] **Step 3: Implement read-only audit and content-addressed report**

The audit report includes:

- schema version and audit timestamp;
- repository and Git HEAD identity;
- uv and runner CPython identity;
- exact legacy source roots and installed-link paths inspected;
- process facts with PID, PGID, and a bounded scrubbed command digest;
- each state path, provider, run ID, status, resumable flag when present,
  SHA-256, and classification;
- accepted abandonment digests;
- blocker codes;
- report SHA-256.

Write the report with file `fsync`, atomic rename, and directory `fsync`.
Do not follow state symlinks. Reject unsafe ownership, file type, traversal,
oversize JSON, and duplicate run IDs.

- [ ] **Step 4: Write failing apply tests**

Cover:

- apply re-runs the full audit and refuses a stale or nonzero report;
- new link destinations must be absent or already be exact matching symlinks;
- legacy link sources must be symlinks resolving to the exact two legacy
  repository roots; a regular file, directory, or different target blocks;
- broken legacy symlinks are still discovered with `lstat`/`readlink` after
  source removal; target absence must not make them invisible;
- four legacy links are removed only when present and exact:
  `~/.codex/skills/kws-codex-plan-executor`,
  `~/.codex/skills/kws-claude-plan-executor`,
  `~/.claude/skills/kws-codex-plan-executor`, and
  `~/.claude/skills/kws-claude-plan-executor`;
- only two new links are installed:
  `~/.codex/skills/kws-codex-plan-runner` and
  `~/.claude/skills/kws-claude-plan-runner`;
- `kws-claude-multi-agent-executor` links remain byte-for-byte unchanged;
- injected interruption before rename leaves either the old exact link or the
  new exact link, never a partial regular file;
- no state or legacy worktree is removed.
- `quarantine-legacy-caches` works only after tracked legacy files are absent,
  requires a fresh zero audit, accepts only enumerated `.venv`, `__pycache__`,
  `.pyc`, and `.DS_Store` remnants inside the two legacy source roots, and
  moves the complete residual root to a unique directory under `~/.Trash`;
- any unknown residual path blocks without moving anything.

- [ ] **Step 5: Implement narrow apply**

`apply` requires:

1. current checkout branch `main`;
2. current HEAD equal to the audit report HEAD;
3. both new source skill roots present and both legacy source roots absent;
4. exact managed runtime still available without downloads;
5. a fresh zero-blocker audit;
6. exact legacy-link ownership and target checks.

Create each new symlink under a unique sibling temporary name, verify its
target, then atomically rename it into place. Unlink only exact legacy symlinks.
Inspect links with `lstat` and lexical `readlink` comparison rather than
`Path.exists()` or strict target resolution, because the approved legacy links
are expected to be broken after their source roots leave integrated `main`.
If any validation fails, stop before the first link mutation. Never remove a
directory or regular file.

`quarantine-legacy-caches` uses the same fresh-audit and exact-repository
checks. It performs a recoverable rename into
`~/.Trash/Archive-plan-runner-legacy-cache-<timestamp>-<uuid>/`, records every
moved source and destination, and never follows a symlink. It is not allowed to
move a root that still contains a Git-tracked file.

- [ ] **Step 6: Run and commit cutover unit tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  scripts/agent/test_plan_runner_cutover.py -v
bash -n scripts/agent/plan-runner-cutover
```

Expected: PASS.

```bash
chmod +x scripts/agent/plan-runner-cutover
git add scripts/agent/plan-runner-cutover \
  scripts/agent/plan-runner-cutover.py \
  scripts/agent/test_plan_runner_cutover.py
git commit -m "feat: add fail-closed plan runner cutover gate"
```

## Task 3: Provider-Specific Routing and Repository Verification

**Files:**

- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `skills/README.md`
- Modify: `scripts/agent/contract.ts`
- Modify: `scripts/agent/check-contract.test.ts`
- Modify: `scripts/agent/verification-map.ts`
- Modify: `scripts/agent/verification-map.test.ts`

**Interfaces:**

- Produces provider-specific discovery and installation documentation.
- Produces an offline `plan-runner-cutover-test` verification command.
- Keeps the specialized Claude multi-agent executor independently routed.

- [ ] **Step 1: Write failing routing tests**

Require:

- root contract roots include both new runner skills and the existing Claude
  multi-agent executor;
- no contract root or verification scope references either legacy plan
  executor after cutover;
- changes to either new runner select its provider eval, common parity, cutover
  unit tests, agent contract, diff check, and repository check;
- `full-offline` includes both runner evals, parity, cutover tests, and the
  existing Claude multi-agent executor checks;
- no offline scope invokes the live canary;
- the live canary remains an explicit opt-in command.

Define:

```typescript
const planRunnerCutoverTest = command(
  "plan-runner-cutover-test",
  ["./scripts/agent/plan-runner-cutover", "self-test"],
);
```

`self-test` runs only `test_plan_runner_cutover.py` and
`test_plan_runner_live_canary.py` through the already selected managed
interpreter. It must not audit the operator home or invoke a provider.

- [ ] **Step 2: Run routing tests red**

```bash
bun test scripts/agent/check-contract.test.ts \
  scripts/agent/verification-map.test.ts
```

Expected: FAIL while old routing remains and the new cutover command is absent.

- [ ] **Step 3: Update user-facing routing**

Update `AGENTS.md`:

- sequential Codex plan execution →
  `skills/kws-codex-plan-runner/`;
- sequential Claude plan execution →
  `skills/kws-claude-plan-runner/`;
- specialized Claude multi-agent execution remains
  `skills/kws-claude-multi-agent-executor/`.

Update `CLAUDE.md` with the same distinction. Do not present the specialized
multi-agent executor as the default sequential runner or as removed.

Update `skills/README.md`:

- list the two new runner names and common completion meaning;
- explain `implemented` versus run-level `ready_for_integration`;
- document repeated ordered specs and plans without positional pairing;
- document the managed CPython preflight and explicit preparation command
  `uv python install 3.13`;
- install only the Codex runner under `~/.codex/skills` and only the Claude
  runner under `~/.claude/skills`;
- retain independent installation instructions for the Claude multi-agent
  executor;
- remove all installation and usage instructions for the two legacy plan
  executors.

- [ ] **Step 4: Update verification contract and map**

Remove only the legacy CPE contract root, required file, command, and scope.
The legacy CLPE has no current verification scope, so do not invent one.
Add the cutover self-test to both new provider scopes and `full-offline`.
Keep every Claude multi-agent executor command and scope unchanged.

- [ ] **Step 5: Run focused routing tests**

```bash
bun test scripts/agent/check-contract.test.ts \
  scripts/agent/verification-map.test.ts
./scripts/agent/plan-runner-cutover self-test
```

Expected: PASS.

- [ ] **Step 6: Commit routing and verification changes**

```bash
git add AGENTS.md CLAUDE.md skills/README.md \
  scripts/agent/contract.ts \
  scripts/agent/check-contract.test.ts \
  scripts/agent/verification-map.ts \
  scripts/agent/verification-map.test.ts
git commit -m "docs: route sequential plans to provider runners"
```

## Task 4: Live Proof, Zero Gate, and Legacy Source Removal

**Files:**

- Remove: `skills/kws-codex-plan-executor/`
- Remove: `skills/kws-claude-plan-executor/`

The implementation, deterministic tests, canary harness, and read-only audit
can complete while legacy work is active. If the audit reports a live legacy
process or any non-abandoned continuable state, record
`cutover_pending_legacy_runs` and defer source deletion and installed-link
changes. Do not weaken or bypass the zero gate, and do not treat external
legacy activity as an implementation defect. Resume Steps 5-7 only after a
fresh zero audit.

- [ ] **Step 1: Prepare and record the managed runtime**

This is the only stage allowed to prepare Python:

```bash
uv python install 3.13
uv --version
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -c \
  'import platform,sys,sysconfig; print(sys.version); print(sys.executable); print(platform.machine()); print(sysconfig.get_config_var("Py_GIL_DISABLED"))'
```

Require CPython `>=3.13,<3.14`, `arm64` on the current machine, and
`Py_GIL_DISABLED` equal to `0` or `None`. Record the exact uv version,
interpreter patch, resolved path, architecture, and GIL flag in the cutover
audit evidence. Do not modify `/usr/bin/python3`.

- [ ] **Step 2: Run deterministic gates at the candidate HEAD**

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
(cd "$REPO_ROOT/skills/kws-codex-plan-runner" && ./evals/run.sh)
(cd "$REPO_ROOT/skills/kws-claude-plan-runner" && ./evals/run.sh)
(cd "$REPO_ROOT" && ./scripts/agent/check-plan-runner-parity)
./scripts/agent/plan-runner-cutover self-test
bun run agent:verify
```

Expected: every offline gate PASS.

- [ ] **Step 3: Run real installed-CLI canaries**

```bash
cd "$(git rev-parse --show-toplevel)"
./scripts/agent/plan-runner-live-canary \
  --provider all --mode all
```

Expected: Codex session continuity PASS, Claude session continuity PASS, Codex
two-plan runner PASS, and Claude two-plan runner PASS. If a provider is
temporarily unavailable, record a truthful blocker and do not weaken the gate.

- [ ] **Step 4: Produce the zero-use audit**

Use a temporary report outside Git:

```bash
CUTOVER_AUDIT="$(mktemp "${TMPDIR:-/tmp}/plan-runner-cutover.XXXXXX.json")"
./scripts/agent/plan-runner-cutover audit \
  --repo "$(git rev-parse --show-toplevel)" \
  --output "$CUTOVER_AUDIT"
```

Expected: zero live legacy processes and zero non-abandoned continuable legacy
states. If not zero, stop with `cutover_pending_legacy_runs`. Do not terminate,
resume, or alter any legacy run.

If the user has explicitly abandoned a listed run, obtain a separate absolute
abandonment JSON with that run's current state SHA-256 and rerun the audit with
`--abandonment-file`. Never generate or approve abandonment on the user's
behalf.

- [ ] **Step 5: Remove only tracked legacy sources**

Immediately rerun the audit, then use `apply_patch` to delete tracked files
under exactly:

```text
skills/kws-codex-plan-executor/
skills/kws-claude-plan-executor/
```

Do not remove ignored `.venv`, `__pycache__`, legacy state, or worktrees with a
broad command. Ignored remnants in the installed main checkout are handled
only by the tested post-integration `quarantine-legacy-caches` command. Unknown
remnants block for inspection.

- [ ] **Step 6: Scope-check and commit the source cutover**

Before committing, perform a scoped self-check and confirm:

- no old state or worktree mutation;
- no process kill;
- no legacy compatibility code;
- no cross-provider runtime imports;
- no Python download path in active commands;
- no CME source, link, contract, or verification change;
- source deletion is limited to the two legacy plan executors.

```bash
git add -A -- skills/kws-codex-plan-executor \
  skills/kws-claude-plan-executor
git commit -m "refactor: remove superseded plan executors"
CUTOVER_CANDIDATE_HEAD="$(git rev-parse HEAD)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
```

- [ ] **Step 7: Run and seal the final candidate-HEAD gates**

```bash
git diff --check
bun test scripts/agent/check-contract.test.ts \
  scripts/agent/verification-map.test.ts
./scripts/agent/plan-runner-cutover self-test
(cd "$REPO_ROOT/skills/kws-codex-plan-runner" && ./evals/run.sh)
(cd "$REPO_ROOT/skills/kws-claude-plan-runner" && ./evals/run.sh)
(cd "$REPO_ROOT" && ./scripts/agent/check-plan-runner-parity)
bun run agent:verify
```

Expected: old roots are absent from tracked routing, both new runners PASS,
parity PASS, cutover tests PASS, repository verification PASS, and no
unresolved Critical or Important review finding. After the gates, run the
whole-branch review against `code_review.md` at `CUTOVER_CANDIDATE_HEAD`; the
review and every successful gate must refer to that exact HEAD. Do not create
a commit after successful evidence. A required fix must be committed first,
`CUTOVER_CANDIDATE_HEAD` must be updated, and this step must run once for the
new candidate HEAD.

## Task 5: Post-Integration Installed-Skill Cutover

This task is intentionally performed only after the implementation branch is
integrated into local `main` and a fresh audit has no legacy blockers. It is
not executed from a feature worktree whose legacy source deletion has not
reached the installed source checkout. If Task 4 was deferred for active
legacy work, this task remains deferred as well.

- [ ] **Step 1: Verify integrated main and quarantine exact ignored caches**

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
test "$(git branch --show-current)" = "main"
git status --short --branch --untracked-files=all
git rev-parse HEAD
test -x skills/kws-codex-plan-runner/scripts/runner
test -x skills/kws-claude-plan-runner/scripts/runner
test -z "$(git ls-files skills/kws-codex-plan-executor)"
test -z "$(git ls-files skills/kws-claude-plan-executor)"
CACHE_AUDIT="$(mktemp "${TMPDIR:-/tmp}/plan-runner-cache-audit.XXXXXX.json")"
./scripts/agent/plan-runner-cutover audit \
  --repo "$REPO_ROOT" \
  --output "$CACHE_AUDIT"
./scripts/agent/plan-runner-cutover quarantine-legacy-caches \
  --repo "$REPO_ROOT" \
  --audit-report "$CACHE_AUDIT"
test ! -e skills/kws-codex-plan-executor
test ! -e skills/kws-claude-plan-executor
```

Expected: clean `main`, both new tracked sources present, no tracked legacy
files, and any exact ignored legacy caches moved recoverably to the reported
Trash location. If an unknown residual file exists, stop for inspection.
When Task 4 required a user-authored abandonment file, pass that same absolute
file to both the audit and quarantine commands.

- [ ] **Step 2: Re-run canaries and create a main-HEAD audit**

```bash
./scripts/agent/plan-runner-live-canary \
  --provider all --mode all
CUTOVER_AUDIT="$(mktemp "${TMPDIR:-/tmp}/plan-runner-cutover.XXXXXX.json")"
./scripts/agent/plan-runner-cutover audit \
  --repo "$REPO_ROOT" \
  --output "$CUTOVER_AUDIT"
```

Expected: live PASS and zero blockers at the exact integrated main HEAD.

- [ ] **Step 3: Apply exact installed links**

```bash
./scripts/agent/plan-runner-cutover apply \
  --repo "$REPO_ROOT" \
  --audit-report "$CUTOVER_AUDIT"
```

If explicit abandonment was required for the matching audit, pass the same
absolute `--abandonment-file` again. Apply re-audits before mutation.

- [ ] **Step 4: Verify installed surfaces without starting a run**

```bash
readlink ~/.codex/skills/kws-codex-plan-runner
readlink ~/.claude/skills/kws-claude-plan-runner
test ! -e ~/.codex/skills/kws-codex-plan-executor && \
  test ! -L ~/.codex/skills/kws-codex-plan-executor
test ! -e ~/.codex/skills/kws-claude-plan-executor && \
  test ! -L ~/.codex/skills/kws-claude-plan-executor
test ! -e ~/.claude/skills/kws-codex-plan-executor && \
  test ! -L ~/.claude/skills/kws-codex-plan-executor
test ! -e ~/.claude/skills/kws-claude-plan-executor && \
  test ! -L ~/.claude/skills/kws-claude-plan-executor
~/.codex/skills/kws-codex-plan-runner/scripts/runner --help
~/.claude/skills/kws-claude-plan-runner/scripts/runner --help
```

Require the two `readlink` results to equal the two exact source paths under
`$REPO_ROOT/skills/`. Confirm the Claude multi-agent executor link and source
are unchanged.

- [ ] **Step 5: Record final handoff**

Report:

- integrated main HEAD;
- uv version and exact managed CPython identity;
- deterministic gate results;
- four live canary results;
- zero-audit report path and digest;
- exact removed legacy source roots and links;
- exact installed new source/link pairs;
- confirmation that legacy state and worktrees remain for forensic inspection;
- confirmation that the Claude multi-agent executor was untouched;
- `integration=local_main` and remote push state separately.

## Plan 3 Completion Evidence

The complete transition is done only when:

- both new provider skills exist independently;
- both deterministic evals and parity pass at the integrated main HEAD;
- real explicit-session and two-plan canaries pass for both providers;
- the zero-use audit passes or exact user-approved abandonment digests account
  for every nonterminal legacy state;
- both tracked legacy plan-executor sources are absent;
- all four exact legacy installed links are absent;
- the Codex runner is linked only into Codex and the Claude runner only into
  Claude;
- uv-managed normal-GIL CPython `>=3.13,<3.14` is recorded and no active
  command downloaded it;
- all legacy state/worktree evidence remains untouched;
- the Claude multi-agent executor remains unchanged;
- `bun run agent:verify` and review against `code_review.md` pass at the final
  candidate HEAD.

## Approved Design Coverage Map

| Approved concern | Implementation owner |
|---|---|
| Ordered immutable multiple specs and sequential multiple plans | Plan 1 Codex engine; Plan 2 Claude engine; parity |
| Plan `implemented` versus run `ready_for_integration` | Both engine/schema/eval suites; parity |
| Automatic controller recovery and external `resumable` | Both recovery policies and engine tests |
| Healthy same-plan resume versus contaminated fresh session | Both provider adapters and recovery tests; live session probes |
| Candidate-HEAD final set, exact receipts, and fresh whole-branch review | Both helper/evidence/engine suites; runner canaries |
| No duplicate same-HEAD gates and invalidation after changes | Both evidence and engine suites; parity |
| Activity lease versus explicit long-command deadline | Both recovery/process suites |
| No runner-owned model escalation or task/test invention | Both provider/engine contract tests and documentation |
| uv-managed normal-GIL CPython `>=3.13,<3.14` with no active download | Both runtime modules/launchers; parity launcher; canary and cutover tools |
| Runner-runtime identity separate from target verification identity | Both runtime/storage/evidence suites; parity |
| Crash-consistent state and content-addressed evidence | Both storage/evidence suites |
| Accidental remote mutation defenses and stated same-UID limit | Both Git/provider suites and skill documentation |
| Real provider CLI/session behavior | Plan 3 live canaries |
| Zero live/continuable legacy gate and forensic state preservation | Plan 3 audit, abandonment digest, and apply tests |
| Provider-specific installation and no CME regression | Plan 3 routing, exact symlink apply, and final verification |
