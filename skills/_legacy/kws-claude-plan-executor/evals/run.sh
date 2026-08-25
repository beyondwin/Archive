#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/check_units.py"
echo "PASS check_units.py"
python3 "$(dirname "$0")/check_gates.py"
echo "PASS check_gates.py"
python3 "$(dirname "$0")/check_cli.py"
echo "PASS check_cli.py"
echo "3 suites passed"
