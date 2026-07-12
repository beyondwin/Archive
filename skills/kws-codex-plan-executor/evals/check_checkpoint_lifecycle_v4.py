#!/usr/bin/env python3
"""Deterministic lifecycle checks for CPE v4 candidate checkpoints."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.checkpoints import (
    create_candidate_checkpoint,
    promote_verified_checkpoint,
)
try:
    from cpe_runtime.checkpoints import ReviewEvidence, create_review_evidence
except ImportError:
    ReviewEvidence = None
    create_review_evidence = None
from cpe_runtime.task_contracts import compile_task_contract
from cpe_runtime.verification_workspace import run_acceptance, verification_worktree


HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")


class MemoryKernel:
    def __init__(self, source_head: str):
        self._state = {
            "source_head": source_head,
            "checkpoint_head": None,
            "candidate_checkpoints": [],
            "verified_checkpoints": [],
        }
        self.transitions = []

    @property
    def state(self) -> dict:
        return self._state

    def transition(self, command):
        self.transitions.append(command)
        record = {"task_id": command.task_id, **command.payload}
        if command.event_type == "candidate.checkpoint_recorded":
            self._state["candidate_checkpoints"].append(record)
        elif command.event_type == "task.checkpoint_verified":
            self._state["verified_checkpoints"].append(record)
            self._state["checkpoint_head"] = command.payload["commit"]
        return self._state


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def init_repo(root: Path) -> tuple[Path, str]:
    repo = root / "product"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "outside.txt").write_text("outside\n", encoding="utf-8")
    (repo / "build.py").write_text(
        """from pathlib import Path
