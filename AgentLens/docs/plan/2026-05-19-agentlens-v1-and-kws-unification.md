# AgentLens v1 + kws-Skill Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship AgentLens v1 (container runs + opaque event API + claude-session import + TTY-aware shim + cmux auto-chain) and migrate kws-cme/kws-cpe orchestrators from their local logging stacks to AgentLens, eliminating duplicate transcript and event capture.

**Architecture:** AgentLens v0 today wraps `claude -p`/`codex` via a PATH shim, capturing transcript + lifecycle events. v1 introduces (1) **container runs** that carry orchestration events without a transcript, (2) **parent→child run linkage** via `AGENTLENS_PARENT_RUN_ID` env, (3) **opaque event types** (any `<namespace>.<event>` string with arbitrary JSON payload), (4) **session-JSONL import** for interactive Claude Code (which can't be wrapped due to TTY), and (5) **cmux app auto-detect** that backs up cmux's `claude` wrapper and chains it through AgentLens. kws skills add `agentlens run-open` at startup, `agentlens event append` at each phase/task transition, and `AGENTLENS_PARENT_RUN_ID=$ORCH` on every sub-spawn. Each skill's own `state.json` stays kws-local — AgentLens never owns mutable orchestration state.

**Tech Stack:** Python 3.12, Typer CLI, SQLite (derived index), JSONL (canonical event log), pytest, bash (shim + skill SKILL.md). The plan touches `AgentLens/src/agentlens/{cli.py,commands/,adapters/,store/}` and `~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md` and `~/.claude/skills/kws-codex-plan-executor/SKILL.md`.

---

## File Structure

### Files to create

| Path | Responsibility |
|------|----------------|
| `AgentLens/src/agentlens/commands/run_open.py` | `agentlens run-open` — create a container run, print `run_id` |
| `AgentLens/src/agentlens/commands/run_close.py` | `agentlens run-close` — mark container run ended_at |
| `AgentLens/src/agentlens/commands/event.py` | `agentlens event` Typer group with `append` and `query` |
| `AgentLens/src/agentlens/commands/events.py` | `agentlens events` top-level alias for `event query` |
| `AgentLens/src/agentlens/commands/import_claude_session.py` | `agentlens import claude-session` — ingest `~/.claude/projects/<enc>/<session-id>.jsonl` |
| `AgentLens/src/agentlens/store/event_query.py` | Pure functions: read events.jsonl, filter by type-glob/since, tree-merge across runs |
| `AgentLens/src/agentlens/store/claude_session.py` | Pure functions: locate session JSONL, parse Claude Code session format, derive AgentLens events |
| `AgentLens/tests/unit/test_event_query.py` | Unit: glob filter, since filter, tree merge ordering |
| `AgentLens/tests/unit/test_claude_session_parser.py` | Unit: session JSONL → AgentLens events mapping |
| `AgentLens/tests/integration/test_run_open_close.py` | Integration: container run create + event append + close |
| `AgentLens/tests/integration/test_parent_run_linkage.py` | Integration: env-var-driven parent_run_id propagation |
| `AgentLens/tests/integration/test_import_claude_session.py` | Integration: end-to-end session import idempotency |
| `AgentLens/tests/integration/test_cmux_chain.py` | Integration: cmux auto-detect + chained shim install |
| `AgentLens/tests/integration/test_shim_tty_passthrough.py` | Integration: shim TTY-detect for interactive claude |
| `AgentLens/tests/fixtures/claude_sessions/<id>.jsonl` | Fixture: synthetic Claude Code session JSONL for parser tests |

### Files to modify

| Path | Change |
|------|--------|
| `AgentLens/src/agentlens/cli.py` | Register `run-open`, `run-close`, `event` group, `events` alias, `import` group with `claude-session` |
| `AgentLens/src/agentlens/store/sqlite_index.py` | Add `has_transcript BOOLEAN DEFAULT 1` column; idempotent `ALTER TABLE` migration; new indexes |
| `AgentLens/src/agentlens/adapters/process.py` | Read `AGENTLENS_PARENT_RUN_ID` env, populate `parent_run_id` on capture run |
| `AgentLens/src/agentlens/adapters/shims.py` | Add TTY-detect pass-through guard for interactive `claude`; cmux app auto-chain install path |
| `AgentLens/src/agentlens/commands/install.py` | Detect `/Applications/cmux.app/`; backup + replace cmux's `claude`; record `~/.agentlens/cmux-install.json` |
| `AgentLens/src/agentlens/commands/doctor.py` | Check cmux app version/mtime drift; warn if backup missing |
| `~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md` | Add `agentlens run-open` in Phase -1 step b; `AGENTLENS_PARENT_RUN_ID` env on Phase -1 step d spawn; `agentlens event append` at every phase/task transition; dual-write window then delete `append_learning_event.py` |
| `~/.claude/skills/kws-codex-plan-executor/SKILL.md` | Symmetric to above with `kws-cpe.*` events; replace `append_run_event.py` calls |

### Files to delete (Phase 2/3 cutover only)

| Path | Reason |
|------|--------|
| `~/.claude/skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py` | Replaced by `agentlens event append` |
| `~/.claude/skills/kws-codex-plan-executor/scripts/append_run_event.py` | Replaced by `agentlens event append` |

---

# Phase 1 — AgentLens v1

### Task 1: Schema migration — add `has_transcript` column

**Files:**
- Modify: `AgentLens/src/agentlens/store/sqlite_index.py:38-50`
- Test: `AgentLens/tests/unit/test_sqlite_index.py`

- [ ] **Step 1: Write the failing test**

Append to `AgentLens/tests/unit/test_sqlite_index.py`:

```python
def test_init_schema_adds_has_transcript_column(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    # Create old-shape runs table (without has_transcript).
    conn.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, "
        "parent_run_id TEXT, started_at TEXT NOT NULL, ended_at TEXT, "
        "agent_name TEXT NOT NULL, agent_mode TEXT NOT NULL, "
        "recording_mode TEXT NOT NULL, agent_outcome TEXT, eval_status TEXT, "
        "sealed_phase TEXT)"
    )
    conn.commit()
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    assert "has_transcript" in cols


def test_init_schema_has_transcript_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    init_schema(conn)  # second call must not raise
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    assert "has_transcript" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_sqlite_index.py::test_init_schema_adds_has_transcript_column -v`
Expected: FAIL — "has_transcript" not in cols.

- [ ] **Step 3: Update `_SCHEMA_SQL` and add idempotent ALTER**

In `AgentLens/src/agentlens/store/sqlite_index.py`, modify the `CREATE TABLE runs (...)` block to include the column, and add a migration helper for existing DBs. Replace the `_SCHEMA_SQL` runs block with:

```python
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    parent_run_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    agent_name TEXT NOT NULL,
    agent_mode TEXT NOT NULL,
    recording_mode TEXT NOT NULL,
    agent_outcome TEXT,
    eval_status TEXT,
    sealed_phase TEXT,
    has_transcript INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_runs_workspace ON runs(workspace_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_eval_status ON runs(eval_status);
CREATE INDEX IF NOT EXISTS idx_runs_parent ON runs(parent_run_id);
... (rest unchanged) ...
"""


def _migrate_add_has_transcript(conn: sqlite3.Connection) -> None:
    """Add ``has_transcript`` to legacy DBs created before v1."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    if "has_transcript" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN has_transcript INTEGER NOT NULL DEFAULT 1")
        conn.commit()
```

Modify `init_schema(conn)`:

```python
def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    _migrate_add_has_transcript(conn)
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_sqlite_index.py -v`
Expected: PASS (all pre-existing + 2 new tests).

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/store/sqlite_index.py AgentLens/tests/unit/test_sqlite_index.py
git commit -m "feat(agentlens): add has_transcript column with idempotent migration"
```

---

### Task 2: `agentlens run-open` command — happy path

**Files:**
- Create: `AgentLens/src/agentlens/commands/run_open.py`
- Modify: `AgentLens/src/agentlens/cli.py`
- Test: `AgentLens/tests/integration/test_run_open_close.py`

- [ ] **Step 1: Write the failing test**

Create `AgentLens/tests/integration/test_run_open_close.py`:

```python
"""Integration tests for `agentlens run-open` / `run-close` (spec §4.2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agentlens.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_run_open_creates_container_run_and_prints_run_id(home: Path) -> None:
    res = _run_cli("run-open", "--agent", "kws-cme-orchestrator", "--workspace", str(home))
    assert res.returncode == 0, res.stderr
    run_id = res.stdout.strip()
    assert run_id.startswith("run_")
    # Locate the run dir under <home>/runs/<workspace_id>/<run_id>
    run_dirs = list((home / "runs").rglob(run_id))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    # meta.json present, events.jsonl empty, no transcript.jsonl
    assert (run_dir / "meta.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "events.jsonl").read_text() == ""
    assert not (run_dir / "transcript.jsonl").exists()
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["has_transcript"] is False
    assert meta["agent_name"] == "kws-cme-orchestrator"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_run_open_close.py::test_run_open_creates_container_run_and_prints_run_id -v`
Expected: FAIL — "No such command 'run-open'".

- [ ] **Step 3: Implement `run_open.py`**

Create `AgentLens/src/agentlens/commands/run_open.py`:

```python
"""``agentlens run-open`` — create a container run (no transcript).

Container runs carry orchestration events emitted by upstream skills
(e.g. kws-cme) but do not wrap a subprocess. They are linked as parents
of capture runs via ``AGENTLENS_PARENT_RUN_ID`` (spec §4.4).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer

from agentlens.ids import new_run_id, new_workspace_id
from agentlens.store.paths import agentlens_home
from agentlens.store.sqlite_index import index_run, init_db
from agentlens.time import now_iso


def run_open(
    agent: str = typer.Option(..., "--agent", help="Container agent identifier"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace root (defaults to cwd)"
    ),
    parent: Optional[str] = typer.Option(None, "--parent", help="Parent run_id"),
    meta: List[str] = typer.Option(
        [], "--meta", help="key=value meta entry (may be repeated)"
    ),
) -> None:
    workspace_path = (workspace or Path.cwd()).resolve()
    workspace_id = new_workspace_id(workspace_path)
    run_id = new_run_id()
    home = agentlens_home()
    run_dir = home / "runs" / workspace_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "events.jsonl").touch()

    meta_dict: dict = {}
    for entry in meta:
        if "=" not in entry:
            raise typer.BadParameter(f"--meta requires key=value, got: {entry}")
        key, _, value = entry.partition("=")
        meta_dict[key] = value

    meta_payload = {
        "run_id": run_id,
        "workspace_id": workspace_id,
        "agent_name": agent,
        "agent_mode": "container",
        "recording_mode": "events_only",
        "started_at": now_iso(),
        "ended_at": None,
        "parent_run_id": parent,
        "has_transcript": False,
        "meta": meta_dict,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta_payload, indent=2) + "\n")

    # Best-effort SQLite index (mirrors process wrapper §S1.6.17 invariant).
    try:
        conn = init_db(home)
        index_run(conn, run_dir)
        conn.close()
    except Exception as exc:
        typer.echo(f"agentlens: index update failed: {exc}", err=True)

    typer.echo(run_id)
