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
            extra = (
                ["--poll-interval", "0", "--timeout", "1", "--min-polls", "2"]
                if command == "supervise"
                else []
            )
            inspected = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "cpe.py"),
                    command,
                    "--run-id",
                    result["run_id"],
                    *extra,
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
            if command == "supervise":
                assert public["poll_count"] >= 2, public

        events_path = Path(raw) / "codex-home" / "orchestrator" / result["run_id"] / "events.jsonl"
        original_events = events_path.read_text(encoding="utf-8")
        lines = original_events.splitlines()
        mutated = False
        for index, line in enumerate(lines):
            event = json.loads(line)
            if event.get("type") == "decision.recorded":
                event["payload"]["basis"] = "shape-valid tamper"
                lines[index] = json.dumps(event, sort_keys=True, separators=(",", ":"))
                mutated = True
                break
        assert mutated
        events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tampered = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "cpe.py"),
                "inspect",
                "--run-id",
                result["run_id"],
            ],
            env=fixture_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert tampered.returncode != 0, tampered.stdout
        assert json.loads(tampered.stdout)["summary"] == "event_chain_invalid"
        events_path.write_text(original_events, encoding="utf-8")

        for option in ("--timeout", "--poll-interval"):
            for value in ("nan", "inf", "-inf"):
                non_finite = subprocess.run(
                    [
                        sys.executable,
                        str(SKILL_ROOT / "scripts" / "cpe.py"),
                        "supervise",
                        "--run-id",
                        result["run_id"],
                        f"{option}={value}",
                        "--one-pass",
                    ],
                    env=fixture_env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                assert non_finite.returncode != 0, (option, value, non_finite.stdout)
                assert json.loads(non_finite.stdout)["summary"] == "supervise_options_invalid"

        waiting_root = Path(raw) / "waiting-user"
        waiting = run_v4_fixture(
            FIXTURE, waiting_root, pause_task_id="task_1", pause_kind="waiting_user"
        )
        waiting_env = {"CODEX_HOME": str(waiting_root / "codex-home")}
        authority = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "cpe.py"),
                "resume",
                "--run-id",
                waiting["run_id"],
            ],
            env=waiting_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert authority.returncode == 1, authority.stdout
        authority_payload = json.loads(authority.stdout)
        assert authority_payload["user_input_required"] is True, authority_payload
        assert authority_payload["next_safe_action"] == "provide_user_authority", authority_payload
        assert authority_payload["blocker"]["category"] == "operator_review", authority_payload

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
