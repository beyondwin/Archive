#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.prompt_bundles import (
    CONTROL_SOURCE_COMMIT,
    PromptBundleError,
    build_candidate_bundle,
    build_control_bundle,
    paired_bundles,
)
from cpe_runtime.task_contracts import compile_task_contract


SPEC_TEXT = "## S1.12 Active Model Policy\nOnly Sol/high may implement or decide.\n"
SPEC_SHA256 = hashlib.sha256(SPEC_TEXT.encode()).hexdigest()


def fixture_contract():
    task_source = """### Task 7: Prompt bundle

```python
assert paired_bundles(contract)
```
"""
    return compile_task_contract(
        {
            "id": "task_7",
            "title": "Prompt bundle",
            "task_type": "tdd_implementation",
            "task_source": task_source,
            "file_claims": ["src/prompt.py"],
            "forbidden_paths": ["events.jsonl"],
            "acceptance_commands": ["python3 check_prompt.py"],
            "checkpoint_message": "feat: prompt bundle",
        },
        spec_sections=({"id": "S1.12", "sha256": SPEC_SHA256, "text": SPEC_TEXT},),
        source_hashes={"plan": "1" * 64, "spec_sections": {"S1.12": SPEC_SHA256}},
    )


def rejected(callable_) -> bool:
    try:
        callable_()
    except PromptBundleError:
        return True
    return False


def accepted(callable_) -> bool:
    try:
        callable_()
    except PromptBundleError:
        return False
    return True


