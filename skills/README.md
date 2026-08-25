# skills/

이 디렉터리는 Archive가 관리하는 일반 스킬의 원본이다.

## 스킬

| 스킬 | 용도 |
| --- | --- |
| [`korean-writing-editor`](./korean-writing-editor/) | 이미 있는 한국어 글을 뜻과 말투를 유지하며 교정·윤문합니다. |
| [`image-workbench`](./image-workbench/) | 프로젝트에 맞는 래스터 자산을 계획·생성·편집·검토합니다. Codex 전용입니다. |

## 쓰지 말아야 할 때

일상 한국어 대화·번역·초안·요약·코드 리뷰·검출 회피는 `korean-writing-editor`가 아니다. 한 장짜리 취미 이미지·SVG/아이콘/실제 UI 구현은 `image-workbench`가 아니다.

## 설치

설치 스크립트는 없습니다. `korean-writing-editor`는 `~/.agents/skills/korean-writing-editor`에 사본을 두고, Claude Code는 그 사본을 `~/.claude/skills/korean-writing-editor`로 링크하거나 복사합니다. `image-workbench`는 Codex 전용이며 `~/.agents/skills/image-workbench`만 설치합니다. 홈의 실제 디렉터리는 확인 없이 덮어쓰지 않습니다.

## 호출

Codex는 `$korean-writing-editor`와 `$image-workbench`로 호출합니다. Claude Code, Cursor, Grok Build는 `/korean-writing-editor`와 `/image-workbench`로 호출합니다.

## `_legacy`

`_legacy`는 위 표에 없고 이 가이드로 설치하지 않으며 동결입니다. 규칙은 [`_legacy/README.md`](./_legacy/README.md)를 보세요.

## 새 일반 스킬

새 일반 스킬은 [`adding-a-skill.md`](./adding-a-skill.md)를 따릅니다.
