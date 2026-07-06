#!/usr/bin/env python3
"""Tests for initcmd.py — deterministic arg parser + run-id/paths + echo line."""

import datetime
import initcmd


def test_single_plan_defaults():
    c = initcmd.parse_args("plan=docs/p.md spec=docs/s.md")
    assert c["plans"] == [{"plan": "docs/p.md", "spec": "docs/s.md"}]
    assert c["implementer_model"] == "sonnet" and c["parallel"] is True
    assert c["transport_default"] == "p"
    assert c["sources"]["implementer_model"] == "default"


def test_multi_plan_gap_halts():
    try:
        initcmd.parse_args("plan=a.md spec=s.md plan3=c.md spec3=s3.md")
        assert False, "expected ConflictHalt"
    except initcmd.ConflictHalt as e:
        assert "plan2" in str(e)


def test_nl_lexicon_fills_unset():
    c = initcmd.parse_args("plan=a.md spec=s.md 오푸스 순차")
    assert c["implementer_model"] == "opus" and c["parallel"] is False
    assert c["sources"]["implementer_model"] == "nl"


def test_explicit_beats_nl_conflict_halts():
    try:
        initcmd.parse_args("plan=a.md spec=s.md implementer_model=sonnet 오푸스")
        assert False
    except initcmd.ConflictHalt:
        pass


def test_run_id():
    rid = initcmd.derive_run_id("docs/plans/my plan v2.md",
                                datetime.datetime(2026, 7, 6, 9, 5, 1))
    assert rid == "my-plan-v2-20260706-090501"


def test_particle_stripping():
    """Korean grammatical particles are stripped before lexicon matching."""
    c = initcmd.parse_args("plan=a.md spec=s.md 오푸스로 순차적으로")
    assert c["implementer_model"] == "opus"
    assert c["parallel"] is False


def test_echo_line_smoke():
    """echo_line returns a non-empty string and renders unset risk as per-task."""
    c = initcmd.parse_args("plan=a.md spec=s.md")
    line = initcmd.echo_line(c)
    assert isinstance(line, str) and len(line) > 0
    assert "sonnet" in line
    assert "plan" in line.lower() or "1" in line
    assert "risk=per-task" in line


def test_single_plan_missing_spec_halts():
    """A plan= with no matching spec= raises ConflictHalt."""
    try:
        initcmd.parse_args("plan=a.md")
        assert False, "expected ConflictHalt"
    except initcmd.ConflictHalt:
        pass


def test_mode_detach_preserved():
    """mode=interactive and detach=true are parsed and preserved in config."""
    c = initcmd.parse_args("plan=a.md spec=s.md mode=interactive detach=true")
    assert c["mode"] == "interactive"
    assert c["detach"] is True


if __name__ == "__main__":
    test_single_plan_defaults()
    test_multi_plan_gap_halts()
    test_nl_lexicon_fills_unset()
    test_explicit_beats_nl_conflict_halts()
    test_run_id()
    test_particle_stripping()
    test_echo_line_smoke()
    test_single_plan_missing_spec_halts()
    test_mode_detach_preserved()
    print("OK")
