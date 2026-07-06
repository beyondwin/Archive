#!/usr/bin/env python3
"""
initcmd.py — CME v3.0 deterministic argument parser, run-id deriver, and echo line.

Implements the three-pass parser from Phase -1.0:
  Pass 1: collect key=value pairs
  Pass 2: multi-plan auto-detection with gap and missing-spec halts
  Pass 3: natural-language keyword lexicon (with Korean particle stripping)

Reference: skills/kws-claude-multi-agent-executor/references/phases/phase-minus-1-args-and-spawn.md
"""

import os
import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConflictHalt(Exception):
    """Raised on: explicit-vs-NL conflict, multi-plan index gap, or missing specN."""
    pass


# ---------------------------------------------------------------------------
# Pass 1 helpers — recognized key=value pairs
# ---------------------------------------------------------------------------

# Keys that are recognized in Pass 1 but validated as simple string/bool.
# plan/spec/planN/specN are handled separately in Pass 2.
_PASS1_SIMPLE_KEYS = {
    "implementer_model",
    "parallel",
    "risk",
    "docs_scope",
    "mode",
    "detach",
    "transport_default",
    # budget / context keys deferred; accept them silently to avoid halt on valid
    # invocations that include legacy args.
    "budget",
    "budget_action",
    "context_budget",
    "context_threshold",
    "manifest_fallback",
    "manifest",
}


def _is_plan_key(key: str):
    """Return True if key matches ^plan\\d*$."""
    return bool(re.fullmatch(r"plan\d*", key))


def _is_spec_key(key: str):
    """Return True if key matches ^spec\\d*$."""
    return bool(re.fullmatch(r"spec\d*", key))


def _plan_index(key: str) -> int:
    """Map plan key to 0-based index: 'plan'→0, 'plan2'→1, 'plan3'→2, ..."""
    m = re.fullmatch(r"plan(\d*)", key)
    if m is None:
        raise ValueError(f"Not a plan key: {key!r}")
    suffix = m.group(1)
    return 0 if suffix == "" else int(suffix) - 1


def _spec_index(key: str) -> int:
    """Map spec key to 0-based index: 'spec'→0, 'spec2'→1, ..."""
    m = re.fullmatch(r"spec(\d*)", key)
    if m is None:
        raise ValueError(f"Not a spec key: {key!r}")
    suffix = m.group(1)
    return 0 if suffix == "" else int(suffix) - 1


def _index_to_plan_name(i: int) -> str:
    """Map 0-based index to plan key name: 0→'plan', 1→'plan2', ..."""
    return "plan" if i == 0 else f"plan{i + 1}"


def _index_to_spec_name(i: int) -> str:
    """Map 0-based index to spec key name: 0→'spec', 1→'spec2', ..."""
    return "spec" if i == 0 else f"spec{i + 1}"


# ---------------------------------------------------------------------------
# Pass 3 helpers — NL lexicon + Korean particle stripping
# ---------------------------------------------------------------------------

# Korean grammatical particles in priority order (longest first).
_KO_PARTICLES = [
    "적으로", "에서", "으로", "적인", "적", "로", "을", "를", "이", "가", "의", "에",
]

# NL lexicon: stripped+lowercased token → (key, value)
_NL_LEXICON = {
    "opus":      ("implementer_model", "opus"),
    "오푸스":    ("implementer_model", "opus"),
    "sonnet":    ("implementer_model", "sonnet"),
    "소넷":      ("implementer_model", "sonnet"),
    "순차":      ("parallel", False),
    "sequential": ("parallel", False),
    "직렬":      ("parallel", False),
    "시리얼":    ("parallel", False),
    "대화형":    ("mode", "interactive"),
    "interactive": ("mode", "interactive"),
}


def _strip_particle(token: str) -> str:
    """Strip the longest matching Korean trailing particle from a token."""
    for particle in _KO_PARTICLES:
        if token.endswith(particle) and len(token) > len(particle):
            return token[: -len(particle)]
    return token


def _nl_match(token: str):
    """
    Return (key, value) if token matches the NL lexicon after exclusion + particle
    stripping, else None.

    Exclusion: tokens containing '/', '.', '=', or backtick are skipped.
    """
    if any(ch in token for ch in ("/", ".", "=", "`")):
        return None
    stripped = _strip_particle(token)
    lowered = stripped.lower()
    return _NL_LEXICON.get(lowered)


# ---------------------------------------------------------------------------
# Core: parse_args
# ---------------------------------------------------------------------------

