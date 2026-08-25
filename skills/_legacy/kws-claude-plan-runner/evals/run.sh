#!/usr/bin/env bash
set -euo pipefail

PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest discover -s evals -p 'test_*.py' -v
"$PYTHON_313" -m py_compile scripts/runner.py scripts/plan_runner/*.py evals/*.py
bash -n evals/run.sh
bash -n scripts/runner
