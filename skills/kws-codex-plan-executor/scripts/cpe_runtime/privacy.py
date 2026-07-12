from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence


_FORBIDDEN_VALUE_PATTERNS = (
    ("P001", re.compile(r"(?:/Users/|/home/|/private/tmp/|/tmp/|/var/folders/)", re.I)),
    ("P002", re.compile(r"(?:OPENAI_API_KEY|CODEX_API_KEY|auth\.json)", re.I)),
    ("P003", re.compile(r"(?:^|[\"/])oracle(?:[\"/])", re.I)),
    ("P004", re.compile(r"transcripts?", re.I)),
)
_FORBIDDEN_KEYS = frozenset(
    {
        "auth",
        "auth_path",
        "credential",
        "credentials",
        "debug_note",
        "oracle",
        "oracle_path",
        "raw_output",
        "raw_output_path",
        "secret",
        "secrets",
        "transcript",
        "transcripts",
    }
)


def _sensitive_key_present(payload: object) -> bool:
    if isinstance(payload, Mapping):
        return any(
            not isinstance(key, str)
            or key.lower().replace("-", "_") in _FORBIDDEN_KEYS
            or _sensitive_key_present(value)
            for key, value in payload.items()
        )
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return any(_sensitive_key_present(value) for value in payload)
    return False


def audit_sanitized_payload(payload: object) -> dict[str, object]:
    """Audit the actual sanitized object graph with stable, non-sensitive codes."""

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    failures = [code for code, pattern in _FORBIDDEN_VALUE_PATTERNS if pattern.search(serialized)]
    if _sensitive_key_present(payload):
        failures.append("P005")
    failures = list(dict.fromkeys(failures))
    return {"passed": not failures, "failures": failures}
