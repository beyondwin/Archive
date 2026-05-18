"""Secret/path/excerpt patterns for the v1 redaction engine (spec §5.11).

This module is intentionally pure data + small pure helpers; the heavy lifting
lives in :mod:`agentlens.redaction.redact`. All values are part of the public
contract documented in §5.11 and §8.1–8.2.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

# --- Secret regexes (spec §5.11) --------------------------------------------
#
# Each entry is (kind, compiled_pattern). ``kind`` is embedded in the
# replacement token ``<REDACTED:{kind}>`` so downstream consumers can tell
# what was scrubbed without ever seeing the cleartext.

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("stripe_key", re.compile(r"\b(?:pk|sk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("auth_header", re.compile(r"(?im)^authorization:\s*\S+.*$")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----")),
]

# --- Path prefixes (spec §5.11/§8.1) ----------------------------------------
#
# Anything starting with one of these prefixes is treated as a real filesystem
# path and replaced by ``<HOME>/<HASH8>`` (see ``mask_path``). ``Path.home()``
# is listed first so the user's actual home directory is matched preferentially
# over the broader ``/Users/`` / ``/home/`` umbrellas.

HOME_PREFIXES: list[str] = [str(Path.home()), "/Users/", "/home/"]


# --- Excerpt extractors (spec §5.11/§8.2) -----------------------------------
#
# An allow-listed set of small functions that pull a short, well-formed
# summary line from a larger blob. Anything not produced by an extractor is
# never persisted as an excerpt (§8.2 "excerpt allow-list policy").


_PYTEST_SUMMARY_RX = re.compile(
    r"\d+\s+(?:passed|failed|errors?|skipped|warnings?|xfailed|xpassed|deselected)"
    r"(?:[^\n]*\d+\s+(?:passed|failed|errors?|skipped|warnings?|xfailed|xpassed|deselected))*"
    r"[^\n]*",
    re.IGNORECASE,
)


def _extract_pytest_summary(raw: str) -> str | None:
    """Return the tail-summary line from pytest output, or ``None``.

    Picks the **last** matching line so multi-run logs surface their final
    summary rather than the first one.
    """
    if not isinstance(raw, str):
        return None
    matches = list(_PYTEST_SUMMARY_RX.finditer(raw))
    if not matches:
        return None
    return matches[-1].group(0).strip()


_EXIT_CODE_RX = re.compile(
    r"[^\n]*(?:exited with code|exit code|return code)\s+-?\d+[^\n]*",
    re.IGNORECASE,
)


def _extract_exit_code(raw: str) -> str | None:
    """Return the line announcing a process exit code, or ``None``."""
    if not isinstance(raw, str):
        return None
    m = _EXIT_CODE_RX.search(raw)
    return m.group(0).strip() if m else None


_ERROR_TYPE_RX = re.compile(
    r"(?m)^[^\n]*\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\b\s*:\s*[^\n]*"
)


def _extract_error_type(raw: str) -> str | None:
    """Return the last ``<Type>: <message>`` line found in *raw*, or ``None``.

    "Last" because Python tracebacks place the actual error class at the
    bottom of the traceback chain, after any chained causes.
    """
    if not isinstance(raw, str):
        return None
    matches = list(_ERROR_TYPE_RX.finditer(raw))
    if not matches:
        return None
    return matches[-1].group(0).strip()


EXCERPT_EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "pytest_summary": _extract_pytest_summary,
    "exit_code_line": _extract_exit_code,
    "error_type": _extract_error_type,
}


# --- Protected keys (spec §5.12) --------------------------------------------
#
# Literal keys whose values must NEVER be transformed by the redactor — they
# are stable identifiers, hashes, or schema-controlled enums. Suffix-matching
# (``*_hash``) is handled separately in :mod:`agentlens.redaction.redact`.

PROTECTED_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "run_id",
        "workspace_id",
        "event_id",
        "parent_run_id",
        "sha256",
        "status",
        "type",
        "category",
        "severity",
        "source",
        "blame_scope",
        "recoverability",
        "sealed_phase",
        "agent_outcome",
    }
)

PROTECTED_KEY_SUFFIXES: tuple[str, ...] = ("_hash",)


__all__ = [
    "EXCERPT_EXTRACTORS",
    "HOME_PREFIXES",
    "PROTECTED_KEYS",
    "PROTECTED_KEY_SUFFIXES",
    "SECRET_PATTERNS",
]
