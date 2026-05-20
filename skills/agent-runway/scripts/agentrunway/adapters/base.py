from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..models import ProcessSnapshot, WorkerResult, WorkerResultEnvelope, WorkerSpec


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

    def prepare(self, spec: WorkerSpec) -> WorkerHandle:
        raise NotImplementedError

    def start(self, handle: WorkerHandle) -> WorkerHandle:
        raise NotImplementedError

    def poll(self, handle: WorkerHandle) -> ProcessSnapshot:
        raise NotImplementedError

    def collect(self, handle: WorkerHandle) -> WorkerResultEnvelope:
        raise NotImplementedError

    def cancel(self, handle: WorkerHandle) -> None:
        raise NotImplementedError

    def reattach(self, handle: WorkerHandle) -> WorkerHandle | None:
        return None

    def run(self, packet_path: Path, workdir: Path) -> WorkerResult:
        raise NotImplementedError
