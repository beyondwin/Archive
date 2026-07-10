from __future__ import annotations
from pathlib import Path
from .validation import validate_run
from .reconciliation import reconcile
def inspect_run(run_dir: Path) -> dict:
    report = validate_run(run_dir); return {"run_id": run_dir.name, "classification": report.classification, "passed": report.passed, "errors": report.errors, "reconciliation": reconcile(run_dir).classification}
def inspect_recent(codex_home: Path, limit: int) -> dict:
    items = [inspect_run(path) for path in sorted((codex_home / "orchestrator").glob("*/"))[-limit:]] if (codex_home / "orchestrator").exists() else []
    return {"run_count": len(items), "completed_count": sum(1 for item in items if item["passed"]), "blocked_count": 0, "failed_count": 0, "unsupported_schema_count": sum(1 for item in items if item["classification"] == "unsupported_schema"), "runs": items}
