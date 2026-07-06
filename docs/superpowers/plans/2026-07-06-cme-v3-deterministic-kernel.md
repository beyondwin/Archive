# CME v3.0 Deterministic Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CME(kws-claude-multi-agent-executor)의 프로즈 상태머신을 결정론적 스크립트 커널(`scripts/kernel/`)로 이관하고, 디스패치를 headless-first(`claude -p --json-schema`)로 전환한다.

**Architecture:** 커널 CLI(`kernel.py`)가 `init → next → (LLM이 액션 수행) → submit` 사이클로 판정·기록·전이를 전담한다. state.json의 단일 작성자는 커널이며, LLM 오케스트레이터는 커널이 반환한 액션의 수행자다. CPE(kws-codex-plan-executor)의 검증된 모듈(parse_plan, task packets, preflight dispatch, recovery, drift, run_quality)을 포팅해 커널 모듈로 흡수한다.

**Tech Stack:** Python 3 표준 라이브러리만 (기존 스크립트 컨벤션 유지 — 외부 의존 없음). 테스트는 기존 컨벤션대로 `scripts/kernel/test_*.py` 자체 실행형(assert + `python3 <file>` 실행).

**Spec:** `docs/superpowers/specs/2026-07-06-cme-v3-deterministic-kernel-design.md`

## Global Constraints

- 스킬 루트: `skills/kws-claude-multi-agent-executor/` (이하 모든 상대 경로의 기준). CPE 포팅 원본은 `skills/kws-codex-plan-executor/scripts/`.
- 경로 규약 유지: `<worktree>` = `$HOME/.claude/worktrees/<RUN_ID>/`, `<orch_dir>` = `$HOME/.claude/orchestrator/<RUN_ID>/`, `RUN_ID` = `<plan-slug>-<YYYYMMDD-HHMMSS>`.
- state.json 단일 작성자는 커널. LLM 프로즈가 state를 직접 쓰는 경로를 새로 만들지 않는다.
- 품질 임계값 불변: SPEC 0.85 / QUALITY 0.75 / WARN 0.70·0.60. 리트라이 예산 불변: 리뷰 3 / 검증 3 / 에스컬레이션 3.
- 기본 transport는 `"p"`. `claude -p` 호출에는 항상 `--output-format json --json-schema <schema> --model <명시적 모델>`을 포함한다. 모델 기본값: orchestrator=opus, 전 서브에이전트=`claude-sonnet-4-6`.
- 커널 자체 오류·state 쓰기 실패는 하드 홀트. 프로즈 대체 진행 금지.
- 순수 stdlib: `jsonschema` 등 서드파티 패키지 도입 금지 (미니멀 검증기를 직접 구현).
- 실험 프로토콜: 모든 작업은 `docs/experiments/v3.0-deterministic-kernel/` 기록 아래에서 진행. ADR이 필요한 판단은 `decisions/D###-*.md`로 남기고 커밋 메시지에 참조.
- 각 태스크의 커밋은 스킬 디렉터리 내 변경만 담는다 (`git add skills/kws-claude-multi-agent-executor/...`). `.DS_Store` 제외.
- 기존 v2 스크립트는 Wave 3 이전에는 삭제하지 않는다 (커널이 흡수 완료 후 T15에서 정리).

---

### Task 1: 실험 기록 개설 + 커널 스캐폴드 + 원자적 state I/O

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/docs/experiments/v3.0-deterministic-kernel/README.md` (템플릿 복사: `docs/experiments/_template/README.md`)
- Create: `skills/kws-claude-multi-agent-executor/docs/experiments/v3.0-deterministic-kernel/JOURNAL.md` (템플릿 복사)
- Create: `skills/kws-claude-multi-agent-executor/docs/experiments/v3.0-deterministic-kernel/decisions/` , `findings/` (빈 디렉터리, `.gitkeep`)
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/__init__.py` (빈 파일)
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/statefile.py`
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_statefile.py`

**Interfaces:**
- Produces: `statefile.read_state(path: str) -> dict` — JSON 로드, 파일 없으면 `FileNotFoundError`.
- Produces: `statefile.write_state(path: str, state: dict) -> None` — `<path>.lock`에 `fcntl.flock` 배타 잠금 → `<path>.tmp`에 dump → `os.replace` → 재읽기 검증. 재읽기 실패 시 `StateWriteError` (하드 홀트 신호).
- Produces: `statefile.active(state: dict) -> dict` — `<active>` 해석: `plan_chain` 존재 시 `state["plan_chain"][state["active_plan"]]`, 아니면 `state` 자신.
- Produces: `statefile.StateWriteError(Exception)`.
- Produces: `kernel.py` CLI 골격 — `init|next|submit|check-stop|finalize|inspect` 서브커맨드 라우팅(argparse), 미구현 서브커맨드는 exit 3 + `{"error": "not_implemented"}` 출력. 모든 서브커맨드는 결과를 stdout에 JSON 한 덩어리로 출력.

- [ ] **Step 1: 실험 디렉터리 생성** — `_template/`의 README.md·JOURNAL.md를 복사하고 README에 실험명(v3.0-deterministic-kernel), 가설("판정·기록을 커널로 이관하면 프로즈-스킵 회귀 클래스가 소멸한다"), 스펙 링크를 채운다. JOURNAL 첫 엔트리에 착수 기록.
- [ ] **Step 2: 실패하는 테스트 작성** — `test_statefile.py`:

```python
import json, os, tempfile, threading
import statefile

def test_roundtrip():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "state.json")
    statefile.write_state(p, {"schema_version": 3, "tasks": {}})
    assert statefile.read_state(p)["schema_version"] == 3

def test_atomic_no_partial():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "state.json")
    statefile.write_state(p, {"schema_version": 3, "big": "x" * 100000})
    # 동시 쓰기 경쟁에서도 항상 파싱 가능한 전체 문서만 관측되어야 한다
    def writer(i):
        statefile.write_state(p, {"schema_version": 3, "n": i, "big": "y" * 100000})
    ts = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    obj = statefile.read_state(p)
    assert obj["schema_version"] == 3 and "n" in obj

def test_active_resolution():
    single = {"schema_version": 3, "tasks": {"task_1": {}}}
    assert statefile.active(single) is single
    multi = {"schema_version": 3, "active_plan": 1,
             "plan_chain": [{"tasks": {}}, {"tasks": {"task_9": {}}}]}
    assert "task_9" in statefile.active(multi)["tasks"]

if __name__ == "__main__":
    test_roundtrip(); test_atomic_no_partial(); test_active_resolution()
    print("OK")
```

- [ ] **Step 3: 실패 확인** — `cd skills/kws-claude-multi-agent-executor && python3 scripts/kernel/test_statefile.py` → `ModuleNotFoundError: statefile` 로 FAIL.
- [ ] **Step 4: 구현** — `statefile.py`:

```python
import fcntl, json, os

class StateWriteError(Exception):
    pass

def read_state(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_state(path, state):
    lock_path = path + ".lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        try:
            read_state(path)
        except Exception as e:
            raise StateWriteError(f"post-write verification failed: {e}")

def active(state):
    if "plan_chain" in state:
        return state["plan_chain"][state["active_plan"]]
    return state
```

`kernel.py`: argparse 서브파서 6종을 등록하고 각각 `--state`(init 제외) 필수 인자, 핸들러 딕셔너리로 라우팅. 파일 상단에 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` 로 형제 모듈 import 보장.
- [ ] **Step 5: 통과 확인** — 같은 명령 → `OK`. 추가: `python3 scripts/kernel/kernel.py next --state /nonexistent; echo "exit=$?"` → `{"error": "not_implemented"}` + `exit=3`.
- [ ] **Step 6: 커밋** — `git commit -m "feat(cme-kernel): scaffold kernel package with atomic state IO (v3.0 T1)"`

---

### Task 2: init.py — 결정론적 인자 파서 + run-id/경로 + echo line

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/initcmd.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_initcmd.py`
- Modify: `skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py` (init 서브커맨드 연결)

**Interfaces:**
- Consumes: `statefile.write_state`.
- Produces: `initcmd.parse_args(raw: str) -> dict` — 반환 config 키: `plans: list[{"plan": path, "spec": path}]`, `implementer_model: "sonnet"|"opus"`, `parallel: bool`, `risk: None|"low"|"mid"|"high"`, `docs_scope: None|list[str]`, `mode: "kernel"`, `detach: bool`, `transport_default: "p"`, `sources: dict[key -> "explicit"|"nl"|"default"]`. 충돌 시 `initcmd.ConflictHalt(Exception)` (메시지에 충돌 항목 나열).
- Produces: `initcmd.echo_line(config) -> str` — 한 줄 요약(플랜 수, 모델, parallel, transport, risk + 각 값의 출처).
- Produces: `initcmd.derive_run_id(plan_path: str, now: datetime) -> str` — `<plan-slug>-<YYYYMMDD-HHMMSS>`.
- 파싱 규칙은 기존 SKILL.md Phase -1.0과 동일: Pass 1 `key=value`, Pass 2 `plan\d*=` 멀티플랜 스캔(간극 halt, specN 누락 halt), Pass 3 NL 렉시콘(`opus/오푸스, sonnet/소넷, 순차/sequential/직렬/시리얼, 대화형/interactive` — `/`·`.`·`=`·백틱 포함 토큰 제외, explicit이 항상 우선, NL은 미설정 키만 채움). 참조 원본: `references/phases/phase-minus-1-args-and-spawn.md`.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_initcmd.py` 핵심 케이스:

```python
import datetime
import initcmd

def test_single_plan_defaults():
    c = initcmd.parse_args("plan=docs/p.md spec=docs/s.md")
    assert c["plans"] == [{"plan": "docs/p.md", "spec": "docs/s.md"}]
    assert c["implementer_model"] == "sonnet" and c["parallel"] is True
    assert c["transport_default"] == "p"
    assert c["sources"]["implementer_model"] == "default"

def test_multi_plan_gap_halts():
    try:
        initcmd.parse_args("plan=a.md spec=s.md plan3=c.md spec3=s3.md")
        assert False, "expected ConflictHalt"
    except initcmd.ConflictHalt as e:
        assert "plan2" in str(e)

def test_nl_lexicon_fills_unset():
    c = initcmd.parse_args("plan=a.md spec=s.md 오푸스 순차")
    assert c["implementer_model"] == "opus" and c["parallel"] is False
    assert c["sources"]["implementer_model"] == "nl"

def test_explicit_beats_nl_conflict_halts():
    try:
        initcmd.parse_args("plan=a.md spec=s.md implementer_model=sonnet 오푸스")
        assert False
    except initcmd.ConflictHalt:
        pass

def test_run_id():
    rid = initcmd.derive_run_id("docs/plans/my plan v2.md",
                                datetime.datetime(2026, 7, 6, 9, 5, 1))
    assert rid == "my-plan-v2-20260706-090501"

if __name__ == "__main__":
    test_single_plan_defaults(); test_multi_plan_gap_halts()
    test_nl_lexicon_fills_unset(); test_explicit_beats_nl_conflict_halts()
    test_run_id(); print("OK")
```

- [ ] **Step 2: 실패 확인** — `python3 scripts/kernel/test_initcmd.py` → import 에러 FAIL.
- [ ] **Step 3: 구현** — `references/phases/phase-minus-1-args-and-spawn.md`의 Phase -1.0 규칙을 읽고 세 패스를 함수로 구현. 슬러그: 소문자화 + 영숫자 외 `-` 치환 + 연속 `-` 압축 + 확장자 제거. `mode=interactive`/`detach=true` 토큰은 파싱하되 config에 보존만 한다(커널 사이클은 동일).
- [ ] **Step 4: 통과 확인** — `python3 scripts/kernel/test_initcmd.py` → `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): deterministic arg parser with echo line (v3.0 T2)`

---

### Task 3: init 완성 — worktree/훅/state v3 생성 + v2 마이그레이션 심

**Files:**
- Modify: `skills/kws-claude-multi-agent-executor/scripts/kernel/initcmd.py`
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/migrate.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_migrate.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_init_run.py`

**Interfaces:**
- Consumes: 기존 `scripts/materialize_worktree_hooks.py` (subprocess로 호출 — 재작성하지 않음), `scripts/migrate_legacy_state.py`의 변환 규칙(코드를 `migrate.py`로 이식하되 원본은 T15까지 유지).
- Produces: `initcmd.run_init(raw_args: str, home: str, repo_root: str, dry_run: bool=False) -> dict` — 순서: dirty-tree 검사(비어있지 않으면 `{"halt": "dirty_worktree", ...}` 반환) → run_id/경로 생성 → `git worktree add` → materialize_worktree_hooks 호출(비정상 종료 = 하드 홀트) → `<orch_dir>/{packets,prompts,results,hooks}` 생성 → state v3 작성 → `{"state_path", "run_id", "echo_line"}` 반환. `dry_run=True`면 파일시스템 변경 없이 계획만 반환(테스트용).
- Produces: `migrate.to_v3(old_state: dict) -> dict` — v2.x state 감지(`schema_version` 부재 또는 < 3) 시 단방향 변환: 알려진 필드는 v3 위치로 매핑, 미지 필드는 `state["legacy"]`에 보존. `plan2_state` 구형은 먼저 `plan_chain`으로 재작성(기존 migrate_legacy_state.py 규칙).
- Produces: state v3 최소 스키마 (이후 모든 태스크가 이 형태를 소비):

