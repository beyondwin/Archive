#!/usr/bin/env python3
"""Focused contract checks for qualified vNext tasks and plan checkpoints."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.checkpoints import (  # noqa: E402
    create_plan_checkpoint,
    promote_plan_checkpoint,
    upstream_graph_sha256,
)
from cpe_runtime.document_set import compile_document_set  # noqa: E402
from cpe_runtime.manifest import create_manifest, validate_manifest  # noqa: E402
from cpe_runtime.packets import build_packet, verify_packet  # noqa: E402
from cpe_runtime.plan_graph import compile_plan_graph  # noqa: E402
from cpe_runtime.task_contracts import compile_task_contract_vnext  # noqa: E402


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
    spec.write_text("# Contract Spec\n\n## S1 Required\nQualified contracts.\n", encoding="utf-8")
    first = _write(
        root / "first.md",
        "First Plan",
        "cpe-plan",
        {
            "plan_id": "first",
            "tasks": [
                {
                    "task_id": "build",
                    "dependencies": [],
                    "spec_refs": ["S1"],
                    "file_claims": ["first.py"],
                }
            ],
        },
    )
    second = _write(
        root / "second.md",
        "Second Plan",
        "cpe-plan",
        {
            "plan_id": "second",
            "tasks": [
                {
                    "task_id": "integrate",
                    "dependencies": ["first::build"],
                    "spec_refs": ["S1"],
                    "file_claims": ["second.py"],
                }
            ],
        },
    )
    program = _write(
        root / "program.md",
        "Contract Program",
        "cpe-program",
        {
            "plan_order": ["first", "second"],
            "required_spec_sections": ["S1"],
            "spec_coverage": {"S1": ["first::build", "second::integrate"]},
            "cross_plan_dependencies": [["first::build", "second::integrate"]],
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
        contract = compile_task_contract_vnext(
            {
                "id": "integrate",
                "title": "Integrate plans",
                "task_type": "tdd_implementation",
                "task_source": "### Task: integrate\n",
                "dependencies": ["first::build"],
                "file_claims": ["second.py"],
                "acceptance_commands": ["python3 verify.py"],
            },
            plan_id="second",
            document_sha256=second_document.sha256,
            upstream_graph_sha256=upstream,
            source_hashes={"plan": second_document.sha256, "spec_sections": {}},
        )
        assert contract.qualified_task_id == "second::integrate"
        assert contract.dependencies == ("first::build",)
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
            [{"id": task_id} for task_id in graph.tasks],
            pricing,
            source_head="a" * 40,
            plan_graph=graph,
        )
        assert manifest["plan_graph"]["graph_sha256"] == graph.graph_sha256
        assert manifest["plan_graph"]["tasks"][contract.qualified_task_id]["plan_id"] == "second"
        assert validate_manifest(manifest) == []
        graph_tamper = json.loads(json.dumps(manifest))
        graph_tamper["plan_graph"]["tasks"].pop("first::build")
        assert "plan_graph_digest_mismatch" in validate_manifest(graph_tamper)

        task = {
            "id": contract.qualified_task_id,
            "task_contract": contract.body(),
            "task_contract_sha256": contract.contract_sha256,
        }
        draft = build_packet(SimpleNamespace(), task)
        payload = json.loads(draft.content)
        assert payload["task_contract_sha256"] == contract.contract_sha256
        assert payload["task_contract"]["dependencies"] == ["first::build"]
        packet_path = root / draft.relative_path
        packet_path.parent.mkdir(parents=True)
        packet_path.write_bytes(draft.content)
        packet_manifest = {
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
                    "manifest_graph_binding",
                    "packet_digest_and_cross_plan_dependency",
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
