#!/usr/bin/env bash
# Fixture: cmux launcher signature (find_real_claude + HOOKS_JSON)
find_real_claude() {
  command -v claude
}
HOOKS_JSON='{"pre":"","post":""}'
exec "$(find_real_claude)" "$@"
