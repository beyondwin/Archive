#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe import resume_run
from cpe_runtime.evidence import put_json
from cpe_runtime.git_delta import capture_snapshot, diff_snapshots
from cpe_runtime.kernel import RunKernel, Transition
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.model_policy import CORE_ROUTE, SCOUT_ROUTE
from cpe_runtime.packets import build_packet, packet_entry
from cpe_runtime.reconciliation import ResumeDecision, select_resume
from cpe_runtime.validation import ValidationReport
from cpe_runtime.worker import Worker


def report(*errors: str) -> ValidationReport:
    return ValidationReport("invalid" if errors else "valid", not errors, list(errors), [], {})


def blocked(category: str, root: str, *, owner: str = "cpe") -> dict:
    ref = {"kind": "blocker_evidence", "path": "artifacts/evidence/blocker_evidence/a.json", "sha256": "a" * 64, "media_type": "application/json"}
    blocker = {"blocker_id": "B1", "task_id": "T1", "category": category, "root_cause_key": root, "owner": owner, "evidence_refs": [ref]}
    return {
        "lifecycle": "blocked",
        "worktree_revision": 2,
        "current_task": None,
        "tasks": {"T1": {"status": "blocked"}},
        "attempts": [],
        "active_blockers": [blocker],
        "artifact_index": [{"task_id": "T1", "kind": "blocker_evidence", "ref": ref}],
    }


def provider_result(role: str, revision: int) -> dict[str, object]:
    verdict = None
    if role in {"task_review", "verification", "final_review"}:
        verdict = {"status": "passed", "findings": [], "missing_evidence": [], "worktree_revision": revision}
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


