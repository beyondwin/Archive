# AI Conventions

## 구조 원칙

- runtime 원본은 `ai/runtime/*`만 사용한다.
- dotfiles 템플릿과 예시는 `ai/dotfiles/*`만 사용한다.
- 스킬 원본은 `ai/skills/kws-skills/package/*`만 사용한다.
- 운영 문서는 `ai/docs/*`만 사용한다.

## Source Of Truth

- `~/.zprofile`은 직접 수정하지 않고 `chezmoi`가 생성한다.
- shell 함수 정의는 `ai/runtime/init.zsh`만 canonical하며, 사용자용 entrypoint는 `kws`다.
- 문서는 실행 원본을 복사해 적지 않고 실제 runtime 경로를 참조한다.
- provider 차이는 `ai/docs/providers.md`에만 기록한다.
- `kws clean`류 process cleanup은 allowlist 기반으로 좁게 매칭한다. `pkill node`, `pkill java`, `killall chrome`처럼 광범위한 cleanup을 runtime 기본값으로 넣지 않는다.
- runtime 함수 변경 뒤 기존 터미널에서 증상이 재현되면 먼저 `source ~/.zprofile` 또는 새 셸로 재로딩 여부를 확인한다.

## Migration Snapshot

- 과거의 `ai/providers/*`, `ai/shared/*`, 루트 `chezmoi/` 분리는 정리 대상이다.
- 현재 기준 경로는 `ai/runtime`, `ai/dotfiles`, `ai/skills`, `ai/docs`다.
