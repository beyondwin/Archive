# AgentLens v0 상세 플랜

> 본 문서는 `docs/adr/agentlens_architecture_proposal.md`(아키텍처)와 `docs/adr/agentlens_v0_task_breakdown.md`(태스크 분해)를 기반으로 한 **PM/리드 엔지니어 관점의 실행 플랜**이다. 엔지니어용 모듈 명세는 `docs/spec/agentlens_v0_implementation_spec.md` 참조.

---

## 0. 문서 목적

본 플랜은 다음 질문에 답해야 한다.

1. **무엇을 만드는가?** — v0의 in/out scope, 최소 기능 정의.
2. **어떤 순서로 만드는가?** — 마일스톤 간 의존성, 각 마일스톤의 exit criteria.
3. **무엇으로 완료를 판정하는가?** — 마일스톤별 검증 게이트, 회귀 테스트, acceptance criteria.
4. **무엇이 위험한가?** — 식별된 리스크, 완화 전략, escalation 기준.
5. **얼마나 걸리는가?** — 마일스톤별 추정 공수(개발자 1인 기준 일 단위).

---

## 0.1 2026-05-18 엔지니어링 리뷰 반영

본 리뷰의 결론은 "큰 방향은 맞지만, v0 GA 전에 계약을 조금 더 단단하게 잠가야 한다"이다. 특히 아래 항목은 구현 중 발견되면 재작업 비용이 크므로 플랜에 선반영한다.

### Ship-blocking 결함 / 개선

| ID | 우선순위 | 결함 / 개선 | 반영 위치 |
|---|---:|---|---|
| ER-1 | P0 | `agentlens run`이 run 초기화(`run.json`, `events.jsonl`, workspace pointer) 단계에서 실패하면 child command를 실행하지 못할 수 있다. Non-blocking invariant는 **child spawn 전 실패**까지 포함해야 한다. | M5, M8, spec §5.16 |
| ER-2 | P0 | 기존 `workspace_id = remote + rel_path` 규칙은 main checkout과 git worktree가 둘 다 `rel_path="."`일 때 충돌한다. workspace-local persisted id가 필요하다. | M1, spec §5.3/§6.1 |
| ER-3 | P1 | JSON Schema 파일에 `# v1 is locked` 같은 주석을 넣는 계획은 JSON 문법상 불가능하다. top-level `$comment`로 버전 정책을 넣는다. | M0, spec §4 |
| ER-4 | P1 | query command가 SQLite를 직접 읽으면 SQLite 손상 시 fallback이 빠질 가능성이 높다. `store/query.py`를 read facade로 두고 SQLite/full-scan 선택을 캡슐화한다. | M3/M4, spec §5.8a |
| ER-5 | P1 | `stdout`/`stderr`를 순차 line read로 처리하면 한쪽 pipe가 꽉 찰 때 wrapper가 deadlock될 수 있다. 두 stream을 동시에 drain해야 한다. | M5, spec §5.16 |
| ER-6 | P1 | redaction 후 문서가 schema-invalid가 될 수 있는데 writer 의사코드는 validate 후 redact만 한다. persisted artifact 기준으로 redact 후 최종 schema validation을 다시 한다. | M8, spec §5.6/§5.12 |
| ER-7 | P1 | evaluator 내부 check exception이 `skipped`로 묻히면 `eval.status=passed`가 될 수 있다. check exception은 `EVALUATOR_ERROR`로 surfaced 되어야 한다. | M2, spec §5.15 |
| ER-8 | P1 | `success`인데 `changed_files=[]`인 run을 무조건 실패 처리하면 research/no-op agent 작업에서 false positive가 난다. `no_changes_reason`을 명시하면 통과 가능하게 한다. | M2, spec §4.3/§5.14 |
| ER-9 | P2 | Codex App watcher는 post-run/minimal evidence라 full lifecycle 성공 기준과 분리해야 한다. `native-experimental`/`watcher-only`는 degraded integration이다. | M7, 성공 정의 |

### What already exists

- `docs/adr/agentlens_architecture_proposal.md`는 제품 범위, source of truth, lifecycle, privacy 원칙을 이미 정의한다.
- `docs/adr/agentlens_v0_task_breakdown.md`는 작업 단위와 파일 트리를 이미 분해한다.
- 본 플랜과 spec은 위 ADR을 실행 가능한 계약으로 잠그는 layer다. ADR에 남아 있는 `current-run` 단수 표기는 superseded로 보고, v0 구현 기준은 `current-runs/<run_id>` 다중 마커다.

### NOT in scope

- ADR 전체 재작성: 본 변경은 plan/spec의 구현 계약을 고정한다. ADR은 역사적 의사결정 문서로 남긴다.
- legacy log importer, dashboard, MCP API, patch queue, LLM judge: 기존 v0 제외 결정을 유지한다.
- Windows 네이티브 shim: POSIX shell/Python signal 모델을 v0 기준으로 둔다.
- Codex App stable full integration: v0에서는 `native-experimental` 또는 `watcher-only`로만 표시한다.

### Coverage diagram

