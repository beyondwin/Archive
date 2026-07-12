#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import operator
import sys
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
FIXTURES = Path(__file__).resolve().parent / "parser-fixtures"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from parse_plan import parse_plan
from cpe_runtime.manifest import sha256_bytes
from cpe_runtime.packets import PACKET_ROLE_POLICY, build_packet, verify_packet
from cpe_runtime.task_contracts import canonical_contract_bytes, compile_task_contract


SPEC_TEXT = "## Immutable TaskContractV4\nEvery role receives the complete task contract.\n"
SPEC_SHA256 = hashlib.sha256(SPEC_TEXT.encode("utf-8")).hexdigest()


def compile_fixture(name: str):
    fixture = FIXTURES / name
    parsed = parse_plan(fixture, REPO_ROOT, "prompt")
    task = parsed["tasks"][0]
    return compile_task_contract(
        task,
        spec_sections=({"id": "S1.6", "sha256": SPEC_SHA256, "text": SPEC_TEXT},),
        source_hashes={
            "plan": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "spec_sections": {"S1.6": SPEC_SHA256},
        },
    )


def _packet_manifest(draft) -> dict[str, object]:
    return {
        "task_packets": [
            {
                "task_id": draft.task_id,
                "path": draft.relative_path,
                "media_type": draft.media_type,
                "sha256": draft.sha256,
            }
        ]
    }


def _write_packet(root: Path, content: bytes) -> tuple[Path, dict[str, object]]:
    path = root / "artifacts" / "task-packets" / "task_1.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    manifest = {
        "task_packets": [
            {
                "task_id": "task_1",
                "path": "artifacts/task-packets/task_1.json",
                "media_type": "application/json",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ]
    }
    return path, manifest


