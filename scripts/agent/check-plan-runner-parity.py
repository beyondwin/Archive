#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "scripts/agent/fixtures/plan-runner-parity-v1.json"
CONTRACT = REPO_ROOT / "scripts/agent/fixtures/plan-runner-contract-v1.json"
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
GIT_ENV = {
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


class ParityFailure(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
        "FAILURE_TAXONOMY": set(contract["failure_taxonomy"]),
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
        if dict(module.RUNNER_RUNTIME_CONTRACT) != contract["runner_runtime"]:
            raise ParityFailure(f"{provider}: runner runtime drift")
        actual_exits = {
            key: int(getattr(module.ExitCode, enum_name))
            for key, enum_name in exit_names.items()
        }
        if actual_exits != contract["exit_codes"]:
            raise ParityFailure(f"{provider}: exit code drift")


def _init_source(root: Path, env: Mapping[str, str]) -> Path:
    source = root / "source"
    source.mkdir(parents=True)
    _checked_git(source, ("init", "-b", "main"), env)
    (source / "README.md").write_text("parity source\n", encoding="utf-8")
    _checked_git(source, ("add", "README.md"), env)
    _checked_git(
        source,
        (
            "-c",
            "user.name=Plan Runner Parity",
            "-c",
            "user.email=parity@example.test",
            "commit",
            "-m",
            "parity source",
        ),
        env,
    )
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
    relative = reference.get("relative_path")
    if not isinstance(relative, str):
        raise ParityFailure("artifact reference lacks relative_path")
    path = run_root / relative
    value = _load_json(path)
    if not isinstance(value, Mapping):
        raise ParityFailure(f"artifact is not an object: {relative}")
    return value


def _normalized_receipts(
    state: Mapping[str, Any], run_root: Path, worktree: Path
) -> list[dict[str, Any]]:
    contract = _load_json(CONTRACT)
    fields = contract["receipt_identity_fields"]
    normalized = []
    for reference in state["artifact_refs"]:
        if reference.get("kind") != "verification_receipt":
            continue
        receipt = _read_artifact(run_root, reference)
        identity = receipt.get("identity")
        if not isinstance(identity, Mapping) or set(identity) != set(fields):
            raise ParityFailure("verification receipt identity fields drift")
        executable = identity["executable_identity"]
        if not isinstance(executable, Mapping):
            raise ParityFailure("verification executable identity is invalid")
        cwd = Path(identity["cwd"])
        try:
            relative_cwd = str(cwd.relative_to(worktree))
        except ValueError as error:
            raise ParityFailure("verification cwd escapes worktree") from error
        environment_fingerprint = identity["environment_fingerprint"]
        if (
            not isinstance(environment_fingerprint, str)
            or len(environment_fingerprint) != 64
        ):
            raise ParityFailure("environment fingerprint is invalid")
        normalized.append(
            {
                "argv": identity["argv"],
                "candidate_head": identity["candidate_head"],
                "command_role": identity["command_role"],
                "cwd": relative_cwd or ".",
                "environment_fingerprint": "<sha256>",
                "executable_identity": {
                    "path": Path(executable["path"]).name,
                    "sha256": executable["sha256"],
                    "mode": executable["mode"],
                    "size": executable["size"],
                },
                "input_digest": identity["input_digest"],
                "worktree_digest": identity["worktree_digest"],
                "outcome": receipt.get("outcome"),
            }
        )
    return normalized


def _session_action(log_path: Path, actions: Sequence[str]) -> str | None:
    failure_indexes = [
        index
        for index, action in enumerate(actions)
        if action in {"interrupted", "stalled"}
    ]
    if not failure_indexes:
        return None
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    next_launch = failure_indexes[0] + 1
    if next_launch >= len(records):
        raise ParityFailure("recovery launch was not recorded")
    return "resume" if records[next_launch].get("session_action") == "resume" else "fresh"


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
    receipts = _normalized_receipts(state, run_root, worktree)
    finalization = state.get("finalization")
    review_head = (
        finalization.get("review_head")
        if isinstance(finalization, Mapping)
        else None
    )
    candidate_heads = [item["candidate_head"] for item in receipts]
    if isinstance(finalization, Mapping):
        candidate_heads.extend(
            value
            for value in (
                finalization.get("candidate_head"),
                finalization.get("review_head"),
            )
            if isinstance(value, str)
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
        "verification_receipts": receipts,
        "candidate_head_equal": (
            bool(candidate_heads)
            and all(head == observed_head for head in candidate_heads)
        )
        if state["status"] == "ready_for_integration"
        else None,
        "review_outcome": "reviewed" if isinstance(review_head, str) else None,
        "session_action": _session_action(log_path, actions),
        "integration": state["integration"],
    }


def _expected(scenario: Mapping[str, Any]) -> dict[str, Any]:
    names = {
        "expected_exit": "exit",
        "expected_status": "status",
        "expected_plan_statuses": "plan_statuses",
        "expected_task_statuses": "task_statuses",
        "expected_failure": "failure",
        "expected_session_action": "session_action",
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
    _write_sequence(sequence_path, scenario["fake_sequence"])
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
        "0.4",
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
    if sequence_state.get("next_index") != len(scenario["fake_sequence"]):
        raise ParityFailure(
            f"{provider}/{scenario['id']}: fake sequence was not fully consumed"
        )
    return _normalize(
        exit_code=result.returncode,
        state=state,
        run_root=run_root,
        log_path=log_path,
        actions=scenario["fake_sequence"],
        env=env,
    )


def main() -> int:
    try:
        contract = _load_json(CONTRACT)
        fixture = _load_json(FIXTURE)
        if fixture.get("fixture_version") != 1:
            raise ParityFailure("unsupported parity fixture version")
        validate_runtime_vocabularies(contract)
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
