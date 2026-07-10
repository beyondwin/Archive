#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.events import read_events, validate_chain
from cpe_runtime.kernel import RunKernel, Transition, rebuild_snapshot
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.packets import PACKET_MEDIA_TYPE, PacketDraft, canonical_packet_bytes
from cpe_runtime.projector import project


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-replay-") as raw:
        root = Path(raw)
        worktree = root / "worktree"
        worktree.mkdir()
        plan = root / "plan.md"
        pricing = root / "pricing.json"
        plan.write_text("# Replay plan\n", encoding="utf-8")
        pricing.write_text("{}\n", encoding="utf-8")
        task = {
            "id": "T1",
            "title": "Replay task",
            "dependencies": [],
            "file_claims": ["owned.txt"],
            "spec_refs": [],
            "acceptance_command": "true",
        }
        packet_content = canonical_packet_bytes({"schema_version": "3.1", "task_id": "T1"})
        packet = PacketDraft(
            "T1",
            "artifacts/task-packets/T1.json",
            PACKET_MEDIA_TYPE,
            hashlib.sha256(packet_content).hexdigest(),
            packet_content,
        )
        manifest = create_manifest(
            "replay-fixture", "interactive", root, worktree, plan, None, [task], pricing
        )
        run_dir = root / "run"
        kernel = RunKernel.initialize(run_dir, manifest, [packet])
        evidence_ref = {
            "kind": "verification",
            "path": "artifacts/evidence/blocker.json",
            "sha256": "b" * 64,
            "media_type": "application/json",
        }
        commands = [
            Transition("task.status_changed", {"from": "pending", "to": "blocked"}, task_id="T1"),
            Transition(
                "blocker.opened",
                {
                    "blocker_id": "B1",
                    "category": "verification",
                    "root_cause_key": "acceptance:1",
                    "owner": "cpe",
                    "resume_condition": "acceptance passes",
                },
                task_id="T1",
            ),
            Transition("blocker.updated", {"blocker_id": "B1", "owner": "operator"}, task_id="T1"),
            Transition(
                "blocker.resolved",
                {"blocker_id": "B1", "evidence_refs": [evidence_ref]},
                task_id="T1",
            ),
            Transition(
                "task.retry_scheduled",
                {
                    "phase": "acceptance",
                    "root_cause_key": "acceptance:1",
                    "worktree_revision": 0,
                    "evidence_refs": [evidence_ref],
                },
                task_id="T1",
            ),
            Transition(
                "worktree.revision_recorded",
                {
                    "from": 0,
                    "to": 1,
                    "patch_sha256": "a" * 64,
                    "changed_files": ["owned.txt"],
                    "attempt_id": "A1",
                },
                task_id="T1",
                attempt_id="A1",
            ),
        ]
        for command in commands:
            kernel.transition(command)

        stored = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        verified_manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
        replayed = project(verified_manifest, events)
        (run_dir / "state.json").unlink()
        rebuilt = rebuild_snapshot(run_dir)
        checks = {
            "hash_chain_valid": validate_chain(events) == [],
            "snapshot_replay_parity": stored == replayed == rebuilt,
            "resolved_blocker_is_history_only": (
                rebuilt["active_blockers"] == []
                and rebuilt["blocker_history"][0]["status"] == "resolved"
            ),
            "retry_phase_is_explicit": (
                rebuilt["retry_queue"][0]["phase"] == "acceptance"
                and rebuilt["tasks"]["T1"]["status"] == "verifying"
            ),
            "revision_and_patch_projected": (
                rebuilt["worktree_revision"] == 1
                and rebuilt["worktree_patch_sha256"] == "a" * 64
            ),
        }
        assert all(checks.values()), checks
    print(json.dumps({"passed": True, "checks": checks}, sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
