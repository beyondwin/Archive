from __future__ import annotations

from pathlib import Path
from typing import Any


def has_substantive_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return value is True


def path_is_under(path: str, parent: str) -> bool:
    try:
        Path(path).resolve(strict=False).relative_to(Path(parent).resolve(strict=False))
        return True
    except ValueError:
        return False
