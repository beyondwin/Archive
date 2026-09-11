# Living Docs and Agent Guidance Design

**Date:** 2026-09-11

**Status:** Approved design (pending implementation plan)

**Scope:** Current docs and root guidance files. No code-directory moves.
No edits to `docs/history/`, `docs/migration/`, or existing
`docs/superpowers/` file bodies.

## Goal

One shared map for humans and agents. Root agent files carry only what an
agent must not skip. Current docs stay in their folders; overlapping
install/layout/check text collapses to a single owner. Misleading names
(`agentlens.md`, “superpowers is scratch”) get fixed without moving the
plan/spec tree.

## Non-goals

- Moving `apps/`, `packages/`, or `native/`
- Adding package README files
- Moving or rewriting `docs/history/`, `docs/migration/`, or existing
  `docs/superpowers/plans|specs` bodies
- Changing `waygent run --plan/--spec` default directories
- Running full `bun run check`, scenarios, console build, or Rust tests
  for this change

## Entry points

Two doors, one map.

```text
human       README.md
agent       AGENTS.md
                │
                ▼
         docs/README.md
```

Ownership of repeated content:

| Content | Single owner |
| --- | --- |
| Install, first commands, live providers | `docs/getting-started.md` |
| “What should I read?” | `docs/README.md` |
| Code map (where to edit) | `AGENTS.md` |
| Done / `agent:verify` | `AGENTS.md` |
| Plan template | `PLANS.md` |
| Review checklist | `code_review.md` |
| Verification details | `docs/operations/verification.md` |

Root `README.md` may keep a one-line product sentence, a few first commands,
and links. It must not restate layout, apply rules, or live-provider policy.

## Shared map (`docs/README.md`)

Replace the current index table with:

| If you want to | Read |
| --- | --- |
| Install and run | [Getting started](getting-started.md) |
| See which code to change | [AGENTS.md](../AGENTS.md) |
| Understand the runtime | [Architecture](architecture/waygent.md) |
| Run, apply, recover | [Operations](operations/waygent.md) |
| Event and state schemas | [Contracts](contracts/events.md) |
| Author a plan or review | [PLANS.md](../PLANS.md), [code_review.md](../code_review.md) |
| Old records | [history](history/README.md) — not current behavior |
| Executable plan/spec | `docs/superpowers/plans/`, `docs/superpowers/specs/` — default `waygent --plan/--spec` paths. Older scratch files also live here |

Keep the existing Architecture / Operations / Contracts link lists under that
table. Point Lens at `architecture/lens.md`, not `agentlens.md`.

Label `docs/superpowers/` as the executable plan/spec default path in
`docs/README.md`, `docs/operations/waygent.md` (the `--plan`/`--spec`
paragraph), and the one misleading sentence in `docs/roadmap/README.md`
that currently calls those trees “proposals until the matching contracts
ship”. Do not rewrite the rest of the roadmap.

## AGENTS.md

Three sections only. No preflight git block, no `git add` recipe, no
handoff template, no MCP catalog. Do not say “Claude Code then reads
CLAUDE.md”; that belongs in `CLAUDE.md`.

Required shape (wording may tighten, not add sections):

```markdown
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
```

Keep the `components/agentlens` prohibition in “do not recreate” form so
`agent:contract` does not treat it as an active path.

Subtree files `apps/AGENTS.md`, `packages/AGENTS.md`, and
`native/kernel/AGENTS.md` stay as they are.

## Tool guidance

Each tool file is “read `AGENTS.md` first” plus notes that exist only for
that tool. Do not repeat the code map, check command lists, or the
`components/agentlens` ban.

| File | Keep |
| --- | --- |
| `CLAUDE.md` | Read `AGENTS.md` first. Subagents do not write Lens events; Waygent owns drain and emission. Keep `.claude/` out of git. |
| `GEMINI.md` | Pointer only. No Gemini-specific overrides today. |
| `.cursor/rules/archive.mdc` | Keep `alwaysApply` frontmatter. Body: read `AGENTS.md`, then nearest subtree `AGENTS.md`. |
| `.github/copilot-instructions.md` | Pointer only. |
| `.codex/README.md` | Keep Codex-only facts: committed `config.toml`, no committed execpolicy and why, restart after config changes, link to `docs/operations/codex-local-setup.md`. Point destructive Git boundaries at `AGENTS.md`. Drop duplicated layout/check lists. |

`PLANS.md` and `code_review.md` stay at repo root. Do not copy their
content into `AGENTS.md`. Edit them only if a link this work introduces
would otherwise break.

## Current docs

Folders stay: `docs/architecture/`, `docs/operations/`, `docs/contracts/`,
`docs/getting-started.md`.

| File | Change |
| --- | --- |
| `README.md` | Thin to intro + short first commands + links. |
| `docs/getting-started.md` | Canonical install path. No new overlap with `AGENTS.md`. |
| `docs/architecture/agentlens.md` | `git mv` to `docs/architecture/lens.md`. Title stays “Lens”. Schema name `agentlens.event.v3` stays. |
| `docs/architecture/waygent.md` | Point at `lens.md`. Keep the “who owns what” behavior table. Do not duplicate the `AGENTS.md` package inventory. |
| `docs/architecture/runtime.md` | Remove the “Default gates” command list. Point at `operations/verification.md` and `AGENTS.md` Done. |
| `docs/architecture/decisions.md` | No structural change. Historical `components/agentlens` wording may stay (retired context). |
| `docs/operations/waygent.md` | Relabel `--plan`/`--spec` default dirs as executable paths, not scratch. |
| `docs/roadmap/README.md` | Fix the “proposals until…” sentence only. |
| `docs/contracts/*` | No body rewrite. Edit only if a current-doc link to `agentlens.md` must move. |

Rename rule: update markdown links in current guidance and current docs.
Do not rewrite archive file bodies. If `check-markdown-links` then reports a
historical markdown link to `agentlens.md`, add a one-line stub at
`docs/architecture/agentlens.md` that points to `lens.md` instead of
editing the archive.

## Files this work may edit

- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`
- `.cursor/rules/archive.mdc`
- `.github/copilot-instructions.md`
- `.codex/README.md`
- `README.md`
- `docs/README.md`
- `docs/getting-started.md` (only if a leftover overlap remains)
- `docs/architecture/waygent.md`, `runtime.md`, `agentlens.md` (rename)
- `docs/operations/waygent.md`
- `docs/roadmap/README.md`
- `PLANS.md`, `code_review.md` (link-fix only)
- `scripts/agent/*` tests only if they snapshot old guidance strings

## Verification

Required:

```bash
bun run agent:contract
bun test scripts/agent
bun run agent:verify -- --path AGENTS.md --path CLAUDE.md --path README.md --path docs/README.md
```

Pass every changed path to `agent:verify --path`. That scoped run already
includes `agent:contract`, diff check, and `check-markdown-links` on live
`.md` files (not `docs/superpowers/`). Do not invoke
`check-markdown-links.ts` with zero file arguments; that checks nothing.

Live provider checks stay opt-in and are not part of this work.

`stale_active_claim` must stay green: never present `components/agentlens`
or `AgentLens/` as an active/current/primary location.

Do not require `bun run check`, `waygent:scenarios`, console build, or
`cargo test` unless a test file this work edits forces a narrower rerun.

## Leftover risk

`waygent --plan` / `--spec` still default to `docs/superpowers/`. This
design only relabels that fact. Moving those directories is a later change.
