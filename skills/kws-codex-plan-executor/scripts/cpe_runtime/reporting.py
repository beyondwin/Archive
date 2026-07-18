"""Bounded trust-labelled optimization reports derived from run evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from pathlib import PurePosixPath

from .state import TRUST_LEVELS, atomic_private_write


MAX_REPORT_BYTES = 1024 * 1024
MAX_OBSERVED_COUNTER = 2**63 - 1
MAX_INVENTORY_FILES = 10_000
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SIGNAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINDING_REQUIRED = {"signal", "source", "evidence_refs"}
_FINDING_OPTIONAL = {
    "impact", "action", "outcome", "recurrence", "recommendation",
}
_USAGE_EVENT_FIELDS = {
    "input": "input_tokens",
    "cached_input": "cached_input_tokens",
    "output": "output_tokens",
    "reasoning_output": "reasoning_output_tokens",
}


def _observed_counter(value: object) -> int | None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > MAX_OBSERVED_COUNTER
    ):
        return None
    return value


def _usage_reason(event: dict[str, object]) -> str:
    if event.get("timed_out") is True:
        return "timeout"
    returncode = event.get("returncode")
    if (
        isinstance(returncode, int)
        and not isinstance(returncode, bool)
        and returncode != 0
    ):
        return "nonzero_exit"
    return "usage_unavailable"


def _artifact_class(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    name = path.name.lower()
    if path.suffix.lower() in {".diff", ".patch"} or "diff" in name:
        return "review_diff"
    if "review" in name:
        return "review_report"
    if "brief" in name:
        return "brief"
    if name in {"progress.md", "execution-ledger.jsonl"}:
        return "progress_ledger"
    if path.parts and path.parts[0] == "verification":
        return "verification_evidence"
    return "other"


def _safe_inventory_reference(relative_path: str) -> str:
    encoded = relative_path.encode("utf-8", errors="surrogateescape")
    if len(relative_path) <= 500 and "\\" not in relative_path:
        path = PurePosixPath(relative_path)
        if not path.is_absolute() and not any(
            part in {"", ".", ".."} for part in path.parts
        ):
            return relative_path
    return f"artifact-digest/{hashlib.sha256(encoded).hexdigest()}"


def _unavailable_artifact_inventory() -> dict[str, object]:
    return {
        "availability": "unavailable",
        "measurement_kind": "produced_filesystem_metadata_only",
        "advisory_only": True,
        "acceptance_effect": False,
        "produced_files": None,
        "produced_bytes": None,
        "classes": {},
        "largest": None,
        "review_diff_pressure": {
            "files": None,
            "bytes": None,
            "largest_bytes": None,
        },
        "declared_context": {
            "status": "unavailable",
            "refs": None,
            "bytes": None,
            "reason": "not_directly_evidenced",
        },
        "truncated": False,
    }


def inventory_produced_artifacts(sdd_root: Path | None) -> dict[str, object]:
    """Inventory produced SDD metadata without reading artifact bodies."""
    if sdd_root is None:
        return _unavailable_artifact_inventory()
    try:
        root_metadata = sdd_root.lstat()
    except OSError:
        return _unavailable_artifact_inventory()
    if sdd_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        return _unavailable_artifact_inventory()

    produced_files = 0
    produced_bytes = 0
    classes: dict[str, dict[str, int]] = {}
    largest: dict[str, object] | None = None
    largest_review_bytes = 0
    truncated = False
    walk_errors: list[OSError] = []
    for directory, directory_names, file_names in os.walk(
        sdd_root, followlinks=False, onerror=walk_errors.append
    ):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name for name in directory_names
            if not (directory_path / name).is_symlink()
        )
        for name in sorted(file_names):
            if produced_files >= MAX_INVENTORY_FILES:
                truncated = True
                break
            path = directory_path / name
            try:
                metadata = path.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            size = metadata.st_size
            if size < 0 or produced_bytes > MAX_OBSERVED_COUNTER - size:
                truncated = True
                break
            relative = path.relative_to(sdd_root).as_posix()
            artifact_class = _artifact_class(relative)
            bucket = classes.setdefault(artifact_class, {"files": 0, "bytes": 0})
            bucket["files"] += 1
            bucket["bytes"] += size
            if artifact_class == "review_diff":
                largest_review_bytes = max(largest_review_bytes, size)
            produced_files += 1
            produced_bytes += size
            candidate = {
                "relative_path": _safe_inventory_reference(relative),
                "bytes": size,
                "class": artifact_class,
            }
            if (
                largest is None
                or size > largest["bytes"]
                or (
                    size == largest["bytes"]
                    and candidate["relative_path"] < largest["relative_path"]
                )
            ):
                largest = candidate
        if truncated:
            break
    truncated = truncated or bool(walk_errors)

    review = classes.get("review_diff", {"files": 0, "bytes": 0})
    return {
        "availability": "available",
        "measurement_kind": "produced_filesystem_metadata_only",
        "advisory_only": True,
        "acceptance_effect": False,
        "produced_files": produced_files,
        "produced_bytes": produced_bytes,
        "classes": dict(sorted(classes.items())),
        "largest": largest,
        "review_diff_pressure": {
            "files": review["files"],
            "bytes": review["bytes"],
            "largest_bytes": largest_review_bytes,
        },
        "declared_context": {
            "status": "unavailable",
            "refs": None,
            "bytes": None,
            "reason": "not_directly_evidenced",
        },
        "truncated": truncated,
    }


def derive_recovery_metrics(
    events: list[dict[str, object]],
) -> dict[str, object]:
    """Derive bounded recovery counters from the authoritative event stream."""
    launches_avoided = 0
    envelope_repairs = 0
    productive_timeouts = 0
    no_progress_slices = 0
    budget_stops = 0
    reasons: dict[str, int] = {}
    for event in events:
        action = event.get("action")
        reason = event.get("reason")
        if action == "resume.stopped_unchanged_blocker":
            launches_avoided += 1
        if action == "result.envelope_repaired":
            envelope_repairs += 1
            launches_avoided += 1
        if (
            action == "plan.pre_spawn_stopped"
            and reason in {
                "launch_budget_exhausted",
                "wall_budget_exhausted",
            }
        ):
            budget_stops += 1
        if action != "plan.checkpoint_decided" or not isinstance(reason, str):
            continue
        if event.get("decision") == "continue":
            reasons[reason] = reasons.get(reason, 0) + 1
        if reason == "productive_timeout":
            productive_timeouts += 1
        if reason == "no_progress_timeout":
            no_progress_slices += 1
        if reason in {
            "launch_budget_exhausted",
            "wall_budget_exhausted",
        }:
            budget_stops += 1
    return {
        "launches_avoided": launches_avoided,
        "envelope_repairs": envelope_repairs,
        "productive_timeouts": productive_timeouts,
        "no_progress_slices": no_progress_slices,
        "budget_stops": budget_stops,
        "continuation_reason_counts": dict(sorted(reasons.items())),
    }


class OptimizationMarkdownError(RuntimeError):
    """The authoritative JSON report succeeded but its derivative did not."""


def _validate_evidence_reference(reference: object) -> None:
    if (
        not isinstance(reference, str)
        or not reference
        or len(reference) > 500
        or "\\" in reference
    ):
        raise ValueError("optimization finding evidence reference is invalid")
    path = PurePosixPath(reference)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("optimization finding evidence reference is unsafe")


def _validate_finding(finding: object) -> None:
    if not isinstance(finding, dict):
        raise ValueError("optimization finding must be an object")
    fields = set(finding)
    if finding.get("source") not in TRUST_LEVELS:
        raise ValueError("optimization finding trust source is invalid")
    if not _FINDING_REQUIRED.issubset(fields) or fields - _FINDING_REQUIRED - _FINDING_OPTIONAL:
        raise ValueError("optimization finding fields are invalid")
    signal = finding["signal"]
    if not isinstance(signal, str) or not _SIGNAL.fullmatch(signal):
        raise ValueError("optimization finding signal is invalid")
    references = finding["evidence_refs"]
    if not isinstance(references, list) or not references or len(references) > 128:
        raise ValueError("optimization finding evidence references are invalid")
    for reference in references:
        _validate_evidence_reference(reference)
    for name in _FINDING_OPTIONAL & fields:
        value = finding[name]
        if not isinstance(value, str) or not value or len(value) > 2000:
            raise ValueError(f"optimization finding {name} is invalid")


def _validate_bounded_counter(value: object, message: str) -> None:
    if _observed_counter(value) is None:
        raise ValueError(message)


def _validate_usage_metric(
    metric: object, *, observed_field: str, extra_fields: set[str] | None = None
) -> None:
    fields = {
        observed_field, "known_attempts", "unknown_attempts", "total_kind",
        *(extra_fields or set()),
    }
    if not isinstance(metric, dict) or set(metric) != fields:
        raise ValueError("optimization report usage is invalid")
    for name in (observed_field, "known_attempts", "unknown_attempts"):
        _validate_bounded_counter(metric[name], "optimization report usage is invalid")
    expected = "exact" if metric["unknown_attempts"] == 0 else "lower_bound"
    if metric["total_kind"] != expected:
        raise ValueError("optimization report usage is invalid")


def _validate_artifact_inventory(inventory: object) -> None:
    fields = {
        "availability", "measurement_kind", "advisory_only", "acceptance_effect",
        "produced_files", "produced_bytes", "classes", "largest",
        "review_diff_pressure", "declared_context", "truncated",
    }
    if not isinstance(inventory, dict) or set(inventory) != fields:
        raise ValueError("optimization report artifact inventory is invalid")
    if (
        inventory["availability"] not in {"available", "unavailable"}
        or inventory["measurement_kind"] != "produced_filesystem_metadata_only"
        or inventory["advisory_only"] is not True
        or inventory["acceptance_effect"] is not False
        or not isinstance(inventory["truncated"], bool)
    ):
        raise ValueError("optimization report artifact inventory is invalid")
    available = inventory["availability"] == "available"
    for name in ("produced_files", "produced_bytes"):
        value = inventory[name]
        if available:
            _validate_bounded_counter(
                value, "optimization report artifact inventory is invalid"
            )
        elif value is not None:
            raise ValueError("optimization report artifact inventory is invalid")
    classes = inventory["classes"]
    if not isinstance(classes, dict) or len(classes) > 32:
        raise ValueError("optimization report artifact inventory is invalid")
    for name, bucket in classes.items():
        if (
            not isinstance(name, str)
            or not _SIGNAL.fullmatch(name)
            or not isinstance(bucket, dict)
            or set(bucket) != {"files", "bytes"}
        ):
            raise ValueError("optimization report artifact inventory is invalid")
        for value in bucket.values():
            _validate_bounded_counter(
                value, "optimization report artifact inventory is invalid"
            )
    largest = inventory["largest"]
    if largest is not None:
        if (
            not isinstance(largest, dict)
            or set(largest) != {"relative_path", "bytes", "class"}
        ):
            raise ValueError("optimization report artifact inventory is invalid")
        _validate_evidence_reference(largest["relative_path"])
        _validate_bounded_counter(
            largest["bytes"], "optimization report artifact inventory is invalid"
        )
        if not isinstance(largest["class"], str) or not _SIGNAL.fullmatch(largest["class"]):
            raise ValueError("optimization report artifact inventory is invalid")
    pressure = inventory["review_diff_pressure"]
    if not isinstance(pressure, dict) or set(pressure) != {
        "files", "bytes", "largest_bytes",
    }:
        raise ValueError("optimization report artifact inventory is invalid")
    for value in pressure.values():
        if available:
            _validate_bounded_counter(
                value, "optimization report artifact inventory is invalid"
            )
        elif value is not None:
            raise ValueError("optimization report artifact inventory is invalid")
    declared = inventory["declared_context"]
    if declared != {
        "status": "unavailable",
        "refs": None,
        "bytes": None,
        "reason": "not_directly_evidenced",
    }:
        raise ValueError("optimization report artifact inventory is invalid")


def validate_optimization_report(report: object) -> dict[str, object]:
    if not isinstance(report, dict) or set(report) != {
        "format_version", "run_id", "usage", "duration_ms", "recovery_metrics",
        "duration_unknown_attempt_count", "verification", "artifact_inventory",
        "data_quality_warnings", "findings",
    }:
        raise ValueError("optimization report fields are invalid")
    if report["format_version"] != 2:
        raise ValueError("optimization report format version is invalid")
    run_id = report["run_id"]
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("optimization report run identity is invalid")
    duration = report["duration_ms"]
    _validate_bounded_counter(duration, "optimization report duration is invalid")
    _validate_bounded_counter(
        report["duration_unknown_attempt_count"],
        "optimization report duration is invalid",
    )
    usage = report["usage"]
    if not isinstance(usage, dict) or set(usage) != {
        "attempts_finished", "attempts_fully_observed", "input", "cached_input",
        "uncached_input", "output", "reasoning_output", "launcher_prompt",
        "paired_observation_cache_ratio", "unknown_attempt_duration_ms",
        "unknown_attempt_missing_duration_count", "unknown_attempts_by_reason",
        "scope", "attribution", "attribution_unavailable_reason",
    }:
        raise ValueError("optimization report usage is invalid")
    for name in (
        "attempts_finished", "attempts_fully_observed",
        "unknown_attempt_duration_ms", "unknown_attempt_missing_duration_count",
    ):
        _validate_bounded_counter(usage[name], "optimization report usage is invalid")
    if usage["attempts_fully_observed"] > usage["attempts_finished"]:
        raise ValueError("optimization report usage kind is invalid")
    for name in ("input", "cached_input", "output", "reasoning_output"):
        _validate_usage_metric(usage[name], observed_field="observed_tokens")
    _validate_usage_metric(
        usage["uncached_input"], observed_field="observed_tokens",
        extra_fields={"derivation"},
    )
    if usage["uncached_input"]["derivation"] != "input_minus_cached_per_attempt":
        raise ValueError("optimization report usage is invalid")
    _validate_usage_metric(
        usage["launcher_prompt"], observed_field="observed_bytes",
        extra_fields={"unit"},
    )
    if usage["launcher_prompt"]["unit"] != "bytes":
        raise ValueError("optimization report usage is invalid")
    ratio = usage["paired_observation_cache_ratio"]
    if ratio is not None and (
        not isinstance(ratio, (int, float))
        or isinstance(ratio, bool)
        or not 0 <= ratio <= 1
    ):
        raise ValueError("optimization report usage is invalid")
    reasons = usage["unknown_attempts_by_reason"]
    if (
        not isinstance(reasons, dict)
        or set(reasons) - {"timeout", "nonzero_exit", "usage_unavailable"}
    ):
        raise ValueError("optimization report usage is invalid")
    for value in reasons.values():
        _validate_bounded_counter(value, "optimization report usage is invalid")
    if (
        usage["scope"] != "controller_and_nested_agents_aggregate"
        or usage["attribution"] != "unavailable"
        or usage["attribution_unavailable_reason"] != "provider_event_not_agent_scoped"
    ):
        raise ValueError("optimization report usage attribution is invalid")
    verification = report["verification"]
    if not isinstance(verification, dict) or set(verification) != {
        "executions", "reuses", "uncached_executions",
    }:
        raise ValueError("optimization report verification metrics are invalid")
    for value in verification.values():
        _validate_bounded_counter(
            value, "optimization report verification metrics are invalid"
        )
    if verification["uncached_executions"] > verification["executions"]:
        raise ValueError("optimization report verification metrics are invalid")
    _validate_artifact_inventory(report["artifact_inventory"])
    warnings = report["data_quality_warnings"]
    if (
        not isinstance(warnings, list)
        or len(warnings) > 1024
        or any(
            not isinstance(item, str) or not item or len(item) > 200
            for item in warnings
        )
    ):
        raise ValueError("optimization report data quality warnings are invalid")
    metrics = report["recovery_metrics"]
    metric_fields = {
        "launches_avoided", "envelope_repairs", "productive_timeouts",
        "no_progress_slices", "budget_stops", "continuation_reason_counts",
    }
    if not isinstance(metrics, dict) or set(metrics) != metric_fields:
        raise ValueError("optimization report recovery metrics are invalid")
    for name in metric_fields - {"continuation_reason_counts"}:
        _validate_bounded_counter(
            metrics[name], "optimization report recovery metrics are invalid"
        )
    reasons = metrics["continuation_reason_counts"]
    if (
        not isinstance(reasons, dict)
        or len(reasons) > 128
        or any(
            not isinstance(name, str) or not _SIGNAL.fullmatch(name)
            or _observed_counter(value) is None
            for name, value in reasons.items()
        )
    ):
        raise ValueError("optimization report recovery metrics are invalid")
    findings = report["findings"]
    if not isinstance(findings, list) or len(findings) > 1024:
        raise ValueError("optimization report findings are invalid")
    for finding in findings:
        _validate_finding(finding)
    return report


def build_optimization_report(
    *,
    run_id: str,
    events: list[dict[str, object]],
    findings: list[dict[str, object]],
    sdd_root: Path | None = None,
) -> dict[str, object]:
    duration = 0
    duration_unknown = 0
    attempts = [
        event for event in events
        if event.get("action") == "plan.attempt_finished"
        and event.get("source") == "parent_observed"
    ]
    totals = {name: 0 for name in _USAGE_EVENT_FIELDS}
    known = {name: 0 for name in _USAGE_EVENT_FIELDS}
    uncached_total = 0
    uncached_known = 0
    prompt_total = 0
    prompt_known = 0
    fully_observed = 0
    paired_input_total = 0
    paired_cached_total = 0
    unknown_usage_duration = 0
    unknown_usage_missing_duration = 0
    unknown_reasons: dict[str, int] = {}
    warnings: list[str] = []

    for position, event in enumerate(attempts, 1):
        observed_duration = _observed_counter(event.get("duration_ms"))
        if observed_duration is None or duration > MAX_OBSERVED_COUNTER - observed_duration:
            duration_unknown += 1
            observed_duration = None
            warnings.append(f"attempt {position} duration_ms is unavailable")
        else:
            duration += observed_duration

        values = {
            name: _observed_counter(event.get(event_field))
            for name, event_field in _USAGE_EVENT_FIELDS.items()
        }
        input_value = values["input"]
        cached_value = values["cached_input"]
        if (
            input_value is not None
            and cached_value is not None
            and cached_value > input_value
        ):
            values["cached_input"] = None
            cached_value = None
            warnings.append(f"attempt {position} cached_input exceeds input")

        accepted: dict[str, bool] = {}
        for name, event_field in _USAGE_EVENT_FIELDS.items():
            value = values[name]
            if value is None or totals[name] > MAX_OBSERVED_COUNTER - value:
                accepted[name] = False
                warnings.append(f"attempt {position} {event_field} is unavailable")
                continue
            totals[name] += value
            known[name] += 1
            accepted[name] = True

        if input_value is not None and cached_value is not None:
            uncached_value = input_value - cached_value
            if uncached_total <= MAX_OBSERVED_COUNTER - uncached_value:
                uncached_total += uncached_value
                uncached_known += 1
                paired_input_total += input_value
                paired_cached_total += cached_value
            else:
                warnings.append(f"attempt {position} uncached_input aggregate overflow")

        prompt_value = _observed_counter(event.get("launcher_prompt_bytes"))
        if prompt_value is None or prompt_total > MAX_OBSERVED_COUNTER - prompt_value:
            warnings.append(f"attempt {position} launcher_prompt_bytes is unavailable")
        else:
            prompt_total += prompt_value
            prompt_known += 1

        if all(accepted.values()):
            fully_observed += 1
        if not accepted["input"]:
            reason = _usage_reason(event)
            unknown_reasons[reason] = unknown_reasons.get(reason, 0) + 1
            if observed_duration is None:
                unknown_usage_missing_duration += 1
            else:
                unknown_usage_duration += observed_duration

    attempts_finished = len(attempts)

    def token_metric(name: str) -> dict[str, object]:
        unknown = attempts_finished - known[name]
        return {
            "observed_tokens": totals[name],
            "known_attempts": known[name],
            "unknown_attempts": unknown,
            "total_kind": "exact" if unknown == 0 else "lower_bound",
        }

    uncached_unknown = attempts_finished - uncached_known
    prompt_unknown = attempts_finished - prompt_known
    verification_executions = 0
    verification_reuses = 0
    uncached_executions = 0
    seen_verification_events: set[str] = set()
    for event in events:
        if (
            event.get("action") != "verification.evidence_ingested"
            or event.get("source") != "parent_observed"
        ):
            continue
        child_event_id = event.get("child_event_id")
        if not isinstance(child_event_id, str) or child_event_id in seen_verification_events:
            continue
        seen_verification_events.add(child_event_id)
        decision = event.get("decision")
        if decision == "reused":
            verification_reuses += 1
        elif decision in {"executed", "executed_uncached"}:
            verification_executions += 1
            if decision == "executed_uncached":
                uncached_executions += 1

    unique_warnings = sorted(set(warnings))
    if len(unique_warnings) > 1024:
        unique_warnings = unique_warnings[:1023] + [
            "additional data quality warnings were truncated"
        ]

    report: dict[str, object] = {
        "format_version": 2,
        "run_id": run_id,
        "usage": {
            "attempts_finished": attempts_finished,
            "attempts_fully_observed": fully_observed,
            "input": token_metric("input"),
            "cached_input": token_metric("cached_input"),
            "uncached_input": {
                "observed_tokens": uncached_total,
                "known_attempts": uncached_known,
                "unknown_attempts": uncached_unknown,
                "derivation": "input_minus_cached_per_attempt",
                "total_kind": "exact" if uncached_unknown == 0 else "lower_bound",
            },
            "output": token_metric("output"),
            "reasoning_output": token_metric("reasoning_output"),
            "launcher_prompt": {
                "observed_bytes": prompt_total,
                "known_attempts": prompt_known,
                "unknown_attempts": prompt_unknown,
                "total_kind": "exact" if prompt_unknown == 0 else "lower_bound",
                "unit": "bytes",
            },
            "paired_observation_cache_ratio": (
                paired_cached_total / paired_input_total
                if paired_input_total else None
            ),
            "unknown_attempt_duration_ms": unknown_usage_duration,
            "unknown_attempt_missing_duration_count": unknown_usage_missing_duration,
            "unknown_attempts_by_reason": dict(sorted(unknown_reasons.items())),
            "scope": "controller_and_nested_agents_aggregate",
            "attribution": "unavailable",
            "attribution_unavailable_reason": "provider_event_not_agent_scoped",
        },
        "duration_ms": duration,
        "duration_unknown_attempt_count": duration_unknown,
        "verification": {
            "executions": verification_executions,
            "reuses": verification_reuses,
            "uncached_executions": uncached_executions,
        },
        "artifact_inventory": inventory_produced_artifacts(sdd_root),
        "data_quality_warnings": unique_warnings,
        "recovery_metrics": derive_recovery_metrics(events),
        "findings": findings,
    }
    return validate_optimization_report(report)


def render_optimization_markdown(report: dict[str, object]) -> str:
    usage = report["usage"]
    assert isinstance(usage, dict)
    metrics = report["recovery_metrics"]
    assert isinstance(metrics, dict)
    reasons = metrics["continuation_reason_counts"]
    assert isinstance(reasons, dict)
    verification = report["verification"]
    assert isinstance(verification, dict)
    inventory = report["artifact_inventory"]
    assert isinstance(inventory, dict)
    warnings = report["data_quality_warnings"]
    assert isinstance(warnings, list)

    def metric_line(label: str, metric: object, observed_field: str, unit: str) -> str:
        assert isinstance(metric, dict)
        return (
            f"{label} ({metric['total_kind']}): {metric[observed_field]} observed "
            f"{unit}; {metric['known_attempts']} known; "
            f"{metric['unknown_attempts']} unknown."
        )

    cache_ratio = usage["paired_observation_cache_ratio"]
    ratio_text = "unavailable" if cache_ratio is None else str(cache_ratio)
    unknown_reasons = usage["unknown_attempts_by_reason"]
    assert isinstance(unknown_reasons, dict)
    classes = inventory["classes"]
    assert isinstance(classes, dict)
    review_pressure = inventory["review_diff_pressure"]
    assert isinstance(review_pressure, dict)
    declared_context = inventory["declared_context"]
    assert isinstance(declared_context, dict)
    largest = inventory["largest"]
    lines = [
        "# Optimization Report",
        "",
        f"Run: `{report['run_id']}`",
        "Usage scope: controller and nested agents aggregate; role attribution unavailable.",
        metric_line("Input", usage["input"], "observed_tokens", "tokens"),
        metric_line("Cached input", usage["cached_input"], "observed_tokens", "tokens"),
        metric_line(
            "Paired uncached input", usage["uncached_input"],
            "observed_tokens", "tokens",
        ),
        metric_line("Output", usage["output"], "observed_tokens", "tokens"),
        metric_line(
            "Reasoning output", usage["reasoning_output"],
            "observed_tokens", "tokens",
        ),
        metric_line(
            "Launcher prompt", usage["launcher_prompt"],
            "observed_bytes", "bytes",
        ),
        f"Paired cache ratio: {ratio_text}.",
        (
            f"Observed attempt duration: {report['duration_ms']} ms; "
            f"{report['duration_unknown_attempt_count']} attempts unknown."
        ),
        (
            f"Unknown-usage duration: {usage['unknown_attempt_duration_ms']} ms; "
            f"{usage['unknown_attempt_missing_duration_count']} missing durations."
        ),
        "Unknown-usage reasons: "
        + json.dumps(unknown_reasons, sort_keys=True, separators=(",", ":"))
        + ".",
        "",
        "## Verification",
        "",
        f"- Executions: {verification['executions']}",
        f"- Reuses: {verification['reuses']}",
        f"- Uncached executions: {verification['uncached_executions']}",
        "",
        "## Produced Artifact Inventory",
        "",
        f"- Availability: {inventory['availability']}",
        f"- Produced files: {inventory['produced_files']}",
        f"- Produced bytes: {inventory['produced_bytes']}",
        "- Artifact classes: "
        + json.dumps(classes, sort_keys=True, separators=(",", ":"))
        + ".",
        (
            f"- Review-diff pressure: {review_pressure['files']} files, "
            f"{review_pressure['bytes']} bytes, largest "
            f"{review_pressure['largest_bytes']} bytes."
        ),
        (
            "- Largest artifact: unavailable."
            if largest is None
            else (
                f"- Largest artifact: {largest['relative_path']} "
                f"({largest['bytes']} bytes, {largest['class']})."
            )
        ),
        f"- Inventory truncated: {str(inventory['truncated']).lower()}.",
        (
            f"- Declared context: {declared_context['status']} "
            f"({declared_context['reason']}); refs="
            f"{json.dumps(declared_context['refs'])}, bytes="
            f"{json.dumps(declared_context['bytes'])}."
        ),
        "- Measurement: filesystem metadata only; advisory, not model-consumed context.",
        "",
        "## Data Quality Warnings",
        "",
        "Data quality warnings:",
        *(
            [f"- {warning}" for warning in warnings]
            if warnings else ["- None"]
        ),
        "",
        "## Recovery Metrics",
        "",
        f"- Launches avoided: {metrics['launches_avoided']}",
        f"- Local envelope repairs: {metrics['envelope_repairs']}",
        f"- Productive timeouts: {metrics['productive_timeouts']}",
        f"- No-progress slices: {metrics['no_progress_slices']}",
        f"- Budget stops: {metrics['budget_stops']}",
        (
            "- Continuation reasons: " + ", ".join(
                f"{name}={count}" for name, count in reasons.items()
            )
            if reasons else "- Continuation reasons: none"
        ),
        "",
        "## Findings",
        "",
    ]
    findings = report.get("findings", [])
    if not findings:
        lines.append("No optimization findings were derived.")
    else:
        for finding in findings:
            assert isinstance(finding, dict)
            lines.extend([
                f"### {finding.get('signal', finding.get('symptom', 'signal'))}",
                "",
                f"- Source trust: {finding.get('source', 'derived')}",
                f"- Impact: {finding.get('impact', 'unavailable')}",
                f"- Action: {finding.get('action', 'unavailable')}",
                f"- Outcome: {finding.get('outcome', 'unavailable')}",
                f"- Recurrence: {finding.get('recurrence', 'unavailable')}",
                f"- Recommendation: {finding.get('recommendation', 'unavailable')}",
                "- Evidence references: " + ", ".join(
                    str(item) for item in finding.get("evidence_refs", [])
                ),
                "",
            ])
    return "\n".join(lines).rstrip() + "\n"


def write_optimization_reports(
    *,
    reports_root: Path,
    report: dict[str, object],
) -> tuple[Path, Path]:
    validate_optimization_report(report)
    encoded = json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("optimization report exceeds size limit")
    json_path = reports_root / "optimization-report.json"
    md_path = reports_root / "optimization-report.md"
    atomic_private_write(json_path, encoded)
    try:
        markdown = render_optimization_markdown(report).encode("utf-8")
        if len(markdown) > MAX_REPORT_BYTES:
            raise ValueError("optimization markdown exceeds size limit")
        atomic_private_write(md_path, markdown)
    except (OSError, TypeError, ValueError, AssertionError) as exc:
        raise OptimizationMarkdownError(str(exc)) from exc
    return json_path, md_path
