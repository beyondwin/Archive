# AgentRunway Production Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `agent-runway` from local/fake execution plus Codex/Claude command wrappers into a production supervisor that launches, monitors, validates, reviews, verifies, merges, resumes, and applies Codex/Claude worker runs.

**Architecture:** Keep the skill thin and concentrate orchestration in the deterministic Python runner. Add a lifecycle adapter contract, a shared process supervisor, worker attempt state in SQLite, worker worktree creation, result/diff validation, review and verification gates, merge queue conflict handling, resumable state reconciliation, explicit source apply, and AgentLens/local event emission.

**Tech Stack:** Python 3.11+ stdlib (`argparse`, `dataclasses`, `enum`, `json`, `os`, `signal`, `sqlite3`, `subprocess`, `time`, `pathlib`, `hashlib`, `fnmatch`, `shutil`), git worktrees/cherry-pick, pytest, shell fake CLIs for deterministic Codex/Claude adapter evals.

---

## Source Documents

- Design: `docs/superpowers/specs/2026-05-20-agent-runway-production-supervisor-design.md`
- Parent design: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
- Current skill root: `skills/agent-runway/`

## Scope Check

The approved design intentionally chooses the broad production-supervisor path:
Codex and Claude adapters, process supervision, worker worktrees, watchdog,
review/verify gates, merge queue, resume, apply, and observability. This is one
cohesive subsystem because each feature depends on the same worker lifecycle
state model. The implementation plan still uses small commits so each stage has
focused tests and a recoverable checkpoint.

## File Structure

### Rename / Delete

| Path | Change |
| --- | --- |
| `skills/kws-agent-orchestrator/` | Move to `skills/agent-runway/`; do not leave a repo alias directory. |
| `skills/agent-runway/scripts/kao.py` | Move to `skills/agent-runway/scripts/agentrunway.py`. |
| `skills/agent-runway/scripts/kao/` | Move to `skills/agent-runway/scripts/agentrunway/`. |
| `~/.codex/skills/kws-agent-orchestrator` | Remove local skill symlink. |
| `~/.codex/skills/agent-runway` | Create local skill symlink to `skills/agent-runway`. |

### Create

| Path | Responsibility |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/adapters/process.py` | Shared subprocess launch, polling, timeout, log capture, cancellation, and collection primitives. |
| `skills/agent-runway/scripts/agentrunway/supervisor.py` | Runner-level worker attempt orchestration helpers independent of CLI parsing. |
| `skills/agent-runway/scripts/agentrunway/apply.py` | Explicit source checkout apply strategies and rollback helpers. |
| `skills/agent-runway/evals/test_supervisor_state.py` | DB/model tests for worker attempts, state transitions, and applied commit state. |
| `skills/agent-runway/evals/test_process_supervisor.py` | Tests for shared process lifecycle behavior. |
| `skills/agent-runway/evals/test_production_adapters_fake_cli.py` | Fake Codex/Claude adapter tests through real subprocess paths. |
| `skills/agent-runway/evals/test_worker_worktrees.py` | Worker worktree, commit discovery, and diff-scope tests. |
| `skills/agent-runway/evals/test_runner_production_e2e.py` | End-to-end fake Codex/Claude runs with review, verify, and merge. |
| `skills/agent-runway/evals/test_resume_apply.py` | Resume idempotence and `agentrunway apply` safety tests. |
| `skills/agent-runway/evals/fixtures/fake-bin/codex` | Deterministic fake Codex CLI used by tests. |
| `skills/agent-runway/evals/fixtures/fake-bin/claude` | Deterministic fake Claude CLI used by tests. |

### Modify

| Path | Change |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/models.py` | Add worker lifecycle enums, worker specs, handles, process statuses, result envelopes, review/verification dataclasses, and applied commit records. |
| `skills/agent-runway/scripts/agentrunway/db.py` | Add schema columns/tables and repository methods for worker attempts, artifacts, merge candidates, review/verify results, events, watchdog events, and applied commits. |
| `skills/agent-runway/scripts/agentrunway/adapters/base.py` | Replace one-shot adapter-only protocol with lifecycle methods while keeping the local fake `run()` path for tests. |
| `skills/agent-runway/scripts/agentrunway/adapters/local.py` | Keep deterministic local adapter aligned with the expanded contract. |
| `skills/agent-runway/scripts/agentrunway/adapters/codex.py` | Implement Codex lifecycle using `codex exec` and shared process supervisor. |
| `skills/agent-runway/scripts/agentrunway/adapters/claude.py` | Implement Claude lifecycle using headless `claude -p` command and shared process supervisor. |
| `skills/agent-runway/scripts/agentrunway/git_ops.py` | Add git primitives for branches, worktrees, commit lists, changed files, cherry-pick abort, patch generation, and clean reset points. |
| `skills/agent-runway/scripts/agentrunway/worktrees.py` | Add worker/reviewer/verifier worktree creation, orphan inspection, and cleanup helpers. |
| `skills/agent-runway/scripts/agentrunway/packetizer.py` | Support role-specific packet/prompt output paths and review/verification prompt materialization. |
| `skills/agent-runway/scripts/agentrunway/result_validation.py` | Validate worker, review, and verification result schemas with normalized error codes. |
| `skills/agent-runway/scripts/agentrunway/file_claims.py` | Validate actual git-derived changed files against file claims. |
| `skills/agent-runway/scripts/agentrunway/merge_queue.py` | Store candidate state, gate state, merge attempts, and conflict retry decisions. |
| `skills/agent-runway/scripts/agentrunway/watchdog.py` | Classify running workers from process, timeout, log mtime, and artifact evidence. |
| `skills/agent-runway/scripts/agentrunway/events.py` | Emit and persist lifecycle events with redaction. |
| `skills/agent-runway/scripts/agentrunway/runner.py` | Drive production state machine for `run`, `resume`, and `apply`. |
| `skills/agent-runway/scripts/agentrunway/invocation.py` | Add adapter, timeout, apply strategy, and fake CLI test options as needed. |
| `skills/agent-runway/README.md` | Document production supervisor commands, fake adapter tests, and opt-in real CLI smoke tests. |
| `skills/agent-runway/references/runtime-adapters.md` | Replace wrapper wording with production lifecycle contract. |
| `skills/agent-runway/references/merge-queue.md` | Document gate states, conflict retry, and applied commit records. |
| `skills/agent-runway/references/watchdog.md` | Document polling evidence and retry policy. |
| `skills/agent-runway/references/schemas/*.json` | Align schemas with review/verification and multi-commit worker results. |

---

## Task 0: Rename Existing Skill to AgentRunway and Remove Legacy Aliases

```yaml agentrunway-task
task_id: task_000
title: Rename existing skill to AgentRunway and remove legacy aliases
risk: high
phase: implementation
dependencies: []
spec_refs: [S1, S2, S3, S16]
file_claims:
  - {path: skills/kws-agent-orchestrator/**, mode: owned}
  - {path: skills/agent-runway/**, mode: owned}
  - {path: skills/README.md, mode: owned}
acceptance_commands:
  - python -m pytest skills/agent-runway/evals/test_cli_smoke.py -v
  - python -m pytest skills/agent-runway/evals/test_models_and_schemas.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Move: `skills/kws-agent-orchestrator/` -> `skills/agent-runway/`
- Move: `skills/agent-runway/scripts/kao.py` -> `skills/agent-runway/scripts/agentrunway.py`
- Move: `skills/agent-runway/scripts/kao/` -> `skills/agent-runway/scripts/agentrunway/`
- Modify: `skills/agent-runway/SKILL.md`
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/AGENTS.md`
- Modify: `skills/agent-runway/evals/**/*.py`
- Modify: `skills/agent-runway/references/**/*.md`
- Modify: `skills/agent-runway/references/schemas/*.json`
- Modify: `skills/README.md`

- [ ] **Step 1: Move the skill directory and runner package**

Run:

```bash
git mv skills/kws-agent-orchestrator skills/agent-runway
git mv skills/agent-runway/scripts/kao.py skills/agent-runway/scripts/agentrunway.py
git mv skills/agent-runway/scripts/kao skills/agent-runway/scripts/agentrunway
```

Expected: the old repo path no longer exists, and `skills/agent-runway/scripts/agentrunway.py` plus `skills/agent-runway/scripts/agentrunway/__init__.py` exist.

- [ ] **Step 2: Rename Python imports and CLI strings**

Run a mechanical replacement and then inspect the diff. The substitutions below are
order-sensitive: SCREAMING_SNAKE_CASE constants (`KAO_HOME`, `KAO_VERSION`, generic `KAO_*`)
and CamelCase identifiers (`KaoDb`, generic `Kao[A-Z]…`) are rewritten BEFORE the generic
`KAO`→`AgentRunway` rule, otherwise `KAO_HOME` becomes the broken `AgentRunway_HOME`
(Step 6 expects `AGENTRUNWAY_HOME`) and `KaoDb` is left untouched (case-sensitive miss):

```bash
perl -0pi -e 's/from kao\\./from agentrunway./g; s/import kao\\./import agentrunway./g; s/\\bkao\\b/agentrunway/g; s/KAO_HOME/AGENTRUNWAY_HOME/g; s/KAO_VERSION/AGENTRUNWAY_VERSION/g; s/\\bKAO_/AGENTRUNWAY_/g; s/KaoDb/AgentRunwayDb/g; s/\\bKao(?=[A-Z])/AgentRunway/g; s/KAO/AgentRunway/g; s/kws\\.kao/agentrunway/g; s/kws-agent-orchestrator/agent-runway/g; s/KWS Agent Orchestrator/AgentRunway/g' \
  $(rg -l 'kao|KAO|Kao|kws\\.kao|kws-agent-orchestrator|KWS Agent Orchestrator' skills/agent-runway skills/README.md)
git diff -- skills/agent-runway skills/README.md
```

