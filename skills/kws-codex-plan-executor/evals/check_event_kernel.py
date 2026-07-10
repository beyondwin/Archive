#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.events import append_event, read_events, validate_chain
from cpe_runtime.kernel import Kernel, Transition, rebuild_snapshot
from cpe_runtime.projector import initial_state, project


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        run = Path(raw); (run / "run_manifest.json").write_text('{"schema_version":"3","run_id":"fixture"}\n')
        path = run / "events.jsonl"
        append_event(path, {"type": "run.status_changed", "payload": {"from": "created", "to": "ready"}})
        events = read_events(path)
        assert validate_chain(events) == []
        events[0]["payload"]["to"] = "running"
        assert validate_chain(events) == ["event hash mismatch"]
        (run / "events.jsonl").unlink(); (run / "state.json").unlink(missing_ok=True)
        kernel = Kernel(run)
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        kernel._snapshot_writer = lambda *_: (_ for _ in ()).throw(OSError("fixture crash"))
        try:
            kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
        except OSError:
            pass
        recovered = rebuild_snapshot(run)
        assert recovered["lifecycle"] == "running"
        assert recovered["last_event"]["seq"] == 2
    print('{"passed": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
