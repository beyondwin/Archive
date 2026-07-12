# Evals And Verification

The maintained runtime checks include current Codex CLI compatibility: the
worker response schema must stay inside the supported Structured Outputs
subset, and model/reasoning attestation may be recovered only from the
CLI-owned session JSONL whose thread ID and worktree match the completed call.
Workers receive the verified packet's absolute run-store path and digest; the
workspace sandbox may read that external evidence but cannot edit it.
Full-tree scope checks continue to include ignored content, except untracked
Python `__pycache__` directories, which repository policy classifies as
machine-local runtime cache rather than product evidence.

Install the pinned eval dependency in an isolated environment, then run:

```bash
python3 -m pip install -r requirements-eval.txt
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_docs_contract.py
git diff --check
```

The active deterministic suite exercises dependency reporting, fixed routing,
override rejection, manifest/evidence integrity, event replay, execution,
validation parity, reconciliation, safe repair, inspection, recent-run metrics,
fault injection, exact live-matrix compilation, fixture/oracle/ledger integrity,
guarded runner failure modes, migration aggregation, Superpowers capability
checks, and release metadata. `evals/run.sh` reads the maintained eval inventory
and executes every
listed behavior check. Runtime cases invoke the public CLI in temporary Git
repositories with a fake provider, then compare public state and exit behavior
to an isolated oracle. The oracle may compute expectations but may not call the
production scheduler, validator, projector, or repair implementation. A green
deterministic run must not be described as paid live-model evidence.

Version 3.0.1 currently publishes
`deterministic-ready; paid-live-pending` with `release_ready=false`. The live
matrix has four treatments and eight cases: exactly 25 credentialed calls and
seven expected Terra policy failures. Dry-run compilation makes no provider
calls:

```bash
python3 evals/live_model_runner.py dry-run \
  --billing-mode chatgpt_subscription \
  --output /tmp/cpe-v3-subscription-plan.json
```

After reviewing the plan, an operator may explicitly authorize subscription
usage and choose an evidence root outside this repository:

```bash
python3 evals/live_model_runner.py start \
  --billing-mode chatgpt_subscription \
  --confirm-subscription-usage \
  --evidence-root /absolute/private/evidence-root

python3 evals/live_model_runner.py resume \
  --confirm-subscription-usage \
  --run-dir /absolute/private/evidence-root/RUN_ID
```

`start` requires the authenticated ChatGPT Codex binary, rejects API-key
authentication, verifies the exact model catalog, and stops on timeout,
subscription limit, malformed output, drift, or missing attestation. `resume`
continues only unresolved slots; a failed slot additionally requires
`--retry-failed`. Do not place the evidence root in the repository or fixture
tree, and do not commit raw event streams or model output.

Before a Sol v3 credentialed call, the runner executes the immutable fixture
baseline command itself and verifies its declared exit code. It then renders a
bounded snapshot of tracked UTF-8 seed files and that baseline output into the
worker prompt. Read-only cases are instructed to make no tool call; write cases
are instructed to make the minimal edit and run acceptance once. The snapshot
is capped by file count, per-file bytes, and total bytes, and cannot traverse
the separate hidden oracle directory.

Aggregate a completely resolved immutable ledger into a sanitized report:

```bash
python3 evals/live_model_migration.py \
  --billing-mode chatgpt_subscription \
  --confirm-subscription-usage \
  --run-dir /absolute/private/evidence-root/RUN_ID \
  --output /absolute/private/cpe-v3-subscription-report.json
```

The report must preserve the exact manifest/result set, all required input,
prompt, implementation, model-catalog, and result digests, 25 credentialed
calls, seven policy failures, and no unresolved timeout, rate-limit,
malformed-output, or evidence blocker. Subscription billing is an external
boundary, so a valid report states `cost_usd=null` and
`cost_observability=unavailable` rather than inventing a direct USD cost.

Until the checked-in aggregator reports `release_gate.passed=true` and an
independent reviewer approves both the exact implementation and sanitized
report, paid-live closeout has not passed. A dry run proves matrix shape and
digest binding only. No command in this flow changes release metadata.
