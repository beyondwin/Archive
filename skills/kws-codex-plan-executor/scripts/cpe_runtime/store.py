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
from .contracts import RUN_STATUSES, SCHEMA_VERSION, InputDocument, canonical_json, normalize_relative_path, validate_event_payload
_MANIFEST_KEYS = frozenset({'schema_version', 'run_id', 'workspace', 'status', 'document_set_path', 'document_set_sha256', 'manifest_sha256'})
_DOCUMENT_SET_KEYS = frozenset({'schema_version', 'documents'})
_DOCUMENT_KEYS = frozenset(InputDocument.__dataclass_fields__)
_EVENT_KEYS = frozenset({'event_id', 'event_type', 'payload', 'prev_event_sha256', 'event_sha256'})
_ARTIFACT_RECORD_KEYS = frozenset({'artifact_id', 'relative_path', 'sha256', 'byte_length'})
_ARTIFACT_TOMBSTONE_KEYS = frozenset({'artifact_id', 'record_type', 'relative_path', 'prior_artifact_id', 'sha256', 'byte_length'})
UNSELECTED_MAPPING_PUBLICATION_CAP = 1
_ARTIFACT_ROOTS = frozenset({'maps', 'briefs', 'reports', 'reviews', 'verification', 'logs', 'result.json'})
_AUTONOMY_DECISION_KEYS = frozenset({'decision_id', 'issue', 'alternatives', 'selected', 'strategy_key', 'rationale', 'evidence_paths', 'affected_tasks', 'reversible', 'created_at'})

@dataclass(frozen=True)
class RunPaths:
    root: Path
    manifest: Path
    events: Path
    artifact_index: Path
    autonomy_decisions: Path
    writer_lease: Path
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
    return RunPaths(root=root, manifest=root / 'run.json', events=root / 'events.jsonl', artifact_index=root / 'artifacts.jsonl', autonomy_decisions=root / 'autonomy-decisions.jsonl', writer_lease=root / 'writer.lease', result=root / 'result.json', inputs=root / 'inputs', maps=root / 'maps', briefs=root / 'briefs', reports=root / 'reports', reviews=root / 'reviews', verification=root / 'verification', logs=root / 'logs', outbox=root / 'outbox')

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def _mkdir_private(path: Path, *, parents: bool=False) -> None:
    path.mkdir(mode=448, parents=parents, exist_ok=False)
    os.chmod(path, 448)
    _fsync_directory(path.parent)

def _mkdir_artifact_parents(root: Path, parent: Path) -> None:
    relative = parent.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists():
            metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f'artifact parent is not a private directory: {current}')
            continue
        _mkdir_private(current)

def _atomic_write_new(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f'immutable path already exists: {path}')
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 384)
    try:
        os.fchmod(descriptor, 384)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError('short write while persisting immutable data')
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
            raise ValueError(f'immutable path already exists: {path}')
        os.replace(temporary, path)
        os.chmod(path, 384)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)

