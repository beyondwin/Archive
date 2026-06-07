#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"JSON is not readable: {path}: {exc}")
    if not isinstance(data, dict):
        die(f"JSON must be an object: {path}")
    return data


def root_signature(observation: dict) -> str:
    command = str(observation.get("command", "")).strip()
    category = str(observation.get("category", "unknown")).strip()
    evidence = str(observation.get("evidence", "")).strip().splitlines()[0:1]
    raw = "|".join([category, command, evidence[0] if evidence else ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def attempts_for(state: dict, signature: str) -> int:
    attempts = state.get("recovery_attempts", [])
    if not isinstance(attempts, list):
        return 0
    return sum(1 for item in attempts if isinstance(item, dict) and item.get("root_signature") == signature)


def classify(state: dict, task_id: str, observation: dict) -> dict:
    category = str(observation.get("category", "unknown"))
    signature = root_signature(observation)
    count = attempts_for(state, signature)
    command = str(observation.get("command", "")).strip()

    payload = {
        "schema_version": "1",
        "task_id": task_id,
        "category": "transient_tooling_or_resource",
        "subtype": category,
        "root_signature": signature,
        "retry_count": count,
        "retry_budget": 0,
        "next_command": command,
    }

    if category == "dependency_bootstrap":
        if count == 0:
            payload.update({"decision": "bootstrap", "retry_budget": 1, "next_action_kind": "bootstrap"})
        else:
            payload.update({"decision": "block", "category": "workspace_precondition", "next_action_kind": "block"})
    elif category in {"flaky_test", "timeout_or_hang"}:
        payload["retry_budget"] = 2
        if count < 2:
            payload.update({"decision": "retry", "next_action_kind": "retry"})
        else:
            payload.update({"decision": "failed", "category": "transient_tooling_or_resource", "next_action_kind": "fail"})
    elif category == "source_failure":
        payload.update({"decision": "continue", "category": "execution_source_failure", "next_action_kind": "continue"})
    elif category == "permission_or_sandbox":
        payload.update({"decision": "block", "category": "workspace_precondition", "next_action_kind": "block"})
    elif "outside scope" in str(observation.get("evidence", "")).lower() or "diff_scope" in str(observation.get("evidence", "")).lower():
        payload.update({"decision": "block", "category": "diff_scope_gap", "next_action_kind": "block"})
    elif category == "unknown":
        payload["retry_budget"] = 1
        if count < 1:
            payload.update({"decision": "retry", "category": "observability_degraded", "next_action_kind": "retry"})
        else:
            payload.update({"decision": "failed", "category": "observability_degraded", "next_action_kind": "fail"})
    else:
        payload.update({"decision": "block", "category": "observability_degraded", "next_action_kind": "block"})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify command observation recovery action.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = classify(load_json(Path(args.state)), args.task_id, load_json(Path(args.observation)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