```json
{
  "schema_version": 3,
  "run_id": "...", "source_repo": "...", "branch": "...",
  "worktree": "...", "orchestrator_dir": "...",
  "mode": "kernel", "transport_default": "p",
  "implementer_model": {"used": "sonnet", "default": "sonnet"},
  "parallel": true, "dispatch_config": {},
  "timestamps": {"started_at": "...", "completed_at": null},
  "cost_ledger": {"totals": {"dispatches": 0, "input_tokens": 0,
                   "output_tokens": 0, "cost_usd": 0.0}, "by_task": {}},
  "plan": "...", "spec": "...",
  "tasks": {}, "task_summaries": {}, "quality_trend": [],
  "execution_plan": [], "risk_levels": {}, "task_complexity": {},
  "spec_manifest": null, "decisions_register": [],
  "run_quality": null, "completion_audit": null, "drift": null,
  "status": "SETUP", "current_task": null, "last_completed_task": null
}
```

(멀티플랜이면 per-plan 필드가 `plan_chain[N]` 아래로 — `statefile.active` 해석 규칙과 동일.)

- [ ] **Step 1: 실패하는 테스트 작성** — `test_migrate.py`: v2.29 형태 픽스처(최소: `plan/spec/tasks/task_summaries/mode:"interactive_attached"` + `plan2_state` 케이스 1개)를 인라인 dict로 두고 `to_v3` 후 `schema_version==3`, tasks 보존, 미지 필드가 `legacy`에 있는지, `plan2_state`가 `plan_chain` 2원소로 변환되는지 assert. `test_init_run.py`: `dry_run=True`로 경로 계획(worktree/orch_dir 형제 구조, run_id 접미 일치)과 dirty-tree halt 분기를 assert.
- [ ] **Step 2: 실패 확인** — 두 테스트 실행 → FAIL.
- [ ] **Step 3: 구현** — `scripts/migrate_legacy_state.py`를 읽고 변환 규칙을 `migrate.py`로 이식. `run_init`은 subprocess로 `git status --porcelain`, `git worktree add`, `python3 scripts/materialize_worktree_hooks.py`를 호출. state 작성은 `statefile.write_state`.
- [ ] **Step 4: 통과 확인** — 두 테스트 `OK`.
- [ ] **Step 5: kernel.py에 init 연결 후 수동 스모크** — `python3 scripts/kernel/kernel.py init --args "plan=X spec=Y" --dry-run` → 계획 JSON + echo line 출력 확인.
- [ ] **Step 6: 커밋** — `feat(cme-kernel): init with worktree, hooks, state v3, v2 migration (v3.0 T3)`

---

### Task 4: plan.py — 플랜 기계 판독 (CPE parse_plan 포팅)

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/planparse.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_planparse.py`

**Interfaces:**
- Consumes (포팅 원본): `skills/kws-codex-plan-executor/scripts/parse_plan.py` — 구현 전에 전체를 읽을 것.
- Produces: `planparse.parse(text: str) -> dict`:

```python
{"header_level": 2 | 3,          # 감지된 태스크 헤더 레벨 (### 우선)
 "tasks": [{"id": "task_1", "number": 1, "title": str,
            "files": [str], "dependencies": [int],
            "acceptance": str | None,      # ## Acceptance Criteria 셸 블록
            "serial": bool, "resource_key": str | None,
            "body": str}],                  # 헤더 이후 원문 (프롬프트 발췌용)
 "errors": [str]}                # no_task_headers, task_N_missing_files 등
```

- Files 블록 별칭: `Files`, `Affected files`, `Modified files`, `Changed files`, `수정 파일`, `변경 파일`, `대상 파일`, `파일`. `yaml waygent-task` / `yaml agentrunway-task` 펜스 블록의 `file_claims`도 Files로 인정.
- 리포 밖 경로(`../` 정규화 후 루트 이탈, 절대경로)는 `errors`에 `task_N_out_of_repo_path:<path>` 추가.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_planparse.py`: 인라인 마크다운 픽스처 4종 — (a) H3 표준 플랜 2태스크+Files, (b) H2 + 한국어 `수정 파일` 별칭, (c) Files 블록 없는 태스크 → errors, (d) `../escape.py` → out_of_repo error. 각각 tasks 수, files 내용, errors를 assert.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — CPE `parse_plan.py`를 읽고 포팅. CPE 결과 형태와 다른 점: task id를 `task_<N>` 문자열로, `body` 원문 보존 추가, CPE의 CLI 래퍼는 생략(커널 내부 함수로만).
- [ ] **Step 4: 통과 확인** — `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): deterministic plan parser ported from CPE (v3.0 T4)`

---

### Task 5: 역할 스키마 완성 + 미니멀 스키마 검증기

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/references/_schemas/implementer_result.schema.json`
- Create: `skills/kws-claude-multi-agent-executor/references/_schemas/reviewer_result.schema.json`
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/validate.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_validate.py`

**Interfaces:**
- Consumes: 기존 4종 스키마(`references/_schemas/{docs_updater,plan_reviewer,transition_combined,verifier}_result.schema.json`) — 그대로 재사용.
- Produces: `validate.check(instance: dict, schema: dict) -> list[str]` — 지원 키워드: `type`(object/array/string/number/integer/boolean/null), `required`, `properties`, `items`, `enum`, `additionalProperties: false`. 에러는 `"<json-path>: <이유>"` 문자열 리스트, 빈 리스트 = 유효.
- Produces: `implementer_result.schema.json` — 기존 Implementer 텍스트 마커 계약(`references/implementer-prompt.md`의 출력 형식 참조)의 스키마화:

```json
{"$schema": "https://json-schema.org/draft/2020-12/schema",
 "$id": "implementer_result.schema.json",
 "type": "object", "additionalProperties": false,
 "required": ["status", "summary", "files_changed", "files_test_changed"],
 "properties": {
   "status": {"enum": ["DONE", "ESCALATE"]},
   "summary": {"type": "string"},
   "files_changed": {"type": "array", "items": {"type": "string"}},
   "files_test_changed": {"type": "array", "items": {"type": "string"}},
   "commit": {"type": "string"},
   "method_audit": {"type": "object", "additionalProperties": false,
     "properties": {
       "tdd": {"enum": ["applied", "waived"]},
       "waive_reason": {"enum": ["docs-only-task", "config-only-task",
                                  "generated-only-task"]},
       "red_command": {"type": "string"}, "green_command": {"type": "string"}}},
   "key_decision": {"type": "string"},
   "escalate": {"type": "object", "additionalProperties": false,
     "required": ["type", "question"],
     "properties": {"type": {"enum": ["AMBIGUITY", "SPEC_BLOCKER", "ENV_BLOCKER"]},
                    "evidence": {"type": "string"},
                    "question": {"type": "string"}}}}}
```