```

- [ ] **Step 4: Wire into `cli.py`**

Add to `AgentLens/src/agentlens/cli.py` near the other imports and registrations:

```python
from .commands import run_open as run_open_cmd
...
app.command(name="run-open")(run_open_cmd.run_open)
```

- [ ] **Step 5: Update `index_run` to populate `has_transcript`**

In `AgentLens/src/agentlens/store/sqlite_index.py`, modify the `INSERT OR REPLACE INTO runs` SQL inside `index_run()` to include `has_transcript`. Read the value from `meta.json` (falling back to `True`):

```python
has_transcript = bool(meta.get("has_transcript", True))
conn.execute(
    "INSERT OR REPLACE INTO runs (run_id, workspace_id, parent_run_id, "
    "started_at, ended_at, agent_name, agent_mode, recording_mode, "
    "agent_outcome, eval_status, sealed_phase, has_transcript) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (run_id, workspace_id, parent_run_id, started_at, ended_at, agent_name,
     agent_mode, recording_mode, agent_outcome, eval_status, sealed_phase,
     int(has_transcript)),
)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_run_open_close.py::test_run_open_creates_container_run_and_prints_run_id -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/commands/run_open.py AgentLens/src/agentlens/cli.py \
        AgentLens/src/agentlens/store/sqlite_index.py \
        AgentLens/tests/integration/test_run_open_close.py
git commit -m "feat(agentlens): add run-open command for container runs"
```

---

### Task 3: `agentlens run-open` — `--parent` and `--meta` round-trip

**Files:**
- Modify: `AgentLens/tests/integration/test_run_open_close.py`

- [ ] **Step 1: Add failing test for parent + meta**

Append to `AgentLens/tests/integration/test_run_open_close.py`:

```python
def test_run_open_with_parent_and_meta(home: Path) -> None:
    parent = _run_cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    res = _run_cli(
        "run-open", "--agent", "kws-cme-orchestrator",
        "--parent", parent, "--meta", "plan=/p/plan.md", "--meta", "spec=/p/spec.md",
    )
    assert res.returncode == 0, res.stderr
    child_id = res.stdout.strip()
    child_dir = next((home / "runs").rglob(child_id))
    meta = json.loads((child_dir / "meta.json").read_text())
    assert meta["parent_run_id"] == parent
    assert meta["meta"]["plan"] == "/p/plan.md"
    assert meta["meta"]["spec"] == "/p/spec.md"
```

- [ ] **Step 2: Run to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_run_open_close.py -v`
Expected: PASS (implementation already handles these flags from Task 2).

- [ ] **Step 3: Commit**

```bash
git add AgentLens/tests/integration/test_run_open_close.py
git commit -m "test(agentlens): cover run-open --parent and --meta"
```

---

### Task 4: `agentlens run-close` command

**Files:**
- Create: `AgentLens/src/agentlens/commands/run_close.py`
- Modify: `AgentLens/src/agentlens/cli.py`
- Test: `AgentLens/tests/integration/test_run_open_close.py`

- [ ] **Step 1: Write failing test**

Append to `AgentLens/tests/integration/test_run_open_close.py`:

```python
def test_run_close_marks_ended_at(home: Path) -> None:
    run_id = _run_cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    res = _run_cli("run-close", "--run", run_id, "--exit-code", "0")
    assert res.returncode == 0, res.stderr
    run_dir = next((home / "runs").rglob(run_id))
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["ended_at"] is not None
    assert meta["agent_outcome"] == "completed"


def test_run_close_unknown_run_id_is_nonblocking(home: Path) -> None:
    res = _run_cli("run-close", "--run", "run_does_not_exist")
    # Per spec §8 non-blocking invariant: warning to stderr, exit 0.
    assert res.returncode == 0
    assert "not found" in res.stderr.lower() or "warning" in res.stderr.lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_run_open_close.py::test_run_close_marks_ended_at -v`
Expected: FAIL — "No such command 'run-close'".

- [ ] **Step 3: Implement `run_close.py`**

Create `AgentLens/src/agentlens/commands/run_close.py`:

```python
"""``agentlens run-close`` — mark a container run as ended."""
from __future__ import annotations

import json
from typing import Optional

import typer

from agentlens.commands._run_resolve import resolve_run_dir
from agentlens.store.paths import agentlens_home
from agentlens.store.sqlite_index import index_run, init_db
from agentlens.time import now_iso


def run_close(
    run: str = typer.Option(..., "--run", help="run_id to close"),
    exit_code: Optional[int] = typer.Option(None, "--exit-code"),
) -> None:
    home = agentlens_home()
    try:
        run_dir = resolve_run_dir(run, home=home)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"agentlens: run {run!r} not found ({exc})", err=True)
        raise typer.Exit(code=0)  # non-blocking
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["ended_at"] = now_iso()
    if exit_code is not None:
        meta["agent_outcome"] = "completed" if exit_code == 0 else "failed"
    else:
        meta.setdefault("agent_outcome", "completed")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    try:
        conn = init_db(home)
        index_run(conn, run_dir)
        conn.close()
    except Exception as exc:
        typer.echo(f"agentlens: index update failed: {exc}", err=True)
```

- [ ] **Step 4: Wire into `cli.py`**

Add:
```python
from .commands import run_close as run_close_cmd
...
app.command(name="run-close")(run_close_cmd.run_close)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_run_open_close.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/commands/run_close.py AgentLens/src/agentlens/cli.py \
        AgentLens/tests/integration/test_run_open_close.py
git commit -m "feat(agentlens): add run-close command with non-blocking unknown-run handling"
```

---

### Task 5: `agentlens event append` — happy path

**Files:**
- Create: `AgentLens/src/agentlens/commands/event.py`
- Modify: `AgentLens/src/agentlens/cli.py`
- Test: `AgentLens/tests/integration/test_event_append.py`

- [ ] **Step 1: Write failing test**

Create `AgentLens/tests/integration/test_event_append.py`:

```python
"""Integration tests for `agentlens event append` (spec §4.2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def _cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agentlens.cli", *args],
        capture_output=True, text=True, check=False, input=stdin,
    )


def test_event_append_round_trips_payload(home: Path) -> None:
    run_id = _cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    payload = json.dumps({"task_id": "T1", "phase": "1"})
    res = _cli("event", "append", "--run", run_id,
               "--type", "kws-cme.task_started", "--payload-json", payload)
    assert res.returncode == 0, res.stderr
    run_dir = next((home / "runs").rglob(run_id))
    lines = (run_dir / "events.jsonl").read_text().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["type"] == "kws-cme.task_started"
    assert evt["payload"] == {"task_id": "T1", "phase": "1"}
    assert "ts" in evt


def test_event_append_unknown_run_id_exits_zero(home: Path) -> None:
    res = _cli("event", "append", "--run", "run_does_not_exist",
               "--type", "x.y", "--payload-json", "{}")
    assert res.returncode == 0  # non-blocking invariant
    assert "not found" in res.stderr.lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_event_append.py -v`
Expected: FAIL — "No such command 'event'".

- [ ] **Step 3: Implement `event.py`**

Create `AgentLens/src/agentlens/commands/event.py`:

```python
"""``agentlens event`` — append/query orchestration events (spec §4.2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from agentlens.commands._run_resolve import resolve_run_dir
from agentlens.store.paths import agentlens_home
from agentlens.store.writer import append_event
from agentlens.time import now_iso

app = typer.Typer(help="Append or query orchestration events.")


@app.command(name="append")
def append(
    run: str = typer.Option(..., "--run"),
    type_: str = typer.Option(..., "--type", help="<namespace>.<event>"),
    payload_json: Optional[str] = typer.Option(None, "--payload-json"),
    payload_file: Optional[Path] = typer.Option(None, "--payload-file"),
    payload_stdin: bool = typer.Option(False, "--payload-stdin"),
    ts: Optional[str] = typer.Option(None, "--ts"),
) -> None:
    sources = [bool(payload_json), bool(payload_file), payload_stdin]
    if sum(sources) != 1:
        typer.echo("agentlens: provide exactly one of --payload-json/-file/-stdin", err=True)
        raise typer.Exit(code=0)
    if payload_json is not None:
        payload_raw = payload_json
    elif payload_file is not None:
        payload_raw = payload_file.read_text()
    else:
        payload_raw = sys.stdin.read()
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"agentlens: invalid JSON payload ({exc})", err=True)
        raise typer.Exit(code=0)
    home = agentlens_home()
    try:
        run_dir = resolve_run_dir(run, home=home)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"agentlens: run {run!r} not found ({exc})", err=True)
        raise typer.Exit(code=0)
    try:
        event = {"ts": ts or now_iso(), "type": type_, "payload": payload}
        append_event(run_dir, event)
    except Exception as exc:
        typer.echo(f"agentlens: event append failed: {exc}", err=True)
        raise typer.Exit(code=0)
```

