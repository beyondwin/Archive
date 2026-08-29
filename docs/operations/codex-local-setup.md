# Codex local setup

This repo's files configure repo behavior. Auth, MCP credentials, sandbox
defaults, and retained sessions stay on your machine.

## First run

Trust the checkout in Codex so `AGENTS.md` and `.codex/config.toml` load. Then
from the repo root:

```bash
codex doctor --summary --no-color
bun install --frozen-lockfile
bun run agent:contract
bun run agent:verify -- --dry-run --path README.md
```

`codex doctor` findings about auth or user config are local. An
`agent:contract` failure is a repo blocker. Do not weaken the shared checks to
get past it.

## Reloads

Start a new Codex task after changing `AGENTS.md`, a subtree instruction file,
or project config. Restart Codex if a new task still has the old
`.codex/config.toml`. Opening the same checkout in another profile may need
trust again.

## Keep local

- Provider auth
- MCP credentials and account-specific servers
- User-global model, sandbox, and approval policy
- Env vars and notification prefs
- Retained sessions, runtime evidence, stale worktrees

Wire only the MCP servers this task needs. Do not paste credentials into
committed files.

## Git from Codex

The repo does not commit execpolicy rules. Desktop Full Access tasks skip
interactive approvals, and a project rule that asks for confirmation can
reject ordinary `git status` / `add` / `commit`. Destructive-operation
boundaries stay in `AGENTS.md` and the runner's worktree / protected-ref /
remote-mutation checks.

## Pins

Bun `1.3.10`, Rust `1.95.0`, Ubuntu `24.04`, GitHub Actions by full commit
SHA. Change a pin on purpose, keep local files and workflows in sync, then
rerun `bun run agent:test`, `bun run agent:contract`, and the affected scopes.

CI is not fully hermetic. Runners, Actions, registries, and live providers sit
outside the contract.

Next: [verification](verification.md).
