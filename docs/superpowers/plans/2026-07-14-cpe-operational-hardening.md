# CPE Operational Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Because every task edits the same
> four-module runtime, prefer Inline Execution with
> `superpowers:executing-plans`; do not start a CPE run to modify CPE itself.

**Goal:** Harden the small sequential CPE runner so process interruption,
timeouts, concurrent resume, bounded logs, worktree creation, state corruption,
and result isolation fail safely without restoring retired orchestration
machinery.

**Architecture:** Keep the existing Python CLI and four runtime modules.
`state.py` enforces durable invariants, `runner.py` owns the worktree and one
mutating run lock, and `launcher.py` supervises one POSIX process group while
streaming a bounded log. The public state format and ordered plan workflow stay
intact; `initializing` is the only added run status.

**Tech Stack:** Python 3 standard library, POSIX `fcntl` and process groups,
Git worktrees, Codex CLI structured output, JSON/JSONL, Bash, `unittest`, and
temporary Git repositories.

## Global Constraints

- Approved design:
  `docs/superpowers/specs/2026-07-14-cpe-operational-hardening-design.md`.
- Base design:
  `docs/superpowers/specs/2026-07-14-cpe-sequential-superpowers-runner-design.md`.
- Preserve Python standard-library-only runtime dependencies.
- Preserve public commands `run`, `resume`, and `inspect` and exit meanings 0,
  1, 2, and 3.
- Preserve ordered plan execution, one worktree, immutable input snapshots,
  initial plus one automatic attempt, explicit failed retry, and clean exact
  commit handoff.
- Keep `state.json` at `format_version: 1`; add no legacy runner or migration
  subsystem.
- Keep the active tracked skill inventory at exactly twelve files.
- Do not add Waygent imports, Bun wrappers, databases, daemons, task mapping,
  parallel plans, mapper/reviewer roles, or duplicate product verification.
- Use POSIX process groups and advisory locking; Windows support is out of
  scope.
- Keep tests sequential, credential-free, network-free, model-free, and below
  fifteen real seconds on the development machine.
- Do not modify external run roots, external worktrees, evidence branches,
  installed Superpowers skills, Waygent runtime, or Claude executor behavior.
- Do not ask the user to resolve ordinary implementation errors, defects,
  test failures, review findings, or technical choices. Choose the smallest
  reversible, lower-risk, better-tested in-scope fix and continue.
- Do not push, deploy, publish, request credentials, or perform unrelated
  destructive cleanup.
- Use `apply_patch` for tracked edits. Preserve unrelated user changes.
- Use `code_review.md` before final completion and commit every independently
  testable task.

## File Responsibility Map

| File | Responsibility after this plan |
| --- | --- |
| `scripts/cpe.py` | Public argument parsing, JSON output, and exit mapping only |
| `scripts/cpe_runtime/state.py` | Input snapshots, format-1 state, semantic validation, atomic persistence |
| `scripts/cpe_runtime/runner.py` | Two-phase worktree creation, run lock, sequence, retry, reconciliation |
| `scripts/cpe_runtime/launcher.py` | Codex command, POSIX process-group supervision, bounded log, result read |
| `evals/fake_codex.py` | Deterministic scenarios for process, state, result, and retry contracts |
| `evals/check_runner.py` | State, runner, process, log, retry, and handoff contract tests |
| `evals/check_cli.py` | Public CLI, read-only inspect, concurrent invocation, Codex flag tests |
| `evals/run.sh` | Sequential two-suite deterministic gate |
| `SKILL.md` | Concise agent-facing execution and recovery contract |
| `README.md` | Complete user contract, limits, change protocol, inventory, verification |
| `skills/README.md` | Repository-level current skill descriptions |

## Execution Order

- Tasks 1–5 are sequential because they share state transitions and launcher
  signatures.
- Task 6 runs after all runtime behavior is green.
- There are no implementation-time human approval gates.
- Review findings are fixed in place before the final gate.

---

### Task 1: Enforce Semantic State Invariants

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py:16-286`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py:115-177`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py:34-139`

**Interfaces:**

- Consumes: Existing `StateStore.create()`, `open()`, `save()`, and strict
  format-1 field sets.
- Produces: `StateStore._validate_semantics()` and a state contract that later
  creation, locking, and process tasks may rely on.
- Produces: `RUN_STATUSES` containing `initializing`, `running`, `completed`,
  `blocked`, `failed`, and `interrupted`.

- [ ] **Step 1: Add failing state-semantic tests**

Add this helper and test method to `SequentialRunnerTest`:

```python
def assert_state_rejected(self, store: StateStore, message: str) -> None:
    with self.assertRaisesRegex(ValueError, message):
        store.save()

