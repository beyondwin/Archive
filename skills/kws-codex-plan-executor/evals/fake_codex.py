#!/usr/bin/env python3
"""Deterministic Codex CLI boundary for cost-free public CPE integration tests."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def _value(argv: list[str], flag: str) -> str:
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"fake codex missing launcher argument: {flag}") from exc


def _packet(prompt: dict[str, object]) -> tuple[Path, dict[str, object]]:
    declared = Path(str(prompt.get("packet_path") or "")).expanduser()
    expected = str(prompt.get("packet_sha256") or "")
    packet_root = (Path(os.environ["CODEX_HOME"]).resolve() / "orchestrator").resolve()
    path = declared.resolve()
    if not path.is_relative_to(packet_root) or not path.is_file():
        raise SystemExit("fake codex could not resolve one packet")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise SystemExit("fake codex rejected packet digest")
    payload = json.loads(raw)
    if payload.get("task_id") != prompt.get("task_id"):
        raise SystemExit("fake codex rejected packet task binding")
    return path, payload


def main() -> int:
    argv = sys.argv[1:]
    if (
        len(argv) < 3
        or argv[:3] != ["exec", "--ignore-user-config", "--json"]
        or argv[-1] != "-"
    ):
        raise SystemExit("fake codex rejected launcher shape")
    model = _value(argv, "--model")
    reasoning = _value(argv, "-c")
    sandbox = _value(argv, "--sandbox")
    worktree = Path(_value(argv, "-C")).resolve()
    last_message = Path(_value(argv, "--output-last-message"))
    schema = Path(_value(argv, "--output-schema"))
    if not schema.is_file() or reasoning != 'model_reasoning_effort="high"':
        raise SystemExit("fake codex rejected schema or reasoning")
    prompt = json.loads(sys.stdin.read())
    packet_path, packet = _packet(prompt)
    case = json.loads(Path(os.environ["CPE_FAKE_CASE_FILE"]).read_text(encoding="utf-8"))
    instruction = str(prompt.get("instruction") or "")
    lowered = instruction.lower()
    if lowered.startswith("implement"):
        role = "implementation"
    elif lowered.startswith("review task"):
        role = "task_review"
    elif lowered.startswith("verify"):
        role = "verification"
    elif lowered.startswith("repair"):
        role = "repair"
    elif lowered.startswith("review the complete diff"):
        role = "final_review"
    elif "scout" in lowered:
        role = "scout"
    else:
        raise SystemExit("fake codex rejected unknown instruction role")
    if case.get("transient_exit_role") == role:
        print(f"deterministic transient interruption: {role}", file=sys.stderr)
        return 75
    changed: list[str] = []
    if role in {"implementation", "repair"} and case.get("write_claimed_file", False):
        allowed = packet.get("execution_contract", {}).get("allowed_edits", [])
        target = str(allowed[0]) if allowed else ""
        if not target or any(token in target for token in ("*", "?", "[")):
            raise SystemExit("fake codex requires one exact allowed edit")
        output = worktree / target
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(str(case.get("implementation_content", "implemented by fake codex\n")), encoding="utf-8")
        changed = [target]
    if case.get("mutate_packet_after_verification") and role == "implementation":
        packet_path.chmod(0o600)
        packet_path.write_bytes(packet_path.read_bytes() + b"\n")
    verdict = None
    if role in {"task_review", "verification", "final_review"}:
        verdict = {
            "status": "passed",
            "findings": [],
            "missing_evidence": [],
            "worktree_revision": int(prompt.get("worktree_revision", 0)),
        }
    result = {
        "status": "completed",
        "summary": f"deterministic {role}",
        "changed_files": changed,
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": verdict,
    }
    if case.get("invalid_last_message"):
        last_message.write_text("not json\n", encoding="utf-8")
    else:
        last_message.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"type": "thread.started", "model": model, "reasoning_effort": "high"}))
    print(json.dumps({"type": "turn.started"}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
