#!/usr/bin/env python3
"""Judge calibration runner.

Builds a judge-input prompt for both good_impl and broken_impl (using the real
judge.md template), then optionally invokes `claude -p` N reps per impl and
reports the score delta.

Usage:
    python3 run.py                      # dry-run, prints both prompts
    python3 run.py --invoke --reps 3    # actually call judge × 3 each (~$3-5)
    python3 run.py --invoke --reps 3 --model opus  # use opus judge

Acceptance (advisor #3):
    mean(good scores) - mean(broken scores) >= 0.2

Outputs:
    results.json — per-rep scores + verdict
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVALS = HERE.parent
SKILL = EVALS.parent

JUDGE_TEMPLATE = (EVALS / "judge.md").read_text()
FIXTURE = (EVALS / "fixtures" / "08-subtle-input-validation.yaml").read_text()


def _fake_captured(impl_file: Path, label: str) -> dict:
    """Build a fake 'captured run' for one impl."""
    impl_code = impl_file.read_text()
    tests_code = (HERE / "tests.py").read_text()

    # diff_tail = the implementation code (last 200 lines).
    diff = f"diff --git a/src/duration.py b/src/duration.py\n+++ b/src/duration.py\n" + \
           "\n".join(f"+{line}" for line in impl_code.splitlines())
    diff += f"\ndiff --git a/tests/test_duration.py b/tests/test_duration.py\n+++ b/tests/test_duration.py\n" + \
           "\n".join(f"+{line}" for line in tests_code.splitlines())
    diff_tail = "\n".join(diff.splitlines()[-200:])

    return {
        "task_statuses": json.dumps({
            "0": {"status": "DONE", "risk": "MID", "review_retries": 0, "files": ["src/duration.py"]},
            "1": {"status": "DONE", "risk": "MID", "review_retries": 0, "files": ["tests/test_duration.py"]},
        }, indent=2),
        "git_log": (
            "abc1234 docs: update for v2.7\n"
            "def5678 Task 1: Add comprehensive tests in tests/test_duration.py\n"
            "9abcdef Task 0: Implement parse_duration() in src/duration.py\n"
            "1111111 eval bootstrap\n"
        ),
        "files_changed": "src/duration.py\ntests/test_duration.py",
        "test_output": "28 passed in 0.01s",  # tests cover only 14 cases, both pass
        "diff_tail": diff_tail,
        "wall_min": "14",
        "total_tokens": "180000",
        "label": label,
    }


def _build_prompt(captured: dict) -> str:
    """Substitute placeholders in judge.md template."""
    # Extract fixture's expected block as YAML-ish (judge.md uses it as is).
    expected = re.search(r"^expected:\n(.*?)(?=^[a-z_]+:)", FIXTURE, re.MULTILINE | re.DOTALL)
    expected_yaml = expected.group(0) if expected else "(missing)"

    prompt = JUDGE_TEMPLATE
    subs = {
        "fixture_name": "08-subtle-input-validation",
        "fixture_description": "MID-risk parse_duration with 15 edge cases — calibration test",
        "fixture_expected_yaml": expected_yaml,
        "cost_budget_wallclock_minutes": "25",
        "cost_budget_tokens": "350000",
        "captured_task_statuses": captured["task_statuses"],
        "captured_git_log": captured["git_log"],
        "captured_files_changed": captured["files_changed"],
        "captured_test_output": captured["test_output"],
        "wall_time": captured["wall_min"],
        "total_tokens": captured["total_tokens"],
        "captured_diff_tail": captured["diff_tail"],
    }
    for k, v in subs.items():
        prompt = prompt.replace("{" + k + "}", v)
    return prompt


def _extract_json(out: str) -> str | None:
    """Find the first balanced top-level {...} block in `out`."""
    start = out.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(out)):
        ch = out[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return out[start:i + 1]
    return None


def _invoke_judge(prompt: str, model: str = "sonnet", raw_log_path: Path | None = None) -> dict:
    """Call `claude -p` and parse the JSON output."""
    cmd = ["claude", "-p", "--dangerously-skip-permissions", "--model", model, prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    out = result.stdout
    if raw_log_path is not None:
        raw_log_path.write_text(out)
    block = _extract_json(out)
    if block is None:
        return {"error": "no JSON in output", "raw": out[:2000]}
    try:
        return json.loads(block)
    except json.JSONDecodeError as e:
        return {"error": f"json parse failed: {e}", "raw": block[:2000]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--invoke", action="store_true", help="actually call claude -p")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--model", default="sonnet", choices=["sonnet", "opus", "haiku"])
    args = p.parse_args()

    good_cap = _fake_captured(HERE / "good_impl.py", "good")
    broken_cap = _fake_captured(HERE / "broken_impl.py", "broken")

    good_prompt = _build_prompt(good_cap)
    broken_prompt = _build_prompt(broken_cap)

    if not args.invoke:
        print("=== GOOD PROMPT (first 80 lines) ===\n")
        print("\n".join(good_prompt.splitlines()[:80]))
        print(f"\n[... {len(good_prompt.splitlines()) - 80} more lines ...]\n")
        print("=== BROKEN PROMPT (first 80 lines) ===\n")
        print("\n".join(broken_prompt.splitlines()[:80]))
        print(f"\n[... {len(broken_prompt.splitlines()) - 80} more lines ...]\n")
        print(f"\nGood prompt: {len(good_prompt)} chars")
        print(f"Broken prompt: {len(broken_prompt)} chars")
        print(f"Diff in prompts (chars): {abs(len(good_prompt) - len(broken_prompt))}")
        print("\nDry-run only. Re-run with --invoke to actually call judge.")
        return

    raw_dir = HERE / "raw_runs" / args.model
    raw_dir.mkdir(parents=True, exist_ok=True)
    results = {"model": args.model, "reps": args.reps, "good": [], "broken": []}
    for rep in range(args.reps):
        for label, prompt, bucket in [
            ("good", good_prompt, "good"),
            ("broken", broken_prompt, "broken"),
        ]:
            print(f"[rep {rep+1}/{args.reps}] judging {label}...", flush=True)
            t0 = time.time()
            raw_path = raw_dir / f"rep{rep+1}_{label}.txt"
            r = _invoke_judge(prompt, model=args.model, raw_log_path=raw_path)
            dt = time.time() - t0
            r["_elapsed_sec"] = round(dt, 1)
            results[bucket].append(r)
            print(f"  → mean={r.get('mean')} scores={r.get('scores')} notes={r.get('notes', '')[:120]}")

    # Compute deltas.
    def _mean(arr, key):
        vals = [r.get(key) for r in arr if isinstance(r.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else None

    good_mean = _mean(results["good"], "mean")
    broken_mean = _mean(results["broken"], "mean")
    good_cq = [r.get("scores", {}).get("code_quality") for r in results["good"]]
    broken_cq = [r.get("scores", {}).get("code_quality") for r in results["broken"]]

    delta_mean = (good_mean - broken_mean) if good_mean and broken_mean else None
    verdict = (
        "PASS (judge discriminates ≥0.2)" if delta_mean and delta_mean >= 0.2
        else "FAIL (judge cannot discriminate adequately)"
    )

    summary = {
        "model": args.model,
        "good_mean": good_mean,
        "broken_mean": broken_mean,
        "delta_mean": delta_mean,
        "good_code_quality_per_rep": good_cq,
        "broken_code_quality_per_rep": broken_cq,
        "verdict": verdict,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "raw": results}, indent=2))
    print(f"\nResults: {HERE / 'results.json'}")


if __name__ == "__main__":
    main()
