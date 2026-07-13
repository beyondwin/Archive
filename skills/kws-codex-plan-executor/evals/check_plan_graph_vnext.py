#!/usr/bin/env python3
"""Deterministic checks for the immutable CPE vNext PlanGraph."""

from __future__ import annotations

import copy
import hashlib
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
    spec = bundle.get("spec")
    program = bundle.get("program")
    plans = bundle["plans"]
    assert (spec is None or isinstance(spec, dict)) and isinstance(plans, list)
    spec_path = None
    required: list[object] = []
    if isinstance(spec, dict):
        spec_path = root / "spec.md"
        required = spec.get("required_sections", [])
        raw_body = spec.get("raw_body")
        if raw_body is not None:
            spec_path.write_text(f"# {spec['title']}\n\n{raw_body}\n", encoding="utf-8")
        else:
            sections = spec.get("sections")
            if sections is None:
                sections = {str(section): "required" for section in required}
            assert isinstance(sections, dict)
            spec_path.write_text(
                f"# {spec['title']}\n\n"
                + "\n".join(f"## {section}\n{body}" for section, body in sections.items()),
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


def _git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def _compile_exact_canvas(
    bundle: dict[str, object],
    root: Path,
    mutations: dict[str, bytes] | None = None,
):
    root.mkdir(parents=True, exist_ok=True)
    source = bundle["source"]
    plans = bundle["plans"]
    assert isinstance(source, dict) and isinstance(plans, list)
    source_root = (
        FIXTURES / "canvas-program-6d41fb9" / str(source["tracked_sources_root"])
    )
    program_name = Path(str(source["program_path"])).name
    program_bytes = (source_root / program_name).read_bytes()
    assert _git_blob_sha1(program_bytes) == source["program_blob_sha1"]
    program_path = root / program_name
    program_path.write_bytes((mutations or {}).get(program_name, program_bytes))
    plan_paths = []
    for item in plans:
        assert isinstance(item, dict)
        name = Path(str(item["source_path"])).name
        content = (source_root / name).read_bytes()
        assert _git_blob_sha1(content) == item["source_blob_sha1"]
        target = root / name
        target.write_bytes((mutations or {}).get(name, content))
        plan_paths.append(target)
    return compile_plan_graph(
        compile_document_set(None, tuple(plan_paths), program_path, (), workspace=root)
    )


def _exact_canvas_block_category(
    bundle: dict[str, object],
    root: Path,
    mutations: dict[str, bytes],
) -> str | None:
    try:
        _compile_exact_canvas(bundle, root, mutations)
    except PlanGraphBlocked as exc:
        return exc.category
    return None


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


def _section_bundle(sections: dict[str, str]) -> dict[str, object]:
    return {
        "spec": {
            "title": "Sectioned Spec",
            "required_sections": ["S1", "S2"],
            "sections": sections,
        },
        "program": {
            "title": "Section Program",
            "contract": {
                "plan_order": ["section-plan"],
                "required_spec_sections": ["S1", "S2"],
                "spec_coverage": {
                    "S1": ["section-plan::s1"],
                    "S2": ["section-plan::s2"],
                },
                "cross_plan_dependencies": [],
                "file_ownership": {},
                "ownership_transfers": [],
                "global_integration_gate": "section-plan::gate",
            },
        },
        "plans": [
            {
                "plan_id": "section-plan",
                "title": "Section Plan",
                "contract": {
                    "plan_id": "section-plan",
                    "tasks": [
                        {"task_id": "s1", "dependencies": [], "spec_refs": ["S1"], "file_claims": ["s1.py"]},
                        {"task_id": "s2", "dependencies": [], "spec_refs": ["S2"], "file_claims": ["s2.py"]},
                        {"task_id": "gate", "dependencies": ["s1", "s2"], "spec_refs": [], "file_claims": ["gate.py"]},
                    ],
                },
            }
        ],
    }


def _non_s_bundle(raw_body: str | None) -> dict[str, object]:
    bundle = _section_bundle({"S1": "unused", "S2": "unused"})
    bundle["spec"] = (
        None
        if raw_body is None
        else {"title": "Non S Spec", "required_sections": [], "raw_body": raw_body}
    )
    return bundle


def _alias_collision_blocks(root: Path) -> bool:
    root.mkdir(parents=True, exist_ok=True)
    program = root / "program.md"
    program.write_text(
        """# Duplicate Alias Program

## Authoritative Execution Order

| Stage | Plan | Working deliverable | Depends on |
|---|---|---|---|
| 1 | `wave-a1-first.md` | first | design |
| 2 | `wave-a1-second.md` | second | stage 1 |

## Spec Coverage Map

| Design sections | Owning stage |
|---|---|
| 1-2 | A1 |

## File Ownership Map

### A1 owns

- `src/a1/**`

A new wave may change an existing owner only through an interface explicitly named in that wave's plan.
""",
        encoding="utf-8",
    )
    plan_paths = []
    for name, title in (("wave-a1-first.md", "First A1"), ("wave-a1-second.md", "Second A1")):
        path = root / name
        path.write_text(
            f"# {title}\n\n## Task 1: Build\n\n**Files:**\n- Create: `src/a1/{name}.py`\n",
            encoding="utf-8",
        )
        plan_paths.append(path)
    try:
        compile_plan_graph(
            compile_document_set(None, tuple(plan_paths), program, (), workspace=root)
        )
    except PlanGraphBlocked as exc:
        return exc.category == "stage_alias_ambiguous" and bool(exc.evidence)
    return False


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
        canvas = _compile_exact_canvas(canvas_bundle, root / "canvas")
        checks["canvas_has_twelve_plans"] = canvas.plan_count == 12
        checks["canvas_exact_markdown_yields_real_tasks"] = len(canvas.tasks) == 81
        checks["canvas_gate_is_final_wave"] = canvas.global_integration_gate.plan_id.endswith(
            "wave-6-integration-evidence"
        )
        checks["all_task_ids_are_qualified"] = all("::" in task_id for task_id in canvas.tasks)
        canvas_plan_tasks = {
            plan_id: tuple(
                task_id for task_id, task in canvas.tasks.items() if task["plan_id"] == plan_id
            )
            for plan_id in canvas.plan_ids
        }
        checks["canvas_task_heading_order_is_dependency_order"] = all(
            all(edge in canvas.edges for edge in zip(tasks, tasks[1:]))
            for tasks in canvas_plan_tasks.values()
        )
        checks["canvas_internal_dependency_edges_are_nonzero"] = sum(
            1
            for dependency, dependent in canvas.edges
            if canvas.tasks[dependency]["plan_id"] == canvas.tasks[dependent]["plan_id"]
        ) >= 69
        checks["canvas_ownership_glob_is_bound_to_stage"] = canvas.file_ownership_patterns[
            "src/domain/project/**"
        ].endswith("wave-a1-domain-history")
        checks["canvas_ownership_glob_matches_actual_claims"] = any(
            canvas.tasks[writer]["plan_id"].endswith("wave-a1-domain-history")
            for writer in canvas.file_ownership["src/domain/project/types.ts"]
        )
        checks["canvas_interface_only_rule_binds_declared_interface"] = any(
            canvas.tasks[writer]["plan_id"].endswith("wave-a1-domain-history")
            for writer in canvas.file_interface_writers["src/editor/store/editorStore.ts"]
        )
        canvas_a2_patterns = {
            "src/persistence/projectRepository.ts",
            "src/persistence/indexedDbProjectRepository.ts",
            "src/persistence/projectMigration.ts",
            "src/project/commit/**",
            "src/project/recovery/**",
            "src/project/lease/**",
        }
        checks["canvas_a2_all_backtick_paths_are_owner_patterns"] = (
            canvas_a2_patterns.issubset(canvas.file_ownership_patterns)
            and all(
                canvas.file_ownership_patterns[pattern].endswith(
                    "wave-a2-local-repository-recovery"
                )
                for pattern in canvas_a2_patterns
            )
        )

        first_source_name = Path(str(canvas_bundle["plans"][0]["source_path"])).name
        first_source = (
            FIXTURES
            / "canvas-program-6d41fb9"
            / str(canvas_bundle["source"]["tracked_sources_root"])
            / first_source_name
        ).read_bytes()
        changed_first_source = first_source.replace(
            b"**Files:**", b"Task source revision marker.\n\n**Files:**", 1
        )
        changed_exact_canvas = _compile_exact_canvas(
            canvas_bundle,
            root / "canvas-first-task-changed",
            {first_source_name: changed_first_source},
        )
        first_task = canvas_plan_tasks[canvas.plan_ids[0]][0]
        checks["canvas_first_task_change_invalidates_later_tasks"] = (
            invalidated_nodes(canvas, changed_exact_canvas)
            == changed_exact_canvas.downstream_of(first_task)
            and set(canvas_plan_tasks[canvas.plan_ids[0]]).issubset(
                invalidated_nodes(canvas, changed_exact_canvas)
            )
        )
        program_source_name = Path(str(canvas_bundle["source"]["program_path"])).name
        program_source = (
            FIXTURES
            / "canvas-program-6d41fb9"
            / str(canvas_bundle["source"]["tracked_sources_root"])
            / program_source_name
        ).read_bytes()
        unmatched_pattern_program = program_source.replace(
            b"`src/domain/project/**`", b"`src/not-claimed/**`", 1
        )
        checks["canvas_unmatched_ownership_glob_blocks"] = _exact_canvas_block_category(
            canvas_bundle,
            root / "canvas-unmatched-ownership",
            {program_source_name: unmatched_pattern_program},
        ) == "file_ownership_invalid"
        a1_source_name = next(
            Path(str(item["source_path"])).name
            for item in canvas_bundle["plans"]
            if item["plan_id"] == "wave-a1-domain-history"
        )
        a1_source = (
            FIXTURES
            / "canvas-program-6d41fb9"
            / str(canvas_bundle["source"]["tracked_sources_root"])
            / a1_source_name
        ).read_bytes()
        missing_interfaces_a1 = a1_source.replace(b"**Interfaces:**", b"**Contracts:**")
        checks["canvas_missing_interface_only_contract_blocks"] = _exact_canvas_block_category(
            canvas_bundle,
            root / "canvas-missing-interface-contract",
            {a1_source_name: missing_interfaces_a1},
        ) == "interface_contract_missing"
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
        ownership_alias = copy.deepcopy(ownership)
        ownership_alias["plans"][1]["contract"]["tasks"][0]["file_claims"] = [
            "./shared/api.py"
        ]
        checks["canonical_path_alias_cannot_bypass_ownership"] = _blocked(
            "ambiguous_file_ownership", ownership_alias, root / "ownership-alias-blocked"
        )
        parent_claim = _simple_bundle()
        parent_claim["plans"][0]["contract"]["tasks"][0]["file_claims"] = [
            "../outside.py"
        ]
        checks["parent_traversal_file_claim_blocks"] = _blocked(
            "file_claim_invalid", parent_claim, root / "parent-claim"
        )
        absolute_claim = _simple_bundle()
        absolute_claim["plans"][0]["contract"]["tasks"][0]["file_claims"] = [
            "/tmp/outside.py"
        ]
        checks["absolute_file_claim_blocks"] = _blocked(
            "file_claim_invalid", absolute_claim, root / "absolute-claim"
        )
        duplicate_separator_claim = _simple_bundle()
        duplicate_separator_claim["plans"][0]["contract"]["tasks"][0]["file_claims"] = [
            "src//plan-1.py"
        ]
        checks["duplicate_separator_file_claim_blocks"] = _blocked(
            "file_claim_invalid", duplicate_separator_claim, root / "duplicate-separator-claim"
        )
        dot_segment_claim = _simple_bundle()
        dot_segment_claim["plans"][0]["contract"]["tasks"][0]["file_claims"] = [
            "src/./plan-1.py"
        ]
        checks["dot_segment_file_claim_blocks"] = _blocked(
            "file_claim_invalid", dot_segment_claim, root / "dot-segment-claim"
        )
        colliding_claims = _simple_bundle()
        colliding_claims["plans"][0]["contract"]["tasks"][0]["file_claims"] = [
            "shared/api.py",
            "./shared/api.py",
        ]
        checks["canonical_claim_collision_blocks"] = _blocked(
            "file_claim_invalid", colliding_claims, root / "canonical-claim-collision"
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

        sole_owner = _simple_bundle(1, with_program=True)
        sole_owner["program"]["contract"]["file_ownership"] = {
            "src/plan-1.py": ["plan-1::wrong"]
        }
        checks["sole_writer_contradiction_blocks"] = _blocked(
            "ambiguous_file_ownership", sole_owner, root / "sole-owner-bad"
        )
        sole_owner["program"]["contract"]["file_ownership"] = {
            "src/plan-1.py": ["plan-1::build"]
        }
        sole_owner_graph = _compile_bundle(sole_owner, root / "sole-owner-good")
        checks["sole_writer_declaration_is_validated"] = (
            sole_owner_graph.file_ownership["src/plan-1.py"] == ("plan-1::build",)
        )

        bad_transfer = copy.deepcopy(ownership)
        bad_transfer["program"]["contract"]["ownership_transfers"] = [
            {"path": "shared/api.py", "from": "plan-1::missing", "to": owners[1]}
        ]
        checks["transfer_endpoints_must_be_actual_writers"] = _blocked(
            "ambiguous_file_ownership", bad_transfer, root / "bad-transfer-endpoint"
        )

        bad_shared = _simple_bundle(1, with_program=True)
        bad_shared["program"]["contract"]["shared_interfaces"] = ["not-claimed.py"]
        checks["shared_interface_must_name_claimed_path"] = _blocked(
            "ambiguous_file_ownership", bad_shared, root / "bad-shared-interface"
        )
        shared = copy.deepcopy(ownership)
        shared["program"]["contract"]["ownership_transfers"] = []
        shared["program"]["contract"]["shared_interfaces"] = ["shared/api.py"]
        shared_graph = _compile_bundle(shared, root / "shared-interface")
        checks["validated_shared_interface_allows_ordered_writers"] = (
            shared_graph.file_ownership["shared/api.py"] == tuple(owners)
        )
        dual_authority = copy.deepcopy(ownership)
        dual_authority["program"]["contract"]["shared_interfaces"] = ["shared/api.py"]
        checks["dual_transfer_and_shared_authority_blocks"] = _blocked(
            "ambiguous_file_ownership", dual_authority, root / "dual-authority"
        )
        checks["authority_mode_change_invalidates_writers_and_downstream"] = (
            transferred.file_ownership == shared_graph.file_ownership
            and transferred.edges == shared_graph.edges
            and invalidated_nodes(transferred, shared_graph) == tuple(shared_graph.tasks)
            and transferred.ownership_authority["shared/api.py"]["mode"]
            == "ownership_transfer"
            and shared_graph.ownership_authority["shared/api.py"]["mode"]
            == "shared_interface"
        )

        canonical_authority = copy.deepcopy(shared)
        canonical_authority["program"]["contract"]["file_ownership"] = {
            "./shared/api.py": owners
        }
        canonical_authority["program"]["contract"]["shared_interfaces"] = [
            "./shared/api.py"
        ]
        checks["ownership_authority_paths_are_canonical"] = (
            _compile_bundle(canonical_authority, root / "canonical-authority").file_ownership[
                "shared/api.py"
            ]
            == tuple(owners)
        )

        pattern_authority = copy.deepcopy(shared)
        for item in pattern_authority["plans"]:
            item["contract"]["tasks"][0]["interface_declared"] = True
        pattern_authority["program"]["contract"]["file_ownership_patterns"] = {
            "shared/**": "plan-1"
        }
        pattern_authority["program"]["contract"]["file_interface_writers"] = {
            "shared/api.py": ["plan-2::build"]
        }
        pattern_base = _compile_bundle(pattern_authority, root / "pattern-authority-base")
        changed_pattern_authority = copy.deepcopy(pattern_authority)
        changed_pattern_authority["program"]["contract"]["file_ownership_patterns"] = {
            "shared/**": "plan-2"
        }
        changed_pattern_authority["program"]["contract"]["file_interface_writers"] = {
            "shared/api.py": ["plan-1::build"]
        }
        pattern_changed = _compile_bundle(
            changed_pattern_authority, root / "pattern-authority-changed"
        )
        checks["pattern_owner_change_invalidates_writers_and_downstream"] = invalidated_nodes(
            pattern_base, pattern_changed
        ) == tuple(pattern_changed.tasks)

        interface_authority = _simple_bundle(1, with_program=True)
        interface_tasks = interface_authority["plans"][0]["contract"]["tasks"]
        interface_tasks[0]["file_claims"] = ["shared/api.py"]
        interface_tasks[0]["interface_declared"] = True
        interface_tasks.append(
            {
                "task_id": "verify",
                "dependencies": [],
                "spec_refs": ["S1"],
                "file_claims": ["shared/api.py"],
                "interface_declared": True,
            }
        )
        interface_authority["program"]["contract"]["global_integration_gate"] = (
            "plan-1::verify"
        )
        interface_authority["program"]["contract"]["file_interface_writers"] = {
            "shared/api.py": ["plan-1::build"]
        }
        interface_base = _compile_bundle(interface_authority, root / "interface-authority-base")
        changed_interface_authority = copy.deepcopy(interface_authority)
        changed_interface_authority["program"]["contract"]["file_interface_writers"] = {
            "shared/api.py": ["plan-1::verify"]
        }
        interface_changed = _compile_bundle(
            changed_interface_authority, root / "interface-authority-changed"
        )
        checks["interface_authority_change_invalidates_writers_and_downstream"] = (
            invalidated_nodes(interface_base, interface_changed)
            == tuple(interface_changed.tasks)
        )

        writers = _simple_bundle()
        writers["plans"][0]["contract"]["tasks"].append(
            {
                "task_id": "second-write",
                "dependencies": [],
                "spec_refs": ["S1"],
                "file_claims": ["src/second.py"],
            }
        )
        writers_graph = _compile_bundle(writers, root / "dependency-free-writers")
        checks["dependency_free_writers_are_serial"] = (
            "plan-1::build",
            "plan-1::second-write",
        ) in writers_graph.edges

        scouts = _simple_bundle()
        scouts["plans"][0]["contract"]["tasks"] = [
            {
                "task_id": "scout-a",
                "dependencies": [],
                "spec_refs": ["S1"],
                "file_claims": [],
                "read_only": True,
            },
            {
                "task_id": "scout-b",
                "dependencies": [],
                "spec_refs": ["S1"],
                "file_claims": [],
                "read_only": True,
            },
            {
                "task_id": "gate",
                "dependencies": ["scout-a", "scout-b"],
                "spec_refs": ["S1"],
                "file_claims": ["src/gate.py"],
            },
        ]
        scouts_graph = _compile_bundle(scouts, root / "read-only-scouts")
        checks["read_only_scouts_may_run_concurrently"] = (
            ("plan-1::scout-a", "plan-1::scout-b") not in scouts_graph.edges
            and ("plan-1::scout-b", "plan-1::scout-a") not in scouts_graph.edges
        )
        invalid_scout = _simple_bundle()
        invalid_scout["plans"][0]["contract"]["tasks"][0]["read_only"] = True
        checks["read_only_task_with_file_claim_blocks"] = _blocked(
            "read_only_claim_invalid", invalid_scout, root / "invalid-read-only-claim"
        )

        section_base = _compile_bundle(
            _section_bundle({"S1": "alpha", "S2": "beta"}), root / "sections-base"
        )
        section_s1 = _compile_bundle(
            _section_bundle({"S1": "alpha changed", "S2": "beta"}), root / "sections-s1"
        )
        section_s2 = _compile_bundle(
            _section_bundle({"S1": "alpha", "S2": "beta changed"}), root / "sections-s2"
        )
        checks["section_digests_are_canonical"] = (
            section_base.spec_section_hashes["S1"] != section_s1.spec_section_hashes["S1"]
            and section_base.spec_section_hashes["S2"] == section_s1.spec_section_hashes["S2"]
        )
        checks["s1_edit_invalidates_sequential_writers_and_gate"] = invalidated_nodes(
            section_base, section_s1
        ) == tuple(section_s1.tasks)
        checks["s2_edit_invalidates_s2_and_gate_only"] = invalidated_nodes(
            section_base, section_s2
        ) == ("section-plan::s2", "section-plan::gate")
        section_added = _compile_bundle(
            _section_bundle({"S1": "alpha", "S2": "beta", "S3": "new"}),
            root / "sections-added",
        )
        section_removed = _compile_bundle(
            _section_bundle({"S1": "alpha"}), root / "sections-removed"
        )
        checks["section_addition_invalidates_conservatively"] = invalidated_nodes(
            section_base, section_added
        ) == tuple(section_added.tasks)
        checks["section_removal_invalidates_old_coverage_and_downstream"] = invalidated_nodes(
            section_base, section_removed
        ) == ("section-plan::s2", "section-plan::gate")

        numeric_base = _compile_bundle(
            _non_s_bundle("### 7.3 Authority\nalpha\n\n### 7.4 Other\nbeta"),
            root / "numeric-base",
        )
        numeric_changed = _compile_bundle(
            _non_s_bundle("### 7.3 Authority\nalpha changed\n\n### 7.4 Other\nbeta"),
            root / "numeric-changed",
        )
        checks["numeric_heading_spec_change_invalidates_conservatively"] = invalidated_nodes(
            numeric_base, numeric_changed
        ) == tuple(numeric_changed.tasks)
        unstructured_base = _compile_bundle(
            _non_s_bundle("Unstructured requirements alpha"), root / "unstructured-base"
        )
        unstructured_changed = _compile_bundle(
            _non_s_bundle("Unstructured requirements beta"), root / "unstructured-changed"
        )
        checks["unstructured_spec_change_invalidates_conservatively"] = invalidated_nodes(
            unstructured_base, unstructured_changed
        ) == tuple(unstructured_changed.tasks)
        no_spec = _compile_bundle(_non_s_bundle(None), root / "no-spec")
        checks["spec_addition_invalidates_conservatively"] = invalidated_nodes(
            no_spec, unstructured_base
        ) == tuple(unstructured_base.tasks)
        checks["spec_removal_invalidates_conservatively"] = invalidated_nodes(
            unstructured_base, no_spec
        ) == tuple(no_spec.tasks)

        checks["duplicate_natural_stage_alias_blocks"] = _alias_collision_blocks(
            root / "alias-collision"
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
        synthetic_canvas = _compile_bundle(canvas_bundle, root / "canvas-synthetic")
        changed_canvas = _compile_bundle(changed_bundle, root / "canvas-changed")
        checks["invalidation_is_changed_region_and_downstream_only"] = (
            invalidated_nodes(synthetic_canvas, changed_canvas)
            == changed_canvas.downstream_of("wave-b2-import-repair-ux")
            and not any(
                "wave-b1" in node
                for node in invalidated_nodes(synthetic_canvas, changed_canvas)
            )
        )
        checks["graph_hash_is_deterministic"] = (
            canvas.graph_sha256
            == _compile_exact_canvas(canvas_bundle, root / "canvas-again").graph_sha256
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
