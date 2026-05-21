# Waygent Operations

Default local verification:

```bash
skills/waygent/evals/run.sh
bun install
bun run check
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
cd components/agentlens && .venv/bin/python -m pytest -q
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
cd components/agentlens && .venv/bin/python -m pytest -q
```

Opt-in live provider gate:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

The live gate is skipped by default and should run only when the matching local
CLI is installed, authenticated, and acceptable for the current cost and time
budget.

Bootstrap AgentLens tests if the virtualenv is missing:

```bash
cd components/agentlens
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[test]'
fi
.venv/bin/python -m pytest -q
```

Generated local artifacts such as `node_modules/`, `apps/*/dist/`,
`native/kernel/target/`, `components/agentlens/.venv/`, and pytest caches are
ignored and should not be committed.

Live provider smoke checks are intentionally separate from default local
verification because they require authenticated local CLIs. Use
`--provider codex` or `--provider claude` only when the matching CLI is
installed and authenticated; the adapter will execute `codex exec --json -` or
`claude -p --output-format json`, then normalize the provider output into
`runway.worker_result.v1`.

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
