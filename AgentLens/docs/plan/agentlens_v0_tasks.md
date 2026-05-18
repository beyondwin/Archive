# AgentLens v0 — Task-Formatted Plan

> 머신 친화 작업 단위 플랜. 사람용 설계 문서는 `agentlens_v0_detailed_plan.md` 참조. 본 파일은 `kws-claude-multi-agent-executor` 스킬이 요구하는 `### Task N:` 형식으로 마일스톤 M0~M8의 작업 단위(T#.#)를 25개 작업으로 평탄화한다.

전체 코드 루트는 `AgentLens/`이다. `src/agentlens/`는 패키지 본체, 테스트는 `tests/`, 빌드 설정은 `pyproject.toml`. Python 3.11+를 기준으로 한다.

테스트 명령은 `cd AgentLens && python -m pytest -v` 가 표준이다. `test_command`는 Phase 0 자동 감지 결과를 따른다.

각 Task의 `**Files:**`는 변경/생성할 파일 목록, `**Spec Refs:**`는 `agentlens_v0_implementation_spec.md` 섹션 ID(스킬 manifest 기준 `S1.x[.x]`).

---

## Phase 1: M0 Contract Freeze

### Task 0: M0 docs — contract/security/integrations/cli

**Files:**
- `AgentLens/docs/contract.md`
- `AgentLens/docs/security.md`
- `AgentLens/docs/integrations.md`
- `AgentLens/docs/cli.md`

**Spec Refs:** S1.2, S1.4, S1.9, S1.11

산출물: 네 개의 인덱스 문서. 각 문서는 spec의 해당 섹션을 사람이 읽을 수 있게 재서술하고, "v1 잠금" 정책을 명시한다.

- `contract.md` — run 디렉터리 레이아웃(`~/.agentlens/runs/<workspace_id>/<run_id>/`), source of truth(JSON artifacts), 두 단계 seal(`pre_eval` / `final`), `recording_incomplete` 의미.
- `security.md` — 기본 redaction 정책(allow-list excerpt + 패턴 마스크), 절대 경로 비저장, shim 0700 권한.
- `integrations.md` — Integration Level 0~3 정의 (`none | watcher-only | shim | full|native-experimental`).
- `cli.md` — `agentlens` 서브커맨드 contract: `start/mark/attach/final/seal/eval/show/run/install/doctor/mode/gc/latest/status/failures/risks`.

## Acceptance Criteria
```bash
cd AgentLens
for f in docs/contract.md docs/security.md docs/integrations.md docs/cli.md; do
  test -f "$f" || { echo "MISSING: $f" >&2; exit 1; }
  test "$(wc -l < "$f")" -ge 20 || { echo "TOO_SHORT: $f" >&2; exit 1; }
done
grep -q 'pre_eval' docs/contract.md
grep -q 'final' docs/contract.md
grep -q 'recording_incomplete' docs/contract.md
grep -q 'redaction' docs/security.md
grep -q '0700' docs/security.md
grep -qE 'Level [0-3]|level-[0-3]' docs/integrations.md
grep -q 'agentlens run' docs/cli.md
grep -q 'agentlens show' docs/cli.md
echo OK
```

---

### Task 1: M0 JSON Schemas + validation tests

**Files:**
- `AgentLens/src/agentlens/schema/jsonschema/run.schema.json`
- `AgentLens/src/agentlens/schema/jsonschema/event.schema.json`
- `AgentLens/src/agentlens/schema/jsonschema/final.schema.json`
- `AgentLens/src/agentlens/schema/jsonschema/eval.schema.json`
- `AgentLens/src/agentlens/schema/jsonschema/manifest.schema.json`
- `AgentLens/src/agentlens/schema/__init__.py`
- `AgentLens/src/agentlens/schema/validate.py`
- `AgentLens/src/agentlens/schema/check_drift.py`
- `AgentLens/tests/unit/test_schema_validation.py`
- `AgentLens/tests/fixtures/schemas/valid/`  (5 valid 예제)
- `AgentLens/tests/fixtures/schemas/invalid/`  (5 invalid 예제)
- `AgentLens/pyproject.toml`
- `AgentLens/tests/__init__.py`
- `AgentLens/tests/unit/__init__.py`

**Spec Refs:** S1.5, S1.5.1, S1.5.2, S1.5.3, S1.5.4, S1.5.5, S1.5.6, S1.6.11

5개 JSON Schema(Draft 2020-12, `additionalProperties: false`, UTC ISO8601 regex 강제, `agentlens.<entity>.v1` const). 각 파일 최상위에 `$comment: "v1 is locked. Breaking changes require v2 namespace."`. `# v1 is locked` 같은 JSON 비표준 주석 금지. `validate.py`는 `jsonschema` 라이브러리 기반 함수 4종(`validate_run/event/final/eval/manifest`). `pyproject.toml`에 `agentlens` 패키지 + `jsonschema>=4`, `typer`, `pyyaml`, `pytest` 의존성 정의. `check_drift.py`는 `python -m agentlens.schema.check_drift` CLI: 각 schema 파일에 대해 `tests/fixtures/schemas/valid/<entity>.json` 존재 + valid 확인.

## Acceptance Criteria
```bash
cd AgentLens
test -f pyproject.toml
test -d src/agentlens/schema/jsonschema
ls src/agentlens/schema/jsonschema/*.schema.json | wc -l | grep -qE '^\s*5\s*$'
for s in run event final eval manifest; do
  python3 -c "import json,sys; d=json.load(open('src/agentlens/schema/jsonschema/'+'${s}'+'.schema.json'));
assert d.get('\$schema','').startswith('https://json-schema.org/draft/2020-12'),'draft';
assert d.get('additionalProperties') is False,'addl';
assert '\$comment' in d,'comment';"
done
python -m pytest tests/unit/test_schema_validation.py -v
python -m agentlens.schema.check_drift
echo OK
```

---

## Phase 2: M1 Vertical Slice

### Task 2: M1 foundation — constants/time/ids/store/paths

**Files:**
- `AgentLens/src/agentlens/__init__.py`
- `AgentLens/src/agentlens/constants.py`
- `AgentLens/src/agentlens/time.py`
- `AgentLens/src/agentlens/ids.py`
- `AgentLens/src/agentlens/store/__init__.py`
- `AgentLens/src/agentlens/store/paths.py`
- `AgentLens/tests/unit/test_ids.py`
- `AgentLens/tests/unit/test_paths.py`

**Spec Refs:** S1.6.1, S1.6.2, S1.6.3, S1.6.4, S1.7.1

- `constants.py` — `AGENTLENS_HOME` (`~/.agentlens`), `RUN_TS_FORMAT`, `MAX_EXCERPT_CHARS=4096`, schema 식별자 const.
- `time.py` — `now_iso()` (UTC ISO8601 z-suffix), `parse_iso(s)`, `normalize_for_diff(s)` (determinism).
- `ids.py` — `run_id(now=None)` filesystem-safe, `compute_workspace_id(workspace_root, agentlens_home)` per S1.7.1. persisted workspace config(`<workspace>/.agentlens/config.yaml`)에 `workspace_id` 있으면 그대로 사용; 없으면 (a) git remote URL hash + repo-relative root + worktree identity hash, (b) git 없으면 절대경로 hash, (c) 결과는 안정적인 16-hex prefix.
- `store/paths.py` — `runs_root()`, `workspace_dir(ws_id)`, `run_dir(ws_id, run_id)`, `current_runs_dir(ws_id)`, `current_run_marker(ws_id, run_id)` (`current-runs/<run_id>` 다중 마커).

테스트는 main checkout vs git worktree에서 서로 다른 `workspace_id`를 갖는 것을 검증(임시 git repo + `git worktree add`). persisted config가 있으면 worktree 이동 후에도 동일 id.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_ids.py tests/unit/test_paths.py -v
python -c "from agentlens.ids import run_id, compute_workspace_id
from agentlens.time import now_iso, parse_iso
from agentlens.store.paths import runs_root, run_dir
assert len(run_id()) > 0
assert now_iso().endswith('Z')
"
echo OK
```

---

### Task 3: M1 store/writer + store/lock + schema/validate integration

**Files:**
- `AgentLens/src/agentlens/store/lock.py`
- `AgentLens/src/agentlens/store/writer.py`
- `AgentLens/tests/unit/test_writer.py`
- `AgentLens/tests/unit/test_lock.py`

**Spec Refs:** S1.6.5, S1.6.6, S1.6.11

- `store/lock.py` — `with run_lock(run_dir):` posix flock, stale lock detection (PID), `LockTimeoutError`.
- `store/writer.py` — `write_run_meta(run_dir, run)`, `append_event(run_dir, event)`, `write_final(run_dir, final)`, `write_eval(run_dir, eval_doc)`, `write_manifest(run_dir, manifest)`. 모든 write는 temp+rename + fsync. `append_event`는 jsonl append (lock 보호). 모든 write 전에 schema validate (`schema/validate.py` 호출). 길이가 `MAX_EXCERPT_CHARS` 초과하는 `excerpt.text` 거부.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_writer.py tests/unit/test_lock.py -v
echo OK
```

---

### Task 4: M1 store/manifest — two-phase seal

**Files:**
- `AgentLens/src/agentlens/store/manifest.py`
- `AgentLens/tests/unit/test_manifest.py`

**Spec Refs:** S1.6.7, S1.7.2

`init_manifest(run_dir)`, `seal_pre_eval(run_dir)`, `seal_final(run_dir)`, `mark_recording_incomplete(run_dir, reason)`. manifest.json fields: `schema`, `manifest_version`, `run_id`, `sealed_phase ∈ {none, pre_eval, final, recording_incomplete}`, `sealed_at`, `artifacts` (각 파일의 sha256 + size), `recording_incomplete_reason?`.

두 단계 seal: `pre_eval`은 evaluator 실행 전 artifact freeze; `final`은 eval.json 포함 최종 freeze. `recording_incomplete`는 어느 단계든 write 실패 시 그 사실 자체를 기록.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_manifest.py -v
echo OK
```

---

### Task 5: M1 evaluator stub + commands + cli + lifecycle test

**Files:**
- `AgentLens/src/agentlens/evaluator/__init__.py`
- `AgentLens/src/agentlens/evaluator/engine.py`
- `AgentLens/src/agentlens/commands/__init__.py`
- `AgentLens/src/agentlens/commands/start.py`
- `AgentLens/src/agentlens/commands/mark.py`
- `AgentLens/src/agentlens/commands/attach.py`
- `AgentLens/src/agentlens/commands/final.py`
- `AgentLens/src/agentlens/commands/seal.py`
- `AgentLens/src/agentlens/commands/eval.py`
- `AgentLens/src/agentlens/commands/show.py`
- `AgentLens/src/agentlens/cli.py`
- `AgentLens/tests/integration/test_cli_lifecycle.py`
- `AgentLens/tests/integration/__init__.py`

**Spec Refs:** S1.6.16, S1.11.1, S1.7.3

stub evaluator는 2개 체크만 수행: `schema_valid` (run/events/final 스키마 통과), `final_present` (final.json 존재). 결과는 eval.json에 기록. cli entrypoint는 Typer. `agentlens start --agent generic --mode cli` 호출 시 새 run_id 생성, run.json + run.started event 기록, `current-runs/<run_id>` 마커 생성.

lifecycle 통합 테스트: 임시 `AGENTLENS_HOME` 환경에서 `start → mark → final → seal pre_eval → eval → seal final → show --latest` 시퀀스가 성공하고, manifest.sealed_phase가 단계마다 갱신되며, show 출력에 5필드 포함되는지 확인.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_cli_lifecycle.py -v
TMP=$(mktemp -d); export AGENTLENS_HOME="$TMP"
python -m agentlens.cli start --agent generic --mode cli > /tmp/start_out.txt
grep -qE '[0-9a-f-]+' /tmp/start_out.txt
ls "$TMP/runs/" | head -1
rm -rf "$TMP"
echo OK
```

---

## Phase 3: M2 Evaluator Hardening

### Task 6: M2 failure taxonomy + 12 deterministic checks

**Files:**
- `AgentLens/src/agentlens/evaluator/failures.py`
- `AgentLens/src/agentlens/evaluator/checks.py`
- `AgentLens/src/agentlens/evaluator/engine.py`  (확장)
- `AgentLens/tests/unit/test_evaluator_checks.py`

**Spec Refs:** S1.5.5, S1.6.13, S1.6.14, S1.6.15, S1.7.3

`failures.py`: `Failure(code, severity, message, evidence)` dataclass + `FailureCategory` enum (`SCHEMA_INVALID`, `MISSING_FINAL`, `FAILED_COMMAND_UNACKNOWLEDGED`, `RESIDUAL_RISK_UNRESOLVED`, `DIFF_SCOPE_UNKNOWN`, `RECORDING_INCOMPLETE`, `EVALUATOR_ERROR`, ...).

`checks.py`: 12개 함수 — `check_schema_valid`, `check_final_present`, `check_failed_commands_acknowledged`, `check_residual_risk_policy`, `check_changed_files_consistent` (success + 빈 changed_files면 no_changes_reason 요구), `check_event_sequence_valid`, `check_excerpt_size_within_limit`, `check_outcome_evidence_match`, `check_workspace_id_stable`, `check_manifest_sealed`, `check_no_recording_incomplete`, `check_artifact_hashes_match`. 각 함수는 `passed | failed | skipped` 중 하나 + Failure list 반환.

엔진은 check를 알파벳 순으로 정렬해서 실행, 결과 dict는 `sort_keys=True`로 직렬화. check 예외는 잡아서 `EVALUATOR_ERROR` Failure + `eval.status="error"`로 surface. confidence는 [0,1]에서 소수점 2자리로 round.

판정 규칙: success + verification 없음 → failed. success + medium/high/critical residual risk → failed. success + low residual + verification → passed (warning). success + changed_files=[] + no_changes_reason 없음 → DIFF_SCOPE_UNKNOWN.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_evaluator_checks.py -v
echo OK
```

---

### Task 7: M2 evaluator fixtures (5 종)

**Files:**
- `AgentLens/tests/fixtures/minimal_run/`
- `AgentLens/tests/fixtures/failed_command_run/`
- `AgentLens/tests/fixtures/missing_final_run/`
- `AgentLens/tests/fixtures/residual_risk_run/`
- `AgentLens/tests/fixtures/corrupt_manifest_run/`
- `AgentLens/tests/unit/test_evaluator_fixtures.py`

**Spec Refs:** S1.10.1

각 fixture 디렉터리는 완전한 run 구조 (`run.json`, `events.jsonl`, `final.json?`, `manifest.json`)와 기대 `expected_eval.json`을 포함한다. evaluator를 fixture에 실행했을 때 expected와 byte-equal(timestamp normalize 후)이어야 한다.

- `minimal_run`: 정상 success run, no verification → failed로 판정.
- `failed_command_run`: command exit 42 + final unacknowledged → failed.
- `missing_final_run`: events만 있고 final.json 없음 → incomplete.
- `residual_risk_run`: success + high residual risk → failed.
- `corrupt_manifest_run`: manifest.json 손상 → recording_incomplete.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_evaluator_fixtures.py -v
ls tests/fixtures/ | grep -c _run | grep -qE '^\s*5\s*$'
echo OK
```

---

### Task 8: M2 determinism integration test (byte-equal regression)

**Files:**
- `AgentLens/tests/integration/test_eval_determinism.py`
- `AgentLens/src/agentlens/evaluator/engine.py`  (필요시 timestamp normalize 헬퍼 추가)

**Spec Refs:** S1.10.5

evaluator를 fixture 5종 각각에 대해 2회 실행하여 timestamp normalize 후 byte-equal 검증. `normalize_for_diff` 사용하여 `evaluated_at` 등 시간 필드 마스크.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_eval_determinism.py -v
echo OK
```

---

## Phase 4: M3 SQLite Index

### Task 9: M3 store/sqlite_index — schema + index_run + rebuild_index

**Files:**
- `AgentLens/src/agentlens/store/sqlite_index.py`
- `AgentLens/tests/unit/test_sqlite_index.py`

**Spec Refs:** S1.6.8, S1.8.3

- 4개 테이블: `runs(run_id PK, workspace_id, agent_name, agent_mode, started_at, sealed_phase, agent_outcome, eval_status)`, `checks(run_id FK, name, status, severity)`, `failures(run_id FK, code, severity)`, `artifacts(run_id FK, path, sha256, size)`.
- `init_db(agentlens_home)` — 테이블 생성, idempotent.
- `index_run(agentlens_home, run_dir)` — 한 run의 artifact를 읽어 upsert.
- `rebuild_index(agentlens_home)` — DB drop + 모든 `runs/*/*/` full-scan re-index.
- 모든 컬럼은 JSON artifact에서 재계산 가능 (SQLite 전용 필드 금지).

테스트: 빈 DB → index_run 후 row, rebuild_index 후 row 집합이 byte-equal(run_id 정렬 후).

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_sqlite_index.py -v
echo OK
```

---

### Task 10: M3 store/query facade + SQLite fallback

**Files:**
- `AgentLens/src/agentlens/store/query.py`
- `AgentLens/tests/unit/test_query_fallback.py`

**Spec Refs:** S1.6.9

read facade. 함수: `list_runs(filters)`, `get_run(run_id)`, `latest_run(workspace_id?)`, `list_failures(since=30d)`, `list_risks(since=30d)`. 내부에서 SQLite 가용성 판단 후 SQLite 또는 full-scan 사용. SQLite 부재/손상 시 full-scan reader로 자동 fallback (성능 떨어지나 정확함).

테스트: SQLite 파일 삭제 후 `latest_run`이 동일 결과 반환; SQLite 파일 손상(쓰레기 바이트 주입) 후 동일.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_query_fallback.py -v
echo OK
```

---

## Phase 5: M4 Query Surface

### Task 11: M4 query commands — latest/status/show/failures/risks

**Files:**
- `AgentLens/src/agentlens/commands/show.py`  (확장)
- `AgentLens/src/agentlens/commands/latest.py`
- `AgentLens/src/agentlens/commands/status.py`
- `AgentLens/src/agentlens/commands/failures.py`
- `AgentLens/src/agentlens/commands/risks.py`
- `AgentLens/src/agentlens/cli.py`  (서브커맨드 등록)

**Spec Refs:** S1.11.1, S1.11.2

모든 read 명령은 `store/query.py` facade만 사용. `sqlite_index.py`를 직접 호출하지 않는다.

- `latest` — 최근 한 개 run의 `run_id workspace_short outcome eval_status sealed_phase` 한 줄.
- `status` — 동일 + 진행 중 run 포함.
- `show <run_id>` / `show --latest` — full summary (failures + risks 포함).
- `failures` — 최근 30일 sealed run의 evaluator failures만.
- `risks` — final.residual_risks + eval.failures + `RECORDING_INCOMPLETE` 합본.
- eval.json 없으면 `eval_status=needs_eval`.
- 기본 텍스트 출력에 절대 경로 표시 금지 (workspace_id 약식 + 상대 경로).

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_cli_lifecycle.py -v -k 'query or show or latest or failures or risks'
echo OK
```

---

### Task 12: M4 --format json + snapshot tests

**Files:**
- `AgentLens/src/agentlens/commands/_format.py`
- `AgentLens/src/agentlens/commands/show.py`  (확장)
- `AgentLens/src/agentlens/commands/latest.py`  (확장)
- `AgentLens/src/agentlens/commands/status.py`  (확장)
- `AgentLens/src/agentlens/commands/failures.py`  (확장)
- `AgentLens/src/agentlens/commands/risks.py`  (확장)
- `AgentLens/tests/integration/test_format_json_snapshot.py`
- `AgentLens/tests/fixtures/format_snapshots/`  (snapshot files)

**Spec Refs:** S1.11.2

모든 query 명령에 `--format json` 플래그. 출력 schema는 v1로 잠금. snapshot 테스트로 회귀 잡음. JSON 출력에 절대 경로 leak 금지.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_format_json_snapshot.py -v
echo OK
```

---

## Phase 6: M5 Process Wrapper

### Task 13: M5 process wrapper core — spawn + dual-stream drain + excerpt

**Files:**
- `AgentLens/src/agentlens/adapters/__init__.py`
- `AgentLens/src/agentlens/adapters/process.py`
- `AgentLens/src/agentlens/commands/run.py`
- `AgentLens/src/agentlens/cli.py`  (run 등록)
- `AgentLens/tests/integration/test_process_wrapper.py`  (spawn/drain 테스트만)

**Spec Refs:** S1.6.17, S1.9.2

**Resource Key:** process-wrapper-test

`agentlens run -- <cmd args...>` 구현. child spawn + stdout/stderr를 selectors 또는 reader thread 2개로 동시 drain. excerpt는 allow-list extractor만 호출 (자유 텍스트 슬라이스 금지). `MAX_EXCERPT_CHARS=4096` 강제.

child가 stdout/stderr 양쪽에 pipe buffer (~64KB)보다 큰 출력을 내도 deadlock 없이 종료되어야 한다. 테스트로 검증.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_process_wrapper.py -v -k 'spawn or drain or excerpt'
echo OK
```

---

### Task 14: M5 process wrapper — exit code preservation + signal handling

**Files:**
- `AgentLens/src/agentlens/adapters/process.py`  (확장)
- `AgentLens/tests/integration/test_process_wrapper.py`  (확장)

**Spec Refs:** S1.6.17

**Resource Key:** process-wrapper-test

종료 경로 3가지 모두 처리:
- final 있고 exit 0 → `agent_outcome=success | failed | partial` (final이 결정).
- final 없고 exit 0 → `agent_outcome=unknown`.
- exit 비0 → `agent_outcome=failed`, exit code preserved.

SIGINT/SIGTERM: wrapper의 signal handler가 child PID로 forward 후 child reap. `agent_outcome=cancelled`, `exit_signal="SIGINT"`, 종료 코드 `128+signum`.

`agentlens run -- sh -c 'exit 0'` → 0. `agentlens run -- sh -c 'exit 42'` → 42. SIGINT 보내면 130.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_process_wrapper.py -v -k 'exit_code or signal'
echo OK
```

---

### Task 15: M5 non-blocking fault-injection passthrough

**Files:**
- `AgentLens/src/agentlens/adapters/process.py`  (확장)
- `AgentLens/tests/integration/test_nonblocking.py`

**Spec Refs:** S1.6.17

**Resource Key:** process-wrapper-test

AgentLens 측 실패에서도 child exit code 보존:
- run 초기화 실패 (`write_run_meta` fail, `append_event(run.started)` fail) → child 명령은 그대로 실행되고 원래 exit code 반환. 이게 ER-1 fix.
- manifest write 실패 → child exit code 보존.
- evaluator crash → child exit code 보존.
- SQLite update 실패 → child exit code 보존.
- pre_eval seal 실패 → recording_incomplete 마킹 + child exit code 보존.

테스트는 `unittest.mock.patch`로 각 단계 함수를 강제 fail 시키고 wrapper exit code 확인.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_nonblocking.py -v
echo OK
```

---

## Phase 7: M6 Install / Shim / Doctor

### Task 16: M6 config + mode command (priority chain)

**Files:**
- `AgentLens/src/agentlens/config.py`
- `AgentLens/src/agentlens/commands/mode.py`
- `AgentLens/src/agentlens/cli.py`  (mode 등록)
- `AgentLens/tests/unit/test_config.py`

**Spec Refs:** S1.4

config priority chain: env var (`AGENTLENS_*`) > workspace `<workspace>/.agentlens/config.yaml` > user `~/.agentlens/config.yaml` > defaults. `AGENTLENS_DISABLE=1` 어디서든 우선해서 모든 기능 off. `agentlens mode set <mode>` / `agentlens mode show`. mode ∈ `{disabled, minimal, full}`.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_config.py -v
AGENTLENS_DISABLE=1 python -m agentlens.cli mode show | grep -q disabled
echo OK
```

---

### Task 17: M6 shim install — adapters/shims.py + commands/install.py

**Files:**
- `AgentLens/src/agentlens/adapters/shims.py`
- `AgentLens/src/agentlens/commands/install.py`
- `AgentLens/src/agentlens/commands/uninstall.py`
- `AgentLens/src/agentlens/cli.py`  (install/uninstall 등록)
- `AgentLens/tests/unit/test_shim_security.py`
- `AgentLens/tests/integration/test_install_doctor.py`

**Spec Refs:** S1.6.18, S1.7.4, S1.9.3

shim 템플릿: bash script로, `<name>.real` lockfile에서 real binary 절대경로 + sha256을 읽고, sha256 검증 후 `agentlens run -- <real_binary> "$@"` 위임. sha256 mismatch 시 stderr 경고 + passthrough (recording skip). lockfile 누락 시 exit 127 (재탐색 금지).

`agentlens install` — 동의 prompt (`--yes` 우회) + PATH export 한 줄 출력(자동 편집 금지). `~/.agentlens/shims/`는 0700, shim 파일은 0755, owner 검증.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_shim_security.py -v
python -m pytest tests/integration/test_install_doctor.py -v -k 'shim or install'
echo OK
```

---

### Task 18: M6 doctor + nested invocation policy

**Files:**
- `AgentLens/src/agentlens/commands/doctor.py`
- `AgentLens/src/agentlens/adapters/process.py`  (nested 정책 추가)
- `AgentLens/src/agentlens/cli.py`  (doctor 등록)
- `AgentLens/tests/integration/test_install_doctor.py`  (doctor 부분 확장)

**Spec Refs:** S1.6.18, S1.8.4

`agentlens doctor [integrations|paths|all]`. 출력은 텍스트 / `--format json` 둘 다. integrations 출력에는 각 런타임의 integration level (`none|watcher-only|shim|full|native-experimental`)과 `Shim integrity: ok | drift_warning` 항목.

Nested invocation: `AGENTLENS_NESTED_POLICY=passthrough|nested`. 기본 `passthrough` → nested 호출에서는 recording 없이 real 실행. `AGENTLENS_RUN_ID`+PID stamp로 자기 PID에서 만든 변수인지 식별 (무한루프 방지).

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_install_doctor.py -v -k 'doctor or nested'
echo OK
```

---

## Phase 8: M7 Adapter (Claude / Codex)

### Task 19: M7 Claude adapter probe + settings injection

**Files:**
- `AgentLens/src/agentlens/adapters/claude.py`
- `AgentLens/tests/integration/test_install_doctor.py`  (claude 부분 확장)

**Spec Refs:** S1.6.19, S1.10.1

`probe()` — `claude --version`, `claude --help` 호출 (실제 binary 없으면 fake binary path를 받는 hook 사용). 기능 검출: `--include-hook-events`+`--output-format stream-json` 지원 시 `full` 후보. settings JSON injection: 백업 후 AgentLens-owned 블록(`agentlens` 네임스페이스) 삽입. `--bare` 환경 → shim-only로 자동 격하. uninstall 시 backup 복원 + AgentLens-owned 블록만 제거.

테스트는 실제 `claude` 호출 없이 fake binary로 detect 로직 검증.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_install_doctor.py -v -k 'claude'
echo OK
```

---

### Task 20: M7 Codex CLI adapter

**Files:**
- `AgentLens/src/agentlens/adapters/codex_cli.py`
- `AgentLens/tests/integration/test_install_doctor.py`  (codex_cli 부분 확장)

**Spec Refs:** S1.6.19

`probe()` — `codex --version`, `codex plugin --help`, `codex mcp --help`, `codex app-server --help`. `full` 조건: shim 가능 + `exec` 지원. 기본 integration은 shim.

fake binary로 테스트.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_install_doctor.py -v -k 'codex_cli'
echo OK
```

---

### Task 21: M7 Codex App watcher

**Files:**
- `AgentLens/src/agentlens/adapters/codex_app.py`
- `AgentLens/tests/integration/test_install_doctor.py`  (codex_app 부분 확장)
- `AgentLens/tests/fixtures/codex_app_sessions/`  (fixture sessions JSONL)

**Spec Refs:** S1.6.19

`~/.codex/sessions` JSONL watcher + `app-server` probe. 분류: `native-experimental | watcher-only | unavailable`. **절대 `full`로 표시하지 않는다** (R1 정책). Codex 0.129.0 session JSONL fixture pin. 새 버전 감지 시 doctor가 "fixture update required" 경고.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_install_doctor.py -v -k 'codex_app'
echo OK
```

---

## Phase 9: M8 Hardening

### Task 22: M8 redaction engine + patterns

**Files:**
- `AgentLens/src/agentlens/redaction/__init__.py`
- `AgentLens/src/agentlens/redaction/patterns.py`
- `AgentLens/src/agentlens/redaction/redact.py`
- `AgentLens/src/agentlens/store/writer.py`  (redact 적용 + post-redact schema validate)
- `AgentLens/tests/unit/test_redaction.py`

**Spec Refs:** S1.6.12, S1.6.13, S1.7.5, S1.9.1

patterns: home path (`/Users/.../`, `/home/.../`), API key (`sk-...`, `pk_live_...`), `Authorization: Bearer ...`, `-----BEGIN PRIVATE KEY-----`. `redact(doc, profile)` 재귀 적용. protected key (변형 금지): `schema`, `run_id`, `workspace_id`, `*_hash`, `sha256`, enum/status 필드. writer는 redact 적용 후 최종 persisted 문서를 다시 schema validate (ER-6 fix).

테스트 fixture에서 known secret이 마스크되는지 확인.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_redaction.py -v
echo OK
```

---

### Task 23: M8 retention + gc

**Files:**
- `AgentLens/src/agentlens/store/retention.py`
- `AgentLens/src/agentlens/commands/gc.py`
- `AgentLens/src/agentlens/cli.py`  (gc 등록)
- `AgentLens/tests/unit/test_retention.py`

**Spec Refs:** S1.6.10, S1.9.4

`max_total_store_gb=5` 기본. 초과 시 oldest sealed run의 artifact부터 삭제. `keep_eval_summaries=true` 기본 → eval/final/manifest summary는 보존. `agentlens gc --dry-run`은 삭제 대상 artifact 목록 출력 + 실제 GC는 동일 목록 삭제. SQLite 부재 상태에서도 full-scan으로 동작.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/unit/test_retention.py -v
echo OK
```

---

### Task 24: M8 final regression suite — non-blocking + determinism lock

**Files:**
- `AgentLens/tests/integration/test_nonblocking.py`  (확장 — fault-inject 6종 전체)
- `AgentLens/tests/integration/test_eval_determinism.py`  (확장 — 잠금)
- `AgentLens/tests/integration/test_query_fallback.py`
- `AgentLens/docs/runbook.md`

**Spec Refs:** S1.10.4, S1.10.5

fault-injection 6종: run initialization, manifest write, evaluator crash, SQLite update, pre_eval seal, SIGINT. 모두 child exit code 보존 검증. determinism 회귀 잠금. `docs/runbook.md`에 운영/장애 대응 가이드.

## Acceptance Criteria
```bash
cd AgentLens
python -m pytest tests/integration/test_nonblocking.py tests/integration/test_eval_determinism.py tests/integration/test_query_fallback.py -v
test -f docs/runbook.md
echo OK
```

---

## 부록 — 작업 단위 의존성 그래프

```
Task 0 (M0 docs) ──┐
Task 1 (M0 schema) ─┤
                   ├── Task 2 (M1 foundation) ── Task 3 (M1 writer) ── Task 4 (M1 manifest) ── Task 5 (M1 stub+cli+lifecycle)
                                                                                                  │
                                                          ┌───────────────────────────────────────┤
                                                          ▼                                       ▼
                                                Task 6 (M2 failures+checks)            Task 9 (M3 sqlite_index)
                                                          │                                       │
                                                          ▼                                       ▼
                                                Task 7 (M2 fixtures)                  Task 10 (M3 query facade)
                                                          │                                       │
                                                          ▼                                       │
                                                Task 8 (M2 determinism) ──────────────────────────┤
                                                                                                  ▼
                                                                                       Task 11 (M4 commands)
                                                                                                  │
                                                                                                  ▼
                                                                                       Task 12 (M4 --format json)
                                                                                                  │
                                                                                                  ▼
                                                                                       Task 13 (M5 spawn/drain) ── Task 14 (M5 exit/signal) ── Task 15 (M5 fault-inject)
                                                                                                                                                              │
                                                                                                                                                              ▼
                                                                                                                                            Task 16 (M6 config) ── Task 17 (M6 shim) ── Task 18 (M6 doctor)
                                                                                                                                                                                            │
                                                                                                                ┌───────────────────────────────────────────────────────────────────────────┤
                                                                                                                ▼                                                                           ▼
                                                                                                    Task 19/20/21 (M7 adapters, 병렬)                                            Task 22 (M8 redaction)
                                                                                                                │                                                                           │
                                                                                                                ▼                                                                           ▼
                                                                                                    Task 23 (M8 retention) ── Task 24 (M8 final regression)
```

**병렬 가능 구간**
- Task 6~8 (M2) ∥ Task 9~10 (M3) — Task 5 완료 후 동시 가능.
- Task 19, 20, 21 (M7 adapters) — Task 18 완료 후 동시 가능 (파일 disjoint).

**Critical Path**
Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 22 → 23 → 24.
