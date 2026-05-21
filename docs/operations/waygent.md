# Waygent Operations

Default local verification:

```bash
bun install
bun run check
bun run --cwd apps/console build
bun run platform:demo
bun run check:legacy
```

When the Rust toolchain is available:

```bash
cd native/kernel
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```
