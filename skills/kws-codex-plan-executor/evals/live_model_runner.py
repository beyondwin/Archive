#!/usr/bin/env python3
"""Guarded CLI for the ChatGPT subscription live-migration matrix."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from live_migration.compiler import compile_manifest
from live_migration.contracts import (
    CHATGPT_SUBSCRIPTION,
    SlotKey,
    canonical_json,
    sha256_bytes,
)
from live_migration.ledger import LiveRun, append_event, create_run, replay_run
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
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dry = commands.add_parser("dry-run")
    dry.add_argument("--billing-mode", default=CHATGPT_SUBSCRIPTION)
    dry.add_argument("--output", type=Path, required=True)
    dry.add_argument("--run-id", default="cpe-v3-subscription-dry-run")
    _add_checkpoint_arguments(dry)

    start = commands.add_parser("start")
    start.add_argument("--billing-mode", default=CHATGPT_SUBSCRIPTION)
    start.add_argument("--confirm-subscription-usage", action="store_true")
    start.add_argument("--evidence-root", type=Path)
    start.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX_BINARY)
    start.add_argument("--run-id")
    start.add_argument("--slot-timeout-seconds", type=int, default=900)
    _add_checkpoint_arguments(start)

    resume = commands.add_parser("resume")
    resume.add_argument("--run-dir", type=Path)
    resume.add_argument("--confirm-subscription-usage", action="store_true")
    resume.add_argument("--retry-failed", action="store_true")
    resume.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX_BINARY)
    resume.add_argument("--slot-timeout-seconds", type=int, default=900)
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
    billing_mode: str, run_id: str, binding: dict[str, str]
) -> dict[str, object]:
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
        args.billing_mode, args.run_id, _checkpoint_binding(args, required=False)
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
    return child


def _preflight_codex(codex_binary: Path):
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
        return preflight_codex(codex_binary, os.environ)
    finally:
        subprocess.run = original_run


def _context(run: LiveRun, args: argparse.Namespace) -> RunContext:
    attestation = _preflight_codex(args.codex_bin)
    return RunContext(
        run=run,
        eval_dir=ROOT,
        codex=attestation,
        child_env=_child_env(attestation.codex_home),
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
    append_event(context.run, "run_completed", {"completed_slots": len(results)})
    state = replay_run(context.run.run_dir)
    return {
        "status": "completed",
        "run_id": context.run.manifest["run_id"],
        "run_dir": str(context.run.run_dir),
        "slot_count": len(context.run.manifest["slots"]),
        "completed_count": len(state["completed_slots"]),
        "credentialed_call_count": context.run.manifest["credentialed_call_count"],
        "expected_policy_failure_count": context.run.manifest["expected_policy_failure_count"],
        "next_action": "aggregate and verify the immutable live report",
    }


def _start(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict[str, object]:
    if not args.confirm_subscription_usage:
        parser.error("start requires --confirm-subscription-usage")
    if args.evidence_root is None:
        parser.error("start requires --evidence-root")
    if args.billing_mode != CHATGPT_SUBSCRIPTION:
        parser.error("this runner requires --billing-mode chatgpt_subscription")
    run_id = args.run_id or f"cpe-live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = _new_run_dir(args.evidence_root, run_id)
    manifest = _compile(
        args.billing_mode, run_id, _checkpoint_binding(args, required=True)
    )
    if run_dir.exists():
        raise LiveRunnerError("execution_root_not_fresh", f"run directory already exists: {run_dir}")
    attestation = _preflight_codex(args.codex_bin)
    manifest["model_catalog_sha256"] = attestation.catalog_sha256
    manifest = _bind_manifest(manifest, {
        "implementation_commit": str(manifest["implementation_commit"]),
        "implementation_tree": str(manifest["implementation_tree"]),
        "implementation_patch_sha256": str(manifest["implementation_patch_sha256"]),
    })
    run = create_run(run_dir, manifest)
    context = RunContext(run, ROOT, attestation, _child_env(attestation.codex_home), args.slot_timeout_seconds, False)
    descriptor = _acquire_run_execution_lock(run_dir)
    try:
        return _execute(context, list(manifest["slots"]))
    finally:
        os.close(descriptor)


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
        else:
            result = _resume(args, parser)
    except (LiveRunnerError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        code = exc.code if isinstance(exc, LiveRunnerError) else "runner_failed"
        print(json.dumps({"status": "blocked", "error": code, "message": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
