#!/usr/bin/env python3
"""v2.19 baseline-and-ablation cost reporter.

Reads one or more state.json files (post-run) and emits a normalized cost
breakdown for v2.19 ablation comparison.

Single-file mode (baseline capture):
    python3 cost_report.py --state /path/to/run/state.json --label v2.18-baseline

Compare mode (ablation):
    python3 cost_report.py --baseline state-v2.18.json --experiment state-v2.19.json

Output: markdown table to stdout, plus a JSON snapshot to --out (optional).

Does NOT execute evals or trigger API calls — purely a post-hoc reader over
state.cost_ledger written by scripts/accumulate_cost.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

USAGE_FIELDS = ("input_tokens", "output_tokens", "cached_read_tokens", "cached_write_tokens")


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        sys.exit(f"state.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _ledger(state: dict[str, Any]) -> dict[str, Any]:
    led = state.get("cost_ledger") or {}
    if not led.get("totals"):
        sys.exit(
            "state.cost_ledger.totals is empty — v2.16+ helper invocations did not run, "
            "or this is a pre-v2.16 state.json. Cannot report.",
        )
    return led


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _format_row(label: str, agg: dict[str, Any]) -> str:
    return (
        f"| {label} "
        f"| {_format_tokens(agg.get('input_tokens', 0))} "
        f"| {_format_tokens(agg.get('cached_read_tokens', 0))} "
        f"| {_format_tokens(agg.get('cached_write_tokens', 0))} "
        f"| {_format_tokens(agg.get('output_tokens', 0))} "
        f"| ${agg.get('cost_usd', 0.0):.4f} "
        f"| {agg.get('dispatches', 0)} |"
    )


def emit_single(state_path: Path, label: str) -> dict[str, Any]:
    state = _load_state(state_path)
    led = _ledger(state)

    print(f"\n## {label} — {state_path.name}\n")
    header = (
        "| section | input | cache_read | cache_write | output | $ | dispatches |\n"
        "|---|---|---|---|---|---|---|"
    )
    print(header)
    print(_format_row("**TOTALS**", led["totals"]))

    print("\n### By role\n")
    print(header)
    for role, agg in sorted(led.get("by_role", {}).items()):
        print(_format_row(role, agg))

    print("\n### By model\n")
    print(header)
    for model, agg in sorted(led.get("by_model", {}).items()):
        print(_format_row(model, agg))

    return {
        "label": label,
        "state_path": str(state_path),
        "totals": led["totals"],
        "by_role": led.get("by_role", {}),
        "by_model": led.get("by_model", {}),
    }


def _delta(base: dict[str, Any], exp: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in USAGE_FIELDS + ("cost_usd", "dispatches"):
        b = base.get(k, 0)
        e = exp.get(k, 0)
        if isinstance(b, float) or isinstance(e, float):
            out[k] = {"baseline": b, "experiment": e, "delta": e - b,
                      "pct": (e - b) / b * 100 if b else float("inf")}
        else:
            out[k] = {"baseline": b, "experiment": e, "delta": e - b,
                      "pct": (e - b) / b * 100 if b else float("inf")}
    return out


def _format_delta_row(label: str, base: dict[str, Any], exp: dict[str, Any]) -> str:
    def fmt(field: str) -> str:
        b = base.get(field, 0)
        e = exp.get(field, 0)
        if field == "cost_usd":
            d = e - b
            pct = (d / b * 100) if b else 0
            return f"${b:.4f} → ${e:.4f} ({pct:+.1f}%)"
        d = e - b
        pct = (d / b * 100) if b else 0
        return f"{_format_tokens(b)} → {_format_tokens(e)} ({pct:+.1f}%)"

    return (
        f"| {label} "
        f"| {fmt('input_tokens')} "
        f"| {fmt('cached_read_tokens')} "
        f"| {fmt('cached_write_tokens')} "
        f"| {fmt('output_tokens')} "
        f"| {fmt('cost_usd')} |"
    )


def emit_compare(baseline_path: Path, experiment_path: Path) -> dict[str, Any]:
    base = _load_state(baseline_path)
    exp = _load_state(experiment_path)
    bled = _ledger(base)
    eled = _ledger(exp)

    print(f"\n## Ablation: {baseline_path.name} → {experiment_path.name}\n")
    header = (
        "| section | input | cache_read | cache_write | output | $ |\n"
        "|---|---|---|---|---|---|"
    )
    print(header)
    print(_format_delta_row("**TOTALS**", bled["totals"], eled["totals"]))

    print("\n### By role\n")
    print(header)
    all_roles = sorted(set(bled.get("by_role", {})) | set(eled.get("by_role", {})))
    for role in all_roles:
        print(_format_delta_row(
            role,
            bled.get("by_role", {}).get(role, {}),
            eled.get("by_role", {}).get(role, {}),
        ))

    print("\n### By model\n")
    print(header)
    all_models = sorted(set(bled.get("by_model", {})) | set(eled.get("by_model", {})))
    for model in all_models:
        print(_format_delta_row(
            model,
            bled.get("by_model", {}).get(model, {}),
            eled.get("by_model", {}).get(model, {}),
        ))

    return {
        "baseline": {"path": str(baseline_path), "ledger": bled},
        "experiment": {"path": str(experiment_path), "ledger": eled},
        "delta_totals": _delta(bled["totals"], eled["totals"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", help="single state.json to report (baseline capture mode)")
    ap.add_argument("--label", default="run", help="label for single-file report")
    ap.add_argument("--baseline", help="baseline state.json (compare mode)")
    ap.add_argument("--experiment", help="experiment state.json (compare mode)")
    ap.add_argument("--out", help="optional JSON snapshot output path")
    args = ap.parse_args(argv)

    if args.state and not (args.baseline or args.experiment):
        snap = emit_single(Path(args.state), args.label)
    elif args.baseline and args.experiment and not args.state:
        snap = emit_compare(Path(args.baseline), Path(args.experiment))
    else:
        ap.error("Use either --state (single) OR --baseline + --experiment (compare).")
        return 1

    if args.out:
        Path(args.out).write_text(json.dumps(snap, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
