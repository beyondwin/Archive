# CPE Operational Hardening Design

**Date:** 2026-07-14

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**Primary surface:** `skills/kws-codex-plan-executor/`

**Extends:**
`docs/superpowers/specs/2026-07-14-cpe-sequential-superpowers-runner-design.md`

## 1. Summary

Keep the current Python standard-library sequential runner and harden its
operational boundary. The work fixes process-group cleanup, bounded live logs,
single-writer resume, run-creation consistency, state semantics, result
isolation, and contract coverage without rebuilding the retired CPE queue or
moving the skill into Waygent.

The runner remains a small wrapper around approved Superpowers plans. CPE owns
only snapshots, one worktree, fresh process launch, plan-level state, bounded
retry, resume, and inspection. Superpowers continues to own implementation,
review, fixes, verification, and commits inside each plan session.

## 2. Decision And Evidence

The approved direction is targeted Python hardening rather than a Bun rewrite.

Measured on the development machine before this design:

- `python3 -c pass`: 20.37 ms median startup;
- `bun -e ''`: 4.63 ms median startup;
- the current CPE `--help`: 46.54 ms median;
- the complete deterministic CPE suite: 5.77 seconds;
- active Python runtime: 807 lines;
- evals plus the public runner script: 460 lines.

Bun has lower startup latency, but a plan run spends minutes or hours in Git,
Codex, implementation, and verification. Rewriting the runtime and all state
tests would therefore add migration and regression risk for negligible user
latency. Python also provides mature standard-library primitives for POSIX
process groups, `fsync`, file modes, and advisory locks.

The recent sequential cutover already removed the obsolete queue, mapper,
reviewer, auditor, compatibility, and export paths. The active tracked
inventory is the intended twelve files, so there is no second implementation
to preserve or migrate.

## 3. Alternatives

### 3.1 Targeted Python Hardening — Selected

Preserve the four-module runtime and public contracts. Add only the failure
boundaries that the sequential cutover did not yet cover. This has the smallest
regression surface and does not introduce another orchestration layer.

### 3.2 Contract-First Bun Rewrite — Deferred

A future rewrite would first need language-neutral black-box tests, exact
format compatibility, and a demonstrated maintenance or deployment problem
with Python. Runtime consistency with the Waygent monorepo alone is not enough:
CPE is intentionally a standalone, non-product executor skill.

### 3.3 Python Runtime With Bun Wrapper Or Tests — Rejected

A hybrid would require two runtimes and two test conventions while preserving
the same orchestration logic. It conflicts with the goal of removing duplicate
machinery.

## 4. Goals

1. Leave no Codex, shell, or test process running after timeout or interrupt.
2. Prevent two mutating invocations from operating on one run concurrently.
3. Bound log disk and memory use while a child is still running.
4. Make run creation recoverable and prevent a false `running` state when
   worktree creation fails.
5. Reject structurally valid but semantically impossible state before launch.
6. Prevent later plans from mutating earlier result evidence.
7. Remove redundant Codex output, session persistence, prompt fields, tests,
   docs, and ignored residue.
8. Preserve ordered execution, bounded retry, clean commit handoff, and the
   fifteen-second deterministic gate.

## 5. Non-Goals

This hardening does not:

- move CPE into Waygent or import Waygent packages;
- change plan order, task mapping, product-quality ownership, or merge policy;
- add task-level checkpoints, parallel plans, mapper/reviewer roles, or a
  second supervisor service;
- add a run garbage collector or delete pre-existing external evidence;
- restore prompt export, handoff export, legacy schema support, or retired
  documentation trees;
- add a credential-passthrough interface or claim that environment filtering
  is a complete secret boundary;
- rerun product verification after an accepted Superpowers handoff.

## 6. Runtime Structure

The tracked runtime remains:

```text
scripts/cpe.py                 public CLI and exit mapping
scripts/cpe_runtime/state.py   snapshots, atomic state, semantic validation
scripts/cpe_runtime/launcher.py process supervision and bounded logs
scripts/cpe_runtime/runner.py  worktree, lock, sequence, retry, reconciliation
```

No new runtime package, daemon, queue, lease manager, or database is added.
Runtime lock files and attempt outputs live under the existing private run
root and are not tracked source files.

## 7. Single Mutating Owner

`run` and `resume` take an exclusive POSIX advisory lock for the run before
mutating state or launching Codex. `inspect` remains lock-free and read-only
because `state.json` is atomically replaced.

The lock is held for the entire mutating invocation. Its file descriptor is
inherited by the Codex child so a killed CPE coordinator does not release the
run to a second `resume` while that child is still alive. A competing mutating
invocation returns an `interrupted` summary with a bounded `run_busy` error and
does not increment an attempt or start a process.

