"""M5 process wrapper core (spec §5.16, §8.2, §S1.6.17, §S1.9.2).

The wrapper spawns the child process, drains stdout/stderr **concurrently**
(selectors-based dual-stream drain to avoid pipe-buffer deadlock), forwards
SIGINT/SIGTERM, and wires the full §5.16 recording pipeline (run init,
final.json branches, seal/eval/index_run). EVERY recording stage is guarded
so that an AgentLens-internal failure NEVER alters the child's exit code —
this is the §5.16 non-blocking-passthrough invariant (spec §S1.6.17).

Nested-invocation policy (``AGENTLENS_NESTED_POLICY``, spec §S1.7.4 / §S1.8.4):
when the wrapper detects an inherited ``AGENTLENS_RUN_ID`` from a parent
wrapper, the default ``passthrough`` policy skips recording (the child runs
unchanged); ``nested`` opts into a fresh child run that records ``parent_run_id``.

Excerpt extraction obeys an **allow-list only** policy enforcing
``MAX_EXCERPT_CHARS=4096`` with a ``<TRUNCATED>`` marker (spec §8.2).

The ``WrapperResult.exit_code`` MUST always reflect the child's real exit
code (or ``128+signum`` on signal) per the §5.16 invariant.
"""
from __future__ import annotations

import contextlib
import os
import re
import selectors
import signal
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable, Literal

from agentlens.constants import (
    MAX_EXCERPT_CHARS,
    SCHEMA_EVENT_V1,
    SCHEMA_FINAL_V1,
    SCHEMA_RUN_V1,
)
from agentlens.evaluator.engine import evaluate
from agentlens.ids import compute_workspace_id, make_event_id, make_run_id
from agentlens.store.manifest import seal
from agentlens.store.paths import agentlens_home
from agentlens.store.paths import run_dir as build_run_dir
from agentlens.store.sqlite_index import index_run, init_db
from agentlens.store.writer import (
    append_event,
    write_final,
    write_run_meta,
    write_workspace_pointer,
)
from agentlens.time import utc_now_iso

__all__ = [
    "EXCERPT_EXTRACTORS",
    "MAX_EXCERPT_CHARS",
    "TRUNCATED_MARKER",
    "WrapperResult",
    "apply_excerpt_extractors",
    "drain_streams_concurrently",
    "resolve_agent_outcome",
    "wrap_command",
]

TRUNCATED_MARKER = "<TRUNCATED>"

_ADAPTER_FOR_AGENT = {
    "claude_code": "claude_code_shim",
    "codex_cli": "codex_cli_shim",
    "codex_app": "codex_app_shim",
    "generic": "generic_shim",
}


# ---------------------------------------------------------------------------
# WrapperResult
# ---------------------------------------------------------------------------


@dataclass
class WrapperResult:
    """Result of :func:`wrap_command` (spec §5.16).

    ``run_id`` is ``None`` when recording was not initialized (e.g. an
    AgentLens-internal init failure took the passthrough branch).

    ``exit_code`` is *always* the child's actual exit code (or ``128+signum``
    when cancelled by a forwarded signal).

    ``cancelled_by_signal`` is the signal name (``"SIGINT"`` / ``"SIGTERM"`` /
    ``"other"``) if the wrapper forwarded a signal to the child, else ``None``.
    """

    run_id: str | None
    exit_code: int
    cancelled_by_signal: str | None


# ---------------------------------------------------------------------------
# Dual-stream concurrent drain (spec §5.16)
# ---------------------------------------------------------------------------


