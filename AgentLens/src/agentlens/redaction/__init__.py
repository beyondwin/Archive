"""AgentLens redaction engine (spec §5.11–5.12, §8.1–8.2, task_22).

Provides regex-based secret masking, path scrubbing, excerpt extraction, and
a recursive ``apply_to_doc`` used by the writer before persisting any v1
document. Privacy-by-default per §8.1: redaction runs on every write and the
post-redact payload is re-validated against the JSON schema (ER-6).

Public surface re-exported from :mod:`agentlens.redaction.redact` and
:mod:`agentlens.redaction.patterns`.
"""
from agentlens.redaction.patterns import (
    EXCERPT_EXTRACTORS,
    HOME_PREFIXES,
    PROTECTED_KEYS,
    PROTECTED_KEY_SUFFIXES,
    SECRET_PATTERNS,
)
from agentlens.redaction.redact import (
    apply_to_doc,
    make_excerpt,
    mask_path,
    mask_secret,
)

__all__ = [
    "EXCERPT_EXTRACTORS",
    "HOME_PREFIXES",
    "PROTECTED_KEYS",
    "PROTECTED_KEY_SUFFIXES",
    "SECRET_PATTERNS",
    "apply_to_doc",
    "make_excerpt",
    "mask_path",
    "mask_secret",
]
