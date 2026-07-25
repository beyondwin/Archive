# Codex Project Configuration

This directory contains project-scoped Codex configuration that is safe to
commit. Local runtime state still belongs in ignored directories such as
`.waygent/`, `.codex-orchestrator/`, `.orchestrator/`, `.agentlens/`, and
`.claude/`.

Useful files:

- `config.toml` - project defaults for Codex sessions opened in this repo.

Archive intentionally does not commit repository-local execpolicy rules.
Desktop Full Access sessions disable interactive approvals, so project rules
that request confirmation can reject ordinary Git commands instead of showing
an approval prompt. Destructive-operation boundaries remain in `AGENTS.md`,
isolated runner worktrees, protected-ref checks, and remote-mutation guards.

Restart Codex or start a new task after changing project configuration. See the
[local setup guide](../docs/operations/codex-local-setup.md) for trust, reload,
tool-version, and local-state boundaries.
