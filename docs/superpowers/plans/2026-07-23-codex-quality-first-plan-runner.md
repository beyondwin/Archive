# Codex Quality-First Plan Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the greenfield `kws-codex-plan-runner` skill with durable ordered multi-plan execution, Codex session resume/fresh fallback, exact verification receipts, autonomous bounded recovery, and fail-closed `ready_for_integration`.

**Architecture:** The skill is a standard-library runtime on preinstalled uv-managed normal-GIL CPython `>=3.13,<3.14`, isolated from both legacy executors and from the future Claude runner. A self-locating executable resolves the managed interpreter without downloads or uv-project discovery. A small versioned root fixture defines test-only semantic vocabulary; the installed runtime hardcodes and validates its own copy. The provider child receives all immutable specs plus exactly one current plan and calls a parent-owned Unix-socket helper for focused or final verification, so the child never needs write access to private run state.

**Tech Stack:** uv-managed normal-GIL CPython 3.13 standard library, POSIX launcher, Git CLI, Codex CLI JSONL mode, Unix domain sockets, `unittest`, Bash eval entrypoint, Bun/TypeScript repository verification mapping.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-23-quality-first-provider-plan-runners-design.md`.
- Create `skills/kws-codex-plan-runner/`; do not modify or delete either legacy executor in this plan.
- Require uv-managed normal-GIL CPython `>=3.13,<3.14` and standard-library dependencies only; do not support system Python 3.9.
- Public invocation is `./scripts/runner`; it must self-locate and use `uv python find --managed-python --no-python-downloads --no-project --no-config --resolve-links 3.13`.
- Never install or download Python during `run`, `resume`, or `inspect`; preflight must fail before worktree/provider mutation with `runtime_missing` or `runtime_incompatible`.
- Record uv version, exact CPython patch, resolved path, architecture, and GIL mode separately from target verification-command environment identity.
- Keep all production runtime code inside the Codex skill; do not import runtime code from the Claude runner or a root shared package.
- The root contract fixture is test-only and must never be imported by installed runtime code.
- Preserve every `--spec` and `--plan` absolute path, source snapshot, SHA-256 digest, and CLI order.
- Supply all specs and exactly one current plan to an implementation attempt; never expose future-plan snapshot paths in its packet.
- Use one branch `codex-plan/<run-id>` and one worktree for all plans.
- Use fresh sessions at plan boundaries; for a healthy interruption of the same plan, resume only the explicitly recorded session ID and never use `--last`.
- Do not use `--ephemeral`.
- The controller automatically handles recoverable child failures while it is alive; `resumable` is only for a run with no live controller.
- No total token, cost, or run-wall budget is allowed.
- A provider activity lease is distinct from required per-command verification deadlines; process existence and heartbeat alone are not progress.
- The runner never chooses a model escalation. `--model` is pass-through only.
- The runner never invents implementation tasks, test commands, review roles, subagents, performance thresholds, merge, push, or deploy actions.
- Plan-local completion is `implemented`; only the run-level final gate may emit `ready_for_integration`.
- Final verification and whole-branch review are fresh-session, candidate-HEAD-scoped, and reusable only under the exact evidence identity.
- Use `apply_patch` for tracked edits and preserve unrelated working-tree changes.
- During implementation run focused tests only; run `./evals/run.sh` and `bun run agent:verify` once at the final candidate HEAD.

---

## File Structure

Create these files:

```text
skills/kws-codex-plan-runner/
├── AGENTS.md
├── CHANGELOG.md
├── README.md
├── SKILL.md
├── evals/
│   ├── fake_codex.py
│   ├── run.sh
│   ├── test_contracts.py
│   ├── test_engine.py
│   ├── test_evidence.py
│   ├── test_git_ops.py
│   ├── test_helper.py
│   ├── test_provider.py
│   ├── test_recovery.py
│   ├── test_runtime.py
│   └── test_storage.py
├── scripts/
│   ├── runner
│   ├── runner.py
│   └── plan_runner/
│       ├── __init__.py
│       ├── contracts.py
│       ├── engine.py
│       ├── evidence.py
│       ├── git_ops.py
│       ├── helper.py
│       ├── process.py
│       ├── provider.py
│       ├── recovery.py
│       ├── runtime.py
│       └── storage.py
└── templates/
    ├── final-verification-set.schema.json
    ├── finalization-result.schema.json
    └── plan-result.schema.json
```

Create this test-only repository fixture:

```text
scripts/agent/fixtures/plan-runner-contract-v1.json
```

Modify these repository verification files without removing legacy routing:

```text
scripts/agent/contract.ts
scripts/agent/check-contract.test.ts
scripts/agent/verification-map.ts
scripts/agent/verification-map.test.ts
```

Production responsibilities:

- `contracts.py`: format/version constants, state vocabularies, exit codes, bounded JSON validation.
- `storage.py`: private directories, immutable input snapshots, state revisions, locks, content-addressed artifacts.
- `git_ops.py`: source/worktree identity, protected refs, clean/ancestry checks, child Git/credential guard environment.
- `process.py`: bounded output, process groups, termination, exact argv execution.
- `evidence.py`: verification manifests, execution identities, receipts, reuse, final evidence validation.
- `helper.py`: bounded nonce-scoped Unix-socket protocol between provider child and parent controller.
- `recovery.py`: activity lease, material-progress fingerprint, failure signatures, session and changed-strategy decisions.
- `runtime.py`: uv-managed CPython validation and immutable runner-runtime metadata.
- `provider.py`: Codex argv, JSONL parsing, session capture, activity normalization, provider outcome classification.
- `engine.py`: run/resume/inspect state machine, sequential plans, automatic recovery, fresh finalization, handoff.
- `runner`: self-locating, no-download uv interpreter selection.
- `runner.py`: runtime preflight, argparse, hidden helper client, and exit-code adapter.

## Task 1: Versioned Semantic Contract and Managed Runtime Preflight

**Files:**

- Create: `scripts/agent/fixtures/plan-runner-contract-v1.json`
- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/__init__.py`
- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py`
- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/runtime.py`
- Create: `skills/kws-codex-plan-runner/evals/test_contracts.py`
- Create: `skills/kws-codex-plan-runner/evals/test_runtime.py`

**Interfaces:**

- Produces: `FORMAT_VERSION`, `CONTRACT_VERSION`, `RUN_STATUSES`, `PLAN_STATUSES`, `TASK_STATUSES`, `FAILURE_TAXONOMY`, `RUNNER_RUNTIME_CONTRACT`, `ExitCode`, `canonical_json(value)`, `sha256_json(value)`, `require_full_sha(value)`, `require_digest(value)`, `RuntimeIdentity`, `probe_runtime()`, and `require_compatible_runtime()`.
- Consumes: no production interface from another task.

- [ ] **Step 1: Write the failing contract-vocabulary test**

