#!/bin/sh

set -eu

usage() {
  echo "usage: $0 --provider <codex|claude> --dest <skills-dir> [--source /path/to/ai/skills/kws-skills]" >&2
}

SOURCE_DIR=""
DEST_DIR=""
PROVIDER=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      SOURCE_DIR="${2:-}"
      shift 2
      ;;
    --dest)
      DEST_DIR="${2:-}"
      shift 2
      ;;
    --provider)
      PROVIDER="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done

case "$PROVIDER" in
  codex|claude)
    ;;
  *)
    usage
    exit 1
    ;;
esac

if [ -z "$SOURCE_DIR" ]; then
  SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
  SOURCE_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
else
  SOURCE_DIR="$(CDPATH= cd -- "$SOURCE_DIR" && pwd)"
fi

if [ -z "$DEST_DIR" ]; then
  usage
  exit 1
fi

MANIFEST_PATH="$SOURCE_DIR/manifest.json"
SKILLS_SOURCE_DIR="$SOURCE_DIR/package"
METADATA_PATH="$DEST_DIR/.kws-skills.json"

if [ ! -f "$MANIFEST_PATH" ]; then
  echo "missing manifest: $MANIFEST_PATH" >&2
  exit 1
fi

if [ ! -d "$SKILLS_SOURCE_DIR" ]; then
  echo "missing skills dir: $SKILLS_SOURCE_DIR" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"

VERSION="$(python3 - <<'PY' "$MANIFEST_PATH"
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(data["version"])
PY
)"

SKILLS="$(python3 - <<'PY' "$MANIFEST_PATH"
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
for item in data["skills"]:
    print(item)
PY
)"

if [ -z "$SKILLS" ]; then
  echo "manifest has no skills" >&2
  exit 1
fi

for skill in $SKILLS; do
  SOURCE_SKILL_DIR="$SKILLS_SOURCE_DIR/$skill"
  DEST_SKILL_DIR="$DEST_DIR/$skill"

  if [ ! -f "$SOURCE_SKILL_DIR/SKILL.md" ]; then
    echo "missing SKILL.md for $skill" >&2
    exit 1
  fi

  if [ -e "$DEST_SKILL_DIR" ] || [ -L "$DEST_SKILL_DIR" ]; then
    rm -rf "$DEST_SKILL_DIR"
  fi

  ln -s "$SOURCE_SKILL_DIR" "$DEST_SKILL_DIR"
done

GIT_BRANCH=""
GIT_COMMIT=""
GIT_DIRTY="false"
if command -v git >/dev/null 2>&1 && git -C "$SOURCE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_BRANCH="$(git -C "$SOURCE_DIR" branch --show-current 2>/dev/null || true)"
  GIT_COMMIT="$(git -C "$SOURCE_DIR" rev-parse --short HEAD 2>/dev/null || true)"
  if [ -n "$(git -C "$SOURCE_DIR" status --porcelain 2>/dev/null)" ]; then
    GIT_DIRTY="true"
  fi
fi

LINKED_AT="$(date '+%Y-%m-%dT%H:%M:%S%z')"
python3 - "$MANIFEST_PATH" "$METADATA_PATH" "$SOURCE_DIR" "$PROVIDER" "$DEST_DIR" "$LINKED_AT" "$GIT_BRANCH" "$GIT_COMMIT" "$GIT_DIRTY" <<'PY'
import json
import sys

manifest_path, metadata_path, source_dir, provider, dest_dir, linked_at, branch, commit, dirty = sys.argv[1:10]
with open(manifest_path, encoding="utf-8") as fh:
    manifest = json.load(fh)
payload = {
    "name": manifest["name"],
    "version": manifest["version"],
    "updated_at": manifest["updated_at"],
    "mode": "link",
    "provider": provider,
    "source": source_dir,
    "target": dest_dir,
    "linked_at": linked_at,
    "skills": manifest["skills"],
    "skill_versions": manifest.get("skill_versions", {}),
    "git_dirty": dirty == "true",
}
if branch:
    payload["git_branch"] = branch
if commit:
    payload["git_commit"] = commit
with open(metadata_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY

echo "kws-skills version: $VERSION"
echo "provider: $PROVIDER"
echo "mode: link"
echo "skills linked:"
for skill in $SKILLS; do
  echo "  - $skill"
done
