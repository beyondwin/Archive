from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactRecord:
    task_id: str
    kind: str
    path: str
    sha256: str
    ref: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def home_ref(path: Path) -> str:
    home = Path(os.environ.get("HOME", str(Path.home()))).resolve()
    resolved = path.resolve()
    try:
        return "~/" + resolved.relative_to(home).as_posix()
    except ValueError:
        return str(resolved)


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root

    def write_text(self, task_id: str, kind: str, text: str) -> ArtifactRecord:
        path = self.root / task_id / f"{kind}.txt"
        if kind.endswith(".json"):
            path = self.root / task_id / kind
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        digest = sha256_bytes(text.encode("utf-8"))
        return ArtifactRecord(task_id, kind, str(path), digest, home_ref(path))
