"""Frozen pricing — update on Anthropic rate change. Historical runs preserve commit-time rates."""

PRICES = {
    "claude-opus-4-7": {
        "input_per_mtok": 15.00,
        "output_per_mtok": 75.00,
        "cached_read_per_mtok": 1.50,
        "cached_write_per_mtok": 18.75,
    },
    "claude-sonnet-4-6": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cached_read_per_mtok": 0.30,
        "cached_write_per_mtok": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.00,
        "cached_read_per_mtok": 0.08,
        "cached_write_per_mtok": 1.00,
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
    )
