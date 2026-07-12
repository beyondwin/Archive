#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "parser-fixtures" / "21-v4-ten-task-plan.md"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe import run_v4_fixture


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-e2e-") as raw:
        result = run_v4_fixture(FIXTURE, Path(raw))
        assert result["status"] == "completed", result
        assert result["run_ids_created"] == 1, result
        assert result["model_attempts"] <= 40, result
        assert len(result["verified_checkpoints"]) == 10, result
        assert [item["task_id"] for item in result["verified_checkpoints"]] == [
            f"task_{index}" for index in range(1, 11)
        ], result
        assert result["max_same_root_repairs"] <= 2, result
        assert result["transient_resumes"] == 1, result
        assert result["runtime_upgrades"] == 1, result
        assert result["backlog_count"] == 1, result

        help_run = subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / "cpe.py"), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert help_run.returncode == 0
        assert all(command in help_run.stdout for command in ("run", "resume", "supervise", "inspect"))

        fixture_env = {"CODEX_HOME": str(Path(raw) / "codex-home")}
        for command in ("inspect", "supervise"):
            inspected = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "cpe.py"),
                    command,
                    "--run-id",
                    result["run_id"],
                ],
                env=fixture_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            assert inspected.returncode == 0, inspected.stdout
            public = json.loads(inspected.stdout)
            assert public["schema_version"] == "cpe.public-result.v4", public
            assert public["status"] == "completed", public
            assert public["attempt_limit"] == 40 and public["attempt_used"] <= 40, public
            assert len(public["checkpoint_lineage"]) == 10, public
            assert len(public["backlog"]) == 1, public
            assert public["repair_roots"] == {"defect:fixture-repair": 1}, public
            assert public["user_input_required"] is False, public
            assert public["supervised"] is (command == "supervise"), public

        schema3_home = Path(raw) / "schema3-home"
        run_dir = schema3_home / "orchestrator" / "legacy-v3"
        run_dir.mkdir(parents=True)
        (run_dir / "run_manifest.json").write_text('{"schema_version":"3"}\n', encoding="utf-8")
        rejected = subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / "cpe.py"), "resume", "--run-id", "legacy-v3"],
            env={"CODEX_HOME": str(schema3_home)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert rejected.returncode != 0
        payload = json.loads(rejected.stdout)
        assert payload["summary"] == "unsupported_run_schema", payload
        assert "Traceback" not in rejected.stdout

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