- Produces: `reviewer_result.schema.json` — Combined Reviewer 계약: `required: [status, spec_score, quality_score, issues]`, `status: {enum: [PASS, WARN, FAIL, SPEC_FAULT]}`, `spec_score`/`quality_score`: number, `issues`: array of `{severity: {enum: [SPEC, QUALITY, ADVISORY]}, issue_key: string, file: string, description: string}`, `spec_fault: {enum: [spec_contradicts, unclear]}` (optional), `escalate` 오브젝트는 implementer와 동일 형태.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_validate.py`: (a) 유효 implementer DONE 결과 → `[]`, (b) status 누락 → required 에러, (c) 미지 필드 + additionalProperties:false → 에러, (d) `method_audit.waive_reason` enum 위반 → 에러, (e) 기존 `verifier_result.schema.json` 로드해 유효 픽스처 통과 (기존 스키마 호환 확인).
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — `validate.check` 재귀 구현(~80줄) + 스키마 2종 작성. `$ref`는 기존 plan_reviewer 스키마가 사용하므로 `$defs` 로컬 참조만 지원.
- [ ] **Step 4: 통과 확인** — `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): implementer/reviewer schemas + stdlib validator (v3.0 T5)`

---

### Task 6: transitions.py — 전이 규칙 엔진

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/transitions.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_transitions.py`

**Interfaces:**
- Consumes: `statefile.active`, `validate.check`.
- Produces: `transitions.decide(state: dict) -> dict` — 현재 state만 보고 다음 액션 반환. 액션 타입: `{"action": "dispatch", "role": ..., "task_id": ..., "attempt": int}` / `{"action": "run_command", "purpose": "baseline"|"acceptance", "command": str}` / `{"action": "compact"}` / `{"action": "escalate_to_user", "reason": ..., "questions": [...]}` / `{"action": "finalize"}` / `{"action": "halt", "reason": ...}` / `{"action": "done"}`.
- Produces: `transitions.apply_result(state: dict, task_id: str, role: str, payload: dict) -> dict` — 검증된 결과를 반영한 새 state 반환(원본 불변). 규칙 (전부 기존 SKILL.md 가드레일의 코드화):
  - implementer DONE → 태스크 `phase: "review"`; ESCALATE → 에스컬레이션 카운트+1(태스크당 3 초과 시 태스크 halt).
  - reviewer PASS(spec≥0.85 ∧ quality≥0.75) → risk LOW면 `PENDING_BATCH`, MID/HIGH면 `phase: "verify"`. WARN 티어(0.70/0.60 플로어) → 리트라이 소모 없이 진행 + `warnings` 기록. FAIL → `review_retries`+1 (3 초과 → `SKIPPED` + `verification_gaps` 기록, 런은 계속). SPEC_FAULT → `spec_clarifications`+1 (리뷰 예산 비소모, 3 초과 시 escalate_to_user).
  - verifier PASS → `COMPLETE` + `last_completed_task` 갱신 + `quality_trend` append(rolling 10). FAIL → `verifier_retries`+1, 액션에 `pre_task_sha` 리셋 지시 포함 (3 초과 → reset + SKIPPED + gaps).
  - `decide`의 컴팩션 트리거: `<active>.compaction_points`에 도달한 직후 `compact` 액션 (T1 배치 verifier → T2 docs → T3 앵커 순서는 compact 액션의 `steps` 필드에 명시).
- Produces: `transitions.record_timing(state, task_id, event: "started"|"completed", now_iso: str) -> dict` — decide가 dispatch를 반환할 때 kernel.py가 자동 호출 (프로즈 스탬프 제거의 핵심).

- [ ] **Step 1: 실패하는 테스트 작성** — 전이 표를 데이터로 검증. 최소 케이스 10개:

```python
import transitions

def _state_one_task(risk="mid"):
    return {"schema_version": 3, "status": "RUNNING", "current_task": "task_1",
            "risk_levels": {"task_1": risk}, "execution_plan": [["task_1"]],
            "tasks": {"task_1": {"status": "IN_PROGRESS", "phase": "implement",
                                  "review_retries": 0, "verifier_retries": 0,
                                  "escalations": 0, "timing": {}}},
            "task_summaries": {}, "quality_trend": [],
            "cost_ledger": {"totals": {"dispatches": 0}, "by_task": {}}}

def test_implementer_done_moves_to_review():
    s = transitions.apply_result(_state_one_task(), "task_1", "implementer",
        {"status": "DONE", "summary": "x", "files_changed": ["a.py"],
         "files_test_changed": ["test_a.py"], "commit": "abc"})
    assert s["tasks"]["task_1"]["phase"] == "review"

def test_review_fail_burns_retry_then_skip():
    s = _state_one_task()
    s["tasks"]["task_1"].update(phase="review", review_retries=3)
    s2 = transitions.apply_result(s, "task_1", "reviewer",
        {"status": "FAIL", "spec_score": 0.5, "quality_score": 0.5, "issues": []})
    assert s2["tasks"]["task_1"]["status"] == "SKIPPED"
    assert "verification_gaps" in s2["tasks"]["task_1"]

def test_warn_tier_proceeds_without_retry():
    s = _state_one_task(); s["tasks"]["task_1"]["phase"] = "review"
    s2 = transitions.apply_result(s, "task_1", "reviewer",
        {"status": "WARN", "spec_score": 0.72, "quality_score": 0.65, "issues": []})
    assert s2["tasks"]["task_1"]["review_retries"] == 0
    assert s2["tasks"]["task_1"]["phase"] == "verify"

def test_low_risk_pass_goes_pending_batch():
    s = _state_one_task(risk="low"); s["tasks"]["task_1"]["phase"] = "review"
    s2 = transitions.apply_result(s, "task_1", "reviewer",
        {"status": "PASS", "spec_score": 0.9, "quality_score": 0.8, "issues": []})
    assert s2["tasks"]["task_1"]["status"] == "PENDING_BATCH"

def test_all_terminal_decides_finalize():
    s = _state_one_task()
    s["tasks"]["task_1"].update(status="COMPLETE", phase=None)
    assert transitions.decide(s)["action"] == "finalize"

if __name__ == "__main__":
    # ... 나머지: spec_fault 예산, escalation cap, verifier fail reset 지시,
    # compact 트리거, dispatch가 attempt 번호를 올리는지
    print("OK")
```

- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — SKILL.md Guardrails 표와 `references/phases/phase-1-task-cycle.md`의 판정 규칙을 읽고 순수 함수로 구현. 판단이 갈리는 지점(예: WARN 3연속 처리)은 현행 문서 그대로 코드화하고 ADR 불필요; 문서에 없는 새 규칙을 도입하게 되면 `decisions/D001`로 기록.
- [ ] **Step 4: 통과 확인** — `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): transition rule engine codifying guardrails (v3.0 T6)`