Expected: imports use `agentrunway`, CLI help says `agentrunway`, schema constants use `agentrunway.*`, state defaults use `~/.agentrunway`, environment variable is `AGENTRUNWAY_HOME` (all caps), the database class is `AgentRunwayDb`, and README/SKILL docs refer to AgentRunway.

- [ ] **Step 3: Fix package entrypoints**

Update `skills/agent-runway/scripts/agentrunway.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agentrunway.invocation import main


if __name__ == "__main__":
    raise SystemExit(main())
```

Update `skills/agent-runway/scripts/agentrunway/__main__.py` so it imports from `.invocation` and continues to call `main()`.

- [ ] **Step 4: Update schemas and event names**

Update `skills/agent-runway/scripts/agentrunway/models.py` constants:

```python
AGENTRUNWAY_VERSION = "0.1.0"
TASK_PACKET_SCHEMA = "agentrunway.task_packet.v1"
RESULT_SCHEMA = "agentrunway.worker_result.v1"
REVIEW_SCHEMA = "agentrunway.review_result.v1"
VERIFICATION_SCHEMA = "agentrunway.verification_result.v1"
EVENT_SCHEMA = "agentrunway.event.v1"
```

Update `skills/agent-runway/scripts/agentrunway/db.py` to import `AGENTRUNWAY_VERSION` and store `agentrunway_version` instead of the pre-AgentRunway column name. If the table still has the previous column name from an existing test DB, create a fresh test DB rather than carrying a migration alias.

Update schema files under `skills/agent-runway/references/schemas/` so `$id` and `const` values use the `agentrunway.*.v1` ids.

- [ ] **Step 5: Update plan parser fence name**

Modify `skills/agent-runway/scripts/agentrunway/plan_parser.py`:

```python
BLOCK_RE = re.compile(r"```yaml agentrunway-task\n(.*?)\n```", re.DOTALL)
```

Update parser errors and eval fixtures from `agentrunway-task` consistently. The parser must not accept the previous fence name; this enforces the no-alias policy.

- [ ] **Step 6: Update tests to the new script and package**

In evals:

- `SCRIPT = ROOT / "scripts" / "agentrunway.py"`
- imports use `from agentrunway...`
- CLI version assertion starts with `agentrunway `
- git branches use `agentrunway/<run_id>/...`
- env var uses `AGENTRUNWAY_HOME`
- fixture code fences use ````yaml agentrunway-task````
- fake git config uses `agentrunway@example.invalid` and `AgentRunway Test`

- [ ] **Step 7: Replace skill symlink**

Run:

```bash
rm -f /Users/kws/.codex/skills/kws-agent-orchestrator
ln -s /Users/kws/source/private/Archive/skills/agent-runway /Users/kws/.codex/skills/agent-runway
test ! -e /Users/kws/.codex/skills/kws-agent-orchestrator
test -f /Users/kws/.codex/skills/agent-runway/SKILL.md
```

Expected: only the AgentRunway skill symlink remains. There is no old-name symlink.

- [ ] **Step 8: Run rename-focused tests**

Run:

```bash
python -m pytest skills/agent-runway/evals/test_cli_smoke.py -v
python -m pytest skills/agent-runway/evals/test_models_and_schemas.py -v
python -m pytest skills/agent-runway/evals/test_plan_parser.py -v
```

Expected: all pass using only AgentRunway names.

- [ ] **Step 9: Verify legacy names are absent from active skill files**

Run:

```bash
! rg -n 'kws-agent-orchestrator|KWS Agent Orchestrator|kws\\.kao|\\bkao\\b|\\bKao[A-Z]|KAO|kao-task|~/.kao' skills/agent-runway skills/README.md
```

Expected: command exits 0 because `rg` finds no legacy names (including the CamelCase `Kao*` and SCREAMING_SNAKE `KAO_*` forms) in active skill files.

- [ ] **Step 10: Commit**

Run:

```bash
git add skills/agent-runway skills/README.md
git update-index --force-remove skills/kws-agent-orchestrator 2>/dev/null || true
git commit -m "refactor: rename skill to AgentRunway"
```

## Task 1: Worker Lifecycle Models and SQLite State

```yaml agentrunway-task
task_id: task_001
title: Worker lifecycle models and SQLite state
risk: medium
phase: implementation
dependencies: [task_000]
spec_refs: [S5, S6, S12, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/models.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/db.py, mode: owned}
  - {path: skills/agent-runway/evals/test_supervisor_state.py, mode: owned}
acceptance_commands:
  - python -m pytest evals/test_supervisor_state.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: false
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/models.py`
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Create: `skills/agent-runway/evals/test_supervisor_state.py`

- [ ] **Step 1: Write failing state model and DB tests**

Create `skills/agent-runway/evals/test_supervisor_state.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import ProcessState, WorkerRole, WorkerState


def test_worker_lifecycle_enums_cover_production_states() -> None:
    assert WorkerRole.IMPLEMENTER.value == "implementer"
    assert WorkerRole.REVIEWER.value == "reviewer"
    assert WorkerRole.VERIFIER.value == "verifier"
    assert WorkerState.QUEUED.value == "queued"
    assert WorkerState.WORKTREE_CREATED.value == "worktree_created"
    assert WorkerState.DISPATCHED.value == "dispatched"
    assert WorkerState.RUNNING.value == "running"
    assert WorkerState.RESULT_COLLECTED.value == "result_collected"
    assert WorkerState.VALIDATED.value == "validated"
    assert WorkerState.MERGE_READY.value == "merge_ready"
    assert WorkerState.MERGED.value == "merged"
    assert WorkerState.ADAPTER_CRASHED.value == "adapter_crashed"
    assert WorkerState.TIMEOUT.value == "timeout"
    assert WorkerState.DIFF_SCOPE_FAILED.value == "diff_scope_failed"
    assert ProcessState.RUNNING.value == "running"
    assert ProcessState.EXITED.value == "exited"
    assert ProcessState.MISSING.value == "missing"


def test_db_records_worker_attempt_state_and_handle(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="xhigh",
        attempt=1,
        worktree_path="/tmp/worker",
        branch="agentrunway/run/task_001-implementer-001",
        state="queued",
        handle_json={"pid": None, "session_id": None},
    )
    db.set_worker_state("task_001-implementer-001", "running")
    db.update_worker_handle("task_001-implementer-001", {"pid": 123, "session_id": "abc"})

    row = db.get_worker("task_001-implementer-001")
    assert row["state"] == "running"
    assert row["attempt"] == 1
    assert row["handle_json"]["pid"] == 123
    assert row["worktree_path"] == "/tmp/worker"


def test_db_records_merge_candidate_and_applied_commits(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123", "def456"),
        changed_files=("src/a.py",),
        status="pending_review",
    )
    db.set_merge_candidate_status(1, "merge_ready")
    db.record_applied_commit(run_id="run-1", commit_sha="abc123", strategy="cherry-pick")

    candidates = db.list_merge_candidates()
    applied = db.list_applied_commits("run-1")
    assert candidates[0]["commits"] == ["abc123", "def456"]
    assert candidates[0]["changed_files"] == ["src/a.py"]
    assert candidates[0]["status"] == "merge_ready"
    assert applied == [{"commit_sha": "abc123", "strategy": "cherry-pick"}]
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_supervisor_state.py -v
```

Expected: fail because `WorkerRole`, `WorkerState`, `ProcessState`, and the new DB methods do not exist.

- [ ] **Step 3: Add lifecycle models**

Modify `skills/agent-runway/scripts/agentrunway/models.py` by adding these definitions below `TaskStatus`:

```python
class WorkerRole(str, Enum):
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"
    RECOVERY = "recovery"


class WorkerState(str, Enum):
    QUEUED = "queued"
    WORKTREE_CREATED = "worktree_created"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    RESULT_COLLECTED = "result_collected"
    VALIDATED = "validated"
    QUEUED_FOR_REVIEW = "queued_for_review"
    REVIEWING = "reviewing"
    VERIFYING = "verifying"
    MERGE_READY = "merge_ready"
    MERGED = "merged"
    ADAPTER_CRASHED = "adapter_crashed"
    TIMEOUT = "timeout"
    STALLED = "stalled"
    MALFORMED_RESULT = "malformed_result"
    METHOD_AUDIT_FAILED = "method_audit_failed"
    DIFF_SCOPE_FAILED = "diff_scope_failed"
    MERGE_CONFLICT = "merge_conflict"
    VERIFICATION_FAILED = "verification_failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ProcessState(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    EXITED = "exited"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    MISSING = "missing"


@dataclass(frozen=True)
class WorkerSpec:
    run_id: str
    task_id: str
    worker_id: str
    role: str
    runtime: str
    model: str
    reasoning_effort: str
    prompt_path: str
    packet_path: str
    output_path: str
    worktree_path: str
    artifact_dir: str
    timeout_seconds: int
    attempt: int = 1


@dataclass(frozen=True)
class ProcessSnapshot:
    state: str
    pid: int | None
    returncode: int | None = None
    started_at: float | None = None
    ended_at: float | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class WorkerResultEnvelope:
    worker_id: str
    task_id: str
    role: str
    runtime: str
    process: ProcessSnapshot
    result_path: str
    result_json: dict[str, Any] | None
    stdout_path: str
    stderr_path: str
    error: str | None = None
```

- [ ] **Step 4: Add DB schema and repository methods**

Modify `skills/agent-runway/scripts/agentrunway/db.py`:

1. Replace the `workers` table in `SCHEMA_SQL` with this shape:

```sql
CREATE TABLE IF NOT EXISTS workers (
  worker_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  role TEXT NOT NULL,
  runtime TEXT NOT NULL,
  model TEXT NOT NULL,
  reasoning_effort TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL,
  worktree_path TEXT,
  branch TEXT,
  handle_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT,
  ended_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

2. Replace the `merge_queue` table in `SCHEMA_SQL` with:

```sql
CREATE TABLE IF NOT EXISTS merge_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  worker_id TEXT NOT NULL,
  commits_json TEXT NOT NULL,
  changed_files_json TEXT NOT NULL,
  status TEXT NOT NULL,
  merge_attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

