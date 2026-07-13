#!/usr/bin/env bash
# Deterministic, network-free schema-4 verification.

set -euo pipefail
umask 077

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON_BIN="${CPE_EVAL_PYTHON:-$(command -v python3)}"
JOBS="${CPE_EVAL_JOBS:-7}"
CASE_TIMEOUT="${CPE_EVAL_CASE_TIMEOUT:-12}"
TERM_GRACE="${CPE_EVAL_TERM_GRACE:-0.5}"

checks=(
  check_lean_contracts.py
  check_lean_mapping.py
  check_lean_queue.py
  check_lean_final.py
  check_lean_recovery.py
  check_lean_cli.py
)

"$PYTHON_BIN" - "$EVAL_DIR" "$JOBS" "$CASE_TIMEOUT" "$TERM_GRACE" "${checks[@]}" <<'PY'
from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

eval_dir = Path(sys.argv[1])
try:
    jobs = int(sys.argv[2])
    case_timeout = float(sys.argv[3])
    term_grace = float(sys.argv[4])
except ValueError as exc:
    raise SystemExit("eval jobs and deadlines must be numeric") from exc
if not 1 <= jobs <= 8:
    raise SystemExit("CPE_EVAL_JOBS must be between 1 and 8")
if not 0.1 <= case_timeout <= 30:
    raise SystemExit("CPE_EVAL_CASE_TIMEOUT must be between 0.1 and 30 seconds")
if not 0.05 <= term_grace <= 5:
    raise SystemExit("CPE_EVAL_TERM_GRACE must be between 0.05 and 5 seconds")
checks = sys.argv[5:]
self_test = os.environ.get("CPE_EVAL_RUNNER_SELF_TEST")
work: list[tuple[str, str]] = []
counts: dict[str, int] = {}
if self_test:
    if self_test != "hang-descendant":
        raise SystemExit("unknown CPE_EVAL_RUNNER_SELF_TEST mode")
    work.append(("synthetic", self_test))
else:
    for check in checks:
        path = eval_dir / check
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        tests: list[str] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            tests.extend(
                f"{node.name}.{member.name}"
                for member in node.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name.startswith("test_")
            )
        if not tests:
            raise SystemExit(f"no tests discovered in {check}")
        counts[check] = len(tests)
        work.extend((check, test) for test in tests)


def command_for(item: tuple[str, str]) -> list[str]:
    check, test = item
    if check != "synthetic":
        return [sys.executable, str(eval_dir / check), "-q", test]
    pid_path = os.environ.get("CPE_EVAL_SELF_TEST_PID")
    if not pid_path:
        raise RuntimeError("CPE_EVAL_SELF_TEST_PID is required")
    descendant = (
        "import os,signal,time,pathlib;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"pathlib.Path({pid_path!r}).write_text(str(os.getpid()),encoding='utf-8');"
        "time.sleep(60)"
    )
    parent = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]);"
        "time.sleep(60)"
    )
    return [sys.executable, "-c", parent]


def kill_group(process: subprocess.Popen[str], sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def run_test(
    item: tuple[str, str],
) -> tuple[tuple[str, str], int, str, str, bool]:
    process = subprocess.Popen(
        command_for(item),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=case_timeout)
        return item, process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        kill_group(process, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=term_grace)
        except subprocess.TimeoutExpired:
            stdout = stderr = ""
        kill_group(process, signal.SIGKILL)
        final_stdout, final_stderr = process.communicate()
        return (
            item,
            process.returncode if process.returncode is not None else -signal.SIGKILL,
            final_stdout or stdout,
            final_stderr or stderr,
            True,
        )


failures: list[tuple[tuple[str, str], int, str, str, bool]] = []
completed_counts = {check: 0 for check in checks}
with ThreadPoolExecutor(max_workers=jobs) as pool:
    futures = [pool.submit(run_test, item) for item in work]
    for future in as_completed(futures):
        item, returncode, stdout, stderr, timed_out = future.result()
        if item[0] in completed_counts:
            completed_counts[item[0]] += 1
        if timed_out or returncode != 0:
            failures.append((item, returncode, stdout, stderr, timed_out))

if failures:
    for (check, test), _returncode, stdout, stderr, timed_out in sorted(
        failures, key=lambda failure: failure[0]
    ):
        label = "TIMEOUT" if timed_out else "FAIL"
        print(f"{label} {check}::{test}", file=sys.stderr)
        if stdout:
            print(stdout.rstrip(), file=sys.stderr)
        if stderr:
            print(stderr.rstrip(), file=sys.stderr)
    raise SystemExit(f"{len(failures)} lean eval test(s) failed")

for check in checks:
    if completed_counts[check] != counts[check]:
        raise SystemExit(f"incomplete test execution for {check}")
    print(f"PASS {check} ({counts[check]} tests)")
print("6 passed")
PY