---

### Task 7: dispatch.py — 프롬프트 조립 + headless 커맨드 생성

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/dispatch.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_dispatch.py`

**Interfaces:**
- Consumes: `planparse.parse` 결과의 task `body`, 기존 프롬프트 템플릿(`references/implementer-prompt.md`, `reviewer-prompt.md`, `verifier-prompt.md`, `docs-updater-prompts.md`, `plan-reviewer-prompt.md`)과 `references/_scaffolds/` — 템플릿은 수정하지 않고 소비만.
- Produces: `dispatch.build(state, action, skill_dir, orch_dir) -> dict`:

```python
{"prompt_path": "<orch_dir>/prompts/implementer_task_3_a1.md",
 "schema_path": "<skill_dir>/references/_schemas/implementer_result.schema.json",
 "result_path": "<orch_dir>/results/implementer_task_3_a1.json",
 "transport": "p",                      # state.dispatch_config[gate] 반영
 "model": "claude-sonnet-4-6",          # implementer_model.used 매핑, 항상 명시
 "cwd": "<worktree>",
 "command": "claude -p \"$(cat <prompt_path>)\" --output-format json "
            "--json-schema <schema_path> --model <model> "
            "--dangerously-skip-permissions > <result_path>"}
```

- 텍스트 마커 출력 지시 대체: 템플릿의 출력 형식 섹션 뒤에 커널이 `## Output contract` 블록을 덧붙여 "최종 응답은 스키마 준수 JSON"을 명시. SCAFFOLD/PAYLOAD 분할 위치는 유지(스캐폴드 바이트 불변 — `scripts/validate_scaffold_split.py`로 검증 가능해야 함).
- transport `"agent"`(opt-in) 시 `command` 대신 `{"agent_instruction": {...}}` (Agent 툴 파라미터 재료: prompt 파일 경로, model, 결과 파일 작성 지시)를 반환.

- [ ] **Step 1: 실패하는 테스트 작성** — (a) implementer 액션 → command에 `--json-schema`·`--model claude-sonnet-4-6`·`--output-format json` 포함, prompt 파일이 생성되고 `{TASK_BODY}` 류 플레이스홀더가 남아있지 않음, (b) `implementer_model.used=opus` → `--model claude-opus-4-8`, (c) `dispatch_config.verifier_per_task="agent"` → agent_instruction 분기, (d) 조립된 프롬프트의 SCAFFOLD 마커 4종 보존.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — 템플릿 로드 → `{placeholder}` 치환 맵(task body, 패킷 경로는 T10 전이라 spec 발췌로 임시, test_command, risk) → 프롬프트 파일 작성 → 커맨드 문자열 생성. 모델 매핑 상수: `{"sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}`.
- [ ] **Step 4: 통과 확인** — `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): prompt assembly and headless-first dispatch commands (v3.0 T7)`

---

### Task 8: ledger.py + events.py — usage 전사와 이벤트 tee

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/ledger.py`
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/events.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_ledger.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_events.py`

**Interfaces:**
- Consumes: `scripts/price_table.py` (subprocess 아닌 파일 로드 재사용 — `sys.path` 추가 후 import), `claude -p --output-format json` 결과 봉투.
- Produces: `ledger.extract_payload(result_file_text: str) -> tuple[dict, dict]` — `(payload, usage)`. 봉투 파싱 규칙: 최상위 JSON에서 구조화 결과는 `structured_output` 키 우선, 없으면 `result` 키(문자열이면 `json.loads` 시도), usage는 `usage` + `total_cost_usd`. 어느 쪽도 없으면 `LedgerParseError`. **주의:** 봉투 키는 CLI 버전에 따라 다를 수 있음 — T16 재베이스라인에서 실 CLI 출력으로 픽스처를 교체 검증한다.
- Produces: `ledger.record(state, task_id, role, usage) -> dict` — `cost_ledger.by_task["<plan>::<task>::<role>"]` 누적 + totals 갱신 (기존 `accumulate_cost.py` 의미 유지).
- Produces: `events.emit(orch_dir, event_type, payload, agentlens_run_id=None) -> None` — `<orch_dir>/events.jsonl`에 무조건 append(tee); `agentlens_run_id`가 있으면 `agentlens emit ... 2>/dev/null || true` best-effort. 이벤트 네임스페이스 `kws-cme.*` 유지.

- [ ] **Step 1: 실패하는 테스트 작성** — ledger: (a) `{"result": "{\"status\":\"DONE\"...}", "usage": {"input_tokens": 100, "output_tokens": 50}, "total_cost_usd": 0.01}` 픽스처 → payload dict + usage, (b) `structured_output` 키 변형, (c) 둘 다 없음 → LedgerParseError, (d) record 후 `totals.dispatches==1` and by_task 키 형식. events: emit 2회 → jsonl 2줄, 각 줄 파싱 가능 + `event_type`/`ts` 필드, agentlens 부재 환경에서도 예외 없음.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인** — `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): usage ledger and events tee (v3.0 T8)`

---

### Task 9: next/submit 사이클 통합 + 시뮬레이션 e2e

**Files:**
- Modify: `skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py` (next/submit/check-stop 핸들러)
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_cycle_e2e.py`

**Interfaces:**
- Consumes: T1–T8의 전 모듈.
- Produces: `kernel.py next --state <p>` — `transitions.decide` → dispatch 액션이면 `dispatch.build`로 재료 생성 + `transitions.record_timing(started)` + state 저장 → 완성된 액션 JSON 출력.
- Produces: `kernel.py submit --state <p> --task <id> --role <role> --result <file>` — `ledger.extract_payload` → `validate.check`(스키마 위반 시 `{"accepted": false, "violations": [...], "retry_hint": ...}` 출력, 동일 디스패치 3연속 위반이면 halt 액션 예고) → `transitions.apply_result` → `ledger.record` → `events.emit("kws-cme.task_progress", ...)` → state 저장 → `{"accepted": true, "next_hint": "<decide 미리보기>"}`.
- Produces: `kernel.py check-stop --state <p>` — 전 태스크 터미널 && finalize 미완료면 exit 2(+사유 JSON), 아니면 exit 0. (T14에서 quality 게이트가 여기 합류.)

- [ ] **Step 1: 실패하는 e2e 테스트 작성** — `test_cycle_e2e.py`: tmp 디렉터리에 2태스크 플랜(MID 1개, LOW 1개) state를 T3 스키마로 수작성 → 루프: `next` 호출(모듈 함수 직접 호출로 CLI 우회 가능하나 여기서는 `subprocess.run([sys.executable, "scripts/kernel/kernel.py", ...])`로 CLI 계약 자체를 검증) → 반환된 result_path에 가짜 유효 결과 JSON(-p 봉투 형태) 작성 → `submit` → 반복. 검증: 사이클이 implementer→reviewer→verifier(MID)→docs 순서로 진행, LOW는 PENDING_BATCH 경유, 마지막 `next`가 finalize, 종료 후 state에 `timing.started/completed` 전 태스크 non-null, `cost_ledger.totals.dispatches ≥ 5`, `events.jsonl` 존재. 무효 결과(스키마 위반) 1회 주입 → `accepted: false` 확인.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — 핸들러 연결. submit의 위반 카운터는 `tasks.<id>.schema_violations` (3연속 → halt).
- [ ] **Step 4: 통과 확인** — `OK` (이 테스트가 v3의 핵심 회귀 방어선 — 북키핑 필드가 커널 경로에서 자동으로 채워짐을 증명).
- [ ] **Step 5: 커밋** — `feat(cme-kernel): wire next/submit cycle with e2e simulation (v3.0 T9)`

---

### Task 10: packets.py — spec 매니페스트 + task packets (CPE 포팅)

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/packets.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_packets.py`
- Modify: `skills/kws-claude-multi-agent-executor/scripts/kernel/dispatch.py` (패킷 존재 시 spec 발췌 대신 패킷 사용)