```python
# skills/kws-codex-plan-runner/evals/test_contracts.py
import json
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    FAILURE_TAXONOMY,
    FORMAT_VERSION,
    PLAN_STATUSES,
    RUNNER_RUNTIME_CONTRACT,
    RUN_STATUSES,
    TASK_STATUSES,
    ExitCode,
    canonical_json,
    require_digest,
    require_full_sha,
    sha256_json,
)


class ContractVocabularyTest(unittest.TestCase):
    def test_runtime_matches_versioned_test_contract(self):
        fixture = json.loads(
            (REPO_ROOT / "scripts/agent/fixtures/plan-runner-contract-v1.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(CONTRACT_VERSION, fixture["contract_version"])
        self.assertEqual(FORMAT_VERSION, fixture["state_format_version"])
        self.assertEqual(sorted(RUN_STATUSES), sorted(fixture["run_statuses"]))
        self.assertEqual(sorted(PLAN_STATUSES), sorted(fixture["plan_statuses"]))
        self.assertEqual(sorted(TASK_STATUSES), sorted(fixture["task_statuses"]))
        self.assertEqual(sorted(FAILURE_TAXONOMY), sorted(fixture["failure_taxonomy"]))
        self.assertEqual(RUNNER_RUNTIME_CONTRACT, fixture["runner_runtime"])
        self.assertEqual(
            {item.name.lower(): int(item) for item in ExitCode},
            fixture["exit_codes"],
        )

    def test_canonical_digest_is_stable(self):
        left = {"b": [2, 1], "a": "value"}
        right = {"a": "value", "b": [2, 1]}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(sha256_json(left), sha256_json(right))

    def test_full_sha_and_digest_fail_closed(self):
        self.assertEqual(require_full_sha("a" * 40), "a" * 40)
        self.assertEqual(require_digest("b" * 64), "b" * 64)
        with self.assertRaisesRegex(ValueError, "full Git SHA"):
            require_full_sha("deadbeef")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            require_digest("b" * 63)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and confirm it fails because the fixture and runtime do not exist**

Run:

```bash
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest \
  skills/kws-codex-plan-runner/evals/test_contracts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'plan_runner'` or missing fixture.

- [ ] **Step 3: Add the exact versioned test-only fixture**

```json
{
  "contract_version": 1,
  "state_format_version": 1,
  "run_statuses": [
    "blocked",
    "failed",
    "ready_for_integration",
    "recovering",
    "resumable",
    "running"
  ],
  "plan_statuses": [
    "implemented",
    "pending",
    "running"
  ],
  "task_statuses": [
    "pending",
    "reported_done",
    "running"
  ],
  "runner_runtime": {
    "free_threaded": false,
    "implementation": "cpython",
    "managed_by": "uv",
    "requires_python": ">=3.13,<3.14"
  },
  "exit_codes": {
    "blocked": 3,
    "failed": 4,
    "integrity": 65,
    "internal": 70,
    "invalid": 64,
    "ready": 0,
    "resumable": 2
  },
  "failure_taxonomy": [
    "controller_spawn_failed",
    "controller_transport_failed",
    "destructive_authorization_required",
    "external_authority_required",
    "input_changed_requires_new_run",
    "irreconcilable_requirements",
    "provider_auth_blocked",
    "provider_unavailable",
    "provider_usage_blocked",
    "recovery_exhausted",
    "review_failed",
    "runtime_incompatible",
    "runtime_missing",
    "session_invalid",
    "session_resume_failed",
    "stall_expired",
    "state_integrity_failed",
    "verification_failed",
    "verification_timed_out"
  ],
  "receipt_identity_fields": [
    "argv",
    "candidate_head",
    "command_role",
    "cwd",
    "environment_fingerprint",
    "executable_identity",
    "input_digest",
    "worktree_digest"
  ]
}
```

- [ ] **Step 4: Implement the runtime vocabulary without importing the root fixture**

```python
# skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py
from __future__ import annotations

import hashlib
import json
import re
from enum import IntEnum
from typing import Any

CONTRACT_VERSION = 1
FORMAT_VERSION = 1

RUN_STATUSES = frozenset(
    {"running", "recovering", "resumable", "blocked", "failed", "ready_for_integration"}
)
PLAN_STATUSES = frozenset({"pending", "running", "implemented"})
TASK_STATUSES = frozenset({"pending", "running", "reported_done"})
RUNNER_RUNTIME_CONTRACT = {
    "free_threaded": False,
    "implementation": "cpython",
    "managed_by": "uv",
    "requires_python": ">=3.13,<3.14",
}
FAILURE_TAXONOMY = frozenset(
    {
        "controller_spawn_failed",
        "controller_transport_failed",
        "destructive_authorization_required",
        "external_authority_required",
        "input_changed_requires_new_run",
        "irreconcilable_requirements",
        "provider_auth_blocked",
        "provider_unavailable",
        "provider_usage_blocked",
        "recovery_exhausted",
        "review_failed",
        "runtime_incompatible",
        "runtime_missing",
        "session_invalid",
        "session_resume_failed",
        "stall_expired",
        "state_integrity_failed",
        "verification_failed",
        "verification_timed_out",
    }
)

_FULL_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ExitCode(IntEnum):
    READY = 0
    RESUMABLE = 2
    BLOCKED = 3
    FAILED = 4
    INVALID = 64
    INTEGRITY = 65
    INTERNAL = 70


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def require_full_sha(value: object) -> str:
    if not isinstance(value, str) or _FULL_SHA.fullmatch(value) is None:
        raise ValueError("value must be a full Git SHA")
    return value


def require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("value must be a SHA-256 digest")
    return value
```

```python
# skills/kws-codex-plan-runner/scripts/plan_runner/__init__.py
from .contracts import CONTRACT_VERSION, FORMAT_VERSION

__all__ = ["CONTRACT_VERSION", "FORMAT_VERSION"]
```

- [ ] **Step 5: Write failing managed-runtime tests**

`test_runtime.py` must isolate subprocess and interpreter facts so it covers:

- `uv` missing → `RuntimeUnavailable("runtime_missing")`;
- `uv python find --managed-python --no-python-downloads --no-project
  --no-config --resolve-links 3.13` returning no interpreter →
  `runtime_missing`;
- non-CPython, Python 3.12 or 3.14, and `Py_GIL_DISABLED=1` →
  `runtime_incompatible`;
- CPython 3.13 normal-GIL success records exact patch version, resolved
  executable, architecture, GIL mode, and `uv --version`;
- the resolved uv-managed executable must equal the running
  `sys.executable` after path resolution;
- runtime metadata serializes independently from an arbitrary target
  verification environment fingerprint.

- [ ] **Step 6: Implement managed-runtime probing**

`runtime.py` must define immutable `RuntimeIdentity` fields
`uv_version`, `implementation`, `python_version`, `executable`,
`architecture`, and `gil_disabled`. It must call `uv --version` and the exact
no-download `uv python find` argv above without a shell, resolve both returned
and running executable paths, and reject mismatches. `require_compatible_runtime`
must enforce CPython `>=3.13,<3.14` and `gil_disabled is False`.

No production function may call `uv python install`, `uv run`, or omit
`--no-python-downloads`.

- [ ] **Step 7: Run the focused contract and runtime tests**

Run:

```bash
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest \
  skills/kws-codex-plan-runner/evals/test_contracts.py \
  skills/kws-codex-plan-runner/evals/test_runtime.py -v
```

Expected: contract and managed-runtime tests PASS.

- [ ] **Step 8: Commit the contract and runtime foundation**

```bash
git add scripts/agent/fixtures/plan-runner-contract-v1.json \
  skills/kws-codex-plan-runner/scripts/plan_runner/__init__.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/runtime.py \
  skills/kws-codex-plan-runner/evals/test_contracts.py \
  skills/kws-codex-plan-runner/evals/test_runtime.py
git commit -m "feat(codex-runner): define contract and managed runtime"
```

## Task 2: Crash-Consistent Private State, Inputs, Artifacts, and Locks

**Files:**

- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/storage.py`
- Create: `skills/kws-codex-plan-runner/evals/test_storage.py`

**Interfaces:**

- Consumes: `FORMAT_VERSION`, `RUN_STATUSES`, `PLAN_STATUSES`, `canonical_json`, `sha256_json`.
- Produces:

Contractual API:

