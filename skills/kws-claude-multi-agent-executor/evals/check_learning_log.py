#!/usr/bin/env python3
"""Deterministic checks for append_learning_event.py (kws-claude-multi-agent-executor)."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "append_learning_event.py"


def base_event(run_id: str) -> dict:
    return {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-claude-multi-agent-executor",
        "skill_version": "2.10.2",
        "phase": "phase_1",
        "risk_tier": "MID",
        "event_type": "reviewer_warn_or_fail",
        "severity": "medium",
        "execution": {
            "task_id": "task_3",
            "wave": 2,
            "compaction_index": 1,
            "issue_key": "review_retry_quality_low",
        },
        "scores": {"spec_score": 0.82, "quality_score": 0.71, "tier": "WARN"},
        "subagent": {"role": "reviewer", "model": "sonnet", "dispatch": "agent_tool"},
        "summary": "Combined Reviewer returned WARN; quality_score below 0.75.",
        "context": {
            "user_intent": "Add JSON config parsing.",
            "agent_expectation": "Reviewer would PASS.",
            "actual_outcome": "WARN tier.",
            "root_cause": "Happy-path tests only.",
            "evidence": [{"kind": "relative_path", "value": "src/config.py"}],
        },
        "improvement": {
            "target": "references/reviewer-prompt.md",
            "proposal": "Cite specific missing test category.",
            "experiment_link": None,
        },
        "privacy": {"redacted": True, "notes": "Worktree path relativized."},
    }


def run_helper(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env if env is not None else os.environ.copy(),
    )


def init_run(log_root: Path, repo_root: Path, **extras: str) -> str:
    args = [
        "init-run",
        "--log-root", str(log_root),
        "--repo-root", str(repo_root),
        "--repo-name", extras.get("repo_name", "TestRepo"),
        "--branch", extras.get("branch", "feature/x"),
        "--plan-path", extras.get("plan_path", "docs/plans/x.md"),
        "--spec-path", extras.get("spec_path", "docs/specs/x.md"),
        "--session-id", extras.get("session_id", "188042f4-d69e-45d2-91ad-91ad91ad91ad"),
    ]
    result = run_helper(*args)
    if result.returncode != 0:
        raise RuntimeError(f"init-run failed: {result.stderr or result.stdout}")
    return result.stdout.strip()


def write_event(event_dir: Path, event: dict, name: str = "candidate.json") -> Path:
    path = event_dir / name
    path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    return path


def run_dir(log_root: Path, run_id: str) -> Path:
    date = run_id.split("T", 1)[0]
    date_iso = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    return log_root / "runs" / date_iso / run_id


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def record(name: str, ok: bool, msg: str) -> None:
        checks[name] = ok
        if not ok:
            failures.append(msg)

    if not SCRIPT.is_file():
        print(json.dumps({"passed": False, "checks": {"helper_exists": False},
                          "failures": [f"helper script not found at {SCRIPT}"]},
                         indent=2))
        return 1

    with tempfile.TemporaryDirectory(prefix="mae-learning-log-") as temp:
        temp_path = Path(temp)
        log_root = temp_path / "log"
        repo_root = temp_path / "repo"
        repo_root.mkdir()
        event_dir = temp_path / "events"
        event_dir.mkdir()

        # ----- check 1: init-run creates run dir + meta.json with expected fields -----
        try:
            run_id = init_run(log_root, repo_root)
            rd = run_dir(log_root, run_id)
            meta_path = rd / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ok = (
                rd.is_dir()
                and meta_path.is_file()
                and meta.get("run_id") == run_id
                and meta.get("outcome") == "unknown"
                and meta.get("event_count") == 0
                and meta.get("skill") == "kws-claude-multi-agent-executor"
                and meta.get("started_at")
                and isinstance(meta.get("session_ids"), list)
                and len(meta["session_ids"]) == 1
            )
            record("init_run_creates_run_dir", ok,
                   "init-run should create run dir + meta.json with required fields")
        except Exception as exc:  # noqa: BLE001
            record("init_run_creates_run_dir", False, f"init-run raised: {exc}")
            run_id = ""

        # ----- check 2: init-run idempotent -----
        if run_id:
            first_started = json.loads(meta_path.read_text())["started_at"]
            run_id2 = init_run(log_root, repo_root)
            second_started = json.loads(meta_path.read_text())["started_at"]
            ok = run_id == run_id2 and first_started == second_started
            record("init_run_idempotent", ok,
                   "init-run with same args should return same run_id and not bump started_at")

        # ----- check 3: append after init-run writes one valid JSONL line -----
        if run_id:
            cand_path = write_event(event_dir, base_event(run_id))
            res = run_helper(
                "append",
                "--log-root", str(log_root),
                "--run-id", run_id,
                "--event-json", str(cand_path),
                "--repo-root", str(repo_root),
            )
            jsonl = (rd / "events.jsonl")
            lines = jsonl.read_text().splitlines() if jsonl.is_file() else []
            try:
                appended = json.loads(lines[0]) if lines else {}
            except json.JSONDecodeError:
                appended = {}
            ok = (
                res.returncode == 0
                and len(lines) == 1
                and appended.get("run_id") == run_id
                and isinstance(appended.get("event_id"), str)
                and len(appended.get("event_id", "")) >= 12
                and appended.get("event_type") == "reviewer_warn_or_fail"
            )
            record("append_after_init_writes_line", ok,
                   f"append should write one valid line (rc={res.returncode}, lines={len(lines)})")

        # ----- check 4: append without prior init-run self-heals -----
        log_root2 = temp_path / "log2"
        repo_root2 = temp_path / "repo2"
        repo_root2.mkdir()
        fake_run_id = "20260513T143321Z-aaaaaaaa-12345"
        cand2 = write_event(event_dir, base_event(fake_run_id), "self_heal.json")
        res = run_helper(
            "append",
            "--log-root", str(log_root2),
            "--run-id", fake_run_id,
            "--event-json", str(cand2),
            "--repo-root", str(repo_root2),
        )
        rd2 = run_dir(log_root2, fake_run_id)
        meta2_path = rd2 / "meta.json"
        ok = (
            res.returncode == 0
            and meta2_path.is_file()
            and json.loads(meta2_path.read_text()).get("outcome") == "unknown"
            and (rd2 / "events.jsonl").is_file()
        )
        record("append_self_heals_without_init", ok,
               f"append without prior init-run should create meta.json + write event (rc={res.returncode})")

        # ----- check 5: close-run updates ended_at, outcome, event_count -----
        if run_id:
            res = run_helper(
                "close-run",
                "--log-root", str(log_root),
                "--run-id", run_id,
                "--outcome", "success",
            )
            meta_after = json.loads(meta_path.read_text())
            ok = (
                res.returncode == 0
                and meta_after.get("outcome") == "success"
                and meta_after.get("ended_at")
                and meta_after.get("event_count") == 1
            )
            record("close_run_updates_meta", ok,
                   "close-run should update ended_at + outcome + event_count")

            # ----- check 6: close-run idempotent (re-run produces same outcome) -----
            res2 = run_helper(
                "close-run",
                "--log-root", str(log_root),
                "--run-id", run_id,
                "--outcome", "success",
            )
            meta_final = json.loads(meta_path.read_text())
            ok = res2.returncode == 0 and meta_final.get("outcome") == "success"
            record("close_run_idempotent", ok, "close-run idempotent")

        # ----- check 7: --dry-run on append validates without writing -----
        log_root3 = temp_path / "log3"
        repo_root3 = temp_path / "repo3"
        repo_root3.mkdir()
        dry_run_id = init_run(log_root3, repo_root3)
        cand_dry = write_event(event_dir, base_event(dry_run_id), "dry.json")
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(cand_dry),
            "--repo-root", str(repo_root3),
            "--dry-run",
        )
        rd3 = run_dir(log_root3, dry_run_id)
        events_path3 = rd3 / "events.jsonl"
        ok = (
            res.returncode == 0
            and (not events_path3.exists() or len(events_path3.read_text().splitlines()) == 0)
            and "event_id" in res.stdout
        )
        record("append_dry_run_no_write", ok,
               f"--dry-run should validate and print event_id without writing (rc={res.returncode})")

        # ----- check 8: missing required field fails -----
        bad = base_event(dry_run_id)
        del bad["summary"]
        bad_path = write_event(event_dir, bad, "missing.json")
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(bad_path),
        )
        ok = res.returncode != 0 and "summary" in (res.stderr + res.stdout)
        record("missing_required_field_fails", ok, "missing summary should fail")

        # ----- check 9: invalid phase/event_type/severity fail -----
        bad_phase = base_event(dry_run_id)
        bad_phase["phase"] = "phase_bogus"
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(write_event(event_dir, bad_phase, "bad_phase.json")),
        )
        ok_phase = res.returncode != 0 and "phase" in (res.stderr + res.stdout)

        bad_evt = base_event(dry_run_id)
        bad_evt["event_type"] = "not_a_thing"
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(write_event(event_dir, bad_evt, "bad_evt.json")),
        )
        ok_evt = res.returncode != 0 and "event_type" in (res.stderr + res.stdout)

        bad_sev = base_event(dry_run_id)
        bad_sev["severity"] = "extreme"
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(write_event(event_dir, bad_sev, "bad_sev.json")),
        )
        ok_sev = res.returncode != 0 and "severity" in (res.stderr + res.stdout)

        record("invalid_enum_fails", ok_phase and ok_evt and ok_sev,
               "invalid phase/event_type/severity should all fail")

        # ----- check 10: absolute home path is rejected -----
        bad_home = base_event(dry_run_id)
        bad_home["context"]["evidence"] = [
            {"kind": "relative_path", "value": str(Path.home() / "secret.txt")}
        ]
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(write_event(event_dir, bad_home, "home.json")),
        )
        ok = res.returncode != 0 and "home" in (res.stderr + res.stdout).lower()
        record("home_path_rejected", ok,
               "absolute home path in evidence should be rejected")

        # ----- check 11: absolute worktree path is relativized -----
        cand_wt = base_event(dry_run_id)
        absolute_file = repo_root3 / "src" / "config.py"
        absolute_file.parent.mkdir(parents=True, exist_ok=True)
        absolute_file.write_text("# placeholder\n", encoding="utf-8")
        cand_wt["context"]["evidence"] = [
            {"kind": "relative_path", "value": str(absolute_file)}
        ]
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(write_event(event_dir, cand_wt, "wt.json")),
            "--repo-root", str(repo_root3),
            "--dry-run",
        )
        ok = res.returncode == 0 and "src/config.py" in res.stdout and str(repo_root3) not in res.stdout
        record("worktree_path_relativized", ok,
               f"absolute path under repo-root should be relativized (rc={res.returncode})")

        # ----- check 12: secret-like values rejected -----
        bad_secret = base_event(dry_run_id)
        bad_secret["context"]["evidence"] = [
            {"kind": "excerpt", "value": "Authorization: Bearer abc123"}
        ]
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(write_event(event_dir, bad_secret, "secret.json")),
        )
        ok_a = res.returncode != 0 and "secret" in (res.stderr + res.stdout).lower()

        bad_apikey = base_event(dry_run_id)
        bad_apikey["context"]["evidence"] = [
            {"kind": "excerpt", "value": "api_key = sk-abcdefghijklmnopqrstu"}
        ]
        res = run_helper(
            "append",
            "--log-root", str(log_root3),
            "--run-id", dry_run_id,
            "--event-json", str(write_event(event_dir, bad_apikey, "apikey.json")),
        )
        ok_b = res.returncode != 0 and "secret" in (res.stderr + res.stdout).lower()

        record("secret_like_values_rejected", ok_a and ok_b,
               "secret-like values should be rejected (Authorization Bearer, api_key=sk-...)")

        # ----- check 13: concurrent runs isolated (4 parallel run_ids) -----
        log_root4 = temp_path / "log4"
        repo_root4 = temp_path / "repo4"
        repo_root4.mkdir()

        def worker(idx: int) -> bool:
            rid = init_run(log_root4, repo_root4,
                           session_id=f"{idx:08x}-d69e-45d2-91ad-91ad91ad91ad")
            for i in range(20):
                ev = base_event(rid)
                ev["summary"] = f"worker {idx} event {i}"
                cand = event_dir / f"w{idx}-{i}.json"
                cand.write_text(json.dumps(ev), encoding="utf-8")
                r = run_helper(
                    "append",
                    "--log-root", str(log_root4),
                    "--run-id", rid,
                    "--event-json", str(cand),
                )
                if r.returncode != 0:
                    return False
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(worker, range(4)))
        run_dirs = list((log_root4 / "runs").glob("*/*/events.jsonl"))
        total_lines = sum(len(p.read_text().splitlines()) for p in run_dirs)
        ok = all(results) and len(run_dirs) == 4 and total_lines == 80
        record("concurrent_runs_isolated", ok,
               f"4 parallel runs each writing 20 events should produce 4 dirs with 80 lines total (got {len(run_dirs)} dirs, {total_lines} lines)")

        # ----- check 14: close-run with 0 events sets event_count=0 -----
        log_root5 = temp_path / "log5"
        repo_root5 = temp_path / "repo5"
        repo_root5.mkdir()
        empty_run = init_run(log_root5, repo_root5,
                             session_id="ffffffff-d69e-45d2-91ad-91ad91ad91ad")
        res = run_helper(
            "close-run",
            "--log-root", str(log_root5),
            "--run-id", empty_run,
            "--outcome", "success",
        )
        meta_empty = json.loads((run_dir(log_root5, empty_run) / "meta.json").read_text())
        ok = res.returncode == 0 and meta_empty.get("event_count") == 0 and meta_empty.get("outcome") == "success"
        record("close_run_zero_events", ok,
               "close-run on a run with 0 events should set event_count=0 + outcome")

        # ----- check 15: append-session-id extends meta.session_ids -----
        new_sid = "cccccccc-d69e-45d2-91ad-91ad91ad91ad"
        res = run_helper(
            "append-session-id",
            "--log-root", str(log_root5),
            "--run-id", empty_run,
            "--session-id", new_sid,
        )
        meta_chain = json.loads((run_dir(log_root5, empty_run) / "meta.json").read_text())
        sids = meta_chain.get("session_ids", [])
        ok = res.returncode == 0 and len(sids) == 2 and new_sid in sids

        # idempotent on repeat
        res2 = run_helper(
            "append-session-id",
            "--log-root", str(log_root5),
            "--run-id", empty_run,
            "--session-id", new_sid,
        )
        meta_chain2 = json.loads((run_dir(log_root5, empty_run) / "meta.json").read_text())
        sids2 = meta_chain2.get("session_ids", [])
        ok2 = res2.returncode == 0 and len(sids2) == 2  # not duplicated

        record("append_session_id_idempotent", ok and ok2,
               f"append-session-id should extend session_ids[] and be idempotent (sids={sids2})")

        # ----- check 16: context_health (v2.10) accepted with severity=low -----
        ctx_health = base_event(empty_run)
        ctx_health["event_type"] = "context_health"
        ctx_health["severity"] = "low"
        ctx_health["subagent"] = {
            "role": "orchestrator", "model": "opus", "dispatch": "orchestrator",
        }
        ctx_health["summary"] = "Phase Transition T3: passive context-health snapshot."
        ctx_health["context"] = {
            "user_intent": "Observe context-management state across compactions.",
            "agent_expectation": "Counters captured at compaction boundary.",
            "actual_outcome": "Snapshot recorded.",
            "root_cause": "Routine emit point — not a failure.",
            "evidence": [{"kind": "issue_key", "value": "context_health_snapshot"}],
            "compaction_index": 2,
            "completed_tasks_count": 8,
            "resume_chain_handoffs": 0,
        }
        # scores not required for context_health
        ctx_health.pop("scores", None)
        res = run_helper(
            "append",
            "--log-root", str(log_root5),
            "--run-id", empty_run,
            "--event-json", str(write_event(event_dir, ctx_health, "ctx_health.json")),
            "--repo-root", str(repo_root5),
            "--dry-run",
        )
        ok = res.returncode == 0 and "context_health" in res.stdout
        record("context_health_accepted", ok,
               f"context_health event should be accepted (rc={res.returncode}, stderr={res.stderr[:200]})")

        # ----- check 17: bad run_id mismatch in append fails -----
        wrong = base_event("20260513T143321Z-deadbeef-99999")
        res = run_helper(
            "append",
            "--log-root", str(log_root5),
            "--run-id", empty_run,
            "--event-json", str(write_event(event_dir, wrong, "wrong.json")),
        )
        ok = res.returncode != 0 and "run_id" in (res.stderr + res.stdout)
        record("run_id_mismatch_rejected", ok,
               "append with event.run_id != --run-id should fail")

        # ----- outcome fixture helpers (resolver deferred to later task per plan v2.11) -----
        # These fixture builders construct on-disk state and return expected_status /
        # expected_warnings so the future outcome-resolver can be verified against them.
        # For now we assert the on-disk artifacts exist and have the correct content.

        def fixture_index_unknown_final_success(fx_root: Path) -> dict:
            run_id_fx = "20260514T010000Z-test-success-aaaa-aaaaaa"
            rd_fx = fx_root / "runs" / "2026-05-14" / run_id_fx
            rd_fx.mkdir(parents=True, exist_ok=True)
            (fx_root / "index.jsonl").write_text(json.dumps({
                "schema_version": "1", "run_id": run_id_fx, "outcome": "unknown",
            }) + "\n", encoding="utf-8")
            (rd_fx / "final.json").write_text(json.dumps({
                "schema_version": "1", "run_id": run_id_fx, "outcome": "success",
            }), encoding="utf-8")
            return {
                "run_id": run_id_fx,
                "run_dir": rd_fx,
                "index_path": fx_root / "index.jsonl",
                "expected_status": "success",
                "expected_warnings": ["index_outcome_stale"],
            }

        def fixture_zero_event_success(fx_root: Path) -> dict:
            run_id_fx = "20260514T020000Z-test-zero-bbbb-bbbbbb"
            rd_fx = fx_root / "runs" / "2026-05-14" / run_id_fx
            rd_fx.mkdir(parents=True, exist_ok=True)
            (rd_fx / "final.json").write_text(json.dumps({
                "schema_version": "1", "run_id": run_id_fx,
                "outcome": "success", "event_count": 0,
            }), encoding="utf-8")
            return {
                "run_id": run_id_fx,
                "run_dir": rd_fx,
                "expected_status": "success",
                "expected_warnings": [],
            }

        def fixture_dead_pid_unclosed_run(fx_root: Path) -> dict | None:
            dead_pid = 999999
            try:
                os.kill(dead_pid, 0)
                # PermissionError means PID exists on this host — skip fixture
                return None
            except ProcessLookupError:
                pass
            except PermissionError:
                return None
            run_id_fx = "20260514T030000Z-test-dead-cccc-cccccc"
            rd_fx = fx_root / "runs" / "2026-05-14" / run_id_fx
            rd_fx.mkdir(parents=True, exist_ok=True)
            (rd_fx / "meta.json").write_text(json.dumps({
                "schema_version": "1", "run_id": run_id_fx,
                "outcome": "unknown", "event_count": 0,
                "ended_at": None, "pid": dead_pid,
            }), encoding="utf-8")
            return {
                "run_id": run_id_fx,
                "run_dir": rd_fx,
                "expected_status": "stale",
                "expected_warnings": ["dead_pid_unclosed"],
            }

        def fixture_live_pid_unclosed_run(fx_root: Path) -> dict:
            live_pid = os.getpid()
            run_id_fx = "20260514T040000Z-test-live-dddd-dddddd"
            rd_fx = fx_root / "runs" / "2026-05-14" / run_id_fx
            rd_fx.mkdir(parents=True, exist_ok=True)
            (rd_fx / "meta.json").write_text(json.dumps({
                "schema_version": "1", "run_id": run_id_fx,
                "outcome": "unknown", "event_count": 0,
                "ended_at": None, "pid": live_pid,
            }), encoding="utf-8")
            return {
                "run_id": run_id_fx,
                "run_dir": rd_fx,
                "expected_status": "unknown",
                "expected_warnings": [],
            }

        fx_root_base = temp_path / "fx"
        fx_root_base.mkdir()

        # ----- check 18: fixture_index_unknown_final_success -----
        fx18 = fixture_index_unknown_final_success(fx_root_base / "fx18")
        final18 = json.loads((fx18["run_dir"] / "final.json").read_text(encoding="utf-8"))
        index18_line = json.loads((fx18["index_path"]).read_text(encoding="utf-8").splitlines()[0])
        ok = (
            final18.get("outcome") == "success"
            and index18_line.get("outcome") == "unknown"
            and fx18["expected_status"] == "success"
            and "index_outcome_stale" in fx18["expected_warnings"]
        )
        record("fixture_index_unknown_final_success",
               ok, "fixture: index=unknown + final=success -> expected_status=success + warn index_outcome_stale")

        # ----- check 19: fixture_zero_event_success -----
        fx19 = fixture_zero_event_success(fx_root_base / "fx19")
        final19 = json.loads((fx19["run_dir"] / "final.json").read_text(encoding="utf-8"))
        ok = (
            final19.get("outcome") == "success"
            and final19.get("event_count") == 0
            and not (fx19["run_dir"] / "events.jsonl").exists()
            and fx19["expected_status"] == "success"
            and fx19["expected_warnings"] == []
        )
        record("fixture_zero_event_success",
               ok, "fixture: final.outcome=success event_count=0 no events.jsonl -> expected_status=success no warnings")

        # ----- check 20: fixture_dead_pid_unclosed_run -----
        fx20 = fixture_dead_pid_unclosed_run(fx_root_base / "fx20")
        if fx20 is None:
            # PID 999999 is live on this host — skip without failing
            record("fixture_dead_pid_unclosed_run", True,
                   "skipped: PID 999999 is live on this host")
        else:
            meta20 = json.loads((fx20["run_dir"] / "meta.json").read_text(encoding="utf-8"))
            ok = (
                meta20.get("ended_at") is None
                and meta20.get("pid") == 999999
                and not (fx20["run_dir"] / "final.json").exists()
                and fx20["expected_status"] == "stale"
                and "dead_pid_unclosed" in fx20["expected_warnings"]
            )
            record("fixture_dead_pid_unclosed_run",
                   ok, "fixture: no final.json + ended_at=null + dead pid -> expected_status=stale warn dead_pid_unclosed")

        # ----- check 21: fixture_live_pid_unclosed_run -----
        fx21 = fixture_live_pid_unclosed_run(fx_root_base / "fx21")
        meta21 = json.loads((fx21["run_dir"] / "meta.json").read_text(encoding="utf-8"))
        ok = (
            meta21.get("ended_at") is None
            and meta21.get("pid") == os.getpid()
            and not (fx21["run_dir"] / "final.json").exists()
            and fx21["expected_status"] == "unknown"
            and fx21["expected_warnings"] == []
        )
        record("fixture_live_pid_unclosed_run",
               ok, "fixture: no final.json + ended_at=null + live pid -> expected_status=unknown no warnings")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