def test_state_rejects_impossible_plan_and_run_relationships(self) -> None:
    plans = [self.plan(1, "completed"), self.plan(2, "completed")]
    store = StateStore.create(
        run_root=self.home / "orchestrator" / "semantic-state",
        run_id="semantic-state",
        source_repository=self.repo,
        source_commit=git(self.repo, "rev-parse", "HEAD"),
        worktree=self.home / "worktrees" / "semantic-state",
        branch="codex/semantic-state",
        specs=[],
        plans=plans,
    )
    store.state["current_plan_index"] = 1
    self.assert_state_rejected(store, "completed prefix")

    store.state["current_plan_index"] = 0
    store.state["plans"].append(dict(store.state["plans"][0]))
    self.assert_state_rejected(store, "plan input count")
```

Add a second test that marks plan 1 completed with non-null 40-hex commits but
no result path and expects `completed plan evidence is incomplete`. Add a third
case where plan 2 has `attempt_count=1` while plan 1 is current and expect
`future plan is not pristine`.

- [ ] **Step 2: Run RED and confirm semantic corruption is currently accepted**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
env PYTHONDONTWRITEBYTECODE=1 python3 \
  evals/check_runner.py \
  SequentialRunnerTest.test_state_rejects_impossible_plan_and_run_relationships
```

Expected: FAIL because `StateStore.save()` currently accepts at least the
completed-prefix mutation or raises an unrelated indexing error for the count
mutation.

- [ ] **Step 3: Implement semantic validation after structural validation**

Add `initializing` to the run enum and call a new method at the end of
`_validate()`:

```python
RUN_STATUSES = {
    "initializing", "running", "completed", "blocked", "failed", "interrupted"
}

def _validate_semantics(self, plan_ids: list[str]) -> None:
    state = self.state
    plans = state["plans"]
    if len(plan_ids) != len(plans):
        raise ValueError("plan input count does not match plan state")

    completed_prefix = 0
    for plan in plans:
        if plan["status"] != "completed":
            break
        completed_prefix += 1
    if state["current_plan_index"] != completed_prefix:
        raise ValueError("current plan index does not match completed prefix")

    for position, plan in enumerate(plans):
        if position < completed_prefix:
            if not all(plan[name] is not None for name in (
                "starting_commit", "accepted_commit", "result_path"
            )):
                raise ValueError("completed plan evidence is incomplete")
        elif position > completed_prefix:
            if plan != {
                "plan_id": plan["plan_id"],
                "status": "pending",
                "starting_commit": None,
                "accepted_commit": None,
                "attempt_count": 0,
                "result_path": None,
            }:
                raise ValueError("future plan is not pristine")

    if completed_prefix == len(plans):
        if state["status"] != "completed":
            raise ValueError("all plans complete but run is not completed")
        return

    current = plans[completed_prefix]
    if current["status"] == "pending":
        if current != {
            "plan_id": current["plan_id"],
            "status": "pending",
            "starting_commit": None,
            "accepted_commit": None,
            "attempt_count": 0,
            "result_path": None,
        }:
            raise ValueError("pending current plan is not pristine")
    elif (
        current["attempt_count"] < 1
        or current["starting_commit"] is None
        or current["result_path"] is None
        or current["accepted_commit"] is not None
    ):
        raise ValueError("active current plan evidence is incomplete")

    allowed = {
        "initializing": {"pending"},
        "running": {"pending", "running"},
        "blocked": {"blocked"},
        "failed": {"failed", "pending"},
        "interrupted": {"pending", "interrupted"},
    }
    if current["status"] not in allowed.get(state["status"], set()):
        raise ValueError("run and current plan statuses disagree")
```

Call `self._validate_semantics(plan_ids)` only after every input and plan record
has passed type and field validation. Before indexing `plan_ids[position]`,
compare the two lengths so malformed state always raises `ValueError`, never
`IndexError`.

When `result_path` is present, validate the declared path before resolution and
the resolved target after containment:

```python
declared_result = Path(record["result_path"])
if declared_result.is_symlink():
    raise ValueError("result must not be a symlink")
result = _inside(declared_result, results_root, "result")
if not result.is_file():
    raise ValueError("result must be a regular file")
```

- [ ] **Step 4: Make incomplete attempt transitions satisfy the new invariant**

In `SequentialRunner._execute()`, persist the child status on both plan and
run before a bounded automatic recovery begins:

```python
plan["status"] = status
state["status"] = status
store.save()
store.append_event(
    "plan.attempt_incomplete",
    plan_id=plan["plan_id"],
    status=status,
)
```

At the next attempt start, the existing assignment of both statuses to
`running` restores the running invariant. Keep `blocked` as an immediate
return. Keep final exhaustion as `failed`.

When a completed plan advances past the final index, set the run status before
the same atomic save:

```python
state["current_plan_index"] += 1
state["status"] = (
    "completed"
    if state["current_plan_index"] == len(state["plans"])
    else "running"
)
store.save()
```

- [ ] **Step 5: Run focused GREEN and the existing runner suite**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py
```

Expected: all existing tests plus the new semantic-state cases pass.

- [ ] **Step 6: Commit semantic state validation**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "fix(cpe): enforce semantic run state"
```

---

### Task 2: Make Worktree Creation Recoverable

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py:70-158`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py:41-113`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

