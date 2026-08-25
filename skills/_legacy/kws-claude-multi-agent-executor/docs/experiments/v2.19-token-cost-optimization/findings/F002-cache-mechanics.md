# F002 — Anthropic Prompt Cache 동작 메커니즘 (팩트체크)

**일시**: 2026-05-27
**출처**: 사용자 대화 기반 직관 + Anthropic API 문서 + 관측된 거동의 교차 검증

이 문서는 v2.19 최적화 작업의 기반이 되는 **캐시 동작 사실 모델**을 확정한다. 잘못된 통설에 기반해 최적화를 설계하면 측정 가능한 절감을 만들 수 없으므로, 분석 시작 전에 명시적으로 합의해 둔다.

## 핵심 사실 (확정)

### 1. 캐시 키 구성

서버측 캐시 항목은 다음 튜플로 키잉된다:

```
(API key, model identifier, prefix 토큰 시퀀스 + cache_control breakpoint 위치)
```

**중요**:
- `session_id`, `request_id`, 사용자 식별자 등은 키에 포함되지 **않는다**.
- prefix 토큰 시퀀스는 **메시지 직렬화 후의 토큰**이며, 의미적으로 동일해도 토크나이저가 다른 토큰으로 분해하면 다른 키가 된다.
- 한 토큰이라도 다르면 그 지점부터 뒤쪽 전부 cache miss.

### 2. TTL

- 기본 TTL: **5분** (마지막 hit으로부터).
- Extended TTL: **1시간**. cache_control에 `{"type": "ephemeral", "ttl": "1h"}` 명시 시. write 비용 2배, read 비용 동일.
- TTL 만료된 entry는 다음 요청 시 재write 필요 (= 비용 풀가격 input + cache_write).

### 3. Cache_control breakpoint

- 호출당 최대 **4개** 설정 가능.
- 시스템 프롬프트 끝, tool 정의 끝, 메시지 중간 등 임의 위치에 둘 수 있음.
- 더 짧은 prefix를 cache하면 cache hit 가능성이 높지만 write 비용 발생. 안정성과 변동성의 경계에 배치하는 게 최적.

### 4. 가격 (2026 추정)

| 모델 | input | cache_write | cache_read | output |
|---|---|---|---|---|
| Opus | $15/MT | $18.75/MT (1.25x) | $1.50/MT (0.1x) | $75/MT |
| Sonnet | $3/MT | $3.75/MT | $0.30/MT | $15/MT |

cache_read는 input의 **1/10** — 캐시 hit이 비용 절감의 핵심.

---

## 사용자가 가진 직관 vs 실제

| 사용자 가설 | 검증 결과 | 정정 |
|---|---|---|
| "캐시는 세션과 무관, prefix 토큰 시퀀스로만 결정" | ✅ 정확 | — |
| "터미널로 부르면 TTL이 더 잘 살아있다" | ⚠️ 결과는 맞지만 메커니즘 다름 | TTL이 길어지는 게 아니라, **인터랙티브 사용 패턴이 prefix를 안정적으로 유지 + 다음 턴이 5분 안에 발생**하기 때문 |
| "터미널이 앞단 세션들을 '덩어리로' 호출해서 잘 먹힌다" | ⚠️ 표현 보정 필요 | 매 API 콜마다 **전체 히스토리(system + tools + 전체 prior turns)를 풀로 전송**. 차이는 prefix가 append-only로만 자란다는 점 |
| "`-p` 헤들리스는 캐시가 자주 깨진다" | ✅ 정확 | 원인: (a) SessionStart 훅이 시간/git status 같은 동적 컨텍스트를 prefix 앞부분에 주입 → 매 호출 drift, (b) 호출 간격이 5분 초과 잦음 |
| "`--session-id` 고정해도 miss가 난다" | ✅ 정확 | session_id는 서버 캐시 키와 무관. 원인은 위 (a)(b) |
| "서브에이전트는 메인의 warm cache 무관, cold start" | ✅ 정확 | 서브는 새 대화. system prompt, tools, history 모두 새로 시작 |
| "서브에이전트는 컨텍스트 슬롭 방지가 목적, 비용은 트레이드오프" | ✅ 정확 | 정확한 평가. 서브 대비 inline 처리 시 메인 컨텍스트 비대화 위험 |