def _expect_rejection(payload: dict[str, object], expected: str, *, canonical: bool = True) -> bool:
    content = (
        (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if canonical
        else json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    )
    with tempfile.TemporaryDirectory(prefix="cpe-v4-packet-reject-") as raw:
        root = Path(raw)
        _, manifest = _write_packet(root, content)
        try:
            verify_packet(root, manifest, "task_1")
        except ValueError as exc:
            return str(exc) == expected
    return False


def _nested_mutation_is_blocked(path: str) -> bool:
    contract = compile_fixture("20-v4-lossless-plan.md")
    body_before = contract.body()
    digest_before = contract.contract_sha256
    try:
        if path == "spec_sections":
            operator.setitem(contract.spec_sections[0], "text", "tampered")
        elif path == "source_hashes":
            operator.setitem(contract.source_hashes, "plan", "0" * 64)
        elif path == "nested_source_hashes":
            spec_hashes = contract.source_hashes["spec_sections"]
            operator.setitem(spec_hashes, "S1.6", "0" * 64)  # type: ignore[arg-type]
        else:
            raise AssertionError(f"unknown mutation path: {path}")
    except TypeError:
        return contract.body() == body_before and contract.contract_sha256 == digest_before
    return False


def main() -> int:
    checks: dict[str, bool] = {}
    contract = compile_fixture("20-v4-lossless-plan.md")
    fixture_text = (FIXTURES / "20-v4-lossless-plan.md").read_bytes().decode("utf-8")
    expected_source = fixture_text[
        fixture_text.index("### Task 1:") : fixture_text.index("### Task 2:")
    ]

    checks["lossless_source"] = (
        contract.schema_version == "cpe.task-contract.v4"
        and contract.task_type == "tdd_implementation"
        and contract.task_source == expected_source
        and "def test_lossless_contract():" in contract.task_source
        and "python3 -m unittest" in contract.task_source
        and contract.acceptance_commands == ("python3 check_contract.py",)
        and contract.task_source_sha256 == sha256_bytes(contract.task_source.encode())
        and contract.contract_sha256 == sha256_bytes(canonical_contract_bytes(contract.body()))
    )
    checks["compiled_metadata_is_complete"] = (
        contract.risk_class == "high"
        and contract.dependencies == ()
        and contract.file_claims
        == ("skills/kws-codex-plan-executor/scripts/cpe_runtime/task_contracts.py",)
        and contract.forbidden_paths == ("run_manifest.json", "events.jsonl", "state.json")
        and contract.required_methods == ("using-superpowers", "test-driven-development")
        and contract.required_evidence == ("red", "green")
        and contract.checkpoint_message == "feat(cpe): preserve lossless task source"
        and contract.spec_sections[0]["text"] == SPEC_TEXT
    )
    try:
        contract.title = "mutated"  # type: ignore[misc]
    except FrozenInstanceError:
        checks["contract_is_frozen"] = True
    else:
        checks["contract_is_frozen"] = False
    checks["spec_sections_are_deeply_immutable"] = _nested_mutation_is_blocked("spec_sections")
    checks["source_hashes_are_deeply_immutable"] = _nested_mutation_is_blocked("source_hashes")
    checks["nested_source_hashes_are_deeply_immutable"] = _nested_mutation_is_blocked(
        "nested_source_hashes"
    )

    task = {
        "id": contract.task_id,
        "task_contract": contract.body(),
        "task_contract_sha256": contract.contract_sha256,
    }
    draft = build_packet(SimpleNamespace(), task)
    payload = json.loads(draft.content)
    checks["role_digest_parity"] = (
        payload
        == {
            "schema_version": "cpe.task-packet.v4",
            "task_id": contract.task_id,
            "task_contract": contract.body(),
            "task_contract_sha256": contract.contract_sha256,
            "execution_contract": {
                "scope": "bounded task scope",
                "files_to_inspect": list(contract.file_claims),
                "allowed_edits": list(contract.file_claims),
                "forbidden_edits": list(contract.forbidden_paths),
                "acceptance_command_or_honest_substitute": "\n".join(contract.acceptance_commands),
            },
            "role_policy": PACKET_ROLE_POLICY,
            "source_hashes": contract.source_hashes,
        }
        and all(payload["task_contract_sha256"] == contract.contract_sha256 for _ in PACKET_ROLE_POLICY)
    )
    with tempfile.TemporaryDirectory(prefix="cpe-v4-packet-") as raw:
        root = Path(raw)
        path = root / draft.relative_path
        path.parent.mkdir(parents=True)
        path.write_bytes(draft.content)
        checks["verified_packet_preserves_contract"] = verify_packet(
            root, _packet_manifest(draft), contract.task_id
        ) == draft

    checks["canonical_byte_mismatch_rejected"] = _expect_rejection(payload, "packet_invalid", canonical=False)

    source_mismatch = json.loads(json.dumps(payload))
    source_mismatch["task_contract"]["task_source"] += "tampered\n"
    source_mismatch["task_contract_sha256"] = sha256_bytes(
        canonical_contract_bytes(source_mismatch["task_contract"])
    )
    checks["source_digest_mismatch_rejected"] = _expect_rejection(
        source_mismatch, "task_source_digest_mismatch"
    )

    contract_mismatch = json.loads(json.dumps(payload))
    contract_mismatch["task_contract"]["title"] = "tampered"
    checks["contract_digest_mismatch_rejected"] = _expect_rejection(
        contract_mismatch, "task_contract_digest_mismatch"
    )

    spec_mismatch = json.loads(json.dumps(payload))
    spec_mismatch["task_contract"]["spec_sections"][0]["text"] += "tampered\n"
    spec_mismatch["task_contract_sha256"] = sha256_bytes(
        canonical_contract_bytes(spec_mismatch["task_contract"])
    )
    checks["spec_digest_mismatch_rejected"] = _expect_rejection(
        spec_mismatch, "spec_section_digest_mismatch:S1.6"
    )

    role_mismatch = json.loads(json.dumps(payload))
    role_mismatch["role_policy"]["implementation"]["task_contract_sha256"] = "0" * 64
    checks["role_visible_digest_mismatch_rejected"] = _expect_rejection(
        role_mismatch, "packet_role_policy_mismatch"
    )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
