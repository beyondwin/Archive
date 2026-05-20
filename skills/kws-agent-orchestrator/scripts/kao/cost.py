from __future__ import annotations

from typing import Any


def normalize_cost(raw: dict[str, Any]) -> dict[str, Any]:
    if "input_tokens" in raw or "output_tokens" in raw:
        return {
            "tokens_input": int(raw.get("input_tokens", 0) or 0),
            "tokens_output": int(raw.get("output_tokens", 0) or 0),
            "cost_usd": raw.get("cost_usd"),
            "status": "ok",
        }
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else None
    if usage:
        return {
            "tokens_input": int(usage.get("prompt_tokens", 0) or 0),
            "tokens_output": int(usage.get("completion_tokens", 0) or 0),
            "cost_usd": raw.get("cost_usd"),
            "status": "ok",
        }
    return {"tokens_input": 0, "tokens_output": 0, "cost_usd": None, "status": "unknown"}
