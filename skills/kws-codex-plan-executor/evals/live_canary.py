#!/usr/bin/env python3
"""Run one explicit real-provider CPE canary in a preserved temporary root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

SCENARIOS = (
    "sdd-multi-document",
    "session-loss",
    "legacy-adoption",
)
SKILL_ROOT = Path(__file__).resolve().parents[1]
CPE_CLI = (SKILL_ROOT / "scripts" / "cpe.py").resolve(strict=True)
MAX_OUTPUT_BYTES = 131_072
MAX_JSON_BYTES = 1_048_576
COMMAND_TIMEOUT_SECONDS = 1800


class CanaryError(RuntimeError):
    """A bounded canary contract failure."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def require(condition: object, message: str) -> None:
    if not condition:
        raise CanaryError(message)


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run one list-argv command and retain only bounded output."""
    require(bool(argv) and all(isinstance(value, str) for value in argv), "invalid argv")
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CanaryError("bounded command timed out") from exc
    require(
        len(result.stdout) <= MAX_OUTPUT_BYTES
        and len(result.stderr) <= MAX_OUTPUT_BYTES,
        "bounded command output exceeded limit",
    )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def parse_last_json(output: bytes) -> dict[str, object]:
    """Return the final JSON object without retaining provider output."""
    require(len(output) <= MAX_OUTPUT_BYTES, "JSON output exceeded limit")
    text = output.decode("utf-8", errors="replace")
    for raw_line in reversed(output.splitlines()):
        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            continue
        if isinstance(payload, dict) and (
            "status" in payload or "format_version" in payload
        ):
            return payload
    decoder = json.JSONDecoder()
    for offset in range(len(text) - 1, -1, -1):
        if text[offset] != "{":
            continue
        try:
            payload, end = decoder.raw_decode(text, offset)
        except (json.JSONDecodeError, RecursionError):
            continue
        if (
            not text[end:].strip()
            and isinstance(payload, dict)
            and ("status" in payload or "format_version" in payload)
        ):
            return payload
    raise CanaryError("bounded CPE JSON result was not found")


def git(repository: Path, *arguments: str, check: bool = True) -> str:
    result = run(["git", *arguments], cwd=repository, timeout=120)
    if check:
        require(result.returncode == 0, "Git command failed")
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeError as exc:
        raise CanaryError("Git output was not UTF-8") from exc


def write_text(root: Path, relative: str, content: str, mode: int = 0o600) -> Path:
    path = root / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved_parent = path.parent.resolve(strict=True)
    require(
        os.path.commonpath((str(root.resolve()), str(resolved_parent)))
        == str(root.resolve()),
        "write path escaped temporary root",
    )
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path.resolve(strict=True)


def fresh_repository(root: Path) -> tuple[Path, str]:
    repository = root / "repository"
    repository.mkdir(mode=0o700)
    git(repository, "init", "-b", "main")
    git(repository, "config", "--local", "user.name", "CPE Live Canary")
    git(
        repository,
        "config",
        "--local",
        "user.email",
        "cpe-live-canary@invalid.example",
    )
    write_text(repository, ".gitignore", ".superpowers/\n__pycache__/\n*.pyc\n")
    write_text(
        repository,
        "AGENTS.md",
        "# Canary Repository\n\n"
        "- Work only in this repository.\n"
        "- Do not add a remote or perform remote actions.\n"
        "- Follow the caller documents and return the CPE terminal envelope.\n",
    )
    write_text(repository, "README.md", "# CPE live canary\n")
    git(repository, "add", ".gitignore", "AGENTS.md", "README.md")
    git(repository, "commit", "-m", "chore: initialize canary repository")
    require(git(repository, "remote") == "", "fresh repository unexpectedly has a remote")
    return repository.resolve(strict=True), git(repository, "rev-parse", "HEAD")


def recursive_inventory(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(stat.S_IMODE(metadata.st_mode).to_bytes(4, "big"))
        if stat.S_ISREG(metadata.st_mode):
            payload = path.read_bytes()
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
        elif stat.S_ISDIR(metadata.st_mode):
            digest.update(b"D")
        else:
            raise CanaryError("inventory contains a non-file entry")
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, object]:
    require(path.is_file() and not path.is_symlink(), "persisted JSON is unavailable")
    payload = path.read_bytes()
    require(len(payload) <= MAX_JSON_BYTES, "persisted JSON exceeded limit")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CanaryError("persisted JSON is invalid") from exc
    require(isinstance(decoded, dict), "persisted JSON is not an object")
    return decoded


def write_receipt(root: Path, receipt: dict[str, object]) -> Path:
    path = root / "receipt.json"
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    require(len(payload) <= 16_384, "canary receipt exceeded limit")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        remaining = memoryview(payload + b"\n")
        while remaining:
            written = os.write(descriptor, remaining)
            require(written > 0, "canary receipt write was incomplete")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path.resolve(strict=True)


def new_temporary_root(scenario: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"cpe-live-{scenario}-")).resolve(strict=True)
    root.chmod(0o700)
    return root


def _not_implemented(_root: Path, _real_codex: Path) -> dict[str, object]:
    raise RuntimeError("live canary scenario is not implemented")


def resolve_real_codex() -> Path:
    executable = shutil.which("codex")
    require(executable is not None, "real codex executable was not found")
    path = Path(executable).resolve(strict=True)
    require(path.is_file(), "real codex executable is invalid")
    return path


def canary_environment(
    root: Path, real_codex: Path, *, session_loss: bool = False
) -> dict[str, str]:
    """Use a temporary CPE home while delegating provider state to the real home."""
    wrapper_root = root / "bin"
    wrapper_root.mkdir(mode=0o700)
    wrapper = write_text(
        root,
        "bin/codex",
        "#!/usr/bin/env python3\n"
        "import hashlib, json, os, subprocess, sys\n"
        "real = os.environ.pop('CPE_CANARY_REAL_CODEX')\n"
        "host_set = os.environ.pop('CPE_CANARY_HOST_CODEX_HOME_SET') == '1'\n"
        "host_home = os.environ.pop('CPE_CANARY_HOST_CODEX_HOME', '')\n"
        "host_path = os.environ.pop('CPE_CANARY_HOST_PATH')\n"
        "inject_loss = os.environ.pop('CPE_CANARY_SESSION_LOSS') == '1'\n"
        "marker = os.environ.pop('CPE_CANARY_LOSS_MARKER')\n"
        "event_path = os.environ.pop('CPE_CANARY_SHIM_EVENTS')\n"
        "args = sys.argv[1:]\n"
        "is_resume = 'resume' in args\n"
        "session = args[args.index('resume') + 1] if is_resume else None\n"
        "def facts(kind):\n"
        "    head = subprocess.check_output("
        "['git', 'rev-parse', 'HEAD'], text=True).strip()\n"
        "    status = subprocess.check_output("
        "['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'])\n"
        "    value = {'kind': kind, 'cwd': os.getcwd(), 'head': head, "
        "'status_digest': hashlib.sha256(status).hexdigest()}\n"
        "    if session is not None:\n"
        "        value['session_id'] = session\n"
        "    with open(event_path, 'a', encoding='utf-8') as stream:\n"
        "        stream.write(json.dumps(value, sort_keys=True) + '\\n')\n"
        "if inject_loss and is_resume:\n"
        "    try:\n"
        "        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)\n"
        "    except FileExistsError:\n"
        "        pass\n"
        "    else:\n"
        "        os.close(descriptor)\n"
        "        facts('resume_loss')\n"
        "        print(json.dumps({'type': 'error', 'error': "
        "{'code': 'session-not-found'}}), flush=True)\n"
        "        raise SystemExit(1)\n"
        "facts('fallback' if inject_loss and os.path.exists(marker) "
        "and not is_resume else 'initial')\n"
        "if host_set:\n"
        "    os.environ['CODEX_HOME'] = host_home\n"
        "else:\n"
        "    os.environ.pop('CODEX_HOME', None)\n"
        "os.environ['PATH'] = host_path\n"
        "os.execv(real, [real, *sys.argv[1:]])\n",
        0o700,
    )
    require(wrapper.name == "codex", "codex relay path is invalid")
    codex_home = root / "codex-home"
    codex_home.mkdir(mode=0o700, exist_ok=True)
    environment = os.environ.copy()
    host_home = environment.get("CODEX_HOME")
    environment.update(
        {
            "CODEX_HOME": str(codex_home),
            "CPE_CANARY_REAL_CODEX": str(real_codex),
            "CPE_CANARY_HOST_CODEX_HOME_SET": "1" if host_home is not None else "0",
            "CPE_CANARY_HOST_CODEX_HOME": host_home or "",
            "CPE_CANARY_HOST_PATH": environment.get("PATH", ""),
            "CPE_CANARY_SESSION_LOSS": "1" if session_loss else "0",
            "CPE_CANARY_LOSS_MARKER": str(root / "session-loss-once"),
            "CPE_CANARY_SHIM_EVENTS": str(root / "shim-events.jsonl"),
            "PATH": str(wrapper_root) + os.pathsep + environment.get("PATH", ""),
        }
    )
    return environment


def write_documents(root: Path, plan: str) -> tuple[Path, ...]:
    return (
        write_text(
            root,
            "documents/context/shared.md",
            "# Canary Context\n\n"
            "This is a local-only disposable repository. Preserve caller order, "
            "perform no remote action, and use the selected installed Superpowers skill.\n",
        ),
        write_text(root, "documents/execution/shared.md", plan),
        write_text(
            root,
            "documents/unfamiliar/contract.payload",
            "CANARY::OPAQUE{shape=>unfamiliar;meaning=>context-only}\n"
            "Do not treat this structure as a CPE role label.\n",
        ),
    )


def invoke_cpe(
    environment: dict[str, str],
    *arguments: str,
    expected_exit: int,
) -> dict[str, object]:
    result = run(
        [sys.executable, str(CPE_CLI), *arguments],
        cwd=SKILL_ROOT,
        env=environment,
    )
    require(result.returncode == expected_exit, "CPE CLI exit code was unexpected")
    return parse_last_json(result.stdout)


def persisted_run(
    root: Path, run_id: str
) -> tuple[Path, dict[str, object], dict[str, object]]:
    run_root = root / "codex-home" / "cpe-v3" / "runs" / run_id
    require(run_root.is_dir() and not run_root.is_symlink(), "run root is unavailable")
    return run_root, read_json(run_root / "manifest.json"), read_json(run_root / "state.json")


def sdd_multi_document(root: Path, real_codex: Path) -> dict[str, object]:
    repository, base = fresh_repository(root)
    plan = """# SDD Live Canary Execution Contract

