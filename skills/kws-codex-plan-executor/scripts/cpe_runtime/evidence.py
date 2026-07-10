from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    path: str
    sha256: str
    media_type: str = "application/json"


def put_json(run_dir: Path, kind: str, payload: object) -> EvidenceRef:
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    relative = Path("artifacts") / "evidence" / kind / f"{digest}.json"
    target = run_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw:
        raise EvidenceError("existing evidence path has different content")
    if not target.exists():
        with target.open("xb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    return EvidenceRef(kind, relative.as_posix(), digest)


def verify_ref(run_dir: Path, ref: EvidenceRef) -> list[str]:
    path = Path(ref.path)
    if path.is_absolute() or ".." in path.parts:
        return ["evidence path escapes run root"]
    target = run_dir / path
    if not target.is_file():
        return ["evidence missing"]
    if hashlib.sha256(target.read_bytes()).hexdigest() != ref.sha256:
        return ["evidence digest mismatch"]
    return []
