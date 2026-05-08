# AI Skills

개인 스킬 패키지의 원본은 `ai/skills/kws-skills`다.

## 원본과 배포

- 실제 스킬 원본: `ai/skills/kws-skills/package/*`
- 패키지 메타데이터: `ai/skills/kws-skills/manifest.json`
- Codex 안정 동기화 스크립트: `ai/skills/kws-skills/scripts/sync-codex-skills.sh`
- Codex/Claude symlink 스크립트: `ai/skills/kws-skills/scripts/link-agent-skills.sh`
- 개별 스킬 버전: 각 `SKILL.md`의 `metadata.version`/`metadata.updated_at`과 `manifest.json`의 `skill_versions`

## 업데이트 흐름

1. 새 머신에서는 `kws setup`으로 Codex와 Claude 양쪽에 symlink한다.
2. 평소에는 `ai/skills/kws-skills/package/*` 아래 원본을 수정한다.
3. 필요하면 각 `SKILL.md` metadata, `manifest.json`, `README.md`, `CHANGELOG.md`를 함께 갱신한다.
4. 전체 도구 업데이트가 필요할 때 `kws update`를 실행한다.
5. `~/.codex/skills/.kws-skills.json` 또는 `~/.claude/skills/.kws-skills.json`으로 설치 상태를 확인한다.

## 버전 규칙

- `major`: 스킬 이름 변경, 설치 구조 변경, `kws update` 계약 변경
- `minor`: 새 스킬 추가, 기능 확장, 패키지 메타데이터 계약 확장
- `patch`: 문구 수정, 구조 정리, 비호환 없는 내부 개선

패키지 버전은 배포 단위이고, 개별 스킬 버전은 `skill_versions`와 `SKILL.md` metadata가 같은 값을 가져야 한다.
