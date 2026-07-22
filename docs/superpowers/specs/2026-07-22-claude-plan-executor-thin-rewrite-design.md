# KWS Claude Plan Executor (CLPE) — thin rewrite design

- 날짜: 2026-07-22
- 상태: 설계 승인됨 (브레인스토밍 세션 결정 반영)
- 대상: `skills/kws-claude-multi-agent-executor` (CME v3)를 CPE 철학의 얇은
  Claude 런처 `skills/kws-claude-plan-executor` (CLPE)로 교체

## 1. 목적과 소유권 경계

CME v3는 Opus 오케스트레이터 + 결정적 커널(17모듈)이 워크플로 의미론
전체(플랜 파싱, 웨이브 분할, 리뷰 티어, 재시도, 품질 점수, 컴팩션,
finalize)를 직접 소유한다. 이 설계는 그 층을 제거하고 CPE
(`kws-codex-plan-executor`)와 동일한 소유권 경계를 채택한다:

> CLPE는 실행 환경 하나를 유지하고 제출된 사실을 검증한다.
> 무엇이 올바른 작업·검증·병렬화인지는 자식 Claude 세션의 Superpowers가
> 결정한다.

- CLPE가 하는 일: 워크트리 생성, 입력 스냅샷, 자식 `claude` 세션 런칭,
  wall-clock 타임아웃, fail-closed 결과 검증, 세션 위임 재개.
- CLPE가 하지 않는 일: 플랜 컴파일, 태스크 선택, 역할 분리
  (implementer/reviewer/verifier), 재시도 정책, 품질 판단, 리뷰 티어,
  머지/푸시. 멀티에이전트 사용 여부와 병렬도는 자식 세션이 스스로
  결정한다(Superpowers subagent-driven-development / Agent 툴 / 워크플로 자유).

## 2. 확정된 결정 (브레인스토밍)

| 결정 | 선택 |
|---|---|
| 얇게의 의미 | 소유권 경계 재편 (CPE 방식) |
| 멀티에이전트 | 자식에게 완전 위임 |
| 구현 전략 | 최소 신규 작성 (CPE 런타임 재사용/포크 안 함) |
| 기존 v3 자산 | 아카이브 후 교체 |
| 재개 | 포함 — Claude 세션 저장소에 위임 (`--resume <session_id>`) |
| 안전 모델 | 플래그 deny + 프롬프트 금지 + Git 게이트 (훅·샌드박스 없음) |
| 이름 | `kws-claude-plan-executor` 로 개명 |

## 3. 구성물

전부 신규 작성, Python 3 표준 라이브러리만. 목표 규모 ~400줄 (clpe.py
단일 스크립트) + 스키마 + 결정적 evals.

```
skills/kws-claude-plan-executor/
├── SKILL.md                        # ~100줄, CPE SKILL.md 수준
├── README.md                       # 사용법·계약 요약
├── scripts/clpe.py                 # run / resume / inspect (단일 파일)
├── templates/plan-result.schema.json
└── evals/
    ├── run.sh                      # 순차·네트워크 없음·모델 없음
    ├── fake_claude.py              # argv·봉투 검증용 가짜 claude 바이너리
    └── check_*.py                  # 결정적 체크
```

기존 `skills/kws-claude-multi-agent-executor/` 전체는
`archive/kws-claude-multi-agent-executor-v3/` 로 이동(git mv)하고,
`~/.claude/skills/` 심링크는 신규 스킬로 교체한다. `skills/README.md`의
스킬 표와 심링크 예제를 갱신한다.

## 4. CLI 계약

```bash
python3 scripts/clpe.py run \
  --spec /abs/spec.md [--spec ...] \
  --plan /abs/plan.md \
  --workspace /abs/repository \
  [--model opus|sonnet|fable] [--max-turns N] \
  [--timeout-seconds 1200..7200]
python3 scripts/clpe.py resume --run-id RUN_ID
python3 scripts/clpe.py inspect --run-id RUN_ID
```

