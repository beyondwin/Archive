# KWS Codex Plan Executor 3.0.1

CPE v3 executes implementation plans in isolated git worktrees and records each
durable transition as a hash-chained event. It remains independent from
Waygent. `events.jsonl` is authoritative; `state.json` is a rebuildable
projection for resume and inspection.

Published evidence state: **deterministic-ready; paid-live-pending**. The cost-free
integrity suite now exercises the audited fail-closed boundaries. The
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
python3 scripts/reconcile_state.py --run-dir ~/.codex/orchestrator/RUN_ID --check
python3 scripts/repair_runs.py --run-dir ~/.codex/orchestrator/RUN_ID --dry-run
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans
python3 scripts/analyze_recent_runs.py --codex-home ~/.codex --recent 20
```

## Contract Summary

- Sol/high is fixed for all core and verdict-capable attempts.
- Terra/high is limited to bounded read-only scouting.
- Write-capable tasks run sequentially.
- Supplied specs require explicit per-task section mappings.
- Models cannot write durable executor state.
- All six worker roles consume one manifest-indexed, digest-verified task packet.
- Implementation and repair are the only product-writing roles; every success
  record binds to the resulting Git revision and patch digest.
- Validation, reconciliation, repair, and inspection replay the same manifest
  and event chain.
- V2 runs are preserved but classified only as `unsupported_schema`.

Execution prints exactly one machine-readable `PublicResult`. Status-to-exit
mapping is `success=0`, `blocked=1`, and `failed=2`; zero is possible only after
canonical completion validation. The deterministic harness uses the maintained
eval inventory to drive the public CLI against temporary repositories and
compares results with an isolated oracle. It never treats duplicated fixture
logic as production behavior.

See [SKILL.md](SKILL.md), [ARCHITECTURE.md](ARCHITECTURE.md), and
[evals-and-verification.md](docs/evals-and-verification.md).
