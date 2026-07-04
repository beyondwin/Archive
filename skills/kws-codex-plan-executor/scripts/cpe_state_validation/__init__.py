from __future__ import annotations

from typing import Any


def validate(data: dict[str, Any]) -> list[str]:
    from validate_state import validate as legacy_validate

    return legacy_validate(data)
