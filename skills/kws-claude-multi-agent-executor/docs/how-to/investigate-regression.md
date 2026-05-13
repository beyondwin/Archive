# 회귀 조사하는 법

`bash evals/run.sh` 가 이전 베이스라인보다 낮은 judge mean 을 생산하거나, 루브릭 `pass_rate` 떨어지거나, `learning_log_adherence: no` 가 예상치 못하게 나타날 때. 회귀는 *알려진 코드/프롬프트 변경과 상관관계 있는 eval 출력 변화*.

이 가이드는 진단 레시피. 회귀 컨텍스트 없는 정례 운영 이슈는 [`../troubleshooting.md`](../troubleshooting.md) 참조.

## Step 1 — 회귀임을 확인

단일 rep 이 fluctuate 가능. 추격 전에:

```bash
# 현재 베이스라인 vs 이전 버전 비교
diff <(jq -S . evals/baselines/v<previous>.json) <(jq -S . evals/baselines/v<current>.json)
```

한 픽스처의 평균만 ≤0.05 떨어지고 비슷한 루브릭: 단일 rep 노이즈 가능성. 재실행으로 확인.

```bash
# 의심 픽스처 재실행
bash evals/run.sh evals/fixtures/<fixture>.yaml > /tmp/rerun.log 2>&1
tail -20 /tmp/rerun.log
```

두 번째 실행도 회귀 보이면: 진행. 베이스라인 복귀하면: 분산 로그, 액션 불필요.

## Step 2 — 회귀 국소화

어느 축이 떨어졌나 식별:

```bash
# 픽스처별 축 분해
jq '.fixtures[] | {fixture, mean, scores}' evals/baselines/v<current>.json
```

낙하를 카테고리로 매핑:

| 낙하 위치 | 가능 원인 | 처음 볼 곳 |
|-----------|-----------|------------|
| `correctness` (또는 루브릭 pass_rate) | Implementer 회귀 | Implementer 프롬프트, 모델 기본값, 픽스처 루브릭 |
| `spec_compliance` | Reviewer 회귀 | Reviewer 프롬프트 (SPEC_COVERAGE_WALK), 스펙 발췌 명확성 |
| `code_quality` | Reviewer 또는 judge 회귀 | Reviewer 프롬프트 (Part 2), judge 프롬프트 임계값 |
| `cost_efficiency` | 토큰 예산 회귀 | Effort guidance, 재시도 루프 동작 |
| `learning_log_adherence: no` | Step 7.5 건너뜀 | SKILL.md 표현, MAE_LEARNING_RUN_ID 전파 |

## Step 3 — 원인 커밋 찾기

```bash
# 이전 베이스라인 이후 이 스킬에서 무엇이 변경됐나?
git log --oneline v<previous-tag>..HEAD -- skills/kws-claude-multi-agent-executor
```

각 커밋을 회귀 축에 대해 교차 참조:

- `references/<role>-prompt.md` 프롬프트 변경 → 편집이 채점 앵커, 출력 포맷, 또는 지시 강도를 바꿨는지 확인.
- SKILL.md 변경 → 단계 스텝 번호와 디스패치 로직 확인.
- 헬퍼 스크립트 변경 → 헬퍼를 독립 실행해 작동 검증.
- Eval 하네스 변경 → preflight 실행 + rubric.py 출력 포맷 재확인.

## Step 4 — 실제 run.jsonl 추출

```bash
# 픽스처의 tmpdir 찾기 (가장 최근)
TMPDIR=$(ls -dt /var/folders/01/*/T/mae-eval-parent-<fixture>.* 2>/dev/null | head -1)
echo $TMPDIR

# 실행 트랜스크립트
RUN_JSONL=$TMPDIR/repo/.harness/run.jsonl
ls -la $RUN_JSONL
```

이 파일이 오케스트레이터 + 서브에이전트가 실제로 무엇을 했는지에 대한 진실의 출처, 무엇을 하라고 들었는지가 아님.

## Step 5 — 툴 타입별 검사

```python
# /tmp/inspect.py 로 저장하고 python3 /tmp/inspect.py 로 실행
import json, sys
from collections import Counter

path = sys.argv[1]
tools = Counter()
agents = []
errors = []

for line in open(path):
    try: d = json.loads(line)
    except: continue
    msg = d.get('message', {})
    if d.get('type') == 'assistant':
        for c in msg.get('content', []):
            if isinstance(c, dict) and c.get('type') == 'tool_use':
                tools[c.get('name')] += 1
                if c.get('name') == 'Agent':
                    agents.append({
                        'id': c['id'],
                        'desc': c.get('input', {}).get('description', '?'),
                        'subtype': c.get('input', {}).get('subagent_type', '?'),
                    })
    if d.get('type') == 'user' and isinstance(msg.get('content'), list):
        for c in msg['content']:
            if isinstance(c, dict) and c.get('type') == 'tool_result' and c.get('is_error'):
                errors.append(c.get('content', '')[:200])

print("Tool counts:", dict(tools))
print("\nAgent dispatches:")
for a in agents:
    print(f"  - [{a['subtype']}] {a['desc']}")
print(f"\nError tool_results: {len(errors)}")
for e in errors[:5]:
    print(f"  - {e}")
```

