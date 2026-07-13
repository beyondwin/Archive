#!/usr/bin/env python3
"""Focused contract checks for qualified vNext tasks and plan checkpoints."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

SPEC_SECTION_TEXT = "## S1 Required\nQualified contracts.\n"
FIRST_TASK = {
    "task_id": "build",
    "dependencies": [],
    "spec_refs": ["S1"],
    "file_claims": ["first.py"],
}
PREPARE_TASK = {
    "task_id": "prepare",
    "dependencies": ["first::build"],
    "spec_refs": ["S1"],
    "file_claims": ["prepare.py"],
}
INTEGRATE_TASK = {
    "task_id": "integrate",
    "dependencies": ["prepare", "first::build"],
    "spec_refs": ["S1"],
    "file_claims": ["second.py"],
}

from cpe_runtime.checkpoints import (  # noqa: E402
    create_plan_checkpoint,
    promote_plan_checkpoint,
    upstream_graph_sha256,
)
from cpe_runtime.document_set import compile_document_set  # noqa: E402
from cpe_runtime.manifest import canonical_hash, create_manifest, validate_manifest  # noqa: E402
from cpe_runtime.packets import (  # noqa: E402
    build_packet,
    canonical_packet_bytes,
    verify_packet,
)
from cpe_runtime.plan_graph import compile_plan_graph  # noqa: E402
from cpe_runtime.task_contracts import (  # noqa: E402
    canonical_contract_bytes,
    compile_task_contract_vnext,
    contract_from_body,
)


def _write(path: Path, title: str, contract_tag: str, contract: dict[str, object]) -> Path:
    path.write_text(
        f"# {title}\n\n```json {contract_tag}\n"
        + json.dumps(contract, sort_keys=True)
        + "\n```\n",
        encoding="utf-8",
    )
    return path


def _fixture(root: Path):
    spec = root / "spec.md"
    spec.write_text("# Contract Spec\n\n" + SPEC_SECTION_TEXT, encoding="utf-8")
    first = _write(
        root / "first.md",
        "First Plan",
        "cpe-plan",
        {
            "plan_id": "first",
            "tasks": [FIRST_TASK],
        },
    )
    second = _write(
        root / "second.md",
        "Second Plan",
        "cpe-plan",
        {
            "plan_id": "second",
            "tasks": [PREPARE_TASK, INTEGRATE_TASK],
        },
    )
    program = _write(
        root / "program.md",
        "Contract Program",
        "cpe-program",
        {
            "plan_order": ["first", "second"],
            "required_spec_sections": ["S1"],
            "spec_coverage": {
                "S1": ["first::build", "second::prepare", "second::integrate"]
            },
            "cross_plan_dependencies": [
                ["first::build", "second::prepare"],
                ["first::build", "second::integrate"],
            ],
            "file_ownership": {},
            "ownership_transfers": [],
            "global_integration_gate": "second::integrate",
        },
    )
    documents = compile_document_set(spec, (first, second), program, (), workspace=root)
    return spec, first, second, documents, compile_plan_graph(documents)


def _assert_rejected(expected: str, operation) -> None:
    try:
        operation()
    except ValueError as exc:
        assert str(exc) == expected, (str(exc), expected)
    else:
        raise AssertionError(f"expected ValueError: {expected}")


def _assert_packet_rejected(
    root: Path,
    manifest: dict[str, object],
    payload: dict[str, object],
    task_id: str,
    expected: str,
) -> None:
    content = canonical_packet_bytes(payload)
    packet_manifest = json.loads(json.dumps(manifest))
    packet_manifest["task_packets"][0]["sha256"] = hashlib.sha256(content).hexdigest()
    path = root / packet_manifest["task_packets"][0]["path"]
    path.write_bytes(content)
    _assert_rejected(
        expected,
        lambda: verify_packet(root, packet_manifest, task_id),
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-vnext-multiplan-") as raw:
        root = Path(raw)
        spec, first, second, documents, graph = _fixture(root)
        spec_document = next(item for item in documents.documents if item.kind == "spec")
        second_document = next(
            item
            for item in documents.documents
            if item.kind == "plan" and item.path == Path("second.md")
        )
        upstream = upstream_graph_sha256(graph, "second")
        spec_section_sha256 = hashlib.sha256(SPEC_SECTION_TEXT.encode()).hexdigest()
        first_document = next(
            item
            for item in documents.documents
            if item.kind == "plan" and item.path == Path("first.md")
        )
        first_contract = compile_task_contract_vnext(
            {
                "id": "build",
                "title": "Build first plan",
                "task_type": "tdd_implementation",
                "task_source": json.dumps(
                    FIRST_TASK, sort_keys=True, separators=(",", ":")
                ),
                "dependencies": [],
                "file_claims": ["first.py"],
                "acceptance_commands": ["python3 verify.py"],
            },
            plan_id="first",
            document_sha256=first_document.sha256,
            upstream_graph_sha256=upstream_graph_sha256(graph, "first"),
            source_hashes={
                "plan": first_document.sha256,
                "spec_sections": {"S1": spec_section_sha256},
            },
            spec_sections=(
                {
                    "id": "S1",
                    "sha256": spec_section_sha256,
                    "text": SPEC_SECTION_TEXT,
                },
            ),
            plan_graph=graph,
        )
        prepare_contract = compile_task_contract_vnext(
            {
                "id": "prepare",
                "title": "Prepare integration",
                "task_type": "tdd_implementation",
                "task_source": json.dumps(
                    PREPARE_TASK, sort_keys=True, separators=(",", ":")
                ),
                "dependencies": ["first::build"],
                "file_claims": ["prepare.py"],
                "acceptance_commands": ["python3 verify.py"],
            },
            plan_id="second",
            document_sha256=second_document.sha256,
            upstream_graph_sha256=upstream,
            source_hashes={
                "plan": second_document.sha256,
                "spec_sections": {"S1": spec_section_sha256},
            },
            spec_sections=(
                {
                    "id": "S1",
                    "sha256": spec_section_sha256,
                    "text": SPEC_SECTION_TEXT,
                },
            ),
            plan_graph=graph,
        )
        contract = compile_task_contract_vnext(
            {
                "id": "integrate",
                "title": "Integrate plans",
                "task_type": "tdd_implementation",
                "task_source": json.dumps(
                    INTEGRATE_TASK, sort_keys=True, separators=(",", ":")
                ),
                "dependencies": ["second::prepare", "first::build"],
                "file_claims": ["second.py"],
                "acceptance_commands": ["python3 verify.py"],
            },
            plan_id="second",
            document_sha256=second_document.sha256,
            upstream_graph_sha256=upstream,
            source_hashes={
                "plan": second_document.sha256,
                "spec_sections": {"S1": spec_section_sha256},
            },
            spec_sections=(
                {
                    "id": "S1",
                    "sha256": spec_section_sha256,
                    "text": SPEC_SECTION_TEXT,
                },
            ),
            plan_graph=graph,
        )
        assert contract.qualified_task_id == "second::integrate"
        assert contract.dependencies == ("first::build", "second::prepare")
        assert contract.document_sha256 == second_document.sha256
        assert contract.upstream_graph_sha256 == upstream

        pricing = root / "pricing.json"
        pricing.write_text("{}\n", encoding="utf-8")
        manifest = create_manifest(
            "vnext-contract-fixture",
            "interactive",
            root,
            root,
            second,
            spec,
            [
                {
                    "id": first_contract.qualified_task_id,
                    "dependencies": list(first_contract.dependencies),
                    "task_contract": first_contract.body(),
                    "task_contract_sha256": first_contract.contract_sha256,
                },
                {
                    "id": prepare_contract.qualified_task_id,
                    "dependencies": list(prepare_contract.dependencies),
                    "task_contract": prepare_contract.body(),
                    "task_contract_sha256": prepare_contract.contract_sha256,
                },
                {
                    "id": contract.qualified_task_id,
                    "dependencies": list(contract.dependencies),
                    "task_contract": contract.body(),
                    "task_contract_sha256": contract.contract_sha256,
                },
            ],
            pricing,
            source_head="a" * 40,
            plan_graph=graph,
        )
        assert manifest["plan_graph"]["graph_sha256"] == graph.graph_sha256
        assert manifest["plan_graph"]["tasks"][contract.qualified_task_id]["plan_id"] == "second"
        assert len(manifest["task_graph"]) == len(graph.tasks)
        assert len({task["id"] for task in manifest["task_graph"]}) == len(graph.tasks)
        assert validate_manifest(manifest) == []
        graph_tamper = json.loads(json.dumps(manifest))
        graph_tamper["plan_graph"]["tasks"].pop("first::build")
        assert "plan_graph_digest_mismatch" in validate_manifest(graph_tamper)
        dependency_tamper = json.loads(json.dumps(manifest))
        dependency_tamper["task_graph"][2]["dependencies"] = []
        assert "plan_graph_dependency_mismatch" in validate_manifest(dependency_tamper)
        missing_contract = json.loads(json.dumps(manifest))
        missing_contract["task_graph"][0].pop("task_contract")
        missing_contract["task_graph"][0].pop("task_contract_sha256")
        missing_contract["plan_graph_hash"] = canonical_hash(missing_contract["task_graph"])
        assert "plan_graph_task_contract_invalid" in validate_manifest(missing_contract)
        forged_digest = json.loads(json.dumps(manifest))
        forged_digest["task_graph"][1]["task_contract_sha256"] = "f" * 64
        forged_digest["plan_graph_hash"] = canonical_hash(forged_digest["task_graph"])
        assert "plan_graph_task_contract_invalid" in validate_manifest(forged_digest)
        forged_upstream = json.loads(json.dumps(manifest))
        forged_body = forged_upstream["task_graph"][2]["task_contract"]
        forged_body["upstream_graph_sha256"] = "f" * 64
        forged_upstream["task_graph"][2]["task_contract_sha256"] = hashlib.sha256(
            canonical_contract_bytes(forged_body)
        ).hexdigest()
        forged_upstream["plan_graph_hash"] = canonical_hash(forged_upstream["task_graph"])
        assert "plan_graph_task_contract_invalid" in validate_manifest(forged_upstream)
        duplicate_contract = json.loads(json.dumps(manifest))
        duplicate_contract["task_graph"].append(
            json.loads(json.dumps(duplicate_contract["task_graph"][0]))
        )
        duplicate_contract["plan_graph_hash"] = canonical_hash(
            duplicate_contract["task_graph"]
        )
        assert "plan_graph_task_cardinality_invalid" in validate_manifest(
            duplicate_contract
        )

        task = {
            "id": contract.qualified_task_id,
            "task_contract": contract.body(),
            "task_contract_sha256": contract.contract_sha256,
        }
        draft = build_packet(SimpleNamespace(plan_graph=graph), task)
        payload = json.loads(draft.content)
        assert payload["task_contract_sha256"] == contract.contract_sha256
        assert payload["task_contract"]["dependencies"] == [
            "first::build",
            "second::prepare",
        ]
        packet_path = root / draft.relative_path
        packet_path.parent.mkdir(parents=True)
        packet_path.write_bytes(draft.content)
        packet_manifest = {
            "plan_graph": manifest["plan_graph"],
            "task_packets": [
                {
                    "task_id": draft.task_id,
                    "path": draft.relative_path,
                    "media_type": draft.media_type,
                    "sha256": draft.sha256,
                }
            ]
        }
        assert verify_packet(root, packet_manifest, contract.qualified_task_id) == draft
        integer_plan = contract.body()
        integer_plan["plan_id"] = 7
        integer_plan["qualified_task_id"] = "7::integrate"
        integer_digest = hashlib.sha256(
            canonical_contract_bytes(integer_plan)
        ).hexdigest()
        _assert_rejected(
            "task_contract_invalid",
            lambda: contract_from_body(integer_plan, integer_digest, plan_graph=graph),
        )
        integer_dependency = contract.body()
        integer_dependency["dependencies"] = [123]
        integer_dependency_digest = hashlib.sha256(
            canonical_contract_bytes(integer_dependency)
        ).hexdigest()
        _assert_rejected(
            "task_contract_invalid",
            lambda: contract_from_body(
                integer_dependency,
                integer_dependency_digest,
                plan_graph=graph,
            ),
        )
        integer_packet = json.loads(json.dumps(payload))
        integer_packet["task_contract"] = integer_plan
        integer_packet["task_contract_sha256"] = integer_digest
        _assert_packet_rejected(
            root,
            packet_manifest,
            integer_packet,
            contract.qualified_task_id,
            "task_contract_invalid",
        )
        list_packet = json.loads(json.dumps(payload))
        list_packet["task_contract"] = integer_dependency
        list_packet["task_contract_sha256"] = integer_dependency_digest
        _assert_packet_rejected(
            root,
            packet_manifest,
            list_packet,
            contract.qualified_task_id,
            "task_contract_invalid",
        )
        _assert_rejected(
            "qualified_dependency_invalid",
            lambda: compile_task_contract_vnext(
                {
                    "id": "integrate",
                    "title": "Unqualified dependency",
                    "task_type": "tdd_implementation",
                    "task_source": "### Task: integrate\n",
                    "dependencies": ["build"],
                    "file_claims": ["second.py"],
                    "acceptance_commands": ["python3 verify.py"],
                },
                plan_id="second",
                document_sha256=second_document.sha256,
                upstream_graph_sha256=upstream,
                source_hashes={"plan": second_document.sha256, "spec_sections": {}},
                plan_graph=graph,
            ),
        )
        for dependencies in (["missing::task"], []):
            _assert_rejected(
                "task_contract_graph_dependency_mismatch",
                lambda dependencies=dependencies: compile_task_contract_vnext(
                    {
                        "id": "integrate",
                        "title": "Divergent dependency",
                        "task_type": "tdd_implementation",
                        "task_source": json.dumps(
                            INTEGRATE_TASK, sort_keys=True, separators=(",", ":")
                        ),
                        "dependencies": dependencies,
                        "file_claims": ["second.py"],
                        "acceptance_commands": ["python3 verify.py"],
                    },
                    plan_id="second",
                    document_sha256=second_document.sha256,
                    upstream_graph_sha256=upstream,
                    source_hashes={
                        "plan": second_document.sha256,
                        "spec_sections": {"S1": spec_section_sha256},
                    },
                    spec_sections=(
                        {
                            "id": "S1",
                            "sha256": spec_section_sha256,
                            "text": SPEC_SECTION_TEXT,
                        },
                    ),
                    plan_graph=graph,
                ),
            )
        _assert_rejected(
            "qualified_dependency_invalid",
            lambda: compile_task_contract_vnext(
                {
                    "id": "integrate",
                    "title": "Duplicate dependency",
                    "task_type": "tdd_implementation",
                    "task_source": json.dumps(
                        INTEGRATE_TASK, sort_keys=True, separators=(",", ":")
                    ),
                    "dependencies": ["first::build", "first::build"],
                    "file_claims": ["second.py"],
                    "acceptance_commands": ["python3 verify.py"],
                },
                plan_id="second",
                document_sha256=second_document.sha256,
                upstream_graph_sha256=upstream,
                source_hashes={
                    "plan": second_document.sha256,
                    "spec_sections": {"S1": spec_section_sha256},
                },
                spec_sections=(
                    {
                        "id": "S1",
                        "sha256": spec_section_sha256,
                        "text": SPEC_SECTION_TEXT,
                    },
                ),
                plan_graph=graph,
            ),
        )
        authoritative_task = {
            "id": "integrate",
            "title": "Authoritative integration",
            "task_type": "tdd_implementation",
            "task_source": json.dumps(
                INTEGRATE_TASK, sort_keys=True, separators=(",", ":")
            ),
            "dependencies": ["first::build", "second::prepare"],
            "file_claims": ["second.py"],
            "acceptance_commands": ["python3 verify.py"],
        }
        authoritative_kwargs = {
            "plan_id": "second",
            "document_sha256": second_document.sha256,
            "upstream_graph_sha256": upstream,
            "source_hashes": {
                "plan": second_document.sha256,
                "spec_sections": {"S1": spec_section_sha256},
            },
            "spec_sections": (
                {
                    "id": "S1",
                    "sha256": spec_section_sha256,
                    "text": SPEC_SECTION_TEXT,
                },
            ),
            "plan_graph": graph,
        }
        expanded_claim = dict(authoritative_task)
        expanded_claim["file_claims"] = ["second.py", "outside.py"]
        _assert_rejected(
            "task_contract_graph_scope_mismatch",
            lambda: compile_task_contract_vnext(expanded_claim, **authoritative_kwargs),
        )
        divergent_source = dict(authoritative_task)
        divergent_source["task_source"] += "\n"
        _assert_rejected(
            "task_contract_source_mismatch",
            lambda: compile_task_contract_vnext(divergent_source, **authoritative_kwargs),
        )
        divergent_spec = dict(authoritative_kwargs)
        divergent_spec["spec_sections"] = ()
        divergent_spec["source_hashes"] = {
            "plan": second_document.sha256,
            "spec_sections": {},
        }
        _assert_rejected(
            "task_contract_graph_scope_mismatch",
            lambda: compile_task_contract_vnext(authoritative_task, **divergent_spec),
        )
        for tampered_graph in (
            replace(graph, graph_sha256="f" * 64),
            replace(
                graph,
                global_integration_gate=replace(
                    graph.global_integration_gate,
                    task_id="build",
                ),
            ),
            replace(graph, ownership_authority={}),
        ):
            _assert_rejected(
                "plan_graph_digest_mismatch",
                lambda tampered_graph=tampered_graph: upstream_graph_sha256(
                    tampered_graph, "second"
                ),
            )

        first_checkpoint = create_plan_checkpoint(
            plan_id="first",
            commit="1" * 40,
            tree="2" * 40,
            plan_sha256=next(
                item.sha256
                for item in documents.documents
                if item.kind == "plan" and item.path == Path("first.md")
            ),
            spec_sha256=spec_document.sha256,
            upstream_checkpoint=None,
            upstream_graph_sha256=upstream_graph_sha256(graph, "first"),
            evidence_refs=({"kind": "acceptance", "sha256": "3" * 64},),
        )
        checkpoint = create_plan_checkpoint(
            plan_id="second",
            commit="4" * 40,
            tree="5" * 40,
            plan_sha256=second_document.sha256,
            spec_sha256=spec_document.sha256,
            upstream_checkpoint=first_checkpoint.identity(),
            upstream_graph_sha256=upstream,
            evidence_refs=({"kind": "global_review", "sha256": "6" * 64},),
        )
        assert checkpoint.upstream_graph_sha256 == upstream
        assert checkpoint.spec_sha256 == spec_document.sha256
        assert checkpoint.upstream_checkpoint == first_checkpoint.identity()
        assert promote_plan_checkpoint(
            checkpoint,
            plan_id="second",
            plan_sha256=second_document.sha256,
            spec_sha256=spec_document.sha256,
            upstream_checkpoint=first_checkpoint.identity(),
            upstream_graph_sha256=upstream,
        ) == checkpoint
        _assert_rejected(
            "plan_checkpoint_upstream_graph_stale",
            lambda: promote_plan_checkpoint(
                checkpoint,
                plan_id="second",
                plan_sha256=second_document.sha256,
                spec_sha256=spec_document.sha256,
                upstream_checkpoint=first_checkpoint.identity(),
                upstream_graph_sha256="f" * 64,
            ),
        )
        _assert_rejected(
            "plan_checkpoint_upstream_stale",
            lambda: promote_plan_checkpoint(
                checkpoint,
                plan_id="second",
                plan_sha256=second_document.sha256,
                spec_sha256=spec_document.sha256,
                upstream_checkpoint="e" * 64,
                upstream_graph_sha256=upstream,
            ),
        )
        _assert_rejected(
            "plan_checkpoint_invalid",
            lambda: promote_plan_checkpoint(
                replace(checkpoint, commit="short"),
                plan_id="second",
                plan_sha256=second_document.sha256,
                spec_sha256=spec_document.sha256,
                upstream_checkpoint=first_checkpoint.identity(),
                upstream_graph_sha256=upstream,
            ),
        )

    print(
        json.dumps(
            {
                "passed": True,
                "checks": [
                    "qualified_task_identity",
                    "strict_wire_type_and_packet_parity",
                    "manifest_graph_binding",
                    "complete_graph_identity_validation",
                    "packet_digest_and_cross_plan_dependency",
                    "authoritative_graph_dependencies",
                    "complete_execution_scope_authority",
                    "mandatory_manifest_task_contracts",
                    "unique_manifest_task_contract_cardinality",
                    "immutable_plan_checkpoint",
                    "checkpoint_promotion",
                    "stale_upstream_fail_closed",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
