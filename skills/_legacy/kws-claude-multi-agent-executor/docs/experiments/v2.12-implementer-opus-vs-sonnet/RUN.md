# RUN — v2.12 Implementer Opus vs Sonnet comparison

End-to-end procedure to reproduce the experiment on your machine.

## Prerequisites

- Skill checked out on branch `experiment/v2.12-implementer-opus-vs-sonnet` (this branch contains the patched SKILL.md that honors `implementer_model=`).
- Python 3.10+
- `claude` CLI logged in (account with budget for 6 plan runs — see §Cost below)
- A clean working area, e.g. `~/scratch/v2.12-bench-runs/`

## Step 1 — Prepare the benchmark target repo

The benchmark needs a fresh Git repo whose contents the orchestrator will mutate. Create it from the provided skeleton:

```bash
SKILL=/Users/kws/.claude/skills/kws-claude-multi-agent-executor
EXP=$SKILL/docs/experiments/v2.12-implementer-opus-vs-sonnet
mkdir -p ~/scratch/v2.12-bench
cp -R $EXP/bench/repo-skeleton/. ~/scratch/v2.12-bench/
cd ~/scratch/v2.12-bench
git init -q
git add -A
git commit -q -m "chore: benchmark skeleton"
```

Make sure `pytest` is importable in the system python (`python3 -m pytest --version`). If not, install once: `pip install --user pytest`. No venv needed — `pyproject.toml`'s `pythonpath = ["src"]` and the plan's `PYTHONPATH=src python -c` make imports work from the worktree directly.

The orchestrator will operate on this repo. It will create one git worktree per invocation under `../worktrees/<plan-slug>-<timestamp>` (relative to the bench repo).

## Step 2 — Run the Sonnet arm (3 runs)

From `~/scratch/v2.12-bench/`, invoke the skill three times. Each invocation produces an isolated worktree, so they can run sequentially.

```bash
cd ~/scratch/v2.12-bench
for i in 1 2 3; do
  echo "=== Sonnet run $i ==="
  # In your Claude Code session, invoke:
  #   /kws-claude-multi-agent-executor plan=$EXP/bench/plan.md spec=$EXP/bench/spec.md implementer_model=sonnet parallel=off
  # Wait for HEADLESS_DONE.txt or finish in interactive mode, then continue.
done
```

The `parallel=off` flag forces sequential dispatch. The skill's Step P.2 was patched in v2.12 to propagate the model param to parallel dispatches, but `parallel=off` is a belt-and-suspenders measure that also keeps timing comparison fair (parallel speedup would otherwise muddy wall-time deltas). Use it for both arms.

After each run finishes, record the worktree path. The exact worktree slug is derived from the plan filename per Phase 0 Step 2 rules — `plan.md` → slug `plan`. So state files live at:

```
~/scratch/worktrees/plan-<TIMESTAMP>/.orchestrator/state.json
```

(Path is `../worktrees/plan-<TIMESTAMP>/.orchestrator/state.json` relative to `~/scratch/v2.12-bench/`.) Verify with `git worktree list` from inside the bench repo.

For interactive mode (no `claude -p` Agent SDK credits — uses subscription pool):

```
/kws-claude-multi-agent-executor plan=<...>/bench/plan.md spec=<...>/bench/spec.md implementer_model=sonnet parallel=off mode=interactive
```

## Step 3 — Run the Opus arm (3 runs)

Same as Step 2, but with `implementer_model=opus`:

```
/kws-claude-multi-agent-executor plan=<...>/bench/plan.md spec=<...>/bench/spec.md implementer_model=opus parallel=off
```

Each Implementer dispatch will use Opus. Reviewer/Verifier remain on Sonnet (judge consistency, ADR D001).

## Step 4 — Collect state files

You should have 6 `state.json` files across 6 worktree directories. Copy or list them:

```bash
ls ~/scratch/v2.12-bench/../worktrees/*/. orchestrator/state.json 2>/dev/null
# or
find ~/scratch/v2.12-bench/../worktrees -maxdepth 3 -name state.json
```

## Step 5 — Aggregate

```bash
python3 $EXP/bench/aggregate.py \
  ~/scratch/worktrees/plan-*/.orchestrator/state.json \
  --csv $EXP/findings/F001-data.csv
```

The script reads `implementer_model.used` from each state.json — worktree names don't need to disambiguate arms. Just pass all 6 paths in any order.

The terminal output shows per-arm summary, per-complexity breakdown, and Δ (Opus − Sonnet) per bucket. The CSV is for further analysis (load into pandas, R, sheet).

## Step 6 — Write the finding

Copy `docs/experiments/_template/findings/F000-template.md` to `findings/F001-quality-vs-cost-by-complexity.md` and fill it in based on the aggregate output and your reading of individual `state.json` files (look at `task_summaries.task_N.warnings` for WARN tasks — they're qualitative signal).

Update `README.md` "Phase status" rows and the "Findings index" with F001.

## Cost

Rough order of magnitude per run (your mileage varies — these are estimates, not quotes):

| Arm | Implementer model | Estimated per-run cost (Claude tokens) | 3 runs |
|-----|-------------------|----------------------------------------|--------|
| Sonnet | Sonnet 4.6 | ~$1-3 | ~$3-9 |
| Opus | Opus 4.7 | ~$5-15 | ~$15-45 |

Plus Orchestrator (Opus) overhead, ~$2-5 per run regardless of arm. Total experiment: roughly $30-70 in API/credit usage.

If running headless (`claude -p`), this comes out of Agent SDK credits (effective 2026-06-15). Interactive mode (`mode=interactive`) comes out of regular subscription pool.

## Troubleshooting

- **State.json missing `implementer_model` field**: you ran the skill from `main` (which is still v2.10.2). Check out `experiment/v2.12-implementer-opus-vs-sonnet`.
- **Agent tool errored "unknown model: opus"**: the model literal expected by the Agent tool's `model` parameter is one of `opus`, `sonnet`, `haiku`. Match exactly.
- **Verifier baseline mismatch**: `pyproject.toml` requires `pip install -e '.[dev]'` in the bench repo before the first run — otherwise pytest baseline is 0/0 and tests never execute.
- **Aggregate.py shows everything as `sonnet`**: pre-v2.12 state files don't have `implementer_model`; the script falls back to `"sonnet"` for missing values. Re-run with the patched skill so the field is populated.
