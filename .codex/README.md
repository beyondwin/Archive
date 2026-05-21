# Codex Project Configuration

This directory contains project-scoped Codex configuration that is safe to
commit. Local runtime state still belongs in ignored directories such as
`.codex-orchestrator/`, `.orchestrator/`, `.agentlens/`, and `.claude/`.

Useful files:

- `config.toml` - project defaults for Codex sessions opened in this repo.
- `rules/*.rules` - command approval/safety rules loaded when this trusted
  project's `.codex` layer is active.

Restart Codex or start a new session after changing these files.