- `run` 전제: clean git workspace, 절대경로의 읽기 가능한 UTF-8 spec/plan,
  `claude` on PATH.
- 종료 코드: `completed` 0, `failed` 1, `blocked` 2, `resumable` 3.
  `inspect` 는 읽기 전용, 존재하는 run 에 대해 0.
- 상태 저장: `~/.claude/clpe/<run-id>/` (run.json, 입력 스냅샷, 결과 봉투
  사본), 워크트리는 `~/.claude/worktrees/<run-id>/`. 소스 레포 안에는
  아무것도 쓰지 않는다.
- `--model` 기본값: 미지정 시 플래그 생략(사용자 기본 모델 상속).
- `--timeout-seconds` 기본 3600. run 구성(모델/타임아웃/max-turns)은
  run.json 에 기록하되 resume 에서 timeout 은 재지정 가능(세션 외부
  속성이므로 CPE 와 달리 불변으로 만들지 않는다).

## 5. 런칭 계약

`run` 흐름:

1. 더티 트리 검사(`git status --porcelain` 비어있지 않으면 halt).
2. `RUN_ID = <plan-slug>-<YYYYMMDD-HHMMSS>` 파생, 워크트리 + 브랜치
   `clpe/<run-id>` 생성, spec/plan 을 상태 디렉터리로 스냅샷.
