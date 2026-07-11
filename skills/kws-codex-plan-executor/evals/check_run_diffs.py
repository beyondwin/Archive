#!/usr/bin/env python3
"""Deterministic checks for check_run_diffs.py."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.git_delta import capture_snapshot, diff_snapshots, scope_errors
from cpe_runtime.kernel import Kernel


RUN_ID = "diff-policy-20260519-143022"


def base_state(repo: Path, task_id: str = "task_0") -> dict:
    run_dir = repo / ".codex-test" / "orchestrator" / RUN_ID
    return {
        "schema_version": "1",
        "run_id": RUN_ID,
        "mode": "interactive",
        "workspace": str(repo),
        "plan": str(repo / "plan.md"),
        "branch": f"codex/{RUN_ID}",
        "worktree": str(repo / ".codex" / "worktrees" / RUN_ID),
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "current_task": task_id,
        "current_phase": "task_loop",
        "tasks": {
            task_id: {
                "status": "in_progress",
                "risk": "low",
                "files_declared": ["docs/allowed.md"],
                "contract": {
                    "scope": "Update allowed docs.",
                    "files_to_inspect": ["docs/allowed.md"],
                    "allowed_edits": ["docs/allowed.md"],
                    "forbidden_edits": ["docs/forbidden.md"],
                    "acceptance_command_or_honest_substitute": "python3 scripts/check_run_diffs.py",
                },
                "unit_manifest": {
                    "unit_type": "execute-task",
                    "context_mode": "focused",
                    "required_skills": ["using-superpowers", "test-driven-development"],
                    "tool_policy": "implementation",
                    "allowed_write_globs": ["docs/allowed.md"],
                    "forbidden_write_globs": ["docs/forbidden.md"],
                    "artifact_policy": "inline-summary",
                    "max_context_chars": 60000,
                },
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {
            "started_at": "2026-05-16T00:00:00Z",
            "updated_at": "2026-05-16T00:00:00Z",
            "completed_at": None,
        },
    }


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def init_repo(repo: Path) -> None:
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "allowed.md").write_text("allowed\n", encoding="utf-8")
    (repo / "docs" / "forbidden.md").write_text("forbidden\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "plan.md").write_text("### Task 0\n\n**Files:**\n- docs/allowed.md\n", encoding="utf-8")
    run(["git", "init", "-q"], repo).check_returncode()
    run(["git", "config", "user.email", "eval@example.com"], repo).check_returncode()
    run(["git", "config", "user.name", "Eval"], repo).check_returncode()
    run(["git", "add", "-A"], repo).check_returncode()
    run(["git", "commit", "-q", "-m", "bootstrap"], repo).check_returncode()


def write_state(repo: Path, state: dict) -> Path:
    state_path = repo / state["state_path"]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state_path


def run_checker(script: Path, repo: Path, state_path: Path, task_id: str = "task_0") -> subprocess.CompletedProcess[str]:
    return run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--state",
            str(state_path),
            "--task",
            task_id,
            "--json",
        ],
        repo,
    )


def json_payload(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def case(script: Path, name: str, mutate_state, mutate_repo, expect_pass: bool) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix=f"codex-diff-policy-{name}-") as temp:
        repo = Path(temp)
        init_repo(repo)
        state = base_state(repo)
        mutate_state(state)
        state_path = write_state(repo, state)
        run(["git", "add", str(state_path.relative_to(repo))], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "state"], repo).check_returncode()
        mutate_repo(repo)
        result = run_checker(script, repo, state_path)
        payload = json_payload(result)
        passed = result.returncode == 0 and payload.get("passed") is True
        failed = result.returncode != 0 and payload.get("passed") is False and payload.get("violations")
        if expect_pass and passed:
            return True, ""
        if not expect_pass and failed:
            return True, ""
        return False, f"{name}: rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_run_diffs.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    cases = [
        (
            "allowed_change_passes",
            lambda state: None,
            lambda repo: (repo / "docs" / "allowed.md").write_text("allowed changed\n", encoding="utf-8"),
            True,
        ),
        (
            "outside_allowed_fails",
            lambda state: None,
            lambda repo: (repo / "docs" / "outside.md").write_text("outside\n", encoding="utf-8"),
            False,
        ),
        (
            "forbidden_change_fails",
            lambda state: None,
            lambda repo: (repo / "docs" / "forbidden.md").write_text("forbidden changed\n", encoding="utf-8"),
            False,
        ),
        (
            "read_only_no_changes_passes",
            lambda state: (
                state["tasks"]["task_0"]["unit_manifest"].update(
                    {"tool_policy": "read-only", "allowed_write_globs": []}
                ),
                state["tasks"]["task_0"]["contract"].update({"allowed_edits": []}),
            ),
            lambda repo: None,
            True,
        ),
        (
            "docs_policy_docs_change_passes",
            lambda state: (
                state["tasks"]["task_0"]["unit_manifest"].update(
                    {"tool_policy": "docs", "allowed_write_globs": ["docs/**"]}
                ),
                state["tasks"]["task_0"]["contract"].update({"allowed_edits": []}),
            ),
            lambda repo: (repo / "docs" / "new.md").write_text("new\n", encoding="utf-8"),
            True,
        ),
        (
            "nul_safe_docs_path_passes",
            lambda state: (
                state["tasks"]["task_0"]["unit_manifest"].update(
                    {"tool_policy": "docs", "allowed_write_globs": ["docs/**"]}
                ),
                state["tasks"]["task_0"]["contract"].update({"allowed_edits": []}),
            ),
            lambda repo: (repo / "docs" / "odd\nname.md").write_text(
                "new\n", encoding="utf-8"
            ),
            True,
        ),
    ]

    for name, mutate_state, mutate_repo, expect_pass in cases:
        ok, failure = case(script, name, mutate_state, mutate_repo, expect_pass)
        checks[name] = ok
        if not ok:
            failures.append(failure)

    with tempfile.TemporaryDirectory(prefix="cpe-git-delta-") as raw:
        repo = Path(raw)
        run(["git", "init", "-q"], repo).check_returncode()
        run(["git", "config", "user.email", "eval@example.com"], repo).check_returncode()
        run(["git", "config", "user.name", "Eval"], repo).check_returncode()
        (repo / "tracked.txt").write_bytes(b"before\x00tracked")
        (repo / "deleted.txt").write_text("delete me\n", encoding="utf-8")
        (repo / "link").symlink_to("target-before")
        run(["git", "add", "-A"], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "base"], repo).check_returncode()
        before = capture_snapshot(repo)
        os.utime(repo / "tracked.txt", None)
        mtime_only = capture_snapshot(repo)
        (repo / "tracked.txt").write_bytes(b"after\x00tracked")
        (repo / "deleted.txt").unlink()
        (repo / "link").unlink()
        (repo / "link").symlink_to("target-after")
        odd_path = "odd\nname.bin"
        (repo / odd_path).write_bytes(b"\x00\xff\x10binary")
        after = capture_snapshot(repo)
        delta = diff_snapshots(before, after, repo)
        expected = tuple(sorted(("deleted.txt", "link", odd_path, "tracked.txt")))
        checks.update(
            {
                "mtime_is_not_a_change": before == mtime_only,
                "tracked_delete_binary_and_symlink_detected": delta.changed_files == expected,
                "nul_safe_path_preserved": odd_path in delta.changed_files,
                "patch_digest_is_canonical": delta.patch_sha256
                == hashlib.sha256(delta.patch_bytes).hexdigest(),
                "snapshot_is_content_stable": after == capture_snapshot(repo),
                "scope_errors_are_deterministic": scope_errors(
                    delta,
                    ["tracked.txt", "*.bin"],
                    ["deleted.txt", "link"],
                )
                == [
                    "forbidden_write:deleted.txt",
                    "forbidden_write:link",
                ],
                "forbidden_precedes_unclaimed": scope_errors(
                    delta,
                    ["tracked.txt"],
                    ["link", "deleted.txt"],
                )
                == [
                    "forbidden_write:deleted.txt",
                    "forbidden_write:link",
                    f"unclaimed_write:{odd_path}",
                ],
            }
        )
        run(["git", "add", "-A"], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "worker commit"], repo).check_returncode()
        committed = capture_snapshot(repo)
        head_delta = diff_snapshots(after, committed, repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "empty worker commit"], repo).check_returncode()
        empty_committed = capture_snapshot(repo)
        empty_head_delta = diff_snapshots(committed, empty_committed, repo)
        checks.update(
            {
                "head_change_detected": head_delta.head_changed,
                "empty_head_change_detected": empty_head_delta.head_changed
                and empty_head_delta.changed_files == (),
                "head_is_in_canonical_patch": before.head.encode() in delta.patch_bytes
                and after.head.encode() in delta.patch_bytes
                and committed.head.encode() in head_delta.patch_bytes,
                "head_change_is_scope_error": scope_errors(head_delta, ["**"], [])
                == ["worktree_head_changed"],
            }
        )

    with tempfile.TemporaryDirectory(prefix="cpe-root-literal-scope-") as raw:
        repo = Path(raw)
        run(["git", "init", "-q"], repo).check_returncode()
        run(["git", "config", "user.email", "eval@example.com"], repo).check_returncode()
        run(["git", "config", "user.name", "Eval"], repo).check_returncode()
        (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
        run(["git", "add", "baseline.txt"], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "baseline"], repo).check_returncode()
        before_nested = capture_snapshot(repo)
        nested = repo / "fixtures" / "template" / "run" / "state.json"
        nested.parent.mkdir(parents=True)
        nested.write_text("{}\n", encoding="utf-8")
        after_nested = capture_snapshot(repo)
        nested_delta = diff_snapshots(before_nested, after_nested, repo)
        checks["root_literal_does_not_forbid_nested_fixture"] = scope_errors(
            nested_delta, ["fixtures/**"], ["state.json"]
        ) == []
        (repo / "state.json").write_text("{}\n", encoding="utf-8")
        root_delta = diff_snapshots(after_nested, capture_snapshot(repo), repo)
        checks["root_literal_still_forbids_root_file"] = scope_errors(
            root_delta, ["fixtures/**"], ["state.json"]
        ) == ["forbidden_write:state.json"]

    with tempfile.TemporaryDirectory(prefix="cpe-ignored-git-delta-") as raw:
        repo = Path(raw)
        run(["git", "init", "-q"], repo).check_returncode()
        run(["git", "config", "user.email", "eval@example.com"], repo).check_returncode()
        run(["git", "config", "user.name", "Eval"], repo).check_returncode()
        (repo / ".gitignore").write_text("ignored-by-gitignore.bin\n", encoding="utf-8")
        run(["git", "add", ".gitignore"], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "ignore rules"], repo).check_returncode()
        info_exclude = repo / ".git" / "info" / "exclude"
        info_exclude.write_text(
            info_exclude.read_text(encoding="utf-8") + "\nignored-by-info.bin\n",
            encoding="utf-8",
        )
        before_ignored = capture_snapshot(repo)
        (repo / "ignored-by-gitignore.bin").write_bytes(b"\x00ignored")
        (repo / "ignored-by-info.bin").write_bytes(b"ignored by info\n")
        (repo / "__pycache__").mkdir()
        (repo / "__pycache__" / "generated.cpython-314.pyc").write_bytes(
            b"generated cache"
        )
        after_ignored = capture_snapshot(repo)
        ignored_delta = diff_snapshots(before_ignored, after_ignored, repo)
        ignored_paths = ("ignored-by-gitignore.bin", "ignored-by-info.bin")
        checks.update(
            {
                "ignored_content_is_in_full_tree_snapshot": ignored_delta.changed_files
                == ignored_paths,
                "untracked_python_cache_is_excluded": not any(
                    path == "__pycache__" or path.startswith("__pycache__/")
                    for path, _fingerprint in after_ignored.files
                ),
                "git_metadata_is_excluded_from_snapshot": not any(
                    path == ".git" or path.startswith(".git/")
                    for path, _fingerprint in after_ignored.files
                ),
            }
        )

    with tempfile.TemporaryDirectory(prefix="cpe-filesystem-delta-") as raw:
        repo = Path(raw)
        run(["git", "init", "-q"], repo).check_returncode()
        run(["git", "config", "user.email", "eval@example.com"], repo).check_returncode()
        run(["git", "config", "user.name", "Eval"], repo).check_returncode()
        (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
        run(["git", "add", "baseline.txt"], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "baseline"], repo).check_returncode()
        before_filesystem = capture_snapshot(repo)
        (repo / "hidden").mkdir()
        (repo / "hidden" / ".git").write_bytes(b"nested content")
        (repo / "empty-unclaimed").mkdir()
        after_filesystem = capture_snapshot(repo)
        filesystem_delta = diff_snapshots(before_filesystem, after_filesystem, repo)
        checks.update(
            {
                "nested_git_and_empty_directory_are_content": filesystem_delta.changed_files
                == ("empty-unclaimed", "hidden", "hidden/.git"),
                "only_root_git_metadata_is_excluded": "hidden/.git"
                in dict(after_filesystem.files),
            }
        )

        before_unreadable = after_filesystem
        sealed = repo / "sealed.bin"
        sealed.write_bytes(b"sealed\x00content")
        sealed.chmod(0)
        try:
            try:
                tolerant = capture_snapshot(repo, tolerate_invalid_git=True)
                unreadable_delta = diff_snapshots(before_unreadable, tolerant, repo)
                tolerant_ok = (
                    "sealed.bin" in unreadable_delta.changed_files
                    and not tolerant._filesystem_valid
                )
            except (OSError, RuntimeError):
                tolerant_ok = False
        finally:
            sealed.chmod(0o600)
        checks["tolerant_unreadable_content_is_measurable"] = tolerant_ok

        sealed.chmod(0)
        try:
            try:
                capture_snapshot(repo)
            except (OSError, RuntimeError):
                strict_rejected = True
            else:
                strict_rejected = False
        finally:
            sealed.chmod(0o600)
        checks["strict_unreadable_baseline_fails_closed"] = strict_rejected

    with tempfile.TemporaryDirectory(prefix="cpe-directory-scope-") as raw:
        repo = Path(raw)
        run(["git", "init", "-q"], repo).check_returncode()
        run(["git", "config", "user.email", "eval@example.com"], repo).check_returncode()
        run(["git", "config", "user.name", "Eval"], repo).check_returncode()
        (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
        run(["git", "add", "baseline.txt"], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "baseline"], repo).check_returncode()

        before_created_tree = capture_snapshot(repo)
        owned = repo / "newdir" / "sub" / "owned.txt"
        owned.parent.mkdir(parents=True)
        owned.write_text("owned\n", encoding="utf-8")
        after_created_tree = capture_snapshot(repo)
        created_tree_delta = diff_snapshots(before_created_tree, after_created_tree, repo)
        checks.update(
            {
                "exact_child_authorizes_structural_parents": scope_errors(
                    created_tree_delta, ["newdir/sub/owned.txt"], []
                )
                == [],
                "recursive_glob_authorizes_child_and_parents": scope_errors(
                    created_tree_delta, ["newdir/**"], []
                )
                == [],
                "forbidden_child_does_not_authorize_structural_parents": scope_errors(
                    created_tree_delta,
                    ["newdir/sub/owned.txt"],
                    ["newdir/sub/owned.txt"],
                )
                == [
                    "forbidden_write:newdir/sub/owned.txt",
                    "unclaimed_write:newdir",
                    "unclaimed_write:newdir/sub",
                ],
            }
        )

        before_empty = after_created_tree
        (repo / "standalone-empty").mkdir()
        empty_delta = diff_snapshots(before_empty, capture_snapshot(repo), repo)
        checks["standalone_empty_directory_stays_unclaimed"] = scope_errors(
            empty_delta, [], []
        ) == ["unclaimed_write:standalone-empty"]

        existing = repo / "existing-directory"
        existing.mkdir()
        existing.chmod(0o700)
        before_mode = capture_snapshot(repo)
        existing.chmod(0o755)
        mode_delta = diff_snapshots(before_mode, capture_snapshot(repo), repo)
        checks["existing_directory_mode_change_stays_unclaimed"] = scope_errors(
            mode_delta, [], []
        ) == ["unclaimed_write:existing-directory"]

        before_removed_tree = capture_snapshot(repo)
        owned.unlink()
        owned.parent.rmdir()
        (repo / "newdir").rmdir()
        removed_tree_delta = diff_snapshots(
            before_removed_tree, capture_snapshot(repo), repo
        )
        checks["allowed_removed_child_authorizes_removed_parents"] = scope_errors(
            removed_tree_delta, ["newdir/sub/owned.txt"], []
        ) == []

    with tempfile.TemporaryDirectory(prefix="cpe-patch-kernel-") as raw:
        run_dir = Path(raw) / "run"
        run_dir.mkdir()
        kernel = Kernel(run_dir)
        ref = kernel.store_patch_evidence(b"canonical patch\x00bytes")
        same_ref = kernel.store_patch_evidence(b"canonical patch\x00bytes")
        target = run_dir / ref["path"]
        checks.update(
            {
                "kernel_patch_is_content_addressed": ref == same_ref
                and ref["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest(),
                "kernel_patch_is_private_file": target.stat().st_mode & 0o777 == 0o600,
            }
        )

    with tempfile.TemporaryDirectory(prefix="cpe-patch-nofollow-") as raw:
        run_dir = Path(raw) / "run"
        patches = run_dir / "artifacts" / "patches"
        patches.mkdir(parents=True)
        raw_patch = b"no follow patch"
        digest = hashlib.sha256(raw_patch).hexdigest()
        outside = Path(raw) / "outside"
        outside.write_bytes(b"untouched")
        (patches / f"{digest}.patch").symlink_to(outside)
        try:
            Kernel(run_dir).store_patch_evidence(raw_patch)
        except ValueError:
            nofollow_rejected = outside.read_bytes() == b"untouched"
        else:
            nofollow_rejected = False
        checks["kernel_patch_refuses_symlink"] = nofollow_rejected

    failures.extend(name for name, passed in checks.items() if not passed and name not in failures)

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
