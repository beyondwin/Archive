# 학습 로그 이벤트 타입 셋 확장하는 법

스키마에 새 이벤트 타입 추가. 이건 스키마 정의, 계약 체크, 참조 문서, 그리고 새 타입을 발산할 적어도 하나의 서브에이전트 프롬프트(또는 오케스트레이터 emit 지점)에 걸친 협응 변경입니다.

기존 10개 이벤트 타입과 계약은 [`../../references/learning-log.md`](../../references/learning-log.md) 참조. 추가 전, 아래 결정 기준 검증.

> **v2.17 cutover 이후**: AgentLens 가 단독 이벤트 싱크입니다. 이벤트는 `agentlens event append --run "$ORCH_RUN_ID" --type kws-cme.<event_type>` 로 발행됩니다. `scripts/append_learning_event.py` 와 `evals/check_learning_log.py` 는 제거되었으므로 더 이상 갱신 대상이 아닙니다.

## 결정: 새 이벤트 타입이 존재해야 하나?

이벤트 타입 추가는 스키마 변경. 기존 10개 타입은 오케스트레이터가 보는 주목할 만한 경계에 대해 jointly exhaustive 하도록 선택됨. 추가 전:

1. **새 신호가 기존 타입의 정제로 표현 가능한가?** 대부분의 "X 를 기록하고 싶다" 는 기존 타입 + 풍부해진 `context` 필드로 매핑. 그쪽 선호.
2. **측정된 필요가 있나?** 추측으로 추가 금지 — `deferred-candidates.md` 에 기록하고 증거 누적 시 재방문.
3. **현재 서브에이전트 프롬프트(또는 오케스트레이터 emit 지점) 중 적어도 하나가 실제로 이를 발산할 것인가?** 생산자 없는 이벤트 타입은 데드 코드.

세 답이 모두 yes 면 진행. 아니면 deferred-candidates 에 기록.

## 갱신할 네 곳 (v2.17+)

새 이벤트 타입이 건드리는 산출물; 누락 시 계약 깨짐 또는 타입 비가시:

1. **`references/learning-log.md`** — 스키마 문서 (베이스라인 필드 + 타입별 필수 context 필드 + 예시 페이로드)
2. **`evals/check_skill_contract.py`** — `EVENT_TYPES` 리스트 (교차 체크)
3. **`scripts/compare_agentlens_events.py`** — legacy → `kws-cme.<event_type>` rename 계약 + `--self-test` 케이스
4. **`references/` 하위 적어도 하나의 서브에이전트 프롬프트** (또는 SKILL.md 오케스트레이터 emit 지점) — 발산자

선택이지만 권장:
5. **`references/escalation-playbook.md`** — 이 타입이 ESCALATE 카테고리에 매핑되면

## Step 1 — `references/learning-log.md` 갱신

새 타입을 enumerate 에 추가. 각 타입에 대해 문서가 현재 가진 것:
- 한 줄 설명
- 오케스트레이터가 발산하는 시점 (또는 어느 서브에이전트가 후보 작성)
- 스키마 베이스라인 너머의 필수 `context` 필드
- 예시 페이로드 하나

그 패턴 매칭.

```markdown
### N. `your_new_type` (vX.Y.Z 에서 NEW)

**언제 발산**: <한 문장 — 오케스트레이터 또는 서브에이전트 + 트리거 조건>

**AgentLens 타입**: `kws-cme.your_new_type`

**베이스라인 너머 필수 context 필드**:
- `field_a` (string) — <무엇을 운반>
- `field_b` (object) — <구조>

**예시**:
\`\`\`json
{
  "schema_version": "1",
  "phase": "phase_1",
  "risk_tier": "MID",
  "event_type": "your_new_type",
  "severity": "medium",
  ...
}
\`\`\`
```

타입이 스키마 버전 변경 (새 최상위 필수 필드) 이면 `schema_version` 번프하고 HISTORY.md 에 마이그레이션 문서화.

## Step 2 — `evals/check_skill_contract.py` 갱신

계약 체크가 `references/learning-log.md` 와 교차 참조하는 `EVENT_TYPES` 리스트 보유. 새 타입 추가:

```python
EVENT_TYPES = [
    "blocker",
    "error",
    "verification_failure",
    "reviewer_warn_or_fail",
    "escalation",
    "recurring_issue",
    "user_correction",
    "parallel_dispatch_failure",
    "successful_workaround",
    "completion_learning",
    "your_new_type",          # vX.Y.Z 에서 NEW
]
```

`python3 evals/check_skill_contract.py --skill SKILL.md` 실행 — `learning_log_event_types` 체크가 여전히 통과해야 함 (이 리스트의 모든 멤버를 `learning-log.md` 에서 grep).

## Step 3 — `scripts/compare_agentlens_events.py` 갱신

이 스크립트는 legacy `events.jsonl` (cutover-pre-2026-05-19 runs) 의 `event_type` → AgentLens `kws-cme.<event_type>` rename 계약을 인코딩합니다. 새 타입 추가 시:

1. `--self-test` 케이스에 양성 매핑 추가:
   ```python
   # self-test fixture 에서
   ("legacy_event_type=your_new_type", "kws-cme.your_new_type"),
   ```
2. `python3 scripts/compare_agentlens_events.py --self-test` 실행 — 통과해야 함.

(과거 디스크 아카이브가 새 타입을 포함할 수 없으면 이 스텝은 생략 — 새 타입은 cutover 이후 도입됐을 것이므로 legacy 매핑이 자명하지 않음.)

