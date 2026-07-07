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
# First match wins (most specific patterns first).

_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # missing_local_env — import errors, command not found, module missing
    (re.compile(r"ModuleNotFoundError", re.IGNORECASE),
     "missing_local_env",
     "ModuleNotFoundError in output"),

    (re.compile(r"ImportError", re.IGNORECASE),
     "missing_local_env",
     "ImportError in output"),

    (re.compile(r"command not found", re.IGNORECASE),
     "missing_local_env",
     "command not found in output"),

    (re.compile(r"No such file or directory", re.IGNORECASE),
     "missing_local_env",
     "No such file or directory in output"),

    # dependency_bootstrap — package manager / install hints
    (re.compile(r"node_modules", re.IGNORECASE),
     "dependency_bootstrap",
     "node_modules reference in output — run npm/yarn install"),

    (re.compile(r"run (npm|yarn|pnpm|pip|poetry|bun) install", re.IGNORECASE),
     "dependency_bootstrap",
     "install-hint pattern in output"),

    # resource_oom
    (re.compile(r"(out of memory|oom kill|heap|memory|killed)", re.IGNORECASE),
     "resource_oom",
     "OOM/resource-kill signal in output"),

    # timeout_or_hang
    (re.compile(r"(timed? ?out|timeout|SIGKILL|hung|hang)", re.IGNORECASE),
     "timeout_or_hang",
     "Timeout/hang signal in output"),

    # permission_or_sandbox
    (re.compile(r"(permission denied|Operation not permitted|sandbox|EPERM|EACCES)",
                re.IGNORECASE),
     "permission_or_sandbox",
     "Permission/sandbox block in output"),

    # tooling_bug — tool internal errors
    (re.compile(r"(internal error|segmentation fault|core dumped|SIGSEGV)",
                re.IGNORECASE),
     "tooling_bug",
     "Tooling internal error / crash in output"),

    # source_failure — test assertion failures, FAILED test lines
    (re.compile(r"(AssertionError|FAILED |assert .* ==|assert .* !=|"
                r"raise AssertionError|assert False)",
                re.IGNORECASE),
     "source_failure",
     "Assertion / test failure in output"),

    (re.compile(r"(SyntaxError|NameError|TypeError|AttributeError|"
                r"ValueError|RuntimeError|NotImplementedError)",
                re.IGNORECASE),
     "source_failure",
     "Python source exception in output"),
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
