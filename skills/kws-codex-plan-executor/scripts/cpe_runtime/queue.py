"""Deterministic multi-document mapping queue for lean schema-4 CPE."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    AUTHORITY_CODES,
    InputDocument,
    canonical_json,
    validate_document_map,
    validate_program_map,
    validate_task_brief,
)
from .launcher import ChildLauncher, ChildRequest, LaunchOutcome
from .store import RunStore
from .worktree import Worktree


_GENERATION_ID = "generation-0001"
_GENERATION_ROOT = f"maps/{_GENERATION_ID}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(data: bytes, name: str) -> dict[str, object]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or data != canonical_json(payload):
        raise ValueError(f"{name} must be canonical JSON object bytes")
    return payload


@dataclass(frozen=True)
class _PendingDocumentMap:
    document: InputDocument
    attempt_id: str
    artifact_path: str
    outcome: LaunchOutcome


class QueueEngine:
    """Own mapping launches, ordered ingestion, validation, and one map event."""

    def __init__(
        self, store: RunStore, worktree: Worktree, launcher: ChildLauncher
    ) -> None:
        if not isinstance(store, RunStore):
            raise ValueError("queue store must be a RunStore")
        if not isinstance(worktree, Worktree):
            raise ValueError("queue worktree must be a Worktree")
        if not isinstance(launcher, ChildLauncher):
            raise ValueError("queue launcher must be a ChildLauncher")
        worktree.verify_identity()
        self.store = store
        self.worktree = worktree
        self.launcher = launcher

    def _repository_instructions(self) -> tuple[Path, ...]:
        root = self.worktree.root
        instructions = root / "AGENTS.md"
        if not instructions.is_file() or instructions.is_symlink():
            raise ValueError("mapping requires repository-root AGENTS.md instructions")
        return (instructions.resolve(strict=True),)

    @staticmethod
    def _document_map_path(document: InputDocument) -> str:
        return f"{_GENERATION_ROOT}/documents/{document.document_id}.json"

    def _allocate_attempt(self, base_attempt_id: str) -> tuple[str, Path]:
        attempt_id = base_attempt_id
        retry = 0
        while (self.store.paths.outbox / attempt_id).exists() or (
            self.store.paths.outbox / attempt_id
        ).is_symlink():
            retry += 1
            attempt_id = f"{base_attempt_id}-retry-{retry:04d}"
        return attempt_id, self.store.allocate_outbox(attempt_id)

    @staticmethod
    def _read_outbox_file(outbox: Path, relative_path: str) -> bytes:
        current = outbox
        parts = Path(relative_path).parts
        for index, part in enumerate(parts):
            current = current / part
            try:
                metadata = current.lstat()
            except OSError as exc:
                raise ValueError("program mapper omitted a reported artifact") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("program mapper artifact path contains a symlink")
            if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("program mapper artifact parent is not a directory")
        descriptor = os.open(current, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("program mapper artifact is not a regular file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _read_document_map(
        self, document: InputDocument, relative_path: str
    ) -> tuple[dict[str, object], bytes]:
        data = self.store.read_artifact(relative_path)
        payload = _load_json(data, f"document map {document.document_id}")
        validated = validate_document_map(payload, document=document)
        if canonical_json(validated) != data:
            raise ValueError("document map is not in its canonical validated shape")
        source = self.store.read_artifact(document.snapshot_path)
        for section in ("requirements", "task_candidates"):
            for entry in validated[section]:
                self._verify_exact_excerpt(
                    source,
                    line_start=int(entry["line_start"]),
                    line_end=int(entry["line_end"]),
                    exact_excerpt=str(entry["exact_excerpt"]),
                )
        return validated, data

    @staticmethod
    def _verify_exact_excerpt(
        source: bytes, *, line_start: int, line_end: int, exact_excerpt: str
    ) -> None:
        try:
            lines = source.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise ValueError("immutable source is not UTF-8") from exc
        if line_end > len(lines):
            raise ValueError("exact excerpt line range exceeds the immutable source")
        expected = "".join(lines[line_start - 1 : line_end])
        if exact_excerpt != expected:
            raise ValueError("exact excerpt does not equal its immutable source range")

    def _verify_source_references(
        self,
        references: list[dict[str, object]],
        *,
        sources: dict[str, bytes],
    ) -> None:
        for reference in references:
            document_id = str(reference["document_id"])
            if document_id not in sources:
                raise ValueError("source reference names an unknown immutable document")
            self._verify_exact_excerpt(
                sources[document_id],
                line_start=int(reference["line_start"]),
                line_end=int(reference["line_end"]),
                exact_excerpt=str(reference["exact_excerpt"]),
            )

    def _launch_document_map(
        self,
        document: InputDocument,
        instructions: tuple[Path, ...],
        attempt_id: str,
        artifact_path: str,
    ) -> _PendingDocumentMap:
        outbox = self.store.paths.outbox / attempt_id
        request = ChildRequest(
            role="document_mapper",
            item_id=document.document_id,
            goal=(
                "Map exactly one immutable input snapshot into a lossless structural "
                "document map with exact excerpts and source ranges."
            ),
            input_paths=(self.store.paths.root / document.snapshot_path, *instructions),
            repository=self.worktree.source,
            worktree=self.worktree.root,
            outbox=outbox,
            report_path=artifact_path,
            applicable_skills=("using-superpowers",),
            done_when=(
                "the one input snapshot has one canonical digest-bound document map",
            ),
        )
        outcome = self.launcher.launch(
            request,
            worktree=self.worktree,
            store=self.store,
            ingest_artifacts=False,
        )
        return _PendingDocumentMap(document, attempt_id, artifact_path, outcome)

    def map_documents(self) -> tuple[str, ...]:
        """Launch one fresh mapper per missing immutable input, then ingest in order."""

        documents = self.store.document_set()
        instructions = self._repository_instructions()
        paths = tuple(self._document_map_path(document) for document in documents)
        pending: list[tuple[InputDocument, str, str]] = []
        for document, relative_path in zip(documents, paths, strict=True):
            target = self.store.paths.root / relative_path
            if target.exists() or target.is_symlink():
                self._read_document_map(document, relative_path)
                continue
            attempt_id, _ = self._allocate_attempt(
                f"map-document-{document.input_order + 1:04d}"
            )
            pending.append((document, attempt_id, relative_path))

        completed: list[_PendingDocumentMap] = []
        failures: list[Exception] = []
        if pending:
            with ThreadPoolExecutor(max_workers=min(4, len(pending))) as executor:
                futures = [
                    executor.submit(
                        self._launch_document_map,
                        document,
                        instructions,
                        attempt_id,
                        relative_path,
                    )
                    for document, attempt_id, relative_path in pending
                ]
                for future in futures:
                    try:
                        completed.append(future.result())
                    except Exception as exc:
                        failures.append(exc)

        for item in sorted(completed, key=lambda result: result.document.input_order):
            if item.outcome.result.status != "completed":
                raise ValueError(
                    f"document mapper {item.document.document_id} did not complete"
                )
            if item.outcome.result.artifact_paths != (item.artifact_path,):
                raise ValueError("document mapper returned unexpected artifact paths")
            self.store.ingest_outbox(item.attempt_id, item.outcome.result.artifact_paths)
            self._read_document_map(item.document, item.artifact_path)
        if failures:
            raise failures[0]
        return paths

    def _validated_document_maps(
        self,
    ) -> tuple[
        tuple[InputDocument, dict[str, object], bytes, str], ...
    ]:
        values: list[tuple[InputDocument, dict[str, object], bytes, str]] = []
        for document in self.store.document_set():
            relative_path = self._document_map_path(document)
            payload, data = self._read_document_map(document, relative_path)
            values.append((document, payload, data, relative_path))
        return tuple(values)

    def _validate_program_artifacts(
        self,
        document_maps: tuple[
            tuple[InputDocument, dict[str, object], bytes, str], ...
        ],
    ) -> tuple[dict[str, object], bytes, tuple[str, ...]]:
        program_path = f"{_GENERATION_ROOT}/program-map.json"
        program_bytes = self.store.read_artifact(program_path)
        program = validate_program_map(
            _load_json(program_bytes, "program map"),
            document_ids={document.document_id for document, _, _, _ in document_maps},
        )
        if canonical_json(program) != program_bytes:
            raise ValueError("program map is not in its canonical validated shape")
        expected_map_hashes = {
            document.document_id: _sha256(data)
            for document, _, data, _ in document_maps
        }
        if program["document_map_sha256s"] != expected_map_hashes:
            raise ValueError("program map document-map SHA set does not match")

        normative_requirements = {
            str(requirement["requirement_id"])
            for _, document_map, _, _ in document_maps
            for requirement in document_map["requirements"]
            if requirement["kind"] == "normative"
        }
        if set(program["coverage"]) != normative_requirements:
            raise ValueError("program coverage does not exactly cover normative requirements")
        required_final_commands = {
            str(command)
            for _, document_map, _, _ in document_maps
            for command in document_map["verification_commands"]
        }
        if not required_final_commands <= set(program["final_verification_commands"]):
            raise ValueError("program map omits a document-level verification command")

        task_candidates = {
            str(candidate["task_id"]): (document, candidate)
            for document, document_map, _, _ in document_maps
            for candidate in document_map["task_candidates"]
        }
        split_targets = {
            str(task_id)
            for split in program["task_splits"]
            for task_id in split["split_task_ids"]
        }
        split_sources = {
            str(split["source_task_id"]) for split in program["task_splits"]
        }
        expected_task_ids = (set(task_candidates) - split_sources) | split_targets
        if {str(task["task_id"]) for task in program["tasks"]} != expected_task_ids:
            raise ValueError("program task graph differs from mapped candidates and splits")

        program_sha256 = _sha256(program_bytes)
        document_hashes = {
            document.document_id: document.sha256
            for document, _, _, _ in document_maps
        }
        document_sources = {
            document.document_id: self.store.read_artifact(document.snapshot_path)
            for document, _, _, _ in document_maps
        }
        artifact_paths = [
            program_path,
            f"{_GENERATION_ROOT}/coverage.json",
            f"{_GENERATION_ROOT}/authority-queue.json",
        ]
        coverage = _load_json(
            self.store.read_artifact(artifact_paths[1]), "coverage companion"
        )
        if coverage != {
            "schema_version": 1,
            "program_map_sha256": program_sha256,
            "coverage": program["coverage"],
        }:
            raise ValueError("coverage companion does not match the program map")
        authority_queue = _load_json(
            self.store.read_artifact(artifact_paths[2]), "authority queue"
        )
        if authority_queue != {
            "schema_version": 1,
            "program_map_sha256": program_sha256,
            "authority_items": program["authority_items"],
        }:
            raise ValueError("authority queue does not match the program map")

        briefs: dict[str, dict[str, object]] = {}
        for task in program["tasks"]:
            brief_path = str(task["brief_path"])
            brief_bytes = self.store.read_artifact(brief_path)
            brief = validate_task_brief(
                _load_json(brief_bytes, f"task brief {task['task_id']}"),
                program_map_sha256=program_sha256,
                document_hashes=document_hashes,
            )
            if canonical_json(brief) != brief_bytes:
                raise ValueError("task brief is not in its canonical validated shape")
            self._verify_source_references(
                brief["source_references"], sources=document_sources
            )
            self._verify_source_references(
                brief["global_constraints"], sources=document_sources
            )
            if (
                brief["task_id"] != task["task_id"]
                or brief["title"] != task["title"]
                or brief["dependencies"] != task["dependencies"]
            ):
                raise ValueError("task brief identity or dependencies differ from program map")
            referenced_documents = {
                str(reference["document_id"])
                for reference in brief["source_references"]
            }
            if not set(task["document_ids"]) <= referenced_documents:
                raise ValueError("task brief omits a program-map source document")
            task_id = str(task["task_id"])
            if task_id in task_candidates:
                candidate_document, candidate = task_candidates[task_id]
                expected_task_reference = {
                    "document_id": candidate_document.document_id,
                    "heading": candidate["heading"],
                    "line_start": candidate["line_start"],
                    "line_end": candidate["line_end"],
                    "source_sha256": candidate_document.sha256,
                    "exact_excerpt": candidate["exact_excerpt"],
                }
                if canonical_json(expected_task_reference) not in {
                    canonical_json(reference)
                    for reference in brief["source_references"]
                }:
                    raise ValueError("task brief omits its exact mapped task source")
                if not set(candidate["acceptance"]) <= set(brief["acceptance"]):
                    raise ValueError("task brief omits mapped acceptance commands")
            briefs[str(task["task_id"])] = brief
            artifact_paths.append(brief_path)

        for split in program["task_splits"]:
            self._verify_source_references(
                split["source_references"], sources=document_sources
            )
            split_refs = {
                canonical_json(reference) for reference in split["source_references"]
            }
            brief_refs = {
                canonical_json(reference)
                for task_id in split["split_task_ids"]
                for reference in briefs[str(task_id)]["source_references"]
            }
            if not split_refs <= brief_refs:
                raise ValueError("task split changed or omitted exact source coverage")
        for authority_item in program["authority_items"]:
            self._verify_source_references(
                authority_item["source_references"], sources=document_sources
            )
        return program, program_bytes, tuple(sorted(artifact_paths))

    def _append_authority_events(
        self, program: dict[str, object], authority_path: str
    ) -> None:
        existing = {
            str(event["payload"]["authority_id"])
            for event in self.store.validate_event_chain()
            if event["event_type"] == "authority.opened"
        }
        for item in sorted(
            program["authority_items"], key=lambda value: str(value.get("authority_id", ""))
        ):
            authority_id = item.get("authority_id")
            authority_code = item.get("authority_code")
            task_ids = item.get("affected_task_ids", [])
            if (
                not isinstance(authority_id, str)
                or not authority_id
                or authority_code not in AUTHORITY_CODES
                or not isinstance(task_ids, list)
                or not all(isinstance(task_id, str) and task_id for task_id in task_ids)
            ):
                raise ValueError("program authority item is not event-safe")
            if authority_id not in existing:
                self.store.append_event(
                    "authority.opened",
                    {
                        "authority_id": authority_id,
                        "authority_code": authority_code,
                        "status": "waiting_authority",
                        "task_ids": task_ids,
                        "artifact_paths": [authority_path],
                    },
                )

    def map_program(self) -> str:
        """Compose validated document maps into one immutable global program map."""

        self.map_documents()
        document_maps = self._validated_document_maps()
        program_path = f"{_GENERATION_ROOT}/program-map.json"
        target = self.store.paths.root / program_path
        reported_artifact_paths: tuple[str, ...] | None = None
        if not target.exists() and not target.is_symlink():
            attempt_id, outbox = self._allocate_attempt("map-program-0001")
            request = ChildRequest(
                role="program_mapper",
                item_id=_GENERATION_ID,
                goal=(
                    "Compose validated document maps into a topological task graph, honest "
                    "coverage, lossless task briefs, and bounded authority records."
                ),
                input_paths=(
                    *(self.store.paths.root / relative_path for _, _, _, relative_path in document_maps),
                    *self._repository_instructions(),
                ),
                repository=self.worktree.source,
                worktree=self.worktree.root,
                outbox=outbox,
                report_path=program_path,
                applicable_skills=("using-superpowers",),
                done_when=(
                    "every normative requirement has one approved structural disposition",
                    "every task has a lossless digest-bound brief",
                ),
            )
            outcome = self.launcher.launch(
                request,
                worktree=self.worktree,
                store=self.store,
                ingest_artifacts=False,
            )
            if outcome.result.status != "completed":
                raise ValueError("program mapper did not complete")
            reported_artifact_paths = outcome.result.artifact_paths
            untrusted_program_bytes = self._read_outbox_file(outbox, program_path)
            untrusted_program = validate_program_map(
                _load_json(untrusted_program_bytes, "program mapper output"),
                document_ids={
                    document.document_id for document, _, _, _ in document_maps
                },
            )
            expected_reported_paths = {
                program_path,
                f"{_GENERATION_ROOT}/coverage.json",
                f"{_GENERATION_ROOT}/authority-queue.json",
                *(str(task["brief_path"]) for task in untrusted_program["tasks"]),
            }
            if (
                len(reported_artifact_paths) != len(expected_reported_paths)
                or set(reported_artifact_paths) != expected_reported_paths
            ):
                raise ValueError("program mapper returned unexpected artifact paths")
            self.store.ingest_outbox(attempt_id, outcome.result.artifact_paths)

        program, program_bytes, artifact_paths = self._validate_program_artifacts(
            document_maps
        )
        returned_paths = set(artifact_paths)
        if not returned_paths:
            raise ValueError("program generation has no immutable artifacts")
        if reported_artifact_paths is not None and (
            len(reported_artifact_paths) != len(artifact_paths)
            or set(reported_artifact_paths) != returned_paths
        ):
            raise ValueError("program mapper returned unexpected artifact paths")
        authority_path = f"{_GENERATION_ROOT}/authority-queue.json"
        self._append_authority_events(program, authority_path)
        blocking = sorted(
            requirement_id
            for requirement_id, record in program["coverage"].items()
            if record["disposition"] in {"conflict", "unmapped"}
        )
        if blocking:
            raise ValueError(f"blocking coverage dispositions: {blocking}")

        events = self.store.validate_event_chain()
        generation_events = [
            event
            for event in events
            if event["event_type"] == "map.generation_created"
            and event["payload"]["generation_id"] == _GENERATION_ID
        ]
        if len(generation_events) > 1:
            raise ValueError("map generation was accepted more than once")
        if generation_events:
            event_payload = generation_events[0]["payload"]
            if (
                event_payload.get("map_sha256") != _sha256(program_bytes)
                or event_payload.get("artifact_paths") != list(artifact_paths)
            ):
                raise ValueError("map generation event differs from immutable artifacts")
        else:
            self.store.append_event(
                "map.generation_created",
                {
                    "generation_id": _GENERATION_ID,
                    "map_sha256": _sha256(program_bytes),
                    "artifact_paths": list(artifact_paths),
                },
            )
        return program_path

    def run_until_terminal(self) -> dict[str, object]:
        """Advance through the mapping boundary; later tasks own task dispatch."""

        self.map_documents()
        self.map_program()
        return self.store.replay()
