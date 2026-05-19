#!/usr/bin/env python3
"""Accumulate a single sub-agent dispatch's usage into state.cost_ledger.

Designed to be called from the orchestrator in Phase 1 Step 4 substep 1.5
("Accumulate cost (F2)"). Reads state.json, computes cost via price_table,
and updates by_task / by_role / by_model / totals atomically (R-M-W under
an exclusive flock on state.json).

Usage:
    python3 accumulate_cost.py \\
      --state <orch_dir>/state.json \\
      --task-id task_3 \\
      --role implementer \\
      --model opus \\
      --usage-json '{"input_tokens": 1234, "output_tokens": 567,
                     "cached_read_tokens": 800, "cached_write_tokens": 0}'

`<orch_dir>` = ~/.claude/orchestrator/<RUN_ID>/ (sibling of worktree under
~/.claude/, NOT nested inside it).

Alternatively pass --usage-file <path> with the same JSON shape, useful when
parsing a headless `claude -p --output-format stream-json` stdout file (caller
extracts the final `{"type":"result","usage":{...}}` line and writes its
`usage` block to the file).

Behavior:
- Unknown model → recorded with model="unknown", cost_usd=0.0. Not a failure.
- Missing usage keys default to 0.
- state.json write failure raises (caller handles per state-write guardrail).
- by_task key is `<active_plan>::<task_id>::<role>` so implementer / reviewer /
  verifier each get their own entry under the same task. Re-dispatches of the
  SAME role for the same task (retries) overwrite — the by_role / by_model /
  totals aggregations INCREMENT in all cases so cumulative spend is correct.

Exit codes:
- 0  success (cost printed to stdout as JSON)
- 1  argparse / IO / JSON parse failure (stderr message)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import tempfile
from pathlib import Path

try:
    from price_table import compute_cost  # type: ignore
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from price_table import compute_cost  # type: ignore


USAGE_FIELDS = ("input_tokens", "output_tokens", "cached_read_tokens", "cached_write_tokens")
VALID_ROLES = {"implementer", "reviewer", "verifier", "plan_reviewer", "docs_updater"}


def _utc_now_iso() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_aggregate() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
        "cost_usd": 0.0,
        "dispatches": 0,
    }


def _normalize_usage(raw: dict) -> dict:
    return {k: int(raw.get(k, 0) or 0) for k in USAGE_FIELDS}


def _resolve_active_plan_key(state: dict) -> str:
    if "plan_chain" in state and state["plan_chain"]:
        return str(state.get("active_plan", 0))
    ap = state.get("active_plan")
    if isinstance(ap, str):
        return ap
    return "plan1"


def _increment(agg: dict, usage: dict, cost: float) -> None:
    for k in USAGE_FIELDS:
        agg[k] = int(agg.get(k, 0)) + int(usage.get(k, 0))
    agg["cost_usd"] = float(agg.get("cost_usd", 0.0)) + float(cost)
    agg["dispatches"] = int(agg.get("dispatches", 0)) + 1


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=str(path.parent), prefix=path.name + ".", suffix=".tmp",
        delete=False, encoding="utf-8",
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp.flush()
        import os
        os.fsync(tmp.fileno())
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        try:
            Path(tmp.name).unlink()
        except OSError:
            pass
        raise


def accumulate(
    state_path: Path,
    task_id: str,
    role: str,
    model: str,
    usage: dict,
) -> dict:
    usage = _normalize_usage(usage)
    cost = compute_cost(model, usage) if model != "unknown" else 0.0

    # Lock state.json for atomic R-M-W
    lock = open(state_path, "r+", encoding="utf-8")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        state = json.load(lock)

        ledger = state.setdefault("cost_ledger", {
            "by_task": {}, "by_role": {}, "by_model": {}, "totals": _empty_aggregate(),
        })
        for sect in ("by_task", "by_role", "by_model"):
            ledger.setdefault(sect, {})
        ledger.setdefault("totals", _empty_aggregate())

        active_key = _resolve_active_plan_key(state)
        key = f"{active_key}::{task_id}::{role}"
        entry = {
            **usage,
            "cost_usd": float(cost),
            "model": model,
            "role": role,
            "dispatched_at": _utc_now_iso(),
        }
        ledger["by_task"][key] = entry  # role-specific; same-role retries overwrite

        role_agg = ledger["by_role"].setdefault(role, _empty_aggregate())
        _increment(role_agg, usage, cost)
        model_agg = ledger["by_model"].setdefault(model, _empty_aggregate())
        _increment(model_agg, usage, cost)
        _increment(ledger["totals"], usage, cost)

        _atomic_write_json(state_path, state)
        return entry
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True, help="path to state.json")
    ap.add_argument("--task-id", required=True, help="e.g. task_3")
    ap.add_argument("--role", required=True, choices=sorted(VALID_ROLES))
    ap.add_argument("--model", required=True, help="opus|sonnet|haiku|claude-...|unknown")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--usage-json", help="inline JSON string with usage fields")
    g.add_argument("--usage-file", help="path to file containing usage JSON")
    args = ap.parse_args(argv)

    state_path = Path(args.state)
    if not state_path.is_file():
        print(f"state.json not found at {state_path}", file=sys.stderr)
        return 1

    raw = args.usage_json if args.usage_json else Path(args.usage_file).read_text(encoding="utf-8")
    try:
        usage = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"usage JSON parse failed: {exc}", file=sys.stderr)
        return 1
    if not isinstance(usage, dict):
        print("usage must be a JSON object", file=sys.stderr)
        return 1

    try:
        entry = accumulate(state_path, args.task_id, args.role, args.model, usage)
    except OSError as exc:
        print(f"state.json write failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(entry, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