This replaces the pre-AgentRunway `merge_queue(commit_sha, patch_path)` shape and is an
intentional breaking change consistent with the no-alias policy in design §3. There is no
migration: any pre-existing `~/.kao/.../state.sqlite` is abandoned, and tests must open
fresh DB files. If an integration accidentally re-uses an old DB, `CREATE TABLE IF NOT
EXISTS` will skip the new shape — `db.py` must therefore `DROP TABLE IF EXISTS merge_queue`
once at module bootstrap when the surviving columns do not match (or, more simply,
require that callers always open a path that does not yet contain a `merge_queue` row).

3. Add applied commit storage to `SCHEMA_SQL`:

```sql
CREATE TABLE IF NOT EXISTS applied_commits (
  run_id TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  strategy TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(run_id, commit_sha)
);
```

4. Add methods to `AgentRunwayDb`:

```python
    def create_worker_attempt(self, **fields: Any) -> None:
        payload = {
            "worker_id": fields["worker_id"],
            "task_id": fields["task_id"],
            "role": fields["role"],
            "runtime": fields["runtime"],
            "model": fields["model"],
            "reasoning_effort": fields["reasoning_effort"],
            "attempt": int(fields.get("attempt", 1)),
            "worktree_path": fields.get("worktree_path"),
            "branch": fields.get("branch"),
            "state": fields["state"],
            "handle_json": json.dumps(fields.get("handle_json", {}), sort_keys=True),
        }
        # Plain INSERT, not INSERT OR REPLACE: design §11 requires each retry to
        # mint a new worker_id, so a primary-key collision here is a programming
        # bug we want to surface, not silently overwrite.
        self.conn.execute(
            """
            INSERT INTO workers
              (worker_id, task_id, role, runtime, model, reasoning_effort, attempt, worktree_path, branch, state, handle_json)
            VALUES
              (:worker_id, :task_id, :role, :runtime, :model, :reasoning_effort, :attempt, :worktree_path, :branch, :state, :handle_json)
            """,
            payload,
        )
        self.conn.commit()

    def set_worker_state(self, worker_id: str, state: str) -> None:
        self.conn.execute(
            "UPDATE workers SET state=?, updated_at=CURRENT_TIMESTAMP WHERE worker_id=?",
            (state, worker_id),
        )
        self.conn.commit()

    def update_worker_handle(self, worker_id: str, handle_json: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE workers SET handle_json=?, updated_at=CURRENT_TIMESTAMP WHERE worker_id=?",
            (json.dumps(handle_json, sort_keys=True), worker_id),
        )
        self.conn.commit()

    def get_worker(self, worker_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM workers WHERE worker_id=?", (worker_id,)).fetchone()
        if row is None:
            raise KeyError(worker_id)
        data = dict(row)
        data["handle_json"] = json.loads(data["handle_json"])
        return data

    def enqueue_merge_candidate(
        self,
        *,
        task_id: str,
        worker_id: str,
        commits: tuple[str, ...],
        changed_files: tuple[str, ...],
        status: str,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO merge_queue (task_id, worker_id, commits_json, changed_files_json, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, worker_id, json.dumps(list(commits)), json.dumps(list(changed_files)), status),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def set_merge_candidate_status(self, candidate_id: int, status: str, error: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE merge_queue
            SET status=?, error=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (status, error, candidate_id),
        )
        self.conn.commit()

    def list_merge_candidates(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM merge_queue ORDER BY id").fetchall()
        candidates: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["commits"] = json.loads(data.pop("commits_json"))
            data["changed_files"] = json.loads(data.pop("changed_files_json"))
            candidates.append(data)
        return candidates

    def record_applied_commit(self, *, run_id: str, commit_sha: str, strategy: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO applied_commits (run_id, commit_sha, strategy) VALUES (?, ?, ?)",
            (run_id, commit_sha, strategy),
        )
        self.conn.commit()

    def list_applied_commits(self, run_id: str) -> list[dict[str, str]]:
        rows = self.conn.execute(
            "SELECT commit_sha, strategy FROM applied_commits WHERE run_id=? ORDER BY applied_at, commit_sha",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 5: Run the state tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_supervisor_state.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Run existing DB/model tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_db.py evals/test_models_and_schemas.py -v
```

Expected: existing tests still pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/models.py \
  skills/agent-runway/scripts/agentrunway/db.py \
  skills/agent-runway/evals/test_supervisor_state.py
git commit -m "feat: add AgentRunway worker lifecycle state"
```

---

## Task 2: Shared Process Supervisor

```yaml agentrunway-task
task_id: task_002
title: Shared process supervisor
risk: medium
phase: implementation
dependencies: [task_001]
spec_refs: [S6, S11, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/adapters/process.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/adapters/base.py, mode: owned}
  - {path: skills/agent-runway/evals/test_process_supervisor.py, mode: owned}
acceptance_commands:
  - python -m pytest evals/test_process_supervisor.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: false
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/adapters/process.py`
- Modify: `skills/agent-runway/scripts/agentrunway/adapters/base.py`
- Create: `skills/agent-runway/evals/test_process_supervisor.py`

- [ ] **Step 1: Write failing process lifecycle tests**

Create `skills/agent-runway/evals/test_process_supervisor.py`:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path

from agentrunway.adapters.process import ProcessLaunchSpec, ProcessSupervisor


def test_process_supervisor_collects_exit_and_logs(tmp_path: Path) -> None:
    script = tmp_path / "worker.py"
    output = tmp_path / "result.json"
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "print('hello stdout')\n"
        "print('hello stderr', file=sys.stderr)\n"
        f"Path({str(output)!r}).write_text('{{\"ok\": true}}', encoding='utf-8')\n",
        encoding="utf-8",
    )
    spec = ProcessLaunchSpec(
        worker_id="worker-1",
        command=[sys.executable, str(script)],
        cwd=tmp_path,
        stdout_path=stdout,
        stderr_path=stderr,
        timeout_seconds=10,
        env={},
    )

    supervisor = ProcessSupervisor()
    handle = supervisor.start(spec)
    snapshot = supervisor.wait(handle)

    assert snapshot.state == "exited"
    assert snapshot.returncode == 0
    assert stdout.read_text(encoding="utf-8").strip() == "hello stdout"
    assert stderr.read_text(encoding="utf-8").strip() == "hello stderr"
    assert output.exists()


def test_process_supervisor_reports_timeout(tmp_path: Path) -> None:
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    spec = ProcessLaunchSpec(
        worker_id="worker-timeout",
        command=[sys.executable, str(script)],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_seconds=0,
        env={},
    )

    supervisor = ProcessSupervisor()
    handle = supervisor.start(spec)
    snapshot = supervisor.wait(handle)

    assert snapshot.state == "timed_out"
    assert snapshot.reason == "timeout"


def test_process_supervisor_merges_environment(tmp_path: Path) -> None:
    script = tmp_path / "env.py"
    out = tmp_path / "env.txt"
    script.write_text(
        "import os\n"
        "from pathlib import Path\n"
        f"Path({str(out)!r}).write_text(os.environ['AGENTRUNWAY_TEST_VALUE'], encoding='utf-8')\n",
        encoding="utf-8",
    )
    spec = ProcessLaunchSpec(
        worker_id="worker-env",
        command=[sys.executable, str(script)],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_seconds=10,
        env={"AGENTRUNWAY_TEST_VALUE": "present"},
    )

    supervisor = ProcessSupervisor()
    snapshot = supervisor.wait(supervisor.start(spec))
    assert snapshot.state == "exited"
    assert out.read_text(encoding="utf-8") == "present"
    assert os.environ.get("AGENTRUNWAY_TEST_VALUE") is None
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_process_supervisor.py -v
```

Expected: fail because `agentrunway.adapters.process` does not exist.

- [ ] **Step 3: Implement process primitives**

Create `skills/agent-runway/scripts/agentrunway/adapters/process.py`:

```python
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ..models import ProcessSnapshot


@dataclass(frozen=True)
class ProcessLaunchSpec:
    worker_id: str
    command: list[str]
    cwd: Path
    stdout_path: Path
    stderr_path: Path
    timeout_seconds: int
    env: dict[str, str]


@dataclass(frozen=True)
class ProcessHandle:
    worker_id: str
    pid: int
    command: list[str]
    cwd: str
    stdout_path: str
    stderr_path: str
    timeout_seconds: int
    started_at: float


class ProcessSupervisor:
    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen[str]] = {}

    def start(self, spec: ProcessLaunchSpec) -> ProcessHandle:
        spec.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        spec.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = spec.stdout_path.open("w", encoding="utf-8")
        stderr = spec.stderr_path.open("w", encoding="utf-8")
        env = os.environ.copy()
        env.update(spec.env)
        proc = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            stdout=stdout,
            stderr=stderr,
            text=True,
            env=env,
            start_new_session=True,
        )
        stdout.close()
        stderr.close()
        self._processes[proc.pid] = proc
        return ProcessHandle(
            worker_id=spec.worker_id,
            pid=proc.pid,
            command=list(spec.command),
            cwd=str(spec.cwd),
            stdout_path=str(spec.stdout_path),
            stderr_path=str(spec.stderr_path),
            timeout_seconds=spec.timeout_seconds,
            started_at=time.time(),
        )

    def poll(self, handle: ProcessHandle) -> ProcessSnapshot:
        proc = self._processes.get(handle.pid)
        if proc is None:
            return ProcessSnapshot(
                state="missing",
                pid=handle.pid,
                started_at=handle.started_at,
                stdout_path=handle.stdout_path,
                stderr_path=handle.stderr_path,
                reason="process_not_tracked",
            )
        returncode = proc.poll()
        state = "running" if returncode is None else "exited"
        return ProcessSnapshot(
            state=state,
            pid=handle.pid,
            returncode=returncode,
            started_at=handle.started_at,
            ended_at=None if returncode is None else time.time(),
            stdout_path=handle.stdout_path,
            stderr_path=handle.stderr_path,
        )

    def wait(self, handle: ProcessHandle) -> ProcessSnapshot:
        proc = self._processes.get(handle.pid)
        if proc is None:
            return ProcessSnapshot(
                state="missing",
                pid=handle.pid,
                started_at=handle.started_at,
                stdout_path=handle.stdout_path,
                stderr_path=handle.stderr_path,
                reason="process_not_tracked",
            )
        try:
            returncode = proc.wait(timeout=max(handle.timeout_seconds, 0))
        except subprocess.TimeoutExpired:
            self.cancel(handle)
            return ProcessSnapshot(
                state="timed_out",
                pid=handle.pid,
                returncode=None,
                started_at=handle.started_at,
                ended_at=time.time(),
                stdout_path=handle.stdout_path,
                stderr_path=handle.stderr_path,
                reason="timeout",
            )
        finally:
            self._processes.pop(handle.pid, None)
        return ProcessSnapshot(
            state="exited",
            pid=handle.pid,
            returncode=returncode,
            started_at=handle.started_at,
            ended_at=time.time(),
            stdout_path=handle.stdout_path,
            stderr_path=handle.stderr_path,
        )

    def cancel(self, handle: ProcessHandle) -> None:
        try:
            os.killpg(handle.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
```

