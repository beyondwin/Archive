from __future__ import annotations

from typing import Any


class CheckpointScheduler:
    def next_wave(self, *, projection: Any) -> list[dict[str, Any]]:
        safe_wave = getattr(projection, "safe_wave", None)
        if safe_wave is not None:
            return list(safe_wave)
        if hasattr(projection, "to_dict"):
            payload = projection.to_dict()
        else:
            payload = dict(projection)
        return list(payload.get("safe_wave") or [])
