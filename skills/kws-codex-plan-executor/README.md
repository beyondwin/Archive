# KWS Codex Plan Executor 3.0.0

CPE v3 executes implementation plans in isolated git worktrees and records each
durable transition as a hash-chained event. It remains independent from
Waygent. `events.jsonl` is authoritative; `state.json` is a rebuildable
projection for resume and inspection.

Release status: **integrity-closure-pending; paid-live-pending**. The current
deterministic suite does not yet exercise every audited integrity failure. The
credentialed four-treatment, eight-case live matrix still requires explicit
cost approval and must pass before paid release closeout is claimed.

## Quick Start

```bash
cd skills/kws-codex-plan-executor
python3 scripts/cpe.py run --plan /abs/plan.md --spec /abs/spec.md \
  --workspace /abs/repo --mode interactive
```

Export without executing:

```bash
python3 scripts/cpe.py export --plan /abs/plan.md \
  --workspace /abs/repo --mode prompt
python3 scripts/cpe.py export --plan /abs/plan.md \
  --workspace /abs/repo --mode handoff
```

Resume and inspect:

```bash
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/validate_state.py ~/.codex/orchestrator/RUN_ID
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans
python3 scripts/analyze_recent_runs.py --codex-home ~/.codex --recent 20
```

## Contract Summary

- Sol/high is fixed for all core and verdict-capable attempts.
- Terra/high is limited to bounded read-only scouting.
- Write-capable tasks run sequentially.
- Supplied specs require explicit per-task section mappings.
- Models cannot write durable executor state.
- Validation, reconciliation, repair, and inspection replay the same manifest
  and event chain.
- V2 runs are preserved but classified only as `unsupported_schema`.

See [SKILL.md](SKILL.md), [ARCHITECTURE.md](ARCHITECTURE.md), and
[evals-and-verification.md](docs/evals-and-verification.md).
