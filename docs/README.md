# Docs

Start with the root [README](../README.md) or [AGENTS.md](../AGENTS.md), then
pick a path.

| If you want to | Read |
| --- | --- |
| Install and run | [Getting started](getting-started.md) |
| See which code to change | [AGENTS.md](../AGENTS.md) |
| Understand the runtime | [Architecture](architecture/waygent.md) |
| Run, apply, recover | [Operations](operations/waygent.md) |
| Event and state schemas | [Contracts](contracts/events.md) |
| Author a plan or review | [PLANS.md](../PLANS.md), [code_review.md](../code_review.md) |
| Old records | [history](history/README.md) — not current behavior |
| Executable plan/spec | `docs/superpowers/plans/`, `docs/superpowers/specs/` — default `waygent --plan` / `--spec` paths. Older scratch files also live here |

## Words

| Word | Meaning |
| --- | --- |
| Run | One execution of a plan |
| Task | One piece of work in that run |
| Plan | Markdown file with `waygent-task` blocks |
| Provider | Who writes the code: Codex, Claude, or fake |
| Isolated copy | Git worktree for one task |
| Checkpoint | Saved patch for a finished task |
| Apply | Copy finished patches into your repo |
| Scheduler | Starts tasks and decides recovery (`packages/orchestrator`) |
| Kernel | Rust side: processes, copies, apply |
| Lens | Saves records and builds views |
| Saved run file | `waygent.run_state.v2` — the file that wins |
| Event log | `agentlens.event.v3` JSONL — records you can replay |
| Ready to apply | Checks passed and your repo is clean |
| Safe task group | Tasks that can run together without file fights |

Folder names stay as they are. The table is the everyday reading.

## How it is built

- [Waygent](architecture/waygent.md)
- [Runtime](architecture/runtime.md)
- [Lens](architecture/lens.md)
- [Decisions](architecture/decisions.md)

## How to run it

- [Run, inspect, apply](operations/waygent.md)
- [Codex setup](operations/codex-local-setup.md)
- [Codex best loop](operations/codex-best-loop.md)
- [When it fails](operations/recovery.md)
- [Checks](operations/verification.md)
- [Writing a plan](operations/plan-authoring.md)
- [Where runs are stored](operations/state-root-migration.md)

## Contracts

- [Events](contracts/events.md)
- [Run file](contracts/run-state.md)
- [Provider result](contracts/provider-result.md)

## History

Old designs, incidents, and move notes: [history](history/README.md).