- immutable `ArtifactRef(kind: str, digest: str, relative_path: str)`;
- `StateStore.create` keyword inputs: `root`, `provider`, `run_id`,
  `source_repository`, `source_commit`, `worktree`, `branch`, ordered `specs`,
  ordered `plans`, `immutable_config`, and `runner_runtime`; returns
  `StateStore`;
- `StateStore.open(root: Path) -> StateStore`;
- `StateStore.snapshot() -> dict[str, object]`;
- `StateStore.put_artifact(kind, payload) -> ArtifactRef`;
- `StateStore.commit(next_state) -> dict[str, object]`;
- `StateStore.referenced_artifact(reference) -> Path`;
- `RunLock` is a context manager whose enter returns itself and whose exit
  always releases its nonblocking exclusive lock.

- [ ] **Step 1: Write storage tests for immutable order, revision integrity, orphan handling, symlink rejection, and lock exclusion**

```python
# skills/kws-codex-plan-runner/evals/test_storage.py
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.storage import RunLock, StateStore  # noqa: E402


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.spec_a = self.root / "spec-a.md"
        self.spec_b = self.root / "spec-b.md"
        self.plan_a = self.root / "plan-a.md"
        self.plan_b = self.root / "plan-b.md"
        for path, text in (
            (self.spec_a, "spec a\n"),
            (self.spec_b, "spec b\n"),
            (self.plan_a, "plan a\n"),
            (self.plan_b, "plan b\n"),
        ):
            path.write_text(text, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def create_store(self):
        return StateStore.create(
            root=self.root / "state" / "run-1",
            provider="codex",
            run_id="plan-a-12345678-1234-4234-8234-123456789abc",
            source_repository=self.repo,
            source_commit="a" * 40,
            worktree=self.root / "worktree",
            branch="codex-plan/plan-a-12345678-1234-4234-8234-123456789abc",
            specs=[self.spec_b, self.spec_a],
            plans=[self.plan_b, self.plan_a],
            immutable_config={"stall_seconds": 3600, "sandbox": "workspace-write"},
            runner_runtime={
                "uv_version": "uv 0.11.28",
                "implementation": "cpython",
                "python_version": "3.13.14",
                "executable": "/managed/python3.13",
                "architecture": "arm64",
                "gil_disabled": False,
            },
        )

    def test_preserves_role_local_cli_order_and_original_digest(self):
        store = self.create_store()
        state = store.snapshot()
        specs = [item for item in state["inputs"] if item["role"] == "spec"]
        plans = [item for item in state["inputs"] if item["role"] == "plan"]
        self.assertEqual([Path(item["source_path"]).name for item in specs], ["spec-b.md", "spec-a.md"])
        self.assertEqual([Path(item["source_path"]).name for item in plans], ["plan-b.md", "plan-a.md"])
        self.assertEqual([item["input_order"] for item in specs], [0, 1])
        self.assertEqual([item["input_order"] for item in plans], [0, 1])
        self.assertEqual([item["status"] for item in state["plans"]], ["pending", "pending"])
        self.assertEqual(state["runner_runtime"]["python_version"], "3.13.14")

    def test_artifact_is_durable_before_state_reference_and_orphan_is_ignored(self):
        store = self.create_store()
        orphan = store.put_artifact("receipts", {"outcome": "success"})
        reopened = StateStore.open(store.root)
        self.assertNotIn(orphan.digest, json.dumps(reopened.snapshot()))
        next_state = reopened.snapshot()
        next_state["artifact_refs"] = [orphan.as_dict()]
        committed = reopened.commit(next_state)
        self.assertEqual(committed["revision"], 2)
        self.assertTrue(reopened.referenced_artifact(orphan.as_dict()).is_file())

    def test_rejects_symlink_input(self):
        link = self.root / "linked-spec.md"
        link.symlink_to(self.spec_a)
        with self.assertRaisesRegex(ValueError, "regular file"):
            StateStore.create(
                root=self.root / "state" / "bad",
                provider="codex",
                run_id="bad-12345678-1234-4234-8234-123456789abc",
                source_repository=self.repo,
                source_commit="a" * 40,
                worktree=self.root / "worktree",
                branch="codex-plan/bad-12345678-1234-4234-8234-123456789abc",
                specs=[link],
                plans=[self.plan_a],
                immutable_config={"stall_seconds": 3600, "sandbox": "workspace-write"},
                runner_runtime={
                    "uv_version": "uv 0.11.28",
                    "implementation": "cpython",
                    "python_version": "3.13.14",
                    "executable": "/managed/python3.13",
                    "architecture": "arm64",
                    "gil_disabled": False,
                },
            )

    def test_second_nonblocking_lock_is_rejected(self):
        store = self.create_store()
        with RunLock(store.root / "run.lock"):
            with self.assertRaisesRegex(RuntimeError, "run is busy"):
                with RunLock(store.root / "run.lock"):
                    self.fail("second lock must not be acquired")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the storage test and confirm the missing module failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_storage.py -v
```

Expected: FAIL with missing `plan_runner.storage`.

- [ ] **Step 3: Implement private writes and directory validation**

Use these exact invariants in `storage.py`:

```python
def atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    descriptor = os.open(
        str(temporary),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("private artifact must be a regular file")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(str(temporary), str(path))
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
```

Add `_require_private_directory`, `_reject_symlink_components`,
`_read_utf8_regular`, `_validate_run_id`, and `_validate_state`. Validation must
reject unknown format versions, invalid status vocabulary, non-monotonic
revisions, unsafe relative artifact paths, mismatched state digest, wrong
provider, wrong owner, group/other-writable directories, and missing referenced
artifacts.

- [ ] **Step 4: Implement artifact-first state commits**

Use this state envelope:

```json
{
  "format_version": 1,
  "contract_version": 1,
  "provider": "codex",
  "run_id": "slug-uuid",
  "revision": 1,
  "state_digest": "sha256 of the object with state_digest omitted",
  "status": "resumable",
  "integration": "not_observed",
  "immutable_config": {},
  "repository": {},
  "inputs": [],
  "plans": [],
  "current_plan_index": 0,
  "task_ledger": [],
  "sessions": [],
  "attempts": [],
  "artifact_refs": [],
  "failure": null,
  "finalization": null
}
```

`put_artifact(kind, payload)` must write
`artifacts/<kind>/<sha256>.json`, verify any existing same-name content is
identical, and return:

```python
@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    digest: str
    relative_path: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "digest": self.digest,
            "relative_path": self.relative_path,
        }
```

`commit(next_state)` must copy the mapping, set `revision` to current revision
plus one, recompute `state_digest`, validate every artifact reference, then
atomically replace `state.json`. It must not scan orphan artifacts into state.

- [ ] **Step 5: Implement `RunLock` with `fcntl.flock(LOCK_EX | LOCK_NB)`**

The lock file must be a private regular file under the run root. Release the
flock and descriptor in `__exit__`. Convert `EACCES` and `EAGAIN` into
`RuntimeError("run is busy")`.

- [ ] **Step 6: Run the storage tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_storage.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 7: Commit durable storage**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/storage.py \
  skills/kws-codex-plan-runner/evals/test_storage.py
git commit -m "feat(codex-runner): add crash-consistent run storage"
```

## Task 3: Git Worktree Identity and Accidental Remote-Mutation Guards

**Files:**

- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py`
- Create: `skills/kws-codex-plan-runner/evals/test_git_ops.py`

**Interfaces:**

- Consumes: full-SHA and digest validators from `contracts.py`.
- Produces:

Contractual API:

- immutable `WorktreeObservation` fields: `head`, `branch`,
  `porcelain_digest`, `tree_digest`, and `clean`;
- `GitWorkspace.create(source, worktree, branch) -> GitWorkspace`;
- `GitWorkspace.open(source, worktree, branch) -> GitWorkspace`;
- `observe`, `require_identity`, and
  `require_clean_ancestor(starting_commit)` return `WorktreeObservation`;
