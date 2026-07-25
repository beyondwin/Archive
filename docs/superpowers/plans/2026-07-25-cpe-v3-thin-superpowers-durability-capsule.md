# CPE v3 Thin Superpowers Durability Capsule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CPE 2.1 with a small CPE v3 runtime that gives one Codex Superpowers root controller a durable multi-document run/worktree/session boundary without owning task, review, verification, or completion semantics.

**Architecture:** Build a clean-room format-5 runtime in five focused Python standard-library modules: state, Git, controller, runtime, and CLI. The runtime byte-snapshots an ordered caller-supplied document bundle without classifying or reviewing it, creates or explicitly adopts one worktree, launches one selected Superpowers skill, resumes the same Codex session first, permits one fresh fallback only for explicit session loss, and publishes only a mechanical `handed_off` Git receipt. Existing format-3/4 artifacts and the paused recovery branch remain read-only forensic evidence.

**Tech Stack:** Python 3 standard library, Git CLI, Codex CLI JSONL, POSIX `fcntl`/process groups, `unittest`, Bash, Bun repository verification.

## Global Constraints

- Governing design: `docs/superpowers/specs/2026-07-25-cpe-v3-thin-superpowers-durability-capsule-design.md`.
- Companion runner boundary: `docs/superpowers/specs/2026-07-25-provider-plan-runners-thin-superpowers-boundary-design.md`.
- Use direct `subagent-driven-development`; never use CPE to modify CPE.
- Preserve `/Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery`, branch `codex/cpe-thin-superpowers-v62-recovery`, committed HEAD `0450c65252368cc7c49a755ec909d7085aef4141`, and its five paused Fix Round 5 modifications unchanged.
- One CPE run is one execution contract with one branch, worktree, and root controller at a time; it accepts one globally ordered sequence of repeatable `--document` inputs.
- Superpowers exclusively owns task decomposition, `progress.md`, TDD, implementation, review, fix rounds, verification selection/execution/meaning, and engineering completion.
- CPE must not classify, lint, parse, cross-check, approve, or judge the completeness of caller-supplied documents. It only establishes exact-byte identity and safe local paths.
- CPE must not contain or persist plan queues, task IDs, review/finding/obligation state, verification arrays, final-review receipts, or migration authority.
- New run-state `format_version` is exactly `5`; public CPE release contract is exactly `3`.
- New run roots live under `${CODEX_HOME:-~/.codex}/cpe-v3/runs/<run-id>/`; legacy `~/.codex/orchestrator/<run-id>/` roots remain read-only.
- Python production runtime uses only the standard library and targets POSIX hosts.
- Default sandbox is `workspace-write`; `danger-full-access` is explicit at run creation and immutable.
- All controller launches use `--ignore-user-config`, `--ignore-rules`, `--strict-config`, `-c 'approval_policy="never"'`, and the persisted sandbox.
- Initial, resumed, and fallback controllers use the same sealed Git author/committer name and email.
- CPE never stores a full controller transcript by default.
- CPE never merges, pushes, opens a PR, tags, publishes, releases, or deploys. The implementation workflow may merge the finished Archive branch to local `main` only in Task 9.
- Target production runtime is 1,000–1,400 Python lines, with a hard ceiling of 1,500; no production module may exceed 450 lines without a concrete whole-diff-review justification.
- Each task follows RED → focused GREEN → focused regression → `git diff --check` → narrow non-amend commit.
- Run the complete `./evals/run.sh` only at the final clean candidate revision after focused task verification; release live canaries are separate opt-in evidence.

---

## File And Interface Map

### Production files retained or created

| File | Responsibility |
| --- | --- |
| `skills/kws-codex-plan-executor/scripts/cpe.py` | JSON CLI for `run`, `resume`, and read-only `inspect` |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py` | Format-5 manifest/state types, immutable input snapshots, bounds, atomic private writes, run lock |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/git.py` | Repository/worktree identity, Git author/committer capture, create/adopt, HEAD/ancestry/status facts |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/controller.py` | Codex argv, JSONL/session parsing, terminal envelope, process group, bounded provider outcome |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/runtime.py` | Initial run, same-session resume, one fallback, inspect, handoff |
| `skills/kws-codex-plan-executor/templates/terminal-envelope.schema.json` | Minimal child claim/capsule JSON schema |

### Deterministic evaluation files

| File | Responsibility |
| --- | --- |
| `skills/kws-codex-plan-executor/evals/test_state.py` | Snapshot, manifest, state, bounds, atomicity, lock contracts |
| `skills/kws-codex-plan-executor/evals/test_git.py` | Git identity, worktree creation/adoption, ancestry/status contracts |
| `skills/kws-codex-plan-executor/evals/test_controller.py` | Codex argv, stream/session/envelope/process behavior |
| `skills/kws-codex-plan-executor/evals/test_runtime.py` | Run, resume, fallback, handoff, inspect, legacy-read-only behavior |
| `skills/kws-codex-plan-executor/evals/test_cli.py` | Public arguments, JSON outputs, exit codes, removed commands |
| `skills/kws-codex-plan-executor/evals/check_architecture.py` | Production inventory, forbidden semantic fields, size budget |
| `skills/kws-codex-plan-executor/evals/fake_codex.py` | Small JSONL/session/process fixture only |
| `skills/kws-codex-plan-executor/evals/live_canary.py` | Opt-in temporary-repository SDD, session-loss, and legacy-adoption canaries |
| `skills/kws-codex-plan-executor/evals/run.sh` | Sequential offline suite and syntax checks |

### Files deleted after replacement coverage exists

- `skills/kws-codex-plan-executor/scripts/cpe_runtime/capabilities.py`
- `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`
- `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- `skills/kws-codex-plan-executor/scripts/cpe_runtime/progress.py`
- `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- `skills/kws-codex-plan-executor/scripts/cpe_runtime/result_validation.py`
- `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- `skills/kws-codex-plan-executor/scripts/cpe_runtime/verification.py`
- `skills/kws-codex-plan-executor/templates/execution-ledger.schema.json`
- `skills/kws-codex-plan-executor/templates/optimization-report.schema.json`
- `skills/kws-codex-plan-executor/templates/plan-result-schema.json`
- all five historical comparative/forensic fixtures under `skills/kws-codex-plan-executor/evals/fixtures/`
- legacy `evals/check_runner.py` and `evals/check_cli.py`

### Cross-task interface contract

```text
# state.py
DocumentSource(path: Path)
DocumentRecord(order: int, source_path: str, snapshot_path: str, sha256: str, byte_length: int)
GitIdentity(author_name: str, author_email: str, committer_name: str, committer_email: str)
RunManifest(
    format_version: int,
    contract_version: int,
    run_id: str,
    source_repository: str,
    base_commit: str,
    branch: str,
    worktree: str,
    documents: tuple of DocumentRecord,
    superpowers_skill: str,
    git_identity: GitIdentity,
    sandbox: str,
    approval_policy: str,
    integration_policy: str,
    remote_action_policy: str,
    created_at: str,
)
RunState(
    status: str,
    controller_session_id: str or None,
    controller_generation: int,
    fresh_fallback_used: bool,
    active_pid: int or None,
    active_process_group: int or None,
    last_observed_head: str,
    tracked_clean: bool,
    untracked_present: bool,
    status_digest: str,
    last_process_class: str or None,
    last_exit_code: int or None,
    resume_capsule: mapping or None,
    blocker: mapping or None,
    updated_at: str,
)
RunStore.create(codex_home: Path, manifest: RunManifest, state: RunState) -> RunStore
RunStore.open(codex_home: Path, run_id: str) -> RunStore
RunStore.save_state(state: RunState) -> None
RunStore.write_handoff(payload: Mapping[str, object]) -> Path
RunStore.lock(shared: bool = False) -> RunLock

