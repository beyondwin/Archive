"""Source-bound compiled run index preparation and validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BRANCH_PHASES = {"task_red", "task_green", "task_review", "final_verification"}
_MUTABLE_INPUT_POLICIES = {"forbidden", "declared_external_state"}
_COORDINATION_REASONS = {
    "source_requires_shared_context", "source_requires_cross_task_coordination",
    "source_requires_integrated_review",
}


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


def _schema_error() -> ValueError:
    return ValueError("compiled index schema is invalid")


def _validation_error_code(error: ValueError) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(error).lower()).strip("_")
    return normalized[:96] or "compiled_index_validation_failed"


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _unique_strings(values: object) -> bool:
    return (isinstance(values, list) and all(isinstance(value, str) for value in values)
            and len(values) == len(set(values)))


def _relative_artifact(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 512 or value.startswith("/"):
        return False
    return ".." not in value.split("/")


def _validate_nested_contract(compiled: dict[str, Any]) -> set[str]:
    task_fields = {
        "task_id", "order", "source_line_start", "source_line_end",
        "source_text_sha256",
    }
    task_ids: list[str] = []
    for order, task in enumerate(compiled["tasks"]):
        if (not isinstance(task, dict) or set(task) != task_fields
                or not _identifier(task.get("task_id"))
                or type(task.get("order")) is not int or task["order"] != order):
            raise _schema_error()
        task_ids.append(task["task_id"])
    if len(task_ids) != len(set(task_ids)):
        raise _schema_error()
    known_tasks = set(task_ids)

    verification_fields = {
        "command_id", "argv", "allowed_branch_phases", "deterministic",
        "mutable_input_policy", "required_artifacts", "source_line_start",
        "source_line_end", "source_text_sha256",
    }
    command_ids: list[str] = []
    for item in compiled["verifications"]:
        if not isinstance(item, dict) or set(item) != verification_fields:
            raise _schema_error()
        argv, phases, artifacts = (
            item["argv"], item["allowed_branch_phases"], item["required_artifacts"]
        )
        if (not _identifier(item["command_id"])
                or not isinstance(argv, list) or not 1 <= len(argv) <= 128
                or not all(isinstance(arg, str) and len(arg) <= 4096 for arg in argv)
                or not _unique_strings(phases) or not phases
                or not set(phases) <= _BRANCH_PHASES
                or type(item["deterministic"]) is not bool
                or not isinstance(item["mutable_input_policy"], str)
                or item["mutable_input_policy"] not in _MUTABLE_INPUT_POLICIES
                or not _unique_strings(artifacts) or len(artifacts) > 64
                or not all(_relative_artifact(path) for path in artifacts)):
            raise _schema_error()
        command_ids.append(item["command_id"])
    if len(command_ids) != len(set(command_ids)):
        raise _schema_error()

    capability_fields = {"capability_id", "task_ids"}
    capability_ids: list[str] = []
    for item in compiled["capabilities"]:
        if not isinstance(item, dict) or set(item) != capability_fields:
            raise _schema_error()
        references = item["task_ids"]
        if (not _identifier(item["capability_id"]) or not _unique_strings(references)
                or not references or not all(_identifier(value) for value in references)
                or not set(references) <= known_tasks):
            raise _schema_error()
        capability_ids.append(item["capability_id"])
    if len(capability_ids) != len(set(capability_ids)):
        raise _schema_error()

    exception_fields = {
        "task_id", "role", "fork_turns", "reason_code", "source_line_start",
        "source_line_end", "source_text_sha256",
    }
    for item in compiled["coordination_exceptions"]:
        if (not isinstance(item, dict) or set(item) != exception_fields
                or not _identifier(item["task_id"])
                or item["task_id"] not in known_tasks
                or not isinstance(item["role"], str) or not 1 <= len(item["role"]) <= 64
                or item["fork_turns"] != "all"
                or not isinstance(item["reason_code"], str)
                or item["reason_code"] not in _COORDINATION_REASONS):
            raise _schema_error()
    return known_tasks


def _read_private_cache(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("compiled index cache must not be a symlink")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("compiled index cache must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("compiled index cache must have private mode")
    if metadata.st_size > MAX_COMPILER_OUTPUT_BYTES:
        raise ValueError("compiled index cache exceeds size limit")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_ino != metadata.st_ino
                or opened.st_dev != metadata.st_dev):
            raise ValueError("compiled index cache changed during validation")
        if stat.S_IMODE(opened.st_mode) & 0o077:
            raise ValueError("compiled index cache must have private mode")
        if opened.st_size > MAX_COMPILER_OUTPUT_BYTES:
            raise ValueError("compiled index cache exceeds size limit")
        chunks: list[bytes] = []
        remaining = MAX_COMPILER_OUTPUT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_COMPILER_OUTPUT_BYTES:
            raise ValueError("compiled index cache exceeds size limit")
        return payload
    finally:
        os.close(descriptor)


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
        for field in (
            "tasks", "verifications", "capabilities", "coordination_exceptions",
            "execution_advisories", "unknowns",
        ):
            if not isinstance(compiled[field], list):
                raise _schema_error()
        _validate_nested_contract(compiled)
        if compiled.get("source_sha256") != record["sha256"]:
            raise ValueError("compiled plan source digest is invalid")
        lines = _source_lines(record)
        if (type(compiled.get("byte_length")) is not int
                or type(compiled.get("line_count")) is not int
                or compiled["byte_length"] != record["byte_length"]
                or compiled["line_count"] != len(lines)):
            raise ValueError("compiled plan source metadata is invalid")
        tasks = compiled["tasks"]
        for order, task in enumerate(tasks):
            if not isinstance(task, dict) or task.get("order") != order:
                raise ValueError("compiled task order is invalid")
            _validate_span(task, lines, "source")
        verifications = compiled["verifications"]
        command_ids = [item.get("command_id") for item in verifications if isinstance(item, dict)]
        if len(command_ids) != len(verifications) or len(command_ids) != len(set(command_ids)):
            raise ValueError("compiled verification command IDs are invalid")
        for verification in verifications:
            _validate_span(verification, lines, "verification source")
        exceptions = compiled["coordination_exceptions"]
        for exception in exceptions:
            if not isinstance(exception, dict) or exception.get("fork_turns") != "all":
                raise ValueError("compiled coordination exception is invalid")
            _validate_span(exception, lines, "coordination exception source")
        unknowns = compiled.get("unknowns", [])
        if (not isinstance(unknowns, list)
                or not all(isinstance(item, str) and 1 <= len(item) <= 512 for item in unknowns)):
            raise ValueError("compiled unknowns are invalid")
        if any(item.startswith(SAFETY_UNKNOWN_PREFIXES) for item in unknowns):
            raise ValueError("compiled safety field is ambiguous")
        advisories = compiled["execution_advisories"]
        if not _unique_strings(advisories) or any(item not in {
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
        if target.exists() or target.is_symlink():
            cache_bytes = _read_private_cache(target)
            cached = json.loads(cache_bytes)
            validate_compiled_index(cached, store.state, contract)
            store.state["compiled_run_index_path"] = str(target)
            store.state["compiled_run_index_sha256"] = _sha256(cache_bytes)
            store.save()
            return target
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
                if not repair:
                    error_path = store.root / "results" / "compiler-attempt-1.error-code"
                    atomic_private_write(
                        error_path,
                        _validation_error_code(exc).encode("ascii"),
                    )
                    error_path.chmod(0o400)
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
