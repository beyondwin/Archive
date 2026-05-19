#!/usr/bin/env python3
"""Parity checker: legacy kws-cpe event journals vs AgentLens kws-cpe.* events.

kws-cpe has TWO legacy event layers; this script compares both:

1. Project-local event journal
     .codex-orchestrator/runs/<run_id>/events.jsonl
   (emitted by the now-removed `scripts/append_run_event.py`) vs the AgentLens
   stream restricted to `kws-cpe.<event>` types.

2. User-local learning log
     ~/.codex/learning/kws-codex-plan-executor/runs/<date>/<run_id>/events.jsonl
   (emitted by the now-removed `scripts/append_learning_event.py`) vs the
   AgentLens stream restricted to `kws-cpe.learning.<event>` types.

Usage:
    compare_agentlens_events.py [--journal <journal.jsonl>] [--learning <learning.jsonl>] \\
                                <agentlens_run_dir>
    compare_agentlens_events.py --self-test

Outputs a single JSON parity report to stdout. Exits 0 if both layers report
`parity_ok=true`; non-zero otherwise.

Parity contract (Task 13 / spec v2.18):

Journal layer (project-local) — most legacy types share names with their
AgentLens mirror but THREE are renamed:

  | Legacy `type`           | AgentLens `type`         |
  |-------------------------|--------------------------|
  | run_started             | kws-cpe.run_started      |
  | task_contract_recorded  | kws-cpe.task_started     |   ← rename
  | task_completed          | kws-cpe.task_completed   |
  | verification_passed     | kws-cpe.verification_passed |
  | verification_failed     | kws-cpe.verification_failed |
  | blocked                 | kws-cpe.blocker          |   ← rename
  | failed                  | kws-cpe.failed           |
  | finished                | kws-cpe.run_completed    |   ← rename

The other legacy journal vocabulary (`context_snapshot_created`,
`pre_dispatch_checked`, `dispatch_gate_failed`, `task_started`,
`verification_started`, `drift_detected`, `drift_repaired`) has no dual-write
counterpart at the documented emit sites; events of those types in the legacy
stream are NOT expected to appear in AgentLens.

`kws-cpe.compaction` is an AgentLens-only orchestrator boundary event with no
legacy counterpart; its absence from the legacy stream is expected.

Learning layer (user-local) — clean prefix:

  legacy event_type  ↔  kws-cpe.learning.<event_type>

for all of: blocker, error, verification_failure, recurring_issue,
user_correction, successful_workaround, completion_learning.

Ordering parity is checked by relative order of matched pairs only (legacy and
AgentLens emits race within the same dual-write site, so timestamps are not
strictly compared).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


# ---------- mapping tables ----------

# Journal layer: legacy run-event `type` → AgentLens `type` (kws-cpe.*).
# Only entries with documented dual-write emits are listed. Other legacy
# vocabulary is ignored when comparing.
JOURNAL_LEGACY_TO_AGENTLENS: dict[str, str] = {
    "run_started": "kws-cpe.run_started",
    "task_contract_recorded": "kws-cpe.task_started",
    "task_completed": "kws-cpe.task_completed",
    "verification_passed": "kws-cpe.verification_passed",
    "verification_failed": "kws-cpe.verification_failed",
    "blocked": "kws-cpe.blocker",
    "failed": "kws-cpe.failed",
    "finished": "kws-cpe.run_completed",
}

# AgentLens-only journal-layer types: orchestrator boundary emits without a
# legacy counterpart. Their presence in AgentLens is not a parity violation.
JOURNAL_AGENTLENS_ONLY: set[str] = {
    "kws-cpe.compaction",
}

# Learning layer: clean prefix kws-cpe.learning.<event_type>.
LEARNING_DUAL_WRITE_TYPES: set[str] = {
    "blocker",
    "error",
    "verification_failure",
    "recurring_issue",
    "user_correction",
    "successful_workaround",
    "completion_learning",
}
LEARNING_AGENTLENS_ONLY: set[str] = set()


def learning_to_agentlens(legacy_type: str) -> str:
    return f"kws-cpe.learning.{legacy_type}"


# ---------- IO ----------

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def find_agentlens_events_file(run_dir: Path) -> Path:
    return run_dir / "events.jsonl"


# ---------- comparison engine ----------

def _compare_streams(
    legacy_events: list[dict[str, Any]],
    legacy_type_key: str,
    expected_map: dict[str, str],
    agentlens_events: list[dict[str, Any]],
    agentlens_prefix: str,
    agentlens_only: set[str],
) -> dict[str, Any]:
    """Generic ordered-match parity comparison.

    Args:
        legacy_events: legacy JSONL events (already loaded).
        legacy_type_key: name of the legacy event-type field
            (`"type"` for the journal layer, `"event_type"` for the learning
            layer).
        expected_map: legacy type → AgentLens type mapping for events expected
            to dual-write.
        agentlens_events: AgentLens stream JSONL (already loaded).
        agentlens_prefix: AgentLens namespace prefix (e.g. `"kws-cpe."` or
            `"kws-cpe.learning."`).
        agentlens_only: AgentLens-namespace types intentionally without a
            legacy counterpart.
    """
    legacy_pairs: list[tuple[int, str, str]] = []
    for i, ev in enumerate(legacy_events):
        etype = ev.get(legacy_type_key)
        if isinstance(etype, str) and etype in expected_map:
            legacy_pairs.append((i, etype, expected_map[etype]))

    al_indexed: list[tuple[int, str]] = []
    for j, ev in enumerate(agentlens_events):
        atype = ev.get("type")
        if isinstance(atype, str) and atype.startswith(agentlens_prefix):
            # Learning layer: ensure we only count learning.* events in that
            # comparison, not the broader kws-cpe.* journal events.
            if agentlens_prefix == "kws-cpe." and atype.startswith("kws-cpe.learning."):
                continue
            al_indexed.append((j, atype))

    consumed_al: set[int] = set()
    matched: list[dict[str, Any]] = []
    missing_in_agentlens: list[dict[str, Any]] = []
    last_al_idx = -1
    ordering_mismatches: list[dict[str, Any]] = []

    for legacy_idx, legacy_type, expected_al_type in legacy_pairs:
        found_idx: int | None = None
        for j, atype in al_indexed:
            if j in consumed_al:
                continue
            if atype == expected_al_type:
                found_idx = j
                break
        if found_idx is None:
            missing_in_agentlens.append({
                "legacy_index": legacy_idx,
                "legacy_event_type": legacy_type,
                "expected_agentlens_type": expected_al_type,
            })
            continue
        consumed_al.add(found_idx)
        matched.append({
            "legacy_index": legacy_idx,
            "legacy_event_type": legacy_type,
            "agentlens_index": found_idx,
            "agentlens_type": expected_al_type,
        })
        if found_idx < last_al_idx:
            ordering_mismatches.append({
                "legacy_index": legacy_idx,
                "agentlens_index": found_idx,
                "prior_agentlens_index": last_al_idx,
            })
        last_al_idx = found_idx

    missing_in_legacy: list[dict[str, Any]] = []
    for j, atype in al_indexed:
        if j in consumed_al:
            continue
        if atype in agentlens_only:
            continue
        missing_in_legacy.append({
            "agentlens_index": j,
            "agentlens_type": atype,
        })

    parity_ok = (
        not missing_in_agentlens
        and not missing_in_legacy
        and not ordering_mismatches
    )

    return {
        "matched": matched,
        "missing_in_agentlens": missing_in_agentlens,
        "missing_in_legacy": missing_in_legacy,
        "ordering_mismatches": ordering_mismatches,
        "legacy_event_count": len(legacy_events),
        "agentlens_event_count": len(agentlens_events),
        "agentlens_namespace_count": len(al_indexed),
        "parity_ok": parity_ok,
    }


def compare_journal(
    legacy_events: list[dict[str, Any]],
    agentlens_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Journal layer: legacy.events.jsonl uses `type`; AgentLens namespace `kws-cpe.*`."""
    return _compare_streams(
        legacy_events=legacy_events,
        legacy_type_key="type",
        expected_map=JOURNAL_LEGACY_TO_AGENTLENS,
        agentlens_events=agentlens_events,
        agentlens_prefix="kws-cpe.",
        agentlens_only=JOURNAL_AGENTLENS_ONLY,
    )


