#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_task_packet as packet_adapter
from cpe_runtime.kernel import RunKernel
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.packets import PACKET_ROLE_POLICY, build_packet, verify_packet
from cpe_runtime.scheduler import make_packet_request


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
            request.packet_path == entry["path"]
            and request.packet_sha256 == entry["sha256"]
            and request.task_id == "T1"
            and SENTINEL not in request.prompt
            for request in requests
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
