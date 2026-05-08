#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

STUB_SETUP="$TMP_DIR/setup.sh"
STUB_UPDATE="$TMP_DIR/update.sh"
STUB_CLEAN="$TMP_DIR/clean.sh"
CALL_LOG="$TMP_DIR/calls.log"

cat >"$STUB_SETUP" <<'EOF'
#!/bin/sh
echo "setup:$*" >>"$KWS_TEST_CALL_LOG"
EOF
chmod +x "$STUB_SETUP"

cat >"$STUB_UPDATE" <<'EOF'
#!/bin/sh
echo "update:$*" >>"$KWS_TEST_CALL_LOG"
EOF
chmod +x "$STUB_UPDATE"

cat >"$STUB_CLEAN" <<'EOF'
#!/bin/sh
echo "clean:$*" >>"$KWS_TEST_CALL_LOG"
EOF
chmod +x "$STUB_CLEAN"

KWS_TEST_CALL_LOG="$CALL_LOG" \
ARCHIVE_HOME="$ROOT_DIR" \
KWS_SETUP_SCRIPT_OVERRIDE="$STUB_SETUP" \
KWS_UPDATE_SCRIPT_OVERRIDE="$STUB_UPDATE" \
KWS_CLEAN_SCRIPT_OVERRIDE="$STUB_CLEAN" \
zsh -f <<'EOF'
set -eu
source "$ARCHIVE_HOME/ai/runtime/init.zsh"

whence -w kws >/dev/null
if whence -w ai >/dev/null 2>&1; then
  echo "ai compatibility function should not be defined" >&2
  exit 1
fi

kws setup
kws update --dry-run
kws clean
kws clean apply
kws clean java
kws clean foreign
kws clean all
kws clean help

if kws unknown 2>/dev/null; then
  echo "kws unknown should fail" >&2
  exit 1
fi
EOF

grep -q '^setup:$' "$CALL_LOG"
grep -q '^update:--dry-run$' "$CALL_LOG"
grep -q '^clean:$' "$CALL_LOG"
grep -q '^clean:--apply$' "$CALL_LOG"
grep -q '^clean:--apply --build-daemons$' "$CALL_LOG"
grep -q '^clean:--apply --foreign-mcp$' "$CALL_LOG"
grep -q '^clean:--apply --build-daemons --foreign-mcp$' "$CALL_LOG"
grep -q '^clean:--help$' "$CALL_LOG"
if [ "$(grep -c '^update:--dry-run$' "$CALL_LOG")" -ne 1 ]; then
  echo "expected kws update to call update script once" >&2
  exit 1
fi
