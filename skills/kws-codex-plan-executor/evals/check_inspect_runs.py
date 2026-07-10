#!/usr/bin/env python3
from __future__ import annotations
import tempfile
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.inspection import inspect_run, inspect_recent, _cost
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); run = root / "orchestrator" / "r"; run.mkdir(parents=True); (run / "run_manifest.json").write_text('{"schema_version":"2.27.0"}\n')
        assert inspect_run(run)["classification"] == "unsupported_schema"
        assert inspect_recent(root, 5)["unsupported_schema_count"] == 1
        pricing = root / "pricing.json"
        pricing.write_text(json.dumps({"models": {
            "gpt-5.6-sol": {"short_context": {"input": 10, "cached_input": 1, "output": 20}},
            "gpt-5.6-terra": {"short_context": {"input": 1, "cached_input": 0.1, "output": 2}},
        }}), encoding="utf-8")
        manifest = {"pricing_snapshot": {"ref": str(pricing)}}
        usage = {"input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 0}
        core = _cost([{"usage": usage, "attestation": {"actual_model": "gpt-5.6-sol"}}], manifest)
        terra = _cost([{"usage": usage, "attestation": {"actual_model": "gpt-5.6-terra"}}], manifest)
        assert terra["short_context_cost_usd"] < core["short_context_cost_usd"]
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
