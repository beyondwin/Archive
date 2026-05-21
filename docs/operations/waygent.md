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
