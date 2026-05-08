#!/bin/sh

set -eu

usage() {
  echo "usage: $0 --repo <git-url-or-path> [--ref main] --dest <checkout-dir>" >&2
}

REPO_URL=""
REPO_REF="main"
DEST_DIR=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --ref)
      REPO_REF="${2:-}"
      shift 2
      ;;
    --dest)
      DEST_DIR="${2:-}"
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

if [ -z "$REPO_URL" ] || [ -z "$DEST_DIR" ]; then
  usage
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 1
fi

PARENT_DIR="$(dirname "$DEST_DIR")"
mkdir -p "$PARENT_DIR"

if [ ! -d "$DEST_DIR/.git" ]; then
  git clone --branch "$REPO_REF" --single-branch "$REPO_URL" "$DEST_DIR" >/dev/null 2>&1
else
  git -C "$DEST_DIR" remote set-url origin "$REPO_URL"
  git -C "$DEST_DIR" fetch origin "$REPO_REF" --tags >/dev/null 2>&1
  git -C "$DEST_DIR" checkout -B "$REPO_REF" "origin/$REPO_REF" >/dev/null 2>&1
  git -C "$DEST_DIR" reset --hard "origin/$REPO_REF" >/dev/null 2>&1
  git -C "$DEST_DIR" clean -fd >/dev/null 2>&1
fi

echo "repo updated:"
echo "  - url: $REPO_URL"
echo "  - ref: $REPO_REF"
echo "  - dest: $DEST_DIR"
