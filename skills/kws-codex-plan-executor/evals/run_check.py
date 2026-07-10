#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command is required after --")
    started = time.monotonic()
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        returncode = result.returncode
        raw_output = result.stdout or b""
    except OSError as error:
        returncode = 127
        raw_output = f"{type(error).__name__}: {error}".encode("utf-8", errors="replace")
    output = raw_output.decode("utf-8", errors="replace").strip()
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    row = {
        "name": args.name,
        "argv": command,
        "duration_seconds": round(time.monotonic() - started, 3),
        "status": "passed" if returncode == 0 else "failed",
        "returncode": returncode,
        "failure_output": "" if returncode == 0 else output[-8000:],
    }
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False))
    if returncode:
        print(output)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
