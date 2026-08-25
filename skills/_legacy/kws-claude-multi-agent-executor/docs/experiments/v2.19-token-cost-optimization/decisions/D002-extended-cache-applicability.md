# D002 — Extended Cache (1h TTL) 적용 범위

**Status**: Draft — 조사 필요 (Claude Code/Agent SDK가 호출자에게 cache_control 노출 여부)
**Date**: 2026-05-27

## 결정 (잠정)

1h extended TTL을 다음 두 위치에 적용한다 (SDK 노출 시):

1. **오케스트레이터 세션의 시스템 prefix** — SKILL.md (슬림화 후 ~10k) + 툴 정의. 손익분기 6분, 오케스트레이터 평균 세션 30분+이므로 무조건 이득.
2. **서브에이전트 dispatch의 시스템 prefix** — Required Skills + Output Format 블록 (~3–8k). wave 내 fan-out이 5분 안에 끝나지 않을 가능성 대비 (예: Verifier가 길게 도는 동안 다음 Implementer가 spawn되는 케이스).

다음 위치는 적용하지 않는다:

3. **User message 변동 영역** — diff, spec 발췌, task 텍스트 등은 dispatch별로 매번 다르므로 cache_write 비용만 발생하고 hit 기회 없음.
4. **state.json 슬라이스 inject** — 작고 변동이 잦아 cache 효과 미미.

## 선행 조사 (실행 전 확인 필요)

- Claude Code 가 sub-agent dispatch (Agent 툴) 시 cache_control 파라미터를 호출자에게 노출하는가? 현재 문서에선 미공개.
- Claude Code 의 시스템 프롬프트 영역에 호출자가 cache_control을 박을 수 있는가? (CLAUDE.md / system prompt extension)
- `claude -p` 헤들리스 호출에서 동일.

조사 방법:
- `claude --help` / agent SDK 문서 점검
- API request 페이로드를 SDK 로깅으로 캡처해 cache_control 필드 유무 확인

## 노출되지 않은 경우의 대안

SDK가 cache_control을 노출하지 않으면:

A. 자동 5분 TTL에 의존 (현재 동작). 절감은 슬림화에 의해서만 발생.
B. Anthropic SDK 직접 호출로 우회 — 그러나 Claude Code의 dispatch 로직을 우회하면 hooks/safety gate를 잃음. 비추.
C. SDK 이슈/기능 요청 제기 — 1h cache는 명백한 토큰 절감 기능이므로 합리적인 요청.

권장: **B는 절대 안 하고**, A로 폴백 + C로 장기 해결책 추구.

## 측정 방법

T6 ablation에 1h cache의 효과를 분리해서 측정하기 어려움 (SDK 단에서 결정되므로). 대신:

- 같은 픽스처를 5분 미만 간격과 5분 초과 간격으로 2회 실행해 cache_read vs cache_write 비율을 비교
- 1h cache가 작동하면 두 경우의 비율이 비슷, 작동 안 하면 5분 초과 케이스가 cache_write 풀가격 발생

## 미해결

- SDK 노출 여부 조사 (T2 베이스라인 측정 작업의 사전 단계로 포함하는 게 자연스러움)
- 노출 안 될 시 이슈 작성 여부
