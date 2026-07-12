#!/usr/bin/env python3
"""Deterministic checks for command-level CPE v4 method evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from cpe_runtime.command_evidence import (  # noqa: E402
    MethodEvidenceError,
    build_method_evidence,
    normalize_codex_items,
)
from cpe_runtime.evidence import verify_ref  # noqa: E402
from cpe_runtime.worker import Worker, WorkerError, WorkerRequest  # noqa: E402


TEST_COMMAND = (
    "python3 /Users/example/private/.superpowers/sdd/hidden-oracle.py "
    "sk-secret-marker ghp_examplecredentialmarker"
)


def command_event(*, exit_code: int, status: str, output: str) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "id": f"command-{exit_code}-{status}",
            "type": "command_execution",
            "command": TEST_COMMAND,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": status,
        },
    }


def mutation_event() -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "id": "mutation-1",
            "type": "file_change",
            "changes": [{"path": "/Users/example/private/product.py", "kind": "update"}],
            "status": "completed",
        },
    }


def raises(expected: type[BaseException], fn) -> BaseException:
    try:
        fn()
    except expected as exc:
        return exc
    raise AssertionError(f"expected {expected.__name__}")


def valid_events() -> list[dict[str, object]]:
    return [
        command_event(
            exit_code=1,
            status="failed",
            output="FAILED /Users/example/private/test_product.py\nsk-secret-marker\n",
        ),
        mutation_event(),
        command_event(
            exit_code=0,
            status="completed",
            output="PASSED /Users/example/private/test_product.py\nsk-secret-marker\n",
        ),
    ]


def result_payload(method_evidence_ref: object = None) -> dict[str, object]:
    return {
        "status": "completed",
        "summary": "implemented with RED and GREEN",
        "changed_files": ["product.py"],
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": None,
        "method_evidence_ref": method_evidence_ref,
    }


def worker_request(run_dir: Path, task_type: str) -> WorkerRequest:
    packet = run_dir / "artifacts" / "task-packets" / "T1.json"
    packet.parent.mkdir(parents=True)
    packet_bytes = (
        json.dumps({"task_contract": {"task_type": task_type}}, sort_keys=True) + "\n"
    ).encode("utf-8")
    packet.write_bytes(packet_bytes)
    return WorkerRequest(
        attempt_id="T1.implementation.1",
        attempt_kind="implementation",
        prompt="implement",
        worktree=run_dir.parent / "worktree",
        read_only=False,
        verdict_capable=False,
        task_id="T1",
        packet_path=str(packet),
        packet_sha256=hashlib.sha256(packet_bytes).hexdigest(),
    )


def provider(events: list[dict[str, object]], payload: dict[str, object]):
    return lambda _request, _argv: {
        "result": payload,
        "events": events,
        "provider_metadata": {
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "trusted_source": "codex_cli_jsonl",
        },
    }


def main() -> int:
    observations = normalize_codex_items(valid_events())
    evidence = build_method_evidence("tdd_implementation", observations)
    assert evidence.red is not None and evidence.red.exit_code == 1
    assert evidence.red.before_first_mutation is True
    assert evidence.green is not None and evidence.green.exit_code == 0
    assert evidence.green.before_first_mutation is False
    assert evidence.red.command == evidence.green.command
    assert len(evidence.observations_sha256) == 64

    serialized = json.dumps(asdict(evidence), sort_keys=True)
    for forbidden in (
        "/Users/example",
        "sk-secret-marker",
        "ghp_examplecredentialmarker",
        ".superpowers/sdd",
        "hidden-oracle.py",
        "FAILED",
        "PASSED",
    ):
        assert forbidden not in serialized, (forbidden, serialized)
    assert all(len(item.output_sha256) == 64 for item in observations)
    assert [item.sequence for item in observations] == [0, 2]

    summary_only = [
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": "RED exited 1 before edits and GREEN exited 0",
            },
        }
    ]
    raises(
        MethodEvidenceError,
        lambda: build_method_evidence(
            "tdd_implementation", normalize_codex_items(summary_only)
        ),
    )
    raises(
        MethodEvidenceError,
        lambda: build_method_evidence(
            "tdd_implementation",
            normalize_codex_items([mutation_event(), *valid_events()]),
        ),
    )
    raises(
        MethodEvidenceError,
        lambda: build_method_evidence(
            "tdd_implementation", normalize_codex_items(valid_events()[:2])
        ),
    )
    for exit_code, status in ((1, "completed"), (0, "failed")):
        events = [command_event(exit_code=exit_code, status=status, output="x")]
        raises(
            MethodEvidenceError,
            lambda events=events: build_method_evidence(
                "tdd_implementation", normalize_codex_items(events)
            ),
        )

    non_tdd = build_method_evidence("non_tdd_implementation", observations)
    assert non_tdd.red is None and non_tdd.green is None

    schema = json.loads((SKILL / "templates" / "worker-result-schema.json").read_text())
    assert "method_evidence_ref" in schema["required"]
    assert "method_evidence_ref" in schema["properties"]

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        run_dir = root / "run"
        request = worker_request(run_dir, "tdd_implementation")
        result = Worker(provider=provider(valid_events(), result_payload())).run(request)
        ref = result.payload.get("method_evidence_ref")
        assert isinstance(ref, dict), result.payload
        assert verify_ref(run_dir, ref) == []
        artifact = (run_dir / str(ref["path"])).read_text(encoding="utf-8")
        assert "/Users/example" not in artifact
        assert "sk-secret-marker" not in artifact
        assert ".superpowers/sdd" not in artifact

    with tempfile.TemporaryDirectory() as raw:
        request = worker_request(Path(raw) / "run", "tdd_implementation")
        worker = Worker(provider=provider(summary_only, result_payload()))
        error = raises(WorkerError, lambda: worker.run(request))
        assert "method_contract_failed" in str(error), error

    with tempfile.TemporaryDirectory() as raw:
        request = worker_request(Path(raw) / "run", "non_tdd_implementation")
        fabricated = {"kind": "method_evidence", "path": "fake", "sha256": "0" * 64}
        worker = Worker(provider=provider([], result_payload(fabricated)))
        error = raises(WorkerError, lambda: worker.run(request))
        assert "fabricated_method_evidence" in str(error), error

    with tempfile.TemporaryDirectory() as raw:
        request = worker_request(Path(raw) / "run", "tdd_implementation")
        Path(request.packet_path).write_text(
            json.dumps(
                {"task_contract": {"task_type": "non_tdd_implementation"}},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        worker = Worker(provider=provider([], result_payload()))
        error = raises(WorkerError, lambda: worker.run(request))
        assert "method_contract_packet_digest_mismatch" in str(error), error

    with tempfile.TemporaryDirectory() as raw:
        request = worker_request(Path(raw) / "run", "tdd_implementation")
        packet_bytes = b'{"task_contract":{}}\n'
        Path(request.packet_path).write_bytes(packet_bytes)
        request = replace(
            request,
            packet_sha256=hashlib.sha256(packet_bytes).hexdigest(),
        )
        worker = Worker(provider=provider([], result_payload()))
        error = raises(WorkerError, lambda: worker.run(request))
        assert "method_contract_task_type_missing" in str(error), error

    print(json.dumps({"passed": True, "observations": len(observations)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
