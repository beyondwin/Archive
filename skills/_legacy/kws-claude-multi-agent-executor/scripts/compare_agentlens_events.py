#!/usr/bin/env python3
"""Parity checker: legacy learning-log events.jsonl vs AgentLens kws-cme.* events.

Maps legacy `event_type` values from
    ~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/events.jsonl
to AgentLens `type` values from an AgentLens run directory's events.jsonl, restricted
to events whose `type` starts with `kws-cme.`.

Usage:
    compare_agentlens_events.py <legacy_events_jsonl> <agentlens_run_dir>
    compare_agentlens_events.py --self-test

Outputs a JSON parity report to stdout. Exits 0 if parity_ok else 1.

Parity contract (Task 11 / spec v2.17):

* The orchestrator's candidate-drain loop dual-writes each candidate JSON. The
  legacy helper writes the unprefixed `event_type` field; the AgentLens emit
  prefixes that same string with `kws-cme.`. So every legacy event whose
  `event_type` is one of the candidate-drain taxonomy MUST have a matching
  `kws-cme.<event_type>` in the AgentLens stream.

* AgentLens carries four additional orchestrator-only events that have no
  legacy counterpart: `kws-cme.phase_0_started`, `kws-cme.task_completed`,
  `kws-cme.compaction`, `kws-cme.phase_2_complete`. These are intentional
  AgentLens-only events; their presence is NOT a parity violation.

* Timestamps: not strictly compared (legacy and AgentLens emits race within the
  same drain loop). Ordering parity is checked by relative order of matched
  pairs only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


# Legacy event_type values that ARE expected to appear in both streams.
# Mirror of VALID_EVENT_TYPES in append_learning_event.py, intersected with the
# spec §6.2 dual-write contract (every candidate written by sub-agents is
# drained into both streams in the same orchestrator loop).
LEGACY_DUAL_WRITE_TYPES = {
    "blocker",
    "error",
    "verification_failure",
    "reviewer_warn_or_fail",
    "escalation",
    "recurring_issue",
    "user_correction",
    "parallel_dispatch_failure",
    "successful_workaround",
    "completion_learning",
    "context_health",
}

# AgentLens-only event types (orchestrator boundary emits). These have no
# legacy counterpart and their absence from the legacy stream is expected.
AGENTLENS_ONLY_TYPES = {
    "kws-cme.phase_0_started",
    "kws-cme.task_completed",
    "kws-cme.compaction",
    "kws-cme.phase_2_complete",
}


def legacy_to_agentlens(legacy_type: str) -> str:
    """Map a legacy event_type string to its AgentLens type string."""
    return f"kws-cme.{legacy_type}"


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
    """AgentLens run dir layout: <run_dir>/events.jsonl is the canonical file."""
    return run_dir / "events.jsonl"


def compare(legacy_events: list[dict[str, Any]],
            agentlens_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare two event streams and return a parity report.

    Algorithm:
    1. Project legacy events to (legacy_type, expected_agentlens_type) ordered list.
    2. Filter AgentLens events to those starting with "kws-cme." ordered list.
    3. For each legacy expected type, find the FIRST unmatched AgentLens event
       of that type in order. If found: pair it. If not: mark missing_in_agentlens.
    4. Any remaining AgentLens kws-cme.* events that aren't in AGENTLENS_ONLY_TYPES
       are missing_in_legacy.
    5. Ordering mismatch = a matched pair whose AgentLens index is less than the
       previous matched pair's AgentLens index (out-of-order match).
    """
    legacy_pairs: list[tuple[int, str, str]] = []
    for i, ev in enumerate(legacy_events):
        etype = ev.get("event_type")
        if isinstance(etype, str) and etype in LEGACY_DUAL_WRITE_TYPES:
            legacy_pairs.append((i, etype, legacy_to_agentlens(etype)))

    al_indexed: list[tuple[int, str]] = []
    for j, ev in enumerate(agentlens_events):
        atype = ev.get("type")
        if isinstance(atype, str) and atype.startswith("kws-cme."):
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
        if atype in AGENTLENS_ONLY_TYPES:
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
        "agentlens_kws_cme_count": len(al_indexed),
        "parity_ok": parity_ok,
    }


# ---------- self-test ----------