# git.py
WorktreeAssignment(repository: Path, worktree: Path, branch: str, base_commit: str, git_common_dir: Path)
GitFacts(head: str, tracked_clean: bool, untracked_present: bool, status_digest: str)
capture_git_identity(repository: Path) -> GitIdentity
create_worktree(repository: Path, base: str, run_id: str, root: Path) -> WorktreeAssignment
adopt_worktree(repository: Path, worktree: Path, base: str) -> WorktreeAssignment
observe_git(worktree: Path) -> GitFacts
require_ancestor(worktree: Path, base: str, head: str) -> None

# controller.py
ResumeCapsule(head_commit: str, worktree_status_digest: str, note: str, evidence_refs: tuple of str)
TerminalEnvelope(claim: str, head_commit: str, resume_capsule: ResumeCapsule or None, blocker: mapping or None)
ControllerRequest(
    mode: str,
    worktree: Path,
    git_common_dir: Path,
    sandbox: str,
    prompt: str,
    schema_path: Path,
    session_id: str or None,
    generation: int,
    git_identity: GitIdentity,
    lock_fd: int,
)
ControllerOutcome(
    session_id: str or None,
    exit_code: int,
    process_class: str,
    terminal: TerminalEnvelope or None,
    provider_code: str or None,
)
CodexController.launch(
    request: ControllerRequest,
    on_session_id: Callable[[str], None],
    on_process_started: Callable[[int, int], None],
) -> ControllerOutcome

# runtime.py
CpeRuntime.run(
    workspace: Path,
    documents: Sequence[DocumentSource],
    superpowers_skill: str,
    sandbox: str,
    adopt_worktree_path: Path or None,
    base: str or None,
) -> dict[str, object]
CpeRuntime.resume(run_id: str) -> dict[str, object]
CpeRuntime.inspect(run_id: str) -> dict[str, object]
```

The implementation may make a type more private, but later tasks must use these
names and meanings unless the same commit updates all dependent tasks and
tests.

---

### Task 1: Format-5 State, Opaque Document Bundle, And Terminal Schema

**Files:**
- Rewrite: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py`
- Create: `skills/kws-codex-plan-executor/templates/terminal-envelope.schema.json`
- Create: `skills/kws-codex-plan-executor/evals/test_state.py`

**Interfaces:**
- Consumes: Python standard library only.
- Produces: `DocumentSource`, `DocumentRecord`, `GitIdentity`, `RunManifest`, `RunState`, `RunStore`, `RunLock`, `snapshot_documents()`.

- [ ] **Step 1: Record the protected legacy worktree before editing**

Run:

```bash
git -C /Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery \
  status --short --branch --untracked-files=all
git -C /Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery \
  rev-parse HEAD
```

Expected: HEAD is `0450c65252368cc7c49a755ec909d7085aef4141` and exactly the five
known Fix Round 5 files are modified. Do not edit or stage that worktree.

- [ ] **Step 2: Write state and snapshot RED tests**

Create `evals/test_state.py` with focused cases using `tempfile.TemporaryDirectory`:

```python
class StateContractTests(unittest.TestCase):
    def test_snapshots_opaque_documents_in_global_order(self) -> None:
        records = snapshot_documents(
            run_root=self.root,
            sources=(
                DocumentSource(self.write_bytes("a/shared.md", b"# Design\n")),
                DocumentSource(self.write_bytes("b/shared.md", b"not a task list")),
                DocumentSource(self.write_bytes("c/shared.md", b"\xff\x00opaque")),
                DocumentSource(self.write_bytes("incident.txt", b"[broken](missing.md)")),
            ),
        )
        self.assertEqual(
            [Path(record.snapshot_path).name for record in records],
            [
                "document-001-shared.md",
                "document-002-shared.md",
                "document-003-shared.md",
                "document-004-incident.txt",
            ],
        )
        self.assertEqual(
            [Path(record.snapshot_path).read_bytes() for record in records],
            [b"# Design\n", b"not a task list", b"\xff\x00opaque", b"[broken](missing.md)"],
        )

    def test_state_rejects_semantic_workflow_fields(self) -> None:
        payload = self.valid_state_payload()
        payload["completed_task_ids"] = []
        with self.assertRaisesRegex(ValueError, "format-5 state"):
            RunStore.validate_state_payload(payload)

    def test_manifest_is_read_only_after_creation(self) -> None:
        store = self.create_store()
        self.assertEqual(stat.S_IMODE(store.manifest_path.stat().st_mode), 0o400)
        with self.assertRaises(PermissionError):
            store.manifest_path.write_text("changed", encoding="utf-8")

    def test_resume_capsule_bounds_are_structural_only(self) -> None:
        valid = {
            "head_commit": "a" * 40,
            "worktree_status_digest": "b" * 64,
            "note": "continue from the existing worktree",
            "evidence_refs": ["evidence/result.txt"],
        }
        self.assertEqual(validate_resume_capsule(valid)["note"], valid["note"])
        invalid = dict(valid, note="x" * 2049)
        with self.assertRaisesRegex(ValueError, "resume capsule"):
            validate_resume_capsule(invalid)
```

Also cover:

- zero input documents rejected;
- symlink, relative, duplicate resolved file identities, directories, and
  non-regular inputs rejected;
- non-UTF-8 bytes, missing Markdown structure, broken links, and unfamiliar
  extensions accepted unchanged;
- snapshot global order is stable;
- run IDs match `^cpe-[0-9a-f]{16}$`;
- run root is `0700`;
- state, lock, and handoff are `0600`;
- manifest keys are exact;
- state keys are exact;
- `format_version == 5`, `contract_version == 3`;
- controller generation is only `0` or `1`;
- `fresh_fallback_used` agrees with generation;
- status is one of `prepared`, `running`, `interrupted`, `blocked`, `failed`, `handed_off`;
- atomic replacement leaves no temporary file;
- lock acquisition refuses a second writer.

