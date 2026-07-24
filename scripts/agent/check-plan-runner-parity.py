#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "scripts/agent/fixtures/plan-runner-parity-v1.json"
CONTRACT = REPO_ROOT / "scripts/agent/fixtures/plan-runner-contract-v1.json"
CODEX_PUBLIC_DOCS = tuple(
    REPO_ROOT / "skills/kws-codex-plan-runner" / name
    for name in ("SKILL.md", "README.md", "CHANGELOG.md")
)
PROVIDERS = {
    "codex": {
        "runner": REPO_ROOT / "skills/kws-codex-plan-runner/scripts/runner",
        "fake": REPO_ROOT / "skills/kws-codex-plan-runner/evals/fake_codex.py",
        "contracts": (
            REPO_ROOT
            / "skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py"
        ),
        "state": Path(".codex/plan-runner"),
        "worktrees": Path(".codex/worktrees/plan-runner"),
    },
    "claude": {
        "runner": REPO_ROOT / "skills/kws-claude-plan-runner/scripts/runner",
        "fake": REPO_ROOT / "skills/kws-claude-plan-runner/evals/fake_claude.py",
        "contracts": (
            REPO_ROOT
            / "skills/kws-claude-plan-runner/scripts/plan_runner/contracts.py"
        ),
        "state": Path(".claude/plan-runner"),
        "worktrees": Path(".claude/worktrees/plan-runner"),
    },
}
OUTPUT_LIMIT = 4_096
PARITY_STALL_SECONDS = 1.5
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
GIT_ENV = {
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


class ParityFailure(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ParityFailure(f"{label} digest is invalid")
    return value


def _require_head(value: object, label: str) -> str:
    if not isinstance(value, str) or GIT_HEAD.fullmatch(value) is None:
        raise ParityFailure(f"{label} Git HEAD is invalid")
    return value


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float = 45,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise ParityFailure(f"command exceeded {timeout:g}s: {argv[0]}") from error


def _checked_git(
    root: Path, arguments: Sequence[str], env: Mapping[str, str]
) -> str:
    result = _run(("git", *arguments), cwd=root, env=env)
    if result.returncode != 0:
        raise ParityFailure(
            f"git {' '.join(arguments)} failed: "
            f"{(result.stderr or result.stdout)[-OUTPUT_LIMIT:]}"
        )
    return result.stdout.strip()


def _load_contract_module(provider: str, path: Path) -> Any:
    name = f"_plan_runner_parity_{provider}_contracts"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ParityFailure(f"cannot load {provider} contract vocabulary")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_runtime_vocabularies(contract: Mapping[str, Any]) -> None:
    expected = {
        "RUN_STATUSES": set(contract["run_statuses"]),
        "PLAN_STATUSES": set(contract["plan_statuses"]),
        "TASK_STATUSES": set(contract["task_statuses"]),
    }
    exit_names = {
        "ready": "READY",
        "resumable": "RESUMABLE",
        "blocked": "BLOCKED",
        "failed": "FAILED",
        "invalid": "INVALID",
        "integrity": "INTEGRITY",
        "internal": "INTERNAL",
    }
    for provider, paths in PROVIDERS.items():
        module = _load_contract_module(provider, paths["contracts"])
        if module.CONTRACT_VERSION != contract["contract_version"]:
            raise ParityFailure(f"{provider}: contract version drift")
        if module.FORMAT_VERSION != contract["state_format_version"]:
            raise ParityFailure(f"{provider}: state format version drift")
        for name, vocabulary in expected.items():
            if set(getattr(module, name)) != vocabulary:
                raise ParityFailure(f"{provider}: {name} drift")
        failure_vocabulary = set(contract["failure_taxonomy"])
        failure_vocabulary.update(
            contract["provider_failure_taxonomy_extensions"].get(provider, [])
        )
        if set(module.FAILURE_TAXONOMY) != failure_vocabulary:
            raise ParityFailure(f"{provider}: FAILURE_TAXONOMY drift")
        if dict(module.RUNNER_RUNTIME_CONTRACT) != contract["runner_runtime"]:
            raise ParityFailure(f"{provider}: runner runtime drift")
        actual_exits = {
            key: int(getattr(module.ExitCode, enum_name))
            for key, enum_name in exit_names.items()
        }
        if actual_exits != contract["exit_codes"]:
            raise ParityFailure(f"{provider}: exit code drift")


def validate_codex_public_contract(contract: Mapping[str, Any]) -> None:
    expected_policy = {
        "version": 1,
        "prefixes": [
            "refs/codex/turn-diffs/captures/",
            "refs/codex/turn-diffs/checkpoints/",
        ],
    }
    if contract.get("volatile_ref_policy") != expected_policy:
        raise ParityFailure("codex: volatile ref policy drift")

    documents = [path.read_text(encoding="utf-8") for path in CODEX_PUBLIC_DOCS]
    combined = "\n".join(documents)
    required = (
        "subagent-driven-development",
        "thin wrapper",
        "Superpowers v6.2.0",
        "strategic recovery shell",
        "danger-full-access",
        'approval_policy="never"',
        "--ignore-rules",
        "matching_run_exists",
        "volatile-codex-turn-refs",
        "unsealed-provider-partial",
        "bun run agent:verify -- --base",
    )
    missing = [value for value in required if value not in combined]
    if missing:
        raise ParityFailure(f"codex: public contract vocabulary drift: {missing}")


def _init_source(root: Path, env: Mapping[str, str]) -> Path:
    source = root / "source"
    source.mkdir(parents=True)
    _checked_git(source, ("init", "-b", "main"), env)
    _checked_git(source, ("config", "user.name", "Plan Runner Parity"), env)
    _checked_git(source, ("config", "user.email", "parity@example.test"), env)
    (source / "README.md").write_text("parity source\n", encoding="utf-8")
    _checked_git(source, ("add", "README.md"), env)
    _checked_git(source, ("commit", "-m", "parity source"), env)
    return source


def _write_inputs(root: Path) -> tuple[list[Path], list[Path]]:
    inputs = root / "inputs"
    inputs.mkdir()
    specs = [inputs / "spec-z.md", inputs / "spec-a.md"]
    plans = [inputs / "plan-z.md", inputs / "plan-a.md"]
    for index, path in enumerate(specs):
        path.write_text(f"# Specification {index}\n\nProvider-neutral.\n", encoding="utf-8")
    for index, path in enumerate(plans):
        path.write_text(f"# Plan {index}\n\nImplement in CLI order.\n", encoding="utf-8")
    return specs, plans


def _install_fake(provider: str, root: Path) -> Path:
    binary = root / "bin"
    binary.mkdir()
    target = binary / provider
    shutil.copyfile(PROVIDERS[provider]["fake"], target)
    target.chmod(0o700)
    return binary


def _write_sequence(path: Path, actions: Sequence[str]) -> None:
    path.write_text(
        json.dumps(
            {"protocol_version": 1, "actions": list(actions), "next_index": 0},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _last_json(stdout: str, label: str) -> Mapping[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise ParityFailure(f"{label}: no bounded JSON result")


def _read_artifact(run_root: Path, reference: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(reference) != {"kind", "digest", "relative_path"}:
        raise ParityFailure("artifact reference fields drift")
    kind = reference.get("kind")
    if not isinstance(kind, str) or not kind:
        raise ParityFailure("artifact reference kind is invalid")
    digest = _require_digest(reference.get("digest"), "artifact reference")
    relative = reference.get("relative_path")
    if not isinstance(relative, str):
        raise ParityFailure("artifact reference lacks relative_path")
    relative_path = Path(relative)
    expected = Path("artifacts") / kind / f"{digest}.json"
    if relative_path != expected or relative_path.is_absolute() or ".." in relative_path.parts:
        raise ParityFailure("artifact reference path is invalid")
    path = run_root / relative_path
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ParityFailure("artifact reference digest mismatch")
    value = json.loads(payload)
    if not isinstance(value, Mapping):
        raise ParityFailure(f"artifact is not an object: {relative}")
    return value


def _validate_executable_identity(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "path",
        "sha256",
        "mode",
        "size",
    }:
        raise ParityFailure("verification executable identity fields drift")
    path_value = value["path"]
    mode = value["mode"]
    size = value["size"]
    if (
        not isinstance(path_value, str)
        or not Path(path_value).is_absolute()
        or not isinstance(mode, int)
        or isinstance(mode, bool)
        or not stat.S_ISREG(mode)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
    ):
        raise ParityFailure("verification executable identity types are invalid")
    digest = _require_digest(value["sha256"], "verification executable")
    executable = Path(path_value)
    try:
        metadata = executable.stat()
        actual_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    except OSError as error:
        raise ParityFailure("verification executable path is unavailable") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode != mode
        or metadata.st_size != size
        or actual_digest != digest
    ):
        raise ParityFailure("verification executable path or hash mismatch")
    return {
        "path": executable.name,
        "sha256": digest,
        "mode": mode,
        "size": size,
    }


def _validate_receipt(
    receipt: Mapping[str, Any], worktree: Path
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    if receipt.get("schema_version") != 1:
        raise ParityFailure("verification receipt schema version drift")
    identity = receipt.get("identity")
    fields = _load_json(CONTRACT)["receipt_identity_fields"]
    if not isinstance(identity, Mapping) or set(identity) != set(fields):
        raise ParityFailure("verification receipt identity fields drift")
    argv = identity["argv"]
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
    ):
        raise ParityFailure("verification argv is invalid")
    candidate_head = _require_head(identity["candidate_head"], "verification")
    if identity["command_role"] != "final":
        raise ParityFailure("verification command role is not final")
    cwd_value = identity["cwd"]
    if not isinstance(cwd_value, str) or not Path(cwd_value).is_absolute():
        raise ParityFailure("verification cwd is invalid")
    cwd = Path(cwd_value)
    try:
        relative_cwd = str(cwd.relative_to(worktree))
    except ValueError as error:
        raise ParityFailure("verification cwd escapes worktree") from error
    environment_fingerprint = _require_digest(
        identity["environment_fingerprint"], "environment fingerprint"
    )
    input_digest = _require_digest(identity["input_digest"], "verification input")
    worktree_digest = _require_digest(identity["worktree_digest"], "worktree")
    executable = _validate_executable_identity(identity["executable_identity"])
    identity_digest = _require_digest(
        receipt.get("identity_digest"), "verification identity"
    )
    if hashlib.sha256(_canonical_json(identity)).hexdigest() != identity_digest:
        raise ParityFailure("verification identity digest mismatch")
    if receipt.get("outcome") != "success" or receipt.get("exit_code") != 0:
        raise ParityFailure("required verification receipt is not successful")
    return (
        {
            "argv": argv,
            "candidate_head": "<git-head>",
            "command_role": "final",
            "cwd": relative_cwd or ".",
            "environment_fingerprint": "<sha256>",
            "executable_identity": executable,
            "input_digest": input_digest,
            "worktree_digest": worktree_digest,
            "outcome": "success",
        },
        identity,
    )


def _normalized_receipts(
    state: Mapping[str, Any], run_root: Path, worktree: Path
) -> list[dict[str, Any]]:
    normalized = []
    for reference in state["artifact_refs"]:
        if reference.get("kind") != "verification_receipt":
            continue
        receipt = _read_artifact(run_root, reference)
        normalized.append(_validate_receipt(receipt, worktree)[0])
    return normalized


def _validate_recovery_evidence(
    scenario_id: str,
    records: Sequence[Mapping[str, Any]],
    state: Mapping[str, Any] | None = None,
) -> str | None:
    expected_action = {
        "healthy-resume": "interrupted",
        "stalled-fresh-strategy": "stalled",
    }.get(scenario_id)
    if expected_action is None:
        return None
    first = next(
        (
            index
            for index, record in enumerate(records)
            if record.get("action") == expected_action
        ),
        None,
    )
    if first is None or first + 1 >= len(records):
        raise ParityFailure("recovery launch was not recorded")
    failed = records[first]
    recovered = records[first + 1]
    failed_session = failed.get("session_id")
    recovered_session = recovered.get("session_id")
    if (
        not isinstance(failed_session, str)
        or not isinstance(recovered_session, str)
    ):
        raise ParityFailure("recovery session identity was not recorded")
    failed_packet_digest = _require_digest(
        failed.get("packet_digest"), "failed recovery packet"
    )
    recovered_packet_digest = _require_digest(
        recovered.get("packet_digest"), "recovered recovery packet"
    )
    if expected_action == "interrupted":
        session_action = recovered.get("session_action")
        if session_action == "resume" and recovered_session == failed_session:
            action = "recovered"
        elif (
            session_action == "fresh"
            and recovered_session != failed_session
            and recovered.get("required_strategy_change") is True
        ):
            action = "recovered"
        else:
            raise ParityFailure(
                "interrupted recovery used neither the exact healthy session "
                "nor an evidence-backed fresh strategy"
            )
    else:
        if recovered_packet_digest == failed_packet_digest:
            raise ParityFailure(
                "changed strategy did not use a distinct packet digest"
            )
        if (
            recovered.get("session_action") != "fresh"
            or recovered_session == failed_session
        ):
            raise ParityFailure("contaminated recovery did not use a distinct fresh session")
        if recovered.get("required_strategy_change") is not True:
            raise ParityFailure("fresh recovery lacks a durable changed-strategy packet")
        action = "fresh"
    if state is not None:
        sessions = [
            item
            for item in state.get("sessions", [])
            if isinstance(item, Mapping)
            and item.get("mode") == "implementation"
            and item.get("session_id") in {failed_session, recovered_session}
        ]
        if len(sessions) < 2:
            raise ParityFailure("durable session recovery evidence is incomplete")
        if expected_action == "stalled" and not any(
            item.get("session_id") == failed_session
            and item.get("health") == "invalid"
            for item in sessions
        ):
            raise ParityFailure("stalled session is not durably marked invalid")
    return action


def _references(
    state: Mapping[str, Any], kind: str
) -> list[Mapping[str, Any]]:
    return [
        item
        for item in state.get("artifact_refs", [])
        if isinstance(item, Mapping) and item.get("kind") == kind
    ]


def _one_reference(state: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    references = _references(state, kind)
    if len(references) != 1:
        raise ParityFailure(f"ready run requires exactly one {kind} artifact")
    return references[0]


def _validate_ready_evidence(
    state: Mapping[str, Any],
    run_root: Path,
    worktree: Path,
    observed_head: str,
) -> dict[str, Any]:
    observed_head = _require_head(observed_head, "observed candidate")
    if state.get("integration") != "not_observed":
        raise ParityFailure("ready integration must remain not_observed")
    finalization = state.get("finalization")
    if not isinstance(finalization, Mapping):
        raise ParityFailure("ready finalization state is missing")
    set_ref = _one_reference(state, "final_verification_set")
    final_set = _read_artifact(run_root, set_ref)
    if (
        final_set.get("kind") != "commands"
        or not isinstance(final_set.get("commands"), list)
        or not final_set["commands"]
    ):
        raise ParityFailure("ready run requires a nonempty final command set")
    if final_set.get("candidate_head") != observed_head:
        raise ParityFailure("final command set HEAD does not match the candidate")
    set_digest = set_ref["digest"]
    if finalization.get("verification_set_digest") != set_digest:
        raise ParityFailure("finalization verification set digest mismatch")
    receipt_refs = _references(state, "verification_receipt")
    if len(receipt_refs) != len(final_set["commands"]):
        raise ParityFailure("not every required final command has one receipt")
    normalized_receipts: list[dict[str, Any]] = []
    raw_identities: list[Mapping[str, Any]] = []
    for reference in receipt_refs:
        receipt = _read_artifact(run_root, reference)
        normalized, identity = _validate_receipt(receipt, worktree)
        normalized_receipts.append(normalized)
        raw_identities.append(identity)
    unmatched = list(raw_identities)
    for command in final_set["commands"]:
        expected_cwd = str((worktree / command["cwd"]).resolve())
        match = next(
            (
                identity
                for identity in unmatched
                if identity.get("candidate_head") == observed_head
                and identity.get("command_role") == command.get("command_role")
                and identity.get("argv") == command.get("argv")
                and identity.get("cwd") == expected_cwd
                and identity.get("input_digest") == command.get("input_digest")
            ),
            None,
        )
        if match is None:
            raise ParityFailure("required final command receipt identity mismatch")
        unmatched.remove(match)
    review_ref = _one_reference(state, "final_review_receipt")
    review = _read_artifact(run_root, review_ref)
    if (
        review.get("status") != "reviewed"
        or review.get("candidate_head") != observed_head
        or review.get("review_head") != observed_head
        or review.get("verification_set_digest") != set_digest
        or review.get("open_findings") != []
        or review.get("open_obligation_ids") != []
    ):
        raise ParityFailure("final review is not approved at the candidate HEAD")
    handoff_ref = _one_reference(state, "branch_handoff")
    handoff = _read_artifact(run_root, handoff_ref)
    if (
        handoff.get("status") != "ready_for_integration"
        or handoff.get("candidate_head") != observed_head
        or handoff.get("review_head") != observed_head
        or handoff.get("verification_set_digest") != set_digest
        or handoff.get("review_receipt") != review_ref
        or handoff.get("verification_receipts") != receipt_refs
        or handoff.get("integration") != "not_observed"
        or finalization.get("candidate_head") != observed_head
        or finalization.get("review_head") != observed_head
    ):
        raise ParityFailure("final handoff evidence does not share one candidate HEAD")
    return {
        "verification_receipts": normalized_receipts,
        "required_receipt_count": len(receipt_refs),
        "all_required_receipts": True,
        "final_head_equal": True,
        "review_outcome": "approved",
        "review_approved": True,
        "integration": "not_observed",
    }


def _normalize(
    *,
    exit_code: int,
    state: Mapping[str, Any],
    run_root: Path,
    log_path: Path,
    actions: Sequence[str],
    env: Mapping[str, str],
) -> dict[str, Any]:
    worktree = Path(state["repository"]["worktree"])
    observed_head = _checked_git(worktree, ("rev-parse", "HEAD"), env)
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ready = (
        _validate_ready_evidence(state, run_root, worktree, observed_head)
        if state["status"] == "ready_for_integration"
        else {
            "verification_receipts": _normalized_receipts(
                state, run_root, worktree
            ),
            "required_receipt_count": 0,
            "all_required_receipts": None,
            "final_head_equal": None,
            "review_outcome": None,
            "review_approved": None,
            "integration": state["integration"],
        }
    )
    failure = state.get("failure")
    return {
        "exit": exit_code,
        "status": state["status"],
        "plan_statuses": [plan["status"] for plan in state["plans"]],
        "task_statuses": [task["status"] for task in state["task_ledger"]],
        "failure": (
            failure.get("reason_code") if isinstance(failure, Mapping) else None
        ),
        "verification_receipts": ready["verification_receipts"],
        "required_receipt_count": ready["required_receipt_count"],
        "all_required_receipts": ready["all_required_receipts"],
        "final_head_equal": ready["final_head_equal"],
        "review_outcome": ready["review_outcome"],
        "review_approved": ready["review_approved"],
        "session_action": _validate_recovery_evidence(
            log_path.parent.name, records, state
        ),
        "integration": ready["integration"],
    }


def _expected(scenario: Mapping[str, Any]) -> dict[str, Any]:
    names = {
        "expected_exit": "exit",
        "expected_status": "status",
        "expected_plan_statuses": "plan_statuses",
        "expected_task_statuses": "task_statuses",
        "expected_failure": "failure",
        "expected_session_action": "session_action",
        "expected_required_receipt_count": "required_receipt_count",
        "expected_all_required_receipts": "all_required_receipts",
        "expected_final_head_equal": "final_head_equal",
        "expected_review_outcome": "review_outcome",
        "expected_review_approved": "review_approved",
        "expected_integration": "integration",
    }
    return {
        normalized: scenario[source]
        for source, normalized in names.items()
        if source in scenario
    }


def _bounded_diff(expected: Any, actual: Any) -> str:
    document = json.dumps(
        {"expected": expected, "actual": actual},
        indent=2,
        sort_keys=True,
    )
    return document[:OUTPUT_LIMIT]


def run_provider(
    provider: str, scenario: Mapping[str, Any], temporary_root: Path
) -> dict[str, Any]:
    root = temporary_root / provider / scenario["id"]
    home = root / "home"
    home.mkdir(parents=True)
    env = dict(os.environ)
    env.update(GIT_ENV)
    env["HOME"] = str(home)
    # Keep runtime discovery read-only while isolating every provider HOME.
    env["UV_PYTHON_INSTALL_DIR"] = str(Path(sys.executable).resolve().parents[2])
    binary = _install_fake(provider, root)
    env["PATH"] = os.pathsep.join((str(binary), env.get("PATH", "")))
    sequence_path = root / "sequence.json"
    log_path = root / "fake.jsonl"
    provider_sequences = scenario.get("provider_fake_sequences", {})
    actions = (
        provider_sequences.get(provider, scenario["fake_sequence"])
        if isinstance(provider_sequences, Mapping)
        else scenario["fake_sequence"]
    )
    _write_sequence(sequence_path, actions)
    env["PLAN_RUNNER_FAKE_SEQUENCE"] = str(sequence_path)
    env["PLAN_RUNNER_FAKE_LOG"] = str(log_path)
    env["FAKE_CODEX_LOG"] = str(log_path)
    env["FAKE_CLAUDE_LOG"] = str(log_path)
    source = _init_source(root, env)
    specs, plans = _write_inputs(root)
    runner = PROVIDERS[provider]["runner"]
    argv = [
        str(runner),
        "run",
        "--spec",
        str(specs[0]),
        "--spec",
        str(specs[1]),
        "--plan",
        str(plans[0]),
        "--plan",
        str(plans[1]),
        "--workspace",
        str(source),
        "--stall-seconds",
        str(PARITY_STALL_SECONDS),
    ]
    result = _run(argv, cwd=root, env=env)
    summary = _last_json(result.stdout, f"{provider}/{scenario['id']} run")
    run_id = summary.get("run_id")
    state_home = home / PROVIDERS[provider]["state"]
    if not isinstance(run_id, str):
        candidates = [item for item in state_home.glob("*") if item.is_dir()]
        if len(candidates) != 1:
            raise ParityFailure(
                f"{provider}/{scenario['id']}: cannot resolve durable run; "
                f"exit={result.returncode}; "
                f"output={(result.stderr or result.stdout)[-OUTPUT_LIMIT:]}"
            )
        run_id = candidates[0].name
    inspect = _run(
        (str(runner), "inspect", "--run-id", run_id),
        cwd=root,
        env=env,
    )
    if inspect.returncode != 0:
        raise ParityFailure(
            f"{provider}/{scenario['id']}: inspect failed: "
            f"{(inspect.stderr or inspect.stdout)[-OUTPUT_LIMIT:]}"
        )
    inspected = _last_json(inspect.stdout, f"{provider}/{scenario['id']} inspect")
    run_root = state_home / run_id
    state = _load_json(run_root / "state.json")
    if not isinstance(state, Mapping):
        raise ParityFailure(f"{provider}/{scenario['id']}: state is invalid")
    if inspected.get("status") != state.get("status"):
        raise ParityFailure(f"{provider}/{scenario['id']}: inspect status drift")
    if [
        Path(item["source_path"]).name
        for item in state["inputs"]
        if item["role"] == "spec"
    ] != [path.name for path in specs]:
        raise ParityFailure(f"{provider}/{scenario['id']}: spec order drift")
    if [Path(item["source_path"]).name for item in state["plans"]] != [
        path.name for path in plans
    ]:
        raise ParityFailure(f"{provider}/{scenario['id']}: plan order drift")
    sequence_state = _load_json(sequence_path)
    if sequence_state.get("next_index") != len(actions):
        raise ParityFailure(
            f"{provider}/{scenario['id']}: fake sequence was not fully consumed "
            f"({sequence_state.get('next_index')}/{len(actions)})"
        )
    return _normalize(
        exit_code=result.returncode,
        state=state,
        run_root=run_root,
        log_path=log_path,
        actions=actions,
        env=env,
    )


def main() -> int:
    try:
        contract = _load_json(CONTRACT)
        fixture = _load_json(FIXTURE)
        if fixture.get("fixture_version") != 1:
            raise ParityFailure("unsupported parity fixture version")
        validate_runtime_vocabularies(contract)
        validate_codex_public_contract(contract)
        failures = 0
        temporary_parent = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(
            prefix="plan-runner-parity-", dir=temporary_parent
        ) as raw:
            temporary_root = Path(raw)
            for scenario in fixture["scenarios"]:
                results: dict[str, dict[str, Any]] = {}
                try:
                    for provider in PROVIDERS:
                        results[provider] = run_provider(
                            provider, scenario, temporary_root
                        )
                    expected = _expected(scenario)
                    for provider, actual in results.items():
                        subset = {key: actual.get(key) for key in expected}
                        if subset != expected:
                            raise ParityFailure(
                                f"{provider} expectation mismatch\n"
                                f"{_bounded_diff(expected, subset)}"
                            )
                    if results["codex"] != results["claude"]:
                        raise ParityFailure(
                            "provider outcome mismatch\n"
                            + _bounded_diff(results["codex"], results["claude"])
                        )
                except (OSError, ValueError, KeyError, ParityFailure) as error:
                    failures += 1
                    detail = str(error).replace(str(temporary_root), "<tmp>")
                    print(f"{scenario['id']}: FAIL\n{detail[:OUTPUT_LIMIT]}")
                else:
                    print(f"{scenario['id']}: PASS")
        if failures:
            print(f"plan runner parity: FAIL ({failures} scenario(s))")
            return 1
        print("plan runner parity: PASS")
        return 0
    except (OSError, ValueError, KeyError, ParityFailure) as error:
        print(f"plan runner parity: FAIL ({str(error)[:OUTPUT_LIMIT]})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
