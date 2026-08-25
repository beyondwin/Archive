#!/usr/bin/env python3
"""Compare two executor regression baselines and gate dispatch cost metrics.

Used by v2.22's dispatch-optimization work to verify that API-based dispatch
with prompt caching meets two targets versus a prior baseline:

  * cache hit ratio >= 0.60  (--check-cache-hit-min)
  * candidate input tokens <= 20% of baseline (--check-input-cost-max-ratio)

Older baselines (<= v2.21.0) predate the per-dispatch ``metrics`` block, so the
input-cost ratio check degrades gracefully (SKIPPED) when the baseline lacks
``metrics.input_tokens_mean``.

stdlib only (json, argparse). Comparison/gate logic lives in importable
functions so ``--self-test`` exercises them directly without shelling out.
"""
import argparse
import json
import sys


# ---------------------------------------------------------------------------
# Pure helpers (exercised by --self-test)
# ---------------------------------------------------------------------------

def get_metric(baseline, key):
    """Return metrics[key] from a baseline dict, or None if absent."""
    metrics = baseline.get("metrics") if isinstance(baseline, dict) else None
    if not isinstance(metrics, dict):
        return None
    return metrics.get(key)


def check_cache_hit(candidate, minimum):
    """Gate: candidate metrics.cache_hit_ratio_mean must be >= minimum.

    Returns (status, message) where status is one of
    'PASS', 'FAIL', 'SKIPPED'.
    """
    value = get_metric(candidate, "cache_hit_ratio_mean")
    if value is None:
        return ("SKIPPED",
                "candidate lacks metrics.cache_hit_ratio_mean; "
                "cannot check cache-hit gate")
    if value >= minimum:
        return ("PASS",
                "cache_hit_ratio_mean=%.4f >= %.4f" % (value, minimum))
    return ("FAIL",
            "cache_hit_ratio_mean=%.4f < %.4f" % (value, minimum))


def check_input_cost_ratio(baseline, candidate, max_ratio, baseline_path="baseline"):
    """Gate: candidate.input_tokens_mean / baseline.input_tokens_mean <= max_ratio.

    Degrades gracefully: if the baseline (or candidate) lacks
    metrics.input_tokens_mean, returns ('SKIPPED', ...) which callers treat as
    non-failing. Returns (status, message, ratio_or_None).
    """
    base_val = get_metric(baseline, "input_tokens_mean")
    cand_val = get_metric(candidate, "input_tokens_mean")
    if base_val is None:
        return ("SKIPPED",
                "baseline %s predates input-cost metric; cannot compute ratio"
                % baseline_path,
                None)
    if cand_val is None:
        return ("SKIPPED",
                "candidate lacks metrics.input_tokens_mean; cannot compute ratio",
                None)
    if base_val == 0:
        return ("SKIPPED",
                "baseline input_tokens_mean is 0; cannot compute ratio",
                None)
    ratio = cand_val / base_val
    if ratio <= max_ratio:
        return ("PASS",
                "input_tokens ratio=%.4f <= %.4f (candidate=%d, baseline=%d)"
                % (ratio, max_ratio, cand_val, base_val),
                ratio)
    return ("FAIL",
            "input_tokens ratio=%.4f > %.4f (candidate=%d, baseline=%d)"
            % (ratio, max_ratio, cand_val, base_val),
            ratio)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt(value, fmt="%s"):
    return "n/a" if value is None else fmt % value


