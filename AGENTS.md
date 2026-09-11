# AGENTS.md - Archive

Read this first. If you edit a subtree, also read that subtree's `AGENTS.md`.
Plans: [PLANS.md](PLANS.md). Reviews: [code_review.md](code_review.md).
Docs map: [docs/README.md](docs/README.md).

## Invariants

Waygent owns scheduling, worktrees, providers, verification, recovery, apply,
and event emission. Drive runs with the `waygent` CLI. Do not orchestrate
workers from chat. Do not add a `skills/` tree.

Lens is TypeScript. Do not recreate `components/agentlens`. JSON/JSONL is the
source of truth; SQLite is a rebuildable cache. New events use `platform.*`,
`runway.*`, `kernel.*`, and `lens.*` inside `agentlens.event.v3` records. Old
`agentrunway.*`, `kws-cpe.*`, and `kws-cme.*` names are history, not the
Waygent model.

Do not revert unrelated user work. Keep runtime state out of git: `.waygent/`,
`.agentlens/`, `.claude/`, `.codex-orchestrator/`, `.orchestrator/`,
`.superpowers/`, `node_modules/`, `.venv/`, build outputs, caches. Do not
commit secrets or full transcripts. Prefer existing parsers over ad hoc text
scraping. If a behavior change hits a documented contract, update the docs in
the same commit. Reply in Korean when the user writes Korean, unless the
artifact is conventionally English.

## Map

| Area | Paths |
| --- | --- |
| Surfaces | `apps/cli`, `apps/api`, `apps/console` |
| Orchestration | `packages/orchestrator`, `packages/runway-control` |
| Providers and kernel | `packages/provider-adapters`, `native/kernel`, `packages/kernel-client`, `packages/policy` |
| Lens | `packages/lens-store`, `packages/lens-projectors` |
| Contracts and plans | `packages/contracts`, `packages/design-contract`, `packages/context-packer` |
| Tests | `packages/testkit` |

Workflow surface: `waygent` CLI in `apps/cli`.

## Done

Run `bun run agent:verify` plus any extra live evidence the task asked for.
Review against `code_review.md`. Report changed files, exact command results,
skipped opt-in checks, leftover risk, and local vs remote state.
