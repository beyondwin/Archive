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

Version 3.1.0 publishes `deterministic-ready; paid-live-verified` with
`release_ready=true`. The reviewed live matrix completed its four treatments
and eight cases: exactly 25 credentialed calls and seven expected Terra policy
failures. The unchanged release gate passed, and the tracked privacy audit found
no raw transcripts, oracle paths, temporary execution paths, or absolute user
home paths. Dry-run compilation still makes no provider calls:

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

The published report records `release_gate.passed=true`; independent review
approved both the exact implementation and sanitized report, and the T11
privacy audit passed. A dry run proves matrix shape and digest binding only.
Future evidence runs do not change release metadata automatically and must
repeat the same review and privacy gates.

The unpublished v4 quality harness keeps the pinned 3.1.0 production control
schema as its reviewed source, then applies one shared status-contract overlay
to the control, candidate, and scout prompt bundles and to the exact schema
bytes passed to `codex exec --output-schema`. A correct refusal at a policy,
security, privacy, state-integrity, or destructive-migration boundary must use
top-level `status=blocked`; ordinary successful work uses `completed`, and an
attempted failure uses `failed`. The launched schema rejects a nested blocked
verdict paired with top-level completed. `check_prompt_bundle_v4.py` and
`check_quality_matrix_v4.py` bind these instructions and schema bytes to the
compiled prompt, manifest, fake launcher, result, and evidence digests without
making a provider call. This deterministic contract does not amend or rerun
previously captured live evidence and does not publish v4 release readiness.

The same check reorders the manifest and proves that `--sentinel-only` still
selects the exact candidate security/migration key. Its production CLI fake
compares actual stdin and the actual `--output-schema` file byte-for-byte with
the sealed launch envelope, proves a failed sentinel stops at one invocation,
and proves resume neither bypasses nor duplicates a passed sentinel. Envelope,
prompt, schema, route, source/fixture, and separate oracle-binding mismatches
fail closed before a credentialed call; aggregate and release validation reject
envelope substitution across manifest, result, slot index, prompt binding, and
ledger evidence.

The cost-free authentic production E2E launches the real runner CLI and fake
Codex subprocess with a top-level blocked sentinel carrying the wrong hidden-
oracle ID, then proves one invocation followed by a zero-call blocked resume.
Its passing branch compiles and materializes the real sealed artifacts, parses
fake Codex output, evaluates the runner-owned hidden oracle, resumes without
duplicating the sentinel, and lets production `aggregate` write the five
canonical release files. The public validator independently enforces closed
schemas, Git/checkpoint/digest/envelope bindings, and a shared privacy re-audit
over those actual payloads. Unknown fields such as caller `debug_note` fail
even when superficial hashes and the stored privacy boolean are rewritten.
The pre-dogfood package uses a closed `status=not_run` record with zero metrics;
no arbitrary dogfood JSON is copied.

When the sole authorized corrected v4 run uses a new evidence root, import the
failed predecessor lineage without copying its oracle-bearing manifest:

```bash
python3 evals/live_model_runner.py attest-predecessor \
  --predecessor-root /absolute/failed-evidence-root \
  --evidence-root /absolute/corrected-evidence-root
```

This command is cost-free and accepts no caller-supplied summary. It validates
the real predecessor root in place and writes only a sanitized digest
attestation followed by its hash-chained event. Repeating the same import is
idempotent; a different or tampered predecessor, an unchanged corrected
checkpoint, or a third registration fails before provider preflight.
