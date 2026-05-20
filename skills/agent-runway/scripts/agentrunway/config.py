from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ModelAssignment


@dataclass(frozen=True)
class ModelProfile:
    orchestrator: ModelAssignment
    workers: dict[str, ModelAssignment] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectiveConfig:
    default_profile: str
    profiles: dict[str, ModelProfile]
    runtime_caps: dict[str, int]
    agentlens_namespace_prefix: str = "agentrunway"
    apply_to_source: bool = False


class BuiltinProfiles:
    @staticmethod
    def default() -> dict[str, ModelProfile]:
        return {
            "codex-default": ModelProfile(
                orchestrator=ModelAssignment("codex", "gpt-5.5", "highest", "xhigh"),
                workers={"default": ModelAssignment("codex", "gpt-5.5", "high", "high")},
            ),
            "claude-default": ModelProfile(
                orchestrator=ModelAssignment("claude", "opus", "high", "high"),
                workers={"default": ModelAssignment("claude", "opus", "high", "high")},
            ),
            "same-host": ModelProfile(
                orchestrator=ModelAssignment("host", "default", "medium", "default"),
                workers={"default": ModelAssignment("host", "default", "medium", "default")},
            ),
        }


def _parse_simple_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except Exception:
        if text.strip().startswith("{"):
            return json.loads(text)
        data: dict[str, Any] = {}
        for line in text.splitlines():
            if ":" in line and not line.startswith(" "):
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip() or {}
        return data
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


def resolve_reasoning(runtime: str, requested: str) -> tuple[str, str]:
    portable = "highest" if requested == "xhigh" else requested
    if portable not in {"lowest", "low", "medium", "high", "highest"}:
        raise ValueError(f"unsupported reasoning_effort: {requested}")
    table = {
        "codex": {"lowest": "low", "low": "medium", "medium": "medium", "high": "high", "highest": "xhigh"},
        "claude": {"lowest": "low", "low": "low", "medium": "medium", "high": "high", "highest": "high"},
        "local": {"lowest": "n/a", "low": "n/a", "medium": "n/a", "high": "n/a", "highest": "n/a"},
        "host": {"lowest": "default", "low": "default", "medium": "default", "high": "default", "highest": "default"},
    }
    runtime_map = table.get(runtime)
    if runtime_map is None:
        raise ValueError(f"unsupported runtime for reasoning resolution: {runtime}")
    return portable, runtime_map[portable]


def load_effective_config(repo_root: Path, invocation: dict[str, Any]) -> EffectiveConfig:
    local = _parse_simple_yaml(repo_root / "agentrunway.yaml")
    global_cfg = _parse_simple_yaml(Path.home() / ".agentrunway" / "global.yaml")
    default_profile = str(invocation.get("model_profile") or local.get("default_profile") or "codex-default")
    caps_raw = global_cfg.get("runtime_caps") if isinstance(global_cfg.get("runtime_caps"), dict) else {}
    runtime_caps = {
        "claude": int(caps_raw.get("claude", {}).get("max_concurrent_workers", 6)) if isinstance(caps_raw.get("claude"), dict) else 6,
        "codex": int(caps_raw.get("codex", {}).get("max_concurrent_workers", 8)) if isinstance(caps_raw.get("codex"), dict) else 8,
    }
    agentlens = local.get("agentlens") if isinstance(local.get("agentlens"), dict) else {}
    return EffectiveConfig(
        default_profile=default_profile,
        profiles=BuiltinProfiles.default(),
        runtime_caps=runtime_caps,
        agentlens_namespace_prefix=str(agentlens.get("namespace_prefix", "agentrunway")),
        apply_to_source=bool(invocation.get("apply_to_source", False)),
    )
