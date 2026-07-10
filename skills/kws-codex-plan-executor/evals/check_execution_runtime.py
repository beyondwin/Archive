#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.attempt_controller import ROLE_POLICIES, RolePolicy, validate_verdict
from cpe_runtime.events import read_events
from cpe_runtime.kernel import RunKernel
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.model_policy import CORE_ROUTE, SCOUT_ROUTE
from cpe_runtime.packets import build_packet
from cpe_runtime.scheduler import make_packet_request, run_tasks
from cpe_runtime.worker import Worker, WorkerError


def expect_worker_error(message: str, fn) -> None:
    try:
        fn()
    except WorkerError as exc:
        assert str(exc) == message, str(exc)
        return
    raise AssertionError(f"expected WorkerError: {message}")


def result_for(role: str, revision: int) -> dict[str, object]:
    verdict = None
    if ROLE_POLICIES[role].verdict_capable:
        verdict = {
            "status": "passed",
            "findings": [],
            "missing_evidence": [],
            "worktree_revision": revision,
        }
    return {
        "status": "completed",
        "summary": role,
        "changed_files": [],
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": verdict,
        "_provider_metadata": {
            "model": SCOUT_ROUTE.model if role == "scout" else CORE_ROUTE.model,
            "reasoning": "high",
            "trusted_source": "fixture",
        },
    }


def main() -> int:
    assert ROLE_POLICIES == {
        "scout": RolePolicy(True, False, False),
        "implementation": RolePolicy(False, False, True),
        "task_review": RolePolicy(True, True, False),
        "verification": RolePolicy(True, True, False),
        "repair": RolePolicy(False, False, True),
        "final_review": RolePolicy(True, True, False),
    }

    expect_worker_error(
        "passed verdict conflicts with critical findings",
        lambda: validate_verdict(
            {
                "status": "passed",
                "findings": [{"severity": "critical", "summary": "false completion"}],
                "missing_evidence": [],
                "worktree_revision": 2,
            },
            "task_review",
            2,
        ),
    )
    expect_worker_error(
        "passed verdict conflicts with missing evidence",
        lambda: validate_verdict(
            {
                "status": "passed",
                "findings": [],
                "missing_evidence": ["acceptance output"],
                "worktree_revision": 2,
            },
            "verification",
            2,
        ),
    )
    expect_worker_error(
        "blocked verdict requires owner and resume_condition",
        lambda: validate_verdict(
            {
                "status": "blocked",
                "findings": [],
                "missing_evidence": [],
                "worktree_revision": 2,
            },
            "task_review",
            2,
        ),
    )
    expect_worker_error(
        "inconclusive verdict requires next_evidence_action",
        lambda: validate_verdict(
            {
                "status": "inconclusive",
                "findings": [],
                "missing_evidence": [],
                "worktree_revision": 2,
            },
            "verification",
            2,
        ),
    )
    expect_worker_error(
        "changes_requested verdict requires an actionable finding",
        lambda: validate_verdict(
            {
                "status": "changes_requested",
                "findings": [],
                "missing_evidence": [],
                "worktree_revision": 2,
            },
            "final_review",
            2,
        ),
    )
    expect_worker_error(
        "verdict revision is stale",
        lambda: validate_verdict(
            {
                "status": "passed",
                "findings": [],
                "missing_evidence": [],
                "worktree_revision": 1,
            },
            "task_review",
            2,
        ),
    )

    with tempfile.TemporaryDirectory(prefix="cpe-execution-") as raw:
        root = Path(raw)
        plan = root / "plan.md"
        pricing = root / "pricing.json"
        plan.write_text("# plan\n", encoding="utf-8")
        pricing.write_text("{}\n", encoding="utf-8")
        worktree = root / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
        tasks = [
            {
                "id": "T1",
                "title": "one",
                "dependencies": [],
                "file_claims": [],
                "acceptance_command": "true",
                "prompt": "PACKET_BODY_SENTINEL_MUST_NOT_BE_INLINED",
            },
            {
                "id": "T2",
                "title": "two",
                "dependencies": ["T1"],
                "file_claims": [],
                "acceptance_command": "true",
            },
        ]
        compiled = SimpleNamespace(sources=(), spec_manifest=None)
        drafts = [build_packet(compiled, task) for task in tasks]
        manifest = create_manifest(
            "execution-fixture", "interactive", root, worktree, plan, None, tasks, pricing
        )
        run_dir = root / "run"
        RunKernel.initialize(run_dir, manifest, drafts)
        manifest = load_verified_manifest(run_dir / "run_manifest.json")

        launched: list[tuple[str, str]] = []

        def provider(request, argv):
            sandbox = argv[argv.index("--sandbox") + 1]
            launched.append((request.attempt_kind, sandbox))
            expected = "read-only" if ROLE_POLICIES[request.attempt_kind].read_only else "workspace-write"
            assert sandbox == expected
            prompt = json.loads(request.prompt)
            assert set(prompt) == {
                "task_id",
                "packet_path",
                "packet_sha256",
                "worktree_revision",
                "instruction",
            }
            assert prompt["task_id"] == request.task_id
            assert prompt["packet_path"] == request.packet_path
            assert prompt["packet_sha256"] == request.packet_sha256
            assert prompt["worktree_revision"] == request.worktree_revision
            assert "PACKET_BODY_SENTINEL_MUST_NOT_BE_INLINED" not in request.prompt
            return result_for(request.attempt_kind, request.worktree_revision)

        worker = Worker(provider=provider)
        for role in ROLE_POLICIES:
            request = make_packet_request(
                run_dir,
                manifest,
                "T1",
                f"T1.{role}.direct",
                role,
                "bounded instruction",
                worktree,
            )
            worker.run(request)
            if role == "task_review":
                expect_worker_error(
                    "worker request violates role policy",
                    lambda request=request: worker.run(replace(request, read_only=False)),
                )

        result = run_tasks(tasks, worker, run_dir)
        assert result == {
            "completed": ["T1", "T2"],
            "blocked": None,
            "status": "completed",
        }, result
        events = read_events(run_dir / "events.jsonl")
        assert all(event["type"] != "attempt.recorded" for event in events)
        assert any(event["type"] == "attempt.started" for event in events)
        assert any(event["type"] == "attempt.completed" for event in events)
        assert all(
            event["payload"]["worktree_revision"] == 0
            for event in events
            if event["type"] in {"attempt.started", "attempt.completed"}
        )
        verdict_events = [event for event in events if event["type"] == "verdict.recorded"]
        assert verdict_events
        assert all(
            event["payload"]["worktree_revision"] == 0
            and event["payload"]["status"] == "passed"
            for event in verdict_events
        )
        assert {sandbox for role, sandbox in launched if ROLE_POLICIES[role].verdict_capable} == {
            "read-only"
        }

    print('{"passed": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
