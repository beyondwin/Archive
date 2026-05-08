# AI Install

이 저장소의 AI 운영 환경은 `ai/runtime`, `ai/dotfiles`, `ai/skills`, `ai/docs` 네 영역으로 나뉜다.

## 새 머신 설정

1. `Archive`를 원하는 위치에 checkout 한다. 이 문서의 예시는
   `$HOME/source/private/Archive`를 사용한다.
2. `brew install chezmoi`
3. `mkdir -p ~/.config/chezmoi`
4. `ai/dotfiles/examples/chezmoi.toml`을 참고해 `~/.config/chezmoi/chezmoi.toml`을 만든다.
5. `chezmoi init --apply "$HOME/source/private/Archive"`
6. 새 셸을 열고 `type kws`, `type codex`, `type claude`를 확인한다.
7. `kws setup`을 실행해 `kws-skills`를 Codex와 Claude에 symlink한다.
8. 필요할 때 `kws update`를 실행해 CLI와 외부 스킬 설치 상태를 맞춘다.
   link mode에서는 `kws-skills` symlink를 보존하고, `superpowers`, `gstack`까지 함께 갱신한다.
9. Codex tool/MCP process cleanup을 쓰려면 `ai/runtime/codex-clean-agent-processes`가 executable인지 확인한다.

## Runtime 확인

- `type kws`는 `ai/runtime/init.zsh`에서 로드된 shell function을 보여야 한다.
- `kws`만 실행했을 때 usage는 `usage: kws {setup|update|clean}`이어야 한다.
- `kws clean`은 process를 종료하지 않고 cleanup 후보만 출력해야 한다.
- 기존 터미널에 예전 함수가 남아 있으면 `source ~/.zprofile`을 실행한다.

## 운영 원칙

- `~/.zprofile`은 직접 수정하지 않고 `chezmoi`로 생성한다.
- shell 함수 원본은 `ai/runtime/init.zsh`만 사용한다.
- `~/.codex`와 `~/.claude` 전체는 관리하지 않고 필요한 `kws-skills`만 `kws setup`으로 symlink한다.
- cleanup helper는 전체 `node`/`java`/`chrome`을 죽이지 않고 알려진 Codex tool/MCP command만 좁게 매칭해야 한다.