def parse_args(raw: str) -> dict:
    """
    Parse a CME invocation string and return a config dict.

    Keys in returned dict:
        plans: list[{"plan": str, "spec": str}]
        implementer_model: "sonnet" | "opus"
        parallel: bool
        risk: None | "low" | "mid" | "high"
        docs_scope: None | list[str]
        mode: str  (default "kernel"; may be "interactive")
        detach: bool
        transport_default: str  (default "p")
        sources: dict[key -> "explicit" | "nl" | "default"]
    """
    tokens = raw.split()

    # ------------------------------------------------------------------ Pass 1
    kv_explicit: dict = {}    # key -> value for recognized key=value pairs
    plan_kv: dict = {}        # plan-index (int) -> path
    spec_kv: dict = {}        # spec-index (int) -> path
    free_tokens: list = []    # tokens not consumed by Pass 1

    for token in tokens:
        if "=" in token:
            key, _, value = token.partition("=")
            if _is_plan_key(key):
                idx = _plan_index(key)
                plan_kv[idx] = value
            elif _is_spec_key(key):
                idx = _spec_index(key)
                spec_kv[idx] = value
            elif key in _PASS1_SIMPLE_KEYS:
                kv_explicit[key] = value
            else:
                raise ConflictHalt(f"Unknown argument: {key}={value}")
        else:
            free_tokens.append(token)

    # ------------------------------------------------------------------ Pass 2
    # Require plan= (index 0).
    if 0 not in plan_kv:
        raise ConflictHalt("Missing required arg: plan=<path>")

    # manifest= is mutually exclusive with planN=/specN=.
    if "manifest" in kv_explicit and (len(plan_kv) > 0 or len(spec_kv) > 0):
        raise ConflictHalt("manifest= is mutually exclusive with planN=/specN= args.")

    # Detect gaps.
    if plan_kv:
        max_idx = max(plan_kv.keys())
        for i in range(max_idx + 1):
            if i not in plan_kv:
                missing_name = _index_to_plan_name(i)
                provided = sorted(plan_kv.keys())
                provided_names = [_index_to_plan_name(k) for k in provided]
                raise ConflictHalt(
                    f"Plan index gap: expected {missing_name}= but only "
                    f"{', '.join(provided_names)} provided. "
                    f"Renumber consecutively or fill the gap."
                )

    # For each planN= ensure specN= is present.
    for idx in sorted(plan_kv.keys()):
        if idx not in spec_kv:
            plan_name = _index_to_plan_name(idx)
            spec_name = _index_to_spec_name(idx)
            raise ConflictHalt(f"{plan_name}= present but {spec_name}= missing")

    # Build ordered plans list.
    plans = [
        {"plan": plan_kv[i], "spec": spec_kv[i]}
        for i in sorted(plan_kv.keys())
    ]

    # ------------------------------------------------------------------ Pass 3
    # Process free tokens against NL lexicon.
    # Collect NL matches; detect NL-vs-NL conflicts within same key.
    nl_matches: dict = {}   # key -> (value, original_token)

    for token in free_tokens:
        match = _nl_match(token)
        if match is None:
            continue
        nl_key, nl_value = match
        if nl_key in nl_matches:
            prev_value, prev_token = nl_matches[nl_key]
            if prev_value != nl_value:
                raise ConflictHalt(
                    f"Natural-language conflict: '{prev_token}' (→ {prev_value}) and "
                    f"'{token}' (→ {nl_value}) both target {nl_key}. "
                    f"Disambiguate explicitly."
                )
            # Same value; no-op (duplicate mention).
        else:
            nl_matches[nl_key] = (nl_value, token)

    # Apply NL matches; check for conflicts with explicit values.
    for nl_key, (nl_value, nl_token) in nl_matches.items():
        if nl_key in kv_explicit:
            explicit_val = kv_explicit[nl_key]
            # Normalize the explicit value for comparison.
            normalized_explicit = _normalize_value(nl_key, explicit_val)
            if normalized_explicit != nl_value:
                raise ConflictHalt(
                    f"Argument conflict: explicit {nl_key}={explicit_val} contradicts "
                    f"natural-language '{nl_token}' (→ {nl_value}). Remove one or align them."
                )
            # Agree → no-op; stays explicit in sources.
        else:
            kv_explicit[nl_key] = _denormalize_value(nl_key, nl_value)

    # ------------------------------------------------------------------ Resolve config
    sources: dict = {}

    # Track the original explicit keys (before NL merge).
    # We need to distinguish "was in Pass 1" from "was added by NL".
    # Re-parse Pass 1 only to get original explicit set.
    _original_explicit_keys: set = set()
    for token in tokens:
        if "=" in token:
            key, _, _ = token.partition("=")
            if key in _PASS1_SIMPLE_KEYS:
                _original_explicit_keys.add(key)

    # Now build config with correct sources.
    def _resolve_with_source(key, default):
        if key in _original_explicit_keys:
            sources[key] = "explicit"
            return kv_explicit[key]
        elif key in nl_matches:
            nl_val, _ = nl_matches[key]
            sources[key] = "nl"
            return _denormalize_value(key, nl_val)
        else:
            sources[key] = "default"
            return default

    # implementer_model
    implementer_model_raw = _resolve_with_source("implementer_model", "sonnet")
    implementer_model = implementer_model_raw.lower() if isinstance(implementer_model_raw, str) else implementer_model_raw
    if implementer_model not in ("sonnet", "opus"):
        raise ConflictHalt(f"Unknown implementer_model={implementer_model_raw}. Allowed: opus, sonnet.")

    # parallel
    parallel_raw = _resolve_with_source("parallel", True)
    if isinstance(parallel_raw, bool):
        parallel = parallel_raw
    else:
        s = parallel_raw.lower()
        if s in ("true", "on", "yes", "1"):
            parallel = True
        elif s in ("false", "off", "no", "0"):
            parallel = False
        else:
            raise ConflictHalt(f"Unknown parallel={parallel_raw}. Allowed: true, false, on, off.")

    # risk
    risk_raw = _resolve_with_source("risk", None)
    if risk_raw is not None:
        risk_raw = risk_raw.lower() if isinstance(risk_raw, str) else risk_raw
        if risk_raw not in ("low", "mid", "high"):
            raise ConflictHalt(f"Unknown risk={risk_raw}. Allowed: low, mid, high.")
    risk = risk_raw

    # docs_scope
    docs_scope_raw = _resolve_with_source("docs_scope", None)
    if docs_scope_raw is not None and isinstance(docs_scope_raw, str):
        docs_scope = [s.strip() for s in docs_scope_raw.split(",") if s.strip()]
    else:
        docs_scope = docs_scope_raw

    # mode
    mode_raw = _resolve_with_source("mode", "kernel")
    mode = mode_raw

    # detach
    detach_raw = _resolve_with_source("detach", False)
    if isinstance(detach_raw, bool):
        detach = detach_raw
    else:
        s = str(detach_raw).lower()
        detach = s in ("true", "on", "yes", "1")
    sources["detach"] = sources.get("detach", "default")

    # transport_default — constant default, no NL rule
    transport_default = kv_explicit.get("transport_default", "p")
    sources["transport_default"] = "explicit" if "transport_default" in _original_explicit_keys else "default"

    return {
        "plans": plans,
        "implementer_model": implementer_model,
        "parallel": parallel,
        "risk": risk,
        "docs_scope": docs_scope,
        "mode": mode,
        "detach": detach,
        "transport_default": transport_default,
        "sources": sources,
    }