## Step 4 — 적어도 하나의 발산자 연결

### 서브에이전트 발산 (가장 흔함)

새 후보 파일을 생산해야 할 서브에이전트 프롬프트 선택. `references/<role>-prompt.md` 편집해서 "Learning log emit" 섹션 추가 (또는 확장):

```markdown
## Learning log emit (vX.Y.Z)

<트리거 조건> 이면, 출력 반환 전 `<orch_dir>/learning_events/<task_id>-<role>.json` 에 learning-event 후보 JSON 파일 작성. **AgentLens 를 직접 호출하지 마세요** — 오케스트레이터가 Phase 1 Step 3.5 에서 이 디렉터리를 스캔하고 `agentlens event append --type kws-cme.<event_type>` 호출.

최소 후보 본문:

\`\`\`json
{
  "schema_version": "1",
  "phase": "<phase_0|phase_1|transition|phase_2>",
  "risk_tier": "<LOW|MID|HIGH>",
  "event_type": "your_new_type",
  "severity": "<low|medium|high>",
  "execution": {"task_id": "task_<N>", "issue_key": "<top_issue_key>"},
  "subagent": {"role": "<your-role>", "model": "sonnet", "dispatch": "agent_tool"},
  "summary": "<≤1 문장 — 무엇이 일어났나>",
  "context": {
    "user_intent": "<…>",
    "agent_expectation": "<…>",
    "actual_outcome": "<…>",
    "root_cause": "<…>",
    "evidence": [{"kind": "<…>", "value": "<…>"}],
    "field_a": "<value>",
    "field_b": {...}
  },
  "improvement": {
    "target": "<개선이 건드릴 파일>",
    "proposal": "<≤1 문장>",
    "experiment_link": null
  },
  "privacy": {"redacted": true, "notes": "<무엇이 redact 됐나>"}
}
\`\`\`
```

여러 서브에이전트가 타입 발산하면 각각 반복.

### 오케스트레이터 발산

오케스트레이터 자체가 발산하면 (서브에이전트가 아니라), 적절한 Phase/Step 와 함께 `SKILL.md` 직접 갱신. AgentLens emit 패턴:

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append --run "$ORCH_RUN_ID" \
    --type kws-cme.your_new_type \
    --payload-json "$(jq -nc \
      --arg field_a "<value>" \
      '{field_a: $field_a, field_b: {...}}')" \
    2>/dev/null || true
fi
```

`|| true` 가드 필수 — observability 실패가 실행을 막으면 안 됨.

## Step 5 — 에스컬레이션 플레이북 갱신 (해당 시)

새 이벤트 타입이 ESCALATE 카테고리에 대응하면 `references/escalation-playbook.md` 에 행 추가:

| ESCALATE 타입 | 이벤트 타입 | 심각도 |
|---------------|-------------|--------|
| `<your_escalate>` | `your_new_type` | <severity> |

## Step 6 — 버전 번프

이벤트 타입 추가는 기능; 마이너 버전 번프 (예: v2.17.0 → v2.18.0). 갱신:

- `SKILL.md` frontmatter `metadata.version`
- `README.md` 현재 버전 라인 + "Recent changes" 항목
- `HISTORY.md` §1 아래 v2.X.0 항목에 새 타입과 이를 동기 부여한 증거 설명

## Step 7 — 풀 preflight 실행

```bash
python3 evals/check_skill_contract.py --skill SKILL.md       # 18+ 체크 통과
python3 scripts/compare_agentlens_events.py --self-test      # rename 계약 통과
```

그리고 다른 게 깨지지 않았는지 검증할 단일 픽스처 실행:

```bash
bash evals/run.sh evals/fixtures/01-trivial-typo.yaml  # smoke
```

## Step 8 — 커밋 + 실험 기록 (비자명할 때)

새 타입이 실험 (예: 타입을 결정한 D### 가 있는 v2.X-<name>/ 디렉터리) 에서 왔으면, 이를 정당화한 실험 finding 과 함께 스키마 + 발산자 변경 커밋.

변경이 작고 논쟁 여지 없으면: 스키마 + 발산자 하나의 커밋이면 됨.

## 흔한 함정

- **계약 eval 동기화 누락**: `learning-log.md` 에는 새 타입 있지만 `check_skill_contract.py` 의 `EVENT_TYPES` 에 없음 → 교차 참조 체크 실패. 수정: 두 곳 동기화.
- **발산자 누락**: 스키마가 새 타입 수락하지만 어느 서브에이전트도 생산 안 함. 타입은 데드. 수정: 출하 전 적어도 하나의 프롬프트 연결; 샘플 실행이 후보 파일 생산하는지 검증.
- **타입 의미가 기존 타입과 겹침**: 미래 독자가 잘못된 타입 발산. 수정: `references/learning-log.md` 에 둘을 구분하는 "타입 X vs Y 사용" 섹션 작성.
- **오케스트레이터 emit 에서 `|| true` 가드 누락**: AgentLens CLI 누락 시 plan 실행이 막힘. 수정: 모든 `agentlens` 호출은 `2>/dev/null || true`.
- **`ORCH_RUN_ID` 가드 누락**: env var 비어있을 때 emit 시도하면 stderr 노이즈. 수정: `if [ -n "${ORCH_RUN_ID:-}" ]; then ... fi` 블록으로 감싸기.
