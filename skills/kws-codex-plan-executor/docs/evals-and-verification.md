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
Packet prompts also state the role-specific result contract: write roles emit
`verdict=null`, while verdict-capable roles repeat the exact verdict findings
and missing-evidence arrays at the top level for contradiction checks.
Transient worker failures are recorded with their active role, including
`task_review_interrupted`, so an integrity-valid blocked run can retry the
exact read-only phase instead of being rejected as an unknown generic failure.

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
fault injection, migration planning, Superpowers capability checks, and release
metadata. `evals/run.sh` reads the maintained eval inventory and executes every
listed behavior check. Runtime cases invoke the public CLI in temporary Git
repositories with a fake provider, then compare public state and exit behavior
to an isolated oracle. The oracle may compute expectations but may not call the
production scheduler, validator, projector, or repair implementation. A green
deterministic run must not be described as paid live-model evidence.

Release status for 3.0.0 is
`integrity-closure-pending; paid-live-pending` with `release_ready=false`.
Task 13 may move to deterministic readiness only after L0-L4, fresh Graphify,
and clean tracked-tree evidence. The live matrix has four treatments and eight
cases. It is opt-in, capped at `$50.00`, and requires the operator's explicit
approval in the session that incurs cost:

```bash
python3 evals/live_model_migration.py \
  --confirm-live-cost --budget-usd 50 \
  --output /tmp/cpe-v3-live-report.json
```

Until that report exists and `release_gate.passed=true`, paid release closeout
has not passed. A dry run proves matrix shape and budget enforcement only.
