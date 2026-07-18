# Codex Project Configuration

This directory contains project-scoped Codex configuration that is safe to
commit. Local runtime state still belongs in ignored directories such as
`.waygent/`, `.codex-orchestrator/`, `.orchestrator/`, `.agentlens/`, and
`.claude/`.

Useful files:

- `config.toml` - project defaults for Codex sessions opened in this repo.
- `rules/*.rules` - command approval/safety rules loaded when this trusted
  project's `.codex` layer is active.

These rules are repository-local. They do not change user-global authentication,
MCP, sandbox, or approval configuration and do not protect other repositories.
All Git commands currently prompt because execpolicy matches literal leading
tokens; the extra read-only prompts close bypasses through global Git options,
while direct hard reset and force push remain forbidden.

Restart Codex or start a new task after changing these files. See the
[local setup guide](../docs/operations/codex-local-setup.md) for trust, reload,
tool-version, and local-state boundaries.
