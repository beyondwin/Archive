"""Pure usage-summary extractor for imported sessions (spec §4.3).

``extract_usage()`` aggregates per-record token usage captured by importers
(Claude session JSONL and Codex rollout JSONL) into a single ``UsageSummary``.

The function is intentionally pure: it has no I/O, no clock dependencies, no
pricing logic, and depends only on the standard library. Callers (the
importers) are responsible for slicing the raw vendor lines down to the
"billable" subset (e.g., Claude ``type=="assistant"`` messages, Codex turn
records) before invoking it.

Confidence semantics (spec §4.3):

* ``exact`` — every billable record has usage AND every token field is
  explicitly present in that record (nothing was inferred from a missing key).
* ``estimated`` — at least one record has usage but at least one expected
  token field was missing and treated as 0.
* ``unknown`` — no records, or no records had usage, or fewer than 50 % of
  records had any usage fields. Also returned when the input list is empty.

Cost is always ``None`` in v1.x (no pricing table baked in).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["ModelUsage", "UsageSummary", "extract_usage"]


Source = Literal["claude-session", "codex-rollout"]
Confidence = Literal["exact", "estimated", "unknown"]


# Canonical token field names used both on UsageSummary and ModelUsage.
_TOKEN_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_creation_tokens",
    "cache_read_tokens",
    "reasoning_tokens",
)


@dataclass(frozen=True)
class ModelUsage:
    """Per-model token aggregate."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True)