```text
CODE PATHS / CONTRACTS                              TEST REQUIREMENTS
[+] schema/jsonschema/*.json                        [GAP] $comment policy, no JSON comments
  ├── run/event/final/eval/manifest valid           [★★★] valid + invalid fixtures
  ├── additionalProperties false                    [★★★] unknown field rejection
  └── no_changes_reason rule                        [GAP] success + empty changed_files cases

[+] ids.py / store/paths.py                         [GAP] main checkout vs worktree distinct
  ├── existing workspace config id                  [GAP] move workspace with config keeps id
  └── missing config recompute                      [★★] deterministic fallback documented

[+] adapters/process.py                             [GAP] init write failure passthrough
  ├── child exit 0 / 42                              [★★★] exit code preserved
  ├── SIGINT/SIGTERM                                [★★★] 128+signal + cancelled final
  ├── stdout/stderr drain                           [GAP] large stderr/stdout no deadlock
  └── seal/eval/index failures                      [★★★] recording_incomplete or passthrough

[+] evaluator/engine.py                             [GAP] check exception => eval.status=error
  ├── missing final                                 [★★★] incomplete
  ├── failed command unacknowledged                 [★★★] failed
  └── residual risk policy                          [★★★] low warning vs medium+ failed

[+] store/query.py                                  [GAP] SQLite corrupt/missing full-scan fallback
  ├── latest/status/show                            [★★★] text + JSON snapshot
  └── failures/risks                                [★★★] eval failures + recording_incomplete
```

### Failure modes to lock

| Failure mode | Expected behavior | Required test |
|---|---|---|
| run metadata write fails before child spawn | child command still runs passthrough; no AgentLens exit-code contamination | `test_nonblocking.py::test_init_failure_passthrough` |
| SQLite file corrupt/missing | query rebuilds or full-scans durable store | `test_sqlite_index.py`, `test_query_fallback.py` |
| evaluator check raises | `eval.status="error"` and `EVALUATOR_ERROR` failure is visible | `test_evaluator_checks.py` |
| stdout or stderr emits > pipe buffer | wrapper drains both streams and exits | `test_process_wrapper.py` |
| success with no changed files but explicit no-op | evaluator passes or warns, not false-fails | `test_evaluator_checks.py` |
| success with no changed files and no explanation | evaluator emits `DIFF_SCOPE_UNKNOWN` | `test_evaluator_checks.py` |

### Worktree parallelization strategy

| Lane | Modules | Depends on | Notes |
|---|---|---|---|
| A | `schema/`, `docs/contract.md` | M0 start | Contract first; other lanes consume schema enums. |
| B | `ids.py`, `store/paths.py`, `store/writer.py`, `store/manifest.py` | A | Core write path; keep sequential because path and writer contracts are tightly coupled. |
| C | `evaluator/` + fixtures | A, B stub | Can run in parallel with SQLite after M1 vertical slice. |
| D | `store/sqlite_index.py`, `store/query.py`, query command tests | A, B | Parallel with evaluator after M1; merge before M4. |
| E | `adapters/process.py` | B, C, D | Wrapper needs meaningful eval/query output. |
| F | `adapters/shims.py`, `commands/install.py`, `commands/doctor.py` | E | Shim delegates lifecycle to process wrapper. |
| G | `adapters/{claude,codex_cli,codex_app}.py` | F | Adapter probes can split into parallel worktrees. |

Launch C + D in parallel after M1. Launch Claude/Codex CLI/Codex App adapter work in parallel after M6. Keep B and E sequential to avoid contract drift in the write path.

---

## 1. 제품 목표 재확인

> AgentLens v0는 Claude/Codex/기타 AI agent의 **새로운 실행**을 local-first contract로 기록하고, **deterministic evaluator**로 agent claim과 evidence를 비교해 리스크·결함을 사람이 검토 가능한 형태로 남기는 시스템이다.

### 1.1 성공 정의 (v0 ship 기준)

다음 모두 만족 시 v0 GA.

- [ ] 사용자가 `agentlens install` 한 번 실행한 뒤 평소처럼 Claude Code CLI 또는 Codex CLI(`claude`/`codex`)를 실행하면, 종료 후 `~/.agentlens/runs/<workspace_id>/<run_id>/`에 6개 항목(`run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`, `artifacts/`) 이 남는다.
- [ ] Codex App은 `native-experimental | watcher-only | unavailable`로 별도 표기한다. watcher-only는 post-run/minimal evidence이며 v0 GA의 full lifecycle 성공 기준으로 간주하지 않는다.
- [ ] `agentlens show --latest`가 `agent_outcome`/`eval_status`/`sealed_phase`를 1초 이내 출력한다.
- [ ] `agentlens failures`, `agentlens risks`가 최근 30일 sealed run 전체에서 결함·리스크를 텍스트와 `--format json` 두 형식으로 출력한다.
- [ ] AgentLens 측 모든 실패 경로(스토어 쓰기 실패, evaluator crash, SQLite 손상)에서 child agent의 exit code가 변하지 않는다.
- [ ] `AGENTLENS_DISABLE=1`로 완전히 꺼진다.
- [ ] 기본 설정으로 절대 경로/시크릿 토큰이 durable store에 남지 않는다.

### 1.2 비 목표 (명시적 제외)

다음은 v0에서 **만들지 않는다**. 만들면 scope creep으로 간주한다.

- legacy log importer (claude/codex 과거 세션 가져오기)
- live dashboard / studio UI
- MCP lesson/eval API
- 자동 patch queue / 자동 수정
- LLM judge 기반 평가
- cross-run lesson compiler
- cloud sync, OTel/Langfuse exporter
- Windows 네이티브 지원 (macOS/Linux 우선, 명시적으로 Windows out-of-v0)

---

## 2. 전체 마일스톤 지도

