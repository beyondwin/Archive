"""Tests that pass for BOTH good_impl and broken_impl.

These tests only cover the 10 'safe' behaviors. They do NOT cover the 5 edge
cases that broken_impl gets wrong (internal whitespace, uppercase, repeated
unit, decimal, bare unit). This simulates the realistic case where the test
author thought of obvious cases but missed the subtle ones — exactly when
quality matters.

Run as: python -m pytest -q calibration/tests.py
"""

import pytest

# Import both — but only test against one at a time via parametrize.
import good_impl, broken_impl


@pytest.fixture(params=[good_impl.parse_duration, broken_impl.parse_duration], ids=["good", "broken"])
def parse(request):
    return request.param


def test_seconds(parse):
    assert parse("30s") == 30


def test_minutes(parse):
    assert parse("5m") == 300


def test_hours(parse):
    assert parse("2h") == 7200


def test_days(parse):
    assert parse("1d") == 86400


def test_multi(parse):
    assert parse("1h30m") == 5400


def test_multi_three(parse):
    assert parse("1h30m45s") == 5445


def test_any_order(parse):
    assert parse("30m1h") == 5400


def test_zero(parse):
    assert parse("0s") == 0


def test_zero_with_others(parse):
    assert parse("0h30m") == 1800


def test_outer_whitespace(parse):
    assert parse(" 30s ") == 30


def test_empty_raises(parse):
    with pytest.raises(ValueError):
        parse("")


def test_bare_number_raises(parse):
    with pytest.raises(ValueError):
        parse("30")


def test_unknown_unit_raises(parse):
    with pytest.raises(ValueError):
        parse("5x")


def test_negative_raises(parse):
    with pytest.raises(ValueError):
        parse("-30s")
