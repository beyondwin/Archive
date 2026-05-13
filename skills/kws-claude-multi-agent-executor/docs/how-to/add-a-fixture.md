# 새 eval 픽스처 추가하는 법

`evals/fixtures/` 에 픽스처 추가하기 위한 단계별. Anthropic eval 가이드는 5-8 픽스처가 sweet spot — 9번째 추가는 기존 픽스처가 다루지 않는 측정된 실패 타입이 있을 때만 의미.

포맷 수준 상세는 [`../../evals/README.md`](../../evals/README.md) 참조. 추가 결정 패턴은 [`../deferred-candidates.md`](../deferred-candidates.md) §Fixture spec audit 참조.

## 결정: 이 픽스처가 존재해야 하나?

YAML 쓰기 전에 답하기:

1. **이 픽스처가 테스트할 실패 모드가 기존 픽스처에 없는가?** "특별히는 없는데 유용해 보임" → 추가 안 함. 픽스처 셋 증가 = eval 비용 증가.
2. **실패 모드 발생의 *측정된* 증거가 있나?** 있으면 학습 로그 이벤트 또는 실험 finding 참조. 없으면 픽스처는 추측 — [`../deferred-candidates.md`](../deferred-candidates.md) 에 후보로 기록하고 실패 표면화 시에만 추가.
3. **어떤 위험 등급?** LOW (작은 수정 1개, <5줄), MID (파일 생성 + 테스트, ≤2 파일), HIGH (크로스 파일 리팩터 또는 새 모듈).

## 파일 레이아웃

```
evals/fixtures/0N-<short-slug>.yaml      ← 픽스처
evals/baselines/v<X.Y.Z>.json            ← 첫 실행 후 캡처
```

`N` = 다음 순차 번호 (현재 08 이 가장 높음). kebab-case slug ≤ 30자.

## YAML 구조

```yaml
name: <파일명과-일치하는-픽스처-이름>
description: |
  <한 문단 "이게 무엇을 테스트하나"; 위험 등급과 예상 복잡도 포함.
   judge 프롬프트에 나타남.>

bootstrap: |
  <계획 실행 시작 전 빈 레포를 셋업하는 bash 명령들.
   디렉터리 생성, pyproject.toml / package.json / Makefile 작성, 최소
   deps 설치. 종료 상태: 빈 src/ + 빈 tests/, 계획이 채울 준비.>

plan: |
  ### Task 0: <명령형 제목>
  
  **Files:**
  - path/to/file.py
  
  <오케스트레이터가 읽는 Markdown 본문. 구체적 명령과 함께 "## Acceptance
   Criteria" 서브섹션 포함해야 함.>

  ### Task 1: <…>
  
  <필요한 만큼 태스크 반복; 보통 1-3>

spec: |
  # Spec: <컴포넌트 이름>
  
  <Reviewer 가 읽는 Markdown 본문. 자체 완결이어야 함 — Reviewer 는
   리뷰 시 계획을 안 봄. 포함:
   - Input/output 계약
   - 예시 (happy path)
   - 에러 케이스 (must raise / reject)
   - 노트 (예시로 캡처 안 된 제약)
   - 메타 규칙 ("strict", "reject" 등 문장) — v2.9 Spec Coverage Walk 가
     소비>

invocation: ""              # 선택, /kws-claude-multi-agent-executor 추가 args

expected:
  task_count: <int>          # 계획의 태스크 수
  expected_files_changed:    # 오케스트레이터가 건드릴 파일들
    - <path>
  commit_count_min: <int>
  commit_count_max: <int>
  test_after: |              # 오케스트레이터 완료 후 실행되는 bash 명령
    <test invocation>
  rubric:                    # 선택이지만 권장 — 결정론적 정확성
    valid_inputs:
      - check: <bash 한 줄; exit 0 = pass>
    error_cases:
      - check: <ValueError 가 raise 됨을 주장하는 bash 한 줄>
        desc: <사람이 읽는 이름; rubric.json 에 나타남>
    code_quality_dimensions: # 선택 — judge 가 소비
      - <한 문장 dimension>
  notes: |                   # judge 용 선택적 컨텍스트

cost_budget:
  wallclock_minutes: <int>   # 자문; 하네스 리포팅용
  tokens: <int>              # 자문
```

완전한 작동 예시는 `evals/fixtures/08-subtle-input-validation.yaml` 참조.

## 결정적: 스펙 vs 루브릭 정렬

이게 v2.9 Phase 2 의 교훈 — 픽스처 08 의 스펙이 반복 단위에 대해 모호했음; 루브릭은 ValueError 요구. Reviewer 는 스펙이 그걸 허용한다고 추론. 결과: 루브릭 FAIL 인데 Reviewer PASS, eval 신호 혼란.