- [ ] **Step 3: Run the state tests and confirm RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_state
```

Expected: FAIL because the format-5 dataclasses, snapshot functions, and store
do not exist.

- [ ] **Step 4: Replace state.py with the minimal format-5 model**

Implement constants and exact-field validation:

```python
FORMAT_VERSION = 5
CONTRACT_VERSION = 3
SUPERPOWERS_SKILLS = ("subagent-driven-development", "executing-plans")
SANDBOXES = ("workspace-write", "danger-full-access")
STATUSES = ("prepared", "running", "interrupted", "blocked", "failed", "handed_off")
RUN_ID = re.compile(r"^cpe-[0-9a-f]{16}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_RESUME_NOTE_BYTES = 2048
MAX_EVIDENCE_REFS = 16
```

Use `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW, mode)`,
`os.fsync`, and one
same-directory `os.replace` for private writes. `snapshot_documents()` must
open each absolute source once with no-follow semantics, confirm the opened
descriptor is a regular file, read raw bytes once, write the exact bytes under
`inputs/document-<ordinal>-<basename>`, and return immutable records. It must
not decode text, inspect an extension, read Markdown structure, follow links,
or compare one document's content with another.

`RunStore.create()` accepts a prepared run root that contains only its
`inputs/` snapshots. It atomically adds the immutable manifest and initial
state; it must refuse any other pre-existing run artifact.

`RunLock` uses `fcntl.flock` and exposes its descriptor for child inheritance:

```python
class RunLock:
    def __enter__(self) -> "RunLock":
        self.descriptor = os.open(
            self.path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def fileno(self) -> int:
        if self.descriptor is None:
            raise RuntimeError("run lock is not held")
        return self.descriptor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None
```

- [ ] **Step 5: Add the minimal terminal-envelope schema**

Create a strict JSON Schema whose root has `additionalProperties: false`,
requires `claim` and `head_commit`, and permits only:

- `claim`: `completed`, `interrupted`, or `blocked`;
- lowercase 40-hex `head_commit`;
- optional bounded `resume_capsule`;
- optional normalized blocker.

Use this complete root shape; runtime validation additionally enforces UTF-8
byte bounds, worktree containment, and claim/optional-field combinations:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["claim", "head_commit"],
  "properties": {
    "claim": {
      "enum": ["completed", "interrupted", "blocked"]
    },
    "head_commit": {
      "type": "string",
      "pattern": "^[0-9a-f]{40}$"
    },
    "resume_capsule": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "head_commit",
        "worktree_status_digest",
        "note",
        "evidence_refs"
      ],
      "properties": {
        "head_commit": {
          "type": "string",
          "pattern": "^[0-9a-f]{40}$"
        },
        "worktree_status_digest": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "note": {
          "type": "string",
          "maxLength": 2048
        },
        "evidence_refs": {
          "type": "array",
          "maxItems": 16,
          "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512
          }
        }
      }
    },
    "blocker": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "class",
        "code",
        "resource",
        "operation",
        "retry_condition"
      ],
      "properties": {
        "class": {
          "type": "string",
          "minLength": 1,
          "maxLength": 64
        },
        "code": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128
        },
        "resource": {
          "type": "string",
          "minLength": 1,
          "maxLength": 256
        },
        "operation": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128
        },
        "retry_condition": {
          "type": "string",
          "minLength": 1,
          "maxLength": 512
        },
        "provider_code": {
          "type": ["string", "null"],
          "maxLength": 128
        }
      }
    }
  }
}
```

The schema must not contain `verification`, `final_review`, `finding`,
`obligation`, or task fields.

- [ ] **Step 6: Run focused GREEN and static syntax**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_state
python3 -m py_compile scripts/cpe_runtime/state.py evals/test_state.py
git diff --check
```

Expected: all state tests PASS and static checks exit 0.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py \
  skills/kws-codex-plan-executor/templates/terminal-envelope.schema.json \
  skills/kws-codex-plan-executor/evals/test_state.py
git commit -m "feat(cpe): add minimal format-5 state"
```

---

### Task 2: Git Identity, Worktree Creation, And Explicit Adoption

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/git.py`
- Create: `skills/kws-codex-plan-executor/evals/test_git.py`

**Interfaces:**
- Consumes: `GitIdentity` from Task 1.
- Produces: `WorktreeAssignment`, `GitFacts`, `capture_git_identity()`, `create_worktree()`, `adopt_worktree()`, `observe_git()`, `require_ancestor()`.

- [ ] **Step 1: Write Git RED tests**

Create `evals/test_git.py`:

```python
class GitContractTests(unittest.TestCase):
    def test_capture_git_identity_reads_only_name_and_email(self) -> None:
        self.git("config", "user.name", "CPE Canary")
        self.git("config", "user.email", "cpe@example.invalid")
        identity = capture_git_identity(self.repository)
        self.assertEqual(identity.author_name, "CPE Canary")
        self.assertEqual(identity.author_email, "cpe@example.invalid")
        self.assertEqual(identity.committer_name, "CPE Canary")
        self.assertEqual(identity.committer_email, "cpe@example.invalid")

    def test_missing_git_identity_blocks_before_worktree_creation(self) -> None:
        self.git("config", "--unset-all", "user.name", check=False)
        self.git("config", "--unset-all", "user.email", check=False)
        with self.assertRaisesRegex(ValueError, "Git identity"):
            capture_git_identity(self.repository)

    def test_create_worktree_uses_exact_base_and_run_branch(self) -> None:
        base = self.git("rev-parse", "HEAD")
        assignment = create_worktree(
            self.repository,
            base=base,
            run_id="cpe-0123456789abcdef",
            root=self.temp / "worktrees",
        )
        self.assertEqual(assignment.branch, "codex/cpe-0123456789abcdef")
        self.assertEqual(self.git_at(assignment.worktree, "rev-parse", "HEAD"), base)

    def test_adopt_dirty_worktree_without_mutating_it(self) -> None:
        worktree = self.make_linked_worktree()
        dirty = worktree / "unfinished.txt"
        dirty.write_text("preserve me", encoding="utf-8")
        before = dirty.read_bytes()
        assignment = adopt_worktree(
            self.repository,
            worktree=worktree,
            base=self.base,
        )
        self.assertEqual(assignment.worktree, worktree.resolve())
        self.assertEqual(dirty.read_bytes(), before)
```

Also test:

- source path is the worktree's common repository;
- an ordinary directory, symlinked worktree, detached HEAD, or wrong repository is rejected;
- an existing v3 worktree lock blocks adoption;
- base must be a 40-hex commit and ancestor of current HEAD;
- `observe_git()` distinguishes tracked dirt from untracked presence;
- status digest is deterministic over raw NUL-delimited `git status` bytes;
- no create/adopt function runs reset, rebase, merge, cherry-pick, or checkout.

- [ ] **Step 2: Run Git tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_git
```

Expected: FAIL because `cpe_runtime.git` does not exist.

- [ ] **Step 3: Implement the Git boundary**

Use `subprocess.run` with argument arrays and `check=True`; never use a shell.

Capture identity with:

```python
def capture_git_identity(repository: Path) -> GitIdentity:
    author = _git(repository, "var", "GIT_AUTHOR_IDENT")
    committer = _git(repository, "var", "GIT_COMMITTER_IDENT")
    author_name, author_email = _parse_ident(author)
    committer_name, committer_email = _parse_ident(committer)
    return GitIdentity(
        author_name=author_name,
        author_email=author_email,
        committer_name=committer_name,
        committer_email=committer_email,
    )
```

`_parse_ident()` extracts only the name and `<email>` preceding the timestamp,
rejects newlines/NUL, empty values, and values longer than 320 characters.

Create a worktree using:

```python
branch = f"codex/{run_id}"
worktree = (root / run_id).resolve()
_git(repository, "worktree", "add", "-b", branch, str(worktree), base)
```

If `git worktree add` partially fails inside `create_worktree()`, remove only
the exact path and branch created by that call. Later run-initialization cleanup
belongs to Task 4. No Git helper ever cleans an adopted worktree.

- [ ] **Step 4: Run focused GREEN**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_git
python3 -m unittest -v evals.test_state
python3 -m py_compile scripts/cpe_runtime/{state,git}.py evals/test_{state,git}.py
git diff --check
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/git.py \
  skills/kws-codex-plan-executor/evals/test_git.py
git commit -m "feat(cpe): add mechanical Git boundary"
```

---

### Task 3: Thin Codex Controller Adapter

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/controller.py`
- Rewrite: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Create: `skills/kws-codex-plan-executor/evals/test_controller.py`

**Interfaces:**
- Consumes: `GitIdentity`, `RunLock.fileno()`.
- Produces: `ResumeCapsule`, `TerminalEnvelope`, `ControllerRequest`, `ControllerOutcome`, `CodexController`.

- [ ] **Step 1: Write controller RED tests**

Create tests for the exact command and stream contract:

```python
class ControllerContractTests(unittest.TestCase):
    def test_initial_and_resume_argv_share_one_profile(self) -> None:
        controller = CodexController(executable="/opt/fake/codex")
        initial = controller.build_argv(self.request(session_id=None))
        resumed = controller.build_argv(
            self.request(session_id="11111111-1111-4111-8111-111111111111")
        )
        required = [
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "-c",
            'approval_policy="never"',
            "--json",
            "--sandbox",
            "workspace-write",
        ]
        for argument in required:
            self.assertIn(argument, initial)
            self.assertIn(argument, resumed)
        self.assertEqual(initial[-1], "-")
        self.assertEqual(
            resumed[-3:],
            ["resume", "11111111-1111-4111-8111-111111111111", "-"],
        )

    def test_git_identity_is_injected_without_copying_git_config(self) -> None:
        environment = CodexController.build_environment(self.request())
        self.assertEqual(environment["GIT_AUTHOR_NAME"], "CPE Canary")
        self.assertEqual(environment["GIT_AUTHOR_EMAIL"], "cpe@example.invalid")
        self.assertNotIn("GIT_CONFIG", environment)
        self.assertNotIn("GIT_CONFIG_GLOBAL", environment)

    def test_stream_persists_first_session_and_terminal_envelope(self) -> None:
        observed: list[str] = []
        outcome = self.launch_fake(
            scenario="completed",
            on_session_id=observed.append,
        )
        self.assertEqual(observed, ["11111111-1111-4111-8111-111111111111"])
        self.assertEqual(outcome.session_id, observed[0])
        self.assertEqual(outcome.terminal.claim, "completed")
        self.assertEqual(outcome.process_class, "completed")
```

Also cover:

- session ID must be one UUID;
- duplicate different session IDs fail closed;
- JSONL lines and final envelope have byte bounds;
- raw stderr is not persisted;
- recognized provider codes map only to `auth`, `quota`,
  `provider_unavailable`, `session_unavailable`, `transport`, or `unknown`;
- generic nonzero is not `session_unavailable`;
- malformed terminal JSON becomes `invalid_envelope`;
- process PID/group callback fires before output consumption;
- child receives the run lock descriptor through `pass_fds`;
- SIGTERM escalates to SIGKILL only after bounded grace;
- capsule note and evidence-reference bounds match Task 1;
- terminal envelope never accepts semantic completion fields.

- [ ] **Step 2: Run controller tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_controller
```

Expected: FAIL because the controller adapter does not exist.

- [ ] **Step 3: Replace fake_codex with a small JSONL provider fixture**

`fake_codex.py` accepts a scenario from `CPE_FAKE_SCENARIO`, emits:

```json
{"type":"thread.started","thread_id":"11111111-1111-4111-8111-111111111111"}
{"type":"item.completed","item":{"type":"agent_message","text":"{\"claim\":\"completed\",\"head_commit\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}"}}
{"type":"turn.completed"}
```

Implement explicit scenarios:

- `completed`;
- `interrupted`;
- `blocked_auth`;
- `blocked_quota`;
- `provider_unavailable`;
- `session_unavailable`;
- `transport`;
- `invalid_envelope`;
- `duplicate_session`;
- `ignore_term`.

The fixture must remain provider/process-only; it does not emit tasks, reviews,
verification, or findings.

- [ ] **Step 4: Implement CodexController**

Build argv exactly as:

```python
argv = [
    executable,
    "exec",
    "--ignore-user-config",
    "--ignore-rules",
    "--strict-config",
    "-c",
    'approval_policy="never"',
    "--json",
    "--output-schema",
    str(request.schema_path),
    "--cd",
    str(request.worktree),
    "--sandbox",
    request.sandbox,
    "--add-dir",
    str(request.git_common_dir),
]
argv.extend(
    ["-"]
    if request.session_id is None
    else ["resume", request.session_id, "-"]
)
```

Do not use `--ephemeral` or `--output-last-message`. Parse the structured final
agent message from JSONL in memory, bound it, and return it to the parent.

Launch with:

```python
process = subprocess.Popen(
    argv,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=request.worktree,
    env=environment,
    start_new_session=True,
    pass_fds=(request.lock_fd,),
)
```

Drain stdout and stderr concurrently with `selectors`; forward bounded live
output to the current terminal but do not create a transcript file.

- [ ] **Step 5: Run focused GREEN and regress state/Git**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_controller
python3 -m unittest -v evals.test_state evals.test_git
python3 -m py_compile scripts/cpe_runtime/{state,git,controller}.py evals/{fake_codex,test_controller}.py
git diff --check
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/controller.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/test_controller.py
git commit -m "feat(cpe): add thin Codex session adapter"
```

---

### Task 4: Initial Run, Multi-Document Prompt, And Local Handoff

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runtime.py`
- Create: `skills/kws-codex-plan-executor/evals/test_runtime.py`

**Interfaces:**
- Consumes: all Task 1–3 interfaces.
- Produces: `CpeRuntime.run()`, `render_initial_prompt()`, `render_resume_prompt()`, `render_fallback_prompt()`, mechanical handoff.

- [ ] **Step 1: Write initial-run and handoff RED tests**

Create `evals/test_runtime.py` with dependency-injected fake controller:

```python
class RuntimeContractTests(unittest.TestCase):
    def test_run_passes_all_documents_to_one_controller(self) -> None:
        result = self.runtime.run(
            workspace=self.repository,
            documents=(
                DocumentSource(self.spec_a),
                DocumentSource(self.spec_b),
                DocumentSource(self.plan_a),
                DocumentSource(self.plan_b),
                DocumentSource(self.incident),
                DocumentSource(self.authority),
            ),
            superpowers_skill="subagent-driven-development",
            sandbox="workspace-write",
        )
        self.assertEqual(result["status"], "handed_off")
        self.assertEqual(len(self.controller.requests), 1)
        prompt = self.controller.requests[0].prompt
        for record in self.open_manifest(result["run_id"]).inputs:
            self.assertIn(record.snapshot_path, prompt)
        self.assertNotIn("current_plan_index", prompt)
        self.assertNotIn("completed_task_ids", prompt)

    def test_completed_claim_requires_exact_clean_head(self) -> None:
        self.controller.terminal_head = "b" * 40
        result = self.run_once()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["reason"], "handoff_incomplete")
        self.assertFalse(self.handoff_path(result["run_id"]).exists())

    def test_handoff_is_mechanical_and_local_only(self) -> None:
        result = self.run_once()
        handoff = self.read_handoff(result["run_id"])
        self.assertEqual(handoff["controller_claim"], "completed")
        self.assertEqual(handoff["integration"], "not_observed")
        self.assertEqual(handoff["remote_actions_by_cpe"], "none")
        self.assertNotIn("verification", handoff)
        self.assertNotIn("findings", handoff)