def drain_streams_concurrently(
    child: subprocess.Popen,
    *,
    tee: bool = True,
) -> tuple[bytes, bytes]:
    """Drain ``child.stdout`` and ``child.stderr`` concurrently.

    Uses :mod:`selectors` so a single thread services both pipes; this avoids
    the classic deadlock where the child blocks writing to one pipe while the
    parent blocks reading the other.

    Spec §5.16: "POSIX v0에서는 ``selectors`` 또는 두 reader thread를 사용한다.
    한 stream만 순차로 읽는 구현은 stderr/stdout pipe buffer가 꽉 찰 때
    deadlock을 만들 수 있으므로 금지한다."

    When ``tee`` is ``True`` (default), each chunk read from the child is
    *also* written to the parent's ``sys.stdout.buffer`` / ``sys.stderr.buffer``
    and flushed. This preserves the user-facing contract of
    ``agentlens run -- <cmd>`` as a transparent wrapper (cf. ``time``,
    ``strace``): the user sees child output live while AgentLens captures it
    for excerpt extraction. ``tee=False`` is for tests that need to capture
    large payloads without polluting test output.

    Returns the captured ``(stdout_bytes, stderr_bytes)``. The child file
    descriptors are closed by this function once both reach EOF.
    """
    if child.stdout is None or child.stderr is None:
        raise ValueError(
            "drain_streams_concurrently requires child spawned with "
            "stdout=PIPE and stderr=PIPE"
        )

    sel = selectors.DefaultSelector()
    buffers: dict[int, bytearray] = {}
    fd_stdout = child.stdout.fileno()
    fd_stderr = child.stderr.fileno()
    buffers[fd_stdout] = bytearray()
    buffers[fd_stderr] = bytearray()
    sel.register(child.stdout, selectors.EVENT_READ, data=fd_stdout)
    sel.register(child.stderr, selectors.EVENT_READ, data=fd_stderr)

    open_fds = 2
    while open_fds > 0:
        for key, _events in sel.select():
            chunk = key.fileobj.read1(65536)  # type: ignore[attr-defined]
            if not chunk:
                sel.unregister(key.fileobj)
                key.fileobj.close()
                open_fds -= 1
                continue
            buffers[key.data].extend(chunk)
            if tee:
                sink = sys.stdout if key.data == fd_stdout else sys.stderr
                try:
                    sink.buffer.write(chunk)
                    sink.buffer.flush()
                except (AttributeError, OSError):
                    # Wrapped/redirected sinks may lack .buffer or be closed;
                    # never let tee failure break drain (non-blocking invariant).
                    pass
    sel.close()
    return bytes(buffers[fd_stdout]), bytes(buffers[fd_stderr])


# ---------------------------------------------------------------------------
# Excerpt extractors — allow-list only (spec §5.11, §8.2)
# ---------------------------------------------------------------------------


_PYTEST_SUMMARY_RE = re.compile(
    r"^=+\s*(?:\d+\s+\w+(?:,\s*)?)+(?:\s+in\s+[0-9.]+s)?\s*=+\s*$",
    re.MULTILINE,
)
_EXCEPTION_LINE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9_.]*Error|[A-Z][A-Za-z0-9_.]*Exception|"
    r"AssertionError|StopIteration|SystemExit|KeyboardInterrupt|"
    r"GeneratorExit|Warning)(?::\s.*)?$",
    re.MULTILINE,
)
_EXIT_CODE_RE = re.compile(
    r"(?:exited|exit(?:ed)?)\s+with\s+(?:code|status)\s+(-?\d+)",
    re.IGNORECASE,
)


def _extract_pytest_summary(text: str) -> str | None:
    """Return the last pytest summary banner line, e.g.
    ``"12 passed, 1 failed in 0.42s"`` (without the surrounding ``=`` rule)."""
    matches = list(_PYTEST_SUMMARY_RE.finditer(text))
    if not matches:
        return None
    line = matches[-1].group(0).strip()
    # Strip the leading/trailing '=' rule and surrounding whitespace.
    line = line.strip("=").strip()
    return line or None


def _extract_error_type(text: str) -> str | None:
    """Return the trailing Python-style exception line (e.g.
    ``"TypeError: bad thing"``)."""
    matches = list(_EXCEPTION_LINE_RE.finditer(text))
    if not matches:
        return None
    return matches[-1].group(0).rstrip()


def _extract_exit_code(text: str) -> str | None:
    """Return the matched ``"exited with code N"`` line if present."""
    m = _EXIT_CODE_RE.search(text)
    if not m:
        return None
    return m.group(0)


# Allow-list. Tasks adding extractors MUST keep this allow-list discipline
# (spec §8.2 — "추출은 ``EXCERPT_EXTRACTORS`` allow-list로만").
EXCERPT_EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "pytest_summary": _extract_pytest_summary,
    "exit_code_line": _extract_exit_code,
    "error_type": _extract_error_type,
}


def _enforce_max_chars(value: str) -> str:
    """Cap ``value`` at ``MAX_EXCERPT_CHARS`` with ``<TRUNCATED>`` marker
    appended when truncation occurs (spec §8.2)."""
    if len(value) <= MAX_EXCERPT_CHARS:
        return value
    keep = MAX_EXCERPT_CHARS - len(TRUNCATED_MARKER)
    if keep < 0:
        # Pathological constant change; preserve marker, drop content.
        return TRUNCATED_MARKER[:MAX_EXCERPT_CHARS]
    return value[:keep] + TRUNCATED_MARKER