def _normalize_value(key: str, value):
    """Normalize an explicit string value to the same type as the NL value for comparison."""
    if key == "parallel":
        if isinstance(value, bool):
            return value
        s = str(value).lower()
        if s in ("true", "on", "yes", "1"):
            return True
        if s in ("false", "off", "no", "0"):
            return False
        return value
    if key == "implementer_model":
        return str(value).lower() if isinstance(value, str) else value
    return value


def _denormalize_value(key: str, value):
    """Convert normalized NL value back to the storage type."""
    # NL values are already the correct Python types (str/bool/...).
    return value


# ---------------------------------------------------------------------------
# derive_run_id
# ---------------------------------------------------------------------------

def derive_run_id(plan_path: str, now: datetime) -> str:
    """
    Derive a run ID from the plan file path and timestamp.

    Format: <plan-slug>-<YYYYMMDD-HHMMSS>

    Slug derivation:
      1. Take basename (strip directory).
      2. Strip file extension.
      3. Lowercase.
      4. Replace non-alphanumeric characters with '-'.
      5. Collapse consecutive '-' into one.
      6. Strip leading/trailing '-'.
    """
    basename = os.path.basename(plan_path)
    name, _ = os.path.splitext(basename)
    lower = name.lower()
    dashed = re.sub(r"[^a-z0-9]+", "-", lower)
    collapsed = re.sub(r"-{2,}", "-", dashed)
    slug = collapsed.strip("-")
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    return f"{slug}-{timestamp}"


# ---------------------------------------------------------------------------
# echo_line
# ---------------------------------------------------------------------------

def echo_line(config: dict) -> str:
    """
    Return a one-line summary of the parsed config for user confirmation.

    Format:
      Parsed: <N> plan(s) [<slug0>→<slug1>→...], implementer_model=<val> [from <src>],
              parallel=<val> [from <src>], transport=<val> [from <src>],
              mode=<val> [from <src>], risk=<val or "none"> [from <src>]
    """
    plans = config["plans"]
    n = len(plans)
    slugs = [_plan_slug(p["plan"]) for p in plans]
    plan_part = f"{n} plan(s) [{' → '.join(slugs)}]"

    sources = config.get("sources", {})

    def _src(key):
        return sources.get(key, "default")

    model = config["implementer_model"]
    parallel = config["parallel"]
    transport = config["transport_default"]
    mode = config["mode"]
    risk = config["risk"]

    parts = [
        f"Parsed: {plan_part}",
        f"implementer_model={model} [from {_src('implementer_model')}]",
        f"parallel={parallel} [from {_src('parallel')}]",
        f"transport={transport} [from {_src('transport_default')}]",
        f"mode={mode} [from {_src('mode')}]",
        f"risk={risk if risk is not None else 'none'} [from {_src('risk')}]",
    ]
    return ", ".join(parts)


def _plan_slug(plan_path: str) -> str:
    """Return just the slug portion from a plan path (no timestamp)."""
    basename = os.path.basename(plan_path)
    name, _ = os.path.splitext(basename)
    lower = name.lower()
    dashed = re.sub(r"[^a-z0-9]+", "-", lower)
    collapsed = re.sub(r"-{2,}", "-", dashed)
    return collapsed.strip("-")
