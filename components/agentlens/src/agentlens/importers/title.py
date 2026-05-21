"""Pure display-title extractor for imported sessions (spec §4.2).

`extract_display_title()` derives a short, redaction-safe display title from a
caller-provided explicit title or the first user message of a session. It is
deterministic, has no I/O, and depends only on the standard library so it can
be reused from any importer without circular-import worries.

The heuristic is intentionally conservative: when in doubt, return ``None``
rather than emit something noisy or leaky. Stripping order matters and is
documented inline.
"""
from __future__ import annotations

import re

__all__ = ["extract_display_title"]

# U+2026 HORIZONTAL ELLIPSIS — single code point, not three dots.
_ELLIPSIS = "…"

# URLs: cap at 64 code points, with U+2026 at position 63 when longer.
_URL_MAX = 64

# Control chars: \x00–\x08, \x0b, \x0c, \x0e–\x1f. (Tab/LF/CR are spared so the
# downstream whitespace-collapse pass can handle them uniformly.)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)

# Inline code: `…`. We deliberately forbid newlines inside the span so a stray
# backtick on its own line cannot swallow half the message.
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

_SENTINEL_RE = re.compile(r"<<[^<>]*>>")

_AGENTS_BLOCK_RE = re.compile(r"<AGENTS>.*?</AGENTS>", re.DOTALL | re.IGNORECASE)
_SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>", re.DOTALL | re.IGNORECASE
)

_META_LINE_PREFIXES = ("AGENTS:", "# AGENTS", "Environment:", "Working directory:")

# Absolute paths: at least two `/segment` components. The character class
# matches typical filename chars (\w covers ASCII letters/digits/underscore;
# also `.` and `-`). The negative lookbehind `(?<!:)` prevents matches that
# start immediately after a URL scheme's colon-slash (so `https://a/b` is left
# to the URL handler).
_ABS_PATH_RE = re.compile(r"(?<![:/\w])(?:/[\w.\-]+){2,}")

_URL_RE = re.compile(r"https?://\S+")

_WHITESPACE_RE = re.compile(r"\s+")

# Code points that count as "punctuation or whitespace" for the rule that
# requires at least one informative character. We accept the Unicode notion of
# alphanumeric (`str.isalnum`) plus the small set of script characters Python
# treats as letters.
def _has_informative_char(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def _truncate_url(url: str) -> str:
    if len(url) <= _URL_MAX:
        return url
    return url[: _URL_MAX - 1] + _ELLIPSIS


def _cap_explicit(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + _ELLIPSIS


def extract_display_title(
    explicit: str | None = None,
    first_user_message: str | None = None,
    max_chars: int = 120,
) -> str | None:
    """Return a redaction-safe display title or ``None``.

    See spec §4.2 for the full algorithm.
    """
    # Rule 1: explicit override wins (after strip), capped at max_chars.
    if explicit is not None:
        stripped = explicit.strip()
        if stripped:
            return _cap_explicit(stripped, max_chars)

    if first_user_message is None:
        return None

    text = first_user_message
    if not text.strip():
        # Rule 2: nothing to extract from.
        return None

    # Rule 3 (in order): strip blocks first so finer rules can't tear them apart.
    text = _FENCED_CODE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    text = _SENTINEL_RE.sub("", text)
    text = _AGENTS_BLOCK_RE.sub("", text)
    text = _SYSTEM_REMINDER_RE.sub("", text)

    # Drop meta lines.
    kept: list[str] = []
    for line in text.splitlines():
        leading = line.lstrip()
        if any(leading.startswith(prefix) for prefix in _META_LINE_PREFIXES):
            continue
        kept.append(line)
    text = "\n".join(kept)

    # Truncate over-long URLs first — their path component would otherwise be
    # eaten by the absolute-path replacement below.
    text = _URL_RE.sub(lambda m: _truncate_url(m.group(0)), text)

    # Replace absolute paths.
    text = _ABS_PATH_RE.sub("<path>", text)

    # Drop control chars.
    text = _CONTROL_CHARS_RE.sub("", text)

    # Rule 4: first non-empty line of what remains, with whitespace collapsed.
    first_line: str | None = None
    for line in text.splitlines():
        collapsed = _WHITESPACE_RE.sub(" ", line).strip()
        if collapsed:
            first_line = collapsed
            break

    if first_line is None:
        return None

    # Rule 6: punctuation/whitespace only → None.
    if not _has_informative_char(first_line):
        return None

    # Rule 5: cap at max_chars; append U+2026 if truncated.
    if len(first_line) > max_chars:
        first_line = first_line[: max_chars - 1] + _ELLIPSIS

    return first_line