- [ ] **Step 4: Wire into `cli.py`**

```python
from .commands import event as event_cmd
...
app.add_typer(event_cmd.app, name="event")
```

- [ ] **Step 5: Verify `append_event` accepts our event shape**

Check `AgentLens/src/agentlens/store/writer.py:append_event` — it validates `event` is a dict and writes one JSON line under `events.jsonl`. Our `{ts, type, payload}` triple satisfies the existing contract.

- [ ] **Step 6: Run tests to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_event_append.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/commands/event.py AgentLens/src/agentlens/cli.py \
        AgentLens/tests/integration/test_event_append.py
git commit -m "feat(agentlens): add event append command with non-blocking error handling"
```

---

### Task 6: `agentlens event append` — `--payload-stdin` and `--payload-file`

**Files:**
- Modify: `AgentLens/tests/integration/test_event_append.py`

- [ ] **Step 1: Add failing tests**

```python
def test_event_append_payload_stdin(home: Path) -> None:
    run_id = _cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    res = _cli("event", "append", "--run", run_id, "--type", "x.y",
               "--payload-stdin", stdin='{"k":"v"}')
    assert res.returncode == 0, res.stderr
    run_dir = next((home / "runs").rglob(run_id))
    evt = json.loads((run_dir / "events.jsonl").read_text().splitlines()[0])
    assert evt["payload"] == {"k": "v"}


def test_event_append_payload_file(home: Path, tmp_path: Path) -> None:
    run_id = _cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    pf = tmp_path / "p.json"
    pf.write_text('{"from":"file"}')
    res = _cli("event", "append", "--run", run_id, "--type", "x.y",
               "--payload-file", str(pf))
    assert res.returncode == 0, res.stderr
    run_dir = next((home / "runs").rglob(run_id))
    evt = json.loads((run_dir / "events.jsonl").read_text().splitlines()[0])
    assert evt["payload"] == {"from": "file"}
```

- [ ] **Step 2: Run to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_event_append.py -v`
Expected: PASS (Task 5 already covers all three source forms).

- [ ] **Step 3: Commit**

```bash
git add AgentLens/tests/integration/test_event_append.py
git commit -m "test(agentlens): cover event append --payload-stdin and --payload-file"
```

---

### Task 7: `event_query` pure module (filter by type glob, since)

**Files:**
- Create: `AgentLens/src/agentlens/store/event_query.py`
- Test: `AgentLens/tests/unit/test_event_query.py`

- [ ] **Step 1: Write failing tests**

Create `AgentLens/tests/unit/test_event_query.py`:

```python
"""Unit tests for event_query pure functions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlens.store.event_query import filter_events, load_events_jsonl, tree_merge


def _write_events(path: Path, *events: dict) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def test_load_events_jsonl_returns_dicts(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_events(p, {"ts": "2026-05-19T00:00:00Z", "type": "a.b", "payload": {}})
    events = list(load_events_jsonl(p))
    assert len(events) == 1
    assert events[0]["type"] == "a.b"


def test_filter_events_glob(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_events(
        p,
        {"ts": "2026-05-19T00:00:00Z", "type": "kws-cme.task_started", "payload": {}},
        {"ts": "2026-05-19T00:00:01Z", "type": "command.started", "payload": {}},
        {"ts": "2026-05-19T00:00:02Z", "type": "kws-cme.task_completed", "payload": {}},
    )
    matches = list(filter_events(load_events_jsonl(p), type_glob="kws-cme.*"))
    assert [m["type"] for m in matches] == ["kws-cme.task_started", "kws-cme.task_completed"]


def test_filter_events_since(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_events(
        p,
        {"ts": "2026-05-19T00:00:00Z", "type": "a.b", "payload": {}},
        {"ts": "2026-05-19T00:00:05Z", "type": "a.b", "payload": {}},
    )
    matches = list(filter_events(load_events_jsonl(p), since="2026-05-19T00:00:03Z"))
    assert len(matches) == 1
    assert matches[0]["ts"] == "2026-05-19T00:00:05Z"


def test_tree_merge_orders_by_ts(tmp_path: Path) -> None:
    a = tmp_path / "a.jsonl"; b = tmp_path / "b.jsonl"
    _write_events(a,
        {"ts": "2026-05-19T00:00:00Z", "type": "parent.x", "payload": {}},
        {"ts": "2026-05-19T00:00:10Z", "type": "parent.y", "payload": {}})
    _write_events(b,
        {"ts": "2026-05-19T00:00:05Z", "type": "child.x", "payload": {}})
    merged = list(tree_merge([a, b]))
    assert [m["type"] for m in merged] == ["parent.x", "child.x", "parent.y"]
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_event_query.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `event_query.py`**

Create `AgentLens/src/agentlens/store/event_query.py`:

```python
"""Pure query primitives over events.jsonl (spec §4.2 events command)."""
from __future__ import annotations

import fnmatch
import heapq
import json
from pathlib import Path
from typing import Iterable, Iterator, Optional


def load_events_jsonl(path: Path) -> Iterator[dict]:
    if not path.is_file():
        return iter(())
    def gen() -> Iterator[dict]:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip torn writes
    return gen()


def filter_events(
    events: Iterable[dict],
    *,
    type_glob: Optional[str] = None,
    since: Optional[str] = None,
) -> Iterator[dict]:
    for evt in events:
        if type_glob and not fnmatch.fnmatchcase(evt.get("type", ""), type_glob):
            continue
        if since and evt.get("ts", "") < since:
            continue
        yield evt


def tree_merge(paths: Iterable[Path]) -> Iterator[dict]:
    """Merge multiple sorted events.jsonl streams by (ts, source-path)."""
    streams = [
        ((evt["ts"], str(p), evt) for evt in load_events_jsonl(p))
        for p in paths
    ]
    for _ts, _src, evt in heapq.merge(*streams, key=lambda t: (t[0], t[1])):
        yield evt
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_event_query.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/store/event_query.py AgentLens/tests/unit/test_event_query.py
git commit -m "feat(agentlens): add event_query pure module with glob/since/tree-merge"
```

---

### Task 8: `agentlens event query` subcommand + `agentlens events` alias

**Files:**
- Modify: `AgentLens/src/agentlens/commands/event.py`
- Create: `AgentLens/src/agentlens/commands/events.py`
- Modify: `AgentLens/src/agentlens/cli.py`
- Test: `AgentLens/tests/integration/test_event_append.py`

- [ ] **Step 1: Add failing test for query**

Append to `AgentLens/tests/integration/test_event_append.py`:

```python
def test_event_query_returns_appended_event_as_jsonl(home: Path) -> None:
    run_id = _cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    _cli("event", "append", "--run", run_id, "--type", "kws-cme.task_started",
         "--payload-json", '{"task":"T1"}')
    res = _cli("event", "query", "--run", run_id)
    assert res.returncode == 0, res.stderr
    lines = [l for l in res.stdout.splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == "kws-cme.task_started"


def test_events_alias_works_identically(home: Path) -> None:
    run_id = _cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    _cli("event", "append", "--run", run_id, "--type", "x.y", "--payload-json", "{}")
    res = _cli("events", "--run", run_id)
    assert res.returncode == 0, res.stderr
    assert len(res.stdout.strip().splitlines()) == 1
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_event_append.py -v -k query`
Expected: FAIL — "No such command 'query'".

- [ ] **Step 3: Add `query` to `event.py`**

Append to `AgentLens/src/agentlens/commands/event.py`:

```python
from agentlens.store.event_query import filter_events, load_events_jsonl, tree_merge


@app.command(name="query")
def query(
    run: Optional[str] = typer.Option(None, "--run"),
    type_glob: Optional[str] = typer.Option(None, "--type"),
    since: Optional[str] = typer.Option(None, "--since"),
    tree: bool = typer.Option(False, "--tree"),
    follow: bool = typer.Option(False, "--follow"),
) -> None:
    home = agentlens_home()
    if run is None:
        typer.echo("agentlens: --run is required (cross-run query in a later task)", err=True)
        raise typer.Exit(code=2)
    try:
        run_dir = resolve_run_dir(run, home=home)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"agentlens: run {run!r} not found ({exc})", err=True)
        raise typer.Exit(code=0)
    if tree:
        # tree merge handled in Task 11
        paths = [run_dir / "events.jsonl"]
    else:
        paths = [run_dir / "events.jsonl"]
    if len(paths) == 1:
        events = load_events_jsonl(paths[0])
    else:
        events = tree_merge(paths)
    for evt in filter_events(events, type_glob=type_glob, since=since):
        typer.echo(json.dumps(evt))
    if follow:
        typer.echo("agentlens: --follow not yet implemented", err=True)
```

- [ ] **Step 4: Create `events.py` alias**

Create `AgentLens/src/agentlens/commands/events.py`:

```python
"""``agentlens events`` — top-level alias for ``agentlens event query``."""
from __future__ import annotations

