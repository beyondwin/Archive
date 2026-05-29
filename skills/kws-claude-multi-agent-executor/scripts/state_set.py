#!/usr/bin/env python3
"""Set a field in state.json, resolving the active-plan tree, under an flock.

One helper for every Phase 1 / Transition / Phase 2 state write. The orchestrator
supplies a dot-path field and a value mode; this script owns active-tree
resolution + the flock-guarded read-modify-write + atomic rename + readback. It
replaces the inline `jq` + Write-then-readback boilerplate that SKILL.md repeated
dozens of times (see D001).

Usage:
    python3 state_set.py --state <orch_dir>/state.json \\
      --field "tasks.task_3.timing.completed" \\
      ( --value <json> | --now | --inc <n> | --append-json <json>
        | --setdefault-json <json> ) \\
      [--plan-scope active|run]

`<orch_dir>` = ~/.claude/orchestrator/<RUN_ID>/ (sibling of the worktree under
~/.claude/, NOT nested inside it).

Field path:
- `--field` is a dot-path *relative to the active tree* by default.
- A leading `state.` segment, or `--plan-scope run`, forces a top-level/run-level
  write (for fields like `timestamps.completed_at`, `cost_ledger`, `mode`).
- Missing intermediate dict segments are auto-created as objects.
- A numeric segment indexes an EXISTING list element (e.g.
  `plan_chain.1.baseline` writes into a non-active plan during the Cross-Plan
  Trigger). List elements are never auto-created; an out-of-range or
  non-integer index raises.
- An existing non-container intermediate is never overwritten: descending past
  a scalar raises rather than clobbering it (this guards against the D001 bug
  where `plan_chain.0.status` collapsed the whole list into a dict).

Active-tree resolution (mirrors the SKILL.md `<active>` table):
- `state.plan_chain` present              → state["plan_chain"][active_plan]
- else `active_plan == "plan2"` (legacy)  → state["plan2_state"]
- else (single-plan / plan1)              → top-level state

Value modes (mutually exclusive, one required):
- `--value <json>`          set the field to the parsed JSON value.
- `--now`                   set the field to an ISO-8601 UTC timestamp string.
- `--inc <n>`               numeric increment (missing field treated as 0).
- `--append-json <json>`    append the parsed value to a list (missing → []).
- `--setdefault-json <json>` write only if the field is currently absent.

Concurrency / durability:
- Exclusive flock on `<state>.lock` (a stable sibling inode, so concurrent
  writers serialize even across the atomic rename that swaps state.json's inode).
- Write to a temp file in the same dir, fsync, atomic rename over state.json.
- Read the file back and re-navigate to the field to confirm the write landed;
  mismatch → non-zero exit (the state-write hard-halt guardrail).

Exit codes:
- 0  success (the resulting field value printed to stdout as JSON)
- 1  argparse / IO / JSON parse / resolution / readback failure (stderr message)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path


def _utc_now_iso() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=str(path.parent), prefix=path.name + ".", suffix=".tmp",
        delete=False, encoding="utf-8",
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        try:
            Path(tmp.name).unlink()
        except OSError:
            pass
        raise


def resolve_active_tree(state: dict, scope: str, force_run: bool) -> dict:
    """Return the dict (by reference, within `state`) that the field path is
    relative to. `scope == "run"` or a leading `state.` forces top-level."""
    if scope == "run" or force_run:
        return state
    if state.get("plan_chain"):
        idx = state.get("active_plan", 0)
        if not isinstance(idx, int):
            raise ValueError(
                f"plan_chain present but active_plan is not an int index: {idx!r}"
            )
        chain = state["plan_chain"]
        if idx < 0 or idx >= len(chain):
            raise ValueError(
                f"active_plan index {idx} out of range for plan_chain (len {len(chain)})"
            )
        return chain[idx]
    if state.get("active_plan") == "plan2":  # legacy v2.12 two-plan (removed post-D004)
        return state.setdefault("plan2_state", {})
    return state


def _is_index(seg: str) -> bool:
    return seg.lstrip("-").isdigit()


def _list_index(container: list, seg: str) -> int:
    """Validate `seg` as an in-range index into `container`. List elements are
    never auto-created — a dotted index only navigates an element that exists."""
    if not _is_index(seg):
        raise ValueError(f"cannot index list with non-integer segment {seg!r}")
    idx = int(seg)
    if idx < 0 or idx >= len(container):
        raise ValueError(f"list index {idx} out of range (len {len(container)})")
    return idx


def _step(cur, seg: str, *, create: bool):
    """Descend one path segment into `cur`.

    Lists are indexed by an integer segment; dict keys are looked up by name and,
    when `create`, a missing key auto-vivifies as an empty object. An EXISTING
    value is never replaced here: descending past a scalar raises instead of
    clobbering it (the bug that collapsed `plan_chain` into a dict — see D001)."""
    if isinstance(cur, list):
        return cur[_list_index(cur, seg)]
    if isinstance(cur, dict):
        if seg in cur:
            return cur[seg]
        if create:
            nxt: dict = {}
            cur[seg] = nxt
            return nxt
        raise KeyError(seg)
    raise ValueError(
        f"cannot descend into non-container at segment {seg!r} "
        f"(found {type(cur).__name__}); refusing to overwrite existing data"
    )


def _navigate_create(tree: dict, segments: list[str]):
    """Walk/create intermediate segments, returning the container (dict or list)
    that holds the final key."""
    cur = tree
    for seg in segments[:-1]:
        cur = _step(cur, seg, create=True)
    return cur


def apply_op(container, key: str, op: str, payload) -> None:
    if isinstance(container, list):
        idx = _list_index(container, key)
        if op == "value":
            container[idx] = payload
        elif op == "now":
            container[idx] = _utc_now_iso()
        elif op == "inc":
            container[idx] = (container[idx] or 0) + payload
        elif op == "append":
            lst = container[idx]
            if not isinstance(lst, list):
                raise ValueError(f"--append target at index {idx} is not a list")
            lst.append(payload)
        elif op == "setdefault":
            pass  # the bounds-checked element already exists
        else:  # pragma: no cover - guarded by argparse
            raise ValueError(f"unknown op {op}")
        return
    if op == "value":
        container[key] = payload
    elif op == "now":
        container[key] = _utc_now_iso()
    elif op == "inc":
        cur = container.get(key, 0) or 0
        container[key] = cur + payload
    elif op == "append":
        lst = container.get(key)
        if not isinstance(lst, list):
            lst = []
        lst.append(payload)
        container[key] = lst
    elif op == "setdefault":
        container.setdefault(key, payload)
    else:  # pragma: no cover - guarded by argparse
        raise ValueError(f"unknown op {op}")


def _read_field(tree: dict, segments: list[str]):
    cur = tree
    for seg in segments:
        try:
            cur = _step(cur, seg, create=False)
        except (ValueError, IndexError) as exc:
            raise KeyError(seg) from exc
    return cur


def state_set(
    state_path: Path,
    field: str,
    op: str,
    payload,
    plan_scope: str,
):
    # A leading `state.` segment is a run-level escape hatch.
    force_run = False
    if field.startswith("state."):
        force_run = True
        field = field[len("state."):]
    segments = field.split(".")
    if not segments or any(s == "" for s in segments):
        raise ValueError(f"invalid --field path: {field!r}")

    lock_path = state_path.with_name(state_path.name + ".lock")
    lock = open(lock_path, "w", encoding="utf-8")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)

        tree = resolve_active_tree(state, plan_scope, force_run)
        container = _navigate_create(tree, segments)
        apply_op(container, segments[-1], op, payload)

        _atomic_write_json(state_path, state)

        # Readback: re-parse from disk and re-navigate.
        with open(state_path, "r", encoding="utf-8") as fh:
            reread = json.load(fh)
        rtree = resolve_active_tree(reread, plan_scope, force_run)
        try:
            value = _read_field(rtree, segments)
        except KeyError as exc:
            raise RuntimeError(
                f"readback failed: field {field!r} absent after write (missing {exc})"
            )
        return value
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True, help="path to state.json")
    ap.add_argument("--field", required=True, help="dot-path relative to active tree")
    ap.add_argument(
        "--plan-scope", choices=("active", "run"), default="active",
        help="active (default) resolves the active-plan tree; run forces top-level",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--value", help="raw JSON value to set")
    g.add_argument("--now", action="store_true", help="set ISO-8601 UTC timestamp")
    g.add_argument("--inc", help="numeric increment (int or float)")
    g.add_argument("--append-json", help="append parsed JSON value to a list")
    g.add_argument("--setdefault-json", help="write only if field is absent")
    args = ap.parse_args(argv)

    state_path = Path(args.state)
    if not state_path.is_file():
        print(f"state.json not found at {state_path}", file=sys.stderr)
        return 1

    op: str
    payload = None
    try:
        if args.value is not None:
            op, payload = "value", json.loads(args.value)
        elif args.now:
            op = "now"
        elif args.inc is not None:
            op = "inc"
            payload = json.loads(args.inc)
            if not isinstance(payload, (int, float)) or isinstance(payload, bool):
                print("--inc must be a JSON number", file=sys.stderr)
                return 1
        elif args.append_json is not None:
            op, payload = "append", json.loads(args.append_json)
        else:  # setdefault-json
            op, payload = "setdefault", json.loads(args.setdefault_json)
    except json.JSONDecodeError as exc:
        print(f"value JSON parse failed: {exc}", file=sys.stderr)
        return 1

    try:
        value = state_set(state_path, args.field, op, payload, args.plan_scope)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"state_set failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
