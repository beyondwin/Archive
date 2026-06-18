#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "evals" / "baseline_utils.py"


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def baseline(fixtures: list[dict], *, date: str = "2026-06-18T00:00:00Z") -> dict:
    return {"version": "2.22.0", "date": date, "fixtures": fixtures}


def run_util(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-baseline-utils-") as temp:
        root = Path(temp)
        expected = root / "expected.json"
        actual = root / "actual.json"
        write_json(expected, baseline([{"fixture": "a", "passed": True}, {"fixture": "b", "passed": True}]))
        write_json(actual, baseline([{"fixture": "a", "passed": True}], date="2026-06-18T01:00:00Z"))
        result = run_util("compare", "--expected", str(expected), "--actual", str(actual), "--mode", "full")
        checks["full_compare_rejects_missing_fixture"] = result.returncode != 0 and "fixture list mismatch" in result.stderr
        if not checks["full_compare_rejects_missing_fixture"]:
            failures.append("full compare should reject missing or reordered fixture lists")

    with tempfile.TemporaryDirectory(prefix="cpe-baseline-utils-") as temp:
        root = Path(temp)
        expected = root / "expected.json"
        actual = root / "actual.json"
        fixtures = [{"fixture": "a", "passed": True}, {"fixture": "b", "passed": True}]
        write_json(expected, baseline(fixtures, date="2026-06-18T00:00:00Z"))
        write_json(actual, baseline(fixtures, date="2026-06-18T01:00:00Z"))
        result = run_util("compare", "--expected", str(expected), "--actual", str(actual), "--mode", "full")
        checks["full_compare_accepts_same_fixtures_with_different_date"] = result.returncode == 0
        if not checks["full_compare_accepts_same_fixtures_with_different_date"]:
            failures.append("full compare should ignore top-level date when fixture payloads match")

    with tempfile.TemporaryDirectory(prefix="cpe-baseline-utils-") as temp:
        root = Path(temp)
        expected = root / "expected.json"
        actual = root / "actual.json"
        write_json(expected, baseline([{"fixture": "a", "passed": True}, {"fixture": "b", "passed": True}]))
        write_json(actual, baseline([{"fixture": "a", "passed": True}], date="2026-06-18T01:00:00Z"))
        result = run_util("compare", "--expected", str(expected), "--actual", str(actual), "--mode", "subset")
        checks["subset_compare_accepts_executed_subset"] = result.returncode == 0
        if not checks["subset_compare_accepts_executed_subset"]:
            failures.append("subset compare should accept matching executed fixture subset")

    with tempfile.TemporaryDirectory(prefix="cpe-baseline-utils-") as temp:
        root = Path(temp)
        expected = root / "expected.json"
        actual = root / "actual.json"
        write_json(expected, baseline([{"fixture": "a", "passed": True}]))
        write_json(actual, baseline([{"fixture": "unknown", "passed": True}], date="2026-06-18T01:00:00Z"))
        result = run_util("compare", "--expected", str(expected), "--actual", str(actual), "--mode", "subset")
        checks["subset_compare_rejects_unknown_fixture"] = result.returncode != 0 and "baseline missing fixture" in result.stderr
        if not checks["subset_compare_rejects_unknown_fixture"]:
            failures.append("subset compare should reject generated fixtures absent from baseline")

    with tempfile.TemporaryDirectory(prefix="cpe-baseline-utils-") as temp:
        root = Path(temp)
        existing = root / "existing.json"
        generated = root / "generated.json"
        target = root / "target.json"
        write_json(existing, baseline([{"fixture": "a", "passed": False}, {"fixture": "b", "passed": True}]))
        write_json(generated, baseline([{"fixture": "a", "passed": True}], date="2026-06-18T02:00:00Z"))
        result = run_util("merge-subset", "--existing", str(existing), "--generated", str(generated), "--target", str(target))
        merged = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
        checks["merge_subset_replaces_only_executed_fixture"] = (
            result.returncode == 0
            and [item.get("fixture") for item in merged.get("fixtures", [])] == ["a", "b"]
            and merged["fixtures"][0]["passed"] is True
            and merged["fixtures"][1]["passed"] is True
        )
        if not checks["merge_subset_replaces_only_executed_fixture"]:
            failures.append("subset merge should replace executed fixtures and preserve unexecuted fixtures")

    with tempfile.TemporaryDirectory(prefix="cpe-baseline-utils-") as temp:
        root = Path(temp)
        existing = root / "existing.json"
        generated = root / "generated.json"
        target = root / "target.json"
        write_json(existing, baseline([{"fixture": "a", "passed": True}]))
        write_json(generated, baseline([{"fixture": "unknown", "passed": True}], date="2026-06-18T02:00:00Z"))
        result = run_util("merge-subset", "--existing", str(existing), "--generated", str(generated), "--target", str(target))
        checks["merge_subset_rejects_unknown_fixture"] = (
            result.returncode != 0
            and "refusing subset baseline update for unknown fixture" in result.stderr
            and not target.exists()
        )
        if not checks["merge_subset_rejects_unknown_fixture"]:
            failures.append("subset merge should reject unknown fixtures without writing target")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