```
M0 Contract Freeze
   │
   ▼
M1 Vertical Slice (start → mark → final → seal → eval-stub → show)
   │
   ├──► M2 Evaluator Hardening (전체 deterministic 체크 + fixture suite)
   │
   ├──► M3 SQLite Index (rebuildable cache)
   │
   ▼
M4 Query Surface (status / latest / failures / risks / --format json)
   │
   ▼
M5 Process Wrapper (agentlens run -- <cmd>, SIGINT 처리)
   │
   ▼
M6 Install / Shim / Doctor (PATH 동의, lockfile, permissions)
   │
   ▼
M7 Claude / Codex Adapter (stream-json, shim, watcher)
   │
   ▼
M8 Hardening (redaction, retention, non-blocking, determinism)
   │
   ▼
v0 GA
```

### 2.1 마일스톤 의존성 규칙

- M2/M3는 **M1 종료 후 병렬 가능**. 단, M4 시작 전 둘 다 M1과 합쳐져 있어야 한다.
- M5는 M4 종료 후 시작. (wrapper가 의미 있는 query 결과를 만들어야 하기 때문)
- M6 → M7 은 엄격한 순서. shim 인프라가 없으면 adapter integration 시험이 불가.
- M8은 마지막. invariant를 잠그는 단계이지 새 기능 단계가 아님.

### 2.2 공수 추정 (개발자 1인 풀타임, 단위: 일)

| 마일스톤 | 추정 | 비고 |
|---|---|---|
| M0 Contract Freeze | 2 | 스키마/문서 4개 |
| M1 Vertical Slice | 4 | 핵심 store + eval stub + show |
| M2 Evaluator Hardening | 4 | check 12개 + fixture 5개 |
| M3 SQLite Index | 2 | 단순 테이블 + rebuild |
| M4 Query Surface | 2 | 4개 명령 + JSON 포맷 |
| M5 Process Wrapper | 3 | 신호 처리/exit code 보존 |
| M6 Install / Shim / Doctor | 4 | shim 보안 + doctor JSON |
| M7 Claude/Codex Adapter | 5 | 3 runtime 표면 detect/install |
| M8 Hardening | 4 | redaction + retention + fault-injection |
| 통합 회귀/문서/태그 | 2 | release 작업 |
| **합계** | **32일** | 약 6주 (1인 기준) |

2인 병렬 작업 시 M2/M3 동시, M6/M7 부분 동시로 약 4주 단축 가능.

---

## 3. 마일스톤 상세

각 마일스톤은 다음 형식으로 기술한다.

```
목적 / 산출물 / 의존성 / 작업 단위 / Exit Criteria / 검증 / 리스크
```

### 3.1 M0 - Contract Freeze

**목적**
이후 모든 코드가 의존할 JSON 계약·디렉터리 레이아웃·enum·정책을 동결한다. 이 단계에서 계약이 흔들리면 이후 모든 작업이 재작업된다.

**산출물**
- `docs/contract.md` — run 디렉터리 레이아웃, source of truth 정의
- `docs/security.md` — 기본 redaction/retention 정책
- `docs/integrations.md` — Integration Level 0~3 정의
- `docs/cli.md` — 명령 contract
- `src/agentlens/schema/jsonschema/*.json` — 5개 스키마
- `tests/unit/test_schema_validation.py` — valid/invalid round-trip

**의존성**
- 없음 (project 시작점)

**작업 단위**
- T0.1 문서 4종 작성
- T0.2 5개 스키마 작성 + 검증 테스트

**Exit Criteria**
- [ ] 5개 스키마 모두 Draft 2020-12, `additionalProperties: false`, UTC ISO8601 regex 강제
- [ ] 각 JSON Schema 파일은 JSON 문법을 유지한다. 버전 정책은 주석 문법이 아니라 top-level `$comment`로 기록한다.
- [ ] valid 예제 통과, invalid 예제 거부 테스트 모두 green
- [ ] enum 경계 케이스(`agent.name="unknown_agent"` 등) 거부 확인
- [ ] 문서 4개 markdownlint 통과 (도구 가용 시)

**검증**
```bash
pytest tests/unit/test_schema_validation.py -v
markdownlint docs/*.md
```

**리스크 / 완화**
- 계약 후 변경 압력 → 변경 정책 문서화: v1 잠금, 깨는 변경은 v2로. JSON Schema에는 top-level `$comment`로 "v1 is locked" 정책을 넣고, `#` 주석은 쓰지 않는다.

---

### 3.2 M1 - Vertical Slice

**목적**
종이 위 계약을 실제로 굴려본다. `start → mark → final → seal(pre_eval) → eval(stub) → seal(final) → show --latest`가 손으로 호출 가능한 상태를 만든다. **M1이 끝났을 때 데모가 가능해야 한다.**

**산출물**
- `src/agentlens/constants.py`, `ids.py`, `time.py`, `store/paths.py`
- `src/agentlens/store/writer.py` (atomic write, append, lock)
- `src/agentlens/store/manifest.py` (two-phase seal)
- `src/agentlens/evaluator/engine.py` (stub: `schema_valid` + `final_present`만)
- `src/agentlens/commands/{start,mark,attach,final,seal,eval,show}.py`
- `src/agentlens/cli.py` (Typer entrypoint)
- `tests/integration/test_cli_lifecycle.py`

**의존성**
- M0 완료 (스키마 필수)

