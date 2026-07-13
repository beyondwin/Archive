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
    tasks: Mapping[str, Mapping[str, object]]
    edges: tuple[tuple[str, str], ...]
    spec_coverage: Mapping[str, tuple[str, ...]]
    file_ownership: Mapping[str, tuple[str, ...]]
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
        dependencies = _inline_yaml_list(yaml_body, "dependencies")
        spec_refs = _inline_yaml_list(yaml_body, "spec_refs") or SPEC_REF_RE.findall(body)
        file_claims = _yaml_block_list(yaml_body, "file_claims")
        task_id = "task_" + match.group("number").replace(".", "_")
        tasks.append(
            {
                "task_id": task_id,
                "dependencies": dependencies,
                "spec_refs": list(dict.fromkeys(spec_refs)),
                "file_claims": file_claims,
                "source_token": hashlib.sha256(
                    text[match.start() : end].encode("utf-8")
                ).hexdigest(),
            }
        )
    return {"plan_id": _document_plan_id(document), "tasks": tasks}


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
        _blocked(
            "program_contract_missing",
            "a program document must declare cross-plan authority",
            document_id=programs[0].document_id,
        )
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
    ownership: dict[str, tuple[str, ...]] = {}
    for path, writers in claimed.items():
        writer_plans = {str(task_records[writer]["plan_id"]) for writer in writers}
        if len(writer_plans) == 1:
            ownership[path] = tuple(writers)
            continue
        raw_owners = declared_ownership.get(path)
        owners = tuple(str(item) for item in raw_owners) if isinstance(raw_owners, list) else ()
        if len(owners) != len(set(owners)) or set(owners) != set(writers):
            _blocked(
                "ambiguous_file_ownership",
                "cross-plan writers need one exact ownership order",
                path=path,
                writers=writers,
                declared=list(owners),
            )
        if path not in shared_interfaces:
            missing_transfers = [
                [first, second]
                for first, second in zip(owners, owners[1:])
                if (path, first, second) not in transfers
            ]
            if missing_transfers:
                _blocked(
                    "ambiguous_file_ownership",
                    "cross-plan writers need explicit ownership transfers",
                    path=path,
                    missing_transfers=missing_transfers,
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
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "spec_document_id": specs[0].document_id if specs else None,
        "program_document_id": programs[0].document_id if programs else None,
        "plan_documents": [parsed_plans[plan_id][0].document_id for plan_id in plan_order],
        "plan_ids": list(plan_order),
        "document_hashes": document_hashes,
        "tasks": task_records,
        "edges": sorted(edges),
        "spec_coverage": coverage,
        "file_ownership": ownership,
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
        tasks=_freeze(task_records),
        edges=tuple(sorted(edges)),
        spec_coverage=_freeze(coverage),
        file_ownership=_freeze(ownership),
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
    if old.spec_document_id and new.spec_document_id:
        if old.document_hashes.get(old.spec_document_id) != new.document_hashes.get(
            new.spec_document_id
        ):
            seeds.update(task for tasks in new.spec_coverage.values() for task in tasks)
    affected: set[str] = set()
    for seed in seeds:
        affected.update(new.downstream_of(seed))
    return tuple(task_id for task_id in new.tasks if task_id in affected)