- Consumes: Task 1 `initializing` status and semantic state contract.
- Produces: `SequentialRunner._create_or_reconcile_worktree(store)`.
- Produces: durable `initializing -> running|failed` creation transitions.

- [ ] **Step 1: Write failing creation and reconciliation tests**

Add a deterministic runner subclass to `check_runner.py`:

```python
class FailingCreateRunner(SequentialRunner):
    def _add_new_worktree(self, store: StateStore) -> None:
        raise subprocess.CalledProcessError(128, ["git", "worktree", "add"])
```

Add these tests:

```python
def test_worktree_creation_failure_never_leaves_running_state(self) -> None:
    runner = FailingCreateRunner(codex_home=self.home, launcher=self.runner().launcher)
    result = runner.run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "completed")],
        run_id="create-failure",
    )
    self.assertEqual(result["status"], "failed")
    state = json.loads(
        (self.home / "orchestrator" / "create-failure" / "state.json").read_text()
    )
    self.assertEqual(state["status"], "failed")
    self.assertFalse((self.home / "worktrees" / "create-failure").exists())

def test_resume_reconciles_verified_initializing_worktree(self) -> None:
    runner = self.runner()
    store = runner._initialize_run(
        workspace=self.repo,
        specs=[],
        plans=[self.plan(1, "completed")],
        run_id="reconcile-create",
    )
    runner._add_new_worktree(store)
    self.assertEqual(store.state["status"], "initializing")
    result = runner.resume(run_id="reconcile-create")
    self.assertEqual(result["status"], "completed")
```

- [ ] **Step 2: Run RED and confirm run creation still raises externally**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py \
  SequentialRunnerTest.test_worktree_creation_failure_never_leaves_running_state \
  SequentialRunnerTest.test_resume_reconciles_verified_initializing_worktree