**작업 단위**
- T1.1 Path/ID 유틸 (persisted workspace_id, git/path basis 양쪽, run_id filesystem-safe)
- T1.2 Run Writer (atomic temp+rename, fsync, append-tolerant jsonl)
- T1.3 Manifest two-phase seal (pre_eval / final / recording_incomplete)
- T1.4 Eval stub + show --latest

**Exit Criteria**
- [ ] `agentlens start --agent generic --mode cli` 호출 시 `~/.agentlens/runs/<workspace_id>/<run_id>/run.json`이 생성됨
- [ ] `events.jsonl`에 `run.started` 한 줄
- [ ] `agentlens mark checkpoint.marked --name foo`로 한 줄 추가됨
- [ ] `agentlens final --outcome success`로 `final.json` 생성됨
- [ ] `agentlens seal`(pre_eval) → `agentlens eval`(stub) → `agentlens seal --final` 호출 시 manifest의 `sealed_phase`가 각각 올바르게 갱신됨
- [ ] `agentlens show --latest`가 5필드(run_id, workspace_id 약식, agent_outcome, eval_status, sealed_phase)를 출력
- [ ] 워크스페이스 절대 경로가 `run.json` 어디에도 평문으로 나타나지 않음
- [ ] main checkout과 git worktree가 서로 다른 `workspace_id`를 갖는다.
- [ ] `<workspace>/.agentlens/config.yaml`에 persisted `workspace_id`가 있으면 workspace 이동 후에도 같은 id를 사용한다.

**검증**
```bash
pytest tests/integration/test_cli_lifecycle.py -v
```

**리스크 / 완화**
- atomic write 누락으로 partial JSON → temp+rename 강제, fsync 호출. crash 시뮬레이션 테스트 추가.
- jsonl 한 줄 깨짐이 reader crash 유발 → reader는 bad line을 evaluator failure로 변환, raise하지 않음.
- workspace_id가 worktree·main checkout을 같게 만듦 → persisted workspace config를 우선 사용하고, 최초 계산에는 git remote hash + repo-relative root + host/worktree identity hash를 포함한다. id_basis 단위 테스트 필수.

---

### 3.3 M2 - Evaluator Hardening

**목적**
M1의 stub evaluator를 12개 check + multi-axis failure taxonomy로 확장. **fixture 5종이 항상 같은 결과를 낸다(=결정적이다)** 는 것을 잠근다.

**산출물**
- `src/agentlens/evaluator/checks.py` (체크 함수 12개)
- `src/agentlens/evaluator/failures.py` (taxonomy)
- `tests/fixtures/{minimal,failed_command,missing_final,residual_risk,corrupt_manifest}_run/`
- `tests/integration/test_eval_determinism.py` (byte-equal 회귀)

**의존성**
- M1 완료 (`engine.py` stub 존재)

**작업 단위**
- T2.1 Check/Failure 모델
- T2.2 Check 함수 12개 구현
- T2.3 Fixture 5종 + 기대 eval.json 작성
- T2.4 Determinism 회귀 (시간 normalize 후 byte-equal)

**Exit Criteria**
- [ ] 모든 check가 `passed | failed | skipped` 중 하나를 반환
- [ ] `agent_outcome=success` + verification 없음 → `failed`
- [ ] `agent_outcome=success` + medium/high/critical residual risk → `failed`
- [ ] `agent_outcome=success` + low residual risk + verification → `passed` (with warning)
- [ ] `agent_outcome=success` + `changed_files=[]` + `no_changes_reason` 없음 → `DIFF_SCOPE_UNKNOWN`
- [ ] evaluator check exception은 `skipped`로 묻지 않고 `eval.status="error"` + `EVALUATOR_ERROR`로 surfaced
- [ ] fixture 5종에서 evaluator를 2회 실행 후 `eval.json` (timestamp normalize 후) byte-equal
- [ ] evaluator 자체 crash 시 `eval.json.status="error"`로 기록, exit code 별도로 보존

**검증**
```bash
pytest tests/unit/test_evaluator_checks.py -v
pytest tests/integration/test_eval_determinism.py -v
```

**리스크 / 완화**
- check 순서가 결과에 영향 → check 결과 정렬키를 `name` 알파벳 순으로 강제, dict 직렬화 `sort_keys=True`.
- floating-point confidence가 플랫폼별로 미세 차이 → `confidence`는 [0,1]에서 소수점 2자리로 round.

---

### 3.4 M3 - SQLite Index

**목적**
조회 가속을 위한 read-only index를 둔다. **SQLite는 source of truth가 아니다.** 깨지거나 사라져도 durable store에서 재생성 가능해야 한다.

**산출물**
- `src/agentlens/store/sqlite_index.py` (스키마, `index_run`, `rebuild_index`)
- `src/agentlens/store/query.py` (SQLite 사용 가능 여부 판단 + full-scan fallback)
- `tests/unit/test_sqlite_index.py`
- `tests/unit/test_query_fallback.py`

**의존성**
- M1 완료 (run 디렉터리 존재)

**작업 단위**
- T3.1 테이블 스키마 + `index_run(run_dir)`
- T3.2 `rebuild_index(agentlens_home)` (full-scan)
- T3.3 `store/query.py` read facade: SQLite 부재/손상 시 fallback (full-scan reader)

