"""recovery.py — Command-observation classification + root-signature recovery (CME v3.0 T12).

Ported and adapted from skills/kws-codex-plan-executor/scripts/classify_recovery.py.

Public API
----------
classify(command: str, exit_code: int, output_tail: str) -> dict
    Classify a single command failure by pattern-matching the output.
    Returns {"category": <cat>, "evidence": str}.

decide_recovery(state, task_id, observation) -> dict
    Given a command observation dict already carrying a category, look up prior
    attempts in state.recovery_attempts[] and decide the next action.
    Returns {"action": "bootstrap"|"retry"|"escalate"|"implementer_retry",
             "root_signature": str}.

_root_signature(observation: dict) -> str
    Deterministic 16-char hex: sha256(category|command|first_evidence_line)[:16].
    Exported so tests and transitions can call it directly.

Category taxonomy (from references/command-observations.md):
    source_failure         — real test/build failures from source code
    missing_local_env      — ModuleNotFoundError, command not found, etc.
    dependency_bootstrap   — missing node_modules / package install needed
    resource_oom           — OOM kill / heap exhausted
    timeout_or_hang        — timeout / SIGKILL after deadline
    flaky_test             — known-flaky / intermittent
    permission_or_sandbox  — permission denied / sandbox block
    tooling_bug            — tool crash unrelated to source
    unknown                — captured evidence but root cause unclear

Decision logic (adapted from CPE classify_recovery.py):
    ENV family (missing_local_env, dependency_bootstrap, resource_oom,
                timeout_or_hang, permission_or_sandbox, flaky_test,
                tooling_bug, unknown):
        1st signature occurrence → bootstrap / retry (does NOT burn verifier budget)
        2nd+ signature occurrence → escalate (ENV_BLOCKER)
    source_failure:
        → implementer_retry (DOES burn verifier budget, routes to existing FAIL path)
"""

from __future__ import annotations

import hashlib
import re


# ── ENV-family categories (do NOT burn verifier budget on first occurrence) ───

_ENV_FAMILY = frozenset({
    "missing_local_env",
    "dependency_bootstrap",
    "resource_oom",
    "timeout_or_hang",
    "permission_or_sandbox",
    "flaky_test",
    "tooling_bug",
    "unknown",
})


# ── Pattern table for classify() ─────────────────────────────────────────────
# Each entry: (regex_pattern, category, evidence_template).
# First match wins, so ORDER IS LOAD-BEARING:
#
#   1. ENV import errors (ModuleNotFoundError / ImportError) — these are *Error
#      names but they mean "environment isn't set up", so they MUST win before
#      the generic source-exception catch below.
#   2. Source exceptions — explicit assert/FAILED lines plus a generic `\w+Error`
#      catch (AssertionError, MemoryError, KeyError, ...). This wins over the
#      loose env keyword patterns so a real code bug ("AssertionError: memory
#      not freed", "3 files changed") is NOT misrouted to an env category.
#   3. dependency_bootstrap / resource_oom / timeout / permission / tooling —
#      WORD-ANCHORED env signals only. Bare substrings like "memory", "heap",
#      "hang", "killed" are deliberately NOT used: they collide with normal
#      git/pytest output ("3 files changed" contains "hang"; assertions mention
#      "memory") and would invert this module's purpose (skip budget burn +
#      reset on a genuine source failure).

