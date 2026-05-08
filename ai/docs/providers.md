# AI Providers

## Codex

- `kws-skills`는 `kws setup`으로 `~/.codex/skills/<skill-name>`에 symlink된다.
- `kws update`는 Codex CLI 업그레이드, link mode 보존, `superpowers` 재설치, `gstack` Codex 재설치를 수행한다.
- `gstack`는 Codex에서 `~/.codex/skills/gstack*` 형태로 설치된다.
- `kws clean`은 Codex CLI/Codex app이 남긴 알려진 tool/MCP process 후보를 dry-run으로 보여주고, `kws clean apply`부터 종료를 적용한다.
- 기본 cleanup 후보는 Codex app `node_repl`, Playwright MCP, PointPatch MCP, Pencil MCP, Computer Use MCP처럼 Codex tool/MCP로 식별되는 command다.
- `kws clean foreign`은 Claude 등 다른 CLI agent가 소유한 MCP process group까지 종료할 수 있으므로, 실행 전 dry-run 출력의 owner/command를 확인한다.

## Claude

- Claude CLI는 `kws update`로 Homebrew 업그레이드를 수행한다.
- `kws-skills`는 `kws setup`으로 `~/.claude/skills/<skill-name>`에 symlink된다.
- `gstack` README의 Team mode 자동 업데이트는 Claude Code 세션 시작 훅 기준이다.
- Claude용 별도 복사본은 만들지 않고 공통 원본을 symlink한다.
- Claude가 띄운 context7/serena 같은 foreign MCP는 기본 `kws clean apply` 대상이 아니다. 필요할 때만 `kws clean foreign` 또는 `kws clean all`을 사용한다.