- [ ] **Step 4: Expand adapter base contract**

Modify `skills/agent-runway/scripts/agentrunway/adapters/base.py` to include lifecycle methods:

```python
class RuntimeAdapter:
    capabilities: AdapterCapabilities

    def prepare(self, spec: WorkerSpec) -> WorkerHandle:
        raise NotImplementedError

    def start(self, handle: WorkerHandle) -> WorkerHandle:
        raise NotImplementedError

    def poll(self, handle: WorkerHandle) -> ProcessSnapshot:
        raise NotImplementedError

    def collect(self, handle: WorkerHandle) -> WorkerResultEnvelope:
        raise NotImplementedError

    def cancel(self, handle: WorkerHandle) -> None:
        raise NotImplementedError

    def reattach(self, handle: WorkerHandle) -> WorkerHandle | None:
        return None

    def run(self, packet_path: Path, workdir: Path) -> WorkerResult:
        raise NotImplementedError
```

Add imports for `WorkerSpec`, `ProcessSnapshot`, and `WorkerResultEnvelope` from `agentrunway.models`.

- [ ] **Step 5: Run process tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_process_supervisor.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Run adapter smoke tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_process_adapters.py evals/test_adapters.py -v
```

Expected: existing command-builder and local adapter tests still pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/adapters/base.py \
  skills/agent-runway/scripts/agentrunway/adapters/process.py \
  skills/agent-runway/evals/test_process_supervisor.py
git commit -m "feat: add AgentRunway process supervisor"
```

---

## Task 3: Codex and Claude Production Adapters

```yaml agentrunway-task
task_id: task_003
title: Codex and Claude production adapters
risk: high
phase: implementation
dependencies: [task_001, task_002]
spec_refs: [S6, S15, S16]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/adapters/codex.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/adapters/claude.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/adapters/process.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_process_adapters.py, mode: owned}
  - {path: skills/agent-runway/evals/test_production_adapters_fake_cli.py, mode: owned}
  - {path: skills/agent-runway/evals/fixtures/fake-bin/codex, mode: owned}
  - {path: skills/agent-runway/evals/fixtures/fake-bin/claude, mode: owned}
acceptance_commands:
  - python -m pytest evals/test_process_adapters.py evals/test_production_adapters_fake_cli.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: false
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/adapters/codex.py`
- Modify: `skills/agent-runway/scripts/agentrunway/adapters/claude.py`
- Modify: `skills/agent-runway/evals/test_process_adapters.py`
- Create: `skills/agent-runway/evals/test_production_adapters_fake_cli.py`
- Create: `skills/agent-runway/evals/fixtures/fake-bin/codex`
- Create: `skills/agent-runway/evals/fixtures/fake-bin/claude`

- [ ] **Step 1: Create deterministic fake CLIs**

