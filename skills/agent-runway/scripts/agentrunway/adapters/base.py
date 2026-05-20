from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..models import WorkerResult


@dataclass(frozen=True)
class AdapterCapabilities:
    runtime: str
    supports_reattach: bool = False
    supports_streaming: bool = False
    network_egress: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkerHandle:
    worker_id: str
    task_id: str
    role: str
    pid: int | None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


class RuntimeAdapter:
    capabilities: AdapterCapabilities

    def run(self, packet_path: Path, workdir: Path) -> WorkerResult:
        raise NotImplementedError
