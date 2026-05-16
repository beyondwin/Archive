"""Tests for price_table module — API contract checks."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from price_table import ALIASES, PRICES, compute_cost, get_price  # noqa: E402


def test_known_model_alias_sonnet_input_price():
    assert abs(get_price("sonnet", "input_per_mtok") - 3.00) < 0.001


def test_known_model_alias_opus_output_price():
    assert abs(get_price("opus", "output_per_mtok") - 75.00) < 0.001


def test_known_model_alias_haiku_cached_read_price():
    assert abs(get_price("haiku", "cached_read_per_mtok") - 0.08) < 0.001


def test_canonical_model_id_lookup():
    assert abs(get_price("claude-opus-4-7", "input_per_mtok") - 15.00) < 0.001


def test_unknown_model_returns_zero():
    assert get_price("unknown", "input_per_mtok") == 0.0


def test_completely_unmapped_model_returns_zero():
    assert get_price("nonexistent-model-xyz", "output_per_mtok") == 0.0


def test_compute_cost_sonnet_arithmetic():
    # 2M input * $3 + 1M output * $15 = $6 + $15 = $21
    c = compute_cost(
        "sonnet",
        {
            "input_tokens": 2_000_000,
            "output_tokens": 1_000_000,
            "cached_read_tokens": 0,
            "cached_write_tokens": 0,
        },
    )
    assert 20.99 < c < 21.01, c


def test_compute_cost_with_cached_tokens():
    # opus: 1M input * $15 + 1M output * $75 + 1M cached_read * $1.50 + 1M cached_write * $18.75
    # = 15 + 75 + 1.50 + 18.75 = 110.25
    c = compute_cost(
        "opus",
        {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cached_read_tokens": 1_000_000,
            "cached_write_tokens": 1_000_000,
        },
    )
    assert abs(c - 110.25) < 0.001, c


def test_compute_cost_unknown_model_returns_zero():
    c = compute_cost(
        "unknown",
        {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
        },
    )
    assert c == 0.0


def test_compute_cost_missing_usage_keys_defaults_to_zero():
    # Only input_tokens provided; other keys should default to 0.
    c = compute_cost("sonnet", {"input_tokens": 1_000_000})
    assert abs(c - 3.00) < 0.001, c


def test_module_docstring_exact_text():
    import price_table

    expected = "Frozen pricing — update on Anthropic rate change. Historical runs preserve commit-time rates."
    assert price_table.__doc__ is not None
    assert expected in price_table.__doc__


def test_prices_dict_has_required_models():
    assert "claude-opus-4-7" in PRICES
    assert "claude-sonnet-4-6" in PRICES
    assert "claude-haiku-4-5-20251001" in PRICES


def test_aliases_dict_has_required_keys():
    assert ALIASES["sonnet"] == "claude-sonnet-4-6"
    assert ALIASES["opus"] == "claude-opus-4-7"
    assert ALIASES["haiku"] == "claude-haiku-4-5-20251001"
    assert ALIASES["unknown"] is None


if __name__ == "__main__":
    import traceback

    tests = [
        (name, obj)
        for name, obj in list(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