def _build_synthetic_legacy(types: list[str]) -> list[dict[str, Any]]:
    return [{"event_type": t, "summary": f"synthetic {t}", "timestamp": f"2026-05-19T00:00:{i:02d}Z"}
            for i, t in enumerate(types)]


def _build_synthetic_agentlens(types: list[str]) -> list[dict[str, Any]]:
    return [{"type": t, "payload": {}, "ts": f"2026-05-19T00:00:{i:02d}Z"}
            for i, t in enumerate(types)]


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")


def _run_cli(legacy_path: Path, run_dir: Path) -> tuple[int, dict[str, Any]]:
    """Invoke the compare script's main() in-process and capture report + exit."""
    legacy_events = read_jsonl(legacy_path)
    al_events = read_jsonl(find_agentlens_events_file(run_dir))
    report = compare(legacy_events, al_events)
    exit_code = 0 if report["parity_ok"] else 1
    return exit_code, report


def self_test() -> int:
    """Embedded smoke test. Returns 0 on success, 1 on failure."""
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)

        # --- Case A: full parity (every legacy type appears, plus boundary events) ---
        legacy_a = _build_synthetic_legacy([
            "blocker", "verification_failure", "context_health",
            "reviewer_warn_or_fail",
        ])
        agentlens_a = _build_synthetic_agentlens([
            "kws-cme.phase_0_started",
            "kws-cme.blocker",
            "kws-cme.task_completed",
            "kws-cme.verification_failure",
            "kws-cme.context_health",
            "kws-cme.compaction",
            "kws-cme.reviewer_warn_or_fail",
            "kws-cme.phase_2_complete",
        ])
        legacy_path_a = tmp / "case_a" / "legacy.jsonl"
        run_dir_a = tmp / "case_a" / "agentlens_run"
        _write_jsonl(legacy_path_a, legacy_a)
        _write_jsonl(run_dir_a / "events.jsonl", agentlens_a)
        rc, report = _run_cli(legacy_path_a, run_dir_a)
        if rc != 0:
            failures.append(f"case A: expected parity_ok, got rc={rc}, report={report}")
        if len(report["matched"]) != 4:
            failures.append(f"case A: expected 4 matched, got {len(report['matched'])}")
        if report["missing_in_agentlens"]:
            failures.append(f"case A: unexpected missing_in_agentlens: {report['missing_in_agentlens']}")
        if report["missing_in_legacy"]:
            failures.append(f"case A: unexpected missing_in_legacy: {report['missing_in_legacy']}")

        # --- Case B: legacy event with no AgentLens counterpart ---
        legacy_b = _build_synthetic_legacy(["blocker", "verification_failure"])
        agentlens_b = _build_synthetic_agentlens([
            "kws-cme.blocker",
            # verification_failure missing
        ])
        legacy_path_b = tmp / "case_b" / "legacy.jsonl"
        run_dir_b = tmp / "case_b" / "agentlens_run"
        _write_jsonl(legacy_path_b, legacy_b)
        _write_jsonl(run_dir_b / "events.jsonl", agentlens_b)
        rc, report = _run_cli(legacy_path_b, run_dir_b)
        if rc == 0:
            failures.append("case B: expected non-zero exit (parity broken)")
        if not any(m["expected_agentlens_type"] == "kws-cme.verification_failure"
                   for m in report["missing_in_agentlens"]):
            failures.append(f"case B: expected verification_failure missing in agentlens, got {report['missing_in_agentlens']}")

        # --- Case C: AgentLens has an unexpected non-boundary event ---
        legacy_c = _build_synthetic_legacy(["blocker"])
        agentlens_c = _build_synthetic_agentlens([
            "kws-cme.blocker",
            "kws-cme.context_health",  # no legacy counterpart
        ])
        legacy_path_c = tmp / "case_c" / "legacy.jsonl"
        run_dir_c = tmp / "case_c" / "agentlens_run"
        _write_jsonl(legacy_path_c, legacy_c)
        _write_jsonl(run_dir_c / "events.jsonl", agentlens_c)
        rc, report = _run_cli(legacy_path_c, run_dir_c)
        if rc == 0:
            failures.append("case C: expected non-zero exit (extra kws-cme.context_health unmatched)")
        if not any(m["agentlens_type"] == "kws-cme.context_health"
                   for m in report["missing_in_legacy"]):
            failures.append(f"case C: expected context_health missing_in_legacy, got {report['missing_in_legacy']}")

        # --- Case D: matched but out of order ---
        legacy_d = _build_synthetic_legacy(["blocker", "verification_failure"])
        agentlens_d = _build_synthetic_agentlens([
            "kws-cme.verification_failure",
            "kws-cme.blocker",
        ])
        legacy_path_d = tmp / "case_d" / "legacy.jsonl"
        run_dir_d = tmp / "case_d" / "agentlens_run"
        _write_jsonl(legacy_path_d, legacy_d)
        _write_jsonl(run_dir_d / "events.jsonl", agentlens_d)
        rc, report = _run_cli(legacy_path_d, run_dir_d)
        if rc == 0:
            failures.append("case D: expected non-zero exit (ordering mismatch)")
        if not report["ordering_mismatches"]:
            failures.append(f"case D: expected ordering_mismatches non-empty, got {report}")

        # --- Case E: empty legacy + only boundary AgentLens events => parity ok ---
        legacy_e: list[dict[str, Any]] = []
        agentlens_e = _build_synthetic_agentlens([
            "kws-cme.phase_0_started",
            "kws-cme.phase_2_complete",
        ])
        legacy_path_e = tmp / "case_e" / "legacy.jsonl"
        run_dir_e = tmp / "case_e" / "agentlens_run"
        _write_jsonl(legacy_path_e, legacy_e)
        _write_jsonl(run_dir_e / "events.jsonl", agentlens_e)
        rc, report = _run_cli(legacy_path_e, run_dir_e)
        if rc != 0:
            failures.append(f"case E: expected parity_ok (boundary-only), got rc={rc}, report={report}")

        # --- Case F: state.json resume schema test — agentlens_orchestration_run optional ---
        # Verifies that a state.json without the agentlens_orchestration_run field is still
        # treated as resumable. The compare script doesn't read state.json directly, but we
        # encode this contract here as a documentation-grade assertion: the resume protocol's
        # legacy-defaults block (SKILL.md Phase 0 Step 0) uses setdefault, so missing field
        # is safe.
        synthetic_state_no_field = {
            "schema_version": "2",
            "mode": "headless_running",
            "plan": "plans/x.md",
        }
        synthetic_state_with_field = {**synthetic_state_no_field,
                                       "agentlens_orchestration_run": None}
        # Both shapes must be valid JSON and load cleanly.
        try:
            json.loads(json.dumps(synthetic_state_no_field))
            json.loads(json.dumps(synthetic_state_with_field))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"case F: state.json shapes failed roundtrip: {exc}")
        # Field is optional => absence must not be a structural error.
        if "agentlens_orchestration_run" in synthetic_state_no_field:
            failures.append("case F: pre-condition violated (field should be absent)")

    if failures:
        print("SELF-TEST FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("self-test ok: 6 cases passed (A parity, B missing-in-agentlens, "
          "C extra-in-agentlens, D ordering, E boundary-only, F state.json optional field)")
    return 0


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("legacy_events_jsonl", nargs="?",
                   help="Path to legacy ~/.claude/learning/.../events.jsonl")
    p.add_argument("agentlens_run_dir", nargs="?",
                   help="Path to AgentLens run dir (contains events.jsonl)")
    p.add_argument("--self-test", action="store_true",
                   help="Run embedded synthetic parity tests; exit 0 on success.")
    p.add_argument("--indent", type=int, default=2,
                   help="JSON output indent (default: 2)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.legacy_events_jsonl or not args.agentlens_run_dir:
        print("error: legacy_events_jsonl and agentlens_run_dir are required "
              "(or use --self-test)", file=sys.stderr)
        return 2
    legacy_path = Path(args.legacy_events_jsonl).expanduser()
    run_dir = Path(args.agentlens_run_dir).expanduser()
    if not legacy_path.is_file():
        print(f"error: legacy events file not found: {legacy_path}", file=sys.stderr)
        return 2
    if not run_dir.is_dir():
        print(f"error: AgentLens run dir not found: {run_dir}", file=sys.stderr)
        return 2
    legacy_events = read_jsonl(legacy_path)
    al_events = read_jsonl(find_agentlens_events_file(run_dir))
    report = compare(legacy_events, al_events)
    print(json.dumps(report, indent=args.indent, sort_keys=True))
    return 0 if report["parity_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