Before launch, CPE creates one private regular result placeholder and records
the incremented attempt number, `running` plan status, starting commit, and
deterministic result path. The current commit remains directly observable from
the worktree. If the coordinator dies, a later resume can identify the exact
prior result and log. It does not infer an unknown child exit code. A fresh
recovery session may validate the existing commit and result, but it must not
blindly accept an unobserved process as completed.

## 8. Process Lifecycle

`launcher.py` replaces `subprocess.run()` with an explicit `Popen()` supervisor
loop.

1. Start Codex in a new session and process group.
2. Read combined stdout and stderr through a pipe while monitoring deadline and
   interruption.
3. On timeout, `KeyboardInterrupt`, or termination, send `SIGTERM` to the whole
   process group.
4. Wait a short fixed grace period, then send `SIGKILL` to the remaining group.
5. Reap the direct child and confirm that the process group is gone before
   returning control to the runner.
6. If Codex exits while descendants remain, terminate those descendants and do
   not accept a completed handoff.

The supervisor classification is:

- operator interrupt: clean the group, mark the current plan and run
  `interrupted`, and stop the current invocation;
- timeout: clean the group, record a recoverable interrupted attempt, and use
  at most the remaining automatic recovery attempt;
- spawn failure: record a failed attempt with bounded diagnostics;
- invalid result, wrong commit, broken ancestry, or dirty completed handoff:
  fail immediately as runner-integrity failure;
- exhausted attempts: mark the current plan and run `failed`.

A completed plan requires a normally observed exit code of zero, no timeout or
forced process cleanup, a quiescent process group, a valid result, exact clean
`HEAD`, valid ancestry, and successful verification evidence.

## 9. Bounded Live Logs

The child no longer writes directly to an unbounded log file. CPE reads pipe
chunks and writes them itself.

- The retained tail is one MiB per attempt.
- The file may grow to two MiB before compaction.
- Compaction reads and rewrites at most the final one MiB; it never loads the
  complete log.
- A bounded marker records whether truncation occurred and how many bytes were
  discarded.
- The prior log is selected by numeric attempt order, not lexical filename
  order, so attempts ten and above remain correct.
- Files stay private and the recovery prompt receives only the exact latest
  attempt log path.

This bounds steady-state disk use, peak compaction memory, and recovery input
without introducing rotation directories or a logging service.

## 10. Run Creation Transaction

Run creation becomes an explicit two-phase transition using the existing
format-1 state shape and a new `initializing` status.

1. Validate the workspace, inputs, run ID, branch absence, worktree path, and
   run-root path without launching a child.
2. Snapshot inputs and atomically persist `status=initializing`.
3. Create the branch and worktree from the recorded source commit.
4. Verify repository identity, branch, path, and exact starting `HEAD`.
5. Atomically transition to `running` and begin the first attempt.

On an ordinary creation error, CPE removes only a branch or worktree proven to
have been created by the current transaction, records `failed`, emits a
bounded `run.creation_failed` event, and returns the run ID with the error. It
does not delete ambiguous or pre-existing paths.

On resume from `initializing`:

- a complete, correctly identified worktree is finalized as `running`;
- an absent worktree is recreated from the recorded source commit;
- a mismatched repository, branch, path, or commit fails closed without
  deletion.

`state.json` remains authoritative; no parallel creation journal is added.

## 11. State Semantics

State validation enforces relationships, not only field types.

- `current_plan_index` equals the length of the leading completed-plan prefix.
- Every plan before the index is `completed` and has a starting commit,
  accepted commit, and regular result file.
- A current plan may be pending, running, blocked, failed, or interrupted.
- Plans after the current plan are pending and have no starting commit,
  accepted commit, result, or attempts.
- `completed` run status requires every plan to be completed and the index to
  equal plan count.
- `blocked`, `failed`, and `interrupted` run states agree with the current plan.
- A creation failure is the only failed run allowed to have all plans pending.
- Plan input records and plan-state records have the same count and order.
- Snapshot digests, sizes, UTF-8 content, and private-root containment continue
  to be verified.
- Result paths resolve beneath `results/`, are regular files, and are not
  symlinks or directories.
- Accepted commits descend from the source and from the preceding accepted
  plan commit.

Impossible combinations fail before worktree mutation or process launch. CPE
does not guess which field should win.

## 12. Result And Sandbox Boundary

The model returns the strict result object as its final response. Codex CLI
persists that response through `--output-last-message`; the prompt no longer
asks the model to write the result file itself.

The launcher:

- removes unused `--json` event output;
- adds `--ephemeral` to avoid a second persistent Codex session transcript;
- removes the duplicate `REPOSITORY` marker when it equals `WORKTREE`;
- removes write access to the complete `results/` directory;
- gives each attempt one deterministic result path;
- makes accepted result files read-only after validation.

For every child status, reported `head_commit` must equal observed worktree
`HEAD`. Incomplete statuses may preserve dirty progress. `completed` alone
requires a clean tracked and untracked worktree, non-empty verification, and
zero for every reported verification exit code.

