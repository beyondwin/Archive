#!/usr/bin/env python3
"""Parse kws-codex-plan-executor key/value args and natural-language hints."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path


DEFAULTS = {
    "mode": "interactive",
    "subagents": "auto",
    "context_mode": "auto",
    "context_budget": 60000,
    "context_threshold": 0.70,
    "manifest_fallback": "full_spec_on_blocker",
    "parallel": "auto",
}
RECOGNIZED_KEYS = {
    "plan",
    "spec",
    "docs",
    "workspace",
    "resume",
    "mode",
    "subagents",
    "headless_sandbox",
    "context_mode",
    "context_budget",
    "context_threshold",
    "manifest_fallback",
    "parallel",
    "implementer_model",
}
CHOICES = {
    "mode": {"interactive", "headless", "prompt", "handoff"},
    "subagents": {"auto", "on", "off"},
    "headless_sandbox": {"workspace-write", "read-only"},
    "context_mode": {"auto", "sliced", "full"},
    "manifest_fallback": {"full_spec_on_blocker", "halt_on_blocker"},
    "parallel": {"auto", "off"},
    "implementer_model": {"opus"},
}
NL_HINTS = {
    "대화형": ("mode", "interactive"),
    "interactive": ("mode", "interactive"),
    "헤드리스": ("mode", "headless"),
    "headless": ("mode", "headless"),
    "프롬프트": ("mode", "prompt"),
    "prompt": ("mode", "prompt"),
    "핸드오프": ("mode", "handoff"),
    "handoff": ("mode", "handoff"),
    "병렬": ("subagents", "on"),
    "parallel": ("subagents", "on"),
    "서브에이전트": ("subagents", "on"),
    "subagents": ("subagents", "on"),
    "로컬": ("subagents", "off"),
    "local": ("subagents", "off"),
    "순차": ("parallel", "off"),
    "sequential": ("parallel", "off"),
    "직렬": ("parallel", "off"),
    "슬라이스": ("context_mode", "sliced"),
    "sliced": ("context_mode", "sliced"),
    "전체": ("context_mode", "full"),
    "full": ("context_mode", "full"),
    "오푸스": ("implementer_model", "opus"),
    "opus": ("implementer_model", "opus"),
}
KOREAN_PARTICLES = ("에서", "으로", "에게", "부터", "까지", "로", "은", "는", "이", "가", "을", "를", "에", "와", "과", "도", "만")


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_hint(token: str) -> str | None:
    raw = token.strip().strip(".,;:!?()[]{}\"'")
    if not raw:
        return None
    lowered = raw.lower()
    if raw in NL_HINTS:
        return raw
    if lowered in NL_HINTS:
        return lowered
    for particle in KOREAN_PARTICLES:
        if raw.endswith(particle) and len(raw) > len(particle):
            stripped = raw[: -len(particle)]
            if stripped in NL_HINTS:
                return stripped
            lowered_stripped = stripped.lower()
            if lowered_stripped in NL_HINTS:
                return lowered_stripped
    return None


def coerce_value(key: str, value: str) -> object:
    if key == "context_budget":
        try:
            parsed = int(value)
        except ValueError:
            die("context_budget must be a positive integer")
        if parsed <= 0:
            die("context_budget must be a positive integer")
        return parsed
    if key == "context_threshold":
        try:
            parsed_float = float(value)
        except ValueError:
            die("context_threshold must be a float")
        if parsed_float < 0.05 or parsed_float > 0.95:
            die("context_threshold must be in [0.05,0.95]")
        return parsed_float
    if key in CHOICES and value not in CHOICES[key]:
        die(f"{key} must be one of {sorted(CHOICES[key])}")
    return value


def parse(args_text: str) -> dict:
    try:
        tokens = shlex.split(args_text)
    except ValueError as exc:
        die(f"could not parse args: {exc}")

    values: dict[str, object] = dict(DEFAULTS)
    sources: dict[str, str] = {key: "default" for key in DEFAULTS}
    explicit: dict[str, object] = {}
    nl: dict[str, tuple[object, str]] = {}

    for token in tokens:
        if "=" in token:
            key, raw_value = token.split("=", 1)
            if key not in RECOGNIZED_KEYS:
                die(f"unknown argument key: {key}")
            value = coerce_value(key, raw_value)
            if key in explicit and explicit[key] != value:
                die(f"conflict for {key}: {explicit[key]} vs {value}")
            explicit[key] = value
            continue

        hint = normalize_hint(token)
        if hint is None:
            continue
        key, raw_value = NL_HINTS[hint]
        value = coerce_value(key, str(raw_value))
        source = f"NL '{token}'"
        if key in nl and nl[key][0] != value:
            die(f"conflict for {key}: {nl[key][0]} vs {value}")
        nl[key] = (value, source)

    for key, value in explicit.items():
        if key in nl and nl[key][0] != value:
            die(f"conflict for {key}: explicit {value} vs {nl[key][1]} {nl[key][0]}")
        values[key] = value
        sources[key] = f"{key}=value"

    for key, (value, source) in nl.items():
        if key not in explicit:
            values[key] = value
            sources[key] = source

    plan_value = values.get("plan")
    plan_count = 1 if isinstance(plan_value, str) and plan_value.strip() else 0
    plan_slug = Path(plan_value).stem if plan_count else "-"
    echo = (
        f"Parsed: {plan_count} plan [{plan_slug}], "
        f"mode={values['mode']} [from {sources['mode']}], "
        f"subagents={values['subagents']} [from {sources['subagents']}], "
        f"context_mode={values['context_mode']} [from {sources['context_mode']}], "
        f"context_budget={values['context_budget']}, "
        f"manifest_fallback={values['manifest_fallback']}, "
        f"parallel={values['parallel']}."
    )
    return {"values": values, "sources": sources, "echo": echo}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--args", required=True, help="Invocation arguments as a single string")
    args = parser.parse_args()
    print(json.dumps(parse(args.args), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
