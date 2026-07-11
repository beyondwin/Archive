#!/usr/bin/env python3
"""Public-CLI subprocess checks for result schema and fail-closed exits."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from cpe_runtime.events import append_event
from cpe_runtime.kernel import Kernel, RunKernel, Transition
from cpe_runtime.manifest import create_manifest
from cpe_runtime.packets import build_packet
from cpe_runtime.public_result import PublicResult, blocked_result, failed_result


def _schema_errors(value: object, schema: dict, path: str = "$") -> list[str]:
    """Interpret the tracked schema subset without an undeclared dependency."""

    errors: list[str] = []
    expected = schema.get("type")
    allowed = expected if isinstance(expected, list) else [expected] if expected else []
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
        "boolean": isinstance(value, bool),
    }
    if allowed and not any(type_ok.get(str(item), False) for item in allowed):
        return [f"{path}:type"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}:const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}:enum")
    if isinstance(value, str) and len(value) < int(schema.get("minLength", 0)):
        errors.append(f"{path}:minLength")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_schema_errors(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, dict):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"{path}.{key}:required")
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}.{key}:additional" for key in value.keys() - properties.keys())
        for key, child in properties.items():
            if key in value and isinstance(child, dict):
                errors.extend(_schema_errors(value[key], child, f"{path}.{key}"))
    for clause in schema.get("allOf") or []:
        condition = clause.get("if") if isinstance(clause, dict) else None
        then = clause.get("then") if isinstance(clause, dict) else None
        if isinstance(condition, dict) and isinstance(then, dict) and not _schema_errors(value, condition, path):
            errors.extend(_schema_errors(value, then, path))
    return errors


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE)
    return result.stdout.strip()


def _repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "cpe@example.invalid")
    _git(repo, "config", "user.name", "CPE Fixture")
    (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "baseline.txt")
    _git(repo, "commit", "-qm", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def _initialize(root: Path, run_id: str) -> tuple[Path, Path, Path]:
    repo, head = _repo(root)
    worktree = root / "worktree"
    _git(repo, "worktree", "add", "-q", "-b", f"codex/{run_id}", str(worktree), head)
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# Plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    task = {
        "id": "T1",
        "title": "fixture",
        "dependencies": [],
        "file_claims": ["owned.txt"],
        "acceptance_command": "true",
    }
    draft = build_packet(SimpleNamespace(sources=(), spec_manifest=None), task)
    run_dir = root / "codex" / "orchestrator" / run_id
    manifest = create_manifest(run_id, "headless", repo, worktree, plan, None, [task], pricing, source_head=head)
    RunKernel.initialize(run_dir, manifest, [draft])
    return repo, worktree, run_dir


def _public(codex_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CODEX_HOME": str(codex_home)}
    return subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "cpe.py"), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _fake_codex(bin_dir: Path) -> None:
    bin_dir.mkdir()
    path = bin_dir / "codex"
    path.write_text(
        """#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
if '--version' in args:
    print('codex-cli 0.114.0')
    raise SystemExit(0)
prompt = json.loads(sys.stdin.read())
instruction = prompt.get('instruction', '')
revision = int(prompt.get('worktree_revision', 0))
role = 'implementation' if instruction.startswith('Implement task') else 'repair' if instruction.startswith('Repair ') else 'task_review' if instruction.startswith('Review task') else 'verification' if instruction.startswith('Verify ') else 'final_review'
worktree = pathlib.Path(args[args.index('-C') + 1])
changed = []
if role in {'implementation', 'repair'}:
    target = worktree / 'target.txt'
    target.write_text(target.read_text() + 'implemented\\n')
    changed = ['target.txt']
verdict = None
if role in {'task_review', 'verification', 'final_review'}:
    verdict = {'status': 'passed', 'findings': [], 'missing_evidence': [], 'worktree_revision': revision}
