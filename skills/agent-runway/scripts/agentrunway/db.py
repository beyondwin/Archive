from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import AGENTRUNWAY_VERSION, TaskSpec


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, repo_root TEXT NOT NULL, plan_path TEXT NOT NULL,
  spec_path TEXT, contract_path TEXT, plan_hash TEXT NOT NULL, spec_hash TEXT, base_commit_sha TEXT NOT NULL,
  model_profile TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'created', allowed_dirty INTEGER NOT NULL DEFAULT 0,
  apply_to_source INTEGER NOT NULL DEFAULT 0, agentlens_run_id TEXT, agentlens_status TEXT NOT NULL DEFAULT 'disabled',
  agentrunway_version TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY, title TEXT NOT NULL, risk TEXT NOT NULL, phase TEXT NOT NULL,
  dependencies_json TEXT NOT NULL, spec_refs_json TEXT NOT NULL, acceptance_commands_json TEXT NOT NULL,
  resource_keys_json TEXT NOT NULL, required_skills_json TEXT NOT NULL, serial INTEGER NOT NULL,
  objective TEXT NOT NULL, line INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS task_packets (task_id TEXT PRIMARY KEY, packet_hash TEXT NOT NULL, prompt_path TEXT NOT NULL, packet_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS file_claims (task_id TEXT NOT NULL, path TEXT NOT NULL, mode TEXT NOT NULL, PRIMARY KEY(task_id, path, mode));
CREATE TABLE IF NOT EXISTS waves (wave_index INTEGER NOT NULL, task_id TEXT NOT NULL, PRIMARY KEY(wave_index, task_id));
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
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT, direction TEXT NOT NULL, message_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, worker_id TEXT, kind TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
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
CREATE TABLE IF NOT EXISTS applied_commits (
  run_id TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  strategy TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(run_id, commit_sha)
);
CREATE TABLE IF NOT EXISTS agentlens_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS cost_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT, runtime TEXT, model TEXT, tokens_input INTEGER, tokens_output INTEGER, cost_usd REAL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS method_audits (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT NOT NULL, task_id TEXT NOT NULL, status TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS context_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS worktree_registry (path TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, run_id TEXT NOT NULL, branch TEXT NOT NULL, lifecycle TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS resource_locks (run_id TEXT NOT NULL, resource_key TEXT NOT NULL, task_id TEXT NOT NULL, PRIMARY KEY(run_id, resource_key, task_id));
CREATE TABLE IF NOT EXISTS watchdog_events (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT, action TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
"""


class AgentRunwayDb:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path) -> "AgentRunwayDb":
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        db = cls(conn)
        db._drop_legacy_merge_queue()
        db.conn.executescript(SCHEMA_SQL)
        db._ensure_runs_contract_path_column()
        db.conn.commit()
        return db

    def _drop_legacy_merge_queue(self) -> None:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='merge_queue'"
        ).fetchone()
        if row is None:
            return
        columns = {str(item["name"]) for item in self.conn.execute("PRAGMA table_info(merge_queue)").fetchall()}
        expected = {"commits_json", "changed_files_json", "merge_attempts"}
        if not expected.issubset(columns):
            self.conn.execute("DROP TABLE merge_queue")

    def table_names(self) -> set[str]:
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(row["name"]) for row in rows}

    def _ensure_runs_contract_path_column(self) -> None:
        columns = {
            str(item["name"])
            for item in self.conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        if "contract_path" not in columns:
            self.conn.execute("ALTER TABLE runs ADD COLUMN contract_path TEXT")
            self.conn.commit()

    def create_run(self, **fields: Any) -> None:
        payload = {
            "run_id": fields["run_id"],
            "workspace_id": fields["workspace_id"],
            "repo_root": fields["repo_root"],
            "plan_path": fields["plan_path"],
            "spec_path": fields.get("spec_path"),
            "plan_hash": fields["plan_hash"],
            "spec_hash": fields.get("spec_hash"),
            "base_commit_sha": fields["base_commit_sha"],
            "model_profile": fields["model_profile"],
            "allowed_dirty": int(bool(fields.get("allowed_dirty", False))),
            "apply_to_source": int(bool(fields.get("apply_to_source", False))),
            "agentrunway_version": AGENTRUNWAY_VERSION,
        }
        self.conn.execute(
            """
            INSERT INTO runs (run_id, workspace_id, repo_root, plan_path, spec_path, plan_hash, spec_hash, base_commit_sha, model_profile, allowed_dirty, apply_to_source, agentrunway_version)
            VALUES (:run_id, :workspace_id, :repo_root, :plan_path, :spec_path, :plan_hash, :spec_hash, :base_commit_sha, :model_profile, :allowed_dirty, :apply_to_source, :agentrunway_version)
            """,
            payload,
        )
        self.conn.commit()

    def set_run_status(self, run_id: str, status: str) -> None:
        self.conn.execute("UPDATE runs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?", (status, run_id))
        self.conn.commit()

    def set_run_contract_path(self, run_id: str, contract_path: str) -> None:
        self.conn.execute(
            "UPDATE runs SET contract_path=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            (contract_path, run_id),
        )
        self.conn.commit()

    def insert_event(self, *, event_type: str, payload: dict[str, Any], status: str, error: str | None = None) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO agentlens_events (event_type, payload_json, status, error)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, json.dumps(payload, ensure_ascii=False, sort_keys=True), status, error),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def list_events(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM agentlens_events ORDER BY id").fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["payload"] = json.loads(data.pop("payload_json"))
            events.append(data)
        return events

    def agentlens_summary(self) -> dict[str, Any]:
        rows = self.list_events()
        failed = [row for row in rows if row["status"] == "agentlens_failed"]
        emitted = [row for row in rows if row["status"] == "agentlens_emitted"]
        return {
            "events": len(rows),
            "emitted": len(emitted),
            "failed": len(failed),
            "last_status": rows[-1]["status"] if rows else "none",
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def upsert_task(self, task: TaskSpec) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tasks
              (task_id, title, risk, phase, dependencies_json, spec_refs_json, acceptance_commands_json, resource_keys_json, required_skills_json, serial, objective, line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.title,
                task.risk,
                task.phase,
                json.dumps(list(task.dependencies)),
                json.dumps(list(task.spec_refs)),
                json.dumps(list(task.acceptance_commands)),
                json.dumps(list(task.resource_keys)),
                json.dumps(list(task.required_skills)),
                int(task.serial),
                task.objective,
                task.line,
            ),
        )
        for claim in task.file_claims:
            self.conn.execute(
                "INSERT OR REPLACE INTO file_claims (task_id, path, mode) VALUES (?, ?, ?)",
                (task.task_id, claim.path, claim.mode),
            )
        self.conn.commit()

    def set_task_status(self, task_id: str, status: str) -> None:
        self.conn.execute("UPDATE tasks SET status=? WHERE task_id=?", (status, task_id))
        self.conn.commit()

    def insert_packet(self, task_id: str, packet_hash: str, prompt_path: str, packet_json: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO task_packets (task_id, packet_hash, prompt_path, packet_json) VALUES (?, ?, ?, ?)",
            (task_id, packet_hash, prompt_path, packet_json),
        )
        self.conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return dict(row)

    def list_tasks(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM tasks ORDER BY task_id")]

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

    def list_workers(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM workers ORDER BY worker_id").fetchall()
        workers: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["handle_json"] = json.loads(data["handle_json"])
            workers.append(data)
        return workers

    def count_worker_attempts(self, *, task_id: str, role: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM workers WHERE task_id=? AND role=?",
            (task_id, role),
        ).fetchone()
        return int(row["count"])

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
