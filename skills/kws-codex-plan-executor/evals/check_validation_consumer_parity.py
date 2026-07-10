#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.events import append_event, read_events
from cpe_runtime.evidence import put_json
from cpe_runtime.git_delta import capture_snapshot, diff_snapshots
from cpe_runtime.inspection import inspect_run
from cpe_runtime.kernel import RunKernel, Transition, rebuild_snapshot
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.model_policy import CORE_ROUTE
from cpe_runtime.packets import build_packet, packet_entry
from cpe_runtime.projector import project
from cpe_runtime.reconciliation import reconcile
from cpe_runtime.validation import validate_completion, validate_integrity, validate_run


VALIDATOR = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"
EXPECTED_FALSE_COMPLETION_CODES = [
    "current_revision_acceptance_not_passed",
    "current_revision_task_review_not_passed",
    "current_revision_verification_not_passed",
    "current_revision_final_review_not_passed",
    "current_revision_repository_check_missing",
    "completion_audit_missing",
]


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _append(run_dir: Path, event_type: str, payload: dict, *, task_id: str | None = None, attempt_id: str | None = None) -> None:
    append_event(
        run_dir / "events.jsonl",
        {"type": event_type, "payload": payload, "task_id": task_id, "attempt_id": attempt_id},
    )


def _attestation() -> dict[str, object]:
    return {
        "verified": True,
        "actual_model": CORE_ROUTE.model,
        "actual_reasoning": CORE_ROUTE.reasoning,
    }


def _attempt(run_dir: Path, task_id: str | None, attempt_id: str, kind: str, revision: int) -> None:
    _append(
        run_dir,
        "attempt.started",
        {"kind": kind, "worktree_revision": revision},
        task_id=task_id,
        attempt_id=attempt_id,
    )
    _append(
        run_dir,
        "attempt.completed",
        {
            "status": "completed",
            "attestation": _attestation(),
            "usage": {},
            "latency_ms": 1,
            "worktree_revision": revision,
        },
        task_id=task_id,
        attempt_id=attempt_id,
    )


