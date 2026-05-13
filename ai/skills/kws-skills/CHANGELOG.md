# Changelog

## 2.6.0 - 2026-05-13

- `kws-codex-plan-executor`를 Codex-native 계획 실행용 forward skill로 추가했습니다.
- interactive, headless, prompt, handoff mode 계약과 `.codex-orchestrator/state.json` 스키마를 추가했습니다.
- 기존 fresh-session prompt export 계약을 새 executor skill의 `mode=prompt`로 이전했습니다.
- `kws-new-session-plan-prompt-gpt-5-5`를 호환 wrapper로 deprecated 처리했습니다.
- prompt/execution fixture를 검증하는 deterministic eval harness scaffold를 추가했습니다.

## 2.5.0 - 2026-05-13

- `kws-new-session-plan-prompt-gpt-5-5`에 `HISTORY.md`, `ARCHITECTURE.md`, 변경 프로토콜, 평가 fixture, 실험 기록 템플릿을 추가해 점진적 개선 이력을 남길 수 있게 했습니다.
- `kws-new-session-plan-prompt-gpt-5-5`의 개별 스킬 버전을 `2.3.0`으로 갱신했습니다.
- manifest와 README의 개별 스킬 버전 표를 현재 `SKILL.md` metadata와 맞췄습니다.

## 2.4.1 - 2026-05-08

- `kws-new-session-plan-prompt-gpt-5-5`의 기본 로드 경로를 줄이기 위해 Spark scout opt-in 본문과 common mistakes reference를 별도 파일로 분리했습니다.
- fresh-session 템플릿에서 implementation subagent 자기 보고가 review를 대체하지 않도록 `gpt-5.5 high` 두 단계 리뷰 경계를 명확히 했습니다.
- workspace 추론 규칙, prompt-only 검증 체크리스트, OpenAI agent trigger 문구를 개별 스킬 버전 `2.2.3`에 맞춰 갱신했습니다.

## 2.4.0 - 2026-05-08

- `kws-claude-multi-agent-executor` 스킬을 패키지 manifest와 전역 링크 대상에 추가했습니다.
- 패키지 테스트가 `package/*` 스킬과 manifest 목록 불일치를 잡도록 보강했습니다.

## 2.3.0 - 2026-05-08

- `frontend-design` 스킬을 패키지에서 제거했습니다.

## 2.2.0 - 2026-05-05

- `kws setup` 흐름을 위해 Codex와 Claude 전역 스킬 디렉터리에 `kws-skills` 원본을 symlink하는 스크립트를 추가했습니다.
- `kws update`가 link mode metadata를 감지하면 vendor sync 대신 symlink를 재연결하도록 갱신했습니다.
- 설치 metadata에 `mode`와 `provider`를 기록해 link/sync 상태를 구분할 수 있게 했습니다.
- 기존 `ai update` 호환 wrapper를 제거하고 사용자 entrypoint를 `kws`로 단일화했습니다.

## 2.1.2 - 2026-05-05

- `kws-doc-prompt-review`가 Codex `SKILL.md`/skill bundle 리뷰에는 트리거되지 않도록 description과 UI 문구를 명확히 했습니다.
- pasted/standalone docs의 로컬 규칙 적용 예외, 최신 OpenAI guidance 출처 확인, 패치 요청 감지, named safety check 탐색 기준을 보강했습니다.
- manifest, README, sync test를 개별 스킬 버전 `1.0.1`에 맞췄습니다.

## 2.1.1 - 2026-05-05

- `kws-skill-prompt-review`의 guidance 로딩 순서, 스킬 유형별 리뷰 기준, 패치 요청 감지 규칙을 명확히 했습니다.
- bundled GPT-5.5 rubric이 이 스킬에서는 Codex skill bundle에만 적용된다는 범위를 명시했습니다.
- OpenAI agent default prompt를 review-only 기본 동작에 맞추고, manifest, README, sync test를 개별 스킬 버전 `1.0.1`에 맞췄습니다.

## 2.1.0 - 2026-05-05

- `kws-new-session-plan-prompt-gpt-5-5`의 경로 검증, prompt-only 언어/출력 규칙, placeholder 제거 검사를 보강했습니다.
- fresh-session 템플릿의 placeholder를 명시적 `{{...}}` 토큰으로 바꾸고, subagent/model/verification/doc update 지시를 더 짧게 정리했습니다.
- compact 관련 지시를 시스템 compaction을 제어하는 표현 대신 짧은 `HANDOFF CHECKPOINT`와 예외적 `CONTINUATION PROMPT` 규칙으로 바꿨습니다.
- manifest, README, sync test, OpenAI agent default prompt를 개별 스킬 버전 `2.1.0`에 맞췄습니다.

## 2.0.0 - 2026-04-30

- `new-session-plan-prompt-gpt-5-5` 스킬 이름을 `kws-new-session-plan-prompt-gpt-5-5`로 변경했습니다.
- generated prompt 마지막 단계에 `$kws-doc-prompt-review` 기반 전체 프로젝트 문서 검토와 업데이트를 추가했습니다.
- manifest, README, sync test, 전역 스킬 원본을 새 이름과 개별 스킬 버전 `2.0.0`에 맞췄습니다.

## 1.4.0 - 2026-04-30

- `new-session-plan-prompt-gpt-5-5`를 `kws-skill-prompt-review` 기준으로 개선했습니다.
- trigger description, workflow, stop rules, success criteria, pressure scenarios, pre-send checklist를 보강했습니다.
- 전역 스킬과 패키지 원본의 `new-session-plan-prompt-gpt-5-5` 내용을 동기화했습니다.

## 1.3.0 - 2026-04-30

- 각 `SKILL.md` frontmatter에 개별 `metadata.version`과 `metadata.updated_at`을 추가했습니다.
- `manifest.json`에 `skill_versions`를 추가해 패키지 밖에서도 개별 스킬 버전을 확인할 수 있게 했습니다.
- `sync-codex-skills.sh`가 설치 메타데이터 `.kws-skills.json`에 개별 스킬 버전 정보를 함께 기록하도록 갱신했습니다.

## 1.2.0 - 2026-04-30

- `kws-doc-prompt-review` 스킬을 패키지에 추가했습니다.
- `kws-skill-prompt-review` 스킬을 패키지에 추가했습니다.
- GPT-5.5 프롬프팅 기준으로 문서/스킬 리뷰를 분리해 실행할 수 있도록 manifest와 README를 갱신했습니다.

## 1.1.0 - 2026-04-29

- `archive-docs-organizer` 스킬을 패키지에 추가했습니다.
- `new-session-plan-prompt-gpt-5-5` 스킬을 패키지에 추가했습니다.
- 다른 환경에서도 두 스킬을 동기화할 수 있도록 manifest와 README를 갱신했습니다.

## 1.0.1 - 2026-03-16

- 패키지 버전을 `1.0.1`로 올렸습니다.
- `ai upgrade` 이후 설치 메타데이터에서 `1.0.1`을 확인할 수 있도록 검증 기준을 갱신했습니다.

## 1.0.0 - 2026-03-16

- 개인 스킬 원본을 `ai/skills/kws-skills` 패키지로 통합했습니다.
- 개별 스킬 버전 대신 패키지 단일 버전 체계로 전환했습니다.
- Codex 전역 스킬 동기화를 위한 스크립트와 `ai upgrade` 연동 준비를 추가했습니다.

호환성 영향: 개별 스킬 호출 이름은 유지됩니다.
