# AI Workspace

`ai` 디렉터리는 개인 AI 작업 자산을 운영 영역별로 나눠 관리한다.
성공 기준은 새 셸에서 `kws setup`, `kws update`, `kws clean`이 같은 runtime
원본을 통해 동작하고, Codex/Claude 스킬 원본은 한 곳에서 관리되는 것이다.

## 구조

- `runtime/`: `kws` shell 함수, setup/update/cleanup entrypoint, runtime 테스트
- `dotfiles/`: `chezmoi` source tree와 예시 설정
- `skills/`: 실제 스킬 원본 패키지
- `docs/`: 설치, 운영, provider 차이 문서

## 어디를 수정하나

스킬 본문이나 배포 스크립트를 수정할 때는 항상 `ai/skills/kws-skills` 아래를 수정한다.
shell 함수나 업그레이드 흐름을 바꿀 때는 `ai/runtime` 아래를 수정한다.
dotfile bootstrap을 바꿀 때는 `ai/dotfiles` 아래를 수정한다.

## 운영 흐름

1. 새 머신에서 `kws setup` 실행
2. `ai/skills/kws-skills/package/*`에서 원본 수정
3. 전체 도구 업데이트가 필요할 때 `kws update` 실행
4. Codex/Codex app 작업 뒤 남은 MCP/tool process가 있으면 `kws clean`으로 확인하고 필요할 때 적용
5. `~/.codex/skills/.kws-skills.json` 또는 `~/.claude/skills/.kws-skills.json`으로 설치 상태 확인

## `kws` 명령

| 명령 | 동작 |
| --- | --- |
| `kws setup` | `kws-skills` 원본을 Codex와 Claude 전역 스킬 디렉터리에 symlink한다. |
| `kws update` | CLI, 외부 스킬, symlink/link mode 상태를 최신화한다. |
| `kws clean` | stale Codex tool/MCP process 후보를 dry-run으로 출력한다. |
| `kws clean apply` | 기본 cleanup 후보 process group에 TERM을 보낸다. |
| `kws clean java` | 기본 cleanup을 적용하고 Gradle daemon도 `gradle --stop`으로 정리한다. |
| `kws clean foreign` | 기본 cleanup에 더해 다른 CLI agent가 띄운 MCP 후보까지 정리한다. |
| `kws clean all` | 기본 cleanup, Gradle daemon, foreign MCP cleanup을 모두 적용한다. |

`kws update`는 아래를 한 번에 수행한다.

- `codex` CLI Homebrew 업그레이드
- `claude` CLI Homebrew 업그레이드
- link mode에서는 `kws-skills` Codex/Claude symlink 보존 및 재연결
- sync mode에서는 `kws-skills` Git 원본 갱신 및 Codex 전역 스킬 동기화
- `superpowers`를 `obra/superpowers` 최신 `main`으로 재설치
- `gstack`를 최신 원본으로 갱신하고 Codex 전역 스킬 재설치

## Shell Sync

- `~/.zprofile`은 repo 루트의 `.chezmoiroot`가 가리키는 `ai/dotfiles/chezmoi` source tree에서 관리한다.
- 실제 `kws` 함수 정의는 `ai/runtime/init.zsh`에 두고 `~/.zprofile`은 bootstrap만 담당한다.
- 기존 터미널에서 runtime을 고친 뒤에는 `source ~/.zprofile`을 실행하거나 새 터미널을 열어 함수 정의를 다시 로드한다.
- 초기 설정과 운영 문서는 `ai/docs/*`를 따른다.
