# kws-skills

개인적으로 쓰는 AI 스킬을 한 패키지로 관리하는 루트다.

## 목적

- 흩어진 개인 스킬을 `kws-skills` 하나로 관리한다.
- 패키지 버전은 배포 단위로 관리하고, 개별 스킬 버전은 각 스킬의 내용 변경 추적에 사용한다.
- 실제 Codex에서는 계속 개별 스킬로 설치되어 사용한다.
- `kws setup`은 Codex와 Claude의 전역 스킬 디렉터리에 원본 스킬을 symlink한다.
- `kws update`는 전체 AI 도구를 갱신하되, symlink 모드에서는 `kws-skills` 링크를 보존한다.

## 현재 버전

- 패키지 버전: `2.3.0`
- 마지막 갱신일: `2026-05-08`

## 포함된 스킬

- `archive-docs-organizer`
- `kws-doc-prompt-review`
- `kws-new-session-plan-prompt-gpt-5-5`
- `kws-skill-prompt-review`
- `reflective-essay-writer`
- `reflective-writing-coach`

## 개별 스킬 버전

| 스킬 | 버전 | 갱신일 |
| --- | --- | --- |
| `archive-docs-organizer` | `1.1.1` | `2026-04-30` |
| `kws-doc-prompt-review` | `1.0.1` | `2026-05-05` |
| `kws-new-session-plan-prompt-gpt-5-5` | `2.1.0` | `2026-05-05` |
| `kws-skill-prompt-review` | `1.0.1` | `2026-05-05` |
| `reflective-essay-writer` | `1.0.1` | `2026-04-30` |
| `reflective-writing-coach` | `1.0.1` | `2026-04-30` |

## 구조

```text
ai/skills/kws-skills/
  manifest.json
  CHANGELOG.md
  package/
  scripts/
```

## 운영 규칙

- 원본 스킬은 `ai/skills/kws-skills/package/*`만 사용한다.
- Codex 개발 모드 대상은 `~/.codex/skills/<skill-name>` symlink다.
- Claude 개발 모드 대상은 `~/.claude/skills/<skill-name>` symlink다.
- 안정 sync 대상은 기존처럼 Codex `~/.codex/skills/<skill-name>` 복사본이다.
- 개별 스킬 버전과 갱신일은 각 `SKILL.md`의 `metadata`와 `manifest.json`의 `skill_versions`를 함께 맞춘다.
- 운영 문서는 `ai/docs/skills.md`, `ai/docs/providers.md`를 참고한다.
- 패키지 버전은 배포 단위로 관리하고, 개별 스킬 버전은 각 스킬의 내용 변경 추적에 사용한다.

## 버전 규칙

- `major`: 스킬 이름 변경, 설치 구조 변경, `kws update` 동기화 계약 변경
- `minor`: 새 스킬 추가, 기존 스킬 기능 확장, 패키지 메타데이터 계약 확장
- `patch`: 문구 수정, 예시 보강, 구조 정리, 비호환 없는 내부 개선

## 업데이트 방법

1. 새 머신에서는 `kws setup`을 실행해 Codex와 Claude 양쪽에 symlink한다.
2. 평소에는 `ai/skills/kws-skills/package/*` 아래 원본만 수정한다.
3. 전체 도구 업데이트가 필요할 때 `kws update`를 실행한다.
4. `~/.codex/skills/.kws-skills.json` 또는 `~/.claude/skills/.kws-skills.json`으로 link/sync 모드와 git 상태를 확인한다.
