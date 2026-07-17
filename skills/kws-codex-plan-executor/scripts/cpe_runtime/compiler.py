"""Source-bound compiled run index preparation and validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .state import StateStore, atomic_private_write

MAX_COMPILER_INPUT_BYTES = 512 * 1024
MAX_COMPILER_OUTPUT_BYTES = 1024 * 1024
SAFETY_UNKNOWN_PREFIXES = (
    "workspace:", "repository:", "source_commit:", "plan_order:", "remote_policy:",
)
CompilerCallback = Callable[[StateStore, dict[str, object], bool], dict[str, object]]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def default_operator_contract(state: dict[str, Any]) -> dict[str, object]:
    return {
        "workspace": state["source_repository"],
        "source_commit": state["source_commit"],
        "plan_ids": [plan["plan_id"] for plan in state["plans"]],
        "completion_scope": "cpe_branch_completed",
        "remote_policy": "forbidden",
        "merge_policy": "external_finisher_only",
    }


def compiler_cache_key(state: dict[str, Any], contract: dict[str, object]) -> str:
    return _sha256(_canonical({
        "format_version": 2,
        "input_sha256": [record["sha256"] for record in state["inputs"]],
        "operator_contract": contract,
        "compiler_schema_version": 1,
        "cpe_version": "2.0",
    }))


def _source_lines(record: dict[str, Any]) -> list[str]:
    return Path(record["snapshot_path"]).read_text(encoding="utf-8").splitlines(keepends=True)


def _validate_span(item: dict[str, Any], lines: list[str], label: str) -> None:
    start, end = item.get("source_line_start"), item.get("source_line_end")
    if (not isinstance(start, int) or isinstance(start, bool) or
            not isinstance(end, int) or isinstance(end, bool) or
            not 1 <= start <= end <= len(lines)):
        raise ValueError(f"compiled {label} span is invalid")
    selected = "".join(lines[start - 1:end]).encode("utf-8")
    if _sha256(selected) != item.get("source_text_sha256"):
        raise ValueError(f"compiled {label} span digest is invalid")


def validate_compiled_index(payload: dict[str, Any], state: dict[str, Any], contract: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("format_version") != 2:
        raise ValueError("compiled index format is invalid")
    if set(payload) != {"format_version", "cache_key", "plans"}:
        raise ValueError("compiled index fields are invalid")
    if payload.get("cache_key") != compiler_cache_key(state, contract):
        raise ValueError("compiled index cache key is invalid")
    plan_inputs = [record for record in state["inputs"] if record["role"] == "plan"]
    plans = payload.get("plans")
    if not isinstance(plans, list) or len(plans) != len(plan_inputs):
        raise ValueError("compiled plan count is invalid")
    for expected_order, (compiled, record) in enumerate(zip(plans, plan_inputs, strict=True)):
        if not isinstance(compiled, dict) or compiled.get("plan_id") != f"plan-{expected_order + 1:02d}":
            raise ValueError("compiled plan order is invalid")
        required_plan_fields = {
            "plan_id", "source_sha256", "byte_length", "line_count", "tasks",
            "verifications", "capabilities", "coordination_exceptions",
            "execution_advisories", "unknowns",
        }
        if set(compiled) != required_plan_fields:
            raise ValueError("compiled plan fields are invalid")
        if compiled.get("source_sha256") != record["sha256"]:
            raise ValueError("compiled plan source digest is invalid")
        lines = _source_lines(record)
        if compiled.get("byte_length") != record["byte_length"] or compiled.get("line_count") != len(lines):
            raise ValueError("compiled plan source metadata is invalid")
        tasks = compiled["tasks"]
        if not isinstance(tasks, list):
            raise ValueError("compiled tasks are invalid")
        for order, task in enumerate(tasks):
            if not isinstance(task, dict) or task.get("order") != order:
                raise ValueError("compiled task order is invalid")
            _validate_span(task, lines, "source")
        verifications = compiled["verifications"]
        if not isinstance(verifications, list):
            raise ValueError("compiled verifications are invalid")
        command_ids = [item.get("command_id") for item in verifications if isinstance(item, dict)]
        if len(command_ids) != len(verifications) or len(command_ids) != len(set(command_ids)):
            raise ValueError("compiled verification command IDs are invalid")
        for verification in verifications:
            _validate_span(verification, lines, "verification source")
        exceptions = compiled["coordination_exceptions"]
        if not isinstance(exceptions, list):
            raise ValueError("compiled coordination exceptions are invalid")
        for exception in exceptions:
            if not isinstance(exception, dict) or exception.get("fork_turns") != "all":
                raise ValueError("compiled coordination exception is invalid")
            _validate_span(exception, lines, "coordination exception source")
        unknowns = compiled.get("unknowns", [])
        if not isinstance(unknowns, list) or not all(isinstance(item, str) for item in unknowns):
            raise ValueError("compiled unknowns are invalid")
        if any(item.startswith(SAFETY_UNKNOWN_PREFIXES) for item in unknowns):
            raise ValueError("compiled safety field is ambiguous")
        advisories = compiled["execution_advisories"]
        if not isinstance(advisories, list) or any(item not in {
            "split_or_checkpoint_required", "handoff_to_waygent",
        } for item in advisories):
            raise ValueError("compiled execution advisories are invalid")
    return payload


class CompiledIndexService:
    def __init__(self, *, compile_once: CompilerCallback) -> None:
        self.compile_once = compile_once
        self.compile_calls = 0

    def prepare(self, store: StateStore) -> Path:
        contract = default_operator_contract(store.state)
        contract_bytes = _canonical(contract)
        contract_path = store.root / "operator-contract.json"
        atomic_private_write(contract_path, contract_bytes)
        store.state["operator_contract_path"] = str(contract_path.resolve())
        store.state["operator_contract_sha256"] = _sha256(contract_bytes)
        target = store.root / "compiled-run-index.json"
        if target.is_file():
            cached = json.loads(target.read_text(encoding="utf-8"))
            validate_compiled_index(cached, store.state, contract)
            store.state["compiled_run_index_path"] = str(target.resolve())
            store.state["compiled_run_index_sha256"] = _sha256(target.read_bytes())
            store.save()
            return target.resolve()
        input_bytes = sum(record["byte_length"] for record in store.state["inputs"]) + len(contract_bytes)
        if input_bytes > MAX_COMPILER_INPUT_BYTES:
            raise ValueError("compiler input exceeds size limit")
        last_error: ValueError | None = None
        for repair in (False, True):
            self.compile_calls += 1
            candidate = self.compile_once(store, contract, repair)
            try:
                validated = validate_compiled_index(candidate, store.state, contract)
                break
            except ValueError as exc:
                last_error = exc
        else:
            assert last_error is not None
            raise last_error
        encoded = _canonical(validated)
        if len(encoded) > MAX_COMPILER_OUTPUT_BYTES:
            raise ValueError("compiled index exceeds size limit")
        atomic_private_write(target, encoded)
        store.state["compiled_run_index_path"] = str(target.resolve())
        store.state["compiled_run_index_sha256"] = _sha256(encoded)
        store.save()
        return target.resolve()
