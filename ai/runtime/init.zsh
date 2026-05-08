# Shared KWS shell entrypoints loaded from ~/.zprofile via chezmoi.

if [[ -z "${ARCHIVE_HOME:-}" ]]; then
  echo "kws shell init: ARCHIVE_HOME is not set. Configure it via ~/.config/chezmoi/chezmoi.toml." >&2
  return 1
fi

if [[ ! -d "$ARCHIVE_HOME" ]]; then
  echo "kws shell init: ARCHIVE_HOME '$ARCHIVE_HOME' does not exist." >&2
  return 1
fi

KWS_SETUP_SCRIPT="${KWS_SETUP_SCRIPT_OVERRIDE:-$ARCHIVE_HOME/ai/runtime/setup-ai-tooling.sh}"
KWS_UPDATE_SCRIPT="${KWS_UPDATE_SCRIPT_OVERRIDE:-$ARCHIVE_HOME/ai/runtime/upgrade-ai-tooling.sh}"
KWS_CLEAN_SCRIPT="${KWS_CLEAN_SCRIPT_OVERRIDE:-$ARCHIVE_HOME/ai/runtime/codex-clean-agent-processes}"

if [[ ! -x "$KWS_SETUP_SCRIPT" ]]; then
  echo "kws shell init: missing executable $KWS_SETUP_SCRIPT." >&2
  return 1
fi

if [[ ! -x "$KWS_UPDATE_SCRIPT" ]]; then
  echo "kws shell init: missing executable $KWS_UPDATE_SCRIPT." >&2
  return 1
fi

alias cc='claude --dangerously-skip-permissions'

codex() {
  if [[ "$1" == "upgrade" || "$1" == "upgarde" || "$1" == "update" ]]; then
    shift
    brew update && brew upgrade --cask codex && /opt/homebrew/bin/codex --version
    return $?
  fi

  /opt/homebrew/bin/codex "$@"
}

claude() {
  if [[ "$1" == "upgrade" || "$1" == "upgarde" || "$1" == "update" ]]; then
    shift
    brew update && brew upgrade --cask claude-code && /opt/homebrew/bin/claude --version
    return $?
  fi

  /opt/homebrew/bin/claude "$@"
}

kws() {
  local subcommand="${1:-}"

  if [[ "$subcommand" == "setup" ]]; then
    shift
    "$KWS_SETUP_SCRIPT" "$@"
    return $?
  fi

  if [[ "$subcommand" == "upgrade" || "$subcommand" == "upgarde" || "$subcommand" == "update" ]]; then
    shift
    "$KWS_UPDATE_SCRIPT" "$@"
    return $?
  fi

  if [[ "$subcommand" == "clean" ]]; then
    if [[ ! -x "$KWS_CLEAN_SCRIPT" ]]; then
      echo "kws clean: missing executable $KWS_CLEAN_SCRIPT." >&2
      return 1
    fi

    shift
    local mode="${1:-dry}"
    case "$mode" in
      dry|"")
        "$KWS_CLEAN_SCRIPT"
        ;;
      apply|now)
        "$KWS_CLEAN_SCRIPT" --apply
        ;;
      java|build)
        "$KWS_CLEAN_SCRIPT" --apply --build-daemons
        ;;
      foreign)
        "$KWS_CLEAN_SCRIPT" --apply --foreign-mcp
        ;;
      all)
        "$KWS_CLEAN_SCRIPT" --apply --build-daemons --foreign-mcp
        ;;
      help|-h|--help)
        "$KWS_CLEAN_SCRIPT" --help
        ;;
      *)
        echo "usage: kws clean {dry|apply|java|foreign|all|help}" >&2
        return 1
        ;;
    esac
    return $?
  fi

  echo "usage: kws {setup|update|clean}" >&2
  return 1
}
