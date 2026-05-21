# Getting Started With Waygent

## Prerequisites

Use a local checkout with Bun installed. Rust is required for native kernel
checks. Live Codex or Claude provider smoke tests also require the matching
local CLI to be installed and authenticated.

## Install

Install workspace dependencies from the repository root:

```bash
bun install
```

## Default Local Verification

The default offline checks are deterministic and do not require live provider
credentials:

```bash
bun install
bun run check
bun run platform:demo
```

## Demo Run

`bun run platform:demo` exercises the local platform path and demo surfaces. It
is the first command to run when checking whether the checkout is usable before
starting live provider work.

## Basic CLI Flow

Use the CLI to create or inspect runs:

```bash
waygent run --latest
waygent status --last
waygent inspect --run <run_id> --json
waygent explain --last
```

Use `waygent resume --last` only after inspecting the last run. Use
`waygent apply --run <run_id>` only when the source checkout is clean and the
apply projection is ready.

## Graphify Refresh

Refresh the repository map after meaningful code or documentation structure
changes:

```bash
graphify update .
graphify query "how does Waygent decide apply readiness?" --graph graphify-out/graph.json
```

Graphify output is navigation and audit evidence, not product runtime state.

## Live Provider Checks

Live smoke checks are opt-in because they consume local provider CLIs and may
depend on authentication, account limits, and local machine state:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

If a provider CLI is unavailable or unauthenticated, keep verification on the
offline fake-provider and scenario gates.

## Stop Rules

Stop before applying when the source checkout is dirty, the run selection is
ambiguous, verification has failed, checkpoint artifacts are missing, or
`waygent explain` reports unresolved blockers. Do not replace Waygent resume or
apply decisions with chat-managed file edits.
