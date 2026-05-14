# shellcheck shell=zsh

# Intentional interactive shortcut for Claude Code.
# This overrides macOS `/usr/bin/cc` in zsh sessions where this file is sourced.
if command -v claude >/dev/null 2>&1; then
  alias cc='claude --dangerously-skip-permissions'
fi