```bash
python3 /tmp/inspect.py $RUN_JSONL
```

핵심 질문:
- 예상 수의 Implementer + Reviewer + Verifier 디스패치가 발생했나?
- 에러 tool_results 가 있나 (서브에이전트 실패 표시)?
- 비어있지 않은 run 디렉터리에 LEARNING_LOG_INIT: 마커 존재?

## Step 6 — 실패한 서브에이전트의 출력 추출

어느 서브에이전트가 회귀했는지 (예: Reviewer) 알면 전체 출력 추출:

```python
# /tmp/extract.py 로 저장
import json, sys, re

path, role = sys.argv[1], sys.argv[2]   # 예: "Reviewer" 또는 "Verifier"
agent_uses, agent_results = {}, {}

for line in open(path):
    try: d = json.loads(line)
    except: continue
    msg = d.get('message', {})
    if d.get('type') == 'assistant':
        for c in msg.get('content', []):
            if isinstance(c, dict) and c.get('type') == 'tool_use' and c.get('name') == 'Agent':
                agent_uses[c['id']] = c.get('input', {}).get('description', '?')
    if d.get('type') == 'user' and isinstance(msg.get('content'), list):
        for c in msg['content']:
            if isinstance(c, dict) and c.get('type') == 'tool_result':
                tid = c.get('tool_use_id')
                if tid in agent_uses:
                    ct = c.get('content', '')
                    if isinstance(ct, list): ct = ''.join(b.get('text','') for b in ct if isinstance(b, dict))
                    agent_results[tid] = ct

for tid, desc in agent_uses.items():
    if role in desc:
        print(f"\n{'='*70}\n{desc}\n{'='*70}")
        print(agent_results.get(tid, '(no result)'))
```

```bash
python3 /tmp/extract.py $RUN_JSONL Reviewer
```

프롬프트 템플릿 (`references/<role>-prompt.md`) 과 비교:
- 서브에이전트가 출력 포맷을 따랐나?
- 점수가 예상 범위인가?
- 버전별 `SPEC_FAULT` / `SPEC_COVERAGE_WALK` / 등이 존재하나?

## Step 7 — 이전 버전 산출물과 비교

회귀가 특정 Reviewer 동작이면, *이전 버전의* 프롬프트를 같은 픽스처에 (세션의 Agent 툴로 수동) 실행하고 diff:

```bash
git show v<previous-tag>:skills/kws-claude-multi-agent-executor/references/reviewer-prompt.md > /tmp/prev-reviewer-prompt.md
diff /tmp/prev-reviewer-prompt.md references/reviewer-prompt.md
```

diff 의 어느 줄이 동작 변경을 일으켰을 가능성이 있는지 식별.

## Step 8 — 결정: 수정 vs 문서화

회귀가 작고 다루기 쉬우면: 수정. 수정이 ≥50줄이거나 자체 가설이 있으면 실험 기록 열기.

회귀가 진짜지만 수정 비용이 손실 비용을 초과하면: [`../risks-and-limitations.md`](../risks-and-limitations.md) 와 HISTORY.md 에 문서화, known-limitation 노트 출하.

회귀가 eval 측 (judge 캘리브레이션 드리프트, 픽스처 스펙 모호성) 으로 판명되면: *eval* 이 버그. 픽스처 수정 또는 judge 재보정 — 스킬 수정 X.

## Step 9 — 베이스라인 복구

수정 후:

```bash
# 영향받은 픽스처 재실행
bash evals/run.sh evals/fixtures/<fixture>.yaml

# 베이스라인 JSON 이 기대와 일치하는지 검증
cat evals/baselines/v<current>.json | jq '.fixtures'

# 복구된 베이스라인 커밋
git add evals/baselines/v<current>.json
git commit -m "test: recover baseline for <fixture> after <fix summary>"
```

## 작동 예시 — F001 PARTIAL 진단

v2.8 F001 Smoke B 에 대해 풀 패턴 진행:

1. **증상**: v2.8.0 아래 픽스처 08 실행 후 `learning_log_adherence: no`.
2. **국소화**: Step 7.5 준수 축.
3. **확인**: `grep -c LEARNING_LOG_INIT: run.jsonl` → 0 줄.
4. **파일시스템 교차 확인**: `~/.claude/learning/...` 하위에 run 디렉터리 생성 안 됨.
5. **툴 타입 검사**: 47개 Bash 호출, 0개가 `append_learning_event` 참조.
6. **원인 위치**: SKILL.md Step 7.5 가 "must NOT block plan execution" 표현 사용, 오케스트레이터가 "may skip" 으로 읽음.
7. **수정**: v2.8.1 — MANDATORY 표현 + 마커 + eval 측 준수 체크.
8. **복구**: T5 n=4 reps 모두 `learning_log_adherence: yes`.

전체 narrative 는 [`../experiments/v2.8-learning-log/findings/F001-smoke.md`](../experiments/v2.8-learning-log/findings/F001-smoke.md) 참조.
