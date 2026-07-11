#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.evidence import put_json
from cpe_runtime.events import read_events
from cpe_runtime.kernel import RunKernel, Transition
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.packets import build_packet, packet_entry
from cpe_runtime.repair import apply_repair
from cpe_runtime.validation import validate_completion


def fixture(root: Path) -> tuple[Path, RunKernel]:
    run_id = "repair-fixture"
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
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    task = {"id": "T1", "title": "repair", "dependencies": [], "file_claims": ["owned.txt"], "acceptance_command": "true"}
    draft = build_packet(SimpleNamespace(sources=(), spec_manifest=None), task)
    manifest = create_manifest(run_id, "interactive", root, worktree, plan, None, [task], pricing, source_head=head)
    run_dir = root / "run"
    kernel = RunKernel.initialize(run_dir, manifest, [draft])
    return run_dir, kernel


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as raw:
        run_dir, kernel = fixture(Path(raw))
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        adapter = Path(__file__).resolve().parents[1] / "scripts" / "repair_runs.py"
        dry_run = subprocess.run(
            [sys.executable, str(adapter), "--run-dir", str(run_dir), "--dry-run"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert dry_run.returncode == 0, dry_run
        assert json.loads(dry_run.stdout)["dry_run"] is True, dry_run.stdout
        before = read_events(run_dir / "events.jsonl")
        result = apply_repair(
            run_dir,
            "mark_stale_attempt_interrupted",
            details={"attempt_id": "missing"},
            expected_projection_delta={"attempt_status:missing": "interrupted"},
        )
        assert result["applied"] is False, result
        assert result["reason"] == "expected_projection_delta_not_observed", result
        assert read_events(run_dir / "events.jsonl") == before, "a no-op repair must append no event"

        try:
            apply_repair(run_dir, "mark_stale_attempt_interrupted", details={"attempt_id": "missing"}, expected_projection_delta={})
        except ValueError as exc:
            assert str(exc) == "expected_projection_delta_required", exc
        else:
            raise AssertionError("repair accepted an empty projection delta")

        kernel.transition(Transition("task.status_changed", {"from": "pending", "to": "ready"}, task_id="T1"))
        kernel.transition(Transition("task.status_changed", {"from": "ready", "to": "implementing"}, task_id="T1"))
        kernel.transition(Transition("task.status_changed", {"from": "implementing", "to": "reviewing"}, task_id="T1"))
        kernel.transition(Transition("task.status_changed", {"from": "reviewing", "to": "verifying"}, task_id="T1"))
        kernel.transition(
            Transition(
                "attempt.started",
                {"kind": "verification", "worktree_revision": 0},
                task_id="T1",
                attempt_id="T1.verification.interrupted",
            )
        )
        recovery_ref = put_json(
            run_dir,
            "recovery",
            {"attempt_id": "T1.verification.interrupted", "reason": "process_exit"},
        ).as_dict()
        kernel.transition(
            Transition(
                "evidence.attached",
                {"kind": "recovery", "ref": recovery_ref},
                task_id="T1",
                attempt_id="T1.verification.interrupted",
            )
        )
        before_wrong = read_events(run_dir / "events.jsonl")
        try:
            apply_repair(
                run_dir,
                "mark_stale_attempt_interrupted",
                details={"attempt_id": "T1.verification.interrupted", "evidence_refs": [recovery_ref]},
                expected_projection_delta={"tasks.T1.status": "completed"},
            )
        except ValueError as exc:
            assert str(exc) == "expected_projection_delta_mismatch", exc
        else:
            raise AssertionError("contradictory expected delta was accepted")
        assert read_events(run_dir / "events.jsonl") == before_wrong, "wrong expected delta mutated the run"

        interrupted = apply_repair(
            run_dir,
            "mark_stale_attempt_interrupted",
            details={"attempt_id": "T1.verification.interrupted", "evidence_refs": [recovery_ref]},
        )
        assert interrupted["applied"] is True, interrupted
        attempts = kernel.state["attempts"]
        assert next(item for item in attempts if item["attempt_id"] == "T1.verification.interrupted")["status"] == "interrupted"

        invalid_ref = dict(recovery_ref, sha256="0" * 64)
        before_invalid = read_events(run_dir / "events.jsonl")
        invalid = apply_repair(
            run_dir,
            "reconnect_existing_evidence",
            details={"task_id": "T1", "ref": invalid_ref},
        )
        assert invalid["applied"] is False, invalid
        assert read_events(run_dir / "events.jsonl") == before_invalid, "invalid evidence ref was connected"

        candidate_payload = {
            "kind": "verification",
            "task_id": "T1",
            "attempt_id": "T1.verification.interrupted",
            "status": "passed",
        }
        candidate_ref = put_json(run_dir, "verification", candidate_payload).as_dict()
        before_provenance = read_events(run_dir / "events.jsonl")
        for bad_details in (
            {"task_id": "missing", "attempt_id": "T1.verification.interrupted", "ref": candidate_ref},
            {"task_id": "T1", "attempt_id": "missing", "ref": candidate_ref},
        ):
            rejected = apply_repair(run_dir, "reconnect_existing_evidence", details=bad_details)
            assert rejected["applied"] is False, rejected
            assert read_events(run_dir / "events.jsonl") == before_provenance, "bad provenance mutated events"

        connected = apply_repair(
            run_dir,
            "reconnect_existing_evidence",
            details={"task_id": "T1", "attempt_id": "T1.verification.interrupted", "sha256": candidate_ref["sha256"]},
        )
        assert connected["applied"] is True, connected
        assert connected["validation"]["passed"] is True, connected

        duplicate_payload = {"task_id": "T1", "purpose": "ambiguous reconnect"}
        first_duplicate = put_json(run_dir, "recovery", duplicate_payload).as_dict()
        second_duplicate = put_json(run_dir, "blocker_evidence", duplicate_payload).as_dict()
        assert first_duplicate["sha256"] == second_duplicate["sha256"]
        before_duplicate = read_events(run_dir / "events.jsonl")
        ambiguous = apply_repair(
            run_dir,
            "reconnect_existing_evidence",
            details={"task_id": "T1", "sha256": first_duplicate["sha256"]},
        )
        assert ambiguous["applied"] is False, ambiguous
        assert read_events(run_dir / "events.jsonl") == before_duplicate, "ambiguous digest mutated events"

        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        packet_sha = packet_entry(manifest, "T1")["sha256"]
        binding = {
            "worktree_revision": 0,
            "worktree_patch_sha256": None,
            "packet_sha256": packet_sha,
        }
        acceptance_id = "T1.acceptance.1"
        acceptance_ref = put_json(
            run_dir,
            "acceptance",
            {
                "kind": "acceptance",
                "task_id": "T1",
                "attempt_id": acceptance_id,
                "status": "passed",
                "passed": True,
                "findings": [],
                "missing_evidence": [],
                **binding,
            },
        ).as_dict()
        acceptance = apply_repair(
            run_dir,
            "reconnect_existing_evidence",
            details={"task_id": "T1", "attempt_id": acceptance_id, "ref": acceptance_ref},
        )
        assert acceptance["applied"] is True and acceptance["validation"]["passed"] is True, acceptance

        repository_id = "run.repository_checks.0.1"
        repository_ref = put_json(
            run_dir,
            "repository_check",
            {
                "kind": "repository_check",
                "task_id": "T1",
                "attempt_id": repository_id,
                "status": "passed",
                "passed": True,
                "findings": [],
                "missing_evidence": [],
                **binding,
            },
        ).as_dict()
        repository = apply_repair(
            run_dir,
            "reconnect_existing_evidence",
            details={"task_id": "T1", "attempt_id": repository_id, "ref": repository_ref},
        )
        assert repository["applied"] is True and repository["validation"]["passed"] is True, repository
        completion_errors = validate_completion(run_dir).errors
        assert "current_revision_acceptance_not_passed" not in completion_errors, completion_errors
        assert "current_revision_repository_check_missing" not in completion_errors, completion_errors

        for kind, malformed_id, malformed_binding in (
            ("acceptance", "T1.acceptance.01", binding),
            ("acceptance", "T1.acceptance.2", {**binding, "worktree_revision": 1}),
            ("repository_check", "run.repository_checks.1.1", {**binding, "worktree_revision": 1}),
            ("repository_check", "run.repository_checks.0.2", binding),
        ):
            malformed_ref = put_json(
                run_dir,
                kind,
                {
                    "kind": kind,
                    "task_id": "T1",
                    "attempt_id": malformed_id,
                    "status": "passed",
                    "passed": True,
                    "findings": [],
                    "missing_evidence": [],
                    **malformed_binding,
                },
            ).as_dict()
            before_malformed = read_events(run_dir / "events.jsonl")
            malformed = apply_repair(
                run_dir,
                "reconnect_existing_evidence",
                details={"task_id": "T1", "attempt_id": malformed_id, "ref": malformed_ref},
            )
            assert malformed["applied"] is False, malformed
            assert read_events(run_dir / "events.jsonl") == before_malformed, "malformed synthetic evidence mutated events"

    print('{"passed": true, "checks": {"run_dir_adapter": true, "no_op_false": true, "delta_required": true, "wrong_delta_no_mutation": true, "stale_attempt_evidence": true, "invalid_reconnect_rejected": true, "reconnect_provenance": true, "ambiguous_digest_rejected": true, "synthetic_acceptance_reconnected": true, "synthetic_repository_check_reconnected": true, "malformed_synthetic_rejected": true}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
