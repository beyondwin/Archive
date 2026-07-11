#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_task_packet as packet_adapter
from cpe_runtime.kernel import RunKernel
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.model_policy import CORE_ROUTE
from cpe_runtime.packets import PACKET_ROLE_POLICY, build_packet, export_packet, verify_packet
from cpe_runtime import scheduler
from cpe_runtime.scheduler import make_packet_request
from cpe_runtime.worker import WorkerResult


SENTINEL = "CPE_PACKET_SENTINEL_7d3e2d"


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-packet-") as raw:
        root = Path(raw)
        worktree = root / "worktree"
        worktree.mkdir()
        plan = root / "plan.md"
        spec = root / "spec.md"
        pricing = root / "pricing.json"
        plan.write_text("# Plan\n", encoding="utf-8")
        spec_text = "# Spec\nPacket section.\n"
        spec.write_text(spec_text, encoding="utf-8")
        pricing.write_text("{}\n", encoding="utf-8")
        section_text = "Packet section.\n"
        task = {
            "id": "T1",
            "title": "Packet task",
            "dependencies": [],
            "file_claims": ["src/example.py"],
            "spec_refs": ["S1"],
            "acceptance_command": "python3 -m pytest",
            "prompt": f"Implement the bounded change. {SENTINEL}",
            "execution_contract": {
                "allowed_paths": ["src/example.py"],
                "forbidden_paths": ["run_manifest.json", "events.jsonl", "state.json"],
                "acceptance_command": "python3 -m pytest",
            },
            "source_hashes": {
                "plan": hashlib.sha256(plan.read_bytes()).hexdigest(),
                "spec_sections": {"S1": hashlib.sha256(section_text.encode()).hexdigest()},
            },
        }
        compiled = SimpleNamespace(
            tasks=(task,),
            spec_manifest={
                "sections": {
                    "S1": {
                        "line_start": 2,
                        "line_end": 2,
                        "sha256": hashlib.sha256(section_text.encode()).hexdigest(),
                    }
                }
            },
            sources=(
                SimpleNamespace(
                    role="plan",
                    content=plan.read_bytes(),
                    sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
                ),
                SimpleNamespace(
                    role="spec",
                    content=spec.read_bytes(),
                    sha256=hashlib.sha256(spec.read_bytes()).hexdigest(),
                ),
            ),
        )

        draft = build_packet(compiled, task)
        payload = json.loads(draft.content)
        checks["canonical_v31_packet_contains_sentinel"] = (
            draft.task_id == "T1"
            and draft.relative_path == "artifacts/task-packets/T1.json"
            and draft.media_type == "application/json"
            and payload["schema_version"] == "3.1"
            and SENTINEL in payload["task"]["prompt"]
            and hashlib.sha256(draft.content).hexdigest() == draft.sha256
        )
        checks["six_role_policy_is_serialized"] = (
            set(PACKET_ROLE_POLICY)
            == {"scout", "implementation", "task_review", "verification", "repair", "final_review"}
            and payload["role_policy"] == PACKET_ROLE_POLICY
            and all(
                set(policy) == {"read_only", "verdict_capable", "product_write"}
                and all(isinstance(value, bool) for value in policy.values())
                for policy in PACKET_ROLE_POLICY.values()
            )
        )

        manifest = create_manifest("packet-fixture", "interactive", root, worktree, plan, spec, [task], pricing)
        run_dir = root / "run"
        RunKernel.initialize(run_dir, manifest, [draft])
        verified_manifest = load_verified_manifest(run_dir / "run_manifest.json")
        entry = verified_manifest["task_packets"][0]
        verified = verify_packet(run_dir, verified_manifest, "T1")
        checks["kernel_indexes_and_verifies_packet"] = (
            entry
            == {
                "task_id": "T1",
                "path": draft.relative_path,
                "media_type": draft.media_type,
                "sha256": draft.sha256,
            }
            and verified == draft
        )

        raw_task = {
            "id": "T1",
            "title": "Packet task",
            "depends_on": [],
            "files": ["src/example.py"],
            "spec_refs": ["S1"],
            "acceptance_command": "python3 -m pytest",
            "body": f"Implement the bounded change. {SENTINEL}",
        }
        adapter_draft = packet_adapter.build_packet(
            {"plan": str(plan), "tasks": [raw_task]},
            "T1",
            spec,
            compiled.spec_manifest,
        )
        checks["public_builder_is_thin_canonical_adapter"] = (
            adapter_draft.media_type == draft.media_type
            and json.loads(adapter_draft.content)["schema_version"] == "3.1"
            and SENTINEL in adapter_draft.content.decode("utf-8")
        )
        try:
            packet_adapter.build_packet(
                {"plan": str(plan), "tasks": [{**raw_task, "spec_refs": []}]},
                "T1",
                spec,
                compiled.spec_manifest,
            )
        except ValueError as exc:
            checks["public_builder_rejects_missing_explicit_mapping"] = str(exc) == "missing_explicit_spec_mapping"
        else:
            checks["public_builder_rejects_missing_explicit_mapping"] = False

        export_path = root / "exported-task-packet.json"
        with patch("cpe_runtime.packets.os.fsync", wraps=os.fsync) as synced:
            export_packet(export_path, draft)
        checks["public_export_is_fsynced"] = synced.call_count == 1
        preserved = export_path.read_bytes()
        try:
            export_packet(export_path, draft)
        except FileExistsError:
            checks["public_export_never_overwrites"] = export_path.read_bytes() == preserved
        else:
            checks["public_export_never_overwrites"] = False
        symlink_target = root / "symlink-target.json"
        symlink_target.write_bytes(b"preserve-me\n")
        symlink_path = root / "symlink-export.json"
        symlink_path.symlink_to(symlink_target)
        try:
            export_packet(symlink_path, draft)
        except OSError:
            checks["public_export_refuses_symlink"] = symlink_target.read_bytes() == b"preserve-me\n"
        else:
            checks["public_export_refuses_symlink"] = False

        roles = ("implementation", "task_review", "verification", "repair", "final_review")
        requests = [
            make_packet_request(
                run_dir,
                verified_manifest,
                "T1",
                f"T1.{role}.1",
                role,
                "Consume the verified packet.",
                worktree,
            )
            for role in roles
        ]
        checks["all_dispatch_roles_receive_manifest_packet"] = all(
            request.packet_path == str((run_dir / entry["path"]).resolve())
            and request.packet_sha256 == entry["sha256"]
            and request.task_id == "T1"
            and SENTINEL not in request.prompt
            for request in requests
        )

        task_two = {
            **task,
            "id": "T2",
            "title": "Second packet task",
            "file_claims": ["src/second.py"],
            "execution_contract": {
                **task["execution_contract"],
                "allowed_paths": ["src/second.py"],
            },
        }
        draft_two = build_packet(compiled, task_two)
        multi_manifest = create_manifest(
            "multi-packet-fixture",
            "interactive",
            root,
            worktree,
            plan,
            spec,
            [task, task_two],
            pricing,
        )
        multi_run_dir = root / "multi-run"
        multi_kernel = RunKernel.initialize(multi_run_dir, multi_manifest, [draft, draft_two])
        final_review_requests = []

        class RecordingWorker:
            def run(self, request):
                final_review_requests.append(request)
                return WorkerResult(
                    "completed",
                    {
                        "status": "completed",
                        "summary": "reviewed",
                        "changed_files": [],
                        "findings": [],
                        "evidence_refs": [],
                        "missing_evidence": [],
                        "verification": [],
                    },
                    {
                        "verified": True,
                        "actual_model": CORE_ROUTE.model,
                        "actual_reasoning": CORE_ROUTE.reasoning,
                    },
                    {},
                    0,
                    "0" * 64,
                )

        run_final_reviews = getattr(scheduler, "run_final_reviews", None)
        if run_final_reviews is None:
            checks["multi_task_final_review_consumes_every_packet"] = False
        else:
            results = run_final_reviews(
                [task, task_two], RecordingWorker(), multi_kernel, worktree
            )
            multi_entries = {
                entry["task_id"]: entry
                for entry in load_verified_manifest(
                    multi_run_dir / "run_manifest.json"
                )["task_packets"]
            }
            checks["multi_task_final_review_consumes_every_packet"] = (
                len(results) == 2
                and [request.task_id for request in final_review_requests] == ["T1", "T2"]
                and all(
                    request.attempt_kind == "final_review"
                    and request.packet_path
                    == str(
                        (
                            multi_run_dir
                            / multi_entries[request.task_id]["path"]
                        ).resolve()
                    )
                    and request.packet_sha256 == multi_entries[request.task_id]["sha256"]
                    for request in final_review_requests
                )
            )

        packet_path = run_dir / draft.relative_path
        packet_path.write_bytes(draft.content.replace(SENTINEL.encode(), b"MUTATED_PACKET_SENTINEL"))
        try:
            verify_packet(run_dir, verified_manifest, "T1")
        except ValueError as exc:
            checks["packet_mutation_fails_closed"] = str(exc) == "packet_digest_mismatch"
        else:
            checks["packet_mutation_fails_closed"] = False

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