**Interfaces:**
- Consumes (포팅 원본): `skills/kws-codex-plan-executor/scripts/build_spec_manifest.py`, `build_task_packet.py`, `references/unit-context-manifest.md` — 구현 전 필독. CME 기존 `scripts/build_spec_manifest.py`·`build_context_slice.py`와 중복 기능은 커널판으로 통합.
- Produces: `packets.build_manifest(spec_text: str) -> dict` — 섹션 분할(헤딩 기준) + 섹션 해시 + id.
- Produces: `packets.build_packet(task: dict, manifest: dict, spec_text: str, budget_chars: int = 60000) -> dict`:

```python
{"task_id": "task_3", "task_body": str, "files": [str],
 "spec_sections": [{"id": str, "text": str}],   # Spec Refs 명시 우선, 없으면 파일-섹션 매칭
 "fallback_used": bool, "fallback_reason": str | None,
 "next_action": str | None,     # 플랜 저자용 개선 힌트
 "budget": {"limit": int, "used": int, "status": "green"|"yellow"|"red"}}
```

- yellow = used > 0.7×limit, red = used > limit (red면 섹션을 우선순위 순으로 잘라 limit 이하로 강제 + fallback_reason 기록).
- Produces: `<orch_dir>/packets/task_N.json` 저장 + 사람용 `.md` 뷰(파생물 — JSON이 authoritative).

- [ ] **Step 1: 실패하는 테스트 작성** — (a) Spec Refs 명시 태스크 → 해당 섹션만 포함, (b) 매칭 불가 태스크 → fallback_used=true + next_action 문자열, (c) 거대 spec → red 판정 + 잘림, (d) budget.used가 실제 문자수와 일치.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — CPE 원본 포팅 + dispatch.py의 spec 발췌 로직을 패킷 소비로 교체.
- [ ] **Step 4: 통과 확인** — `test_packets.py`, `test_dispatch.py` 모두 `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): task packets with context budget (v3.0 T10, ported from CPE)`

---

### Task 11: gate.py — 리스크/웨이브/사전 디스패치 판정 (CPE 포팅 + CME 적응)

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/gate.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_gate.py`
- Modify: `skills/kws-claude-multi-agent-executor/scripts/kernel/transitions.py` (decide가 execution_plan을 gate 산출물에서 읽음)

**Interfaces:**
- Consumes (포팅 원본): `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`, `audit_plan_executability.py`. CME 기존 규칙: Phase 0 Step 4(리스크 배정·LOW 파일충돌 승격), Step 6(웨이브 분할·resource_key 직렬화) — `references/phases/phase-0-setup.md` 참조.
- Produces: `gate.assign_risk(tasks, override: str|None) -> dict[task_id, "low"|"mid"|"high"]` — 기존 기준 코드화(공유 파일 LOW 승격 포함).
- Produces: `gate.partition_waves(tasks, risk, parallel: bool) -> list[list[str]]` — 의존성 위상정렬 + `serial`/`resource_key` 싱글턴 규칙.
- Produces: `gate.preflight(task, packet, state) -> dict`:

```python
{"decision": "delegate_parallel" | "delegate_serial" | "block",
 "reason": str,
 "would_have": {"decision": str, "reason": str} | None}
```

**CME 적응 (ADR 필요 — decisions/D001로 기록):** CPE의 `local_fallback`(메인 에이전트 직접 구현)은 CME 가드레일 "오케스트레이터는 코드를 쓰지 않는다"와 충돌하므로, 가치 게이트의 결과를 "병렬 서브워크트리 디스패치 vs 메인 워크트리 직렬 디스패치"로 매핑한다. 안전 게이트(파일 중복, write-scope 초과, 패킷 red)는 `block` 유지.
- Produces: `gate.executability_audit(parsed_plan, packets) -> dict` — 태스크별 분류 + `raw_blocking_issue_count`/`blocking_issue_count` 이중 카운트 + `operator_reviewed_blocking_issues`/`operator_decision` 기록 슬롯. BLOCKER 존재 시 transitions.decide가 `escalate_to_user`(배치 질문) 반환.

- [ ] **Step 1: 실패하는 테스트 작성** — (a) 공유 파일 가진 LOW 2개 → 승격 또는 싱글턴 분리, (b) resource_key 동일 태스크 → 같은 웨이브 내 싱글턴, (c) 파일 겹치는 병렬 후보 → block, (d) AC 없는 HIGH 태스크 → executability blocking issue, (e) operator 리뷰 반영 시 effective < raw.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — 포팅 + 적응. D001 ADR 작성(local_fallback 의미 조정).
- [ ] **Step 4: 통과 확인** — `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): risk/wave partition + deterministic dispatch gate (v3.0 T11, per D001)`

---

### Task 12: recovery.py — 커맨드 관찰 분류 + root-signature 복구 (CPE 포팅)

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/recovery.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_recovery.py`
- Modify: `skills/kws-claude-multi-agent-executor/scripts/kernel/transitions.py` (verifier FAIL 경로에 recovery 선분류 삽입)

