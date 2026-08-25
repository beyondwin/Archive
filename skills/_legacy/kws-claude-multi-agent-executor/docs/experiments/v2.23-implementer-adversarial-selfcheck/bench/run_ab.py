#!/usr/bin/env python3
"""Isolated A/B for the v2.23 Implementer adversarial self-check (per D002).

Dispatches a single Implementer sub-agent for fixture 08 Task 0 (parse_duration)
via `claude -p`, N reps per arm, scores each first-pass src/duration.py with the
fixture-08 rubric (evals/rubric.py), and records the four meta-rule-only checks
(30m20m / 1h 30m / 1H / s) plus the ADVERSARIAL_SELFCHECK line.

Arms:
  control   — implementer-prompt.md as of git HEAD (pre-intervention)
  treatment — implementer-prompt.md in the working tree (with the self-check)

This measures PREVENTION (first-pass quality), NOT final quality — see D001.
The reviewer walk (v2.9) is intentionally NOT in the loop here.

Usage:
  python3 run_ab.py --arm control   --reps 4 --outdir results/
  python3 run_ab.py --arm treatment --reps 4 --outdir results/

Cost: one `claude -p` Implementer dispatch per rep. Budget before running.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Repo-relative path of the prompt under test (for `git show HEAD:<path>`).
SKILL_REL = "skills/kws-claude-multi-agent-executor"
PROMPT_REL = f"{SKILL_REL}/references/implementer-prompt.md"

HERE = Path(__file__).resolve().parent
# HERE = .../<skill>/docs/experiments/v2.23-.../bench → skill dir is parents[3]
SKILL_DIR = HERE.parents[3]  # .../skills/kws-claude-multi-agent-executor
REPO_ROOT = SKILL_DIR.parents[1]  # Archive repo root
FIXTURE = SKILL_DIR / "evals" / "fixtures" / "08-subtle-input-validation.yaml"
RUBRIC = SKILL_DIR / "evals" / "rubric.py"

# The four fixture-08 rubric checks that are covered ONLY by a spec meta-rule
# (not by an explicit example) — the prevention target of this experiment.
META_RULE_DESCS = {
    "repeated unit raises ValueError",       # 30m20m
    "internal whitespace raises ValueError", # 1h 30m
    "uppercase unit raises ValueError",      # 1H
    "unit without integer raises ValueError",# s
}

TASK0_TEXT = """### Task 0: Implement parse_duration() in src/duration.py

**Files:**
- src/duration.py

Implement a function `parse_duration(s: str) -> int` that parses duration strings
(e.g., "1h30m", "30s", "2d") and returns the total number of seconds. The function
must implement ALL of the behaviors and error cases described in `spec.md` exactly.

Do NOT add behaviors not in the spec. Do NOT silently accept inputs the spec marks
as invalid.

## Acceptance Criteria

