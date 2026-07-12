# KWS Codex Plan Executor 3.1.0

CPE v3 executes implementation plans in isolated git worktrees and records each
durable transition as a hash-chained event. It remains independent from
Waygent. `events.jsonl` is authoritative; `state.json` is a rebuildable
projection for resume and inspection.

Published evidence state: **deterministic-ready; paid-live-verified**. The
cost-free integrity suite exercises the audited fail-closed boundaries, and the
reviewed four-treatment, eight-case ChatGPT subscription matrix completed all
25 credentialed calls and seven expected policy failures with the unchanged
release gate passing. The tracked privacy audit also passed; account-side USD
cost attribution remains unavailable.

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

Plan the subscription live matrix without making provider calls:

```bash
python3 evals/live_model_runner.py dry-run \
  --billing-mode chatgpt_subscription \
  --output /tmp/cpe-v3-subscription-plan.json
```

`start` and `resume` are release-evidence operations, not normal CPE execution
commands. They require `--confirm-subscription-usage`, an external evidence
directory, and ChatGPT login; API-key authentication is rejected. Any future
matrix must again receive independent review of the exact implementation and
sanitized report. See [evals-and-verification.md](docs/evals-and-verification.md).

For an explicitly authorized v4 corrected run in a new evidence root, first
use `live_model_runner.py attest-predecessor`. The command makes no provider
call: it validates the old failed ledger, projections, manifests, aggregate,
privacy verdict, and Git checkpoint in place, then persists only digest-bound
lineage. The corrected registration must use a changed checkpoint, and a third
full run is rejected before authentication or provider preflight.

V4 execution always qualifies the exact candidate security/migration case
before other credentialed slots. The compiler seals exact stdin and
`--output-schema` bytes into one content-addressed launch envelope per call;
the runner reopens and verifies that artifact immediately before launch.
Hidden oracle paths and bytes are bound separately and never enter the worker
prompt, argv, or environment. Resume reuses a passed sentinel and cannot bypass
or duplicate it. The runner-owned semantic gate requires an exact hidden-oracle
ID match for the qualified block case, and the compiler-owned 17-entry envelope
map is reused unchanged by ledger aggregation and sanitized release validation.

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
- The live runner freezes the exact 32-slot manifest (25 credentialed calls and
  seven expected policy failures), runs each credentialed slot in an isolated
  ephemeral Codex turn, and commits digest-bound evidence to a replayable
  external ledger.

Execution prints exactly one machine-readable `PublicResult`. Status-to-exit
mapping is `success=0`, `blocked=1`, and `failed=2`; zero is possible only after
canonical completion validation. The deterministic harness uses the maintained
eval inventory to drive the public CLI against temporary repositories and
compares results with an isolated oracle. It never treats duplicated fixture
logic as production behavior.

See [SKILL.md](SKILL.md), [ARCHITECTURE.md](ARCHITECTURE.md), and
[evals-and-verification.md](docs/evals-and-verification.md).
