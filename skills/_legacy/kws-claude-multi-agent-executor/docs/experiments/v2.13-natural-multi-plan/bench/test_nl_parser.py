#!/usr/bin/env python3
"""Run every example from examples/invocations.md through the reference parser
and assert that the echo line matches.

This is the v2.13 equivalent of the v2.12 acceptance-criteria simulation —
empirical validation that the prose lexicon spec actually produces the
documented behavior.

Run: python3 test_nl_parser.py
Exit 0 on all pass, 1 on any failure (prints diff).
"""
from __future__ import annotations

import sys

from nl_parser_reference import format_echo, parse_args


CASES: list[tuple[str, str, str]] = [
    # (name, args_str, expected_echo)
    (
        "1. single plan defaults",
        "plan=plans/feature-a.md spec=specs/feature-a.spec",
        "Parsed: 1 plan [feature-a], implementer_model=sonnet [default], parallel=on [default], mode=headless [default], risk=per-task.",
    ),
    (
        "2. single plan explicit opus + parallel=off",
        "plan=plans/feature-a.md spec=specs/feature-a.spec implementer_model=opus parallel=off",
        "Parsed: 1 plan [feature-a], implementer_model=opus [explicit], parallel=off [explicit], mode=headless [default], risk=per-task.",
    ),
    (
        "3. single plan NL korean 오푸스로 + 순차적으로",
        "plan=plans/feature-a.md spec=specs/feature-a.spec 오푸스로 순차적으로 진행해줘",
        "Parsed: 1 plan [feature-a], implementer_model=opus [NL '오푸스로'], parallel=off [NL '순차적으로'], mode=headless [default], risk=per-task.",
    ),
    (
        "4. three plan chain defaults",
        "plan=plans/a.md spec=specs/a.spec plan2=plans/b.md spec2=specs/b.spec plan3=plans/c.md spec3=specs/c.spec",
        "Parsed: 3 plans [a→b→c], implementer_model=sonnet [default], parallel=on [default], mode=headless [default], risk=per-task.",
    ),
    (
        "5. three plan chain NL korean",
        "plan=plans/a.md spec=specs/a.spec plan2=plans/b.md spec2=specs/b.spec plan3=plans/c.md spec3=specs/c.spec 오푸스로 순차적으로 진행해줘",
        "Parsed: 3 plans [a→b→c], implementer_model=opus [NL '오푸스로'], parallel=off [NL '순차적으로'], mode=headless [default], risk=per-task.",
    ),
    (
        "10. false positive guard — path containing opus",
        "plan=plans/opus-migration.md spec=specs/opus-migration.spec",
        "Parsed: 1 plan [opus-migration], implementer_model=sonnet [default], parallel=on [default], mode=headless [default], risk=per-task.",
    ),
    (
        "11. NL agrees with explicit — no-op + log",
        "plan=plans/a.md spec=specs/a.spec implementer_model=opus 오푸스로 가자",
        "Parsed: 1 plan [a], implementer_model=opus [explicit; NL '오푸스로' agrees], parallel=on [default], mode=headless [default], risk=per-task.",
    ),
]


HALT_CASES: list[tuple[str, str, str]] = [
    # (name, args_str, expected_substring_in_halt_message)
    (
        "6. conflict explicit + NL contradicting",
        "plan=plans/a.md spec=specs/a.spec implementer_model=sonnet 오푸스로 진행해줘",
        "explicit implementer_model=sonnet contradicts natural-language '오푸스로'",
    ),
    (
        "7. NL self-conflict",
        "plan=plans/a.md spec=specs/a.spec opus 좀 보고 sonnet으로 해보자",
        "Natural-language conflict",
    ),
    (
        "8. plan index gap",
        "plan=plans/a.md spec=specs/a.spec plan3=plans/c.md spec3=specs/c.spec",
        "Plan index gap: expected plan2= but only plan, plan3 provided",
    ),
    (
        "9. plan without matching spec",
        "plan=plans/a.md spec=specs/a.spec plan2=plans/b.md",
        "plan2= present but spec2= missing",
    ),
]


def run() -> int:
    failed = 0
    for name, args_str, expected_echo in CASES:
        parsed = parse_args(args_str)
        if parsed["halts"]:
            print(f"FAIL [{name}]: unexpected halt — {parsed['halts']}")
            failed += 1
            continue
        actual = format_echo(parsed)
        if actual != expected_echo:
            print(f"FAIL [{name}]:")
            print(f"  expected: {expected_echo}")
            print(f"  actual:   {actual}")
            failed += 1
        else:
            print(f"PASS [{name}]")

    for name, args_str, expected_substr in HALT_CASES:
        parsed = parse_args(args_str)
        if not parsed["halts"]:
            print(f"FAIL [{name}]: expected halt but got: {format_echo(parsed)}")
            failed += 1
            continue
        joined = " | ".join(parsed["halts"])
        if expected_substr not in joined:
            print(f"FAIL [{name}]:")
            print(f"  expected halt to contain: {expected_substr!r}")
            print(f"  actual halts: {parsed['halts']}")
            failed += 1
        else:
            print(f"PASS [{name}] (halt)")

    print()
    if failed:
        print(f"{failed} failure(s)")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(run())
