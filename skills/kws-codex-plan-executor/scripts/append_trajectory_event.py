#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def redact_home(value: str) -> str:
    home = str(Path.home())
    redacted = value.replace(home, "~")
    return re.sub(r"/Users/[^/\s]+", "~", redacted)


def next_seq(path: Path) -> int:
    if not path.is_file():
        return 1
    seq = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            seq = max(seq, int(json.loads(line).get("seq", 0)))
        except Exception:
            continue
    return seq + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a compact CPE trajectory event.")
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--state-ref", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--evidence-ref", action="append", default=[])
    parser.add_argument("--context-status", default="unknown")
    args = parser.parse_args()
    path = Path(args.trajectory)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": "1",
        "seq": next_seq(path),
        "event": args.event,
        "at": now_iso(),
        "task_id": args.task_id,
        "state_ref": redact_home(args.state_ref),
        "summary": redact_home(args.summary),
        "evidence_refs": [redact_home(item) for item in args.evidence_ref],
        "context_budget": {"status": args.context_status},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
