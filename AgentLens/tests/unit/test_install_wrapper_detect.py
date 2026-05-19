"""Unit tests for the install-time wrapper-signature scanner (spec §3.1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentlens.adapters.wrapper_detect import (
    ANTI_WRAPPER_SIGNATURES,
    WrapperDetection,
    scan_real_candidate,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "install_wrapper_safety"


def test_cmux_launcher_fixture_is_flagged_as_cmux() -> None:
    result = scan_real_candidate(FIXTURES / "cmux-launcher.sh")
    assert isinstance(result, WrapperDetection)
    assert result.category == "cmux"
    # find_real_claude is listed before HOOKS_JSON; first-match wins.
    assert result.matched_pattern == b"find_real_claude"
    assert result.remediation.startswith("agentlens install ")
    assert "--cmux" in result.remediation


def test_self_shim_fixture_is_flagged_as_agentlens_self() -> None:
    result = scan_real_candidate(FIXTURES / "self-shim.sh")
    assert result.category == "agentlens_self"
    assert result.matched_pattern is not None
    assert b"agentlens" in result.matched_pattern
    assert result.remediation.startswith("agentlens install ")
    assert "--real" in result.remediation


def test_path_lookup_fixture_is_flagged_as_path_lookup() -> None:
    result = scan_real_candidate(FIXTURES / "path-lookup.sh")
    assert result.category == "path_lookup"
    assert result.matched_pattern is not None
    assert b"command -v" in result.matched_pattern
    assert result.remediation.startswith("agentlens install ")
    assert "--real" in result.remediation


def test_safe_binary_without_shebang_is_not_flagged() -> None:
    result = scan_real_candidate(FIXTURES / "safe-binary.bin")
    assert result.category is None
    assert result.matched_pattern is None
    assert result.remediation == ""


def test_loop_trap_fixture_has_shebang_but_no_wrapper_signature(tmp_path: Path) -> None:
    # The loop-trap.sh fixture is for Task 5. It has a shebang but no
    # wrapper-signature pattern, so Layer 1 should NOT flag it here.
    result = scan_real_candidate(FIXTURES / "loop-trap.sh")
    assert result.category is None
    assert result.matched_pattern is None
    assert result.remediation == ""


def test_empty_file_is_not_flagged(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    result = scan_real_candidate(empty)
    assert result.category is None
    assert result.matched_pattern is None
    assert result.remediation == ""


def test_signature_past_16kib_cap_is_not_flagged(tmp_path: Path) -> None:
    # 32 KiB shell script with the wrapper signature placed beyond 16 KiB.
    # Per spec, the scanner reads only the first 16 KiB — by design.
    big = tmp_path / "big-script.sh"
    head = b"#!/usr/bin/env bash\n"
    pad = b"# padding\n" * 2048  # ~20 KiB of comments
    sig = b"find_real_claude() { :; }\n"
    big.write_bytes(head + pad + sig)
    assert len(head + pad + sig) > 16 * 1024
    result = scan_real_candidate(big)
    assert result.category is None
    assert result.matched_pattern is None
    assert result.remediation == ""


def test_binary_with_coincidental_byte_sequence_is_not_flagged(tmp_path: Path) -> None:
    # No shebang → accept (Mach-O / ELF path), even if pattern bytes appear.
    bin_file = tmp_path / "weird.bin"
    bin_file.write_bytes(b"\x7fELF\x02\x01" + b"find_real_claude" + b"\x00" * 64)
    result = scan_real_candidate(bin_file)
    assert result.category is None
    assert result.matched_pattern is None
    assert result.remediation == ""


def test_exec_path_lookup_pattern_matches(tmp_path: Path) -> None:
    script = tmp_path / "exec-path.sh"
    script.write_bytes(b"#!/usr/bin/env bash\nexec $PATH/bin/claude \"$@\"\n")
    result = scan_real_candidate(script)
    assert result.category == "path_lookup"
    assert result.matched_pattern is not None


def test_which_pattern_matches(tmp_path: Path) -> None:
    script = tmp_path / "which-script.sh"
    script.write_bytes(b"#!/usr/bin/env bash\nexec $(which codex) \"$@\"\n")
    result = scan_real_candidate(script)
    assert result.category == "path_lookup"
    assert result.matched_pattern == rb"which (claude|codex)\b"


def test_cmux_env_var_signatures_match(tmp_path: Path) -> None:
    for needle in (b"CMUX_AGENT_LAUNCH", b"CMUX_BUNDLED_CLI_PATH", b"HOOKS_JSON"):
        script = tmp_path / f"{needle.decode()}.sh"
        script.write_bytes(b"#!/usr/bin/env bash\n" + needle + b"=1\nexec claude \"$@\"\n")
        result = scan_real_candidate(script)
        assert result.category == "cmux", f"expected cmux for {needle!r}"


def test_first_match_wins_ordering(tmp_path: Path) -> None:
    # Contains both agentlens_self and cmux patterns; agentlens_self is first.
    script = tmp_path / "mixed.sh"
    script.write_bytes(
        b"#!/usr/bin/env bash\n"
        b"agentlens run --agent claude_code\n"
        b"find_real_claude\n"
    )
    result = scan_real_candidate(script)
    assert result.category == "agentlens_self"


def test_signatures_table_categories_are_well_formed() -> None:
    valid = {"agentlens_self", "cmux", "path_lookup"}
    for pattern, category in ANTI_WRAPPER_SIGNATURES:
        assert isinstance(pattern, bytes)
        assert category in valid


def test_remediation_messages_are_category_specific(tmp_path: Path) -> None:
    cases = {
        "agentlens_self": b"#!/bin/sh\nexec agentlens run --agent claude_code -- \"$@\"\n",
        "cmux": b"#!/bin/sh\nfind_real_claude\n",
        "path_lookup": b"#!/bin/sh\nexec $(command -v claude) \"$@\"\n",
    }
    for expected_category, content in cases.items():
        f = tmp_path / f"{expected_category}.sh"
        f.write_bytes(content)
        result = scan_real_candidate(f)
        assert result.category == expected_category
        assert result.remediation.startswith("agentlens install ")
        if expected_category == "cmux":
            assert "--cmux" in result.remediation
            assert "--real" in result.remediation
        else:
            assert "--real" in result.remediation
