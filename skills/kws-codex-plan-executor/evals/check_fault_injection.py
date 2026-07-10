#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.attempt_controller import validate_verdict
from cpe_runtime.events import read_events
from cpe_runtime.kernel import RunKernel
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.model_policy import CORE_ROUTE
from cpe_runtime.packets import build_packet
from cpe_runtime.projector import project
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.worker import Worker, WorkerError, WorkerRequest


def rejected(message: str, fn) -> bool:
    try:
        fn()
    except WorkerError as exc:
        return str(exc) == message
    return False


def worker_rejects_result(message: str, payload: dict[str, object]) -> bool:
    request = WorkerRequest(
        attempt_id="T1.task_review.fault",
        attempt_kind="task_review",
        prompt="{}",
        worktree=Path("/tmp/cpe-verdict-fault-worktree"),
        read_only=True,
        verdict_capable=True,
        task_id="T1",
        packet_path="artifacts/task-packets/T1.json",
        packet_sha256="a" * 64,
        worktree_revision=7,
    )
    provider_payload = {
        **payload,
        "_provider_metadata": {
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "trusted_source": "fault-fixture",
        },
    }
    return rejected(message, lambda: Worker(provider=lambda _request, _argv: provider_payload).run(request))


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _scope_result(role: str, revision: int, changed_files: list[str]) -> dict[str, object]:
    verdict = None
    if role in {"task_review", "verification", "final_review"}:
        verdict = {
            "status": "passed",
            "findings": [],
            "missing_evidence": [],
            "worktree_revision": revision,
        }
    return {
        "status": "completed",
        "summary": role,
        "changed_files": changed_files,
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": verdict,
        "_provider_metadata": {
            "model": CORE_ROUTE.model,
            "reasoning": CORE_ROUTE.reasoning,
            "trusted_source": "scope-fault-fixture",
        },
    }


def _scope_fixture(root: Path) -> tuple[Path, Path, list[dict], RunKernel]:
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# scope fault\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    worktree = root / "worktree"
    worktree.mkdir()
    _run(["git", "init", "-q"], worktree).check_returncode()
    _run(["git", "config", "user.email", "eval@example.com"], worktree).check_returncode()
    _run(["git", "config", "user.name", "Eval"], worktree).check_returncode()
    (worktree / "owned-a.txt").write_text("a0\n", encoding="utf-8")
    (worktree / "owned-b.txt").write_text("b0\n", encoding="utf-8")
    _run(["git", "add", "-A"], worktree).check_returncode()
    _run(["git", "commit", "-q", "-m", "bootstrap"], worktree).check_returncode()
    head = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
    tasks = [
        {
            "id": "T1",
            "title": "owns a",
            "dependencies": [],
            "file_claims": ["owned-a.txt"],
            "acceptance_command": "true",
        },
        {
            "id": "T2",
            "title": "owns b",
            "dependencies": ["T1"],
            "file_claims": ["owned-b.txt"],
            "acceptance_command": "true",
        },
    ]
    drafts = [build_packet(SimpleNamespace(sources=(), spec_manifest=None), task) for task in tasks]
    manifest = create_manifest(
        "scope-fault", "interactive", root, worktree, plan, None, tasks, pricing,
        source_head=head,
    )
    kernel = RunKernel.initialize(root / "run", manifest, drafts)
    return worktree, kernel.run_dir, tasks, kernel


def _scope_fault(commit_head: bool, invalid_worker_result: bool = False) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="cpe-scope-fault-") as raw:
        worktree, run_dir, tasks, kernel = _scope_fixture(Path(raw))
        launched: list[str] = []

        def provider(request, _argv):
            launched.append(request.attempt_kind)
            reported: list[str] = []
            if request.attempt_kind == "implementation" and request.task_id == "T1":
                if commit_head:
                    (worktree / "owned-a.txt").write_text("a1\n", encoding="utf-8")
                    _run(["git", "add", "owned-a.txt"], worktree).check_returncode()
                    _run(["git", "commit", "-q", "-m", "worker commit"], worktree).check_returncode()
                    reported = ["owned-a.txt"]
                else:
                    (worktree / "owned-b.txt").write_text("cross-task\n", encoding="utf-8")
                    reported = ["owned-a.txt"]
                if invalid_worker_result:
                    return {"status": "completed"}
            return _scope_result(request.attempt_kind, request.worktree_revision, reported)

        try:
            result = run_tasks(tasks, Worker(provider=provider), kernel)
        except ValueError as exc:
            result = {"status": "error", "reason": str(exc)}
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
        state = project(manifest, events)
        revision_indexes = [index for index, event in enumerate(events) if event["type"] == "worktree.revision_recorded"]
        blocker_indexes = [index for index, event in enumerate(events) if event["type"] == "blocker.opened"]
        expected_root = "worktree_head_changed" if commit_head else "task_scope:T1:owned-b.txt"
        blocker = state["active_blockers"][0] if state["active_blockers"] else {}
        return {
            "blocked_before_downstream": result.get("status") == "blocked"
            and result.get("failure_category") == "policy_violation"
            and "task_review" not in launched
            and "verification" not in launched,
            "revision_advanced": state["worktree_revision"] == 1,
            "policy_blocker_typed": blocker.get("category") == "policy_violation"
            and blocker.get("root_cause_key") == expected_root,
            "revision_precedes_blocker": bool(revision_indexes and blocker_indexes)
            and revision_indexes[0] < blocker_indexes[0],
            "worker_report_is_diagnostic_only": commit_head
            or any(
                event["type"] == "worktree.revision_recorded"
                and event["payload"].get("changed_files") == ["owned-b.txt"]
                for event in events
            ),
        }


