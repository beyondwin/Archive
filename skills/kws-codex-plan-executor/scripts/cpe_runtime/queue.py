"""Deterministic multi-document mapping queue for lean schema-4 CPE."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
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

    def run_until_terminal(self) -> dict[str, object]:
        """Advance through the mapping boundary; later tasks own task dispatch."""

        self.map_documents()
        self.map_program()
        return self.store.replay()
