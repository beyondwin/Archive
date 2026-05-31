#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_token(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("token counts must be non-negative")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Append optional cache token observation to CPE state.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--source", default="codex-metadata")
    parser.add_argument("--input-tokens")
    parser.add_argument("--cached-read-tokens")
    parser.add_argument("--cached-write-tokens")
    parser.add_argument("--output-tokens")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    observation = {
        "observed_at": now_iso(),
        "source": args.source,
        "unit": args.unit,
        "mode": args.mode,
        "model": args.model,
        "input_tokens": parse_token(args.input_tokens),
        "cached_read_tokens": parse_token(args.cached_read_tokens),
        "cached_write_tokens": parse_token(args.cached_write_tokens),
        "output_tokens": parse_token(args.output_tokens),
        "notes": args.notes,
    }
    state.setdefault("cache_observations", []).append(observation)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(observation, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
