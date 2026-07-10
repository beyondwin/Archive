from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .events import read_events, validate_chain
from .manifest import load_manifest
@dataclass(frozen=True)
class ReconciliationReport:
    classification: str; findings: list[dict]
def reconcile(run_dir: Path) -> ReconciliationReport:
    try: load_manifest(run_dir / "run_manifest.json")
    except ValueError: return ReconciliationReport("blocking_drift", [{"code": "unsupported_schema"}])
    except OSError: return ReconciliationReport("blocking_drift", [{"code": "manifest_missing"}])
    errors = validate_chain(read_events(run_dir / "events.jsonl"))
    if errors: return ReconciliationReport("blocking_drift", [{"code": "event_chain_invalid", "message": item} for item in errors])
    if not (run_dir / "state.json").exists(): return ReconciliationReport("repairable", [{"code": "snapshot_missing", "repair_action": "rebuild_snapshot"}])
    return ReconciliationReport("clean", [])
