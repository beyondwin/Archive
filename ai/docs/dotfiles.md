# AI Dotfiles

`chezmoi` source tree는 `ai/dotfiles/chezmoi`에 있다. repo 루트의 `.chezmoiroot`는 이 경로를 가리킨다.

## 관리 범위

- 현재 1차 범위는 `~/.zprofile` bootstrap만 포함한다.
- bootstrap은 `ARCHIVE_HOME`, `AI_MACHINE_PROFILE`을 export한 뒤 `ai/runtime/init.zsh`를 source한다.
- `~/.codex`, 캐시, 세션 파일은 `chezmoi` 관리 대상이 아니다.
- cleanup helper 원본은 `ai/runtime/codex-clean-agent-processes`다. `~/.codex/bin` 같은 로컬 bin 디렉터리는 기본적으로 `chezmoi` 관리 대상이 아니다.

## 로컬 설정 계약

`~/.config/chezmoi/chezmoi.toml`에는 아래 값이 필요하다.

- `sourceDir`: 현재 작업 중인 `Archive` checkout 경로
- `archiveHome`: runtime이 참조할 `Archive` 절대 경로
- `machineProfile`: `personal` 또는 `work`

예시는 `ai/dotfiles/examples/chezmoi.toml`을 사용한다.

## 검증

- `chezmoi doctor`
- `chezmoi diff`
- `chezmoi apply --dry-run --verbose`
- `zsh -n ~/.zprofile`
- `zsh -n "$ARCHIVE_HOME/ai/runtime/init.zsh"`
- 새 셸에서 `kws clean` dry-run 확인
