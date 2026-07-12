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
from cpe_runtime.evidence import verify_method_evidence_ref, verify_ref  # noqa: E402
from cpe_runtime.worker import Worker, WorkerError, WorkerRequest  # noqa: E402


TEST_COMMAND = "python3 evals/check_method_evidence_v4.py"
CONTRACT_SHA256 = "c" * 64


def command_event(
    *, exit_code: int, status: str, output: str, command: str = TEST_COMMAND
) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "id": f"command-{exit_code}-{status}",
            "type": "command_execution",
            "command": command,
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
        json.dumps(
            {
                "task_id": "T1",
                "task_contract": {
                    "task_id": "T1",
                    "task_type": task_type,
                    "acceptance_commands": [TEST_COMMAND],
                },
                "task_contract_sha256": CONTRACT_SHA256,
            },
            sort_keys=True,
        )
        + "\n"
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


def normalize(events: list[dict[str, object]] | tuple[dict[str, object], ...]):
    return normalize_codex_items(events, test_commands=(TEST_COMMAND,))


def main() -> int:
    observations = normalize(valid_events())
    evidence = build_method_evidence("tdd_implementation", observations)
    assert evidence.red is not None and evidence.red.exit_code == 1
    assert evidence.red.before_first_mutation is True
    assert evidence.green is not None and evidence.green.exit_code == 0
    assert evidence.green.before_first_mutation is False
    assert evidence.red.command == evidence.green.command
    assert evidence.red.command == "python3 test-script <args>"
    assert evidence.red.command_kind == evidence.green.command_kind == "test"
    assert evidence.red.command_sha256 == evidence.green.command_sha256
    assert len(evidence.red.command_sha256) == 64
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

    review_failures: list[str] = []
    for mutating_command in (
        "printf 'implemented' > product.py",
        "sed -i '' 's/old/new/' product.py",
        "sed -n 'w product.py' input.txt",
        "git diff --output=product.py",
        "python3 check_mutation.py",
    ):
        bypass_events = [
            command_event(
                command=mutating_command,
                exit_code=0,
                status="completed",
                output="",
            ),
            *valid_events(),
        ]
        try:
            build_method_evidence(
                "tdd_implementation", normalize(bypass_events)
            )
        except MethodEvidenceError:
            pass
        else:
            review_failures.append(f"mutation_order_bypass:{mutating_command}")

    for wrapped_command in (
        "env bash -c 'python3 mutate_then_fail.py'",
        "python3 -c 'raise SystemExit(1)'",
        "xargs python3 test_product.py",
        "node test_product.js",
    ):
        wrapped_events = [
            command_event(
                command=wrapped_command,
                exit_code=1,
                status="failed",
                output="",
            ),
            mutation_event(),
            command_event(
                command=wrapped_command,
                exit_code=0,
                status="completed",
                output="",
            ),
        ]
        try:
            build_method_evidence(
                "tdd_implementation",
                normalize_codex_items(
                    wrapped_events, test_commands=(wrapped_command,)
                ),
            )
        except MethodEvidenceError:
            pass
        else:
            review_failures.append(
                f"wrapped_contract_command_accepted:{wrapped_command}"
            )

    credential_commands = {
        "flag-token-value": f"{TEST_COMMAND} --token flag-token-value",
        "basic-password": f"{TEST_COMMAND} https://basic-user:basic-password@example.test/x",
        "db-password": f"{TEST_COMMAND} postgres://db-user:db-password@db.example.test/app",
        "opaque-provider-token-4fa8b9c7": (
            f"{TEST_COMMAND} opaque-provider-token-4fa8b9c7"
        ),
    }
    for marker, command in credential_commands.items():
        encoded = json.dumps(
            asdict(
                normalize(
                    [command_event(command=command, exit_code=1, status="failed", output="")]
                )[0]
            ),
            sort_keys=True,
        )
        if marker in encoded:
            review_failures.append(f"credential_persisted:{marker}")
        for raw_argument in ("example.test", "basic-user", "db-user"):
            if raw_argument in encoded:
                review_failures.append(f"raw_argument_persisted:{raw_argument}")
    assert not review_failures, review_failures

    for direct_test_command in (
        TEST_COMMAND,
        "python3 -m pytest tests/test_product.py",
        "python3 -m unittest tests.test_product",
        "pytest tests/test_product.py",
        "bun test tests/product.test.ts",
    ):
        direct_events = [
            command_event(
                command=direct_test_command,
                exit_code=1,
                status="failed",
                output="",
            ),
            mutation_event(),
            command_event(
                command=direct_test_command,
                exit_code=0,
                status="completed",
                output="",
            ),
        ]
        direct_evidence = build_method_evidence(
            "tdd_implementation",
            normalize_codex_items(
                direct_events, test_commands=(direct_test_command,)
            ),
        )
        assert direct_evidence.red is not None, direct_test_command
        assert direct_evidence.green is not None, direct_test_command

    raises(
        MethodEvidenceError,
        lambda: build_method_evidence(
            "tdd_implementation",
            normalize(
                [
                    command_event(
                        command=f"{TEST_COMMAND} --token first-value",
                        exit_code=1,
                        status="failed",
                        output="",
                    ),
                    mutation_event(),
                    command_event(
                        command=f"{TEST_COMMAND} --token substituted-value",
                        exit_code=0,
                        status="completed",
                        output="",
                    ),
                ]
            ),
        ),
    )

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
            "tdd_implementation", normalize(summary_only)
        ),
    )
    raises(
        MethodEvidenceError,
        lambda: build_method_evidence(
            "tdd_implementation",
            normalize([mutation_event(), *valid_events()]),
        ),
    )
    raises(
        MethodEvidenceError,
        lambda: build_method_evidence(
            "tdd_implementation", normalize(valid_events()[:2])
        ),
    )
    for exit_code, status in ((1, "completed"), (0, "failed")):
        events = [command_event(exit_code=exit_code, status=status, output="x")]
        raises(
            MethodEvidenceError,
            lambda events=events: build_method_evidence(
                "tdd_implementation", normalize(events)
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
        assert ref["task_id"] == request.task_id
        assert ref["packet_sha256"] == request.packet_sha256
        assert ref["contract_sha256"] == CONTRACT_SHA256
        assert verify_ref(run_dir, ref) == []
        binding = {
            "task_id": request.task_id,
            "packet_sha256": request.packet_sha256,
            "contract_sha256": CONTRACT_SHA256,
        }
        assert verify_method_evidence_ref(run_dir, ref, **binding) == []
        artifact = (run_dir / str(ref["path"])).read_text(encoding="utf-8")
        artifact_payload = json.loads(artifact)
        assert artifact_payload["task_id"] == request.task_id
        assert artifact_payload["packet_sha256"] == request.packet_sha256
        assert artifact_payload["contract_sha256"] == CONTRACT_SHA256
        assert "/Users/example" not in artifact
        assert "sk-secret-marker" not in artifact
        assert ".superpowers/sdd" not in artifact
        substitutions = {
            "task_id": "T2",
            "packet_sha256": "d" * 64,
            "contract_sha256": "e" * 64,
        }
        for field, substitute in substitutions.items():
            forged_ref = {**ref, field: substitute}
            assert verify_method_evidence_ref(run_dir, forged_ref, **binding), field
            forged_binding = {**binding, field: substitute}
            assert verify_method_evidence_ref(run_dir, ref, **forged_binding), field
            assert verify_method_evidence_ref(
                run_dir, forged_ref, **forged_binding
            ), field

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