from agentlens.commands.event import query as events  # re-export
```

- [ ] **Step 5: Wire into `cli.py`**

```python
from .commands import events as events_cmd
...
app.command(name="events")(events_cmd.events)
```

- [ ] **Step 6: Run tests**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_event_append.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/commands/event.py AgentLens/src/agentlens/commands/events.py \
        AgentLens/src/agentlens/cli.py AgentLens/tests/integration/test_event_append.py
git commit -m "feat(agentlens): add event query subcommand and events top-level alias"
```

---

### Task 9: `AGENTLENS_PARENT_RUN_ID` env read in process wrapper

**Files:**
- Modify: `AgentLens/src/agentlens/adapters/process.py` (around line 716 where `AGENTLENS_RUN_ID` is set)
- Test: `AgentLens/tests/integration/test_parent_run_linkage.py`

- [ ] **Step 1: Write failing test**

Create `AgentLens/tests/integration/test_parent_run_linkage.py`:

```python
"""Spec §4.4 — AGENTLENS_PARENT_RUN_ID propagation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_parent_run_id_env_populates_capture_run_meta(home: Path) -> None:
    parent_id = subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "run-open",
         "--agent", "kws-cme-orchestrator"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    env = {**os.environ, "AGENTLENS_PARENT_RUN_ID": parent_id}
    subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "run",
         "--agent", "claude_code", "--", "echo", "hello"],
        env=env, capture_output=True, text=True, check=True,
    )
    # Locate the newest capture run that's not the parent.
    all_runs = [p for p in (home / "runs").rglob("run_*") if p.is_dir() and p.name != parent_id]
    assert all_runs, "no capture run created"
    latest = max(all_runs, key=lambda p: p.stat().st_mtime)
    meta = json.loads((latest / "meta.json").read_text())
    assert meta.get("parent_run_id") == parent_id
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_parent_run_linkage.py -v`
Expected: FAIL — `parent_run_id` is None.

- [ ] **Step 3: Modify `process.py` to read env**

In `AgentLens/src/agentlens/adapters/process.py`, locate where `meta` is constructed for the capture run (search for `agent_mode` and `recording_mode`). Add immediately before writing meta:

```python
parent_run_id = os.environ.get("AGENTLENS_PARENT_RUN_ID") or None
```

And include `parent_run_id` in the meta dict.

- [ ] **Step 4: Run test to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_parent_run_linkage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/adapters/process.py AgentLens/tests/integration/test_parent_run_linkage.py
git commit -m "feat(agentlens): propagate AGENTLENS_PARENT_RUN_ID into capture run meta"
```

---

### Task 10: SQLite `parent_run_id` column populated from capture runs

**Files:**
- Modify: `AgentLens/src/agentlens/store/sqlite_index.py` `index_run()`
- Test: `AgentLens/tests/integration/test_parent_run_linkage.py`

- [ ] **Step 1: Add failing test**

```python
def test_parent_run_id_appears_in_sqlite_index(home: Path) -> None:
    import sqlite3
    parent_id = subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "run-open",
         "--agent", "kws-cme-orchestrator"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    env = {**os.environ, "AGENTLENS_PARENT_RUN_ID": parent_id}
    subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "run",
         "--agent", "claude_code", "--", "echo", "hi"],
        env=env, check=True, capture_output=True,
    )
    db = home / "index.db"
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT run_id, parent_run_id FROM runs WHERE parent_run_id = ?",
        (parent_id,)
    ).fetchall()
    assert len(rows) == 1
```

- [ ] **Step 2: Run to verify fail or pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_parent_run_linkage.py -v`
Expected: If `index_run()` already reads `parent_run_id` from meta, PASS. If FAIL, proceed to Step 3.

- [ ] **Step 3: If fail, update `index_run()`**

In `AgentLens/src/agentlens/store/sqlite_index.py:index_run()`, read `parent_run_id` from `meta.json` (defaulting to None) and include in the INSERT.

- [ ] **Step 4: Verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_parent_run_linkage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (only if changes made)**

```bash
git add -u && git commit -m "feat(agentlens): index parent_run_id column from meta.json"
```

---

### Task 11: `agentlens event query --tree` cross-run merge

**Files:**
- Modify: `AgentLens/src/agentlens/commands/event.py`
- Test: `AgentLens/tests/integration/test_event_append.py`

- [ ] **Step 1: Write failing test**

```python
def test_event_query_tree_merges_parent_and_child(home: Path) -> None:
    parent = _cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    _cli("event", "append", "--run", parent, "--type", "kws-cme.task_started",
         "--payload-json", '{"task":"T1"}')
    env = {**os.environ, "AGENTLENS_PARENT_RUN_ID": parent}
    subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "run", "--agent", "claude_code",
         "--", "echo", "child"],
        env=env, check=True, capture_output=True,
    )
    _cli("event", "append", "--run", parent, "--type", "kws-cme.task_completed",
         "--payload-json", '{"task":"T1"}')
    res = _cli("event", "query", "--run", parent, "--tree")
    assert res.returncode == 0, res.stderr
    lines = [json.loads(l) for l in res.stdout.splitlines() if l.strip()]
    types = [e["type"] for e in lines]
    # Parent events + child's command.started/finished, all in ts order.
    assert "kws-cme.task_started" in types
    assert "command.started" in types
    assert "command.finished" in types
    assert "kws-cme.task_completed" in types
    # Ordering by ts
    for a, b in zip(lines, lines[1:]):
        assert a["ts"] <= b["ts"]
```

Also add at top of file:
```python
import os
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_event_append.py -v -k tree`
Expected: FAIL — `--tree` returns only parent events.

- [ ] **Step 3: Implement tree expansion in `event.py query()`**

Replace the placeholder block in `query()`:

```python
    if tree:
        import sqlite3
        from agentlens.store.paths import index_db_path
        conn = sqlite3.connect(index_db_path(home))
        run_id = json.loads((run_dir / "meta.json").read_text())["run_id"]
        children = [row[0] for row in conn.execute(
            "WITH RECURSIVE descendants(id) AS ("
            "  SELECT run_id FROM runs WHERE parent_run_id = ?"
            "  UNION ALL SELECT r.run_id FROM runs r JOIN descendants d "
            "  ON r.parent_run_id = d.id"
            ") SELECT id FROM descendants",
            (run_id,)
        ).fetchall()]
        conn.close()
        from agentlens.commands._run_resolve import resolve_run_dir as _r
        paths = [run_dir / "events.jsonl"]
        for child_id in children:
            try:
                paths.append(_r(child_id, home=home) / "events.jsonl")
            except Exception:
                continue
    else:
        paths = [run_dir / "events.jsonl"]
```

If `index_db_path` doesn't exist in `paths.py`, add helper:

```python
def index_db_path(home: Path | None = None) -> Path:
    return (home or agentlens_home()) / "index.db"
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_event_append.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/commands/event.py AgentLens/src/agentlens/store/paths.py \
        AgentLens/tests/integration/test_event_append.py
git commit -m "feat(agentlens): event query --tree merges parent + descendant runs"
```

---

### Task 12: Shim — TTY-detect pass-through for interactive `claude`

**Files:**
- Modify: `AgentLens/src/agentlens/adapters/shims.py` `SHIM_TEMPLATE`
- Test: `AgentLens/tests/unit/test_shim_security.py`

- [ ] **Step 1: Write failing test**

Append to `AgentLens/tests/unit/test_shim_security.py`:

```python
def test_shim_claude_interactive_tty_passthrough_guard(home: Path, tmp_path: Path) -> None:
    """For `claude` (no -p/--print), interactive TTY should pass-through to REAL."""
    binary = _make_fake_binary(tmp_path, "claude")
    install_shim("claude", binary)
    shim_text = (home / ".agentlens/shims/claude").read_text()
    # Must include the TTY guard.
    assert "[ -t 0 ]" in shim_text
    assert "-p|--print|--output-format" in shim_text  # whitelisted non-TTY flags
    # codex shim must NOT include the guard (it has no TUI).
    bin_codex = _make_fake_binary(tmp_path, "codex")
    install_shim("codex", bin_codex)
    codex_shim = (home / ".agentlens/shims/codex").read_text()
    assert "[ -t 0 ]" not in codex_shim
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_shim_security.py::test_shim_claude_interactive_tty_passthrough_guard -v`
Expected: FAIL.

- [ ] **Step 3: Add TTY guard conditional in `SHIM_TEMPLATE`**

In `AgentLens/src/agentlens/adapters/shims.py`, restructure to have two templates or template-conditional. Simplest: add a new placeholder `{tty_guard}` and parameterize at install time.