def report_delta(baseline, candidate, base_path, cand_path):
    """Print a human-readable per-role and overall delta report."""
    lines = []
    lines.append("Cost comparison")
    lines.append("  baseline:  %s" % base_path)
    lines.append("  candidate: %s" % cand_path)
    lines.append("")

    base_m = baseline.get("metrics") if isinstance(baseline, dict) else None
    cand_m = candidate.get("metrics") if isinstance(candidate, dict) else None

    base_roles = (base_m or {}).get("per_role", {}) if isinstance(base_m, dict) else {}
    cand_roles = (cand_m or {}).get("per_role", {}) if isinstance(cand_m, dict) else {}
    roles = sorted(set(base_roles) | set(cand_roles))
    if roles:
        lines.append("Per-role (baseline -> candidate):")
        for role in roles:
            b = base_roles.get(role, {})
            c = cand_roles.get(role, {})
            lines.append("  %s:" % role)
            lines.append("    wall_ms_mean:        %s -> %s"
                         % (_fmt(b.get("wall_ms_mean")), _fmt(c.get("wall_ms_mean"))))
            lines.append("    input_tokens_mean:   %s -> %s"
                         % (_fmt(b.get("input_tokens_mean")), _fmt(c.get("input_tokens_mean"))))
            lines.append("    cache_hit_ratio_mean: %s -> %s"
                         % (_fmt(b.get("cache_hit_ratio_mean")), _fmt(c.get("cache_hit_ratio_mean"))))
        lines.append("")

    lines.append("Overall (baseline -> candidate):")
    for key in ("input_tokens_mean", "cache_hit_ratio_mean",
                "escalate_count", "output_quality_mean"):
        lines.append("  %-20s %s -> %s"
                     % (key + ":", _fmt(get_metric(baseline, key)),
                        _fmt(get_metric(candidate, key))))
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def self_test():
    # cache-hit gate: pass
    cand_good = {"metrics": {"cache_hit_ratio_mean": 0.66}}
    status, _ = check_cache_hit(cand_good, 0.60)
    assert status == "PASS", "expected PASS for 0.66 >= 0.60, got %s" % status

    # cache-hit gate: fail
    cand_bad = {"metrics": {"cache_hit_ratio_mean": 0.40}}
    status, _ = check_cache_hit(cand_bad, 0.60)
    assert status == "FAIL", "expected FAIL for 0.40 < 0.60, got %s" % status

    # cache-hit gate: candidate missing metric -> SKIPPED
    status, _ = check_cache_hit({"metrics": {}}, 0.60)
    assert status == "SKIPPED", "expected SKIPPED when metric absent, got %s" % status

    # input-cost ratio: pass (3000 / 20000 = 0.15 <= 0.20)
    base_full = {"metrics": {"input_tokens_mean": 20000}}
    cand_low = {"metrics": {"input_tokens_mean": 3000}}
    status, _, ratio = check_input_cost_ratio(base_full, cand_low, 0.20)
    assert status == "PASS", "expected PASS for 0.15 <= 0.20, got %s" % status
    assert abs(ratio - 0.15) < 1e-9, "expected ratio 0.15, got %s" % ratio

    # input-cost ratio: fail (10000 / 20000 = 0.50 > 0.20)
    cand_high = {"metrics": {"input_tokens_mean": 10000}}
    status, _, ratio = check_input_cost_ratio(base_full, cand_high, 0.20)
    assert status == "FAIL", "expected FAIL for 0.50 > 0.20, got %s" % status

    # input-cost ratio: baseline predates metric -> SKIPPED (non-failing)
    base_old = {"version": "2.21.0", "fixtures": []}
    status, msg, ratio = check_input_cost_ratio(base_old, cand_low, 0.20, "v2.21.0.json")
    assert status == "SKIPPED", "expected SKIPPED when baseline lacks metric, got %s" % status
    assert ratio is None, "expected ratio None on SKIP, got %s" % ratio
    assert "predates input-cost metric" in msg, "expected predates message, got %r" % msg

    # input-cost ratio: candidate missing metric -> SKIPPED
    status, _, _ = check_input_cost_ratio(base_full, {"metrics": {}}, 0.20)
    assert status == "SKIPPED", "expected SKIPPED when candidate lacks metric, got %s" % status

    print("SELF-TEST OK")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare two executor baselines and gate dispatch cost metrics.")
    parser.add_argument("--baseline", help="path to the prior baseline JSON")
    parser.add_argument("--candidate", help="path to the candidate baseline JSON")
    parser.add_argument("--check-cache-hit-min", type=float, default=None,
                        help="gate: candidate cache_hit_ratio_mean must be >= this")
    parser.add_argument("--check-input-cost-max-ratio", type=float, default=None,
                        help="gate: candidate/baseline input_tokens_mean must be <= this")
    parser.add_argument("--self-test", action="store_true",
                        help="run internal assertions and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.baseline or not args.candidate:
        parser.error("--baseline and --candidate are required unless --self-test")

    baseline = load_json(args.baseline)
    candidate = load_json(args.candidate)

    report_delta(baseline, candidate, args.baseline, args.candidate)
    print("")

    failed = False

    if args.check_cache_hit_min is not None:
        status, msg = check_cache_hit(candidate, args.check_cache_hit_min)
        print("CACHE-HIT GATE [%s]: %s" % (status, msg))
        if status == "FAIL":
            failed = True

    if args.check_input_cost_max_ratio is not None:
        status, msg, _ = check_input_cost_ratio(
            baseline, candidate, args.check_input_cost_max_ratio, args.baseline)
        print("INPUT-COST GATE [%s]: %s" % (status, msg))
        if status == "FAIL":
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