3. **env 스크럽 (load-bearing):** 자식 subprocess env 에서
   `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_ENTRYPOINT` 를
   제거한다. 미제거 시 중첩 세션으로 분류되어 `--resume`·히스토리에서
   제외된다 (GitHub anthropics/claude-agent-sdk-python#573,
   claude-code#32618). CPE 와 동일하게 `*_API_KEY`, `*_TOKEN`,
   `*_SECRET` 패턴의 시크릿 변수도 제거한다.
4. 자식 런칭 — 프로세스 그룹 분리(`start_new_session=True`), cwd=워크트리:

```
claude -p <prompt> \
  --output-format json \
  --json-schema <templates/plan-result.schema.json> \
  --permission-mode bypassPermissions \
  --disallowedTools "Bash(git push*)" "Bash(git merge*)" \
                    "Bash(rm -rf /*)" "Bash(git reset --hard origin*)" \
  [--model X] [--max-turns N]
```

  stdout 을 `~/.claude/clpe/<run-id>/envelope.json` 으로 캡처한다.
  `--bare` 는 사용하지 않는다 — 자식이 Superpowers 플러그인/유저 스킬을
  자동 로드해야 한다.
5. wall-clock 타임아웃: `claude -p` 에는 전체 타임아웃 플래그가 없으므로
   CLPE 가 경과 시간 후 프로세스 그룹에 SIGTERM → grace → SIGKILL.
6. 봉투 파싱 → run.json 에 `session_id`, `subtype`, `total_cost_usd`,
   상태를 기록.

**자식 프롬프트** 는 CPE 와 같은 선언적 사실 나열 + 위임 지시 + 금지
prose 로 구성한다:

```
WORKTREE: <path>
PLAN: <snapshot path>
SPECIFICATIONS:
- <snapshot path>...
STARTING_COMMIT: <sha>
BRANCH: clpe/<run-id>

Execute the approved implementation plan with Superpowers
(superpowers:executing-plans). You may dispatch subagents for
independent tasks (superpowers:subagent-driven-development) — that
choice is yours. Commit work to the current branch.

Your FINAL response must be only the JSON object matching the enforced
schema (status / head_commit / summary / open_findings / blocker?).

Do not merge, push, deploy, or modify files outside WORKTREE.
Do not ask the user questions; if blocked, return status "blocked"
with a blocker object.
```

프롬프트 금지는 guard 이지 sandbox 대체가 아니다 — CPE 와 동일한 잔여
위험 인정: `bypassPermissions` 하에서 워크트리 밖 쓰기는 완전히 관측·
복원 가능하지 않다. deny 플래그 + Git 게이트가 남는 통제다.

## 6. 결과 계약과 fail-closed 검증

`plan-result.schema.json` (자식 최종 출력, `--json-schema` 로 강제):

```json
{
  "status": "completed | blocked | failed",
  "head_commit": "sha",
  "summary": "string",
  "open_findings": ["string"],
  "blocker": { "kind": "...", "detail": "..." }   // blocked 일 때 필수
}
```

`completed` 승인 조건 — 전부 만족해야 하며 하나라도 어긋나면 승인하지
않는다 (fail closed):

1. 봉투 `subtype == "success"` **이고** `structured_output` 존재·non-null.
   (`success` 인데 `structured_output` 없음 = 실패로 취급 — 문서화된 함정.)
2. `structured_output.status == "completed"`.
3. 워크트리 clean (`git status --porcelain` 빈 문자열).
4. `structured_output.head_commit == git rev-parse HEAD` (워크트리 실측).
5. `git merge-base --is-ancestor <starting_commit> HEAD` 통과 (조상성).
6. `open_findings == []`.

핸드오프(`~/.claude/clpe/<run-id>/handoff.json`)는 브랜치, 관측 HEAD,
`integration=not_observed` 사실만 기록한다. merge/push/deploy/제품 수용을
주장하지 않는다. 워크트리는 자동 삭제하지 않는다.

CPE 의 `workflow_receipt`(ledger_path / final_review_path 검증)는 채택하지
않는다 — 그 원장은 Codex 쪽 Superpowers 산출물 경로 계약이고, CLPE 는
리뷰 라이프사이클 추론을 하지 않는다는 원칙을 더 얇게 지킨다. Git 게이트
(3–5번)가 유일한 실측 검증이다.

## 7. 실패 분류

exit code 표가 문서화되어 있지 않으므로 봉투 필드로 분류한다:

| 관측 | run.json 상태 | 종료 코드 | resume 가능 |
|---|---|---|---|
| `subtype=="success"` + §6 게이트 전부 통과 | `completed` | 0 | — |
| `structured_output.status=="failed"`, 또는 `status=="completed"` 인데 §6 게이트 실패 | `failed` | 1 | 새 run 권장, resume 허용 |
| `structured_output.status=="blocked"` | `blocked` (blocker 기록) | 2 | 환경 변화 후 resume |
| `subtype=="error_max_turns"` / `"error_max_budget_usd"` | `resumable` | 3 | plain resume |
| CLPE 타임아웃 (SIGTERM) | `resumable(timed_out)` | 3 | plain resume, 남은 예산 내 |
| 봉투 없음/파싱 불가/스키마 불일치 | `result_invalid` → `failed` | 1 | resume 허용 (session_id 확보 시) |
| 오류 카테고리 `rate_limit`·`overloaded` | `blocked(provider_usage_blocked / provider_unavailable)` | 2 | 운영자 판단 |
| 오류 카테고리 `authentication_failed`·`billing_error` | `blocked(provider_auth_blocked)` | 2 | 운영자 판단 |

원시 제공자 메시지는 분류 결과만 남기고 보존하지 않는다(CPE 와 동일).
타임아웃 resume 는 run.json 의 누적 launch 횟수(기본 최대 5회)로 bound.

## 8. 재개 계약 (세션 위임)

CPE 가 체크포인트 저널/복구 캡슐/환경 재탐침으로 직접 구현한 내구성을
CLPE 는 Claude Code 세션 저장소(`~/.claude/projects/<encoded-cwd>/`)에
위임한다:

```bash
clpe.py resume --run-id RUN_ID
# → env 스크럽 후:
claude -p "Continue executing the plan. When done, return only the
result JSON per the enforced schema." \
  --resume <run.json 의 session_id> \
  --output-format json --json-schema <동일 스키마> [--max-turns N]
```

- 동일한 fail-closed 검증을 재적용한다. resume 는 검증을 완화하지 않는다.
- `session_id` 가 없는 run(스폰 실패 등)은 resume 불가 — 새 run 안내.
- 워크트리는 동일한 것을 재사용한다. 세션 저장이 cwd 기준이므로 resume 도
  같은 워크트리 cwd 에서 실행해야 한다 (run.json 에 기록된 경로 사용).
- `completed` run 의 resume 는 no-op 거부.

## 9. 안전 모델

- `--permission-mode bypassPermissions` (자율 실행) + 스코프 deny:
  `Bash(git push*)`, `Bash(git merge*)`, `Bash(rm -rf /*)`,
  `Bash(git reset --hard origin*)`. deny 규칙은 bypassPermissions 보다
  우선 적용된다(문서 확인됨).
- 워크트리에 훅/설정 파일을 심지 않는다 — CME v3 의 4-hook 체계 폐기.
  워크트리는 자식 소유이고 CLPE 는 `.claude/` 를 건드리지 않는다.
- 네이티브 샌드박스 미사용(테스트 실행·네트워크 제약으로 플랜 실행이
  깨질 수 있음). 수용된 잔여 위험은 §5 말미와 동일하게 SKILL.md 에 명시.

## 10. 구현 전 실측 1건 (과금 경로)

공식 문서는 "CLI `-p` 는 OAuth 구독 과금 유지", CME v2.25 실험 기록은
"`-p` 는 크레딧 과금, 구독 풀은 세션 내 Agent 툴만" 으로 상충한다.
구현 착수 전 1회 실측(짧은 `claude -p` 실행 후 과금처 확인)으로 확정하고
결과를 SKILL.md 의 사실 절에 기록한다. 설계 자체는 결과와 무관하게
불변이다 — 과금 사실은 사용자 고지 사항이지 아키텍처 입력이 아니다.

## 11. Evals

CPE 관례를 따른다: 순차·네트워크 없음·자격증명 없음·모델 없음.

- `fake_claude.py` — argv 를 기록하고 준비된 봉투를 뱉는 가짜 `claude`.
  검증 항목: env 스크럽(3개 변수 부재), `--bare` 부재, deny 플래그 존재,
  `--json-schema` 경로, stdout 캡처.
- 검증 로직 단위 체크: subtype/structured_output 매트릭스(§7 표 전 행),
  clean-HEAD·조상성 게이트(임시 git 레포로), resume no-op/불가 경로.
- `./evals/run.sh` 가 완전 로컬 게이트. 행동 변경 전 focused eval 선행.

## 12. Non-goals

- 커널/상태머신/역할 디스패치/품질 점수/리뷰 티어 재구현 (v3 로 회귀 금지).
- CPE 코드 재사용·공유 런타임 (독립 최소 구현).
- 검증 receipt 재사용(`verify` 서브커맨드) — 필요해지면 별도 설계.
- 멀티플랜 순차 실행 — v1 은 플랜 1개. 다플랜은 run 을 연속 실행.
- merge/push/deploy/워크트리 자동 삭제.

## 13. 알려진 불확실성

- 워크트리 cwd 에서 어느 `.claude/`(프로젝트 설정)가 로드되는지 공식
  문서화가 불완전 — 구현 중 실측하고 SKILL.md 에 기록.
- 헤드리스에서 auto-compact 보장이 문서화되어 있지 않음 — 긴 플랜은
  `error_max_turns` → resume 경로가 안전망.
- `--json-schema` 강제와 스킬 주도 장기 실행의 상호작용(최종 턴이 스키마
  JSON 이어야 함)은 실측 대상. 실패 시 대안은 결과 파일 관례(프롬프트로
  경로 지정, 런처가 파일 존재 검증) — 봉투 검증 1번 항목만 파일 검증으로
  치환되고 나머지 게이트는 동일.