**Exit Criteria**
- [ ] `runs`, `checks`, `failures`, `artifacts` 4개 테이블
- [ ] `agentlens.sqlite` 삭제 후 rebuild → 원래 row 집합과 동일 (run_id 기준 정렬 후 byte-equal)
- [ ] 모든 컬럼이 JSON artifact로부터 재계산 가능 (SQLite 전용 필드 금지)
- [ ] SQLite 없는 상태에서도 `agentlens latest`, `agentlens gc`가 동작 (성능은 떨어지나 정확함)
- [ ] query command는 `sqlite_index.py`를 직접 호출하지 않고 `store/query.py`만 사용

**검증**
```bash
pytest tests/unit/test_sqlite_index.py tests/unit/test_query_fallback.py -v
rm ~/.agentlens/agentlens.sqlite && agentlens latest    # 동작 확인
```

**리스크 / 완화**
- SQLite를 canonical로 오해 → 코드 리뷰 규칙: `sqlite_index.py`는 index build/upsert primitive만 제공하고, query command는 `store/query.py` facade를 통과한다. write path는 JSON artifact 먼저, index update는 best-effort.

---

### 3.5 M4 - Query Surface

**목적**
사람과 CI가 모두 소비 가능한 조회 명령을 완성한다.

**산출물**
- `src/agentlens/commands/show.py` (status, latest, show, failures, risks; read path는 `store/query.py` 사용)
- `--format json` 표준 플래그

**의존성**
- M2 완료 (eval.json 데이터)
- M3 완료 (인덱스 가속)

**작업 단위**
- T4.1 `latest`, `status`, `show --latest`, `show <run_id>`
- T4.2 `failures`, `risks` (final + eval 조합)
- T4.3 `--format json` 모든 query 명령에 적용

**Exit Criteria**
- [ ] eval.json 없으면 `eval_status=needs_eval`로 표시
- [ ] `failures`는 evaluator failure만, `risks`는 final.residual_risks + eval.failures + recording_incomplete 합본
- [ ] `recording_incomplete`는 `RECORDING_INCOMPLETE` risk item으로 표시한다.
- [ ] `--format json`이 모든 query 명령에서 stable schema 출력 (snapshot test 통과)
- [ ] 기본 출력에 절대 경로 없음

**검증**
```bash
pytest tests/integration/test_cli_lifecycle.py -v
agentlens show --latest --format json | jq .   # 파싱 가능 확인
```

**리스크 / 완화**
- JSON 출력 schema가 시간 지나며 drift → query 명령용 출력 스키마도 v1로 고정, snapshot test로 회귀 잡음.

---

### 3.6 M5 - Process Wrapper

**목적**
`agentlens run -- <command>`로 임의 명령을 감싸 자동 record/seal/eval한다. **모든 종료 경로(정상 / 비정상 / 신호) 에서 child exit code를 보존한다.**

**산출물**
- `src/agentlens/adapters/process.py`
- `tests/integration/test_process_wrapper.py`

**의존성**
- M4 완료

**작업 단위**
- T5.1 child 프로세스 spawn, stdout/stderr excerpt 캡처 (allow-list 추출만)
- T5.2 종료 경로 3가지 처리 (final 있음 / 없고 exit 0 / 없고 exit 비0)
- T5.3 SIGINT/SIGTERM signal handler (cancel 마킹 + 신호 재전파)
- T5.4 AgentLens 단계 실패 시에도 child exit code 보존

**Exit Criteria**
- [ ] run 초기화(`write_run_meta`, `append_event(run.started)`, workspace pointer) 실패 시 child command는 passthrough로 실행되고 원래 exit code가 반환됨
- [ ] `agentlens run -- sh -c 'exit 0'` → exit 0, `agent_outcome=unknown`
- [ ] `agentlens run -- sh -c 'exit 42'` → exit 42, `agent_outcome=failed`
- [ ] `agentlens run -- sh -c 'sleep 10' & kill -INT $!` → exit 128+SIGINT, `agent_outcome=cancelled`, `exit_signal="SIGINT"`
- [ ] child가 stdout/stderr 양쪽에 pipe buffer보다 큰 출력을 내도 deadlock 없이 종료됨
- [ ] manifest write fault-inject 후에도 child exit code 그대로
- [ ] evaluator crash fault-inject 후에도 child exit code 그대로
- [ ] stdout excerpt에 자유 텍스트 슬라이스 없음 (allow-list 패턴만)

**검증**
```bash
pytest tests/integration/test_process_wrapper.py -v
```

**리스크 / 완화**
- signal race (child가 신호 받기 전 wrapper가 reap) → wrapper의 signal handler는 child PID로 forward 후 reap.
- stdout/stderr buffering으로 deadlock 또는 excerpt 누락 → PTY 미사용, `selectors` 또는 reader thread 2개로 stdout/stderr를 동시에 drain.

---

### 3.7 M6 - Install / Shim / Doctor

**목적**
사용자가 PATH에 `claude`/`codex` shim을 install-once로 깔 수 있게 한다. **supply-chain 표면이므로 보안이 1급 요구.**

**산출물**
- `src/agentlens/adapters/shims.py` (shim 스크립트 템플릿)
- `src/agentlens/commands/{install,doctor,mode}.py`
- `tests/integration/test_install_doctor.py`
- `tests/unit/test_shim_security.py`

**의존성**
- M5 완료 (wrapper가 실제로 동작해야 shim이 의미가 있음)

