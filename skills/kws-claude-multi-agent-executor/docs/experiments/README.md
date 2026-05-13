# Experiments — kws-claude-multi-agent-executor

이 스킬에 대한 비자명한 변경 중 검증할 가설이 있거나, 비자명한 트레이드오프가 있거나, 부정 결과를 낼 수 있는 변경은 여기 자체 실험 기록을 갖습니다.

작은 버그 수정과 자명한 개선은 실험 기록이 필요 없습니다 — git 커밋 + CHANGELOG 항목이면 충분.

## 인덱스

| 실험 | 상태 | 결과 | 기록 |
|------|------|------|------|
| `v2.7-quality-mode` | **CLOSED** (2026-05-13) | `quality_plus` 부정; rubric 인프라 긍정 | [v2.7-quality-mode/](./v2.7-quality-mode/) |
| _(미래 실험이 여기 나열)_ | | | |

## 언제 실험 기록을 시작하나

다음 중 **하나라도** 해당하면 새 `docs/experiments/<version>-<short-name>/` 서브디렉터리 열기:

- SKILL.md 변경이 ≥ 50줄이거나 멀티 파일 동작 변경
- 틀릴 수 있는 가설이 있음 (예: "best-of-N 이 품질 개선")
- 변경이 픽스처나 평가 방법 설계 필요
- 사용자 명확화, advisor 호출, 외부 리뷰가 필요할 것으로 예상
- 비용 > $20 API 또는 > 1시간 실질 작업

변경이 기계적이면(이름 변경, 오타 수정, 의존성 번프): 그냥 커밋. 실험 기록 불필요.

## 구조 (템플릿 사용)

모든 실험 서브디렉터리는 이 레이아웃 따름:

```
docs/experiments/<version>-<name>/
├── README.md              # 한 페이지 개요 + 상태 + 결정 인덱스
├── JOURNAL.md             # 작업의 시간순 narrative
├── decisions/             # 주요 결정마다 짧은 ADR 하나
│   ├── D001-<topic>.md
│   ├── D002-<topic>.md
│   └── ...
└── findings/              # 결과, 데이터, 마감 문서
    ├── F001-<topic>.md
    ├── F002-close-out.md  # ship/skip 권고와 함께 최종 요약
    └── <raw-data-files>
```

스타터 스캐폴드는 `_template/` 참조.

## 필수 문서

마감 시 모든 실험 기록은 다음을 가져야 함:

1. **README.md** — 현재 상태 블록 + 결정 인덱스 + findings 인덱스
2. **JOURNAL.md** — 타임스탬프 포함 시간순 로그:
   - 초기 문제 정의
   - 추론과 함께 각 주요 결정
   - 각 advisor 리뷰 (실제 조언 캡처, 의역 금지)
   - 이유와 함께 각 피벗 또는 범위 변경
   - 최종 마감
3. **적어도 하나의 findings/ 문서** — 무엇이 수집됐고 무엇이 결정됐는지
4. **마감 finding** (`Fnn-close-out.md` 또는 유사) — 명시적 결정: ship / skip / pivot

## 문서화 프로토콜 (실험 실행 에이전트용)

- JOURNAL 을 **진행하면서** 갱신, 끝에서가 아님. 미래의 나와 다른 사람은 결과만이 아니라 *언제 무슨 생각이었는지* 알 필요 있음.
- 다음에 해당하는 결정에 대해 ADR (`D###-<topic>.md`) 작성:
  - 기존 코드만으로는 만들 수 없었음 (판단 필요)
  - 나중에 그럴듯하게 재방문 가능
  - 거부됨 (거부 이유 기록 — 동등하게 가치 있음)
- 커밋 메시지가 ADR ID 참조: 예, `feat(skill): X (per D003)`.
- 마감 시 이 README 의 인덱스와 `../HISTORY.md` §3 갱신.

## 실험 닫기

1. 최종 권고와 함께 `findings/Fnn-close-out.md` 작성
2. 실험 자체의 `README.md` 상태를 CLOSED + outcome 으로 갱신
3. 이 파일의 인덱스 표 갱신
4. 아직 안 됐으면 `HISTORY.md` §3 갱신
5. 메시지 `docs(experiment): close-out v<X.Y>-<name> — <outcome>` 로 커밋
6. 브랜치 전용이면: 산출물로 브랜치 열어둠. 실험에서 무엇이든 출하되면 마감 참조하는 별도 cherry-pick 커밋(들)을 main 으로.

## 실험을 닫지 않을 때

닫지 않고 작업 일시 중지: JOURNAL 에 *남은 일, 차단된 것, 이유* 명시하는 "PAUSED YYYY-MM-DD" 항목 남기기. 미래의 나는 차가운 컨텍스트에서 재개해야 함.
