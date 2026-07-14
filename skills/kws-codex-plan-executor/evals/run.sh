#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/check_runner.py"
echo "PASS check_runner.py"
python3 "$(dirname "$0")/check_cli.py"
echo "PASS check_cli.py"
echo "2 suites passed"