payload = {'status':'completed','summary':role,'changed_files':changed,'findings':[],'evidence_refs':[],'missing_evidence':[],'verification':[],'verdict':verdict}
last = pathlib.Path(args[args.index('--output-last-message') + 1])
last.write_text(json.dumps(payload))
model = args[args.index('--model') + 1]
print(json.dumps({'type':'thread.started','model':model,'reasoning_effort':'high'}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'cached_input_tokens':0,'output_tokens':1,'reasoning_output_tokens':0}}))
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _success_subprocess(root: Path) -> subprocess.CompletedProcess[str]:
    repo, _ = _repo(root)
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    plan = repo / "plan.md"
    plan.write_text(
        "# Fixture Plan\n\n"
        "> REQUIRED SUB-SKILL: subagent-driven-development or executing-plans\n\n"
        "## Task 1: Implement target\n\n"
        "**Files:**\n- Modify: `target.txt`\n\n"
        "Verification:\n```bash\ntrue\n```\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "plan")
    bin_dir = root / "bin"
    _fake_codex(bin_dir)
    env = {
        **os.environ,
        "CODEX_HOME": str(root / "codex"),
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    }
    return subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts" / "cpe.py"),
            "run",
            "--plan",
            str(plan),
            "--workspace",
            str(repo),
            "--mode",
            "headless",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _initialization_failure_subprocess(root: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    repo, _ = _repo(root)
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    plan = repo / "plan.md"
    plan.write_text(
        "# Fixture Plan\n\n"
        "> REQUIRED SUB-SKILL: subagent-driven-development or executing-plans\n\n"
        "## Task 1: Implement target\n\n"
        "**Files:**\n- Modify: `target.txt`\n\n"
        "Verification:\n```bash\ntrue\n```\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "plan")
    home = root / "codex"
    home.mkdir()
    (home / "orchestrator").write_text("not a directory\n", encoding="utf-8")
    result = _public(home, "run", "--plan", str(plan), "--workspace", str(repo), "--mode", "headless")
    return result, repo


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    schema = json.loads((SKILL / "templates" / "headless-output-schema.json").read_text(encoding="utf-8"))
    checks: dict[str, bool] = {}
    failures: list[str] = []

    samples = [
        PublicResult("success", "run", "/state.json", "done", next_action="review"),
        blocked_result("bad plan", category="preflight"),
        failed_result("bad state", category="state_integrity"),
    ]
    checks["public_result_schema_matrix"] = all(not _schema_errors(item.as_dict(), schema) for item in samples)
    checks["public_result_exit_matrix"] = [item.exit_code() for item in samples] == [0, 1, 2]

    with tempfile.TemporaryDirectory() as raw:
        success = _success_subprocess(Path(raw))
        success_payload = _payload(success)
        checks["success_subprocess_validated"] = (
            success.returncode == 0
            and success_payload.get("status") == "success"
            and success_payload.get("verification") == [{"command": "validate_completion", "status": "passed"}]
            and not _schema_errors(success_payload, schema)
            and "Traceback" not in success.stderr
        )

    with tempfile.TemporaryDirectory() as raw:
        failed_init, repo = _initialization_failure_subprocess(Path(raw))
        payload = _payload(failed_init)
        worktrees = _git(repo, "worktree", "list", "--porcelain")
        branches = _git(repo, "branch", "--format=%(refname:short)")
        checks["unpublished_initialization_cleanup"] = (
            failed_init.returncode == 2
            and payload.get("status") == "failed"
            and payload.get("run_id")
            and not _schema_errors(payload, schema)
            and worktrees.count("worktree ") == 1
            and "codex/" not in branches
            and "Traceback" not in failed_init.stderr
        )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        missing = _public(root / "empty-home", "run", "--plan", str(root / "missing.md"), "--workspace", str(root))
        missing_payload = _payload(missing)
        checks["preflight_subprocess_blocked"] = (
            missing.returncode == 1
            and missing_payload.get("status") == "blocked"
            and not _schema_errors(missing_payload, schema)
            and "Traceback" not in missing.stderr
        )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _, _, run_dir = _initialize(root, "tampered")
        packet = run_dir / "artifacts" / "task-packets" / "T1.json"
        packet.write_bytes(packet.read_bytes() + b" ")
        tampered = _public(root / "codex", "resume", "--run-id", "tampered")
        payload = _payload(tampered)
        checks["packet_tamper_subprocess_failed"] = (
            tampered.returncode == 2
            and payload.get("status") == "failed"
            and not _schema_errors(payload, schema)
            and "Traceback" not in tampered.stderr
        )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, worktree, run_dir = _initialize(root, "blocked-resume")
        Kernel(run_dir).transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        _git(repo, "worktree", "remove", "--force", str(worktree))
        blocked = _public(root / "codex", "resume", "--run-id", "blocked-resume")
        payload = _payload(blocked)
        checks["missing_worktree_resume_blocked"] = (
            blocked.returncode == 1
            and payload.get("status") == "blocked"
            and not _schema_errors(payload, schema)
            and "Traceback" not in blocked.stderr
        )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _, _, run_dir = _initialize(root, "invalid-completion")
        events = run_dir / "events.jsonl"
        append_event(events, {"type": "run.status_changed", "payload": {"from": "created", "to": "ready"}})
        append_event(events, {"type": "run.status_changed", "payload": {"from": "ready", "to": "running"}})
        append_event(events, {"type": "run.status_changed", "payload": {"from": "running", "to": "completed"}})
        invalid = _public(root / "codex", "resume", "--run-id", "invalid-completion")
        payload = _payload(invalid)
        checks["completion_validation_subprocess_failed"] = (
            invalid.returncode == 2
            and payload.get("status") == "failed"
            and not _schema_errors(payload, schema)
            and "Traceback" not in invalid.stderr
        )

    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
