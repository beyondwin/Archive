from __future__ import annotations

import subprocess
from pathlib import Path

from kao.events import build_event_payload, redact_payload
from kao.git_ops import Git
from kao.merge_queue import MergeCandidate, apply_candidate, validate_candidate_scope


def test_redaction_removes_home_paths_and_secret_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    payload = {"path": str(tmp_path / "secret.txt"), "token": "abc123", "nested": {"api_key": "hidden"}}
    redacted = redact_payload(payload)
    assert str(tmp_path) not in str(redacted)
    assert redacted["token"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"


def test_event_payload_has_namespace_schema_and_privacy() -> None:
    payload = build_event_payload("run-1", "planning", "success", "planned")
    assert payload["schema"] == "kws.kao.event.v1"
    assert payload["kao_run_id"] == "run-1"
    assert payload["privacy"]["redacted"] is True


def test_merge_candidate_scope_validation_and_apply(git_repo: Path, tmp_path: Path) -> None:
    git = Git(git_repo)
    worker = tmp_path / "worker"
    subprocess.run(["git", "worktree", "add", "-b", "worker/task", str(worker), "HEAD"], cwd=git_repo, check=True)
    (worker / "src.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.py"], cwd=worker, check=True)
    subprocess.run(["git", "commit", "-m", "worker"], cwd=worker, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worker, check=True, text=True, capture_output=True).stdout.strip()
    candidate = MergeCandidate(task_id="task_001", worker_id="w1", commits=(commit,), changed_files=("src.py",))
    validate_candidate_scope(candidate, ("src.py",))
    apply_candidate(git, candidate)
    assert (git_repo / "src.py").read_text(encoding="utf-8") == "print('ok')\n"