def _read_private_installed_file(path: Path) -> bytes:
    """Read one crash-installed file without accepting type, link, or mode drift."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except OSError as exc:
        raise ValueError('unindexed artifact must be a private regular file') from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError('unindexed artifact must be a private regular file')
        if stat.S_IMODE(metadata.st_mode) != 384:
            raise ValueError('unindexed artifact mode must remain private')
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        try:
            current = path.lstat()
        except OSError as exc:
            raise ValueError('unindexed artifact changed while reconciling') from exc
        if stat.S_ISLNK(current.st_mode) or current.st_dev != metadata.st_dev or current.st_ino != metadata.st_ino or (stat.S_IMODE(current.st_mode) != 384):
            raise ValueError('unindexed artifact changed while reconciling')
        return b''.join(chunks)
    finally:
        os.close(descriptor)

def _validate_workspace(workspace: Path) -> Path:
    try:
        resolved = workspace.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f'workspace is unavailable: {workspace}') from exc
    if not resolved.is_dir():
        raise ValueError('workspace must be a directory')
    completed = subprocess.run(['git', '-C', str(resolved), 'rev-parse', '--show-toplevel'], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise ValueError('workspace must be inside a Git repository')
    return resolved

def _snapshot_sources(specs: Sequence[Path], plans: Sequence[Path], program_plan: Path | None) -> tuple[tuple[str, str, Path, bytes], ...]:
    if not plans:
        raise ValueError('at least one plan is required')
    declared: list[tuple[str, str, Path]] = []
    declared.extend(((f'spec-{index:02d}', 'spec', source) for index, source in enumerate(specs, 1)))
    declared.extend(((f'plan-{index:02d}', 'plan', source) for index, source in enumerate(plans, 1)))
    if program_plan is not None:
        declared.append(('program-plan', 'program_plan', program_plan))
    seen: set[Path] = set()
    snapshots: list[tuple[str, str, Path, bytes]] = []
    for document_id, role, source in declared:
        if not isinstance(source, Path):
            raise ValueError('input documents must be pathlib.Path values')
        try:
            if source.is_symlink():
                raise ValueError(f'input document must not be a symlink: {source}')
            resolved = source.expanduser().resolve(strict=True)
            metadata = resolved.stat()
        except OSError as exc:
            raise ValueError(f'input document is unavailable: {source}') from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f'input document must be a regular file: {source}')
        if resolved in seen:
            raise ValueError(f'duplicate input document path: {resolved}')
        seen.add(resolved)
        try:
            data = resolved.read_bytes()
            data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError(f'input document is not UTF-8: {resolved}') from exc
        except OSError as exc:
            raise ValueError(f'input document is unreadable: {resolved}') from exc
        snapshots.append((document_id, role, resolved, data))
    return tuple(snapshots)

class RunStore:

    def __init__(self, *, codex_home: Path, run_id: str, paths: RunPaths):
        self.codex_home = codex_home
        self.run_id = run_id
        self.paths = paths

    @classmethod
    def create(cls, *, codex_home: Path, workspace: Path, specs: Sequence[Path], plans: Sequence[Path], program_plan: Path | None) -> 'RunStore':
        workspace_path = _validate_workspace(workspace)
        sources = _snapshot_sources(specs, plans, program_plan)
        home = codex_home.expanduser()
        if not home.exists():
            _mkdir_private(home, parents=True)
        elif not home.is_dir() or home.is_symlink():
            raise ValueError('CODEX_HOME must be a directory')
        orchestrator = home / 'orchestrator'
        if not orchestrator.exists():
            _mkdir_private(orchestrator)
        elif not orchestrator.is_dir() or orchestrator.is_symlink():
            raise ValueError('orchestrator root must be a directory')
        else:
            os.chmod(orchestrator, 448)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run_id = f'cpe-{stamp}-{uuid.uuid4().hex[:12]}'
        paths = _run_paths(orchestrator / run_id)
        _mkdir_private(paths.root)
        for directory in (paths.inputs, paths.maps, paths.briefs, paths.reports, paths.reviews, paths.verification, paths.logs, paths.outbox):
            _mkdir_private(directory)
        documents: list[InputDocument] = []
        for input_order, (document_id, role, original_path, data) in enumerate(sources):
            filename = f'{document_id}.md'
            snapshot_path = f'inputs/{filename}'
            _atomic_write_new(paths.root / snapshot_path, data)
            documents.append(InputDocument(document_id=document_id, role=role, original_path=str(original_path), snapshot_path=snapshot_path, sha256=_sha256(data), byte_length=len(data), input_order=input_order))
        document_set = {'schema_version': SCHEMA_VERSION, 'documents': [document.to_json() for document in documents]}
        document_set_bytes = canonical_json(document_set)
        _atomic_write_new(paths.inputs / 'document-set.json', document_set_bytes)
        _atomic_write_new(paths.events, b'')
        _atomic_write_new(paths.artifact_index, b'')
        _atomic_write_new(paths.autonomy_decisions, b'')
        _atomic_write_new(paths.writer_lease, b'')
        manifest_body: dict[str, object] = {'schema_version': SCHEMA_VERSION, 'run_id': run_id, 'workspace': str(workspace_path), 'status': 'mapping', 'document_set_path': 'inputs/document-set.json', 'document_set_sha256': _sha256(document_set_bytes)}
        manifest = {**manifest_body, 'manifest_sha256': _sha256(canonical_json(manifest_body))}
        _atomic_write_new(paths.manifest, canonical_json(manifest))
        store = cls(codex_home=home, run_id=run_id, paths=paths)
        store.append_event('run.created', {'run_id': run_id, 'manifest_sha256': manifest['manifest_sha256']})
        store.append_event('documents.snapshotted', {'document_set_sha256': manifest['document_set_sha256'], 'document_ids': [document.document_id for document in documents], 'snapshot_sha256s': [document.sha256 for document in documents]})
        return store

    @classmethod
    def open(cls, *, codex_home: Path, run_id: str, read_only: bool=False) -> 'RunStore':
        if normalize_relative_path(run_id) != run_id or '/' in run_id:
            raise ValueError('run_id must be one normalized path component')
        home = codex_home.expanduser()
        paths = _run_paths(home / 'orchestrator' / run_id)
        if not paths.root.is_dir() or paths.root.is_symlink():
            raise ValueError(f'run does not exist: {run_id}')
        store = cls(codex_home=home, run_id=run_id, paths=paths)
        store._load_manifest()
        store.document_set()
        store.validate_event_chain()
        store.autonomy_decisions()
        if not read_only:
            store.reconcile_autonomy_events()
            store.prune_unselected_mapping_publications()
        for record in store._artifact_records():
            store._read_record(record)
        for event in store.validate_event_chain():
            if event['event_type'] == 'map.generation_created' and event['payload']['generation_id'] != 'generation-0001':
                store.document_set_for_generation(str(event['payload']['generation_id']))
        store.pending_input_revision()
        return store

    def _load_manifest(self) -> dict[str, object]:
        try:
            raw = self.paths.manifest.read_bytes()
            manifest = json.loads(raw.decode('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('run manifest is unreadable') from exc
        if not isinstance(manifest, dict) or frozenset(manifest) != _MANIFEST_KEYS:
            raise ValueError('run manifest has unexpected fields')
        if raw != canonical_json(manifest):
            raise ValueError('run manifest is not canonical JSON')
        digest = manifest.get('manifest_sha256')
        body = {key: value for key, value in manifest.items() if key != 'manifest_sha256'}
        if digest != _sha256(canonical_json(body)):
            raise ValueError('run manifest hash does not match')
        if manifest.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('run manifest is not schema 4')
        if manifest.get('run_id') != self.run_id:
            raise ValueError('run manifest identity does not match its directory')
        if manifest.get('status') not in RUN_STATUSES:
            raise ValueError('run manifest status is invalid')
        return manifest

    def document_set(self) -> tuple[InputDocument, ...]:
        manifest = self._load_manifest()
        relative_path = manifest['document_set_path']
        if relative_path != 'inputs/document-set.json':
            raise ValueError('run manifest document-set path is invalid')
        path = self.paths.root / relative_path
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('document set is unreadable') from exc
        if _sha256(raw) != manifest['document_set_sha256']:
            raise ValueError('document-set hash does not match the manifest')
        if raw != canonical_json(payload):
            raise ValueError('document set is not canonical JSON')
        if not isinstance(payload, dict) or frozenset(payload) != _DOCUMENT_SET_KEYS:
            raise ValueError('document set has unexpected fields')
        if payload.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('document set is not schema 4')
        values = payload.get('documents')
        if not isinstance(values, list):
            raise ValueError('document set must contain a document array')
        documents: list[InputDocument] = []
        for expected_order, value in enumerate(values):
            if not isinstance(value, dict) or frozenset(value) != _DOCUMENT_KEYS:
                raise ValueError('input document has unexpected fields')
            try:
                document = InputDocument(**value)
            except TypeError as exc:
                raise ValueError('input document field types are invalid') from exc
            if not isinstance(document.document_id, str) or not document.document_id or (not isinstance(document.role, str)) or (document.role not in {'spec', 'plan', 'program_plan'}) or (not isinstance(document.original_path, str)) or (not document.original_path) or (not isinstance(document.sha256, str)) or (len(document.sha256) != 64) or (not isinstance(document.byte_length, int)) or isinstance(document.byte_length, bool) or (document.byte_length < 0) or (not isinstance(document.input_order, int)) or isinstance(document.input_order, bool):
                raise ValueError('input document field values are invalid')
            if document.input_order != expected_order:
                raise ValueError('input document order is not contiguous')
            snapshot_relative = normalize_relative_path(document.snapshot_path)
            if not snapshot_relative.startswith('inputs/'):
                raise ValueError('input snapshot must remain below inputs')
            snapshot = self.paths.root / snapshot_relative
            try:
                metadata = snapshot.lstat()
                data = snapshot.read_bytes()
            except OSError as exc:
                raise ValueError('input snapshot is unreadable') from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError('input snapshot must be a regular file')
            if len(data) != document.byte_length or _sha256(data) != document.sha256:
                raise ValueError('input snapshot digest does not match its contract')
            documents.append(document)
        document_ids = {document.document_id for document in documents}
        if len(document_ids) != len(documents):
            raise ValueError('input document IDs must be unique')
        return tuple(documents)

    def document_set_for_generation(self, generation_id: str) -> tuple[InputDocument, ...]:
        """Return the immutable document revision selected for one map generation."""
        if generation_id == 'generation-0001':
            return self.document_set()
        if len(generation_id) != len('generation-0001') or not generation_id.startswith('generation-') or (not generation_id.removeprefix('generation-').isdigit()) or (int(generation_id.removeprefix('generation-')) < 2):
            raise ValueError('input revision generation ID is invalid')
        path = self.paths.inputs / generation_id / 'document-set.json'
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('input revision document set is unreadable') from exc
        if raw != canonical_json(payload):
            raise ValueError('input revision document set is not canonical JSON')
        if not isinstance(payload, dict) or frozenset(payload) != _DOCUMENT_SET_KEYS:
            raise ValueError('input revision document set has unexpected fields')
        if payload.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('input revision document set is not schema 4')
        values = payload.get('documents')
        if not isinstance(values, list):
            raise ValueError('input revision documents must be an array')
        documents: list[InputDocument] = []
        for expected_order, value in enumerate(values):
            if not isinstance(value, dict) or frozenset(value) != _DOCUMENT_KEYS:
                raise ValueError('input revision document fields are invalid')
            try:
                document = InputDocument(**value)
            except TypeError as exc:
                raise ValueError('input revision field types are invalid') from exc
            if document.input_order != expected_order or document.role not in {'spec', 'plan', 'program_plan'} or (not isinstance(document.byte_length, int)) or isinstance(document.byte_length, bool) or (document.byte_length < 0) or (not isinstance(document.sha256, str)) or (len(document.sha256) != 64):
                raise ValueError('input revision field values are invalid')
            snapshot_path = normalize_relative_path(document.snapshot_path)
            if not snapshot_path.startswith('inputs/'):
                raise ValueError('input revision snapshot must remain below inputs')
            snapshot = self.paths.root / snapshot_path
            try:
                metadata = snapshot.lstat()
                data = snapshot.read_bytes()
            except OSError as exc:
                raise ValueError('input revision snapshot is unreadable') from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError('input revision snapshot must be a regular file')
            if len(data) != document.byte_length or _sha256(data) != document.sha256:
                raise ValueError('input revision snapshot digest does not match')
            documents.append(document)
        if [item.document_id for item in documents] != [item.document_id for item in self.document_set()]:
            raise ValueError('input revision changes stable document IDs')
        matching_snapshots = [event for event in self.validate_event_chain() if event['event_type'] == 'documents.snapshotted' and event['payload']['document_set_sha256'] == _sha256(raw) and (event['payload']['document_ids'] == [document.document_id for document in documents]) and (event['payload']['snapshot_sha256s'] == [document.sha256 for document in documents])]
        if len(matching_snapshots) != 1:
            raise ValueError('input revision lacks a unique snapshot event')
        return tuple(documents)

    def refresh_inputs(self) -> tuple[str, tuple[InputDocument, ...], tuple[str, ...]]:
        """Snapshot explicitly changed original sources into one new revision."""
        generation_events = [event for event in self.validate_event_chain() if event['event_type'] == 'map.generation_created']
        if not generation_events:
            raise ValueError('input_refresh_requires_accepted_generation')
        if self.pending_input_revision() is not None:
            raise ValueError('input_refresh_already_pending')
        current_id = str(generation_events[-1]['payload']['generation_id']) if generation_events else 'generation-0001'
        current = self.document_set_for_generation(current_id)
        generation_number = int(current_id.removeprefix('generation-')) + 1
        generation_id = f'generation-{generation_number:04d}'
        revision_root = self.paths.inputs / generation_id
        if revision_root.exists() or revision_root.is_symlink():
            raise ValueError('input revision already exists')
        _mkdir_private(revision_root)
        revised: list[InputDocument] = []
        changed: list[str] = []
        try:
            for document in current:
                source = Path(document.original_path)
                if source.is_symlink():
                    raise ValueError('input source must not become a symlink')
                resolved = source.resolve(strict=True)
                data = resolved.read_bytes()
                data.decode('utf-8')
                digest = _sha256(data)
                if digest == document.sha256:
                    revised.append(document)
                    continue
                changed.append(document.document_id)
                snapshot_path = f'inputs/{generation_id}/{document.document_id}.md'
                _atomic_write_new(self.paths.root / snapshot_path, data)
                revised.append(InputDocument(document_id=document.document_id, role=document.role, original_path=str(resolved), snapshot_path=snapshot_path, sha256=digest, byte_length=len(data), input_order=document.input_order))
            if not changed:
                raise ValueError('input_refresh_has_no_changes')
            document_set = {'schema_version': SCHEMA_VERSION, 'documents': [document.to_json() for document in revised]}
            raw = canonical_json(document_set)
            _atomic_write_new(revision_root / 'document-set.json', raw)
        except BaseException:
            if revision_root.exists():
                shutil.rmtree(revision_root)
            raise
        try:
            self.append_event('documents.snapshotted', {'document_set_sha256': _sha256(raw), 'document_ids': [document.document_id for document in revised], 'snapshot_sha256s': [document.sha256 for document in revised]})
        except BaseException:
            try:
                pending = self.pending_input_revision()
                published = pending is not None and pending[0] == generation_id
            except (OSError, RuntimeError, ValueError):
                published = False
            if not published and revision_root.exists():
                shutil.rmtree(revision_root)
            raise
        return (generation_id, tuple(revised), tuple(changed))

    def pending_input_revision(self) -> tuple[str, tuple[InputDocument, ...]] | None:
        """Return the sole snapshotted revision not yet bound to a map event."""
        events = self.validate_event_chain()
        generation_events = [event for event in events if event['event_type'] == 'map.generation_created']
        accepted_ids = {str(event['payload']['generation_id']) for event in generation_events}
        revision_ids: list[str] = []
        for entry in self.paths.inputs.iterdir():
            if not entry.is_dir() and (not entry.is_symlink()):
                continue
            name = entry.name
            if entry.is_symlink() or len(name) != len('generation-0001') or (not name.startswith('generation-')) or (not name.removeprefix('generation-').isdigit()) or (int(name.removeprefix('generation-')) < 2):
                raise ValueError('input revision directory is invalid')
            revision_ids.append(name)
        pending_ids = sorted(set(revision_ids) - accepted_ids)
        if not pending_ids:
            return None
        latest_number = int(str(generation_events[-1]['payload']['generation_id']).removeprefix('generation-')) if generation_events else 1
        expected_id = f'generation-{latest_number + 1:04d}'
        if pending_ids != [expected_id]:
            raise ValueError('pending input revision sequence is invalid')
        documents = self.document_set_for_generation(expected_id)
        return (expected_id, documents)

    @staticmethod
    def _parse_events(raw: bytes) -> tuple[dict[str, object], ...]:
        if not raw:
            return ()
        events: list[dict[str, object]] = []
        previous: str | None = None
        for index, line in enumerate(raw.splitlines(keepends=True), 1):
            if not line.endswith(b'\n'):
                raise ValueError('event log ends with a partial record')
            content = line[:-1]
            try:
                event = json.loads(content.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError('event log contains invalid JSON') from exc
            if not isinstance(event, dict) or frozenset(event) != _EVENT_KEYS:
                raise ValueError('event has unexpected fields')
            if content != canonical_json(event):
                raise ValueError('event is not canonical JSON')
            if event.get('event_id') != f'E{index:06d}':
                raise ValueError('event IDs are not contiguous')
            event_type = event.get('event_type')
            payload = event.get('payload')
            if not isinstance(event_type, str) or not isinstance(payload, dict):
                raise ValueError('event payload must be an object')
            if validate_event_payload(event_type, payload) != payload:
                raise ValueError('event payload is not canonical')
            if event.get('prev_event_sha256') != previous:
                raise ValueError('event previous hash does not match')
            digest = event.get('event_sha256')
            body = {key: value for key, value in event.items() if key != 'event_sha256'}
            if not isinstance(digest, str) or digest != _sha256(canonical_json(body)):
                raise ValueError('event hash does not match')
            previous = digest
            events.append(event)
        return tuple(events)

    def append_event(self, event_type: str, payload: Mapping[str, object]) -> dict[str, object]:
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
            events = self._parse_events(b''.join(chunks))
            previous = events[-1]['event_sha256'] if events else None
            body: dict[str, object] = {'event_id': f'E{len(events) + 1:06d}', 'event_type': event_type, 'payload': payload_copy, 'prev_event_sha256': previous}
            event = {**body, 'event_sha256': _sha256(canonical_json(body))}
            line = canonical_json(event) + b'\n'
            view = memoryview(line)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError('short event append')
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
            events = self._parse_events(b''.join(chunks))
            return events
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    @staticmethod
    def _validate_autonomy_decision(payload: Mapping[str, object], *, expected_id: str) -> dict[str, object]:
        if not isinstance(payload, Mapping) or frozenset(payload) != _AUTONOMY_DECISION_KEYS:
            raise ValueError('autonomy decision fields are invalid')
        decision = dict(payload)
        if decision.get('decision_id') != expected_id:
            raise ValueError('autonomy decision IDs are not contiguous')
        for field, limit in (('issue', 4000), ('selected', 1000), ('strategy_key', 512), ('rationale', 4000), ('created_at', 128)):
            value = decision.get(field)
            if not isinstance(value, str) or not value or len(value) > limit:
                raise ValueError(f'autonomy decision {field} is invalid')
        for field, limit in (('alternatives', 16), ('evidence_paths', 64), ('affected_tasks', 64)):
            value = decision.get(field)
            if not isinstance(value, list) or not value or len(value) > limit or (not all((isinstance(item, str) and item and (len(item) <= 512) for item in value))) or (len(set(value)) != len(value)):
                raise ValueError(f'autonomy decision {field} is invalid')
        if decision['selected'] not in decision['alternatives']:
            raise ValueError('autonomy decision selection is not an alternative')
        for path in decision['evidence_paths']:
            normalize_relative_path(path)
        if not isinstance(decision.get('reversible'), bool):
            raise ValueError('autonomy decision reversible flag is invalid')
        try:
            datetime.fromisoformat(str(decision['created_at']).replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('autonomy decision created_at is invalid') from exc
        return decision

    @classmethod
    def _parse_autonomy_decisions(cls, raw: bytes) -> tuple[dict[str, object], ...]:
        if not raw:
            return ()
        decisions: list[dict[str, object]] = []
        for index, line in enumerate(raw.splitlines(keepends=True), 1):
            if not line.endswith(b'\n'):
                raise ValueError('autonomy decision ledger ends with a partial record')
            content = line[:-1]
            try:
                payload = json.loads(content.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError('autonomy decision ledger contains invalid JSON') from exc
            decision = cls._validate_autonomy_decision(payload, expected_id=f'D{index:04d}')
            if content != canonical_json(decision):
                raise ValueError('autonomy decision is not canonical JSON')
            decisions.append(decision)
        return tuple(decisions)

    def autonomy_decisions(self) -> tuple[dict[str, object], ...]:
        descriptor = os.open(self.paths.autonomy_decisions, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 384:
                raise ValueError('autonomy decision ledger must remain private')
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return self._parse_autonomy_decisions(b''.join(chunks))
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def append_autonomy_decision(self, *, issue: str, alternatives: Sequence[str], selected: str, strategy_key: str, rationale: str, evidence_paths: Sequence[str], affected_tasks: Sequence[str], reversible: bool) -> dict[str, object]:
        descriptor = os.open(self.paths.autonomy_decisions, os.O_RDWR | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            existing = self._parse_autonomy_decisions(b''.join(chunks))
            decision = self._validate_autonomy_decision({'decision_id': f'D{len(existing) + 1:04d}', 'issue': issue, 'alternatives': list(alternatives), 'selected': selected, 'strategy_key': strategy_key, 'rationale': rationale, 'evidence_paths': list(evidence_paths), 'affected_tasks': list(affected_tasks), 'reversible': reversible, 'created_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}, expected_id=f'D{len(existing) + 1:04d}')
            line = canonical_json(decision) + b'\n'
            view = memoryview(line)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError('short autonomy decision append')
                view = view[written:]
            os.fsync(descriptor)
            return decision
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def allocate_outbox(self, attempt_id: str) -> Path:
        normalized = normalize_relative_path(attempt_id)
        if '/' in normalized:
            raise ValueError('attempt_id must be one normalized path component')
        path = self.paths.outbox / normalized
        if path.exists() or path.is_symlink():
            raise ValueError(f'outbox already exists: {attempt_id}')
        _mkdir_private(path)
        return path

    def ingest_outbox(self, attempt_id: str, relative_paths: Sequence[str]) -> tuple[str, ...]:
        normalized_attempt = normalize_relative_path(attempt_id)
        if '/' in normalized_attempt:
            raise ValueError('attempt_id must be one normalized path component')
        source_root = self.paths.outbox / normalized_attempt
        if not source_root.is_dir() or source_root.is_symlink():
            raise ValueError(f'outbox does not exist: {attempt_id}')
        ingested: list[str] = []
        for relative_path in relative_paths:
            normalized = normalize_relative_path(relative_path)
            if normalized in ingested:
                raise ValueError('outbox artifact paths must be unique')
            source = source_root / normalized
            try:
                current = source_root
                metadata = None
                for index, part in enumerate(Path(normalized).parts):
                    current = current / part
                    metadata = current.lstat()
                    if stat.S_ISLNK(metadata.st_mode):
                        raise ValueError(f'outbox artifact path contains a symlink: {normalized}')
                    if index < len(Path(normalized).parts) - 1 and (not stat.S_ISDIR(metadata.st_mode)):
                        raise ValueError(f'outbox artifact parent is not a directory: {normalized}')
                data = source.read_bytes()
            except OSError as exc:
                raise ValueError(f'outbox artifact is unreadable: {normalized}') from exc
            assert metadata is not None
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f'outbox artifact must be a regular file: {normalized}')
            self.put_artifact(normalized, data)
            ingested.append(normalized)
        return tuple(ingested)

    def discard_outbox(self, attempt_id: str) -> None:
        """Atomically detach and safely remove one rejected or consumed outbox."""
        normalized_attempt = normalize_relative_path(attempt_id)
        if '/' in normalized_attempt:
            raise ValueError('attempt_id must be one normalized path component')
        source = self.paths.outbox / normalized_attempt
        try:
            metadata = source.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValueError(f'outbox is unavailable: {attempt_id}') from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError('outbox discard target must be a real directory')
        detached = self.paths.outbox / f'.discarded-{uuid.uuid4().hex}'
        os.replace(source, detached)
        _fsync_directory(self.paths.outbox)
        shutil.rmtree(detached)
        _fsync_directory(self.paths.outbox)

    def replay(self) -> dict[str, object]:
        manifest = self._load_manifest()
        self.document_set()
        events = self.validate_event_chain()
        for record in self._artifact_records():
            self._read_record(record)
        status = manifest['status']
        tasks: dict[str, dict[str, object]] = {}
        authorities: dict[str, dict[str, object]] = {}
        for event in events:
            event_type = event['event_type']
            payload = event['payload']
            if event_type == 'map.generation_created':
                for authority in authorities.values():
                    if authority.get('status') == 'waiting_authority':
                        authority['status'] = 'superseded'
                status = 'waiting_authority' if event['payload'].get('authority_ids') else 'running'
                for task_id in event['payload'].get('invalidated_task_ids', []):
                    tasks.pop(str(task_id), None)
            elif event_type == 'authority.opened':
                status = 'waiting_authority'
                authorities[str(payload['authority_id'])] = {'authority_code': payload['authority_code'], 'status': 'waiting_authority', 'task_ids': list(payload.get('task_ids', [])), 'artifact_paths': list(payload['artifact_paths'])}
            elif event_type == 'authority.resolved':
                authority = authorities.setdefault(str(payload['authority_id']), {})
                authority['status'] = 'resolved'
                status = 'waiting_authority' if any((item.get('status') == 'waiting_authority' for item in authorities.values())) else 'running'
            elif event_type == 'task.started':
                task = tasks.setdefault(str(payload['task_id']), {'attempts': [], 'reviews': [], 'report_paths': []})
                if isinstance(task.get('active_attempt'), Mapping):
                    raise ValueError('task started while another active attempt is live')
                if any((isinstance(attempt, Mapping) and attempt.get('attempt_id') == payload['attempt_id'] for attempt in task['attempts'])):
                    raise ValueError('task attempt ID was already reported')
                task['active_attempt'] = {'attempt_id': payload['attempt_id'], 'role': payload.get('role', 'task_agent'), 'strategy_key': payload['strategy_key'], 'baseline_commit': payload['baseline_commit'], 'evidence_sha256': payload['evidence_sha256']}
                task.pop('pending_recovery', None)
            elif event_type == 'task.reported':
                task = tasks.setdefault(str(payload['task_id']), {'attempts': [], 'reviews': [], 'report_paths': []})
                active = task.get('active_attempt')
                if not isinstance(active, Mapping):
                    raise ValueError('task report has no matching active attempt')
                if active.get('attempt_id') != payload['attempt_id']:
                    raise ValueError('task report differs from its active attempt')
                if payload.get('strategy_key') != active.get('strategy_key'):
                    raise ValueError('task report strategy differs from its active attempt')
                attempt = {'attempt_id': payload['attempt_id'], 'role': active.get('role', 'task_agent'), 'status': payload['status'], 'commit': payload.get('commit'), 'strategy_key': payload.get('strategy_key'), 'result_sha256': payload.get('result_sha256'), 'artifact_paths': list(payload['artifact_paths']), 'baseline_commit': active.get('baseline_commit'), 'evidence_sha256': active.get('evidence_sha256')}
                task['attempts'].append(attempt)
                task['report_paths'].extend(payload['artifact_paths'])
                task['task_status'] = payload['status']
                task['latest_strategy_key'] = payload.get('strategy_key')
                if payload.get('commit') is not None:
                    task['latest_commit'] = payload['commit']
                task.pop('active_attempt', None)
            elif event_type == 'review.reported':
                task = tasks.setdefault(str(payload['task_id']), {'attempts': [], 'reviews': [], 'report_paths': []})
                review = {'review_id': payload['review_id'], 'status': payload['status'], 'commit': payload.get('commit'), 'verdict': payload['verdict'], 'artifact_paths': list(payload['artifact_paths']), 'evidence_sha256': payload['evidence_sha256']}
                task['reviews'].append(review)
                task['review_status'] = payload['status']
                task['review_verdict'] = payload['verdict']
            elif event_type == 'autonomy.recorded':
                for task_id in payload.get('task_ids', []):
                    task = tasks.setdefault(str(task_id), {'attempts': [], 'reviews': [], 'report_paths': []})
                    recovery = {'decision_id': payload['decision_id'], 'strategy_key': payload['strategy_key'], 'artifact_paths': [path for path in payload['artifact_paths'] if path != 'autonomy-decisions.jsonl']}
                    task.setdefault('autonomy', []).append(recovery)
                    task['pending_recovery'] = recovery
            elif event_type == 'run.interrupted':
                status = 'interrupted'
            elif event_type == 'audit.reported':
                status = 'final_audit'
            elif event_type == 'run.completed':
                status = 'completed'
            elif event_type == 'run.failed':
                status = 'failed'
        return {'schema_version': SCHEMA_VERSION, 'run_id': self.run_id, 'status': status, 'event_count': len(events), 'last_event_sha256': events[-1]['event_sha256'] if events else None, 'tasks': tasks, 'authorities': authorities, 'autonomy_decision_count': len(self.autonomy_decisions())}

    @staticmethod
    def _parse_artifact_index(raw: bytes) -> tuple[dict[str, object], ...]:
        records = []
        for index, line in enumerate(raw.splitlines(keepends=True), 1):
            if not line.endswith(b'\n'):
                raise ValueError('artifact index ends with a partial record')
            try:
                record = json.loads(line[:-1].decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError('artifact index contains invalid JSON') from exc
            if not isinstance(record, dict) or frozenset(record) != _ARTIFACT_RECORD_KEYS or line[:-1] != canonical_json(record) or (record.get('artifact_id') != f'A{index:06d}'):
                raise ValueError('artifact index record is invalid')
            path = record.get('relative_path')
            digest = record.get('sha256')
            size = record.get('byte_length')
            if not isinstance(path, str) or normalize_relative_path(path) != path or path.split('/', 1)[0] not in _ARTIFACT_ROOTS or (not isinstance(digest, str)) or (len(digest) != 64) or (not isinstance(size, int)) or isinstance(size, bool) or (size < 0) or any((old['relative_path'] == path for old in records)):
                raise ValueError('artifact index record fields are invalid')
            records.append(record)
        return tuple(records)

    def _artifact_records(self) -> tuple[dict[str, object], ...]:
        descriptor = os.open(self.paths.artifact_index, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            return self._parse_artifact_index(os.read(descriptor, os.fstat(descriptor).st_size))
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _artifact_target(self, relative_path: str, *, allow_inputs: bool=False) -> tuple[str, Path]:
        normalized = normalize_relative_path(relative_path)
        root = normalized.split('/', 1)[0]
        if root not in _ARTIFACT_ROOTS and (not (allow_inputs and root == 'inputs')):
            raise ValueError('artifact path is outside the durable run roots')
        if root == 'result.json' and normalized != 'result.json':
            raise ValueError('result.json is a file')
        return (normalized, self.paths.root / normalized)

    @staticmethod
    def _read_private_file(path: Path) -> bytes:
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except OSError as exc:
            raise ValueError('durable artifact is unreadable') from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 384:
                raise ValueError('durable artifact must remain a private regular file')
            return os.read(descriptor, metadata.st_size)
        finally:
            os.close(descriptor)

    def _read_record(self, record: Mapping[str, object]) -> bytes:
        data = self._read_private_file(self.paths.root / str(record['relative_path']))
        if len(data) != record['byte_length'] or _sha256(data) != record['sha256']:
            raise ValueError('artifact digest does not match its index')
        return data

    def put_artifact(self, relative_path: str, data: bytes) -> Path:
        normalized, target = self._artifact_target(relative_path)
        if not isinstance(data, bytes):
            raise ValueError('artifact data must be bytes')
        descriptor = os.open(self.paths.artifact_index, os.O_RDWR | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.lseek(descriptor, 0, os.SEEK_SET)
            records = self._parse_artifact_index(os.read(descriptor, os.fstat(descriptor).st_size))
            existing = next((item for item in records if item['relative_path'] == normalized), None)
            if existing is not None:
                if self._read_record(existing) != data:
                    raise ValueError('immutable artifact path already contains different bytes')
                return target
            _mkdir_artifact_parents(self.paths.root, target.parent)
            try:
                _atomic_write_new(target, data)
            except FileExistsError:
                if self._read_private_file(target) != data:
                    raise ValueError('unindexed artifact contains different bytes')
            record = {'artifact_id': f'A{len(records) + 1:06d}', 'relative_path': normalized, 'sha256': _sha256(data), 'byte_length': len(data)}
            os.write(descriptor, canonical_json(record) + b'\n')
            os.fsync(descriptor)
            return target
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def read_artifact(self, relative_path: str) -> bytes:
        normalized, target = self._artifact_target(relative_path, allow_inputs=True)
        if normalized.startswith('inputs/'):
            documents = [*self.document_set()]
            for directory in sorted(self.paths.inputs.glob('generation-*')):
                if directory.is_dir() and (not directory.is_symlink()):
                    documents.extend(self.document_set_for_generation(directory.name))
            match = next((item for item in documents if item.snapshot_path == normalized), None)
            if match is None:
                raise ValueError('input path is not an immutable snapshot')
            data = self._read_private_file(target)
            if len(data) != match.byte_length or _sha256(data) != match.sha256:
                raise ValueError('input snapshot digest does not match')
            return data
        record = next((item for item in self._artifact_records() if item['relative_path'] == normalized), None)
        if record is None:
            raise ValueError('artifact has no durable digest record')
        return self._read_record(record)

    def read_accepted_publication(self, manifest_path: str, manifest_sha256: str, *, require_event_selection: bool=True) -> tuple[dict[str, object], dict[str, bytes]]:
        raw = self.read_artifact(manifest_path)
        if _sha256(raw) != manifest_sha256:
            raise ValueError('mapping bundle digest does not match')
        try:
            manifest = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('mapping bundle is invalid JSON') from exc
        required = {'schema_version', 'generation_id', 'publication_id', 'program_map_sha256', 'artifacts'}
        if not isinstance(manifest, dict) or set(manifest) != required or manifest['schema_version'] != 1:
            raise ValueError('mapping bundle fields are invalid')
        if require_event_selection:
            matches = [event for event in self.validate_event_chain() if event['event_type'] == 'map.generation_created' and event['payload'].get('publication_manifest_path') == manifest_path and (event['payload'].get('publication_manifest_sha256') == manifest_sha256)]
            if len(matches) != 1:
                raise ValueError('mapping bundle is not uniquely event-selected')
        descriptors = manifest['artifacts']
        if not isinstance(descriptors, dict) or not descriptors:
            raise ValueError('mapping bundle artifacts are invalid')
        artifacts = {}
        commitment = {}
        for logical, descriptor in descriptors.items():
            if not isinstance(logical, str) or not isinstance(descriptor, dict) or set(descriptor) != {'relative_path', 'sha256', 'byte_length'} or (descriptor['relative_path'] != logical):
                raise ValueError('mapping bundle artifact binding is invalid')
            data = self.read_artifact(logical)
            if len(data) != descriptor['byte_length'] or _sha256(data) != descriptor['sha256']:
                raise ValueError('mapping bundle artifact digest does not match')
            artifacts[logical] = data
            commitment[logical] = {'sha256': descriptor['sha256'], 'byte_length': descriptor['byte_length']}
        expected = _sha256(b'cpe-map-publication-v1\x00' + canonical_json(commitment))
        if manifest['publication_id'] != expected:
            raise ValueError('mapping bundle commitment does not match')
        return (manifest, artifacts)

    def artifact_paths(self, *, prefix: str) -> tuple[str, ...]:
        boundary = normalize_relative_path(prefix).rstrip('/') + '/'
        records = self._artifact_records()
        for record in records:
            self._read_record(record)
        return tuple(sorted((str(item['relative_path']) for item in records if str(item['relative_path']).startswith(boundary))))

    def reconcile_autonomy_events(self) -> None:
        decisions = self.autonomy_decisions()
        events = [event for event in self.validate_event_chain() if event['event_type'] == 'autonomy.recorded']
        for decision in decisions[len(events):]:
            evidence = list(decision['evidence_paths'])
            self.append_event('autonomy.recorded', {'decision_id': decision['decision_id'], 'strategy_key': decision['strategy_key'], 'decision_sha256': _sha256(canonical_json(decision)), 'task_ids': list(decision['affected_tasks']), 'artifact_paths': list(dict.fromkeys(['autonomy-decisions.jsonl', *evidence]))})

    def prune_unselected_mapping_publications(self, generation_id: str = "") -> None:
        return None