```

Also cover:

- exactly one root controller for all input documents;
- selected skill is required and immutable;
- prompt tells the controller to read `AGENTS.md`, use the selected installed
  Superpowers skill, treat the ordered document paths as opaque caller inputs,
  use Git/Superpowers for semantic recovery, and avoid remote actions;
- CPE accepts documents with missing headings, broken links, contradictory
  prose, and unfamiliar extensions without creating a preflight failure;
- prompt does not restate TDD, task, review, fix-round, or verification policy;
- controller session callback updates state immediately;
- process callback updates active PID/group immediately;
- run result does not expose private input source paths or Git email;
- completed claim with tracked dirt, wrong branch/worktree, or ancestry
  violation does not hand off;
- untracked files are observed but do not become CPE semantic failure;
- state records only the last bounded process/Git facts needed for recovery;
- no per-invocation receipt or event log is created.

- [ ] **Step 2: Run runtime tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_runtime
```

Expected: FAIL because `CpeRuntime` does not exist.

- [ ] **Step 3: Implement the minimal prompts**

`render_initial_prompt()` must be a pure function. Its body contains:

```text
Execute the immutable CPE document bundle in the assigned worktree.
Read repository AGENTS.md. The manifest entries are caller-supplied documents
in caller order; interpret and use them under Superpowers without asking CPE
for document roles or validation.
Use the installed Superpowers skill named in SUPERPOWERS_SKILL.
Superpowers and Git own semantic progress and recovery.
Do not merge, push, open a PR, tag, publish, release, or deploy.
Return only the terminal envelope required by TERMINAL_SCHEMA.
```

