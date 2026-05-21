# Waygent Operations

Related operations docs:

- [Recovery](./recovery.md)
- [Verification](./verification.md)

## Operational Trust Loop

Waygent treats `waygent.run_state.v2` as the runtime source of truth for
apply readiness. Event journals, API responses, and console views can replay or
present that evidence, but they do not decide whether a run is safe to resume
or apply.

### Run Preflight

`waygent run` classifies the source checkout before provider dispatch:

- `clean`: dispatch can continue.
- `dirty_unrelated`: dispatch can continue, but the preflight warning is
  recorded in state and events.
- `dirty_related`: dispatch is blocked with `dirty_source_checkout`; clean or
  commit the related files before retrying.

If a target run id already has durable evidence, `waygent run` stops with
`run_id_already_exists` instead of deleting the prior run root. Use a fresh run
id or a resume path; do not overwrite the only evidence for a failed run.

From the Codex app or Codex CLI, `waygent run` defaults to Codex provider and
`multi-agent` execution. `waygent demo` is offline-only and rejects live
providers; explicit `--provider fake` remains the deterministic path for tests.
When PATH does not expose a `waygent` binary, use the repo-local command
`bun run waygent -- run ...`.

`--plan` and `--spec` accept full paths or basenames from approved docs
locations such as `docs/superpowers/plans/` and `docs/superpowers/specs/`.
Ambiguous basenames fail with candidate paths instead of silently selecting
one. Directory-bearing paths and markdown-looking spec filenames must exist;
typos fail instead of being treated as inline spec text.

### Apply Readiness

`ready` means all of the following are true:

- completion audit passed;
- each verified task has a valid checkpoint manifest;
- checkpoint patch bytes exist and match recorded digest and byte length;
- checkpoint dry-run evidence exists and passed;
- combined apply evidence exists, points to a materialized patch, and matches
  recorded digest and byte length;
- reconciliation has no unrepaired drift or artifact blockers.

An empty checkpoint patch is valid no-op evidence when provider work and
Waygent-owned verification both pass. Waygent records `no_op: true`, skips
`git apply --check` for the empty patch, and still runs post-apply
verification before marking apply complete.

`not_ready` means the run lacks enough verified apply evidence. `blocked`
means evidence exists that prevents apply, such as drift, missing artifacts, a
provider failure, verification failure, or dirty source checkout. `applied`
means the verified patch has already been applied.

`waygent apply --run <run_id>` is the only source-checkout mutation path. It
checks for a clean source checkout before applying and revalidates the same
readiness contract used by `resume`, API, and console.

## Safe-Wave Parallel Execution

Waygent may run tasks in the same scheduler-approved safe wave concurrently.
Parallelism never bypasses file-claim, dependency, risk, verification,
checkpoint, completion-audit, reconciliation, or apply-readiness gates.

Live providers default to conservative bounded concurrency. Set
`WAYGENT_WAVE_CONCURRENCY=<n>` only when the local machine and provider
account can sustain the requested parallel work.

## Execution Intelligence

`waygent inspect --json` and the console expose execution intelligence from
durable run evidence. The projection explains safe waves, withheld tasks,
barriers, phase timing, artifact health, and next plan-shaping actions.

Execution intelligence is read-only. Apply readiness still comes from
checkpoint manifests, patch digest checks, dry-run evidence, completion audit,
reconciliation, and clean source checkout validation.

## Verification Environment

Waygent prepares verification-only dependency access for isolated local
worktrees. For Bun workspaces, a source `node_modules` directory may be
temporarily linked into the task worktree during kernel verification and
removed before checkpointing. If dependency access is unavailable, verification
is blocked as `dependency_missing` or `environment_blocker` instead of
`unknown`.

Before treating execution intelligence as complete, run a real Waygent dogfood
execution and confirm `inspect` shows non-empty `artifact_index`, task
`phase_timings`, real event timestamps, and precise `explain` blockers.

### Recovery Actions

Use `waygent explain --last` or `waygent inspect --run <run_id>` before
choosing a recovery action.

- Drift or missing artifact: inspect the run, retry checkpoint generation only
  when the required artifacts and worktree still exist, otherwise choose human
  decision.
- Provider crash, timeout, or malformed output: retry with the bounded provider
  policy, switch provider, or route to human decision.
- Verification failure: rerun verification after fixing the task worktree or
  choose human decision.
- Dirty source checkout: clean or commit the checkout before resume or apply.
- Duplicate run id: select a new run id or resume the existing run.

Default local verification:

```bash
skills/waygent/evals/run.sh
bun install
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

## V1 Maturity Verification

Default offline gate:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

Opt-in live provider gate:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

The live gate is skipped by default and should run only when the matching local
CLI is installed, authenticated, and acceptable for the current cost and time
budget.

Generated local artifacts such as `node_modules/`, `apps/*/dist/`,
`native/kernel/target/`, and test caches are ignored and should not be
committed.

Live provider smoke checks are intentionally separate from default local
verification because they require authenticated local CLIs. Use
`--provider codex` or `--provider claude` only when the matching CLI is
installed and authenticated; the adapter will execute `codex exec --json -` or
`claude -p --output-format json`, then normalize the provider output into
`runway.worker_result.v1`.

Scenario and live-smoke gates assert the same readiness shape as runtime state:
manifest-backed checkpoint refs, combined patch evidence, provider attempt
artifacts, and explicit blockers. Fake-provider scenarios are the default
offline gate; live Codex and Claude checks remain opt-in through
`WAYGENT_LIVE_PROVIDER`.

## Operator Stop Rules

- Stop and inspect when `waygent run --latest` or an active run selection is
  ambiguous.
- Stop when apply reports `dirty_source_checkout`; do not retry against a dirty
  source checkout.
- Stop when a live provider CLI is unavailable or unauthenticated; use fake
  provider scenarios instead.
- Stop after failed verification and run `waygent explain --last` before
  `waygent resume --last`.
- Stop when `waygent apply --run <run_id>` reports no verified checkpoint.
