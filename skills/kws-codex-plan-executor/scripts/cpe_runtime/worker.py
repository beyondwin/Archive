from __future__ import annotations
import hashlib, json, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from .model_policy import launcher_argv, route_for, attest_launcher

@dataclass(frozen=True)
class WorkerRequest:
    attempt_id: str; attempt_kind: str; prompt: str; worktree: Path; read_only: bool; verdict_capable: bool

@dataclass(frozen=True)
class WorkerResult:
    status: str; payload: dict; attestation: dict; usage: dict; latency_ms: int; raw_event_digest: str

class Worker:
    def __init__(self, provider=None): self.provider = provider
    def run(self, request: WorkerRequest) -> WorkerResult:
        route = route_for(request.attempt_kind, read_only=request.read_only, verdict_capable=request.verdict_capable)
        argv = launcher_argv(route, request.worktree, sandbox="read-only" if request.read_only else "workspace-write")
        started = time.monotonic()
        if self.provider:
            payload = self.provider(request, argv)
        else:
            proc = subprocess.run(argv, input=request.prompt, text=True, capture_output=True)
            payload = json.loads(proc.stdout.splitlines()[-1]) if proc.stdout.strip() else {"status": "failed", "summary": proc.stderr[-1000:]}
        raw = json.dumps(payload, sort_keys=True).encode()
        return WorkerResult(payload.get("status", "failed"), payload, attest_launcher(route, argv), payload.get("usage", {}), int((time.monotonic()-started)*1000), hashlib.sha256(raw).hexdigest())
