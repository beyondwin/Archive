#!/usr/bin/env bash
# Fixture: shell script that resolves binary by name through PATH.
exec "$(command -v claude)" "$@"
