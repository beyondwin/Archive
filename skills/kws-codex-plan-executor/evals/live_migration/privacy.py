"""Shared privacy contract for sanitized v4 quality evidence."""

from __future__ import annotations

import re

from .contracts import canonical_json


FORBIDDEN_SANITIZED_PATTERNS = {
    "absolute_home_path": r"(?:/Users/|/home/|/private/tmp/|/var/folders/)",
    "credential_material": r"(?:OPENAI_API_KEY|CODEX_API_KEY|auth\.json)",
    "hidden_oracle_path": r"(?:^|[\"/])oracle(?:[\"/])",
    "transcript_surface": r"transcripts?",
}


def audit_sanitized_payload(payload: object) -> dict[str, object]:
    """Return the stable fail-closed privacy verdict used by runner and importer."""

    serialized = canonical_json(payload).decode("utf-8")
    failures = [
        name
        for name, pattern in FORBIDDEN_SANITIZED_PATTERNS.items()
        if re.search(pattern, serialized, re.I)
    ]
    return {"passed": not failures, "failures": failures}
