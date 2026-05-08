#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)"
UPDATE_SCRIPT="$ROOT_DIR/ai/runtime/upgrade-ai-tooling.sh"
MANIFEST="$ROOT_DIR/ai/skills/kws-skills/manifest.json"
SKILLS="$(python3 - "$MANIFEST" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(" ".join(data["skills"]))
PY
)"

assert_file() {
  if [ ! -f "$1" ]; then
    echo "missing file: $1" >&2
    exit 1
  fi
}

assert_dir() {
  if [ ! -d "$1" ]; then
    echo "missing dir: $1" >&2
    exit 1
  fi
}

assert_file "$UPDATE_SCRIPT"
assert_file "$MANIFEST"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

TEST_HOME="$TMP_DIR/home"
TEST_BIN="$TMP_DIR/bin"
TEST_CODEX_HOME="$TEST_HOME/.codex"
TEST_CLAUDE_HOME="$TEST_HOME/.claude"
TEST_INSTALLER_DIR="$TEST_CODEX_HOME/skills/.system/skill-installer/scripts"
TEST_GSTACK_SRC="$TMP_DIR/gstack-src"
TEST_LOG_DIR="$TMP_DIR/logs"

mkdir -p "$TEST_HOME" "$TEST_BIN" "$TEST_INSTALLER_DIR" "$TEST_LOG_DIR" "$TEST_CODEX_HOME/skills" "$TEST_CLAUDE_HOME/skills"

cat >"$TEST_BIN/brew" <<'EOF'
#!/bin/sh
echo "brew $*" >>"$TEST_LOG_DIR/brew.log"
exit 0
EOF
chmod +x "$TEST_BIN/brew"

cat >"$TEST_BIN/codex" <<'EOF'
#!/bin/sh
echo "codex $*" >>"$TEST_LOG_DIR/codex.log"
if [ "${1:-}" = "--version" ]; then
  echo "codex 0.0.0-test"
fi
exit 0
EOF
chmod +x "$TEST_BIN/codex"

cat >"$TEST_BIN/claude" <<'EOF'
#!/bin/sh
echo "claude $*" >>"$TEST_LOG_DIR/claude.log"
if [ "${1:-}" = "--version" ]; then
  echo "claude 0.0.0-test"
fi
exit 0
EOF
chmod +x "$TEST_BIN/claude"

cat >"$TEST_INSTALLER_DIR/install-skill-from-github.py" <<'EOF'
#!/usr/bin/env python3
import os
from pathlib import Path

log_dir = Path(os.environ["TEST_LOG_DIR"])
log_dir.mkdir(parents=True, exist_ok=True)
(log_dir / "skill-installer.log").write_text(" ".join(os.sys.argv[1:]) + "\n", encoding="utf-8")
EOF
chmod +x "$TEST_INSTALLER_DIR/install-skill-from-github.py"

mkdir -p "$TEST_GSTACK_SRC"
git -C "$TEST_GSTACK_SRC" init -b main >/dev/null 2>&1
cat >"$TEST_GSTACK_SRC/setup" <<'EOF'
#!/bin/sh
set -eu
printf '%s\n' "$*" >"$HOME/.gstack-setup-args"
touch "$HOME/.gstack-setup-ran"
EOF
chmod +x "$TEST_GSTACK_SRC/setup"
git -C "$TEST_GSTACK_SRC" add setup
git -C "$TEST_GSTACK_SRC" -c user.name='Test User' -c user.email='test@example.com' commit -m "init gstack" >/dev/null 2>&1

cat >"$TEST_CODEX_HOME/skills/.kws-skills.json" <<EOF
{
  "name": "kws-skills",
  "version": "2.2.0",
  "mode": "link",
  "provider": "codex",
  "source": "$ROOT_DIR/ai/skills/kws-skills"
}
EOF

cat >"$TEST_CLAUDE_HOME/skills/.kws-skills.json" <<EOF
{
  "name": "kws-skills",
  "version": "2.2.0",
  "mode": "link",
  "provider": "claude",
  "source": "$ROOT_DIR/ai/skills/kws-skills"
}
EOF

env \
  HOME="$TEST_HOME" \
  CODEX_HOME="$TEST_CODEX_HOME" \
  CLAUDE_HOME="$TEST_CLAUDE_HOME" \
  BREW_BIN="$TEST_BIN/brew" \
  CODEX_BIN="$TEST_BIN/codex" \
  CLAUDE_BIN="$TEST_BIN/claude" \
  TEST_LOG_DIR="$TEST_LOG_DIR" \
  AI_REPO_URL="$ROOT_DIR" \
  AI_REPO_REF="main" \
  GSTACK_REPO_URL="$TEST_GSTACK_SRC" \
  GSTACK_REPO_REF="main" \
  sh "$UPDATE_SCRIPT"

assert_file "$TEST_HOME/.gstack-setup-ran"
assert_dir "$TEST_HOME/.gstack/repos/gstack/.git"
assert_file "$TEST_CODEX_HOME/skills/.kws-skills.json"
assert_file "$TEST_CLAUDE_HOME/skills/.kws-skills.json"
grep -q '"mode":[[:space:]]*"link"' "$TEST_CODEX_HOME/skills/.kws-skills.json"
grep -q '"mode":[[:space:]]*"link"' "$TEST_CLAUDE_HOME/skills/.kws-skills.json"
grep -q "\"source\":[[:space:]]*\"$ROOT_DIR/ai/skills/kws-skills\"" "$TEST_CODEX_HOME/skills/.kws-skills.json"
grep -q "\"source\":[[:space:]]*\"$ROOT_DIR/ai/skills/kws-skills\"" "$TEST_CLAUDE_HOME/skills/.kws-skills.json"

for skill in $SKILLS; do
  if [ ! -L "$TEST_CODEX_HOME/skills/$skill" ]; then
    echo "missing codex symlink: $skill" >&2
    exit 1
  fi
  if [ ! -L "$TEST_CLAUDE_HOME/skills/$skill" ]; then
    echo "missing claude symlink: $skill" >&2
    exit 1
  fi
done

if [ -d "$TEST_CODEX_HOME/vendor_imports/kws-skills/.git" ]; then
  echo "kws link mode should not refresh vendor source" >&2
  exit 1
fi
