#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
ARCHIVE_ROOT="$(CDPATH= cd -- "$ROOT_DIR/../../.." && pwd)"
MANIFEST="$ROOT_DIR/manifest.json"
CHANGELOG="$ROOT_DIR/CHANGELOG.md"
SYNC_SCRIPT="$ROOT_DIR/scripts/sync-codex-skills.sh"
INSTALL_SCRIPT="$ROOT_DIR/scripts/install-codex-skills.sh"
UPDATE_GIT_SOURCE_SCRIPT="$ROOT_DIR/scripts/update-git-source.sh"
LINK_AGENT_SKILLS_SCRIPT="$ROOT_DIR/scripts/link-agent-skills.sh"
PACKAGE_DIR="$ROOT_DIR/package"
SKILLS="$(python3 - "$MANIFEST" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(" ".join(data["skills"]))
PY
)"
VERSION="$(python3 - "$MANIFEST" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(data["version"])
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

assert_file "$MANIFEST"
assert_file "$CHANGELOG"
assert_file "$SYNC_SCRIPT"
assert_file "$INSTALL_SCRIPT"
assert_file "$UPDATE_GIT_SOURCE_SCRIPT"
assert_file "$LINK_AGENT_SKILLS_SCRIPT"
assert_dir "$PACKAGE_DIR"
if [ -e "$PACKAGE_DIR/new-session-plan-prompt-gpt-5-5" ]; then
  echo "old skill name should not exist: $PACKAGE_DIR/new-session-plan-prompt-gpt-5-5" >&2
  exit 1
fi

for skill in $SKILLS; do
  assert_dir "$PACKAGE_DIR/$skill"
  assert_file "$PACKAGE_DIR/$skill/SKILL.md"
  grep -q '^metadata:' "$PACKAGE_DIR/$skill/SKILL.md"
  grep -q '^[[:space:]]*version:[[:space:]]*"' "$PACKAGE_DIR/$skill/SKILL.md"
  grep -q '^[[:space:]]*updated_at:[[:space:]]*"' "$PACKAGE_DIR/$skill/SKILL.md"
done

python3 - "$MANIFEST" $SKILLS <<'PY'
import json, sys
import re
from pathlib import Path
manifest_path, *skills = sys.argv[1:]
package_dir = Path(manifest_path).parent / "package"
with open(manifest_path, encoding="utf-8") as fh:
    data = json.load(fh)
skill_versions = data.get("skill_versions")
if not isinstance(skill_versions, dict):
    raise SystemExit("manifest missing skill_versions object")
for skill in skills:
    item = skill_versions.get(skill)
    if not isinstance(item, dict):
        raise SystemExit(f"manifest missing skill_versions entry for {skill}")
    if not item.get("version") or not item.get("updated_at"):
        raise SystemExit(f"manifest missing version or updated_at for {skill}")
    skill_md = (package_dir / skill / "SKILL.md").read_text(encoding="utf-8")
    version_match = re.search(r'(?m)^[ \t]*version:[ \t]*"([^"]+)"[ \t]*$', skill_md)
    updated_match = re.search(r'(?m)^[ \t]*updated_at:[ \t]*"([^"]+)"[ \t]*$', skill_md)
    if not version_match or not updated_match:
        raise SystemExit(f"SKILL.md missing metadata version or updated_at for {skill}")
    if item["version"] != version_match.group(1) or item["updated_at"] != updated_match.group(1):
        raise SystemExit(f"manifest and SKILL.md metadata differ for {skill}")
PY

TMP_DEST="$(mktemp -d)"
TMP_GIT_DEST="$(mktemp -d)"
trap 'rm -rf "$TMP_DEST" "$TMP_GIT_DEST"' EXIT INT TERM

sh "$UPDATE_GIT_SOURCE_SCRIPT" \
  --repo "$ARCHIVE_ROOT" \
  --ref main \
  --dest "$TMP_GIT_DEST/repo"

assert_dir "$TMP_GIT_DEST/repo/.git"
assert_file "$TMP_GIT_DEST/repo/ai/skills/kws-skills/manifest.json"

sh "$SYNC_SCRIPT" \
  --source "$ROOT_DIR" \
  --dest "$TMP_DEST" \
  --repo-url "$ARCHIVE_ROOT" \
  --ref main

for skill in $SKILLS; do
  assert_dir "$TMP_DEST/$skill"
  assert_file "$TMP_DEST/$skill/SKILL.md"
done

assert_file "$TMP_DEST/.kws-skills.json"

grep -q '"name":[[:space:]]*"kws-skills"' "$MANIFEST"
grep -q "\"version\":[[:space:]]*\"$VERSION\"" "$MANIFEST"
grep -q "\"version\":[[:space:]]*\"$VERSION\"" "$TMP_DEST/.kws-skills.json"
grep -q '"skill_versions"' "$TMP_DEST/.kws-skills.json"
for skill in $SKILLS; do
  grep -q "\"$skill\"" "$TMP_DEST/.kws-skills.json"
done
grep -q '"repo_url"' "$TMP_DEST/.kws-skills.json"
grep -q '"ref"' "$TMP_DEST/.kws-skills.json"

python3 - "$TMP_DEST/.kws-skills.json" $SKILLS <<'PY'
import json, sys
metadata_path, *skills = sys.argv[1:]
with open(metadata_path, encoding="utf-8") as fh:
    data = json.load(fh)
skill_versions = data.get("skill_versions")
if not isinstance(skill_versions, dict):
    raise SystemExit("installed metadata missing skill_versions object")
for skill in skills:
    item = skill_versions.get(skill)
    if not isinstance(item, dict):
        raise SystemExit(f"installed metadata missing skill_versions entry for {skill}")
    if not item.get("version") or not item.get("updated_at"):
        raise SystemExit(f"installed metadata missing version or updated_at for {skill}")
PY

assert_file "$ARCHIVE_ROOT/ai/README.md"
assert_file "$ARCHIVE_ROOT/ai/runtime/init.zsh"
assert_file "$ARCHIVE_ROOT/ai/runtime/upgrade-ai-tooling.sh"
assert_file "$ARCHIVE_ROOT/ai/dotfiles/examples/chezmoi.toml"
assert_file "$ARCHIVE_ROOT/ai/docs/install.md"
assert_file "$ARCHIVE_ROOT/ai/docs/dotfiles.md"
assert_file "$ARCHIVE_ROOT/ai/docs/skills.md"
assert_file "$ARCHIVE_ROOT/ai/docs/providers.md"
assert_file "$ARCHIVE_ROOT/ai/docs/conventions.md"