def apply_excerpt_extractors(
    data: bytes | str,
    *,
    extractor: str,
) -> str | None:
    """Run an allow-list extractor on ``data`` and enforce length policy.

    - Only names present in :data:`EXCERPT_EXTRACTORS` are honored; unknown
      names return ``None`` (no free-text slicing — spec §8.2).
    - ``bytes`` input is decoded as UTF-8 with ``errors='replace'`` so the
      extractor sees a ``str``.
    - Output is capped at :data:`MAX_EXCERPT_CHARS`; truncation appends
      ``<TRUNCATED>``.
    - Returns ``None`` if the extractor produced no match.
    """
    fn = EXCERPT_EXTRACTORS.get(extractor)
    if fn is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        text = bytes(data).decode("utf-8", errors="replace")
    else:
        text = data
    result = fn(text)
    if result is None:
        return None
    return _enforce_max_chars(result)


# ---------------------------------------------------------------------------
# Recording init (spec §5.16) — replaces task_13 stub
# ---------------------------------------------------------------------------


def _root_hash(workspace_root: Path) -> str:
    """Return ``"sha256:<hex>"`` of the workspace root's resolved absolute path."""
    return "sha256:" + sha256(
        str(workspace_root.resolve()).encode("utf-8")
    ).hexdigest()


def _build_run_doc(
    *,
    run_id: str,
    workspace_id: str,
    basis: str,
    metadata: dict,
    workspace_root: Path,
    agent_name: str,
    agent_mode: str,
    mode: str,
    parent_run_id: str | None = None,
) -> dict:
    workspace_block: dict = {
        "root_label": "<workspace>",
        "root_hash": _root_hash(workspace_root),
        "id_basis": basis,
    }
    if "git_remote_hash" in metadata:
        workspace_block["git_remote_hash"] = metadata["git_remote_hash"]
    if "git_branch" in metadata:
        workspace_block["git_branch"] = metadata["git_branch"]

    doc: dict = {
        "schema": SCHEMA_RUN_V1,
        "run_id": run_id,
        "workspace_id": workspace_id,
        "started_at": utc_now_iso(),
        "agent": {"name": agent_name, "mode": agent_mode},
        "workspace": workspace_block,
        "recording": {
            "mode": mode,
            "adapter": _ADAPTER_FOR_AGENT.get(agent_name, "generic_shim"),
        },
    }
    # Spec §S1.8.4: nested runs carry parent_run_id linking back to the
    # outer run id, so query/lineage tooling can traverse the chain.
    if parent_run_id:
        doc["parent_run_id"] = parent_run_id
    return doc


def _make_event(
    *,
    run_id: str,
    event_type: str,
    payload: dict,
) -> dict:
    return {
        "schema": SCHEMA_EVENT_V1,
        "event_id": make_event_id(),
        "run_id": run_id,
        "ts": utc_now_iso(),
        "type": event_type,
        "payload": payload,
    }