Include exact paths and immutable facts after those sentences. Do not add
private descriptions of SDD workflow steps.

- [ ] **Step 4: Implement CpeRuntime.run()**

The implementation order is:

```python
repository = resolve_repository(workspace)
identity = capture_git_identity(repository)
run_id = new_run_id()
selected_base = base if adopt_worktree_path is not None else resolve_head(repository)
if selected_base is None:
    raise ValueError("--base is required with --adopt-worktree")
assignment = (
    adopt_worktree(
        repository,
        worktree=adopt_worktree_path,
        base=selected_base,
    )
    if adopt_worktree_path is not None
    else create_worktree(
        repository,
        base=selected_base,
        run_id=run_id,
        root=worktree_root,
    )
)
run_root = codex_home / "cpe-v3" / "runs" / run_id
records = snapshot_documents(run_root=run_root, sources=documents)
facts = observe_git(assignment.worktree)
manifest = RunManifest(
    format_version=5,
    contract_version=3,
    run_id=run_id,
    source_repository=str(assignment.repository),
    base_commit=assignment.base_commit,
    branch=assignment.branch,
    worktree=str(assignment.worktree),
    documents=tuple(records),
    superpowers_skill=superpowers_skill,
    git_identity=identity,
    sandbox=sandbox,
    approval_policy="never",
    integration_policy="local-handoff-only",
    remote_action_policy="prohibited",
    created_at=utc_now(),
)
state = RunState(
    status="prepared",
    controller_session_id=None,
    controller_generation=0,
    fresh_fallback_used=False,
    active_pid=None,
    active_process_group=None,
    last_observed_head=facts.head,
    tracked_clean=facts.tracked_clean,
    untracked_present=facts.untracked_present,
    status_digest=facts.status_digest,
    last_process_class=None,
    last_exit_code=None,
    resume_capsule=None,
    blocker=None,
    updated_at=utc_now(),
)
store = RunStore.create(
    codex_home=codex_home,
    manifest=manifest,
    state=state,
)
```

If CPE created the worktree and document snapshot or store initialization
fails, remove only that exact newly created worktree and its exact run branch.
Never clean an adopted worktree. `create_worktree()` itself cleans only a
partial `git worktree add` failure that occurred inside that function.

Hold the run lock across controller launch. Save session and process callbacks
before continuing. After exit, clear active process fields, atomically retain
only the last bounded process/Git outcome in state, and evaluate only:

- process class;
- terminal claim;
- submitted versus observed HEAD;
- base ancestry;
- tracked cleanliness;
- branch/worktree identity.

- [ ] **Step 5: Implement local handoff**

Use this exact public shape:

```json
{
  "format_version": 1,
  "run_id": "cpe-0123456789abcdef",
  "branch": "codex/cpe-0123456789abcdef",
  "saved_worktree": "/absolute/worktree",
  "base_commit": "40-hex",
  "observed_head": "40-hex",
  "tracked_clean": true,
  "untracked_present": false,
  "controller_claim": "completed",
  "controller_session_id": "uuid",
  "controller_generation": 0,
  "integration": "not_observed",
  "remote_actions_by_cpe": "none"
}
```

Do not include Git identity values, input source paths, task/review state, or
verification.

- [ ] **Step 6: Run focused GREEN**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_runtime
python3 -m unittest -v evals.test_state evals.test_git evals.test_controller
python3 -m py_compile scripts/cpe_runtime/{state,git,controller,runtime}.py evals/test_runtime.py
git diff --check
```

Expected: all tests PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runtime.py \
  skills/kws-codex-plan-executor/evals/test_runtime.py
git commit -m "feat(cpe): run one durable Superpowers contract"
```

---

### Task 5: Same-Session Resume, One Fresh Fallback, And Read-Only Legacy Inspect

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runtime.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Modify: `skills/kws-codex-plan-executor/evals/test_runtime.py`
- Modify: `skills/kws-codex-plan-executor/evals/test_state.py`

**Interfaces:**
- Consumes: `CpeRuntime.run()`, `RunStore`, `ControllerOutcome`, Git facts.
- Produces: `CpeRuntime.resume()`, `CpeRuntime.inspect()`, explicit bounded recovery transitions.

- [ ] **Step 1: Write recovery RED tests**

Add:

```python
def test_resume_uses_saved_session_before_any_fallback(self) -> None:
    run_id = self.create_interrupted_run()
    original = self.store(run_id).state.controller_session_id
    result = self.runtime.resume(run_id=run_id)
    self.assertEqual(result["status"], "handed_off")
    self.assertEqual(self.controller.requests[-1].session_id, original)
    self.assertEqual(self.store(run_id).state.controller_generation, 0)
    self.assertFalse(self.store(run_id).state.fresh_fallback_used)

def test_explicit_missing_session_allows_one_fresh_fallback(self) -> None:
    run_id = self.create_interrupted_run()
    self.controller.outcomes = [
        self.outcome("session_unavailable", terminal=None),
        self.outcome("completed", session_id=self.new_session, terminal=self.completed()),
    ]
    result = self.runtime.resume(run_id=run_id)
    self.assertEqual(result["status"], "handed_off")
    self.assertIsNotNone(self.controller.requests[0].session_id)
    self.assertIsNone(self.controller.requests[1].session_id)
    state = self.store(run_id).state
    self.assertEqual(state.controller_generation, 1)
    self.assertTrue(state.fresh_fallback_used)

def test_second_session_loss_blocks_without_launching_generation_two(self) -> None:
    run_id = self.create_generation_one_interrupted_run()
    self.controller.outcomes = [self.outcome("session_unavailable", terminal=None)]
    result = self.runtime.resume(run_id=run_id)
    self.assertEqual(result["status"], "blocked")
    self.assertEqual(len(self.controller.requests), 1)
    self.assertEqual(self.store(run_id).state.controller_generation, 1)

def test_legacy_inspect_is_byte_for_byte_read_only(self) -> None:
    legacy = self.write_legacy_state(format_version=3)
    before = self.hash_tree(legacy.parent)
    result = self.runtime.inspect(run_id=legacy.parent.name)
    after = self.hash_tree(legacy.parent)
    self.assertEqual(result["status"], "legacy_read_only")
    self.assertEqual(result["format_version"], 3)
    self.assertEqual(after, before)
```