The current environment scrub remains a best-effort defense, not a security
boundary. This change does not add implicit credential inheritance or a new
environment policy that could break existing local verification.

## 13. Deterministic Verification

The existing three Python eval files remain the complete deterministic test
surface. They add focused cases for:

### Process And Concurrency

- a timed-out Codex child with a grandchild leaves no surviving process;
- an interrupted attempt leaves no orphan process;
- a concurrent resume returns `run_busy` and launches no second child;
- a coordinator-loss fixture preserves the lock until its child exits;
- a completed handoff is rejected when forced descendant cleanup occurred.

### Logs And Retry

- output above two MiB compacts to the bounded tail and retains a final marker;
- compaction reports discarded bytes;
- attempt ten and later select the numerically latest result and log;
- timeout consumes only the remaining bounded recovery allowance.

### Creation And State

- worktree-add failure never leaves a false running state;
- an initializing run resumes only from a verified worktree;
- mismatched branch, repository, path, or commit fails closed;
- plan/input count, completed-prefix, index, and run/plan status corruption are
  rejected;
- result symlinks, directories, and outside-root paths are rejected.

### Handoff And CLI

- broken ancestry and failed verification have dedicated fixtures;
- wrong `head_commit` is rejected for incomplete as well as completed results;
- only `run`, `resume`, and `inspect` remain public;
- installed Codex help exposes every flag used by the launcher, including
  `--ephemeral`, `--ignore-user-config`, `--output-schema`, and
  `--output-last-message`.

Tests remain sequential, network-free, credential-free, and model-free. The
complete suite must remain below fifteen seconds on the development machine.

## 14. Documentation And Cleanup

The implementation updates documentation and behavior together.

- `SKILL.md` moves to active-line version `1.1.0` and describes the hardened
  process, logging, and recovery contract.
- The skill README documents limitations and a compact change protocol: every
  CLI, exit, state, process, retry, or completion change requires a focused
  deterministic fixture.
- Root `skills/README.md` stops advertising the removed export and handoff
  commands and does not imply that every skill has `docs/` or `references/`.
- The completed-cutover `require_cutover()` skip helper is removed.
- The eval summary says `2 suites passed`, not `2 passed`.
- The two ignored `.DS_Store` files under the skill are removed.
- No architecture, history, user-guide, risk, reference, or protocol tree is
  recreated.

The active tracked skill inventory remains exactly twelve files.

## 15. Autonomous Execution Contract

Implementation must continue without asking the user to resolve ordinary
errors, defects, test failures, code-review findings, implementation choices,
or safe recovery decisions.

The implementation agent must:

1. inspect current Git, state, logs, and test evidence before acting;
2. choose the smallest reversible fix that preserves approved contracts;
3. use repository architecture, lower operational risk, and stronger
   testability as tie-breakers;
4. retry with a changed technical strategy when the first fix fails;
5. repair newly discovered in-scope defects and their regression tests;
6. avoid external side effects, destructive unrelated cleanup, credentials,
   pushes, deploys, and material scope expansion;
7. use a safe local fallback when an optional tool or path is unavailable;
8. continue through implementation, review, verification, and commit without a
   routine user-decision gate.

Because this design requires no credentials or external authority, no expected
implementation path needs a user question. If an unforeseen path would require
an unauthorized external or destructive action, the agent must choose a safe
in-scope alternative rather than requesting permission or performing the
action.

## 16. Acceptance Criteria

The hardening is complete when:

1. Python standard library remains the only CPE runtime dependency.
2. The public CLI remains `run`, `resume`, and `inspect` with existing exit
   meanings.
3. Ordered plans, immutable inputs, bounded retry, clean exact-commit handoff,
   and completed-plan resume skipping still pass.
4. Timeout and interrupt tests prove the entire child process group is gone.
5. Concurrent resume cannot launch a second child.
6. Attempt logs remain within the documented bound during execution.
7. Failed or interrupted creation cannot masquerade as a running run.
8. Semantic state corruption fails before mutation.
9. Earlier results are not writable by later plan sandboxes.
10. The tracked skill inventory remains twelve files with no ignored residue.
11. `./evals/run.sh` completes below fifteen seconds.
12. Python compilation, shell syntax, CLI help, and `git diff --check` pass.
13. Skill and root documentation match the actual interface.

## 17. Residual Risks

- POSIX process-group and advisory-lock behavior remains a platform assumption;
  Windows portability is not added by this change.
- A hard machine shutdown can leave an `initializing` run requiring the
  documented reconciliation path.
- The retained one-MiB log tail may omit early diagnostics; truncation is made
  explicit and the tail is preferred for recovery relevance.
- CPE still trusts successful product-verification evidence reported by the
  Superpowers session rather than rerunning product commands.
- Environment filtering remains best-effort and is not a substitute for Codex
  sandboxing or operator secret hygiene.

These risks are narrower than adding another runtime, state store, or
supervision service and are accepted for this standalone executor.