- `protected_refs() -> dict[str, str]`;
- `sanitized_child_env(source_env, *, provider_auth_prefixes, remotes, run_id)
  -> dict[str, str]`.

- [ ] **Step 1: Write Git tests using disposable repositories and a local bare remote**

Include tests that:

- reject a dirty source at `GitWorkspace.create`;
- create `codex-plan/<run-id>` once and reopen the exact registered worktree;
- detect branch, Git common-directory, and ancestry drift;
- include tracked, staged, untracked regular-file content in
  `porcelain_digest`/`tree_digest` without storing file bodies;
- remove `SSH_AUTH_SOCK`, `SSH_ASKPASS`, `GIT_ASKPASS`, `GH_TOKEN`,
  `GITHUB_TOKEN`, unrelated `*_TOKEN`, `*_SECRET`, and `*_API_KEY`;
- preserve `OPENAI_*` and `CODEX_*` provider authentication variables;
- set `GIT_TERMINAL_PROMPT=0`;
- remove inherited `GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_*`, and
  `GIT_CONFIG_VALUE_*`;
- inject `remote.<name>.pushurl=disabled://plan-runner/<run-id>/<name>` for
  every discovered remote;
- prove a child `git push origin HEAD` fails against a local bare remote while
  `git remote get-url origin` in repository config remains unchanged;
- detect changes to protected refs other than the assigned plan branch.

Use local repository configuration:

```python
def init_repository(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Runner Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "runner@example.test"], check=True)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "base"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
```

- [ ] **Step 2: Run the focused Git tests and confirm the missing module failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_git_ops.py -v
```

Expected: FAIL with missing `plan_runner.git_ops`.

- [ ] **Step 3: Implement shell-free Git execution and identity observation**

Every Git call must use:

```python
subprocess.run(
    ["git", *arguments],
    cwd=str(cwd),
    env=env,
    check=False,
    capture_output=True,
    text=False,
)
```

Never pass `shell=True`. Resolve the Git common directory through
`git rev-parse --git-common-dir`, require a real directory, and compare
`git worktree list --porcelain` records when reopening.

Build the worktree digest from sorted NUL-delimited porcelain-v2 entries plus
the SHA-256 of staged and untracked regular-file bytes. Reject symlinks,
directories escaping the worktree, unreadable entries, and files larger than
the implementation's explicit bounded-hash limit rather than silently omitting
them.

- [ ] **Step 4: Implement credential scrubbing and environment-only push URL overrides**

Use `GIT_CONFIG_COUNT` entries, not repository writes:

```python
for index, remote in enumerate(sorted(remotes)):
    clean[f"GIT_CONFIG_KEY_{index}"] = f"remote.{remote}.pushurl"
    clean[f"GIT_CONFIG_VALUE_{index}"] = (
        f"disabled://plan-runner/{run_id}/{remote}"
    )
clean["GIT_CONFIG_COUNT"] = str(len(remotes))
clean["GIT_TERMINAL_PROMPT"] = "0"
```

Sanitize remote names before using them in values and reject names containing
control characters. Document in the function docstring that these are
accidental-mutation guards, not same-UID isolation.

- [ ] **Step 5: Run the Git tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_git_ops.py -v
```

Expected: all Git and environment tests PASS without network access.

- [ ] **Step 6: Commit Git isolation**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py \
  skills/kws-codex-plan-runner/evals/test_git_ops.py
git commit -m "feat(codex-runner): guard worktree and git identity"
```

## Task 4: Exact Process Execution, Deadlines, and Verification Receipts

**Files:**

- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/process.py`
- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/evidence.py`
- Create: `skills/kws-codex-plan-runner/evals/test_evidence.py`

**Interfaces:**

- Consumes: `StateStore`, `ArtifactRef`, `GitWorkspace`, canonical hashing.
- Produces:

Contractual API:

- immutable `ExactCommand` fields: `command_id`, `command_role`, literal
  `argv`, relative `cwd`, `input_digest`, and `deadline_seconds`;
- immutable `VerificationReceipt` fields: `artifact`, `identity_digest`,
  `outcome`, `exit_code`, and `reused`;
- `EvidenceStore.execute(command, *, candidate_head) -> VerificationReceipt`;
- `reusable_success(identity_digest) -> VerificationReceipt | None`;
- `declare_final_set(payload, candidate_head) -> ArtifactRef`;
- `load_final_command(set_digest, index) -> ExactCommand`.

- [ ] **Step 1: Write focused evidence tests**

Cover these behaviors with real short-lived subprocesses:

```python
def python_command(source: str, *arguments: str) -> tuple[str, ...]:
    return (sys.executable, "-c", source, *arguments)
```

- literal argv such as `"$(touch should-not-exist)"` reaches Python unchanged;
- stdout and stderr are separately bounded and secret-like values are redacted;
- a command with `deadline_seconds=0.15` that sleeps for 5 seconds returns
  `verification_timed_out`, terminates its process group, and leaves no child;
- a successful exact identity is reused without a second launch;
- failed and timed-out receipts are not reusable successes;
- changed argv, cwd, executable, environment fingerprint, input digest,
  worktree digest, candidate HEAD, or command role changes identity;
- a final command is loaded only from a sealed final-set artifact;
- an empty final set is rejected unless it is exactly
  `{"kind":"no_applicable_verification","rationale":"non-empty"}`;
- every receipt artifact exists before its digest appears in state;
- liveness samples are recorded but never returned as material progress.

- [ ] **Step 2: Run the evidence test and confirm missing modules**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_evidence.py -v
```

Expected: FAIL with missing `process` or `evidence`.

- [ ] **Step 3: Implement bounded process-group execution**

`process.py` must define:

```python
@dataclass(frozen=True)
class ProcessResult:
    kind: str
    exit_code: int | None
    stdout_tail: bytes
    stderr_tail: bytes
    stdout_digest: str
    stderr_digest: str
    started_at: str
    finished_at: str
    forced_kill: bool


def run_exact(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    deadline_seconds: float,
    output_limit: int = 1_048_576,
) -> ProcessResult:
```

Requirements:

- validate non-empty string argv and a finite positive deadline;
- resolve the executable with `shutil.which` under the supplied environment;
- use `subprocess.Popen(list(argv), start_new_session=True, shell=False)`;
- drain stdout and stderr concurrently with `selectors`;
- hash all bytes while retaining only bounded tails;
- on deadline, send SIGTERM to the process group, wait 10 seconds, then SIGKILL;
- verify the process group is gone before returning;
- never refresh a provider progress lease from process existence.

- [ ] **Step 4: Implement execution identity and receipt sealing**

The identity object must contain exactly:

```python
{
    "argv": list(command.argv),
    "candidate_head": candidate_head,
    "command_role": command.command_role,
    "cwd": str(resolved_cwd),
    "environment_fingerprint": environment_fingerprint,
    "executable_identity": {
        "path": str(executable_path),
        "sha256": executable_digest,
        "mode": executable_stat.st_mode,
        "size": executable_stat.st_size,
    },
    "input_digest": command.input_digest,
    "worktree_digest": observation.tree_digest,
}
```

Receipt outcomes are `success`, `failed`, or `timed_out`. Only `success` may be
reused, and only after revalidating the content-addressed artifact and exact
identity.

- [ ] **Step 5: Implement final verification-set sealing**

Accepted declarations are:

```json
{
  "kind": "commands",
  "candidate_head": "full sha",
  "commands": [
    {
      "command_id": "final-unit",
      "command_role": "final",
      "argv": ["python3", "-m", "unittest"],
      "cwd": ".",
      "input_digest": "64 hex chars",
      "deadline_seconds": 7200
    }
  ]
}
```

