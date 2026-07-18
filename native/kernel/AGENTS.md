# Native Kernel Agent Instructions

- Keep process, filesystem, Git, and sandbox enforcement in the Rust boundary.
- Treat platform-specific process control as an explicit support boundary.
- Run rustfmt check and `cargo test --workspace` from `native/kernel/`.
