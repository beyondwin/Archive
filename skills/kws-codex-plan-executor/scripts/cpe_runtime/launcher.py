"""Bounded fresh-process launcher for one sequential CPE plan."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


_SECRETS = {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN", "GITHUB_TOKEN",
}


@dataclass(frozen=True)
class LaunchResult:
    payload: dict[str, object] | None
    returncode: int | None
    timed_out: bool
    result_path: Path
    log_path: Path


class CodexLauncher:
    def __init__(
        self,
        *,
        schema_path: Path,
        codex_bin: str = "codex",
        timeout_seconds: float = 3600,
        environ: Mapping[str, str] | None = None,
        log_limit_bytes: int = 1_000_000,
    ) -> None:
        try:
            self.schema_path = schema_path.resolve(strict=True)
            schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("plan result schema is unavailable or invalid") from exc
        if not self.schema_path.is_file() or self.schema_path.is_symlink() or schema.get("additionalProperties") is not False:
            raise ValueError("plan result schema must be a strict regular file")
        if not codex_bin or timeout_seconds <= 0 or log_limit_bytes <= 0:
            raise ValueError("launcher configuration is invalid")
        self.codex_bin = codex_bin
        self.timeout_seconds = float(timeout_seconds)
        self.environ = dict(os.environ if environ is None else environ)
        self.log_limit_bytes = log_limit_bytes

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

    @staticmethod
    def _prompt(
        *,
        worktree: Path,
        plan_id: str,
        plan_path: Path,
        spec_paths: Sequence[Path],
        starting_commit: str,
        current_commit: str,
        result_path: Path,
        prior_result: Path | None,
        prior_log: Path | None,
    ) -> str:
        lines = [
            "Execute one approved implementation plan in the isolated worktree.",
            f"REPOSITORY: {worktree}",
            f"WORKTREE: {worktree}",
            f"PLAN_ID: {plan_id}",
            f"CURRENT_PLAN: {plan_path}",
            f"STARTING_COMMIT: {starting_commit}",
            f"CURRENT_COMMIT: {current_commit}",
            f"RESULT_PATH: {result_path}",
            "SPECIFICATIONS_IN_ORDER:",
        ]
        lines.extend(f"- {path}" for path in spec_paths)
        if prior_result is not None:
            lines.append(f"PRIOR_RESULT: {prior_result}")
        if prior_log is not None:
            lines.append(f"PRIOR_LOG: {prior_log}")
        lines.extend(
            [
                "",
                "Discover and follow repository AGENTS.md instructions from root to the edited subtree.",
                "Use the Superpowers workflow declared by the plan. Complete implementation, review, fixes, verification, and commits before reporting completed.",
                "For completed, leave the worktree fully clean, report its exact HEAD, and include at least one successful verification command.",
                "Write only the fixed schema result to RESULT_PATH. Do not merge, push, deploy, or modify files outside the worktree and result directory.",
            ]
        )
        return "\n".join(lines) + "\n"

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
        command = [
            self.codex_bin, "exec", "--ignore-user-config", "--json",
            "--sandbox", "workspace-write", "-C", str(worktree),
            "--add-dir", str(result_path.parent), "--output-schema", str(self.schema_path),
            "--output-last-message", str(result_path), "-",
        ]
        prompt = self._prompt(
            worktree=worktree, plan_id=plan_id, plan_path=plan_path,
            spec_paths=spec_paths, starting_commit=starting_commit,
            current_commit=current_commit, result_path=result_path,
            prior_result=prior_result, prior_log=prior_log,
        )
        environment = {key: value for key, value in self.environ.items() if key not in _SECRETS}
        returncode: int | None = None
        timed_out = False
        with log_path.open("wb") as log:
            try:
                completed = subprocess.run(
                    command, input=prompt, text=True, stdout=log, stderr=subprocess.STDOUT,
                    timeout=self.timeout_seconds, start_new_session=True, env=environment,
                    pass_fds=(lock_fd,), check=False,
                )
                returncode = completed.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
        log_path.chmod(0o600)
        if log_path.stat().st_size > self.log_limit_bytes:
            tail = log_path.read_bytes()[-self.log_limit_bytes :]
            log_path.write_bytes(tail)
            log_path.chmod(0o600)

        payload = None
        if result_path.is_file() and not result_path.is_symlink():
            try:
                candidate = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    payload = candidate
                result_path.chmod(0o600)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        return LaunchResult(payload, returncode, timed_out, result_path, log_path)
