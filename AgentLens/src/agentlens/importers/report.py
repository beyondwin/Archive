"""Import-report dataclass and helpers (spec §4.1).

`ImportReport` is the per-import accounting object written to
``import_report.json`` alongside an imported run. It tracks counters
(parsed/skipped lines), first-error provenance, byte-cap status, derived
display title, and a *redacted* label for the source path plus a sha256 hash
of the raw absolute path so a reader can correlate two reports from the same
source without learning where the file lived on disk.

The dataclass is mutable (counters mutate over the course of an import) but
its public API is intentionally small — call `record_parsed`/`record_skip`/
etc. rather than mutating fields directly. `to_dict()` produces the exact
spec §4.1 JSON shape (nested ``lines.*``/``derived.*``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

__all__ = [
    "FirstError",
    "ImportReport",
    "TranscriptArtifact",
]


Source = Literal["claude-session", "codex-rollout"]
TitleSource = Literal["explicit", "first_user_message", "null"]
ByteCapSource = Literal[
    "default", "env:AGENTLENS_IMPORT_BYTE_CAP", "flag:--byte-cap"
]
AnalysisState = Literal["full", "partial", "skipped"]

# Default 64 MiB cap (spec §4.1). Override via env/flag in callers.
_DEFAULT_BYTE_CAP = 64 * 1024 * 1024

# Valid skip-reason prefixes; record_skip rejects everything else so unknown
# reasons cannot silently land in the report.
_REASON_MALFORMED = "json_decode"
_REASON_OVERSIZED = "line_too_large"
_REASON_UNSUPPORTED_PREFIX = "unsupported_type:"


@dataclass(frozen=True)
class FirstError:
    """First skip recorded during an import.

    Captured once (later skips do not overwrite) so a reader can locate the
    earliest divergence between the raw source and what landed on disk.
    """

    line_number: int
    byte_offset: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_number": self.line_number,
            "byte_offset": self.byte_offset,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TranscriptArtifact:
    """Pointer to the verbatim transcript copy written next to the report."""

    path: str
    bytes: int
    copied: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "bytes": self.bytes, "copied": self.copied}


@dataclass
class ImportReport:
    """Mutable per-import accounting (spec §4.1).

    Counters mutate via `record_parsed`/`record_skip`; everything else is
    populated by setters on the import path. `analysis_state` is computed.
    """

    source: Source
    source_session_id: str = ""
    source_path: str = ""  # redacted label, never the raw absolute path
    source_path_hash: str = ""  # "sha256:<64-hex>"
    source_bytes: int = 0
    byte_cap_bytes: int = _DEFAULT_BYTE_CAP
    byte_cap_hit: bool = False
    byte_cap_source: ByteCapSource = "default"
    deep_parse_only_skipped: bool = False
    total_scanned: int = 0
    parsed: int = 0
    skipped_malformed: int = 0
    skipped_unsupported_type: int = 0
    skipped_oversized: int = 0
    first_error: Optional[FirstError] = None
    transcript_artifact: Optional[TranscriptArtifact] = None
    display_title: Optional[str] = None
    title_source: TitleSource = "null"
    title_algorithm: str = "agentlens.title.v1"
    duration_ms: int = 0
    schema_version: str = "1"

    # ------------------------------------------------------------------
    # Counter mutators
    # ------------------------------------------------------------------

    def record_parsed(self) -> None:
        """Account a successfully parsed line."""
        self.total_scanned += 1
        self.parsed += 1

    def record_skip(
        self, reason: str, line_number: int, byte_offset: int
    ) -> None:
        """Account a skipped line.

        Bumps `total_scanned` and the per-reason counter; on the first call
        also populates `first_error`. Unknown reasons raise ``ValueError`` so
        a typo cannot silently inflate `total_scanned` without a counter.
        """
        self.total_scanned += 1
        if reason == _REASON_MALFORMED:
            self.skipped_malformed += 1
        elif reason == _REASON_OVERSIZED:
            self.skipped_oversized += 1
        elif reason.startswith(_REASON_UNSUPPORTED_PREFIX):
            self.skipped_unsupported_type += 1
        else:
            raise ValueError(f"unknown skip reason: {reason!r}")

        if self.first_error is None:
            self.first_error = FirstError(
                line_number=line_number,
                byte_offset=byte_offset,
                reason=reason,
            )

    def record_byte_cap_hit(self) -> None:
        """Mark that the byte-cap was reached during scanning."""
        self.byte_cap_hit = True

    def set_transcript_artifact(self, path: str | Path, bytes: int) -> None:
        """Attach the verbatim-transcript artifact pointer."""
        self.transcript_artifact = TranscriptArtifact(
            path=str(path), bytes=int(bytes)
        )

    def set_display_title(
        self, title: Optional[str], source: TitleSource
    ) -> None:
        """Assign the derived display title and its provenance."""
        self.display_title = title
        self.title_source = source

    def set_source_path(self, raw: str | Path) -> None:
        """Populate the redacted source-path label and hash.

        The label never contains the raw absolute path — only
        ``<source>:<session-id>`` — so callers can publish the report without
        leaking ``$HOME`` or session-directory layout. The accompanying
        ``source_path_hash`` is the sha256 of the resolved absolute path,
        sufficient for cross-report correlation.
        """
        resolved = str(Path(raw).resolve())
        digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()
        self.source_path_hash = f"sha256:{digest}"
        self.source_path = f"{self.source}:{self.source_session_id}"

    def finalize(self, duration_ms: int) -> None:
        """Record the wall-clock cost of the import (final field set)."""
        self.duration_ms = int(duration_ms)

    # ------------------------------------------------------------------
    # Derived state + serialization
    # ------------------------------------------------------------------

    @property
    def analysis_state(self) -> AnalysisState:
        """Compute the analysis state per spec §4.1.

        ``skipped`` wins over everything else: it signals "we did not deep-
        parse this source at all" (e.g., source exceeded the byte cap and the
        caller opted out of partial parsing). ``partial`` covers any skip or
        byte-cap-hit during deep parsing. ``full`` is the no-loss path.
        """
        if self.deep_parse_only_skipped:
            return "skipped"
        any_skip = (
            self.skipped_malformed
            + self.skipped_unsupported_type
            + self.skipped_oversized
        ) > 0
        if self.byte_cap_hit or any_skip:
            return "partial"
        return "full"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the exact spec §4.1 JSON shape."""
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "source_path": self.source_path,
            "source_path_hash": self.source_path_hash,
            "source_session_id": self.source_session_id,
            "analysis_state": self.analysis_state,
            "source_bytes": self.source_bytes,
            "byte_cap_bytes": self.byte_cap_bytes,
            "byte_cap_hit": self.byte_cap_hit,
            "byte_cap_source": self.byte_cap_source,
            "lines": {
                "total_scanned": self.total_scanned,
                "parsed": self.parsed,
                "skipped_malformed": self.skipped_malformed,
                "skipped_unsupported_type": self.skipped_unsupported_type,
                "skipped_oversized": self.skipped_oversized,
            },
            "first_error": (
                self.first_error.to_dict()
                if self.first_error is not None
                else None
            ),
            "transcript_artifact": (
                self.transcript_artifact.to_dict()
                if self.transcript_artifact is not None
                else None
            ),
            "derived": {
                "display_title": self.display_title,
                "title_source": self.title_source,
                "title_algorithm": self.title_algorithm,
            },
            "duration_ms": self.duration_ms,
        }