The `python3` token above is deliberately target-project argv, not the runner
interpreter. Its resolved executable and environment are sealed only in this
verification receipt and never copied into `runner_runtime`.

or:

```json
{
  "kind": "no_applicable_verification",
  "candidate_head": "full sha",
  "rationale": "documentation-only change with no executable contract"
}
```

Reject absolute `cwd`, traversal, duplicate command IDs, non-final roles,
empty argv, control characters, invalid digests, nonpositive deadlines, and a
HEAD different from the observed clean worktree HEAD.

- [ ] **Step 6: Run the evidence tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_evidence.py -v
```

Expected: all tests PASS; the deadline test completes in under 12 seconds.

- [ ] **Step 7: Commit process and receipt support**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/process.py \
  skills/kws-codex-plan-runner/scripts/plan_runner/evidence.py \
  skills/kws-codex-plan-runner/evals/test_evidence.py
git commit -m "feat(codex-runner): seal exact verification receipts"
```

## Task 5: Parent-Owned Verification Helper Protocol

**Files:**

- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/helper.py`
- Create: `skills/kws-codex-plan-runner/evals/test_helper.py`
- Create: `skills/kws-codex-plan-runner/templates/final-verification-set.schema.json`

**Interfaces:**

- Consumes: `EvidenceStore`, `ExactCommand`, and `StateStore`.
- Produces:

Contractual API:

- immutable `HelperDescriptor` fields: `protocol_version`, `socket_path`,
  `nonce`, and literal absolute `client_argv`;
- `HelperServer` is a context manager whose enter starts the server and whose
  exit closes the socket, joins the thread, and unlinks the socket;
- read-only `descriptor -> HelperDescriptor`;
- read-only `active_command_deadline -> float | None`;
- `helper_client(socket_path, nonce, request) -> dict[str, object]`.

- [ ] **Step 1: Write protocol tests**

Test:

- the server creates one Unix socket at `<worktree>/.kws-plan-runner.sock`;
- `git status --porcelain` remains empty while the socket exists;
- the descriptor uses a 32-byte random nonce and absolute client argv;
- wrong nonce, wrong run ID, oversized request, malformed JSON, unknown
  operation, extra fields, traversal cwd, and concurrent final-set declarations
  are rejected without state mutation;
- `verify_focused` executes the exact submitted argv;
- `declare_final_set` seals one candidate-HEAD manifest;
- `verify_final` accepts only a command index from that sealed manifest;
- helper liveness is observable but not material progress;
- disconnecting the client does not cancel or duplicate an already running
  exact command;
- closing the server unlinks the socket and joins the server thread.

Use this request envelope:

```json
{
  "protocol_version": 1,
  "run_id": "slug-uuid",
  "nonce": "64 hex chars",
  "operation": "verify_focused",
  "payload": {}
}
```

- [ ] **Step 2: Run the helper test and confirm the missing module failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_helper.py -v
```

Expected: FAIL with missing `plan_runner.helper`.

- [ ] **Step 3: Implement a bounded newline-delimited JSON Unix-socket server**

Implementation requirements:

- maximum request size: 262,144 bytes;
- maximum response size: 262,144 bytes;
- one request and one response per connection;
- socket mode `0o600`;
- server thread is non-daemon and joined during shutdown;
- the socket path must be a direct child of the validated worktree;
- request dispatch runs under the parent controller and writes private state
  through `StateStore`;
- errors return
  `{"ok":false,"error_code":"unknown_operation","detail":"bounded text"}`;
- successes return
  `{"ok":true,"operation":"verify_focused","artifact":{"digest":"64 lowercase hex"}}`;
- no Python traceback or environment values cross the socket.

The provider child is a trusted same-UID executor, so the nonce prevents
cross-run accidents rather than claiming hostile authentication.

- [ ] **Step 4: Implement the client function and final-set schema**

The schema must use `additionalProperties: false`, distinguish `commands` from
`no_applicable_verification` with `oneOf`, require a full SHA pattern, require
64-hex digests, and require a positive `deadline_seconds`.

`helper_client` must use an exact Unix socket path, send canonical JSON plus one
newline, call `shutdown(SHUT_WR)`, read a bounded one-line response, validate
`ok` as boolean, and raise a bounded `RuntimeError` for protocol failure.

- [ ] **Step 5: Run the helper tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_helper.py -v
```

Expected: all helper tests PASS.

- [ ] **Step 6: Commit helper IPC**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/helper.py \
  skills/kws-codex-plan-runner/evals/test_helper.py \
  skills/kws-codex-plan-runner/templates/final-verification-set.schema.json
git commit -m "feat(codex-runner): add parent-owned verification helper"
```

## Task 6: Activity Lease, Material Progress, and Recovery Decisions

**Files:**

- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/recovery.py`
- Create: `skills/kws-codex-plan-runner/evals/test_recovery.py`

**Interfaces:**

- Consumes: state vocabulary and digest helpers.
- Produces:

Contractual API:

- immutable `ProgressSnapshot` fields: `git_tree_digest`,
  `reported_done_ids`, `successful_receipt_digests`, and
  `resolved_finding_ids`;
- immutable `RecoveryDecision` fields: `action`, `run_status`,
  `session_action`, `failure_signature`, `required_strategy_change`, and
  `reason_code`;
- `ActivityLease.observe_provider_event(kind, unique_key, now) -> bool`;
- `cover_command_until(deadline)`, `command_finished(now)`, and
  `expired(now) -> bool`;
- `RecoveryPolicy.decide(state, outcome) -> RecoveryDecision`.

- [ ] **Step 1: Write deterministic recovery tests with an injected fake clock**

Cover:

- distinct tool start/finish and lifecycle-phase events refresh the provider
  lease;
- repeated event keys, raw token deltas, repeated warnings, repeated output
  digests, and helper heartbeat do not refresh it;
- a command deadline covers provider inactivity only until its own deadline;
- controller alive plus child failure yields `recovering`, never `resumable`;
- controller absent yields `resumable`;
- healthy simple interruption chooses explicit-session resume;
- stall, repeated signature, context overflow, abnormal compaction, and session
  damage invalidate the session and require fresh session;
- missing session or resume failure falls back fresh;
- input digest change returns `input_changed_requires_new_run`;
- the initial attempt plus three distinct changed strategies are allowed;
- duplicate strategy-note digest is rejected;
- a new Git tree, evidence-backed `reported_done`, newly successful receipt, or
  resolved finding resets the failure sequence;
- logs, timestamps, token output, or a tree that returns to the same digest do
  not reset it;
- model name never appears in automatic recovery decisions.

- [ ] **Step 2: Run the recovery tests and confirm missing module failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_recovery.py -v
```

Expected: FAIL with missing `plan_runner.recovery`.

- [ ] **Step 3: Implement a lease that separates provider activity from command coverage**

Use:

```python
class ActivityLease:
    def __init__(self, stall_seconds: float, started_at: float) -> None:
        if not math.isfinite(stall_seconds) or stall_seconds <= 0:
            raise ValueError("stall_seconds must be positive")
        self._stall_seconds = stall_seconds
        self._last_activity = started_at
        self._seen_keys = set()
        self._command_deadline = None

    def observe_provider_event(self, kind: str, unique_key: str, now: float) -> bool:
        if kind not in {"tool_started", "tool_finished", "lifecycle_advanced"}:
            return False
        key = (kind, unique_key)
        if key in self._seen_keys:
            return False
        self._seen_keys.add(key)
        self._last_activity = now
        return True

    def cover_command_until(self, deadline: float) -> None:
        self._command_deadline = deadline

    def command_finished(self, now: float) -> None:
        self._command_deadline = None
        self._last_activity = now

    def expired(self, now: float) -> bool:
        if self._command_deadline is not None:
            return now >= self._command_deadline
        return now - self._last_activity >= self._stall_seconds
```

