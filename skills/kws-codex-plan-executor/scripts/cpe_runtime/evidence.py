from __future__ import annotations

import hashlib
import json
import os
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


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _evidence_root(run_dir: Path) -> Path:
    root = run_dir.resolve() / "artifacts" / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise EvidenceError("evidence root must not be a symlink")
    return root.resolve()


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
    _validate_kind(kind)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    root = _evidence_root(run_dir)
    kind_dir = root / kind
    kind_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
    if kind_dir.is_symlink() or not _contained(root, kind_dir.resolve()):
        raise EvidenceError("evidence path escapes run root")
    target = kind_dir / f"{digest}.json"
    relative = target.relative_to(run_dir.resolve())
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != raw:
            raise EvidenceError("existing evidence path has different content")
    else:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            _fsync_dir(kind_dir)
    return EvidenceRef(kind, relative.as_posix(), digest)


def put_method_evidence(run_dir: Path, evidence: object) -> EvidenceRef:
    """Persist only the canonical, sanitized method-evidence projection."""

    from .command_evidence import MethodEvidence, method_evidence_payload

    if not isinstance(evidence, MethodEvidence):
        raise EvidenceError("invalid method evidence")
    return put_json(run_dir, "method_evidence", method_evidence_payload(evidence))


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