**Interfaces:**
- Consumes (포팅 원본): `skills/kws-codex-plan-executor/scripts/classify_recovery.py`, `references/command-observations.md`.
- Produces: `recovery.classify(command: str, exit_code: int, output_tail: str) -> dict` — `{"category": "source_failure"|"missing_local_env"|"dependency_bootstrap"|"resource_oom"|"timeout_or_hang"|"flaky_test"|"permission_or_sandbox"|"tooling_bug"|"unknown", "evidence": str}`.
- Produces: `recovery.decide_recovery(state, task_id, observation) -> dict` — root signature = sha256(category+command+첫 evidence 줄)[:16]; `recovery_attempts[]`에서 동일 시그니처 조회 → `{"action": "bootstrap"|"retry"|"escalate"|"implementer_retry", "root_signature": str}`. env 계열 1회차는 리트라이 예산 비소모(bootstrap/retry), 동일 시그니처 2회째부터 escalate(ENV_BLOCKER). `source_failure`만 `implementer_retry`(기존 reset+재디스패치 경로, 예산 소모).
- transitions 통합: verifier 결과에 `command_observation`이 포함되면 apply_result가 recovery를 먼저 통과시킨다. `category=unknown`으로 완주한 런은 T14의 completion_audit `residual_risk`에 해당 커맨드 기재.

- [ ] **Step 1: 실패하는 테스트 작성** — (a) `ModuleNotFoundError` output → missing_local_env + 1회차 bootstrap + 예산 비소모, (b) 동일 시그니처 2회 → escalate, (c) assert 실패 output → source_failure → implementer_retry + verifier_retries 증가, (d) 시그니처 결정성(같은 입력 = 같은 해시).
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — 포팅 + verifier 프롬프트가 이미 반환하는 커맨드 증거 필드와 배선(verifier 스키마의 `commands_run` 활용).
- [ ] **Step 4: 통과 확인** — `test_recovery.py`, `test_transitions.py` `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): env-vs-bug recovery classification (v3.0 T12, ported from CPE)`

---

