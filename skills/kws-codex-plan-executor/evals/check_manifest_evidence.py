#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.evidence import put_json, verify_ref
from cpe_runtime.manifest import create_manifest, write_manifest


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        plan, spec, pricing = (root / "plan.md", root / "spec.md", root / "pricing.json")
        for path, text in ((plan, "# plan\n"), (spec, "# spec\n"), (pricing, "{}\n")):
            path.write_text(text, encoding="utf-8")
        run_dir = root / "run"
        manifest = create_manifest("fixture-20260710-010203", "interactive", root, root / "worktree", plan, spec, [], pricing)
        assert manifest["schema_version"] == "3"
        target = run_dir / "run_manifest.json"
        write_manifest(target, manifest)
        try:
            write_manifest(target, manifest)
        except FileExistsError:
            pass
        else:
            raise AssertionError("manifest rewrite must fail")
        ref = put_json(run_dir, "verification", {"passed": True})
        assert verify_ref(run_dir, ref) == []
        (run_dir / ref.path).write_text("{}\n", encoding="utf-8")
        assert verify_ref(run_dir, ref) == ["evidence digest mismatch"]
    print('{"passed": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