def interrupted_run(root: Path) -> tuple[str, Path]:
    run_id = "recovery-integration"
    codex_home = root / "codex"
    run_dir = codex_home / "orchestrator" / run_id
    worktree = root / "worktree"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "cpe@example.invalid"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "CPE Fixture"], cwd=worktree, check=True)
    (worktree / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=worktree, check=True)
    subprocess.run(["git", "checkout", "-qb", f"codex/{run_id}"], cwd=worktree, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    task = {"id": "T1", "title": "recover", "dependencies": [], "file_claims": ["owned.txt"], "acceptance_command": "true"}
    draft = build_packet(SimpleNamespace(sources=(), spec_manifest=None), task)
    manifest = create_manifest(run_id, "interactive", root, worktree, plan, None, [task], pricing, source_head=head)
    kernel = RunKernel.initialize(run_dir, manifest, [draft])
    packet_sha = packet_entry(load_verified_manifest(run_dir / "run_manifest.json"), "T1")["sha256"]
    kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
    kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
    kernel.transition(Transition("task.status_changed", {"from": "pending", "to": "ready"}, task_id="T1"))
    kernel.transition(Transition("task.status_changed", {"from": "ready", "to": "implementing"}, task_id="T1"))
    kernel.transition(Transition("attempt.started", {"kind": "implementation", "worktree_revision": 0, "packet_sha256": packet_sha}, task_id="T1", attempt_id="T1.implementation.1"))
    before = capture_snapshot(worktree)
    (worktree / "owned.txt").write_text("implemented\n", encoding="utf-8")
    after = capture_snapshot(worktree)
    delta = diff_snapshots(before, after, worktree)
    patch_ref = kernel.store_patch_evidence(delta.patch_bytes)
    kernel.transition(
        Transition(
            "worktree.revision_recorded",
            {"from": 0, "to": 1, "patch_sha256": delta.patch_sha256, "patch_ref": patch_ref, "changed_files": list(delta.changed_files), "attempt_id": "T1.implementation.1"},
            task_id="T1",
            attempt_id="T1.implementation.1",
        )
    )
    kernel.transition(
        Transition(
            "attempt.completed",
            {
                "status": "completed",
                "attestation": {"verified": True, "actual_model": CORE_ROUTE.model, "actual_reasoning": CORE_ROUTE.reasoning},
                "usage": {},
                "latency_ms": 1,
            },
            task_id="T1",
            attempt_id="T1.implementation.1",
        )
    )
    kernel.transition(Transition("task.status_changed", {"from": "implementing", "to": "reviewing"}, task_id="T1"))
    kernel.transition(Transition("task.status_changed", {"from": "reviewing", "to": "verifying"}, task_id="T1"))
    ref = put_json(run_dir, "recovery", {"task_id": "T1", "phase": "verification", "reason": "interrupted"}).as_dict()
    kernel.transition(Transition("evidence.attached", {"kind": "recovery", "ref": ref}, task_id="T1"))
    kernel.transition(Transition("blocker.opened", {"blocker_id": "B1", "category": "verification_interrupted", "root_cause_key": "verification:interrupted", "owner": "cpe", "resume_condition": "rerun acceptance", "evidence_refs": [ref]}, task_id="T1"))
    kernel.transition(Transition("task.status_changed", {"from": "verifying", "to": "blocked"}, task_id="T1"))
    kernel.transition(Transition("run.status_changed", {"from": "running", "to": "blocked"}))
    os.environ["CODEX_HOME"] = str(codex_home)
    return run_id, run_dir


def main() -> int:
    matrix = {
        ("implementation_interrupted", "implementation:interrupted"): "implementation",
        ("acceptance_failed", "acceptance:1"): "repair",
        ("task_review_interrupted", "task_review:interrupted"): "task_review",
        ("task_review_changes_requested", "task_review:changes_requested"): "repair",
        ("verification_interrupted", "verification:interrupted"): "acceptance",
        ("verification_failed", "verification:failed"): "repair",
        ("review_evidence_and_run_integrity", "scheduled_retry:repair"): "repair",
        (
            "runtime_blocked",
            "repair:repair_did_not_advance_revision:scheduled_retry:repair",
        ): "repair",
        (
            "runtime_blocked",
            "repair:repair_did_not_advance_revision:t2_review_evidence_not_fail_closed",
        ): "repair",
    }
    for (category, root), phase in matrix.items():
        decision = select_resume(blocked(category, root), report())
        assert decision == ResumeDecision("retry", phase, "B1", decision.evidence_refs), decision
        assert decision.evidence_refs, decision

    legacy_transient = blocked("transient", "transient:WorkerError")
    legacy_transient["attempts"] = [
        {
            "attempt_id": "T1.task_review.1",
            "task_id": "T1",
            "kind": "task_review",
            "status": "failed",
        }
    ]
    transient_decision = select_resume(legacy_transient, report())
    assert transient_decision.action == "retry", transient_decision
    assert transient_decision.phase == "task_review", transient_decision

    revalidated_scope = select_resume(
        blocked("policy_violation", "task_scope:T1:nested/state.json"), report()
    )
    assert revalidated_scope.action == "retry", revalidated_scope
    assert revalidated_scope.phase == "implementation", revalidated_scope

    operator = select_resume(blocked("operator_review", "operator:decision", owner="operator"), report())
    assert operator.action == "remain_blocked" and operator.phase is None, operator

    invalid = select_resume(blocked("verification_failed", "verification:failed"), report("packet_digest_mismatch"))
    assert invalid.action == "reject" and invalid.phase is None, invalid

    unindexed = blocked("verification_failed", "verification:failed")
    unindexed["artifact_index"] = []
    assert select_resume(unindexed, report()).action == "reject"

    with tempfile.TemporaryDirectory(prefix="cpe-resume-") as raw:
        run_id, run_dir = interrupted_run(Path(raw))
        worker = Worker(provider=lambda request, _argv: provider_result(request.attempt_kind, request.worktree_revision))
        assert resume_run(run_id, worker=worker) == 0
        completed = load_verified_manifest(run_dir / "run_manifest.json")
        from cpe_runtime.events import read_events
        from cpe_runtime.projector import project
        state = project(completed, read_events(run_dir / "events.jsonl"))
        assert state["lifecycle"] == "completed", state
        assert state["tasks"]["T1"]["status"] == "completed", state
        assert state["blocker_history"][0]["status"] == "resolved", state
        assert state["retry_queue"][-1]["phase"] == "acceptance", state

    with tempfile.TemporaryDirectory(prefix="cpe-resume-invalid-") as raw:
        run_id, run_dir = interrupted_run(Path(raw))
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        packet = run_dir / manifest["task_packets"][0]["path"]
        packet.write_text(packet.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        before_events = (run_dir / "events.jsonl").read_bytes()
        assert resume_run(run_id, worker=Worker(provider=lambda _request, _argv: (_ for _ in ()).throw(AssertionError("worker must not run")))) == 2
        assert (run_dir / "events.jsonl").read_bytes() == before_events, "invalid packet resume mutated events"

    with tempfile.TemporaryDirectory(prefix="cpe-resume-missing-worktree-") as raw:
        run_id, run_dir = interrupted_run(Path(raw))
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        worktree = Path(manifest["execution_worktree_ref"]).expanduser()
        parked = worktree.with_name("parked-worktree")
        worktree.rename(parked)
        assert resume_run(run_id, worker=Worker(provider=lambda _request, _argv: (_ for _ in ()).throw(AssertionError("worker must not run")))) == 1
        from cpe_runtime.events import read_events
        from cpe_runtime.projector import project
        state = project(manifest, read_events(run_dir / "events.jsonl"))
        assert any(item["category"] == "workspace_precondition" for item in state["active_blockers"]), state
        first_missing_events = (run_dir / "events.jsonl").read_bytes()
        first_missing_artifacts = list(state["artifact_index"])
        assert resume_run(run_id, worker=Worker(provider=lambda _request, _argv: (_ for _ in ()).throw(AssertionError("worker must not run")))) == 1
        repeated = project(manifest, read_events(run_dir / "events.jsonl"))
        assert (run_dir / "events.jsonl").read_bytes() == first_missing_events, "repeated missing-worktree resume appended events"
        assert repeated["artifact_index"] == first_missing_artifacts, "repeated missing-worktree resume duplicated evidence"
        assert len([item for item in repeated["active_blockers"] if item["category"] == "workspace_precondition"]) == 1
        parked.rename(worktree)
        worker = Worker(provider=lambda request, _argv: provider_result(request.attempt_kind, request.worktree_revision))
        assert resume_run(run_id, worker=worker) == 0
        state = project(manifest, read_events(run_dir / "events.jsonl"))
        assert state["lifecycle"] == "completed", state

    print('{"passed": true, "checks": {"resume_matrix": true, "operator_blocker": true, "digest_reject": true, "indexed_evidence": true, "blocked_resume_completed": true, "invalid_packet_non_mutating": true, "missing_worktree_idempotent": true}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