Do not add CPU/I/O heuristics or process-heartbeat progress.

- [ ] **Step 4: Implement canonical failure signatures and the bounded strategy ledger**

The failure signature hashes only stable facts:

```python
{
    "reason_code": reason_code,
    "provider_code": provider_code,
    "command_identity": command_identity,
    "candidate_head": candidate_head,
    "input_digest": input_digest,
}
```

Strategy notes are trimmed, bounded to 4,096 UTF-8 bytes, secret-scrubbed, and
stored by digest. For automatic recovery, the provider result must supply its
changed strategy note; the runner checks uniqueness but does not choose its
content.

- [ ] **Step 5: Run the recovery tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_recovery.py -v
```

Expected: all recovery tests PASS.

- [ ] **Step 6: Commit recovery policy**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/recovery.py \
  skills/kws-codex-plan-runner/evals/test_recovery.py
git commit -m "feat(codex-runner): add autonomous bounded recovery"
```

## Task 7: Codex Session Adapter and Stream Contract

**Files:**

- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/provider.py`
- Create: `skills/kws-codex-plan-runner/evals/fake_codex.py`
- Create: `skills/kws-codex-plan-runner/evals/test_provider.py`

**Interfaces:**

- Consumes: `ActivityLease`, `run_exact` process-group primitives,
  `sanitized_child_env`, `HelperDescriptor`.
- Produces:

Contractual API:

- immutable `ProviderRequest` fields: `worktree`, `git_common_dir`, `prompt`,
  `output_schema`, `output_path`, `sandbox`, optional `model`, and optional
  explicit `session_id`;
- immutable `ProviderOutcome` fields: `kind`, `return_code`, explicit
  `session_id`, structured `result`, `provider_code`, bounded `usage`,
  distinct `activity_keys`, and scrubbed `stderr_tail`;
- `CodexAdapter.build_argv(request) -> list[str]`;
- `CodexAdapter.launch(request, lease) -> ProviderOutcome`.

- [ ] **Step 1: Write provider argv, JSONL, session, environment, and stall tests**

The fake must:

- emit `{"type":"thread.started","thread_id":"<uuid>"}`;
- emit distinct `turn.started`, `item.started`, `item.completed`, and
  `turn.completed` events;
- write the structured final object to the `--output-last-message` path;
- log argv, cwd, selected environment keys, and launch number;
- support initial, explicit resume, resume-failure, transport-failure,
  context-overflow, repeated-log, stall, implemented, blocked, and failed
  scenarios;
- create commits only when the scenario requests implementation.

Tests must assert:

- initial argv includes `codex exec`, `--ignore-user-config`, `--json`,
  `--output-schema`, `--output-last-message`, `--cd`, `--sandbox`, one
  `--add-dir <git-common-dir>`, optional `--model`, and stdin prompt `-`;
- initial argv does not contain `--ephemeral`, `resume`, or `--last`;
- resume argv places exec-level flags before
  `resume <explicit-session-id> -`;
- resume argv never contains `--last`;
- the session UUID is captured before final output;
- only distinct lifecycle/tool events refresh the lease;
- repeated logs and token-like deltas do not prevent a stall;
- provider auth/usage/unavailable outcomes are classified as blockers;
- malformed JSONL and invalid structured output fail closed;
- stderr is bounded and scrubbed.

- [ ] **Step 2: Run the provider test and confirm missing adapter failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_provider.py -v
```

Expected: FAIL with missing `plan_runner.provider`.

- [ ] **Step 3: Implement exact initial and resume argv**

Initial:

```python
argv = [
    "codex", "exec",
    "--ignore-user-config",
    "--json",
    "--output-schema", str(request.output_schema),
    "--output-last-message", str(request.output_path),
    "--cd", str(request.worktree),
    "--sandbox", request.sandbox,
    "--add-dir", str(request.git_common_dir),
]
if request.model is not None:
    argv.extend(["--model", request.model])
argv.append("-")
```

Resume:

```python
argv = [
    "codex", "exec",
    "--ignore-user-config",
    "--json",
    "--output-schema", str(request.output_schema),
    "--output-last-message", str(request.output_path),
    "--cd", str(request.worktree),
    "--sandbox", request.sandbox,
    "--add-dir", str(request.git_common_dir),
]
if request.model is not None:
    argv.extend(["--model", request.model])
argv.extend(["resume", request.session_id, "-"])
```

Reject a resume request without a UUID-shaped explicit session ID.

- [ ] **Step 4: Implement streaming launch and event normalization**

Use a selectors loop over stdout and stderr. Bound each JSONL line to 65,536
bytes and retained logs to 1 MiB. Normalize only:

- `thread.started` with `thread_id` → session capture;
- unique `turn.started`/`turn.completed` → lifecycle activity;
- unique `item.started`/`item.completed` IDs → tool activity;
- `turn.completed.usage` → informational counters;
- structured error codes → provider blocker taxonomy.

Ignore partial-message/token deltas as activity. On lease expiry, terminate the
whole process group and return `kind="stalled"`.

- [ ] **Step 5: Run the provider tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_provider.py -v
```

Expected: all provider tests PASS.

- [ ] **Step 6: Verify installed Codex flag availability without running a model**

Run:

```bash
codex --version
codex exec --help
codex exec resume --help
```

Expected: version prints successfully; help contains `--json`,
`--output-schema`, `--output-last-message`, `--cd`, `--sandbox`, `--add-dir`,
and explicit `SESSION_ID` resume.

- [ ] **Step 7: Commit the Codex adapter**

```bash
git add skills/kws-codex-plan-runner/scripts/plan_runner/provider.py \
  skills/kws-codex-plan-runner/evals/fake_codex.py \
  skills/kws-codex-plan-runner/evals/test_provider.py