**작업 단위**
- T6.1 Mode config (priority chain, `AGENTLENS_DISABLE`)
- T6.2 Shim install (퍼미션, lockfile, 동의 prompt). shim은 lifecycle owner가 아니라 `agentlens run`으로 위임한다.
- T6.3 Doctor (integration level detect, JSON 포맷)
- T6.4 Nested invocation policy (`AGENTLENS_NESTED_POLICY=passthrough|nested`)

**Exit Criteria**
- [ ] `~/.agentlens/shims/` 디렉터리 권한 `0700` (owner only)
- [ ] shim 파일 권한 `0755`, owner 일치 확인
- [ ] `<name>.real` 락파일에 real binary 절대경로 + sha256 저장
- [ ] real binary sha256 변경 시 shim이 stderr 경고 + passthrough fallback (recording skip)
- [ ] lockfile 누락 시 shim은 자기 자신을 재탐색하지 않고, 안전하게 real binary 후보를 찾지 못하면 exit 127로 실패한다.
- [ ] `agentlens install` 시 PATH 변경 명시 동의 (`--yes`로 우회)
- [ ] `agentlens doctor integrations` 출력에 `Shim integrity: ok | drift_warning` 항목
- [ ] doctor `--format json` 가능
- [ ] nested 호출에서 `AGENTLENS_NESTED_POLICY=passthrough`(기본)면 recording 없이 real 실행

**검증**
```bash
pytest tests/integration/test_install_doctor.py -v
pytest tests/unit/test_shim_security.py -v
agentlens doctor integrations --format json | jq .
```

**리스크 / 완화**
- shim hijack 위험 → 0700 디렉터리, owner 검증, lockfile sha256 매번 검증.
- 사용자 ~/.zshrc/~/.bashrc 수정 충돌 → install은 PATH export 한 줄만 제안 후 사용자 승인. 자동 편집 금지.
- nested re-entry 무한루프 → `AGENTLENS_RUN_ID`+PID stamp로 자기 PID에서 만든 변수인지 식별.

---

### 3.8 M7 - Claude / Codex Adapter

**목적**
세 런타임(Claude Code, Codex CLI, Codex App)에 대해 각각 가능한 최상위 integration을 자동 선택한다.

**산출물**
- `src/agentlens/adapters/{claude,codex_cli,codex_app}.py`
- doctor 출력 확장

**의존성**
- M6 완료 (shim 인프라)

**작업 단위**
- T7.1 Claude Code: `--version`, `--help` probe → plugin/hooks 가용성 detect, settings JSON 주입(백업 후), `--bare` fallback
- T7.2 Codex CLI: `--version`, `plugin --help`, `mcp --help`, `app-server --help` probe → 기본은 shim
- T7.3 Codex App: `~/.codex/sessions` watcher + `app-server` probe → `native-experimental | watcher-only | unavailable` 분류

**Exit Criteria**
- [ ] Claude `full` 판정 조건: `--include-hook-events`+`--output-format stream-json` 지원 확인 + settings 주입 가능
- [ ] Claude `--bare` 환경에서는 shim-only로 자동 격하
- [ ] Codex CLI `full` 조건: shim + `exec` 지원 확인
- [ ] Codex App은 절대 `full`로 표시하지 않음 (`native-experimental` 또는 `watcher-only`)
- [ ] adapter install 시 사용자 설정 백업 (rollback 가능)
- [ ] uninstall 시 AgentLens-owned 블록만 제거 (사용자 다른 설정 보존)
- [ ] 테스트는 실제 binary 호출 없이 fake binary로 detect 로직 검증
- [ ] probe fixture는 `--help` output 기반으로 pin하고, 새 CLI 버전 감지 시 doctor가 "fixture update required"를 경고

**검증**
```bash
pytest tests/integration/test_install_doctor.py -v
agentlens doctor integrations
```

**리스크 / 완화**
- Codex 0.129.x → 0.130.x 포맷 변경 → session JSONL fixture를 0.129.0에 pin + 회귀 테스트. 새 버전 감지 시 doctor가 명시적 경고.
- Claude `--settings` 스키마 변경 → AgentLens-owned 블록을 별도 키로 격리 (`agentlens` 네임스페이스).

---

### 3.9 M8 - Hardening (Redaction / Retention / Non-Blocking)

**목적**
보안·프라이버시·복원력 invariant를 잠근다. 이 단계는 "기능 추가"가 아니라 "invariant 회귀 테스트 작성"이 본질.

**산출물**
- `src/agentlens/redaction/{patterns,redact}.py`
- `src/agentlens/store/retention.py`, `commands/gc.py`
- `tests/integration/test_nonblocking.py`
- `tests/integration/test_eval_determinism.py`
- `tests/unit/test_redaction.py`, `test_retention.py`

**의존성**
- M7 완료 (모든 write path가 redaction 적용 가능 상태)

**작업 단위**
- T8.1 Redaction engine (allow-list excerpt + 패턴 마스크)
- T8.2 Retention + GC (`max_total_store_gb`까지 enforce)
- T8.3 Non-blocking fault-injection regression
- T8.4 Determinism regression (M2에서 시작, 여기서 잠금)

**Exit Criteria**
- [ ] `tests/unit/test_redaction.py`에서 다음 fixture에 대해 모두 마스크 확인:
  - `~/Users/foo/...` (absolute home path)
  - `sk-...`, `pk_live_...` 형태 API key
  - `Authorization: Bearer ...` 헤더 라인
  - `-----BEGIN PRIVATE KEY-----`
