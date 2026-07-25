# Codex Local Setup

This guide prepares a local Codex installation to use Archive's committed
agent contract. Repository files configure only repository behavior; account
authentication, MCP credentials, sandbox and approval defaults, and retained
sessions remain machine-local operator concerns.

## Prerequisites And First Run

Trust the checkout in Codex before expecting `AGENTS.md` or the project
`.codex/config.toml` layer to load. Then run these commands from the repository
root:

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
`.codex/config.toml` in a new task. Existing tasks can retain the instructions
and configuration loaded when they started.

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

## Command Safety

Archive does not commit repository-local Codex execpolicy rules. Desktop Full
Access tasks use non-interactive approvals, and a project rule that requests
confirmation can otherwise reject routine Git commands such as status, add,
and commit. Follow `AGENTS.md` destructive-operation boundaries and use the
repository's isolated worktree, protected-ref, and remote-mutation checks for
automated plan execution.

## Version And CI Pin Updates

The repository pins Bun `1.3.10`, Rust `1.95.0`, Ubuntu `24.04`, and GitHub
Actions by full commit SHA. Update a pin intentionally in a reviewed change,
keep the local pin files and workflow values synchronized, and rerun
`bun run agent:test`, `bun run agent:contract`, and the affected verification
scopes.

These pins make the declared toolchain reproducible, but CI is not fully
hermetic. GitHub-hosted runners, GitHub Actions availability, package
registries, and tool distribution services remain operational dependencies.
Provider authentication and live model availability are not part of the CI
contract.

Continue with the [verification guide](verification.md) for path-aware local and
CI gates.
