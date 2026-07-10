from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from .events import read_events, validate_chain
from .manifest import load_manifest
from .projector import project

CHECK_ORDER = ("schema", "manifest", "event_chain", "snapshot_replay", "artifacts", "task_states", "model_attestation", "worktree_and_diff", "verification", "completion")
@dataclass(frozen=True)
class ValidationReport:
    classification: str; passed: bool; errors: list[str]; warnings: list[str]
    def as_dict(self): return {"classification": self.classification, "passed": self.passed, "errors": self.errors, "warnings": self.warnings}

def validate_run(run_dir: Path) -> ValidationReport:
    try: manifest = load_manifest(run_dir / "run_manifest.json")
    except ValueError as exc:
        if str(exc) == "unsupported_schema": return ValidationReport("unsupported_schema", False, ["unsupported_schema"], [])
        return ValidationReport("invalid_manifest", False, ["manifest_invalid"], [])
    except OSError: return ValidationReport("manifest_missing", False, ["manifest_missing"], [])
    events = read_events(run_dir / "events.jsonl"); errors = validate_chain(events)
    expected = project(manifest, events)
    snapshot = run_dir / "state.json"
    if snapshot.exists() and json.loads(snapshot.read_text(encoding="utf-8")) != expected: errors.append("snapshot_replay_mismatch")
    return ValidationReport("valid" if not errors else "invalid", not errors, errors, [])