- [ ] `excerpt.max_chars=4096` 강제 (writer가 길이 검사)
- [ ] excerpt는 자유 텍스트 슬라이스 금지, allow-list extractor만 호출
- [ ] writer는 redaction 적용 후 최종 persisted document를 다시 schema validate한다.
- [ ] `schema`, `run_id`, `workspace_id`, `*_hash`, `sha256`, enum/status 필드는 redaction이 변형하지 않는 protected key로 처리한다.
- [ ] GC `--dry-run` 출력에 삭제될 artifact 목록, 실제 GC 시 동일 목록 삭제
- [ ] `max_total_store_gb=5` 초과 시 oldest sealed run의 artifact부터 삭제, eval/final/manifest summary는 보존
- [ ] SQLite 부재 상태에서도 GC가 full-scan으로 동작
- [ ] fault-injection 6종 (run initialization fail, manifest write fail, evaluator crash, SQLite update fail, pre_eval seal fail, SIGINT)에서 child exit code 모두 보존
- [ ] determinism: fixture 5종에 대해 evaluator 2회 실행 결과 byte-equal (timestamp normalize 후)

**검증**
```bash
pytest tests/unit/test_redaction.py tests/unit/test_retention.py -v
pytest tests/integration/test_nonblocking.py tests/integration/test_eval_determinism.py -v
```

**리스크 / 완화**
- redaction false negative (시크릿이 패턴에 안 잡혀 통과) → 매 릴리스마다 known-secret fixture에 신규 패턴 추가, 회귀 잠금.
- retention이 eval/final summary까지 지움 → `keep_eval_summaries=true` 기본, 테스트로 강제.

---

## 4. 의존성 그래프 (작업 단위 수준)

```
T0.1 docs ──┐
T0.2 schema ─┤
            ├──► T1.1 ids/paths ──► T1.2 writer ──► T1.3 manifest ──► T1.4 eval-stub + show
            │                                                              │
            │                                                              ├──► T2.1~T2.4 evaluator hardening
            │                                                              │
            │                                                              ├──► T3.1~T3.3 sqlite index
            │                                                              │
            │                                                              ▼
            │                                                          T4.1~T4.3 query
            │                                                              │
            │                                                              ▼
            │                                                          T5.1~T5.4 wrapper
            │                                                              │
            │                                                              ▼
            │                                                          T6.1~T6.4 install/shim/doctor
            │                                                              │
            │                                                              ▼
            │                                                          T7.1~T7.3 adapter
            │                                                              │
            │                                                              ▼
            └──────────────────────────────────────────────────────────► T8.1~T8.4 hardening
```

**병렬 가능 구간**
- T2.x 와 T3.x: M1 완료 후 동시 가능
- T7.1/T7.2/T7.3: 서로 독립, 동시 가능

**Critical Path**
- T0.2 → T1.x → T2.x → T4.x → T5.x → T6.x → T7.x → T8.x
- 약 23일 (32일 중 약 70%가 critical path)

---

## 5. 품질 게이트

모든 마일스톤 PR은 아래 4개 게이트를 통과해야 머지 가능.

### 5.1 Lint
```bash
ruff check .
```
- 사용 규칙 셋: `E`, `F`, `I`, `B`, `UP`, `SIM`, `RUF`
- 0 error 강제. warning은 PR description에 명시.

### 5.2 Type check
```bash
pyright
```
- `strict` 모드. JSON Schema가 계약의 source of truth다. Pydantic 모델은 선택적 생성물이며, hand-maintained 모델이 schema 계약을 대체하면 안 된다.

### 5.3 Test
```bash
pytest -v
```
- unit + integration 전체 green
- 신규 코드는 신규 테스트와 함께 PR
- 마일스톤별 fault-injection 테스트가 회귀 잠금 역할

### 5.4 Schema drift check
```bash
python -m agentlens.schema.check_drift
```
- jsonschema 변경 시 examples 디렉터리 동기화 강제
- v1 잠금 위반(스키마 const 변경 등) 시 fail

---

## 6. 위험 관리

### 6.1 식별된 리스크 (impact × likelihood)

| ID | 리스크 | Impact | Likelihood | 완화 |
|---|---|---|---|---|
| R1 | Codex App `app-server` protocol 비공식/변경 | High | High | `native-experimental` 표기 + watcher fallback 필수 |
| R2 | 과도한 로그 수집으로 시크릿 누출 | Critical | Medium | 기본 minimal 모드 + allow-list excerpt + redaction 회귀 테스트 |
| R3 | SQLite를 canonical로 오해 → 손상 복구 불가 | High | Medium | 코드 리뷰 규칙 + SQLite 부재 fallback 테스트 |
| R4 | agent의 success claim을 그대로 신뢰 | High | High | `final.json` vs `eval.json` 분리 + query에서 `eval.json` 우선 |
| R5 | scope creep (Dashboard, MCP, importer) | Medium | High | `docs/cli.md`에서 deferred 명시, help 출력에서 제외 |
| R6 | shim hijack | Critical | Low | 0700 권한 + lockfile sha256 + drift 경고 |
| R7 | AgentLens 실패가 child 실패로 전파 | Critical | Medium | fault-injection 6종 회귀 테스트 (M8) |
| R8 | Claude/Codex 버전 업데이트로 detect 깨짐 | Medium | High | fixture pin + doctor 경고 + minimal fallback |
| R9 | run 초기화 실패가 child spawn 자체를 막음 | Critical | Medium | init failure passthrough 테스트를 M5/M8에 추가 |
| R10 | stdout/stderr pipe deadlock | High | Medium | dual-stream drain 구현 + large-output 회귀 |
| R11 | worktree/main checkout workspace_id 충돌 | High | Medium | persisted workspace_id + worktree identity 테스트 |

