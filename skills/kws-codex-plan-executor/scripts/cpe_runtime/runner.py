"""Single-worktree sequential execution and plan-level resume."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Sequence

from .launcher import CodexLauncher, LaunchResult
from .state import StateStore


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RESULT_FIELDS = {"plan_id", "status", "head_commit", "verification", "summary"}


def _git(repository: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments], check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


class SequentialRunner:
    def __init__(
        self,
        *,
        codex_home: Path | None = None,
        launcher: CodexLauncher | None = None,
    ) -> None:
        self.codex_home = (codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))).expanduser().resolve()
        schema = Path(__file__).resolve().parents[2] / "templates" / "plan-result-schema.json"
        self.launcher = launcher or CodexLauncher(schema_path=schema)

    def run(
        self,
        *,
        workspace: Path,
        specs: Sequence[Path],
        plans: Sequence[Path],
        run_id: str | None = None,
    ) -> dict[str, Any]:
        identifier = run_id or f"cpe-{uuid.uuid4().hex[:16]}"
        if not _RUN_ID.fullmatch(identifier):
            raise ValueError("run ID contains unsupported characters")
        repository = workspace.resolve(strict=True)
        if not repository.is_dir() or _git(repository, "rev-parse", "--is-inside-work-tree") != "true":
            raise ValueError("workspace must be a Git repository")
        if _git(repository, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("workspace has tracked changes")
        source_commit = _git(repository, "rev-parse", "HEAD")
        run_root = self.codex_home / "orchestrator" / identifier
        worktree = self.codex_home / "worktrees" / identifier
        branch = f"codex/{identifier}"
        store = StateStore.create(
            run_root=run_root, run_id=identifier, source_repository=repository,
            source_commit=source_commit, worktree=worktree, branch=branch,
            specs=specs, plans=plans,
        )
        worktree.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        worktree.parent.chmod(0o700)
        if worktree.exists():
            raise ValueError("run worktree already exists")
        subprocess.run(
            ["git", "-C", str(repository), "worktree", "add", "-q", "-b", branch, str(worktree), source_commit],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        store.append_event("worktree.created", head=source_commit)
        try:
            return self._execute(store, explicit_retry=False)
        except KeyboardInterrupt:
            store.state["status"] = "interrupted"
            store.save()
            store.append_event("run.interrupted", plan_index=store.state["current_plan_index"])
            return self._summary(store)

    def resume(self, *, run_id: str, retry_failed: bool = False) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run ID contains unsupported characters")
        store = StateStore.open(self.codex_home / "orchestrator" / run_id)
        self._verify_worktree(store)
        status = store.state["status"]
        if status == "completed":
            if retry_failed:
                raise ValueError("retry-failed requires a failed run")
            return self._summary(store)
        if retry_failed != (status == "failed"):
            if status == "failed":
                raise ValueError("failed run requires --retry-failed")
            if retry_failed:
                raise ValueError("retry-failed requires a failed run")
        store.state["status"] = "running"
        store.save()
        store.append_event("run.resumed", retry_failed=retry_failed)
        try:
            return self._execute(store, explicit_retry=retry_failed)
        except KeyboardInterrupt:
            store.state["status"] = "interrupted"
            store.save()
            store.append_event("run.interrupted", plan_index=store.state["current_plan_index"])
            return self._summary(store)

    def inspect(self, *, run_id: str) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run ID contains unsupported characters")
        store = StateStore.open(self.codex_home / "orchestrator" / run_id)
        return self._summary(store)

    def _execute(self, store: StateStore, *, explicit_retry: bool) -> dict[str, Any]:
        state = store.state
        while state["current_plan_index"] < len(state["plans"]):
            index = state["current_plan_index"]
            plan = state["plans"][index]
            if plan["status"] == "completed":
                state["current_plan_index"] += 1
                store.save()
                continue
            allowed_attempts = plan["attempt_count"] + 1 if explicit_retry else max(2, plan["attempt_count"] + (1 if plan["status"] == "blocked" else 0))
            explicit_retry = False
            while plan["attempt_count"] < allowed_attempts:
                worktree = Path(state["worktree"])
                current_head = _git(worktree, "rev-parse", "HEAD")
                if plan["starting_commit"] is None:
                    plan["starting_commit"] = current_head
                prior_result = Path(plan["result_path"]) if plan["result_path"] else None
                prior_log = self._latest_log(store, plan["plan_id"])
                plan["attempt_count"] += 1
                plan["status"] = "running"
                state["status"] = "running"
                store.save()
                store.append_event("plan.attempt_started", plan_id=plan["plan_id"], attempt=plan["attempt_count"], head=current_head)
                plan_input = next(record for record in state["inputs"] if record["document_id"] == plan["plan_id"])
                spec_paths = [Path(record["snapshot_path"]) for record in state["inputs"] if record["role"] == "spec"]
                outcome = self.launcher.launch(
                    worktree=worktree, plan_id=plan["plan_id"], plan_path=Path(plan_input["snapshot_path"]),
                    spec_paths=spec_paths, starting_commit=plan["starting_commit"], current_commit=current_head,
                    results_directory=store.root / "results", logs_directory=store.root / "logs",
                    attempt=plan["attempt_count"], prior_result=prior_result, prior_log=prior_log,
                )
                plan["result_path"] = str(outcome.result_path.resolve()) if outcome.result_path.exists() else str(self._synthetic_result(store, plan, outcome))
                integrity_error = self._handoff_error(store, plan, outcome)
                if integrity_error is not None:
                    plan["status"] = "failed"
                    state["status"] = "failed"
                    store.save()
                    store.append_event("plan.integrity_failed", plan_id=plan["plan_id"], reason=integrity_error)
                    return self._summary(store, error=integrity_error)
                payload = outcome.payload
                assert payload is not None
                status = payload["status"]
                if status == "completed":
                    plan["status"] = "completed"
                    plan["accepted_commit"] = payload["head_commit"]
                    state["current_plan_index"] += 1
                    store.save()
                    store.append_event("plan.completed", plan_id=plan["plan_id"], head=payload["head_commit"])
                    break
                plan["status"] = status
                if status == "blocked":
                    state["status"] = "blocked"
                    store.save()
                    store.append_event("plan.blocked", plan_id=plan["plan_id"])
                    return self._summary(store)
                store.save()
                store.append_event("plan.attempt_incomplete", plan_id=plan["plan_id"], status=status)
            else:
                plan["status"] = "failed"
                state["status"] = "failed"
                store.save()
                store.append_event("plan.failed", plan_id=plan["plan_id"], attempts=plan["attempt_count"])
                return self._summary(store)

        state["status"] = "completed"
        store.save()
        store.append_event("run.completed", head=_git(Path(state["worktree"]), "rev-parse", "HEAD"))
        return self._summary(store)

    def _handoff_error(self, store: StateStore, plan: dict[str, Any], outcome: LaunchResult) -> str | None:
        payload = outcome.payload
        if payload is None or set(payload) != _RESULT_FIELDS:
            return "invalid_result"
        if payload.get("plan_id") != plan["plan_id"] or payload.get("status") not in {"completed", "interrupted", "blocked", "failed"}:
            return "invalid_result"
        head = payload.get("head_commit")
        summary = payload.get("summary")
        verification = payload.get("verification")
        if not isinstance(head, str) or not _SHA.fullmatch(head) or not isinstance(summary, str) or not summary.strip() or len(summary) > 2000 or not isinstance(verification, list):
            return "invalid_result"
        for item in verification:
            if not isinstance(item, dict) or set(item) != {"command", "exit_code"} or not isinstance(item["command"], str) or not item["command"].strip() or not isinstance(item["exit_code"], int) or isinstance(item["exit_code"], bool):
                return "invalid_result"
        if payload["status"] != "completed":
            return None
        worktree = Path(store.state["worktree"])
        observed = _git(worktree, "rev-parse", "HEAD")
        if head != observed:
            return "wrong_head"
        ancestry = subprocess.run(["git", "-C", str(worktree), "merge-base", "--is-ancestor", plan["starting_commit"], head], check=False).returncode
        if ancestry != 0:
            return "broken_ancestry"
        if _git(worktree, "status", "--porcelain", "--untracked-files=all"):
            return "dirty_handoff"
        if not verification or any(item["exit_code"] != 0 for item in verification):
            return "verification_failed"
        return None

    def _verify_worktree(self, store: StateStore) -> None:
        state = store.state
        worktree = Path(state["worktree"])
        if not worktree.is_dir() or _git(worktree, "rev-parse", "--show-toplevel") != str(worktree.resolve()):
            raise ValueError("recorded worktree is missing or changed")
        if _git(worktree, "branch", "--show-current") != state["branch"]:
            raise ValueError("recorded worktree branch changed")
        current_head = _git(worktree, "rev-parse", "HEAD")
        if subprocess.run(
            ["git", "-C", str(worktree), "merge-base", "--is-ancestor", state["source_commit"], current_head],
            check=False,
        ).returncode != 0:
            raise ValueError("worktree HEAD no longer descends from the source commit")
        for plan in state["plans"]:
            if plan["status"] == "completed":
                if subprocess.run(["git", "-C", str(worktree), "merge-base", "--is-ancestor", plan["accepted_commit"], "HEAD"], check=False).returncode != 0:
                    raise ValueError("accepted plan commit is not in worktree history")
            elif plan["starting_commit"] is not None and subprocess.run(
                ["git", "-C", str(worktree), "merge-base", "--is-ancestor", plan["starting_commit"], current_head],
                check=False,
            ).returncode != 0:
                raise ValueError("current plan history no longer descends from its starting commit")

    @staticmethod
    def _latest_log(store: StateStore, plan_id: str) -> Path | None:
        matches = sorted((store.root / "logs").glob(f"{plan_id}-attempt-*.log"))
        return matches[-1] if matches else None

    @staticmethod
    def _synthetic_result(store: StateStore, plan: dict[str, Any], outcome: LaunchResult) -> Path:
        target = store.root / "results" / f"{plan['plan_id']}-attempt-{plan['attempt_count']}-synthetic.json"
        worktree = Path(store.state["worktree"])
        observed = _git(worktree, "rev-parse", "HEAD") if worktree.is_dir() else store.state["source_commit"]
        payload = {
            "plan_id": plan["plan_id"], "status": "failed", "head_commit": observed,
            "verification": [],
            "summary": f"child produced no valid result; returncode={outcome.returncode}; timed_out={outcome.timed_out}; log={outcome.log_path}",
        }
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        target.chmod(0o600)
        return target.resolve()

    @staticmethod
    def _summary(store: StateStore, *, error: str | None = None) -> dict[str, Any]:
        state = store.state
        worktree = Path(state["worktree"])
        head = _git(worktree, "rev-parse", "HEAD") if worktree.is_dir() else state["source_commit"]
        result = {
            "run_id": state["run_id"], "status": state["status"], "source_commit": state["source_commit"],
            "worktree": state["worktree"], "branch": state["branch"], "head_commit": head,
            "current_plan_index": state["current_plan_index"],
            "plans": [
                {key: plan[key] for key in ("plan_id", "status", "starting_commit", "accepted_commit", "attempt_count", "result_path")}
                for plan in state["plans"]
            ],
        }
        if error:
            result["error"] = error
        return result
