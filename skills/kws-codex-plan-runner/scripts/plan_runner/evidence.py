from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import canonical_json, require_digest, require_full_sha, sha256_json
from .git_ops import GitWorkspace, WorktreeObservation
from .process import OpenedExecutable, open_executable, run_exact
from .storage import ArtifactRef, StateStore


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECRET = re.compile(r"(?i)(?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|API_KEY)|password)=[^\s]+")


def _safe_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise ValueError(f"{label} must be a non-empty string without control characters")
    return value


@dataclass(frozen=True)
class ExactCommand:
    command_id: str
    command_role: str
    argv: tuple[str, ...]
    cwd: str
    input_digest: str
    deadline_seconds: float

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(_safe_string(self.command_id, "command ID")) is None:
            raise ValueError("command ID is invalid")
        _safe_string(self.command_role, "command role")
        if not isinstance(self.argv, tuple) or not self.argv:
            raise ValueError("command argv is invalid")
        for argument in self.argv:
            _safe_string(argument, "command argv")
        cwd = _safe_string(self.cwd, "command cwd")
        relative = Path(cwd)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("command cwd must be relative without traversal")
        require_digest(self.input_digest)
        if not isinstance(self.deadline_seconds, (int, float)) or isinstance(self.deadline_seconds, bool) or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0:
            raise ValueError("command deadline must be finite and positive")


@dataclass(frozen=True)
class VerificationReceipt:
    artifact: ArtifactRef
    identity_digest: str
    outcome: str
    exit_code: int | None
    reused: bool

    def __post_init__(self) -> None:
        require_digest(self.identity_digest)
        if self.outcome not in {"success", "failed", "timed_out"}:
            raise ValueError("receipt outcome is invalid")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _redacted(value: bytes, environment: Mapping[str, str], output_limit: int) -> str:
    text = value.decode("utf-8", "replace")
    text = _SECRET.sub(lambda match: match.group(0).split("=", 1)[0] + "=[REDACTED]", text)
    for key, secret in environment.items():
        if secret and re.search(r"(?i)(token|secret|api_key|password)", key):
            text = text.replace(secret, "[REDACTED]")
    if output_limit == 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= output_limit:
        return text
    return encoded[-output_limit:].decode("utf-8", "ignore")


