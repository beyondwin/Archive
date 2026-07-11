#!/usr/bin/env python3
"""Deterministic contract checks for the ChatGPT subscription live runner."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from live_migration.compiler import compile_manifest
from live_migration.contracts import (
    EXPECTED_CASES,
    canonical_json,
    sha256_bytes,
    worker_prompt_bytes,
)
from live_migration.fixtures import materialize_fixture
from live_migration.runner import (
    CodexAttestation,
    LiveRunnerError,
    RunContext,
    SlotRequest,
    SubscriptionLiveRunner,
    preflight_codex,
    render_prompt,
    run_slot,
)
from live_migration.ledger import append_event, create_run, replay_run


ROOT = Path(__file__).resolve().parent
REVIEWED_CHECKOUT_ENV = "CPE_LIVE_RUNNER_REVIEWED_TEST_CHECKOUT"
_CHECKPOINT_ARGUMENTS: tuple[str, ...] | None = None


def _run_from_clean_reviewed_checkout() -> int | None:
    """Re-exec the suite from a committed snapshot when the source tree is dirty."""

    if os.environ.get(REVIEWED_CHECKOUT_ENV) == "1":
        return None
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    if not status:
        return None
    with tempfile.TemporaryDirectory(prefix="cpe-live-reviewed-checkout-") as raw:
        repository = Path(raw) / "repo"
        skill = repository / "skills" / "kws-codex-plan-executor"
        shutil.copytree(ROOT.parent, skill)
        subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repository, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=CPE deterministic eval",
                "-c",
                "user.email=cpe-eval@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "reviewed live runner fixture",
            ],
            cwd=repository,
            check=True,
        )
        completed = subprocess.run(
            [sys.executable, str(skill / "evals" / Path(__file__).name)],
            cwd=skill,
            env={
                **os.environ,
                REVIEWED_CHECKOUT_ENV: "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        return completed.returncode


def _checkpoint_arguments() -> tuple[str, ...]:
    global _CHECKPOINT_ARGUMENTS
    if _CHECKPOINT_ARGUMENTS is None:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", f"{commit}^{{tree}}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        patch = sha256_bytes(
            subprocess.run(
                ["git", "show", "--format=", "--binary", commit],
                cwd=ROOT,
                capture_output=True,
                check=True,
            ).stdout
        )
        _CHECKPOINT_ARGUMENTS = (
            "--implementation-commit",
            commit,
            "--implementation-tree",
            tree,
            "--implementation-patch-sha256",
            patch,
        )
    return _CHECKPOINT_ARGUMENTS


def _bind_reviewed_checkpoint(manifest: dict[str, object]) -> dict[str, object]:
    arguments = _checkpoint_arguments()
    manifest.update(
        {
            "implementation_commit": arguments[1],
            "implementation_tree": arguments[3],
            "implementation_patch_sha256": arguments[5],
        }
    )
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    manifest["manifest_sha256"] = sha256_bytes(canonical_json(body))
    return manifest


def check_fake_codex_launcher_modes() -> None:
    valid = (
        ["exec", "--ignore-user-config", "--json", "--ephemeral", "-"],
        ["exec", "--ignore-user-config", "--json", "-"],
    )
    for argv in valid:
        result = subprocess.run(
            [sys.executable, str(ROOT / "fake_codex.py"), *argv],
            text=True,
            input="",
            capture_output=True,
        )
        assert result.returncode != 0
        assert "fake codex missing launcher argument: --model" in result.stderr, (argv, result.stderr)
    for unsupported in (
        ["exec", "--json", "-"],
        ["exec", "--json", "--ephemeral", "-"],
        ["exec", "--json", "--ephemeral"],
    ):
        result = subprocess.run(
            [sys.executable, str(ROOT / "fake_codex.py"), *unsupported],
            text=True,
            input="",
            capture_output=True,
        )
        assert result.returncode != 0
        assert "fake codex rejected launcher shape" in result.stderr, (unsupported, result.stderr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_run_codex_home(run_dir: Path) -> None:
    home = run_dir / "codex-home"
    home.mkdir(mode=0o700)
    auth = home / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    auth.chmod(0o600)


def _readonly_tree(path: Path) -> None:
    for item in sorted(path.rglob("*"), reverse=True):
        item.chmod(0o555 if item.is_dir() else 0o444)
    path.chmod(0o555)


def _isolated_fake_codex(tmp: Path) -> Path:
    launcher = tmp / "isolated_fake_codex.py"
    _write(
        launcher,
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        f"FAKE_CODEX = {str(ROOT / 'fake_codex.py')!r}\n"
        "argv = sys.argv[1:]\n"
        "if argv[:1] == ['exec'] and '--ignore-user-config' not in argv:\n"
        "    argv.insert(1, '--ignore-user-config')\n"
        "os.execv(sys.executable, [sys.executable, FAKE_CODEX, *argv])\n",
    )
    launcher.chmod(0o755)
    return launcher


def _runner(tmp: Path, *, env: dict[str, str] | None = None) -> SubscriptionLiveRunner:
    source = tmp / "source"
    fixture = tmp / "fixture"
    home = tmp / "codex-home"
    _write(source / "README.md", "source\n")
    _write(fixture / "task.py", "VALUE = 1\n")
    home.mkdir()
    _readonly_tree(source)
    _readonly_tree(fixture)
    binary = _isolated_fake_codex(tmp)
    return SubscriptionLiveRunner(
        codex_binary=binary,
        codex_home=home,
        source_checkout=source,
        fixture_template=fixture,
        execution_root=tmp / "live-output",
        required_models={"gpt-5.5": {"high"}, "gpt-5.6-sol": {"high"}, "gpt-5.6-terra": {"high"}},
        base_env={**os.environ, **(env or {})},
    )


def _slot(treatment: str = "sol_v3", *, eligible: bool = True) -> SlotRequest:
    return SlotRequest(
        slot_id=f"single-file--{treatment}",
        case_id="single-file-implementation",
        treatment=treatment,
        model={"gpt55_current": "gpt-5.5", "terra_scout": "gpt-5.6-terra"}.get(treatment, "gpt-5.6-sol"),
        case_task="Implement the requested bounded change.",
        historical_prompt="HISTORICAL PREFIX\n",
        fresh_prompt="FRESH V3 PREFIX\n",
        output_schema={"type": "object", "required": ["status", "verdict"]},
        terra_eligible=eligible,
        rejected_role=None if eligible else "implementation",
        matrix_policy_digest="a" * 64,
        timeout_seconds=5.0,
    )


def _is_isolated_exec(call: dict[str, object]) -> bool:
    argv = call.get("argv")
    return (
        isinstance(argv, list)
        and argv[:1] == ["exec"]
        and "--json" in argv
        and "--ignore-user-config" in argv
    )


def check_preflight_and_execution() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-live-runner-") as raw:
        tmp = Path(raw)
        log = tmp / "invocations.jsonl"
        runner = _runner(
            tmp,
            env={
                "CPE_FAKE_LOGIN": "chatgpt",
                "CPE_FAKE_MODELS": json.dumps(
                    [
                        {"model": "gpt-5.5", "reasoning_efforts": ["high"]},
                        {"model": "gpt-5.6-sol", "reasoning_efforts": ["high"]},
                        {"model": "gpt-5.6-terra", "reasoning_efforts": ["high"]},
                    ]
                ),
                "CPE_FAKE_INVOCATION_LOG": str(log),
                "OPENAI_API_KEY": "must-not-leak",
                "CODEX_API_KEY": "must-not-leak",
            },
        )
        attestation = runner.preflight()
        assert attestation["authentication"] == "chatgpt"
        assert attestation["catalog"]["gpt-5.6-sol"] == ["high"]
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        catalog_call = next(call for call in calls if call["argv"][:2] == ["app-server", "--stdio"])
        assert '"method": "model/list"' in catalog_call["stdin"]

        result = runner.run_slot(_slot())
        assert result["status"] == "completed"
        assert result["usage"] == {
            "input_tokens": 1,
            "cached_input_tokens": 0,
            "output_tokens": 1,
            "reasoning_output_tokens": 0,
        }
        assert result["cost_usd"] is None
        assert result["cost_observability"] == "unavailable"
        assert result["billing_boundary"]
        assert result["attempts"] == 1
        assert result["prompt_sha256"]

        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        execution = next(call for call in calls if _is_isolated_exec(call))
        assert "--ephemeral" in execution["argv"]
        assert execution["env"].get("CODEX_HOME") == str(runner.codex_home)
        assert "OPENAI_API_KEY" not in execution["env"]
        assert "CODEX_API_KEY" not in execution["env"]
        prompt = execution["stdin"]
        assert prompt.startswith("FRESH V3 PREFIX\n")
        assert "Implement the requested bounded change." in prompt
        assert str(result["repository_path"]) in prompt
        assert prompt.index("FRESH V3 PREFIX") < prompt.index(str(result["repository_path"]))

        historical = runner.run_slot(_slot("gpt55_current"))
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        historical_call = [call for call in calls if _is_isolated_exec(call)][-1]
        assert historical_call["stdin"].startswith("HISTORICAL PREFIX\n")
        assert historical["repository_path"] != result["repository_path"]


def check_policy_rejection_does_not_launch() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-live-policy-") as raw:
        tmp = Path(raw)
        log = tmp / "invocations.jsonl"
        runner = _runner(
            tmp,
            env={
                "CPE_FAKE_LOGIN": "chatgpt",
                "CPE_FAKE_MODELS": json.dumps(
                    [{"model": model, "reasoning_efforts": ["high"]} for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")]
                ),
                "CPE_FAKE_INVOCATION_LOG": str(log),
            },
        )
        runner.preflight()
        before = len(log.read_text(encoding="utf-8").splitlines())
        result = runner.run_slot(_slot("terra_scout", eligible=False))
        after = len(log.read_text(encoding="utf-8").splitlines())
        assert before == after
        assert result["expected_policy_failure"] is True
        assert result["rejected_role"] == "implementation"
        assert result["matrix_policy_digest"] == "a" * 64


def check_fail_closed_preflight() -> None:
    for login in ("api_key", "logged_out"):
        with tempfile.TemporaryDirectory(prefix="cpe-live-auth-") as raw:
            tmp = Path(raw)
            runner = _runner(tmp, env={"CPE_FAKE_LOGIN": login, "CPE_FAKE_MODELS": "[]"})
            try:
                runner.preflight()
            except LiveRunnerError as exc:
                assert exc.code in {"api_key_authentication", "chatgpt_login_required"}
            else:
                raise AssertionError(f"preflight accepted {login}")

    with tempfile.TemporaryDirectory(prefix="cpe-live-auth-exact-") as raw:
        tmp = Path(raw)
        runner = _runner(
            tmp,
            env={"CPE_FAKE_LOGIN": "chatgpt_extra", "CPE_FAKE_MODELS": "[]"},
        )
        try:
            runner.preflight()
        except LiveRunnerError as exc:
            assert exc.code == "chatgpt_login_required"
        else:
            raise AssertionError("preflight accepted an inexact ChatGPT attestation")

    with tempfile.TemporaryDirectory(prefix="cpe-live-model-") as raw:
        tmp = Path(raw)
        runner = _runner(
            tmp,
            env={
                "CPE_FAKE_LOGIN": "chatgpt",
                "CPE_FAKE_MODELS": json.dumps(
                    [{"model": "gpt-5.6-sol", "reasoning_efforts": ["high"]}]
                ),
            },
        )
        try:
            runner.preflight()
        except LiveRunnerError as exc:
            assert exc.code == "required_model_unavailable"
        else:
            raise AssertionError("preflight accepted a missing matrix model")


def check_public_interfaces_and_prompt_isolation() -> None:
    assert CodexAttestation.__dataclass_fields__
    assert RunContext.__dataclass_fields__
    assert callable(preflight_codex)
    assert callable(render_prompt)
    assert callable(run_slot)

    manifest = compile_manifest(
        ROOT,
        "chatgpt_subscription",
        "1" * 40,
        "2026-07-11T00:00:00Z",
        "runner-contract-check",
    )
    with tempfile.TemporaryDirectory(prefix="cpe-live-prompt-") as raw:
        fixture = materialize_fixture(
            ROOT / "live-migration",
            EXPECTED_CASES[0],
            Path(raw) / "repo",
        )
        for treatment in ("gpt55_current", "sol_current", "sol_v3"):
            slot = next(item for item in manifest["slots"] if item["treatment_id"] == treatment)
            prompt = render_prompt(slot, fixture, ROOT)
            prefix_ref = str(slot["prompt_renderer"])
            source = (ROOT / "live-migration" / prefix_ref).resolve().read_bytes()
            prefix = worker_prompt_bytes(source, prefix_ref).decode("utf-8")
            assert prompt.startswith(prefix)
            assert str(fixture.contract["task"]) in prompt
            assert json.dumps(fixture.contract["allowed_paths"], sort_keys=True) in prompt
            assert json.dumps(fixture.contract["forbidden_paths"], sort_keys=True) in prompt
            assert str(fixture.contract["acceptance_command"]) in prompt
            assert "worker-result-schema.json" in prompt
            assert str(fixture.oracle_dir) not in prompt
            assert "expected.json" not in prompt
            if treatment == "sol_v3":
                assert "{{WORKSPACE}}" not in prompt
                assert "{{PLAN}}" not in prompt
                assert len(prefix.encode("utf-8")) < 256


def check_dry_run_cli_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-live-dry-") as raw:
        tmp = Path(raw)
        output = tmp / "plan.json"
        invocation_log = tmp / "calls.jsonl"
        env = {**os.environ, "CPE_FAKE_INVOCATION_LOG": str(invocation_log)}
        command = [
            sys.executable,
            str(ROOT / "live_model_runner.py"),
            "dry-run",
            "--billing-mode",
            "chatgpt_subscription",
            "--output",
            str(output),
        ]
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["slot_count"] == 32
        assert payload["credentialed_call_count"] == 25
        assert payload["expected_policy_failure_count"] == 7
        assert "budget_usd" not in payload
        assert not invocation_log.exists(), "dry-run invoked Codex"

        for subcommand in ("start", "resume"):
            guarded = subprocess.run(
                [sys.executable, str(ROOT / "live_model_runner.py"), subcommand],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            assert guarded.returncode != 0
            assert "confirm-subscription-usage" in guarded.stderr


def check_execution_root_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-live-boundary-") as raw:
        tmp = Path(raw)
        log = tmp / "invocations.jsonl"
        env = {
            **os.environ,
            "CODEX_HOME": str(tmp / "codex-home"),
            "CPE_FAKE_INVOCATION_LOG": str(log),
        }
        (tmp / "codex-home").mkdir()
        cases = (
            (tmp / "evidence", str(tmp / "absolute-run"), "invalid_run_id", tmp / "absolute-run"),
            (tmp / "evidence", "../escaped-run", "invalid_run_id", tmp / "escaped-run"),
            (
                ROOT / "forbidden-live-evidence",
                "repo-local-run",
                "unsafe_execution_root",
                ROOT / "forbidden-live-evidence" / "repo-local-run",
            ),
        )
        for evidence_root, run_id, expected_code, forbidden_output in cases:
            command = [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "start",
                "--confirm-subscription-usage",
                "--evidence-root",
                str(evidence_root),
                "--run-id",
                run_id,
                "--codex-bin",
                str(ROOT / "fake_codex.py"),
                *_checkpoint_arguments(),
            ]
            completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
            assert completed.returncode != 0
            payload = json.loads(completed.stdout)
            assert payload["error"] == expected_code, (run_id, payload)
            assert not evidence_root.exists()
            assert not forbidden_output.exists()
            assert not log.exists(), f"boundary rejection invoked Codex for {run_id}"


def check_start_checkpoint_binding_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-live-checkpoint-binding-") as raw:
        tmp = Path(raw)
        evidence_root = tmp / "evidence"
        invocation_log = tmp / "invocations.jsonl"
        log = tmp / "invocations.jsonl"
        base_command = [
            sys.executable,
            str(ROOT / "live_model_runner.py"),
            "start",
            "--confirm-subscription-usage",
            "--evidence-root",
            str(evidence_root),
            "--run-id",
            "checkpoint-binding",
            "--codex-bin",
            str(ROOT / "fake_codex.py"),
        ]
        env = {**os.environ, "CPE_FAKE_INVOCATION_LOG": str(log)}

        missing = subprocess.run(
            base_command, cwd=ROOT, env=env, text=True, capture_output=True
        )
        assert missing.returncode != 0
        assert json.loads(missing.stdout)["error"] == "checkpoint_binding_required"

        checkpoint = list(_checkpoint_arguments())
        tree_index = checkpoint.index("--implementation-tree") + 1
        wrong_tree = [*checkpoint]
        wrong_tree[tree_index] = "0" * 40
        mismatched_tree = subprocess.run(
            [*base_command, *wrong_tree],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert mismatched_tree.returncode != 0
        assert json.loads(mismatched_tree.stdout)["error"] == "checkpoint_tree_mismatch"

        patch_index = checkpoint.index("--implementation-patch-sha256") + 1
        wrong_patch = [*checkpoint]
        wrong_patch[patch_index] = "0" * 64
        mismatched_patch = subprocess.run(
            [*base_command, *wrong_patch],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert mismatched_patch.returncode != 0
        assert json.loads(mismatched_patch.stdout)["error"] == "checkpoint_patch_mismatch"

        dirty_marker = ROOT.parent / ".checkpoint-binding-dirty-marker"
        try:
            dirty_marker.write_text("unreviewed\n", encoding="utf-8")
            dirty = subprocess.run(
                [*base_command, *checkpoint],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
        finally:
            dirty_marker.unlink(missing_ok=True)
        assert dirty.returncode != 0
        assert json.loads(dirty.stdout)["error"] == "checkpoint_worktree_mismatch"
        assert not evidence_root.exists()
        assert not log.exists(), "checkpoint rejection invoked Codex"


def check_start_persists_authenticated_catalog_for_aggregation() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-live-catalog-binding-") as raw:
        tmp = Path(raw)
        run_id = "catalog-bound-run"
        evidence_root = tmp / "evidence"
        invocation_log = tmp / "invocations.jsonl"
        codex_home = tmp / "codex-home"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
        env = {
            **os.environ,
            "CODEX_HOME": str(codex_home),
            "CPE_FAKE_LOGIN": "chatgpt",
            "CPE_FAKE_MODELS": json.dumps(
                [
                    {"model": model, "reasoning_efforts": ["high"]}
                    for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")
                ]
            ),
            "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
        }
        attestation = preflight_codex(ROOT / "fake_codex.py", env)
        started = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "start",
                "--confirm-subscription-usage",
                "--evidence-root",
                str(evidence_root),
                "--run-id",
                run_id,
                "--codex-bin",
                str(ROOT / "fake_codex.py"),
                "--slot-timeout-seconds",
                "2",
                *_checkpoint_arguments(),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert started.returncode == 0, (started.stdout, started.stderr)

        run_dir = evidence_root / run_id
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["model_catalog_sha256"] == attestation.catalog_sha256
        body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        assert manifest["manifest_sha256"] == sha256_bytes(canonical_json(body))
        run_home = run_dir / "codex-home"
        assert {path.name for path in run_home.iterdir()} <= {"auth.json", "sessions"}
        calls = [json.loads(line) for line in invocation_log.read_text(encoding="utf-8").splitlines()]
        executions = [call for call in calls if _is_isolated_exec(call)]
        assert executions
        assert all(
            Path(call["env"].get("CODEX_HOME", "")).resolve() == run_home.resolve()
            for call in executions
        )
        assert all(call["env"].get("PYTHONDONTWRITEBYTECODE") == "1" for call in executions)

        report = tmp / "report.json"
        aggregated = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_migration.py"),
                "--confirm-subscription-usage",
                "--run-dir",
                str(run_dir),
                "--output",
                str(report),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert aggregated.returncode == 1, (aggregated.stdout, aggregated.stderr)
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["model_catalog_sha256"] == attestation.catalog_sha256
        assert payload["release_gate"]["failures"] == [
            "context_token_reduction_below_25_percent"
        ]


def check_slot_failures_are_explicit() -> None:
    expected = {
        "malformed": "malformed_output",
        "billing": "subscription_limit_reached",
        "structured_billing": "subscription_limit_reached",
        "timeout": "timeout_retry_required",
    }
    for behavior, code in expected.items():
        with tempfile.TemporaryDirectory(prefix=f"cpe-live-{behavior}-") as raw:
            tmp = Path(raw)
            runner = _runner(
                tmp,
                env={
                    "CPE_FAKE_LOGIN": "chatgpt",
                    "CPE_FAKE_MODELS": json.dumps(
                        [{"model": model, "reasoning_efforts": ["high"]} for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")]
                    ),
                    "CPE_FAKE_LIVE_BEHAVIOR": behavior,
                },
            )
            runner.preflight()
            request = _slot()
            if behavior == "timeout":
                request = SlotRequest(**{**request.__dict__, "timeout_seconds": 0.05})
            try:
                runner.run_slot(request)
            except LiveRunnerError as exc:
                assert exc.code == code, (behavior, exc.code)
            else:
                raise AssertionError(f"slot behavior did not fail closed: {behavior}")
            events = tmp / "live-output" / "slots" / request.slot_id / "evidence" / "events.jsonl"
            assert events.is_file()
            if behavior == "billing":
                try:
                    runner.run_slot(_slot("gpt55_current"))
                except LiveRunnerError as exc:
                    assert exc.code == "live_run_stopped"
                else:
                    raise AssertionError("billing failure did not stop the live run")

    with tempfile.TemporaryDirectory(prefix="cpe-live-stdout-marker-") as raw:
        tmp = Path(raw)
        runner = _runner(
            tmp,
            env={
                "CPE_FAKE_LOGIN": "chatgpt",
                "CPE_FAKE_MODELS": json.dumps(
                    [
                        {"model": model, "reasoning_efforts": ["high"]}
                        for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")
                    ]
                ),
                "CPE_FAKE_LIVE_BEHAVIOR": "stdout_marker",
            },
        )
        runner.preflight()
        assert runner.run_slot(_slot())["status"] == "completed"


def _assert_process_exited(pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError(f"timed-out descendant remained alive: {pid}")


def check_public_failure_lifecycle() -> None:
    expected = {
        "malformed": "malformed_output",
        "schema_invalid": "malformed_output",
        "billing": "subscription_limit_reached",
        "nonzero": "codex_execution_failed",
        "timeout": "timeout_retry_required",
    }
    for behavior, code in expected.items():
        with tempfile.TemporaryDirectory(prefix=f"cpe-public-{behavior}-") as raw:
            tmp = Path(raw)
            run_id = f"public-{behavior}"
            evidence_root = tmp / "evidence"
            invocation_log = tmp / "calls.jsonl"
            descendant_pid = tmp / "descendant.pid"
            codex_home = tmp / "codex-home"
            codex_home.mkdir()
            (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
            env = {
                **os.environ,
                "CODEX_HOME": str(codex_home),
                "CPE_FAKE_LOGIN": "chatgpt",
                "CPE_FAKE_MODELS": json.dumps(
                    [{"model": model, "reasoning_efforts": ["high"]} for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")]
                ),
                "CPE_FAKE_LIVE_BEHAVIOR": behavior,
                "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
                "CPE_FAKE_DESCENDANT_PID": str(descendant_pid),
            }
            command = [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "start",
                "--confirm-subscription-usage",
                "--evidence-root",
                str(evidence_root),
                "--run-id",
                run_id,
                "--codex-bin",
                str(ROOT / "fake_codex.py"),
                "--slot-timeout-seconds",
                "1",
                *_checkpoint_arguments(),
            ]
            failed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
            assert failed.returncode != 0, (behavior, failed.stdout, failed.stderr)
            assert json.loads(failed.stdout)["error"] == code

            run_dir = evidence_root / run_id
            state = replay_run(run_dir)
            assert state["active_slot"] is None
            assert len(state["failed_slots"]) == 1
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            failure = next(event for event in events if event["type"] == "slot_failed")
            assert failure["payload"]["code"] == code
            assert events[-1]["type"] == "run_blocked"
            for relative, digest in failure["payload"]["evidence_sha256"].items():
                artifact = run_dir / relative
                assert artifact.is_file(), artifact
                assert hashlib.sha256(artifact.read_bytes()).hexdigest() == digest

            calls_before_resume = invocation_log.read_text(encoding="utf-8")
            resume = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "live_model_runner.py"),
                    "resume",
                    "--confirm-subscription-usage",
                    "--run-dir",
                    str(run_dir),
                    "--codex-bin",
                    str(ROOT / "fake_codex.py"),
                ],
                cwd=ROOT,
                env={**env, "CPE_FAKE_LIVE_BEHAVIOR": "success"},
                text=True,
                capture_output=True,
            )
            assert resume.returncode != 0
            assert json.loads(resume.stdout)["error"] == "retry_failed_required"
            assert invocation_log.read_text(encoding="utf-8") == calls_before_resume
            if behavior in {"billing", "nonzero", "timeout"}:
                retried = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "live_model_runner.py"),
                        "resume",
                        "--confirm-subscription-usage",
                        "--retry-failed",
                        "--run-dir",
                        str(run_dir),
                        "--codex-bin",
                        str(ROOT / "fake_codex.py"),
                        "--slot-timeout-seconds",
                        "2",
                    ],
                    cwd=ROOT,
                    env={**env, "CPE_FAKE_LIVE_BEHAVIOR": "success"},
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
                assert retried.returncode == 0, (retried.stdout, retried.stderr)
                retried_state = replay_run(run_dir)
                assert retried_state["active_slot"] is None
                assert retried_state["failed_slots"] == []
                assert len(retried_state["completed_slots"]) == 32
                events_after_retry = [
                    json.loads(line)
                    for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                retry_events = [
                    event for event in events_after_retry
                    if event["type"] == "slot_retry_started"
                ]
                assert len(retry_events) == 1
                assert retry_events[0]["payload"] == {
                    "treatment_id": failure["payload"]["treatment_id"],
                    "case_id": failure["payload"]["case_id"],
                }
            if behavior == "timeout":
                _assert_process_exited(int(descendant_pid.read_text(encoding="utf-8")))


def check_interrupted_resume_requires_retry() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-public-interrupted-") as raw:
        tmp = Path(raw)
        run_id = "public-interrupted"
        manifest = _bind_reviewed_checkpoint(
            compile_manifest(
                ROOT,
                "chatgpt_subscription",
                "1" * 40,
                "2026-07-11T00:00:00Z",
                run_id,
            )
        )
        run = create_run(tmp / run_id, manifest)
        _seed_run_codex_home(run.run_dir)
        first = manifest["slots"][0]
        append_event(run, "slot_started", {"treatment_id": first["treatment_id"], "case_id": first["case_id"]})
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "resume",
                "--confirm-subscription-usage",
                "--run-dir",
                str(run.run_dir),
                "--codex-bin",
                str(ROOT / "fake_codex.py"),
            ],
            cwd=ROOT,
            env={**os.environ, "CODEX_HOME": str(tmp / "missing-home")},
            text=True,
            capture_output=True,
        )
        assert completed.returncode != 0
        assert json.loads(completed.stdout)["error"] == "retry_failed_required"
        state = replay_run(run.run_dir)
        assert state["active_slot"] is None
        assert state["failed_slots"] == [
            {"treatment_id": first["treatment_id"], "case_id": first["case_id"]}
        ]
        events = [
            json.loads(line)
            for line in (run.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert events[-1]["type"] == "slot_failed"
        assert events[-1]["payload"]["code"] == "interrupted_slot_abandoned"


def check_partial_resume_does_not_duplicate_completed_calls() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-public-partial-") as raw:
        tmp = Path(raw)
        invocation_log = tmp / "calls.jsonl"
        codex_home = tmp / "codex-home"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
        env = {
            **os.environ,
            "CODEX_HOME": str(codex_home),
            "CPE_FAKE_LOGIN": "chatgpt",
            "CPE_FAKE_MODELS": json.dumps(
                [
                    {"model": model, "reasoning_efforts": ["high"]}
                    for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")
                ]
            ),
            "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
        }
        manifest = _bind_reviewed_checkpoint(
            compile_manifest(
                ROOT,
                "chatgpt_subscription",
                "1" * 40,
                "2026-07-11T00:00:00Z",
                "public-partial",
            )
        )
        run = create_run(tmp / "public-partial", manifest)
        _seed_run_codex_home(run.run_dir)
        attestation = preflight_codex(_isolated_fake_codex(tmp), env)
        context = RunContext(run, ROOT, attestation, env, 2, False)
        first = next(slot for slot in manifest["slots"] if slot["outcome_kind"] == "credentialed_call")
        run_slot(context, first)

        resumed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "resume",
                "--confirm-subscription-usage",
                "--run-dir",
                str(run.run_dir),
                "--codex-bin",
                str(ROOT / "fake_codex.py"),
                "--slot-timeout-seconds",
                "2",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
        calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        executions = [call for call in calls if _is_isolated_exec(call)]
        assert len(executions) == manifest["credentialed_call_count"]
        state = replay_run(run.run_dir)
        assert len(state["completed_slots"]) == len(manifest["slots"])


def check_concurrent_resume_is_rejected_without_duplicate_calls() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-public-concurrent-") as raw:
        tmp = Path(raw)
        invocation_log = tmp / "calls.jsonl"
        codex_home = tmp / "codex-home"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
        env = {
            **os.environ,
            "CODEX_HOME": str(codex_home),
            "CPE_FAKE_LOGIN": "chatgpt",
            "CPE_FAKE_MODELS": json.dumps(
                [
                    {"model": model, "reasoning_efforts": ["high"]}
                    for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")
                ]
            ),
            "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
            "CPE_FAKE_LIVE_DELAY_SECONDS": "0.05",
        }
        manifest = _bind_reviewed_checkpoint(
            compile_manifest(
                ROOT,
                "chatgpt_subscription",
                "1" * 40,
                "2026-07-11T00:00:00Z",
                "public-concurrent",
            )
        )
        run = create_run(tmp / "public-concurrent", manifest)
        _seed_run_codex_home(run.run_dir)
        command = [
            sys.executable,
            str(ROOT / "live_model_runner.py"),
            "resume",
            "--confirm-subscription-usage",
            "--run-dir",
            str(run.run_dir),
            "--codex-bin",
            str(ROOT / "fake_codex.py"),
            "--slot-timeout-seconds",
            "2",
        ]
        first = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if invocation_log.is_file() and '"exec"' in invocation_log.read_text(encoding="utf-8"):
                break
            time.sleep(0.01)
        else:
            first.kill()
            raise AssertionError("first resume did not launch a slot")
        second = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=5,
        )
        first_stdout, first_stderr = first.communicate(timeout=30)
        assert first.returncode == 0, (first_stdout, first_stderr)
        assert second.returncode != 0
        assert json.loads(second.stdout)["error"] == "run_already_executing"
        calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        executions = [call for call in calls if _is_isolated_exec(call)]
        assert len(executions) == manifest["credentialed_call_count"]


def check_resume_cannot_abandon_an_active_start() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-public-start-lock-") as raw:
        tmp = Path(raw)
        run_id = "public-active-start"
        evidence_root = tmp / "evidence"
        run_dir = evidence_root / run_id
        invocation_log = tmp / "calls.jsonl"
        codex_home = tmp / "codex-home"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
        env = {
            **os.environ,
            "CODEX_HOME": str(codex_home),
            "CPE_FAKE_LOGIN": "chatgpt",
            "CPE_FAKE_MODELS": json.dumps(
                [
                    {"model": model, "reasoning_efforts": ["high"]}
                    for model in ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra")
                ]
            ),
            "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
            "CPE_FAKE_LIVE_DELAY_SECONDS": "0.05",
        }
        start = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "start",
                "--confirm-subscription-usage",
                "--evidence-root",
                str(evidence_root),
                "--run-id",
                run_id,
                "--codex-bin",
                str(ROOT / "fake_codex.py"),
                "--slot-timeout-seconds",
                "2",
                *_checkpoint_arguments(),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if invocation_log.is_file() and '"exec"' in invocation_log.read_text(encoding="utf-8"):
                break
            time.sleep(0.01)
        else:
            start.kill()
            raise AssertionError("start did not launch a slot")
        resume = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "resume",
                "--confirm-subscription-usage",
                "--run-dir",
                str(run_dir),
                "--codex-bin",
                str(ROOT / "fake_codex.py"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=5,
        )
        start_stdout, start_stderr = start.communicate(timeout=30)
        assert start.returncode == 0, (start_stdout, start_stderr)
        assert resume.returncode != 0
        assert json.loads(resume.stdout)["error"] == "run_already_executing"
        state = replay_run(run_dir)
        assert state["failed_slots"] == []
        calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        executions = [call for call in calls if _is_isolated_exec(call)]
        assert len(executions) == 25


def main() -> int:
    check_fake_codex_launcher_modes()
    check_public_interfaces_and_prompt_isolation()
    check_dry_run_cli_contract()
    check_execution_root_boundaries()
    check_start_checkpoint_binding_fails_closed()
    check_start_persists_authenticated_catalog_for_aggregation()
    check_preflight_and_execution()
    check_policy_rejection_does_not_launch()
    check_fail_closed_preflight()
    check_slot_failures_are_explicit()
    check_public_failure_lifecycle()
    check_interrupted_resume_requires_retry()
    check_partial_resume_does_not_duplicate_completed_calls()
    check_concurrent_resume_is_rejected_without_duplicate_calls()
    check_resume_cannot_abandon_an_active_start()
    print("live model runner checks passed")
    return 0


if __name__ == "__main__":
    reviewed_checkout_result = _run_from_clean_reviewed_checkout()
    raise SystemExit(main() if reviewed_checkout_result is None else reviewed_checkout_result)