def _verdict(
    run_dir: Path,
    task_id: str | None,
    attempt_id: str,
    *,
    status: str,
    revision: int,
    patch_sha256: str | None,
    packet_sha256: str,
    packet_task_id: str | None = None,
    findings: list[dict] | None = None,
    missing_evidence: list[object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "findings": list(findings or []),
        "missing_evidence": list(missing_evidence or []),
        "worktree_revision": revision,
        "worktree_patch_sha256": patch_sha256,
        "packet_sha256": packet_sha256,
    }
    if packet_task_id is not None:
        payload["packet_task_id"] = packet_task_id
    _append(run_dir, "verdict.recorded", payload, task_id=task_id, attempt_id=attempt_id)
    return payload


def _attach_payload(
    run_dir: Path,
    *,
    kind: str,
    task_id: str,
    attempt_id: str,
    payload: dict[str, object],
) -> dict[str, str]:
    semantic = {**payload, "kind": kind, "task_id": task_id}
    ref = put_json(run_dir, kind, semantic).as_dict()
    _append(
        run_dir,
        "evidence.attached",
        {"kind": kind, "ref": ref},
        task_id=task_id,
        attempt_id=attempt_id,
    )
    return ref


def record_revision(run_dir: Path, task_id: str, content: bytes) -> dict:
    manifest = load_verified_manifest(run_dir / "run_manifest.json")
    state = project(manifest, read_events(run_dir / "events.jsonl"))
    worktree = Path(str(manifest["execution_worktree_ref"])).expanduser().resolve()
    before = capture_snapshot(worktree)
    (worktree / "owned.txt").write_bytes(content)
    after = capture_snapshot(worktree)
    delta = diff_snapshots(before, after, worktree)
    patch_ref = RunKernel(run_dir).store_patch_evidence(delta.patch_bytes)
    _append(
        run_dir,
        "worktree.revision_recorded",
        {
            "from": state["worktree_revision"],
            "to": state["worktree_revision"] + 1,
            "patch_sha256": delta.patch_sha256,
            "patch_ref": patch_ref,
            "changed_files": list(delta.changed_files),
        },
        task_id=task_id,
        attempt_id=f"{task_id}.repair.actual",
    )
    return rebuild_snapshot(run_dir)


def make_v3_run(
    root: Path,
    *,
    false_completion: bool,
    terminal: bool,
    record_audit: bool = True,
    file_claims: list[str] | None = None,
    include_patch_ref: bool = True,
    include_stale_history: bool = False,
    revision_changed_files: list[str] | None = None,
    repository_contradiction: bool = False,
) -> tuple[Path, dict]:
    root.mkdir(parents=True, exist_ok=True)
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# validator fixture\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    worktree = root / "worktree"
    worktree.mkdir()
    _run(["git", "init", "-q"], worktree).check_returncode()
    _run(["git", "config", "user.email", "eval@example.com"], worktree).check_returncode()
    _run(["git", "config", "user.name", "Eval"], worktree).check_returncode()
    (worktree / "owned.txt").write_text("before\n", encoding="utf-8")
    (worktree / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
    _run(["git", "add", "owned.txt", ".gitignore"], worktree).check_returncode()
    _run(["git", "commit", "-q", "-m", "fixture"], worktree).check_returncode()
    head = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
    task = {
        "id": "T1",
        "title": "validator fixture",
        "dependencies": [],
        "file_claims": list(file_claims or ["owned.txt"]),
        "acceptance_command": "true",
    }
    draft = build_packet(SimpleNamespace(sources=(), spec_manifest=None), task)
    manifest = create_manifest(
        "validator-fixture",
        "interactive",
        root,
        worktree,
        plan,
        None,
        [task],
        pricing,
        source_head=head,
    )
    run_dir = root / "run"
    kernel = RunKernel.initialize(run_dir, manifest, [draft])
    manifest = load_verified_manifest(run_dir / "run_manifest.json")
    packet_sha = packet_entry(manifest, "T1")["sha256"]

    _append(run_dir, "run.status_changed", {"from": "created", "to": "ready"})
    _append(run_dir, "run.status_changed", {"from": "ready", "to": "running"})
    _append(run_dir, "task.status_changed", {"from": "pending", "to": "ready"}, task_id="T1")
    _append(run_dir, "task.status_changed", {"from": "ready", "to": "implementing"}, task_id="T1")
    _attempt(run_dir, "T1", "T1.implementation.1", "implementation", 0)

    before_write = capture_snapshot(worktree)
    (worktree / "owned.txt").write_text("after\n", encoding="utf-8")
    after_write = capture_snapshot(worktree)
    delta = diff_snapshots(before_write, after_write, worktree)
    patch_sha = delta.patch_sha256
    patch_ref = kernel.store_patch_evidence(delta.patch_bytes)
    revision_payload = {
        "from": 0,
        "to": 1,
        "patch_sha256": patch_sha,
        "changed_files": list(
            delta.changed_files if revision_changed_files is None else revision_changed_files
        ),
    }
    if include_patch_ref:
        revision_payload["patch_ref"] = patch_ref
    _append(
        run_dir,
        "worktree.revision_recorded",
        revision_payload,
        task_id="T1",
        attempt_id="T1.implementation.1",
    )
    _append(run_dir, "task.status_changed", {"from": "implementing", "to": "reviewing"}, task_id="T1")

    evidence_refs: list[dict] = []
    evidence_records: list[dict[str, object]] = []
    if false_completion:
        acceptance_payload = {
            "kind": "acceptance",
            "task_id": "T1",
            "passed": True,
            "worktree_revision": 0,
            "worktree_patch_sha256": None,
            "packet_sha256": packet_sha,
        }
        acceptance_ref = put_json(run_dir, "acceptance", acceptance_payload).as_dict()
        evidence_refs.append(acceptance_ref)
        evidence_records.append({"kind": "acceptance", "task_id": "T1", "ref": acceptance_ref})
        _append(
            run_dir,
            "evidence.attached",
            {"kind": "acceptance", "ref": acceptance_ref},
            task_id="T1",
            attempt_id="T1.acceptance.1",
        )
        _attempt(run_dir, "T1", "T1.task_review.1", "task_review", 1)
        review_payload = _verdict(
            run_dir,
            "T1",
            "T1.task_review.1",
            status="changes_requested",
            revision=1,
            patch_sha256=patch_sha,
            packet_sha256=packet_sha,
            findings=[{"severity": "critical", "action": "repair false completion"}],
        )
        review_ref = _attach_payload(
            run_dir,
            kind="task_review",
            task_id="T1",
            attempt_id="T1.task_review.1",
            payload=review_payload,
        )
        evidence_refs.append(review_ref)
        evidence_records.append({"kind": "task_review", "task_id": "T1", "ref": review_ref})
        _append(run_dir, "task.status_changed", {"from": "reviewing", "to": "verifying"}, task_id="T1")
        _attempt(run_dir, "T1", "T1.verification.1", "verification", 1)
        verification_payload = _verdict(
            run_dir,
            "T1",
            "T1.verification.1",
            status="passed",
            revision=1,
            patch_sha256=patch_sha,
            packet_sha256=packet_sha,
            missing_evidence=["required device proof"],
        )
        verification_ref = _attach_payload(
            run_dir,
            kind="verification",
            task_id="T1",
            attempt_id="T1.verification.1",
            payload=verification_payload,
        )
        evidence_refs.append(verification_ref)
        evidence_records.append({"kind": "verification", "task_id": "T1", "ref": verification_ref})
        _append(run_dir, "task.status_changed", {"from": "verifying", "to": "completed"}, task_id="T1")
        _attempt(run_dir, None, "run.final_review.1", "final_review", 1)
        final_payload = _verdict(
            run_dir,
            None,
            "run.final_review.1",
            status="changes_requested",
            revision=1,
            patch_sha256=patch_sha,
            packet_sha256=packet_sha,
            packet_task_id="T1",
            findings=[{"severity": "critical", "action": "repair accepted content"}],
        )
        final_ref = _attach_payload(
            run_dir,
            kind="final_review",
            task_id="T1",
            attempt_id="run.final_review.1",
            payload=final_payload,
        )
        evidence_refs.append(final_ref)
        evidence_records.append({"kind": "final_review", "task_id": "T1", "ref": final_ref})
    else:
        if include_stale_history:
            stale_payload = {
                "kind": "acceptance",
                "task_id": "T1",
                "passed": True,
                "worktree_revision": 0,
                "worktree_patch_sha256": None,
                "packet_sha256": packet_sha,
            }
            stale_ref = put_json(run_dir, "acceptance", stale_payload).as_dict()
            _append(
                run_dir,
                "evidence.attached",
                {"kind": "acceptance", "ref": stale_ref},
                task_id="T1",
                attempt_id="T1.acceptance.old",
            )
        acceptance_payload = {
            "kind": "acceptance",
            "task_id": "T1",
            "passed": True,
            "worktree_revision": 1,
            "worktree_patch_sha256": patch_sha,
            "packet_sha256": packet_sha,
        }
        acceptance_ref = put_json(run_dir, "acceptance", acceptance_payload).as_dict()
        evidence_refs.append(acceptance_ref)
        evidence_records.append({"kind": "acceptance", "task_id": "T1", "ref": acceptance_ref})
        _append(run_dir, "evidence.attached", {"kind": "acceptance", "ref": acceptance_ref}, task_id="T1")
        _attempt(run_dir, "T1", "T1.task_review.1", "task_review", 1)
        review_payload = _verdict(run_dir, "T1", "T1.task_review.1", status="passed", revision=1, patch_sha256=patch_sha, packet_sha256=packet_sha)
        review_ref = _attach_payload(run_dir, kind="task_review", task_id="T1", attempt_id="T1.task_review.1", payload=review_payload)
        evidence_refs.append(review_ref)
        evidence_records.append({"kind": "task_review", "task_id": "T1", "ref": review_ref})
        _append(run_dir, "task.status_changed", {"from": "reviewing", "to": "verifying"}, task_id="T1")
        _attempt(run_dir, "T1", "T1.verification.1", "verification", 1)
        verification_payload = _verdict(run_dir, "T1", "T1.verification.1", status="passed", revision=1, patch_sha256=patch_sha, packet_sha256=packet_sha)
        verification_ref = _attach_payload(run_dir, kind="verification", task_id="T1", attempt_id="T1.verification.1", payload=verification_payload)
        evidence_refs.append(verification_ref)
        evidence_records.append({"kind": "verification", "task_id": "T1", "ref": verification_ref})
        _append(run_dir, "task.status_changed", {"from": "verifying", "to": "completed"}, task_id="T1")
        repository_payload = {
            "kind": "repository_check",
            "task_id": "T1",
            "passed": True,
            "worktree_revision": 1,
            "worktree_patch_sha256": patch_sha,
            "packet_sha256": packet_sha,
            "commands": ["true"],
        }
        if repository_contradiction:
            repository_payload["status"] = "failed"
        repository_ref = put_json(run_dir, "repository_check", repository_payload).as_dict()
        evidence_refs.append(repository_ref)
        evidence_records.append({"kind": "repository_check", "task_id": "T1", "ref": repository_ref})
        _append(run_dir, "evidence.attached", {"kind": "repository_check", "ref": repository_ref}, task_id="T1")
        _attempt(run_dir, None, "run.final_review.1", "final_review", 1)
        final_payload = _verdict(run_dir, None, "run.final_review.1", status="passed", revision=1, patch_sha256=patch_sha, packet_sha256=packet_sha, packet_task_id="T1")
        final_ref = _attach_payload(run_dir, kind="final_review", task_id="T1", attempt_id="run.final_review.1", payload=final_payload)
        evidence_refs.append(final_ref)
        evidence_records.append({"kind": "final_review", "task_id": "T1", "ref": final_ref})
        if record_audit:
            _append(
                run_dir,
                "completion.recorded",
                {
                    "passed": True,
                    "prompt_to_artifact_checklist": evidence_records,
                    "verification_evidence": evidence_refs,
                    "residual_risk": [],
                },
            )

    if terminal:
        _append(run_dir, "run.status_changed", {"from": "running", "to": "completed"})
    state = project(manifest, read_events(run_dir / "events.jsonl"))
    (run_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return run_dir, state


def _standalone_codes(run_dir: Path, *, completion: bool = False) -> list[str]:
    command = [sys.executable, str(VALIDATOR), str(run_dir)]
    if completion:
        command.extend(["--profile", "completion"])
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 1, result.stderr or result.stdout
    return list(json.loads(result.stdout)["errors"])


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-validator-parity-") as raw:
        root = Path(raw)
        running_run, running_state = make_v3_run(root / "running", false_completion=True, terminal=False)
        integrity = validate_integrity(running_run)
        completion = validate_completion(running_run)
        checks["healthy_running_integrity_passes"] = integrity.passed
        checks["false_completion_fails"] = completion.errors == EXPECTED_FALSE_COMPLETION_CODES
        checks["stale_evidence_is_integrity_warning"] = "stale_revision_evidence" in integrity.warnings
        try:
            RunKernel(running_run).transition(
                Transition("run.status_changed", {"from": "running", "to": "completed"})
            )
        except ValueError as exc:
            kernel_codes = str(exc).partition(": ")[2].split(",")
        else:
            kernel_codes = []
        checks["kernel_uses_canonical_codes"] = kernel_codes == EXPECTED_FALSE_COMPLETION_CODES
        checks["kernel_rejection_is_non_mutating"] = project(
            load_verified_manifest(running_run / "run_manifest.json"), read_events(running_run / "events.jsonl")
        ) == running_state
        running_reconciliation_codes = [
            item["code"] for item in reconcile(running_run, completion=True).findings
        ]
        running_inspection_codes = inspect_run(running_run, completion=True)["errors"]
        running_standalone_codes = _standalone_codes(running_run, completion=True)
        checks["same_running_candidate_has_consumer_parity"] = all(
            codes == EXPECTED_FALSE_COMPLETION_CODES
            for codes in (
                running_reconciliation_codes,
                running_inspection_codes,
                running_standalone_codes,
            )
        )

        terminal_run, _ = make_v3_run(root / "terminal", false_completion=True, terminal=True)
        adapter_codes = validate_run(terminal_run).errors
        reconciliation_codes = [item["code"] for item in reconcile(terminal_run).findings]
        inspection_codes = inspect_run(terminal_run)["errors"]
        standalone_codes = _standalone_codes(terminal_run)
        checks["all_completion_consumers_share_ordered_codes"] = all(
            codes == EXPECTED_FALSE_COMPLETION_CODES
            for codes in (adapter_codes, reconciliation_codes, inspection_codes, standalone_codes)
        )

        healthy_run, healthy_state = make_v3_run(root / "healthy", false_completion=False, terminal=False)
        checks["healthy_completion_candidate_passes"] = validate_completion(
            healthy_run, candidate_state=healthy_state
        ).passed

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
