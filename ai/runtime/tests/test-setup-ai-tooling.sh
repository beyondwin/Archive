#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)"
SETUP_SCRIPT="$ROOT_DIR/ai/runtime/setup-ai-tooling.sh"
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

assert_link() {
  if [ ! -L "$1" ]; then
    echo "missing symlink: $1" >&2
    exit 1
  fi
}

assert_file "$SETUP_SCRIPT"
assert_file "$MANIFEST"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

TEST_HOME="$TMP_DIR/home"
TEST_CODEX_HOME="$TEST_HOME/.codex"
TEST_CLAUDE_HOME="$TEST_HOME/.claude"
mkdir -p "$TEST_HOME"

HOME="$TEST_HOME" \
CODEX_HOME="$TEST_CODEX_HOME" \
CLAUDE_HOME="$TEST_CLAUDE_HOME" \
ARCHIVE_HOME="$ROOT_DIR" \
sh "$SETUP_SCRIPT"

for skill in $SKILLS; do
  assert_link "$TEST_CODEX_HOME/skills/$skill"
  assert_file "$TEST_CODEX_HOME/skills/$skill/SKILL.md"
  assert_link "$TEST_CLAUDE_HOME/skills/$skill"
  assert_file "$TEST_CLAUDE_HOME/skills/$skill/SKILL.md"
done

assert_file "$TEST_CODEX_HOME/skills/.kws-skills.json"
assert_file "$TEST_CLAUDE_HOME/skills/.kws-skills.json"
grep -q '"mode":[[:space:]]*"link"' "$TEST_CODEX_HOME/skills/.kws-skills.json"
grep -q '"mode":[[:space:]]*"link"' "$TEST_CLAUDE_HOME/skills/.kws-skills.json"
grep -q "\"source\":[[:space:]]*\"$ROOT_DIR/ai/skills/kws-skills\"" "$TEST_CODEX_HOME/skills/.kws-skills.json"
grep -q "\"source\":[[:space:]]*\"$ROOT_DIR/ai/skills/kws-skills\"" "$TEST_CLAUDE_HOME/skills/.kws-skills.json"

python3 - "$TEST_CODEX_HOME/skills/.kws-skills.json" "$TEST_CLAUDE_HOME/skills/.kws-skills.json" "$ROOT_DIR" <<'PY'
import json
import sys
from pathlib import Path

codex_metadata, claude_metadata, root = sys.argv[1:]
for provider, metadata_path in (("codex", codex_metadata), ("claude", claude_metadata)):
    with open(metadata_path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("mode") != "link":
        raise SystemExit(f"{provider} metadata should record link mode")
    if data.get("provider") != provider:
        raise SystemExit(f"{provider} metadata should record provider")
    if data.get("source") != str(Path(root) / "ai/skills/kws-skills"):
        raise SystemExit(f"{provider} metadata should record source path")
    if "git_commit" not in data or "git_dirty" not in data:
        raise SystemExit(f"{provider} metadata should include git state")
PY
