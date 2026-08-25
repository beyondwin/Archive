# 실행 텔레메트리 집계하는 법

`scripts/aggregate_runs.py` 는 **여러 실행에 걸친** 텔레메트리를 모아 리포트로
발산한다. 단일 실행 검사용 [`../../scripts/query_run.sh`](../../scripts/query_run.sh)
의 보완재 — `query_run.sh` 가 한 `state.json` 을 본다면, 이 집계자는
`~/.claude/orchestrator/<run_id>/state.json` 들과 아카이브된
`~/.claude/learning/kws-claude-multi-agent-executor/runs/**/...` run 산출물 전체를
스캔해 위험 등급별 분포·비용·캐시·관측성 갭을 가로질러 본다.

데이터 게이팅된 비용 의사결정 (Haiku 등급 도입 여부, `context_health` 능동 액션
도입 여부) 을 추측 대신 실측 분포에 대고 평가하려고 v2.24 Phase A 에서 출하됐다.

## 호출

cwd 는 스킬 루트 (`skills/kws-claude-multi-agent-executor`).

```bash
# 전체 코퍼스, 마크다운 리포트 (기본)
python scripts/aggregate_runs.py

# 위험 등급 필터 + JSON 출력
python scripts/aggregate_runs.py --risk low --format json

# 특정 ISO 날짜 이후 시작된 실행만
python scripts/aggregate_runs.py --since 2026-05-31

# 플랜 슬러그 glob 으로 필터
python scripts/aggregate_runs.py --plan 'v2.*'

# 마크다운을 stdout 으로, 동시에 JSON 산출물도 파일로 기록
python scripts/aggregate_runs.py --json /tmp/aggregate.json --format md
```

`--json <path>` 는 선택한 `--format` 과 무관하게 항상 그 경로에 JSON 산출물을
추가로 쓴다 (md 리포트를 보면서 raw 수치도 보존하려는 용도).

## 리포트 섹션

| 섹션 | 내용 |
|------|------|
| **Per-run summary** | 실행별 행: `run_id`, `plan`, `done/total`, `dispatches`, `cost_usd`, `cache_hit`, `started`. 비용/캐시는 `cost_ledger` 에서, 진행은 `tasks` 에서 평탄화. |
| **Verifier-retry distribution by risk tier** | 위험 등급(LOW/MID/HIGH/UNKNOWN)별 verifier 재시도 횟수 히스토그램. **LOW 줄** 이 Phase B 게이트 입력 (`LOW (Phase B gate input):`). 등급은 대문자로 canonical 화돼 한 줄로 모인다. |
| **Quality fail-rate (P4 proxy)** | P4 품질 점수가 임계값 미만인 작업 비율. Phase B 게이트의 두 번째 입력. |
| **Recurring ISSUE_KEY signatures** | 여러 실행에 걸쳐 반복되는 ISSUE_KEY 시그니처 (같은 file:line·결함 클래스 재출현). 드리프트 신호. |
| **Observability gaps (report-only)** | 텔레메트리가 일관되게 기록되지 않은 실행: `dispatches=0` (비용 헬퍼 미호출 추정), `started_at`/`completed_at` null, `quality_trend` empty. 데이터 신뢰도 경고. |

## Observation-only (G5)

이 도구는 **관측 전용** 이다. run 산출물을 *읽기만* 한다.

- `state.json` 을 절대 변경하지 않는다.
- 오케스트레이터 제어 흐름 (`references/phases/*.md`) 에 **절대 import 되거나 호출되어선 안 된다**.
- 출력은 오프라인 분석·실험 기록·게이트 평가용일 뿐, 런타임 디스패치/모델 선택에
  되먹임되지 않는다.

이는 가드 **G5** — 관측이 제어로 새는 것을 막는다. 게이트 통과 후 동작 변경이
정당화되더라도, 그 변경은 별도 출하로 phases 문서에 반영해야 하며 이 집계자를
배선해선 안 된다.
