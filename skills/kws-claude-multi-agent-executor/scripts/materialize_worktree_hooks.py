#!/usr/bin/env python3
"""Materialize + verify the four worktree safety hooks in settings.json (v2.27).

Replaces the hand-written JSON block at Phase 0 Step 2.5. The hand-write had no
merge step, so a source repo that already shipped .claude/settings.json (e.g. a
permissions allowlist) silently lost all four hooks — including the v2.26 Stop
finalization gate (run readmates-host-prep-pace-20260606-003707). This script
deep-merges instead: every existing top-level key is preserved, and the four hook
events we own are injected (winning over any repo entry under those keys, while
other repo-defined hook events survive).

v3.0 (T15 cutover): the Stop hook now invokes the deterministic kernel
(`kernel.py check-stop`) instead of the v2 `finalization-stop-gate.sh`. check-stop
exits 2 (blocking the stop) whenever outstanding work remains — a finalize-pending
all-terminal run or a lingering PENDING_BATCH batch-drain. The corrective guidance
is echoed to stderr by kernel.py so Claude Code surfaces it to the orchestrator.

Modes:
  (write)  --worktree <p> --orch-dir <p> --skill-dir <p>
           Read <worktree>/.claude/settings.json (absent -> {}), deep-merge our
           hooks, atomic-write, then self-assert (same checks as --check).
  --check  --worktree <p>
           Assert the four events are present and Stop references
           kernel.py check-stop. No write. Reused as the Phase-1 Task-1
           preflight (improvement #3).

Exit codes:
  0  success / wired
  1  assertion failure, IO error, or unparseable existing settings.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import state_set as ss  # type: ignore
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import state_set as ss  # type: ignore

REQUIRED_EVENTS = ("PreToolUse", "PostToolUse", "SubagentStop", "Stop")

_PRE_CMD = (
    "CMD=$(echo \"$CLAUDE_TOOL_INPUT\" | jq -r '.command // empty' 2>/dev/null); "
    "if [ -z \"$CMD\" ]; then CMD=\"$CLAUDE_TOOL_INPUT\"; fi; "
    "if echo \"$CMD\" | grep -qE "
    "'rm\\s+-rf\\s+/|git\\s+push\\s+--force\\s+(origin\\s+)?(main|master|trunk)"
    "|DROP\\s+(TABLE|DATABASE|SCHEMA)\\s'; "
    "then echo 'BLOCKED: dangerous command detected' >&2; exit 1; fi"
)


def build_hooks(orch_dir: str, skill_dir: str) -> dict[str, Any]:
    """The canonical four-event hooks block (matches safety-hooks.md)."""
    return {
        "PreToolUse": [{
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": _PRE_CMD}],
        }],
        "PostToolUse": [{
            "matcher": "Edit|Write",
            "hooks": [{"type": "command",
                       "command": f"{orch_dir}/hooks/scan-debug-artifacts.sh"}],
        }],
        "SubagentStop": [{
            "hooks": [{"type": "command",
                       "command": f"{orch_dir}/hooks/check-implementer-output.sh"}],
        }],
        "Stop": [{
            "hooks": [{"type": "command",
                       "command": (f"python3 {skill_dir}/scripts/kernel/kernel.py "
                                   f"check-stop --state {orch_dir}/state.json")}],
        }],
    }


def merge_settings(existing: dict[str, Any], hooks_block: dict[str, Any]) -> dict[str, Any]:
    """Preserve every existing top-level key; our four hook events win."""
    merged = dict(existing)
    prior_hooks = existing.get("hooks")
    prior_hooks = prior_hooks if isinstance(prior_hooks, dict) else {}
    merged_hooks = dict(prior_hooks)
    merged_hooks.update(hooks_block)
    merged["hooks"] = merged_hooks
    return merged


def check_problems(settings: dict[str, Any]) -> list[str]:
    """Return a list of wiring problems; empty list means correctly wired."""
    problems: list[str] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return ["settings.json has no 'hooks' object"]
    for event in REQUIRED_EVENTS:
        entries = hooks.get(event)
        if not isinstance(entries, list) or not entries:
            problems.append(f"missing or empty hook event: {event}")
    stop = hooks.get("Stop")
    if isinstance(stop, list) and stop:
        cmds = " ".join(
            h.get("command", "")
            for entry in stop
            for h in (entry.get("hooks") or [])
            if isinstance(h, dict)
        )
        if "kernel.py" not in cmds or "check-stop" not in cmds:
            problems.append("Stop hook does not reference kernel.py check-stop")
    return problems


def _settings_path(worktree: str) -> Path:
    return Path(worktree) / ".claude" / "settings.json"


def do_write(worktree: str, orch_dir: str, skill_dir: str) -> int:
    path = _settings_path(worktree)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"refusing to clobber unparseable {path}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(existing, dict):
            print(f"refusing to clobber non-object {path}", file=sys.stderr)
            return 1
    merged = merge_settings(existing, build_hooks(orch_dir, skill_dir))
    ss._atomic_write_json(path, merged)
    problems = check_problems(merged)
    if problems:
        print("post-write hook assertion failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def do_check(worktree: str) -> int:
    path = _settings_path(worktree)
    if not path.is_file():
        print(f"no settings.json at {path}", file=sys.stderr)
        return 1
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"unparseable {path}: {exc}", file=sys.stderr)
        return 1
    problems = check_problems(settings if isinstance(settings, dict) else {})
    if problems:
        print(f"worktree hooks not wired in {path}:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="assert hooks are wired; no write")
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--orch-dir")
    ap.add_argument("--skill-dir")
    args = ap.parse_args(argv)

    if args.check:
        return do_check(args.worktree)
    if not args.orch_dir or not args.skill_dir:
        ap.error("write mode requires --orch-dir and --skill-dir")
    return do_write(args.worktree, args.orch_dir, args.skill_dir)


if __name__ == "__main__":
    sys.exit(main())
