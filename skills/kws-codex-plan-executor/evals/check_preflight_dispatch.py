#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.kernel import RunKernel
from cpe_runtime.manifest import create_manifest
from cpe_runtime.packets import build_packet


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preflight_dispatch.py"


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=repo, check=True)


def create_run(
    root: Path,
    repo: Path,
    files: list[str],
    *,
    allowed: list[str] | None = None,
    dependencies: list[str] | None = None,
    risk_markers: list[str] | None = None,
) -> Path:
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# Plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    task = {
        "id": "task_0",
        "title": "Task",
        "dependencies": dependencies or [],
        "file_claims": files,
        "spec_refs": [],
        "acceptance_command": "python3 -m pytest",
        "prompt": "Implement the bounded task.",
        "risk_markers": risk_markers or [],
        "execution_contract": {
            "allowed_paths": allowed or files,
            "forbidden_paths": [".git/**", "graphify-out/**"],
            "acceptance_command": "python3 -m pytest",
        },
        "source_hashes": {"plan": hashlib.sha256(plan.read_bytes()).hexdigest(), "spec_sections": {}},
    }
    compiled = SimpleNamespace(tasks=(task,), spec_manifest=None, sources=())
    draft = build_packet(compiled, task)
    manifest = create_manifest("dispatch-fixture", "interactive", repo, repo, plan, None, [task], pricing)
    run_dir = root / "run"
    RunKernel.initialize(run_dir, manifest, [draft])
    return run_dir


def run_dispatch(repo: Path, run_dir: Path, *extra: str, write_scope: list[str] | None = None):
    output = run_dir.parent / "dispatch.json"
    command = [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--task-id", "task_0", "--repo-root", str(repo)]
    for scope in write_scope or ["docs/example.md"]:
        command.extend(["--write-scope", scope])
    command.extend(["--output", str(output), *extra])
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def fixture(files: list[str], **kwargs):
    temp = tempfile.TemporaryDirectory(prefix="cpe-dispatch-")
    root = Path(temp.name)
    repo = root / "repo"
    repo.mkdir()
    init_repo(repo)
    run_dir = create_run(root, repo, files, **kwargs)
    return temp, repo, run_dir


def main() -> int:
    checks: dict[str, bool] = {}

    temp, repo, run_dir = fixture(["docs/example.md"])
    with temp:
        result, data = run_dispatch(repo, run_dir)
        checks["verified_docs_packet_uses_local_fast_path"] = result.returncode == 0 and data.get("reason") == "adaptive_policy_local_fast_path_docs_only"

    temp, repo, run_dir = fixture(["scripts/a.py", "scripts/b.py", "evals/a.py", "evals/b.py"], allowed=["scripts/*.py", "evals/*.py"])
    with temp:
        result, data = run_dispatch(repo, run_dir, "--spawn-policy", "available", write_scope=["scripts/*.py", "evals/*.py"])
        checks["verified_complex_packet_delegates"] = result.returncode == 0 and data.get("decision") == "delegate"

    temp, repo, run_dir = fixture(["bun.lock"], risk_markers=["lockfile"])
    with temp:
        result, data = run_dispatch(repo, run_dir, write_scope=["bun.lock"])
        checks["risky_packet_blocks"] = result.returncode != 0 and data.get("decision") == "block"

    temp, repo, run_dir = fixture(["docs/example.md"])
    with temp:
        (repo / "docs").mkdir()
        (repo / "docs/example.md").write_text("dirty\n", encoding="utf-8")
        result, data = run_dispatch(repo, run_dir)
        checks["dirty_overlap_blocks"] = result.returncode != 0 and any(str(item).startswith("dirty_overlap:") for item in data.get("failed_prerequisites", []))

    temp, repo, run_dir = fixture(["docs/example.md"])
    with temp:
        packet = run_dir / "artifacts/task-packets/task_0.json"
        packet.write_bytes(b"{}\n")
        result, data = run_dispatch(repo, run_dir)
        checks["packet_mutation_blocks_before_dispatch"] = result.returncode != 0 and "packet_digest_mismatch" in data.get("failed_prerequisites", [])

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
