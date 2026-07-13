from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path


class EvidenceError(ValueError):
    pass


KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    path: str
    sha256: str
    media_type: str = "application/json"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _validate_kind(kind: str) -> None:
    if not isinstance(kind, str) or not KIND_RE.fullmatch(kind):
        raise EvidenceError("invalid evidence kind")


def _contained(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def put_json(run_dir: Path, kind: str, payload: object) -> EvidenceRef:
    """Compatibility adapter; EvidenceStore is the only writer implementation."""

    from .evidence_store import EvidenceStore

    return EvidenceStore(run_dir).put_json(kind, payload)


def put_method_evidence(
    run_dir: Path,
    evidence: object,
    *,
    task_id: str,
    packet_sha256: str,
    contract_sha256: str,
) -> dict[str, str]:
    """Persist only the canonical, sanitized method-evidence projection."""

    from .command_evidence import MethodEvidence, method_evidence_payload

    if not isinstance(evidence, MethodEvidence):
        raise EvidenceError("invalid method evidence")
    payload = {
        **method_evidence_payload(evidence),
        "task_id": task_id,
        "packet_sha256": packet_sha256,
        "contract_sha256": contract_sha256,
    }
    from .evidence_store import EvidenceStore

    ref = EvidenceStore(run_dir).put_json("method_evidence", payload).as_dict()
    return {
        **ref,
        "task_id": task_id,
        "packet_sha256": packet_sha256,
        "contract_sha256": contract_sha256,
    }


def coerce_ref(value: EvidenceRef | dict[str, object]) -> EvidenceRef:
    if isinstance(value, EvidenceRef):
        return value
    try:
        return EvidenceRef(
            kind=str(value["kind"]),
            path=str(value["path"]),
            sha256=str(value["sha256"]),
            media_type=str(value.get("media_type", "application/json")),
        )
    except (KeyError, TypeError) as exc:
        raise EvidenceError("invalid evidence reference") from exc


def verify_ref(run_dir: Path, value: EvidenceRef | dict[str, object]) -> list[str]:
    try:
        ref = coerce_ref(value)
        _validate_kind(ref.kind)
    except EvidenceError:
        return ["evidence path escapes run root"]
    path = Path(ref.path)
    if path.is_absolute() or ".." in path.parts:
        return ["evidence path escapes run root"]
    run_root = run_dir.resolve()
    expected_root = run_root / "artifacts" / "evidence" / ref.kind
    lexical = run_root / path
    try:
        metadata = lexical.lstat()
    except FileNotFoundError:
        return ["evidence missing"]
    if stat.S_ISLNK(metadata.st_mode):
        return ["evidence path escapes run root"]
    resolved = lexical.resolve()
    if not _contained(expected_root.resolve(), resolved) or resolved.parent != expected_root.resolve():
        return ["evidence path escapes run root"]
    if not resolved.is_file():
        return ["evidence missing"]
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != ref.sha256:
        return ["evidence digest mismatch"]
    return []


def verify_method_evidence_ref(
    run_dir: Path,
    value: object,
    *,
    task_id: str,
    packet_sha256: str,
    contract_sha256: str,
) -> list[str]:
    """Re-open method evidence and bind it to its immutable authorization."""

    if not isinstance(value, dict):
        return ["method evidence reference invalid"]
    problems = verify_ref(run_dir, value)
    if problems:
        return problems
    expected = {
        "task_id": task_id,
        "packet_sha256": packet_sha256,
        "contract_sha256": contract_sha256,
    }
    if value.get("kind") != "method_evidence" or any(
        value.get(field) != expected_value for field, expected_value in expected.items()
    ):
        return ["method evidence authorization mismatch"]
    try:
        payload = json.loads((run_dir.resolve() / str(value["path"])).read_text(encoding="utf-8"))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["method evidence invalid"]
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "cpe.method-evidence.v4"
        or any(payload.get(field) != expected_value for field, expected_value in expected.items())
    ):
        return ["method evidence authorization mismatch"]
    return []
