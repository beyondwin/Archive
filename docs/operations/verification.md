# Verification

## Repo contract

From the repo root:

```bash
bun run agent:contract
bun run agent:test
bun run agent:verify
bun run agent:verify -- --dry-run --path apps/console/src/App.tsx
bun run agent:verify -- --base origin/main --head HEAD
```

`agent:verify` picks deterministic commands from changed tracked and untracked
paths, including deletions. It checks Markdown links only for files that still
exist, and runs `git diff --check`. A clean path set still runs
`agent:contract` and patch hygiene.

Known paths pick the narrowest scope. Changes across two `packages/*` roots or
`bun.lock` select `waygent-closure`. Unknown paths escalate to `full-offline`.

Live provider smoke and the Claude executor full eval stay outside
`agent:verify`. Report them as `NOT RUN (opt-in)`.

```bash
bun run agent:claude-offline
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
(cd skills/_legacy/kws-claude-multi-agent-executor && ./evals/run.sh)
```

CI uses the same entry points. Pins: Bun `1.3.10`, Rust `1.95.0`, Ubuntu
`24.04`. See [Codex setup](codex-local-setup.md).

## Which gate

| You changed | Run |
| --- | --- |
| Docs only | `git diff --check` plus link inspection |
| Default runtime / fake provider | `bun run check && bun run platform:demo && bun run waygent:scenarios && bun run waygent:dogfood` |
| Apply, review, recovery, budget, stale-run cleanup | add `waygent:fixture-lab`, console build |
| Failure evidence / salvage / repair | orchestrator + projector tests, then scenarios / fixture-lab / dogfood |
| Console UI | `bun run --cwd apps/console build` (and `bun test src` there) |
| Native kernel | `cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace` |

`waygent:dogfood` is an offline fake-provider run that asserts the maturity
projection is complete. `waygent:scenarios` includes blocked replay fixtures;
checkpoint dry-run conflicts must be `needs_rebase`, not `missing_checkpoint`.
`waygent:fixture-lab` replays recoverable and unsafe intake.

## Verify env (SP-2)

Waygent prepares an isolated dependency env per task.

- `inherit_node_modules` — symlink workspace `node_modules`. Fast path.
- `isolated_workspace_resolve` — `bun install` against a content-addressed
  snapshot. Used for multi-package diffs, `bun.lock` / root `package.json`, or
  `verify_isolation: "isolated"`.

```yaml
verify_isolation: "isolated" | "fast" | "auto"   # default: auto
```

If isolation cannot be prepared, verify fails with
`runway.verification_environment` and `isolation_status="unavailable"`. No
automatic fallback.

| reason | meaning |
| --- | --- |
| `isolation_unavailable.bun_install` | `bun install` failed |
| `isolation_unavailable.snapshot_io` | snapshot read/write error |
| `isolation_unavailable.materialize` | failed to materialize `node_modules` |
| `isolation_unavailable.manifest_drift` | workspace packages differ from snapshot |
| `isolation_unavailable.cache_key_io` | cache key failed |

Cache: `<workspace>/.waygent/verify-env-snapshot/<cache_key>/`. LRU keeps 5
snapshots (`WAYGENT_VERIFY_SNAPSHOT_KEEP=N`).

Kill switches: `WAYGENT_DISABLE_VERIFICATION_ENV=1`,
`WAYGENT_DISABLE_ISOLATED_VERIFY_ENV=1`,
`WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE=0` (tests only).

## Intake commands

Plan verify commands are classified before dispatch. Safe: known test runners,
declared package scripts, `node --test`, `git diff --check`, Android Gradle
through `./gradlew` or `gradle`. `&&` chains are safe only when every segment
is. A leading `cd` must stay inside the workspace. Destructive commands, path
escapes, redirects, and unknown shell features block intake.
