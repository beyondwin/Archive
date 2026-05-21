# Waygent Verification

## Default Offline Gate

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
```

This is the default gate for docs-adjacent runtime checks and fake-provider
coverage.

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
bun run check:legacy
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
git diff --check
```
