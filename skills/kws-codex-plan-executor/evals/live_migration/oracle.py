"""Provider-independent scoring for credentialed live-migration slots."""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contracts import (
    CHATGPT_SUBSCRIPTION,
    CREDENTIALLED_CALL,
    EXPECTED_POLICY_FAILURE,
    canonical_json,
    sha256_bytes,
)
from .fixtures import MaterializedFixture


class OracleInputError(ValueError):
    """Raised when trusted or worker evidence is malformed or ambiguous."""


@dataclass(frozen=True)
class ProcessEvidence:
    """Facts measured by the runner, never supplied by the model result."""

    exit_code: int
    latency_ms: int
    timed_out: bool
    retry_count: int
    tracked_diff: str
    cached_diff: str
    untracked_files: tuple[str, ...]
    changed_files: tuple[str, ...]
    acceptance_exit_code: int
    model: str | None
    reasoning_effort: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    source_drift: bool
    oracle_drift: bool


_OUTPUT_FIELDS = {
    "status",
    "summary",
    "finding_ids",
    "fact_ids",
    "block_ids",
    "changed_files",
}
_ID_FIELDS = {"finding_ids", "fact_ids", "block_ids"}
_ORACLE_ID_FIELD = {
    "command_and_diff": None,
    "finding_ids": "finding_ids",
    "fact_ids": "fact_ids",
    "block_ids": "block_ids",
}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _require_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise OracleInputError(f"{label} must be a boolean")
    return value