import os
Path('dist').mkdir()
Path('dist/result.txt').write_text('ok\\n')
print(os.environ.get('HOME', ''))
print(os.environ.get('CPE_TEST_SECRET', ''))
raise SystemExit(0 if 'CPE_TEST_SECRET' not in os.environ else 9)
""",
        encoding="utf-8",
    )
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    git(repo, "commit", "-q", "-m", "bootstrap", env=commit_env)
    return repo, git(repo, "rev-parse", "HEAD")


def contract(*, claims: tuple[str, ...] = ("app.py",), variant: str = "base"):
    return compile_task_contract(
        {
            "id": "T3",
            "title": f"candidate checkpoint {variant}",
            "task_type": "tdd_implementation",
            "task_source": f"### Task 3: candidate checkpoint {variant}\n",
            "file_claims": list(claims),
            "acceptance_commands": ["python3 build.py"],
            "checkpoint_message": "feat: candidate",
        },
        source_hashes={"plan": "f" * 64, "spec_sections": {}},
    )


def assert_raises_text(error_type: type[BaseException], expected: str, operation) -> None:
    try:
        operation()
    except error_type as exc:
        assert str(exc) == expected, (str(exc), expected)
    else:
        raise AssertionError(f"expected {error_type.__name__}: {expected}")


def check_candidate_and_disposable_acceptance(root: Path) -> None:
    repo, source_head = init_repo(root)
    task_contract = contract()
    kernel = MemoryKernel(source_head)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    candidate = create_candidate_checkpoint(kernel, task_contract, repo)
    assert HEX40.fullmatch(candidate.commit)
    assert candidate.predecessor == source_head
    assert candidate.contract_sha256 == task_contract.contract_sha256
    assert kernel.transitions[0].payload["contract_sha256"] == task_contract.contract_sha256
    assert git(repo, "rev-parse", f"{candidate.commit}^") == source_head
    assert candidate.changed_files == ("app.py",)
    assert HEX64.fullmatch(candidate.patch_sha256)
    assert git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert git(repo, "show", "-s", "--format=%an <%ae>", candidate.commit) == (
        "CPE Executor <cpe@example.invalid>"
    )

    run_dir = root / "run"
    secret_home = root / "private-home"
    secret_oracle = root / "private-oracle.json"
    acceptance_env = {
        **os.environ,
        "HOME": str(secret_home),
        "ORACLE_PATH": str(secret_oracle),
        "CPE_TEST_SECRET": "credential-value",
    }
    with verification_worktree(repo, candidate.commit, run_dir, task_contract.task_id) as checkout:
        assert checkout.is_relative_to(run_dir.resolve())
        results = run_acceptance(task_contract.acceptance_commands, checkout, acceptance_env)
        assert (checkout / "dist" / "result.txt").is_file()
    assert results[0].exit_code == 0
    assert HEX64.fullmatch(results[0].stdout_sha256)
    assert HEX64.fullmatch(results[0].stderr_sha256)
    assert not hasattr(results[0], "stdout") and not hasattr(results[0], "stderr")
    encoded = json.dumps(dataclasses.asdict(results[0]))
    assert str(secret_home) not in encoded
    assert str(secret_oracle) not in encoded
    assert "credential-value" not in encoded
    assert not checkout.exists()
    assert str(checkout) not in git(repo, "worktree", "list", "--porcelain")
    assert not (repo / "dist").exists()

    review = _review(candidate, task_contract)
    assert review is not None
    verified = promote_verified_checkpoint(
        kernel, task_contract, candidate, results, review
    )
    assert verified.predecessor == source_head
    assert verified.commit == candidate.commit
    assert verified.review_sha256 == review.artifact_sha256
    assert kernel.state["checkpoint_head"] == candidate.commit


def _review(candidate, task_contract):
    if create_review_evidence is None:
        return None
    return create_review_evidence(
        task_id=task_contract.task_id,
        candidate_commit=candidate.commit,
        contract_sha256=task_contract.contract_sha256,
        decision="approved",
        review_content_sha256="a" * 64,
    )


def _promotion_rejected(operation, expected: str) -> bool:
    try:
        operation()
    except ValueError as exc:
        return str(exc) == expected
    return False


def check_promotion_evidence_forgery(root: Path) -> list[str]:
    vulnerabilities: list[str] = []

    repo, source_head = init_repo(root / "contract-substitution")
    original = contract(variant="original")
    substituted = contract(variant="substituted")
    kernel = MemoryKernel(source_head)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    candidate = create_candidate_checkpoint(kernel, original, repo)
    with verification_worktree(repo, candidate.commit, root / "contract-run", "T3") as checkout:
        results = run_acceptance(original.acceptance_commands, checkout, os.environ)
    review = _review(candidate, original)
    operation = (
        (lambda: promote_verified_checkpoint(kernel, substituted, candidate, results))
        if review is None
        else (
            lambda: promote_verified_checkpoint(
                kernel, substituted, candidate, results, review
            )
        )
    )
    if not _promotion_rejected(operation, "candidate_contract_mismatch"):
        vulnerabilities.append("substituted_contract_promoted")

    repo, source_head = init_repo(root / "command-substitution")
    task_contract = contract()
    kernel = MemoryKernel(source_head)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    candidate = create_candidate_checkpoint(kernel, task_contract, repo)
    with verification_worktree(repo, candidate.commit, root / "command-run", "T3") as checkout:
        results = run_acceptance(("true",), checkout, os.environ)
    review = _review(candidate, task_contract)
    operation = (
        (lambda: promote_verified_checkpoint(kernel, task_contract, candidate, results))
        if review is None
        else (
            lambda: promote_verified_checkpoint(
                kernel, task_contract, candidate, results, review
            )
        )
    )
    if not _promotion_rejected(operation, "acceptance_command_mismatch"):
        vulnerabilities.append("undeclared_acceptance_promoted")

    repo, source_head = init_repo(root / "review-omission")
    task_contract = contract()
    kernel = MemoryKernel(source_head)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    candidate = create_candidate_checkpoint(kernel, task_contract, repo)
    with verification_worktree(repo, candidate.commit, root / "review-run", "T3") as checkout:
        results = run_acceptance(task_contract.acceptance_commands, checkout, os.environ)
    if not _promotion_rejected(
        lambda: promote_verified_checkpoint(kernel, task_contract, candidate, results),
        "review_evidence_missing",
    ):
        vulnerabilities.append("missing_review_promoted")
    if create_review_evidence is not None:
        mismatched = create_review_evidence(
            task_id=task_contract.task_id,
            candidate_commit=source_head,
            contract_sha256=task_contract.contract_sha256,
            decision="approved",
            review_content_sha256="b" * 64,
        )
        if not _promotion_rejected(
            lambda: promote_verified_checkpoint(
                kernel, task_contract, candidate, results, mismatched
            ),
            "review_evidence_mismatch",
        ):
            vulnerabilities.append("mismatched_review_promoted")
        unapproved = create_review_evidence(
            task_id=task_contract.task_id,
            candidate_commit=candidate.commit,
            contract_sha256=task_contract.contract_sha256,
            decision="changes_requested",
            review_content_sha256="c" * 64,
        )
        if not _promotion_rejected(
            lambda: promote_verified_checkpoint(
                kernel, task_contract, candidate, results, unapproved
            ),
            "review_not_approved",
        ):
            vulnerabilities.append("unapproved_review_promoted")
        tampered = dataclasses.replace(
            _review(candidate, task_contract), artifact_sha256="f" * 64
        )
        if not _promotion_rejected(
            lambda: promote_verified_checkpoint(
                kernel, task_contract, candidate, results, tampered
            ),
            "review_evidence_invalid",
        ):
            vulnerabilities.append("tampered_review_promoted")
    return vulnerabilities


def check_daemonized_child_is_bounded(root: Path) -> str | None:
    repo, commit = init_repo(root)
    run_dir = root / "run"
    with verification_worktree(repo, commit, run_dir, "T3") as checkout:
        (checkout / "daemon.py").write_text(
            """import subprocess