```

Expected: FAIL because the runner has no `_initialize_run()`, no overridable
worktree creation boundary, and currently persists `running` before Git add.

- [ ] **Step 3: Split initialization from verified worktree creation**

Extract the state-only part of `run()`:

```python
@staticmethod
def _validate_workspace(repository: Path) -> None:
    if (
        not repository.is_dir()
        or _git(repository, "rev-parse", "--is-inside-work-tree") != "true"
    ):
        raise ValueError("workspace must be a Git repository")
    if _git(repository, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("workspace has tracked changes")

def _initialize_run(
    self,
    *,
    workspace: Path,
    specs: Sequence[Path],
    plans: Sequence[Path],
    run_id: str,
) -> StateStore:
    repository = workspace.resolve(strict=True)
    self._validate_workspace(repository)
    source_commit = _git(repository, "rev-parse", "HEAD")
    store = StateStore.create(
        run_root=self.codex_home / "orchestrator" / run_id,
        run_id=run_id,
        source_repository=repository,
        source_commit=source_commit,
        worktree=self.codex_home / "worktrees" / run_id,
        branch=f"codex/{run_id}",
        specs=specs,
        plans=plans,
        initial_status="initializing",
    )
    return store
```

Add `initial_status: str = "initializing"` to `StateStore.create()`, use it for
the initial state instead of hard-coding `running`, and pass the same value to
the initial `run.created` event.

- [ ] **Step 4: Implement idempotent worktree creation and reconciliation**

Add these runner boundaries:

```python
def _add_new_worktree(self, store: StateStore) -> None:
    state = store.state
    worktree = Path(state["worktree"])
    worktree.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    worktree.parent.chmod(0o700)
    subprocess.run(
        [
            "git", "-C", state["source_repository"], "worktree", "add", "-q",
            "-b", state["branch"], str(worktree), state["source_commit"],
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

def _cleanup_created_worktree(self, store: StateStore) -> None:
    state = store.state
    source = Path(state["source_repository"])
    worktree = Path(state["worktree"])
    if worktree.exists():
        try:
            self._verify_worktree(store, allow_initializing=True)
        except (OSError, ValueError, subprocess.SubprocessError):
            return
        subprocess.run(
            ["git", "-C", str(source), "worktree", "remove", "--force", str(worktree)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    branch_head = _git(source, "rev-parse", "--verify", state["branch"], check=False)
    if branch_head == state["source_commit"]:
        subprocess.run(
            ["git", "-C", str(source), "branch", "-D", state["branch"]],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

def _create_or_reconcile_worktree(self, store: StateStore) -> None:
    state = store.state
    worktree = Path(state["worktree"])
    if not worktree.exists():
        source = Path(state["source_repository"])
        branch_head = _git(
            source, "rev-parse", "--verify", state["branch"], check=False
        )
        if branch_head and branch_head != state["source_commit"]:
            raise ValueError("initializing branch is not at the source commit")
        if branch_head:
            subprocess.run(
                [
                    "git", "-C", str(source), "worktree", "add", "-q",
                    str(worktree), state["branch"],
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        else:
            self._add_new_worktree(store)
    self._verify_worktree(store, allow_initializing=True)
    state["status"] = "running"
    store.save()
    store.append_event("worktree.ready", head=state["source_commit"])
```

Extend `_verify_worktree()` with `allow_initializing: bool = False`. After its
existing repository and branch checks, require this additional condition:

```python
if allow_initializing and current_head != state["source_commit"]:
    raise ValueError("initializing worktree is not at the source commit")
```

A branch collision, different repository, different path, or different commit
raises without deletion.

In `resume()`, open state before ordinary worktree verification and route only
`initializing` through reconciliation:

```python
store = StateStore.open(self.codex_home / "orchestrator" / run_id)
if store.state["status"] == "initializing":
    self._create_or_reconcile_worktree(store)
else:
    self._verify_worktree(store)
```

- [ ] **Step 5: Persist a bounded failed creation result instead of throwing**

Wrap only the creation transaction in `run()`:

```python
try:
    self._create_or_reconcile_worktree(store)
except (OSError, ValueError, subprocess.SubprocessError) as exc:
    self._cleanup_created_worktree(store)
    store.state["status"] = "failed"
    store.save()
    reason = (str(exc).strip() or type(exc).__name__)[:2000]
    store.append_event("run.creation_failed", reason=reason)
    return self._summary(store, error=reason)
return self._execute(store, explicit_retry=False)
```

Before `StateStore.create()`, use `git show-ref --verify --quiet` to reject an
existing branch. `_cleanup_created_worktree()` may therefore remove only a
worktree whose repository, branch, and exact source `HEAD` pass
`_verify_worktree()`, followed by that exact branch when it still resolves to
the source commit. If any proof fails, the helper returns without deletion and
the run remains failed.

- [ ] **Step 6: Run GREEN and verify existing creation behavior**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py
```

Expected: creation failure and initializing reconciliation pass without
regressing sequential execution or resume.

- [ ] **Step 7: Commit two-phase creation**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "fix(cpe): make worktree creation recoverable"
```

---

### Task 3: Serialize Mutating Runs And Persist Attempt Identity

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

- Consumes: Task 2 initialized run root and verified worktree.
- Produces: `_RunLock.__enter__()` returning a held descriptor.
- Produces: `CodexLauncher.attempt_paths()` and a launcher call with the held
  descriptor passed as `lock_fd`.
- Produces: a pre-created expected result file persisted before child spawn.

- [ ] **Step 1: Add a blocking fake scenario and concurrent-resume RED test**

Add `blocking_completed` to `SCENARIOS`. In `fake_codex.py`, signal readiness
and wait for a test-owned release file before completing:

```python
elif scenario == "blocking_completed":
    ready = Path(os.environ["CPE_FAKE_READY"])
    release = Path(os.environ["CPE_FAKE_RELEASE"])
    ready.write_text(str(os.getpid()), encoding="utf-8")
    deadline = time.monotonic() + 5
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not release.exists():
        raise SystemExit("blocking fixture was not released")
    head = commit_plan(worktree, plan_id)
    status = "completed"
```

Add a test that starts one run in a helper Python process, waits for the ready
file, calls `resume` in the test process, and asserts:

```python
self.assertEqual(second["status"], "interrupted")
self.assertEqual(second["error"], "run_busy")
self.assertEqual(len(self.invocations()), 1)
```

Then create the release file, wait for the first process, and assert its result
is completed.

Add `test_coordinator_loss_keeps_the_child_lock`. Start the same blocking CLI,
wait for the child-ready file, send `SIGKILL` only to the CPE coordinator, and
run a second `resume` before releasing the child. Require `run_busy` and one
recorded invocation. After creating the release file and observing the child
exit, run `resume` again and require a second recovery invocation to validate
the existing worktree rather than blindly accepting an unobserved exit code.

- [ ] **Step 2: Run RED and prove concurrent execution is currently possible**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py \
  SequentialRunnerTest.test_concurrent_resume_does_not_launch_a_second_child
```

Expected: FAIL because there is no run lock or because the second invocation
mutates the same running plan.

- [ ] **Step 3: Implement one POSIX advisory run lock**

Add to `runner.py`:

```python
import fcntl

class RunBusyError(RuntimeError):
    pass

class _RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: int | None = None

    def __enter__(self) -> int:
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise RunBusyError("run_busy") from exc
        self.descriptor = descriptor
        return descriptor

    def __exit__(self, *_: object) -> None:
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None
```

Wrap the complete mutating portion of `run()` and `resume()` with
`_RunLock(store.root / "run.lock")`. On `RunBusyError`, return `_summary()`
with status overridden to `interrupted` and error `run_busy`; do not save that
transient public status into the authoritative run state.

```python
result = self._summary(store, error="run_busy")
result["status"] = "interrupted"
return result
```

- [ ] **Step 4: Persist the deterministic attempt result before spawn**

Change the launcher interface:

```python
@staticmethod
def attempt_paths(
    results_directory: Path,
    logs_directory: Path,
    plan_id: str,
    attempt: int,
) -> tuple[Path, Path]:
    return (
        results_directory / f"{plan_id}-attempt-{attempt}.json",
        logs_directory / f"{plan_id}-attempt-{attempt}.log",
    )

def launch(
    self,
    *,
    worktree: Path,
    plan_id: str,
    plan_path: Path,
    spec_paths: Sequence[Path],
    starting_commit: str,
    current_commit: str,
    result_path: Path,
    log_path: Path,
    lock_fd: int,
    prior_result: Path | None = None,
    prior_log: Path | None = None,
) -> LaunchResult:
    """Launch one attempt using caller-owned paths and the held run lock."""
```

In `_execute()`, calculate prior evidence before incrementing, create the new
result file with exclusive mode, and save its path before launch:

```python
previous_attempt = plan["attempt_count"]
prior_result = Path(plan["result_path"]) if plan["result_path"] else None
prior_log = (
    store.root / "logs" / f"{plan['plan_id']}-attempt-{previous_attempt}.log"
    if previous_attempt else None
)
plan["attempt_count"] += 1
result_path, log_path = self.launcher.attempt_paths(
    store.root / "results", store.root / "logs",
    plan["plan_id"], plan["attempt_count"],
)
descriptor = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.close(descriptor)
plan["result_path"] = str(result_path.resolve())
plan["status"] = "running"
state["status"] = "running"
store.save()
```

Add `pass_fds=(lock_fd,)` to the existing `subprocess.run()` call until Task 4
replaces that call with `Popen()`. Remove `_latest_log()` and glob sorting.

- [ ] **Step 5: Run GREEN and verify lock inheritance**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py
```

Expected: only one blocking child invocation is recorded, the competing
resume returns `run_busy`, coordinator loss retains the child-held lock, and
all pre-existing tests pass.

- [ ] **Step 6: Commit single-owner execution**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "fix(cpe): serialize mutating plan runs"
```

---

### Task 4: Supervise Process Groups And Bound Live Logs

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py:18-149`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py:115-211`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

- Consumes: Task 3 explicit attempt paths and inherited run-lock descriptor.
- Produces: `_BoundedLog` with one-MiB retained and two-MiB compact thresholds.
- Produces: process-group `TERM -> grace -> KILL -> reap` lifecycle.
- Produces: `LaunchResult` fields `forced_cleanup` and
  `discarded_log_bytes` in addition to existing payload and exit evidence.

- [ ] **Step 1: Add timeout-grandchild and large-log fake scenarios**

Add `timeout_grandchild` and `large_log` scenarios:

```python
elif scenario == "timeout_grandchild":
    pid_path = Path(os.environ["CPE_FAKE_GRANDCHILD_PID"])
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pid_path.write_text(str(grandchild.pid), encoding="utf-8")
    while True:
        print("waiting for timeout", flush=True)
        time.sleep(0.05)
elif scenario == "large_log":
    sys.stdout.buffer.write(b"x" * (2_200_000))
    sys.stdout.buffer.write(b"CPE_FINAL_LOG_MARKER\n")
    sys.stdout.flush()
    head = commit_plan(worktree, plan_id)
    status = "completed"
```

Add tests that use a launcher timeout of `0.25` seconds and termination grace
of `0.10` seconds. After timeout, poll `os.kill(pid, 0)` for at most one second
and require `ProcessLookupError`. For the large log, require:

```python
self.assertLessEqual(log_path.stat().st_size, 1_048_576)
self.assertIn(b"CPE_FINAL_LOG_MARKER", log_path.read_bytes())
self.assertGreater(outcome.discarded_log_bytes, 0)
```

Add `test_keyboard_interrupt_kills_the_complete_process_group`. Start the
public CPE CLI with the same grandchild fixture, wait for the PID file, send
`SIGINT` to the CPE process, and assert exit code 3 before checking that the
grandchild PID disappears:

```python
process.send_signal(signal.SIGINT)
stdout, stderr = process.communicate(timeout=2)
self.assertEqual(process.returncode, 3, stderr)
self.assertEqual(json.loads(stdout)["status"], "interrupted")
with self.assertRaises(ProcessLookupError):
    os.kill(int(pid_path.read_text()), 0)
```

- [ ] **Step 2: Run RED and prove descendants and logs are not bounded live**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py \
  SequentialRunnerTest.test_timeout_kills_the_complete_process_group \
  SequentialRunnerTest.test_keyboard_interrupt_kills_the_complete_process_group \
  SequentialRunnerTest.test_large_log_retains_only_a_bounded_tail
```

Expected: FAIL because timeout kills only the direct process and the existing
launcher truncates only after reading the complete file.

- [ ] **Step 3: Implement a bounded binary tail writer**

Add to `launcher.py`:

```python
_RETAINED_LOG_BYTES = 1_048_576
_COMPACT_AT_BYTES = 2_097_152

class _BoundedLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream = path.open("w+b")
        self.total_bytes = 0
        self.discarded_bytes = 0

    def write(self, chunk: bytes) -> None:
        self.stream.seek(0, os.SEEK_END)
        self.stream.write(chunk)
        self.total_bytes += len(chunk)
        if self.stream.tell() >= _COMPACT_AT_BYTES:
            self._compact()

    def _compact(self) -> None:
        self.stream.flush()
        end = self.stream.seek(0, os.SEEK_END)
        marker_budget = 96
        tail_size = max(0, _RETAINED_LOG_BYTES - marker_budget)
        self.stream.seek(max(0, end - tail_size))
        tail = self.stream.read(tail_size)
        self.discarded_bytes = max(0, self.total_bytes - len(tail))
        marker = (
            f"[cpe log truncated; discarded_bytes={self.discarded_bytes}]\n"
        ).encode("ascii")
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(marker + tail[-(_RETAINED_LOG_BYTES - len(marker)):])
        self.stream.flush()

    def close(self) -> None:
        if self.stream.seek(0, os.SEEK_END) > _RETAINED_LOG_BYTES:
            self._compact()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.path.chmod(0o600)
```

The implementation must keep the final file at or below one MiB, including
the marker. It must never call `read_bytes()` on the complete log.

- [ ] **Step 4: Implement the process-group supervisor loop**

Use `Popen()` with a pipe and inherited lock descriptor:

```python
process = subprocess.Popen(
    command,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    env=environment,
    pass_fds=(lock_fd,),
)
assert process.stdin is not None and process.stdout is not None
process.stdin.write(prompt.encode("utf-8"))
process.stdin.close()
```

Read `os.read(process.stdout.fileno(), 65_536)` through
`selectors.DefaultSelector` with a maximum `0.05` second poll interval. Compare
`time.monotonic()` with the fixed deadline on every poll.

Add exact group helpers:

```python
def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False

def _terminate_group(process_group: int, grace_seconds: float) -> bool:
    forced = False
    if _group_exists(process_group):
        os.killpg(process_group, signal.SIGTERM)
        deadline = time.monotonic() + grace_seconds
        while _group_exists(process_group) and time.monotonic() < deadline:
            time.sleep(0.02)
        if _group_exists(process_group):
            forced = True
            os.killpg(process_group, signal.SIGKILL)
    return forced
```

On timeout, call `_terminate_group(process.pid, grace)`, reap with
`process.wait()`, drain remaining pipe bytes into `_BoundedLog`, and return
`timed_out=True`. On `KeyboardInterrupt`, perform the same cleanup and log
finalization, then re-raise. On normal child exit, check the group and clean any
remaining descendants; set `forced_cleanup=True` when cleanup was required.

In the `run()` and `resume()` interrupt handlers, update both levels before the
atomic save:

```python
index = store.state["current_plan_index"]
if index < len(store.state["plans"]):
    current = store.state["plans"][index]
    if current["status"] == "running":
        current["status"] = "interrupted"
store.state["status"] = "interrupted"
store.save()
store.append_event("run.interrupted", plan_index=index)
```

- [ ] **Step 5: Make timeout recoverable and forced cleanup ineligible for completion**

Extend `LaunchResult`:

```python
@dataclass(frozen=True)
class LaunchResult:
    payload: dict[str, object] | None
    returncode: int | None
    timed_out: bool
    forced_cleanup: bool
    discarded_log_bytes: int
    result_path: Path
    log_path: Path
```

In `_handoff_error()`, reject a completed result when return code is nonzero,
timeout occurred, or descendants required cleanup. In `_execute()`, translate
a known timeout with no valid child result into an interrupted attempt so the
existing bounded automatic recovery may run once. Malformed output without a
known supervisor timeout remains immediate `invalid_result`.

Handle supervisor evidence before calling `_handoff_error()`:

```python
if outcome.timed_out:
    plan["status"] = "interrupted"
    state["status"] = "interrupted"
    store.save()
    store.append_event(
        "plan.attempt_incomplete",
        plan_id=plan["plan_id"],
        status="interrupted",
        timed_out=True,
    )
    continue
integrity_error = self._handoff_error(store, plan, outcome)
```

- [ ] **Step 6: Run GREEN and measure the focused suite**

```bash
env PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -p python3 evals/check_runner.py
```

Expected: all process, log, retry, and existing runner tests pass; focused
runner suite remains comfortably below the full fifteen-second ceiling.

- [ ] **Step 7: Commit the process and log boundary**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "fix(cpe): bound child processes and logs"
```

---

### Task 5: Harden Result And Sandbox Handoffs

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py:50-149`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py:184-211`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py:19-111`

**Interfaces:**

- Consumes: Task 4 supervisor evidence and explicit result path.
- Produces: minimal ephemeral Codex command and one read-only accepted result.
- Produces: exact `HEAD` validation for every child status and dedicated
  ancestry and verification fixtures.
- Produces: `CodexLauncher._command()` as a pure command-shape boundary.

- [ ] **Step 1: Add missing handoff fixture scenarios and RED assertions**

Add scenarios:

```text
broken_ancestry
verification_failed
wrong_commit_interrupted
nonzero_completed
```

Implement their result mutations explicitly:

```python
elif scenario == "broken_ancestry":
    git(worktree, "checkout", "--orphan", "fake-unrelated")
    for child in worktree.iterdir():
        if child.name != ".git" and child.is_file():
            child.unlink()
    head = commit_plan(worktree, plan_id)
    status = "completed"
elif scenario == "verification_failed":
    head = commit_plan(worktree, plan_id)
    status = "completed"
elif scenario == "wrong_commit_interrupted":
    head = "0" * 40
    status = "interrupted"
elif scenario == "nonzero_completed":
    head = commit_plan(worktree, plan_id)
    status = "completed"
```

For `verification_failed`, emit one verification with exit 1. For
`nonzero_completed`, write the valid result and finish with:

```python
if scenario == "nonzero_completed":
    return 1
return 0 if status == "completed" else 1
```

Add subtests requiring all four scenarios to produce a failed run.

- [ ] **Step 2: Add a CLI command-shape test before changing the launcher**

Extract a pure `_command(worktree, result_path)` method, call it directly in a
launcher unit test, call `_prompt()` directly for the prompt, and assert:

```python
self.assertIn("--ephemeral", command)
self.assertNotIn("--json", command)
self.assertNotIn("--add-dir", command)
self.assertEqual(command.count("--output-last-message"), 1)
self.assertNotIn("REPOSITORY:", prompt)
self.assertIn("WORKTREE:", prompt)
self.assertNotIn("Write only the fixed schema result to RESULT_PATH", prompt)
```

In `check_cli.py`, run `codex exec --help` and require the locally installed
CLI to expose `--ephemeral`, `--ignore-user-config`, `--output-schema`, and
`--output-last-message`. Resolve the real executable with
`shutil.which("codex", path=os.environ["PATH"])` before the test prepends its
fake binary directory. This command performs no network or model call.

- [ ] **Step 3: Run RED for missing fixtures and redundant command flags**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_cli.py
```

Expected: the new result scenarios or command-shape assertions fail while the
pre-existing contracts remain green.

- [ ] **Step 4: Minimize the Codex command and prompt**

Implement `_command()` with this exact shape:

```python
return [
    self.codex_bin,
    "exec",
    "--ignore-user-config",
    "--ephemeral",
    "--sandbox",
    "workspace-write",
    "-C",
    str(worktree),
    "--output-schema",
    str(self.schema_path),
    "--output-last-message",
    str(result_path),
    "-",
]
```

Keep `WORKTREE`, current plan, ordered specs, starting/current commits, prior
evidence paths, repository instruction discovery, and the exact completion
contract. Remove the duplicate repository marker and instruct the child to
return only the schema object as its final response. Do not grant the model
write access to the complete results directory.

- [ ] **Step 5: Validate every reported head and protect accepted results**

In `_handoff_error()`, observe the worktree head before branching on child
status:

```python
worktree = Path(store.state["worktree"])
observed = _git(worktree, "rev-parse", "HEAD")
if head != observed:
    return "wrong_head"
if subprocess.run(
    ["git", "-C", str(worktree), "merge-base", "--is-ancestor",
     plan["starting_commit"], head],
    check=False,
).returncode != 0:
    return "broken_ancestry"
if payload["status"] != "completed":
    return None
```

Then retain completed-only cleanliness and successful verification checks. A
completed child also requires `returncode == 0`, `timed_out is False`, and
`forced_cleanup is False`. After accepting the handoff, set the result file to
mode `0400`. Incomplete result files remain private `0600` for recovery.

- [ ] **Step 6: Run the complete behavior suite**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_runner.py
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_cli.py
```

Expected: all handoff scenarios, command-shape assertions, Codex help flags,
and prior behavior pass.

- [ ] **Step 7: Commit result and sandbox hardening**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py \
  skills/kws-codex-plan-executor/evals/check_cli.py
git commit -m "fix(cpe): harden result handoffs"
```

---

### Task 6: Align Skill Documentation And Run The Final Gate

**Files:**

- Modify: `skills/kws-codex-plan-executor/SKILL.md:1-38`
- Modify: `skills/kws-codex-plan-executor/README.md:1-105`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh:1-8`
- Modify: `skills/README.md:1-60`
- Remove ignored: `skills/kws-codex-plan-executor/.DS_Store`
- Remove ignored: `skills/kws-codex-plan-executor/evals/.DS_Store`
- Reference: `code_review.md`

**Interfaces:**

- Consumes: Tasks 1–5 final CLI, state, process, log, and result contracts.
- Produces: version `1.1.0`, accurate user docs, compact change protocol, and
  the final verification record.

- [ ] **Step 1: Make documentation drift fail in the CLI suite**

Add assertions in `check_cli.py`:

```python
def test_skill_docs_match_hardened_public_contract(self) -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    self.assertIn('version: "1.1.0"', skill)
    for phrase in (
        "process group", "bounded", "run_busy", "initializing", "Change Protocol"
    ):
        self.assertIn(phrase, skill + readme)
    root_index = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    self.assertNotIn("내보내기", root_index)
```

- [ ] **Step 2: Run RED and confirm current docs are stale**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_cli.py \
  SequentialCliTest.test_skill_docs_match_hardened_public_contract
```

Expected: FAIL on version `1.0.0`, missing hardened terms, or the root skill
index's removed export description.

- [ ] **Step 3: Update the two CPE contracts without adding documents**

In `SKILL.md`:

- set `version: "1.1.0"` and `updated_at: "2026-07-14"`;
- keep only the three public commands;
- state that one mutating run is allowed, process groups are cleaned on
  timeout/interrupt, logs retain a bounded tail, and resume validates
  initializing and interrupted state;
- preserve Superpowers ownership and bounded retry wording.

In `README.md`, add exact sections `Operational Safety`, `Limitations`, and
`Change Protocol`. The protocol text must require a focused deterministic
fixture for every change to CLI, exit codes, state, process lifecycle, retry,
or completion acceptance. Keep the twelve-file inventory unchanged.

- [ ] **Step 4: Correct repository-level skill descriptions and eval output**

Change the CPE row in `skills/README.md` to:

```markdown
| [`kws-codex-plan-executor`](./kws-codex-plan-executor/) | 승인된 Superpowers 구현 계획을 고정 순서로 실행하고 중단 후 재개하는 소형 Codex 실행기. |
```

Change the general documentation sentence to point first to each `SKILL.md`
and then to files that actually exist. Remove `require_cutover()` and its two
call sites from `check_cli.py`. Change the last line of `evals/run.sh` to:

```bash
echo "2 suites passed"
```

- [ ] **Step 5: Remove only the two approved ignored residue files**

First prove both paths are inside the skill, then remove those exact files:

```bash
test -f skills/kws-codex-plan-executor/.DS_Store
test -f skills/kws-codex-plan-executor/evals/.DS_Store
rm -f -- \
  skills/kws-codex-plan-executor/.DS_Store \
  skills/kws-codex-plan-executor/evals/.DS_Store
```

Do not run a recursive cleanup and do not touch external run evidence.

- [ ] **Step 6: Run the focused docs and deterministic gate**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
env PYTHONDONTWRITEBYTECODE=1 python3 evals/check_cli.py
/usr/bin/time -p ./evals/run.sh
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
codex exec --help
```

Expected: both suites pass, the measured `real` time is below 15 seconds, shell
syntax is valid, only three CPE commands are shown, and every launcher flag is
present in Codex help.

- [ ] **Step 7: Compile, remove generated residue, and assert inventory**

```bash
python3 -m py_compile \
  scripts/cpe.py \
  scripts/cpe_runtime/*.py \
  evals/*.py
rm -rf -- \
  scripts/__pycache__ \
  scripts/cpe_runtime/__pycache__ \
  evals/__pycache__
git ls-files . | sort
git status --ignored --short -- .
```

Expected: the tracked list is exactly the twelve files in `README.md`; ignored
status contains no `.DS_Store`, `__pycache__`, or `.pyc` below the skill.

- [ ] **Step 8: Perform the repository review and patch-hygiene gate**

From the repository root:

```bash
cd /Users/kws/source/private/Archive
git diff --check
git status --short --branch --untracked-files=all
git diff --stat HEAD~5..HEAD
```

Use `code_review.md` and inspect correctness, regression risk, verification,
scope, security/privacy, and observability. Fix every in-scope finding with a
focused regression test, rerun the affected suite, and repeat `git diff
--check`. Do not ask the user to choose among ordinary fixes.

- [ ] **Step 9: Commit documentation and final cleanup**

```bash
git add \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/evals/check_cli.py \
  skills/kws-codex-plan-executor/evals/run.sh \
  skills/README.md
git commit -m "docs(cpe): document operational hardening"
git status --short --branch --untracked-files=all
```

Expected: the commit succeeds and the worktree is clean. The branch is not
pushed, merged, or deployed by this plan.

---

## Final Verification Checklist

- [ ] `./evals/run.sh` passes below 15 real seconds.
- [ ] `python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py`
  succeeds.
- [ ] `bash -n evals/run.sh` succeeds.
- [ ] All four CLI help commands succeed and only three public CPE commands
  exist.
- [ ] `codex exec --help` contains every launcher flag.
- [ ] Timeout and interrupt fixtures leave no surviving descendant.
- [ ] Concurrent resume records one child invocation.
- [ ] Large log fixture is at most one MiB and retains its final marker.
- [ ] Creation failure is durable `failed`, never false `running`.
- [ ] Semantic state corruption fails before mutation.
- [ ] Broken ancestry, wrong incomplete head, failed verification, and nonzero
  completed process are rejected.
- [ ] Skill version is `1.1.0` and docs match behavior.
- [ ] Tracked inventory remains twelve files and ignored residue is absent.
- [ ] `git diff --check` succeeds and `code_review.md` has no unresolved
  in-scope findings.
- [ ] Worktree is clean and no push, merge, deploy, or external cleanup
  occurred.
