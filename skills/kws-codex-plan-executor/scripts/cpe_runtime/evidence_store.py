"""Sole content-addressed evidence writer for the vNext runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Callable

from .evidence import EvidenceError, EvidenceRef


_KIND = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class EvidenceStore:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(os.path.abspath(os.fspath(run_dir.expanduser())))

    def _resolved_root(self) -> Path:
        try:
            metadata = self.run_dir.lstat()
        except FileNotFoundError:
            self.run_dir.mkdir(parents=True, mode=0o700)
            metadata = self.run_dir.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise EvidenceError("evidence path escapes run root")
        return self.run_dir.resolve()

    def _checked_dir(self, path: Path, parent: Path) -> Path:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or path.resolve().parent != parent.resolve()
        ):
            raise EvidenceError("evidence path escapes run root")
        return path

    def _assert_lexical_components(self, target: Path) -> None:
        try:
            relative = target.relative_to(self.run_dir)
        except ValueError as exc:
            raise EvidenceError("evidence path escapes run root") from exc
        current = self.run_dir
        self._resolved_root()
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise EvidenceError("evidence path escapes run root")
        try:
            target.resolve(strict=False).relative_to(self._resolved_root())
        except ValueError as exc:
            raise EvidenceError("evidence path escapes run root") from exc

    def _root(self, kind: str) -> Path:
        if not isinstance(kind, str) or _KIND.fullmatch(kind) is None:
            raise EvidenceError("invalid evidence kind")
        self._resolved_root()
        artifacts = self._checked_dir(self.run_dir / "artifacts", self.run_dir)
        root = self._checked_dir(artifacts / "evidence", artifacts)
        return self._checked_dir(root / kind, root)

    def put_bytes(
        self,
        kind: str,
        content: bytes,
        *,
        media_type: str = "application/octet-stream",
        suffix: str = ".bin",
        crash_hook: Callable[[str], None] | None = None,
    ) -> EvidenceRef:
        if not isinstance(content, bytes) or not content:
            raise EvidenceError("evidence bytes must be non-empty")
        if not suffix.startswith(".") or "/" in suffix or "\\" in suffix:
            raise EvidenceError("invalid evidence suffix")
        hook = crash_hook or (lambda _point: None)
        digest = hashlib.sha256(content).hexdigest()
        root = self._root(kind)
        target = root / f"{digest}{suffix}"
        self._assert_lexical_components(target)
        hook("before_evidence_persistence")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != content:
                raise EvidenceError("existing evidence path has different content")
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_dir(root)
        hook("after_evidence_persistence")
        return EvidenceRef(
            kind=kind,
            path=target.relative_to(self.run_dir).as_posix(),
            sha256=digest,
            media_type=media_type,
        )

    def put_json(self, kind: str, payload: object) -> EvidenceRef:
        raw = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode()
        return self.put_bytes(
            kind,
            raw,
            media_type="application/json",
            suffix=".json",
        )

    def read_verified(self, ref: EvidenceRef | dict[str, str]) -> bytes:
        if isinstance(ref, dict):
            try:
                ref = EvidenceRef(**ref)
            except (TypeError, KeyError) as exc:
                raise EvidenceError("evidence_reference_invalid") from exc
        path = Path(ref.path)
        if path.is_absolute() or ".." in path.parts:
            raise EvidenceError("evidence_path_invalid")
        target = self.run_dir / path
        try:
            self._assert_lexical_components(target)
        except EvidenceError as exc:
            raise EvidenceError("evidence_path_invalid") from exc
        try:
            metadata = target.lstat()
        except FileNotFoundError as exc:
            raise EvidenceError("evidence_missing") from exc
        expected_parent = (
            self.run_dir / "artifacts" / "patches"
            if ref.kind == "patch"
            else self.run_dir / "artifacts" / "evidence" / ref.kind
        )
        expected_suffix = ".patch" if ref.kind == "patch" else (
            ".json" if ref.media_type == "application/json" else ".bin"
        )
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not target.is_file()
            or target.resolve().parent != expected_parent.resolve()
            or target.name != f"{ref.sha256}{expected_suffix}"
        ):
            raise EvidenceError("evidence_path_invalid")
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != ref.sha256:
            raise EvidenceError("evidence_digest_mismatch")
        return content

    def put_patch(self, content: bytes) -> EvidenceRef:
        """Store patch evidence through the canonical writer at its stable wire path."""

        if not isinstance(content, bytes) or not content:
            raise EvidenceError("evidence bytes must be non-empty")
        digest = hashlib.sha256(content).hexdigest()
        self._resolved_root()
        artifacts = self._checked_dir(self.run_dir / "artifacts", self.run_dir)
        root = self._checked_dir(artifacts / "patches", artifacts)
        target = root / f"{digest}.patch"
        self._assert_lexical_components(target)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != content:
                raise EvidenceError("existing evidence path has different content")
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_dir(root)
        return EvidenceRef(
            kind="patch",
            path=target.relative_to(self.run_dir).as_posix(),
            sha256=digest,
            media_type="application/octet-stream",
        )