git commit -m "feat(codex-runner): add persistent session adapter"
```

## Task 8: Sequential Engine, Fresh Finalization, Public CLI, and Schemas

**Files:**

- Create: `skills/kws-codex-plan-runner/scripts/plan_runner/engine.py`
- Create: `skills/kws-codex-plan-runner/scripts/runner`
- Create: `skills/kws-codex-plan-runner/scripts/runner.py`
- Create: `skills/kws-codex-plan-runner/templates/plan-result.schema.json`
- Create: `skills/kws-codex-plan-runner/templates/finalization-result.schema.json`
- Create: `skills/kws-codex-plan-runner/evals/test_engine.py`

**Interfaces:**

- Consumes: all prior task interfaces.
- Produces:

Contractual API:

- immutable `RuntimePaths` fields: `state_home`, `worktree_home`,
  `runner_script`, and `skill_root`;
- `PlanRunner.create_run` keyword inputs: ordered `specs`, ordered `plans`,
  `workspace`, `stall_seconds`, `sandbox`, and optional `model`; returns the
  stable process exit code;
- `PlanRunner.resume(run_id, *, retry_blocked, retry_failed, strategy_note)
  -> int`;
- `PlanRunner.inspect(run_id) -> int`.

- [ ] **Step 1: Write engine tests around the fake Codex**

Build disposable Git repositories and inject:

```python
paths = RuntimePaths(
    state_home=temp_root / "state",
    worktree_home=temp_root / "worktrees",
    runner_script=SKILL_ROOT / "scripts/runner.py",
    skill_root=SKILL_ROOT,
)
```

Cover:

- multiple specs preserve order and are all in each implementation packet;
- multiple plans execute in CLI order;
- the packet exposes only current plan path, current index, and total count;
- plan states transition `pending → running → implemented`;
- opaque task entries accept only `pending`, `running`, `reported_done`;
- an implemented plan is never replayed;
- runner-runtime preflight completes and is persisted before worktree creation
  or provider launch;
- `runtime_missing` and `runtime_incompatible` produce `blocked` without a
  worktree, provider process, or Python download;
- state stores runner runtime identity independently from every verification
  receipt's target environment identity;
- invoking the absolute `scripts/runner` path from an unrelated current
  directory still locates `runner.py` and selects the same managed interpreter;
- every next plan starts a new session and receives Git/ledger/receipts, not the
  previous conversation;
- a controller-live recoverable failure loops automatically through
  `recovering`;
- healthy simple interruption resumes the explicit session;
- stall, repeated strategy, context damage, missing session, or failed resume
  starts a fresh session with changed strategy;
- the same failure permits only three distinct changed strategies after the
  initial attempt;
- material progress resets the sequence;
- controller-process reconciliation changes stale `running` to `resumable`;
- `resume --retry-blocked` is required for unchanged authority blockers;
- `resume --retry-failed` requires a nonempty nonduplicate `--strategy-note`;
- input snapshot digest change returns exit 64 without launching Codex;
- finalization starts one fresh session after all plans;
- finalization declares and executes every final command through the helper;
- finalization session may resume only at the same candidate HEAD/declaration;
- review result and all final receipts must name the same full SHA;
- a review finding causes a consolidated implementation recovery and a new
  candidate HEAD before finalization repeats;
- no applicable verification requires structured rationale and review
  approval;
- dirty worktree, wrong HEAD, wrong ancestry, changed protected refs, missing
  receipt, open Critical/Important finding, incomplete obligation, or helper
  tampering fails closed;
- successful output is `ready_for_integration` and
  `integration=not_observed`;
- no code path invokes merge, push, deploy, `--last`, or automatic model change;
- inspect is read-only and concise;
- exit codes match the versioned fixture.

- [ ] **Step 2: Run the engine tests and confirm missing engine failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: FAIL with missing `plan_runner.engine`.

- [ ] **Step 3: Add strict plan and finalization result schemas**

Plan result status is one of `implemented`, `blocked`, or `failed`.
`implemented` requires:

```json
{
  "status": "implemented",
  "head_commit": "full sha",
  "summary": "bounded text",
  "task_ledger": [
    {
      "task_id": "bounded identifier",
      "status": "reported_done",
      "evidence_digests": ["64 hex"]
    }
  ],
  "open_obligation_ids": [],
  "failure_signature": null,
  "strategy_note": "bounded text or null"
}
```

Blocked results require a blocker with one approved authority kind. Failed
results require a stable failure signature and nonempty strategy note.

Finalization result requires:

```json
{
  "status": "reviewed",
  "review_head": "full sha",
  "verification_set_digest": "64 hex",
  "open_findings": [],
  "open_obligation_ids": [],
  "no_applicable_verification_approved": false,
  "summary": "bounded text"
}
```

Findings include `id`, `severity`, `summary`, and `evidence`; severity is one
of `Critical`, `Important`, or `Minor`. Use `additionalProperties: false`.

- [ ] **Step 4: Implement immutable execution-packet construction**

Implementation packet fields:

```python
{
    "packet_version": 1,
    "mode": "implementation",
    "run_id": run_id,
    "worktree": str(worktree),
    "branch": branch,
    "starting_commit": starting_commit,
    "current_head": observation.head,
    "specifications": [
        {"snapshot_path": item["snapshot_path"], "sha256": item["sha256"]}
        for item in ordered_specs
    ],
    "current_plan": {
        "index": current_index,
        "total": len(plans),
        "snapshot_path": current_plan["snapshot_path"],
        "sha256": current_plan["sha256"],
    },
    "implemented_plan_handoffs": implemented_handoffs,
    "task_ledger": task_ledger,
    "verification_receipts": receipt_summaries,
    "checkpoint_revision": state["revision"],
    "required_strategy_change": required_strategy_change,
    "helper": helper_descriptor_as_dict,
    "quality_profile": "quality_first",
    "integration": "not_observed",
}
```

Do not include future plan paths, contents, or provider conversations.

- [ ] **Step 5: Implement the controller-owned automatic execution loop**

The loop order is:

```text
acquire run lock
reconcile stale controller identity
validate immutable inputs and Git identity
while a pending plan exists:
  mark current plan running
  open helper server
  choose healthy explicit-session resume or fresh session
  launch Codex with implementation packet
  checkpoint session ID, outcome, Git digest, ledger, receipts
  if implemented and mechanically valid: mark plan implemented
  if authority blocker: mark blocked and return 3
  if recoverable and controller alive: mark recovering and continue
  if recovery exhausted: mark failed and return 4
launch fresh finalization session for clean candidate HEAD
seal declared verification set
require every declared command success at candidate HEAD
require structured review at same HEAD and set digest
require unchanged clean worktree, ancestry, protected refs, and no open
  Critical/Important finding or obligation
write branch handoff
mark ready_for_integration and return 0
```

Persist state before and after every provider launch. Store OS process attempt
IDs separately from provider session lineage. A fresh plan always invalidates
the previous plan session for future resume.

- [ ] **Step 6: Implement concise prompts without duplicating Superpowers**

Implementation prompt must state facts and constraints only:

```text
Read the execution packet and immutable source documents.
Use Superpowers to implement CURRENT_PLAN only.
All SPECIFICATIONS are source-of-truth context; there is no positional
spec-to-plan pairing.
Choose implementation, tests, reviews, subagents, and technical recovery
strategies yourself. Quality and completion outrank token use.
Resolve ordinary defects autonomously. Do not ask the user.
Use the supplied helper for verification. Do not merge, push, deploy, or
modify files outside WORKTREE.
Return only the enforced structured result.
```

Finalization prompt must state:

```text
This is a fresh finalization context for CANDIDATE_HEAD.
Review the full starting-commit-to-candidate diff against every immutable spec
and plan. First declare the complete final verification set through the
helper, then execute every declared command through the helper, then return
one structured whole-branch review. Do not modify the worktree and do not
repeat existing exact successful evidence.
```

- [ ] **Step 7: Implement argparse and the helper client adapter**

Public commands:

```bash
./scripts/runner run --spec ABS [--spec ABS ...] \
  --plan ABS [--plan ABS ...] --workspace ABS \
  [--stall-seconds 3600] [--model MODEL] \
  [--sandbox workspace-write|danger-full-access]
./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note TEXT
./scripts/runner inspect --run-id RUN_ID
```

Add a hidden `_helper` subcommand that reads exactly one request object from
stdin and calls `helper_client`. Reject `--strategy-note` unless
`--retry-failed` is present and reject `--retry-failed` without a note.

Create executable `scripts/runner` exactly as a POSIX `sh` launcher:

```sh
#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' \
    '{"status":"blocked","reason_code":"runtime_missing","detail":"uv is not available"}'
  exit 3
fi

