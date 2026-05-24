# Waygent Verification

## Default Offline Gate

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:dogfood
```

This is the default gate for docs-adjacent runtime checks and fake-provider
coverage.

`waygent:dogfood` runs an offline fake-provider Waygent run and asserts the
shared maturity projection has complete dogfood evidence, runtime cost,
provider readiness, real timestamps, provider attempts, verification evidence,
and a precise explain result.

`waygent:scenarios` includes blocked replay fixtures for source/apply
readiness, including checkpoint dry-run conflicts. Those conflicts must surface
as `needs_rebase` with no apply-ready checkpoint refs, not as
`missing_checkpoint`.

`bun run waygent:fixture-lab` replays recoverable and unsafe intake examples.
It proves that bad-but-recoverable plan/spec shapes start safely, unsafe input
asks for a user decision, and provider-output parser regressions remain covered.

## Console Gate

```bash
bun run --cwd apps/console build
```

Use this when console models, UI code, or operator-facing projections change.

## Native Kernel Gate

```bash
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

Use this when native kernel crates, worktree handling, process supervision,
artifact sealing, policy, or diff application changes.

## Live Provider Gate

Live provider gates require an installed and authenticated provider CLI and an
explicit provider selection:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Keep these checks opt-in. Use offline scenario gates when provider access is
not configured or not appropriate for the current time and cost budget.

## Docs-Only Gate

```bash
git diff --check
```

For documentation-only work, also manually inspect changed links and paths.

## Full Local Checklist

Use this combined checklist before accepting broader runtime or product-surface
changes:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:dogfood
bun run check:legacy
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
git diff --check
```

## Verify Env Worktree-Awareness (SP-2)

Waygent prepares an isolated dependency environment per task before running
verification commands. Two strategies exist:

- **inherit_node_modules** (fast path) — symlinks the workspace's
  `node_modules` into the worktree. Used when the worker's diff stays inside
  a single `packages/*` or only runs unit tests. Wall-clock cost is negligible.
- **isolated_workspace_resolve** (isolated) — runs `bun install` against a
  content-addressed snapshot, materializes it into the worktree, and rewrites
  `@waygent/*` entries to worktree-local paths. Used when the worker edits
  two or more `packages/*`, touches `bun.lock`/root `package.json`, or the
  plan task carries `verify_isolation: "isolated"`.

### Plan task field

```yaml
verify_isolation: "isolated" | "fast" | "auto"   # default: "auto"
```

- `"isolated"` — always isolate, even if the diff is small.
- `"fast"` — always use inherit_node_modules, even if the diff is
  cross-package. Author intent overrides automatic detection.
- `"auto"` — let the strategy decider pick based on the worker's worktree
  diff (`git status --porcelain`).

### Failure surface

When isolation cannot be prepared, the verify phase fails and emits a
`runway.verification_environment` event with `isolation_status="unavailable"`.
The `reason` field is namespaced:

| reason code                            | meaning                                       |
|----------------------------------------|-----------------------------------------------|
| `isolation_unavailable.bun_install`    | `bun install` exited non-zero                 |
| `isolation_unavailable.snapshot_io`    | filesystem error reading/writing snapshot     |
| `isolation_unavailable.materialize`    | failed to materialize node_modules in worktree |
| `isolation_unavailable.manifest_drift` | workspace package set differs from snapshot   |
| `isolation_unavailable.cache_key_io`   | failed to compute cache key                   |

There is no automatic retry and no automatic fallback to the fast path. The
operator must intervene.

## Intake Verification Policy

Waygent classifies plan verification commands before provider dispatch. The
same policy is used by Superpowers plan normalization, deterministic intake
recovery, and plan preflight. Safe commands include known test runners,
declared package scripts, `node --test`, `git diff --check`, and Android Gradle
invocations through `./gradlew` or `gradle`.

Command chains split by `&&` are safe only when every segment is safe. A leading
`cd` is allowed only when it stays inside the workspace. Destructive commands,
workspace escapes, shell redirection, and unknown shell features block intake.

### Cache

- Location: `<workspace>/.waygent/verify-env-snapshot/<cache_key>/`
- Key: `sha256(bun.lock + packages/*/package.json + root workspaces/dependencies)`
- LRU: keep newest 5 snapshots by default (`WAYGENT_VERIFY_SNAPSHOT_KEEP=N`).

### Kill switches

- `WAYGENT_DISABLE_VERIFICATION_ENV=1` — disable verify env preparation entirely.
- `WAYGENT_DISABLE_ISOLATED_VERIFY_ENV=1` — force every task to fast path
  regardless of `verify_isolation` value. Evidence records
  `decision.reason="killed_by_env_var"`.
- `WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE=0` — drop `--frozen-lockfile` from
  the snapshot's `bun install`. Used by synthetic test fixtures with empty
  lockfiles; production should leave this unset.
