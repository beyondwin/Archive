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
  spec_path TEXT, plan_hash TEXT NOT NULL, spec_hash TEXT, base_commit_sha TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS workers (worker_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, role TEXT NOT NULL, runtime TEXT NOT NULL, model TEXT NOT NULL, reasoning_effort TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT, direction TEXT NOT NULL, message_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, worker_id TEXT, kind TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS merge_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, worker_id TEXT NOT NULL, commit_sha TEXT, patch_path TEXT, status TEXT NOT NULL);
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
        db.conn.executescript(SCHEMA_SQL)
        db.conn.commit()
        return db

    def table_names(self) -> set[str]:
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(row["name"]) for row in rows}

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
