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
from cpe_runtime.evidence import verify_ref
from cpe_runtime.kernel import RunKernel
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.model_policy import CORE_ROUTE, SCOUT_ROUTE
from cpe_runtime.packets import build_packet
from cpe_runtime.scheduler import make_packet_request, next_phase, route_verdict, run_tasks
from cpe_runtime.projector import project
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


def initialize_run(root: Path, run_id: str, tasks: list[dict]) -> tuple[Path, Path, dict]:
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    worktree = root / "worktree"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "cpe@example.invalid"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "CPE Fixture"], cwd=worktree, check=True)
    (worktree / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=worktree, check=True)
    subprocess.run(["git", "checkout", "-qb", f"codex/{run_id}"], cwd=worktree, check=True)
    source_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree, check=True, text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    compiled = SimpleNamespace(sources=(), spec_manifest=None)
    drafts = [build_packet(compiled, task) for task in tasks]
    manifest = create_manifest(
        run_id, "interactive", root, worktree, plan, None, tasks, pricing,
        source_head=source_head,
    )
    run_dir = root / "run"
    RunKernel.initialize(run_dir, manifest, drafts)
    return run_dir, worktree, load_verified_manifest(run_dir / "run_manifest.json")


def semantic_phases(run_dir: Path, revision: int) -> list[str]:
    events = read_events(run_dir / "events.jsonl")
    phases: list[str] = []
    for event in events:
        if event["type"] == "attempt.started" and event["payload"]["kind"] in {
            "implementation", "repair", "task_review", "verification", "final_review",
        }:
            phases.append(event["payload"]["kind"])
        if event["type"] != "evidence.attached" or event["payload"]["kind"] not in {
            "acceptance", "repository_check",
        }:
            continue
        ref = event["payload"]["ref"]
        assert not verify_ref(run_dir, ref)
        payload = json.loads((run_dir / ref["path"]).read_text(encoding="utf-8"))
        if payload.get("worktree_revision") == revision:
            phases.append(event["payload"]["kind"])
    return phases


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
    assert next_phase({"tasks": {"T1": {"status": "ready"}}}, "T1") == "implementation"
    assert route_verdict({"status": "passed"}) == "continue"
    assert route_verdict({"status": "changes_requested"}) == "repair"
    for invalid in ("unknown", {"status": "unknown"}):
        try:
            route_verdict(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown verdict must fail closed")

    with tempfile.TemporaryDirectory(prefix="cpe-execution-") as raw:
        root = Path(raw)
        tasks = [
            {
                "id": "T1",
                "title": "one",
                "dependencies": [],
                "file_claims": ["T1.txt"],
                "acceptance_command": "true",
                "prompt": "PACKET_BODY_SENTINEL_MUST_NOT_BE_INLINED",
            },
            {
                "id": "T2",
                "title": "two",
                "dependencies": ["T1"],
                "file_claims": ["T2.txt"],
                "acceptance_command": "true",
            },
        ]
        run_dir, worktree, manifest = initialize_run(root, "execution-fixture", tasks)

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
            if request.attempt_kind == "implementation" and not request.attempt_id.endswith(".direct"):
                target = worktree / f"{request.task_id}.txt"
                target.write_text(f"revision for {request.task_id}\n", encoding="utf-8")
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

        review_request = make_packet_request(
            run_dir,
            manifest,
            "T1",
            "T1.task_review.contradiction",
            "task_review",
            "check contradictory output",
            worktree,
        )
        critical_result = result_for("task_review", review_request.worktree_revision)
        critical_result["findings"] = [
            {"severity": "critical", "summary": "top-level contradiction"}
        ]
        expect_worker_error(
            "worker result findings do not match verdict",
            lambda: Worker(provider=lambda _request, _argv: critical_result).run(review_request),
        )
        missing_result = result_for("verification", review_request.worktree_revision)
        missing_result["missing_evidence"] = ["required acceptance output"]
        verification_request = replace(
            review_request,
            attempt_id="T1.verification.contradiction",
            attempt_kind="verification",
        )
        expect_worker_error(
            "worker result missing_evidence does not match verdict",
            lambda: Worker(provider=lambda _request, _argv: missing_result).run(
                verification_request
            ),
        )

        launched.clear()
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
        state = project(manifest, events)
        assert state["worktree_revision"] == 2, state
        verdict_events = [event for event in events if event["type"] == "verdict.recorded"]
        assert verdict_events
        assert all(
            event["payload"]["worktree_revision"] in {1, 2}
            and event["payload"]["status"] == "passed"
            and event["payload"]["packet_sha256"]
            for event in verdict_events
        )
        assert {sandbox for role, sandbox in launched if ROLE_POLICIES[role].verdict_capable} == {
            "read-only"
        }
        current_phases = semantic_phases(run_dir, 2)
        assert current_phases[-7:] == [
            "acceptance", "task_review", "verification",
            "repository_check", "repository_check",
            "final_review", "final_review",
        ], current_phases

    with tempfile.TemporaryDirectory(prefix="cpe-final-repair-") as raw:
        root = Path(raw)
        tasks = [{
            "id": "T1", "title": "one", "dependencies": [],
            "file_claims": ["T1.txt"], "acceptance_command": "true",
        }]
        run_dir, worktree, manifest = initialize_run(root, "final-repair-fixture", tasks)
        final_calls = 0

        def repair_provider(request, _argv):
            nonlocal final_calls
            if request.attempt_kind == "implementation":
                (worktree / "T1.txt").write_text("revision 1\n", encoding="utf-8")
            elif request.attempt_kind == "repair":
                (worktree / "T1.txt").write_text("revision 2\n", encoding="utf-8")
            result = result_for(request.attempt_kind, request.worktree_revision)
            if request.attempt_kind == "final_review":
                final_calls += 1
                if final_calls == 1:
                    finding = {
                        "task_id": "T1", "severity": "high",
                        "summary": "repair T1", "action": "update T1",
                    }
                    result["findings"] = [finding]
                    result["verdict"] = {
                        "status": "changes_requested", "findings": [finding],
                        "missing_evidence": [],
                        "worktree_revision": request.worktree_revision,
                    }
            return result

        result = run_tasks(tasks, Worker(provider=repair_provider), run_dir)
        assert result["status"] == "completed", result
        state = project(manifest, read_events(run_dir / "events.jsonl"))
        assert state["worktree_revision"] == 2
        phases = semantic_phases(run_dir, 2)
        assert phases[-6:] == [
            "repair", "acceptance", "task_review", "verification",
            "repository_check", "final_review",
        ], phases
        current_kinds = []
        for artifact in state["artifact_index"]:
            if artifact["kind"] not in {
                "acceptance", "task_review", "verification", "repository_check", "final_review",
            }:
                continue
            payload = json.loads((run_dir / artifact["ref"]["path"]).read_text(encoding="utf-8"))
            if payload["worktree_revision"] == 2:
                current_kinds.append(artifact["kind"])
        assert current_kinds == [
            "acceptance", "task_review", "verification", "repository_check", "final_review",
        ], current_kinds

    with tempfile.TemporaryDirectory(prefix="cpe-refresh-stabilization-") as raw:
        root = Path(raw)
        tasks = [
            {
                "id": "T1", "title": "one", "dependencies": [],
                "file_claims": ["T1.txt"], "acceptance_command": "true",
            },
            {
                "id": "T2", "title": "two", "dependencies": ["T1"],
                "file_claims": ["T2.txt"], "acceptance_command": "true",
            },
        ]
        run_dir, worktree, manifest = initialize_run(root, "stabilization-fixture", tasks)
        requested_repairs: set[tuple[str, int]] = set()

        def stabilization_provider(request, _argv):
            if request.attempt_kind == "implementation":
                (worktree / f"{request.task_id}.txt").write_text(
                    f"initial {request.task_id}\n", encoding="utf-8"
                )
            elif request.attempt_kind == "repair":
                target = worktree / f"{request.task_id}.txt"
                target.write_text(
                    target.read_text(encoding="utf-8")
                    + f"repair after revision {request.worktree_revision}\n",
                    encoding="utf-8",
                )
            result = result_for(request.attempt_kind, request.worktree_revision)
            repair_key = (request.task_id, request.worktree_revision)
            should_request = (
                request.attempt_kind == "task_review"
                and repair_key in {("T1", 2), ("T2", 3)}
                and repair_key not in requested_repairs
            )
            if should_request:
                requested_repairs.add(repair_key)
                finding = {
                    "task_id": request.task_id,
                    "severity": "high",
                    "summary": f"refresh {request.task_id}",
                    "action": f"repair {request.task_id}",
                }
                result["findings"] = [finding]
                result["verdict"] = {
                    "status": "changes_requested",
                    "findings": [finding],
                    "missing_evidence": [],
                    "worktree_revision": request.worktree_revision,
                }
            return result

        result = run_tasks(tasks, Worker(provider=stabilization_provider), run_dir)
        assert result["status"] == "completed", result
        state = project(manifest, read_events(run_dir / "events.jsonl"))
        assert state["worktree_revision"] == 4, state["worktree_revision"]
        for task_id in ("T1", "T2"):
            for kind in ("acceptance", "task_review", "verification"):
                current = []
                for artifact in state["artifact_index"]:
                    if artifact.get("task_id") != task_id or artifact.get("kind") != kind:
                        continue
                    payload = json.loads(
                        (run_dir / artifact["ref"]["path"]).read_text(encoding="utf-8")
                    )
                    if payload.get("worktree_revision") == 4:
                        current.append(payload)
                assert current and current[-1].get("status") == "passed", (task_id, kind)

    print('{"passed": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
