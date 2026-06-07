# Eval 커버리지 — MAST 실패-분류 매핑

> **권위 문서**: 이 파일은 `evals/` 픽스처 스위트가 어떤 멀티에이전트 실패모드를
> 커버하는지의 *권위 매핑*이다. 새 픽스처를 추측으로 추가하지 말 것 — 먼저 이 표의
> 갭을 보고, 어떤 미커버 모드를 운동시킬지 정한 뒤 추가한다.
>
> 짝 설계 문서: [개선 플랜 v2.30](./improvements/품질개선-v2.30-플랜-ko.md) §2.2,
> [구현 명세 v2.30](./improvements/품질개선-v2.30-구현-ko.md) J1.
> 도출 실험: [v2.30-failure-taxonomy-coverage](./experiments/v2.30-failure-taxonomy-coverage/README.md).
> 작성: 2026-06-08.

---

## §1. MAST — 14 실패모드 / 3 범주

MAST(Multi-Agent System failure Taxonomy)는 멀티에이전트 LLM 시스템 실패를 14개
모드 / 3개 범주로 분류한다. 1,642개 트레이스 주석에서 도출되었고, 실패의
**~42% 가 스펙·설계 / ~37% 가 에이전트간 조정 / ~21% 가 검증·종료** 단계에서
발생한다고 보고한다.

출처: Cemri et al. 2025, *"Why Do Multi-Agent LLM Systems Fail?"* (arXiv 2503.13657).
정리: <https://www.augmentcode.com/guides/why-multi-agent-llm-systems-fail-and-how-to-fix-them>.

