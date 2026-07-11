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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dry = commands.add_parser("dry-run")
    dry.add_argument("--billing-mode", default=CHATGPT_SUBSCRIPTION)
    dry.add_argument("--output", type=Path, required=True)
    dry.add_argument("--run-id", default="cpe-v3-subscription-dry-run")

    start = commands.add_parser("start")
    start.add_argument("--billing-mode", default=CHATGPT_SUBSCRIPTION)
    start.add_argument("--confirm-subscription-usage", action="store_true")
    start.add_argument("--evidence-root", type=Path)
    start.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX_BINARY)
    start.add_argument("--run-id")
    start.add_argument("--slot-timeout-seconds", type=int, default=900)

    resume = commands.add_parser("resume")
    resume.add_argument("--run-dir", type=Path)
    resume.add_argument("--confirm-subscription-usage", action="store_true")
    resume.add_argument("--retry-failed", action="store_true")
    resume.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX_BINARY)
    resume.add_argument("--slot-timeout-seconds", type=int, default=900)
    return parser


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


def _compile(billing_mode: str, run_id: str) -> dict[str, object]:
    return compile_manifest(ROOT, billing_mode, _git_commit(), _created_at(), run_id)


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
    manifest = _compile(args.billing_mode, args.run_id)
    payload = {
        "status": "dry_run",
        "run_id": manifest["run_id"],
        "billing_mode": manifest["billing_mode"],
        "slot_count": len(manifest["slots"]),
        "credentialed_call_count": manifest["credentialed_call_count"],
        "expected_policy_failure_count": manifest["expected_policy_failure_count"],
        "manifest_sha256": manifest["manifest_sha256"],
        "slots": manifest["slots"],
        "next_action": "review plan, then run start with --confirm-subscription-usage",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def _child_env(codex_home: Path) -> dict[str, str]:
    child = {key: value for key, value in os.environ.items() if key not in API_KEY_ENV_NAMES}
    child["CODEX_HOME"] = str(codex_home)
    return child


def _context(run: LiveRun, args: argparse.Namespace) -> RunContext:
    attestation = preflight_codex(args.codex_bin, os.environ)
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


def _execute(
    context: RunContext,
    slots: list[dict[str, object]],
    *,
    retry_slots: set[SlotKey] | None = None,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    try:
        for slot in slots:
            slot_context = context
            if retry_slots is not None:
                key = SlotKey(str(slot["treatment_id"]), str(slot["case_id"]))
                slot_context = replace(context, retry_failed=key in retry_slots)
            results.append(run_slot(slot_context, slot))
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
    manifest = _compile(args.billing_mode, run_id)
    if run_dir.exists():
        raise LiveRunnerError("execution_root_not_fresh", f"run directory already exists: {run_dir}")
    attestation = preflight_codex(args.codex_bin, os.environ)
    manifest["model_catalog_sha256"] = attestation.catalog_sha256
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    manifest["manifest_sha256"] = sha256_bytes(canonical_json(manifest_body))
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
