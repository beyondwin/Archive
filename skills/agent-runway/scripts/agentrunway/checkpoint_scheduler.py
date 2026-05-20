from __future__ import annotations

from typing import Any


class CheckpointScheduler:
    def _payload(self, *, projection: Any) -> dict[str, Any]:
        if hasattr(projection, "to_dict"):
            return projection.to_dict()
        return dict(projection)

    def next_wave(self, *, projection: Any) -> list[dict[str, Any]]:
        safe_wave = getattr(projection, "safe_wave", None)
        if safe_wave is not None:
            return list(safe_wave)
        return list(self._payload(projection=projection).get("safe_wave") or [])

    def diagnostics(self, *, projection: Any) -> dict[str, Any]:
        payload = self._payload(projection=projection)
        return {
            "projection_status": payload.get("projection_status"),
            "safe_wave": payload.get("safe_wave") or [],
            "withheld_tasks": payload.get("withheld_tasks") or [],
            "stale_activities": payload.get("stale_activities") or [],
            "task_classes": {
                str(item["task_id"]): item
                for item in payload.get("task_classes") or []
                if isinstance(item, dict) and item.get("task_id")
            },
        }
