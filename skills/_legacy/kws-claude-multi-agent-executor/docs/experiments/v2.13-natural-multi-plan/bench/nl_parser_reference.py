#!/usr/bin/env python3
"""Reference implementation of v2.13 skill-arg parser.

The orchestrator's prose interpretation in SKILL.md Phase -1.0 MUST produce
the same parsed dict as this script. Use this as the authoritative spec for
the lexicon + particle stripping rules; SKILL.md prose is the human-readable
mirror.

Usage:
    python3 nl_parser_reference.py "plan=A.md spec=A.spec 오푸스로 순차"
    # Prints JSON of the parsed args.

The tested cases live in test_nl_parser.py alongside this file.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

# Particle suffixes, longest-first (matters for greedy stripping).
KOREAN_PARTICLES = [
    "적으로", "에서", "으로", "적인",
    "적", "로", "을", "를", "이", "가", "의", "에",
]

# Stripped tokens → canonical args. Tokens are lowercased before lookup.
LEXICON: dict[str, tuple[str, str]] = {
    # token  →  (key, value)
    "opus": ("implementer_model", "opus"),
    "오푸스": ("implementer_model", "opus"),
    "sonnet": ("implementer_model", "sonnet"),
    "소넷": ("implementer_model", "sonnet"),
    "순차": ("parallel", "off"),
    "sequential": ("parallel", "off"),
    "직렬": ("parallel", "off"),
    "시리얼": ("parallel", "off"),
    "대화형": ("mode", "interactive"),
    "interactive": ("mode", "interactive"),
}

RECOGNIZED_KEYS = {
    "plan", "spec", "implementer_model", "parallel", "risk", "docs_scope",
    "mode", "manifest",
}

KEY_RE = re.compile(r"^(?P<key>[a-z_][a-z_0-9]*)=(?P<val>.*)$")
PLANSPEC_RE = re.compile(r"^(?P<base>plan|spec)(?P<n>\d*)$")
EXCLUDE_CHARS = set("/.=`")


def _strip_particle(token: str) -> str:
    """Strip the longest Korean particle suffix once. ASCII unaffected."""
    for p in KOREAN_PARTICLES:
        if token.endswith(p) and len(token) > len(p):
            return token[: -len(p)]
    return token


def _is_path_like(tok: str) -> bool:
    return any(c in EXCLUDE_CHARS for c in tok)


class ParseError(Exception):
    pass


def parse_args(args_str: str) -> dict[str, Any]:
    """Three-pass parser per SKILL.md Phase -1.0.

    Returns a dict:
        {
          "plans": [{"plan": "...", "spec": "..."}, ...],
          "implementer_model": "sonnet" | "opus" | None,
          "parallel": "on" | "off" | None,
          "mode": "headless" | "interactive" | None,
          "risk": "low" | "mid" | "high" | None,
          "docs_scope": "..." | None,
          "sources": {key: "explicit" | "NL '<word>'" | "default"},
          "halts": [<reason1>, ...],   # populated on halt
        }
    """
    result: dict[str, Any] = {
        "plans": [],
        "implementer_model": None,
        "parallel": None,
        "mode": None,
        "risk": None,
        "docs_scope": None,
        "sources": {},
        "halts": [],
    }
    if not args_str.strip():
        result["halts"].append("Missing required arg: plan=<path>")
        return result

    tokens = args_str.split()
    kv: dict[str, str] = {}
    free_tokens: list[str] = []

    # Pass 1: collect key=value
    plan_keys: dict[int, str] = {}
    spec_keys: dict[int, str] = {}
    for tok in tokens:
        m = KEY_RE.match(tok)
        if not m:
            free_tokens.append(tok)
            continue
        key = m.group("key")
        val = m.group("val")
        plan_match = PLANSPEC_RE.match(key)
        if plan_match:
            base = plan_match.group("base")
            n_str = plan_match.group("n")
            if n_str == "":
                idx = 0
            elif n_str == "1":
                # Disallow plan1=/spec1= (ambiguous with plan=/spec= → halt for clarity)
                result["halts"].append(
                    f"Disallowed key '{key}=' — use '{base}=' for index 0; "
                    f"start from {base}2= for additional plans."
                )
                return result
            else:
                idx = int(n_str) - 1
            target = plan_keys if base == "plan" else spec_keys
            if idx in target:
                result["halts"].append(f"Duplicate {base} index {idx}: '{target[idx]}' vs '{val}'")
                return result
            target[idx] = val
            continue
        if key not in RECOGNIZED_KEYS:
            result["halts"].append(f"Unknown argument: {key}={val}")
            return result
        kv[key] = val

    # Pass 2: assemble plan list
    if "manifest" in kv and (plan_keys or spec_keys):
        result["halts"].append("manifest= is mutually exclusive with planN=/specN= args.")
        return result
    if 0 not in plan_keys:
        result["halts"].append("Missing required arg: plan=<path>")
        return result
    max_idx = max(plan_keys.keys())
    for i in range(max_idx + 1):
        if i not in plan_keys:
            shown = "plan" if i == 0 else f"plan{i+1}"
            existing = sorted(
                ("plan" if k == 0 else f"plan{k+1}") for k in plan_keys
            )
            result["halts"].append(
                f"Plan index gap: expected {shown}= but only {', '.join(existing)} provided. "
                "Renumber consecutively or fill the gap."
            )
            return result
        if i not in spec_keys:
            shown_plan = "plan" if i == 0 else f"plan{i+1}"
            shown_spec = "spec" if i == 0 else f"spec{i+1}"
            result["halts"].append(f"{shown_plan}= present but {shown_spec}= missing")
            return result
        result["plans"].append({"plan": plan_keys[i], "spec": spec_keys[i]})

    # Explicit kv: record into result + sources
    if "implementer_model" in kv:
        v = kv["implementer_model"].lower()
        if v not in ("opus", "sonnet"):
            result["halts"].append(f"Unknown implementer_model={kv['implementer_model']}. Allowed: opus, sonnet.")
            return result
        result["implementer_model"] = v
        result["sources"]["implementer_model"] = "explicit"
    if "parallel" in kv:
        v = kv["parallel"].lower()
        result["parallel"] = "off" if v == "off" else "on"
        result["sources"]["parallel"] = "explicit"
    if "mode" in kv:
        result["mode"] = kv["mode"]
        result["sources"]["mode"] = "explicit"
    if "risk" in kv:
        result["risk"] = kv["risk"]
        result["sources"]["risk"] = "explicit"
    if "docs_scope" in kv:
        result["docs_scope"] = kv["docs_scope"]
        result["sources"]["docs_scope"] = "explicit"

    # Pass 3: NL keywords from free_tokens
    nl_hits: dict[str, tuple[str, str]] = {}  # key → (value, original_word)
    for tok in free_tokens:
        if _is_path_like(tok):
            continue
        stripped = _strip_particle(tok).lower()
        if stripped not in LEXICON:
            continue
        key, val = LEXICON[stripped]
        # Conflict between NL hits for same key with diff values
        if key in nl_hits:
            prev_val, prev_word = nl_hits[key]
            if prev_val != val:
                result["halts"].append(
                    f"Natural-language conflict: '{prev_word}' (→ {key}={prev_val}) "
                    f"and '{tok}' (→ {key}={val}) both target {key}. Disambiguate explicitly."
                )
                return result
            # same value, just record (no-op)
            continue
        nl_hits[key] = (val, tok)

    # Apply NL hits — explicit always wins; agreement noted; contradiction halts.
    for key, (val, word) in nl_hits.items():
        if key in result["sources"] and result["sources"][key] == "explicit":
            explicit_val = result[key]
            if explicit_val != val:
                result["halts"].append(
                    f"Argument conflict: explicit {key}={explicit_val} contradicts "
                    f"natural-language '{word}' (→ {key}={val}). Remove one or align them."
                )
                return result
            result["sources"][key] = f"explicit; NL '{word}' agrees"
            continue
        result[key] = val
        result["sources"][key] = f"NL '{word}'"

    # Fill defaults
    if result["implementer_model"] is None:
        result["implementer_model"] = "sonnet"
        result["sources"]["implementer_model"] = "default"
    if result["parallel"] is None:
        result["parallel"] = "on"
        result["sources"]["parallel"] = "default"
    if result["mode"] is None:
        result["mode"] = "headless"
        result["sources"]["mode"] = "default"
    if result["risk"] is None:
        result["sources"]["risk"] = "per-task"

    return result


def _slug(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    if base.endswith(".md"):
        base = base[:-3]
    # Strip leading date prefix per Phase 0 Step 2: e.g. 2026-05-08-foo → foo
    base = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", base)
    return base.replace("_", "-").lower()


def format_echo(parsed: dict[str, Any]) -> str:
    """Format the one-line echo per SKILL.md Phase -1.0."""
    if parsed["halts"]:
        return "HALT: " + " | ".join(parsed["halts"])
    n = len(parsed["plans"])
    slugs = [_slug(p["plan"]) for p in parsed["plans"]]
    plan_label = f"{n} plan [{slugs[0]}]" if n == 1 else f"{n} plans [{'→'.join(slugs)}]"
    parts = [f"Parsed: {plan_label}"]
    for key in ("implementer_model", "parallel", "mode"):
        src = parsed["sources"].get(key, "default")
        parts.append(f"{key}={parsed[key]} [{src}]")
    risk_src = parsed["sources"].get("risk", "per-task")
    parts.append(f"risk={parsed['risk'] if parsed['risk'] else 'per-task'}")
    return ", ".join(parts) + "."


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: nl_parser_reference.py '<args string>'", file=sys.stderr)
        return 2
    args_str = " ".join(sys.argv[1:])
    parsed = parse_args(args_str)
    print(format_echo(parsed))
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    return 1 if parsed["halts"] else 0


if __name__ == "__main__":
    sys.exit(main())
