#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_spec_manifest import build_manifest
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "spec.md"; path.write_text("# A\nbody\n## B\ntext\n", encoding="utf-8")
        data = build_manifest(path)
    checks = {"schema_v3": data.get("schema_version") == "3", "stable_sections": data.get("section_order") == ["S1", "S1.1"], "metadata": all(all(key in item for key in ("title", "level", "line_start", "line_end", "chars", "sha256")) for item in data["sections"].values()), "explicit_mapping_slot": data.get("task_to_sections") == {}, "no_fallback_policy": "fallback_policy" not in data}
    payload = {"passed": all(checks.values()), "checks": checks, "failures": [key for key, value in checks.items() if not value]}; print(json.dumps(payload, indent=2)); return 0 if payload["passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
