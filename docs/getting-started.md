# Getting started

You need Bun. Rust is required for kernel checks. Live Codex or Claude checks
also need that CLI installed and signed in.

## Install

```bash
bun install --frozen-lockfile
```

## Offline check

```bash
bun run check
bun run platform:demo
```

`platform:demo` is the first signal that the checkout actually runs.

## First commands

```bash
waygent run --latest
waygent status --last
waygent inspect --run <run_id> --json
waygent explain --last
```

Use `waygent resume --last` only after you have read the last run. Use
`waygent apply --run <run_id>` only when the source checkout is clean and the
apply projection is ready.

If PATH has no `waygent` binary:

```bash
bun run waygent -- status --last
```

## Live providers

These consume a local CLI and may hit auth or account limits:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

If the CLI is missing or unsigned-in, stay on fake-provider and scenario
checks.

## Stop

Do not apply when the source checkout is dirty, the run pick is ambiguous,
verification failed, checkpoints are missing, or `waygent explain` still
reports blockers. Do not patch from chat instead of resume or apply.

Next: [operations](operations/waygent.md) and [recovery](operations/recovery.md).
