#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/check_units.py"
echo "PASS check_units.py"
echo "1 suite passed"
