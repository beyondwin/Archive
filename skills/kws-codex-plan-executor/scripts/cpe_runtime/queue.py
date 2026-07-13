"""Deterministic multi-document mapping queue for lean schema-4 CPE."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    AUTHORITY_CODES,
    ChildResult,
    InputDocument,
    canonical_json,
    normalize_relative_path,
    validate_document_audit,
    validate_document_map,
    validate_program_map,
    validate_task_brief,
    validate_terminal_artifact,
)
from .launcher import ChildLauncher, ChildRequest, LaunchOutcome
from .store import RunStore
from .worktree import Worktree


_GENERATION_ID = "generation-0001"
_GENERATION_ROOT = f"maps/{_GENERATION_ID}"
_INVESTIGATION_RECOVERY_METHODS = (
    "root_cause_reanalysis",
    "architecture_synthesis",
)


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

    @staticmethod
    def _instruction_file(path: Path) -> Path | None:
        if path.is_symlink():
            raise ValueError("mapping instructions must not be a symlink")
        if not path.exists():
            return None
        if not path.is_file():
            raise ValueError("mapping instructions must be a regular file")
        return path.resolve(strict=True)

    def _document_instructions(self, document: InputDocument) -> tuple[Path, ...]:
        root = self.worktree.root
        result: list[Path] = []
        root_instruction = self._instruction_file(root / "AGENTS.md")
        if root_instruction is not None:
            result.append(root_instruction)

        try:
            original = Path(document.original_path).resolve(strict=True)
            relative_parent = original.relative_to(self.worktree.source).parent
        except (OSError, ValueError):
            return tuple(result)
        current = root
        for part in relative_parent.parts:
            current = current / part
            instruction = self._instruction_file(current / "AGENTS.md")
            if instruction is not None and instruction not in result:
                result.append(instruction)
        return tuple(result)

    def _repository_instructions(self) -> tuple[Path, ...]:
        result: list[Path] = []
        for document in self.store.document_set():
            for instruction in self._document_instructions(document):
                if instruction not in result:
                    result.append(instruction)
        return tuple(result)

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

    @staticmethod
    def _outbox_artifact_paths(outbox: Path) -> tuple[str, ...]:
        paths: list[str] = []
        for path in sorted(outbox.rglob("*")):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("mapper outbox contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("mapper outbox contains a special file")
            relative = path.relative_to(outbox).as_posix()
            if relative != ".child-result.json":
                paths.append(relative)
        return tuple(paths)

    def _validate_document_map_bytes(
        self, document: InputDocument, data: bytes
    ) -> dict[str, object]:
        payload = _load_json(data, f"document map {document.document_id}")
        validated = validate_document_map(payload, document=document)
        if canonical_json(validated) != data:
            raise ValueError("document map is not in its canonical validated shape")
        source = self.store.read_artifact(document.snapshot_path)
        self._verify_nested_source_references(
            validated, sources={document.document_id: source}
        )
        for section in ("requirements", "task_candidates"):
            for entry in validated[section]:
                self._verify_exact_excerpt(
                    source,
                    line_start=int(entry["line_start"]),
                    line_end=int(entry["line_end"]),
                    exact_excerpt=str(entry["exact_excerpt"]),
                )
        return validated

    def _read_document_map(
        self, document: InputDocument, relative_path: str
    ) -> tuple[dict[str, object], bytes]:
        data = self.store.read_artifact(relative_path)
        validated = self._validate_document_map_bytes(document, data)
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

    def _verify_nested_source_references(
        self, value: object, *, sources: dict[str, bytes]
    ) -> None:
        if isinstance(value, Mapping):
            source_fields = {
                "document_id",
                "heading",
                "line_start",
                "line_end",
                "source_sha256",
                "exact_excerpt",
            }
            if set(value) == source_fields:
                self._verify_source_references([dict(value)], sources=sources)
                return
            for child in value.values():
                self._verify_nested_source_references(child, sources=sources)
        elif isinstance(value, list):
            for child in value:
                self._verify_nested_source_references(child, sources=sources)

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
                        self._document_instructions(document),
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

        successful = sorted(
            (
                item
                for item in completed
                if item.outcome.result.status == "completed"
            ),
            key=lambda result: result.document.input_order,
        )
        noncompleted = sorted(
            (
                item
                for item in completed
                if item.outcome.result.status != "completed"
            ),
            key=lambda result: result.document.input_order,
        )
        validation_failures: list[Exception] = []
        for item in successful:
            outbox = self.store.paths.outbox / item.attempt_id
            try:
                if item.outcome.result.artifact_paths != (item.artifact_path,):
                    raise ValueError("document mapper returned unexpected artifact paths")
                if self._outbox_artifact_paths(outbox) != (item.artifact_path,):
                    raise ValueError("document mapper outbox has unexpected artifacts")
                data = self._read_outbox_file(outbox, item.artifact_path)
                self._validate_document_map_bytes(item.document, data)
                self.store.put_artifact(item.artifact_path, data)
                self._read_document_map(item.document, item.artifact_path)
            except Exception as exc:
                validation_failures.append(exc)
            finally:
                self.store.discard_outbox(item.attempt_id)
        for item in noncompleted:
            self.store.discard_outbox(item.attempt_id)
            validation_failures.append(
                ValueError(
                    f"document mapper {item.document.document_id} did not complete"
                )
            )
        successful_attempts = {item.attempt_id for item in completed}
        for _, attempt_id, _ in pending:
            if attempt_id not in successful_attempts:
                self.store.discard_outbox(attempt_id)
        failures.extend(validation_failures)
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

    @staticmethod
    def _publication_id(artifacts: Mapping[str, bytes]) -> str:
        commitment = {
            relative_path: {
                "sha256": _sha256(data),
                "byte_length": len(data),
            }
            for relative_path, data in sorted(artifacts.items())
        }
        return _sha256(b"cpe-map-publication-v1\0" + canonical_json(commitment))

    def _publish_program_artifacts(
        self, artifacts: Mapping[str, bytes], *, program_path: str
    ) -> tuple[dict[str, object], str, str]:
        publication_id = self._publication_id(artifacts)
        prefix = (
            f"{_GENERATION_ROOT}/attempts/{publication_id}/artifacts"
        )
        records: dict[str, dict[str, object]] = {}
        for logical_path, data in sorted(artifacts.items()):
            physical_path = f"{prefix}/{logical_path}"
            self.store.put_artifact(physical_path, data)
            records[logical_path] = {
                "relative_path": physical_path,
                "sha256": _sha256(data),
                "byte_length": len(data),
            }
        manifest = {
            "schema_version": 1,
            "generation_id": _GENERATION_ID,
            "publication_id": publication_id,
            "program_map_sha256": _sha256(artifacts[program_path]),
            "artifacts": records,
        }
        manifest_bytes = canonical_json(manifest)
        manifest_path = (
            f"{_GENERATION_ROOT}/attempts/{publication_id}/accepted.json"
        )
        self.store.put_artifact(manifest_path, manifest_bytes)
        return manifest, manifest_path, _sha256(manifest_bytes)

    def _accepted_program_artifacts(
        self,
        manifest_path: str,
        manifest_sha256: str,
        *,
        require_event_selection: bool = True,
    ) -> dict[str, bytes]:
        manifest, artifacts = self.store.read_accepted_publication(
            manifest_path,
            manifest_sha256,
            require_event_selection=require_event_selection,
        )
        if frozenset(manifest) != frozenset(
            {
                "schema_version",
                "generation_id",
                "publication_id",
                "program_map_sha256",
                "artifacts",
            }
        ) or manifest.get("schema_version") != 1 or manifest.get(
            "generation_id"
        ) != _GENERATION_ID:
            raise ValueError("accepted program publication has invalid fields")
        publication_id = manifest.get("publication_id")
        records = manifest.get("artifacts")
        if (
            not isinstance(publication_id, str)
            or len(publication_id) != 64
            or not isinstance(records, Mapping)
            or not records
        ):
            raise ValueError("accepted program publication identity is invalid")
        prefix = f"{_GENERATION_ROOT}/attempts/{publication_id}/artifacts/"
        for logical_path, raw_record in records.items():
            if not isinstance(logical_path, str) or not isinstance(raw_record, Mapping):
                raise ValueError("accepted program publication record is invalid")
            if set(raw_record) != {"relative_path", "sha256", "byte_length"}:
                raise ValueError("accepted program publication record fields are invalid")
            physical_path = raw_record["relative_path"]
            if physical_path != f"{prefix}{logical_path}":
                raise ValueError("accepted program publication path is invalid")
        if self._publication_id(artifacts) != publication_id:
            raise ValueError("accepted program publication commitment does not match")
        program_path = f"{_GENERATION_ROOT}/program-map.json"
        if manifest.get("program_map_sha256") != _sha256(artifacts[program_path]):
            raise ValueError("accepted program map digest does not match")
        return artifacts

    def _validate_program_artifacts(
        self,
        document_maps: tuple[
            tuple[InputDocument, dict[str, object], bytes, str], ...
        ],
        *,
        reader: Callable[[str], bytes] | None = None,
    ) -> tuple[dict[str, object], bytes, tuple[str, ...]]:
        read = self.store.read_artifact if reader is None else reader
        program_path = f"{_GENERATION_ROOT}/program-map.json"
        program_bytes = read(program_path)
        document_hashes = {
            document.document_id: document.sha256
            for document, _, _, _ in document_maps
        }
        program = validate_program_map(
            _load_json(program_bytes, "program map"),
            document_hashes=document_hashes,
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
        mapped_requirements = {
            str(requirement["requirement_id"]): (document, requirement)
            for document, document_map, _, _ in document_maps
            for requirement in document_map["requirements"]
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

        expected_plan_wave_graph = {
            key: [
                item
                for _, document_map, _, _ in document_maps
                for item in document_map["plan_wave_graph"][key]
            ]
            for key in ("plans", "waves", "edges")
        }
        expected_plan_wave_graph["edges"] = [
            item
            for _, document_map, _, _ in document_maps
            for item in (
                *document_map["dependencies"],
                *document_map["plan_wave_graph"]["edges"],
            )
        ]
        if program["plan_wave_graph"] != expected_plan_wave_graph:
            raise ValueError("program map weakens or invents the mapped plan-wave graph")
        for field in ("hotspots", "decisions", "constraints"):
            expected = [
                item
                for _, document_map, _, _ in document_maps
                for item in document_map[field]
            ]
            if program[field] != expected:
                raise ValueError(f"program map weakens or invents mapped {field}")
        program_authority = {
            str(item["authority_id"]): item for item in program["authority_items"]
        }
        for _, document_map, _, _ in document_maps:
            for document_authority in document_map["authority_items"]:
                authority_id = str(document_authority["authority_id"])
                mapped = program_authority.get(authority_id)
                if mapped is None or any(
                    mapped[field] != document_authority[field]
                    for field in (
                        "authority_code",
                        "question",
                        "source_references",
                    )
                ):
                    raise ValueError("program map omits or changes mapped authority")

        global_constraint_bindings = [
            {
                "statement": constraint["statement"],
                "source_references": constraint["source_references"],
                "authority_ids": constraint["authority_ids"],
            }
            for _, document_map, _, _ in document_maps
            for constraint in document_map["constraints"]
            if constraint["kind"] == "global" and not constraint["affected_ids"]
        ]

        def encoded(values: list[dict[str, object]]) -> set[bytes]:
            return {canonical_json(item) for item in values}

        def candidate_reference(
            document: InputDocument, candidate: dict[str, object]
        ) -> dict[str, object]:
            return {
                "document_id": document.document_id,
                "heading": candidate["heading"],
                "line_start": candidate["line_start"],
                "line_end": candidate["line_end"],
                "source_sha256": document.sha256,
                "exact_excerpt": candidate["exact_excerpt"],
            }

        def requirement_reference(requirement_id: str) -> dict[str, object]:
            document, requirement = mapped_requirements[requirement_id]
            return {
                "document_id": document.document_id,
                "heading": requirement["heading"],
                "line_start": requirement["line_start"],
                "line_end": requirement["line_end"],
                "source_sha256": document.sha256,
                "exact_excerpt": requirement["exact_excerpt"],
            }

        task_by_id = {str(task["task_id"]): task for task in program["tasks"]}
        split_by_source = {
            str(split["source_task_id"]): split for split in program["task_splits"]
        }
        for source_task_id in split_by_source:
            if source_task_id not in task_candidates:
                raise ValueError("task split source_task_id is not a mapped candidate")

        for candidate_id, (candidate_document, candidate) in task_candidates.items():
            split = split_by_source.get(candidate_id)
            target_ids = (
                [str(item) for item in split["split_task_ids"]]
                if split is not None
                else [candidate_id]
            )
            target_tasks = [task_by_id[task_id] for task_id in target_ids]
            mapped_requirement_ids = {
                str(requirement_id)
                for requirement_id in candidate["requirement_ids"]
                if requirement_id in program["coverage"]
                and program["coverage"][requirement_id]["disposition"]
                in {"planned", "conflict"}
            }
            unknown_requirement_ids = set(candidate["requirement_ids"]) - set(
                program["coverage"]
            )
            if unknown_requirement_ids:
                raise ValueError(
                    "mapped candidate names unknown normative requirements: "
                    f"{sorted(unknown_requirement_ids)}"
                )
            actual_requirement_ids = {
                str(requirement_id)
                for task in target_tasks
                for requirement_id in task["requirement_ids"]
            }
            if actual_requirement_ids != mapped_requirement_ids:
                raise ValueError("program tasks weaken or invent mapped candidate coverage")
            requirement_constraints = [
                constraint
                for requirement_id in mapped_requirement_ids
                for constraint in mapped_requirements[requirement_id][1]["constraints"]
            ]
            expected_constraints = encoded(
                [
                    *candidate["global_constraints"],
                    *global_constraint_bindings,
                    *requirement_constraints,
                ]
            )
            if split is None:
                task = target_tasks[0]
                if task["dependencies"] != candidate["dependencies"]:
                    raise ValueError("program task dependencies differ from mapped candidate")
                if task["dependency_edges"] != candidate["dependency_edges"]:
                    raise ValueError("program dependency edges differ from mapped candidate")
                if task["acceptance"] != candidate["acceptance"]:
                    raise ValueError("program task acceptance differs from mapped candidate")
                if encoded(task["global_constraints"]) != expected_constraints:
                    raise ValueError("program task constraints differ from mapped candidate")
                if task["upstream_interface_commitments"] != candidate[
                    "upstream_interface_commitments"
                ]:
                    raise ValueError(
                        "program task upstream interfaces differ from mapped candidate"
                    )
            else:
                expected_reference = candidate_reference(candidate_document, candidate)
                if split["source_references"] != [expected_reference]:
                    raise ValueError("task split source reference differs from its candidate")
                external_dependencies = {
                    str(dependency)
                    for task in target_tasks
                    for dependency in task["dependencies"]
                    if dependency not in target_ids
                }
                if external_dependencies != set(candidate["dependencies"]):
                    raise ValueError("task split dependencies differ from mapped candidate")
                external_dependency_edges = [
                    edge
                    for task in target_tasks
                    for edge in task["dependency_edges"]
                    if edge["task_id"] not in target_ids
                ]
                if encoded(external_dependency_edges) != encoded(
                    candidate["dependency_edges"]
                ):
                    raise ValueError(
                        "task split dependency edges differ from mapped candidate"
                    )
                if encoded(
                    [item for task in target_tasks for item in task["acceptance"]]
                ) != encoded(candidate["acceptance"]):
                    raise ValueError("task split acceptance differs from mapped candidate")
                if encoded(
                    [
                        item
                        for task in target_tasks
                        for item in task["global_constraints"]
                    ]
                ) != expected_constraints:
                    raise ValueError("task split constraints differ from mapped candidate")
                if encoded(
                    [
                        item
                        for task in target_tasks
                        for item in task["upstream_interface_commitments"]
                    ]
                ) != encoded(candidate["upstream_interface_commitments"]):
                    raise ValueError(
                        "task split upstream interfaces differ from mapped candidate"
                    )

        for requirement_id, record in program["coverage"].items():
            expected_reference = requirement_reference(requirement_id)
            if canonical_json(expected_reference) not in encoded(
                record["source_references"]
            ):
                raise ValueError("coverage disposition omits its exact requirement source")

        program_sha256 = _sha256(program_bytes)
        document_sources = {
            document.document_id: self.store.read_artifact(document.snapshot_path)
            for document, _, _, _ in document_maps
        }
        self._verify_nested_source_references(program, sources=document_sources)
        artifact_paths = [
            program_path,
            f"{_GENERATION_ROOT}/coverage.json",
            f"{_GENERATION_ROOT}/authority-queue.json",
        ]
        coverage = _load_json(
            read(artifact_paths[1]), "coverage companion"
        )
        if coverage != {
            "schema_version": 1,
            "program_map_sha256": program_sha256,
            "coverage": program["coverage"],
        }:
            raise ValueError("coverage companion does not match the program map")
        authority_queue = _load_json(
            read(artifact_paths[2]), "authority queue"
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
            brief_bytes = read(brief_path)
            brief = validate_task_brief(
                _load_json(brief_bytes, f"task brief {task['task_id']}"),
                program_map_sha256=program_sha256,
                document_hashes=document_hashes,
            )
            if canonical_json(brief) != brief_bytes:
                raise ValueError("task brief is not in its canonical validated shape")
            self._verify_nested_source_references(brief, sources=document_sources)
            if (
                brief["task_id"] != task["task_id"]
                or brief["title"] != task["title"]
                or brief["dependencies"] != task["dependencies"]
                or brief["dependency_edges"] != task["dependency_edges"]
                or brief["acceptance"] != task["acceptance"]
                or brief["global_constraints"] != task["global_constraints"]
                or brief["upstream_interface_commitments"]
                != task["upstream_interface_commitments"]
            ):
                raise ValueError("task brief contract differs from program map")
            referenced_documents = {
                str(reference["document_id"])
                for reference in brief["source_references"]
            }
            if not set(task["document_ids"]) <= referenced_documents:
                raise ValueError("task brief omits a program-map source document")
            brief_source_references = {
                canonical_json(reference)
                for reference in brief["source_references"]
            }
            for requirement_id in task["requirement_ids"]:
                if canonical_json(requirement_reference(requirement_id)) not in (
                    brief_source_references
                ):
                    raise ValueError(
                        "task brief omits its canonical assigned requirement source"
                    )
            task_id = str(task["task_id"])
            if task_id in task_candidates:
                candidate_document, candidate = task_candidates[task_id]
                expected_task_reference = candidate_reference(
                    candidate_document, candidate
                )
                if canonical_json(expected_task_reference) not in {
                    canonical_json(reference)
                    for reference in brief["source_references"]
                }:
                    raise ValueError("task brief omits its exact mapped task source")
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

    @staticmethod
    def _generation_authority_state(
        program: Mapping[str, object]
    ) -> tuple[list[str], list[str]]:
        items = program.get("authority_items")
        if not isinstance(items, list):
            raise ValueError("program authority items are not event-safe")
        authority_ids = sorted(str(item["authority_id"]) for item in items)
        task_ids = sorted(
            {
                str(task_id)
                for item in items
                for task_id in item["affected_task_ids"]
            }
        )
        if len(authority_ids) > 64 or len(task_ids) > 64:
            raise ValueError("program authority state exceeds bounded generation event")
        return authority_ids, task_ids

    def map_program(self) -> str:
        """Compose validated document maps into one immutable global program map."""

        self.map_documents()
        document_maps = self._validated_document_maps()
        program_path = f"{_GENERATION_ROOT}/program-map.json"
        events = self.store.validate_event_chain()
        generation_events = [
            event
            for event in events
            if event["event_type"] == "map.generation_created"
            and event["payload"]["generation_id"] == _GENERATION_ID
        ]
        if len(generation_events) > 1:
            raise ValueError("map generation was accepted more than once")
        selected_manifest_path: str | None = None
        selected_manifest_sha256: str | None = None
        if generation_events:
            selected_manifest_path = generation_events[0]["payload"].get(
                "publication_manifest_path"
            )
            selected_manifest_sha256 = generation_events[0]["payload"].get(
                "publication_manifest_sha256"
            )
            if not isinstance(selected_manifest_path, str) or not isinstance(
                selected_manifest_sha256, str
            ):
                raise ValueError("map generation event omits accepted publication")
        reported_artifact_paths: tuple[str, ...] | None = None
        if not generation_events:
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
            try:
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
                    document_hashes={
                        document.document_id: document.sha256
                        for document, _, _, _ in document_maps
                    },
                )
                expected_reported_paths = {
                    program_path,
                    f"{_GENERATION_ROOT}/coverage.json",
                    f"{_GENERATION_ROOT}/authority-queue.json",
                    *(str(task["brief_path"]) for task in untrusted_program["tasks"]),
                }
                actual_paths = set(self._outbox_artifact_paths(outbox))
                if (
                    len(reported_artifact_paths) != len(expected_reported_paths)
                    or set(reported_artifact_paths) != expected_reported_paths
                    or actual_paths != expected_reported_paths
                ):
                    raise ValueError("program mapper returned unexpected artifact paths")
                staged_bytes = {
                    relative_path: self._read_outbox_file(outbox, relative_path)
                    for relative_path in sorted(expected_reported_paths)
                }
                staged_program, _, staged_paths = self._validate_program_artifacts(
                    document_maps,
                    reader=staged_bytes.__getitem__,
                )
                if staged_program != untrusted_program or set(staged_paths) != actual_paths:
                    raise ValueError("staged program artifacts changed during validation")
                blocking = sorted(
                    requirement_id
                    for requirement_id, record in staged_program["coverage"].items()
                    if record["disposition"] == "unmapped"
                )
                if blocking:
                    raise ValueError(f"blocking coverage dispositions: {blocking}")
                self._generation_authority_state(staged_program)
                _, selected_manifest_path, selected_manifest_sha256 = (
                    self._publish_program_artifacts(
                        staged_bytes, program_path=program_path
                    )
                )
            finally:
                self.store.discard_outbox(attempt_id)

        if not isinstance(selected_manifest_path, str) or not isinstance(
            selected_manifest_sha256, str
        ):
            raise ValueError("accepted program publication is unavailable")
        published_bytes = self._accepted_program_artifacts(
            selected_manifest_path,
            selected_manifest_sha256,
            require_event_selection=bool(generation_events),
        )
        program, program_bytes, artifact_paths = self._validate_program_artifacts(
            document_maps,
            reader=published_bytes.__getitem__,
        )
        returned_paths = set(artifact_paths)
        if not returned_paths:
            raise ValueError("program generation has no immutable artifacts")
        if reported_artifact_paths is not None and (
            len(reported_artifact_paths) != len(artifact_paths)
            or set(reported_artifact_paths) != returned_paths
        ):
            raise ValueError("program mapper returned unexpected artifact paths")
        blocking = sorted(
            requirement_id
            for requirement_id, record in program["coverage"].items()
            if record["disposition"] == "unmapped"
        )
        if blocking:
            raise ValueError(f"blocking coverage dispositions: {blocking}")

        authority_ids, authority_task_ids = self._generation_authority_state(program)
        generation_payload = {
            "generation_id": _GENERATION_ID,
            "map_sha256": _sha256(program_bytes),
            "publication_manifest_path": selected_manifest_path,
            "publication_manifest_sha256": selected_manifest_sha256,
            "authority_ids": authority_ids,
            "task_ids": authority_task_ids,
        }
        if generation_events:
            event_payload = generation_events[0]["payload"]
            if event_payload != generation_payload:
                raise ValueError("map generation event differs from immutable artifacts")
        else:
            self.store.append_event(
                "map.generation_created",
                generation_payload,
            )
        authority_path = f"{_GENERATION_ROOT}/authority-queue.json"
        self._append_authority_events(program, authority_path)
        return program_path

    @staticmethod
    def _task_slug(task_id: str) -> str:
        return task_id.replace(":", "-")

    def _program_context(
        self,
    ) -> tuple[dict[str, object], dict[str, Path]]:
        generation_events = [
            event
            for event in self.store.validate_event_chain()
            if event["event_type"] == "map.generation_created"
            and event["payload"]["generation_id"] == _GENERATION_ID
        ]
        if len(generation_events) != 1:
            raise ValueError("task queue requires one accepted map generation")
        payload = generation_events[0]["payload"]
        manifest_path = payload["publication_manifest_path"]
        manifest_sha256 = payload["publication_manifest_sha256"]
        if not isinstance(manifest_path, str) or not isinstance(manifest_sha256, str):
            raise ValueError("accepted map generation binding is invalid")
        manifest, artifacts = self.store.read_accepted_publication(
            manifest_path, manifest_sha256
        )
        program, _, _ = self._validate_program_artifacts(
            self._validated_document_maps(), reader=artifacts.__getitem__
        )
        descriptors = manifest["artifacts"]
        assert isinstance(descriptors, Mapping)
        physical: dict[str, Path] = {}
        for logical_path, descriptor in descriptors.items():
            if not isinstance(logical_path, str) or not isinstance(descriptor, Mapping):
                raise ValueError("accepted program artifact binding is invalid")
            relative_path = descriptor.get("relative_path")
            if not isinstance(relative_path, str):
                raise ValueError("accepted program artifact path is invalid")
            path = self.store.paths.root / relative_path
            if path.is_symlink() or not path.is_file():
                raise ValueError("accepted program artifact is unavailable")
            physical[logical_path] = path.resolve(strict=True)
        return program, physical

    def _artifact_input(self, relative_path: str, selected: Mapping[str, Path]) -> Path:
        if relative_path in selected:
            return selected[relative_path]
        self.store.read_artifact(relative_path)
        path = self.store.paths.root / relative_path
        if path.is_symlink() or not path.is_file():
            raise ValueError("queue input artifact is unavailable")
        return path.resolve(strict=True)

    @staticmethod
    def _dedupe_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
        result: list[Path] = []
        for path in paths:
            if path not in result:
                result.append(path)
        return tuple(result)

    @staticmethod
    def _result_digest(result: ChildResult, store: RunStore) -> str:
        artifact_hashes = []
        for relative_path in result.artifact_paths:
            artifact_hashes.append(_sha256(store.read_artifact(relative_path)))
        payload = {
            "role": result.role,
            "status": result.status,
            "item_id": result.item_id,
            "commit": result.commit,
            "verdict": result.verdict,
            "failure_code": result.failure_code,
            "authority_id": result.authority_id,
            "strategy_key": result.strategy_key,
            "artifact_sha256s": artifact_hashes,
        }
        return _sha256(canonical_json(payload))

    def _artifact_evidence_digest(self, relative_paths: Sequence[str]) -> str:
        hashes = sorted(_sha256(self.store.read_artifact(path)) for path in relative_paths)
        return _sha256(b"cpe-task-evidence-v1\0" + canonical_json(hashes))

    @staticmethod
    def _input_evidence_digest(paths: Sequence[Path]) -> str:
        hashes = sorted(_sha256(path.read_bytes()) for path in paths)
        return _sha256(b"cpe-task-input-v1\0" + canonical_json(hashes))

    def _assert_new_attempt(
        self, task_id: str, strategy_key: str, evidence_sha256: str
    ) -> None:
        for event in self.store.validate_event_chain():
            if event["event_type"] != "task.started":
                continue
            payload = event["payload"]
            if (
                payload["task_id"] == task_id
                and payload["strategy_key"] == strategy_key
                and payload["evidence_sha256"] == evidence_sha256
            ):
                raise ValueError(
                    "previously attempted strategy and evidence cannot be replayed"
                )

    def _attempted_strategies(
        self, task_id: str, evidence_sha256: str
    ) -> tuple[str, ...]:
        values = {
            str(event["payload"]["strategy_key"])
            for event in self.store.validate_event_chain()
            if event["event_type"] == "task.started"
            and event["payload"]["task_id"] == task_id
            and event["payload"]["evidence_sha256"] == evidence_sha256
        }
        return tuple(sorted(values))

    @staticmethod
    def _investigation_prefix(task_id: str) -> str:
        return f"reports/{QueueEngine._task_slug(task_id)}/investigations"

    @staticmethod
    def _investigation_record_path(
        task_id: str, sequence: int, record_type: str
    ) -> str:
        if record_type not in {"launch", "outcome"}:
            raise ValueError("investigation record type is invalid")
        return (
            f"{QueueEngine._investigation_prefix(task_id)}/"
            f"investigation-{sequence:04d}-{record_type}.json"
        )

    @staticmethod
    def _validate_investigation_launch(
        payload: object, *, task_id: str, expected_sequence: int
    ) -> dict[str, object]:
        fields = frozenset(
            {
                "schema_version",
                "investigation_id",
                "task_id",
                "sequence",
                "recovery_method",
                "previous_strategy",
                "dispatch_evidence_sha256",
                "attempted_strategies",
                "report_path",
            }
        )
        if not isinstance(payload, Mapping) or frozenset(payload) != fields:
            raise ValueError("investigation launch fields are invalid")
        value = dict(payload)
        sequence = value["sequence"]
        if (
            value["schema_version"] != 1
            or sequence != expected_sequence
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
        ):
            raise ValueError("investigation launch sequence is invalid")
        expected_id = (
            f"{QueueEngine._task_slug(task_id)}-investigation-{sequence:04d}"
        )
        if value["task_id"] != task_id or value["investigation_id"] != expected_id:
            raise ValueError("investigation launch identity is invalid")
        if value["recovery_method"] not in _INVESTIGATION_RECOVERY_METHODS:
            raise ValueError("investigation recovery method is invalid")
        for field in ("previous_strategy", "dispatch_evidence_sha256", "report_path"):
            if not isinstance(value[field], str) or not value[field]:
                raise ValueError(f"investigation launch {field} is invalid")
        digest = str(value["dispatch_evidence_sha256"])
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("investigation launch evidence digest is invalid")
        strategies = value["attempted_strategies"]
        if (
            not isinstance(strategies, list)
            or len(strategies) > 4096
            or not all(isinstance(item, str) and item for item in strategies)
            or strategies != sorted(set(strategies))
        ):
            raise ValueError("investigation attempted strategies are invalid")
        report_path = normalize_relative_path(str(value["report_path"]))
        expected_report = (
            f"reports/{QueueEngine._task_slug(task_id)}/"
            f"investigation-{sequence}.md"
        )
        if report_path != expected_report:
            raise ValueError("investigation report path is invalid")
        value["report_path"] = report_path
        return value

    @staticmethod
    def _validate_investigation_outcome(
        payload: object,
        *,
        task_id: str,
        expected_sequence: int,
        launch: Mapping[str, object],
    ) -> dict[str, object]:
        fields = frozenset(
            {
                "schema_version",
                "investigation_id",
                "task_id",
                "sequence",
                "recovery_method",
                "status",
                "strategy_key",
                "selection",
                "result_sha256",
                "artifact_paths",
            }
        )
        if not isinstance(payload, Mapping) or frozenset(payload) != fields:
            raise ValueError("investigation outcome fields are invalid")
        value = dict(payload)
        if (
            value["schema_version"] != 1
            or value["sequence"] != expected_sequence
            or value["investigation_id"] != launch["investigation_id"]
            or value["task_id"] != task_id
            or value["recovery_method"] != launch["recovery_method"]
        ):
            raise ValueError("investigation outcome identity is invalid")
        if value["selection"] not in {
            "accepted",
            "rejected_historical",
            "unusable",
        }:
            raise ValueError("investigation outcome selection is invalid")
        for field in ("status", "result_sha256"):
            if not isinstance(value[field], str) or not value[field]:
                raise ValueError(f"investigation outcome {field} is invalid")
        strategy_key = value["strategy_key"]
        if strategy_key is not None and (
            not isinstance(strategy_key, str) or not strategy_key
        ):
            raise ValueError("investigation outcome strategy_key is invalid")
        if value["selection"] != "unusable" and strategy_key is None:
            raise ValueError("usable investigation outcome requires a strategy_key")
        digest = str(value["result_sha256"])
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("investigation outcome digest is invalid")
        artifact_paths = value["artifact_paths"]
        if (
            not isinstance(artifact_paths, list)
            or not artifact_paths
            or len(artifact_paths) > 256
        ):
            raise ValueError("investigation outcome artifact paths are invalid")
        normalized_paths = [
            normalize_relative_path(str(path)) for path in artifact_paths
        ]
        if len(set(normalized_paths)) != len(normalized_paths):
            raise ValueError("investigation outcome artifact paths must be unique")
        if str(launch["report_path"]) not in normalized_paths:
            raise ValueError("investigation outcome omits its report artifact")
        value["artifact_paths"] = normalized_paths
        return value

    def _investigation_records(
        self, task_id: str
    ) -> tuple[tuple[dict[str, object], dict[str, object] | None], ...]:
        prefix = self._investigation_prefix(task_id)
        paths = self.store.artifact_paths(prefix=prefix)
        launch_paths = sorted(path for path in paths if path.endswith("-launch.json"))
        outcome_paths = {
            path for path in paths if path.endswith("-outcome.json")
        }
        records: list[tuple[dict[str, object], dict[str, object] | None]] = []
        expected_outcomes: set[str] = set()
        for sequence, path in enumerate(launch_paths, 1):
            expected_launch_path = self._investigation_record_path(
                task_id, sequence, "launch"
            )
            if path != expected_launch_path:
                raise ValueError("investigation launch history is not contiguous")
            launch = self._validate_investigation_launch(
                _load_json(self.store.read_artifact(path), "investigation launch"),
                task_id=task_id,
                expected_sequence=sequence,
            )
            outcome_path = self._investigation_record_path(
                task_id, sequence, "outcome"
            )
            expected_outcomes.add(outcome_path)
            outcome = None
            if outcome_path in outcome_paths:
                outcome = self._validate_investigation_outcome(
                    _load_json(
                        self.store.read_artifact(outcome_path),
                        "investigation outcome",
                    ),
                    task_id=task_id,
                    expected_sequence=sequence,
                    launch=launch,
                )
            records.append((launch, outcome))
        if outcome_paths - expected_outcomes:
            raise ValueError("investigation outcome has no durable launch")
        return tuple(records)

    def _investigation_history(self, task_id: str) -> tuple[dict[str, object], ...]:
        return tuple(
            outcome
            for _, outcome in self._investigation_records(task_id)
            if outcome is not None
        )

    def _record_investigation_launch(self, record: Mapping[str, object]) -> None:
        task_id = str(record.get("task_id", ""))
        sequence = record.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ValueError("investigation launch sequence is invalid")
        validated = self._validate_investigation_launch(
            record, task_id=task_id, expected_sequence=sequence
        )
        self.store.put_artifact(
            self._investigation_record_path(task_id, sequence, "launch"),
            canonical_json(validated),
        )

    def _record_investigation_outcome(self, record: Mapping[str, object]) -> None:
        task_id = str(record.get("task_id", ""))
        sequence = record.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ValueError("investigation outcome sequence is invalid")
        records = self._investigation_records(task_id)
        if sequence < 1 or sequence > len(records):
            raise ValueError("investigation outcome has no durable launch")
        launch, existing = records[sequence - 1]
        if existing is not None:
            raise ValueError("investigation outcome was already recorded")
        validated = self._validate_investigation_outcome(
            record,
            task_id=task_id,
            expected_sequence=sequence,
            launch=launch,
        )
        self.store.put_artifact(
            self._investigation_record_path(task_id, sequence, "outcome"),
            canonical_json(validated),
        )

    def _accepted_investigation_state(
        self,
        *,
        task_id: str,
        launch: Mapping[str, object],
        outcome: Mapping[str, object],
    ) -> str:
        if outcome.get("selection") != "accepted":
            raise ValueError("investigation outcome is not accepted")
        strategy_key = outcome.get("strategy_key")
        artifact_paths = outcome.get("artifact_paths")
        if not isinstance(strategy_key, str) or not isinstance(artifact_paths, list):
            raise ValueError("accepted investigation outcome is invalid")

        self.store.reconcile_autonomy_events()
        matching_decisions = [
            decision
            for decision in self.store.autonomy_decisions()
            if decision["strategy_key"] == strategy_key
            and decision["affected_tasks"] == [task_id]
            and set(artifact_paths).issubset(set(decision["evidence_paths"]))
        ]
        if not matching_decisions:
            premature_consumption = any(
                event["event_type"] == "task.started"
                and event["payload"]["task_id"] == task_id
                and event["payload"]["strategy_key"] == strategy_key
                and event["payload"]["evidence_sha256"]
                == launch["dispatch_evidence_sha256"]
                for event in self.store.validate_event_chain()
            )
            if premature_consumption:
                self._record_interrupted("investigation_replay_ambiguous")
                raise ValueError("accepted investigation replay is ambiguous")
            return "pending_decision"
        if len(matching_decisions) != 1:
            self._record_interrupted("investigation_replay_ambiguous")
            raise ValueError("accepted investigation replay is ambiguous")

        decision = matching_decisions[0]
        events = self.store.validate_event_chain()
        matching_events = [
            (index, event)
            for index, event in enumerate(events)
            if event["event_type"] == "autonomy.recorded"
            and event["payload"]["decision_id"] == decision["decision_id"]
            and event["payload"]["strategy_key"] == strategy_key
            and event["payload"].get("task_ids") == [task_id]
            and set(artifact_paths).issubset(
                set(event["payload"]["artifact_paths"])
            )
        ]
        if len(matching_events) != 1:
            self._record_interrupted("investigation_replay_ambiguous")
            raise ValueError("accepted investigation decision projection is ambiguous")

        decision_index, _ = matching_events[0]
        later_starts = [
            event
            for event in events[decision_index + 1 :]
            if event["event_type"] == "task.started"
            and event["payload"]["task_id"] == task_id
        ]
        if not later_starts:
            return "pending_dispatch"
        first_start = later_starts[0]["payload"]
        decision_evidence = self._artifact_evidence_digest(
            tuple(str(path) for path in decision["evidence_paths"])
        )
        allowed_evidence = {
            str(launch["dispatch_evidence_sha256"]),
            decision_evidence,
        }
        if (
            first_start["strategy_key"] != strategy_key
            or first_start["evidence_sha256"] not in allowed_evidence
        ):
            self._record_interrupted("investigation_replay_ambiguous")
            raise ValueError("accepted investigation consumption is ambiguous")
        return "consumed"

    def _append_investigation_decision(
        self,
        *,
        task_id: str,
        evidence_paths: Sequence[str],
        outcome: Mapping[str, object],
    ) -> None:
        strategy_key = outcome.get("strategy_key")
        outcome_paths = outcome.get("artifact_paths")
        if not isinstance(strategy_key, str) or not isinstance(outcome_paths, list):
            raise ValueError("accepted investigation outcome is invalid")
        self.store.append_autonomy_decision(
            issue="focused test or child evidence failed under the previous strategy",
            alternatives=["repeat patch", "fresh root-cause investigation"],
            selected="fresh root-cause investigation",
            strategy_key=strategy_key,
            rationale="same strategy and evidence made no progress",
            evidence_paths=list(dict.fromkeys([*evidence_paths, *outcome_paths])),
            affected_tasks=[task_id],
            reversible=True,
        )
        self.store.reconcile_autonomy_events()

    def _append_task_started(
        self,
        *,
        task_id: str,
        attempt_id: str,
        role: str,
        strategy_key: str,
        baseline_commit: str,
        evidence_sha256: str,
    ) -> None:
        self._assert_new_attempt(task_id, strategy_key, evidence_sha256)
        self.store.append_event(
            "task.started",
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "role": role,
                "strategy_key": strategy_key,
                "baseline_commit": baseline_commit,
                "evidence_sha256": evidence_sha256,
            },
        )

    def _task_by_id(self, task_id: str) -> dict[str, object]:
        program, _ = self._program_context()
        for task in program["tasks"]:
            if task["task_id"] == task_id:
                return task
        raise ValueError(f"unknown queue task: {task_id}")

    def _blocked_task_ids(self, state: Mapping[str, object]) -> set[str]:
        authorities = state.get("authorities", {})
        if not isinstance(authorities, Mapping):
            raise ValueError("replayed authority state is invalid")
        return {
            str(task_id)
            for authority in authorities.values()
            if isinstance(authority, Mapping)
            and authority.get("status") == "waiting_authority"
            for task_id in authority.get("task_ids", [])
        }

    def _next_ready_task(
        self, state: Mapping[str, object]
    ) -> dict[str, object] | None:
        program, _ = self._program_context()
        replayed_tasks = state.get("tasks", {})
        if not isinstance(replayed_tasks, Mapping):
            raise ValueError("replayed task state is invalid")
        blocked = self._blocked_task_ids(state)
        for task in program["tasks"]:
            task_id = str(task["task_id"])
            current = replayed_tasks.get(task_id, {})
            if isinstance(current, Mapping) and current.get("review_verdict") == "pass":
                continue
            if task_id in blocked:
                continue
            dependencies = [str(item) for item in task["dependencies"]]
            if all(
                isinstance(replayed_tasks.get(dependency), Mapping)
                and replayed_tasks[dependency].get("review_verdict") == "pass"
                for dependency in dependencies
            ):
                return task
        return None

    def _dependency_report_paths(
        self, task: Mapping[str, object], state: Mapping[str, object]
    ) -> tuple[str, ...]:
        replayed_tasks = state.get("tasks", {})
        assert isinstance(replayed_tasks, Mapping)
        paths: list[str] = []
        for dependency in task["dependencies"]:
            dependency_state = replayed_tasks.get(str(dependency))
            if not isinstance(dependency_state, Mapping):
                raise ValueError("ready task dependency has no durable state")
            reports = dependency_state.get("report_paths", [])
            if not isinstance(reports, list) or not reports:
                raise ValueError("ready task dependency has no interface report")
            for path in reports:
                if isinstance(path, str) and path not in paths:
                    paths.append(path)
        return tuple(paths)

    def _attempt_number(self, task_id: str) -> int:
        return len(
            [
                event
                for event in self.store.validate_event_chain()
                if event["event_type"] == "task.started"
                and event["payload"]["task_id"] == task_id
            ]
        ) + 1

    def _review_number(self, task_id: str) -> int:
        state = self.store.replay()
        task = state["tasks"].get(task_id, {})
        reviews = task.get("reviews", []) if isinstance(task, Mapping) else []
        return len(reviews) + 1

    def _launch_role(
        self,
        *,
        role: str,
        item_id: str,
        goal: str,
        input_paths: Sequence[Path],
        report_path: str,
        skills: tuple[str, ...],
        done_when: tuple[str, ...],
        attempt_id: str,
    ) -> LaunchOutcome:
        _, outbox = self._allocate_attempt(attempt_id)
        request = ChildRequest(
            role=role,
            item_id=item_id,
            goal=goal,
            input_paths=self._dedupe_paths(input_paths),
            repository=self.worktree.source,
            worktree=self.worktree.root,
            outbox=outbox,
            report_path=report_path,
            applicable_skills=skills,
            done_when=done_when,
        )
        try:
            return self.launcher.launch(
                request,
                worktree=self.worktree,
                store=self.store,
            )
        finally:
            self.store.discard_outbox(outbox.name)

    def _append_task_result(
        self,
        result: ChildResult,
        *,
        task_id: str,
        attempt_id: str,
        strategy_key: str,
    ) -> None:
        if result.strategy_key != strategy_key:
            raise ValueError("child result strategy_key differs from its dispatch")
        self.store.append_event(
            "task.reported",
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": result.status,
                "commit": result.commit,
                "strategy_key": strategy_key,
                "result_sha256": self._result_digest(result, self.store),
                "artifact_paths": list(result.artifact_paths),
            },
        )

    def _open_authority(self, result: ChildResult, task_id: str) -> None:
        if result.status != "waiting_authority" or result.authority_id not in AUTHORITY_CODES:
            raise ValueError("non-authority child result cannot open authority")
        known_documents = {
            document.document_id for document in self.store.document_set()
        }
        affected_documents = set(result.affected_document_ids)
        unknown = affected_documents - known_documents
        if unknown:
            raise ValueError(
                f"unknown affected document IDs: {sorted(unknown)}"
            )
        if not affected_documents:
            raise ValueError("authority result must name affected documents")
        program, _ = self._program_context()
        affected_tasks = [
            str(task["task_id"])
            for task in program["tasks"]
            if affected_documents & set(task["document_ids"])
        ]
        if task_id not in affected_tasks:
            raise ValueError("authority affected documents do not cover the current task")
        if len(affected_tasks) > 64:
            raise ValueError("authority affects more than 64 tasks")
        existing = [
            event
            for event in self.store.validate_event_chain()
            if event["event_type"] == "authority.opened"
        ]
        authority_id = f"A{len(existing) + 1:04d}"
        self.store.append_event(
            "authority.opened",
            {
                "authority_id": authority_id,
                "authority_code": result.authority_id,
                "status": "waiting_authority",
                "task_ids": affected_tasks,
                "artifact_paths": list(result.artifact_paths),
            },
        )

    def _run_task(self, task: Mapping[str, object]) -> None:
        task_id = str(task["task_id"])
        state = self.store.replay()
        _, selected = self._program_context()
        attempt_number = self._attempt_number(task_id)
        attempt_id = f"{self._task_slug(task_id)}-attempt-{attempt_number:04d}"
        strategy_key = "initial"
        report_path = f"reports/{self._task_slug(task_id)}/attempt-{attempt_number}.md"
        start_commit = self.worktree.head()
        dependency_reports = self._dependency_report_paths(task, state)
        inputs = [
            selected[str(task["brief_path"])],
            *(self._artifact_input(path, selected) for path in dependency_reports),
        ]
        self._append_task_started(
            task_id=task_id,
            attempt_id=attempt_id,
            role="task_agent",
            strategy_key=strategy_key,
            baseline_commit=start_commit,
            evidence_sha256=self._input_evidence_digest(inputs),
        )
        outcome = self._launch_role(
            role="task_agent",
            item_id=task_id,
            goal=(
                f"Strategy key: {strategy_key}\n"
                "Implement exactly the immutable task brief and produce a commit-bound "
                "clean handoff."
            ),
            input_paths=inputs,
            report_path=report_path,
            skills=("using-superpowers", "test-driven-development"),
            done_when=(
                "focused covering tests pass",
                "one real commit equals clean worktree HEAD",
            ),
            attempt_id=attempt_id,
        )
        self._append_task_result(
            outcome.result,
            task_id=task_id,
            attempt_id=attempt_id,
            strategy_key=strategy_key,
        )
        if outcome.result.status == "completed":
            assert outcome.result.commit is not None
            self._run_review(task, start_commit, outcome.result.commit)
        elif outcome.result.status == "waiting_authority":
            self._open_authority(outcome.result, task_id)
        else:
            commit = self._handle_child_failure(outcome.result, task_id)
            if commit is not None:
                self._run_review(task, start_commit, commit)

    def _run_review(
        self, task: Mapping[str, object], start_commit: str, end_commit: str
    ) -> None:
        task_id = str(task["task_id"])
        while True:
            review_number = self._review_number(task_id)
            review_id = f"{self._task_slug(task_id)}-review-{review_number:04d}"
            report_path = f"reviews/{self._task_slug(task_id)}/review-{review_number}.md"
            diff_path = f"reports/{self._task_slug(task_id)}/diff-{review_number}.patch"
            self.store.put_artifact(
                diff_path, self.worktree.diff(start_commit, end_commit).encode("utf-8")
            )
            state = self.store.replay()
            _, selected = self._program_context()
            task_state = state["tasks"][task_id]
            previous_review_digests = {
                review.get("evidence_sha256")
                for review in task_state.get("reviews", [])
                if isinstance(review, Mapping)
                and review.get("verdict") == "changes_requested"
            }
            input_paths = [
                selected[str(task["brief_path"])],
                *(self._artifact_input(path, selected) for path in task_state["report_paths"]),
                *(
                    self._artifact_input(path, selected)
                    for path in self._dependency_report_paths(task, state)
                ),
                self._artifact_input(diff_path, selected),
            ]
            outcome = self._launch_role(
                role="reviewer",
                item_id=task_id,
                goal=(
                    f"Review the exact immutable task range {start_commit}..{end_commit}; "
                    "use the supplied focused-test evidence and do not rerun the identical command."
                ),
                input_paths=input_paths,
                report_path=report_path,
                skills=("using-superpowers", "requesting-code-review"),
                done_when=("all Critical and Important findings are reported together",),
                attempt_id=review_id,
            )
            result = outcome.result
            material_paths = tuple(
                path for path in result.artifact_paths if path != report_path
            ) or result.artifact_paths
            evidence_sha256 = self._artifact_evidence_digest(material_paths)
            self.store.append_event(
                "review.reported",
                {
                    "task_id": task_id,
                    "review_id": review_id,
                    "status": result.status,
                    "commit": end_commit,
                    "verdict": result.verdict,
                    "result_sha256": self._result_digest(result, self.store),
                    "evidence_sha256": evidence_sha256,
                    "artifact_paths": list(result.artifact_paths),
                },
            )
            if result.status == "completed" and result.verdict == "pass":
                return
            if result.status == "waiting_authority":
                self._open_authority(result, task_id)
                return
            if result.status == "changes_requested" and result.verdict == "changes_requested":
                if evidence_sha256 in previous_review_digests:
                    latest_strategy = str(
                        task_state.get("latest_strategy_key") or "review-consolidated"
                    )
                    strategy, investigation_paths = self._run_investigation(
                        task,
                        result.artifact_paths,
                        previous_strategy=latest_strategy,
                        dispatch_evidence_sha256=evidence_sha256,
                    )
                    finding_paths = (*result.artifact_paths, *investigation_paths)
                else:
                    strategy = "review-consolidated"
                    finding_paths = result.artifact_paths
                fixed_commit = self._run_consolidated_fix(
                    task,
                    finding_paths,
                    strategy_key=strategy,
                    evidence_sha256=evidence_sha256,
                )
                if fixed_commit is None:
                    return
                end_commit = fixed_commit
                continue
            commit = self._handle_child_failure(result, task_id)
            if commit is None:
                return
            end_commit = commit

    def _run_consolidated_fix(
        self,
        task: Mapping[str, object],
        finding_paths: Sequence[str],
        *,
        strategy_key: str,
        evidence_sha256: str | None = None,
    ) -> str | None:
        task_id = str(task["task_id"])
        attempt_number = self._attempt_number(task_id)
        attempt_id = f"{self._task_slug(task_id)}-attempt-{attempt_number:04d}"
        report_path = f"reports/{self._task_slug(task_id)}/attempt-{attempt_number}.md"
        state = self.store.replay()
        _, selected = self._program_context()
        inputs = [
            selected[str(task["brief_path"])],
            *(self._artifact_input(path, selected) for path in finding_paths),
            *(
                self._artifact_input(path, selected)
                for path in self._dependency_report_paths(task, state)
            ),
        ]
        baseline_commit = self.worktree.head()
        dispatch_evidence = (
            evidence_sha256
            if evidence_sha256 is not None
            else self._artifact_evidence_digest(finding_paths)
        )
        self._append_task_started(
            task_id=task_id,
            attempt_id=attempt_id,
            role="fix_agent",
            strategy_key=strategy_key,
            baseline_commit=baseline_commit,
            evidence_sha256=dispatch_evidence,
        )
        outcome = self._launch_role(
            role="fix_agent",
            item_id=task_id,
            goal=(
                f"Strategy key: {strategy_key}\n"
                "Fix every supplied Critical and Important finding in one consolidated commit."
            ),
            input_paths=inputs,
            report_path=report_path,
            skills=("using-superpowers", "systematic-debugging", "test-driven-development"),
            done_when=("covering checks pass and one clean fix commit equals HEAD",),
            attempt_id=attempt_id,
        )
        self._append_task_result(
            outcome.result,
            task_id=task_id,
            attempt_id=attempt_id,
            strategy_key=strategy_key,
        )
        if outcome.result.status == "completed":
            assert outcome.result.commit is not None
            return outcome.result.commit
        if outcome.result.status == "waiting_authority":
            self._open_authority(outcome.result, task_id)
            return None
        recovered = self._handle_child_failure(outcome.result, task_id)
        if recovered is None:
            return None
        return recovered

    def _run_investigation(
        self,
        task: Mapping[str, object],
        evidence_paths: Sequence[str],
        *,
        previous_strategy: str,
        dispatch_evidence_sha256: str | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        task_id = str(task["task_id"])
        state = self.store.replay()
        _, selected = self._program_context()
        inputs = [
            selected[str(task["brief_path"])],
            *(self._artifact_input(path, selected) for path in evidence_paths),
            *(
                self._artifact_input(path, selected)
                for path in self._dependency_report_paths(task, state)
            ),
        ]
        selection_evidence = (
            dispatch_evidence_sha256
            if dispatch_evidence_sha256 is not None
            else self._artifact_evidence_digest(evidence_paths)
        )
        records = self._investigation_records(task_id)
        evidence_records = tuple(
            (launch, outcome)
            for launch, outcome in records
            if launch["dispatch_evidence_sha256"] == selection_evidence
        )
        attempted_history = set(
            self._attempted_strategies(task_id, selection_evidence)
        )
        attempted_history.update(
            str(outcome["strategy_key"])
            for _, outcome in evidence_records
            if outcome is not None and outcome["strategy_key"] is not None
        )

        recovery_method = _INVESTIGATION_RECOVERY_METHODS[0]
        if evidence_records:
            latest_launch, latest_outcome = evidence_records[-1]
            latest_method = str(latest_launch["recovery_method"])
            if latest_outcome is not None and latest_outcome["selection"] == "accepted":
                accepted_state = self._accepted_investigation_state(
                    task_id=task_id,
                    launch=latest_launch,
                    outcome=latest_outcome,
                )
                if accepted_state == "pending_decision":
                    self._append_investigation_decision(
                        task_id=task_id,
                        evidence_paths=evidence_paths,
                        outcome=latest_outcome,
                    )
                if accepted_state != "consumed":
                    return (
                        str(latest_outcome["strategy_key"]),
                        tuple(
                            str(path) for path in latest_outcome["artifact_paths"]
                        ),
                    )
            try:
                recovery_index = _INVESTIGATION_RECOVERY_METHODS.index(latest_method)
            except ValueError as error:
                raise ValueError("investigation recovery history is invalid") from error
            if recovery_index + 1 >= len(_INVESTIGATION_RECOVERY_METHODS):
                self._record_interrupted("investigator_recovery_methods_exhausted")
                raise ValueError("investigator recovery methods exhausted")
            recovery_method = _INVESTIGATION_RECOVERY_METHODS[recovery_index + 1]

        while True:
            investigation_number = len(records) + 1
            investigation_id = (
                f"{self._task_slug(task_id)}-investigation-"
                f"{investigation_number:04d}"
            )
            report_path = (
                f"reports/{self._task_slug(task_id)}/"
                f"investigation-{investigation_number}.md"
            )
            launch = {
                "schema_version": 1,
                "investigation_id": investigation_id,
                "task_id": task_id,
                "sequence": investigation_number,
                "recovery_method": recovery_method,
                "previous_strategy": previous_strategy,
                "dispatch_evidence_sha256": selection_evidence,
                "attempted_strategies": sorted(attempted_history),
                "report_path": report_path,
            }
            self._record_investigation_launch(launch)
            outcome = self._launch_role(
                role="investigator",
                item_id=task_id,
                goal=(
                    "Reproduce the failure, identify the root cause, and select a "
                    "materially changed recovery strategy. "
                    f"Recovery method: {recovery_method}. Previously attempted "
                    "strategies for this evidence: "
                    f"{json.dumps(sorted(attempted_history))}"
                ),
                input_paths=inputs,
                report_path=report_path,
                skills=("using-superpowers", "systematic-debugging"),
                done_when=("the root cause and a changed strategy are recorded",),
                attempt_id=investigation_id,
            )
            result = outcome.result
            candidate_evidence = (
                dispatch_evidence_sha256
                if dispatch_evidence_sha256 is not None
                else self._artifact_evidence_digest(
                    (*evidence_paths, *result.artifact_paths)
                )
            )
            attempted = self._attempted_strategies(task_id, candidate_evidence)
            if result.status != "completed" or not result.strategy_key:
                selection = "unusable"
            elif result.strategy_key == previous_strategy:
                selection = "unusable"
            elif result.strategy_key in attempted:
                selection = "rejected_historical"
            else:
                selection = "accepted"
            durable_outcome = {
                "schema_version": 1,
                "investigation_id": investigation_id,
                "task_id": task_id,
                "sequence": investigation_number,
                "recovery_method": recovery_method,
                "status": result.status,
                "strategy_key": result.strategy_key,
                "selection": selection,
                "result_sha256": self._result_digest(result, self.store),
                "artifact_paths": list(result.artifact_paths),
            }
            self._record_investigation_outcome(durable_outcome)
            records = (*records, (launch, durable_outcome))

            if selection == "unusable" and result.strategy_key == previous_strategy:
                self._record_interrupted("investigator_unchanged_strategy")
                raise ValueError("unchanged strategy_key cannot be redispatched")
            if selection == "accepted":
                assert result.strategy_key is not None
                self._append_investigation_decision(
                    task_id=task_id,
                    evidence_paths=evidence_paths,
                    outcome=durable_outcome,
                )
                return result.strategy_key, result.artifact_paths

            if result.strategy_key:
                attempted_history.add(result.strategy_key)
            recovery_index = _INVESTIGATION_RECOVERY_METHODS.index(recovery_method)
            if recovery_index + 1 >= len(_INVESTIGATION_RECOVERY_METHODS):
                self._record_interrupted("investigator_recovery_methods_exhausted")
                raise ValueError("investigator recovery methods exhausted")
            recovery_method = _INVESTIGATION_RECOVERY_METHODS[recovery_index + 1]

    def _handle_child_failure(self, result: ChildResult, task_id: str) -> str | None:
        if result.status == "waiting_authority":
            self._open_authority(result, task_id)
            return None
        task = self._task_by_id(task_id)
        previous_strategy = result.strategy_key or "initial"
        strategy_key, investigation_paths = self._run_investigation(
            task,
            result.artifact_paths,
            previous_strategy=previous_strategy,
        )
        return self._run_consolidated_fix(
            task,
            (*result.artifact_paths, *investigation_paths),
            strategy_key=strategy_key,
        )

    def _commit_parent(self, commit: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.worktree.root), "rev-parse", f"{commit}^{{commit}}^"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            raise ValueError("completed task commit has no valid parent")
        parent = completed.stdout.strip()
        if len(parent) != 40:
            raise ValueError("completed task parent is not a full commit")
        return parent

    def _record_interrupted(self, failure_code: str) -> None:
        events = self.store.validate_event_chain()
        if not (
            events
            and events[-1]["event_type"] == "run.interrupted"
            and events[-1]["payload"]["failure_code"] == failure_code
        ):
            self.store.append_event(
                "run.interrupted",
                {"status": "interrupted", "failure_code": failure_code},
            )

    def _recover_active_attempt(
        self, task: Mapping[str, object], task_state: Mapping[str, object]
    ) -> None:
        task_id = str(task["task_id"])
        active = task_state.get("active_attempt")
        if not isinstance(active, Mapping):
            raise ValueError("active task attempt is invalid")
        baseline = active.get("baseline_commit")
        attempt_id = active.get("attempt_id")
        strategy_key = active.get("strategy_key")
        role = active.get("role")
        evidence_sha256 = active.get("evidence_sha256")
        if not all(
            isinstance(value, str) and value
            for value in (
                baseline,
                attempt_id,
                strategy_key,
                role,
                evidence_sha256,
            )
        ):
            raise ValueError("active task attempt lacks durable launch binding")
        if self.worktree.status():
            self._record_interrupted("active_writer_left_dirty_worktree")
            raise ValueError("active writer left a dirty worktree; run is interrupted")
        head = self.worktree.head()
        if head == baseline:
            self._record_interrupted("active_writer_has_no_bound_result")
            raise ValueError("active writer has no bound result; run is interrupted")
        ancestor = subprocess.run(
            [
                "git",
                "-C",
                str(self.worktree.root),
                "merge-base",
                "--is-ancestor",
                str(baseline),
                head,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ancestor.returncode != 0:
            self._record_interrupted("active_writer_commit_not_descendant")
            raise ValueError("active writer commit is not based on its baseline")

        report_number = str(attempt_id).rsplit("-", 1)[-1].lstrip("0") or "0"
        report_path = f"reports/{self._task_slug(task_id)}/attempt-{report_number}.md"
        try:
            self.store.read_artifact(report_path)
        except ValueError as exc:
            self._record_interrupted("active_writer_report_unavailable")
            raise ValueError("active writer report is unavailable; run is interrupted") from exc
        diff_path = (
            f"reports/{self._task_slug(task_id)}/{attempt_id}-interrupted.patch"
        )
        self.store.put_artifact(
            diff_path, self.worktree.diff(str(baseline), head).encode("utf-8")
        )
        recovered_paths = [report_path, diff_path]
        self.store.append_event(
            "task.reported",
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "interrupted",
                "commit": head,
                "strategy_key": strategy_key,
                "artifact_paths": recovered_paths,
            },
        )
        changed_strategy, investigation_paths = self._run_investigation(
            task,
            recovered_paths,
            previous_strategy=str(strategy_key),
        )
        fixed = self._run_consolidated_fix(
            task,
            (*recovered_paths, *investigation_paths),
            strategy_key=changed_strategy,
        )
        if fixed is None:
            return
        completed = [
            attempt
            for attempt in task_state.get("attempts", [])
            if isinstance(attempt, Mapping)
            and attempt.get("status") == "completed"
            and isinstance(attempt.get("commit"), str)
        ]
        review_start = (
            self._commit_parent(str(completed[0]["commit"]))
            if completed
            else str(baseline)
        )
        self._run_review(task, review_start, fixed)

    def _resume_task(
        self, task: Mapping[str, object], task_state: Mapping[str, object]
    ) -> None:
        task_id = str(task["task_id"])
        attempts = task_state.get("attempts", [])
        if not isinstance(attempts, list):
            raise ValueError("replayed task attempts are invalid")
        if isinstance(task_state.get("active_attempt"), Mapping):
            self._recover_active_attempt(task, task_state)
            return
        completed = [
            attempt
            for attempt in attempts
            if isinstance(attempt, Mapping)
            and attempt.get("status") == "completed"
            and isinstance(attempt.get("commit"), str)
        ]
        latest_attempt = attempts[-1] if attempts else None
        if isinstance(latest_attempt, Mapping) and latest_attempt.get("status") in {
            "failed",
            "interrupted",
        }:
            evidence_paths = latest_attempt.get("artifact_paths", [])
            previous_strategy = latest_attempt.get("strategy_key") or "initial"
            if not isinstance(evidence_paths, list) or not all(
                isinstance(path, str) for path in evidence_paths
            ):
                raise ValueError("failed or interrupted task evidence is invalid")
            pending = task_state.get("pending_recovery")
            if isinstance(pending, Mapping):
                strategy = pending.get("strategy_key")
                recovery_paths = pending.get("artifact_paths")
                if not isinstance(strategy, str) or not isinstance(
                    recovery_paths, list
                ) or not all(isinstance(path, str) for path in recovery_paths):
                    raise ValueError("pending autonomous recovery is invalid")
                investigation_paths = tuple(recovery_paths)
            else:
                strategy, investigation_paths = self._run_investigation(
                    task,
                    evidence_paths,
                    previous_strategy=str(previous_strategy),
                )
            if completed:
                review_start = self._commit_parent(str(completed[0]["commit"]))
            else:
                baseline = latest_attempt.get("baseline_commit")
                review_start = (
                    str(baseline)
                    if latest_attempt.get("status") == "interrupted"
                    and isinstance(baseline, str)
                    else self.worktree.head()
                )
            recovered = self._run_consolidated_fix(
                task,
                (*evidence_paths, *investigation_paths),
                strategy_key=strategy,
            )
            if recovered is not None:
                self._run_review(task, review_start, recovered)
            return
        if not completed:
            self._run_task(task)
            return

        first_commit = str(completed[0]["commit"])
        end_commit = str(completed[-1]["commit"])
        start_commit = self._commit_parent(first_commit)
        reviews = task_state.get("reviews", [])
        if not isinstance(reviews, list):
            raise ValueError("replayed task reviews are invalid")
        last_review = reviews[-1] if reviews else None
        if isinstance(last_review, Mapping) and last_review.get("verdict") == "changes_requested":
            finding_paths = last_review.get("artifact_paths", [])
            if not isinstance(finding_paths, list) or not all(
                isinstance(path, str) for path in finding_paths
            ):
                raise ValueError("review finding paths are invalid")
            reviewed_commit = last_review.get("commit")
            if reviewed_commit == end_commit:
                review_evidence = last_review.get("evidence_sha256")
                if not isinstance(review_evidence, str):
                    raise ValueError("review finding evidence digest is invalid")
                end_commit = self._run_consolidated_fix(
                    task,
                    finding_paths,
                    strategy_key="review-consolidated",
                    evidence_sha256=review_evidence,
                )
                if end_commit is None:
                    return
        elif isinstance(last_review, Mapping) and last_review.get("status") == "failed":
            evidence_paths = last_review.get("artifact_paths", [])
            if not isinstance(evidence_paths, list) or not all(
                isinstance(path, str) for path in evidence_paths
            ):
                raise ValueError("failed review evidence is invalid")
            strategy, investigation_paths = self._run_investigation(
                task,
                evidence_paths,
                previous_strategy="review-failed",
            )
            recovered = self._run_consolidated_fix(
                task,
                (*evidence_paths, *investigation_paths),
                strategy_key=strategy,
            )
            if recovered is None:
                return
            end_commit = recovered
        self._run_review(task, start_commit, end_commit)

    @staticmethod
    def _final_root(revision: str) -> str:
        return f"verification/final/{revision}"

    def _audit_path(self, revision: str, document_id: str) -> str:
        return f"{self._final_root(revision)}/audits/{document_id}.json"

    def _terminal_path(self, revision: str) -> str:
        return f"{self._final_root(revision)}/terminal.json"

    def _integration_launch_path(self, revision: str) -> str:
        return f"{self._final_root(revision)}/integration-launch.json"

    def _integration_result_path(self, revision: str) -> str:
        return f"{self._final_root(revision)}/integration-result.json"

    def _integration_handoff_path(self, revision: str) -> str:
        return f"{self._final_root(revision)}/integration-handoff.json"

    def _integration_failure_path(self, revision: str) -> str:
        return f"{self._final_root(revision)}/integration-child-failure.json"

    def _integration_retry_path(self, revision: str) -> str:
        return f"{self._final_root(revision)}/integration-retry-launch.json"

    def _tasks_are_final_ready(
        self, state: Mapping[str, object], program: Mapping[str, object]
    ) -> bool:
        if state.get("status") == "completed":
            return False
        replayed_tasks = state.get("tasks")
        authorities = state.get("authorities")
        if not isinstance(replayed_tasks, Mapping) or not isinstance(
            authorities, Mapping
        ):
            raise ValueError("replayed final queue state is invalid")
        if any(
            isinstance(authority, Mapping)
            and authority.get("status") == "waiting_authority"
            for authority in authorities.values()
        ):
            return False
        return all(
            isinstance(replayed_tasks.get(str(task["task_id"])), Mapping)
            and replayed_tasks[str(task["task_id"])].get("review_verdict") == "pass"
            for task in program["tasks"]
        )

    def _audit_requirements(
        self, document: InputDocument
    ) -> tuple[str, ...]:
        document_map, _ = self._read_document_map(
            document, self._document_map_path(document)
        )
        return tuple(
            str(requirement["requirement_id"])
            for requirement in document_map["requirements"]
            if requirement["kind"] == "normative"
        )

    def _validate_audit_event(
        self,
        event: Mapping[str, object],
        *,
        document: InputDocument,
        revision: str,
    ) -> tuple[str, str]:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("document audit event payload is invalid")
        expected_path = self._audit_path(revision, document.document_id)
        paths = payload.get("artifact_paths")
        if paths != [expected_path]:
            raise ValueError("document audit event has unexpected artifacts")
        data = self.store.read_artifact(expected_path)
        validated = validate_document_audit(
            _load_json(data, f"document audit {document.document_id}"),
            document_id=document.document_id,
            source_sha256=document.sha256,
            revision=revision,
            requirement_ids=self._audit_requirements(document),
        )
        if canonical_json(validated) != data:
            raise ValueError("document audit is not in its canonical validated shape")
        verdict = str(validated["verdict"])
        if payload.get("status") != "completed" or payload.get("verdict") != verdict:
            raise ValueError("document audit event differs from its artifact")
        report_sha256 = payload.get("report_sha256")
        if report_sha256 is not None and report_sha256 != _sha256(data):
            raise ValueError("document audit event report digest does not match")
        return expected_path, verdict

    def _current_document_audits(
        self, revision: str
    ) -> dict[str, tuple[str, str]]:
        documents = {item.document_id: item for item in self.store.document_set()}
        result: dict[str, tuple[str, str]] = {}
        for event in self.store.validate_event_chain():
            if event["event_type"] != "audit.reported":
                continue
            payload = event["payload"]
            if payload.get("commit") != revision:
                continue
            paths = payload.get("artifact_paths")
            if not isinstance(paths, list) or len(paths) != 1:
                raise ValueError("document audit event has invalid artifacts")
            matched = [
                document
                for document in documents.values()
                if paths[0] == self._audit_path(revision, document.document_id)
            ]
            if len(matched) != 1 or matched[0].document_id in result:
                raise ValueError("document audit events are ambiguous")
            document = matched[0]
            result[document.document_id] = self._validate_audit_event(
                event, document=document, revision=revision
            )
        return result

    def _audit_inputs(
        self,
        document: InputDocument,
        *,
        revision: str,
        program: Mapping[str, object],
        selected: Mapping[str, Path],
        state: Mapping[str, object],
    ) -> tuple[Path, ...]:
        source = self.store.paths.root / document.snapshot_path
        inputs: list[Path] = [source.resolve(strict=True)]
        inputs.append(
            self._artifact_input(self._document_map_path(document), selected)
        )
        replayed_tasks = state["tasks"]
        assert isinstance(replayed_tasks, Mapping)
        for task in program["tasks"]:
            if document.document_id not in task["document_ids"]:
                continue
            task_id = str(task["task_id"])
            inputs.append(selected[str(task["brief_path"])])
            task_state = replayed_tasks.get(task_id)
            if not isinstance(task_state, Mapping):
                raise ValueError("final audit task evidence is unavailable")
            evidence_paths = [
                *task_state.get("report_paths", []),
                *(
                    path
                    for review in task_state.get("reviews", [])
                    if isinstance(review, Mapping)
                    for path in review.get("artifact_paths", [])
                ),
            ]
            if not all(isinstance(path, str) for path in evidence_paths):
                raise ValueError("final audit task artifact paths are invalid")
            inputs.extend(
                self._artifact_input(str(path), selected) for path in evidence_paths
            )
            attempts = task_state.get("attempts", [])
            baseline = self.worktree.base_commit
            if attempts and isinstance(attempts[0], Mapping):
                candidate = attempts[0].get("baseline_commit")
                if isinstance(candidate, str):
                    baseline = candidate
            passing_reviews = [
                review
                for review in task_state.get("reviews", [])
                if isinstance(review, Mapping)
                and review.get("verdict") == "pass"
                and isinstance(review.get("commit"), str)
            ]
            if not passing_reviews:
                raise ValueError("final audit task has no passing reviewed commit")
            reviewed_commit = str(passing_reviews[-1]["commit"])
            diff_path = (
                f"{self._final_root(revision)}/diffs/"
                f"{document.document_id}-{self._task_slug(task_id)}.patch"
            )
            self.store.put_artifact(
                diff_path,
                self.worktree.diff(baseline, reviewed_commit).encode("utf-8"),
            )
            inputs.append(self._artifact_input(diff_path, selected))
        integration_state = replayed_tasks.get("program:integration")
        if isinstance(integration_state, Mapping):
            for attempt in integration_state.get("attempts", []):
                if not isinstance(attempt, Mapping) or attempt.get("status") != "completed":
                    continue
                baseline = attempt.get("baseline_commit")
                commit = attempt.get("commit")
                attempt_id = attempt.get("attempt_id")
                if not all(
                    isinstance(value, str) and value
                    for value in (baseline, commit, attempt_id)
                ):
                    raise ValueError("integration fix audit range is invalid")
                diff_path = (
                    f"{self._final_root(revision)}/diffs/"
                    f"{document.document_id}-{attempt_id}.patch"
                )
                self.store.put_artifact(
                    diff_path,
                    self.worktree.diff(str(baseline), str(commit)).encode("utf-8"),
                )
                inputs.append(self._artifact_input(diff_path, selected))
        return self._dedupe_paths(inputs)

    def _run_document_audits(self, revision: str) -> dict[str, tuple[str, str]]:
        audits = self._current_document_audits(revision)
        program, selected = self._program_context()
        state = self.store.replay()
        for document in self.store.document_set():
            if document.document_id in audits:
                continue
            report_path = self._audit_path(revision, document.document_id)
            outcome = self._launch_role(
                role="document_auditor",
                item_id=document.document_id,
                goal=(
                    "Audit only this immutable source document against its mapped "
                    f"requirements and supplied implementation evidence at {revision}."
                ),
                input_paths=self._audit_inputs(
                    document,
                    revision=revision,
                    program=program,
                    selected=selected,
                    state=state,
                ),
                report_path=report_path,
                skills=("using-superpowers", "verification-before-completion"),
                done_when=(
                    "every normative requirement has one explicit coverage verdict",
                    "the verdict is bound to the exact immutable source and revision",
                ),
                attempt_id=(
                    f"final-audit-{document.document_id}-{revision[:12]}"
                ),
            )
            result = outcome.result
            if result.commit != revision:
                raise ValueError("document auditor revision does not match current HEAD")
            if result.status != "completed" or result.verdict not in {
                "pass",
                "blocked",
            }:
                raise ValueError("document auditor returned a non-terminal verdict")
            if result.artifact_paths != (report_path,):
                raise ValueError("document auditor returned unexpected artifacts")
            data = self.store.read_artifact(report_path)
            self.store.append_event(
                "audit.reported",
                {
                    "audit_id": (
                        f"audit-{document.document_id}-{revision[:12]}"
                    ),
                    "status": result.status,
                    "commit": revision,
                    "verdict": result.verdict,
                    "report_sha256": _sha256(data),
                    "artifact_paths": [report_path],
                },
            )
            audits[document.document_id] = self._validate_audit_event(
                self.store.validate_event_chain()[-1],
                document=document,
                revision=revision,
            )
        return audits

    def _whole_diff_path(self, revision: str) -> str:
        path = f"{self._final_root(revision)}/whole.patch"
        self.store.put_artifact(
            path,
            self.worktree.diff(self.worktree.base_commit, revision).encode("utf-8"),
        )
        return path

    def _open_authority_ids(self) -> tuple[str, ...]:
        state = self.store.replay()
        authorities = state.get("authorities")
        if not isinstance(authorities, Mapping):
            raise ValueError("replayed authority state is invalid")
        return tuple(
            sorted(
                str(authority_id)
                for authority_id, authority in authorities.items()
                if isinstance(authority, Mapping)
                and authority.get("status") == "waiting_authority"
            )
        )

    def _authority_state_path(self, revision: str) -> str:
        path = f"{self._final_root(revision)}/authority-open.json"
        self.store.put_artifact(
            path,
            canonical_json(
                {
                    "schema_version": 1,
                    "revision": revision,
                    "authority_open": list(self._open_authority_ids()),
                }
            ),
        )
        return path

    def _integration_launch_record(
        self,
        *,
        revision: str,
        audit_paths: Sequence[str],
        verification_commands: Sequence[str],
        whole_diff_path: str,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "revision": revision,
            "audit_sha256s": {
                audit_path: _sha256(self.store.read_artifact(audit_path))
                for audit_path in audit_paths
            },
            "verification_commands": list(verification_commands),
            "whole_diff_path": whole_diff_path,
            "whole_diff_sha256": _sha256(
                self.store.read_artifact(whole_diff_path)
            ),
            "terminal_path": self._terminal_path(revision),
        }

    def _prepare_integration_launch(
        self,
        *,
        revision: str,
        audit_paths: Sequence[str],
        verification_commands: Sequence[str],
        whole_diff_path: str,
    ) -> str:
        path = self._integration_launch_path(revision)
        data = canonical_json(
            self._integration_launch_record(
                revision=revision,
                audit_paths=audit_paths,
                verification_commands=verification_commands,
                whole_diff_path=whole_diff_path,
            )
        )
        self.store.put_artifact(path, data)
        if self.store.read_artifact(path) != data:
            raise ValueError("final integration launch commitment changed")
        return path

    def _validate_integration_launch(
        self,
        *,
        revision: str,
        audit_paths: Sequence[str],
        verification_commands: Sequence[str],
        whole_diff_path: str,
    ) -> str:
        path = self._integration_launch_path(revision)
        expected = canonical_json(
            self._integration_launch_record(
                revision=revision,
                audit_paths=audit_paths,
                verification_commands=verification_commands,
                whole_diff_path=whole_diff_path,
            )
        )
        if self.store.read_artifact(path) != expected:
            raise ValueError("final integration launch commitment is stale")
        return path

    def _integration_result_record(
        self,
        *,
        revision: str,
        status: str,
        verdict: str,
        artifact_paths: Sequence[str],
    ) -> dict[str, object]:
        paths = [normalize_relative_path(path) for path in artifact_paths]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("final integration result artifacts are invalid")
        terminal_path = self._terminal_path(revision)
        if terminal_path not in paths or "result.json" in paths:
            raise ValueError("final integration result uses a reserved artifact path")
        artifact_sha256s = {
            path: _sha256(self.store.read_artifact(path)) for path in paths
        }
        return {
            "schema_version": 1,
            "revision": revision,
            "status": status,
            "verdict": verdict,
            "report_sha256": artifact_sha256s[terminal_path],
            "artifact_paths": paths,
            "artifact_sha256s": artifact_sha256s,
        }

    def _read_integration_handoff(self, revision: str) -> dict[str, object]:
        handoff_path = self._integration_handoff_path(revision)
        data = self.store.read_artifact(handoff_path)
        payload = _load_json(data, "final integration child handoff")
        if set(payload) != {
            "schema_version",
            "producer",
            "child_result",
            "report_path",
            "report_sha256",
            "artifact_sha256s",
        } or payload.get("schema_version") != 1 or payload.get(
            "producer"
        ) != "cpe_launcher":
            raise ValueError("final integration child handoff fields are invalid")
        child = payload.get("child_result")
        child_fields = {
            "role",
            "status",
            "item_id",
            "commit",
            "verdict",
            "failure_code",
            "authority_id",
            "strategy_key",
            "affected_document_ids",
            "artifact_paths",
            "summary",
        }
        if not isinstance(child, Mapping) or set(child) != child_fields:
            raise ValueError("final integration child result fields are invalid")
        if (
            child.get("role") != "program_final_integrator"
            or child.get("item_id") != "program-final"
            or child.get("commit") != revision
            or (child.get("status"), child.get("verdict"))
            not in {
                ("completed", "pass"),
                ("changes_requested", "changes_requested"),
            }
            or child.get("failure_code") is not None
            or child.get("authority_id") is not None
            or child.get("affected_document_ids") != []
            or (
                child.get("strategy_key") is not None
                and (
                    not isinstance(child.get("strategy_key"), str)
                    or not child["strategy_key"]
                )
            )
            or not isinstance(child.get("summary"), str)
            or not child["summary"]
        ):
            raise ValueError("final integration child result binding is invalid")
        paths = child.get("artifact_paths")
        if (
            not isinstance(paths, list)
            or not all(isinstance(path, str) for path in paths)
            or len(paths) != len(set(paths))
            or not paths
            or paths[0] != handoff_path
            or self._terminal_path(revision) not in paths
            or "result.json" in paths
        ):
            raise ValueError("final integration child artifact list is invalid")
        normalized_paths = [normalize_relative_path(path) for path in paths]
        digests = payload.get("artifact_sha256s")
        if not isinstance(digests, Mapping) or set(digests) != set(
            normalized_paths[1:]
        ):
            raise ValueError("final integration child artifact hashes are invalid")
        for path in normalized_paths[1:]:
            digest = digests[path]
            if not isinstance(digest, str) or digest != _sha256(
                self.store.read_artifact(path)
            ):
                raise ValueError("final integration child artifact hash is stale")
        terminal_path = self._terminal_path(revision)
        if (
            payload.get("report_path") != terminal_path
            or payload.get("report_sha256") != digests[terminal_path]
        ):
            raise ValueError("final integration child report binding is invalid")
        return payload

    def _read_integration_result(
        self, revision: str
    ) -> dict[str, object]:
        path = self._integration_result_path(revision)
        data = self.store.read_artifact(path)
        payload = _load_json(data, "final integration result record")
        expected_fields = {
            "schema_version",
            "revision",
            "status",
            "verdict",
            "report_sha256",
            "artifact_paths",
            "artifact_sha256s",
        }
        if set(payload) != expected_fields or payload.get("schema_version") != 1:
            raise ValueError("final integration result record fields are invalid")
        status = payload.get("status")
        verdict = payload.get("verdict")
        if payload.get("revision") != revision or (status, verdict) not in {
            ("completed", "pass"),
            ("changes_requested", "changes_requested"),
        }:
            raise ValueError("final integration result record binding is invalid")
        paths = payload.get("artifact_paths")
        digests = payload.get("artifact_sha256s")
        if (
            not isinstance(paths, list)
            or not all(isinstance(path, str) for path in paths)
            or not isinstance(digests, Mapping)
            or set(digests) != set(paths)
        ):
            raise ValueError("final integration result artifact binding is invalid")
        expected = self._integration_result_record(
            revision=revision,
            status=str(status),
            verdict=str(verdict),
            artifact_paths=tuple(paths),
        )
        if payload != expected or canonical_json(expected) != data:
            raise ValueError("final integration result record is stale")
        return expected

    def _integration_event_payload(
        self, revision: str, result_record: Mapping[str, object]
    ) -> dict[str, object]:
        lifecycle_paths = [
            self._integration_launch_path(revision),
            *self._validated_integration_retry_paths(revision),
        ]
        lifecycle_paths.append(self._integration_result_path(revision))
        return {
            "integration_id": f"program-final-{revision[:12]}",
            "status": result_record["status"],
            "commit": revision,
            "verdict": result_record["verdict"],
            "report_sha256": result_record["report_sha256"],
            "artifact_paths": [
                *lifecycle_paths,
                *result_record["artifact_paths"],
            ],
        }

    def _validated_integration_retry_paths(self, revision: str) -> tuple[str, ...]:
        launch_path = self._integration_launch_path(revision)
        failure_path = self._integration_failure_path(revision)
        retry_path = self._integration_retry_path(revision)
        failure_target = self.store.paths.root / failure_path
        retry_target = self.store.paths.root / retry_path
        failure_exists = failure_target.exists() or failure_target.is_symlink()
        retry_exists = retry_target.exists() or retry_target.is_symlink()
        if retry_exists and not failure_exists:
            raise ValueError("final integration retry has no child failure record")
        result: list[str] = []
        if failure_exists:
            expected_failure = {
                "schema_version": 1,
                "revision": revision,
                "status": "pre_artifact_failure",
                "launch_sha256": _sha256(self.store.read_artifact(launch_path)),
            }
            failure = _load_json(
                self.store.read_artifact(failure_path),
                "final integrator child failure",
            )
            if failure != expected_failure:
                raise ValueError("final integrator child failure record is stale")
            result.append(failure_path)
        if retry_exists:
            expected_retry = {
                "schema_version": 1,
                "revision": revision,
                "failure_sha256": _sha256(self.store.read_artifact(failure_path)),
            }
            retry = _load_json(
                self.store.read_artifact(retry_path),
                "final integrator retry launch",
            )
            if retry != expected_retry:
                raise ValueError("final integrator retry launch record is stale")
            result.append(retry_path)
        return tuple(result)

    def _validate_integration_event(
        self,
        event: Mapping[str, object],
        *,
        revision: str,
        audit_paths: Sequence[str],
        program: Mapping[str, object],
        whole_diff_path: str,
    ) -> Mapping[str, object]:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("final integration event payload is invalid")
        if payload.get("commit") != revision:
            raise ValueError("final integration event revision does not match")
        self._validate_integration_launch(
            revision=revision,
            audit_paths=audit_paths,
            verification_commands=tuple(program["final_verification_commands"]),
            whole_diff_path=whole_diff_path,
        )
        result_record = self._read_integration_result(revision)
        paths = payload.get("artifact_paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ValueError("final integration artifact paths are invalid")
        expected_paths = self._integration_event_payload(
            revision, result_record
        )["artifact_paths"]
        if paths != expected_paths:
            raise ValueError("final integration event differs from its result record")
        terminal_path = self._terminal_path(revision)
        if terminal_path not in paths:
            raise ValueError("final integration report is unavailable")
        report = self.store.read_artifact(terminal_path)
        if (
            payload.get("status") != result_record["status"]
            or payload.get("verdict") != result_record["verdict"]
            or payload.get("report_sha256") != result_record["report_sha256"]
            or payload.get("report_sha256") != _sha256(report)
        ):
            raise ValueError("final integration report digest does not match")
        if payload.get("status") == "changes_requested":
            if payload.get("verdict") != "changes_requested":
                raise ValueError("final integration change request is invalid")
            return payload
        if payload.get("status") != "completed" or payload.get("verdict") != "pass":
            raise ValueError("final integration did not pass")
        validated = validate_terminal_artifact(
            _load_json(report, "terminal artifact"),
            revision=revision,
            auditor_document_ids=tuple(
                document.document_id for document in self.store.document_set()
            ),
            verification_commands=tuple(program["final_verification_commands"]),
        )
        if canonical_json(validated) != report:
            raise ValueError("terminal artifact is not in its canonical validated shape")
        if validated["quality_verdict"] != "pass":
            raise ValueError("completed final integration quality verdict is not pass")
        if validated["authority_open"] != list(self._open_authority_ids()):
            raise ValueError("terminal artifact authority state is stale")
        whole_diff = self.store.read_artifact(whole_diff_path)
        if validated["whole_diff_sha256"] != _sha256(whole_diff):
            raise ValueError("terminal artifact whole diff digest does not match")
        auditor_verdicts = validated["auditor_verdicts"]
        if any(
            auditor_verdicts[document.document_id] != "pass"
            for document in self.store.document_set()
        ):
            raise ValueError("terminal artifact contains a non-passing auditor verdict")
        for record in validated["verification"]:
            output_path = str(record["output_path"])
            if output_path not in paths:
                raise ValueError("terminal verification output was not reported")
            self.store.read_artifact(output_path)
        expected_child_paths = [
            self._integration_handoff_path(revision),
            terminal_path,
            *(str(record["output_path"]) for record in validated["verification"]),
        ]
        if result_record["artifact_paths"] != expected_child_paths:
            raise ValueError("passing final integration reported extra artifacts")
        if set(audit_paths) != {
            self._audit_path(revision, document.document_id)
            for document in self.store.document_set()
        }:
            raise ValueError("terminal integration audit evidence is incomplete")
        return payload

    def _current_integration(
        self,
        *,
        revision: str,
        audit_paths: Sequence[str],
        program: Mapping[str, object],
        whole_diff_path: str,
    ) -> Mapping[str, object] | None:
        matches = [
            event
            for event in self.store.validate_event_chain()
            if event["event_type"] == "integration.reported"
            and event["payload"].get("commit") == revision
        ]
        if len(matches) > 1:
            raise ValueError("final integration events are ambiguous")
        if matches:
            return self._validate_integration_event(
                matches[0],
                revision=revision,
                audit_paths=audit_paths,
                program=program,
                whole_diff_path=whole_diff_path,
            )

        launch_path = self._integration_launch_path(revision)
        result_path = self._integration_result_path(revision)
        handoff_path = self._integration_handoff_path(revision)
        terminal_path = self._terminal_path(revision)
        launch_target = self.store.paths.root / launch_path
        result_target = self.store.paths.root / result_path
        handoff_target = self.store.paths.root / handoff_path
        terminal_target = self.store.paths.root / terminal_path
        failure_path = self._integration_failure_path(revision)
        if result_target.exists() or result_target.is_symlink():
            self._validate_integration_launch(
                revision=revision,
                audit_paths=audit_paths,
                verification_commands=tuple(program["final_verification_commands"]),
                whole_diff_path=whole_diff_path,
            )
            result_record = self._read_integration_result(revision)
            candidate = self._integration_event_payload(revision, result_record)
            self._validate_integration_event(
                {"payload": candidate},
                revision=revision,
                audit_paths=audit_paths,
                program=program,
                whole_diff_path=whole_diff_path,
            )
            self.store.append_event("integration.reported", candidate)
            return candidate
        if handoff_target.exists() or handoff_target.is_symlink():
            self._validate_integration_launch(
                revision=revision,
                audit_paths=audit_paths,
                verification_commands=tuple(program["final_verification_commands"]),
                whole_diff_path=whole_diff_path,
            )
            handoff = self._read_integration_handoff(revision)
            child = handoff["child_result"]
            assert isinstance(child, Mapping)
            result_record = self._integration_result_record(
                revision=revision,
                status=str(child["status"]),
                verdict=str(child["verdict"]),
                artifact_paths=tuple(child["artifact_paths"]),
            )
            self.store.put_artifact(result_path, canonical_json(result_record))
            candidate = self._integration_event_payload(revision, result_record)
            self._validate_integration_event(
                {"payload": candidate},
                revision=revision,
                audit_paths=audit_paths,
                program=program,
                whole_diff_path=whole_diff_path,
            )
            self.store.append_event("integration.reported", candidate)
            return candidate
        if terminal_target.exists() or terminal_target.is_symlink():
            self._record_interrupted("final_integrator_handoff_unavailable")
            raise ValueError(
                "orphaned final integrator artifacts have no durable child handoff"
            )
        if launch_target.exists() or launch_target.is_symlink():
            self._validate_integration_launch(
                revision=revision,
                audit_paths=audit_paths,
                verification_commands=tuple(program["final_verification_commands"]),
                whole_diff_path=whole_diff_path,
            )
            retry_paths = self._validated_integration_retry_paths(revision)
            if retry_paths == (failure_path,):
                return None
            self._record_interrupted("final_integrator_result_unavailable")
            raise ValueError(
                "final integrator launch has no durable result; refusing duplicate verification"
            )
        return None

    def _run_program_final_integrator(
        self,
        *,
        revision: str,
        audits: Mapping[str, tuple[str, str]],
        program: Mapping[str, object],
        selected: Mapping[str, Path],
        whole_diff_path: str,
    ) -> Mapping[str, object]:
        audit_paths = tuple(
            audits[document.document_id][0] for document in self.store.document_set()
        )
        existing = self._current_integration(
            revision=revision,
            audit_paths=audit_paths,
            program=program,
            whole_diff_path=whole_diff_path,
        )
        if existing is not None:
            return existing
        terminal_path = self._terminal_path(revision)
        authority_state_path = self._authority_state_path(revision)
        launch_path = self._prepare_integration_launch(
            revision=revision,
            audit_paths=audit_paths,
            verification_commands=tuple(program["final_verification_commands"]),
            whole_diff_path=whole_diff_path,
        )
        failure_path = self._integration_failure_path(revision)
        retry_path = self._integration_retry_path(revision)
        failure_target = self.store.paths.root / failure_path
        retry_target = self.store.paths.root / retry_path
        if failure_target.exists() or failure_target.is_symlink():
            retry_record = {
                "schema_version": 1,
                "revision": revision,
                "failure_sha256": _sha256(self.store.read_artifact(failure_path)),
            }
            self.store.put_artifact(retry_path, canonical_json(retry_record))
        inputs = [
            selected[f"{_GENERATION_ROOT}/program-map.json"],
            selected[f"{_GENERATION_ROOT}/coverage.json"],
            *(self._artifact_input(path, selected) for path in audit_paths),
            self.store.paths.autonomy_decisions.resolve(strict=True),
            selected[f"{_GENERATION_ROOT}/authority-queue.json"],
            self._artifact_input(authority_state_path, selected),
            self._artifact_input(whole_diff_path, selected),
            self._artifact_input(launch_path, selected),
        ]
        try:
            outcome = self._launch_role(
                role="program_final_integrator",
                item_id="program-final",
                goal=(
                    "Integrate all document audits and run each final verification command "
                    f"exactly once at revision {revision}."
                ),
                input_paths=inputs,
                report_path=terminal_path,
                skills=("using-superpowers", "verification-before-completion"),
                done_when=(
                    "the terminal artifact binds every audit and verification output",
                    "a pass is emitted only for the exact clean final revision",
                ),
                attempt_id=f"final-integrator-{revision[:12]}",
            )
        except (ValueError, TimeoutError):
            terminal_target = self.store.paths.root / terminal_path
            if not (
                terminal_target.exists()
                or terminal_target.is_symlink()
                or failure_target.exists()
                or failure_target.is_symlink()
                or retry_target.exists()
                or retry_target.is_symlink()
            ):
                self.store.put_artifact(
                    failure_path,
                    canonical_json(
                        {
                            "schema_version": 1,
                            "revision": revision,
                            "status": "pre_artifact_failure",
                            "launch_sha256": _sha256(
                                self.store.read_artifact(launch_path)
                            ),
                        }
                    ),
                )
            raise
        result = outcome.result
        if result.commit != revision or self.worktree.head() != revision:
            raise ValueError("final integrator revision does not match current HEAD")
        if self.worktree.status():
            raise ValueError("final integrator left a dirty worktree")
        if (result.status, result.verdict) not in {
            ("completed", "pass"),
            ("changes_requested", "changes_requested"),
        }:
            raise ValueError("final integrator returned an invalid result")
        if terminal_path not in result.artifact_paths:
            raise ValueError("final integrator omitted its terminal report")
        handoff = self._read_integration_handoff(revision)
        if handoff["child_result"] != {
            "role": result.role,
            "status": result.status,
            "item_id": result.item_id,
            "commit": result.commit,
            "verdict": result.verdict,
            "failure_code": result.failure_code,
            "authority_id": result.authority_id,
            "strategy_key": result.strategy_key,
            "affected_document_ids": list(result.affected_document_ids),
            "artifact_paths": list(result.artifact_paths),
            "summary": result.summary,
        }:
            raise ValueError(
                "final integrator normalized result differs from durable handoff"
            )
        result_record = self._integration_result_record(
            revision=revision,
            status=result.status,
            verdict=str(result.verdict),
            artifact_paths=result.artifact_paths,
        )
        result_path = self._integration_result_path(revision)
        self.store.put_artifact(result_path, canonical_json(result_record))
        payload = self._integration_event_payload(revision, result_record)
        validated = self._validate_integration_event(
            {"payload": payload},
            revision=revision,
            audit_paths=audit_paths,
            program=program,
            whole_diff_path=whole_diff_path,
        )
        self.store.append_event("integration.reported", payload)
        return validated

    def _run_integration_fix(
        self,
        *,
        revision: str,
        finding_paths: Sequence[str],
        selected: Mapping[str, Path],
    ) -> str:
        task_id = "program:integration"
        attempt_number = self._attempt_number(task_id)
        attempt_id = f"program-integration-attempt-{attempt_number:04d}"
        report_path = f"reports/program-integration/attempt-{attempt_number}.md"
        inputs = [
            selected[f"{_GENERATION_ROOT}/program-map.json"],
            *(self._artifact_input(path, selected) for path in finding_paths),
        ]
        evidence_sha256 = self._artifact_evidence_digest(finding_paths)
        self._append_task_started(
            task_id=task_id,
            attempt_id=attempt_id,
            role="integration_fix_agent",
            strategy_key="integration-consolidated",
            baseline_commit=revision,
            evidence_sha256=evidence_sha256,
        )
        outcome = self._launch_role(
            role="integration_fix_agent",
            item_id=task_id,
            goal=(
                "Strategy key: integration-consolidated\n"
                "Resolve all supplied final integration findings in one commit."
            ),
            input_paths=inputs,
            report_path=report_path,
            skills=(
                "using-superpowers",
                "systematic-debugging",
                "test-driven-development",
            ),
            done_when=("all final integration findings are resolved together",),
            attempt_id=attempt_id,
        )
        result = outcome.result
        self._append_task_result(
            result,
            task_id=task_id,
            attempt_id=attempt_id,
            strategy_key="integration-consolidated",
        )
        if result.status != "completed" or result.commit is None:
            raise ValueError("integration fix agent did not complete")
        if result.commit == revision:
            raise ValueError("integration fix did not create a new revision")
        return result.commit

    def _reconcile_active_integration_fix(self) -> None:
        state = self.store.replay()
        tasks = state.get("tasks")
        if not isinstance(tasks, Mapping):
            raise ValueError("replayed task state is invalid")
        integration_state = tasks.get("program:integration")
        if not isinstance(integration_state, Mapping):
            return
        active = integration_state.get("active_attempt")
        if not isinstance(active, Mapping):
            return
        attempt_id = active.get("attempt_id")
        strategy_key = active.get("strategy_key")
        baseline = active.get("baseline_commit")
        if (
            active.get("role") != "integration_fix_agent"
            or not all(
                isinstance(value, str) and value
                for value in (attempt_id, strategy_key, baseline)
            )
        ):
            self._record_interrupted("integration_fix_replay_ambiguous")
            raise ValueError("active integration fix binding is invalid")
        if self.worktree.status():
            self._record_interrupted("active_integration_fix_left_dirty_worktree")
            raise ValueError("active integration fix left a dirty worktree")
        commit = self.worktree.head()
        if commit == baseline:
            self._record_interrupted("active_integration_fix_has_no_bound_result")
            raise ValueError("active integration fix has no bound result")
        report_number = str(attempt_id).rsplit("-", 1)[-1].lstrip("0") or "0"
        report_path = f"reports/program-integration/attempt-{report_number}.md"
        try:
            self.store.read_artifact(report_path)
        except ValueError as exc:
            self._record_interrupted("active_integration_fix_report_unavailable")
            raise ValueError("active integration fix report is unavailable") from exc
        self.store.append_event(
            "task.reported",
            {
                "task_id": "program:integration",
                "attempt_id": str(attempt_id),
                "status": "completed",
                "commit": commit,
                "strategy_key": str(strategy_key),
                "artifact_paths": [report_path],
            },
        )

    def _complete_run(
        self,
        *,
        revision: str,
        integration: Mapping[str, object],
    ) -> None:
        terminal_path = self._terminal_path(revision)
        terminal = self.store.read_artifact(terminal_path)
        completed = [
            event
            for event in self.store.validate_event_chain()
            if event["event_type"] == "run.completed"
        ]
        expected_paths = ["result.json", *integration["artifact_paths"]]
        if completed:
            if len(completed) != 1 or completed[0]["payload"] != {
                "status": "completed",
                "commit": revision,
                "result_sha256": _sha256(terminal),
                "artifact_paths": expected_paths,
            }:
                raise ValueError("run completion event differs from terminal evidence")
            if self.store.read_artifact("result.json") != terminal:
                raise ValueError("terminal result artifact differs from completion event")
            return
        if self.worktree.head() != revision or self.worktree.status():
            raise ValueError("run completion revision is not the clean worktree HEAD")
        self.store.put_artifact("result.json", terminal)
        self.store.append_event(
            "run.completed",
            {
                "status": "completed",
                "commit": revision,
                "result_sha256": _sha256(terminal),
                "artifact_paths": expected_paths,
            },
        )

    def _run_final_closure(self) -> dict[str, object]:
        while True:
            self._reconcile_active_integration_fix()
            revision = self.worktree.head()
            if self.worktree.status():
                raise ValueError("final audit requires a clean worktree")
            program, selected = self._program_context()
            audits = self._run_document_audits(revision)
            if set(audits) != {
                document.document_id for document in self.store.document_set()
            }:
                raise ValueError("final document audit set is incomplete")
            if any(verdict != "pass" for _, verdict in audits.values()):
                return self.store.replay()
            whole_diff_path = self._whole_diff_path(revision)
            integration = self._run_program_final_integrator(
                revision=revision,
                audits=audits,
                program=program,
                selected=selected,
                whole_diff_path=whole_diff_path,
            )
            if integration["status"] == "changes_requested":
                new_revision = self._run_integration_fix(
                    revision=revision,
                    finding_paths=tuple(integration["artifact_paths"]),
                    selected=selected,
                )
                if self.worktree.head() != new_revision or self.worktree.status():
                    raise ValueError("integration fix handoff is not a clean new revision")
                continue
            self._complete_run(revision=revision, integration=integration)
            return self.store.replay()

    def tick(self) -> str | None:
        """Advance exactly one ready task through a fresh review or durable wait."""

        self.worktree.verify_identity()
        self.map_program()
        with self.launcher.writer_lifecycle(self.store):
            self.store.reconcile_autonomy_events()
            state = self.store.replay()
            task = self._next_ready_task(state)
            if task is None:
                return None
            task_id = str(task["task_id"])
            task_state = state["tasks"].get(task_id)
            if isinstance(task_state, Mapping) and (
                task_state.get("attempts") or task_state.get("active_attempt")
            ):
                self._resume_task(task, task_state)
            else:
                self._run_task(task)
            return task_id

    def run_until_terminal(self) -> dict[str, object]:
        """Run ready tasks, revision-bound audits, and one terminal integrator."""

        self.map_documents()
        self.map_program()
        while self.tick() is not None:
            pass
        state = self.store.replay()
        if state["status"] == "completed":
            return state
        program, _ = self._program_context()
        if not self._tasks_are_final_ready(state, program):
            return state
        with self.launcher.writer_lifecycle(self.store):
            return self._run_final_closure()