### Task 13: drift.py — 드리프트 감지 + 안전 복구 (CPE 포팅)

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/drift.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_drift.py`

**Interfaces:**
- Consumes (포팅 원본): `skills/kws-codex-plan-executor/scripts/reconcile_state.py`, `repair_runs.py`, `references/drift-reconciliation.md`.
- Produces: `drift.check(state, orch_dir) -> dict` — `{"blocking": [...], "repairable": [...]}`. 감지 항목(CME 적응): 터미널 태스크의 timing null(커널 경로에선 발생 불가지만 마이그레이션 런 방어), COMPLETE인데 result 파일 부재, `timing_inverted`(un-waivable), PENDING_BATCH 잔존, worktree 유실, dispatches=0(비-waive).
- Produces: `drift.repair_safe(state, orch_dir) -> dict` — 타임스탬프 스탬핑 등 안전 항목만; blocking은 건드리지 않음. 복구 이력을 `state["drift"]["records"]`에 기록.
- Produces: `drift.repair_stale_run(state_path, apply: bool) -> dict` — dry-run 기본, `apply=True`일 때만 `lifecycle: blocked_stale` 마킹(파일 삭제 없음).

- [ ] **Step 1: 실패하는 테스트 작성** — (a) timing null 터미널 태스크 → repairable, (b) completed<started → blocking(un-waivable), (c) repair_safe 후 repairable 소거 + records 기록, (d) repair_stale_run dry-run이 파일 미변경.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — 포팅 + CME state v3 필드 매핑.
- [ ] **Step 4: 통과 확인** — `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): drift reconciliation and safe repair (v3.0 T13, ported from CPE)`

---

### Task 14: quality.py — run_quality/completion_audit/정규화 + finalize·check-stop 완성

**Files:**
- Create: `skills/kws-claude-multi-agent-executor/scripts/kernel/quality.py`
- Test: `skills/kws-claude-multi-agent-executor/scripts/kernel/test_quality.py`
- Modify: `skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py` (finalize/check-stop/inspect 핸들러 완성)

**Interfaces:**
- Consumes (포팅 원본): `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`, `normalize_cpe_run.py`. 통합 대상(기존 CME): `scripts/finalize_run.py`, `validate_state_schema.py`, `validate_method_audit.py`의 검사 항목 — 커널판으로 흡수하되 원본 파일은 T15에서 정리.
- Produces: `quality.build_run_quality(state, orch_dir) -> dict` — `{"readiness": {...}, "dispatch_consistency": {...}, "context_quality": {"full_spec_fallback_count": int, ...}, "verification_quality": {...}, "open_followups": [str], "grade": "green"|"yellow"|"red"}`. 제품 정합(전 태스크 verify 통과)과 실행기 효율(fallback, 스키마 위반 횟수, recovery unknown)을 분리 채점.
- Produces: `quality.build_completion_audit(state) -> dict` — `{"passed": bool, "checklist": [...], "verification_evidence": [...], "residual_risk": [{"class": str, "summary": str, "blocks_release": bool}]}`. `blocks_release=true` 항목 존재 시 passed=true 불가.
- Produces: `quality.normalize_run(state) -> dict` — eval용 결정론 요약(카운트·클래스명만, 원문 없음) + 금지 패턴 스캔(`sk-`, `/Users/`, 풀 트랜스크립트 마커) 결과.
- Produces: `kernel.py finalize` — drift.check(blocking 있으면 거부) → method_audit 검증 → completed_at 스탬프 → run_quality + completion_audit 작성 → `events.emit("kws-cme.phase_2_complete")` → run-close best-effort. `kernel.py check-stop` — 전 태스크 터미널인데 finalize 산출물(completion_audit) 부재면 exit 2.
- Produces: `kernel.py inspect` — run_quality + normalize 요약 출력(무변경 read-only).

- [ ] **Step 1: 실패하는 테스트 작성** — (a) 정상 완료 state → grade green + passed true, (b) fallback 3회+스키마 위반 → yellow(제품 pass 유지), (c) blocks_release 리스크 → passed false, (d) blocking drift → finalize 거부, (e) normalize 출력에 홈 경로 원문 부재, (f) check-stop: 미finalize 전-터미널 state → exit 2.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인** — `test_quality.py` + `test_cycle_e2e.py`(finalize까지 연장) `OK`.
- [ ] **Step 5: 커밋** — `feat(cme-kernel): run quality, completion audit, finalize gates (v3.0 T14)`

---

### Task 15: 컷오버 — SKILL.md v3.0 재작성 + 훅 전환 + 구스크립트 정리

**Files:**
- Modify: `skills/kws-claude-multi-agent-executor/SKILL.md` (전면 재작성, version 3.0.0)
- Modify: `skills/kws-claude-multi-agent-executor/scripts/materialize_worktree_hooks.py` (Stop 훅 커맨드를 `kernel.py check-stop` 호출로 교체)
- Modify: `skills/kws-claude-multi-agent-executor/references/phases/` (판정 로직 제거 — 각 파일을 "커널 액션 수행 가이드"로 축약하거나 삭제; 프롬프트 템플릿 5종과 `_scaffolds/`, `_schemas/`, cross-cutting 중 hooks/agent-dispatch는 유지)
- Delete: `scripts/accumulate_cost.py`, `scripts/phase_boundary.py`, `scripts/finalize_run.py`, `scripts/validate_state_schema.py`, `scripts/migrate_legacy_state.py`, `scripts/build_spec_manifest.py`, `scripts/build_context_slice.py`, `scripts/state_set.py`, `scripts/state_resume_digest.py` + 각 `test_*.py` (커널이 흡수 완료한 것만 — 삭제 전 `grep -rn "<파일명>" SKILL.md references/ evals/ scripts/`로 잔존 참조 0건 확인; 참조가 남은 파일은 삭제 대신 deprecation 주석)
- Test: 기존 `scripts/kernel/test_*.py` 전체 + `evals/check_doc_freshness.py`

**Interfaces:**
- Consumes: T1–T14 완성된 커널.
- Produces: SKILL.md v3.0 구조 — ① 경로 규약(현행 유지) ② 호출 계약(사용자 인자 → `kernel.py init`) ③ 실행 사이클(next→수행→submit 루프, 액션 타입별 수행 방법: `dispatch`는 command 실행 또는 Agent 툴, `run_command`, `escalate_to_user`는 배치 질문, `compact`는 컨텍스트 앵커) ④ 가드레일 요약표(커널이 강제하는 것 vs LLM이 지켜야 하는 것 구분) ⑤ 하드 홀트 규칙(커널 오류 시 프로즈 대체 진행 금지) ⑥ 폴라이트-스톱 금지 불변식. `<active>` 치환 프로즈, 북키핑 지시, 전이 판정 프로즈는 전부 삭제.

- [ ] **Step 1: 삭제 대상 참조 스캔** — 위 grep으로 잔존 참조 목록 작성, JOURNAL에 기록.
- [ ] **Step 2: SKILL.md 재작성** — 위 6개 섹션. description의 버전·NOTE 유지, metadata.version을 `"3.0.0"`으로.
- [ ] **Step 3: Stop 훅 전환** — materialize_worktree_hooks.py의 Stop 커맨드를 `python3 <skill_dir>/scripts/kernel/kernel.py check-stop --state <orch_dir>/state.json`으로. `python3 scripts/test_materialize_worktree_hooks.py` 통과하도록 기대값 갱신.
- [ ] **Step 4: 구스크립트 정리 + 전체 테스트** — `for t in scripts/kernel/test_*.py; do python3 "$t" || exit 1; done && python3 scripts/test_materialize_worktree_hooks.py && python3 evals/check_doc_freshness.py` → 전부 통과 (freshness의 HISTORY 항목은 T16에서 추가되므로 이 시점 WARN은 허용, 실패만 금지).
- [ ] **Step 5: 커밋** — `feat(cme): cut over SKILL.md to kernel-driven v3.0.0`

---

### Task 16: eval 재베이스라인 + 문서 동기화 + 실험 close-out

**Files:**
- Modify: `skills/kws-claude-multi-agent-executor/evals/` (하네스가 커널 사이클을 구동하도록 어댑터 수정 — 기존 구조를 읽고 최소 변경)
- Modify: `skills/kws-claude-multi-agent-executor/ARCHITECTURE.md` (§ 커널 아키텍처 신설, 상태 스키마 §5 갱신, §13 트리거 목록 갱신)
- Modify: `skills/kws-claude-multi-agent-executor/HISTORY.md` (v3.0.0 항목)
- Create: `skills/kws-claude-multi-agent-executor/docs/snapshots/v3.0.md`
- Modify: `skills/kws-claude-multi-agent-executor/docs/decision-log.md` (D001 등 ADR 인덱싱)
- Create: `skills/kws-claude-multi-agent-executor/docs/experiments/v3.0-deterministic-kernel/findings/F01-close-out.md`
- Modify: `skills/kws-claude-multi-agent-executor/README.md` (커널 안내)

**Interfaces:**
- Consumes: 전체 커널 + v3 SKILL.md.
- Produces: 스펙 Success Criteria 검증 증거 — ① 커널 테스트 전체 green ② 실 플랜 스모크(작은 실플랜 1개를 attached·headless 각 1회 실행: 타이밍·비용 완전 기록, wedge 없는 종료, run_quality/completion_audit 생성 — 결과 요약을 F01에 첨부; **이 단계에서 `claude -p --output-format json` 실 봉투로 ledger 픽스처 검증·교정**) ③ SKILL.md에서 `grep -c "STATUS:" SKILL.md` 가 프롬프트 템플릿 참조 외 0 ④ freshness strict 통과.

- [ ] **Step 1: eval 어댑터** — `evals/run.sh`와 하네스 구조를 읽고, 커널 사이클 기반 실행으로 어댑터 수정. 커널 단위 테스트를 preflight에 편입.
- [ ] **Step 2: 실 플랜 스모크 2회** — 위 ② 수행. ledger 봉투 불일치 발견 시 `ledger.extract_payload` 수정 + 픽스처 교체 (같은 커밋).
- [ ] **Step 3: 문서 동기화** — ARCHITECTURE/HISTORY/스냅샷/decision-log/README 갱신. `DOC_FRESHNESS_STRICT=1 python3 evals/check_doc_freshness.py` 통과.
- [ ] **Step 4: close-out** — F01에 ship 판정 + Success Criteria 증거 + 미해결 항목(예: Haiku A/B는 후속 실험) 기록. 실험 README status 갱신, `docs/experiments/README.md` 인덱스 + HISTORY §3 표 갱신.
- [ ] **Step 5: 커밋** — `docs(cme): v3.0 rebaseline, doc sync, experiment close-out (v3.0 T16)`

---

## Self-Review 결과 (작성자 점검)

- **스펙 커버리지**: §1 사이클=T9, 커널 모듈 11종=T1–T14(init=T2/T3, plan=T4, packets=T10, gate=T11, transitions=T6, dispatch=T7, ledger/events=T8, recovery=T12, drift=T13, quality=T14), 스키마 계약=T5, headless-first=T7, 마이그레이션=T3, 훅 전환=T14/T15, SKILL.md 축소=T15, eval·문서·close-out=T16, Success Criteria=T16. 잔여 gap 없음.
- **의도적 스코프 제외**: Resume Chain 자동 트리거의 커널 이관은 T6 compact 액션에 포함되나 체인 spawn 자체는 v3.0에서 기존 문서 경로 유지(스펙 §4 하드 홀트 규칙과 무충돌). Haiku A/B·프롬프트 캐시 감사 강화는 Out of Scope(스펙과 일치).
- **타입 일관성**: 액션 dict 키(`action/role/task_id/attempt/prompt_path/schema_path/result_path/transport/model/command`)와 state v3 필드명을 전 태스크에서 통일 확인.