_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # ── 1. ENV import errors — must win before the generic *Error catch ──────
    (re.compile(r"\bModuleNotFoundError\b"),
     "missing_local_env",
     "ModuleNotFoundError in output"),

    (re.compile(r"\bImportError\b"),
     "missing_local_env",
     "ImportError in output"),

    (re.compile(r"command not found", re.IGNORECASE),
     "missing_local_env",
     "command not found in output"),

    (re.compile(r"No such file or directory", re.IGNORECASE),
     "missing_local_env",
     "No such file or directory in output"),

    # ── 2. Source failures — win over loose env keyword patterns below ───────
    # Explicit assertion / test-failure lines.
    (re.compile(r"(\bAssertionError\b|\bFAILED\b|"
                r"\bassert\b.*(==|!=)|raise AssertionError|\bassert False\b)",
                re.IGNORECASE),
     "source_failure",
     "Assertion / test failure in output"),

    # Generic Python source exception: any CamelCase *Error token.
    # ModuleNotFoundError/ImportError already handled above, so anything left
    # (MemoryError, KeyError, RecursionError, ZeroDivisionError, IndexError,
    # ValueError, ...) is a source bug, not an env problem.
    (re.compile(r"\b\w+Error\b"),
     "source_failure",
     "Python source exception in output"),

    # ── 3. dependency_bootstrap — package manager / install hints ────────────
    (re.compile(r"node_modules", re.IGNORECASE),
     "dependency_bootstrap",
     "node_modules reference in output — run npm/yarn install"),

    (re.compile(r"run (npm|yarn|pnpm|pip|poetry|bun) install", re.IGNORECASE),
     "dependency_bootstrap",
     "install-hint pattern in output"),

    # ── resource_oom — specific OOM signals only (no bare memory/heap/killed) ─
    (re.compile(r"\b(out of memory|oom[- ]?kill(?:er|ed)?|OOM)\b", re.IGNORECASE),
     "resource_oom",
     "OOM signal in output"),

    (re.compile(r"Cannot allocate memory|JavaScript heap out of memory",
                re.IGNORECASE),
     "resource_oom",
     "Memory-exhaustion signal in output"),

    # ── timeout_or_hang — word-anchored timeout signals (no bare hang/hung) ───
    (re.compile(r"\b(timed? ?out|timeout|SIGKILL|deadline exceeded)\b",
                re.IGNORECASE),
     "timeout_or_hang",
     "Timeout signal in output"),

    # ── permission_or_sandbox ────────────────────────────────────────────────
    (re.compile(r"(permission denied|Operation not permitted|sandbox|"
                r"\bEPERM\b|\bEACCES\b)",
                re.IGNORECASE),
     "permission_or_sandbox",
     "Permission/sandbox block in output"),

    # ── tooling_bug — tool internal errors / crashes ─────────────────────────
    (re.compile(r"(internal error|segmentation fault|core dumped|\bSIGSEGV\b)",
                re.IGNORECASE),
     "tooling_bug",
     "Tooling internal error / crash in output"),
]


def classify(command: str, exit_code: int, output_tail: str) -> dict:
    """Classify a single command failure by pattern-matching *output_tail*.

    Returns::

        {"category": str, "evidence": str}

    *exit_code* is accepted for future use; current logic is output-driven.
    Exit code 0 with empty output → category ``unknown``.
    """
    for pattern, category, evidence_template in _PATTERNS:
        match = pattern.search(output_tail)
        if match:
            return {
                "category": category,
                "evidence": f"{evidence_template} (matched: {match.group(0)!r})",
            }

    # Fallback
    if exit_code != 0:
        return {
            "category": "unknown",
            "evidence": f"Non-zero exit {exit_code} with no recognized error pattern",
        }
    return {
        "category": "unknown",
        "evidence": "Exit 0 with no recognized output pattern",
    }


def _root_signature(observation: dict) -> str:
    """Deterministic 16-char hex signature from category + command + first evidence line.

    Formula: sha256(category|command|first_evidence_line)[:16]
    Exported so tests and transitions can use it directly.
    """
    category = str(observation.get("category", "unknown")).strip()
    command = str(observation.get("command", "")).strip()
    evidence = str(observation.get("evidence", "")).strip()
    first_evidence_line = evidence.splitlines()[0] if evidence else ""
    raw = "|".join([category, command, first_evidence_line])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _attempts_for(state: dict, signature: str) -> int:
    """Count prior attempts in state.recovery_attempts[] with the given signature."""
    attempts = state.get("recovery_attempts", [])
    if not isinstance(attempts, list):
        return 0
    return sum(
        1
        for item in attempts
        if isinstance(item, dict) and item.get("root_signature") == signature
    )


def decide_recovery(state: dict, task_id: str, observation: dict) -> dict:
    """Decide recovery action for a failed command observation.

    *observation* must carry at least ``command``, ``category``, and ``evidence``.
    Looks up prior attempts (via root_signature) in ``state.recovery_attempts[]``.

    Returns::

        {"action": "bootstrap"|"retry"|"escalate"|"implementer_retry",
         "root_signature": str}

    Decision rules
    --------------
    - source_failure → implementer_retry (burns verifier budget; existing FAIL path)
    - ENV family, 1st occurrence → bootstrap (missing_local_env/dependency_bootstrap)
                                    or retry (others)
    - ENV family, 2nd+ occurrence (same signature) → escalate (ENV_BLOCKER)
    """
    category = str(observation.get("category", "unknown"))
    signature = _root_signature(observation)
    count = _attempts_for(state, signature)

    if category == "source_failure":
        return {"action": "implementer_retry", "root_signature": signature}

    # ENV-family (all non-source_failure categories)
    if count == 0:
        # First occurrence: bootstrap for install/env types, retry for others
        if category in ("missing_local_env", "dependency_bootstrap"):
            return {"action": "bootstrap", "root_signature": signature}
        else:
            return {"action": "retry", "root_signature": signature}
    else:
        # 2nd+ occurrence of same root signature → ENV_BLOCKER
        return {"action": "escalate", "root_signature": signature}
