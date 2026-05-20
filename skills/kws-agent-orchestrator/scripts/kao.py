#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from kao.invocation import main


if __name__ == "__main__":
    raise SystemExit(main())
