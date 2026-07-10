from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .events import read_events, validate_chain
from .evidence import verify_ref
from .manifest import load_manifest, resolve_ref, validate_manifest
from .model_policy import CORE_ROUTE, SCOUT_ROUTE
from .projector import project


CHECK_ORDER = (
    "schema", "manifest", "event_chain", "snapshot_replay", "artifacts",
    "task_states", "model_attestation", "worktree_and_diff", "verification", "completion",
)


@dataclass(frozen=True)
class ValidationReport:
    classification: str
    passed: bool
    errors: list[str]
    warnings: list[str]
    checks: dict[str, list[str]] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks or {},
        }


def _schema_marker(run_dir: Path) -> str | None:
    for name in ("run_manifest.json", "state.json"):
        try:
            payload = json.loads((run_dir / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        value = payload.get("schema_version")
        if value is not None:
            return str(value)
    return None


def _git_changed_files(worktree: Path) -> tuple[list[str], str | None]:
    if not worktree.is_dir():
        return [], "worktree_missing"
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        return [], "worktree_identity_mismatch"
    changed = [line[3:].split(" -> ")[-1] for line in result.stdout.splitlines() if len(line) >= 4]
    return changed, None


def _attestation_errors(attempts: list[dict]) -> list[str]:
    errors: list[str] = []
    for attempt in attempts:
        attestation = attempt.get("attestation")
        if not isinstance(attestation, dict) or attestation.get("verified") is not True:
            errors.append("model_attestation_missing")
            continue
        if attempt.get("kind") == "scout":
            expected = SCOUT_ROUTE
            if not attempt.get("read_only") or attempt.get("verdict_capable"):
                errors.append("model_policy_violation")
        else:
            expected = CORE_ROUTE
        if (
            attestation.get("actual_model") != expected.model
            or attestation.get("actual_reasoning") != expected.reasoning
            or attestation.get("mismatch") is True
        ):
            errors.append("model_attestation_mismatch")
    return errors


def validate_run(run_dir: Path) -> ValidationReport:
    run_dir = run_dir.expanduser().resolve()
    checks: dict[str, list[str]] = {name: [] for name in CHECK_ORDER}
    marker = _schema_marker(run_dir)
    if marker is not None and marker != "3":
        return ValidationReport("unsupported_schema", False, ["unsupported_schema"], [], checks)
    try:
        manifest = load_manifest(run_dir / "run_manifest.json")
    except ValueError as exc:
        code = "unsupported_schema" if str(exc) == "unsupported_schema" else "manifest_invalid"
        classification = "unsupported_schema" if code == "unsupported_schema" else "invalid"
        return ValidationReport(classification, False, [code], [], checks)
    except (OSError, json.JSONDecodeError):
        return ValidationReport("invalid", False, ["manifest_missing"], [], checks)

    checks["manifest"].extend(validate_manifest(manifest))
    try:
        events = read_events(run_dir / "events.jsonl")
    except ValueError:
        events = []
        checks["event_chain"].append("event_chain_invalid")
    chain = validate_chain(events)
    if chain:
        checks["event_chain"].append("event_chain_invalid")
    try:
        expected = project(manifest, events)
    except (KeyError, TypeError, ValueError):
        expected = None
        checks["event_chain"].append("event_projection_invalid")

    snapshot_path = run_dir / "state.json"
    if not snapshot_path.is_file():
        checks["snapshot_replay"].append("snapshot_missing")
    elif expected is not None:
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            checks["snapshot_replay"].append("snapshot_replay_mismatch")
        else:
            if snapshot != expected:
                checks["snapshot_replay"].append("snapshot_replay_mismatch")

    if expected is not None:
        for artifact in expected.get("artifact_index", []):
            ref = artifact.get("ref")
            problems = verify_ref(run_dir, ref) if isinstance(ref, dict) else ["evidence missing"]
            for problem in problems:
                checks["artifacts"].append({
                    "evidence missing": "evidence_missing",
                    "evidence digest mismatch": "evidence_digest_mismatch",
                    "evidence path escapes run root": "evidence_path_invalid",
                }.get(problem, "evidence_invalid"))

        tasks = expected.get("tasks") or {}
        if not tasks:
            checks["task_states"].append("task_graph_empty")
        for task in tasks.values():
            if task.get("status") != "completed":
                checks["task_states"].append("task_incomplete")
        checks["model_attestation"].extend(_attestation_errors(expected.get("attempts") or []))

        worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
        changed, git_error = _git_changed_files(worktree)
        if git_error:
            checks["worktree_and_diff"].append(git_error)
        else:
            claims = {
                str(path)
                for task in manifest.get("task_graph", [])
                for path in (task.get("file_claims") or [])
            }
            if any(path not in claims for path in changed):
                checks["worktree_and_diff"].append("diff_scope_violation")

        attempts = expected.get("attempts") or []
        artifact_kinds = {
            (item.get("task_id"), item.get("kind"))
            for item in expected.get("artifact_index", [])
        }
        for task_id, task in tasks.items():
            if task.get("status") != "completed":
                continue
            kinds = {
                item.get("kind")
                for item in attempts
                if item.get("task_id") == task_id and item.get("status") == "completed"
            }
            if not {"implementation", "review", "verification"}.issubset(kinds):
                checks["verification"].append("verification_missing")
            if (task_id, "acceptance") not in artifact_kinds or (task_id, "verification") not in artifact_kinds:
                checks["verification"].append("verification_evidence_missing")

        if expected.get("lifecycle") == "completed":
            audit = expected.get("completion_audit")
            final_review = any(
                item.get("task_id") is None
                and item.get("kind") == "final_review"
                and item.get("status") == "completed"
                for item in attempts
            )
            if not (
                isinstance(audit, dict)
                and audit.get("passed") is True
                and audit.get("verification_evidence")
                and audit.get("prompt_to_artifact_checklist")
                and final_review
                and not expected.get("blockers")
            ):
                checks["completion"].append("completion_gate_failed")
        else:
            checks["completion"].append("completion_gate_failed")

    errors = list(dict.fromkeys(code for name in CHECK_ORDER for code in checks[name]))
    if not errors:
        classification = "valid"
    elif errors == ["unsupported_schema"]:
        classification = "unsupported_schema"
    else:
        classification = "invalid"
    return ValidationReport(classification, not errors, errors, [], checks)