class UsageSummary:
    """Aggregated usage summary across all billable records in a session."""

    source: Source
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    model_breakdown: tuple[ModelUsage, ...] = ()
    confidence: Confidence = "unknown"
    events_with_usage: int = 0
    events_missing_usage: int = 0
    model_field_missing_events: int = 0
    schema_version: str = "1"
    cost_usd: float | None = None
    pricing_source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the exact spec §4.3 JSON shape."""
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "model_breakdown": [m.to_dict() for m in self.model_breakdown],
            "cost_usd": self.cost_usd,
            "pricing_source": self.pricing_source,
            "confidence": self.confidence,
            "diagnostics": {
                "events_with_usage": self.events_with_usage,
                "events_missing_usage": self.events_missing_usage,
                "model_field_missing_events": self.model_field_missing_events,
            },
        }


# ---------------------------------------------------------------------------
# Vendor-specific extraction helpers
# ---------------------------------------------------------------------------

# Maps for translating raw vendor field names to canonical names. Order matters
# only for error reporting; lookups are by exact key.
_CLAUDE_TOKEN_MAP: dict[str, str] = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_creation_input_tokens": "cache_creation_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    # Claude does not expose reasoning tokens today; if it ever does, both
    # spellings are accepted for forward compatibility.
    "reasoning_tokens": "reasoning_tokens",
    "reasoning_output_tokens": "reasoning_tokens",
}

# Codex already uses canonical names, but accept both spellings defensively.
_CODEX_TOKEN_MAP: dict[str, str] = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_creation_tokens": "cache_creation_tokens",
    "cache_creation_input_tokens": "cache_creation_tokens",
    "cache_read_tokens": "cache_read_tokens",
    "cached_input_tokens": "cache_read_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    "reasoning_tokens": "reasoning_tokens",
    "reasoning_output_tokens": "reasoning_tokens",
}


def _coerce_int(value: Any) -> int | None:
    """Return ``value`` as an int, or ``None`` if not coercible.

    Booleans are rejected (Python treats ``True``/``False`` as ints, but a
    bool-as-token-count is almost certainly a parser bug).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _extract_claude(record: dict[str, Any]) -> tuple[dict[str, int] | None, str | None, bool]:
    """Return ``(tokens, model, fully_populated)``.

    * ``tokens`` is the canonical-key dict, or ``None`` if no usage was found.
    * ``model`` is the model string, or ``None`` if missing.
    * ``fully_populated`` is ``True`` iff every canonical token field expected
      for Claude (``input_tokens``, ``output_tokens``,
      ``cache_creation_tokens``, ``cache_read_tokens``) was explicitly present
      in the raw record (under either canonical or vendor spelling). Used to
      distinguish ``exact`` vs ``estimated`` confidence.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        return None, None, False

    model_raw = message.get("model")
    model = model_raw if isinstance(model_raw, str) and model_raw else None

    usage_raw = message.get("usage")
    if not isinstance(usage_raw, dict):
        return None, model, False

    tokens: dict[str, int] = {}
    present_canonical: set[str] = set()
    for vendor_key, canonical in _CLAUDE_TOKEN_MAP.items():
        if vendor_key in usage_raw:
            coerced = _coerce_int(usage_raw[vendor_key])
            if coerced is None:
                continue
            present_canonical.add(canonical)
            tokens[canonical] = tokens.get(canonical, 0) + coerced

    if not tokens:
        return None, model, False

    expected = {
        "input_tokens",
        "output_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
    }
    fully_populated = expected.issubset(present_canonical)
    return tokens, model, fully_populated


def _extract_codex(record: dict[str, Any]) -> tuple[dict[str, int] | None, str | None, bool]:
    """Return ``(tokens, model, fully_populated)`` for a Codex rollout record."""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None, None, False
    info = payload.get("info")
    if not isinstance(info, dict):
        return None, None, False

    model_raw = info.get("model")
    model = model_raw if isinstance(model_raw, str) and model_raw else None

    tokens_raw = info.get("tokens")
    if not isinstance(tokens_raw, dict):
        return None, model, False

    tokens: dict[str, int] = {}
    present_canonical: set[str] = set()
    for vendor_key, canonical in _CODEX_TOKEN_MAP.items():
        if vendor_key in tokens_raw:
            coerced = _coerce_int(tokens_raw[vendor_key])
            if coerced is None:
                continue
            present_canonical.add(canonical)
            tokens[canonical] = tokens.get(canonical, 0) + coerced

    if not tokens:
        return None, model, False

    expected = {
        "input_tokens",
        "output_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
        "reasoning_tokens",
    }
    fully_populated = expected.issubset(present_canonical)
    return tokens, model, fully_populated


_EXTRACTORS = {
    "claude-session": _extract_claude,
    "codex-rollout": _extract_codex,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_usage(source: Source, usage_records: list[dict[str, Any]]) -> UsageSummary:
    """Aggregate per-record token usage into a single ``UsageSummary``.

    ``usage_records`` must be the full list of *billable* raw vendor lines as
    captured by the importer — not normalized events, and not pre-filtered to
    lines that already contain usage. See spec §4.3.
    """
    if source not in _EXTRACTORS:  # pragma: no cover - defensive
        raise ValueError(f"unknown source: {source!r}")
    extractor = _EXTRACTORS[source]

    total = len(usage_records)
    if total == 0:
        return UsageSummary(source=source, confidence="unknown")

    totals: dict[str, int] = {k: 0 for k in _TOKEN_FIELDS}
    per_model: dict[str, dict[str, int]] = {}
    model_order: list[str] = []
    events_with_usage = 0
    events_missing_usage = 0
    model_field_missing_events = 0
    any_partial = False  # True if any record had usage but was not fully populated

    for record in usage_records:
        if not isinstance(record, dict):
            events_missing_usage += 1
            continue
        tokens, model, fully_populated = extractor(record)

        if model is None:
            model_field_missing_events += 1

        if tokens is None:
            events_missing_usage += 1
            continue

        events_with_usage += 1
        if not fully_populated:
            any_partial = True

        for key, value in tokens.items():
            totals[key] += value

        if model is not None:
            bucket = per_model.get(model)
            if bucket is None:
                bucket = {k: 0 for k in _TOKEN_FIELDS}
                per_model[model] = bucket
                model_order.append(model)
            for key, value in tokens.items():
                bucket[key] += value

    # Confidence rules — apply in order per spec §4.3.
    if events_with_usage == 0:
        confidence: Confidence = "unknown"
    elif events_with_usage * 2 < total:
        # Strictly fewer than 50 %.
        confidence = "unknown"
    elif any_partial or events_missing_usage > 0:
        confidence = "estimated"
    else:
        confidence = "exact"

    model_breakdown = tuple(
        ModelUsage(model=name, **per_model[name]) for name in model_order
    )

    return UsageSummary(
        source=source,
        input_tokens=totals["input_tokens"],
        output_tokens=totals["output_tokens"],
        cache_creation_tokens=totals["cache_creation_tokens"],
        cache_read_tokens=totals["cache_read_tokens"],
        reasoning_tokens=totals["reasoning_tokens"],
        model_breakdown=model_breakdown,
        confidence=confidence,
        events_with_usage=events_with_usage,
        events_missing_usage=events_missing_usage,
        model_field_missing_events=model_field_missing_events,
    )
