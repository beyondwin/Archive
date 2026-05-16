#!/usr/bin/env bash
# archive_run.sh - Tar + redact the .orchestrator/ dir of a finished run for forensics.
#
# Usage:
#   archive_run.sh --worktree <abs_path> --run-id <id> [--outcome <success|blocked|aborted>]
#
# Writes:
#   $HOME/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run-id>/artifacts/
#     - state.final.json     (copy of .orchestrator/state.json)
#     - orchestrator.tar.gz  (redacted)
#     - archive_meta.json    (metadata describing the archive)
#   And updates <worktree>/.orchestrator/state.json with an "archive" field.
#
# Exit codes:
#   0  success
#   1  hard failure (state copy, tar build, or final mv)
#   2  best-effort partial (tar created, redaction failed)
#   3  bad CLI args
set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REDACT_PY="${SCRIPT_DIR}/redact_archive.py"

usage() {
  echo "Usage: archive_run.sh --worktree <abs_path> --run-id <id> [--outcome <success|blocked|aborted>]" >&2
}

# ---- arg parse ----
WORKTREE=""
RUN_ID=""
OUTCOME=""

while [ $# -gt 0 ]; do
  case "$1" in
    --worktree)
      WORKTREE="${2:-}"
      shift 2
      ;;
    --run-id)
      RUN_ID="${2:-}"
      shift 2
      ;;
    --outcome)
      OUTCOME="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "archive_run.sh: unknown arg: $1" >&2
      usage
      exit 3
      ;;
  esac
done

if [ -z "${WORKTREE}" ] || [ -z "${RUN_ID}" ]; then
  usage
  exit 3
fi

if [ ! -d "${WORKTREE}/.orchestrator" ]; then
  echo "archive_run.sh: ${WORKTREE}/.orchestrator does not exist" >&2
  exit 1
fi

# ---- step 1+2: target dir ----
DATE_DIR="$(date +%Y-%m-%d)"
TARGET_DIR="${HOME}/.claude/learning/kws-claude-multi-agent-executor/runs/${DATE_DIR}/${RUN_ID}/artifacts"
mkdir -p "${TARGET_DIR}"

# ---- step 3: copy state.json -> state.final.json ----
SRC_STATE="${WORKTREE}/.orchestrator/state.json"
DST_STATE="${TARGET_DIR}/state.final.json"
if [ ! -f "${SRC_STATE}" ]; then
  echo "archive_run.sh: missing ${SRC_STATE}" >&2
  exit 1
fi
if ! cp "${SRC_STATE}" "${DST_STATE}"; then
  echo "archive_run.sh: failed to copy state.json" >&2
  exit 1
fi

# ---- step 4+5: tar -> tempfile (exclude transient files) ----
TMP_TAR="$(mktemp -t archive_run.XXXXXX).tar.gz"
cleanup_tmp_tar() {
  if [ -n "${TMP_TAR:-}" ] && [ -f "${TMP_TAR}" ]; then
    rm -f "${TMP_TAR}" || true
  fi
}

EXCLUDES=(
  --exclude='*.appended'
  --exclude='headless.pid'
  --exclude='exec/'
  --exclude='hooks/'
  --exclude='*.tar.gz'
)

TAR_ERR_LOG="$(mktemp -t archive_run_tarerr.XXXXXX)"
if ! tar -czf "${TMP_TAR}" -C "${WORKTREE}" "${EXCLUDES[@]}" .orchestrator/ 2>"${TAR_ERR_LOG}"; then
  echo "archive_run.sh: tar failed:" >&2
  cat "${TAR_ERR_LOG}" >&2 2>/dev/null || true
  rm -f "${TAR_ERR_LOG}"
  cleanup_tmp_tar
  exit 1
fi
rm -f "${TAR_ERR_LOG}"

# ---- step 6: redact (best-effort) ----
REDACTION_APPLIED="false"
REDACTION_REPLACEMENTS=0
REDACTION_ERROR=""

# Detect repo_root via git; fall back to worktree path.
REPO_ROOT=""
if command -v git >/dev/null 2>&1; then
  REPO_ROOT="$(git -C "${WORKTREE}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="${WORKTREE}"
fi

META_JSON="$(WORKTREE="${WORKTREE}" REPO_ROOT="${REPO_ROOT}" python3 -c '
import json, os
print(json.dumps({"worktree_path": os.environ["WORKTREE"], "repo_root": os.environ["REPO_ROOT"]}))
')"

REDACT_RC=0
REDACT_OUT="$(python3 "${REDACT_PY}" "${TMP_TAR}" --meta "${META_JSON}" 2>&1)" || REDACT_RC=$?

