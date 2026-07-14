#!/usr/bin/env bash
set -euo pipefail

for check in \
  check_lean_contracts.py \
  check_lean_mapping.py \
  check_lean_queue.py \
  check_lean_final.py \
  check_lean_recovery.py \
  check_lean_cli.py
do
  python3 "$(dirname "$0")/$check"
  echo "PASS $check"
done

echo "6 passed"