class EvidenceStore:
    def __init__(
        self,
        state: StateStore,
        workspace: GitWorkspace,
        environment: Mapping[str, str],
        *,
        output_limit: int = 1_048_576,
    ) -> None:
        if any(not isinstance(key, str) or not isinstance(value, str) or _CONTROL.search(key) or "\0" in value for key, value in environment.items()):
            raise ValueError("verification environment is invalid")
        self.state = state
        self.workspace = workspace
        self.environment = dict(environment)
        if not isinstance(output_limit, int) or isinstance(output_limit, bool) or output_limit < 0:
            raise ValueError("output limit is invalid")
        self.output_limit = output_limit

    def _observation(self, candidate_head: str) -> WorktreeObservation:
        candidate_head = require_full_sha(candidate_head)
        observation = self.workspace.observe()
        if not observation.clean or observation.head != candidate_head:
            raise ValueError("candidate HEAD must match the observed clean worktree HEAD")
        return observation

    def _cwd(self, command: ExactCommand) -> Path:
        resolved = (self.workspace.worktree / command.cwd).resolve(strict=True)
        try:
            resolved.relative_to(self.workspace.worktree)
        except ValueError as error:
            raise ValueError("command cwd escapes worktree") from error
        if not resolved.is_dir():
            raise ValueError("command cwd must be a directory")
        return resolved

    def _executable_identity(self, command: ExactCommand, cwd: Path) -> dict[str, object]:
        import shutil

        located = shutil.which(command.argv[0], path=self.environment.get("PATH"))
        if located is None:
            raise ValueError("command executable is unavailable")
        executable = Path(located)
        if not executable.is_absolute():
            executable = cwd / executable
        try:
            executable = executable.resolve(strict=True)
            metadata = executable.stat()
        except OSError as error:
            raise ValueError("command executable is unavailable") from error
        if not stat.S_ISREG(metadata.st_mode) or not os.access(executable, os.X_OK):
            raise ValueError("command executable is unavailable")
        return {
            "path": str(executable),
            "sha256": _file_digest(executable),
            "mode": metadata.st_mode,
            "size": metadata.st_size,
        }

    def _identity(
        self,
        command: ExactCommand,
        candidate_head: str,
        observation: WorktreeObservation,
        executable_identity: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        cwd = self._cwd(command)
        return {
            "argv": list(command.argv),
            "candidate_head": candidate_head,
            "command_role": command.command_role,
            "cwd": str(cwd),
            "environment_fingerprint": sha256_json(self.environment),
            "executable_identity": dict(executable_identity) if executable_identity is not None else self._executable_identity(command, cwd),
            "input_digest": command.input_digest,
            "worktree_digest": observation.tree_digest,
        }

    def identity_digest(self, command: ExactCommand, *, candidate_head: str) -> str:
        # Identity inspection is intentionally side-effect free, so callers can
        # demonstrate which candidate or tree fact invalidates reuse. Execution
        # itself still requires the candidate to be the observed clean HEAD.
        candidate_head = require_full_sha(candidate_head)
        observation = self.workspace.observe()
        with open_executable(command.argv[0], cwd=self._cwd(command), env=self.environment) as executable:
            return sha256_json(self._identity(command, candidate_head, observation, executable.identity()))

    def _append_artifact(self, artifact: ArtifactRef) -> None:
        next_state = self.state.snapshot()
        references = next_state["artifact_refs"]
        assert isinstance(references, list)
        if artifact.as_dict() not in references:
            references.append(artifact.as_dict())
            self.state.commit(next_state)

    def _artifact_document(self, artifact: ArtifactRef) -> dict[str, object]:
        raw = self.state.referenced_artifact(artifact.as_dict()).read_bytes()
        document = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(document, dict)
            or canonical_json(document) != raw
            or sha256_json(document) != artifact.digest
        ):
            raise ValueError("artifact content digest mismatch")
        return document

    def _receipt_from_artifact(self, artifact: ArtifactRef) -> VerificationReceipt | None:
        try:
            document = self._artifact_document(artifact)
            if not isinstance(document, dict) or set(document) != {"exit_code", "identity", "identity_digest", "outcome", "process", "schema_version", "stdout_tail", "stderr_tail"}:
                return None
            digest = document["identity_digest"]
            if not isinstance(digest, str) or sha256_json(document["identity"]) != digest:
                return None
            outcome = document["outcome"]
            if outcome not in {"success", "failed", "timed_out"}:
                return None
            exit_code = document["exit_code"]
            if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
                return None
            if outcome == "success" and exit_code != 0:
                return None
            return VerificationReceipt(artifact, digest, outcome, exit_code, False)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def reusable_success(self, identity_digest: str) -> VerificationReceipt | None:
        require_digest(identity_digest)
        state = self.state.snapshot()
        references = state["artifact_refs"]
        assert isinstance(references, list)
        for reference in reversed(references):
            if not isinstance(reference, dict) or reference.get("kind") != "verification_receipt":
                continue
            artifact = ArtifactRef(**reference)
            receipt = self._receipt_from_artifact(artifact)
            if receipt is not None and receipt.outcome == "success" and receipt.identity_digest == identity_digest:
                return VerificationReceipt(receipt.artifact, receipt.identity_digest, receipt.outcome, receipt.exit_code, True)
        return None

    def execute(self, command: ExactCommand, *, candidate_head: str) -> VerificationReceipt:
        observation = self._observation(candidate_head)
        cwd = self._cwd(command)
        with open_executable(command.argv[0], cwd=cwd, env=self.environment) as executable:
            identity = self._identity(command, candidate_head, observation, executable.identity())
            digest = sha256_json(identity)
            reusable = self.reusable_success(digest)
            if reusable is not None:
                return reusable
            result = run_exact(
                command.argv,
                cwd=cwd,
                env=self.environment,
                deadline_seconds=command.deadline_seconds,
                output_limit=self.output_limit,
                opened_executable=executable,
            )
        outcome = {"success": "success", "failed": "failed", "verification_timed_out": "timed_out"}[result.kind]
        document = {
            "schema_version": 1,
            "identity": identity,
            "identity_digest": digest,
            "outcome": outcome,
            "exit_code": result.exit_code,
            "stdout_tail": _redacted(result.stdout_tail, self.environment, self.output_limit),
            "stderr_tail": _redacted(result.stderr_tail, self.environment, self.output_limit),
            "process": {
                "stdout_digest": result.stdout_digest,
                "stderr_digest": result.stderr_digest,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "forced_kill": result.forced_kill,
            },
        }
        artifact = self.state.put_artifact("verification_receipt", document)
        self._append_artifact(artifact)
        return VerificationReceipt(artifact, digest, outcome, result.exit_code, False)

    def _command_from_document(self, value: object, *, require_final: bool) -> ExactCommand:
        if not isinstance(value, Mapping) or set(value) != {"command_id", "command_role", "argv", "cwd", "input_digest", "deadline_seconds"}:
            raise ValueError("final command shape is invalid")
        argv = value["argv"]
        if not isinstance(argv, list):
            raise ValueError("final command argv is invalid")
        command = ExactCommand(
            command_id=value["command_id"], command_role=value["command_role"], argv=tuple(argv),
            cwd=value["cwd"], input_digest=value["input_digest"], deadline_seconds=value["deadline_seconds"],
        )
        if require_final and command.command_role != "final":
            raise ValueError("final command role must be final")
        return command

    def declare_verification(
        self,
        payload: object,
        candidate_head: str,
        *,
        plan_index: int,
        prior_set_digests: list[str],
        is_final_plan: bool,
    ) -> ArtifactRef:
        self._observation(candidate_head)
        expected_prior = self.implemented_prior_set_digests(plan_index)
        if prior_set_digests != expected_prior:
            raise ValueError("verification prior plan-set provenance is invalid")
        if not isinstance(payload, Mapping) or payload.get("candidate_head") != candidate_head:
            raise ValueError("verification candidate HEAD is invalid")
        kind = payload.get("kind")
        if kind == "commands":
            if set(payload) != {"kind", "candidate_head", "commands"} or not isinstance(payload.get("commands"), list) or not payload["commands"]:
                raise ValueError("verification command set is invalid")
            commands = [self._command_from_document(item, require_final=False) for item in payload["commands"]]
            sealed = {"kind": "commands", "candidate_head": candidate_head, "plan_index": plan_index, "commands": [
                {"command_id": command.command_id, "command_role": command.command_role, "argv": list(command.argv), "cwd": command.cwd, "input_digest": command.input_digest, "deadline_seconds": command.deadline_seconds}
                for command in commands
            ]}
        elif kind == "no_applicable_verification":
            if set(payload) != {"kind", "candidate_head", "rationale"}:
                raise ValueError("no-applicable verification declaration is invalid")
            sealed = {"kind": kind, "candidate_head": candidate_head, "plan_index": plan_index, "rationale": _safe_string(payload.get("rationale"), "rationale")}
        else:
            raise ValueError("verification kind is invalid")
        plan = self.state.put_artifact("plan_verification_set", sealed)
        self._append_artifact(plan)
        if not is_final_plan:
            return plan
        command_documents: list[dict[str, object]] = []
        for digest in [*expected_prior, plan.digest]:
            command_documents.extend(self._verification_commands(digest))
        deduplicated: list[dict[str, object]] = []
        seen: set[str] = set()
        for command in command_documents:
            identity = sha256_json({key: command[key] for key in ("argv", "cwd", "input_digest", "deadline_seconds")})
            if identity not in seen:
                seen.add(identity)
                deduplicated.append(command)
        run = self.state.put_artifact("run_verification_set", {"kind": "commands", "candidate_head": candidate_head, "plan_set_digests": [*expected_prior, plan.digest], "commands": deduplicated})
        self._append_artifact(run)
        return run

    def implemented_prior_set_digests(self, plan_index: int) -> list[str]:
        """Return the runner-owned, ordered verification lineage before a plan."""
        if not isinstance(plan_index, int) or isinstance(plan_index, bool) or plan_index < 0:
            raise ValueError("plan index is invalid")
        state = self.state.snapshot()
        plans = state.get("plans")
        references = state.get("artifact_refs")
        if not isinstance(plans, list) or not isinstance(references, list) or plan_index > len(plans):
            raise ValueError("plan verification lineage is invalid")
        artifacts = {
            reference.get("digest"): ArtifactRef(**reference)
            for reference in references
            if isinstance(reference, dict)
            and reference.get("kind") == "plan_handoff"
            and isinstance(reference.get("digest"), str)
        }
        digests: list[str] = []
        for expected_index, plan in enumerate(plans[:plan_index]):
            if not isinstance(plan, Mapping) or plan.get("status") != "implemented":
                raise ValueError("prior plan is not implemented")
            handoff_digest = plan.get("handoff_digest")
            if not isinstance(handoff_digest, str) or handoff_digest not in artifacts:
                raise ValueError("prior plan handoff is not sealed")
            handoff = self._artifact_document(artifacts[handoff_digest])
            if handoff.get("plan_index") != expected_index:
                raise ValueError("prior plan handoff identity is invalid")
            verification_digest = handoff.get("verification_set_digest")
            if not isinstance(verification_digest, str):
                raise ValueError("prior plan verification set is invalid")
            self._plan_set_payload(verification_digest, expected_index)
            digests.append(verification_digest)
        return digests

    def _plan_set_payload(self, digest: str, plan_index: int) -> Mapping[str, object]:
        require_digest(digest)
        for reference in self.state.snapshot()["artifact_refs"]:
            if isinstance(reference, dict) and reference.get("kind") == "plan_verification_set" and reference.get("digest") == digest:
                payload = self._artifact_document(ArtifactRef(**reference))
                if payload.get("plan_index") != plan_index:
                    raise ValueError("plan verification set identity is invalid")
                return payload
        raise ValueError("plan verification set is not sealed")

    def _verification_commands(self, digest: str) -> list[dict[str, object]]:
        require_digest(digest)
        for reference in self.state.snapshot()["artifact_refs"]:
            if isinstance(reference, dict) and reference.get("kind") == "plan_verification_set" and reference.get("digest") == digest:
                payload = self._artifact_document(ArtifactRef(**reference))
                if payload.get("kind") == "commands" and isinstance(payload.get("commands"), list):
                    return [dict(command) for command in payload["commands"] if isinstance(command, dict)]
        raise ValueError("plan verification set is not sealed")

    def load_verification_command(self, set_digest: str, index: int) -> ExactCommand:
        require_digest(set_digest)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("verification command index is invalid")
        for reference in self.state.snapshot()["artifact_refs"]:
            if isinstance(reference, dict) and reference.get("digest") == set_digest and reference.get("kind") in {"plan_verification_set", "run_verification_set"}:
                payload = self._artifact_document(ArtifactRef(**reference))
                commands = payload.get("commands")
                if not isinstance(commands, list):
                    raise ValueError("verification set has no commands")
                try:
                    return self._command_from_document(commands[index], require_final=False)
                except IndexError as error:
                    raise ValueError("verification command index is unavailable") from error
        raise ValueError("verification set is not sealed")

    def require_successful_verification_set(
        self,
        set_digest: str,
        *,
        candidate_head: str,
        kind: str,
        plan_index: int | None,
    ) -> None:
        require_digest(set_digest)
        candidate_head = require_full_sha(candidate_head)
        matching = [
            ArtifactRef(**reference)
            for reference in self.state.snapshot()["artifact_refs"]
            if isinstance(reference, dict)
            and reference.get("kind") == kind
            and reference.get("digest") == set_digest
        ]
        if len(matching) != 1:
            raise ValueError("verification set is not sealed")
        payload = self._artifact_document(matching[0])
        if payload.get("candidate_head") != candidate_head:
            raise ValueError("verification set candidate HEAD mismatch")
        if kind == "plan_verification_set" and plan_index is not None and payload.get("plan_index") != plan_index:
            raise ValueError("verification set plan identity mismatch")
        if kind == "run_verification_set" and plan_index is not None:
            plan_sets = payload.get("plan_set_digests")
            if not isinstance(plan_sets, list) or not plan_sets:
                raise ValueError("run verification plan declarations are invalid")
            expected_prior = self.implemented_prior_set_digests(plan_index)
            if plan_sets[:-1] != expected_prior:
                raise ValueError("run verification plan provenance is invalid")
            for prior_index, prior_digest in enumerate(expected_prior):
                if not isinstance(prior_digest, str):
                    raise ValueError("run verification plan declaration is invalid")
                self._plan_set_payload(prior_digest, prior_index)
            final_plan_set = plan_sets[-1]
            if not isinstance(final_plan_set, str):
                raise ValueError("run verification plan declaration is invalid")
            self.require_successful_verification_set(
                final_plan_set,
                candidate_head=candidate_head,
                kind="plan_verification_set",
                plan_index=plan_index,
            )
        commands = payload.get("commands")
        if payload.get("kind") == "no_applicable_verification":
            if not isinstance(payload.get("rationale"), str) or not payload["rationale"].strip():
                raise ValueError("verification rationale is invalid")
            return
        if not isinstance(commands, list) or not commands:
            raise ValueError("verification set commands are invalid")
        for index in range(len(commands)):
            command = self.load_verification_command(set_digest, index)
            identity = self.identity_digest(command, candidate_head=candidate_head)
            receipt = self.reusable_success(identity)
            if receipt is None or receipt.outcome != "success":
                raise ValueError("successful verification receipt is missing")

    def record_liveness(self, sample: Mapping[str, object]) -> None:
        if not isinstance(sample, Mapping):
            raise ValueError("liveness sample is invalid")
        artifact = self.state.put_artifact("liveness_sample", dict(sample))
        self._append_artifact(artifact)
        return None
