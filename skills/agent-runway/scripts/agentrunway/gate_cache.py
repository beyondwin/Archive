from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GateCacheKey:
    gate: str
    base_commit: str
    task_packet_hash: str
    diff_hash: str
    command_hash: str
    tool_version: str


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def gate_cache_digest(key: GateCacheKey) -> str:
    return stable_hash(asdict(key))