def compare_learning(
    legacy_events: list[dict[str, Any]],
    agentlens_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Learning layer: legacy events use `event_type`; AgentLens namespace `kws-cpe.learning.*`."""
    expected_map = {t: learning_to_agentlens(t) for t in LEARNING_DUAL_WRITE_TYPES}
    return _compare_streams(
        legacy_events=legacy_events,
        legacy_type_key="event_type",
        expected_map=expected_map,
        agentlens_events=agentlens_events,
        agentlens_prefix="kws-cpe.learning.",
        agentlens_only=LEARNING_AGENTLENS_ONLY,
    )


# ---------- self-test ----------

def _build_journal_events(types: list[str]) -> list[dict[str, Any]]:
    return [{"type": t, "seq": i + 1,
             "timestamp": f"2026-05-19T00:00:{i:02d}Z",
             "payload": {"k": t}}
            for i, t in enumerate(types)]


def _build_learning_events(types: list[str]) -> list[dict[str, Any]]:
    return [{"event_type": t, "summary": f"synthetic {t}",
             "timestamp": f"2026-05-19T00:00:{i:02d}Z"}
            for i, t in enumerate(types)]


def _build_agentlens_events(types: list[str]) -> list[dict[str, Any]]:
    return [{"type": t, "payload": {}, "ts": f"2026-05-19T00:00:{i:02d}Z"}
            for i, t in enumerate(types)]


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")


def _run_cli_dual(
    journal_path: Path,
    learning_path: Path,
    run_dir: Path,
) -> tuple[int, dict[str, Any]]:
    al_events = read_jsonl(find_agentlens_events_file(run_dir))
    journal_events = read_jsonl(journal_path) if journal_path.is_file() else []
    learning_events = read_jsonl(learning_path) if learning_path.is_file() else []
    journal_report = compare_journal(journal_events, al_events)
    learning_report = compare_learning(learning_events, al_events)
    parity_ok = journal_report["parity_ok"] and learning_report["parity_ok"]
    report = {
        "journal": journal_report,
        "learning": learning_report,
        "parity_ok": parity_ok,
    }
    return (0 if parity_ok else 1), report


def self_test() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)

        # --- Case A: full parity across both layers, including all three renames ---
        journal_a = _build_journal_events([
            "run_started",                # → kws-cpe.run_started
            "task_contract_recorded",     # rename → kws-cpe.task_started
            "task_completed",
            "verification_passed",
            "blocked",                    # rename → kws-cpe.blocker
            "failed",
            "finished",                   # rename → kws-cpe.run_completed
        ])
        learning_a = _build_learning_events([
            "blocker", "verification_failure", "completion_learning",
        ])
        agentlens_a = _build_agentlens_events([
            "kws-cpe.run_started",
            "kws-cpe.task_started",
            "kws-cpe.task_completed",
            "kws-cpe.verification_passed",
            "kws-cpe.compaction",          # AgentLens-only, fine
            "kws-cpe.blocker",
            "kws-cpe.failed",
            "kws-cpe.run_completed",
            "kws-cpe.learning.blocker",
            "kws-cpe.learning.verification_failure",
            "kws-cpe.learning.completion_learning",
        ])
        jp_a = tmp / "case_a" / "journal.jsonl"
        lp_a = tmp / "case_a" / "learning.jsonl"
        rd_a = tmp / "case_a" / "agentlens_run"
        _write_jsonl(jp_a, journal_a)
        _write_jsonl(lp_a, learning_a)
        _write_jsonl(rd_a / "events.jsonl", agentlens_a)
        rc, report = _run_cli_dual(jp_a, lp_a, rd_a)
        if rc != 0:
            failures.append(f"case A: expected parity_ok across both layers, got rc={rc}, report={report}")
        if len(report["journal"]["matched"]) != 7:
            failures.append(f"case A: journal expected 7 matched, got {len(report['journal']['matched'])}")
        if len(report["learning"]["matched"]) != 3:
            failures.append(f"case A: learning expected 3 matched, got {len(report['learning']['matched'])}")

        # --- Case B: journal layer missing the renamed `task_contract_recorded` mirror ---
        journal_b = _build_journal_events(["run_started", "task_contract_recorded"])
        learning_b: list[dict[str, Any]] = []
        agentlens_b = _build_agentlens_events([
            "kws-cpe.run_started",
            # kws-cpe.task_started missing — rename gap
        ])
        jp_b = tmp / "case_b" / "journal.jsonl"
        lp_b = tmp / "case_b" / "learning.jsonl"
        rd_b = tmp / "case_b" / "agentlens_run"
        _write_jsonl(jp_b, journal_b)
        _write_jsonl(lp_b, learning_b)
        _write_jsonl(rd_b / "events.jsonl", agentlens_b)
        rc, report = _run_cli_dual(jp_b, lp_b, rd_b)
        if rc == 0:
            failures.append("case B: expected non-zero exit (missing renamed task_started)")
        if not any(m["expected_agentlens_type"] == "kws-cpe.task_started"
                   for m in report["journal"]["missing_in_agentlens"]):
            failures.append(f"case B: expected kws-cpe.task_started missing_in_agentlens, got {report['journal']['missing_in_agentlens']}")

        # --- Case C: AgentLens has an extra journal-layer event not in legacy ---
        journal_c = _build_journal_events(["run_started"])
        learning_c: list[dict[str, Any]] = []
        agentlens_c = _build_agentlens_events([
            "kws-cpe.run_started",
            "kws-cpe.task_completed",  # extra; no legacy counterpart
        ])
        jp_c = tmp / "case_c" / "journal.jsonl"
        lp_c = tmp / "case_c" / "learning.jsonl"
        rd_c = tmp / "case_c" / "agentlens_run"
        _write_jsonl(jp_c, journal_c)
        _write_jsonl(lp_c, learning_c)
        _write_jsonl(rd_c / "events.jsonl", agentlens_c)
        rc, report = _run_cli_dual(jp_c, lp_c, rd_c)
        if rc == 0:
            failures.append("case C: expected non-zero exit (extra kws-cpe.task_completed)")
        if not any(m["agentlens_type"] == "kws-cpe.task_completed"
                   for m in report["journal"]["missing_in_legacy"]):
            failures.append(f"case C: expected kws-cpe.task_completed missing_in_legacy, got {report['journal']['missing_in_legacy']}")

        # --- Case D: ordering mismatch in journal layer (finished before blocker) ---
        journal_d = _build_journal_events(["blocked", "finished"])
        learning_d: list[dict[str, Any]] = []
        agentlens_d = _build_agentlens_events([
            "kws-cpe.run_completed",  # finished mirror comes first
            "kws-cpe.blocker",
        ])
        jp_d = tmp / "case_d" / "journal.jsonl"
        lp_d = tmp / "case_d" / "learning.jsonl"
        rd_d = tmp / "case_d" / "agentlens_run"
        _write_jsonl(jp_d, journal_d)
        _write_jsonl(lp_d, learning_d)
        _write_jsonl(rd_d / "events.jsonl", agentlens_d)
        rc, report = _run_cli_dual(jp_d, lp_d, rd_d)
        if rc == 0:
            failures.append("case D: expected non-zero exit (ordering mismatch)")
        if not report["journal"]["ordering_mismatches"]:
            failures.append(f"case D: expected journal ordering_mismatches non-empty, got {report['journal']}")

        # --- Case E: empty legacy + only AgentLens-only journal types => parity ok ---
        jp_e = tmp / "case_e" / "journal.jsonl"
        lp_e = tmp / "case_e" / "learning.jsonl"
        rd_e = tmp / "case_e" / "agentlens_run"
        _write_jsonl(jp_e, [])
        _write_jsonl(lp_e, [])
        _write_jsonl(rd_e / "events.jsonl", _build_agentlens_events([
            "kws-cpe.compaction",
        ]))
        rc, report = _run_cli_dual(jp_e, lp_e, rd_e)
        if rc != 0:
            failures.append(f"case E: expected parity_ok for boundary-only AgentLens stream, got {report}")

        # --- Case F: learning layer parity, mapping kws-cpe.learning.<event> ---
        journal_f = _build_journal_events(["run_started"])
        learning_f = _build_learning_events([
            "successful_workaround", "user_correction",
        ])
        agentlens_f = _build_agentlens_events([
            "kws-cpe.run_started",
            "kws-cpe.learning.successful_workaround",
            "kws-cpe.learning.user_correction",
        ])
        jp_f = tmp / "case_f" / "journal.jsonl"
        lp_f = tmp / "case_f" / "learning.jsonl"
        rd_f = tmp / "case_f" / "agentlens_run"
        _write_jsonl(jp_f, journal_f)
        _write_jsonl(lp_f, learning_f)
        _write_jsonl(rd_f / "events.jsonl", agentlens_f)
        rc, report = _run_cli_dual(jp_f, lp_f, rd_f)
        if rc != 0:
            failures.append(f"case F: expected parity_ok learning layer, got rc={rc}, report={report}")
        if len(report["learning"]["matched"]) != 2:
            failures.append(f"case F: learning expected 2 matched, got {report['learning']}")

        # --- Case G: learning layer missing-in-agentlens ---
        learning_g = _build_learning_events(["blocker", "recurring_issue"])
        agentlens_g = _build_agentlens_events([
            "kws-cpe.learning.blocker",
            # kws-cpe.learning.recurring_issue missing
        ])
        jp_g = tmp / "case_g" / "journal.jsonl"
        lp_g = tmp / "case_g" / "learning.jsonl"
        rd_g = tmp / "case_g" / "agentlens_run"
        _write_jsonl(jp_g, [])
        _write_jsonl(lp_g, learning_g)
        _write_jsonl(rd_g / "events.jsonl", agentlens_g)
        rc, report = _run_cli_dual(jp_g, lp_g, rd_g)
        if rc == 0:
            failures.append("case G: expected non-zero exit (learning recurring_issue missing)")
        if not any(m["expected_agentlens_type"] == "kws-cpe.learning.recurring_issue"
                   for m in report["learning"]["missing_in_agentlens"]):
            failures.append(f"case G: expected learning.recurring_issue missing_in_agentlens, got {report['learning']}")

        # --- Case H: rename gap — `blocked → kws-cpe.blocker` not honored ---
        # Catches the specific bug where someone naively used `f"kws-cpe.{t}"`
        # and emitted `kws-cpe.blocked` instead of the required `kws-cpe.blocker`.
        journal_h = _build_journal_events(["blocked"])
        agentlens_h = _build_agentlens_events([
            "kws-cpe.blocked",  # wrong name; the dual-write contract requires kws-cpe.blocker
        ])
        jp_h = tmp / "case_h" / "journal.jsonl"
        lp_h = tmp / "case_h" / "learning.jsonl"
        rd_h = tmp / "case_h" / "agentlens_run"
        _write_jsonl(jp_h, journal_h)
        _write_jsonl(lp_h, [])
        _write_jsonl(rd_h / "events.jsonl", agentlens_h)
        rc, report = _run_cli_dual(jp_h, lp_h, rd_h)
        if rc == 0:
            failures.append("case H: expected non-zero exit (rename `blocked → kws-cpe.blocker` not honored)")
        if not any(m["expected_agentlens_type"] == "kws-cpe.blocker"
                   for m in report["journal"]["missing_in_agentlens"]):
            failures.append(f"case H: expected kws-cpe.blocker missing_in_agentlens, got {report['journal']}")
        if not any(m["agentlens_type"] == "kws-cpe.blocked"
                   for m in report["journal"]["missing_in_legacy"]):
            failures.append(f"case H: expected kws-cpe.blocked missing_in_legacy (extra), got {report['journal']}")

        # --- Case I: state.json optional `agentlens_orchestration_run` field roundtrip ---
        synthetic_state_no_field = {
            "schema_version": "1",
            "mode": "interactive",
            "plan": "plans/x.md",
        }
        synthetic_state_with_field = {**synthetic_state_no_field,
                                       "agentlens_orchestration_run": None}
        try:
            json.loads(json.dumps(synthetic_state_no_field))
            json.loads(json.dumps(synthetic_state_with_field))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"case I: state.json shapes failed roundtrip: {exc}")
        if "agentlens_orchestration_run" in synthetic_state_no_field:
            failures.append("case I: pre-condition violated (field should be absent)")

    if failures:
        print("SELF-TEST FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("self-test ok: 9 cases passed (A both-layer parity, B journal-rename-missing, "
          "C journal-extra, D journal-ordering, E boundary-only, F learning-parity, "
          "G learning-missing-in-agentlens, H rename `blocked→kws-cpe.blocker` enforced, "
          "I state.json optional field)")
    return 0


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("agentlens_run_dir", nargs="?",
                   help="Path to AgentLens run dir (contains events.jsonl)")
    p.add_argument("--journal",
                   help="Path to project-local .codex-orchestrator/runs/<run_id>/events.jsonl")
    p.add_argument("--learning",
                   help="Path to user-local ~/.codex/learning/.../events.jsonl")
    p.add_argument("--self-test", action="store_true",
                   help="Run embedded synthetic parity tests; exit 0 on success.")
    p.add_argument("--indent", type=int, default=2,
                   help="JSON output indent (default: 2)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.agentlens_run_dir:
        print("error: agentlens_run_dir is required (or use --self-test)",
              file=sys.stderr)
        return 2
    run_dir = Path(args.agentlens_run_dir).expanduser()
    if not run_dir.is_dir():
        print(f"error: AgentLens run dir not found: {run_dir}", file=sys.stderr)
        return 2
    al_events = read_jsonl(find_agentlens_events_file(run_dir))

    journal_events: list[dict[str, Any]] = []
    if args.journal:
        jp = Path(args.journal).expanduser()
        if not jp.is_file():
            print(f"error: --journal file not found: {jp}", file=sys.stderr)
            return 2
        journal_events = read_jsonl(jp)

    learning_events: list[dict[str, Any]] = []
    if args.learning:
        lp = Path(args.learning).expanduser()
        if not lp.is_file():
            print(f"error: --learning file not found: {lp}", file=sys.stderr)
            return 2
        learning_events = read_jsonl(lp)

    journal_report = compare_journal(journal_events, al_events)
    learning_report = compare_learning(learning_events, al_events)
    parity_ok = journal_report["parity_ok"] and learning_report["parity_ok"]
    report = {
        "journal": journal_report,
        "learning": learning_report,
        "parity_ok": parity_ok,
    }
    print(json.dumps(report, indent=args.indent, sort_keys=True))
    return 0 if parity_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
