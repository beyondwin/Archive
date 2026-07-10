#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile, subprocess
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.worker import Worker, WorkerRequest
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.model_policy import CORE_ROUTE
from cpe_runtime.manifest import create_manifest, write_manifest
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        plan = root / "plan.md"; pricing = root / "pricing.json"
        plan.write_text("# plan\n", encoding="utf-8")
        pricing.write_text("{}\n", encoding="utf-8")
        run_dir = root / "run"; worktree = root / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
        task_graph = [{"id": "T1", "acceptance_command": "true"}, {"id": "T2", "acceptance_command": "true"}]
        manifest = create_manifest("x", "interactive", root, worktree, plan, None, task_graph, pricing)
        write_manifest(run_dir / "run_manifest.json", manifest)
        def provider(request, argv):
            assert argv[argv.index("--model") + 1] == CORE_ROUTE.model
            return {"status": "completed", "summary": request.attempt_id, "changed_files": [], "findings": [], "evidence_refs": [], "missing_evidence": [], "verification": [], "_provider_metadata": {"model": CORE_ROUTE.model, "reasoning": CORE_ROUTE.reasoning, "trusted_source": "fixture"}}
        worker = Worker(provider=provider)
        result = run_tasks(task_graph, worker, run_dir)
        assert result["completed"] == ["T1", "T2"]
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
