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

Executable `waygent-task` file claims use `owned`, `shared_append`, or
`read_only`. Waygent also accepts `mode: edit` as a compatibility alias for
`owned` so implementation-plan snippets can run without manual rewrite.

`--plan-preflight off|deterministic|full` controls the plan/spec audit.
Source checkout preflight is separate and always-on. Fake/demo runs default to
deterministic plan preflight; live provider runs default to off during burn-in.
The deterministic audit accepts both `## Task N:` and `### Task N:`
Superpowers sections, rejects missing file claims or verification commands,
blocks escaping file claims, and validates dependency references before run
state is created.

`--spec-slice off|manifest` controls task packet spec context. Manifest mode
stores `spec_manifest` in run state, emits `runway.spec_slice_computed`, and
falls back to the full spec when no section match is safe.

`--budget-cap <USD> --budget-action warn|pause|off` records token/cost ledger
policy. Budget pauses happen only at safe parent-process boundaries; Waygent
does not interrupt an active provider process.

`--hook-config off|builtin|<path>` controls runtime hooks. The first hook tier
checks pre-dispatch task packets and final provider output; per-tool provider
hooks require stable provider event streams and are not claimed by this slice.

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

A checkpoint manifest and patch that exist but fail `git apply --check`
against the current source checkout are classified as `needs_rebase`, not
`missing_checkpoint`. Waygent preserves the manifest, patch, dry-run evidence,
and failed file list, keeps `checkpoint_refs` empty until a dry-run passes, and
blocks apply until the checkpoint is regenerated or reviewed.

`not_ready` means the run lacks enough verified apply evidence. `blocked`
means evidence exists that prevents apply, such as drift, missing artifacts, a
provider failure, verification failure, or dirty source checkout. `applied`
means the verified patch has already been applied.

`waygent apply --run <run_id>` is the only source-checkout mutation path. It
checks for a clean source checkout before applying and revalidates the same
readiness contract used by `resume`, API, and console.

`waygent apply --require-evidence --run <run_id>` enables the opt-in method
evidence overlay. Missing structured `worker.evidence.method_audit` blocks
apply with `lens.evidence_apply_blocked`; docs-only, config-only, and
generated-only tasks can use allowlisted waivers. The existing checkpoint,
completion, reconciliation, and clean-checkout gates remain authoritative.

If post-apply verification fails, the apply result and `runway.apply_failed`
event include `post_apply_verification` diagnostics with the failed command,
request id, exit code, timeout flag, and short output snippets. Treat that
payload as the first recovery target before rerunning or applying again.

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

Additional read-only operator commands:

- `waygent decisions --run <id>|--last`: reads the decision register and
  `DECISIONS.md` projection.
- `waygent cost --run <id>|--last`: reads the provider usage/cost ledger.
- `waygent verify --run <id>|--last [--task <task_id>]`: reruns the selected
  task packet's verification commands in its existing active worktree and
  records kernel evidence back into the run state and event journal.
- `waygent watch --run <id>|--last --json --timeout 1s`: reads the event
  journal as filtered transitions.
- `waygent orphans --root <root>`: lists invalid run roots and stale worktrees.
  `waygent orphans --delete <id> --yes` deletes exactly one validated orphan;
  there is no delete-all path.

Repeated `--plan` and `--spec` flags form a plan chain. The first
implementation keeps child runs as v2 run states coordinated by a chain id;
it does not introduce `waygent.run_state.v3`.

Execution intelligence is read-only. Apply readiness still comes from
checkpoint manifests, patch digest checks, dry-run evidence, completion audit,
reconciliation, and clean source checkout validation.

## Operational Maturity Loop

`waygent inspect --json`, API run detail, and the console share one
operational maturity projection:

- `dogfood_evidence` checks event journal, provider attempts, verification
  records, artifact index, task phase timings, wave timing, real runtime
  timestamps, explain summary, and readiness artifact refs.
- `runtime_cost` summarizes measured waves, parallelism score, serial
  barriers, phase totals, hotspots, fixed costs, and read-only plan-shaping
  recommendations.
- `provider_readiness` classifies fake, Codex, and Claude process evidence as
  `ready`, `not_configured`, `unavailable`, `auth_required`, `failed`, or
  `unknown` without running live providers by default. Successful provider
  attempts with plugin-manifest, skill-loader, or MCP startup warnings stay
  `ready`; the warnings are summarized as cleanup guidance rather than runtime
  failure.

The operator loop is:

1. run or demo a Waygent task;
2. inspect the run and read operational maturity;
3. explain the run for the shortest next diagnosis;
4. repair provider setup, environment, missing evidence, drift, or plan shape;
5. rerun, resume, or apply only through the existing readiness gates.

Operational maturity is diagnostic. It never marks a run apply-ready and never
mutates the source checkout.

## Verification Environment

Waygent prepares verification-only dependency access for isolated local
worktrees. For Bun workspaces, a source `node_modules` directory may be
temporarily linked into the task worktree during kernel verification and
removed before checkpointing. If dependency access is unavailable, verification
is blocked as `dependency_missing` or `environment_blocker` instead of
`unknown`.

Before treating execution intelligence as complete, run the offline dogfood
gate and confirm `inspect` shows non-empty `artifact_index`, task
`phase_timings`, real event timestamps, provider attempts, verification
records, runtime cost, and precise `explain` output:

```bash
bun run waygent:dogfood
```

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
- Checkpoint dry-run conflict: inspect the run, regenerate or rebase the
  checkpoint against current source, or choose human decision. Do not apply the
  stale checkpoint from chat context.
- Dirty source checkout: clean or commit the checkout before resume or apply.
- Duplicate run id: select a new run id or resume the existing run.
- Budget paused: inspect `waygent cost --last` and raise or disable the cap
  before resuming.
- Missing method evidence: inspect `lens.evidence_apply_blocked` and either
  provide structured method audit evidence or an allowlisted waiver.

Default local verification:

```bash
skills/waygent/evals/run.sh
bun install
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
bun run waygent:dogfood
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
bun run waygent:dogfood
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
