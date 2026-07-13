"""Immutable compilation and selective invalidation for CPE vNext plan graphs."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .document_set import DocumentSet, InputDocument


SCHEMA_VERSION = "cpe.plan-graph.vnext"
CONTRACT_RE = re.compile(
    r"(?ms)^```json[ \t]+(?P<tag>cpe-(?:plan|program))[ \t]*\n(?P<body>.*?)\n```[ \t]*$"
)
TASK_RE = re.compile(
    r"(?m)^#{2,4}[ \t]+(?:Task|작업)[ \t]+(?P<number>\d+(?:\.\d+)*)"
    r"[ \t]*(?::|-|–|—)[ \t]*(?P<title>.+?)[ \t]*$"
)
SPEC_REF_RE = re.compile(r"\bS\d+(?:\.\d+)*\b")


class PlanGraphBlocked(ValueError):
    """A document set cannot form one unambiguous executable graph."""

    def __init__(self, category: str, summary: str, evidence: dict[str, object]):
        super().__init__(summary)
        self.category = category
        self.summary = summary
        self.evidence = evidence


@dataclass(frozen=True, order=True)
class QualifiedTaskId:
    plan_id: str
    task_id: str

    def __str__(self) -> str:
        return f"{self.plan_id}::{self.task_id}"


@dataclass(frozen=True)
class IntegrationGate(Mapping[str, object]):
    plan_id: str
    task_id: str
    qualified_task_id: str

    def __getitem__(self, key: str) -> object:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "qualified_task_id": self.qualified_task_id,
        }[key]

    def __iter__(self) -> Iterator[str]:
        return iter(("plan_id", "task_id", "qualified_task_id"))

    def __len__(self) -> int:
        return 3


@dataclass(frozen=True)
class PlanGraph:
    schema_version: str
    spec_document_id: str | None
    program_document_id: str | None
    plan_documents: tuple[str, ...]
    plan_ids: tuple[str, ...]
    document_hashes: Mapping[str, str]
    spec_section_hashes: Mapping[str, str]
    tasks: Mapping[str, Mapping[str, object]]
    edges: tuple[tuple[str, str], ...]
    spec_coverage: Mapping[str, tuple[str, ...]]
    file_ownership: Mapping[str, tuple[str, ...]]
    file_ownership_patterns: Mapping[str, str]
    file_interface_writers: Mapping[str, tuple[str, ...]]
    plan_checkpoints: Mapping[str, tuple[str, ...]]
    global_integration_gate: IntegrationGate
    graph_sha256: str

    @property
    def plan_count(self) -> int:
        return len(self.plan_documents)

    def downstream_of(self, selector: str) -> tuple[str, ...]:
        seeds = {
            task_id
            for task_id, task in self.tasks.items()
            if task_id == selector or task.get("plan_id") == selector
        }
        if not seeds:
            raise KeyError(f"unknown task or plan selector: {selector}")
        outgoing: dict[str, set[str]] = defaultdict(set)
        for dependency, dependent in self.edges:
            outgoing[dependency].add(dependent)
        affected = set(seeds)
        pending = deque(seeds)
        while pending:
            for dependent in outgoing[pending.popleft()]:
                if dependent not in affected:
                    affected.add(dependent)
                    pending.append(dependent)
        return tuple(task_id for task_id in self.tasks if task_id in affected)


def _blocked(category: str, summary: str, **evidence: object) -> None:
    raise PlanGraphBlocked(category, summary, evidence)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _json_contract(document: InputDocument, tag: str) -> dict[str, object] | None:
    try:
        text = document.content.decode("utf-8")
    except UnicodeDecodeError:
        _blocked(
            "document_encoding_invalid",
            "plan graph inputs must be UTF-8",
            document_id=document.document_id,
        )
    matches = [match for match in CONTRACT_RE.finditer(text) if match.group("tag") == tag]
    if not matches:
        return None
    if len(matches) != 1:
        _blocked(
            "contract_ambiguous",
            "a document must contain at most one graph contract",
            document_id=document.document_id,
            contract_tag=tag,
            count=len(matches),
        )
    try:
        payload = json.loads(matches[0].group("body"))
    except json.JSONDecodeError as exc:
        _blocked(
            "contract_invalid",
            "graph contract is not valid JSON",
            document_id=document.document_id,
            error=str(exc),
        )
    if not isinstance(payload, dict):
        _blocked(
            "contract_invalid",
            "graph contract must be a JSON object",
            document_id=document.document_id,
            contract_tag=tag,
        )
    return payload


def _document_plan_id(document: InputDocument) -> str:
    parts = document.document_id.split(":", 2)
    return parts[1] if len(parts) == 3 else document.document_id


def _path_plan_id(document: InputDocument) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", document.path.stem)


def _list(value: object, *, field: str, document_id: str) -> list[object]:
    if not isinstance(value, list):
        _blocked(
            "contract_invalid",
            f"{field} must be a list",
            document_id=document_id,
            field=field,
        )
    return value


def _fallback_plan_contract(document: InputDocument) -> dict[str, object]:
    """Read the existing Task-heading shape without reopening mutable source paths."""

    text = document.content.decode("utf-8")
    matches = list(TASK_RE.finditer(text))
    if not matches:
        _blocked(
            "plan_tasks_missing",
            "implementation plan has no executable tasks",
            document_id=document.document_id,
        )
    tasks: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        yaml_match = re.search(r"(?ms)^```yaml[^\n]*\n(?P<body>.*?)\n```", body)
        yaml_body = yaml_match.group("body") if yaml_match else ""
        dependencies = _inline_yaml_list(yaml_body, "dependencies") or _markdown_dependencies(body)
        if not dependencies and tasks:
            dependencies = [str(tasks[-1]["task_id"])]
        spec_refs = _inline_yaml_list(yaml_body, "spec_refs") or SPEC_REF_RE.findall(body)
        file_claims = _yaml_block_list(yaml_body, "file_claims") or _markdown_file_claims(body)
        task_id = "task_" + match.group("number").replace(".", "_")
        tasks.append(
            {
                "task_id": task_id,
                "dependencies": dependencies,
                "spec_refs": list(dict.fromkeys(spec_refs)),
                "file_claims": file_claims,
                "interface_declared": _markdown_interfaces_declared(body),
                "source_token": hashlib.sha256(
                    text[match.start() : end].encode("utf-8")
                ).hexdigest(),
            }
        )
    return {"plan_id": _path_plan_id(document), "tasks": tasks}


def _inline_yaml_list(body: str, key: str) -> list[str]:
    match = re.search(rf"(?m)^{re.escape(key)}:[ \t]*\[(?P<items>[^\]]*)\]", body)
    if not match:
        return []
    return [
        item.strip().strip("'\"")
        for item in match.group("items").split(",")
        if item.strip()
    ]


def _yaml_block_list(body: str, key: str) -> list[str]:
    match = re.search(
        rf"(?ms)^{re.escape(key)}:[ \t]*\n(?P<items>(?:[ \t]+-[^\n]*\n?)+)", body
    )
    if not match:
        return []
    return [
        line.split("-", 1)[1].strip().strip("'\"")
        for line in match.group("items").splitlines()
        if "-" in line
    ]


def _markdown_file_claims(body: str) -> list[str]:
    heading = re.search(r"(?mi)^\*\*Files:\*\*[ \t]*$", body)
    if not heading:
        return []
    claims: list[str] = []
    for line in body[heading.end() :].splitlines():
        stripped = line.strip()
        if not stripped:
            if claims:
                break
            continue
        if not stripped.startswith("-"):
            if claims:
                break
            continue
        path_match = re.search(r"`([^`]+)`", stripped)
        if path_match:
            claims.append(path_match.group(1).strip())
    return list(dict.fromkeys(claims))


def _markdown_dependencies(body: str) -> list[str]:
    match = re.search(r"(?mi)^\*\*Depends(?: on)?:\*\*[ \t]*(?P<value>.+)$", body)
    if not match:
        return []
    return [
        "task_" + number.replace(".", "_")
        for number in re.findall(r"\b(?:Task|T)[ _]?(\d+(?:\.\d+)*)\b", match.group("value"), re.I)
    ]


def _markdown_interfaces_declared(body: str) -> bool:
    match = re.search(r"(?mi)^\*\*Interfaces?:\*\*[ \t]*$", body)
    if not match:
        return False
    for line in body[match.end() :].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("**") or stripped.startswith("#"):
            return False
        return stripped.startswith("-")
    return False


def _markdown_section(text: str, heading: str) -> str:
    match = re.search(rf"(?mi)^##[ \t]+{re.escape(heading)}[ \t]*$", text)
    if not match:
        _blocked(
            "program_contract_missing",
            "natural-language program is missing a required section",
            heading=heading,
        )
    following = re.search(r"(?m)^##[ \t]+", text[match.end() :])
    end = match.end() + following.start() if following else len(text)
    return text[match.end() : end]


def _stage_alias(document: InputDocument) -> str | None:
    match = re.search(r"(?:^|-)wave-([a-c]\d|\d+)(?:-|$)", _path_plan_id(document), re.I)
    return match.group(1).upper() if match else None


def _path_matches_pattern(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3].rstrip("/") + "/")
    return path == pattern


def _natural_ownership_rules(
    section: str,
    aliases: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    patterns: dict[str, str] = {}
    interface_only: dict[str, str] = {}
    current_owner: str | None = None
    for line in section.splitlines():
        heading = re.match(r"^###[ \t]+([A-C]\d)[ \t]+owns[ \t]*$", line, re.I)
        if heading:
            alias = heading.group(1).upper()
            if alias not in aliases:
                _blocked(
                    "file_ownership_invalid",
                    "ownership heading references an unknown stage alias",
                    stage_alias=alias,
                )
            current_owner = aliases[alias]
            continue
        if current_owner is None or not line.lstrip().startswith("-"):
            continue
        bullet = line.lstrip()[1:].strip()
        candidates = [item for item in re.findall(r"`([^`]+)`", bullet) if "/" in item]
        for candidate in candidates:
            target = patterns if bullet.startswith(f"`{candidate}`") else interface_only
            previous = target.get(candidate)
            if previous is not None and previous != current_owner:
                _blocked(
                    "ambiguous_file_ownership",
                    "ownership pattern has more than one normalized owner",
                    pattern=candidate,
                    owners=[previous, current_owner],
                )
            target[candidate] = current_owner
    if not patterns:
        _blocked(
            "file_ownership_invalid",
            "natural-language program has no path ownership patterns",
            heading="File Ownership Map",
        )
    return patterns, interface_only


def _natural_program_contract(
    document: InputDocument,
    plans: Mapping[str, tuple[InputDocument, dict[str, object]]],
) -> dict[str, object]:
    """Parse the reviewed Canvas-style program tables without heuristic ordering."""

    text = document.content.decode("utf-8")
    order_section = _markdown_section(text, "Authoritative Execution Order")
    by_name = {item.path.name: plan_id for plan_id, (item, _) in plans.items()}
    staged: list[tuple[int, str]] = []
    for line in order_section.splitlines():
        match = re.match(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|", line)
        if not match:
            continue
        source_name = match.group(2)
        if source_name not in by_name:
            _blocked(
                "plan_order_invalid",
                "program order references a missing implementation plan",
                source_path=source_name,
            )
        staged.append((int(match.group(1)), by_name[source_name]))
    if not staged or [stage for stage, _ in staged] != list(range(1, len(staged) + 1)):
        _blocked(
            "plan_order_invalid",
            "program stage table must be contiguous and start at one",
            stages=[stage for stage, _ in staged],
        )
    plan_order = [plan_id for _, plan_id in staged]

    aliases: dict[str, str] = {}
    for plan_id, (plan_document, _) in plans.items():
        alias = _stage_alias(plan_document)
        if alias is None:
            continue
        if alias in aliases and aliases[alias] != plan_id:
            _blocked(
                "stage_alias_ambiguous",
                "normalized natural-program stage aliases must be unique",
                stage_alias=alias,
                plan_ids=[aliases[alias], plan_id],
            )
        aliases[alias] = plan_id
    coverage_section = _markdown_section(text, "Spec Coverage Map")
    ownership_section = _markdown_section(text, "File Ownership Map")
    coverage: dict[str, list[str]] = {}
    for line in coverage_section.splitlines():
        if not line.startswith("|") or re.match(r"^\|[- |]+$", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0] == "Design sections":
            continue
        owner_aliases = re.findall(r"\b([A-C]\d)\b", cells[1], re.I)
        owner_aliases.extend(re.findall(r"\bWave\s+(\d+)\b", cells[1], re.I))
        owner_ids = list(dict.fromkeys(aliases.get(alias.upper()) for alias in owner_aliases))
        if not owner_ids or any(owner is None for owner in owner_ids):
            _blocked(
                "missing_spec_coverage",
                "program coverage owner cannot be resolved to a plan",
                spec_section=cells[0],
                owner=cells[1],
            )
        coverage[cells[0]] = [
            str(QualifiedTaskId(owner, str(task.get("task_id") or task.get("id"))))
            for owner in owner_ids
            for task in plans[owner][1]["tasks"]
        ]

    ownership_patterns, interface_only_rules = _natural_ownership_rules(
        ownership_section, aliases
    )
    claimed: dict[str, list[str]] = defaultdict(list)
    task_interfaces: dict[str, bool] = {}
    for plan_id in plan_order:
        for task in plans[plan_id][1]["tasks"]:
            task_id = str(QualifiedTaskId(plan_id, str(task.get("task_id") or task.get("id"))))
            task_interfaces[task_id] = task.get("interface_declared") is True
            for path in task.get("file_claims", []):
                claimed[str(path)].append(task_id)
    interface_writers: dict[str, list[str]] = defaultdict(list)
    for pattern, owner_plan in ownership_patterns.items():
        matching_paths = [path for path in claimed if _path_matches_pattern(path, pattern)]
        owner_claims = [
            writer
            for path in matching_paths
            for writer in claimed[path]
            if writer.startswith(owner_plan + "::")
        ]
        if not owner_claims:
            _blocked(
                "file_ownership_invalid",
                "ownership pattern must match a claim by its owning plan",
                pattern=pattern,
                owner_plan=owner_plan,
            )
        for path in matching_paths:
            for writer in claimed[path]:
                if writer.startswith(owner_plan + "::"):
                    continue
                if not task_interfaces.get(writer, False):
                    _blocked(
                        "interface_contract_missing",
                        "non-owner file claim must declare an explicit task interface",
                        pattern=pattern,
                        path=path,
                        writer=writer,
                        owner_plan=owner_plan,
                    )
                interface_writers[path].append(writer)
    for pattern, interface_plan in interface_only_rules.items():
        matching = [
            writer
            for path, writers in claimed.items()
            if _path_matches_pattern(path, pattern)
            for writer in writers
            if writer.startswith(interface_plan + "::") and task_interfaces.get(writer, False)
        ]
        if not matching:
            _blocked(
                "interface_contract_missing",
                "interface-only path rule must match a declared task interface",
                pattern=pattern,
                interface_plan=interface_plan,
            )
        for path, writers in claimed.items():
            if _path_matches_pattern(path, pattern):
                interface_writers[path].extend(writer for writer in writers if writer in matching)
    ownership = {
        path: list(dict.fromkeys(writers))
        for path, writers in claimed.items()
        if len({writer.split("::", 1)[0] for writer in writers}) > 1
    }
    if ownership and not re.search(
        r"A new wave may change an existing owner only through an interface explicitly named in that wave's plan\.",
        ownership_section,
    ):
        _blocked(
            "ambiguous_file_ownership",
            "natural-language program does not authorize its repeated file claims",
            paths=sorted(ownership),
        )

    final_plan = plan_order[-1]
    if _stage_alias(plans[final_plan][0]) != "6" or not re.search(
        r"Wave 6 remains the only final evidence gate", text, re.I
    ):
        _blocked(
            "global_gate_missing",
            "natural-language program must identify final Wave 6 as its only gate",
            final_plan=final_plan,
        )
    final_tasks = plans[final_plan][1]["tasks"]
    final_task_id = str(final_tasks[-1].get("task_id") or final_tasks[-1].get("id"))
    return {
        "plan_order": plan_order,
        "required_spec_sections": list(coverage),
        "spec_coverage": coverage,
        "cross_plan_dependencies": [],
        "file_ownership": ownership,
        "ownership_transfers": [
            {"path": path, "from": first, "to": second}
            for path, writers in ownership.items()
            if path not in interface_writers
            for first, second in zip(writers, writers[1:])
        ],
        "shared_interfaces": [
            path
            for path in ownership
            if path in interface_writers
        ],
        "file_ownership_patterns": ownership_patterns,
        "file_interface_writers": {
            path: list(dict.fromkeys(writers))
            for path, writers in interface_writers.items()
        },
        "global_integration_gate": str(QualifiedTaskId(final_plan, final_task_id)),
    }


def _spec_section_hashes(document: InputDocument | None) -> dict[str, str]:
    if document is None:
        return {}
    lines = document.content.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(rb"^(#{2,6})[ \t]+(S\d+(?:\.\d+)*)\b", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).decode("ascii")))
    hashes: dict[str, str] = {}
    for offset, (start, level, section_id) in enumerate(headings):
        if section_id in hashes:
            _blocked(
                "spec_section_ambiguous",
                "specification section IDs must be unique",
                spec_section=section_id,
            )
        end = len(lines)
        for next_start, next_level, _ in headings[offset + 1 :]:
            if next_level <= level:
                end = next_start
                break
        canonical_section = b"".join(lines[start:end]).rstrip(b"\r\n") + b"\n"
        hashes[section_id] = hashlib.sha256(canonical_section).hexdigest()
    return hashes


def _qualified(reference: object, current_plan: str) -> str:
    value = str(reference).strip()
    if not value:
        _blocked("contract_invalid", "task reference must not be empty", plan_id=current_plan)
    if "::" in value:
        return value
    task_number = re.fullmatch(r"(?:T|Task[ _]?)(\d+(?:\.\d+)*)", value, re.IGNORECASE)
    if task_number:
        value = "task_" + task_number.group(1).replace(".", "_")
    return str(QualifiedTaskId(current_plan, value))


def _cycle(tasks: Mapping[str, object], edges: set[tuple[str, str]]) -> tuple[str, ...] | None:
    incoming: dict[str, int] = {task_id: 0 for task_id in tasks}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for dependency, dependent in edges:
        incoming[dependent] += 1
        outgoing[dependency].append(dependent)
    pending = deque(task_id for task_id in tasks if incoming[task_id] == 0)
    visited: list[str] = []
    while pending:
        node = pending.popleft()
        visited.append(node)
        for dependent in outgoing[node]:
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                pending.append(dependent)
    if len(visited) == len(tasks):
        return None
    return tuple(task_id for task_id, count in incoming.items() if count)


def _roots_and_sinks(
    plan_id: str,
    task_order: tuple[str, ...],
    edges: set[tuple[str, str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    members = tuple(task for task in task_order if task.startswith(plan_id + "::"))
    member_set = set(members)
    roots = tuple(task for task in members if not any(end == task and start in member_set for start, end in edges))
    sinks = tuple(task for task in members if not any(start == task and end in member_set for start, end in edges))
    return roots, sinks


def compile_plan_graph(document_set: DocumentSet) -> PlanGraph:
    """Compile one immutable graph from the exact bytes in ``document_set``."""

    specs = [item for item in document_set.documents if item.kind == "spec"]
    programs = [item for item in document_set.documents if item.kind == "program"]
    plan_documents = [item for item in document_set.documents if item.kind == "plan"]
    if len(specs) > 1 or len(programs) > 1 or not plan_documents:
        _blocked(
            "document_shape_invalid",
            "a graph accepts at most one spec/program and at least one plan",
            spec_count=len(specs),
            program_count=len(programs),
            plan_count=len(plan_documents),
        )

    parsed_plans: dict[str, tuple[InputDocument, dict[str, object]]] = {}
    input_order: list[str] = []
    for document in plan_documents:
        contract = _json_contract(document, "cpe-plan") or _fallback_plan_contract(document)
        plan_id = str(contract.get("plan_id") or _document_plan_id(document)).strip()
        if not plan_id or "::" in plan_id:
            _blocked(
                "plan_id_invalid",
                "plan ID must be non-empty and cannot contain the task separator",
                document_id=document.document_id,
                plan_id=plan_id,
            )
        if plan_id in parsed_plans:
            _blocked(
                "duplicate_plan_id",
                "plan IDs must be unique",
                plan_id=plan_id,
                first_document_id=parsed_plans[plan_id][0].document_id,
                duplicate_document_id=document.document_id,
            )
        parsed_plans[plan_id] = (document, contract)
        input_order.append(plan_id)

    program_contract = _json_contract(programs[0], "cpe-program") if programs else None
    if programs and program_contract is None:
        program_contract = _natural_program_contract(programs[0], parsed_plans)
    if program_contract is not None and "tasks" in program_contract:
        _blocked(
            "program_redefines_task",
            "program plans coordinate task references but cannot define executable tasks",
            document_id=programs[0].document_id,
        )
    if program_contract is not None:
        plan_order = tuple(
            str(item) for item in _list(
                program_contract.get("plan_order"),
                field="plan_order",
                document_id=programs[0].document_id,
            )
        )
        if len(plan_order) != len(set(plan_order)) or set(plan_order) != set(input_order):
            _blocked(
                "plan_order_invalid",
                "program order must name every implementation plan exactly once",
                declared=list(plan_order),
                actual=input_order,
            )
    else:
        plan_order = tuple(input_order)

    task_records: dict[str, dict[str, object]] = {}
    edges: set[tuple[str, str]] = set()
    plan_tasks: dict[str, tuple[str, ...]] = {}
    for plan_id in plan_order:
        document, contract = parsed_plans[plan_id]
        raw_tasks = _list(contract.get("tasks"), field="tasks", document_id=document.document_id)
        local_ids: set[str] = set()
        ordered: list[str] = []
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                _blocked(
                    "contract_invalid",
                    "plan tasks must be objects",
                    document_id=document.document_id,
                    task=raw,
                )
            task_id = str(raw.get("task_id") or raw.get("id") or "").strip()
            if not task_id or "::" in task_id:
                _blocked(
                    "task_id_invalid",
                    "local task ID must be non-empty and unqualified",
                    plan_id=plan_id,
                    task_id=task_id,
                )
            if task_id in local_ids:
                _blocked(
                    "duplicate_task_id",
                    "task IDs must be unique within a plan",
                    plan_id=plan_id,
                    task_id=task_id,
                )
            local_ids.add(task_id)
            qualified = str(QualifiedTaskId(plan_id, task_id))
            dependencies = tuple(
                _qualified(item, plan_id)
                for item in _list(
                    raw.get("dependencies", []),
                    field="dependencies",
                    document_id=document.document_id,
                )
            )
            refs = tuple(
                str(item)
                for item in _list(
                    raw.get("spec_refs", []),
                    field="spec_refs",
                    document_id=document.document_id,
                )
            )
            claims = tuple(
                str(item)
                for item in _list(
                    raw.get("file_claims", []),
                    field="file_claims",
                    document_id=document.document_id,
                )
            )
            canonical_source = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
            task_records[qualified] = {
                "id": qualified,
                "plan_id": plan_id,
                "task_id": task_id,
                "plan_document_id": document.document_id,
                "dependencies": dependencies,
                "spec_refs": refs,
                "file_claims": claims,
                "interface_declared": raw.get("interface_declared") is True,
                "task_source_sha256": hashlib.sha256(canonical_source).hexdigest(),
            }
            ordered.append(qualified)
        if not ordered:
            _blocked("plan_tasks_missing", "implementation plan has no tasks", plan_id=plan_id)
        plan_tasks[plan_id] = tuple(ordered)

    plan_position = {plan_id: index for index, plan_id in enumerate(plan_order)}
    for task_id, task in task_records.items():
        for dependency in task["dependencies"]:
            if dependency not in task_records:
                _blocked(
                    "orphan_task",
                    "task dependency does not resolve to a qualified task",
                    task_id=task_id,
                    dependency=dependency,
                )
            dependency_plan = str(task_records[dependency]["plan_id"])
            task_plan = str(task["plan_id"])
            if plan_position[dependency_plan] > plan_position[task_plan]:
                _blocked(
                    "plan_order_conflict",
                    "explicit dependency contradicts authoritative plan order",
                    task_id=task_id,
                    dependency=dependency,
                )
            edges.add((dependency, task_id))

    # Program order and no-program repeated argument order are both conservative.
    for previous, current in zip(plan_order, plan_order[1:]):
        _, previous_sinks = _roots_and_sinks(previous, tuple(task_records), edges)
        current_roots, _ = _roots_and_sinks(current, tuple(task_records), edges)
        edges.update((sink, root) for sink in previous_sinks for root in current_roots)

    if program_contract is not None:
        raw_cross = _list(
            program_contract.get("cross_plan_dependencies", []),
            field="cross_plan_dependencies",
            document_id=programs[0].document_id,
        )
        for entry in raw_cross:
            if isinstance(entry, dict):
                dependency = str(entry.get("from") or "")
                dependent = str(entry.get("to") or "")
            elif isinstance(entry, list) and len(entry) == 2:
                dependency, dependent = map(str, entry)
            else:
                _blocked("contract_invalid", "cross-plan edge must name from and to", edge=entry)
            if dependency not in task_records or dependent not in task_records:
                _blocked(
                    "orphan_task",
                    "cross-plan dependency references an unknown task",
                    dependency=dependency,
                    dependent=dependent,
                )
            edges.add((dependency, dependent))

    cycle = _cycle(task_records, edges)
    if cycle:
        _blocked("dependency_cycle", "plan graph contains a dependency cycle", tasks=list(cycle))

    raw_coverage = program_contract.get("spec_coverage", {}) if program_contract else {}
    if not isinstance(raw_coverage, dict):
        _blocked("contract_invalid", "spec_coverage must be an object", field="spec_coverage")
    coverage: dict[str, tuple[str, ...]] = {}
    if program_contract is not None:
        for section, references in raw_coverage.items():
            qualified_refs = tuple(
                str(item)
                for item in _list(
                    references,
                    field=f"spec_coverage.{section}",
                    document_id=programs[0].document_id,
                )
            )
            unknown = [item for item in qualified_refs if item not in task_records]
            if unknown:
                _blocked(
                    "orphan_task",
                    "spec coverage references unknown tasks",
                    spec_section=str(section),
                    task_ids=unknown,
                )
            coverage[str(section)] = qualified_refs
        required = tuple(
            str(item)
            for item in _list(
                program_contract.get("required_spec_sections", []),
                field="required_spec_sections",
                document_id=programs[0].document_id,
            )
        )
    else:
        aggregate: dict[str, list[str]] = defaultdict(list)
        for task_id, task in task_records.items():
            for section in task["spec_refs"]:
                aggregate[str(section)].append(task_id)
        coverage = {section: tuple(task_ids) for section, task_ids in aggregate.items()}
        required = tuple(coverage)
    missing = sorted(section for section in required if not coverage.get(section))
    if missing:
        _blocked(
            "missing_spec_coverage",
            "required specification sections need executable owners",
            missing_sections=missing,
        )

    claimed: dict[str, list[str]] = defaultdict(list)
    for task_id, task in task_records.items():
        for path in task["file_claims"]:
            claimed[str(path)].append(task_id)
    raw_patterns = program_contract.get("file_ownership_patterns", {}) if program_contract else {}
    if not isinstance(raw_patterns, dict):
        _blocked(
            "contract_invalid",
            "file_ownership_patterns must be an object",
            field="file_ownership_patterns",
        )
    ownership_patterns = {str(pattern): str(owner) for pattern, owner in raw_patterns.items()}
    matched_pattern_owners: dict[str, str] = {}
    for pattern, owner_plan in ownership_patterns.items():
        if owner_plan not in plan_order:
            _blocked(
                "file_ownership_invalid",
                "ownership pattern references an unknown plan",
                pattern=pattern,
                owner_plan=owner_plan,
            )
        matching_paths = [path for path in claimed if _path_matches_pattern(path, pattern)]
        if not any(
            writer.startswith(owner_plan + "::")
            for path in matching_paths
            for writer in claimed[path]
        ):
            _blocked(
                "file_ownership_invalid",
                "ownership pattern must match an actual writer in its owning plan",
                pattern=pattern,
                owner_plan=owner_plan,
            )
        for path in matching_paths:
            previous = matched_pattern_owners.get(path)
            if previous is not None and previous != owner_plan:
                _blocked(
                    "ambiguous_file_ownership",
                    "concrete path matches ownership patterns with different owners",
                    path=path,
                    owners=[previous, owner_plan],
                )
            matched_pattern_owners[path] = owner_plan
    raw_interface_writers = (
        program_contract.get("file_interface_writers", {}) if program_contract else {}
    )
    if not isinstance(raw_interface_writers, dict):
        _blocked(
            "contract_invalid",
            "file_interface_writers must be an object",
            field="file_interface_writers",
        )
    interface_writers: dict[str, tuple[str, ...]] = {}
    for path, raw_writers in raw_interface_writers.items():
        if not isinstance(raw_writers, list) or str(path) not in claimed:
            _blocked(
                "interface_contract_missing",
                "interface writers must be a list for one actually claimed path",
                path=str(path),
            )
        writers = tuple(str(writer) for writer in raw_writers)
        if (
            not writers
            or len(writers) != len(set(writers))
            or any(writer not in claimed[str(path)] for writer in writers)
            or any(task_records[writer].get("interface_declared") is not True for writer in writers)
        ):
            _blocked(
                "interface_contract_missing",
                "interface writers must be unique actual writers with declared interfaces",
                path=str(path),
                writers=list(writers),
                actual_writers=claimed[str(path)],
            )
        interface_writers[str(path)] = writers
    for path, owner_plan in matched_pattern_owners.items():
        missing_interface_writers = [
            writer
            for writer in claimed[path]
            if not writer.startswith(owner_plan + "::")
            and writer not in interface_writers.get(path, ())
        ]
        if missing_interface_writers:
            _blocked(
                "interface_contract_missing",
                "non-owner pattern writers require an explicit interface binding",
                path=path,
                owner_plan=owner_plan,
                writers=missing_interface_writers,
            )
    declared_ownership = program_contract.get("file_ownership", {}) if program_contract else {}
    if not isinstance(declared_ownership, dict):
        _blocked("contract_invalid", "file_ownership must be an object", field="file_ownership")
    undeclared_paths = sorted(set(declared_ownership) - set(claimed))
    if undeclared_paths:
        _blocked(
            "ambiguous_file_ownership",
            "file ownership can name only claimed paths",
            paths=undeclared_paths,
        )
    raw_transfers = program_contract.get("ownership_transfers", []) if program_contract else []
    transfers: set[tuple[str, str, str]] = set()
    for entry in _list(
        raw_transfers,
        field="ownership_transfers",
        document_id=programs[0].document_id if programs else "fallback",
    ):
        if not isinstance(entry, dict):
            _blocked("contract_invalid", "ownership transfer must be an object", transfer=entry)
        transfer = (str(entry.get("path")), str(entry.get("from")), str(entry.get("to")))
        if transfer[0] not in claimed:
            _blocked(
                "ambiguous_file_ownership",
                "ownership transfer can name only a claimed path",
                transfer=list(transfer),
            )
        transfers.add(transfer)
    raw_shared = program_contract.get("shared_interfaces", []) if program_contract else []
    shared_interfaces = {
        str(item)
        for item in _list(
            raw_shared,
            field="shared_interfaces",
            document_id=programs[0].document_id if programs else "fallback",
        )
    }
    invalid_shared = sorted(shared_interfaces - set(claimed))
    if invalid_shared:
        _blocked(
            "ambiguous_file_ownership",
            "shared interfaces can name only claimed paths",
            paths=invalid_shared,
        )
    for path, first, second in transfers:
        actual_writers = set(claimed[path])
        if first not in actual_writers or second not in actual_writers or first == second:
            _blocked(
                "ambiguous_file_ownership",
                "ownership transfer endpoints must be distinct actual writers",
                path=path,
                transfer=[first, second],
                writers=claimed[path],
            )
    ownership: dict[str, tuple[str, ...]] = {}
    for path, writers in claimed.items():
        writer_plans = {str(task_records[writer]["plan_id"]) for writer in writers}
        raw_owners = declared_ownership.get(path)
        if raw_owners is not None and not isinstance(raw_owners, list):
            _blocked(
                "ambiguous_file_ownership",
                "file ownership entry must be an ordered writer list",
                path=path,
                declared=raw_owners,
            )
        owners = tuple(str(item) for item in raw_owners) if raw_owners is not None else tuple(writers)
        if (
            len(owners) != len(set(owners))
            or set(owners) != set(writers)
            or (len(writer_plans) > 1 and raw_owners is None)
        ):
            _blocked(
                "ambiguous_file_ownership",
                "declared ownership must exactly order every actual writer",
                path=path,
                writers=writers,
                declared=list(owners),
            )
        if path in shared_interfaces and len(writer_plans) < 2:
            _blocked(
                "ambiguous_file_ownership",
                "shared interface requires writers from at least two plans",
                path=path,
                writers=writers,
            )
        required_transfers = {(path, first, second) for first, second in zip(owners, owners[1:])}
        declared_transfers = {transfer for transfer in transfers if transfer[0] == path}
        if path in shared_interfaces:
            unexpected = declared_transfers - required_transfers
            if unexpected:
                _blocked(
                    "ambiguous_file_ownership",
                    "shared-interface transfer does not follow writer order",
                    path=path,
                    transfers=[list(item[1:]) for item in sorted(unexpected)],
                )
        elif len(writer_plans) > 1 and declared_transfers != required_transfers:
            _blocked(
                "ambiguous_file_ownership",
                "cross-plan writers need exactly the adjacent ownership transfers",
                path=path,
                required=[list(item[1:]) for item in sorted(required_transfers)],
                declared=[list(item[1:]) for item in sorted(declared_transfers)],
            )
        elif len(writer_plans) == 1 and declared_transfers:
            _blocked(
                "ambiguous_file_ownership",
                "single-plan ownership cannot declare a transfer",
                path=path,
                transfers=[list(item[1:]) for item in sorted(declared_transfers)],
            )
        edges.update((first, second) for first, second in zip(owners, owners[1:]))
        ownership[path] = owners

    if len(plan_order) > 1 and program_contract is not None:
        raw_gate = program_contract.get("global_integration_gate")
        if not isinstance(raw_gate, str) or not raw_gate:
            _blocked(
                "global_gate_missing",
                "multi-plan programs require one final integration gate",
                plan_count=len(plan_order),
            )
        gate_id = raw_gate
    elif program_contract is not None and isinstance(program_contract.get("global_integration_gate"), str):
        gate_id = str(program_contract["global_integration_gate"])
    else:
        gate_id = plan_tasks[plan_order[-1]][-1]
    if gate_id not in task_records:
        _blocked(
            "global_gate_invalid",
            "global integration gate must reference an executable task",
            task_id=gate_id,
        )
    gate_plan = str(task_records[gate_id]["plan_id"])
    if gate_plan != plan_order[-1]:
        _blocked(
            "global_gate_invalid",
            "global integration gate must belong to the final plan",
            task_id=gate_id,
            final_plan=plan_order[-1],
        )
    _, gate_plan_sinks = _roots_and_sinks(gate_plan, tuple(task_records), edges)
    edges.update((sink, gate_id) for sink in gate_plan_sinks if sink != gate_id)

    cycle = _cycle(task_records, edges)
    if cycle:
        _blocked("dependency_cycle", "plan graph contains a dependency cycle", tasks=list(cycle))

    checkpoints = {
        plan_id: _roots_and_sinks(plan_id, tuple(task_records), edges)[1]
        for plan_id in plan_order
    }
    gate = IntegrationGate(
        plan_id=gate_plan,
        task_id=str(task_records[gate_id]["task_id"]),
        qualified_task_id=gate_id,
    )
    document_hashes = {item.document_id: item.sha256 for item in document_set.documents}
    spec_section_hashes = _spec_section_hashes(specs[0] if specs else None)
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "spec_document_id": specs[0].document_id if specs else None,
        "program_document_id": programs[0].document_id if programs else None,
        "plan_documents": [parsed_plans[plan_id][0].document_id for plan_id in plan_order],
        "plan_ids": list(plan_order),
        "document_hashes": document_hashes,
        "spec_section_hashes": spec_section_hashes,
        "tasks": task_records,
        "edges": sorted(edges),
        "spec_coverage": coverage,
        "file_ownership": ownership,
        "file_ownership_patterns": ownership_patterns,
        "file_interface_writers": interface_writers,
        "plan_checkpoints": checkpoints,
        "global_integration_gate": dict(gate),
    }
    graph_sha256 = hashlib.sha256(
        json.dumps(_plain(canonical), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return PlanGraph(
        schema_version=SCHEMA_VERSION,
        spec_document_id=specs[0].document_id if specs else None,
        program_document_id=programs[0].document_id if programs else None,
        plan_documents=tuple(canonical["plan_documents"]),
        plan_ids=plan_order,
        document_hashes=_freeze(document_hashes),
        spec_section_hashes=_freeze(spec_section_hashes),
        tasks=_freeze(task_records),
        edges=tuple(sorted(edges)),
        spec_coverage=_freeze(coverage),
        file_ownership=_freeze(ownership),
        file_ownership_patterns=_freeze(ownership_patterns),
        file_interface_writers=_freeze(interface_writers),
        plan_checkpoints=_freeze(checkpoints),
        global_integration_gate=gate,
        graph_sha256=graph_sha256,
    )


def invalidated_nodes(old: PlanGraph, new: PlanGraph) -> tuple[str, ...]:
    """Return changed executable nodes plus only their new-graph downstream closure."""

    seeds: set[str] = set()
    for task_id in set(old.tasks) | set(new.tasks):
        if task_id not in old.tasks or task_id not in new.tasks:
            if task_id in new.tasks:
                seeds.add(task_id)
            continue
        if old.tasks[task_id].get("task_source_sha256") != new.tasks[task_id].get(
            "task_source_sha256"
        ):
            seeds.add(task_id)
    changed_edges = set(old.edges) ^ set(new.edges)
    seeds.update(node for edge in changed_edges for node in edge if node in new.tasks)
    for section in set(old.spec_coverage) | set(new.spec_coverage):
        if old.spec_coverage.get(section) != new.spec_coverage.get(section):
            seeds.update(new.spec_coverage.get(section, ()))
    for path in set(old.file_ownership) | set(new.file_ownership):
        if old.file_ownership.get(path) != new.file_ownership.get(path):
            seeds.update(new.file_ownership.get(path, ()))
    if old.global_integration_gate != new.global_integration_gate:
        seeds.add(new.global_integration_gate.qualified_task_id)
    changed_sections = {
        section
        for section in set(old.spec_section_hashes) | set(new.spec_section_hashes)
        if old.spec_section_hashes.get(section) != new.spec_section_hashes.get(section)
    }
    all_covered_tasks = {
        task
        for graph in (old, new)
        for task_ids in graph.spec_coverage.values()
        for task in task_ids
        if task in new.tasks
    }
    for section in changed_sections:
        related = {
            task
            for graph in (old, new)
            for task in graph.spec_coverage.get(section, ())
            if task in new.tasks
        }
        seeds.update(related or all_covered_tasks)
    old_spec_binding = (
        old.spec_document_id,
        old.document_hashes.get(old.spec_document_id) if old.spec_document_id else None,
    )
    new_spec_binding = (
        new.spec_document_id,
        new.document_hashes.get(new.spec_document_id) if new.spec_document_id else None,
    )
    if old_spec_binding != new_spec_binding and not changed_sections:
        seeds.update(all_covered_tasks)
    affected: set[str] = set()
    for seed in seeds:
        affected.update(new.downstream_of(seed))
    return tuple(task_id for task_id in new.tasks if task_id in affected)
