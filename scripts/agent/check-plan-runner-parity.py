#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
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
        "state": Path(".codex/plan-runner"),
    },
    "claude": {
        "runner": REPO_ROOT / "skills/kws-claude-plan-runner/scripts/runner",
        "fake": REPO_ROOT / "skills/kws-claude-plan-runner/evals/fake_claude.py",
        "state": Path(".claude/plan-runner"),
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
FAKE_FILE_LIMIT = 4_096
CODEX_SDD_RELATIVE_PATHS = (
    Path("skills/subagent-driven-development/SKILL.md"),
    Path("skills/subagent-driven-development/scripts/sdd-workspace"),
    Path("skills/subagent-driven-development/scripts/task-brief"),
    Path("skills/subagent-driven-development/scripts/review-package"),
    Path("skills/subagent-driven-development/implementer-prompt.md"),
    Path("skills/subagent-driven-development/task-reviewer-prompt.md"),
    Path("skills/subagent-driven-development/re-review-prompt.md"),
    Path("skills/requesting-code-review/code-reviewer.md"),
)


class ParityFailure(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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


def validate_external_contract(contract: Mapping[str, Any]) -> None:
    expected_fields = [
        "exit",
        "status",
        "plan_statuses",
        "handoff_heads",
        "verification_set_digest",
        "required_receipt_count",
        "session_action",
        "integration",
    ]
    if contract.get("contract_version") != 2:
        raise ParityFailure("unsupported parity contract version")
    if contract.get("state_format_version") != 2:
        raise ParityFailure("unsupported parity state format version")
    if contract.get("parity_fields") != expected_fields:
        raise ParityFailure("external parity field drift")


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


def _prepare_fake_codex_environment(
    root: Path, environment: dict[str, str]
) -> Path:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    codex_home = root / "fake-codex-home"
    codex_home.mkdir(mode=0o700)
    codex_home.chmod(0o700)
    documents = {
        Path("auth.json"): json.dumps(
            {
                "auth_mode": "apikey",
                "last_refresh": None,
                "OPENAI_API_KEY": "fake-parity-api-key",
                "tokens": None,
            },
            sort_keys=True,
        )
        + "\n",
    }
    documents.update(
        {
            relative: "fake-sdd-entrypoint\n"
            for relative in CODEX_SDD_RELATIVE_PATHS
        }
    )
    for relative, contents in documents.items():
        encoded = contents.encode("utf-8")
        if not encoded or len(encoded) > FAKE_FILE_LIMIT:
            raise ParityFailure("fake Codex capability file is not bounded")
        target = codex_home / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(encoded)
        target.chmod(0o600)

    expected = set(documents)
    actual = {
        path.relative_to(codex_home)
        for path in codex_home.rglob("*")
        if path.is_file()
    }
    if actual != expected or any(
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size <= 0
        or path.stat().st_size > FAKE_FILE_LIMIT
        for path in (codex_home / relative for relative in expected)
    ):
        raise ParityFailure("fake Codex capability home failed its self-check")

    environment.pop("OPENAI_API_KEY", None)
    environment["CODEX_HOME"] = str(codex_home)
    return codex_home


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


def _validate_recovery_evidence(
    scenario_id: str,
    records: Sequence[Mapping[str, Any]],
) -> str | None:
    expected_action = {
        "healthy-resume": "clean-interrupted",
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
    recovered = records[first + 1]
    if scenario_id == "healthy-resume":
        if recovered.get("session_action") != "resume":
            raise ParityFailure("healthy recovery did not use the root resume action")
        return "resume_root"
    else:
        if recovered.get("session_action") != "fresh":
            raise ParityFailure("fallback recovery did not use the fresh-root action")
        return "fresh_root"


def _artifact_by_digest(
    state: Mapping[str, Any],
    run_root: Path,
    *,
    digest: str,
    kind: str,
) -> Mapping[str, Any]:
    matches = [
        item
        for item in state.get("artifact_refs", [])
        if isinstance(item, Mapping)
        and item.get("kind") == kind
        and item.get("digest") == digest
    ]
    if len(matches) != 1:
        raise ParityFailure(f"expected one accepted {kind} artifact")
    return _read_artifact(run_root, matches[0])


def _external_outcome(
    *,
    exit_code: int,
    state: Mapping[str, Any],
    run_root: Path,
    session_action: str | None,
) -> dict[str, Any]:
    handoff_heads: list[str] = []
    accepted_digest: str | None = None
    for index, plan in enumerate(state["plans"]):
        handoff_digest = plan.get("handoff_digest")
        if handoff_digest is None:
            continue
        digest = _require_digest(handoff_digest, "plan handoff")
        handoff = _artifact_by_digest(
            state,
            run_root,
            digest=digest,
            kind="plan_handoff",
        )
        if handoff.get("plan_index") != index:
            raise ParityFailure("ordered plan handoff identity drift")
        handoff_heads.append(
            _require_head(handoff.get("head_commit"), "plan handoff")
        )
        accepted_digest = _require_digest(
            handoff.get("verification_set_digest"),
            "accepted verification set",
        )

    required_receipt_count = 0
    if accepted_digest is not None:
        accepted_kind = (
            "run_verification_set"
            if state["status"] == "ready_for_integration"
            else "plan_verification_set"
        )
        accepted = _artifact_by_digest(
            state,
            run_root,
            digest=accepted_digest,
            kind=accepted_kind,
        )
        commands = accepted.get("commands", [])
        if not isinstance(commands, list):
            raise ParityFailure("accepted verification commands are invalid")
        if accepted.get("candidate_head") != handoff_heads[-1]:
            raise ParityFailure(
                "accepted verification union does not bind the final handoff HEAD"
            )
        identities: set[bytes] = set()
        for command in commands:
            if not isinstance(command, Mapping):
                raise ParityFailure("accepted verification command is invalid")
            identity_fields = (
                "argv",
                "cwd",
                "input_digest",
                "deadline_seconds",
            )
            if any(field not in command for field in identity_fields):
                raise ParityFailure(
                    "accepted verification command identity is incomplete"
                )
            identity = _canonical_json(
                {field: command[field] for field in identity_fields}
            )
            if identity in identities:
                raise ParityFailure(
                    "accepted verification union contains a duplicate"
                )
            identities.add(identity)
        required_receipt_count = len(commands)
        accepted_digest = hashlib.sha256(
            _canonical_json(
                {
                    "candidate_head": handoff_heads[-1],
                    "commands": commands,
                }
            )
        ).hexdigest()

    return {
        "exit": exit_code,
        "status": state["status"],
        "plan_statuses": [plan["status"] for plan in state["plans"]],
        "handoff_heads": handoff_heads,
        "verification_set_digest": accepted_digest,
        "required_receipt_count": required_receipt_count,
        "session_action": session_action,
        "integration": state["integration"],
    }


def _normalize(
    *,
    exit_code: int,
    state: Mapping[str, Any],
    run_root: Path,
    log_path: Path,
) -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return _external_outcome(
        exit_code=exit_code,
        state=state,
        run_root=run_root,
        session_action=_validate_recovery_evidence(
            log_path.parent.name,
            records,
        ),
    )


def _expected(scenario: Mapping[str, Any]) -> dict[str, Any]:
    names = {
        "expected_exit": "exit",
        "expected_status": "status",
        "expected_plan_statuses": "plan_statuses",
        "expected_handoff_heads": "handoff_heads",
        "expected_verification_set_digest": "verification_set_digest",
        "expected_required_receipt_count": "required_receipt_count",
        "expected_session_action": "session_action",
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


def _require_expected_outcome(
    provider: str,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> None:
    if dict(actual) != dict(expected):
        raise ParityFailure(
            f"{provider} expectation mismatch\n"
            f"{_bounded_diff(expected, actual)}"
        )


def run_provider(
    provider: str, scenario: Mapping[str, Any], temporary_root: Path
) -> dict[str, Any]:
    root = temporary_root / provider / scenario["id"]
    home = root / "home"
    home.mkdir(parents=True)
    env = dict(os.environ)
    env.update(GIT_ENV)
    env["HOME"] = str(home)
    if provider == "codex":
        _prepare_fake_codex_environment(root, env)
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
    resume_count = 0
    while result.returncode == 2:
        if resume_count >= len(actions):
            raise ParityFailure(
                f"{provider}/{scenario['id']}: external resume did not terminate"
            )
        result = _run(
            (str(runner), "resume", "--run-id", run_id),
            cwd=root,
            env=env,
        )
        resume_count += 1
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
    if (
        state.get("format_version"),
        state.get("contract_version"),
    ) != (2, 2):
        raise ParityFailure(f"{provider}/{scenario['id']}: state version drift")
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
    )


def main() -> int:
    try:
        contract = _load_json(CONTRACT)
        fixture = _load_json(FIXTURE)
        if fixture.get("fixture_version") != 2:
            raise ParityFailure("unsupported parity fixture version")
        validate_external_contract(contract)
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
                        _require_expected_outcome(provider, expected, actual)
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
