#!/usr/bin/env python3
"""Check compatibility with the current Codex CLI evidence surfaces."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from cpe_runtime.worker import _read_session_attestation  # noqa: E402


def main() -> int:
    schema = json.loads(
        (SKILL_DIR / "templates" / "worker-result-schema.json").read_text(
            encoding="utf-8"
        )
    )
    arrays_have_items = all(
        isinstance(value.get("items"), dict) and "type" in value["items"]
        for value in schema["properties"].values()
        if value.get("type") == "array"
    ) and all(
        isinstance(value.get("items"), dict) and "type" in value["items"]
        for branch in schema["properties"]["verdict"].get("anyOf", [])
        if branch.get("type") == "object"
        for value in branch["properties"].values()
        if value.get("type") == "array"
    )

    with tempfile.TemporaryDirectory(prefix="cpe-cli-compat-") as raw:
        codex_home = Path(raw) / "codex-home"
        workspace = Path(raw) / "workspace"
        workspace.mkdir()
        session_dir = codex_home / "sessions" / "2026" / "07" / "11"
        session_dir.mkdir(parents=True)
        thread_id = "019f4fba-940e-7f71-bcda-6e9c32f26853"
        session = session_dir / f"rollout-test-{thread_id}.jsonl"
        records = [
            {
                "type": "session_meta",
                "payload": {"id": thread_id, "cwd": str(workspace)},
            },
            {
                "type": "turn_context",
                "payload": {
                    "cwd": str(workspace),
                    "model": "gpt-5.6-sol",
                    "effort": "high",
                },
            },
        ]
        session.write_text(
            "".join(json.dumps(item) + "\n" for item in records),
            encoding="utf-8",
        )
        attestation = _read_session_attestation(
            codex_home=codex_home,
            thread_id=thread_id,
            worktree=workspace,
        )

    checks = {
        "structured_output_arrays_have_items": arrays_have_items,
        "structured_output_uses_supported_union": (
            "anyOf" in schema["properties"]["verdict"]
            and "oneOf" not in schema["properties"]["verdict"]
        ),
        "session_model_attested": attestation.get("model") == "gpt-5.6-sol",
        "session_reasoning_attested": attestation.get("reasoning") == "high",
        "session_source_trusted": (
            attestation.get("trusted_source") == "codex_session_jsonl"
        ),
    }
    print(json.dumps(checks, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
