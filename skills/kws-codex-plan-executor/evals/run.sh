#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m unittest -v \
  evals.test_state \
  evals.test_git \
  evals.test_controller \
  evals.test_runtime \
  evals.test_cli \
  evals.test_live_canary
python3 evals/check_architecture.py
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
