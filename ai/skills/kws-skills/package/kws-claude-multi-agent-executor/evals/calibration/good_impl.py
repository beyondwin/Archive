"""parse_duration — full spec implementation.

Single-pass regex tokenizer; lowercase-only units; rejects all 10 invalid forms
listed in spec.md of fixture 08.
"""

import re

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_SEGMENT_RE = re.compile(r"([0-9]+)([a-zA-Z]+)")


def parse_duration(s: str) -> int:
    if not isinstance(s, str):
        raise ValueError(f"expected str, got {type(s).__name__}")

    stripped = s.strip()
    if not stripped:
        raise ValueError("empty duration")

    if any(ch.isspace() for ch in stripped):
        raise ValueError(f"internal whitespace not allowed: {s!r}")

    if "." in stripped or "-" in stripped:
        raise ValueError(f"decimals and negatives not allowed: {s!r}")

    pos = 0
    seen_units: set[str] = set()
    total = 0
    while pos < len(stripped):
        m = _SEGMENT_RE.match(stripped, pos)
        if m is None or m.start() != pos:
            raise ValueError(f"invalid segment at position {pos}: {stripped[pos:]!r}")
        value_str, unit = m.group(1), m.group(2)

        if unit != unit.lower() or len(unit) != 1:
            raise ValueError(f"unknown unit {unit!r} (only s/m/h/d allowed)")
        if unit not in _UNIT_SECONDS:
            raise ValueError(f"unknown unit {unit!r} (only s/m/h/d allowed)")
        if unit in seen_units:
            raise ValueError(f"repeated unit {unit!r}")
        seen_units.add(unit)

        total += int(value_str) * _UNIT_SECONDS[unit]
        pos = m.end()

    if pos != len(stripped):
        raise ValueError(f"trailing characters at position {pos}: {stripped[pos:]!r}")

    return total
