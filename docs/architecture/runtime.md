# Runtime

Waygent owns scheduling, the saved run file, isolated git copies, providers,
checks, recovery, apply, and event writing. CLI, API, and console are windows
onto that state.

## TypeScript side

`apps/` and `packages/` are Bun/TypeScript. `apps/cli` is the command you type.
`packages/orchestrator` creates runs, starts safe task groups, records the
final check, and decides if the run is ready to apply.

## Kernel

`native/kernel/` starts processes, makes isolated git copies, locks saved
files, enforces policy, and applies diffs. Run the Rust workspace tests when
kernel code changes.

## Safe task groups

A task joins a group only when file claims, dependencies, risk, and
checkpoints allow it. Chat cannot override that.

## Providers

`packages/provider-adapters` keeps fake, Codex, and Claude behind one
`WorkerResult` boundary. Codex and Claude run configured process commands, take
the task prompt on stdin, and turn JSON, JSONL, or fenced JSON into
`runway.worker_result.v1`.

## Check, recover, apply

Provider output is a record, not a pass. Kernel checks, review gates,
checkpoint files, and the final check decide whether work is usable.

`waygent apply --run <run_id>` is the only write to your source repo. It needs
the saved run file ready, checkpoint files, combined patch records, dry-run
results, and a clean source checkout.

Verification commands live in [verification](../operations/verification.md).
Agent Done is `bun run agent:verify` in [AGENTS.md](../../AGENTS.md).
