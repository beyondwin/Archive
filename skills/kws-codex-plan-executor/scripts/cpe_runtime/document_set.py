"""Immutable, content-addressed inputs for the CPE vNext runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


DocumentKind = Literal["spec", "program", "plan", "doc"]
TITLE_RE = re.compile(rb"(?m)^#[ \t]+([^\r\n]+?)[ \t]*$")


@dataclass(frozen=True)
class InputDocument:
    document_id: str
    kind: DocumentKind
    path: Path
    sha256: str
    content: bytes


@dataclass(frozen=True)
class DocumentSet:
    documents: tuple[InputDocument, ...]
    sha256: str


class DocumentSetBlocked(ValueError):
    """An ambiguous or unsafe source prevented document-set compilation."""

    def __init__(self, category: str, summary: str, evidence: dict[str, object]):
        super().__init__(summary)
        self.category = category
        self.summary = summary
        self.evidence = evidence


def _normalized_path(source: Path, kind: DocumentKind) -> Path:
    expanded = source.expanduser()
    normalized = Path(os.path.abspath(os.path.normpath(os.fspath(expanded))))
    try:
        metadata = normalized.lstat()
    except OSError as exc:
        raise DocumentSetBlocked(
            "source_unreadable",
            f"{kind} source is unreadable",
            {"kind": kind, "source_path": str(normalized), "error": str(exc)},
        ) from None
    if stat.S_ISLNK(metadata.st_mode):
        raise DocumentSetBlocked(
            "source_symlink",
            f"{kind} source must not be a symbolic link",
            {"kind": kind, "source_path": str(normalized)},
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise DocumentSetBlocked(
            "source_not_file",
            f"{kind} source must be a regular file",
            {"kind": kind, "source_path": str(normalized)},
        )
    if metadata.st_mode & 0o444 == 0:
        raise DocumentSetBlocked(
            "source_unreadable",
            f"{kind} source is unreadable",
            {"kind": kind, "source_path": str(normalized), "error": "no read permission bits"},
        )
    try:
        return normalized.resolve(strict=True)
    except OSError as exc:
        raise DocumentSetBlocked(
            "source_unreadable",
            f"{kind} source path cannot be canonicalized",
            {"kind": kind, "source_path": str(normalized), "error": str(exc)},
        ) from None


def _declared_title(content: bytes, kind: DocumentKind, path: Path) -> str:
    match = TITLE_RE.search(content)
    if match is None:
        raise DocumentSetBlocked(
            "declared_title_missing",
            f"{kind} source has no declared level-one title",
            {"kind": kind, "source_path": str(path)},
        )
    try:
        title = match.group(1).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise DocumentSetBlocked(
            "declared_title_invalid",
            f"{kind} source title is not UTF-8",
            {"kind": kind, "source_path": str(path), "error": str(exc)},
        ) from None
    if not title:
        raise DocumentSetBlocked(
            "declared_title_missing",
            f"{kind} source has an empty declared title",
            {"kind": kind, "source_path": str(path)},
        )
    return title


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or "document"


def _compile_document(kind: DocumentKind, source: Path) -> tuple[InputDocument, str]:
    path = _normalized_path(source, kind)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise DocumentSetBlocked(
            "source_unreadable",
            f"{kind} source is unreadable",
            {"kind": kind, "source_path": str(path), "error": str(exc)},
        ) from None
    title = _declared_title(content, kind, path)
    source_hash = hashlib.sha256(content).hexdigest()
    identity_hash = hashlib.sha256(
        b"cpe.document.vnext\0"
        + kind.encode("ascii")
        + b"\0"
        + title.encode("utf-8")
        + b"\0"
        + path.as_posix().encode("utf-8")
    ).hexdigest()
    document_id = f"{kind}:{_slug(title)}:{identity_hash[:16]}"
    return InputDocument(document_id, kind, path, source_hash, content), title.casefold()


def compile_document_set(
    spec: Path | None,
    plans: tuple[Path, ...],
    program_plan: Path | None,
    docs: tuple[Path, ...],
) -> DocumentSet:
    """Snapshot one native vNext input set without allocating run state."""

    if not plans:
        raise DocumentSetBlocked(
            "plans_missing",
            "at least one implementation plan is required",
            {"plan_count": 0},
        )
    declared: list[tuple[DocumentKind, Path]] = []
    if spec is not None:
        declared.append(("spec", spec))
    if program_plan is not None:
        declared.append(("program", program_plan))
    declared.extend(("plan", path) for path in plans)
    declared.extend(("doc", path) for path in docs)

    documents: list[InputDocument] = []
    paths: dict[Path, str] = {}
    identities: dict[tuple[DocumentKind, str], str] = {}
    hashes: dict[str, str] = {}
    for kind, source in declared:
        document, normalized_title = _compile_document(kind, source)
        if document.path in paths:
            raise DocumentSetBlocked(
                "duplicate_path",
                "input documents resolve to the same canonical path",
                {
                    "source_path": str(document.path),
                    "first_document_id": paths[document.path],
                    "duplicate_document_id": document.document_id,
                },
            )
        if document.sha256 in hashes:
            raise DocumentSetBlocked(
                "duplicate_content",
                "input documents have identical source bytes",
                {
                    "sha256": document.sha256,
                    "first_document_id": hashes[document.sha256],
                    "duplicate_document_id": document.document_id,
                },
            )
        identity = (kind, normalized_title)
        if identity in identities:
            raise DocumentSetBlocked(
                "duplicate_identity",
                "input documents have an ambiguous declared identity",
                {
                    "kind": kind,
                    "title": normalized_title,
                    "first_document_id": identities[identity],
                    "duplicate_document_id": document.document_id,
                },
            )
        paths[document.path] = document.document_id
        identities[identity] = document.document_id
        hashes[document.sha256] = document.document_id
        documents.append(document)

    payload = [
        {
            "document_id": item.document_id,
            "kind": item.kind,
            "path": item.path.as_posix(),
            "sha256": item.sha256,
        }
        for item in documents
    ]
    set_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DocumentSet(tuple(documents), set_hash)
