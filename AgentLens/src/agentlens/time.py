"""Time helpers (spec §S1.6.2).

All AgentLens timestamps are UTC ISO8601 with a trailing ``Z``. The schemas
validate this with the pattern::

    ^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$

Naive datetimes or non-UTC offsets are rejected.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# Strict ISO8601 UTC pattern matching the schema constraint.
_ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"
)
# Looser substring pattern used when normalizing diffs.
_ISO_UTC_SUB_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z"
)

_PLACEHOLDER = "0000-00-00T00:00:00.000000Z"


def utc_now_iso() -> str:
    """Return the current time as ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (UTC)."""
    s = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    # Replace the trailing ``+00:00`` with ``Z`` to match the spec format.
    if s.endswith("+00:00"):
        s = s[: -len("+00:00")] + "Z"
    return s


# Acceptance-criteria alias (see task-resolution note).
now_iso = utc_now_iso


def validate_iso8601_utc(s: str) -> bool:
    """Return True iff *s* is a valid UTC ISO8601 string per the spec."""
    if not isinstance(s, str):
        return False
    return bool(_ISO_UTC_RE.match(s))


def parse_iso(s: str) -> datetime:
    """Parse a UTC ISO8601 string and return a tz-aware :class:`datetime`.

    Raises :class:`ValueError` for malformed input or non-UTC offsets.
    """
    if not isinstance(s, str):
        raise ValueError(f"expected str, got {type(s).__name__}")
    if not _ISO_UTC_RE.match(s):
        raise ValueError(f"not a UTC ISO8601 timestamp: {s!r}")
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    # The regex already enforces Z, but be defensive about offsets.
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError(f"timestamp is not UTC: {s!r}")
    return dt


def normalize_for_diff(s: str) -> str:
    """Replace every ISO8601-UTC substring with a fixed placeholder.

    Used by determinism regression tests so two recordings with different
    timestamps can be compared byte-for-byte.
    """
    return _ISO_UTC_SUB_RE.sub(_PLACEHOLDER, s)


__all__ = [
    "normalize_for_diff",
    "now_iso",
    "parse_iso",
    "utc_now_iso",
    "validate_iso8601_utc",
]
