from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .validation import validate_completion, validate_run


@dataclass(frozen=True)
class ReconciliationFinding:
    code: str
    severity: str
    message: str
    repair_action: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    classification: str
    findings: list[dict[str, object]]

    def as_dict(self) -> dict[str, object]:
        return {"classification": self.classification, "findings": self.findings}


REPAIRABLE = {
    "snapshot_missing": "rebuild_snapshot",
    "snapshot_replay_mismatch": "rebuild_snapshot",
}


def reconcile(run_dir: Path, *, completion: bool = False) -> ReconciliationReport:
    """Classify canonical findings without treating healthy incompletion as drift.

    Recovery planning uses the default lifecycle adapter. Completion callers may
    request the strict profile before a terminal event exists.
    """
    report = validate_completion(run_dir) if completion else validate_run(run_dir)
    if report.classification == "unsupported_schema":
        return ReconciliationReport(
            "blocking_drift",
            [asdict(ReconciliationFinding("unsupported_schema", "blocking", "v2 state is unsupported and immutable"))],
        )
    findings: list[dict[str, object]] = []
    for code in report.errors:
        action = REPAIRABLE.get(code)
        findings.append(
            asdict(
                ReconciliationFinding(
                    code,
                    "repairable" if action else "blocking",
                    code.replace("_", " "),
                    action,
                )
            )
        )
    if not findings:
        classification = "clean"
    elif all(item["severity"] == "repairable" for item in findings):
        classification = "repairable"
    else:
        classification = "blocking_drift"
    return ReconciliationReport(classification, findings)
