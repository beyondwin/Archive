"""AgentLens persistent store layout helpers (spec §S1.6.4–§S1.6.7)."""
from __future__ import annotations

from .lock import LockTimeoutError, file_lock
from .manifest import (
    ManifestEntry,
    SealPhase,
    collect_files,
    init_manifest,
    mark_recording_incomplete,
    seal,
    seal_final,
    seal_pre_eval,
    verify,
)
from .paths import (
    agentlens_home,
    current_run_marker,
    current_runs_dir,
    run_dir,
    runs_root,
    safe_label_path,
    workspace_dir,
    workspace_local,
)
from .writer import (
    WriteError,
    append_event,
    atomic_write_json,
    write_final,
    write_run_meta,
    write_workspace_pointer,
)

__all__ = [
    "LockTimeoutError",
    "ManifestEntry",
    "SealPhase",
    "WriteError",
    "agentlens_home",
    "append_event",
    "atomic_write_json",
    "collect_files",
    "current_run_marker",
    "current_runs_dir",
    "file_lock",
    "init_manifest",
    "mark_recording_incomplete",
    "run_dir",
    "runs_root",
    "safe_label_path",
    "seal",
    "seal_final",
    "seal_pre_eval",
    "verify",
    "workspace_dir",
    "workspace_local",
    "write_final",
    "write_run_meta",
    "write_workspace_pointer",
]
