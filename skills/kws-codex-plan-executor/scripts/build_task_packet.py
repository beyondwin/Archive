#!/usr/bin/env python3
"""Build compact per-task context packets from a parsed plan and spec manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


FALLBACK_POLICIES = {"full_spec_on_blocker", "halt_on_blocker"}
DEFAULT_FORBIDDEN_GLOBS = [".git/**", "graphify-out/**"]


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        die(f"JSON file is not readable: {path}: {exc}")
    except json.JSONDecodeError as exc:
        die(f"JSON file is invalid: {path}: {exc}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def component(
    role: str,
    source_path: str,
    source_ref: str,
    text: str,
    inclusion_reason: str,
    reducible: bool,
) -> dict:
    return {
        "role": role,
        "source_path": source_path,
        "source_ref": source_ref,
        "chars": len(text),
        "estimated_tokens": max(1, len(text) // 4),
        "sha256": sha256_text(text),
        "inclusion_reason": inclusion_reason,
        "reducible": reducible,
    }


def find_task(plan: dict, task_id: str) -> dict:
    for task in plan.get("tasks", []):
        if task.get("id") == task_id:
            return task
    die(f"unknown task id: {task_id}")


def section_text(spec_text: str, section: dict) -> str:
    lines = spec_text.splitlines(keepends=True)
    start = int(section.get("line_start", 1))
    end = int(section.get("line_end", start))
    return "".join(lines[start - 1 : end])


def tokenize(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def path_tokens(files: list[str]) -> set[str]:
    tokens: set[str] = set()
    for file_path in files:
        tokens.update(tokenize(file_path))
        path = Path(file_path)
        tokens.update(tokenize(path.stem))
        tokens.update(tokenize(" ".join(path.parts)))
    return tokens


def path_literal_matches(path_literal: str, files: list[str]) -> bool:
    literal = path_literal.strip().strip("/")
    if not literal:
        return False
    for file_path in files:
        candidate = file_path.strip().strip("/")
        if candidate == literal or candidate.endswith("/" + literal) or literal.endswith("/" + candidate):
            return True
    return False


def score_section(task: dict, section_id: str, section: dict) -> tuple[int, list[str]]:
    files = [item for item in task.get("files", []) if isinstance(item, str)]
    file_tokens = path_tokens(files)
    signals = section.get("signals") if isinstance(section.get("signals"), dict) else {}
    score = 0
    reasons: list[str] = []
    for path_literal in signals.get("path_literals", []):
        if path_literal_matches(str(path_literal), files):
            score += 8
            reasons.append("path_literal")
            break
    identifiers = set(signals.get("code_identifiers", []))
    if identifiers and identifiers.intersection(file_tokens):
        score += 4
        reasons.append("code_identifier")
    title_tokens = set(signals.get("title_tokens", [])) or tokenize(str(section.get("title", "")))
    if title_tokens and title_tokens.issubset(file_tokens):
        score += 2
        reasons.append("title_token")
    task_ids = set(signals.get("task_ids", []))
    if str(task.get("id", "")).lower() in task_ids:
        score += 6
        reasons.append("task_id")
    return score, reasons


def heuristic_sections(task: dict, manifest: dict) -> tuple[list[str], list[dict]]:
    tokens = path_tokens([item for item in task.get("files", []) if isinstance(item, str)])
    if not tokens:
        return [], []
    matched: list[str] = []
    candidate_scores: list[dict] = []
    sections = manifest.get("sections", {})
    for section_id in manifest.get("section_order", []):
        section = sections.get(section_id, {})
        score, signals = score_section(task, section_id, section)
        if score:
            candidate_scores.append({"section_id": section_id, "score": score, "signals": signals})
        if score >= 2:
            matched.append(section_id)
    candidate_scores.sort(key=lambda item: (-item["score"], item["section_id"]))
    return matched, candidate_scores


def fallback_reason(task: dict, candidate_scores: list[dict]) -> str:
    explicit = [item for item in task.get("spec_refs", []) if isinstance(item, str) and item.strip()]
    files = [item for item in task.get("files", []) if isinstance(item, str) and item.strip()]
    if candidate_scores or files:
        return "weak_heuristic_match"
    if not explicit:
        return "missing_spec_refs"
    return "manifest_gap"


def suggested_spec_refs(candidate_scores: list[dict]) -> list[str]:
    result: list[str] = []
    for item in candidate_scores[:3]:
        section_id = item.get("section_id")
        if isinstance(section_id, str) and section_id not in result:
            result.append(section_id)
    return result


def resolve_sections(task: dict, manifest: dict, fallback_policy: str) -> tuple[list[str], bool, dict]:
    sections = manifest.get("sections", {})
    explicit = [item for item in task.get("spec_refs", []) if isinstance(item, str) and item.strip()]
    if explicit:
        for section_id in explicit:
            if section_id not in sections:
                die(f"unknown spec ref for {task.get('id')}: {section_id}")
        return explicit, False, {
            "selected_section_ids": explicit,
            "candidate_scores": [{"section_id": section_id, "score": 100, "signals": ["explicit_spec_ref"]} for section_id in explicit],
            "mapping_reason": "Matched explicit Spec Refs.",
            "requires_parent_mapping": False,
            "source": "explicit",
        }

    task_to_sections = manifest.get("task_to_sections") if isinstance(manifest.get("task_to_sections"), dict) else {}
    manifest_refs = [
        item.strip()
        for item in task_to_sections.get(str(task.get("id", "")), [])
        if isinstance(item, str) and item.strip()
    ]
    if manifest_refs:
        for section_id in manifest_refs:
            if section_id not in sections:
                die(f"unknown manifest section for {task.get('id')}: {section_id}")
        return manifest_refs, False, {
            "selected_section_ids": manifest_refs,
            "candidate_scores": [
                {"section_id": section_id, "score": 90, "signals": ["manifest_task_to_sections"]}
                for section_id in manifest_refs
            ],
            "mapping_reason": "Matched spec manifest task_to_sections.",
            "requires_parent_mapping": False,
            "source": "manifest",
        }

    matched, candidate_scores = heuristic_sections(task, manifest)
    if matched:
        selected = [item["section_id"] for item in candidate_scores if item["section_id"] in matched]
        return selected, False, {
            "selected_section_ids": selected,
            "candidate_scores": candidate_scores,
            "mapping_reason": "Matched task file or identifier signals.",
            "requires_parent_mapping": False,
            "source": "heuristic",
        }

    if fallback_policy == "halt_on_blocker":
        die(f"no spec section mapping for {task.get('id')}")
    reason = fallback_reason(task, candidate_scores)
    return ["*"], True, {
        "selected_section_ids": ["*"],
        "candidate_scores": candidate_scores,
        "mapping_reason": "No task-specific spec section matched; using full spec fallback.",
        "requires_parent_mapping": True,
        "source": "fallback",
        "fallback_reason": reason,
        "suggested_spec_refs": suggested_spec_refs(candidate_scores),
        "operator_reviewed": False,
    }


def spec_context(spec_path: Path, manifest: dict, section_ids: list[str], fallback_used: bool) -> tuple[str, str, str]:
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"spec is not readable: {spec_path}: {exc}")

    if fallback_used:
        return "full", "*", "## Spec context (full spec fallback)\n\n" + spec_text

    sections = manifest.get("sections", {})
    bodies = [section_text(spec_text, sections[section_id]) for section_id in section_ids]
    label = ", ".join(section_ids)
    return "slice", label, f"## Spec context (sections: {label})\n\n" + "\n".join(bodies)


def load_decisions(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("decisions_register"), list):
        return payload["decisions_register"]
    if isinstance(payload, dict) and isinstance(payload.get("decisions"), list):
        return payload["decisions"]
    die(f"decisions file must contain a list: {path}")


def decision_relevant(decision: dict, task: dict, section_ids: list[str]) -> bool:
    task_id = str(task.get("id", ""))
    task_value = str(decision.get("task", ""))
    if task_value == task_id:
        return True
    if task_value == "global" and not decision.get("superseded_by"):
        return True
    decision_task_ids = decision.get("task_ids")
    if isinstance(decision_task_ids, list) and task_id in decision_task_ids:
        return True
    files = {item for item in task.get("files", []) if isinstance(item, str)}
    decision_files = {item for item in decision.get("files", []) if isinstance(item, str)}
    if files.intersection(decision_files):
        return True
    decision_sections = {item for item in decision.get("spec_section_ids", []) if isinstance(item, str)}
    return bool(decision_sections.intersection(section_ids))


def filter_decisions(decisions: list[dict], task: dict, section_ids: list[str]) -> dict:
    included = [decision for decision in decisions if isinstance(decision, dict) and decision_relevant(decision, task, section_ids)]
    return {
        "included": included,
        "omitted_count": max(0, len(decisions) - len(included)),
        "selection_reason": "Matched task id, files, selected spec sections, or active global decisions.",
    }


def budget_status(estimated_chars: int, max_chars: int, threshold: float) -> str:
    if estimated_chars > max_chars:
        return "red"
    if estimated_chars > int(max_chars * threshold):
        return "yellow"
    return "green"


def build_packet(
    plan: dict,
    task_id: str,
    spec_path: Path,
    manifest: dict,
    decisions: list[dict],
    max_chars: int,
    context_threshold: float,
    fallback_policy: str,
) -> dict:
    if fallback_policy not in FALLBACK_POLICIES:
        die(f"invalid manifest fallback: {fallback_policy}")
    if max_chars <= 0:
        die("--max-chars must be a positive integer")
    if context_threshold < 0.05 or context_threshold > 0.95:
        die("--context-threshold must be in [0.05,0.95]")

    task = find_task(plan, task_id)
    section_ids, fallback_used, mapping = resolve_sections(task, manifest, fallback_policy)
    spec_mode, section_label, spec_text = spec_context(spec_path, manifest, section_ids, fallback_used)
    files = [item for item in task.get("files", []) if isinstance(item, str)]
    depends_on = [item for item in task.get("depends_on", []) if isinstance(item, str)]
    task_body = task.get("body", "")
    acceptance_command = task.get("acceptance_command")
    acceptance_source = task.get("acceptance_source") or (
        "plan.command_fence_fallback" if acceptance_command else "missing"
    )
    acceptance_text = acceptance_command or "missing acceptance command"
    spec_component_role = "spec_full_fallback" if fallback_used else "spec_slice"
    context_components = [
        component("task_body", str(plan.get("plan", "")), task_id, task_body, "active task contract", False),
        component(
            spec_component_role,
            str(spec_path),
            section_label,
            spec_text,
            "full spec fallback" if fallback_used else "selected spec section",
            True,
        ),
        component("write_policy", str(plan.get("plan", "")), task_id, "\n".join(files), "task write scope", False),
        component(
            "acceptance",
            str(plan.get("plan", "")),
            task_id,
            acceptance_text,
            "task verification contract" if acceptance_command else "acceptance missing marker",
            acceptance_command is None,
        ),
    ]
    packet_base = {
        "schema_version": "1",
        "task_id": task_id,
        "task_title": task.get("title", ""),
        "task_body": task_body,
        "files": files,
        "depends_on": depends_on,
        "dependencies": depends_on,
        "acceptance": {
            "has_acceptance_criteria": bool(task.get("has_acceptance_criteria")),
            "command": acceptance_command,
            "source": acceptance_source,
            "honest_substitute_allowed": acceptance_command is None,
        },
        "spec": {
            "mode": spec_mode,
            "section_ids": section_ids,
            "section_label": section_label,
            "fallback_used": fallback_used,
            "text": spec_text,
            "mapping": mapping,
        },
        "decisions_register": filter_decisions(decisions, task, section_ids),
        "write_policy": {
            "allowed_write_globs": files,
            "forbidden_write_globs": DEFAULT_FORBIDDEN_GLOBS,
        },
        "unit_manifest": {
            "unit_type": "execute-task",
            "context_mode": "focused",
            "required_skills": ["using-superpowers", "test-driven-development"],
            "tool_policy": "implementation",
            "allowed_write_globs": files,
            "forbidden_write_globs": DEFAULT_FORBIDDEN_GLOBS,
            "artifact_policy": "inline-summary",
            "max_context_chars": max_chars,
        },
        "context_components": context_components,
    }
    estimated_chars = len(json.dumps(packet_base, ensure_ascii=False, sort_keys=True))
    component_totals: dict[str, int] = {}
    for item in context_components:
        role = item["role"]
        family = "spec" if role.startswith("spec_") else role
        component_totals[family] = component_totals.get(family, 0) + int(item["chars"])
    largest_component = max(
        context_components,
        key=lambda item: int(item["chars"]),
        default={"role": "", "chars": 0, "source_ref": ""},
    )
    packet_base["context_budget"] = {
        "estimated_chars": estimated_chars,
        "max_chars": max_chars,
        "status": budget_status(estimated_chars, max_chars, context_threshold),
        "largest_component": {
            "role": largest_component.get("role"),
            "chars": largest_component.get("chars"),
            "source_ref": largest_component.get("source_ref"),
        },
        "component_totals": component_totals,
    }
    packet_base["sha256"] = sha256_text(json.dumps(packet_base, ensure_ascii=False, sort_keys=True))
    return packet_base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--spec-manifest", required=True)
    parser.add_argument("--decisions")
    parser.add_argument("--max-chars", type=int, default=60000)
    parser.add_argument("--context-threshold", type=float, default=0.70)
    parser.add_argument("--manifest-fallback", default="full_spec_on_blocker")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan = load_json(Path(args.plan_json).expanduser())
    manifest = load_json(Path(args.spec_manifest).expanduser())
    if not isinstance(plan, dict):
        die("plan JSON must be an object")
    if not isinstance(manifest, dict):
        die("spec manifest must be an object")
    decisions = load_decisions(Path(args.decisions).expanduser() if args.decisions else None)
    packet = build_packet(
        plan,
        args.task_id,
        Path(args.spec).expanduser(),
        manifest,
        decisions,
        args.max_chars,
        args.context_threshold,
        args.manifest_fallback,
    )
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