```python
_TTY_GUARD = r"""
# Interactive claude (TUI) cannot safely run under our pipe-based wrapper.
# Pass through directly; the session JSONL is ingested later via
# `agentlens import claude-session`.
if [ -t 0 ]; then
  case "${{1:-}}" in
    -p|--print|--output-format) ;;  # non-TTY mode → wrap
    *) exec "$REAL_PATH" "$@" ;;
  esac
fi
"""

SHIM_TEMPLATE = r"""#!/usr/bin/env bash
# AgentLens shim for {name} — managed file, do not edit.
INSTALLED_AGENTLENS_BIN="{agentlens_bin}"
set -euo pipefail
REAL_LOCKFILE="$HOME/.agentlens/shims/{name}.real"
if [ ! -f "$REAL_LOCKFILE" ]; then
  echo "agentlens: real binary lockfile missing — passthrough" >&2
  mapfile -t CANDIDATES < <(type -P -a {name} 2>/dev/null | grep -F -v "$HOME/.agentlens/shims/" || true)
  if [ "${{#CANDIDATES[@]}}" -eq 0 ]; then
    echo "agentlens: no real {name} binary found" >&2
    exit 127
  fi
  exec "${{CANDIDATES[0]}}" "$@"
fi
REAL_PATH="$(awk -F= '$1=="path"{{print $2}}' "$REAL_LOCKFILE")"
REAL_SHA="$(awk -F= '$1=="sha256"{{print $2}}' "$REAL_LOCKFILE")"
CUR_SHA="$(shasum -a 256 "$REAL_PATH" | awk '{{print $1}}')"
if [ "$REAL_SHA" != "$CUR_SHA" ]; then
  echo "agentlens: real binary sha256 drift — passthrough only" >&2
  exec "$REAL_PATH" "$@"
fi
if [ -n "${{AGENTLENS_RUN_ID:-}}" ]; then
  policy="${{AGENTLENS_NESTED_POLICY:-passthrough}}"
  if [ "$policy" = "passthrough" ]; then exec "$REAL_PATH" "$@"; fi
fi
case "${{1:-}}" in
  auth|login|update|plugin|mcp) exec "$REAL_PATH" "$@" ;;
esac
{tty_guard}
if [ -n "$INSTALLED_AGENTLENS_BIN" ] && [ -x "$INSTALLED_AGENTLENS_BIN" ]; then
  exec "$INSTALLED_AGENTLENS_BIN" run --agent {agent_name} -- "$REAL_PATH" "$@"
fi
if AGENTLENS_BIN="$(command -v agentlens 2>/dev/null)" && [ -x "$AGENTLENS_BIN" ]; then
  exec "$AGENTLENS_BIN" run --agent {agent_name} -- "$REAL_PATH" "$@"
fi
echo "agentlens: CLI not on PATH and install-time path missing — passthrough (no recording)" >&2
exec "$REAL_PATH" "$@"
"""
```

In `install_shim()`, compute `tty_guard = _TTY_GUARD if name == "claude" else ""` and pass to `.format(...)`.

- [ ] **Step 4: Run unit tests**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_shim_security.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/adapters/shims.py AgentLens/tests/unit/test_shim_security.py
git commit -m "feat(agentlens): TTY-detect pass-through for interactive claude shim"
```

---

### Task 13: claude-session parser pure module

**Files:**
- Create: `AgentLens/src/agentlens/store/claude_session.py`
- Create: `AgentLens/tests/fixtures/claude_sessions/session_minimal.jsonl`
- Test: `AgentLens/tests/unit/test_claude_session_parser.py`

- [ ] **Step 1: Create fixture**

Create `AgentLens/tests/fixtures/claude_sessions/session_minimal.jsonl`:

```jsonl
{"type":"summary","timestamp":"2026-05-19T00:00:00Z","sessionId":"abc-123","cwd":"/Users/kws/proj"}
{"type":"user","timestamp":"2026-05-19T00:00:01Z","sessionId":"abc-123","message":{"role":"user","content":"hi"}}
{"type":"assistant","timestamp":"2026-05-19T00:00:02Z","sessionId":"abc-123","message":{"role":"assistant","content":[{"type":"text","text":"hello"}]}}
{"type":"assistant","timestamp":"2026-05-19T00:00:03Z","sessionId":"abc-123","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{"file_path":"/x"}}]}}
```

- [ ] **Step 2: Write failing tests**

Create `AgentLens/tests/unit/test_claude_session_parser.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentlens.store.claude_session import parse_session_jsonl, session_to_run_events

FIXTURE = Path(__file__).parent.parent / "fixtures/claude_sessions/session_minimal.jsonl"


def test_parse_session_jsonl_extracts_session_id_and_start_ts() -> None:
    info = parse_session_jsonl(FIXTURE)
    assert info["session_id"] == "abc-123"
    assert info["started_at"] == "2026-05-19T00:00:00Z"
    assert info["cwd"] == "/Users/kws/proj"


def test_session_to_run_events_emits_command_started_and_finished() -> None:
    events = list(session_to_run_events(FIXTURE))
    types = [e["type"] for e in events]
    assert types[0] == "command.started"
    assert types[-1] == "command.finished"
    # Tool use events preserved as opaque.
    assert any(e["type"] == "claude.tool_use" for e in events)
```

- [ ] **Step 3: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_claude_session_parser.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `claude_session.py`**

Create `AgentLens/src/agentlens/store/claude_session.py`:

```python
"""Parse Claude Code session JSONL → AgentLens events (spec §4.2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


def parse_session_jsonl(path: Path) -> dict:
    """Read the session JSONL and return summary info."""
    with path.open("r", encoding="utf-8") as fh:
        first = json.loads(fh.readline())
        # Replay to find last timestamp.
        last_ts = first.get("timestamp", "")
        for line in fh:
            try:
                rec = json.loads(line)
                if "timestamp" in rec:
                    last_ts = rec["timestamp"]
            except json.JSONDecodeError:
                continue
    return {
        "session_id": first.get("sessionId", ""),
        "started_at": first.get("timestamp", ""),
        "ended_at": last_ts,
        "cwd": first.get("cwd"),
    }


def session_to_run_events(path: Path) -> Iterator[dict]:
    """Convert a session JSONL into AgentLens events.

    Synthesizes:
      - command.started at the first record's timestamp (payload includes session_id)
      - claude.tool_use per assistant tool_use content block
      - command.finished at the last record's timestamp
    """
    info = parse_session_jsonl(path)
    yield {
        "ts": info["started_at"],
        "type": "command.started",
        "payload": {"session_id": info["session_id"], "cwd": info["cwd"]},
    }
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message", {})
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield {
                        "ts": rec.get("timestamp", info["started_at"]),
                        "type": "claude.tool_use",
                        "payload": {
                            "name": block.get("name"),
                            "input": block.get("input"),
                        },
                    }
    yield {
        "ts": info["ended_at"],
        "type": "command.finished",
        "payload": {"session_id": info["session_id"], "exit_code": 0},
    }
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/unit/test_claude_session_parser.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/store/claude_session.py \
        AgentLens/tests/fixtures/claude_sessions/session_minimal.jsonl \
        AgentLens/tests/unit/test_claude_session_parser.py
git commit -m "feat(agentlens): add Claude Code session JSONL parser"
```

---

### Task 14: `agentlens import claude-session` command

**Files:**
- Create: `AgentLens/src/agentlens/commands/import_claude_session.py`
- Modify: `AgentLens/src/agentlens/cli.py`
- Test: `AgentLens/tests/integration/test_import_claude_session.py`

- [ ] **Step 1: Write failing test**

Create `AgentLens/tests/integration/test_import_claude_session.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "agentlens"))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


FIXTURE = Path(__file__).parent.parent / "fixtures/claude_sessions/session_minimal.jsonl"


def _seed_projects(home_tmp: Path) -> Path:
    projects = home_tmp / ".claude/projects/-Users-kws-proj"
    projects.mkdir(parents=True)
    dst = projects / "abc-123.jsonl"
    shutil.copy(FIXTURE, dst)
    return dst


def test_import_claude_session_latest_creates_run(home: Path) -> None:
    _seed_projects(home)
    res = subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "import", "claude-session", "--latest"],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0, res.stderr
    run_id = res.stdout.strip()
    runs_root = home / "agentlens" / "runs"
    run_dirs = list(runs_root.rglob(run_id))
    assert len(run_dirs) == 1
    meta = json.loads((run_dirs[0] / "meta.json").read_text())
    assert meta["agent_name"] == "claude_code"
    assert meta["source"] == "claude-session-jsonl"
    assert meta["session_id"] == "abc-123"


def test_import_claude_session_is_idempotent(home: Path) -> None:
    _seed_projects(home)
    first = subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "import", "claude-session", "--id", "abc-123"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    second = subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "import", "claude-session", "--id", "abc-123"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    assert first == second  # same run, not a duplicate
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_import_claude_session.py -v`
Expected: FAIL — "No such command 'import'".

- [ ] **Step 3: Implement `import_claude_session.py`**

Create `AgentLens/src/agentlens/commands/import_claude_session.py`:

```python
"""``agentlens import claude-session`` — ingest a Claude Code session JSONL."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import typer

from agentlens.ids import new_run_id, new_workspace_id
from agentlens.store.claude_session import parse_session_jsonl, session_to_run_events
from agentlens.store.paths import agentlens_home
from agentlens.store.sqlite_index import index_run, init_db
from agentlens.store.writer import append_event

app = typer.Typer(help="Import external session logs.")


@app.command(name="claude-session")
def claude_session(
    latest: bool = typer.Option(False, "--latest"),
    session_id: Optional[str] = typer.Option(None, "--id"),
    all_: bool = typer.Option(False, "--all"),
    project: Optional[str] = typer.Option(None, "--project"),
    parent: Optional[str] = typer.Option(None, "--parent"),
) -> None:
    if sum([latest, bool(session_id), all_]) != 1:
        typer.echo("agentlens: provide exactly one of --latest/--id/--all", err=True)
        raise typer.Exit(code=2)
    projects_root = Path.home() / ".claude" / "projects"
    if project:
        candidates = list((projects_root / project).glob("*.jsonl"))
    else:
        candidates = list(projects_root.rglob("*.jsonl"))
    if not candidates:
        typer.echo("agentlens: no Claude Code session JSONL found", err=True)
        raise typer.Exit(code=0)
    if latest:
        target = max(candidates, key=lambda p: p.stat().st_mtime)
        targets = [target]
    elif session_id:
        targets = [p for p in candidates if p.stem == session_id]
        if not targets:
            typer.echo(f"agentlens: session {session_id!r} not found", err=True)
            raise typer.Exit(code=0)
    else:
        targets = candidates
    home = agentlens_home()
    last_run_id = ""
    for tgt in targets:
        info = parse_session_jsonl(tgt)
        sid = info["session_id"] or tgt.stem
        cwd = info.get("cwd") or str(Path.home())
        workspace_id = new_workspace_id(Path(cwd))
        # Idempotent: scan for existing run with same session_id.
        runs_root = home / "runs" / workspace_id
        existing = None
        if runs_root.exists():
            for d in runs_root.iterdir():
                meta = d / "meta.json"
                if meta.is_file():
                    try:
                        if json.loads(meta.read_text()).get("session_id") == sid:
                            existing = d.name
                            break
                    except Exception:
                        continue
        if existing:
            typer.echo(existing)
            last_run_id = existing
            continue
        run_id = new_run_id()
        run_dir = home / "runs" / workspace_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(tgt, run_dir / "transcript.jsonl")
        (run_dir / "events.jsonl").touch()
        for evt in session_to_run_events(tgt):
            append_event(run_dir, evt)
        meta_payload = {
            "run_id": run_id,
            "workspace_id": workspace_id,
            "agent_name": "claude_code",
            "agent_mode": "code",
            "recording_mode": "full",
            "started_at": info["started_at"],
            "ended_at": info["ended_at"],
            "parent_run_id": parent,
            "has_transcript": True,
            "source": "claude-session-jsonl",
            "session_id": sid,
        }
        (run_dir / "meta.json").write_text(json.dumps(meta_payload, indent=2) + "\n")
        try:
            conn = init_db(home)
            index_run(conn, run_dir)
            conn.close()
        except Exception as exc:
            typer.echo(f"agentlens: index update failed: {exc}", err=True)
        typer.echo(run_id)
        last_run_id = run_id
    _ = last_run_id  # silence unused
```

- [ ] **Step 4: Wire into `cli.py`**

```python
from .commands import import_claude_session as import_cmd
...
app.add_typer(import_cmd.app, name="import")
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_import_claude_session.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/commands/import_claude_session.py AgentLens/src/agentlens/cli.py \
        AgentLens/tests/integration/test_import_claude_session.py
git commit -m "feat(agentlens): add import claude-session command with idempotency"
```

---

### Task 15: cmux auto-detect at `agentlens install claude`

**Files:**
- Modify: `AgentLens/src/agentlens/commands/install.py`
- Modify: `AgentLens/src/agentlens/adapters/shims.py` (helper `install_cmux_chain`)
- Test: `AgentLens/tests/integration/test_cmux_chain.py`

- [ ] **Step 1: Write failing test**

Create `AgentLens/tests/integration/test_cmux_chain.py`:

```python
"""Spec §4.6 — cmux auto-chain at install time."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def fake_cmux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fake cmux app layout under tmp_path."""
    cmux_root = tmp_path / "cmux.app" / "Contents" / "Resources" / "bin"
    cmux_root.mkdir(parents=True)
    cmux_claude = cmux_root / "claude"
    cmux_claude.write_text(
        '#!/usr/bin/env bash\n# cmux wrapper\necho "cmux-injected" >&2\nexit 0\n'
    )
    cmux_claude.chmod(0o755)
    monkeypatch.setenv("AGENTLENS_CMUX_ROOT", str(tmp_path / "cmux.app"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "agentlens"))
    return cmux_claude


def test_install_with_cmux_chain_backs_up_and_replaces(fake_cmux: Path) -> None:
    real_claude = fake_cmux.parent.parent.parent / "claude.real-binary"
    real_claude.write_text("#!/usr/bin/env bash\necho real\n")
    real_claude.chmod(0o755)
    res = subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "install", "claude",
         str(real_claude), "--cmux", "--yes"],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0, res.stderr
    backup = fake_cmux.with_name("claude.cmux-original")
    assert backup.is_file()
    assert backup.read_text().startswith("#!/usr/bin/env bash\n# cmux wrapper")
    # cmux claude now points at agentlens shim contents.
    assert "AgentLens shim" in fake_cmux.read_text()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_cmux_chain.py -v`
Expected: FAIL — `--cmux` option doesn't exist.

- [ ] **Step 3: Add `--cmux` and `--yes` flags to install command**

In `AgentLens/src/agentlens/commands/install.py`, locate the `install()` function signature and add:

```python
cmux: bool = typer.Option(False, "--cmux", help="Also chain cmux's claude wrapper."),
yes: bool = typer.Option(False, "--yes", help="Auto-confirm prompts (for scripts/tests)."),
```

After the normal `install_shim(...)` call, add:

```python
if cmux and name == "claude":
    from agentlens.adapters.shims import install_cmux_chain
    cmux_root = os.environ.get("AGENTLENS_CMUX_ROOT", "/Applications/cmux.app")
    cmux_bin = Path(cmux_root) / "Contents/Resources/bin/claude"
    if cmux_bin.is_file():
        if not yes:
            typer.confirm(f"Install AgentLens chain at {cmux_bin}?", abort=True)
        install_cmux_chain(cmux_bin)
        typer.echo(f"cmux chain installed at {cmux_bin}", err=True)
