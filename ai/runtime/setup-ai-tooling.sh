#!/bin/sh

set -eu

usage() {
  echo "usage: $0 [--help]" >&2
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

if [ $# -gt 0 ]; then
  usage
  exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
ROOT_DIR="${ARCHIVE_HOME:-$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)}"
ROOT_DIR="$(CDPATH= cd -- "$ROOT_DIR" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
KWS_SOURCE_DIR="$ROOT_DIR/ai/skills/kws-skills"
LINK_AGENT_SKILLS_SCRIPT="$KWS_SOURCE_DIR/scripts/link-agent-skills.sh"

if [ ! -f "$LINK_AGENT_SKILLS_SCRIPT" ]; then
  echo "missing required file: $LINK_AGENT_SKILLS_SCRIPT" >&2
  exit 1
fi

echo "==> Linking kws-skills for Codex"
sh "$LINK_AGENT_SKILLS_SCRIPT" \
  --provider codex \
  --source "$KWS_SOURCE_DIR" \
  --dest "$CODEX_HOME/skills"

echo "==> Linking kws-skills for Claude"
sh "$LINK_AGENT_SKILLS_SCRIPT" \
  --provider claude \
  --source "$KWS_SOURCE_DIR" \
  --dest "$CLAUDE_HOME/skills"

echo "==> kws setup complete"