Use the installed `subagent-driven-development` skill. This contract has two
small tasks and an invocation boundary.

On the initial CPE launch, execute Task 1 only. Create `canary_steps.py` with a
`phase_one()` function returning `phase-one`, create `test_canary_steps.py`
with a unittest for it, run that test, and commit exactly once with message
`test: add canary phase one`. Do not start Task 2. Return an `interrupted`
terminal envelope whose capsule records the current HEAD, the SHA-256 of raw
`git status --porcelain=v1 -z --untracked-files=all`, a short opaque note, and
`test_canary_steps.py` as its relative evidence reference.

When the launch packet says `CONTINUITY=same saved controller session`, execute
Task 2. Add `phase_two()` returning `phase-two`, add its unittest, run the full
test file, and commit exactly once with message `feat: add canary phase two`.
Leave tracked files clean and return the required successful terminal envelope
with the exact current HEAD. Never merge, push, add a remote, or modify files
outside the assigned worktree.
"""
    documents = write_documents(root, plan)
    environment = canary_environment(root, real_codex)
    run_result = invoke_cpe(
        environment,
        "run",
        *sum((("--document", str(path)) for path in documents), ()),
        "--workspace",
        str(repository),
        "--superpowers-skill",
        "subagent-driven-development",
        expected_exit=3,
    )
    require(run_result.get("status") == "interrupted", "initial SDD run did not interrupt")
    run_id = str(run_result.get("run_id"))
    run_root, manifest, first_state = persisted_run(root, run_id)
    manifest_bytes = (run_root / "manifest.json").read_bytes()
    require(
        manifest.get("format_version") == 5
        and manifest.get("contract_version") == 3
        and manifest.get("superpowers_skill") == "subagent-driven-development",
        "persisted SDD manifest is invalid",
    )
    records = manifest.get("documents")
    require(isinstance(records, list) and len(records) == 3, "document manifest is invalid")
    source_names = [Path(str(record["source_path"])).name for record in records]
    require(
        source_names == ["shared.md", "shared.md", "contract.payload"],
        "opaque document order or basenames changed",
    )
    first_session = first_state.get("controller_session_id")
    first_head = str(first_state.get("last_observed_head"))
    require(
        isinstance(first_session, str)
        and first_state.get("controller_generation") == 0
        and first_state.get("resume_capsule") is not None
        and first_head != base,
        "initial SDD persisted facts are invalid",
    )
    worktree = Path(str(manifest.get("worktree"))).resolve(strict=True)
    require(
        git(worktree, "cat-file", "-e", f"{first_head}:test_canary_steps.py") == "",
        "first tested commit is missing its test",
    )

    resume_result = invoke_cpe(
        environment, "resume", "--run-id", run_id, expected_exit=0
    )
    require(
        resume_result.get("status") == "handed_off"
        and resume_result.get("run_id") == run_id,
        "same-session SDD resume did not hand off",
    )
    inspect_result = invoke_cpe(
        environment, "inspect", "--run-id", run_id, expected_exit=0
    )
    require(inspect_result.get("status") == "handed_off", "inspect did not show handoff")
    _, final_manifest, final_state = persisted_run(root, run_id)
    require(
        (run_root / "manifest.json").read_bytes() == manifest_bytes
        and final_manifest == manifest,
        "immutable manifest changed across resume",
    )
    handoff_path = Path(str(resume_result.get("handoff_path"))).resolve(strict=True)
    handoff = read_json(handoff_path)
    final_head = str(handoff.get("observed_head"))
    require(
        final_state.get("status") == "handed_off"
        and final_state.get("controller_generation") == 0
        and final_state.get("controller_session_id") == first_session
        and handoff.get("controller_session_id") == first_session
        and handoff.get("controller_generation") == 0
        and handoff.get("integration") == "not_observed"
        and handoff.get("saved_worktree") == str(worktree),
        "same-session handoff facts are invalid",
    )
    require(
        int(git(worktree, "rev-list", "--count", f"{base}..{final_head}")) == 2
        and git(worktree, "merge-base", "--is-ancestor", first_head, final_head) == "",
        "SDD canary did not preserve exactly two ordered commits",
    )
    require(git(worktree, "remote") == "", "SDD canary added a remote")
    test_result = run(
        [sys.executable, "-m", "unittest", "-v", "test_canary_steps.py"],
        cwd=worktree,
        timeout=120,
    )
    require(test_result.returncode == 0, "SDD canary final test failed")
    return {
        "scenario": "sdd-multi-document",
        "run_id": run_id,
        "controller_session_id": first_session,
        "controller_generation": 0,
        "worktree": str(worktree),
        "head": final_head,
        "handoff_path": str(handoff_path),
        "integration": "not_observed",
        "first_head": first_head,
        "commit_count": 2,
    }


def read_shim_events(root: Path) -> list[dict[str, object]]:
    path = root / "shim-events.jsonl"
    require(path.is_file() and path.stat().st_size <= 16_384, "shim events are invalid")
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise CanaryError("shim event is invalid") from exc
        require(isinstance(value, dict), "shim event is not an object")
        events.append(value)
    return events


def session_loss(root: Path, real_codex: Path) -> dict[str, object]:
    repository, base = fresh_repository(root)
    plan = """# Executing-Plans Session-Loss Canary

