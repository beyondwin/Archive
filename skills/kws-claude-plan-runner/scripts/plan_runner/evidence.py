from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .contracts import canonical_json, require_digest, require_full_sha, sha256_json
from .git_ops import GitWorkspace, WorktreeObservation
from .process import open_executable, run_exact
from .storage import ArtifactRef, StateStore

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SECRET = re.compile(
    r"(?i)(?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|API_KEY)|password)=[^\s]+"
)
_COMMAND_FIELDS = {
    "command_id", "command_role", "argv", "cwd", "input_digest", "deadline_seconds"
}


def _text(value: object, label: str) -> str:
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
        if _ID.fullmatch(_text(self.command_id, "command ID")) is None:
            raise ValueError("command ID is invalid")
        _text(self.command_role, "command role")
        if not isinstance(self.argv, tuple) or not self.argv:
            raise ValueError("command argv is invalid")
        for item in self.argv:
            _text(item, "command argv")
        relative = Path(_text(self.cwd, "command cwd"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("command cwd must be relative without traversal")
        require_digest(self.input_digest)
        if (
            isinstance(self.deadline_seconds, bool)
            or not isinstance(self.deadline_seconds, (int, float))
            or not math.isfinite(self.deadline_seconds)
            or self.deadline_seconds <= 0
        ):
            raise ValueError("command deadline must be finite and positive")

    def as_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "command_role": self.command_role,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "input_digest": self.input_digest,
            "deadline_seconds": self.deadline_seconds,
        }


@dataclass(frozen=True)
class VerificationReceipt:
    artifact: ArtifactRef
    identity_digest: str
    outcome: str
    exit_code: int | None
    reused: bool

    def __post_init__(self) -> None:
        require_digest(self.identity_digest)
        if self.outcome not in ("success", "failed", "timed_out"):
            raise ValueError("receipt outcome is invalid")


def _redact(raw: bytes, environment: Mapping[str, str], limit: int) -> str:
    value = raw.decode("utf-8", "replace")
    value = _SECRET.sub(
        lambda match: match.group(0).split("=", 1)[0] + "=[REDACTED]", value
    )
    for name, secret in environment.items():
        if secret and re.search(r"(?i)(token|secret|api_key|password)", name):
            value = value.replace(secret, "[REDACTED]")
    if not limit:
        return ""
    encoded = value.encode()
    return value if len(encoded) <= limit else encoded[-limit:].decode("utf-8", "ignore")


class EvidenceStore:
    def __init__(
        self,
        state: StateStore,
        workspace: GitWorkspace,
        environment: Mapping[str, str],
        *,
        output_limit: int = 1_048_576,
    ) -> None:
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or _CONTROL.search(key)
            or "\0" in value
            for key, value in environment.items()
        ):
            raise ValueError("verification environment is invalid")
        if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit < 0:
            raise ValueError("output limit is invalid")
        self.state = state
        self.workspace = workspace
        self.environment = dict(environment)
        self.output_limit = output_limit

    def _candidate(self, candidate_head: str) -> WorktreeObservation:
        expected = require_full_sha(candidate_head)
        observed = self.workspace.observe()
        if observed.head != expected or not observed.clean:
            raise ValueError("candidate HEAD must match the observed clean worktree HEAD")
        return observed

    def _cwd(self, command: ExactCommand) -> Path:
        directory = (self.workspace.worktree / command.cwd).resolve(strict=True)
        try:
            directory.relative_to(self.workspace.worktree)
        except ValueError as error:
            raise ValueError("command cwd escapes worktree") from error
        if not directory.is_dir():
            raise ValueError("command cwd must be a directory")
        return directory

    def _identity(
        self,
        command: ExactCommand,
        candidate_head: str,
        observation: WorktreeObservation,
        executable: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "argv": list(command.argv),
            "candidate_head": candidate_head,
            "command_role": command.command_role,
            "cwd": str(self._cwd(command)),
            "environment_fingerprint": sha256_json(self.environment),
            "executable_identity": dict(executable),
            "input_digest": command.input_digest,
            "worktree_digest": observation.tree_digest,
        }

    def identity_digest(self, command: ExactCommand, *, candidate_head: str) -> str:
        head = require_full_sha(candidate_head)
        observation = self.workspace.observe()
        with open_executable(command.argv[0], cwd=self._cwd(command), env=self.environment) as opened:
            return sha256_json(self._identity(command, head, observation, opened.identity()))

    def _reference(self, artifact: ArtifactRef) -> None:
        candidate = self.state.snapshot()
        references = candidate["artifact_refs"]
        assert isinstance(references, list)
        if artifact.as_dict() not in references:
            references.append(artifact.as_dict())
            self.state.commit(candidate)

    def _document(self, artifact: ArtifactRef) -> dict[str, object]:
        raw = self.state.referenced_artifact(artifact.as_dict()).read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict) or raw != canonical_json(value) or artifact.digest != sha256_json(value):
            raise ValueError("artifact content digest mismatch")
        return value

    def _receipt(self, artifact: ArtifactRef) -> VerificationReceipt | None:
        try:
            value = self._document(artifact)
            expected = {
                "schema_version", "identity", "identity_digest", "outcome",
                "exit_code", "stdout_tail", "stderr_tail", "process",
            }
            if set(value) != expected or value["identity_digest"] != sha256_json(value["identity"]):
                return None
            outcome, code = value["outcome"], value["exit_code"]
            if outcome not in ("success", "failed", "timed_out"):
                return None
            if code is not None and (isinstance(code, bool) or not isinstance(code, int)):
                return None
            if outcome == "success" and code != 0:
                return None
            return VerificationReceipt(artifact, value["identity_digest"], outcome, code, False)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def reusable_success(self, identity_digest: str) -> VerificationReceipt | None:
        require_digest(identity_digest)
        references = self.state.snapshot()["artifact_refs"]
        assert isinstance(references, list)
        for value in reversed(references):
            if not isinstance(value, dict) or value.get("kind") != "verification_receipt":
                continue
            receipt = self._receipt(ArtifactRef(**value))
            if receipt and receipt.outcome == "success" and receipt.identity_digest == identity_digest:
                return VerificationReceipt(
                    receipt.artifact, receipt.identity_digest, receipt.outcome,
                    receipt.exit_code, True,
                )
        return None

    def execute(self, command: ExactCommand, *, candidate_head: str) -> VerificationReceipt:
        observation = self._candidate(candidate_head)
        cwd = self._cwd(command)
        with open_executable(command.argv[0], cwd=cwd, env=self.environment) as opened:
            identity = self._identity(command, candidate_head, observation, opened.identity())
            digest = sha256_json(identity)
            if (reused := self.reusable_success(digest)) is not None:
                return reused
            result = run_exact(
                command.argv,
                cwd=cwd,
                env=self.environment,
                deadline_seconds=command.deadline_seconds,
                output_limit=self.output_limit,
                opened_executable=opened,
            )
        outcome = {
            "success": "success",
            "failed": "failed",
            "verification_timed_out": "timed_out",
        }[result.kind]
        document = {
            "schema_version": 1,
            "identity": identity,
            "identity_digest": digest,
            "outcome": outcome,
            "exit_code": result.exit_code,
            "stdout_tail": _redact(result.stdout_tail, self.environment, self.output_limit),
            "stderr_tail": _redact(result.stderr_tail, self.environment, self.output_limit),
            "process": {
                "stdout_digest": result.stdout_digest,
                "stderr_digest": result.stderr_digest,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "forced_kill": result.forced_kill,
            },
        }
        artifact = self.state.put_artifact("verification_receipt", document)
        self._reference(artifact)
        return VerificationReceipt(artifact, digest, outcome, result.exit_code, False)

    @staticmethod
    def _command(value: object, *, final: bool) -> ExactCommand:
        if not isinstance(value, Mapping) or set(value) != _COMMAND_FIELDS:
            raise ValueError("final command shape is invalid")
        if not isinstance(value["argv"], list):
            raise ValueError("final command argv is invalid")
        command = ExactCommand(
            value["command_id"], value["command_role"], tuple(value["argv"]),
            value["cwd"], value["input_digest"], value["deadline_seconds"],
        )
        if final and command.command_role != "final":
            raise ValueError("final command role must be final")
        return command

    def declare_final_set(self, payload: object, candidate_head: str) -> ArtifactRef:
        self._candidate(candidate_head)
        if not isinstance(payload, Mapping) or payload.get("candidate_head") != candidate_head:
            raise ValueError("final set candidate HEAD is invalid")
        kind = payload.get("kind")
        if kind == "commands":
            if set(payload) != {"kind", "candidate_head", "commands"}:
                raise ValueError("final command set is invalid")
            rows = payload["commands"]
            if not isinstance(rows, list) or not rows:
                raise ValueError("final command set is invalid")
            commands = [self._command(row, final=True) for row in rows]
            if len({item.command_id for item in commands}) != len(commands):
                raise ValueError("final command IDs must be unique")
            sealed = {
                "kind": kind,
                "candidate_head": candidate_head,
                "commands": [item.as_dict() for item in commands],
            }
        elif kind == "no_applicable_verification":
            if set(payload) != {"kind", "candidate_head", "rationale"}:
                raise ValueError("no-applicable verification declaration is invalid")
            sealed = {
                "kind": kind,
                "candidate_head": candidate_head,
                "rationale": _text(payload.get("rationale"), "rationale"),
            }
        else:
            raise ValueError("final verification kind is invalid")
        artifact = self.state.put_artifact("final_verification_set", sealed)
        self._reference(artifact)
        return artifact

    def load_final_command(self, set_digest: str, index: int) -> ExactCommand:
        require_digest(set_digest)
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("final command index is invalid")
        references = self.state.snapshot()["artifact_refs"]
        matches = [
            ArtifactRef(**row)
            for row in references
            if isinstance(row, dict)
            and row.get("kind") == "final_verification_set"
            and row.get("digest") == set_digest
        ]
        if len(matches) != 1:
            raise ValueError("final verification set is not sealed")
        payload = self._document(matches[0])
        if payload.get("kind") != "commands" or not isinstance(payload.get("commands"), list):
            raise ValueError("final verification set has no commands")
        try:
            return self._command(payload["commands"][index], final=True)
        except IndexError as error:
            raise ValueError("final command index is unavailable") from error

    def record_liveness(self, sample: Mapping[str, object]) -> None:
        if not isinstance(sample, Mapping):
            raise ValueError("liveness sample is invalid")
        artifact = self.state.put_artifact("liveness_sample", dict(sample))
        self._reference(artifact)
