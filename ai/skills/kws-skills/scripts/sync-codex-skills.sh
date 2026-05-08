#!/bin/sh

set -eu

usage() {
  echo "usage: $0 [--source /path/to/ai/skills/kws-skills] [--dest /path/to/codex/skills] [--repo-url <git-url>] [--ref <git-ref>]" >&2
}

SOURCE_DIR=""
DEST_DIR="${HOME}/.codex/skills"
REPO_URL=""
REPO_REF=""

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
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --ref)
      REPO_REF="${2:-}"
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

if [ -z "$SOURCE_DIR" ]; then
  SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
  SOURCE_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
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

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required" >&2
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

UPDATED_AT="$(python3 - <<'PY' "$MANIFEST_PATH"
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(data["updated_at"])
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

  if [ -L "$DEST_SKILL_DIR" ] || [ -f "$DEST_SKILL_DIR" ]; then
    rm -rf "$DEST_SKILL_DIR"
  fi

  mkdir -p "$DEST_SKILL_DIR"
  rsync -a --delete "$SOURCE_SKILL_DIR"/ "$DEST_SKILL_DIR"/
done

INSTALLED_AT="$(date '+%Y-%m-%dT%H:%M:%S%z')"
python3 - "$MANIFEST_PATH" "$METADATA_PATH" "$SOURCE_DIR" "$INSTALLED_AT" "$REPO_URL" "$REPO_REF" <<'PY'
import json, sys
manifest_path, metadata_path, source_dir, installed_at, repo_url, ref = sys.argv[1:7]
with open(manifest_path, encoding="utf-8") as fh:
    manifest = json.load(fh)
payload = {
    "name": manifest["name"],
    "version": manifest["version"],
    "updated_at": manifest["updated_at"],
    "mode": "sync",
    "provider": "codex",
    "installed_at": installed_at,
    "source": source_dir,
    "skills": manifest["skills"],
    "skill_versions": manifest.get("skill_versions", {}),
}
if repo_url:
    payload["repo_url"] = repo_url
if ref:
    payload["ref"] = ref
with open(metadata_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY

echo "kws-skills version: $VERSION"
echo "skills synced:"
for skill in $SKILLS; do
  echo "  - $skill"
done
if [ -n "$REPO_URL" ]; then
  echo "source repo: $REPO_URL"
fi
if [ -n "$REPO_REF" ]; then
  echo "source ref: $REPO_REF"
fi