**픽스처 저장 전 감사**:

- 각 `error_cases` 루브릭 체크에 대해: `spec:` 본문에 대응하는 명시적 진술이 있나? Examples / Error cases 섹션의 bullet 으로, 또는 모호하지 않게 만드는 Notes bullet 으로?
- 각 `valid_inputs` 루브릭 체크에 대해: 값이 스펙에서 파생 가능한가, 아니면 숨은 가정인가?

루브릭이 스펙이 메타 규칙으로만 함의하는 동작을 요구하면:
1. 스펙에 명시적 Notes bullet 추가.
2. 또는 루브릭 체크 제거.

숨은 스펙 가정 있는 픽스처 출하 금지. [`../risks-and-limitations.md`](../risks-and-limitations.md) §Spec ambiguity vs rubric strictness 참조.

## Preflight + 첫 실행

```bash
# 1. YAML 파싱 검증
python3 -c "import yaml; yaml.safe_load(open('evals/fixtures/0N-<slug>.yaml'))"

# 2. 계약 eval 통과 (필드 누락 등 잡음)
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_learning_log.py

# 3. 베이스라인 캡처 위해 픽스처 1회 실행
bash evals/run.sh evals/fixtures/0N-<slug>.yaml > /tmp/0N-baseline.log 2>&1

# 4. 베이스라인 결과 검사
tail -20 /tmp/0N-baseline.log
cat evals/baselines/v<current-version>.json | jq '.fixtures[] | select(.fixture == "0N-<slug>")'

# 5. 통과하면: 픽스처 + 베이스라인 커밋.
```

## 준수 + walk 검증 (v2.8.1+)

첫 실행 후 검증:

```bash
# Step 7.5 가 실행됐나?
grep -c "LEARNING_LOG_INIT:" <run.jsonl-path>     # ≥1 이어야 함

# Reviewer 가 SPEC_COVERAGE_WALK 발산했나?
grep -c "SPEC_COVERAGE_WALK" <run.jsonl-path>     # Reviewer 당 ≥1

# walk 가 적대적 행 포함 (sub-step B)?
# Reviewer 출력에서 스펙 Examples/Error cases 섹션 직접 인용이 아닌
# 적어도 3행 검사.
```

walk 가 sparse 하거나 sub-step B 가 비어있으면, 픽스처의 스펙이 메타 규칙 신호 부족 — 적대적 생성 트리거 표면화 위해 "strict" / "reject" / "must validate" 문장 추가.

## 커밋

```bash
git add evals/fixtures/0N-<slug>.yaml evals/baselines/v<version>.json
git commit -m "test(kws-claude-multi-agent-executor): add fixture 0N — <한 줄 설명>

Why: <한 문장 — 이것이 측정하는 실패 모드>.
Evidence: <추가를 정당화하는 학습 로그 이벤트 또는 finding 포인터>.

First-run baseline: <judge mean>, rubric <pass_rate>.
"
```

그 다음 이 픽스처가 v2.X 실험의 일부였으면 [`../experiments/`](../experiments/) 에 행 추가, 버전 번프와 함께 출하면 HISTORY.md 갱신.

## 흔한 함정

- **픽스처 너무 쉬움**: n=1 에서 judge mean = 1.0, 회귀 신호 없음. 수정: 미묘한 엣지 케이스나 구현 게으름 잡을 메타 규칙 추가.
- **픽스처 너무 어려움**: n=4 에서 judge mean = 0.5. Eval 노이즈가 신호 묻음. 수정: 단순화하거나 별도 "stretch" 픽스처 파일로 이동.
- **Bootstrap 이 dirty git 트리 남김**: 오케스트레이터의 Phase 0 dirty-tree 체크에 걸림. 수정: bootstrap 이 초기 커밋 1개 만들어서 worktree 가 깨끗하게 시작.
- **`test_after` 가 bootstrap 에 없는 binary 참조**: run.sh 의 test 호출 실패. 수정: bootstrap 이 모든 필수 툴 설치.
- **계획 태스크 이름이 `expected_files_changed` 와 불일치**: 오케스트레이터가 파일 A 수정하는데 expected 가 파일 B 라고 함. 수정: 계획 본문의 `**Files:**` 리스트를 YAML 의 expected_files_changed 와 정렬.

## 픽스처 은퇴 시점

픽스처가 3+ 버전 동안 안정 (실패 없음) 이면 ratchet — floor 회귀 방지하지만 새 정보 거의 표면화 안 함. 은퇴하지 마; 비용 낮음.

기저 실패 모드가 구조적으로 불가능 (예: 함수가 이름 변경 또는 제거됨) 할 때만 은퇴. 은퇴한 픽스처는 `evals/fixtures/_archive/` 로 이동, 이유 설명하는 `RETIRED.md` 노트와 함께.
