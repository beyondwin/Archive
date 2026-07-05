#!/usr/bin/env python3
"""Deterministic checks for compact task packet generation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_task_packet


def write_json(path: Path, payload: dict | list) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_packet(
    root: Path,
    plan: dict,
    spec_text: str,
    manifest: dict,
    task_id: str,
    extra_args: list[str] | None = None,
    decisions_payload: dict | list | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_task_packet.py"
    plan_json = root / "plan.json"
    spec = root / "spec.md"
    manifest_path = root / "spec_manifest.json"
    decisions = root / "decisions_register.json"
    output = root / f"{task_id}.json"
    write_json(plan_json, plan)
    spec.write_text(spec_text, encoding="utf-8")
    write_json(manifest_path, manifest)
    write_json(decisions, [] if decisions_payload is None else decisions_payload)
    command = [
        sys.executable,
        str(script),
        "--plan-json",
        str(plan_json),
        "--task-id",
        task_id,
        "--spec",
        str(spec),
        "--spec-manifest",
        str(manifest_path),
        "--decisions",
        str(decisions),
        "--output",
        str(output),
    ]
    if extra_args:
        command.extend(extra_args)
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def plan_for(task: dict) -> dict:
    return {"plan": "plan.md", "mode": "interactive", "tasks": [task]}


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    spec_text = "# Feature\n\nfeature text\n# Auth Session\n\nauth session text\n# Billing Workflow\n\nbilling workflow text\n"
    manifest = {
        "schema_version": "1",
        "spec_path": "spec.md",
        "fallback_policy": "full_spec_on_blocker",
        "sections": {
            "S1": {"id": "S1", "title": "Feature", "level": 1, "line_start": 1, "line_end": 3, "chars": 24, "sha256": "x"},
            "S2": {"id": "S2", "title": "Auth Session", "level": 1, "line_start": 4, "line_end": 6, "chars": 31, "sha256": "y"},
            "S3": {
                "id": "S3",
                "title": "Billing Workflow",
                "level": 1,
                "line_start": 7,
                "line_end": 9,
                "chars": 32,
                "sha256": "z",
                "signals": {"title_tokens": ["billing", "workflow"]},
            },
        },
        "section_order": ["S1", "S2", "S3"],
        "task_to_sections": {},
    }

    with tempfile.TemporaryDirectory(prefix="codex-task-packet-") as temp:
        root = Path(temp)
        explicit_task = {
            "id": "task_0",
            "title": "Add feature",
            "body": "Task body",
            "files": ["scripts/feature.py"],
            "depends_on": [],
            "spec_refs": ["S1"],
            "has_acceptance_criteria": True,
            "acceptance_command": "python3 evals/check_feature.py",
        }
        explicit_result, explicit = run_packet(root, plan_for(explicit_task), spec_text, manifest, "task_0")
        checks["explicit_refs_exact"] = (
            explicit_result.returncode == 0
            and explicit.get("spec", {}).get("section_ids") == ["S1"]
            and explicit.get("spec", {}).get("fallback_used") is False
            and "feature text" in explicit.get("spec", {}).get("text", "")
            and "auth session text" not in explicit.get("spec", {}).get("text", "")
        )
        if not checks["explicit_refs_exact"]:
            failures.append("explicit spec_refs should map to exact manifest sections")
        components = explicit.get("context_components", [])
        checks["context_components_present"] = (
            explicit_result.returncode == 0
            and isinstance(components, list)
            and any(item.get("role") == "task_body" for item in components)
            and any(item.get("role") == "spec_slice" for item in components)
            and any(item.get("role") == "acceptance" for item in components)
            and all(item.get("sha256") for item in components)
        )
        if not checks["context_components_present"]:
            failures.append("packet should include stable context_components for task/spec/acceptance")
        checks["acceptance_command_preserved"] = explicit.get("acceptance", {}).get("command") == "python3 evals/check_feature.py"
        if not checks["acceptance_command_preserved"]:
            failures.append("packet should preserve parsed acceptance command")
        budget = explicit.get("context_budget", {})
        checks["component_budget_breakdown"] = (
            isinstance(budget.get("largest_component"), dict)
            and isinstance(budget.get("component_totals"), dict)
            and budget["component_totals"].get("spec", 0) > 0
        )
        if not checks["component_budget_breakdown"]:
            failures.append("context_budget should include largest_component and component_totals")

        heuristic_task = {
            "id": "task_1",
            "title": "Auth wiring",
            "body": "Task body",
            "files": ["src/auth/session.py"],
            "depends_on": [],
            "spec_refs": [],
            "has_acceptance_criteria": False,
        }
        heuristic_result, heuristic = run_packet(root, plan_for(heuristic_task), spec_text, manifest, "task_1")
        checks["file_title_heuristic"] = (
            heuristic_result.returncode == 0
            and heuristic.get("spec", {}).get("section_ids") == ["S2"]
            and "auth session text" in heuristic.get("spec", {}).get("text", "")
        )
        if not checks["file_title_heuristic"]:
            failures.append("file path components should map src/auth/session.py to Auth Session")
        mapping = heuristic.get("spec", {}).get("mapping", {})
        checks["mapping_evidence_present"] = (
            mapping.get("selected_section_ids") == ["S2"]
            and isinstance(mapping.get("candidate_scores"), list)
            and mapping.get("mapping_reason")
            and mapping.get("requires_parent_mapping") is False
            and mapping.get("source") == "heuristic"
        )
        if not checks["mapping_evidence_present"]:
            failures.append("packet should preserve spec mapping evidence")

        fallback_task = {
            "id": "task_2",
            "title": "Other",
            "body": "Task body",
            "files": ["src/billing/invoice.py"],
            "depends_on": [],
            "spec_refs": [],
            "has_acceptance_criteria": False,
        }
        fallback_result, fallback = run_packet(root, plan_for(fallback_task), spec_text, manifest, "task_2")
        checks["fallback_full_spec"] = (
            fallback_result.returncode == 0
            and fallback.get("spec", {}).get("section_ids") == ["*"]
            and fallback.get("spec", {}).get("fallback_used") is True
            and "feature text" in fallback.get("spec", {}).get("text", "")
            and "auth session text" in fallback.get("spec", {}).get("text", "")
        )
        if not checks["fallback_full_spec"]:
            failures.append("unmapped task should use full-spec fallback marker")
        checks["full_spec_fallback_component_role"] = any(
            item.get("role") == "spec_full_fallback"
            for item in fallback.get("context_components", [])
        )
        if not checks["full_spec_fallback_component_role"]:
            failures.append("full spec fallback should be visible in context_components")
        fallback_mapping = fallback.get("spec", {}).get("mapping", {})
        checks["fallback_mapping_reason_and_suggestions"] = (
            fallback_mapping.get("fallback_reason") == "weak_heuristic_match"
            and fallback_mapping.get("suggested_spec_refs") == ["S3"]
            and fallback_mapping.get("suggested_plan_patch") == 'spec_refs: ["S3"]'
            and fallback_mapping.get("next_action") == "Add explicit spec_refs to the plan task using one of: S3"
            and fallback_mapping.get("operator_reviewed") is False
        )
        if not checks["fallback_mapping_reason_and_suggestions"]:
            failures.append("full-spec fallback should explain reason and suggested spec refs")
        checks["fallback_preview_is_bounded"] = (
            isinstance(fallback_mapping.get("fallback_preview"), dict)
            and fallback_mapping["fallback_preview"].get("source_ref") == "*"
            and isinstance(fallback_mapping["fallback_preview"].get("chars"), int)
            and fallback_mapping["fallback_preview"].get("chars") <= 1200
        )
        if not checks["fallback_preview_is_bounded"]:
            failures.append("fallback mapping should include bounded preview metadata")

        checks["fallback_next_action_helper_uses_literal_refs"] = (
            (refs := build_task_packet.suggested_spec_refs([{"section_id": "S1", "score": 11}])) == ["S1"]
            and build_task_packet.fallback_next_action("weak_heuristic_match", refs)
            == "Add explicit spec_refs to the plan task using one of: S1"
        )
        if not checks["fallback_next_action_helper_uses_literal_refs"]:
            failures.append("fallback next action helper should preserve the literal suggested refs")

        decision_task = {
            "id": "task_3",
            "title": "Feature decision",
            "body": "Task body",
            "files": ["scripts/feature.py"],
            "depends_on": [],
            "spec_refs": ["S1"],
            "has_acceptance_criteria": True,
            "acceptance_command": "python3 evals/check_feature.py",
        }
        decisions_payload = [
            {"id": "dec_1", "task": "task_3", "decision": "include task decision", "files": []},
            {"id": "dec_2", "task": "task_9", "decision": "omit unrelated", "files": ["other.py"]},
            {"id": "dec_3", "task": "global", "decision": "include global", "files": [], "superseded_by": None},
            {"id": "dec_4", "task": "global", "decision": "omit superseded", "files": [], "superseded_by": "dec_5"},
        ]
        decision_result, decision_packet = run_packet(
            root,
            plan_for(decision_task),
            spec_text,
            manifest,
            "task_3",
            decisions_payload=decisions_payload,
        )
        decision_context = decision_packet.get("decisions_register", {})
        included_ids = [item.get("id") for item in decision_context.get("included", [])]
        checks["decisions_filtered"] = (
            decision_result.returncode == 0
            and included_ids == ["dec_1", "dec_3"]
            and decision_context.get("omitted_count") == 2
            and bool(decision_context.get("selection_reason"))
        )
        if not checks["decisions_filtered"]:
            failures.append("task packet should include only task-relevant decisions")

        suffix_manifest = {
            "schema_version": "1",
            "spec_path": "spec.md",
            "fallback_policy": "full_spec_on_blocker",
            "sections": {
                "S1": {
                    "id": "S1",
                    "title": "State Schema",
                    "level": 1,
                    "line_start": 1,
                    "line_end": 3,
                    "chars": 24,
                    "sha256": "x",
                    "signals": {"path_literals": ["scripts/validate_state.py"], "title_tokens": ["state", "schema"], "code_identifiers": [], "task_ids": []},
                }
            },
            "section_order": ["S1"],
            "task_to_sections": {},
        }
        suffix_task = {
            "id": "task_4",
            "title": "State schema",
            "body": "Task body",
            "files": ["skills/kws-codex-plan-executor/scripts/validate_state.py"],
            "depends_on": [],
            "spec_refs": [],
            "has_acceptance_criteria": True,
            "acceptance_command": "python3 evals/check_state_schema.py",
        }
        suffix_result, suffix_packet = run_packet(root, plan_for(suffix_task), spec_text, suffix_manifest, "task_4")
        checks["path_literal_suffix_mapping"] = (
            suffix_result.returncode == 0
            and suffix_packet.get("spec", {}).get("section_ids") == ["S1"]
            and suffix_packet.get("spec", {}).get("fallback_used") is False
        )
        if not checks["path_literal_suffix_mapping"]:
            failures.append("spec path literals should match repo-root and skill-relative suffix paths")

        invalid_threshold_result, _ = run_packet(
            root,
            plan_for(explicit_task),
            spec_text,
            manifest,
            "task_0",
            extra_args=["--context-threshold", "1.0"],
        )
        checks["context_threshold_range_matches_invocation_parser"] = (
            invalid_threshold_result.returncode != 0
            and "[0.05,0.95]" in (invalid_threshold_result.stderr + invalid_threshold_result.stdout)
        )
        if not checks["context_threshold_range_matches_invocation_parser"]:
            failures.append("task packet context_threshold should reject values outside [0.05,0.95]")

        manifest_mapping = {
            "schema_version": "1",
            "spec_path": "spec.md",
            "fallback_policy": "full_spec_on_blocker",
            "sections": {
                "S1": {
                    "id": "S1",
                    "title": "Feature",
                    "level": 1,
                    "line_start": 1,
                    "line_end": 3,
                    "chars": 24,
                    "sha256": "x",
                },
                "S2": {
                    "id": "S2",
                    "title": "Auth Session",
                    "level": 1,
                    "line_start": 4,
                    "line_end": 6,
                    "chars": 31,
                    "sha256": "y",
                },
            },
            "section_order": ["S1", "S2"],
            "task_to_sections": {"task_manifest": ["S2"]},
        }
        manifest_task = {
            "id": "task_manifest",
            "title": "Unmatched title",
            "body": "Task body",
            "files": ["src/billing/invoice.py"],
            "depends_on": ["task_0"],
            "spec_refs": [],
            "has_acceptance_criteria": True,
            "acceptance_command": "python3 evals/check_task_packet.py",
        }
        manifest_result, manifest_packet = run_packet(
            root,
            plan_for(manifest_task),
            spec_text,
            manifest_mapping,
            "task_manifest",
        )
        checks["manifest_task_to_sections_precedes_full_spec_fallback"] = (
            manifest_result.returncode == 0
            and manifest_packet.get("spec", {}).get("fallback_used") is False
            and manifest_packet.get("spec", {}).get("section_ids") == ["S2"]
            and manifest_packet.get("spec", {}).get("mapping", {}).get("source") == "manifest"
        )
        if not checks["manifest_task_to_sections_precedes_full_spec_fallback"]:
            failures.append("manifest task_to_sections should precede full spec fallback")
        checks["packet_emits_dependencies_alias_for_dispatch"] = (
            manifest_packet.get("depends_on") == ["task_0"]
            and manifest_packet.get("dependencies") == ["task_0"]
        )
        if not checks["packet_emits_dependencies_alias_for_dispatch"]:
            failures.append("packet should emit dependencies alias matching depends_on")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