if ! PYTHON_BIN=$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13 2>/dev/null); then
  printf '%s\n' \
    '{"status":"blocked","reason_code":"runtime_missing","detail":"uv-managed CPython 3.13 is not installed"}'
  exit 3
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/runner.py" "$@"
```

`runner.py` calls `require_compatible_runtime()` before input snapshot,
worktree, or provider mutation. The hidden `_helper` client uses
`(sys.executable, absolute_runner_py, "_helper")` so internal helper calls
remain on the already validated interpreter without re-running uv lookup.

Default paths:

```python
state_home = Path.home() / ".codex" / "plan-runner"
worktree_home = Path.home() / ".codex" / "worktrees" / "plan-runner"
```

- [ ] **Step 8: Run the engine and all focused Codex-runner tests**

Run:

```bash
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest \
  skills/kws-codex-plan-runner/evals/test_contracts.py \
  skills/kws-codex-plan-runner/evals/test_runtime.py \
  skills/kws-codex-plan-runner/evals/test_storage.py \
  skills/kws-codex-plan-runner/evals/test_git_ops.py \
  skills/kws-codex-plan-runner/evals/test_evidence.py \
  skills/kws-codex-plan-runner/evals/test_helper.py \
  skills/kws-codex-plan-runner/evals/test_recovery.py \
  skills/kws-codex-plan-runner/evals/test_provider.py \
  skills/kws-codex-plan-runner/evals/test_engine.py -v
```

Expected: all tests PASS with no network and no real model invocation.

- [ ] **Step 9: Commit the executable engine**

```bash
chmod +x skills/kws-codex-plan-runner/scripts/runner
git add skills/kws-codex-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-codex-plan-runner/scripts/runner \
  skills/kws-codex-plan-runner/scripts/runner.py \
  skills/kws-codex-plan-runner/templates/plan-result.schema.json \
  skills/kws-codex-plan-runner/templates/finalization-result.schema.json \
  skills/kws-codex-plan-runner/evals/test_engine.py
git commit -m "feat(codex-runner): execute sequential plans to verified handoff"
```

## Task 9: Skill Contract, Deterministic Gate, and Repository Verification Routing

**Files:**

- Create: `skills/kws-codex-plan-runner/AGENTS.md`
- Create: `skills/kws-codex-plan-runner/CHANGELOG.md`
- Create: `skills/kws-codex-plan-runner/README.md`
- Create: `skills/kws-codex-plan-runner/SKILL.md`
- Create: `skills/kws-codex-plan-runner/evals/run.sh`
- Modify: `scripts/agent/contract.ts`
- Modify: `scripts/agent/check-contract.test.ts`
- Modify: `scripts/agent/verification-map.ts`
- Modify: `scripts/agent/verification-map.test.ts`

**Interfaces:**

- Consumes: complete Codex runner public CLI and eval modules.
- Produces: discoverable skill version `1.0.0`, deterministic `./evals/run.sh`,
  new `codex-plan-runner` repository verification scope.

- [ ] **Step 1: Write failing repository-contract and verification-map tests**

Add expectations that:

- `skills/kws-codex-plan-runner/AGENTS.md` and
  `skills/kws-codex-plan-runner/evals/run.sh` are required files;
- a change under `skills/kws-codex-plan-runner/` selects scope
  `codex-plan-runner`;
- selected commands are `agent-contract`, `diff-check`,
  `codex-plan-runner-eval`, and `check`;
- the existing legacy `codex-executor` scope remains during this plan.

Use:

```typescript
const codexPlanRunnerEval = command(
  "codex-plan-runner-eval",
  ["./evals/run.sh"],
  "skills/kws-codex-plan-runner",
);
```

- [ ] **Step 2: Run the focused repository tests and confirm failure**

Run:

```bash
bun test scripts/agent/check-contract.test.ts scripts/agent/verification-map.test.ts
```

Expected: FAIL because the new root and scope are not registered.

- [ ] **Step 3: Add the new contract root and verification scope**

Extend `ScopeId` with `"codex-plan-runner"`, add the exact command above, add:

```typescript
{
  id: "codex-plan-runner",
  matchers: ["skills/kws-codex-plan-runner/"],
  commands: [CONTRACT, DIFF_CHECK, CODEX_PLAN_RUNNER_EVAL, CHECK],
}
```

Include the new eval in `OFFLINE_COMMANDS`. Do not remove or rename legacy
commands in this plan.

- [ ] **Step 4: Write the skill instructions and public documentation**

`SKILL.md` frontmatter:

```yaml
---
name: kws-codex-plan-runner
description: Use when approved Superpowers specifications and one or more ordered implementation plans must run autonomously through Codex with durable recovery and fail-closed ready-for-integration evidence.
metadata:
  version: "1.0.0"
  updated_at: "2026-07-23"
---
```

`SKILL.md` and `README.md` must document:

- exact public commands and exit codes;
- uv-managed CPython `>=3.13,<3.14` preinstallation, the self-locating
  `./scripts/runner` launcher, and the no-download active-run rule;
- multiple ordered specs and plans with no positional pairing;
- one worktree/branch and current-plan-only execution;
- session resume versus fresh fallback;
- automatic `recovering` versus external `resumable`;
- helper-owned exact verification and command deadlines;
- candidate-HEAD finalization;
- `implemented` versus `ready_for_integration`;
- no merge/push/deploy and `integration=not_observed`;
- same-UID residual risk;
- deterministic and live validation separation.

`AGENTS.md` must require uv-managed normal-GIL CPython `>=3.13,<3.14`,
standard library only, an independent runtime, focused evals during work, full
eval at final HEAD, and real CLI contract recheck when flags or event parsing
change. It must forbid `uv run`, active-run downloads, and system-Python
fallback.

`CHANGELOG.md` records the 1.0.0 greenfield release without claiming legacy
state compatibility.

- [ ] **Step 5: Add the deterministic eval entrypoint**

```bash
#!/usr/bin/env bash
set -euo pipefail

PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest discover -s evals -p 'test_*.py' -v
"$PYTHON_313" -m py_compile scripts/runner.py scripts/plan_runner/*.py evals/*.py
bash -n evals/run.sh
bash -n scripts/runner
```

Mark `evals/run.sh`, `evals/fake_codex.py`, and `scripts/runner` executable.

- [ ] **Step 6: Run the focused repository tests**

Run:

```bash
bun test scripts/agent/check-contract.test.ts scripts/agent/verification-map.test.ts
```

Expected: PASS.

- [ ] **Step 7: Run the complete Codex runner deterministic gate once**

Run:

```bash
cd skills/kws-codex-plan-runner
./evals/run.sh
```

Expected: all unit/integration evals PASS, compilation PASS, shell syntax PASS.

- [ ] **Step 8: Run repository verification**

Run from repository root:

```bash
bun run agent:verify
```

Expected: `agent contract: PASS`; the Codex plan-runner eval is selected and
passes; no opt-in live evidence is claimed.

- [ ] **Step 9: Review the complete Plan 1 diff**

Review against `code_review.md`, focusing on:

- no legacy directory modifications;
- no runtime import of the root contract fixture;
- no Claude runtime dependency;
- no `--ephemeral` or `--last`;
- no shell execution of submitted verification argv;
- no total run/token/cost budget;
- no automatic model selection;
- no future-plan path in implementation packets;
- no same-UID containment claim.

Expected: no unresolved Critical or Important findings.

- [ ] **Step 10: Commit the Codex skill release surface**

```bash
git add skills/kws-codex-plan-runner \
  scripts/agent/contract.ts \
  scripts/agent/check-contract.test.ts \
  scripts/agent/verification-map.ts \
  scripts/agent/verification-map.test.ts
git commit -m "feat: add Codex quality-first plan runner"
```

## Plan 1 Completion Evidence

Before starting the Claude plan:

```bash
git status --short
git log -1 --oneline
cd skills/kws-codex-plan-runner && ./evals/run.sh
cd /Users/kws/source/private/Archive && bun run agent:verify
```

Required result:

- clean feature worktree;
- Codex runner deterministic gate PASS;
- repository gate PASS;
- no real provider canary claimed yet;
- legacy CPE/CLPE source, symlinks, state, and processes unchanged.