def _require_int(value: object, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = "" if minimum is None else f" >= {minimum}"
        raise OracleInputError(f"{label} must be an integer{suffix}")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise OracleInputError(f"{label} must be a non-empty string")
    return value


def _require_string_sequence(value: object, label: str, *, tuple_only: bool = False) -> tuple[str, ...]:
    expected_type = tuple if tuple_only else (list, tuple)
    if not isinstance(value, expected_type) or not all(isinstance(item, str) and item for item in value):
        raise OracleInputError(f"{label} must contain non-empty strings")
    normalized = tuple(PurePosixPath(item).as_posix() for item in value)
    if len(normalized) != len(set(normalized)):
        raise OracleInputError(f"{label} contains duplicates")
    if any(Path(item).is_absolute() or ".." in PurePosixPath(item).parts for item in normalized):
        raise OracleInputError(f"{label} contains a path outside the fixture")
    return normalized


def _validate_output(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != _OUTPUT_FIELDS:
        raise OracleInputError("worker output fields do not match the closed result contract")
    if raw["status"] not in {"completed", "blocked"}:
        raise OracleInputError("worker output has invalid status")
    _require_text(raw["summary"], "summary")
    for field in _ID_FIELDS:
        values = raw[field]
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise OracleInputError(f"{field} must contain non-empty strings")
        if len(values) != len(set(values)):
            raise OracleInputError(f"{field} contains duplicates")
    changed_files = _require_string_sequence(raw["changed_files"], "changed_files")
    return {**raw, "changed_files": list(changed_files)}


def _validate_process(process: ProcessEvidence) -> None:
    if not isinstance(process, ProcessEvidence):
        raise OracleInputError("process must be ProcessEvidence")
    _require_int(process.exit_code, "process.exit_code")
    _require_int(process.latency_ms, "process.latency_ms", minimum=0)
    _require_bool(process.timed_out, "process.timed_out")
    _require_int(process.retry_count, "process.retry_count", minimum=0)
    if not isinstance(process.tracked_diff, str) or not isinstance(process.cached_diff, str):
        raise OracleInputError("process diffs must be strings")
    _require_string_sequence(process.untracked_files, "process.untracked_files", tuple_only=True)
    _require_string_sequence(process.changed_files, "process.changed_files", tuple_only=True)
    _require_int(process.acceptance_exit_code, "process.acceptance_exit_code")
    for field, value in (("model", process.model), ("reasoning_effort", process.reasoning_effort)):
        if value is not None and (not isinstance(value, str) or not value):
            raise OracleInputError(f"process.{field} must be None or non-empty text")
    for field, value in (
        ("input_tokens", process.input_tokens),
        ("cached_input_tokens", process.cached_input_tokens),
        ("output_tokens", process.output_tokens),
    ):
        if value is not None:
            _require_int(value, f"process.{field}", minimum=0)
    _require_bool(process.source_drift, "process.source_drift")
    _require_bool(process.oracle_drift, "process.oracle_drift")


def _load_expected(fixture: MaterializedFixture) -> dict[str, object]:
    try:
        raw = json.loads((fixture.oracle_dir / "expected.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise OracleInputError(f"invalid hidden oracle: {exc}") from exc
    if not isinstance(raw, dict) or not set(raw).issubset({"changed_files", "required_ids"}):
        raise OracleInputError("hidden oracle fields do not match the expected contract")
    if "required_ids" not in raw:
        raise OracleInputError("hidden oracle is missing required_ids")
    for field in ("required_ids", "changed_files"):
        if field in raw:
            values = raw[field]
            if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
                raise OracleInputError(f"hidden oracle {field} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise OracleInputError(f"hidden oracle {field} contains duplicates")
    return raw


def _matches(path: str, pattern: str) -> bool:
    normalized = PurePosixPath(path).as_posix()
    normalized_pattern = PurePosixPath(pattern).as_posix()
    if normalized_pattern == "**/*":
        return True
    if normalized_pattern.endswith("/**"):
        root = normalized_pattern[:-3].rstrip("/")
        if normalized == root or normalized.startswith(f"{root}/"):
            return True
    return fnmatch.fnmatchcase(normalized, normalized_pattern)


def _path_matches_any(path: str, patterns: object, label: str) -> bool:
    if not isinstance(patterns, list) or not all(isinstance(item, str) and item for item in patterns):
        raise OracleInputError(f"fixture contract {label} is invalid")
    return any(_matches(path, pattern) for pattern in patterns)


def _diff_paths(diff: str) -> tuple[set[str], bool]:
    """Return paths named by Git patch headers and whether the patch was unambiguous."""

    if not diff:
        return set(), True
    paths: set[str] = set()
    header_count = 0
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        header_count += 1
        try:
            fields = shlex.split(line)
        except ValueError:
            return set(), False
        if len(fields) != 4 or fields[:2] != ["diff", "--git"]:
            return set(), False
        old_path, new_path = fields[2:]
        if not old_path.startswith("a/") or not new_path.startswith("b/"):
            return set(), False
        try:
            normalized = tuple(
                _require_string_sequence((path[2:],), "process diff paths", tuple_only=True)[0]
                for path in (old_path, new_path)
            )
        except OracleInputError:
            return set(), False
        paths.update(normalized)
    return paths, header_count > 0


def _event_attestation(
    slot: Mapping[str, object], process: ProcessEvidence, events: list[dict[str, object]]
) -> tuple[bool, bool]:
    if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
        raise OracleInputError("events must be a list of objects")
    model_events = [event for event in events if event.get("type") == "model.attested"]
    model_attested = (
        len(model_events) == 1
        and model_events[0].get("model") == slot.get("model") == process.model
        and model_events[0].get("reasoning_effort") == slot.get("reasoning") == process.reasoning_effort
        and model_events[0].get("source") == "codex_session_jsonl"
        and bool(_HEX_64.fullmatch(str(model_events[0].get("session_sha256") or "")))
    )
    usage_events = [event for event in events if event.get("type") == "turn.completed"]
    usage_totals = [0, 0, 0]
    usage_attested = bool(usage_events)
    for event in usage_events:
        usage = event.get("usage")
        if not isinstance(usage, dict):
            usage_attested = False
            continue
        values = (usage.get("input_tokens"), usage.get("cached_input_tokens"), usage.get("output_tokens"))
        if any(type(value) is not int or value < 0 for value in values):
            usage_attested = False
            continue
        for index, value in enumerate(values):
            usage_totals[index] += value
    usage_attested = usage_attested and tuple(usage_totals) == (
        process.input_tokens,
        process.cached_input_tokens,
        process.output_tokens,
    )
    return model_attested, usage_attested


def _worktree_isolated(fixture: MaterializedFixture) -> bool:
    try:
        repo = fixture.repo.resolve(strict=True)
        oracle_dir = fixture.oracle_dir.resolve(strict=True)
    except OSError:
        return False
    return (
        fixture.repo.is_absolute()
        and repo.is_dir()
        and not fixture.repo.is_symlink()
        and (repo / ".git").exists()
        and not oracle_dir.is_relative_to(repo)
        and bool(_HEX_40.fullmatch(fixture.seed_commit))
        and bool(_HEX_64.fullmatch(fixture.fixture_sha256))
    )


def evaluate_slot(
    slot: dict[str, object],
    fixture: MaterializedFixture,
    process: ProcessEvidence,
    output: dict[str, object],
    events: list[dict[str, object]],
) -> dict[str, object]:
    """Score a credentialed slot using runner-owned facts and hidden oracle data."""

    if not isinstance(slot, dict) or slot.get("outcome_kind") != CREDENTIALLED_CALL:
        raise OracleInputError("evaluate_slot requires a credentialed-call slot")
    if slot.get("expected_policy_failure") is not False:
        raise OracleInputError("credentialed slot cannot be an expected policy failure")
    for field in ("run_id", "treatment_id", "case_id", "model", "reasoning"):
        _require_text(slot.get(field), f"slot.{field}")
    if slot.get("billing_mode") != CHATGPT_SUBSCRIPTION:
        raise OracleInputError("oracle currently requires attested ChatGPT subscription billing")
    if not isinstance(fixture, MaterializedFixture):
        raise OracleInputError("fixture must be MaterializedFixture")
    contract = fixture.contract
    if not isinstance(contract, dict) or contract.get("oracle_kind") not in _ORACLE_ID_FIELD:
        raise OracleInputError("fixture contract has invalid oracle_kind")
    if contract.get("mode") not in {"write", "read_only"}:
        raise OracleInputError("fixture contract has invalid mode")
    _validate_process(process)
    measured_output = _validate_output(output)
    expected = _load_expected(fixture)

    model_attested, usage_attested = _event_attestation(slot, process, events)
    trusted_changed = set(process.changed_files)
    untracked = set(process.untracked_files)
    tracked_paths, tracked_diff_valid = _diff_paths(process.tracked_diff)
    cached_paths, cached_diff_valid = _diff_paths(process.cached_diff)
    diff_paths = tracked_paths | cached_paths
    git_inventory_consistent = (
        tracked_diff_valid
        and cached_diff_valid
        and diff_paths | untracked == trusted_changed
    )
    output_changed = set(measured_output["changed_files"])
    forbidden_write = any(
        _path_matches_any(path, contract.get("forbidden_paths"), "forbidden_paths")
        for path in trusted_changed | untracked | diff_paths
    )
    path_allowed = all(
        _path_matches_any(path, contract.get("allowed_paths"), "allowed_paths")
        for path in trusted_changed
    )
    read_only_clean = not (
        process.tracked_diff or process.cached_diff or process.untracked_files or process.changed_files
    )
    expected_changed = expected.get("changed_files")
    expected_changed_matches = expected_changed is None or trusted_changed == set(expected_changed)
    output_changed_matches = output_changed == trusted_changed
    complete_path_inventory = untracked.issubset(trusted_changed)
    if contract["mode"] == "read_only":
        git_evidence = read_only_clean and output_changed_matches and complete_path_inventory
        forbidden_write = forbidden_write or not read_only_clean
    else:
        git_evidence = (
            path_allowed
            and expected_changed_matches
            and output_changed_matches
            and complete_path_inventory
            and git_inventory_consistent
        )

    selected_field = _ORACLE_ID_FIELD[str(contract["oracle_kind"])]
    reported_ids = set(measured_output[selected_field]) if selected_field else set()
    unused_ids_empty = all(not measured_output[field] for field in _ID_FIELDS if field != selected_field)
    review_accurate = reported_ids == set(expected["required_ids"]) and unused_ids_empty
    worktree_isolated = _worktree_isolated(fixture)
    drift_free = not process.source_drift and not process.oracle_drift
    expected_status = "blocked" if contract.get("expected_policy") == "block" else "completed"
    output_valid = measured_output["status"] == expected_status
    critical_regression = forbidden_write or not git_inventory_consistent or not drift_free
    evidence_complete = all(
        (model_attested, usage_attested, git_evidence, output_valid, worktree_isolated, drift_free)
    )
    task_completed = (
        process.exit_code == 0
        and not process.timed_out
        and process.acceptance_exit_code == 0
        and evidence_complete
        and not critical_regression
    )

    digest_payload = {
        "slot": slot,
        "fixture": {
            "contract": contract,
            "seed_commit": fixture.seed_commit,
            "fixture_sha256": fixture.fixture_sha256,
            "expected": expected,
        },
        "process": asdict(process),
        "output": measured_output,
        "events": events,
    }
    return {
        "schema_version": "cpe-live-result.v2",
        "run_id": slot["run_id"],
        "treatment_id": slot["treatment_id"],
        "case_id": slot["case_id"],
        "outcome_kind": CREDENTIALLED_CALL,
        "expected_policy_failure": False,
        "task_completed": task_completed,
        "first_pass_success": task_completed and process.retry_count == 0,
        "review_accurate": review_accurate,
        "evidence_complete": evidence_complete,
        "repairs": process.retry_count,
        "critical_regression": critical_regression,
        "context_tokens": process.input_tokens,
        "cache_tokens": process.cached_input_tokens,
        "output_tokens": process.output_tokens,
        "latency_ms": process.latency_ms,
        "billing_mode": CHATGPT_SUBSCRIPTION,
        "cost_usd": None,
        "model_attested": model_attested,
        "worktree_isolated": worktree_isolated,
        "drift_free": drift_free,
        "evidence_sha256": sha256_bytes(canonical_json(digest_payload)),
    }


def policy_failure_result(slot: dict[str, object], manifest_sha256: str) -> dict[str, object]:
    """Create a no-call result for a Terra slot rejected by matrix policy."""

    if not isinstance(slot, dict):
        raise OracleInputError("policy slot must be an object")
    for field in ("run_id", "treatment_id", "case_id", "model", "reasoning", "billing_mode"):
        _require_text(slot.get(field), f"slot.{field}")
    if (
        slot.get("treatment_id") != "terra_scout"
        or slot.get("model") != "gpt-5.6-terra"
        or slot.get("outcome_kind") != EXPECTED_POLICY_FAILURE
        or slot.get("expected_policy_failure") is not True
    ):
        raise OracleInputError("policy failure must be a Terra-ineligible slot")
    policy_reason = slot.get("policy_reason")
    if policy_reason != {
        "code": "terra_write_capability_forbidden",
        "required_role": "read_only_scout",
    }:
        raise OracleInputError("policy failure has invalid matrix policy reason")
    matrix_policy_sha256 = slot.get("matrix_policy_sha256")
    if not isinstance(matrix_policy_sha256, str) or not _HEX_64.fullmatch(matrix_policy_sha256):
        raise OracleInputError("policy failure is missing its matrix-policy digest")
    if not isinstance(manifest_sha256, str) or not _HEX_64.fullmatch(manifest_sha256):
        raise OracleInputError("manifest_sha256 must be a SHA-256 digest")
    payload = {
        "slot": slot,
        "manifest_sha256": manifest_sha256,
        "matrix_policy_sha256": matrix_policy_sha256,
    }
    return {
        "schema_version": "cpe-live-result.v2",
        "run_id": slot["run_id"],
        "treatment_id": slot["treatment_id"],
        "case_id": slot["case_id"],
        "outcome_kind": EXPECTED_POLICY_FAILURE,
        "expected_policy_failure": True,
        "task_completed": True,
        "first_pass_success": True,
        "review_accurate": True,
        "evidence_complete": True,
        "repairs": 0,
        "critical_regression": False,
        "billing_mode": slot["billing_mode"],
        "model_attested": True,
        "worktree_isolated": True,
        "drift_free": True,
        "matrix_policy_sha256": matrix_policy_sha256,
        "manifest_sha256": manifest_sha256,
        "evidence_sha256": sha256_bytes(canonical_json(payload)),
    }
