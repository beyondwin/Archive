from __future__ import annotations

import json
from pathlib import Path

from .events import read_events
from .manifest import load_manifest, resolve_ref
from .projector import project
from .reconciliation import reconcile
from .validation import validate_run


def _cost(usage: dict[str, int], manifest: dict) -> dict[str, object]:
    record = manifest.get("pricing_snapshot") or {}
    try:
        pricing = json.loads(resolve_ref(str(record["ref"])).read_text(encoding="utf-8"))
        rates = pricing["models"]["gpt-5.6-sol"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return {"estimated_cost_usd": None, "short_context_cost_usd": None, "long_context_cost_usd": None}

    def calculate(kind: str) -> float:
        rate = rates[kind]
        uncached = max(0, usage["input_tokens"] - usage["cached_input_tokens"])
        total = (
            uncached * float(rate["input"])
            + usage["cached_input_tokens"] * float(rate["cached_input"])
            + usage["output_tokens"] * float(rate["output"])
        ) / 1_000_000
        return round(total, 8)

    return {
        "estimated_cost_usd": None,
        "short_context_cost_usd": calculate("short_context"),
        "long_context_cost_usd": calculate("long_context"),
    }


def inspect_run(run_dir: Path) -> dict[str, object]:
    run_dir = run_dir.expanduser().resolve()
    validation = validate_run(run_dir)
    if validation.classification == "unsupported_schema":
        return {"run_id": run_dir.name, "classification": "unsupported_schema", "passed": False}
    try:
        manifest = load_manifest(run_dir / "run_manifest.json")
        state = project(manifest, read_events(run_dir / "events.jsonl"))
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "run_id": run_dir.name,
            "classification": validation.classification,
            "passed": False,
            "errors": validation.errors,
        }
    attempts = state.get("attempts") or []
    core_attempts = [item for item in attempts if item.get("kind") != "scout"]
    attested = [item for item in core_attempts if (item.get("attestation") or {}).get("verified") is True]
    repairs = [item for item in attempts if item.get("kind") == "repair"]
    usage = state.get("usage_totals") or {}
    lifecycle = state.get("lifecycle")
    reconciliation = reconcile(run_dir)
    result: dict[str, object] = {
        "run_id": manifest["run_id"],
        "classification": validation.classification,
        "passed": validation.passed,
        "lifecycle": lifecycle,
        "task_count": len(state.get("tasks") or {}),
        "completed_task_count": sum(1 for item in state.get("tasks", {}).values() if item.get("status") == "completed"),
        "first_pass_success": lifecycle == "completed" and not repairs,
        "repair_count": len(repairs),
        "model_attestation_success_rate": len(attested) / len(core_attempts) if core_attempts else 0.0,
        "input_tokens": int(usage.get("input_tokens", 0)),
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "reasoning_output_tokens": int(usage.get("reasoning_output_tokens", 0)),
        "latency_ms": sum(int(item.get("latency_ms", 0) or 0) for item in attempts),
        "environment_failure_count": sum(1 for item in attempts if item.get("failure_category") == "environment"),
        "drift_count": int(reconciliation.classification != "clean"),
        "missing_evidence_count": sum(1 for code in validation.errors if code == "evidence_missing"),
        "errors": validation.errors,
        "reconciliation": reconciliation.as_dict(),
    }
    result.update(_cost({key: int(result[key]) for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")}, manifest))
    return result


def inspect_recent(codex_home: Path, limit: int) -> dict[str, object]:
    root = codex_home.expanduser().resolve() / "orchestrator"
    paths = sorted((path for path in root.glob("*") if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)[:limit] if root.exists() else []
    items = [inspect_run(path) for path in paths]
    supported = [item for item in items if item.get("classification") != "unsupported_schema"]
    completed = [item for item in supported if item.get("lifecycle") == "completed"]
    costs = [float(item["short_context_cost_usd"]) for item in supported if item.get("short_context_cost_usd") is not None]
    return {
        "run_count": len(items),
        "completed_count": len(completed),
        "blocked_count": sum(1 for item in supported if item.get("lifecycle") == "blocked"),
        "failed_count": sum(1 for item in supported if item.get("lifecycle") == "failed"),
        "first_pass_success_rate": sum(1 for item in completed if item.get("first_pass_success")) / len(completed) if completed else 0.0,
        "average_repair_attempts": sum(int(item.get("repair_count", 0)) for item in supported) / len(supported) if supported else 0.0,
        "model_attestation_success_rate": sum(float(item.get("model_attestation_success_rate", 0)) for item in supported) / len(supported) if supported else 0.0,
        "input_tokens": sum(int(item.get("input_tokens", 0)) for item in supported),
        "cached_input_tokens": sum(int(item.get("cached_input_tokens", 0)) for item in supported),
        "output_tokens": sum(int(item.get("output_tokens", 0)) for item in supported),
        "reasoning_output_tokens": sum(int(item.get("reasoning_output_tokens", 0)) for item in supported),
        "estimated_cost_usd": round(sum(costs), 8) if costs else None,
        "average_latency_ms": sum(int(item.get("latency_ms", 0)) for item in supported) / len(supported) if supported else 0.0,
        "environment_failure_count": sum(int(item.get("environment_failure_count", 0)) for item in supported),
        "drift_count": sum(int(item.get("drift_count", 0)) for item in supported),
        "repair_count": sum(int(item.get("repair_count", 0)) for item in supported),
        "missing_evidence_count": sum(int(item.get("missing_evidence_count", 0)) for item in supported),
        "unsupported_schema_count": sum(1 for item in items if item.get("classification") == "unsupported_schema"),
        "runs": items,
    }
