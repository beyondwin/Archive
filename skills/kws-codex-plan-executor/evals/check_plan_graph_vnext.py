#!/usr/bin/env python3
"""Deterministic checks for the immutable CPE vNext PlanGraph."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from cpe_runtime.document_set import compile_document_set  # noqa: E402
from cpe_runtime.plan_graph import (  # noqa: E402
    PlanGraphBlocked,
    QualifiedTaskId,
    compile_plan_graph,
    invalidated_nodes,
)


def _markdown(title: str, tag: str, payload: dict[str, object]) -> str:
    return f"# {title}\n\n```json {tag}\n{json.dumps(payload, sort_keys=True)}\n```\n"


def _compile_bundle(bundle: dict[str, object], root: Path):
    root.mkdir(parents=True, exist_ok=True)
    spec = bundle["spec"]
    program = bundle.get("program")
    plans = bundle["plans"]
    assert isinstance(spec, dict) and isinstance(plans, list)
    spec_path = root / "spec.md"
    required = spec.get("required_sections", [])
    spec_path.write_text(
        f"# {spec['title']}\n\n" + "\n".join(f"## {section}\nrequired" for section in required),
        encoding="utf-8",
    )
    program_path = None
    if isinstance(program, dict):
        program_path = root / "program.md"
        program_path.write_text(
            _markdown(str(program["title"]), "cpe-program", program["contract"]),
            encoding="utf-8",
        )
    plan_paths = []
    for index, item in enumerate(plans):
        assert isinstance(item, dict)
        plan_id = str(item["plan_id"])
        contract = copy.deepcopy(item.get("contract"))
        if contract is None:
            contract = {
                "plan_id": plan_id,
                "tasks": [
                    {
                        "task_id": "complete",
                        "dependencies": [],
                        "spec_refs": list(required),
                        "file_claims": [f"owned/{plan_id}.txt"],
                        "source_token": item.get("source_blob_sha1", plan_id),
                    }
                ],
            }
        plan_path = root / "plans" / f"{index:02d}-{plan_id}.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            _markdown(str(item["title"]), "cpe-plan", contract), encoding="utf-8"
        )
        plan_paths.append(plan_path)
    document_set = compile_document_set(
        spec_path, tuple(plan_paths), program_path, (), workspace=root
    )
    return compile_plan_graph(document_set)


def _blocked(category: str, bundle: dict[str, object], root: Path) -> bool:
    try:
        _compile_bundle(bundle, root)
    except PlanGraphBlocked as exc:
        return exc.category == category and bool(exc.evidence)
    return False


def _simple_bundle(plan_count: int = 1, with_program: bool = False) -> dict[str, object]:
    plans = []
    order = []
    for index in range(plan_count):
        plan_id = f"plan-{index + 1}"
        order.append(plan_id)
        plans.append(
            {
                "plan_id": plan_id,
                "title": f"Plan {index + 1}",
                "contract": {
                    "plan_id": plan_id,
                    "tasks": [
                        {
                            "task_id": "build",
                            "dependencies": [],
                            "spec_refs": ["S1"],
                            "file_claims": [f"src/{plan_id}.py"],
                            "source_token": plan_id,
                        }
                    ],
                },
            }
        )
    bundle: dict[str, object] = {
        "spec": {"title": "Spec", "required_sections": ["S1"]},
        "plans": plans,
    }
    if with_program:
        bundle["program"] = {
            "title": "Program",
            "contract": {
                "plan_order": order,
                "required_spec_sections": ["S1"],
                "spec_coverage": {"S1": [f"{order[0]}::build"]},
                "cross_plan_dependencies": [],
                "file_ownership": {},
                "ownership_transfers": [],
                "global_integration_gate": f"{order[-1]}::build",
            },
        }
    return bundle


def main() -> int:
    checks: dict[str, bool] = {}

    canvas_bundle = json.loads(
        (FIXTURES / "canvas-program-6d41fb9" / "fixture.json").read_text(encoding="utf-8")
    )
    self_bundle = json.loads(
        (FIXTURES / "cpe-vnext-self-dogfood.json").read_text(encoding="utf-8")
    )
    checks["canvas_fixture_pins_exact_public_commit"] = (
        canvas_bundle["source"]["commit"] == "6d41fb96aa34d4522a8af5bfd911680c2548be3e"
        and len({plan["source_blob_sha1"] for plan in canvas_bundle["plans"]}) == 12
    )

    with tempfile.TemporaryDirectory(prefix="cpe-plan-graph-") as temp:
        root = Path(temp)
        root.mkdir(exist_ok=True)
        canvas = _compile_bundle(canvas_bundle, root / "canvas")
        checks["canvas_has_twelve_plans"] = canvas.plan_count == 12
        checks["canvas_gate_is_final_wave"] = canvas.global_integration_gate.plan_id.endswith(
            "wave-6-integration-evidence"
        )
        checks["all_task_ids_are_qualified"] = all("::" in task_id for task_id in canvas.tasks)
        checks["qualified_task_id_is_public"] = str(
            QualifiedTaskId("wave-b2-import-repair-ux", "complete")
        ) == "wave-b2-import-repair-ux::complete"

        self_graph = _compile_bundle(self_bundle, root / "self")
        checks["self_dogfood_has_three_plans"] = self_graph.plan_count == 3
        checks["self_dogfood_has_program"] = self_graph.program_document_id is not None

        single = _compile_bundle(_simple_bundle(), root / "single")
        checks["single_plan_needs_no_program"] = (
            single.plan_count == 1 and single.program_document_id is None
        )

        markdown_root = root / "ordinary-markdown"
        markdown_root.mkdir(parents=True)
        markdown_spec = markdown_root / "spec.md"
        markdown_plan = markdown_root / "plan.md"
        markdown_spec.write_text("# Spec\n\n## S1\nrequired\n", encoding="utf-8")
        markdown_plan.write_text(
            """# Ordinary Plan