---

## 보강 사실 (사용자 직관에 추가된 디테일)

### 같은 wave 내 서브에이전트 fan-out

같은 역할(예: Implementer)의 서브에이전트를 5분 안에 N개 spawn할 때:

- 만약 system prompt + tools + Required Skills 블록이 N개 spawn 사이에 **byte-identical**이면, 첫 spawn이 warm시킨 cache entry를 두 번째 spawn부터 hit 가능.
- 시스템 프롬프트에 dispatch별 변수가 박혀있으면 (예: `{implementer_model}` 치환) 그 토큰이 같은 값으로 일관되는 한 OK. 다른 값이 섞이면 그 지점부터 miss.

이 사실이 F003 (서브에이전트 cache fanout 분석) 의 출발점이다.

### Append-only prefix의 의미

인터랙티브 세션에서 대화 히스토리는 append-only로만 자란다 — 이전 메시지를 수정하거나 압축하면 prefix가 바뀌어 그 지점부터 cache 무효. 따라서:

- **중간 history 압축(compact)은 prefix를 깨뜨림** → 압축은 세션 끝낼 때나 장시간 자리 비울 때만.
- 메시지 편집, 툴 결과 후처리 후 재삽입 등도 동일하게 위험.
- 사용자가 "자리 비울 땐 compact/clear" 하는 패턴은 cache가 어차피 만료될 시점이므로 손실이 없고 — **합리적인 운영 전략**.

### Extended TTL (1h)의 손익분기

write 비용 2배 vs 12배 긴 TTL.

- 손익분기점: **6분** 이후 hit이 발생하면 1h cache가 더 저렴.
- 오케스트레이터 세션은 거의 모든 경우 30분 이상 → **무조건 이득**.
- 다만 호출자(Claude Code / Agent SDK)가 `cache_control.ttl` 설정을 노출해야 적용 가능. T2.1에서 사전 조사 필요.

---

## 캐시 친화적 에이전트 설계 원칙 (이 사실들로부터 유도)

1. **Frozen Core + Hot Tail**: 정적인 것은 prefix 앞쪽으로, 동적인 것은 뒤쪽으로.
2. **시스템 프롬프트에 동적 콘텐츠 금지**: 시간 스탬프, git status, session_id, 랜덤 시드, 동적 파일 목록 — 이런 건 첫 user message에 inject.
3. **툴 정의 고정**: 런타임 등록/해제 금지. 한 세션 내내 동일 구성 유지.
4. **멀티 에이전트는 dispatch별 system prompt를 통째로 정적 작성** — "공통 베이스 + 역할별 추가 라인" 식 합성은 prefix가 미묘하게 달라 캐시 공유 X.
5. **압축은 세션 끝낼 때만** — 중간 압축은 cache invalidate.
6. **TTL 안에서 일하기** — 5분 안에 다음 턴 발생 못하면 1h cache 검토.
7. **서브에이전트 spawn은 병렬로** — 같은 wall-clock 윈도우에 fan-out하면 system+tools 캐시 공유 가능.

이 원칙들이 v2.19 의 T1.1 (SKILL.md 슬림화) / T1.2 (slice injection) / T2.1 (1h cache) / T2.2 (system prompt 정규화) 의 직접적 근거가 된다.

---

## 참고

- Anthropic Prompt Caching 공식 문서 (모델별 가격 / TTL 옵션)
- 사용자 직관의 출처는 2026-05-27 대화 — `~/.claude/projects/.../memory/feedback_agent_invocation_style.md` 에 사용자 워크플로 선호로 저장됨.
