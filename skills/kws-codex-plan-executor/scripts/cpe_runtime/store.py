"""Private, immutable run storage for the lean schema-4 CPE runtime."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contracts import (
    RUN_STATUSES,
    SCHEMA_VERSION,
    InputDocument,
    canonical_json,
    normalize_relative_path,
)


_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "workspace",
        "status",
        "document_set_path",
        "document_set_sha256",
        "manifest_sha256",
    }
)
_DOCUMENT_SET_KEYS = frozenset({"schema_version", "documents"})
_DOCUMENT_KEYS = frozenset(InputDocument.__dataclass_fields__)
_EVENT_KEYS = frozenset(
    {"event_id", "event_type", "payload", "prev_event_sha256", "event_sha256"}
)
_ARTIFACT_ROOTS = frozenset(
    {"maps", "briefs", "reports", "reviews", "verification", "logs", "result.json"}
)


@dataclass(frozen=True)
class RunPaths:
    root: Path
    manifest: Path
    events: Path
    result: Path
    inputs: Path
    maps: Path
    briefs: Path
    reports: Path
    reviews: Path
    verification: Path
    logs: Path
    outbox: Path


def _run_paths(root: Path) -> RunPaths:
    return RunPaths(
        root=root,
        manifest=root / "run.json",
        events=root / "events.jsonl",
        result=root / "result.json",
        inputs=root / "inputs",
        maps=root / "maps",
        briefs=root / "briefs",
        reports=root / "reports",
        reviews=root / "reviews",
        verification=root / "verification",
        logs=root / "logs",
        outbox=root / "outbox",
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdir_private(path: Path, *, parents: bool = False) -> None:
    path.mkdir(mode=0o700, parents=parents, exist_ok=False)
    os.chmod(path, 0o700)
    _fsync_directory(path.parent)


def _mkdir_artifact_parents(root: Path, parent: Path) -> None:
    relative = parent.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists():
            metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"artifact parent is not a private directory: {current}")
            continue
        _mkdir_private(current)


def _atomic_write_new(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"immutable path already exists: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while persisting immutable data")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    else:
        os.close(descriptor)
    try:
        if path.exists() or path.is_symlink():
            raise ValueError(f"immutable path already exists: {path}")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_workspace(workspace: Path) -> Path:
    try:
        resolved = workspace.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"workspace is unavailable: {workspace}") from exc
    if not resolved.is_dir():
        raise ValueError("workspace must be a directory")
    completed = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError("workspace must be inside a Git repository")
    return resolved


def _snapshot_sources(
    specs: Sequence[Path], plans: Sequence[Path], program_plan: Path | None
) -> tuple[tuple[str, str, Path, bytes], ...]:
    if not plans:
        raise ValueError("at least one plan is required")
    declared: list[tuple[str, str, Path]] = []
    declared.extend((f"spec-{index:02d}", "spec", source) for index, source in enumerate(specs, 1))
    declared.extend((f"plan-{index:02d}", "plan", source) for index, source in enumerate(plans, 1))
    if program_plan is not None:
        declared.append(("program-plan", "program_plan", program_plan))

    seen: set[Path] = set()
    snapshots: list[tuple[str, str, Path, bytes]] = []
    for document_id, role, source in declared:
        if not isinstance(source, Path):
            raise ValueError("input documents must be pathlib.Path values")
        try:
            if source.is_symlink():
                raise ValueError(f"input document must not be a symlink: {source}")
            resolved = source.expanduser().resolve(strict=True)
            metadata = resolved.stat()
        except OSError as exc:
            raise ValueError(f"input document is unavailable: {source}") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"input document must be a regular file: {source}")
        if resolved in seen:
            raise ValueError(f"duplicate input document path: {resolved}")
        seen.add(resolved)
        try:
            data = resolved.read_bytes()
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"input document is not UTF-8: {resolved}") from exc
        except OSError as exc:
            raise ValueError(f"input document is unreadable: {resolved}") from exc
        snapshots.append((document_id, role, resolved, data))
    return tuple(snapshots)


class RunStore:
    def __init__(self, *, codex_home: Path, run_id: str, paths: RunPaths):
        self.codex_home = codex_home
        self.run_id = run_id
        self.paths = paths

    @classmethod
    def create(
        cls,
        *,
        codex_home: Path,
        workspace: Path,
        specs: Sequence[Path],
        plans: Sequence[Path],
        program_plan: Path | None,
    ) -> "RunStore":
        workspace_path = _validate_workspace(workspace)
        sources = _snapshot_sources(specs, plans, program_plan)

        home = codex_home.expanduser()
        if not home.exists():
            _mkdir_private(home, parents=True)
        elif not home.is_dir() or home.is_symlink():
            raise ValueError("CODEX_HOME must be a directory")
        orchestrator = home / "orchestrator"
        if not orchestrator.exists():
            _mkdir_private(orchestrator)
        elif not orchestrator.is_dir() or orchestrator.is_symlink():
            raise ValueError("orchestrator root must be a directory")
        else:
            os.chmod(orchestrator, 0o700)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"cpe-{stamp}-{uuid.uuid4().hex[:12]}"
        paths = _run_paths(orchestrator / run_id)
        _mkdir_private(paths.root)
        for directory in (
            paths.inputs,
            paths.maps,
            paths.briefs,
            paths.reports,
            paths.reviews,
            paths.verification,
            paths.logs,
            paths.outbox,
        ):
            _mkdir_private(directory)

        documents: list[InputDocument] = []
        for input_order, (document_id, role, original_path, data) in enumerate(sources):
            filename = f"{document_id}.md"
            snapshot_path = f"inputs/{filename}"
            _atomic_write_new(paths.root / snapshot_path, data)
            documents.append(
                InputDocument(
                    document_id=document_id,
                    role=role,
                    original_path=str(original_path),
                    snapshot_path=snapshot_path,
                    sha256=_sha256(data),
                    byte_length=len(data),
                    input_order=input_order,
                )
            )

        document_set = {
            "schema_version": SCHEMA_VERSION,
            "documents": [document.to_json() for document in documents],
        }
        document_set_bytes = canonical_json(document_set)
        _atomic_write_new(paths.inputs / "document-set.json", document_set_bytes)
        _atomic_write_new(paths.events, b"")

        manifest_body: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "workspace": str(workspace_path),
            "status": "mapping",
            "document_set_path": "inputs/document-set.json",
            "document_set_sha256": _sha256(document_set_bytes),
        }
        manifest = {
            **manifest_body,
            "manifest_sha256": _sha256(canonical_json(manifest_body)),
        }
        _atomic_write_new(paths.manifest, canonical_json(manifest))
        return cls(codex_home=home, run_id=run_id, paths=paths)

    @classmethod
    def open(cls, *, codex_home: Path, run_id: str) -> "RunStore":
        if normalize_relative_path(run_id) != run_id or "/" in run_id:
            raise ValueError("run_id must be one normalized path component")
        home = codex_home.expanduser()
        paths = _run_paths(home / "orchestrator" / run_id)
        if not paths.root.is_dir() or paths.root.is_symlink():
            raise ValueError(f"run does not exist: {run_id}")
        store = cls(codex_home=home, run_id=run_id, paths=paths)
        store._load_manifest()
        store.document_set()
        store.validate_event_chain()
        return store

    def _load_manifest(self) -> dict[str, object]:
        try:
            raw = self.paths.manifest.read_bytes()
            manifest = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("run manifest is unreadable") from exc
        if not isinstance(manifest, dict) or frozenset(manifest) != _MANIFEST_KEYS:
            raise ValueError("run manifest has unexpected fields")
        if raw != canonical_json(manifest):
            raise ValueError("run manifest is not canonical JSON")
        digest = manifest.get("manifest_sha256")
        body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        if digest != _sha256(canonical_json(body)):
            raise ValueError("run manifest hash does not match")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("run manifest is not schema 4")
        if manifest.get("run_id") != self.run_id:
            raise ValueError("run manifest identity does not match its directory")
        if manifest.get("status") not in RUN_STATUSES:
            raise ValueError("run manifest status is invalid")
        return manifest

    def document_set(self) -> tuple[InputDocument, ...]:
        manifest = self._load_manifest()
        relative_path = manifest["document_set_path"]
        if relative_path != "inputs/document-set.json":
            raise ValueError("run manifest document-set path is invalid")
        path = self.paths.root / relative_path
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("document set is unreadable") from exc
        if _sha256(raw) != manifest["document_set_sha256"]:
            raise ValueError("document-set hash does not match the manifest")
        if raw != canonical_json(payload):
            raise ValueError("document set is not canonical JSON")
        if not isinstance(payload, dict) or frozenset(payload) != _DOCUMENT_SET_KEYS:
            raise ValueError("document set has unexpected fields")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("document set is not schema 4")
        values = payload.get("documents")
        if not isinstance(values, list):
            raise ValueError("document set must contain a document array")

        documents: list[InputDocument] = []
        for expected_order, value in enumerate(values):
            if not isinstance(value, dict) or frozenset(value) != _DOCUMENT_KEYS:
                raise ValueError("input document has unexpected fields")
            try:
                document = InputDocument(**value)
            except TypeError as exc:
                raise ValueError("input document field types are invalid") from exc
            if document.input_order != expected_order:
                raise ValueError("input document order is not contiguous")
            snapshot_relative = normalize_relative_path(document.snapshot_path)
            if not snapshot_relative.startswith("inputs/"):
                raise ValueError("input snapshot must remain below inputs")
            snapshot = self.paths.root / snapshot_relative
            try:
                metadata = snapshot.lstat()
                data = snapshot.read_bytes()
            except OSError as exc:
                raise ValueError("input snapshot is unreadable") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("input snapshot must be a regular file")
            if len(data) != document.byte_length or _sha256(data) != document.sha256:
                raise ValueError("input snapshot digest does not match its contract")
            documents.append(document)
        return tuple(documents)

    @staticmethod
    def _parse_events(raw: bytes) -> tuple[dict[str, object], ...]:
        if not raw:
            return ()
        events: list[dict[str, object]] = []
        previous: str | None = None
        for index, line in enumerate(raw.splitlines(keepends=True), 1):
            if not line.endswith(b"\n"):
                raise ValueError("event log ends with a partial record")
            content = line[:-1]
            try:
                event = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("event log contains invalid JSON") from exc
            if not isinstance(event, dict) or frozenset(event) != _EVENT_KEYS:
                raise ValueError("event has unexpected fields")
            if content != canonical_json(event):
                raise ValueError("event is not canonical JSON")
            if event.get("event_id") != f"E{index:06d}":
                raise ValueError("event IDs are not contiguous")
            event_type = event.get("event_type")
            if not isinstance(event_type, str) or not event_type:
                raise ValueError("event type must be a non-empty string")
            if not isinstance(event.get("payload"), dict):
                raise ValueError("event payload must be an object")
            if event.get("prev_event_sha256") != previous:
                raise ValueError("event previous hash does not match")
            digest = event.get("event_sha256")
            body = {key: value for key, value in event.items() if key != "event_sha256"}
            if not isinstance(digest, str) or digest != _sha256(canonical_json(body)):
                raise ValueError("event hash does not match")
            previous = digest
            events.append(event)
        return tuple(events)

    def append_event(
        self, event_type: str, payload: Mapping[str, object]
    ) -> dict[str, object]:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        if not isinstance(payload, Mapping):
            raise ValueError("event payload must be an object")
        payload_copy = dict(payload)
        try:
            canonical_json(payload_copy)
        except (TypeError, ValueError) as exc:
            raise ValueError("event payload must be canonical-JSON serializable") from exc

        descriptor = os.open(self.paths.events, os.O_RDWR | os.O_APPEND)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            events = self._parse_events(b"".join(chunks))
            previous = events[-1]["event_sha256"] if events else None
            body: dict[str, object] = {
                "event_id": f"E{len(events) + 1:06d}",
                "event_type": event_type,
                "payload": payload_copy,
                "prev_event_sha256": previous,
            }
            event = {**body, "event_sha256": _sha256(canonical_json(body))}
            line = canonical_json(event) + b"\n"
            view = memoryview(line)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short event append")
                view = view[written:]
            os.fsync(descriptor)
            return event
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def validate_event_chain(self) -> tuple[dict[str, object], ...]:
        descriptor = os.open(self.paths.events, os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return self._parse_events(b"".join(chunks))
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _artifact_target(self, relative_path: str, *, for_write: bool) -> tuple[str, Path]:
        normalized = normalize_relative_path(relative_path)
        if for_write:
            artifact_root = normalized.split("/", 1)[0]
            if artifact_root not in _ARTIFACT_ROOTS:
                raise ValueError("artifact path is outside an immutable artifact directory")
            if artifact_root == "result.json" and normalized != "result.json":
                raise ValueError("result.json is an artifact file, not a directory")
        target = self.paths.root / normalized
        return normalized, target

    def put_artifact(self, relative_path: str, data: bytes) -> Path:
        if not isinstance(data, bytes):
            raise ValueError("artifact data must be bytes")
        _, target = self._artifact_target(relative_path, for_write=True)
        descriptor = os.open(
            self.paths.events,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if target.exists() or target.is_symlink():
                try:
                    metadata = target.lstat()
                    current = target.read_bytes()
                except OSError as exc:
                    raise ValueError("existing artifact is unreadable") from exc
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("artifact target is not a regular file")
                if current == data:
                    return target
                raise ValueError("immutable artifact already exists with different bytes")
            _mkdir_artifact_parents(self.paths.root, target.parent)
            _atomic_write_new(target, data)
            return target
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def read_artifact(self, relative_path: str) -> bytes:
        _, target = self._artifact_target(relative_path, for_write=False)
        try:
            metadata = target.lstat()
            data = target.read_bytes()
        except OSError as exc:
            raise ValueError("artifact is unreadable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("artifact must be a regular file")
        return data

    def allocate_outbox(self, attempt_id: str) -> Path:
        normalized = normalize_relative_path(attempt_id)
        if "/" in normalized:
            raise ValueError("attempt_id must be one normalized path component")
        path = self.paths.outbox / normalized
        if path.exists() or path.is_symlink():
            raise ValueError(f"outbox already exists: {attempt_id}")
        _mkdir_private(path)
        return path

    def ingest_outbox(
        self, attempt_id: str, relative_paths: Sequence[str]
    ) -> tuple[str, ...]:
        normalized_attempt = normalize_relative_path(attempt_id)
        if "/" in normalized_attempt:
            raise ValueError("attempt_id must be one normalized path component")
        source_root = self.paths.outbox / normalized_attempt
        if not source_root.is_dir() or source_root.is_symlink():
            raise ValueError(f"outbox does not exist: {attempt_id}")
        ingested: list[str] = []
        for relative_path in relative_paths:
            normalized = normalize_relative_path(relative_path)
            if normalized in ingested:
                raise ValueError("outbox artifact paths must be unique")
            source = source_root / normalized
            try:
                current = source_root
                metadata = None
                for index, part in enumerate(Path(normalized).parts):
                    current = current / part
                    metadata = current.lstat()
                    if stat.S_ISLNK(metadata.st_mode):
                        raise ValueError(
                            f"outbox artifact path contains a symlink: {normalized}"
                        )
                    if index < len(Path(normalized).parts) - 1 and not stat.S_ISDIR(
                        metadata.st_mode
                    ):
                        raise ValueError(
                            f"outbox artifact parent is not a directory: {normalized}"
                        )
                data = source.read_bytes()
            except OSError as exc:
                raise ValueError(f"outbox artifact is unreadable: {normalized}") from exc
            assert metadata is not None
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"outbox artifact must be a regular file: {normalized}")
            self.put_artifact(normalized, data)
            ingested.append(normalized)
        return tuple(ingested)

    def replay(self) -> dict[str, object]:
        manifest = self._load_manifest()
        events = self.validate_event_chain()
        status = manifest["status"]
        for event in events:
            event_type = event["event_type"]
            if event_type == "map.generation_created":
                status = "running"
            elif event_type == "authority.opened":
                status = "waiting_authority"
            elif event_type == "authority.resolved":
                status = "running"
            elif event_type == "run.interrupted":
                status = "interrupted"
            elif event_type == "audit.reported":
                status = "final_audit"
            elif event_type == "run.completed":
                status = "completed"
            elif event_type == "run.failed":
                status = "failed"
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": status,
            "event_count": len(events),
            "last_event_sha256": events[-1]["event_sha256"] if events else None,
        }
