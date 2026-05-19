"""Unit tests for importers.title.extract_display_title (spec §4.2)."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from agentlens.importers.title import extract_display_title

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "titles"


# ---------------------------------------------------------------------------
# Basic input handling
# ---------------------------------------------------------------------------


def test_returns_none_for_all_none() -> None:
    assert extract_display_title() is None


def test_returns_none_for_empty_strings() -> None:
    assert extract_display_title(explicit="", first_user_message="") is None


def test_returns_none_for_whitespace_only() -> None:
    assert extract_display_title(first_user_message="   \n\t  \n") is None


def test_explicit_wins_over_first_user_message() -> None:
    out = extract_display_title(
        explicit="My run", first_user_message="Some message"
    )
    assert out == "My run"


def test_explicit_is_capped_at_max_chars() -> None:
    explicit = "a" * 200
    out = extract_display_title(explicit=explicit)
    assert out is not None
    assert len(out) == 120
    assert out.endswith("…")


def test_explicit_below_cap_passes_through() -> None:
    out = extract_display_title(explicit="short title")
    assert out == "short title"


def test_explicit_whitespace_falls_through_to_first_user_message() -> None:
    out = extract_display_title(
        explicit="   ", first_user_message="From the message"
    )
    assert out == "From the message"


# ---------------------------------------------------------------------------
# Strip rules
# ---------------------------------------------------------------------------


def test_strips_fenced_code_block() -> None:
    msg = "Fix the bug ```python\ndef foo():\n    pass\n``` in handler."
    out = extract_display_title(first_user_message=msg)
    # Fenced block removed; what remains collapses to a single first line.
    assert out == "Fix the bug in handler."


def test_fenced_code_block_leaves_first_line_only() -> None:
    # Spec rule 4: first non-empty line wins. If the fenced block split the
    # original content across lines, only the first surviving line is used.
    msg = "Header line\n```\ncode here\n```\nFooter line"
    out = extract_display_title(first_user_message=msg)
    assert out == "Header line"


def test_strips_inline_code() -> None:
    msg = "Use `helper()` to wrap calls."
    out = extract_display_title(first_user_message=msg)
    assert out == "Use to wrap calls."


def test_strips_headless_orchestrator_sentinel() -> None:
    msg = "<<HEADLESS_KWS_ORCHESTRATOR>> Real task here"
    out = extract_display_title(first_user_message=msg)
    assert out == "Real task here"


def test_strips_arbitrary_sentinels() -> None:
    msg = "<<TASK_42>> Do the thing <<EOM>>"
    out = extract_display_title(first_user_message=msg)
    assert out == "Do the thing"


def test_strips_agents_block_multiline() -> None:
    msg = (
        "<AGENTS>\nYou are an agent.\nFollow rules.\n</AGENTS>\n"
        "Actual user request"
    )
    out = extract_display_title(first_user_message=msg)
    assert out == "Actual user request"


def test_strips_system_reminder_block_multiline() -> None:
    msg = (
        "<system-reminder>\nbe nice\nbe brief\n</system-reminder>\n"
        "Real ask"
    )
    out = extract_display_title(first_user_message=msg)
    assert out == "Real ask"


@pytest.mark.parametrize(
    "prefix",
    ["AGENTS:", "# AGENTS", "Environment:", "Working directory:"],
)
def test_strips_meta_lines(prefix: str) -> None:
    msg = f"{prefix} something\nReal title line"
    out = extract_display_title(first_user_message=msg)
    assert out == "Real title line"


def test_strips_absolute_paths_to_placeholder() -> None:
    msg = "Open /Users/foo/bar/baz.py please"
    out = extract_display_title(first_user_message=msg)
    assert out == "Open <path> please"


def test_does_not_strip_single_segment_root() -> None:
    # Regex requires (?:/[\w.\-]+){2,} → at least 2 segments.
    msg = "Mount /tmp now"
    out = extract_display_title(first_user_message=msg)
    assert out == "Mount /tmp now"


def test_strips_control_chars() -> None:
    msg = "Hello\x00world\x01x\x07y\x1ftail"
    out = extract_display_title(first_user_message=msg)
    assert out == "Helloworldxytail"


def test_preserves_short_url() -> None:
    msg = "See https://example.com for details"
    out = extract_display_title(first_user_message=msg)
    assert out == "See https://example.com for details"


def test_truncates_long_url() -> None:
    url = "https://example.com/" + "x" * 100
    msg = f"Visit {url} now"
    out = extract_display_title(first_user_message=msg)
    assert out is not None
    # URL truncated to 64 code points with U+2026 at position 63.
    expected_url = url[:63] + "…"
    assert expected_url in out
    assert url not in out
    assert len(expected_url) == 64


# ---------------------------------------------------------------------------
# Cap + truncation semantics
# ---------------------------------------------------------------------------


def test_cap_counts_code_points_not_bytes() -> None:
    # 100 Korean syllables = 100 code points but ~300 UTF-8 bytes.
    msg = "가" * 100
    out = extract_display_title(first_user_message=msg)
    assert out == "가" * 100  # under 120 code points, passes through


def test_truncates_at_120_with_horizontal_ellipsis() -> None:
    msg = "a" * 200
    out = extract_display_title(first_user_message=msg)
    assert out is not None
    assert len(out) == 120
    assert out[-1] == "…"
    assert out[:-1] == "a" * 119


def test_truncation_uses_single_char_ellipsis_not_three_dots() -> None:
    msg = "b" * 200
    out = extract_display_title(first_user_message=msg)
    assert out is not None
    assert not out.endswith("...")
    assert out.endswith("…")


def test_custom_max_chars_respected() -> None:
    msg = "z" * 50
    out = extract_display_title(first_user_message=msg, max_chars=10)
    assert out is not None
    assert len(out) == 10
    assert out.endswith("…")


# ---------------------------------------------------------------------------
# Punctuation-only / passthrough
# ---------------------------------------------------------------------------


def test_punctuation_only_returns_none() -> None:
    assert extract_display_title(first_user_message="!!! ??? ...") is None


def test_punctuation_after_strip_returns_none() -> None:
    msg = "<<X>> `code` !!!"
    assert extract_display_title(first_user_message=msg) is None


def test_korean_passthrough() -> None:
    msg = "한국어 제목입니다"
    assert extract_display_title(first_user_message=msg) == msg


def test_japanese_passthrough() -> None:
    msg = "日本語のタイトル"
    assert extract_display_title(first_user_message=msg) == msg


def test_emoji_passthrough() -> None:
    msg = "Ship it 🚀 today"
    assert extract_display_title(first_user_message=msg) == "Ship it 🚀 today"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_across_reruns() -> None:
    msg = (
        "<system-reminder>be nice</system-reminder>\n"
        "<<TAG>> Investigate `bug` at /Users/a/b/c.py for details "
        "with https://example.com/" + "y" * 80
    )
    first = extract_display_title(first_user_message=msg)
    for _ in range(5):
        assert extract_display_title(first_user_message=msg) == first


# ---------------------------------------------------------------------------
# Fuzz: never raises
# ---------------------------------------------------------------------------


def test_extract_display_title_fuzz_never_raises() -> None:
    rng = random.Random(0)
    for _ in range(200):
        raw = bytes(rng.randrange(256) for _ in range(1024))
        text = raw.decode("utf-8", errors="replace")
        result = extract_display_title(first_user_message=text)
        assert result is None or isinstance(result, str)
        if isinstance(result, str):
            assert len(result) <= 120


def test_extract_display_title_fuzz_is_deterministic() -> None:
    rng_a = random.Random(0)
    rng_b = random.Random(0)
    for _ in range(50):
        raw_a = bytes(rng_a.randrange(256) for _ in range(512))
        raw_b = bytes(rng_b.randrange(256) for _ in range(512))
        text_a = raw_a.decode("utf-8", errors="replace")
        text_b = raw_b.decode("utf-8", errors="replace")
        assert text_a == text_b
        assert (
            extract_display_title(first_user_message=text_a)
            == extract_display_title(first_user_message=text_b)
        )


# ---------------------------------------------------------------------------
# Paired fixture loop
# ---------------------------------------------------------------------------


def _fixture_pairs() -> list[tuple[str, Path, Path]]:
    pairs: list[tuple[str, Path, Path]] = []
    for input_path in sorted(FIXTURES.glob("*.input.md")):
        stem = input_path.name[: -len(".input.md")]
        expected_path = FIXTURES / f"{stem}.expected.txt"
        pairs.append((stem, input_path, expected_path))
    return pairs


@pytest.mark.parametrize("stem,input_path,expected_path", _fixture_pairs())
def test_fixture(stem: str, input_path: Path, expected_path: Path) -> None:
    raw = input_path.read_bytes().decode("utf-8", errors="replace")
    expected = expected_path.read_text(encoding="utf-8")
    # expected fixtures may end with a trailing newline; normalize.
    expected = expected.rstrip("\n")
    actual = extract_display_title(first_user_message=raw)
    assert actual == expected, f"fixture {stem!r} mismatch"


def test_fixture_dir_has_at_least_eight_pairs() -> None:
    pairs = _fixture_pairs()
    assert len(pairs) >= 8, f"only {len(pairs)} fixture pairs found"
    # Ensure each pair has both files.
    for stem, ip, ep in pairs:
        assert ip.exists(), f"missing input for {stem}"
        assert ep.exists(), f"missing expected for {stem}"