### 6.2 Escalation 기준

- R1, R4, R7이 GA 직전까지 회귀 테스트로 잠기지 않으면 ship 보류.
- R2는 매 릴리스에서 known-secret fixture 통과 필수.

---

## 7. 검증 전략 요약

### 7.1 테스트 피라미드

```
            /\
           /e2e\         tests/integration/  (~ 6개)
          /------\         - test_cli_lifecycle.py
         /  unit  \        - test_process_wrapper.py
        /  + fixture\     - test_install_doctor.py
       /  - 5 runs  \     - test_nonblocking.py
      /---------------\   - test_eval_determinism.py
     /                 \  
    /   unit (≈ 12개)   \
   /                     \
  /-----------------------\
```

### 7.2 회귀 잠금 테스트 (반드시 통과)

- `test_schema_validation.py` — 계약 잠금
- `test_eval_determinism.py` — evaluator 결정성 잠금
- `test_nonblocking.py` — non-blocking invariant 잠금
- `test_shim_security.py` — supply-chain 보안 잠금
- `test_redaction.py` — 시크릿/경로 leak 잠금
- `test_query_fallback.py` — SQLite 부재/손상 시 durable-store full-scan 잠금

이 회귀 잠금 테스트가 깨지면 무조건 fix-first, 새 기능 머지 금지.

### 7.3 수동 smoke (v0 GA 직전)

```bash
ruff check . && pyright && pytest -v
python -m agentlens.cli doctor integrations --format json
python -m agentlens.cli run -- sh -c 'echo hello && exit 0'
python -m agentlens.cli latest
python -m agentlens.cli show --latest --format json
python -m agentlens.cli failures
python -m agentlens.cli risks
python -m agentlens.cli gc --dry-run
```

각 명령이 정상 종료 + JSON parsable + 절대 경로 leak 없음 확인.

---

## 8. 커밋 시퀀스 (권장)

각 마일스톤이 1~2 커밋으로 정리되도록 한다. squash 권장.

```
1.  docs: define agentlens v0 contract                      (M0)
2.  feat: add agentlens schema validation                    (M0)
3.  feat: add durable run store with two-phase manifest seal (M1)
4.  feat: add vertical-slice evaluator stub and show --latest (M1)
5.  feat: harden deterministic evaluator with full check set (M2)
6.  feat: add sqlite run index with full-scan rebuild        (M3)
7.  feat: add status, failures, risks, --format json         (M4)
8.  feat: add process wrapper with SIGINT handling           (M5)
9.  feat: add install/doctor and shims with permission+lockfile (M6)
10. feat: add claude stream-json and codex integration probes (M7)
11. feat: add redaction, retention, non-blocking regression  (M8)
12. docs: document v0 operations and limitations             (release)
13. chore: tag v0.1.0                                        (release)
```

---

## 9. v0 → v1 진입 기준

다음을 만족하면 v1 작업(Dashboard, MCP API, importer 등) 착수 검토.

- v0 GA 후 4주 동안 회귀 잠금 테스트 모두 green 유지
- 실제 사용자(=본인) 환경에서 누적 50개 run 이상 기록되고 `eval.json` 결정성 회귀 0건
- Codex App watcher가 한 번 이상 fixture 업데이트로 회귀를 잡아낸 경험
- 사용자(=본인)가 `agentlens risks` 출력을 최소 1회 작업 회고에 활용한 사례

이 조건 전에 v1 기능 추가하면 core contract 안정화가 흔들린다.

---

## 10. 부록 — 마일스톤별 산출물 매핑 (한 눈에 보기)

| 마일스톤 | 핵심 파일 | 핵심 테스트 |
|---|---|---|
| M0 | `docs/{contract,security,integrations,cli}.md`, `schema/jsonschema/*.json` | `test_schema_validation.py` |
| M1 | `ids.py`, `time.py`, `store/{paths,writer,manifest}.py`, `evaluator/engine.py` (stub), `commands/{start,mark,attach,final,seal,eval,show}.py` | `test_cli_lifecycle.py`, `test_manifest.py`, `test_paths.py`, `test_ids.py` |
| M2 | `evaluator/{checks,failures,engine}.py`, `tests/fixtures/*_run/` | `test_evaluator_checks.py`, `test_eval_determinism.py` |
| M3 | `store/{sqlite_index,query}.py` | `test_sqlite_index.py`, `test_query_fallback.py` |
| M4 | `commands/show.py` (확장) | `test_cli_lifecycle.py` (확장) |
| M5 | `adapters/process.py` | `test_process_wrapper.py` |
| M6 | `adapters/shims.py`, `commands/{install,doctor,mode}.py`, `config.py` | `test_install_doctor.py`, `test_shim_security.py`, `test_config.py` |
| M7 | `adapters/{claude,codex_cli,codex_app}.py` | `test_install_doctor.py` (확장) |
| M8 | `redaction/{patterns,redact}.py`, `store/retention.py`, `commands/gc.py` | `test_redaction.py`, `test_retention.py`, `test_nonblocking.py` |

엔지니어 관점 모듈 명세·함수 시그니처·핵심 알고리즘은 `docs/spec/agentlens_v0_implementation_spec.md` 참조.
