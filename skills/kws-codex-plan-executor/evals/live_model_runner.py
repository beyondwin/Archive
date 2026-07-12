#!/usr/bin/env python3
"""Guarded CLI for the ChatGPT subscription live-migration matrix."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from live_migration.compiler import compile_manifest, compile_v4_manifest
from live_migration.contracts import (
    CHATGPT_SUBSCRIPTION,
    SlotKey,
    canonical_json,
    sha256_bytes,
)
from live_migration.ledger import (
    LedgerError,
    LiveRun,
    append_event,
    create_run,
    load_registered_release_manifest,
    record_release_terminal,
    register_release_run,
    replay_run,
)
from live_model_migration import aggregate_run
from live_migration.runner import (
    API_KEY_ENV_NAMES,
    LiveRunnerError,
    RunContext,
    preflight_codex,
    run_slot,
)


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[2]
DEFAULT_CODEX_BINARY = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
GIT_OID = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
INVOCATION_POLICY = {
    "api_key_environment": "removed",
    "authentication": CHATGPT_SUBSCRIPTION,
    "codex_binary": "chatgpt_app_bundled",
    "completed_call_retry": "forbidden",
    "execution_order": "sequential",
    "session_persistence": "new_thread_with_session_attestation",
    "slot_isolation": "fresh_fixture_copy",
    "user_home_isolation": "run_local_auth_only_codex_home",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dry = commands.add_parser("dry-run")
    dry.add_argument("--billing-mode", default=CHATGPT_SUBSCRIPTION)
    dry.add_argument("--output", type=Path, required=True)
    dry.add_argument("--run-id", default="cpe-v3-subscription-dry-run")
    dry.add_argument("--matrix", choices=("v4",))
    _add_checkpoint_arguments(dry)

    start = commands.add_parser("start")
    start.add_argument("--billing-mode", default=CHATGPT_SUBSCRIPTION)
    start.add_argument("--confirm-subscription-usage", action="store_true")
    start.add_argument("--evidence-root", type=Path)
    start.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX_BINARY)
    start.add_argument("--run-id")
    start.add_argument("--slot-timeout-seconds", type=int, default=900)
    start.add_argument("--matrix", choices=("v4",))
    start.add_argument("--sentinel-only", action="store_true")
    _add_checkpoint_arguments(start)

    resume = commands.add_parser("resume")
    resume.add_argument("--run-dir", type=Path)
    resume.add_argument("--confirm-subscription-usage", action="store_true")
    resume.add_argument("--retry-failed", action="store_true")
    resume.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX_BINARY)
    resume.add_argument("--slot-timeout-seconds", type=int, default=900)

    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--run-dir", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    return parser


def _add_checkpoint_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--implementation-commit")
    parser.add_argument("--implementation-tree")
    parser.add_argument("--implementation-patch-sha256")


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _created_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=True
    ).stdout


def _validate_checkpoint_binding(
    values: dict[str, object],
) -> dict[str, str]:
    binding = {key: str(value) for key, value in values.items()}
    if GIT_OID.fullmatch(binding["implementation_commit"]) is None:
        raise LiveRunnerError("invalid_checkpoint_binding", "implementation commit must be a Git SHA-1")
    if GIT_OID.fullmatch(binding["implementation_tree"]) is None:
        raise LiveRunnerError("invalid_checkpoint_binding", "implementation tree must be a Git SHA-1")
    if SHA256.fullmatch(binding["implementation_patch_sha256"]) is None:
        raise LiveRunnerError("invalid_checkpoint_binding", "implementation patch must be a SHA-256")
    actual_tree = _git_bytes(
        "rev-parse", f"{binding['implementation_commit']}^{{tree}}"
    ).decode().strip()
    if actual_tree != binding["implementation_tree"]:
        raise LiveRunnerError("checkpoint_tree_mismatch", "implementation commit does not match its reviewed tree")
    actual_patch = sha256_bytes(
        _git_bytes("show", "--format=", "--binary", binding["implementation_commit"])
    )
    if actual_patch != binding["implementation_patch_sha256"]:
        raise LiveRunnerError("checkpoint_patch_mismatch", "implementation commit does not match its reviewed patch")
    return binding


def _assert_execution_checkpoint(binding: dict[str, str]) -> None:
    current_commit = _git_commit()
    if current_commit != binding["implementation_commit"]:
        raise LiveRunnerError(
            "checkpoint_commit_mismatch",
            "the executing checkout is not at the reviewed implementation commit",
        )
    status = _git_bytes("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise LiveRunnerError(
            "checkpoint_worktree_mismatch",
            "the executing checkout contains changes outside the reviewed implementation tree",
        )


def _manifest_checkpoint_binding(manifest: dict[str, object]) -> dict[str, str]:
    values = {
        "implementation_commit": manifest.get("implementation_commit"),
        "implementation_tree": manifest.get("implementation_tree"),
        "implementation_patch_sha256": manifest.get("implementation_patch_sha256"),
    }
    if any(value is None for value in values.values()):
        raise LiveRunnerError(
            "checkpoint_binding_required",
            "live execution requires the reviewed implementation commit, tree, and patch SHA-256",
        )
    return _validate_checkpoint_binding(values)


def _checkpoint_binding(args: argparse.Namespace, *, required: bool) -> dict[str, str]:
    values: dict[str, object] = {
        "implementation_commit": args.implementation_commit,
        "implementation_tree": args.implementation_tree,
        "implementation_patch_sha256": args.implementation_patch_sha256,
    }
    supplied = [value is not None for value in values.values()]
    if any(supplied) and not all(supplied):
        raise LiveRunnerError(
            "incomplete_checkpoint_binding",
            "implementation commit, tree, and patch SHA-256 must be supplied together",
        )
    if not any(supplied):
        if required:
            raise LiveRunnerError(
                "checkpoint_binding_required",
                "live execution requires the reviewed implementation commit, tree, and patch SHA-256",
            )
        commit = _git_commit()
        tree = _git_bytes("rev-parse", f"{commit}^{{tree}}").decode().strip()
        patch_sha256 = sha256_bytes(_git_bytes("show", "--format=", "--binary", commit))
        return {
            "implementation_commit": commit,
            "implementation_tree": tree,
            "implementation_patch_sha256": patch_sha256,
        }

    binding = _validate_checkpoint_binding(values)
    if required:
        _assert_execution_checkpoint(binding)
    return binding


def _bind_manifest(
    manifest: dict[str, object], binding: dict[str, str]
) -> dict[str, object]:
    manifest.update(binding)
    manifest["invocation_policy"] = INVOCATION_POLICY
    manifest["invocation_policy_sha256"] = sha256_bytes(canonical_json(INVOCATION_POLICY))
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    manifest["manifest_sha256"] = sha256_bytes(canonical_json(manifest_body))
    return manifest


def _compile(
    billing_mode: str,
    run_id: str,
    binding: dict[str, str],
    *,
    matrix: str | None = None,
) -> dict[str, object]:
    if matrix == "v4":
        if billing_mode != CHATGPT_SUBSCRIPTION:
            raise LiveRunnerError(
                "unsupported_billing_mode", "v4 requires ChatGPT subscription billing"
            )
        manifest = compile_v4_manifest(
            binding["implementation_commit"],
            run_id,
            eval_dir=ROOT,
            created_at=_created_at(),
        )
    else:
        manifest = compile_manifest(
            ROOT, billing_mode, binding["implementation_commit"], _created_at(), run_id
        )
    return _bind_manifest(manifest, binding)


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or path.is_relative_to(parent)


def _assert_execution_root_safe(path: Path) -> None:
    protected = (REPOSITORY_ROOT.resolve(), (ROOT / "live-migration").resolve())
    if any(_is_within(path, item) for item in protected):
        raise LiveRunnerError("unsafe_execution_root", "live execution must remain outside repository inputs")


def _new_run_dir(evidence_root: Path, run_id: str) -> Path:
    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise LiveRunnerError("invalid_run_id", "run ID must be one bounded path-safe component")
    root = evidence_root.expanduser().resolve()
    run_dir = (root / run_id).resolve()
    if run_dir.parent != root:
        raise LiveRunnerError("unsafe_execution_root", "run directory must be a direct child of the evidence root")
    _assert_execution_root_safe(root)
    _assert_execution_root_safe(run_dir)
    return run_dir


def _dry_run(args: argparse.Namespace) -> dict[str, object]:
    manifest = _compile(
        args.billing_mode,
        args.run_id,
        _checkpoint_binding(args, required=False),
        matrix=args.matrix,
    )
    payload = {
        "status": "dry_run",
        "run_id": manifest["run_id"],
        "billing_mode": manifest["billing_mode"],
        "slot_count": len(manifest["slots"]),
        "credentialed_call_count": manifest["credentialed_call_count"],
        "expected_policy_failure_count": manifest["expected_policy_failure_count"],
        "implementation_commit": manifest["implementation_commit"],
        "implementation_tree": manifest["implementation_tree"],
        "implementation_patch_sha256": manifest["implementation_patch_sha256"],
        "invocation_policy_sha256": manifest["invocation_policy_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "slots": manifest["slots"],
        "next_action": (
            "review and commit the plan, then run start with the reviewed "
            "--implementation-commit, --implementation-tree, and "
            "--implementation-patch-sha256"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def _child_env(codex_home: Path) -> dict[str, str]:
    child = {key: value for key, value in os.environ.items() if key not in API_KEY_ENV_NAMES}
    child["CODEX_HOME"] = str(codex_home)
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    return child


def _run_codex_home(run: LiveRun, source_home: Path, *, create: bool) -> Path:
    """Create or validate the auth-only Codex home owned by one live ledger."""

    target = run.run_dir / "codex-home"
    auth = target / "auth.json"
    if create:
        source_auth = source_home.expanduser().resolve() / "auth.json"
        if not source_auth.is_file() or source_auth.is_symlink():
            raise LiveRunnerError(
                "subscription_auth_unavailable",
                "ChatGPT subscription auth.json is required for the run-local Codex home",
            )
        target.mkdir(mode=0o700, exist_ok=False)
        shutil.copyfile(source_auth, auth)
        auth.chmod(0o600)
    if (
        not target.is_dir()
        or target.is_symlink()
        or not auth.is_file()
        or auth.is_symlink()
        or target.resolve().parent != run.run_dir.resolve()
    ):
        raise LiveRunnerError(
            "run_codex_home_invalid",
            "live execution requires its original auth-only run-local Codex home",
        )
    return target.resolve()


def _recover_unstarted_v4_run(
    run_dir: Path, manifest: dict[str, object]
) -> LiveRun:
    """Recover only an exact child ledger with no slot execution history."""

    stored = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if canonical_json(stored) != canonical_json(manifest):
        raise LiveRunnerError(
            "registered_child_manifest_mismatch",
            "existing child ledger uses a different registered manifest",
        )
    run = LiveRun(run_dir, stored, str(stored["manifest_sha256"]))
    state = replay_run(run_dir)
    if (
        state.get("event_count") != 0
        or state.get("completed_slots")
        or state.get("failed_slots")
        or state.get("active_slot") is not None
    ):
        raise LiveRunnerError(
            "registered_child_already_started",
            "existing child ledger has slot execution history and cannot restart",
        )
    return run


def _initialize_recoverable_run_codex_home(
    run: LiveRun, source_home: Path
) -> Path:
    """Idempotently finish auth-only home initialization before slot execution."""

    if replay_run(run.run_dir).get("event_count") != 0:
        raise LiveRunnerError(
            "registered_child_already_started",
            "auth initialization recovery is forbidden after slot execution starts",
        )
    source_auth = source_home.expanduser().resolve() / "auth.json"
    if not source_auth.is_file() or source_auth.is_symlink():
        raise LiveRunnerError(
            "subscription_auth_unavailable",
            "ChatGPT subscription auth.json is required for recovery",
        )
    target = run.run_dir / "codex-home"
    target.mkdir(mode=0o700, exist_ok=True)
    if target.is_symlink():
        raise LiveRunnerError("run_codex_home_invalid", "recoverable Codex home is malformed")
    for child in target.iterdir():
        if child.name.startswith(".auth-") and child.name.endswith(".tmp"):
            if not child.is_file() or child.is_symlink():
                raise LiveRunnerError("run_codex_home_invalid", "auth temporary is unsafe")
            child.unlink()
        elif child.name != "auth.json":
            raise LiveRunnerError("run_codex_home_invalid", "recoverable Codex home is malformed")
    auth = target / "auth.json"
    if not auth.exists():
        temporary = target / f".auth-{uuid.uuid4().hex}.tmp"
        shutil.copyfile(source_auth, temporary)
        temporary.chmod(0o600)
        os.replace(temporary, auth)
    if not auth.is_file() or auth.is_symlink():
        raise LiveRunnerError("run_codex_home_invalid", "recoverable auth file is invalid")
    return target.resolve()


def _preflight_codex(
    codex_binary: Path, required_models: tuple[str, ...] | None = None
):
    """Accept the app CLI's stderr login-status stream without weakening its value."""

    original_run = subprocess.run

    def has_catalog_response(stdout: str) -> bool:
        for line in stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("id") == 2 and isinstance(payload.get("result"), dict):
                return True
        return False

    def catalog_fallback(command, run_kwargs, stderr=""):
        probe = original_run(
            [str(command[0]), "debug", "models"],
            env=run_kwargs.get("env"),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if probe.returncode != 0:
            return subprocess.CompletedProcess(command, probe.returncode, probe.stdout, probe.stderr)
        payload = json.loads(probe.stdout)
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return subprocess.CompletedProcess(command, 1, "", probe.stderr)
        data = []
        for model in models:
            if not isinstance(model, dict):
                continue
            data.append(
                {
                    "id": model.get("slug"),
                    "model": model.get("slug"),
                    "supportedReasoningEfforts": [
                        {
                            "reasoningEffort": effort.get("effort"),
                            "description": effort.get("description"),
                        }
                        for effort in model.get("supported_reasoning_levels", [])
                        if isinstance(effort, dict)
                    ],
                }
            )
        response = {"id": 2, "result": {"data": data, "nextCursor": None}}
        return subprocess.CompletedProcess(
            command, 0, json.dumps(response, separators=(",", ":")) + "\n", stderr + probe.stderr
        )

    def run_with_login_status_compatibility(*run_args, **run_kwargs):
        command = run_args[0] if run_args else run_kwargs.get("args")
        try:
            completed = original_run(*run_args, **run_kwargs)
        except subprocess.TimeoutExpired as exc:
            if isinstance(command, (list, tuple)) and list(command[1:]) == ["app-server", "--stdio"]:
                timeout_stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                return catalog_fallback(command, run_kwargs, timeout_stderr)
            raise
        if (
            isinstance(command, (list, tuple))
            and list(command[-2:]) == ["login", "status"]
            and completed.returncode == 0
            and not completed.stdout
            and "Logged in using ChatGPT" in (completed.stderr or "").splitlines()
        ):
            return subprocess.CompletedProcess(
                completed.args,
                completed.returncode,
                "Logged in using ChatGPT\n",
                completed.stderr,
            )
        if (
            isinstance(command, (list, tuple))
            and list(command[1:]) == ["app-server", "--stdio"]
            and (
                completed.returncode != 0
                or (
                    completed.returncode == 0
                    and not has_catalog_response(completed.stdout or "")
                )
            )
        ):
            return catalog_fallback(command, run_kwargs, completed.stderr)
        return completed

    subprocess.run = run_with_login_status_compatibility
    try:
        return preflight_codex(
            codex_binary,
            os.environ,
            required_models=(frozenset(required_models) if required_models else None),
        )
    finally:
        subprocess.run = original_run


def _context(run: LiveRun, args: argparse.Namespace) -> RunContext:
    required_models = (
        ("gpt-5.6-sol", "gpt-5.6-terra")
        if run.manifest.get("schema_version") == "cpe-quality-manifest.v4"
        else None
    )
    attestation = _preflight_codex(args.codex_bin, required_models)
    run_home = _run_codex_home(run, attestation.codex_home, create=False)
    return RunContext(
        run=run,
        eval_dir=ROOT,
        codex=attestation,
        child_env=_child_env(run_home),
        slot_timeout_seconds=args.slot_timeout_seconds,
        retry_failed=bool(getattr(args, "retry_failed", False)),
    )


def _acquire_run_execution_lock(run_dir: Path) -> int:
    descriptor = os.open(run_dir / "manifest.json", os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise LiveRunnerError(
            "run_already_executing", "another process already owns this live run"
        ) from exc
    return descriptor


def _run_slot_with_isolated_user_config(
    context: RunContext, slot: dict[str, object]
) -> dict[str, object]:
    """Add the host-config isolation flag at the T10 launcher boundary."""

    runner_globals = run_slot.__globals__
    runner_subprocess = runner_globals["subprocess"]

    class IsolatedCodexSubprocess:
        def __getattr__(self, name: str):
            return getattr(runner_subprocess, name)

        def Popen(self, argv, *args, **kwargs):
            command = list(argv)
            if (
                command
                and command[0] == str(context.codex.binary)
                and "--output-schema" in command
            ):
                if command[1:2] != ["exec"]:
                    raise LiveRunnerError(
                        "unsafe_codex_invocation",
                        "live Codex invocation must use the exec launcher",
                    )
                if "--ignore-user-config" not in command:
                    command.insert(2, "--ignore-user-config")
            return runner_subprocess.Popen(command, *args, **kwargs)

    runner_globals["subprocess"] = IsolatedCodexSubprocess()
    try:
        return run_slot(context, slot)
    finally:
        runner_globals["subprocess"] = runner_subprocess


def _execute(
    context: RunContext,
    slots: list[dict[str, object]],
    *,
    retry_slots: set[SlotKey] | None = None,
    complete_run: bool = True,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    try:
        binding = _manifest_checkpoint_binding(context.run.manifest)
        _assert_execution_checkpoint(binding)
        for slot in slots:
            _assert_execution_checkpoint(binding)
            slot_context = context
            if retry_slots is not None:
                key = SlotKey(str(slot["treatment_id"]), str(slot["case_id"]))
                slot_context = replace(context, retry_failed=key in retry_slots)
            result = _run_slot_with_isolated_user_config(slot_context, slot)
            results.append(result)
    except LiveRunnerError as exc:
        append_event(context.run, "run_blocked", {"code": exc.code, "message": str(exc)})
        raise
    if complete_run:
        append_event(context.run, "run_completed", {"completed_slots": len(results)})
    state = replay_run(context.run.run_dir)
    return {
        "status": "completed" if complete_run else "sentinel_completed",
        "run_id": context.run.manifest["run_id"],
        "run_dir": str(context.run.run_dir),
        "slot_count": len(context.run.manifest["slots"]),
        "completed_count": len(state["completed_slots"]),
        "credentialed_call_count": context.run.manifest["credentialed_call_count"],
        "expected_policy_failure_count": context.run.manifest["expected_policy_failure_count"],
        "next_action": (
            "aggregate and verify the immutable live report"
            if complete_run
            else "resume the same immutable ledger for pending slots"
        ),
    }


def _register_and_create_v4_run(
    run_dir: Path,
    manifest: dict[str, object],
    *,
    create=create_run,
) -> LiveRun:
    """Idempotently reserve the release attempt, then create its child ledger."""

    register_release_run(run_dir.parent, manifest)
    return create(run_dir, manifest)


def _start(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict[str, object]:
    if not args.confirm_subscription_usage:
        parser.error("start requires --confirm-subscription-usage")
    if args.evidence_root is None:
        parser.error("start requires --evidence-root")
    if args.billing_mode != CHATGPT_SUBSCRIPTION:
        parser.error("this runner requires --billing-mode chatgpt_subscription")
    run_id = args.run_id or f"cpe-live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = _new_run_dir(args.evidence_root, run_id)
    binding = _checkpoint_binding(args, required=True)
    recovered_manifest = load_registered_release_manifest(run_dir.parent, run_id)
    if recovered_manifest is not None:
        if _manifest_checkpoint_binding(recovered_manifest) != binding:
            raise LiveRunnerError(
                "registered_checkpoint_mismatch",
                "registered release manifest uses a different immutable checkpoint",
            )
        manifest = recovered_manifest
    else:
        manifest = _compile(
            args.billing_mode,
            run_id,
            binding,
            matrix=args.matrix,
        )
    recovered_run = None
    if run_dir.exists():
        if recovered_manifest is None:
            raise LiveRunnerError("execution_root_not_fresh", f"run directory already exists: {run_dir}")
        recovered_run = _recover_unstarted_v4_run(run_dir, manifest)
    required_models = (
        ("gpt-5.6-sol", "gpt-5.6-terra")
        if manifest.get("schema_version") == "cpe-quality-manifest.v4"
        else None
    )
    attestation = _preflight_codex(args.codex_bin, required_models)
    if recovered_manifest is not None:
        if manifest.get("model_catalog_sha256") != attestation.catalog_sha256:
            raise LiveRunnerError(
                "registered_catalog_mismatch",
                "authenticated model catalog changed since release registration",
            )
    else:
        manifest["model_catalog_sha256"] = attestation.catalog_sha256
        manifest = _bind_manifest(manifest, {
            "implementation_commit": str(manifest["implementation_commit"]),
            "implementation_tree": str(manifest["implementation_tree"]),
            "implementation_patch_sha256": str(manifest["implementation_patch_sha256"]),
        })
    run = recovered_run or (
        _register_and_create_v4_run(run_dir, manifest)
        if manifest.get("schema_version") == "cpe-quality-manifest.v4"
        else create_run(run_dir, manifest)
    )
    run_home = (
        _initialize_recoverable_run_codex_home(run, attestation.codex_home)
        if manifest.get("schema_version") == "cpe-quality-manifest.v4"
        else _run_codex_home(run, attestation.codex_home, create=True)
    )
    context = RunContext(run, ROOT, attestation, _child_env(run_home), args.slot_timeout_seconds, False)
    descriptor = _acquire_run_execution_lock(run_dir)
    try:
        slots = list(manifest["slots"])
        if args.sentinel_only:
            if manifest.get("schema_version") != "cpe-quality-manifest.v4":
                raise LiveRunnerError(
                    "sentinel_requires_v4", "--sentinel-only requires --matrix v4"
                )
            slots = slots[:1]
        return _execute(context, slots, complete_run=not args.sentinel_only)
    finally:
        os.close(descriptor)


def _privacy_audit(payload: dict[str, object]) -> dict[str, object]:
    serialized = canonical_json(payload).decode("utf-8")
    patterns = {
        "absolute_home_path": r"(?:/Users/|/home/|/private/tmp/|/var/folders/)",
        "credential_material": r"(?:OPENAI_API_KEY|CODEX_API_KEY|auth\.json)",
        "hidden_oracle_path": r"(?:^|[\"/])oracle(?:[\"/])",
        "transcript_surface": r"transcripts?",
    }
    failures = [name for name, pattern in patterns.items() if re.search(pattern, serialized, re.I)]
    return {"passed": not failures, "failures": failures}


def _aggregate(args: argparse.Namespace) -> dict[str, object]:
    run_dir = args.run_dir.expanduser().resolve()
    _assert_execution_root_safe(run_dir)
    aggregate = aggregate_run(run_dir)
    privacy = _privacy_audit(aggregate)
    payload: dict[str, object] = {**aggregate, "privacy_audit": privacy}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(payload))
    aggregate_sha256 = sha256_bytes(canonical_json(aggregate))
    privacy_sha256 = sha256_bytes(canonical_json(privacy))
    gate = aggregate.get("release_gate")
    passed = (
        isinstance(gate, dict)
        and gate.get("passed") is True
        and privacy.get("passed") is True
    )
    record_release_terminal(
        run_dir.parent,
        run_id=str(aggregate["run_id"]),
        manifest_sha256=str(aggregate["manifest_sha256"]),
        passed=passed,
        aggregate_sha256=aggregate_sha256,
        privacy_sha256=privacy_sha256,
    )
    return payload


def _resume(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict[str, object]:
    if not args.confirm_subscription_usage:
        parser.error("resume requires --confirm-subscription-usage")
    if args.run_dir is None:
        parser.error("resume requires --run-dir")
    run_dir = args.run_dir.expanduser().resolve()
    _assert_execution_root_safe(run_dir)
    descriptor = _acquire_run_execution_lock(run_dir)
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        binding = _manifest_checkpoint_binding(manifest)
        _assert_execution_checkpoint(binding)
        run = LiveRun(run_dir, manifest, str(manifest["manifest_sha256"]))
        state = replay_run(run_dir)
        completed = {
            SlotKey(str(item["treatment_id"]), str(item["case_id"]))
            for item in state["completed_slots"]
        }
        failed = {
            SlotKey(str(item["treatment_id"]), str(item["case_id"]))
            for item in state["failed_slots"]
        }
        active = state.get("active_slot")
        interrupted = (
            SlotKey(str(active["treatment_id"]), str(active["case_id"]))
            if isinstance(active, dict)
            else None
        )
        if interrupted is not None:
            append_event(
                run,
                "slot_failed",
                {
                    "treatment_id": interrupted.treatment_id,
                    "case_id": interrupted.case_id,
                    "code": "interrupted_slot_abandoned",
                    "message": "interrupted in-progress slot was abandoned during resume",
                    "evidence_sha256": {},
                },
            )
        if (failed or interrupted is not None) and not args.retry_failed:
            raise LiveRunnerError("retry_failed_required", "failed or interrupted slots require --retry-failed")
        slots = [
            slot for slot in manifest["slots"]
            if SlotKey(str(slot["treatment_id"]), str(slot["case_id"])) not in completed
            and (args.retry_failed or SlotKey(str(slot["treatment_id"]), str(slot["case_id"])) not in failed)
        ]
        retry_slots = set(failed)
        if interrupted is not None:
            retry_slots.add(interrupted)
        return _execute(_context(run, args), slots, retry_slots=retry_slots)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "dry-run":
            result = _dry_run(args)
        elif args.command == "start":
            result = _start(args, parser)
        elif args.command == "resume":
            result = _resume(args, parser)
        else:
            result = _aggregate(args)
    except (
        LedgerError,
        LiveRunnerError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        code = exc.code if isinstance(exc, LiveRunnerError) else "runner_failed"
        print(json.dumps({"status": "blocked", "error": code, "message": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    if args.command == "aggregate":
        gate = result.get("release_gate")
        privacy = result.get("privacy_audit")
        return 0 if (
            isinstance(gate, dict)
            and gate.get("passed") is True
            and isinstance(privacy, dict)
            and privacy.get("passed") is True
        ) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