import sys
import time
subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
time.sleep(30)
""",
            encoding="utf-8",
        )
        driver = root / "driver.py"
        driver.write_text(
            f"""import os
import sys
from pathlib import Path
sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'scripts')!r})
import cpe_runtime.verification_workspace as workspace
workspace.ACCEPTANCE_TIMEOUT_SECONDS = 0.1
results = workspace.run_acceptance(('python3 daemon.py',), Path(sys.argv[1]), os.environ)
raise SystemExit(0 if results[0].exit_code == 124 else 3)
""",
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [sys.executable, str(driver), str(checkout)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            return "daemonized_acceptance_exceeded_deadline"
        if process.returncode != 0:
            return f"daemonized_acceptance_failed:{process.returncode}:{stdout!r}:{stderr!r}"
    return None


def check_rejections(root: Path) -> None:
    out_repo, out_head = init_repo(root / "out-of-claim")
    (out_repo / "outside.txt").write_text("changed\n", encoding="utf-8")
    assert_raises_text(
        ValueError,
        "out_of_claim_candidate:outside.txt",
        lambda: create_candidate_checkpoint(MemoryKernel(out_head), contract(), out_repo),
    )
    assert git(out_repo, "rev-parse", "HEAD") == out_head

    literal_repo, literal_head = init_repo(root / "literal-pathspec")
    literal_path = literal_repo / ":claim.txt"
    literal_path.write_text("literal pathspec\n", encoding="utf-8")
    literal_candidate = create_candidate_checkpoint(
        MemoryKernel(literal_head), contract(claims=(":claim.txt",)), literal_repo
    )
    assert literal_candidate.changed_files == (":claim.txt",)
    assert git(literal_repo, "status", "--porcelain=v1", "--untracked-files=all") == ""

    dirty_repo, dirty_head = init_repo(root / "dirty-after-commit")
    hook = Path(git(dirty_repo, "rev-parse", "--git-path", "hooks")) / "post-commit"
    if not hook.is_absolute():
        hook = dirty_repo / hook
    hook.write_text("#!/bin/sh\nprintf 'hook-dirty\\n' >> app.py\n", encoding="utf-8")
    hook.chmod(0o755)
    (dirty_repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert_raises_text(
        RuntimeError,
        "dirty_product_worktree_after_candidate_commit",
        lambda: create_candidate_checkpoint(MemoryKernel(dirty_head), contract(), dirty_repo),
    )

    repo, source_head = init_repo(root / "promotion")
    kernel = MemoryKernel(source_head)
    task_contract = contract()
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    candidate = create_candidate_checkpoint(kernel, task_contract, repo)
    with verification_worktree(repo, source_head, root / "stale-acceptance-run", "T3") as checkout:
        stale = run_acceptance(("python3 build.py",), checkout, os.environ)
    with verification_worktree(repo, candidate.commit, root / "promotion-run", "T3") as checkout:
        passed = run_acceptance(("python3 build.py",), checkout, os.environ)
        failed = run_acceptance(("python3 -c 'raise SystemExit(7)'",), checkout, os.environ)
    forged = dataclasses.replace(candidate, predecessor="0" * 40)
    review = _review(candidate, task_contract)
    assert review is not None
    assert_raises_text(
        ValueError,
        "non_direct_child_candidate",
        lambda: promote_verified_checkpoint(kernel, task_contract, forged, passed, review),
    )
    assert_raises_text(
        ValueError,
        "acceptance_revision_mismatch",
        lambda: promote_verified_checkpoint(kernel, task_contract, candidate, stale, review),
    )
    assert_raises_text(
        ValueError,
        "acceptance_failed",
        lambda: promote_verified_checkpoint(kernel, task_contract, candidate, failed, review),
    )


def check_cleanup_failure(root: Path) -> None:
    repo, commit = init_repo(root)
    run_dir = root / "run"
    checkout: Path | None = None
    try:
        with verification_worktree(repo, commit, run_dir, "T3") as checkout:
            git(repo, "worktree", "lock", "--reason", "lifecycle-test", str(checkout))
    except RuntimeError as exc:
        assert str(exc) == "evidence_integrity_failure"
    else:
        raise AssertionError("expected evidence_integrity_failure")
    assert checkout is not None and checkout.exists()
    git(repo, "worktree", "unlock", str(checkout))
    git(repo, "worktree", "remove", "--force", str(checkout))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-checkpoints-") as raw:
        root = Path(raw)
        check_candidate_and_disposable_acceptance(root / "lifecycle")
        check_rejections(root / "rejections")
        check_cleanup_failure(root / "cleanup")
        failures = check_promotion_evidence_forgery(root / "forgery")
        daemon_failure = check_daemonized_child_is_bounded(root / "daemon")
        if daemon_failure:
            failures.append(daemon_failure)
        assert not failures, f"checkpoint evidence vulnerabilities: {','.join(failures)}"
    print('{"passed": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