def main() -> int:
    checks: dict[str, bool] = {}
    contract = fixture_contract()
    prior_findings = ({"finding_id": "F-1", "summary": "old finding"},)
    finding_delta = ({"finding_id": "F-1", "status": "repaired"},)
    bounded_context = ({"path": "src/prompt.py", "content": "def build(): ...\n"},)
    control, candidate = paired_bundles(
        contract,
        prior_findings=prior_findings,
        finding_delta=finding_delta,
        bounded_context=bounded_context,
    )

    checks["paired_sol_high"] = (
        control.model == candidate.model == "gpt-5.6-sol"
        and control.reasoning == candidate.reasoning == "high"
        and control.role == candidate.role == "implementation"
    )
    checks["paired_case_and_schema"] = (
        control.case_sha256 == candidate.case_sha256
        and control.output_schema_sha256 == candidate.output_schema_sha256
        and control.task_contract_sha256 == candidate.task_contract_sha256 == contract.contract_sha256
    )
    checks["distinct_real_prompts"] = (
        control.prompt_sha256 != candidate.prompt_sha256
        and len(control.prompt) > 500
        and len(candidate.prompt) > 500
        and "scheduler_instruction" in control.prompt
        and "task_contract" in candidate.prompt
        and "result_schema" in candidate.prompt
        and json.dumps(contract.task_source, ensure_ascii=False)[1:-1] in candidate.prompt
        and json.dumps(SPEC_TEXT, ensure_ascii=False)[1:-1] in candidate.prompt
    )
    checks["candidate_has_bounded_repair_context"] = all(
        marker in candidate.prompt
        for marker in ("prior_findings", "finding_delta", "bounded_visible_context", "F-1", "src/prompt.py")
    )
    checks["control_is_pinned_production_shape"] = all(
        marker in control.prompt
        for marker in (
            CONTROL_SOURCE_COMMIT,
            "scheduler_instruction",
            "packet_bytes",
            "spec_sections",
            "prior_task_evidence",
            "result_contract",
            "$WORKTREE",
            "$RUN_DIR",
        )
    )
    forbidden = ("/private/", "/Users/", "/tmp/", "transcript", "fallback")
    checks["sanitized_and_no_legacy_route"] = all(
        token not in control.prompt and token not in candidate.prompt for token in forbidden
    )

    fixture_path = SKILL_ROOT / "evals" / "control-bundles" / "cpe-3.1.0-production.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    mutations = {
        "commit_drift_rejected": ("source_commit", "0" * 40),
        "scheduler_drift_rejected": ("scheduler_sha256", "0" * 64),
        "packet_drift_rejected": ("packet_sha256", "0" * 64),
        "output_schema_drift_rejected": ("output_schema_sha256", "0" * 64),
    }
    with tempfile.TemporaryDirectory(prefix="cpe-v4-control-check-") as raw:
        for name, (key, value) in mutations.items():
            mutated = json.loads(json.dumps(fixture))
            mutated[key] = value
            path = Path(raw) / f"{name}.json"
            path.write_text(json.dumps(mutated), encoding="utf-8")
            checks[name] = rejected(lambda path=path: build_control_bundle(contract, fixture_path=path))

        label_only = json.loads(json.dumps(fixture))
        label_only["normalized_production_input"] = {"label": "CPE 3.1 control"}
        path = Path(raw) / "label-only.json"
        path.write_text(json.dumps(label_only), encoding="utf-8")
        checks["label_only_control_rejected"] = rejected(
            lambda: build_control_bundle(contract, fixture_path=path)
        )

        prefix = SKILL_ROOT / "templates" / "cpe-v4-worker-prefix.txt"
        drifted_prefix = Path(raw) / "drifted-prefix.txt"
        drifted_prefix.write_bytes(prefix.read_bytes() + b"drift\n")
        checks["candidate_prompt_drift_rejected"] = rejected(
            lambda: build_candidate_bundle(contract, prefix_path=drifted_prefix)
        )

        nested_mutations = {
            "worker_instruction_drift_rejected": (
                ("worker_stdin", "instruction"),
                "mutated scheduler instruction",
            ),
            "selected_spec_drift_rejected": (
                ("selected_spec",),
                [{"id": "S1.12", "sha256": "0" * 64, "text": "mutated"}],
            ),
        }
        for name, (keys, value) in nested_mutations.items():
            mutated = json.loads(json.dumps(fixture))
            target = mutated["normalized_production_input"]
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            path = Path(raw) / f"{name}.json"
            path.write_text(json.dumps(mutated), encoding="utf-8")
            checks[name] = rejected(
                lambda path=path: build_control_bundle(contract, fixture_path=path)
            )

    checks["absolute_dynamic_context_rejected"] = rejected(
        lambda: build_candidate_bundle(
            contract,
            bounded_context=({"path": "/private/example.py", "content": "x"},),
        )
    )
    sensitive_paths = (
        "secrets/api-key.txt",
        "oracle/expected.json",
        "transcripts/session.json",
        "~/private.txt",
        "$HOME/private.txt",
    )
    checks["sensitive_context_paths_rejected"] = all(
        rejected(
            lambda path=path: build_candidate_bundle(
                contract,
                bounded_context=({"path": path, "content": "redacted"},),
            )
        )
        for path in sensitive_paths
    )
    approved_root_bypasses = (
        "$WORKTREE/secrets/api-key.txt",
        "$RUN_DIR/oracle/expected.json",
    )
    checks["approved_root_sensitive_suffixes_rejected"] = all(
        rejected(
            lambda path=path: build_candidate_bundle(
                contract,
                bounded_context=({"path": path, "content": "redacted"},),
            )
        )
        for path in approved_root_bypasses
    )
    sensitive_mapping_keys = (
        "/Users/kws/private.txt",
        "oracle/expected.json",
    )
    checks["sensitive_mapping_keys_rejected"] = all(
        rejected(
            lambda path=path: build_candidate_bundle(
                contract,
                bounded_context=({path: "redacted"},),
            )
        )
        for path in sensitive_mapping_keys
    )
    checks["benign_and_near_match_paths_allowed"] = all(
        accepted(
            lambda path=path: build_candidate_bundle(
                contract,
                bounded_context=({"path": path, "content": "safe"},),
            )
        )
        for path in (
            "$WORKTREE/src/prompt.py",
            "$RUN_DIR/artifacts/result.json",
            "secretary/api-key.txt",
            "oracle-notes/expected.json",
            "transcripts.md/session.json",
        )
    )

    evidence_a = ({"attempt_id": "task_7.implementation.1", "status": "completed"},)
    evidence_b = ({"attempt_id": "task_7.implementation.2", "status": "completed"},)
    control_a, candidate_a = paired_bundles(contract, prior_task_evidence=evidence_a)
    control_b, candidate_b = paired_bundles(contract, prior_task_evidence=evidence_b)
    checks["prior_evidence_is_case_bound"] = (
        control_a.case_sha256 == candidate_a.case_sha256
        and control_b.case_sha256 == candidate_b.case_sha256
        and control_a.case_sha256 != control_b.case_sha256
    )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