Use the installed `executing-plans` skill. On the initial CPE launch, create
`session_steps.py` with `phase_one()` returning `phase-one` and a matching
`test_session_steps.py` unittest. Run the test and commit exactly once with
message `test: add session phase one`. Then return an `interrupted` terminal
envelope with the current HEAD, the SHA-256 of raw
`git status --porcelain=v1 -z --untracked-files=all`, a short opaque note, and
`test_session_steps.py` as its relative evidence reference.

When a fresh controller receives
`CONTINUITY=one fresh controller after explicit saved-session loss`, continue
from Git and the supplied capsule. Add `phase_two()` returning `phase-two`, add
its unittest, run the full test file, and commit exactly once with message
`feat: add session phase two`. Leave tracked files clean and return the
required successful terminal envelope at the exact HEAD. Never add a remote or
perform merge, push, publication, deployment, or outside-worktree writes.
"""
    documents = write_documents(root, plan)
    environment = canary_environment(root, real_codex, session_loss=True)
    run_result = invoke_cpe(
        environment,
        "run",
        *sum((("--document", str(path)) for path in documents), ()),
        "--workspace",
        str(repository),
        "--superpowers-skill",
        "executing-plans",
        expected_exit=3,
    )
    require(
        run_result.get("status") == "interrupted",
        "session-loss initial run did not interrupt",
    )
    run_id = str(run_result.get("run_id"))
    run_root, manifest, initial_state = persisted_run(root, run_id)
    manifest_bytes = (run_root / "manifest.json").read_bytes()
    initial_session = initial_state.get("controller_session_id")
    initial_head = str(initial_state.get("last_observed_head"))
    initial_capsule = initial_state.get("resume_capsule")
    require(
        isinstance(initial_session, str)
        and initial_state.get("controller_generation") == 0
        and initial_state.get("fresh_fallback_used") is False
        and isinstance(initial_capsule, dict),
        "session-loss initial facts are invalid",
    )
    worktree = Path(str(manifest.get("worktree"))).resolve(strict=True)
    require(
        manifest.get("base_commit") == base
        and manifest.get("superpowers_skill") == "executing-plans",
        "session-loss manifest is invalid",
    )

    resume_result = invoke_cpe(
        environment, "resume", "--run-id", run_id, expected_exit=0
    )
    require(
        resume_result.get("status") == "handed_off"
        and resume_result.get("run_id") == run_id,
        "session-loss fallback did not hand off",
    )
    inspect_result = invoke_cpe(
        environment, "inspect", "--run-id", run_id, expected_exit=0
    )
    _, final_manifest, final_state = persisted_run(root, run_id)
    require(
        inspect_result.get("status") == "handed_off"
        and inspect_result.get("controller_generation") == 1
        and final_manifest == manifest
        and (run_root / "manifest.json").read_bytes() == manifest_bytes,
        "session-loss run identity changed",
    )
    final_session = final_state.get("controller_session_id")
    final_capsule = final_state.get("resume_capsule")
    handoff_path = Path(str(resume_result.get("handoff_path"))).resolve(strict=True)
    handoff = read_json(handoff_path)
    final_head = str(handoff.get("observed_head"))
    require(
        isinstance(final_session, str)
        and final_session != initial_session
        and final_state.get("controller_generation") == 1
        and final_state.get("fresh_fallback_used") is True
        and final_capsule == initial_capsule
        and handoff.get("controller_session_id") == final_session
        and handoff.get("controller_generation") == 1
        and handoff.get("saved_worktree") == str(worktree)
        and handoff.get("integration") == "not_observed",
        "session-loss final facts are invalid",
    )
    events = read_shim_events(root)
    losses = [event for event in events if event.get("kind") == "resume_loss"]
    fallbacks = [event for event in events if event.get("kind") == "fallback"]
    initials = [event for event in events if event.get("kind") == "initial"]
    require(
        len(initials) == 1
        and len(losses) == 1
        and len(fallbacks) == 1
        and losses[0].get("session_id") == initial_session
        and losses[0].get("cwd") == str(worktree)
        and fallbacks[0].get("cwd") == str(worktree)
        and losses[0].get("head") == initial_head
        and fallbacks[0].get("head") == initial_head
        and losses[0].get("status_digest") == initial_state.get("status_digest")
        and fallbacks[0].get("status_digest") == initial_state.get("status_digest"),
        "session-loss shim did not prove one same-HEAD fallback",
    )
    require(
        int(git(worktree, "rev-list", "--count", f"{base}..{final_head}")) == 2
        and git(worktree, "remote") == "",
        "session-loss commits or remote state are invalid",
    )
    test_result = run(
        [sys.executable, "-m", "unittest", "-v", "test_session_steps.py"],
        cwd=worktree,
        timeout=120,
    )
    require(test_result.returncode == 0, "session-loss final test failed")
    capsule_digest = hashlib.sha256(
        json.dumps(initial_capsule, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    document_digest = hashlib.sha256(
        json.dumps(
            manifest.get("documents"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return {
        "scenario": "session-loss",
        "run_id": run_id,
        "controller_session_id": final_session,
        "controller_generation": 1,
        "worktree": str(worktree),
        "head": final_head,
        "handoff_path": str(handoff_path),
        "integration": "not_observed",
        "fallback_count": 1,
        "initial_controller_session_id": initial_session,
        "first_resume_session_id": losses[0]["session_id"],
        "final_controller_session_id": final_session,
        "session_loss_head": initial_head,
        "fallback_start_head": fallbacks[0]["head"],
        "initial_resume_capsule_sha256": capsule_digest,
        "final_resume_capsule_sha256": capsule_digest,
        "manifest_sha256": manifest_digest,
        "document_bundle_sha256": document_digest,
        "base_commit": base,
        "generation_two_observed": False,
    }


def legacy_adoption(root: Path, real_codex: Path) -> dict[str, object]:
    repository, _initial = fresh_repository(root)
    write_text(repository, "adopted_state.txt", "baseline\n")
    write_text(
        repository,
        "test_adopted_state.py",
        "from pathlib import Path\n"
        "import unittest\n\n"
        "class AdoptionTest(unittest.TestCase):\n"
        "    def test_preserved_partial_state(self):\n"
        "        self.assertEqual("
        "Path('adopted_state.txt').read_text(), 'preserved partial\\n')\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
    )
    git(repository, "add", "adopted_state.txt", "test_adopted_state.py")
    git(repository, "commit", "-m", "test: define adoption target")
    base = git(repository, "rev-parse", "HEAD")
    adopted_worktree = (root / "adopted-worktree").resolve()
    git(
        repository,
        "worktree",
        "add",
        "-b",
        "codex/live-canary-adoption",
        str(adopted_worktree),
        base,
    )
    write_text(root, "adopted-worktree/adopted_state.txt", "preserved partial\n")
    require(
        git(adopted_worktree, "status", "--porcelain") != "",
        "adoption worktree is not dirty",
    )

    environment = canary_environment(root, real_codex)
    legacy_run_id = "cpe-3333333333333333"
    legacy_root = root / "codex-home" / "orchestrator" / legacy_run_id
    write_text(
        root,
        f"codex-home/orchestrator/{legacy_run_id}/state.json",
        '{"format_version":3,"status":"interrupted"}\n',
        0o400,
    )
    write_text(
        root,
        f"codex-home/orchestrator/{legacy_run_id}/artifacts/nested.json",
        '{"forensic":"preserve"}\n',
        0o400,
    )
    for directory in sorted(
        (path for path in legacy_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    legacy_root.chmod(0o500)
    inventory_before = recursive_inventory(legacy_root)
    legacy_inspect_before = invoke_cpe(
        environment, "inspect", "--run-id", legacy_run_id, expected_exit=0
    )
    require(
        legacy_inspect_before.get("status") == "legacy_read_only"
        and legacy_inspect_before.get("format_version") == 3
        and legacy_inspect_before.get("run_root") == str(legacy_root),
        "synthetic legacy root was not read-only inspectable",
    )

    plan = """# Explicit Legacy Worktree Adoption Contract

