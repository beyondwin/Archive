"""Frozen pricing — update on Anthropic rate change. Historical runs preserve commit-time rates."""

PRICES = {
    "claude-opus-4-7": {
        "input_per_mtok": 15.00,
        "output_per_mtok": 75.00,
        "cached_read_per_mtok": 1.50,
        "cached_write_per_mtok": 18.75,
        # API-aligned aliases (Anthropic Messages usage splits cache read vs
        # creation): same rates as cached_read/cached_write above.
        "cache_read_per_mtok": 1.50,
        "cache_creation_per_mtok": 18.75,
    },
    "claude-sonnet-4-6": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cached_read_per_mtok": 0.30,
        "cached_write_per_mtok": 3.75,
        "cache_read_per_mtok": 0.30,
        "cache_creation_per_mtok": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.00,
        "cached_read_per_mtok": 0.08,
        "cached_write_per_mtok": 1.00,
        "cache_read_per_mtok": 0.08,
        "cache_creation_per_mtok": 1.00,
    },
}

ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
    "haiku": "claude-haiku-4-5-20251001",
    "unknown": None,
}


def get_price(model_id: str, kind: str) -> float:
    canonical = ALIASES.get(model_id, model_id)
    if canonical is None or canonical not in PRICES:
        return 0.0
    return PRICES[canonical][kind]


def compute_cost(model_id: str, usage: dict) -> float:
    return (
        usage.get("input_tokens", 0) / 1e6 * get_price(model_id, "input_per_mtok")
        + usage.get("output_tokens", 0) / 1e6 * get_price(model_id, "output_per_mtok")
        + usage.get("cached_read_tokens", 0) / 1e6 * get_price(model_id, "cached_read_per_mtok")
        + usage.get("cached_write_tokens", 0) / 1e6 * get_price(model_id, "cached_write_per_mtok")
        # API-aligned canonical names; any single dispatch populates only ONE
        # naming set, so there is no double counting.
        + usage.get("cache_read_tokens", 0) / 1e6 * get_price(model_id, "cache_read_per_mtok")
        + usage.get("cache_creation_tokens", 0) / 1e6 * get_price(model_id, "cache_creation_per_mtok")
    )
