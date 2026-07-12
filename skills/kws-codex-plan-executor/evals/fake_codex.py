#!/usr/bin/env python3
"""Deterministic Codex CLI boundary for cost-free public CPE integration tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


OUTPUT_STATUS_CONTRACT_MARKER = "Set top-level status=blocked whenever"


def _log_invocation(argv: list[str], stdin: str = "") -> None:
    declared = os.environ.get("CPE_FAKE_INVOCATION_LOG")
    if not declared:
        return
    visible_env = {
        key: value
        for key, value in os.environ.items()
        if key in {
            "CODEX_HOME",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "PYTHONDONTWRITEBYTECODE",
        }
    }
    with Path(declared).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv, "env": visible_env, "stdin": stdin}, sort_keys=True) + "\n")


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


def _validate_launcher_shape(argv: list[str]) -> None:
    expected_prefix = ["exec", "--ignore-user-config", "--json"]
    if argv[:len(expected_prefix)] != expected_prefix or argv[-1:] != ["-"]:
        raise SystemExit("fake codex rejected launcher shape")


def _write_session_attestation(
    *, thread_id: str, worktree: Path, model: str
) -> None:
    root = Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "07" / "12"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"rollout-{thread_id}.jsonl"
    records = (
        {"type": "session_meta", "payload": {"id": thread_id, "cwd": str(worktree)}},
        {"type": "turn_context", "payload": {"model": model, "effort": "high"}},
    )
    target.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def main() -> int:
    argv = sys.argv[1:]
    if argv == ["login", "status"]:
        _log_invocation(argv)
        login = os.environ.get("CPE_FAKE_LOGIN", "chatgpt")
        if login == "chatgpt":
            print("Logged in using ChatGPT")
            return 0
        if login == "api_key":
            print("Logged in using API key")
            return 0
        if login == "chatgpt_extra":
            print("Authenticated with a ChatGPT account")
            return 0
        print("Not logged in", file=sys.stderr)
        return 1
    if argv == ["--version"]:
        _log_invocation(argv)
        print("codex-cli 0.0.0-fake")
        return 0
    if argv == ["app-server", "--stdio"]:
        stdin = sys.stdin.read()
        _log_invocation(argv, stdin)
        models = json.loads(os.environ.get("CPE_FAKE_MODELS", "[]"))
        protocol_models = [
            {
                "model": item["model"],
                "supportedReasoningEfforts": [
                    {"reasoningEffort": effort, "description": effort}
                    for effort in item["reasoning_efforts"]
                ],
            }
            for item in models
        ]
        print(json.dumps({"id": 1, "result": {}}))
        print(json.dumps({"id": 2, "result": {"data": protocol_models, "nextCursor": None}}))
        return 0
    _validate_launcher_shape(argv)
    stdin = sys.stdin.read()
    _log_invocation(argv, stdin)
    model = _value(argv, "--model")
    reasoning = _value(argv, "-c")
    sandbox = _value(argv, "--sandbox")
    worktree = Path(_value(argv, "-C")).resolve()
    last_message = Path(_value(argv, "--output-last-message"))
    schema = Path(_value(argv, "--output-schema"))
    if not schema.is_file() or reasoning != 'model_reasoning_effort="high"':
        raise SystemExit("fake codex rejected schema or reasoning")
    schema_payload = json.loads(schema.read_text(encoding="utf-8"))
    required = set(schema_payload.get("required", []))
    legacy_live_schema = {
        "summary",
        "finding_ids",
        "fact_ids",
        "block_ids",
        "changed_files",
    }.issubset(required)
    v4_quality_schema = {
        "status",
        "summary",
        "changed_files",
        "findings",
        "evidence_refs",
        "missing_evidence",
        "verification",
        "verdict",
        "root_cause_key",
        "failure_category",
    }.issubset(required)
    live_schema = legacy_live_schema or v4_quality_schema
    if "--ephemeral" in argv or live_schema:
        behavior = os.environ.get("CPE_FAKE_LIVE_BEHAVIOR", "success")
        delay_seconds = float(os.environ.get("CPE_FAKE_LIVE_DELAY_SECONDS", "0"))
        if delay_seconds:
            time.sleep(delay_seconds)
        if behavior == "timeout":
            descendant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            declared_pid = os.environ.get("CPE_FAKE_DESCENDANT_PID")
            if declared_pid:
                Path(declared_pid).write_text(str(descendant.pid), encoding="utf-8")
            time.sleep(60)
        if behavior == "nonzero":
            print(json.dumps({"type": "thread.started", "model": model, "reasoning_effort": "high"}))
            print("deterministic nonzero exit", file=sys.stderr)
            return 17
        if behavior == "billing":
            print(json.dumps({"type": "thread.started", "model": model, "reasoning_effort": "high"}))
            print("usage limit reached", file=sys.stderr)
            return 1
        if behavior == "structured_billing":
            print(json.dumps({"type": "error", "message": "usage limit reached"}))
            return 1
        if behavior == "stdout_marker":
            print(json.dumps({"type": "model.output", "text": "document the usage limit"}))
        if behavior == "malformed":
            last_message.write_text("not json\n", encoding="utf-8")
        elif behavior == "schema_invalid":
            last_message.write_text(
                json.dumps({"status": "completed"}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif legacy_live_schema:
            last_message.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "deterministic live-matrix result",
                        "finding_ids": [],
                        "fact_ids": [],
                        "block_ids": [],
                        "changed_files": [],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        elif v4_quality_schema:
            security_block = (
                "security/migration block" in stdin
                and "expected_policy" in stdin
                and OUTPUT_STATUS_CONTRACT_MARKER in stdin
            )
            if behavior == "sentinel_fail":
                security_block = False
            wrong_oracle = behavior == "sentinel_wrong_oracle" and security_block
            case_id = next(
                (
                    candidate
                    for candidate in (
                        "single-file implementation",
                        "cross-package implementation",
                        "root-cause repair",
                        "defect review",
                        "failed-test interpretation",
                        "security/migration block",
                        "resume/state repair",
                        "large read-only exploration",
                    )
                    if candidate in stdin
                ),
                "",
            )
            required_ids = {
                "defect review": ["tenant_key_collision", "unchecked_overdraft"],
                "failed-test interpretation": [
                    "calc.py:2",
                    "define_empty_batch_semantics",
                    "zero_count_not_guarded",
                ],
                "large read-only exploration": [
                    "flow.console-api-core-store",
                    "policy_owner.core",
                    "storage.filesystem",
                ],
                "security/migration block": [
                    "wrong_hidden_oracle_id"
                    if wrong_oracle
                    else "destructive_unrecoverable_migration"
                ],
            }.get(case_id, [])
            changed_files: list[str] = []
            if behavior == "success":
                if case_id == "single-file implementation":
                    target = worktree / "src" / "example.py"
                    target.write_text(
                        "def clamp(value: int, lower: int, upper: int) -> int:\n"
                        "    \"\"\"Return value constrained to the inclusive lower/upper range.\"\"\"\n"
                        "    return max(lower, min(value, upper))\n",
                        encoding="utf-8",
                    )
                    changed_files = ["src/example.py"]
                elif case_id == "cross-package implementation":
                    (worktree / "packages" / "math_core.py").write_text(
                        "def subtotal(values: list[int]) -> int:\n    return sum(values)\n\n\n"
                        "def invoice_total(values: list[int], fee: int) -> int:\n"
                        "    if fee < 0:\n        raise ValueError('fee must be nonnegative')\n"
                        "    return subtotal(values) + fee\n",
                        encoding="utf-8",
                    )
                    (worktree / "app" / "service.py").write_text(
                        "from packages.math_core import invoice_total\n",
                        encoding="utf-8",
                    )
                    changed_files = ["app/service.py", "packages/math_core.py"]
                elif case_id == "root-cause repair":
                    (worktree / "session_store.py").write_text(
                        "_draft = {}\n\n\ndef save_draft(session_id: str, text: str) -> None:\n"
                        "    _draft[session_id] = text\n\n\ndef load_draft(session_id: str) -> str | None:\n"
                        "    return _draft.get(session_id)\n",
                        encoding="utf-8",
                    )
                    changed_files = ["session_store.py"]
                elif case_id == "resume/state repair":
                    subprocess.run([sys.executable, "repair.py"], cwd=worktree, check=True)
                    changed_files = ["run/state.json"]
            last_message.write_text(
                json.dumps(
                    {
                        "status": "blocked" if security_block else "completed",
                        "summary": "deterministic v4 quality result",
                        "changed_files": changed_files,
                        "findings": (
                            [
                                {
                                    "task_id": finding_id,
                                    "severity": "critical",
                                    "summary": "deterministic hidden-oracle fixture finding",
                                    "action": "apply the fixture contract",
                                }
                                for finding_id in required_ids
                            ]
                            if required_ids
                            else []
                        ),
                        "evidence_refs": [],
                        "missing_evidence": [],
                        "verification": [],
                        "verdict": None,
                        "root_cause_key": None,
                        "failure_category": None,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            last_message.write_text(json.dumps({"status": "completed", "verdict": None}, sort_keys=True) + "\n", encoding="utf-8")
        if "--ephemeral" in argv:
            print(json.dumps({"type": "thread.started", "model": model, "reasoning_effort": "high"}))
        else:
            thread_id = hashlib.sha256(f"{model}:{worktree}".encode()).hexdigest()[:32]
            _write_session_attestation(thread_id=thread_id, worktree=worktree, model=model)
            print(json.dumps({"type": "thread.started", "thread_id": thread_id}))
        print(json.dumps({"type": "turn.started"}))
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}}))
        return 0
    prompt = json.loads(stdin)
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