## Task 1: Build

```yaml
dependencies: []
spec_refs: ["S1"]
file_claims:
  - src/build.py
```

## Task 2: Verify

```yaml
dependencies: ["T1"]
spec_refs: ["S1"]
file_claims:
  - src/verify.py
```
""",
            encoding="utf-8",
        )
        markdown_graph = compile_plan_graph(
            compile_document_set(
                markdown_spec, (markdown_plan,), None, (), workspace=markdown_root
            )
        )
        markdown_tasks = tuple(markdown_graph.tasks)
        checks["ordinary_plan_task_aliases_resolve"] = (
            len(markdown_tasks) == 2 and (markdown_tasks[0], markdown_tasks[1]) in markdown_graph.edges
        )

        fallback = _compile_bundle(_simple_bundle(3), root / "fallback")
        ordered = list(fallback.tasks)
        checks["no_program_fallback_is_serial"] = (
            (ordered[0], ordered[1]) in fallback.edges
            and (ordered[1], ordered[2]) in fallback.edges
            and fallback.global_integration_gate.qualified_task_id == ordered[-1]
        )

        duplicate = _simple_bundle()
        duplicate["plans"][0]["contract"]["tasks"].append(
            copy.deepcopy(duplicate["plans"][0]["contract"]["tasks"][0])
        )
        checks["duplicate_task_ids_block"] = _blocked(
            "duplicate_task_id", duplicate, root / "duplicate"
        )

        orphan = _simple_bundle()
        orphan["plans"][0]["contract"]["tasks"][0]["dependencies"] = ["missing"]
        checks["orphan_dependency_blocks"] = _blocked("orphan_task", orphan, root / "orphan")

        cycle = _simple_bundle()
        cycle_tasks = cycle["plans"][0]["contract"]["tasks"]
        cycle_tasks[0]["dependencies"] = ["second"]
        cycle_tasks.append(
            {
                "task_id": "second",
                "dependencies": ["build"],
                "spec_refs": ["S1"],
                "file_claims": ["src/second.py"],
            }
        )
        checks["cycles_block"] = _blocked("dependency_cycle", cycle, root / "cycle")

        missing_coverage = _simple_bundle(2, with_program=True)
        missing_coverage["program"]["contract"]["spec_coverage"] = {}
        checks["missing_required_coverage_blocks"] = _blocked(
            "missing_spec_coverage", missing_coverage, root / "coverage"
        )

        missing_gate = _simple_bundle(2, with_program=True)
        del missing_gate["program"]["contract"]["global_integration_gate"]
        checks["missing_multiplan_gate_blocks"] = _blocked(
            "global_gate_missing", missing_gate, root / "gate"
        )

        redefined = _simple_bundle(2, with_program=True)
        redefined["program"]["contract"]["tasks"] = [{"task_id": "replacement"}]
        checks["program_cannot_redefine_tasks"] = _blocked(
            "program_redefines_task", redefined, root / "program-redefinition"
        )

        unused_owner = _simple_bundle(2, with_program=True)
        unused_owner["program"]["contract"]["file_ownership"] = {
            "not-claimed.py": ["plan-1::build"]
        }
        checks["unused_ownership_declaration_blocks"] = _blocked(
            "ambiguous_file_ownership", unused_owner, root / "unused-owner"
        )

        ownership = _simple_bundle(2, with_program=True)
        ownership["plans"][0]["contract"]["tasks"][0]["file_claims"] = ["shared/api.py"]
        ownership["plans"][1]["contract"]["tasks"][0]["file_claims"] = ["shared/api.py"]
        checks["ambiguous_cross_plan_ownership_blocks"] = _blocked(
            "ambiguous_file_ownership", ownership, root / "ownership-blocked"
        )
        owners = ["plan-1::build", "plan-2::build"]
        ownership["program"]["contract"]["file_ownership"] = {"shared/api.py": owners}
        ownership["program"]["contract"]["ownership_transfers"] = [
            {"path": "shared/api.py", "from": owners[0], "to": owners[1]}
        ]
        transferred = _compile_bundle(ownership, root / "ownership-transfer")
        checks["explicit_ownership_transfer_is_ordered"] = (
            transferred.file_ownership["shared/api.py"] == tuple(owners)
            and tuple(owners) in transferred.edges
        )

        changed_bundle = copy.deepcopy(canvas_bundle)
        changed = next(
            item for item in changed_bundle["plans"] if item["plan_id"] == "wave-b2-import-repair-ux"
        )
        changed["contract"] = {
            "plan_id": changed["plan_id"],
            "tasks": [
                {
                    "task_id": "complete",
                    "dependencies": [],
                    "spec_refs": ["S-CANVAS"],
                    "file_claims": [f"owned/{changed['plan_id']}.txt"],
                    "source_token": "changed-wave-b2",
                }
            ],
        }
        changed_canvas = _compile_bundle(changed_bundle, root / "canvas-changed")
        checks["invalidation_is_changed_region_and_downstream_only"] = (
            invalidated_nodes(canvas, changed_canvas)
            == changed_canvas.downstream_of("wave-b2-import-repair-ux")
            and not any("wave-b1" in node for node in invalidated_nodes(canvas, changed_canvas))
        )
        checks["graph_hash_is_deterministic"] = (
            canvas.graph_sha256 == _compile_bundle(canvas_bundle, root / "canvas-again").graph_sha256
        )
        try:
            canvas.tasks["new"] = {}  # type: ignore[index]
        except TypeError:
            checks["graph_mappings_are_immutable"] = True
        else:
            checks["graph_mappings_are_immutable"] = False
        try:
            canvas.graph_sha256 = "mutated"  # type: ignore[misc]
        except FrozenInstanceError:
            checks["graph_record_is_frozen"] = True
        else:
            checks["graph_record_is_frozen"] = False

    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failed": failed}, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