def _init_recording(
    argv: list[str],
    *,
    agent_name: str,
    agent_mode: str,
    mode: Literal["minimal", "full"],
    parent_run_id: str | None = None,
) -> tuple[bool, str | None, Path | None]:
    """Recording initialization (spec §5.16).

    Returns ``(recording_enabled, run_id, run_dir)``:

    - ``recording_enabled`` is ``True`` iff the full init block succeeded.
    - ``run_id``/``run_dir`` are populated when recording is enabled, else
      ``None``. On any internal failure the function swallows the exception
      and returns ``(False, None, None)`` so the wrapper's passthrough
      branch executes (spec §S1.6.17 — ER-1 fix: child must still run).
    - ``parent_run_id`` is propagated into ``run.json`` when the policy
      resolves to ``nested`` (spec §S1.8.4).
    """
    try:
        workspace_root = Path.cwd()
        new_run_id = make_run_id()
        workspace_id, basis, metadata = compute_workspace_id(workspace_root)
        target_dir = build_run_dir(workspace_id, new_run_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        run_doc = _build_run_doc(
            run_id=new_run_id,
            workspace_id=workspace_id,
            basis=basis,
            metadata=metadata,
            workspace_root=workspace_root,
            agent_name=agent_name,
            agent_mode=agent_mode,
            mode=mode,
            parent_run_id=parent_run_id,
        )
        write_run_meta(target_dir, run_doc)

        started_event = _make_event(
            run_id=new_run_id,
            event_type="run.started",
            payload={"agent": agent_name, "mode": agent_mode},
        )
        append_event(target_dir, started_event)

        write_workspace_pointer(workspace_root, new_run_id, target_dir)
    except Exception:
        # Spec §S1.6.17 (ER-1): any init failure → non-blocking passthrough.
        return False, None, None

    return True, new_run_id, target_dir


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


_SIGNAL_NAME_MAP = {
    int(signal.SIGINT): "SIGINT",
    int(signal.SIGTERM): "SIGTERM",
}


def _install_signal_handlers(
    child: subprocess.Popen,
) -> tuple[dict[str, str | None], dict[int, object]]:
    """Install SIGINT/SIGTERM forwarders that proxy to ``child`` (spec §5.16).

    Returns ``(sig_received, prior_handlers)``:

    - ``sig_received["name"]`` is set to ``"SIGINT"`` / ``"SIGTERM"`` /
      ``"other"`` if the wrapper receives a signal; otherwise stays ``None``.
    - ``prior_handlers`` maps signum → previous handler, so the caller can
      restore the original disposition via :func:`_restore_signal_handlers`.

    The handler suppresses Python's default SIGINT→KeyboardInterrupt
    translation and forwards the signal to the child's PID. The child's
    own reaction (typically termination) drives wrapper termination via
    :meth:`subprocess.Popen.wait`.
    """
    sig_received: dict[str, str | None] = {"name": None}

    def handler(signum: int, _frame: object) -> None:
        sig_received["name"] = _SIGNAL_NAME_MAP.get(signum, "other")
        try:
            os.kill(child.pid, signum)
        except ProcessLookupError:
            # Child already exited; nothing to forward.
            pass

    prior_handlers: dict[int, object] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        prior_handlers[int(signum)] = signal.signal(signum, handler)
    return sig_received, prior_handlers


def _restore_signal_handlers(prior_handlers: dict[int, object]) -> None:
    """Restore handlers captured by :func:`_install_signal_handlers`."""
    for signum, prev in prior_handlers.items():
        signal.signal(signum, prev)  # type: ignore[arg-type]


def _signum_of(sig_name: str) -> int:
    """Return the POSIX signal number for ``sig_name``.

    Per spec §5.16, the wrapper exit code on a forwarded signal is
    ``128 + signum``. Names ``"SIGINT"`` and ``"SIGTERM"`` resolve to the
    canonical numbers (2 and 15 on POSIX). The fallback ``"other"`` token
    is mapped to ``SIGTERM`` (15) so the canonical 128+signum contract
    still holds for the typical termination signal class.
    """
    if sig_name == "SIGINT":
        return int(signal.SIGINT)
    if sig_name == "SIGTERM":
        return int(signal.SIGTERM)
    # "other" — spec leaves the precise number unspecified for non-INT/TERM
    # signals in v0; use SIGTERM as a conservative default so 128+signum
    # still yields a well-defined exit code.
    return int(signal.SIGTERM)


def resolve_agent_outcome(
    *,
    exit_code: int,
    sig_name: str | None,
    explicit_final_present: bool,
) -> Literal["success", "failed", "partial", "unknown", "cancelled"]:
    """Pure resolver for the spec §5.16 final-outcome 3-branch logic.

    Precedence (highest first):

    1. ``sig_name`` set → ``"cancelled"`` (wrapper was signalled).
    2. ``explicit_final_present`` → ``"success"``. The agent already wrote
       ``final.json``; the wrapper does not overwrite it. This sentinel
       reflects "agent-decided"; downstream readers consult the file for
       the actual ``success | failed | partial`` value.
    3. ``exit_code == 0`` → ``"unknown"`` (no final, clean exit).
    4. Otherwise → ``"failed"`` (no final, non-zero exit).
    """
    if sig_name is not None:
        return "cancelled"
    if explicit_final_present:
        return "success"
    if exit_code == 0:
        return "unknown"
    return "failed"


# ---------------------------------------------------------------------------
# final.json builders (spec §5.16)
# ---------------------------------------------------------------------------


def _base_final_doc(run_id: str) -> dict:
    return {
        "schema": SCHEMA_FINAL_V1,
        "run_id": run_id,
        "ended_at": utc_now_iso(),
        "summary": "",
        "changed_files": [],
        "verification": [],
        "residual_risks": [],
    }


def _write_cancelled_final(
    run_dir: Path, run_id: str, exit_code: int, sig_name: str
) -> None:
    doc = _base_final_doc(run_id)
    doc["agent_outcome"] = "cancelled"
    doc["exit_code"] = exit_code
    # Schema allow-list: SIGINT/SIGTERM/SIGHUP/other.
    doc["exit_signal"] = sig_name if sig_name in {"SIGINT", "SIGTERM", "SIGHUP"} else "other"
    write_final(run_dir, doc)


def _write_unknown_final(run_dir: Path, run_id: str) -> None:
    doc = _base_final_doc(run_id)
    doc["agent_outcome"] = "unknown"
    doc["exit_code"] = 0
    write_final(run_dir, doc)


def _write_failed_final(run_dir: Path, run_id: str, exit_code: int) -> None:
    doc = _base_final_doc(run_id)
    doc["agent_outcome"] = "failed"
    doc["exit_code"] = exit_code
    write_final(run_dir, doc)


# ---------------------------------------------------------------------------
# Post-drain pipeline (spec §5.16) — all stages are best-effort with guards.
# ---------------------------------------------------------------------------


def _run_post_drain_pipeline(
    *,
    run_id: str,
    run_dir: Path,
    rc: int,
    exit_code: int,
    sig_name: str | None,
) -> None:
    """Run the §5.16 finalization pipeline.

    Every stage is wrapped in try/except so a failure cannot alter the
    wrapper's exit code (spec §S1.6.17 invariant). On pre_eval seal or
    evaluator failure, the pipeline marks the run ``recording_incomplete``
    and returns early.
    """
    # command.finished — best-effort.
    with contextlib.suppress(Exception):
        append_event(
            run_dir,
            _make_event(
                run_id=run_id,
                event_type="command.finished",
                payload={"exit_code": exit_code},
            ),
        )

    # final.json branching — only write when the agent didn't already
    # produce one. write_final failures are swallowed so exit_code holds.
    explicit_final = (run_dir / "final.json").exists()
    try:
        if sig_name is not None:
            _write_cancelled_final(run_dir, run_id, rc, sig_name)
        elif explicit_final:
            # Agent wrote final.json — don't overwrite.
            pass
        elif exit_code == 0:
            _write_unknown_final(run_dir, run_id)
        else:
            _write_failed_final(run_dir, run_id, exit_code)
    except Exception:
        # Spec §S1.6.17: final.json write failure must not block exit.
        pass

    # seal(pre_eval) → evaluate → seal(final) → index_run.
    # Each stage's failure is contained.
    try:
        seal(run_dir, "pre_eval")
    except Exception:
        with contextlib.suppress(Exception):
            seal(run_dir, "recording_incomplete")
        return

    try:
        evaluate(run_dir)
    except Exception:
        with contextlib.suppress(Exception):
            seal(run_dir, "recording_incomplete")
        return

    with contextlib.suppress(Exception):
        seal(run_dir, "final")

    # SQLite index update — best-effort per spec §7.3.
    # init_db() composes open_db + init_schema so a fresh AGENTLENS_HOME
    # (no prior `agentlens` command run) gets the tables before index_run
    # tries to INSERT; otherwise stderr emits "no such table: runs".
    try:
        conn = init_db(agentlens_home())
    except Exception:
        return
    try:
        try:
            index_run(conn, run_dir)
        except Exception:
            pass
    finally:
        with contextlib.suppress(Exception):
            conn.close()


# ---------------------------------------------------------------------------
# wrap_command — full §5.16 pipeline
# ---------------------------------------------------------------------------


def wrap_command(
    argv: list[str],
    *,
    agent_name: str,
    agent_mode: str,
    mode: Literal["minimal", "full"],
) -> WrapperResult:
    """Spawn ``argv`` and return :class:`WrapperResult` (spec §5.16).

    Wires the full §5.16 pipeline: recording init → spawn → concurrent
    dual-stream drain → signal forwarding → final.json branching →
    seal/eval/index_run. EVERY recording stage is guarded so an
    AgentLens-internal failure NEVER alters the child's exit code
    (spec §S1.6.17 non-blocking-passthrough invariant).
    """
    # Task 18: nested-invocation policy (spec §S1.7.4, §S1.8.4).
    # When we are already inside an AgentLens run (i.e. a parent wrapper has
    # exported AGENTLENS_RUN_ID), the default policy is ``passthrough`` —
    # the child runs without re-recording so we don't double-record agents
    # that re-invoke themselves. ``nested`` opts into a fresh child run that
    # carries ``parent_run_id`` linking back to the outer run.
    policy = os.environ.get("AGENTLENS_NESTED_POLICY", "passthrough")
    inherited_run_id = os.environ.get("AGENTLENS_RUN_ID")
    inherited_stamp = os.environ.get("AGENTLENS_RUN_PID_STAMP", "")
    nested_passthrough = bool(inherited_run_id) and policy != "nested"

    # The PID stamp (set by the parent wrapper as ``f"{pid}:{run_id}"``)
    # lets shims short-circuit re-entry from the same wrapper PID; if the
    # stamp's prefix matches *our* parent PID, we treat it as a true nested
    # call. The variable is read here to document the contract, but actual
    # shim-level re-entry guarding lives in adapters/shims.py (SHIM_TEMPLATE).
    _ = inherited_stamp

    if nested_passthrough:
        # No recording — spawn directly, preserve exit code, forward signals.
        child = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        sig_received, prior_handlers = _install_signal_handlers(child)
        try:
            drain_streams_concurrently(child)
            child_exit_code = child.wait()
        finally:
            _restore_signal_handlers(prior_handlers)
        sig_name = sig_received["name"]
        rc = (128 + _signum_of(sig_name)) if sig_name else child_exit_code
        return WrapperResult(
            run_id=None, exit_code=rc, cancelled_by_signal=sig_name
        )

    # Recording branch (possibly nested with parent_run_id).
    parent_run_id = inherited_run_id if inherited_run_id else None

    recording_enabled, run_id, run_dir = _init_recording(
        argv,
        agent_name=agent_name,
        agent_mode=agent_mode,
        mode=mode,
        parent_run_id=parent_run_id,
    )

    # command.started — best-effort; only meaningful when recording is on.
    if recording_enabled and run_id is not None and run_dir is not None:
        with contextlib.suppress(Exception):
            append_event(
                run_dir,
                _make_event(
                    run_id=run_id,
                    event_type="command.started",
                    payload={
                        "command_hash": "sha256:"
                        + sha256(
                            "\x00".join(argv).encode("utf-8")
                        ).hexdigest(),
                    },
                ),
            )

    # When recording, propagate run-id / run-dir / PID stamp into the child
    # so nested shims can detect re-entry (spec §S1.7.4 — PID stamp pattern).
    popen_kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if recording_enabled and run_id is not None and run_dir is not None:
        child_env = os.environ.copy()
        child_env["AGENTLENS_RUN_ID"] = run_id
        child_env["AGENTLENS_RUN_DIR"] = str(run_dir)
        child_env["AGENTLENS_RUN_PID_STAMP"] = f"{os.getpid()}:{run_id}"
        popen_kwargs["env"] = child_env

    child = subprocess.Popen(argv, **popen_kwargs)
    sig_received, prior_handlers = _install_signal_handlers(child)
    try:
        # Concurrent dual-stream drain — mandated by spec §5.16. Sequential
        # read is forbidden because it deadlocks on >64KB output per stream.
        _stdout, _stderr = drain_streams_concurrently(child)
        child_exit_code = child.wait()
    finally:
        # Restore the parent's signal disposition so wrap_command is safe
        # to call from library/CLI contexts (spec §5.16 invariant: wrapper
        # does not permanently alter caller signal handlers).
        _restore_signal_handlers(prior_handlers)

    # Spec §5.16 exit-code computation: on a forwarded signal, the
    # wrapper's exit code is ``128 + signum`` (so SIGINT→130, SIGTERM→143);
    # otherwise it is the child's actual exit code.
    sig_name = sig_received["name"]
    if sig_name is not None:
        rc = 128 + _signum_of(sig_name)
    else:
        rc = child_exit_code

    if not recording_enabled or run_id is None or run_dir is None:
        # ER-1 passthrough: init failed. Return the child's real exit code
        # without further recording work.
        return WrapperResult(
            run_id=None, exit_code=rc, cancelled_by_signal=sig_name
        )

    _run_post_drain_pipeline(
        run_id=run_id,
        run_dir=run_dir,
        rc=rc,
        exit_code=child_exit_code,
        sig_name=sig_name,
    )

    return WrapperResult(
        run_id=run_id, exit_code=rc, cancelled_by_signal=sig_name
    )
