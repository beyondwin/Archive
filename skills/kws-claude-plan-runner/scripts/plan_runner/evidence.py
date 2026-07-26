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

    def successful_receipt_digests(self) -> tuple[str, ...]:
        digests: list[str] = []
        seen: set[str] = set()
        for value in self.state.snapshot()["artifact_refs"]:
            if (
                not isinstance(value, dict)
                or value.get("kind") != "verification_receipt"
            ):
                continue
            receipt = self._receipt(ArtifactRef(**value))
            if (
                receipt is not None
                and receipt.outcome == "success"
                and receipt.artifact.digest not in seen
            ):
                seen.add(receipt.artifact.digest)
                digests.append(receipt.artifact.digest)
        return tuple(digests)

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
    def _command(value: object) -> ExactCommand:
        if not isinstance(value, Mapping) or set(value) != _COMMAND_FIELDS:
            raise ValueError("verification command shape is invalid")
        if not isinstance(value["argv"], list):
            raise ValueError("verification command argv is invalid")
        return ExactCommand(
            value["command_id"], value["command_role"], tuple(value["argv"]),
            value["cwd"], value["input_digest"], value["deadline_seconds"],
        )

    def _artifact_by_digest(
        self,
        digest: str,
        *,
        kinds: frozenset[str],
    ) -> tuple[ArtifactRef, dict[str, object]]:
        require_digest(digest)
        matches = [
            ArtifactRef(**reference)
            for reference in self.state.snapshot()["artifact_refs"]
            if isinstance(reference, dict)
            and reference.get("kind") in kinds
            and reference.get("digest") == digest
        ]
        if len(matches) != 1:
            raise ValueError("verification set is not sealed")
        return matches[0], self._document(matches[0])

    def _prior_plan_sets(self, plan_index: int) -> list[str]:
        if (
            isinstance(plan_index, bool)
            or not isinstance(plan_index, int)
            or plan_index < 0
        ):
            raise ValueError("plan index is invalid")
        state = self.state.snapshot()
        plans = state.get("plans")
        if not isinstance(plans, list) or plan_index > len(plans):
            raise ValueError("plan verification lineage is invalid")
        lineage: list[str] = []
        for expected_index, plan in enumerate(plans[:plan_index]):
            if not isinstance(plan, Mapping) or plan.get("status") != "implemented":
                raise ValueError("prior plan is not implemented")
            handoff_digest = plan.get("handoff_digest")
            if not isinstance(handoff_digest, str):
                raise ValueError("prior plan handoff is not sealed")
            _, handoff = self._artifact_by_digest(
                handoff_digest,
                kinds=frozenset({"plan_handoff"}),
            )
            if (
                handoff.get("plan_index") != expected_index
                or not isinstance(handoff.get("verification_set_digest"), str)
            ):
                raise ValueError("prior plan handoff identity is invalid")
            verification_digest = handoff["verification_set_digest"]
            _, verification = self._artifact_by_digest(
                verification_digest,
                kinds=frozenset({"plan_verification_set"}),
            )
            if verification.get("plan_index") != expected_index:
                raise ValueError("prior plan verification identity is invalid")
            lineage.append(verification_digest)
        return lineage

    def declare_verification(
        self,
        payload: object,
        candidate_head: str,
        *,
        plan_index: int,
        prior_set_digests: list[str],
        is_final_plan: bool,
    ) -> ArtifactRef:
        self._candidate(candidate_head)
        expected_prior = self._prior_plan_sets(plan_index)
        if prior_set_digests != expected_prior:
            raise ValueError("verification prior-set provenance is invalid")
        if (
            not isinstance(payload, Mapping)
            or payload.get("candidate_head") != candidate_head
        ):
            raise ValueError("verification candidate HEAD is invalid")
        kind = payload.get("kind")
        if kind == "commands":
            if (
                set(payload) != {"kind", "candidate_head", "commands"}
                or not isinstance(payload.get("commands"), list)
                or not payload["commands"]
            ):
                raise ValueError("verification command set is invalid")
            commands = [self._command(row) for row in payload["commands"]]
            plan_document: dict[str, object] = {
                "kind": "commands",
                "candidate_head": candidate_head,
                "plan_index": plan_index,
                "commands": [command.as_dict() for command in commands],
            }
        elif kind == "no_applicable_verification":
            if set(payload) != {"kind", "candidate_head", "rationale"}:
                raise ValueError("verification rationale shape is invalid")
            plan_document = {
                "kind": kind,
                "candidate_head": candidate_head,
                "plan_index": plan_index,
                "rationale": _text(payload.get("rationale"), "rationale"),
            }
        else:
            raise ValueError("verification kind is invalid")

        plan_artifact = self.state.put_artifact(
            "plan_verification_set",
            plan_document,
        )
        self._reference(plan_artifact)
        if not is_final_plan:
            return plan_artifact

        lineage = [*expected_prior, plan_artifact.digest]
        ordered = self._ordered_union(lineage)
        run_document = (
            {
                "kind": "run_verification",
                "candidate_head": candidate_head,
                "plan_set_digests": lineage,
                "commands": ordered,
            }
            if ordered
            else {
                "kind": "no_applicable_verification",
                "candidate_head": candidate_head,
                "plan_set_digests": lineage,
                "rationales": self._rationale_provenance(lineage),
            }
        )
        run_artifact = self.state.put_artifact(
            "run_verification_set",
            run_document,
        )
        self._reference(run_artifact)
        return run_artifact

    def _ordered_union(
        self,
        plan_set_digests: list[str],
    ) -> list[dict[str, object]]:
        ordered: list[dict[str, object]] = []
        seen: set[str] = set()
        for digest in plan_set_digests:
            _, document = self._artifact_by_digest(
                digest,
                kinds=frozenset({"plan_verification_set"}),
            )
            rows = document.get("commands", [])
            if not isinstance(rows, list):
                raise ValueError("plan verification commands are invalid")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("plan verification command is invalid")
                command = self._command(row)
                normalized = command.as_dict()
                identity = sha256_json(
                    {
                        name: normalized[name]
                        for name in (
                            "argv",
                            "cwd",
                            "input_digest",
                            "deadline_seconds",
                        )
                    }
                )
                if identity not in seen:
                    seen.add(identity)
                    ordered.append(normalized)
        return ordered

    def _rationale_provenance(
        self,
        plan_set_digests: list[str],
    ) -> list[dict[str, object]]:
        rationales: list[dict[str, object]] = []
        for digest in plan_set_digests:
            _, document = self._artifact_by_digest(
                digest,
                kinds=frozenset({"plan_verification_set"}),
            )
            rationale = document.get("rationale")
            plan_index = document.get("plan_index")
            if (
                document.get("kind") != "no_applicable_verification"
                or not isinstance(rationale, str)
                or not rationale.strip()
                or isinstance(plan_index, bool)
                or not isinstance(plan_index, int)
            ):
                raise ValueError(
                    "command-free run requires rationale for every plan"
                )
            rationales.append(
                {
                    "plan_index": plan_index,
                    "plan_set_digest": digest,
                    "rationale": rationale,
                }
            )
        if not rationales:
            raise ValueError("no-applicable run rationale is empty")
        return rationales

    def load_verification_command(
        self,
        set_digest: str,
        index: int,
    ) -> ExactCommand:
        require_digest(set_digest)
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("verification command index is invalid")
        _, payload = self._artifact_by_digest(
            set_digest,
            kinds=frozenset(
                {"plan_verification_set", "run_verification_set"}
            ),
        )
        commands = payload.get("commands")
        if not isinstance(commands, list):
            raise ValueError("verification set has no commands")
        try:
            return self._command(commands[index])
        except IndexError as error:
            raise ValueError("verification command index is unavailable") from error

    def require_successful_verification_set(
        self,
        set_digest: str,
        *,
        candidate_head: str,
        artifact_kind: str,
        plan_index: int,
    ) -> list[dict[str, str]]:
        _, payload = self._artifact_by_digest(
            set_digest,
            kinds=frozenset({artifact_kind}),
        )
        if payload.get("candidate_head") != require_full_sha(candidate_head):
            raise ValueError("verification candidate HEAD mismatch")
        if artifact_kind == "plan_verification_set":
            if payload.get("plan_index") != plan_index:
                raise ValueError("verification plan identity mismatch")
        elif artifact_kind == "run_verification_set":
            lineage = payload.get("plan_set_digests")
            if (
                not isinstance(lineage, list)
                or not lineage
                or lineage[:-1] != self._prior_plan_sets(plan_index)
            ):
                raise ValueError("run verification lineage is invalid")
            _, final_plan = self._artifact_by_digest(
                lineage[-1],
                kinds=frozenset({"plan_verification_set"}),
            )
            if (
                final_plan.get("plan_index") != plan_index
                or final_plan.get("candidate_head") != candidate_head
            ):
                raise ValueError("final plan verification identity is invalid")
            ordered = self._ordered_union(lineage)
            if payload.get("kind") == "no_applicable_verification":
                if (
                    ordered
                    or "commands" in payload
                    or payload.get("rationales")
                    != self._rationale_provenance(lineage)
                ):
                    raise ValueError(
                        "no-applicable run provenance is invalid"
                    )
                return []
            if payload.get("commands") != ordered:
                raise ValueError("run verification union is invalid")
        else:
            raise ValueError("verification artifact kind is invalid")
        commands = payload.get("commands")
        if payload.get("kind") == "no_applicable_verification":
            if (
                not isinstance(payload.get("rationale"), str)
                or not payload["rationale"].strip()
            ):
                raise ValueError("verification rationale is invalid")
            return []
        if not isinstance(commands, list) or not commands:
            raise ValueError("verification commands are invalid")
        receipts: list[dict[str, str]] = []
        for command_index in range(len(commands)):
            command = self.load_verification_command(
                set_digest,
                command_index,
            )
            identity = self.identity_digest(
                command,
                candidate_head=candidate_head,
            )
            receipt = self.reusable_success(identity)
            if receipt is None:
                raise ValueError("successful verification receipt is missing")
            receipts.append(receipt.artifact.as_dict())
        return receipts

    def record_liveness(self, sample: Mapping[str, object]) -> None:
        if not isinstance(sample, Mapping):
            raise ValueError("liveness sample is invalid")
        artifact = self.state.put_artifact("liveness_sample", dict(sample))
        self._reference(artifact)