```bash
python -c "from src.duration import parse_duration; assert parse_duration('1h30m') == 5400"
```
"""

EFFORT_GUIDANCE = (
    "MEDIUM task: implement the function and confirm behavior. Budget ~15-30 tool calls."
)
CONTEXT_SLICE = "deps_for_this_task: []\ntask_summaries: {}  # no upstream deps\nshared_files: {}"


def _load_fixture_spec() -> str:
    import yaml
    data = yaml.safe_load(FIXTURE.read_text())
    return data["spec"]


def _control_prompt_template() -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{PROMPT_REL}"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"git show failed: {out.stderr}")
    return out.stdout


def _treatment_prompt_template() -> str:
    return (SKILL_DIR / "references" / "implementer-prompt.md").read_text()


def _fill(template: str, spec: str) -> str:
    # Extract ONLY the actual prompt body between the outer ```` fences (drop the
    # "# Implementer Prompt Template" doc wrapper / `{placeholders}` meta-line).
    fence = "````"
    if template.count(fence) >= 2:
        body = template.split(fence, 1)[1].rsplit(fence, 1)[0].strip("\n")
    else:
        body = template
    # Drop the {IF re-dispatch ...} Required Skills bullet (not a re-dispatch).
    body = re.sub(
        r"\{IF this is a re-dispatch after Combined Reviewer FAIL OR Verifier FAIL:\}.*?(?=\n## Task Size)",
        "", body, flags=re.DOTALL,
    )
    # Drop the {IF re-dispatch ...} Fix Required block in Instructions.
    body = re.sub(
        r"\{IF this is a re-dispatch after review failure, append:\}.*?(?=\n## Instructions)",
        "", body, flags=re.DOTALL,
    )
    repl = {
        "{files to touch}": "src/duration.py",
        "{orch_dir}": "/tmp/v223-bench-no-orch",
        "{implementer_model}": "sonnet",
        "{decisions_register}": "",
        "{task_size}": "MEDIUM",
        "{effort_guidance}": EFFORT_GUIDANCE,
        "{full text of the task from the plan — copy the entire task section verbatim, at whichever heading level the plan uses (`### Task N:` or `## Task N:`), including all substeps and blocks belonging to that task}": TASK0_TEXT,
        "{spec_section_label}": "FULL",
        "{relevant excerpt from the design spec — copy the section(s) that apply to this task}": spec,
        "{list from the task's Files: block — create / modify / test}": "- src/duration.py",
        "{context_slice}": CONTEXT_SLICE,
        "{risk level}": "MID",
    }
    for k, v in repl.items():
        body = body.replace(k, v)
    # Remove the markdown HTML comment after {decisions_register}, harmless if left.
    return body


def _bootstrap_repo(workdir: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    (workdir / "src").mkdir()
    (workdir / "tests").mkdir()
    (workdir / "pyproject.toml").write_text('[project]\nname = "eval08"\nversion = "0.0.1"\n')
    (workdir / "src" / "__init__.py").touch()
    (workdir / "tests" / "__init__.py").touch()
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(["git", "commit", "-qm", "bootstrap"], cwd=workdir, check=True)


def _run_implementer(prompt: str, workdir: Path) -> str:
    # Pin Sonnet: production dispatches the Implementer on Sonnet (implementer_model
    # default) and v2.7 F002's baseline was measured on Sonnet. Without --model the
    # CLI inherits the user's default (Opus), which trivially ceilings the metric and
    # invalidates the baseline comparison (per D002: dispatch model must match prod).
    proc = subprocess.run(
        ["claude", "-p", "--model", "sonnet", "--dangerously-skip-permissions", prompt],
        cwd=workdir, capture_output=True, text=True, timeout=1800,
    )
    return proc.stdout + "\n" + proc.stderr


def _score(workdir: Path) -> dict:
    out = subprocess.run(
        [sys.executable, str(RUBRIC), "--fixture", str(FIXTURE), "--workdir", str(workdir)],
        capture_output=True, text=True,
    )
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"error": "rubric did not emit JSON", "stdout": out.stdout, "stderr": out.stderr}


def _meta_rule_results(rubric_json: dict) -> dict:
    """Which of the 4 meta-rule-only checks passed? failures carry `desc`."""
    ec = rubric_json.get("error_cases", {})
    failed_descs = {f.get("desc") for f in ec.get("failures", [])}
    return {desc: (desc not in failed_descs) for desc in META_RULE_DESCS}


def _parse_selfcheck(agent_output: str) -> str:
    for line in agent_output.splitlines():
        if line.strip().startswith("ADVERSARIAL_SELFCHECK:"):
            return line.strip()
    return "(absent)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["control", "treatment"])
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--outdir", default=str(HERE / "results"))
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    spec = _load_fixture_spec()
    template = _control_prompt_template() if args.arm == "control" else _treatment_prompt_template()
    prompt = _fill(template, spec)

    # Revival guard: the v2.23 intervention was reverted to HEAD after the SKIP, so
    # the working-tree prompt the treatment arm reads no longer contains the
    # self-check. Running treatment in that state silently produces a control-
    # identical (invalid) A/B. Fail loudly and point at the revive instructions.
    marker = "ADVERSARIAL_SELFCHECK"
    if args.arm == "treatment" and marker not in prompt:
        sys.exit(
            "treatment arm aborted: the self-check intervention is NOT present in "
            "the working-tree prompt (it was reverted after the v2.23 SKIP). "
            "Re-apply the three blocks in ../intervention.md before re-running the "
            "treatment arm, or this would just re-measure control."
        )
    if args.arm == "control" and marker in prompt:
        sys.exit(
            "control arm aborted: HEAD prompt unexpectedly contains the self-check "
            "marker — control must be the pre-intervention baseline."
        )

    reps = []
    for i in range(args.reps):
        with tempfile.TemporaryDirectory(prefix=f"v223-{args.arm}-{i}-") as td:
            wd = Path(td)
            _bootstrap_repo(wd)
            agent_out = _run_implementer(prompt, wd)
            rubric = _score(wd)
            reps.append({
                "rep": i,
                "rubric_summary": rubric.get("summary", {}),
                "meta_rule_checks": _meta_rule_results(rubric),
                "adversarial_selfcheck_line": _parse_selfcheck(agent_out),
                "duration_py_exists": (wd / "src" / "duration.py").is_file(),
            })
            print(f"[{args.arm} rep {i}] meta-rule: {reps[-1]['meta_rule_checks']} "
                  f"selfcheck: {reps[-1]['adversarial_selfcheck_line']}")

    # Aggregate first-pass meta-rule pass-rate.
    n = len(reps) * len(META_RULE_DESCS)
    passed = sum(sum(1 for v in r["meta_rule_checks"].values() if v) for r in reps)
    result = {
        "arm": args.arm,
        "reps": reps,
        "meta_rule_passrate": passed / n if n else None,
        "total_passrate_mean": (
            sum(r["rubric_summary"].get("pass_rate", 0) for r in reps) / len(reps)
            if reps else None
        ),
    }
    out_path = outdir / f"{args.arm}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\n{args.arm}: meta-rule first-pass pass-rate = {result['meta_rule_passrate']:.2%}, "
          f"total pass-rate mean = {result['total_passrate_mean']:.2%}")
    print(f"written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