if [ "${REDACT_RC}" -eq 0 ]; then
  REDACTION_APPLIED="true"
  REDACTION_REPLACEMENTS="$(printf '%s' "${REDACT_OUT}" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(int(d.get("replacements", 0)))
except Exception:
    print(0)
')"
else
  REDACTION_APPLIED="false"
  REDACTION_ERROR="${REDACT_OUT}"
  echo "archive_run.sh: redaction failed (rc=${REDACT_RC}): ${REDACT_OUT}" >&2
fi

# ---- step 7: mv tempfile -> final orchestrator.tar.gz ----
FINAL_TAR="${TARGET_DIR}/orchestrator.tar.gz"
if ! mv "${TMP_TAR}" "${FINAL_TAR}"; then
  echo "archive_run.sh: failed to move tempfile to ${FINAL_TAR}" >&2
  cleanup_tmp_tar
  exit 1
fi
TMP_TAR=""  # moved; do not clean up

# ---- step 8: compute file counts + write archive_meta.json ----
TAR_SIZE_BYTES=$(wc -c <"${FINAL_TAR}" | tr -d ' ')
STATE_SIZE_BYTES=$(wc -c <"${DST_STATE}" | tr -d ' ')
TAR_INNER_COUNT=$(tar -tzf "${FINAL_TAR}" 2>/dev/null | grep -v '/$' | wc -l | tr -d ' ' || echo 0)
ARCHIVED_AT="$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')"

META_PATH="${TARGET_DIR}/archive_meta.json"

TAR_SIZE_BYTES="${TAR_SIZE_BYTES}" \
STATE_SIZE_BYTES="${STATE_SIZE_BYTES}" \
TAR_INNER_COUNT="${TAR_INNER_COUNT}" \
ARCHIVED_AT="${ARCHIVED_AT}" \
REDACTION_APPLIED="${REDACTION_APPLIED}" \
REDACTION_REPLACEMENTS="${REDACTION_REPLACEMENTS}" \
REDACTION_ERROR="${REDACTION_ERROR}" \
META_PATH="${META_PATH}" \
python3 <<'PYEOF'
import json, os

meta = {
    "tar_path": "artifacts/orchestrator.tar.gz",
    "tar_size_bytes": int(os.environ.get("TAR_SIZE_BYTES", "0") or 0),
    "state_final_path": "artifacts/state.final.json",
    "state_final_size_bytes": int(os.environ.get("STATE_SIZE_BYTES", "0") or 0),
    "redaction_applied": os.environ.get("REDACTION_APPLIED", "false") == "true",
    "redaction_replacements": int(os.environ.get("REDACTION_REPLACEMENTS", "0") or 0),
    "exclude_globs": ["*.appended", "headless.pid", "exec/", "hooks/", "*.tar.gz"],
    "archived_at": os.environ.get("ARCHIVED_AT", ""),
    "archived_by": "v2.14",
    "source_worktree": "<WORKTREE>",
    "tar_inner_file_count": int(os.environ.get("TAR_INNER_COUNT", "0") or 0),
}
err = os.environ.get("REDACTION_ERROR", "")
if err and not meta["redaction_applied"]:
    meta["error"] = err

with open(os.environ["META_PATH"], "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2, sort_keys=True)
    f.write("\n")
PYEOF

# ---- step 9: update state.json's "archive" field atomically ----
STATE_PATH="${SRC_STATE}" \
ARCHIVE_TAR_REL="${FINAL_TAR}" \
ARCHIVED_AT="${ARCHIVED_AT}" \
REDACTION_APPLIED="${REDACTION_APPLIED}" \
REDACTION_REPLACEMENTS="${REDACTION_REPLACEMENTS}" \
python3 <<'PYEOF'
import json, os, tempfile

state_path = os.environ["STATE_PATH"]
with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

state["archive"] = {
    "tar_path": os.environ.get("ARCHIVE_TAR_REL", ""),
    "archived_at": os.environ.get("ARCHIVED_AT", ""),
    "redaction_applied": os.environ.get("REDACTION_APPLIED", "false") == "true",
    "redaction_replacements": int(os.environ.get("REDACTION_REPLACEMENTS", "0") or 0),
}

dir_ = os.path.dirname(state_path) or "."
fd, tmp = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=dir_)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(state, out, indent=2, sort_keys=True)
        out.write("\n")
    os.replace(tmp, state_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
PYEOF

if [ "${REDACTION_APPLIED}" = "true" ]; then
  exit 0
else
  exit 2
fi
