#!/usr/bin/env python3
"""Build the Implementer `{context_slice}` block from state.json (v2.29 — I5).

Ports the in-prose derivation in `references/phases/phase-1-task-cycle.md`
(Step 1, the ~40-line `{context_slice}` substitution block) into a helper so the
orchestrator injects a prepared slice instead of executing the assembly logic in
its own context every task (axis A — context reduction). Follows the
`build_spec_manifest.py` call convention: stdlib-only, JSON/text to stdout, exit
2 on a missing state file.

The slice is assembled from:
- `<active>.task_summaries[<dep>].for_next_tasks` for each upstream dep,
- `<active>.global_constraints.shared_files` entries that intersect this task's
  Files block,
- `<active>.global_constraints.text` (free-form global constraints).

`--deps` (upstream task ids) and `--files` (this task's Files block) are small
lists the orchestrator already holds from the Phase 0 dependency graph and the
plan's `**Files:**` block; they are passed in rather than re-derived. Everything
else is read from state by `--task` / `--plan-index`.

usage:
    build_context_slice.py <state.json> --task <task_id> [--plan-index N]
                           [--deps <json-array|csv>] [--files <json-array|csv>]
stdout: the prepared context_slice text (inserted verbatim at `{context_slice}`).
exit:   0 ok / 2 state file not found / 1 parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _canon(tid) -> str:
    """Normalize a task id to the canonical `task_<N>` key form (accepts a bare
    int `2`, a numeric string `"2"`, or an already-canonical `"task_2"`)."""
    s = str(tid)
    return s if s.startswith("task_") else "task_" + s


def _resolve_active(state: dict, plan_index: int | None):
    """Return (active_tree, active_plan_index_label)."""
    if plan_index is not None:
        chain = state.get("plan_chain")
        if not isinstance(chain, list) or plan_index < 0 or plan_index >= len(chain):
            raise ValueError(f"--plan-index {plan_index} out of range for plan_chain")
        return chain[plan_index], plan_index
    if state.get("plan_chain"):
        idx = state.get("active_plan", 0)
        return state["plan_chain"][idx], idx
    return state, "single"


def build_slice_from_state(
    state: dict,
    task: str,  # noqa: ARG001 - kept for call-site symmetry / future RECURRING use
    plan_index: int | None,
    deps: list,
    files_this_task: list,
) -> str:
    active, active_plan_index = _resolve_active(state, plan_index)
    summaries = active.get("task_summaries") or {}
    gc = active.get("global_constraints") or {}
    shared = gc.get("shared_files") or {}

    canon_deps = [_canon(d) for d in deps]

    lines = ["active_plan_index: " + str(active_plan_index)]
    lines.append("deps_for_this_task: " + json.dumps(canon_deps))

    if canon_deps:
        lines.append("task_summaries:")
        for key in canon_deps:
            summary = (summaries.get(key) or {}).get("for_next_tasks", "") or ""
            lines.append("  " + key + ":")
            lines.append("    for_next_tasks: |")
            for line in (summary.splitlines() or [""]):
                lines.append("      " + line)
    else:
        lines.append("task_summaries: {}  # no upstream deps")

    intersecting = {f: shared[f] for f in shared if f in files_this_task}
    if intersecting:
        lines.append("shared_files:")
        for f, other_ids in intersecting.items():
            lines.append("  " + f + ": " + json.dumps(other_ids))
            for other_id in other_ids:
                other_summary = (summaries.get(other_id) or {}).get("for_next_tasks", "") or ""
                if other_summary:
                    lines.append("  # " + other_id + ".for_next_tasks: "
                                 + other_summary.splitlines()[0][:140])
    else:
        lines.append("shared_files: {}  # none of files_to_touch are shared with other tasks")

    gc_text = gc.get("text", "") or ""
    if gc_text:
        lines.append("global_constraints: |")
        for line in gc_text.splitlines():
            lines.append("  " + line)

    return "\n".join(lines)


def _parse_list(raw: str | None) -> list:
    """Accept a JSON array or a comma-separated string; empty/None → []."""
    if not raw:
        return []
    raw = raw.strip()
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return val
        return [val]
    except (ValueError, TypeError):
        return [tok.strip() for tok in raw.split(",") if tok.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("state_path", help="path to <orch_dir>/state.json")
    ap.add_argument("--task", required=True, help="canonical task id, e.g. task_3")
    ap.add_argument("--plan-index", type=int, default=None,
                    help="multi-plan index into plan_chain (default: active_plan)")
    ap.add_argument("--deps", default=None, help="upstream task ids (JSON array or CSV)")
    ap.add_argument("--files", default=None, help="this task's Files block (JSON array or CSV)")
    args = ap.parse_args(argv)

    path = Path(args.state_path)
    if not path.is_file():
        print(f"error: state file not found: {path}", file=sys.stderr)
        return 2
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        text = build_slice_from_state(
            state, args.task, args.plan_index,
            _parse_list(args.deps), _parse_list(args.files),
        )
    except json.JSONDecodeError as exc:
        print(f"error: state JSON parse failed: {exc}", file=sys.stderr)
        return 1
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