| 범주 | 코드 | 실패모드 | 한 줄 의미 |
|------|------|----------|------------|
| **1. 스펙·설계** (~42%) | FM-1.1 | 태스크 스펙 불복 (Disobey task specification) | 명시된 태스크 요구를 따르지 않음 |
| | FM-1.2 | 역할 스펙 불복 (Disobey role specification) | 부여된 역할 경계를 벗어남 |
| | FM-1.3 | 단계 반복 (Step repetition) | 이미 끝낸 단계를 불필요하게 재실행 |
| | FM-1.4 | 대화 히스토리 손실 (Loss of conversation history) | 앞선 맥락을 잃고 일관성 붕괴 |
| | FM-1.5 | 종료 조건 미인지 (Unaware of termination conditions) | 끝내야 할/멈춰야 할 시점을 모름 |
| **2. 에이전트간 조정** (~37%) | FM-2.1 | 대화 리셋 (Conversation reset) | 진행 맥락이 리셋되어 처음부터 |
| | FM-2.2 | 명확화 요청 실패 (Fail to ask for clarification) | 모호할 때 묻지 않고 추측 진행 |
| | FM-2.3 | 태스크 이탈 (Task derailment) | 선언 범위를 벗어나거나 잘못된 입력을 사실로 전파 |
| | FM-2.4 | 정보 은폐 (Information withholding) | 알아낸 사실을 하류에 전달 안 함 |
| | FM-2.5 | 타 에이전트 입력 무시 (Ignored other agent's input) | 동료 에이전트 산출을 반영 안 함 |
| | FM-2.6 | 추론-행동 불일치 (Reasoning-action mismatch) | 추론과 실제 행동이 어긋남 |
| **3. 검증·종료** (~21%) | FM-3.1 | 조기 종료 (Premature termination) | 검증 전에 끝내버림 |
| | FM-3.2 | 미/불완전 검증 (No or incomplete verification) | 검증을 안 하거나 일부만 |
| | FM-3.3 | 부정확 검증 / 고무도장 (Incorrect verification) | 잘못된 산출을 "통과"로 승인 |

---

## §2. 픽스처 ↔ 실패모드 매핑

각 픽스처가 **의도적으로 운동시키는** 실패모드. 각 픽스처 YAML 최상단의
`mast_coverage:` 주석과 1:1 일치한다(아래 §4 갱신 프로토콜).

| 픽스처 | 유형 | `mast_coverage` | 무엇을 운동시키나 |
|--------|------|-----------------|-------------------|
| `01-trivial-typo` | 정상 | `[FM-1.1]` | 최소 태스크에서 스펙 준수 + 오케스트레이터 비우회 |
| `02-three-file-refactor` | 정상 | `[FM-1.1, FM-2.3]` | 다중 파일 범위 — Files-block 부분집합 준수(이탈 방지) |
| `03-add-new-feature` | 정상 | `[FM-1.1, FM-3.2]` | 신규 기능 스펙 준수 + Verifier 전체 스위트 |
| `04-cross-plan-handoff` | 멀티플랜 | `[FM-1.4, FM-2.1]` | plan_chain 핸드오프에서 히스토리/맥락 보존 |
| `05-ambiguous-spec` | expected-halt | `[FM-2.2]` | 모호 스펙에서 추측 대신 Ambiguity Gate 정지 |
| `06-flaky-test-recovery` | 정상 | `[FM-3.2, FM-2.6]` | retry 회복 + 추론대로 검증 실행 |
| `07-low-batch-heavy` | 정상 | `[FM-3.2, FM-1.5]` | LOW 배치 sweep 검증 + finalize 종료 인지 |
| `08-subtle-input-validation` | 적대적 | `[FM-1.1, FM-3.3]` | 미묘한 엣지케이스 — Reviewer Spec Walk 가 누락 적발 |
| `09-spec-intent-uncovered` | 프로브(검출-후-수정) | `[FM-3.3, FM-1.1]` | **고무도장**: 기존 테스트는 통과하나 미커버 스펙 거동 위반 |
| `10-error-propagation` | 프로브(검출-후-수정) | `[FM-2.3, FM-3.2]` | **오류 전파**: 태스크 1 잠복 결함이 태스크 2 로 전파 |

> 픽스처가 아닌 **가드레일**이 커버하는 모드는 §3 의 "가드레일 커버" 열에 기록한다.
> 픽스처와 가드레일은 다른 계층이며, eval 커버리지는 *픽스처* 가 무엇을 측정하는지를
> 다룬다.

---

## §3. 갭 목록 + 재방문 트리거

미/약 커버 모드. 각 항목은 **현 커버**(픽스처/가드레일) + **갭** + **재방문 트리거**
(추측이 아니라 실측 조건)를 갖는다.

| 코드 | 현 커버 | 갭 | 재방문 트리거 |
|------|---------|----|--------------|
| FM-1.2 역할 스펙 불복 | 가드레일("Orchestrator never writes code"), SubagentStop 훅 | 픽스처 없음 (가드레일만) | 역할 경계 위반 사고가 `events.jsonl` 에 표면화 |
| FM-1.3 단계 반복 | 없음 | **resume/압축 후 완료 태스크 재실행 프로브 없음** | 실제 재실행 사고가 코퍼스에 표면화 → resume 프로브 픽스처 |
| FM-1.4 대화 히스토리 손실 | 픽스처 04, Resume Chain, state.json 진실원 | 약 — 핸드오프 1건만 | cross-plan 히스토리 손실 회귀 관측 |
| FM-1.5 종료 조건 미인지 | Stop-훅 강제(v2.26–28), finalize_run, 픽스처 07 | eval 직접검증 없음(가드레일 의존) | finalize 강제 회귀 우려 시 종료-프로브 픽스처 |
| FM-2.4 정보 은폐 | 구조화 출력 계약(STATUS/SUMMARY/FILES) | 픽스처 없음 | 산출 누락 사고 표면화 |
| FM-2.5 타 에이전트 입력 무시 | `previous_issues` 주입, decisions_register | 픽스처 없음 | decision_conflict 가 다운스트림 실패와 상관 |
| FM-3.1 조기 종료 | Stop-훅, polite-stop 금지 가드레일(v2.10.1) | 픽스처 없음 | 조기 종료 사고 표면화 |
| **FM-3.3 고무도장** | 픽스처 08(적대 입력), Spec Walk | ~~green-build + wrong-behavior 미커버~~ → **픽스처 09 로 이 라운드 구현** | (해소) |
| **오류 전파**(FM-2.3 표현) | Files-block 부분집합 검증(약) | ~~다단 전파 체인 없음~~ → **픽스처 10 으로 이 라운드 구현** | (해소) |

### 이번 라운드(v2.30 P0)에서 닫은 갭

- **FM-3.3 고무도장** → 픽스처 `09-spec-intent-uncovered`. 코드가 부트스트랩
  레포의 기존(불완전) 테스트는 통과하지만 스펙이 요구하는 미커버 거동을 위반하는
  상황을 심는다. 파이프라인(Reviewer Spec Coverage Walk + AC-shell Verifier)이 의도
  위반을 표면화하면 통과(고무도장 아님), 둘 다 못 잡으면 결정론 rubric `error_cases`
  가 회귀로 적발.
- **오류 전파** → 픽스처 `10-error-propagation`. 태스크 1 이 공유 유틸에 잠복
  결함(겉보기 통과)을 도입, 태스크 2 가 의존. per-task Verifier(MID)가 전파 전에
  잡거나, 못 잡으면 최종 rubric `happy_path` 합산이 FAIL 로 적발한다.

### 아직 열린 갭(트리거 충족 시 재방문)

FM-1.3(단계 반복), FM-1.5(종료 미인지 직접검증). 둘 다 가드레일로 방어되나 eval
직접검증이 없다. 추측으로 픽스처를 추가하지 않고, 위 표의 트리거(실제 사고가
`events.jsonl`/`run_report.json` 코퍼스에 표면화)가 충족될 때만 구현한다.

---

## §4. 갱신 프로토콜

이 표는 픽스처와 1:1 동기화를 유지해야 한다.

1. **새 픽스처 추가 시**: (a) 픽스처 YAML 최상단에 `mast_coverage: [FM-x.y, ...]`
   주석 추가, (b) §2 표에 행 추가, (c) 닫은 갭이면 §3 표 갱신.
2. **픽스처 제거 시**: §2 행 제거 + §3 의 해당 갭을 "다시 열림"으로 복원.
3. **누가/언제**: eval 레이어를 만지는 변경의 작성자가 같은 커밋에서 갱신.
   `mast_coverage` 주석은 `evals/run.sh` 가 `_meta.json` 화이트리스트에서 제외하므로
   **런타임 무영향**(순수 문서·감사용). `evals/rubric.py` 도 `expected.rubric` 만
   읽으므로 영향 없음.
4. **검증**: `python3 evals/check_doc_freshness.py` 가 이 문서의 내부 링크 resolve 를
   확인한다(비차단). 픽스처 `.yaml` 참조는 백틱/코드스팬으로 두어 링크 체크 대상에서
   제외한다.