Also cover:

- auth, quota, provider unavailable, generic nonzero, invalid envelope, and
  timeout never trigger fresh fallback;
- a transport failure returns `interrupted` without an automatic retry; the
  next attempt requires an explicit `resume`;
- fallback prompt contains immutable input paths, same branch/worktree/base,
  current HEAD/status digest, capsule, and normalized failure facts;
- fallback prompt contains no completed-task reconstruction;
- capsule is ignored on healthy same-session resume;
- generation-one session ID replaces generation-zero only after observation;
- repeated explicit `resume` calls never create generation two or an automatic
  strategy loop;
- blocked auth/quota does not guess credentials;
- `inspect` never takes a write lock or modifies state;
- format 1/2/3/4 return `legacy_read_only`;
- invalid v5 state fails rather than migrating or repairing.

- [ ] **Step 2: Run recovery tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v \
  evals.test_runtime.RuntimeContractTests.test_resume_uses_saved_session_before_any_fallback \
  evals.test_runtime.RuntimeContractTests.test_explicit_missing_session_allows_one_fresh_fallback \
  evals.test_runtime.RuntimeContractTests.test_second_session_loss_blocks_without_launching_generation_two \
  evals.test_runtime.RuntimeContractTests.test_legacy_inspect_is_byte_for_byte_read_only
```

Expected: FAIL because `resume()` and legacy inspect are incomplete.

- [ ] **Step 3: Implement same-session and one-fallback state transitions**

The transition must be explicit:

```python
if outcome.process_class == "session_unavailable":
    if state.fresh_fallback_used or state.controller_generation == 1:
        return block_session_unavailable(store, state)
    state.fresh_fallback_used = True
    state.controller_generation = 1
    state.controller_session_id = None
    store.save_state(state)
    return self._launch(store, mode="fallback", session_id=None)
```

Only execute this block after a real resume request with a saved session. Do not
reuse it for initial launch failures. Persist only the normalized process class,
provider code, and optional blocker already defined by the controller contract;
do not create a fingerprint, retry score, strategy selector, or progress
heuristic.

- [ ] **Step 4: Implement read-only legacy detection**

Search v3 root first. If absent, inspect only the exact legacy path
`${CODEX_HOME}/orchestrator/<run-id>/state.json`. Read at most 64 KiB, reject a
symlink, parse only the root `format_version`, and return:

```json
{
  "status": "legacy_read_only",
  "format_version": 3,
  "run_root": "/absolute/legacy/run",
  "recommended_action": "preserve artifacts; use explicit --adopt-worktree for continuation"
}
```

Do not validate, copy, quarantine, chmod, touch, or write legacy files.

- [ ] **Step 5: Run focused GREEN and full focused runtime regression**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_runtime evals.test_state
python3 -m unittest -v evals.test_git evals.test_controller
python3 -m py_compile scripts/cpe_runtime/{state,git,controller,runtime}.py
git diff --check
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runtime.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/evals/test_runtime.py \
  skills/kws-codex-plan-executor/evals/test_state.py
git commit -m "feat(cpe): bound session recovery"
```

---

### Task 6: Public CLI Cutover And Removal Of Duplicate Authority

**Files:**
- Rewrite: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Create: `skills/kws-codex-plan-executor/evals/test_cli.py`
- Create: `skills/kws-codex-plan-executor/evals/check_architecture.py`
- Rewrite: `skills/kws-codex-plan-executor/evals/run.sh`
- Delete: legacy runtime, schemas, fixtures, `check_runner.py`, `check_cli.py` listed in the File And Interface Map

**Interfaces:**
- Consumes: `CpeRuntime`.
- Produces: stable CLI JSON/exit contract and architecture guard.

- [ ] **Step 1: Write CLI RED tests**

Create `evals/test_cli.py`:

```python
class CliContractTests(unittest.TestCase):
    def test_run_accepts_repeated_documents_in_cli_order(self) -> None:
        parsed = build_parser().parse_args(
            [
                "run",
                "--document", "/tmp/design.md",
                "--document", "/tmp/implementation.md",
                "--document", "/tmp/incident.txt",
                "--document", "/tmp/execution-contract",
                "--workspace", "/tmp/repository",
                "--superpowers-skill", "subagent-driven-development",
            ]
        )
        self.assertEqual(
            parsed.document,
            [
                "/tmp/design.md",
                "/tmp/implementation.md",
                "/tmp/incident.txt",
                "/tmp/execution-contract",
            ],
        )
        self.assertEqual(parsed.sandbox, "workspace-write")

    def test_removed_commands_are_rejected(self) -> None:
        for command in ("verify", "recover-ledger", "migrate-run"):
            with self.subTest(command=command):
                with self.assertRaises(CliUsageError):
                    build_parser().parse_args([command])

    def test_exit_codes_match_truthful_terminal_states(self) -> None:
        self.assertEqual(EXIT_CODES["handed_off"], 0)
        self.assertEqual(EXIT_CODES["failed"], 1)
        self.assertEqual(EXIT_CODES["blocked"], 2)
        self.assertEqual(EXIT_CODES["interrupted"], 3)
```

Also cover:

- at least one `--document` required;
- all input/workspace/adoption paths absolute;
- `--base` required exactly with `--adopt-worktree`;
- `--base` rejected without adoption;
- `resume` accepts only `--run-id`;
- `inspect` exits 0 for v5 and legacy-read-only results;
- JSON errors are bounded to 2,000 characters;
- Ctrl-C returns `interrupted`, not `checkpointed`;
- no output uses `completed` as the CPE status.

- [ ] **Step 2: Write architecture RED tests**

`check_architecture.py` inspects production files only:

```python
EXPECTED_RUNTIME = {
    "__init__.py",
    "state.py",
    "git.py",
    "controller.py",
    "runtime.py",
}
FORBIDDEN = {
    "current_plan_index",
    "completed_task_ids",
    "current_task_id",
    "fix_round",
    "final_review_head",
    "open_finding_ids",
    "open_obligation_ids",
    "\"verification\"",
    "migrate-run",
}
```

It must assert:

- exact runtime inventory;
- exact template inventory `{terminal-envelope.schema.json}`;
- no forbidden token in production Python or the active terminal schema;
- `SKILL.md` and `README.md` expose only `run`, `resume`, and `inspect` in
  active command examples; historical removed-command prose is allowed;
- total production Python lines at most 1,500;
- no production module over 450 lines unless the whole-diff review records a
  concrete necessity and the total ceiling still holds;
- `subprocess` calls never use `shell=True`;
- no import of deleted modules.