Use the installed `executing-plans` skill. The assigned linked worktree already
contains one intentional tracked change in `adopted_state.txt`. Preserve that
content, run `python3 -m unittest -v test_adopted_state.py`, and commit the
existing tracked change exactly once with message
`feat: preserve adopted partial state`. Do not inspect, edit, convert, chmod,
move, or delete any old CPE run root. Leave tracked files clean and return the
required successful terminal envelope at the exact current HEAD. Never add a
remote or perform merge, push, publication, deployment, cleanup, or writes
outside the explicitly adopted worktree.
"""
    documents = write_documents(root, plan)
    run_result = invoke_cpe(
        environment,
        "run",
        *sum((("--document", str(path)) for path in documents), ()),
        "--workspace",
        str(repository),
        "--superpowers-skill",
        "executing-plans",
        "--adopt-worktree",
        str(adopted_worktree),
        "--base",
        base,
        expected_exit=0,
    )
    require(
        run_result.get("status") == "handed_off",
        "legacy adoption did not hand off",
    )
    run_id = str(run_result.get("run_id"))
    require(run_id != legacy_run_id, "v3 run reused the legacy run ID")
    run_root, manifest, state = persisted_run(root, run_id)
    inspect_result = invoke_cpe(
        environment, "inspect", "--run-id", run_id, expected_exit=0
    )
    legacy_inspect_after = invoke_cpe(
        environment, "inspect", "--run-id", legacy_run_id, expected_exit=0
    )
    inventory_after = recursive_inventory(legacy_root)
    require(
        inventory_after == inventory_before
        and legacy_inspect_after == legacy_inspect_before,
        "legacy inventory changed during explicit adoption",
    )
    handoff_path = Path(str(run_result.get("handoff_path"))).resolve(strict=True)
    handoff = read_json(handoff_path)
    head = str(handoff.get("observed_head"))
    session_id = state.get("controller_session_id")
    records = manifest.get("documents")
    require(
        inspect_result.get("status") == "handed_off"
        and manifest.get("format_version") == 5
        and manifest.get("contract_version") == 3
        and manifest.get("base_commit") == base
        and manifest.get("worktree") == str(adopted_worktree)
        and isinstance(records, list)
        and [Path(str(record["source_path"])).name for record in records]
        == ["shared.md", "shared.md", "contract.payload"]
        and state.get("status") == "handed_off"
        and state.get("controller_generation") == 0
        and isinstance(session_id, str)
        and handoff.get("controller_session_id") == session_id
        and handoff.get("controller_generation") == 0
        and handoff.get("saved_worktree") == str(adopted_worktree)
        and handoff.get("integration") == "not_observed",
        "legacy adoption persisted facts are invalid",
    )
    require(
        run_root.parent.parent == root / "codex-home" / "cpe-v3"
        and int(git(adopted_worktree, "rev-list", "--count", f"{base}..{head}")) == 1
        and git(adopted_worktree, "status", "--porcelain") == ""
        and git(adopted_worktree, "remote") == "",
        "legacy adoption Git facts are invalid",
    )
    test_result = run(
        [sys.executable, "-m", "unittest", "-v", "test_adopted_state.py"],
        cwd=adopted_worktree,
        timeout=120,
    )
    require(test_result.returncode == 0, "legacy adoption final test failed")
    return {
        "scenario": "legacy-adoption",
        "run_id": run_id,
        "controller_session_id": session_id,
        "controller_generation": 0,
        "worktree": str(adopted_worktree),
        "head": head,
        "handoff_path": str(handoff_path),
        "integration": "not_observed",
        "legacy_run_id": legacy_run_id,
        "v3_run_id": run_id,
        "legacy_inventory_before": inventory_before,
        "legacy_inventory_after": inventory_after,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.environ.get("CPE_LIVE_CANARY") != "1":
        print("CPE_LIVE_CANARY=1 is required", file=os.sys.stderr)
        return 2
    real_codex = resolve_real_codex()
    root = new_temporary_root(args.scenario)
    scenarios: dict[
        str, Callable[[Path, Path], dict[str, object]]
    ] = {
        name: _not_implemented for name in SCENARIOS
    }
    scenarios["sdd-multi-document"] = sdd_multi_document
    scenarios["session-loss"] = session_loss
    scenarios["legacy-adoption"] = legacy_adoption
    try:
        receipt = scenarios[args.scenario](root, real_codex)
        receipt["receipt_path"] = str((root / "receipt.json").resolve())
        path = write_receipt(root, receipt)
        require(str(path) == receipt["receipt_path"], "receipt path changed")
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        error = {
            "scenario": args.scenario,
            "temporary_root": str(root),
            "error": (str(exc).strip() or type(exc).__name__)[:1000],
        }
        print(json.dumps(error, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
