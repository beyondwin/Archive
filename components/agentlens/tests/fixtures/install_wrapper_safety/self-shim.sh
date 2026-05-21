#!/usr/bin/env bash
# Self-shim: would re-enter `agentlens run --agent claude_code` and loop.
exec "$INSTALLED_AGENTLENS_BIN" run --agent claude_code -- "$@"