- [ ] **Step 3: Run CLI and architecture tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_cli
python3 evals/check_architecture.py
```

Expected: FAIL because the old commands and modules still exist.

- [ ] **Step 4: Rewrite cpe.py**

Build only `run`, `resume`, and `inspect`. Preserve the single CLI declaration
order without assigning roles:

```python
documents = tuple(DocumentSource(Path(path)) for path in args.document)
```

Use:

```python
EXIT_CODES = {
    "handed_off": 0,
    "failed": 1,
    "blocked": 2,
    "interrupted": 3,
}
```

`inspect` explicitly exits 0 after a successful read-only lookup.

- [ ] **Step 5: Delete all legacy authority surfaces**

Delete the exact files listed in the plan's deletion map. Do not retain import
shims, deprecated commands, migration parsers, schema aliases, or forensic
fixtures in the active skill.

Historical evidence remains in Git and preserved external run roots. Do not
delete or modify `/Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery`.

- [ ] **Step 6: Rewrite evals/run.sh**

Use:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m unittest -v \
  evals.test_state \
  evals.test_git \
  evals.test_controller \
  evals.test_runtime \
  evals.test_cli
python3 evals/check_architecture.py
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
```

Do not invoke live canaries from the offline gate.

- [ ] **Step 7: Run focused GREEN**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest -v evals.test_cli
python3 evals/check_architecture.py
python3 -m unittest -v \
  evals.test_state evals.test_git evals.test_controller evals.test_runtime
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
git diff --check
```

Expected: all commands exit 0; the active skill contains no duplicate semantic
authority.

- [ ] **Step 8: Commit Task 6**

```bash
git add -A -- skills/kws-codex-plan-executor
git commit -m "refactor(cpe): remove duplicate workflow authority"
```

---

### Task 7: Public Skill, Operator Documentation, And Opt-In Live Canary Harness

**Files:**
- Rewrite: `skills/kws-codex-plan-executor/SKILL.md`
- Rewrite: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/AGENTS.md`
- Create: `skills/kws-codex-plan-executor/evals/live_canary.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_architecture.py`
- Modify: `docs/superpowers/specs/2026-07-25-cpe-v3-thin-superpowers-durability-capsule-design.md` only for implementation-status corrections proven by this task

**Interfaces:**
- Consumes: final CLI/state/handoff contracts.
- Produces: truthful version 3 operator contract and three opt-in canaries.

- [ ] **Step 1: Write documentation RED assertions**

Extend `check_architecture.py` to require these exact public concepts:

```python
REQUIRED_PUBLIC_PHRASES = {
    "one execution contract",
    "multiple documents",
    "no document review",
    "same-session resume",
    "one fresh fallback",
    "workspace-write",
    "handed_off",
    "legacy_read_only",
    "integration=not_observed",
}
```

Assert `SKILL.md` metadata has:

```yaml
version: "3.0.0"
updated_at: "2026-07-25"
```

Assert docs do not advertise `completed`, `checkpointed`, `verify`,
`recover-ledger`, task evidence, review evidence, or migration as active CPE
features.

- [ ] **Step 2: Run documentation assertions and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_architecture.py
```

Expected: FAIL because the public docs still describe CPE 2.1.

- [ ] **Step 3: Rewrite SKILL.md and README.md**

Document:

- when direct Superpowers is sufficient;
- when CPE's single-contract durability is useful;
- why repeated `--document` inputs are opaque passthrough and do not create a
  CPE plan queue, role model, or document review stage;
- exact run/resume/inspect commands;
- explicit selected Superpowers skill;
- workspace-write default and explicit full access;
- same-session recovery and one fallback;
- mechanical `handed_off`;
- read-only legacy policy and explicit adoption;
- local-only/no-remote boundary;
- POSIX and same-UID residual risks;
- offline versus opt-in live verification.

Do not copy Superpowers task/review procedures into either document.

- [ ] **Step 4: Implement the opt-in canary harness**

`evals/live_canary.py` accepts:

```text
--scenario sdd-multi-document
--scenario session-loss
--scenario legacy-adoption
```

It refuses to run unless `CPE_LIVE_CANARY=1`. Each scenario:

- creates a fresh temporary Git repository with explicit local Git identity;
- creates several small caller-supplied documents, including repeated
  basenames and one document with deliberately unfamiliar structure;
- uses no remote;
- invokes the real CPE CLI;
- writes its private receipt under the temporary directory;
- deletes no preserved user run or worktree.

For `sdd-multi-document`:

1. the plan instructs Superpowers to make one small tested commit and submit
   `interrupted`;
2. `resume` must use the same session and finish a second commit;
3. inspect must show generation 0 and `handed_off`.

For `session-loss`:

1. a PATH-local shim delegates the initial real Codex invocation;
2. on the first `resume <session>` only, the shim emits the provider's
   recognized session-unavailable code;
3. the generation-one fresh invocation delegates to the real Codex executable;
4. the run/worktree/HEAD/capsule remain the same;
5. the receipt proves one fallback and no second fallback.

For `legacy-adoption`:

1. create a synthetic read-only format-3 root and record a recursive SHA-256
   inventory;
2. create one dirty linked worktree;
3. start a new v3 run with explicit `--adopt-worktree` and caller-supplied
   documents;
4. compare the legacy inventory byte-for-byte afterward;
5. require a distinct v3 run ID and local `handed_off`.

The harness must never edit an actual user legacy root or the protected
recovery worktree.

- [ ] **Step 5: Run offline documentation GREEN**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_architecture.py
python3 -m unittest -v evals.test_cli
python3 -m py_compile evals/live_canary.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit Task 7**

```bash
git add \
  skills/kws-codex-plan-executor/AGENTS.md \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/evals/live_canary.py \
  skills/kws-codex-plan-executor/evals/check_architecture.py \
  docs/superpowers/specs/2026-07-25-cpe-v3-thin-superpowers-durability-capsule-design.md
git commit -m "docs(cpe): publish v3 durability boundary"
```

---

### Task 8: Final Candidate Verification, Release Canaries, And Whole-Diff Review

**Files:**
- Modify only if a failing gate or review finding requires an approved-scope fix.
- Do not commit private canary receipts or Superpowers scratch artifacts.

**Interfaces:**
- Consumes: completed Tasks 1–7.
- Produces: clean candidate HEAD, offline gate evidence, three live canary receipts, Critical 0 / Important 0 review.

- [ ] **Step 1: Record candidate range and protected recovery state**

```bash
git status --short --branch --untracked-files=all
git rev-parse HEAD
git merge-base main HEAD
git -C /Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery \
  status --short --branch --untracked-files=all
git -C /Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery \
  rev-parse HEAD
```

Expected: candidate tracked tree clean; protected recovery HEAD/status unchanged.

- [ ] **Step 2: Run the complete offline CPE gate once**

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
```

Expected: all unit, architecture, Python, and Bash checks PASS.

- [ ] **Step 3: Run explicit syntax and diff checks**

```bash
cd skills/kws-codex-plan-executor
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
cd ../../
git diff --check
```

Expected: exit 0.

- [ ] **Step 4: Run all three live canaries**

Resolve the real Codex executable before adding any session-loss shim to PATH:

```bash
cd skills/kws-codex-plan-executor
CPE_LIVE_CANARY=1 python3 evals/live_canary.py --scenario sdd-multi-document
CPE_LIVE_CANARY=1 python3 evals/live_canary.py --scenario session-loss
CPE_LIVE_CANARY=1 python3 evals/live_canary.py --scenario legacy-adoption
```

