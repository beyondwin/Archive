"""Private, immutable run storage for the lean schema-4 CPE runtime."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
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
    DocumentRelationship,
    InputDocument,
    canonical_json,
    normalize_relative_path,
    validate_event_payload,
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
_EVENT_HEAD_KEYS = frozenset({"event_count", "last_event_sha256"})
_ARTIFACT_RECORD_KEYS = frozenset(
    {"artifact_id", "relative_path", "sha256", "byte_length"}
)
_ARTIFACT_ROOTS = frozenset(
    {"maps", "briefs", "reports", "reviews", "verification", "logs", "result.json"}
)


@dataclass(frozen=True)
class RunPaths:
    root: Path
    manifest: Path
    events: Path
    event_head: Path
    artifact_index: Path
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
        event_head=root / "events.head.json",
        artifact_index=root / "artifacts.jsonl",
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


def _atomic_replace_private(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while persisting durable commitment")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    else:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read_private_installed_file(path: Path) -> bytes:
    """Read one crash-installed file without accepting type, link, or mode drift."""

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ValueError("unindexed artifact must be a private regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("unindexed artifact must be a private regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ValueError("unindexed artifact mode must remain private")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        try:
            current = path.lstat()
        except OSError as exc:
            raise ValueError("unindexed artifact changed while reconciling") from exc
        if (
            stat.S_ISLNK(current.st_mode)
            or current.st_dev != metadata.st_dev
            or current.st_ino != metadata.st_ino
            or stat.S_IMODE(current.st_mode) != 0o600
        ):
            raise ValueError("unindexed artifact changed while reconciling")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


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


def _normalize_document_relationships(
    sources: Sequence[tuple[str, str, Path, bytes]],
    relationships: Mapping[str, Sequence[Mapping[str, str]]] | None,
) -> dict[str, tuple[DocumentRelationship, ...]]:
    document_ids = {document_id for document_id, _, _, _ in sources}
    if relationships is None:
        return {document_id: () for document_id in document_ids}
    if not isinstance(relationships, Mapping):
        raise ValueError("document_relationships must be an object keyed by document ID")
    unknown = set(relationships) - document_ids
    if unknown:
        raise ValueError(f"relationships name unknown documents: {sorted(unknown)}")

    normalized: dict[str, tuple[DocumentRelationship, ...]] = {}
    for document_id in document_ids:
        values = relationships.get(document_id, ())
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError("document relationships must be an array")
        items: list[DocumentRelationship] = []
        for value in values:
            if not isinstance(value, Mapping) or frozenset(value) != frozenset(
                {"relationship_type", "target_document_id"}
            ):
                raise ValueError("document relationship fields are invalid")
            relationship_type = value["relationship_type"]
            target_document_id = value["target_document_id"]
            if (
                not isinstance(relationship_type, str)
                or not relationship_type.strip()
                or len(relationship_type) > 128
            ):
                raise ValueError("relationship_type must be a bounded non-empty string")
            if (
                not isinstance(target_document_id, str)
                or not target_document_id
                or len(target_document_id) > 256
            ):
                raise ValueError(
                    "target_document_id must be a bounded non-empty string"
                )
            if target_document_id not in document_ids:
                raise ValueError(
                    f"relationship target is unknown: {target_document_id}"
                )
            if target_document_id == document_id:
                raise ValueError("document relationship cannot target itself")
            item = DocumentRelationship(relationship_type, target_document_id)
            if item in items:
                raise ValueError("document relationships must be unique")
            items.append(item)
        normalized[document_id] = tuple(sorted(items))
    return normalized


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
        document_relationships: Mapping[
            str, Sequence[Mapping[str, str]]
        ] | None = None,
    ) -> "RunStore":
        workspace_path = _validate_workspace(workspace)
        sources = _snapshot_sources(specs, plans, program_plan)
        relationships = _normalize_document_relationships(
            sources, document_relationships
        )

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
                    relationships=relationships[document_id],
                )
            )

        document_set = {
            "schema_version": SCHEMA_VERSION,
            "documents": [document.to_json() for document in documents],
        }
        document_set_bytes = canonical_json(document_set)
        _atomic_write_new(paths.inputs / "document-set.json", document_set_bytes)
        _atomic_write_new(paths.events, b"")
        _atomic_write_new(
            paths.event_head,
            canonical_json({"event_count": 0, "last_event_sha256": None}),
        )
        _atomic_write_new(paths.artifact_index, b"")

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
        store = cls(codex_home=home, run_id=run_id, paths=paths)
        store.append_event(
            "run.created",
            {"run_id": run_id, "manifest_sha256": manifest["manifest_sha256"]},
        )
        store.append_event(
            "documents.snapshotted",
            {
                "document_set_sha256": manifest["document_set_sha256"],
                "document_ids": [document.document_id for document in documents],
                "snapshot_sha256s": [document.sha256 for document in documents],
            },
        )
        return store

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
        store._reconcile_content_addressed_publication_manifests()
        store._validate_artifacts()
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
            relationship_values = value.get("relationships")
            if not isinstance(relationship_values, list):
                raise ValueError("input document relationships must be an array")
            relationships: list[DocumentRelationship] = []
            for relationship_value in relationship_values:
                if (
                    not isinstance(relationship_value, dict)
                    or frozenset(relationship_value)
                    != frozenset({"relationship_type", "target_document_id"})
                ):
                    raise ValueError("input document relationship fields are invalid")
                relationship_type = relationship_value.get("relationship_type")
                target_document_id = relationship_value.get("target_document_id")
                if (
                    not isinstance(relationship_type, str)
                    or not relationship_type.strip()
                    or len(relationship_type) > 128
                    or not isinstance(target_document_id, str)
                    or not target_document_id
                ):
                    raise ValueError("input document relationship values are invalid")
                relationship = DocumentRelationship(
                    relationship_type, target_document_id
                )
                if relationship in relationships:
                    raise ValueError("input document relationships must be unique")
                relationships.append(relationship)
            if relationships != sorted(relationships):
                raise ValueError("input document relationships are not canonical")
            try:
                document = InputDocument(
                    **{key: item for key, item in value.items() if key != "relationships"},
                    relationships=tuple(relationships),
                )
            except TypeError as exc:
                raise ValueError("input document field types are invalid") from exc
            if (
                not isinstance(document.document_id, str)
                or not document.document_id
                or not isinstance(document.role, str)
                or document.role not in {"spec", "plan", "program_plan"}
                or not isinstance(document.original_path, str)
                or not document.original_path
                or not isinstance(document.sha256, str)
                or len(document.sha256) != 64
                or not isinstance(document.byte_length, int)
                or isinstance(document.byte_length, bool)
                or document.byte_length < 0
                or not isinstance(document.input_order, int)
                or isinstance(document.input_order, bool)
            ):
                raise ValueError("input document field values are invalid")
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
        document_ids = {document.document_id for document in documents}
        if len(document_ids) != len(documents):
            raise ValueError("input document IDs must be unique")
        for document in documents:
            for relationship in document.relationships:
                if (
                    relationship.target_document_id not in document_ids
                    or relationship.target_document_id == document.document_id
                ):
                    raise ValueError("input document relationship target is invalid")
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
            payload = event.get("payload")
            if not isinstance(event_type, str) or not isinstance(payload, dict):
                raise ValueError("event payload must be an object")
            if validate_event_payload(event_type, payload) != payload:
                raise ValueError("event payload is not canonical")
            if event.get("prev_event_sha256") != previous:
                raise ValueError("event previous hash does not match")
            digest = event.get("event_sha256")
            body = {key: value for key, value in event.items() if key != "event_sha256"}
            if not isinstance(digest, str) or digest != _sha256(canonical_json(body)):
                raise ValueError("event hash does not match")
            previous = digest
            events.append(event)
        return tuple(events)

    def _read_event_head(self) -> dict[str, object]:
        try:
            metadata = self.paths.event_head.lstat()
            raw = self.paths.event_head.read_bytes()
            head = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("event head commitment is unreadable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("event head commitment must be a regular file")
        if (
            not isinstance(head, dict)
            or frozenset(head) != _EVENT_HEAD_KEYS
            or raw != canonical_json(head)
        ):
            raise ValueError("event head commitment is invalid")
        count = head.get("event_count")
        digest = head.get("last_event_sha256")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or (digest is not None and (not isinstance(digest, str) or len(digest) != 64))
        ):
            raise ValueError("event head commitment fields are invalid")
        return head

    def _validate_event_head(
        self, events: Sequence[Mapping[str, object]]
    ) -> None:
        head = self._read_event_head()
        expected_digest = events[-1]["event_sha256"] if events else None
        if (
            head["event_count"] != len(events)
            or head["last_event_sha256"] != expected_digest
        ):
            raise ValueError("event log does not match its durable head commitment")

    def append_event(
        self, event_type: str, payload: Mapping[str, object]
    ) -> dict[str, object]:
        payload_copy = validate_event_payload(event_type, payload)

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
            self._validate_event_head(events)
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
            _atomic_replace_private(
                self.paths.event_head,
                canonical_json(
                    {
                        "event_count": len(events) + 1,
                        "last_event_sha256": event["event_sha256"],
                    }
                ),
            )
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
            events = self._parse_events(b"".join(chunks))
            self._validate_event_head(events)
            return events
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    @staticmethod
    def _parse_artifact_index(raw: bytes) -> tuple[dict[str, object], ...]:
        if not raw:
            return ()
        records: list[dict[str, object]] = []
        paths: set[str] = set()
        for index, line in enumerate(raw.splitlines(keepends=True), 1):
            if not line.endswith(b"\n"):
                raise ValueError("artifact index ends with a partial record")
            content = line[:-1]
            try:
                record = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("artifact index contains invalid JSON") from exc
            if (
                not isinstance(record, dict)
                or frozenset(record) != _ARTIFACT_RECORD_KEYS
                or content != canonical_json(record)
                or record.get("artifact_id") != f"A{index:06d}"
            ):
                raise ValueError("artifact index record is invalid")
            relative_path = record.get("relative_path")
            digest = record.get("sha256")
            byte_length = record.get("byte_length")
            if (
                not isinstance(relative_path, str)
                or normalize_relative_path(relative_path) != relative_path
                or relative_path in paths
                or not isinstance(digest, str)
                or len(digest) != 64
                or not isinstance(byte_length, int)
                or isinstance(byte_length, bool)
                or byte_length < 0
            ):
                raise ValueError("artifact index record fields are invalid")
            artifact_root = relative_path.split("/", 1)[0]
            if artifact_root not in _ARTIFACT_ROOTS or (
                artifact_root == "result.json" and relative_path != "result.json"
            ):
                raise ValueError("artifact index path is outside managed artifacts")
            paths.add(relative_path)
            records.append(record)
        return tuple(records)

    def _artifact_records(self) -> tuple[dict[str, object], ...]:
        descriptor = os.open(
            self.paths.artifact_index,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return self._parse_artifact_index(b"".join(chunks))
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _read_indexed_artifact(
        self, relative_path: str, record: Mapping[str, object]
    ) -> bytes:
        target = self.paths.root / relative_path
        try:
            metadata = target.lstat()
            data = target.read_bytes()
        except OSError as exc:
            raise ValueError("indexed artifact is unreadable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("indexed artifact must be a regular file")
        if len(data) != record["byte_length"] or _sha256(data) != record["sha256"]:
            raise ValueError("artifact digest does not match its durable index")
        return data

    def _read_physical_indexed_artifact(
        self,
        relative_path: str,
        records: Mapping[str, Mapping[str, object]],
    ) -> bytes:
        """Read one physical artifact without re-entering logical publication lookup."""

        record = records.get(relative_path)
        if record is None:
            raise ValueError("accepted publication artifact is not indexed")
        return self._read_indexed_artifact(relative_path, record)

    def _validate_artifacts(self) -> tuple[dict[str, object], ...]:
        records = self._artifact_records()
        indexed = {str(record["relative_path"]): record for record in records}
        for relative_path, record in indexed.items():
            self._read_indexed_artifact(relative_path, record)

        present: set[str] = set()
        for root_name in sorted(_ARTIFACT_ROOTS - {"result.json"}):
            root = self.paths.root / root_name
            if not root.is_dir() or root.is_symlink():
                raise ValueError("managed artifact root is not a private directory")
            for path in root.rglob("*"):
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError("managed artifact tree contains a symlink")
                if stat.S_ISREG(metadata.st_mode):
                    present.add(path.relative_to(self.paths.root).as_posix())
                elif not stat.S_ISDIR(metadata.st_mode):
                    raise ValueError("managed artifact tree contains a special file")
        if self.paths.result.exists() or self.paths.result.is_symlink():
            metadata = self.paths.result.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("result artifact must be a regular file")
            present.add("result.json")
        if present != set(indexed):
            raise ValueError("managed artifacts do not match their durable index")
        return records

    def _artifact_target(self, relative_path: str, *, for_write: bool) -> tuple[str, Path]:
        normalized = normalize_relative_path(relative_path)
        artifact_root = normalized.split("/", 1)[0]
        if artifact_root not in _ARTIFACT_ROOTS:
            if not for_write and artifact_root == "inputs":
                return normalized, self.paths.root / normalized
            raise ValueError("artifact path is outside an immutable artifact directory")
        if artifact_root == "result.json" and normalized != "result.json":
            raise ValueError("result.json is an artifact file, not a directory")
        target = self.paths.root / normalized
        return normalized, target

    @staticmethod
    def _validate_publication_manifest(
        raw: bytes, relative_path: str
    ) -> dict[str, object]:
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("accepted publication manifest is unreadable") from exc
        parts = Path(relative_path).parts
        if (
            len(parts) != 5
            or parts[0] != "maps"
            or not parts[1].startswith("generation-")
            or parts[2] != "attempts"
            or parts[4] != "accepted.json"
        ):
            raise ValueError("accepted publication manifest path is invalid")
        generation_id = parts[1]
        publication_id = parts[3]
        if (
            not isinstance(manifest, dict)
            or raw != canonical_json(manifest)
            or frozenset(manifest)
            != frozenset(
                {
                    "schema_version",
                    "generation_id",
                    "publication_id",
                    "program_map_sha256",
                    "artifacts",
                }
            )
            or manifest.get("schema_version") != 1
            or manifest.get("generation_id") != generation_id
            or manifest.get("publication_id") != publication_id
            or len(publication_id) != 64
            or any(character not in "0123456789abcdef" for character in publication_id)
        ):
            raise ValueError("accepted publication manifest is invalid")
        artifacts = manifest.get("artifacts")
        program_map_sha256 = manifest.get("program_map_sha256")
        if (
            not isinstance(artifacts, dict)
            or not artifacts
            or not isinstance(program_map_sha256, str)
            or len(program_map_sha256) != 64
        ):
            raise ValueError("accepted publication identity is invalid")
        commitment: dict[str, dict[str, object]] = {}
        for logical_path, descriptor in artifacts.items():
            if (
                not isinstance(logical_path, str)
                or normalize_relative_path(logical_path) != logical_path
                or not isinstance(descriptor, dict)
                or frozenset(descriptor)
                != frozenset({"relative_path", "sha256", "byte_length"})
            ):
                raise ValueError("accepted publication artifact record is invalid")
            physical_path = descriptor.get("relative_path")
            digest = descriptor.get("sha256")
            byte_length = descriptor.get("byte_length")
            expected_physical_path = (
                f"maps/{generation_id}/attempts/{publication_id}/artifacts/"
                f"{logical_path}"
            )
            if (
                physical_path != expected_physical_path
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or not isinstance(byte_length, int)
                or isinstance(byte_length, bool)
                or byte_length < 0
            ):
                raise ValueError("accepted publication artifact binding is invalid")
            commitment[logical_path] = {
                "sha256": digest,
                "byte_length": byte_length,
            }
        expected_publication_id = _sha256(
            b"cpe-map-publication-v1\0" + canonical_json(commitment)
        )
        program_path = f"maps/{generation_id}/program-map.json"
        program_descriptor = artifacts.get(program_path)
        if (
            expected_publication_id != publication_id
            or not isinstance(program_descriptor, dict)
            or program_descriptor.get("sha256") != program_map_sha256
        ):
            raise ValueError("accepted publication commitment does not match")
        return manifest

    def _reconcile_content_addressed_publication_manifests(self) -> None:
        """Index a fully validated accepted manifest left by file-before-index crash."""

        records = self._artifact_records()
        indexed = {str(record["relative_path"]): record for record in records}
        for path in sorted(self.paths.maps.rglob("accepted.json")):
            relative_path = path.relative_to(self.paths.root).as_posix()
            if relative_path in indexed:
                continue
            raw = _read_private_installed_file(path)
            manifest = self._validate_publication_manifest(raw, relative_path)
            artifacts = manifest["artifacts"]
            assert isinstance(artifacts, dict)
            for descriptor in artifacts.values():
                assert isinstance(descriptor, dict)
                physical_path = str(descriptor["relative_path"])
                physical_record = indexed.get(physical_path)
                if physical_record is None:
                    raise ValueError(
                        "accepted publication references an unindexed artifact"
                    )
                data = self._read_indexed_artifact(physical_path, physical_record)
                if (
                    _sha256(data) != descriptor["sha256"]
                    or len(data) != descriptor["byte_length"]
                ):
                    raise ValueError("accepted publication artifact digest does not match")
            self.put_artifact(relative_path, raw)
            indexed = {
                str(record["relative_path"]): record
                for record in self._artifact_records()
            }

    def put_artifact(self, relative_path: str, data: bytes) -> Path:
        if not isinstance(data, bytes):
            raise ValueError("artifact data must be bytes")
        normalized, target = self._artifact_target(relative_path, for_write=True)
        descriptor = os.open(
            self.paths.artifact_index,
            os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            records = self._parse_artifact_index(b"".join(chunks))
            indexed = {str(record["relative_path"]): record for record in records}
            if target.exists() or target.is_symlink():
                record = indexed.get(normalized)
                if record is None:
                    current = _read_private_installed_file(target)
                    if current != data:
                        raise ValueError(
                            "unindexed artifact already exists with different bytes"
                        )
                    record = {
                        "artifact_id": f"A{len(records) + 1:06d}",
                        "relative_path": normalized,
                        "sha256": _sha256(data),
                        "byte_length": len(data),
                    }
                    line = canonical_json(record) + b"\n"
                    view = memoryview(line)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OSError("short artifact index append")
                        view = view[written:]
                    os.fsync(descriptor)
                    return target
                current = self._read_indexed_artifact(normalized, record)
                if current == data:
                    return target
                raise ValueError("immutable artifact already exists with different bytes")
            if normalized in indexed:
                raise ValueError("indexed artifact file is missing")
            _mkdir_artifact_parents(self.paths.root, target.parent)
            _atomic_write_new(target, data)
            record: dict[str, object] = {
                "artifact_id": f"A{len(records) + 1:06d}",
                "relative_path": normalized,
                "sha256": _sha256(data),
                "byte_length": len(data),
            }
            line = canonical_json(record) + b"\n"
            view = memoryview(line)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short artifact index append")
                view = view[written:]
            os.fsync(descriptor)
            return target
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def read_artifact(self, relative_path: str) -> bytes:
        normalized, target = self._artifact_target(relative_path, for_write=False)
        if normalized.startswith("inputs/"):
            documents = {
                document.snapshot_path: document for document in self.document_set()
            }
            if normalized not in documents:
                raise ValueError("input path is not an immutable document snapshot")
            try:
                return target.read_bytes()
            except OSError as exc:
                raise ValueError("input snapshot is unreadable") from exc
        records = {
            str(record["relative_path"]): record
            for record in self._artifact_records()
        }
        published: list[bytes] = []
        for event in self.validate_event_chain():
            if event["event_type"] != "map.generation_created":
                continue
            payload = event["payload"]
            manifest_path = payload.get("publication_manifest_path")
            manifest_digest = payload.get("publication_manifest_sha256")
            if not isinstance(manifest_path, str) or not isinstance(
                manifest_digest, str
            ):
                raise ValueError("map generation event omits its accepted publication")
            raw = self._read_physical_indexed_artifact(manifest_path, records)
            if _sha256(raw) != manifest_digest:
                raise ValueError("accepted publication event digest does not match")
            manifest = self._validate_publication_manifest(raw, manifest_path)
            generation_id = manifest.get("generation_id")
            publication_id = manifest.get("publication_id")
            artifacts = manifest.get("artifacts")
            if (
                not isinstance(generation_id, str)
                or generation_id != payload.get("generation_id")
                or manifest.get("program_map_sha256") != payload.get("map_sha256")
                or not isinstance(publication_id, str)
                or not isinstance(artifacts, dict)
            ):
                raise ValueError("accepted publication identity is invalid")
            descriptor = artifacts.get(normalized)
            if descriptor is None:
                continue
            if (
                not isinstance(descriptor, dict)
                or frozenset(descriptor)
                != frozenset({"relative_path", "sha256", "byte_length"})
            ):
                raise ValueError("accepted publication artifact record is invalid")
            physical_path = descriptor.get("relative_path")
            digest = descriptor.get("sha256")
            byte_length = descriptor.get("byte_length")
            expected_physical_path = (
                f"maps/{generation_id}/attempts/{publication_id}/artifacts/"
                f"{normalized}"
            )
            if (
                not isinstance(physical_path, str)
                or physical_path != expected_physical_path
                or not isinstance(digest, str)
                or len(digest) != 64
                or not isinstance(byte_length, int)
                or isinstance(byte_length, bool)
                or byte_length < 0
            ):
                raise ValueError("accepted publication artifact binding is invalid")
            data = self._read_physical_indexed_artifact(physical_path, records)
            if len(data) != byte_length or _sha256(data) != digest:
                raise ValueError("accepted publication artifact digest does not match")
            published.append(data)
        if len(published) > 1:
            raise ValueError("artifact is published by multiple accepted generations")
        if published:
            return published[0]
        record = records.get(normalized)
        if record is None:
            raise ValueError("artifact has no durable digest record")
        return self._read_indexed_artifact(normalized, record)

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

    def discard_outbox(self, attempt_id: str) -> None:
        """Atomically detach and safely remove one rejected or consumed outbox."""

        normalized_attempt = normalize_relative_path(attempt_id)
        if "/" in normalized_attempt:
            raise ValueError("attempt_id must be one normalized path component")
        source = self.paths.outbox / normalized_attempt
        try:
            metadata = source.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValueError(f"outbox is unavailable: {attempt_id}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("outbox discard target must be a real directory")
        detached = self.paths.outbox / f".discarded-{uuid.uuid4().hex}"
        os.replace(source, detached)
        _fsync_directory(self.paths.outbox)
        shutil.rmtree(detached)
        _fsync_directory(self.paths.outbox)

    def replay(self) -> dict[str, object]:
        manifest = self._load_manifest()
        self.document_set()
        events = self.validate_event_chain()
        self._validate_artifacts()
        status = manifest["status"]
        for event in events:
            event_type = event["event_type"]
            if event_type == "map.generation_created":
                status = (
                    "waiting_authority"
                    if event["payload"].get("authority_ids")
                    else "running"
                )
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