Create `skills/agent-runway/evals/fixtures/fake-bin/codex`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    output = Path(os.environ["AGENTRUNWAY_WORKER_OUTPUT"])
    target = Path(os.environ.get("AGENTRUNWAY_FAKE_TARGET", "src/codex_worker.py"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 'codex'\n", encoding="utf-8")
    subprocess.run(["git", "add", str(target)], check=True)
    subprocess.run(["git", "commit", "-m", "fake codex worker"], check=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
    payload = {
        "schema": "agentrunway.worker_result.v1",
        "worker_id": os.environ["AGENTRUNWAY_WORKER_ID"],
        "task_id": os.environ["AGENTRUNWAY_TASK_ID"],
        "role": os.environ.get("AGENTRUNWAY_WORKER_ROLE", "implementer"),
        "status": "success",
        "changed_files": [str(target)],
        "commit": commit,
        "commits": [commit],
        "summary": "fake codex success",
        "commands_run": [],
        "method_audit": {"superpowers_used": True, "tdd_red": "failed", "tdd_green": "passed"},
        "residual_risks": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print("fake codex wrote result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `skills/agent-runway/evals/fixtures/fake-bin/claude` with the same structure but default target `src/claude_worker.py`, file content `VALUE = 'claude'\n`, commit message `fake claude worker`, and summary `fake claude success`.

Make both executable:

```bash
chmod +x skills/agent-runway/evals/fixtures/fake-bin/codex
chmod +x skills/agent-runway/evals/fixtures/fake-bin/claude
```

- [ ] **Step 2: Write failing production adapter tests**

Create `skills/agent-runway/evals/test_production_adapters_fake_cli.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agentrunway.adapters.claude import ClaudeAdapter
from agentrunway.adapters.codex import CodexAdapter
from agentrunway.models import WorkerSpec


ROOT = Path(__file__).resolve().parents[1]
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "agentrunway@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "AgentRunway Test"], cwd=path, check=True)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)


def _spec(tmp_path: Path, runtime: str) -> WorkerSpec:
    artifact_dir = tmp_path / "artifacts" / runtime
    prompt = artifact_dir / "prompt.txt"
    packet = artifact_dir / "packet.json"
    output = artifact_dir / "worker_result.json"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prompt.write_text("Run fake worker and write AGENTRUNWAY_WORKER_OUTPUT.\n", encoding="utf-8")
    packet.write_text("{}", encoding="utf-8")
    return WorkerSpec(
        run_id="run-1",
        task_id="task_001",
        worker_id=f"task_001-{runtime}-001",
        role="implementer",
        runtime=runtime,
        model="test-model",
        reasoning_effort="high",
        prompt_path=str(prompt),
        packet_path=str(packet),
        output_path=str(output),
        worktree_path=str(tmp_path),
        artifact_dir=str(artifact_dir),
        timeout_seconds=10,
        attempt=1,
    )


def test_codex_adapter_runs_fake_cli_and_collects_worker_result(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ['PATH']}")
    adapter = CodexAdapter(model="test-model", reasoning_effort="high")
    handle = adapter.start(adapter.prepare(_spec(tmp_path, "codex")))
    envelope = adapter.collect(handle)

    assert envelope.process.state == "exited"
    assert envelope.result_json is not None
    assert envelope.result_json["summary"] == "fake codex success"
    assert (tmp_path / "src" / "codex_worker.py").exists()


def test_claude_adapter_runs_fake_cli_and_collects_worker_result(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ['PATH']}")
    adapter = ClaudeAdapter(model="test-model", reasoning_effort="high")
    handle = adapter.start(adapter.prepare(_spec(tmp_path, "claude")))
    envelope = adapter.collect(handle)

    assert envelope.process.state == "exited"
    assert envelope.result_json is not None
    assert envelope.result_json["summary"] == "fake claude success"
    assert (tmp_path / "src" / "claude_worker.py").exists()
```

- [ ] **Step 3: Run failing adapter tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_production_adapters_fake_cli.py -v
```

Expected: fail because `prepare`, `start`, and `collect` are not implemented in Codex/Claude adapters.

- [ ] **Step 4: Implement Codex lifecycle adapter**

Modify `skills/agent-runway/scripts/agentrunway/adapters/codex.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from ..models import WorkerResultEnvelope, WorkerSpec
from .base import AdapterCapabilities, WorkerHandle
from .process import ProcessHandle, ProcessLaunchSpec, ProcessSupervisor


class CodexAdapter:
    capabilities = AdapterCapabilities(runtime="codex", supports_reattach=False)

    def __init__(self, model: str = "gpt-5.5", reasoning_effort: str = "xhigh"):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.supervisor = ProcessSupervisor()

    def build_command(self, prompt_text: str, workdir: Path) -> list[str]:
        # Flags verified against `codex exec --help` (Codex CLI, 2026-05):
        #   -m, --model <MODEL>                       -> --model
        #   -C, --cd <DIR>                            -> we do NOT pass this; the
        #                                                ProcessSupervisor already runs
        #                                                the child with cwd=worktree.
        #   reasoning effort: NO --reasoning-effort flag exists; use the generic
        #   `-c key=value` config override that codex documents in --help.
        #   [PROMPT]: positional TEXT, not a path. Passing the prompt file path
        #   here would make codex treat the literal string `/.../prompt.txt` as
        #   the user instructions.
        return [
            "codex",
            "exec",
            "--model",
            self.model,
            "-c",
            f'model_reasoning_effort="{self.reasoning_effort}"',
            prompt_text,
        ]

    def prepare(self, spec: WorkerSpec) -> WorkerHandle:
        artifact_dir = Path(spec.artifact_dir)
        stdout_path = artifact_dir / f"{spec.worker_id}.stdout.log"
        stderr_path = artifact_dir / f"{spec.worker_id}.stderr.log"
        # `build_command` consumes the prompt TEXT, not the path. Read the
        # materialized prompt file once at prepare time; ProcessSupervisor's
        # cwd= already pins the child to the worker worktree.
        prompt_text = Path(spec.prompt_path).read_text(encoding="utf-8")
        launch = ProcessLaunchSpec(
            worker_id=spec.worker_id,
            command=self.build_command(prompt_text, Path(spec.worktree_path)),
            cwd=Path(spec.worktree_path),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=spec.timeout_seconds,
            env={
                "AGENTRUNWAY_RUN_ID": spec.run_id,
                "AGENTRUNWAY_TASK_ID": spec.task_id,
                "AGENTRUNWAY_WORKER_ID": spec.worker_id,
                "AGENTRUNWAY_WORKER_ROLE": spec.role,
                "AGENTRUNWAY_PACKET_PATH": spec.packet_path,
                "AGENTRUNWAY_WORKER_OUTPUT": spec.output_path,
            },
        )
        return WorkerHandle(
            worker_id=spec.worker_id,
            task_id=spec.task_id,
            role=spec.role,
            pid=None,
            metadata={"spec": spec.__dict__, "launch": launch.__dict__},
        )

    def start(self, handle: WorkerHandle) -> WorkerHandle:
        launch_data = dict(handle.metadata["launch"])
        launch = ProcessLaunchSpec(
            worker_id=str(launch_data["worker_id"]),
            command=list(launch_data["command"]),
            cwd=Path(str(launch_data["cwd"])),
            stdout_path=Path(str(launch_data["stdout_path"])),
            stderr_path=Path(str(launch_data["stderr_path"])),
            timeout_seconds=int(launch_data["timeout_seconds"]),
            env=dict(launch_data["env"]),
        )
        process = self.supervisor.start(launch)
        metadata = dict(handle.metadata)
        metadata["process"] = process.__dict__
        return WorkerHandle(handle.worker_id, handle.task_id, handle.role, process.pid, metadata)

    def collect(self, handle: WorkerHandle) -> WorkerResultEnvelope:
        process_data = dict(handle.metadata["process"])
        process = ProcessHandle(**process_data)
        snapshot = self.supervisor.wait(process)
        spec = dict(handle.metadata["spec"])
        output_path = Path(str(spec["output_path"]))
        result_json = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else None
        return WorkerResultEnvelope(
            worker_id=handle.worker_id,
            task_id=handle.task_id,
            role=handle.role,
            runtime="codex",
            process=snapshot,
            result_path=str(output_path),
            result_json=result_json,
            stdout_path=str(process.stdout_path),
            stderr_path=str(process.stderr_path),
            error=None if result_json is not None else "missing_worker_result",
        )
```

- [ ] **Step 5: Implement Claude lifecycle adapter**

Modify `skills/agent-runway/scripts/agentrunway/adapters/claude.py` with the same lifecycle structure (read the prompt file in `prepare` and pass the text to `build_command`), runtime `"claude"`, and this command builder:

```python
    def build_command(self, prompt_text: str, workdir: Path) -> list[str]:
        # Flags verified against `claude --help` (Claude Code CLI, 2026-05):
        #   -p, --print            -> headless mode (required).
        #   --model <model>        -> long form is the documented one.
        #   --effort <level>       -> reasoning effort knob (low/medium/high/xhigh/max).
        #   No --cwd flag exists; the ProcessSupervisor's cwd= already pins the
        #   child to the worker worktree. `--add-dir` could be added here later
        #   if the adapter needs to expose extra read scope.
        #   The positional `prompt` argument is TEXT, not a path.
        return [
            "claude",
            "-p",
            prompt_text,
            "--model",
            self.model,
            "--effort",
            self.reasoning_effort,
        ]
```

Set `capabilities = AdapterCapabilities(runtime="claude", supports_reattach=True)`.

Both adapters MUST be re-verified against the locally installed CLI's `--help` at
implementation time. Codex/Claude flag surfaces drift between releases; the snapshots
above were captured on 2026-05-20 and are correct as of that date but are not a contract.

- [ ] **Step 6: Run adapter tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_process_adapters.py evals/test_production_adapters_fake_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/adapters/codex.py \
  skills/agent-runway/scripts/agentrunway/adapters/claude.py \
  skills/agent-runway/evals/test_process_adapters.py \
  skills/agent-runway/evals/test_production_adapters_fake_cli.py \
  skills/agent-runway/evals/fixtures/fake-bin/codex \
  skills/agent-runway/evals/fixtures/fake-bin/claude
git commit -m "feat: run Codex and Claude worker adapters"
```

---

## Task 4: Worker Worktrees, Commit Discovery, and Diff Scope

```yaml agentrunway-task
task_id: task_004
title: Worker worktrees and diff validation
risk: high
phase: implementation
dependencies: [task_001]
spec_refs: [S7, S8, S16]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/worktrees.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/git_ops.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/file_claims.py, mode: owned}
  - {path: skills/agent-runway/evals/test_worker_worktrees.py, mode: owned}
acceptance_commands:
  - python -m pytest evals/test_worker_worktrees.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: false
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/worktrees.py`
- Modify: `skills/agent-runway/scripts/agentrunway/git_ops.py`
- Modify: `skills/agent-runway/scripts/agentrunway/file_claims.py`
- Create: `skills/agent-runway/evals/test_worker_worktrees.py`

- [ ] **Step 1: Write failing worker worktree tests**

Create `skills/agent-runway/evals/test_worker_worktrees.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentrunway.file_claims import DiffScopeError, validate_changed_files
from agentrunway.git_ops import Git, changed_files_between, commits_between
from agentrunway.worktrees import create_worker_worktree


def _commit(repo: Path, path: str, text: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", path], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True, text=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_create_worker_worktree_from_main_branch(git_repo: Path, tmp_path: Path) -> None:
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True).stdout.strip()
    main = tmp_path / "main"
    Git(git_repo).run("worktree", "add", "-b", "agentrunway/run-1/main", str(main), base)

    worker = create_worker_worktree(
        Git(git_repo),
        target=tmp_path / "worker",
        branch="agentrunway/run-1/task_001-implementer-001",
        base_ref="agentrunway/run-1/main",
    )

    assert worker.exists()
    assert (worker / ".git").exists()


def test_commits_and_changed_files_between_refs(git_repo: Path) -> None:
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True).stdout.strip()
    commit = _commit(git_repo, "src/a.py", "A = 1\n", "add a")

    assert commits_between(Git(git_repo), base, "HEAD") == (commit,)
    assert changed_files_between(Git(git_repo), base, "HEAD") == ("src/a.py",)


def test_validate_changed_files_rejects_out_of_scope() -> None:
    validate_changed_files(("src/a.py",), ("src/*.py",))
    with pytest.raises(DiffScopeError, match="outside allowed write scope"):
        validate_changed_files(("README.md",), ("src/*.py",))
```

- [ ] **Step 2: Run failing worktree tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_worker_worktrees.py -v
```

Expected: fail because helper functions and `DiffScopeError` do not exist.

- [ ] **Step 3: Add git helpers**

Modify `skills/agent-runway/scripts/agentrunway/git_ops.py`:

```python
def commits_between(git: Git, base_ref: str, head_ref: str) -> tuple[str, ...]:
    result = git.run("rev-list", "--reverse", f"{base_ref}..{head_ref}")
    return tuple(line for line in result.stdout.splitlines() if line)


def changed_files_between(git: Git, base_ref: str, head_ref: str) -> tuple[str, ...]:
    result = git.run("diff", "--name-only", f"{base_ref}..{head_ref}")
    return tuple(line for line in result.stdout.splitlines() if line)


def branch_head(git: Git, branch: str) -> str:
    return git.rev_parse(branch)


def abort_cherry_pick(git: Git) -> None:
    git.run("cherry-pick", "--abort", check=False)
```

- [ ] **Step 4: Add worker worktree helper**

Modify `skills/agent-runway/scripts/agentrunway/worktrees.py`:

```python
def create_worker_worktree(git: Git, target: Path, branch: str, base_ref: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(git.root, branch):
        raise RuntimeError(f"branch already exists: {branch}")
    git.run("worktree", "add", "-b", branch, str(target), base_ref)
    return target
```

- [ ] **Step 5: Add diff scope validator**

Modify `skills/agent-runway/scripts/agentrunway/file_claims.py`:

```python
import fnmatch


class DiffScopeError(ValueError):
    pass


def validate_changed_files(changed_files: tuple[str, ...], allowed_globs: tuple[str, ...]) -> None:
    for path in changed_files:
        if not any(fnmatch.fnmatch(path, pattern) for pattern in allowed_globs):
            raise DiffScopeError(f"{path} is outside allowed write scope")
```

- [ ] **Step 6: Run worktree tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_worker_worktrees.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Run existing safety/worktree tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_worktrees.py evals/test_safety_policies.py evals/test_scheduler.py -v
```

Expected: existing tests still pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/worktrees.py \
  skills/agent-runway/scripts/agentrunway/git_ops.py \
  skills/agent-runway/scripts/agentrunway/file_claims.py \
  skills/agent-runway/evals/test_worker_worktrees.py
git commit -m "feat: add worker worktree diff validation"
```

---

## Task 5: Production Implementer State Machine

```yaml agentrunway-task
task_id: task_005
title: Production implementer state machine
risk: high
phase: implementation
dependencies: [task_001, task_002, task_003, task_004]
spec_refs: [S5, S7, S8, S15, S16]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/supervisor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/packetizer.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: owned}
acceptance_commands:
  - python -m pytest evals/test_runner_production_e2e.py::test_codex_fake_implementer_reaches_validated_candidate -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/supervisor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/packetizer.py`
- Create: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Write failing Codex implementer E2E test**

Create `skills/agent-runway/evals/test_runner_production_e2e.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def _write_plan(repo: Path, path: str = "src/codex_worker.py") -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd worker file.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        f"  - {{path: {path}, mode: owned}}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add worker file.\n",
        encoding="utf-8",
    )
    return plan, spec


def test_codex_fake_implementer_reaches_validated_candidate(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo)
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--adapter",
            "codex",
            "--skip-review",
            "--skip-verify",
        ],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "finished"
    assert payload["main_worktree"]
    main = Path(payload["main_worktree"])
    assert (main / "src" / "codex_worker.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"
```

- [ ] **Step 2: Run failing E2E test**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_runner_production_e2e.py::test_codex_fake_implementer_reaches_validated_candidate -v
```

Expected: fail because `--adapter codex` still falls back to local adapter and `--skip-review`/`--skip-verify` do not exist.

- [ ] **Step 3: Add role output paths to prompt materialization**

Modify `skills/agent-runway/scripts/agentrunway/packetizer.py` so worker prompts name the packet and output path. Add:

```python
def materialize_worker_prompt(packet: TaskPacket, packet_path: Path, output_path: Path, prompt_dir: Path) -> Path:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / f"{packet.task_id}.{packet.role}.prompt.txt"
    path.write_text(
        "You are a AgentRunway worker. Read the task packet and produce exactly the requested JSON artifact.\n"
        f"Packet path: {packet_path}\n"
        f"Output path: {output_path}\n"
        "Use using-superpowers. Code-changing implementers must use test-driven-development.\n"
        "Commit your changes before writing the result artifact.\n",
        encoding="utf-8",
    )
    return path
```

- [ ] **Step 4: Add supervisor implementer helper**

Create `skills/agent-runway/scripts/agentrunway/supervisor.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .adapters.base import RuntimeAdapter
from .db import AgentRunwayDb
from .file_claims import validate_changed_files
from .git_ops import Git, changed_files_between, commits_between
from .models import TaskSpec, WorkerSpec
from .result_validation import validate_worker_result
from .worktrees import create_worker_worktree


def _allowed_globs(task: TaskSpec) -> tuple[str, ...]:
    return tuple(claim.path for claim in task.file_claims if claim.mode in {"owned", "shared_append"})


def run_implementer_attempt(
    *,
    db: AgentRunwayDb,
    run_id: str,
    git: Git,
    main_worktree: Path,
    worktree_root: Path,
    run_dir: Path,
    task: TaskSpec,
    packet_path: Path,
    prompt_path: Path,
    adapter: RuntimeAdapter,
    runtime: str,
    model: str,
    reasoning_effort: str,
    attempt: int,
    timeout_seconds: int,
) -> int:
    worker_id = f"{task.task_id}-implementer-{attempt:03d}"
    branch = f"agentrunway/{run_id}/{worker_id}"
    worker_tree = create_worker_worktree(git, worktree_root / "workers" / worker_id, branch, f"agentrunway/{run_id}/main")
    artifact_dir = run_dir / "artifacts" / task.task_id / worker_id
    output_path = artifact_dir / "worker_result.json"
    spec = WorkerSpec(
        run_id=run_id,
        task_id=task.task_id,
        worker_id=worker_id,
        role="implementer",
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_path=str(prompt_path),
        packet_path=str(packet_path),
        output_path=str(output_path),
        worktree_path=str(worker_tree),
        artifact_dir=str(artifact_dir),
        timeout_seconds=timeout_seconds,
        attempt=attempt,
    )
    db.create_worker_attempt(
        worker_id=worker_id,
        task_id=task.task_id,
        role="implementer",
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        attempt=attempt,
        worktree_path=str(worker_tree),
        branch=branch,
        state="worktree_created",
        handle_json={},
    )
    handle = adapter.start(adapter.prepare(spec))
    db.set_worker_state(worker_id, "running")
    db.update_worker_handle(worker_id, handle.to_json())
    envelope = adapter.collect(handle)
    db.set_worker_state(worker_id, "result_collected")
    if envelope.result_json is None:
        db.set_worker_state(worker_id, "malformed_result")
        raise RuntimeError(envelope.error or "missing_worker_result")
    validate_worker_result(envelope.result_json)
    base = main_worktree.name if False else f"agentrunway/{run_id}/main"
    commits = commits_between(Git(worker_tree), base, "HEAD")
    changed_files = changed_files_between(Git(worker_tree), base, "HEAD")
    validate_changed_files(changed_files, _allowed_globs(task))
    db.set_worker_state(worker_id, "validated")
    candidate_id = db.enqueue_merge_candidate(
        task_id=task.task_id,
        worker_id=worker_id,
        commits=commits,
        changed_files=changed_files,
        status="merge_ready",
    )
    (artifact_dir / "worker_result.json").write_text(json.dumps(envelope.result_json, indent=2, sort_keys=True), encoding="utf-8")
    (artifact_dir / "envelope.json").write_text(json.dumps(asdict(envelope), indent=2, sort_keys=True), encoding="utf-8")
    return candidate_id
```

During implementation, replace the `base = main_worktree.name if False else ...` line with the explicit base ref string `f"agentrunway/{run_id}/main"`; it is shown here as an obvious marker for the intended ref, not as final code.

- [ ] **Step 5: Wire runner adapter selection and skip flags**

Modify `skills/agent-runway/scripts/agentrunway/invocation.py` run args:

```python
run.add_argument("--skip-review", action="store_true")
run.add_argument("--skip-verify", action="store_true")
```

Modify `skills/agent-runway/scripts/agentrunway/runner.py`:

- import `CodexAdapter`, `ClaudeAdapter`, and `run_implementer_attempt`;
- replace the current non-local adapter fallback with explicit adapter selection:

```python
def _select_adapter(name: str, profile: ModelProfile) -> tuple[Any, str, str, str]:
    model = profile.workers.get("default", profile.orchestrator)
    if name == "local":
        return LocalAdapter(fake_success=False), "local", "local", "n/a"
    if name == "codex":
        return CodexAdapter(model=model.model, reasoning_effort=model.reasoning_effort_resolved or model.reasoning_effort), "codex", model.model, model.reasoning_effort_resolved or model.reasoning_effort
    if name == "claude":
        return ClaudeAdapter(model=model.model, reasoning_effort=model.reasoning_effort_resolved or model.reasoning_effort), "claude", model.model, model.reasoning_effort_resolved or model.reasoning_effort
    raise ValueError(f"unsupported adapter: {name}")
```

- for non-local adapters, call `run_implementer_attempt`;
- for `--skip-review --skip-verify`, set candidate status to `merge_ready` and apply it in Task 7.

- [ ] **Step 6: Run E2E test**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_runner_production_e2e.py::test_codex_fake_implementer_reaches_validated_candidate -v
```

Expected: this test may still fail until Task 7 applies merge candidates. If so, adjust this task's assertion to inspect `state.sqlite` merge candidate status, and leave the main-worktree file assertion for Task 7.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/supervisor.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/scripts/agentrunway/invocation.py \
  skills/agent-runway/scripts/agentrunway/packetizer.py \
  skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: dispatch production implementer attempts"
```

---

## Task 6: Review and Verification Gates

```yaml agentrunway-task
task_id: task_006
title: Review and verification gates
risk: high
phase: implementation
dependencies: [task_001, task_002, task_003, task_004, task_005]
spec_refs: [S9, S10, S15, S16]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/supervisor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/result_validation.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/packetizer.py, mode: owned}
  - {path: skills/agent-runway/evals/test_result_validation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - python -m pytest evals/test_result_validation.py evals/test_runner_production_e2e.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/supervisor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/result_validation.py`
- Modify: `skills/agent-runway/scripts/agentrunway/packetizer.py`
- Modify: `skills/agent-runway/evals/test_result_validation.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add failing review/verification validation tests**

Append to `skills/agent-runway/evals/test_result_validation.py`:

```python
from agentrunway.result_validation import validate_review_result, validate_verification_result


def test_review_result_rejects_approved_with_findings() -> None:
    payload = {
        "schema": "agentrunway.review_result.v1",
        "worker_id": "reviewer-1",
        "task_id": "task_001",
        "reviewed_worker_id": "implementer-1",
        "status": "approved",
        "checks": [],
        "findings": [{"severity": "medium", "body": "issue"}],
        "method_audit": {"superpowers_used": True},
    }
    with pytest.raises(ResultValidationError, match="approved review cannot include findings"):
        validate_review_result(payload)


def test_verification_result_requires_passed_failed_or_blocked() -> None:
    payload = {
        "schema": "agentrunway.verification_result.v1",
        "worker_id": "verifier-1",
        "task_id": "task_001",
        "status": "passed",
        "checks": [{"command": "pytest", "status": "passed"}],
        "method_audit": {"superpowers_used": True},
    }
    assert validate_verification_result(payload)["status"] == "passed"
```

- [ ] **Step 2: Run failing validation tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_result_validation.py -v
```

Expected: fail because review/verification validators do not exist.

- [ ] **Step 3: Implement review/verification validators**

Modify `skills/agent-runway/scripts/agentrunway/result_validation.py`:

```python
def validate_review_result(payload: dict[str, object]) -> dict[str, object]:
    required = {"schema", "worker_id", "task_id", "reviewed_worker_id", "status", "checks", "findings", "method_audit"}
    missing = required - set(payload)
    if missing:
        raise ResultValidationError("missing review result fields: " + ", ".join(sorted(missing)))
    if payload["schema"] != "agentrunway.review_result.v1":
        raise ResultValidationError("invalid review result schema")
    if payload["status"] not in {"approved", "changes_requested", "rejected"}:
        raise ResultValidationError("invalid review status")
    findings = payload.get("findings")
    if payload["status"] == "approved" and isinstance(findings, list) and findings:
        raise ResultValidationError("approved review cannot include findings")
    return payload


def validate_verification_result(payload: dict[str, object]) -> dict[str, object]:
    required = {"schema", "worker_id", "task_id", "status", "checks", "method_audit"}
    missing = required - set(payload)
    if missing:
        raise ResultValidationError("missing verification result fields: " + ", ".join(sorted(missing)))
    if payload["schema"] != "agentrunway.verification_result.v1":
        raise ResultValidationError("invalid verification result schema")
    if payload["status"] not in {"passed", "failed", "blocked"}:
        raise ResultValidationError("invalid verification status")
    return payload
```

- [ ] **Step 4: Add supervisor gate helpers**

Modify `skills/agent-runway/scripts/agentrunway/supervisor.py` with helpers that create reviewer/verifier `WorkerSpec`, launch adapters, collect output, and validate with `validate_review_result` / `validate_verification_result`:

```python
def gate_review_result(review_json: dict[str, object]) -> str:
    result = validate_review_result(review_json)
    return str(result["status"])


def gate_verification_result(verification_json: dict[str, object]) -> str:
    result = validate_verification_result(verification_json)
    return str(result["status"])
```

Then call these helpers before marking a candidate `merge_ready`. For this task, fake CLI tests can set `--skip-review` and `--skip-verify`; add separate unit tests for gate behavior first, then wire full E2E in Task 7.

- [ ] **Step 5: Run gate tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_result_validation.py -v
```

Expected: all result validation tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/supervisor.py \
  skills/agent-runway/scripts/agentrunway/result_validation.py \
  skills/agent-runway/scripts/agentrunway/packetizer.py \
  skills/agent-runway/evals/test_result_validation.py \
  skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: validate AgentRunway review and verification gates"
```

---

## Task 7: Merge Queue Application and Conflict Retry

```yaml agentrunway-task
task_id: task_007
title: Merge queue application and conflict retry
risk: high
phase: implementation
dependencies: [task_001, task_004, task_005, task_006]
spec_refs: [S8, S16]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/merge_queue.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/git_ops.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_events_merge_queue.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - python -m pytest evals/test_events_merge_queue.py evals/test_runner_production_e2e.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/merge_queue.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/git_ops.py`
- Modify: `skills/agent-runway/evals/test_events_merge_queue.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add failing merge application test**

Append to `skills/agent-runway/evals/test_events_merge_queue.py`:

```python
def test_apply_candidate_cherry_picks_all_commits(git_repo: Path) -> None:
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git", "checkout", "-b", "worker"], cwd=git_repo, check=True)
    (git_repo / "src").mkdir(exist_ok=True)
    (git_repo / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/a.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "worker"], cwd=git_repo, check=True, capture_output=True, text=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git", "checkout", "-B", "main", base], cwd=git_repo, check=True)

    candidate = MergeCandidate("task_001", "worker-1", (commit,), ("src/a.py",))
    apply_candidate(Git(git_repo), candidate)

    assert (git_repo / "src" / "a.py").read_text(encoding="utf-8") == "A = 1\n"
```

Ensure imports at the top include:

```python
import subprocess
from pathlib import Path
from agentrunway.git_ops import Git
from agentrunway.merge_queue import MergeCandidate, apply_candidate
```

- [ ] **Step 2: Run failing or existing merge tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_events_merge_queue.py -v
```

Expected: fail if imports or `apply_candidate` behavior are incomplete; pass if the primitive already handles the simple case.

- [ ] **Step 3: Implement conflict-safe candidate apply**

Modify `skills/agent-runway/scripts/agentrunway/merge_queue.py`:

```python
class MergeConflictError(RuntimeError):
    pass


def apply_candidate(git: Git, candidate: MergeCandidate) -> None:
    for commit in candidate.commits:
        result = git.run("cherry-pick", commit, check=False)
        if result.returncode != 0:
            git.run("cherry-pick", "--abort", check=False)
            raise MergeConflictError(result.stderr.strip() or result.stdout.strip() or "merge conflict")
```

- [ ] **Step 4: Wire runner to apply merge-ready candidates**

Modify `skills/agent-runway/scripts/agentrunway/runner.py` after production implementer attempts:

```python
for candidate in db.list_merge_candidates():
    if candidate["status"] != "merge_ready":
        continue
    main_git = Git(Path(run_json["main_worktree"]))
    merge_candidate = MergeCandidate(
        task_id=candidate["task_id"],
        worker_id=candidate["worker_id"],
        commits=tuple(candidate["commits"]),
        changed_files=tuple(candidate["changed_files"]),
    )
    try:
        apply_candidate(main_git, merge_candidate)
    except MergeConflictError as exc:
        db.set_merge_candidate_status(int(candidate["id"]), "merge_conflict", str(exc))
        db.set_task_status(candidate["task_id"], "blocked")
    else:
        db.set_merge_candidate_status(int(candidate["id"]), "merged")
        db.set_worker_state(candidate["worker_id"], "merged")
        db.set_task_status(candidate["task_id"], "merged")
```

Import `MergeCandidate`, `MergeConflictError`, and `apply_candidate`.

- [ ] **Step 5: Restore E2E main-worktree assertion**

In `skills/agent-runway/evals/test_runner_production_e2e.py`, assert that the fake Codex file exists in `payload["main_worktree"]` after the run.

- [ ] **Step 6: Run merge and E2E tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_events_merge_queue.py evals/test_runner_production_e2e.py -v
```

Expected: tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/merge_queue.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/scripts/agentrunway/git_ops.py \
  skills/agent-runway/evals/test_events_merge_queue.py \
  skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: apply AgentRunway merge candidates"
```

---

## Task 8: Watchdog, Runtime Semaphores, and Resume Reconciliation

```yaml agentrunway-task
task_id: task_008
title: Watchdog semaphores and resume reconciliation
risk: high
phase: implementation
dependencies: [task_001, task_002, task_005, task_007]
spec_refs: [S11, S12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/watchdog.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/resource_locks.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_status_watchdog_cost.py, mode: owned}
  - {path: skills/agent-runway/evals/test_resume_apply.py, mode: owned}
acceptance_commands:
  - python -m pytest evals/test_status_watchdog_cost.py evals/test_resume_apply.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/watchdog.py`
- Modify: `skills/agent-runway/scripts/agentrunway/resource_locks.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_status_watchdog_cost.py`
- Create: `skills/agent-runway/evals/test_resume_apply.py`

- [ ] **Step 1: Add watchdog classification tests**

Append to `skills/agent-runway/evals/test_status_watchdog_cost.py`:

```python
from agentrunway.models import ProcessSnapshot
from agentrunway.watchdog import classify_worker_snapshot


def test_watchdog_classifies_missing_result_after_successful_exit() -> None:
    snapshot = ProcessSnapshot(state="exited", pid=123, returncode=0, reason=None)
    assert classify_worker_snapshot(snapshot, result_exists=False) == "malformed_result"


def test_watchdog_classifies_nonzero_exit_as_adapter_crash() -> None:
    snapshot = ProcessSnapshot(state="exited", pid=123, returncode=2, reason=None)
    assert classify_worker_snapshot(snapshot, result_exists=False) == "adapter_crashed"
```

- [ ] **Step 2: Add resume idempotence test**

Create `skills/agent-runway/evals/test_resume_apply.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.runner import resume


def test_resume_missing_run_is_idempotent(isolated_home: Path) -> None:
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}
```

- [ ] **Step 3: Run failing watchdog/resume tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_status_watchdog_cost.py evals/test_resume_apply.py -v
```

Expected: fail because `classify_worker_snapshot` does not exist.

- [ ] **Step 4: Implement watchdog classification**

Modify `skills/agent-runway/scripts/agentrunway/watchdog.py`:

```python
from .models import ProcessSnapshot


def classify_worker_snapshot(snapshot: ProcessSnapshot, *, result_exists: bool) -> str:
    if snapshot.state == "timed_out":
        return "timeout"
    if snapshot.state == "missing":
        return "stalled"
    if snapshot.state == "exited" and snapshot.returncode not in {0, None}:
        return "adapter_crashed"
    if snapshot.state == "exited" and snapshot.returncode == 0 and not result_exists:
        return "malformed_result"
    if snapshot.state == "running":
        return "running"
    return "unknown"
```

- [ ] **Step 5: Add semaphore helper**

Modify `skills/agent-runway/scripts/agentrunway/resource_locks.py`:

```python
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def runtime_slot(lock_root: Path, runtime: str, holder: str):
    lock_root.mkdir(parents=True, exist_ok=True)
    path = lock_root / f"{runtime}.{holder}.slot"
    path.write_text(holder, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
```

Before entering the context, callers enforce configured capacity by counting
existing `*.slot` files for the runtime and refusing or retrying when the count
is at the configured limit.

- [ ] **Step 6: Expand resume reconciliation**

Modify `skills/agent-runway/scripts/agentrunway/runner.py` so `resume(run_id)`:

- loads `run.json`;
- returns missing for unknown runs;
- returns `resumed: False` for terminal `finished`/`cancelled`;
- for non-terminal runs, returns `resumed: True` and includes `run_dir`;
- does not create duplicate worker rows.

Use:

```python
def resume(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    terminal = data.get("status") in {"finished", "cancelled"}
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "run_dir": data.get("run_dir"),
        "resumed": not terminal,
    }
```

This preserves existing CLI behavior while making the idempotence contract explicit. Full live reattach uses the same return shape after adapter handle reconciliation is implemented.

- [ ] **Step 7: Run tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_status_watchdog_cost.py evals/test_resume_apply.py -v
```

Expected: tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/watchdog.py \
  skills/agent-runway/scripts/agentrunway/resource_locks.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_status_watchdog_cost.py \
  skills/agent-runway/evals/test_resume_apply.py
git commit -m "feat: add AgentRunway watchdog resume primitives"
```

---

## Task 9: Explicit Source Apply

```yaml agentrunway-task
task_id: task_009
title: Explicit source checkout apply
risk: high
phase: implementation
dependencies: [task_001, task_004, task_007, task_008]
spec_refs: [S13, S16]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/apply.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/invocation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_resume_apply.py, mode: owned}
acceptance_commands:
  - python -m pytest evals/test_resume_apply.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/apply.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Modify: `skills/agent-runway/evals/test_resume_apply.py`

- [ ] **Step 1: Add failing dirty-source apply test**

Append to `skills/agent-runway/evals/test_resume_apply.py`:

```python
import pytest

from agentrunway.apply import ApplyError, apply_commits_to_source


def test_apply_refuses_dirty_source(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ApplyError, match="dirty source checkout"):
        apply_commits_to_source(git_repo, ("abc123",), strategy="cherry-pick")
```

- [ ] **Step 2: Run failing apply test**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_resume_apply.py::test_apply_refuses_dirty_source -v
```

Expected: fail because `agentrunway.apply` does not exist.

- [ ] **Step 3: Implement apply helper**

Create `skills/agent-runway/scripts/agentrunway/apply.py`:

```python
from __future__ import annotations

from pathlib import Path

from .git_ops import Git, assert_clean_source


class ApplyError(RuntimeError):
    pass


def apply_commits_to_source(
    repo: Path,
    commits: tuple[str, ...],
    *,
    strategy: str = "cherry-pick",
    already_applied: tuple[str, ...] = (),
) -> list[str]:
    # Design §13 requires a second `agentrunway apply` to be idempotent.
    # Filter out commits already recorded in `applied_commits` BEFORE we
    # touch the repo so a re-run is a clean no-op (rather than an empty
    # cherry-pick that aborts mid-stream).
    try:
        assert_clean_source(repo)
    except Exception as exc:
        raise ApplyError(str(exc)) from exc
    git = Git(repo)
    applied: list[str] = []
    if strategy != "cherry-pick":
        raise ApplyError(f"unsupported apply strategy: {strategy}")
    skip = set(already_applied)
    for commit in commits:
        if commit in skip:
            continue
        result = git.run("cherry-pick", commit, check=False)
        if result.returncode != 0:
            git.run("cherry-pick", "--abort", check=False)
            raise ApplyError(result.stderr.strip() or result.stdout.strip() or "apply conflict")
        applied.append(commit)
    return applied
```

- [ ] **Step 4: Wire `agentrunway apply`**

Modify `skills/agent-runway/scripts/agentrunway/invocation.py` for the apply subparser:

```python
apply_parser = sub.add_parser("apply", help="apply a AgentRunway run")
apply_parser.add_argument("--run", required=True)
apply_parser.add_argument("--strategy", default="cherry-pick", choices=("cherry-pick",))
```

If current parser creates all run-id commands in a loop, split `apply` out so `--strategy` is available only for apply.

Modify `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
def apply(run_id: str, strategy: str = "cherry-pick") -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    db = AgentRunwayDb.open(Path(data["state_db"]))
    commits: list[str] = []
    for candidate in db.list_merge_candidates():
        if candidate["status"] == "merged":
            commits.extend(candidate["commits"])
    already_applied = tuple(row["commit_sha"] for row in db.list_applied_commits(run_id))
    applied = apply_commits_to_source(
        Path(data["repo_root"]),
        tuple(commits),
        strategy=strategy,
        already_applied=already_applied,
    )
    for commit in applied:
        db.record_applied_commit(run_id=run_id, commit_sha=commit, strategy=strategy)
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "applied": True,
        "commits": applied,
        "already_applied": list(already_applied),
    }
```

Import `apply_commits_to_source` and `AgentRunwayDb`.

- [ ] **Step 5: Run apply tests**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_resume_apply.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/apply.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/scripts/agentrunway/invocation.py \
  skills/agent-runway/evals/test_resume_apply.py
git commit -m "feat: implement explicit AgentRunway apply"
```

---

## Task 10: Observability, Documentation, and Full Eval Pass

```yaml agentrunway-task
task_id: task_010
title: Observability docs and full eval pass
risk: medium
phase: verification
dependencies: [task_001, task_002, task_003, task_004, task_005, task_006, task_007, task_008, task_009]
spec_refs: [S14, S15, S16, S17]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/events.py, mode: owned}
  - {path: skills/agent-runway/README.md, mode: owned}
  - {path: skills/agent-runway/references/runtime-adapters.md, mode: owned}
  - {path: skills/agent-runway/references/merge-queue.md, mode: owned}
  - {path: skills/agent-runway/references/watchdog.md, mode: owned}
  - {path: skills/agent-runway/evals/test_contract_docs.py, mode: owned}
  - {path: skills/agent-runway/evals/run.sh, mode: read_only}
acceptance_commands:
  - ./evals/run.sh
  - python evals/check_skill_contract.py
  - git diff --check
required_skills: [test-driven-development, verification-before-completion]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/events.py`
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/references/runtime-adapters.md`
- Modify: `skills/agent-runway/references/merge-queue.md`
- Modify: `skills/agent-runway/references/watchdog.md`
- Modify: `skills/agent-runway/evals/test_contract_docs.py`

- [ ] **Step 1: Add failing contract docs test terms**

Modify `skills/agent-runway/evals/test_contract_docs.py` so the required term set includes:

```python
required_terms = {
    "production supervisor",
    "process lifecycle",
    "worker_result.json",
    "review_result",
    "verification_result",
    "merge conflict",
    "agentrunway apply",
    "best-effort",
}
```

- [ ] **Step 2: Run failing docs contract test**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_contract_docs.py -v
```

Expected: fail until README/reference docs include the new production supervisor language.

- [ ] **Step 3: Update README**

Modify `skills/agent-runway/README.md`:

```markdown
## Production Supervisor

`agentrunway run --adapter codex` and `agentrunway run --adapter claude` launch real worker
processes through the production supervisor. The runner creates worker
worktrees, writes task packets and prompts, supervises process lifecycle,
collects `worker_result.json`, validates committed changed files against file
claims, runs review and verification gates, and cherry-picks accepted commits
into the run main worktree.

Use fake CLI fixtures for deterministic tests:

```bash
PATH="$PWD/evals/fixtures/fake-bin:$PATH" ./evals/run.sh
```

Use real Codex/Claude smoke runs only when the local CLIs are authenticated and
model usage is intended.

`agentrunway apply --run <run_id>` is explicit. It refuses a dirty source checkout by
default and records applied commits in SQLite.
```

- [ ] **Step 4: Update reference docs**

Modify `skills/agent-runway/references/runtime-adapters.md`:

```markdown
# Runtime Adapters

Adapters implement process lifecycle: prepare, start, poll, collect, cancel,
and reattach. Codex uses `codex exec` and is treated as non-reattachable.
Claude uses headless `claude -p` and may reattach when session metadata is
available. Both write stdout/stderr logs and return runner-validated
`worker_result.json` artifacts.
```

Modify `skills/agent-runway/references/merge-queue.md`:

```markdown
# Merge Queue

Candidates enter merge only after worker result validation, diff-scope checks,
review approval, and verification pass. The runner cherry-picks worker commits
into `agentrunway/<run_id>/main`. Merge conflict aborts the cherry-pick and allows one
fresh re-dispatch from the updated run main before blocking with
`recurring_merge_conflict`.
```

Modify `skills/agent-runway/references/watchdog.md`:

```markdown
# Watchdog

The watchdog is runner-driven polling. It considers process liveness,
wall-clock timeout, stdout/stderr mtime, output artifact presence, retry
budget, and adapter heartbeat when present. Actions move from observe to
cancel, retry, recovery worker, or blocked.
```

- [ ] **Step 5: Persist local event evidence**

Modify `skills/agent-runway/scripts/agentrunway/events.py`:

```python
def write_event_artifact(run_dir: Path, event_type: str, payload: dict[str, Any]) -> Path:
    event_dir = run_dir / "events"
    event_dir.mkdir(parents=True, exist_ok=True)
    safe_type = event_type.replace("/", "_").replace(" ", "_")
    path = event_dir / f"{safe_type}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True) + "\n")
    return path
```

Add `from pathlib import Path` and ensure `json` is imported.

- [ ] **Step 6: Run docs and full evals**

Run:

```bash
cd skills/agent-runway
python -m pytest evals/test_contract_docs.py -v
./evals/run.sh
python evals/check_skill_contract.py
git diff --check
```

Expected:

- docs contract passes,
- full eval runner passes,
- skill contract check exits 0,
- `git diff --check` exits 0.

- [ ] **Step 7: Run graphify after code changes**

Run from repo root:

```bash
cd /Users/kws/source/private/Archive
graphify update .
```

Expected: graphify rebuilds AST graph without API cost. If graphify updates tracked files, include them in the final commit.

- [ ] **Step 8: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/events.py \
  skills/agent-runway/README.md \
  skills/agent-runway/references/runtime-adapters.md \
  skills/agent-runway/references/merge-queue.md \
  skills/agent-runway/references/watchdog.md \
  skills/agent-runway/evals/test_contract_docs.py \
  graphify-out
git commit -m "docs: document AgentRunway production supervisor"
```

---

## Final Verification

Run from the repo root:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
cd skills/agent-runway
./evals/run.sh
python evals/check_skill_contract.py
git diff --check
cd /Users/kws/source/private/Archive
graphify update .
git status --short --branch --untracked-files=all
```

Expected:

- AgentRunway eval suite passes.
- Skill contract check exits 0.
- `git diff --check` exits 0.
- `graphify update .` completes.
- Final git status only includes intended committed changes or no changes.

## Execution Notes

- Keep `--adapter local --fake-success` working throughout so existing smoke
  tests remain deterministic.
- Fake Codex/Claude tests must not require network, model calls, or local CLI
  authentication.
- Real Codex/Claude smoke tests are opt-in and should not run in default
  `./evals/run.sh`.
- Do not modify source checkout by default during runner tests; all accepted
  task commits should land in `~/.agentrunway/worktrees/<workspace_id>/<run_id>/main`
  until `agentrunway apply` is explicitly invoked.