Expected:

- SDD canary: same run/worktree/session, generation 0, `handed_off`;
- session-loss canary: same run/worktree/HEAD/capsule, generation 1, exactly one
  fallback, `handed_off`;
- legacy canary: read-only legacy hash unchanged, explicit adopted worktree,
  distinct v3 run, `handed_off`;
- all canaries: `integration=not_observed`, no remote mutation.

If provider auth, quota, or availability blocks a canary, record the bounded
external blocker and stop. Do not weaken or replace the live evidence.

- [ ] **Step 5: Run exact changed-path root verification**

```bash
cd /Users/kws/.codex/worktrees/archive-cpe-v3-thin-superpowers-capsule-design
CPE_VERIFY_BASE=$(git merge-base main HEAD)
CPE_VERIFY_HEAD=$(git rev-parse HEAD)
bun run agent:verify -- --base "$CPE_VERIFY_BASE" --head "$CPE_VERIFY_HEAD"
```

Expected: `full-offline` selected for the active CPE paths and exit code 0.

- [ ] **Step 6: Dispatch one fresh read-only whole-diff review**

Give the reviewer:

- the complete approved CPE v3 design;
- this complete implementation plan;
- the companion provider-runner boundary design;
- the three July 24 CPE incident reports from source `main`;
- BASE..HEAD full diff;
- offline gate output;
- three live canary receipts;
- protected recovery branch status.

This review evaluates the CPE implementation. It must not introduce a CPE
review or approval stage for the Superpowers documents passed to a run.

Review scope:

- no CPE-owned task/review/verification authority;
- opaque ordered documents without role classification, content validation,
  or plan queue;
- one worktree/root controller;
- same-session first;
- exactly one fresh fallback;
- workflow-neutral capsule;
- Git identity;
- default sandbox and noninteractive profile;
- process lock/group safety;
- mechanical handoff wording;
- read-only legacy preservation;
- production/eval size;
- no remote or product-scope expansion.

Expected: Critical 0, Important 0.

- [ ] **Step 7: Resolve any review finding through the Superpowers fix loop**

For each approved-scope finding:

1. write a focused RED test;
2. run it and observe the intended failure;
3. implement the minimum correction;
4. run focused GREEN and affected regression;
5. commit a narrow non-amend fix;
6. run the scoped re-review.

Do not create a CPE review ledger. Superpowers `progress.md`, review reports,
fix-round entries, and Git history own the loop.

- [ ] **Step 8: Re-run final gates after the last HEAD change**

If Step 7 changed HEAD, repeat Steps 2–6 at the new HEAD. Otherwise do not run
the same expensive gates again.

Expected: clean candidate, all gates green, Critical 0, Important 0.

---

### Task 9: Merge The Finished CPE v3 Candidate To Latest Local Main

**Files:**
- No source edits expected.
- Preserve the three user-owned untracked incident reports in `/Users/kws/source/private/Archive/docs/operations/`.

**Interfaces:**
- Consumes: Task 8 clean candidate and review.
- Produces: one local Archive `main` merge commit and post-merge verification.

- [ ] **Step 1: Confirm current source main and hash user-owned incident reports**

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
git rev-parse main
git rev-parse codex/cpe-v3-thin-superpowers-capsule-design
git merge-base main codex/cpe-v3-thin-superpowers-capsule-design
shasum -a 256 \
  docs/operations/2026-07-24-cpe-execution-ledger-invalid-and-authority-loss-incident.md \
  docs/operations/2026-07-24-cpe-sdd-architecture-gap-and-remediation-report.md \
  docs/operations/2026-07-24-cpe-thin-superpowers-wrapper-incident.md
```

Record the three hashes in the execution report. Do not add, edit, move, or
delete those files.

- [ ] **Step 2: Integrate any concurrently advanced main into the candidate**

If `main` advanced after Task 8:

```bash
cd /Users/kws/.codex/worktrees/archive-cpe-v3-thin-superpowers-capsule-design
git merge --no-ff --no-edit main
```

Resolve only conflicts in candidate-owned paths. Re-run focused/full/root
verification, all impact-selected canaries, and whole-diff review at the new
HEAD. Do not rebase or rewrite the candidate.

- [ ] **Step 3: Create the local main merge commit**

After the candidate is green against latest main:

```bash
cd /Users/kws/source/private/Archive
CPE_PRE_MERGE_MAIN=$(git rev-parse HEAD)
git merge --no-ff --no-edit codex/cpe-v3-thin-superpowers-capsule-design
CPE_MERGE_HEAD=$(git rev-parse HEAD)
```

Do not push.

- [ ] **Step 4: Run post-merge CPE verification**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
CPE_MERGE_HEAD=$(git rev-parse HEAD)
CPE_PRE_MERGE_MAIN=$(git rev-parse HEAD^1)
git diff --check "$CPE_PRE_MERGE_MAIN..$CPE_MERGE_HEAD"
bun run agent:verify -- --base "$CPE_PRE_MERGE_MAIN" --head "$CPE_MERGE_HEAD"
git status --porcelain --untracked-files=no
```

Expected: all commands exit 0 and tracked `main` is clean.

- [ ] **Step 5: Run a fresh read-only post-merge review**

Review `CPE_PRE_MERGE_MAIN..CPE_MERGE_HEAD` on the actual merged `main` and
confirm:

- no merge conflict was resolved incorrectly;
- the reviewed CPE candidate diff is preserved;
- concurrent `main` changes are preserved;
- the repeated `--document` interface still has no CPE content-review stage;
- full CPE and root verification passed on the merge result;
- tracked `main` is clean;
- no remote mutation occurred.

Expected: Critical 0, Important 0. If a finding requires a code change, fix it
on a new narrow `codex/` branch from the merged `main`, run affected and full
verification plus impact-selected canaries, merge that fix locally, and repeat
this post-merge review. Do not amend or rewrite the merge.

- [ ] **Step 6: Recheck user documents and protected recovery branch**

```bash
cd /Users/kws/source/private/Archive
shasum -a 256 \
  docs/operations/2026-07-24-cpe-execution-ledger-invalid-and-authority-loss-incident.md \
  docs/operations/2026-07-24-cpe-sdd-architecture-gap-and-remediation-report.md \
  docs/operations/2026-07-24-cpe-thin-superpowers-wrapper-incident.md
git -C /Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery \
  status --short --branch --untracked-files=all
git -C /Users/kws/.codex/worktrees/archive-cpe-thin-superpowers-v62-recovery \
  rev-parse HEAD
```

Expected: all three hashes match Step 1; recovery HEAD/status still match the
protected baseline.

- [ ] **Step 7: Produce the final local handoff report**

Report:

- implementation base, candidate HEAD, pre-merge main, merge commit, final main;
- production and eval line counts;
- focused/offline/root/post-merge command results;
- all three live canary run IDs, sessions, generations, HEADs, and handoffs;
- whole-diff and post-merge review findings;
- legacy hash preservation;
- protected recovery branch preservation;
- opt-in evidence skipped for concrete external blockers, if any;
- residual risks from the design;
- `integration=not_observed` for canary handoffs;
- local Archive main merge completed;
- push, PR, tag, publish, release, and deploy not performed.
