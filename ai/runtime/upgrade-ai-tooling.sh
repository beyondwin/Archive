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
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
BREW_BIN="${BREW_BIN:-/opt/homebrew/bin/brew}"
CODEX_BIN="${CODEX_BIN:-/opt/homebrew/bin/codex}"
CLAUDE_BIN="${CLAUDE_BIN:-/opt/homebrew/bin/claude}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
CODEX_SKILLS_DIR="$CODEX_HOME/skills"
CLAUDE_SKILLS_DIR="$CLAUDE_HOME/skills"
KWS_VENDOR_DIR="$CODEX_HOME/vendor_imports/kws-skills"
UPDATE_GIT_SOURCE_SCRIPT="$ROOT_DIR/ai/skills/kws-skills/scripts/update-git-source.sh"
SYNC_CODEX_SKILLS_SCRIPT="$ROOT_DIR/ai/skills/kws-skills/scripts/sync-codex-skills.sh"
LINK_AGENT_SKILLS_SCRIPT="$ROOT_DIR/ai/skills/kws-skills/scripts/link-agent-skills.sh"
SKILL_INSTALLER="$CODEX_HOME/skills/.system/skill-installer/scripts/install-skill-from-github.py"
GSTACK_REPO_URL="${GSTACK_REPO_URL:-https://github.com/garrytan/gstack.git}"
GSTACK_REPO_REF="${GSTACK_REPO_REF:-main}"
GSTACK_REPO_DIR="${GSTACK_REPO_DIR:-$HOME/.gstack/repos/gstack}"
SUPERPOWERS_PATHS='
skills/using-git-worktrees
skills/test-driven-development
skills/systematic-debugging
skills/using-superpowers
skills/dispatching-parallel-agents
skills/executing-plans
skills/finishing-a-development-branch
skills/brainstorming
skills/writing-plans
skills/requesting-code-review
skills/receiving-code-review
skills/writing-skills
skills/verification-before-completion
skills/subagent-driven-development
'

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_executable() {
  if [ ! -x "$1" ]; then
    echo "missing required executable: $1" >&2
    exit 1
  fi
}

require_file() {
  if [ ! -f "$1" ]; then
    echo "missing required file: $1" >&2
    exit 1
  fi
}

require_command git
require_command python3
require_executable "$BREW_BIN"
require_executable "$CODEX_BIN"
require_executable "$CLAUDE_BIN"
require_file "$UPDATE_GIT_SOURCE_SCRIPT"
require_file "$SYNC_CODEX_SKILLS_SCRIPT"
require_file "$LINK_AGENT_SKILLS_SCRIPT"
require_file "$SKILL_INSTALLER"

link_source_from_metadata() {
  if [ ! -f "$1" ]; then
    return 0
  fi
  python3 - "$1" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    raise SystemExit(0)

if data.get("mode") == "link" and data.get("source"):
    print(data["source"])
PY
}

repo_url="${AI_REPO_URL:-$(git -C "$ROOT_DIR" remote get-url origin)}"
repo_ref="${AI_REPO_REF:-$(git -C "$ROOT_DIR" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')}"
if [ -z "${repo_ref:-}" ]; then
  repo_ref="main"
fi

echo "==> Upgrading Codex and Claude CLI"
"$BREW_BIN" update
"$BREW_BIN" upgrade --cask codex claude-code
"$CODEX_BIN" --version
"$CLAUDE_BIN" --version

CODEX_LINK_SOURCE="$(link_source_from_metadata "$CODEX_SKILLS_DIR/.kws-skills.json")"
CLAUDE_LINK_SOURCE="$(link_source_from_metadata "$CLAUDE_SKILLS_DIR/.kws-skills.json")"
KWS_LINK_SOURCE="${CODEX_LINK_SOURCE:-$CLAUDE_LINK_SOURCE}"

if [ -n "$KWS_LINK_SOURCE" ]; then
  if [ ! -d "$KWS_LINK_SOURCE/package" ]; then
    echo "kws-skills link source is invalid: $KWS_LINK_SOURCE" >&2
    exit 1
  fi

  echo "==> Relinking kws-skills from $KWS_LINK_SOURCE"
  sh "$LINK_AGENT_SKILLS_SCRIPT" \
    --provider codex \
    --source "$KWS_LINK_SOURCE" \
    --dest "$CODEX_SKILLS_DIR"
  sh "$LINK_AGENT_SKILLS_SCRIPT" \
    --provider claude \
    --source "$KWS_LINK_SOURCE" \
    --dest "$CLAUDE_SKILLS_DIR"
else
  echo "==> Refreshing kws-skills source"
  sh "$UPDATE_GIT_SOURCE_SCRIPT" \
    --repo "$repo_url" \
    --ref "$repo_ref" \
    --dest "$KWS_VENDOR_DIR"

  echo "==> Syncing kws-skills into $CODEX_SKILLS_DIR"
  sh "$SYNC_CODEX_SKILLS_SCRIPT" \
    --source "$KWS_VENDOR_DIR/ai/skills/kws-skills" \
    --dest "$CODEX_SKILLS_DIR" \
    --repo-url "$repo_url" \
    --ref "$repo_ref"
fi

echo "==> Reinstalling superpowers from obra/superpowers@main"
mkdir -p "$CODEX_SKILLS_DIR"
for skill_path in $SUPERPOWERS_PATHS; do
  skill_name="$(basename "$skill_path")"
  rm -rf "$CODEX_SKILLS_DIR/$skill_name"
done

python3 "$SKILL_INSTALLER" \
  --repo obra/superpowers \
  --ref main \
  --path $SUPERPOWERS_PATHS

echo "==> Refreshing gstack source"
sh "$UPDATE_GIT_SOURCE_SCRIPT" \
  --repo "$GSTACK_REPO_URL" \
  --ref "$GSTACK_REPO_REF" \
  --dest "$GSTACK_REPO_DIR"

echo "==> Reinstalling gstack for Codex"
(
  cd "$GSTACK_REPO_DIR"
  ./setup --host codex -q
)

echo "==> Upgrade complete"
