#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_validation_consumer_parity import EXPECTED_FALSE_COMPLETION_CODES, make_v3_run
from cpe_runtime.validation import validate_completion, validate_integrity, validate_run


VALIDATOR = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"


def _cli(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(run_dir)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-v3-validator-adapter-") as raw:
        root = Path(raw)
        running, _ = make_v3_run(root / "running", false_completion=True, terminal=False)
        integrity = validate_integrity(running)
        completion = validate_completion(running)
        adapter = validate_run(running)
        cli = _cli(running)
        cli_payload = json.loads(cli.stdout)
        checks["running_adapter_selects_integrity"] = (
            integrity.passed
            and adapter.as_dict() == integrity.as_dict()
            and cli.returncode == 0
            and cli_payload["passed"] is True
            and completion.errors == EXPECTED_FALSE_COMPLETION_CODES
        )

        terminal, _ = make_v3_run(root / "terminal", false_completion=True, terminal=True)
        completion = validate_completion(terminal)
        adapter = validate_run(terminal)
        cli = _cli(terminal)
        cli_payload = json.loads(cli.stdout)
        checks["completed_adapter_selects_completion"] = (
            not completion.passed
            and adapter.as_dict() == completion.as_dict()
            and cli.returncode == 1
            and cli_payload["errors"] == EXPECTED_FALSE_COMPLETION_CODES
        )

        legacy = root / "legacy"
        legacy.mkdir()
        (legacy / "run_manifest.json").write_text('{"schema_version":"2.27.0"}\n', encoding="utf-8")
        unsupported = _cli(legacy)
        checks["unsupported_schema_exit_is_stable"] = (
            unsupported.returncode == 2
            and json.loads(unsupported.stdout)["classification"] == "unsupported_schema"
        )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
