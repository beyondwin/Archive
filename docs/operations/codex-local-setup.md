# Codex Local Setup

This guide prepares a local Codex installation to use Archive's committed
agent contract. Repository files configure only repository behavior; account
authentication, MCP credentials, sandbox and approval defaults, and retained
sessions remain machine-local operator concerns.

## Prerequisites And First Run

Use Codex `0.144.1` or newer locally. That is the minimum version this
repository supports for the tested `codex execpolicy` contract. CI installs
Codex `0.144.6` exactly.

Trust the checkout in Codex before expecting `AGENTS.md` or the project
`.codex/config.toml` and `.codex/rules/` layer to load. Then run these commands
from the repository root:

```bash
codex doctor --summary --no-color
bun install --frozen-lockfile
bun run agent:contract
bun run agent:verify -- --dry-run --path README.md
```

Treat `codex doctor` findings about authentication, user configuration, or
external services as local-environment findings. A failure from
`agent:contract` is a repository-contract blocker and should not be bypassed by
weakening the shared checks.

## Reload Boundaries

Start a new Codex task after changing `AGENTS.md`, a nearest subtree instruction
file, or project configuration. Restart Codex when the client does not reload
`.codex/config.toml` or `.codex/rules/` in a new task. Existing tasks can retain
the instructions and configuration loaded when they started.

Repository trust is also a local client decision. Opening the same checkout in
another Codex installation or profile may require trusting it again.

## Local-Only State

Keep the following outside the repository:

- provider authentication and account credentials;
- MCP server credentials and account-specific server configuration;
- user-global model, sandbox, and approval policy;
- local environment variables and notification preferences;
- retained task sessions, runtime evidence, and stale worktrees.

Configure only the MCP servers and environment variables required for the
current work. Periodically review retained sessions and stale worktrees, but do
not delete active worktrees or evidence automatically. Never paste credentials
into committed configuration or documentation.

## Repository-Local Command Policy

The rules in `.codex/rules/archive.rules` apply only while this trusted
repository's project layer is active; they do not protect other repositories.
Direct hard reset and `--force`/`-f` push forms are forbidden. Cleanup, branch
deletion, worktree removal, and `--force-with-lease` history rewrites require
operator confirmation.

All project Git commands currently prompt, including read-only commands. This
is an intentional safety/usability tradeoff: Codex execpolicy rules match
literal leading tokens, so a broad `git` prompt prevents global Git options or
alternate spellings from bypassing narrower destructive-command rules. Expect
extra confirmations until execpolicy can safely express those combinations.

## Version And CI Pin Updates

The repository pins Bun `1.3.10`, Codex `0.144.6`, Rust `1.95.0`, Ubuntu
`24.04`, and GitHub Actions by full commit SHA. Update a pin intentionally in a
reviewed change, keep the local pin files and workflow values synchronized, and
rerun `bun run agent:test`, `bun run agent:contract`, and the affected
verification scopes.

These pins make the declared toolchain reproducible, but CI is not fully
hermetic. GitHub-hosted runners, GitHub Actions availability, package
registries, and tool distribution services remain operational dependencies.
Provider authentication and live model availability are not part of the CI
contract.

Continue with the [verification guide](verification.md) for path-aware local and
CI gates.
