from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .events import append_event, read_events
from .projector import RUN_TRANSITIONS, project


@dataclass(frozen=True)
class Transition:
    event_type: str
    payload: dict[str, object]
    task_id: str | None = None
    attempt_id: str | None = None


def atomic_write_snapshot(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp, path)


def transition_run(run_dir: Path, command: Transition, snapshot_writer=atomic_write_snapshot) -> dict:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    events_path = run_dir / "events.jsonl"; state = project(manifest, read_events(events_path))
    if command.event_type == "run.status_changed":
        target = command.payload["to"]
        if target not in RUN_TRANSITIONS.get(state["lifecycle"], set()): raise ValueError("invalid run transition")
    event = append_event(events_path, {"type": command.event_type, "payload": command.payload, "task_id": command.task_id, "attempt_id": command.attempt_id})
    state = project(manifest, read_events(events_path)); snapshot_writer(run_dir / "state.json", state)
    return state


class Kernel:
    def __init__(self, run_dir: Path): self.run_dir = run_dir.resolve(); self._snapshot_writer = atomic_write_snapshot
    def transition(self, command: Transition) -> dict: return transition_run(self.run_dir, command, snapshot_writer=self._snapshot_writer)


def rebuild_snapshot(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    state = project(manifest, read_events(run_dir / "events.jsonl")); atomic_write_snapshot(run_dir / "state.json", state); return state
