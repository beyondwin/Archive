"""Secret/path scrubbing + recursive doc redaction (spec §5.12, task_22).

The writer (:mod:`agentlens.store.writer`) calls :func:`apply_to_doc` on every
document before it is persisted, then re-validates against the JSON schema
(ER-6 in §5.6). Anything that escapes scrubbing here lands on disk, so this
module is the privacy boundary for the local recording.

Public functions:
    mask_secret(text)            — regex-replace known secret tokens.
    mask_path(text, workspace_root=None) — strip workspace + home prefixes.
    make_excerpt(raw, *, extractor) — allow-listed excerpt extraction.
    apply_to_doc(doc, *, workspace_root=None) — recursive redact, returns copy.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from agentlens.constants import MAX_EXCERPT_CHARS

from .patterns import (
    EXCERPT_EXTRACTORS,
    HOME_PREFIXES,
    PROTECTED_KEY_SUFFIXES,
    PROTECTED_KEYS,
    SECRET_PATTERNS,
)


# ---------------------------------------------------------------------------
# Secret masking
# ---------------------------------------------------------------------------


def mask_secret(text: str) -> str:
    """Replace every SECRET_PATTERNS match in *text* with ``<REDACTED:kind>``.

    Non-string inputs are returned unchanged so callers can pass through
    optional values without type-guarding at every call site.
    """
    if not isinstance(text, str):
        return text
    out = text
    for kind, pattern in SECRET_PATTERNS:
        out = pattern.sub(f"<REDACTED:{kind}>", out)
    return out


# ---------------------------------------------------------------------------
# Path masking
# ---------------------------------------------------------------------------


def _home_token(prefix: str) -> str:
    """Stable per-prefix token: ``<HOME>/<sha256(prefix)[:8]>``.

    Hashing the actual prefix (not "HOME") means two different real home
    paths produce two different tags, so a reader can tell "this run came
    from a different account" without learning which account.
    """
    digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:8]
    return f"<HOME>/{digest}"


def mask_path(text: str, workspace_root: Path | None = None) -> str:
    """Strip absolute filesystem paths from *text*.

    Order matters:

    1. If *workspace_root* is given, replace its absolute path with ``./``
       so workspace-relative paths read naturally in dashboards.
    2. Replace any remaining HOME prefix match with ``<HOME>/<HASH8>``.

    Non-string inputs are returned unchanged.
    """
    if not isinstance(text, str):
        return text

    out = text
    if workspace_root is not None:
        ws = str(Path(workspace_root))
        # Replace `<ws>/foo` with `./foo` and a bare `<ws>` with `.`.
        out = out.replace(ws + "/", "./").replace(ws, ".")

    # Sort prefixes by length descending so the most specific (the user's
    # real home directory) wins over the umbrella `/Users/` / `/home/`.
    for prefix in sorted(set(HOME_PREFIXES), key=len, reverse=True):
        if not prefix:
            continue
        # We want to replace `<prefix><user>/...` with `<HOME>/<hash>/...`
        # For umbrella prefixes (`/Users/`, `/home/`) the "username segment"
        # is the next path component; for an absolute `Path.home()` prefix
        # the entire prefix is the user's home and there is no extra segment
        # to consume.
        idx = 0
        while True:
            found = out.find(prefix, idx)
            if found == -1:
                break
            # Determine the full prefix we want to replace, including the
            # next path segment for umbrella prefixes that end in '/'.
            if prefix.endswith("/") and prefix in ("/Users/", "/home/"):
                end = out.find("/", found + len(prefix))
                if end == -1:
                    # Path ends at the username (no trailing slash); consume
                    # to end-of-string-or-whitespace boundary.
                    end = len(out)
                full_prefix = out[found:end]
            else:
                full_prefix = prefix.rstrip("/")
                end = found + len(full_prefix)

            token = _home_token(full_prefix)
            out = out[:found] + token + out[end:]
            idx = found + len(token)
    return out


# ---------------------------------------------------------------------------
# Excerpt extraction
# ---------------------------------------------------------------------------


def make_excerpt(raw: str, *, extractor: str) -> str | None:
    """Return an allow-listed excerpt or ``None``.

    *extractor* must be a key of :data:`EXCERPT_EXTRACTORS`; unknown names
    raise ``KeyError`` so a typo cannot silently bypass the §8.2 allow-list.

    The result is truncated to :data:`MAX_EXCERPT_CHARS` characters.
    """
    fn = EXCERPT_EXTRACTORS[extractor]  # KeyError on unknown - desired.
    result = fn(raw)
    if result is None:
        return None
    if len(result) > MAX_EXCERPT_CHARS:
        result = result[:MAX_EXCERPT_CHARS]
    return result


# ---------------------------------------------------------------------------
# Recursive document redaction
# ---------------------------------------------------------------------------


def _is_protected_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    if key in PROTECTED_KEYS:
        return True
    return any(key.endswith(suffix) for suffix in PROTECTED_KEY_SUFFIXES)


def _mask_string(value: str, *, workspace_root: Path | None) -> str:
    return mask_path(mask_secret(value), workspace_root=workspace_root)


def _walk(value: Any, *, workspace_root: Path | None, key: str | None) -> Any:
    # Protected key: short-circuit. Even if the value is a nested dict we
    # leave it untouched — protected identifiers do not contain free text.
    if key is not None and _is_protected_key(key):
        return value

    if isinstance(value, dict):
        return {
            k: _walk(v, workspace_root=workspace_root, key=k)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _walk(v, workspace_root=workspace_root, key=None) for v in value
        ]
    if isinstance(value, str):
        if key == "path_label":
            # Force path masking even if mask_secret would have been a no-op.
            return mask_path(value, workspace_root=workspace_root)
        masked = _mask_string(value, workspace_root=workspace_root)
        if key == "excerpt" and len(masked) > MAX_EXCERPT_CHARS:
            masked = masked[:MAX_EXCERPT_CHARS]
        return masked
    # ints/floats/bools/None/etc.: nothing to scrub.
    return value


def apply_to_doc(doc: dict, *, workspace_root: Path | None = None) -> dict:
    """Return a redacted deep-copy of *doc*.

    Strings have :func:`mask_secret` and :func:`mask_path` applied. Keys in
    :data:`PROTECTED_KEYS` (and any key ending in ``_hash``) are passed
    through untouched so identifiers, hashes, and schema-controlled enums
    survive intact. ``path_label`` values get an additional forced path-mask
    pass; ``excerpt`` string values are truncated to
    :data:`MAX_EXCERPT_CHARS` after masking.

    Input is never mutated.
    """
    if not isinstance(doc, dict):
        raise TypeError("apply_to_doc requires a dict")
    # Defensive deep-copy: _walk also returns fresh containers, but copying
    # first keeps any non-dict, non-list, non-str leaves safely isolated
    # against future mutation by callers holding references to subtrees.
    snapshot = copy.deepcopy(doc)
    return _walk(snapshot, workspace_root=workspace_root, key=None)  # type: ignore[return-value]


__all__ = [
    "apply_to_doc",
    "make_excerpt",
    "mask_path",
    "mask_secret",
]