def scope_cases() -> dict[str, bool]:
    cross_task = _scope_fault(False)
    head_change = _scope_fault(True)
    failed_worker = _scope_fault(False, invalid_worker_result=True)
    return {
        **{f"cross_task_{name}": passed for name, passed in cross_task.items()},
        **{f"head_change_{name}": passed for name, passed in head_change.items()},
        **{f"failed_worker_{name}": passed for name, passed in failed_worker.items()},
    }
def verdict_cases() -> dict[str, bool]:
    base = {
        "findings": [],
        "missing_evidence": [],
        "worktree_revision": 7,
    }
    passed_worker_result = {
        "status": "completed",
        "summary": "contradictory review",
        "changed_files": [],
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": {**base, "status": "passed"},
    }
    return {
        "worker_top_level_critical_mismatch_rejected": worker_rejects_result(
            "worker result findings do not match verdict",
            {
                **passed_worker_result,
                "findings": [{"severity": "critical", "summary": "hidden contradiction"}],
            },
        ),
        "worker_top_level_missing_evidence_mismatch_rejected": worker_rejects_result(
            "worker result missing_evidence does not match verdict",
            {**passed_worker_result, "missing_evidence": ["required acceptance output"]},
        ),
        "critical_passed_rejected": rejected(
            "passed verdict conflicts with critical findings",
            lambda: validate_verdict(
                {
                    **base,
                    "status": "passed",
                    "findings": [{"severity": "critical", "summary": "completion is false"}],
                },
                "task_review",
                7,
            ),
        ),
        "missing_evidence_passed_rejected": rejected(
            "passed verdict conflicts with missing evidence",
            lambda: validate_verdict(
                {**base, "status": "passed", "missing_evidence": ["acceptance log"]},
                "verification",
                7,
            ),
        ),
        "empty_changes_requested_rejected": rejected(
            "changes_requested verdict requires an actionable finding",
            lambda: validate_verdict(
                {**base, "status": "changes_requested"}, "final_review", 7
            ),
        ),
        "ownerless_blocked_rejected": rejected(
            "blocked verdict requires owner and resume_condition",
            lambda: validate_verdict({**base, "status": "blocked"}, "task_review", 7),
        ),
        "unbounded_inconclusive_rejected": rejected(
            "inconclusive verdict requires next_evidence_action",
            lambda: validate_verdict(
                {**base, "status": "inconclusive"}, "verification", 7
            ),
        ),
        "stale_revision_rejected": rejected(
            "verdict revision is stale",
            lambda: validate_verdict({**base, "status": "passed"}, "task_review", 8),
        ),
        "write_role_verdict_rejected": rejected(
            "role implementation cannot issue a verdict",
            lambda: validate_verdict({**base, "status": "passed"}, "implementation", 7),
        ),
        "valid_passed_accepted": validate_verdict(
            {**base, "status": "passed"}, "task_review", 7
        )["status"]
        == "passed",
        "valid_changes_requested_accepted": validate_verdict(
            {
                **base,
                "status": "changes_requested",
                "findings": [{"severity": "major", "action": "add the missing assertion"}],
            },
            "final_review",
            7,
        )["status"]
        == "changes_requested",
        "valid_blocked_accepted": validate_verdict(
            {
                **base,
                "status": "blocked",
                "owner": "operator",
                "resume_condition": "provide the signed report",
            },
            "verification",
            7,
        )["status"]
        == "blocked",
        "valid_inconclusive_accepted": validate_verdict(
            {
                **base,
                "status": "inconclusive",
                "next_evidence_action": "run the bounded acceptance command",
            },
            "verification",
            7,
        )["status"]
        == "inconclusive",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("verdicts", "scope", "completion"))
    args = parser.parse_args()

    if args.case == "verdicts":
        checks = verdict_cases()
    elif args.case == "scope":
        checks = scope_cases()
    elif args.case == "completion":
        checks = {"completion_fault_cases_pending_task_7": False}
    else:
        checks = {
            **verdict_cases(),
            **scope_cases(),
            "completion_fault_cases_pending_task_7": False,
        }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