```

- [ ] **Step 4: Implement `install_cmux_chain` in `shims.py`**

```python
def install_cmux_chain(cmux_claude: Path) -> None:
    """Back up cmux's claude wrapper and replace with our shim that chains
    through the backup. The shim points REAL_PATH at the backup so cmux's
    own --session-id injection still runs after agentlens recording starts.
    """
    backup = cmux_claude.with_name("claude.cmux-original")
    if not backup.is_file():
        shutil.copy2(cmux_claude, backup)
    install_shim("claude", backup)
    # Copy our shim from ~/.agentlens/shims/claude over cmux's binary.
    our_shim = _shim_dir() / "claude"
    shutil.copy2(our_shim, cmux_claude)
    os.chmod(cmux_claude, 0o755)
    # Record install state for doctor checks.
    state_path = Path.home() / ".agentlens" / "cmux-install.json"
    state_path.write_text(json.dumps({
        "cmux_claude_path": str(cmux_claude),
        "backup_path": str(backup),
        "installed_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }, indent=2) + "\n")
```

Add `import json, shutil` at top of `shims.py` if not already present.

- [ ] **Step 5: Run tests to verify pass**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_cmux_chain.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/commands/install.py AgentLens/src/agentlens/adapters/shims.py \
        AgentLens/tests/integration/test_cmux_chain.py
git commit -m "feat(agentlens): cmux auto-chain install path with backup + state record"
```

---

### Task 16: `doctor` reports cmux backup missing / drift

**Files:**
- Modify: `AgentLens/src/agentlens/commands/doctor.py`
- Test: `AgentLens/tests/integration/test_install_doctor.py`

- [ ] **Step 1: Write failing test**

Append to `AgentLens/tests/integration/test_install_doctor.py`:

```python
def test_doctor_warns_when_cmux_backup_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "agentlens"))
    state = tmp_path / ".agentlens" / "cmux-install.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({
        "cmux_claude_path": str(tmp_path / "nope/claude"),
        "backup_path": str(tmp_path / "nope/claude.cmux-original"),
    }))
    import subprocess, sys
    res = subprocess.run(
        [sys.executable, "-m", "agentlens.cli", "doctor"],
        capture_output=True, text=True, check=False,
    )
    assert "cmux" in res.stdout.lower() or "cmux" in res.stderr.lower()
    assert "missing" in (res.stdout + res.stderr).lower() or "warn" in (res.stdout + res.stderr).lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_install_doctor.py::test_doctor_warns_when_cmux_backup_missing -v`
Expected: FAIL.

- [ ] **Step 3: Add cmux check to `doctor.py`**

In `AgentLens/src/agentlens/commands/doctor.py`, inside `doctor()` (or a helper called by it) add after existing checks:

```python
cmux_state_path = Path.home() / ".agentlens" / "cmux-install.json"
if cmux_state_path.is_file():
    try:
        state = json.loads(cmux_state_path.read_text())
        cmux_claude = Path(state["cmux_claude_path"])
        backup = Path(state["backup_path"])
        if not cmux_claude.is_file():
            typer.echo(f"WARN: cmux claude shim missing at {cmux_claude}", err=True)
        elif "AgentLens shim" not in cmux_claude.read_text():
            typer.echo(f"WARN: cmux claude no longer contains AgentLens shim "
                       f"(probably overwritten by cmux update); re-run "
                       f"`agentlens install claude --cmux`", err=True)
        if not backup.is_file():
            typer.echo(f"WARN: cmux backup missing at {backup}; "
                       f"re-run `agentlens install claude --cmux`", err=True)
    except Exception as exc:
        typer.echo(f"WARN: failed to read cmux state ({exc})", err=True)
```

Add `import json` if missing.

- [ ] **Step 4: Run tests**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_install_doctor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/commands/doctor.py AgentLens/tests/integration/test_install_doctor.py
git commit -m "feat(agentlens): doctor reports cmux chain drift and missing backup"
```

---

### Task 17: End-to-end smoke — orchestrator container + child capture + tree query

**Files:**
- Test: `AgentLens/tests/integration/test_phase1_smoke.py`

- [ ] **Step 1: Write the smoke test**

Create `AgentLens/tests/integration/test_phase1_smoke.py`:

```python
"""Phase 1 end-to-end smoke: parent container run + child capture + tree query."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def _cli(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "agentlens.cli", *args],
        capture_output=True, text=True, check=False, env=env,
    )


def test_phase1_end_to_end(home: Path) -> None:
    # 1. Orchestrator opens a container run.
    orch = _cli("run-open", "--agent", "kws-cme-orchestrator").stdout.strip()
    # 2. Emits a phase-start event.
    r = _cli("event", "append", "--run", orch, "--type", "kws-cme.phase_0_started",
             "--payload-json", '{"plan":"/tmp/p.md"}')
    assert r.returncode == 0, r.stderr
    # 3. Spawns a child claude -p with PARENT_RUN_ID set.
    r = _cli("run", "--agent", "claude_code", "--", "echo", "child-output",
             env_extra={"AGENTLENS_PARENT_RUN_ID": orch})
    assert r.returncode == 0, r.stderr
    # 4. Emits a phase-complete event.
    r = _cli("event", "append", "--run", orch, "--type", "kws-cme.phase_2_complete",
             "--payload-json", '{}')
    assert r.returncode == 0, r.stderr
    # 5. Closes the orchestrator run.
    r = _cli("run-close", "--run", orch, "--exit-code", "0")
    assert r.returncode == 0, r.stderr
    # 6. Tree query includes parent + child events in order.
    r = _cli("events", "--run", orch, "--tree")
    assert r.returncode == 0, r.stderr
    events = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    types = [e["type"] for e in events]
    assert "kws-cme.phase_0_started" in types
    assert "command.started" in types
    assert "command.finished" in types
    assert "kws-cme.phase_2_complete" in types
    # Ordering invariant.
    for a, b in zip(events, events[1:]):
        assert a["ts"] <= b["ts"]
```

- [ ] **Step 2: Run the smoke test**

Run: `cd AgentLens && .venv/bin/pytest tests/integration/test_phase1_smoke.py -v`
Expected: PASS (all prior tasks combined).

- [ ] **Step 3: Run the full AgentLens suite**

Run: `cd AgentLens && .venv/bin/pytest -q`
Expected: PASS — all 430+ existing tests plus new ones.

- [ ] **Step 4: Commit + tag**

```bash
git add AgentLens/tests/integration/test_phase1_smoke.py
git commit -m "test(agentlens): phase-1 end-to-end smoke (orch + child + tree query)"
git tag -a agentlens-v1.0.0 -m "AgentLens v1: container runs, opaque events, claude-session import, cmux chain"
```

---

# Phase 2 — kws-claude-multi-agent-executor migration

### Task 18: kws-cme SKILL.md — add orchestration run-open hook

**Files:**
- Modify: `~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md` (Phase -1 step b section)

- [ ] **Step 1: Read current Phase -1 step b**

Run: `grep -n "Initialize a minimal" ~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`
Note the line number for the "b. Initialize a minimal `.orchestrator/state.json` in the worktree." anchor.

- [ ] **Step 2: Insert the run-open block ABOVE step b's state.json write**

In `~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`, immediately before the "b. Initialize a minimal `.orchestrator/state.json`..." block, insert a new subsection:

```markdown
**b-pre. Open AgentLens orchestration run (optional but recommended).**

```bash
ORCH_RUN_ID="$(agentlens run-open \
  --agent kws-cme-orchestrator \
  --workspace "$WORKTREE_ABS" \
  --meta plan="$PLAN_PATH" --meta spec="$SPEC_PATH" 2>/dev/null || echo "")"
```

If AgentLens is not installed (`agentlens` not on PATH), `ORCH_RUN_ID` is empty and all subsequent `agentlens event append` calls become no-ops. The orchestrator continues normally with its file-based logging (legacy path during the dual-write window).
```

- [ ] **Step 3: Modify state.json schema in step b to persist `agentlens_orchestration_run`**

In the JSON blocks under step b, add the field:

```json
{
  ...,
  "agentlens_orchestration_run": "<ORCH_RUN_ID or empty string>",
  ...
}
```

Both single-plan and multi-plan shapes get this field at the top level.

- [ ] **Step 4: Commit (no test — SKILL.md is documentation)**

```bash
cd ~/.claude/skills/kws-claude-multi-agent-executor && \
git add SKILL.md && \
git commit -m "feat(kws-cme): add AgentLens orchestration run-open in Phase -1"
```

If kws-cme isn't a git repo, skip the commit step but note the change.

---

### Task 19: kws-cme SKILL.md — propagate AGENTLENS_PARENT_RUN_ID on spawn

**Files:**
- Modify: `~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md` (Phase -1 step d)

- [ ] **Step 1: Locate spawn command**

Run: `grep -n 'nohup claude' ~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`

- [ ] **Step 2: Add env var to the spawn**

Modify the `nohup claude -p ...` command to prefix it:

```bash
AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID" \
nohup claude -p --dangerously-skip-permissions \
  --output-format stream-json \
  "$(cat "$WORKTREE_ABS/.orchestrator/headless_prompt.txt")" \
  > "$WORKTREE_ABS/.orchestrator/headless.jsonl" 2>&1 &
```

- [ ] **Step 3: Commit**

```bash
cd ~/.claude/skills/kws-claude-multi-agent-executor && \
git add SKILL.md && \
git commit -m "feat(kws-cme): propagate AGENTLENS_PARENT_RUN_ID to spawned claude -p"
```

---

### Task 20: kws-cme SKILL.md — dual-write event hooks at transitions

**Files:**
- Modify: `~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`

- [ ] **Step 1: Identify all transition points**

Run: `grep -n "append_learning_event" ~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`
Note every occurrence — these are the existing event-emit sites.

- [ ] **Step 2: Add dual-write block next to each existing call**

For each `python scripts/append_learning_event.py ...` invocation, immediately after it add:

```bash
# Dual-write: AgentLens event mirror. Safe to fail silently.
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append \
    --run "$ORCH_RUN_ID" \
    --type "kws-cme.<event_name>" \
    --payload-json '<same JSON payload>' 2>/dev/null || true
fi
```

Map `<event_name>` from the script's `--event-type` arg. Use the same payload JSON the legacy script gets.

The event taxonomy to use:
- `kws-cme.phase_0_started`
- `kws-cme.phase_0_complete`
- `kws-cme.phase_1_started`
- `kws-cme.task_started` (payload includes `task_id`, `risk`)
- `kws-cme.task_completed` (payload includes `task_id`, `outcome`)
- `kws-cme.blocker` (payload includes `task_id`, `reason`)
- `kws-cme.verification_failed` (payload includes `task_id`, `reason`)
- `kws-cme.reviewer_warn_or_fail` (payload includes `task_id`, `severity`)
- `kws-cme.compaction` (payload includes `after_task`)
- `kws-cme.phase_2_complete`

- [ ] **Step 3: Add run-close at completion**

In the HEADLESS_DONE.txt write section, add immediately before:

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens run-close --run "$ORCH_RUN_ID" --exit-code 0 2>/dev/null || true
fi
```

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/skills/kws-claude-multi-agent-executor && \
git add SKILL.md && \
git commit -m "feat(kws-cme): dual-write AgentLens events at all phase/task transitions"
```

---

### Task 21: kws-cme dual-write validation (1-week observation)

**Files:** none

- [ ] **Step 1: Run a real plan end-to-end with AgentLens installed**

Pick a small AgentLens-internal plan (e.g. a 2-task fix). Run the orchestrator interactively and confirm:
- `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/events.jsonl` exists with N events (legacy path).
- `agentlens events --run <ORCH_RUN_ID>` returns the same N events with matching `type` and `payload`.

- [ ] **Step 2: Write a compare script (one-off)**

Create `AgentLens/scripts/compare_kws_cme_logs.py`:

```python
"""Compare legacy kws-cme events.jsonl against AgentLens event log."""
import json, sys, subprocess
from pathlib import Path

legacy_path = Path(sys.argv[1])  # ~/.claude/learning/.../events.jsonl
orch_run_id = sys.argv[2]

legacy = [json.loads(l) for l in legacy_path.read_text().splitlines() if l.strip()]
res = subprocess.run(
    ["agentlens", "events", "--run", orch_run_id],
    capture_output=True, text=True, check=True,
)
agentlens = [json.loads(l) for l in res.stdout.splitlines() if l.strip()]

print(f"legacy={len(legacy)} agentlens={len(agentlens)}")
legacy_types = sorted(e.get("event_type", e.get("type", "?")) for e in legacy)
agent_types = sorted(e["type"].split(".", 1)[1] for e in agentlens
                     if e["type"].startswith("kws-cme."))
mismatch = set(legacy_types) ^ set(agent_types)
if mismatch:
    print(f"MISMATCH: {mismatch}")
    sys.exit(1)
print("OK — event taxonomies match")
```

- [ ] **Step 3: Run compare script after each real run for 1 week**

Wait 1 week. If no mismatches surface, proceed to Task 22. If mismatches, fix the SKILL.md mapping (Task 20) and continue dual-write another cycle.

- [ ] **Step 4: Commit the script**

```bash
git add AgentLens/scripts/compare_kws_cme_logs.py
git commit -m "test(agentlens): dual-write compare script for kws-cme migration validation"
```

---

### Task 22: kws-cme cutover — remove legacy logging

**Files:**
- Modify: `~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`
- Delete: `~/.claude/skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py`

- [ ] **Step 1: Remove `python scripts/append_learning_event.py ...` lines from SKILL.md**

Run: `grep -n "append_learning_event" ~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`
For each match, delete the line(s) invoking the legacy script. Keep the AgentLens `event append` block added in Task 20.

- [ ] **Step 2: Delete the script file**

```bash
rm ~/.claude/skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py
```

- [ ] **Step 3: Update SKILL.md to drop the `~/.claude/learning/...` references**

Run: `grep -n "~/.claude/learning/kws-claude" ~/.claude/skills/kws-claude-multi-agent-executor/SKILL.md`
Remove the obsolete references; replace with `agentlens events --type 'kws-cme.*'` query examples.

- [ ] **Step 4: Run one more end-to-end plan to confirm AgentLens-only path works**

Pick a tiny plan, run it, confirm:
- `agentlens events --run <ORCH_RUN_ID>` shows all phase/task events.
- `~/.claude/learning/kws-claude-multi-agent-executor/runs/<today>/` does NOT contain a new run dir for this run.
- Orchestrator completed normally.

- [ ] **Step 5: Commit (in skill repo if available)**

```bash
cd ~/.claude/skills/kws-claude-multi-agent-executor && \
git add -A && \
git commit -m "feat(kws-cme): cutover to AgentLens-only event logging (remove append_learning_event.py)"
```

---

# Phase 3 — kws-codex-plan-executor migration

### Task 23: kws-cpe SKILL.md — add orchestration run-open hook

**Files:**
- Modify: `~/.claude/skills/kws-codex-plan-executor/SKILL.md`

- [ ] **Step 1: Locate run init point**

Run: `grep -n "init-run\|state.json" ~/.claude/skills/kws-codex-plan-executor/SKILL.md | head -10`

- [ ] **Step 2: Insert run-open block at run init**

Right before any `.codex-orchestrator/state.json` initial write:

```bash
ORCH_RUN_ID="$(agentlens run-open \
  --agent kws-cpe-orchestrator \
  --workspace "$REPO" \
  --meta plan="$PLAN" 2>/dev/null || echo "")"
```

- [ ] **Step 3: Persist into state.json**

Add `"agentlens_orchestration_run": "<ORCH_RUN_ID>"` field to the state.json shape documented in SKILL.md.

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/skills/kws-codex-plan-executor && \
git add SKILL.md && \
git commit -m "feat(kws-cpe): add AgentLens orchestration run-open at run init"
```

---

### Task 24: kws-cpe SKILL.md — propagate AGENTLENS_PARENT_RUN_ID + dual-write events

**Files:**
- Modify: `~/.claude/skills/kws-codex-plan-executor/SKILL.md`

- [ ] **Step 1: Find codex exec spawn points**

Run: `grep -n "codex exec\|codex_exec" ~/.claude/skills/kws-codex-plan-executor/SKILL.md`

- [ ] **Step 2: Prefix each codex exec with the env var**

```bash
AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID" codex exec ...
```

- [ ] **Step 3: Locate all `append_run_event.py` calls**

Run: `grep -n "append_run_event" ~/.claude/skills/kws-codex-plan-executor/SKILL.md`

- [ ] **Step 4: Add dual-write next to each call**

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append \
    --run "$ORCH_RUN_ID" \
    --type "kws-cpe.<event_name>" \
    --payload-json '<same payload>' 2>/dev/null || true
fi
```

Event taxonomy (mirror legacy event types):
- `kws-cpe.run_started`, `kws-cpe.context_snapshot_created`, `kws-cpe.pre_dispatch_checked`
- `kws-cpe.dispatch_gate_failed`, `kws-cpe.task_contract_recorded`
- `kws-cpe.task_started`, `kws-cpe.task_completed`
- `kws-cpe.verification_started`, `kws-cpe.verification_passed`, `kws-cpe.verification_failed`
- `kws-cpe.drift_detected`, `kws-cpe.drift_repaired`
- `kws-cpe.blocked`, `kws-cpe.failed`, `kws-cpe.finished`

- [ ] **Step 5: Add run-close at run completion**

Right before the orchestrator marks the run finished:

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens run-close --run "$ORCH_RUN_ID" --exit-code "$EXIT" 2>/dev/null || true
fi
```

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/skills/kws-codex-plan-executor && \
git add SKILL.md && \
git commit -m "feat(kws-cpe): dual-write AgentLens events + propagate PARENT_RUN_ID"
```

---

### Task 25: kws-cpe dual-write validation (1-week observation)

**Files:**
- Create: `AgentLens/scripts/compare_kws_cpe_logs.py`

- [ ] **Step 1: Copy Task 21 compare script, adapt for kws-cpe taxonomy**

```python
"""Compare legacy kws-cpe events.jsonl against AgentLens event log."""
import json, sys, subprocess
from pathlib import Path

legacy_path = Path(sys.argv[1])  # .codex-orchestrator/runs/<id>/events.jsonl
orch_run_id = sys.argv[2]

legacy = [json.loads(l) for l in legacy_path.read_text().splitlines() if l.strip()]
res = subprocess.run(
    ["agentlens", "events", "--run", orch_run_id],
    capture_output=True, text=True, check=True,
)
agentlens = [json.loads(l) for l in res.stdout.splitlines() if l.strip()]

print(f"legacy={len(legacy)} agentlens={len(agentlens)}")
legacy_types = sorted(e.get("event_type", e.get("type", "?")) for e in legacy)
agent_types = sorted(e["type"].split(".", 1)[1] for e in agentlens
                     if e["type"].startswith("kws-cpe."))
mismatch = set(legacy_types) ^ set(agent_types)
if mismatch:
    print(f"MISMATCH: {mismatch}")
    sys.exit(1)
print("OK — event taxonomies match")
```

- [ ] **Step 2: Run a real kws-cpe plan, compare**

Pick a small codex plan, run it, then:

```bash
agentlens events --run "$ORCH_RUN_ID" > /tmp/al.jsonl
python AgentLens/scripts/compare_kws_cpe_logs.py \
  .codex-orchestrator/runs/<id>/events.jsonl "$ORCH_RUN_ID"
```

Expected: "OK — event taxonomies match"

- [ ] **Step 3: Wait 1 week of dual-write, fix any mismatches in SKILL.md mapping**

- [ ] **Step 4: Commit script**

```bash
git add AgentLens/scripts/compare_kws_cpe_logs.py
git commit -m "test(agentlens): dual-write compare script for kws-cpe migration"
```

---

### Task 26: kws-cpe cutover — remove legacy logging

**Files:**
- Modify: `~/.claude/skills/kws-codex-plan-executor/SKILL.md`
- Delete: `~/.claude/skills/kws-codex-plan-executor/scripts/append_run_event.py`

- [ ] **Step 1: Remove `python scripts/append_run_event.py ...` lines**

Run: `grep -n "append_run_event" ~/.claude/skills/kws-codex-plan-executor/SKILL.md`
Delete each line invoking the legacy script.

- [ ] **Step 2: Delete script file**

```bash
rm ~/.claude/skills/kws-codex-plan-executor/scripts/append_run_event.py
```

- [ ] **Step 3: Update SKILL.md `.codex-orchestrator/runs/<id>/events.jsonl` references**

Remove or rewrite to point at `agentlens events --run "$ORCH_RUN_ID"`.

- [ ] **Step 4: Run a final smoke plan**

Confirm:
- `agentlens events --run <ORCH_RUN_ID>` shows all events.
- `.codex-orchestrator/runs/<id>/events.jsonl` is NOT created.

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/skills/kws-codex-plan-executor && \
git add -A && \
git commit -m "feat(kws-cpe): cutover to AgentLens-only event logging (remove append_run_event.py)"
```

---

### Task 27: Final integration — cross-skill query smoke

**Files:** none (manual verification)

- [ ] **Step 1: Run one kws-cme plan and one kws-cpe plan back to back**

After both complete:

```bash
# Show all orchestrator runs from today.
agentlens latest --limit 20

# Cross-skill: every verification_failed event in the last 24h.
agentlens events --since "$(date -u -v-24H +%Y-%m-%dT%H:%M:%SZ)" \
  --type '*.verification_failed'

# Single run tree (orchestration + spawned subprocesses).
agentlens events --run <ORCH_RUN_ID> --tree
```

Expected: events from both `kws-cme.*` and `kws-cpe.*` namespaces interleaved correctly.

- [ ] **Step 2: Tag the migration complete**

```bash
git tag -a agentlens-v1.1.0 -m "v1.1: kws-cme + kws-cpe migration complete"
git push origin main agentlens-v1.0.0 agentlens-v1.1.0
```

---

## Self-Review Notes

Coverage check against spec:
- §3 Architecture (container vs capture runs) → Tasks 1, 2, 4
- §4.1 Schema (`parent_run_id` exists; `has_transcript` new) → Task 1
- §4.2 `run open` → Tasks 2, 3
- §4.2 `event append` → Tasks 5, 6
- §4.2 `events` query → Task 8
- §4.2 `import claude-session` → Tasks 13, 14
- §4.4 `AGENTLENS_PARENT_RUN_ID` env → Tasks 9, 10
- §4.5 Shim TTY-detect → Task 12
- §4.6 cmux auto-chain → Tasks 15, 16
- §5 Interactive Claude Code (post-session ingest) → Tasks 13, 14
- §6 kws-cme changes → Tasks 18-22
- §7 kws-cpe changes → Tasks 23-26
- §8 Failure modes (non-blocking) → Covered in Tasks 4, 5 (unknown run_id exits 0)
- §9 Migration plan (dual-write) → Tasks 21, 25
- §10 Test surface → Tasks 17, 21, 25, 27

Deferred (explicitly out of scope per spec §12):
- `agentlens daemon` watcher — manual `agentlens import claude-session --latest` covers the use case.
- `accumulate_cost.py` unification.
- Historical event log import.

Type/method consistency check passed — `index_db_path`, `agentlens_home`, `resolve_run_dir`, `append_event`, `init_db`, `index_run` all referenced consistently across tasks.

## Execution Handoff

Plan complete and saved to `AgentLens/docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
