#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_task_packet
def main() -> int:
    manifest = {"sections": {"S1": {"line_start": 1, "line_end": 1}}, "task_to_sections": {}}
    checks = {"explicit_refs_exact": build_task_packet.resolve_sections({"id": "task_1", "spec_refs": ["S1"]}, manifest)[0] == ["S1"]}
    try: build_task_packet.resolve_sections({"id": "task_2"}, manifest)
    except SystemExit as exc: checks["missing_mapping_blocks"] = exc.code == 1
    else: checks["missing_mapping_blocks"] = False
    payload = {"passed": all(checks.values()), "checks": checks, "failures": [key for key, value in checks.items() if not value]}; print(json.dumps(payload, indent=2)); return 0 if payload["passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
