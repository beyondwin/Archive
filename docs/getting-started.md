# Getting started

You need Bun. Kernel checks also need Rust. Live Codex or Claude checks
need that CLI installed and signed in.

## Install

```bash
bun install --frozen-lockfile
```

## Offline check

```bash
bun run check
bun run platform:demo
```

`platform:demo` is the first sign that this checkout actually runs.

## First commands

```bash
waygent run --latest
waygent status --last
waygent inspect --run <run_id> --json
waygent explain --last
```

Use `waygent resume --last` only after you have read the last run. Use
`waygent apply --run <run_id>` only when your repo is clean and the run
is ready to apply.

If PATH has no `waygent` command:

```bash
bun run waygent -- status --last
```

## Live providers

These use a local CLI and may hit auth or account limits:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

If the CLI is missing or not signed in, stay on the fake provider and
scenario checks.

## Stop

Do not apply when your repo is dirty, the run pick is unclear, a check
failed, checkpoints are missing, or `waygent explain` still lists
blockers. Do not patch from chat instead of resume or apply.

Next: [how to run it](operations/waygent.md) and [when it fails](operations/recovery.md).
