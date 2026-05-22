# Waygent 개선/결함 분석 — fixture-lab 양쪽 실행 기반

**Date:** 2026-05-22
**Compared:** waygent CLI (v0.1.0, `/Users/kws/.local/bin/waygent` → bun-exec `apps/cli/src/index.ts`) vs. kws-claude-multi-agent-executor (v2.18 prose-skill at `~/.claude/skills/kws-claude-multi-agent-executor/`)
**Plan:** `docs/superpowers/plans/2026-05-20-trustworthy-source-matching-local-fixture-lab.md` (5 H3 tasks, 1,724 lines)
**Spec:** `docs/superpowers/specs/2026-05-20-trustworthy-source-matching-local-fixture-lab-design.md` (503 lines)
**waygent run:** `trustworthy_fixture_lab_wg_20260522_200031`
**CME run:** `trustworthy-source-matching-local-fixture-lab-20260522-195738`

> 이 문서는 두 executor를 같은 plan/spec로 실제 실행하면서 발견한 **재현 가능한 결함**과, 이를 고치기 위한 **우선순위화된 제안서**입니다. 사전 메모리(`10:54-12:43 | main waygent vs kws-CME: 15 improvements`)의 P0-P3과 통합했습니다.

---

## 0. 한눈에 보기 — 두 executor 비교 테이블

| 측면 | kws-CME | waygent (현재 상태) | gap 등급 |
|------|---------|--------------------|---------|
| Plan 입력 포맷 | Superpowers `### Task N:` (H2/H3 자동 감지) | `\`\`\`yaml waygent-task` 블록만 (native) | **P0** |
| Superpowers plan 자동 변환 | 불필요 | 시도하지만 SAFE_COMMAND_STARTS 화이트리스트 검증 실패 시 차단 | **P0** |
| 기본 run_id | 없음 (timestamp + slug 강제) | `"run_demo"` 로 하드코드 default | **P1** |
| CLI 인자 도움말 | n/a (skill prose) | `--run` 누락 표시 안 됨 (필수 사항인데 옵션처럼 보임) | **P1** |
| Pre-flight gate | Plan Reviewer (separate Sonnet sub-agent) + 사용자에게 BLOCKER 일괄 질의 | deterministic/full/off 3단계, BLOCKER는 즉시 throw | P1 |
| Sub-agent model | Orchestrator=Opus, Implementer/Reviewer/Verifier=Sonnet | provider=claude 시 main+sub 모두 Opus (high reasoning) | **P1** (비용/일관성) |
| Per-task worktree | 단일 메인 worktree, Parallel Sub-Flow에서만 sub-worktree | 모든 task가 자체 worktree branch `waygent/<run>/<task>` | 디자인 차이 |
| Wave/dispatch 모델 | dependency graph → waves → parallel groups (file-disjoint) | safe_waves with checkpoint 의존 (현재 fixture-lab에서 모두 직렬화됨) | P2 |
| Risk inference from plan | 4단계 휴리스틱 + LOW shared-files 자동 upgrade | normalizer 사용 시 `risk: "high"` 일괄 default | **P1** |
| State location | `~/.claude/orchestrator/<RUN_ID>/` (영구) | `/var/folders/.../T/waygent-runs/<RUN_ID>/` (macOS tmp — 휘발성) | **P1** (forensics 손실) |
| Event schema | learning_events 후보 JSON → AgentLens 으로 candidate-drain | `agentlens.event.v3` (구조화, trust_impact 포함) — 더 정교함 | waygent 우위 |
| AgentLens 결합 | 옵션 (CLI 없으면 silent no-op) | 1급 시민 (`agentlens_run_id`가 모든 이벤트에 포함) | waygent 우위 |
| Cost ledger | 자체 helper `accumulate_cost.py` + flock | `waygent cost` 명령 (subcommand 별도) | 디자인 차이 |
| Spec slicing | spec_manifest + task_to_sections (`build_spec_manifest.py`) | `runway.spec_slice_computed` 이벤트로 비슷한 기능 | 동등 |
| Resume/chain | mode 기반 (headless_pending → running → chained → plan2_running) + chain_resume | `waygent resume --run <id>` (별도 subcommand) | 디자인 차이 |
| 결함 escalation | type 3종(SPEC_BLOCKER/ENV_BLOCKER/AMBIGUITY) + per-task 카운터 cap 3 | `recovery_action: request_decision \| retry_with_evidence \| ...` (recovery class 기반) | waygent 표현력 우위 |
| Method audit | `validate_method_audit.py` + TDD/verification/code-review 강제 | 없음 (현재) | **P2** |
| Polite-stop antipattern guard | 명시적 invariant + 가드 | 명시 없음 (대화형 reviewer가 PASS 후 reporting 가능) | **P2** |
| 사용자 대화 위치 | Phase 0.5/3.5/6.5 batched user question | non-interactive (`waygent apply` 단계만 사용자 결정) | 디자인 차이 |

---

## 1. 이번 실행에서 새로 재현된 waygent 결함 (P0-P1)

### D-01 (P0): Plan normalizer가 Superpowers 표준 plan을 거부

**증거 (재현 명령)**
```bash
$ waygent run --run X --plan /Users/kws/source/android/FixThis/docs/superpowers/plans/2026-05-20-trustworthy-source-matching-local-fixture-lab.md \
              --spec ... --provider claude --execution-mode multi-agent --plan-preflight deterministic
{
  "error": "cannot normalize superpowers implementation plan into an executable Waygent plan: ...\n
            - Task 1 \"Add Local Fixture Guardrails And Manifest\" is missing safe verification commands\n
            ...
            Add one or more fenced ```yaml waygent-task blocks, or run waygent scaffold-plan ..."
}
```

**근본 원인** (`packages/orchestrator/src/planNormalizer.ts`)
- `SAFE_COMMAND_STARTS` 화이트리스트 (line 38-55)는 다음만 허용:
  `bun test`, `bun run test`, `bun run check`, `bun run typecheck`, `bun run build`,
  `bun run platform:demo`, `bun run waygent:scenarios`, `cargo test`,
  `npm test`, `npm run test`, `pnpm test`, `pnpm run test`, `yarn test`,
  `test `, `printf `, `git diff --check`
- plan은 `npm run source-matching:fixtures:test`라는 도메인 특화 script 이름을 사용 → 어떤 prefix도 매치하지 않음
- 결과: 4/5 task가 "missing safe verification commands"로 거부
- 또한 line 95: `risk: "high"` 일괄 default — plan에 명시된 위험도 정보 무시
- line 87: 명시적 file_claims 없으면 거부 — `**Files:**` 블록은 인식하지만 추가 형식 요구

**왜 P0인가**: 이 단일 결함 때문에 같은 plan을 두 executor에 실행하는 것 자체가 불가능. fixture-lab 같은 도메인 명령을 가진 모든 superpowers plan이 차단됨.

**제안 수정**
1. **즉시 (P0-a)**: SAFE_COMMAND_STARTS를 **prefix list가 아니라 prefix tree + project-defined script catalog**로 확장
   - `package.json` 의 `scripts` 키를 읽어서 `npm run <name>`, `pnpm run <name>` 모두 허용
   - `Makefile`, `pyproject.toml` 의 ts/poetry script entry 동일 처리
   - **fallback**: `--unsafe-verification` 플래그로 화이트리스트 완전 우회 가능하게 (개발 단계 lab plan용)
2. **중기 (P0-b)**: plan normalizer 자체를 **adapter pattern**으로 외부화
   - `packages/orchestrator/src/planAdapters/superpowers.ts`, `.../waygent_native.ts`, `.../mixed.ts`
   - CLI 인자 `--plan-adapter superpowers|native|auto` 추가
   - auto가 default → first try native, fallback to superpowers normalizer
3. **장기 (P0-c)**: risk 추론 휴리스틱 도입
   - kws-CME의 4단계 휴리스틱 (`### Phase 0 Step 4`) 차용
   - keyword scan ('schema migration', 'database', 'API surface' → high)
   - file count + cross-cutting 검사 (`### Phase 0 Step 6`의 shared_files 알고리즘 차용)

### D-02 (P1): YAML `dependencies` 필드가 inline list만 받음

**증거**
```bash
# 정상 YAML block list 사용 시
{
  "error": "plan_preflight_failed:\n- expected inline list, got "
}
```

**근본 원인** (`packages/orchestrator/src/planParser.ts:163`)
```typescript
function parseInlineList(value: string): string[] {
  const trimmed = value.trim();
  if (trimmed === "[]") return [];
  if (!trimmed.startsWith("[") || !trimmed.endsWith("]")) {
    throw new Error(`expected inline list, got ${value}`);
  }
  // ...
}
```
- `file_claims`, `verify`는 `readStringList()`로 block list (`- item`) 지원
- `dependencies`만 `parseInlineList()` 강제 → YAML idiom 비일관

**제안 수정**
- `parseInlineList`을 dual-mode로 확장:
  ```typescript
  function parseList(value: string, lines: string[], startIdx: number): { values: string[], nextIdx: number } {
    if (value.trim().startsWith("[")) return { values: parseInlineList(value), nextIdx: startIdx };
    return { values: readStringList(lines, startIdx, []), nextIdx: ... };
  }
  ```
- 또는 더 단순히: `dependencies`도 `readStringList` 사용
- 단위 테스트는 `tests/planParser.test.ts`에 fixture 추가

### D-03 (P1): CLI default `run_id`가 `"run_demo"`로 하드코드 — 매 실행마다 충돌

**증거**
```bash
$ waygent run --plan ... --spec ... --provider claude
{"error": "run_id_already_exists"}
```

`apps/cli/src/index.ts:136`은 `--run` 미지정 시 `runWaygent` 디폴트 사용 → `packages/orchestrator/src/orchestrator.ts:74` 의 `options.run_id ?? "run_demo"`.

**제안 수정**
1. `--run` 미지정 시 자동 ID 생성: `<plan_slug>_<YYYYMMDD_HHMMSS>` (kws-CME 패턴 동일)
2. `--help` 텍스트에 `--run <id>` 명시 (현재는 "[--run <id>]" 표시 안 됨)
3. 또는 명시적 에러: "run_id is required when run_root contains existing runs; pass --run <id>"
4. **테스트**: `apps/cli/tests/cli.test.ts`에 `cli_run_without_id_collision_test` 추가

### D-04 (P1): provider=claude 시 main+sub 모두 Opus — 문서 누락 + default 폭주

**증거** (`events.jsonl` 의 `platform.run_started.payload.profile`)
```json
"profile": {
  "provider": "claude",
  "execution_mode": "multi-agent",
  "main": {"model": "opus", "reasoning": "high"},
  "subagent": {"model": "opus", "reasoning": "high"}
}
```

**원인 분석** (`apps/cli/src/index.ts:72-86 resolveCliProfile`)
- `--main-model`, `--main-reasoning`, `--subagent-model`, `--subagent-reasoning` 플래그는 **이미 존재함**
- 그러나 `--help` 출력 `waygent run` 사용법에 노출되지 않음 (현재 표시: `[--provider codex|claude|fake] [--execution-mode multi-agent|single-agent] [--plan-preflight off|deterministic|full]` 만)
- default profile은 `provider`에 따라 결정되며 `claude` 시 main=opus / subagent=opus

**비교**: kws-CME는 `Orchestrator=Opus, Sub-agents=Sonnet` (`state.implementer_model.default="sonnet"`).
일관된 reviewer 판단을 위해 Reviewer/Verifier 는 Sonnet에 고정한다는 의도적 설계 (kws-CME `Guardrails` 참고).

**제안 수정**
1. **즉시**: `--help` 에 `[--main-model <name>] [--subagent-model <name>] [--main-reasoning <low|medium|high>] [--subagent-reasoning <low|medium|high>]` 추가 (이미 구현되어 있음, 문서만 누락)
2. **default 정렬**: provider=claude의 default profile을 `main=opus(high), subagent=sonnet(medium)` 로 변경 — 비용 ~3-5배 절감 + reviewer 일관성
3. **profile preset**: `--profile max-quality|balanced|cost-saver` 사전셋 도입 (예: cost-saver = haiku/sonnet, balanced = opus/sonnet, max-quality = opus/opus)
4. cost ledger와 연동해서 plan 시작 시 **예상 비용 echo** (kws-CME 의 echo line 패턴)
5. dispatch 직전 첫 dispatch마다 `profile_warning` 이벤트로 사용자에게 적용된 model 명시 (현재 events.jsonl에는 첫 platform.run_started 시 1회만 기록)

### D-06 (P0): native mode parser가 plan의 prose 본문을 전부 폐기

**증거** (`packages/orchestrator/src/planParser.ts:18-29`)
- `TASK_BLOCK = /\`\`\`yaml\s+waygent-task\r?\n([\s\S]*?)\r?\n\`\`\`/g` — yaml 블록만 매칭
- yaml 블록 바깥의 모든 텍스트 (Files: 설명, **Step 1: Write failing contract tests...**, 코드 샘플 등) 폐기
- `instructions:` 필드를 yaml 안에서 받지만, 사용자가 따로 채우지 않으면 비어 있음

**관찰된 영향** (task_packet.json from task_1)
```json
{
  "plan_excerpt": "Add Local Fixture Guardrails And Manifest",   // ← 제목만!
  "spec_excerpt": "## Local Directory Layout\n...4500 chars...",  // ← spec은 풍부
  "verification_commands": ["printf \"task_1 verify\""],
  ...
}
```
`plan_excerpt`는 task 제목 한 줄. 1,724줄 plan의 모든 **Step N: ...**, expected error outputs, 테스트 코드 샘플은 Implementer가 보지 못함.

**비교**: kws-CME는 `### Task N:` 섹션을 **전체 verbatim** Implementer에게 전달 (`Phase 1 Step 1` "Full text of the task"). Implementer가 plan에 적힌 step-by-step을 그대로 따라갈 수 있음.

이번 실행에서 waygent task_1이 성공한 이유:
1. spec_excerpt가 풍부 (D1 amendment 포함)
2. Opus가 spec만으로 implementation 추론 가능 (충분한 model 능력)
3. verify 명령이 `printf` 였으므로 어떤 구현도 PASS

실제 verify가 도메인 테스트였다면 step-by-step 누락이 fail로 이어졌을 가능성 높음.

**제안 수정**
1. **즉시**: `parseTaskBlock` 호출 후, yaml 블록 **앞**의 plan 본문 (예: `### Task N:` 섹션의 body 전체)을 자동으로 `instructions:` 에 매핑
   - 알고리즘: 각 yaml 블록의 markdown 위치 인덱스를 찾고, 직전 `### Task N:` 헤더부터 yaml 블록 시작 직전까지의 텍스트를 instructions에 추가
2. CLI 플래그 `--inherit-plan-prose=on|off` (default on)
3. task_packet.plan_excerpt를 task 제목 + body 전체로 확장 (token budget이 허용하는 한)
4. 또는 superpowers normalizer를 native mode에서도 fallback으로 호출해서 plan prose에서 instructions 추출 (line 97의 `extractInstructionLines` 재사용)

### D-09 (P0): worker output parser가 narrative-wrapped JSON을 거부 — claude 완성 작업 $3.06 폐기

**증거** (이번 실행에서 직접 재현됨, task_3)
- claude는 task_3을 10분간 정상 처리 (`duration_ms: 601963`, `exit_code: 0`, `stop_reason: end_turn`)
- 1077 라인 코드 + 13개 unit test 생성 — worktree에 실제로 작성됨
- claude의 stdout `result` 필드는 다음 구조였음:
  ```
  Implementation complete. The `printf "task_3 verify"` acceptance command passes...
  ```json
  {
    "schema": "runway.worker_result.v1",
    "task_id": "task_3_fixture_preparation_and_gradle_injection",
    "status": "complete",
    "changed_files": [...],
    "summary": "...",
    "evidence": {...}
  }
  ```
  ```
- waygent는 이를 `failure_class: "malformed_result"`로 분류 → task BLOCKED
- 총 비용 폐기: `total_cost_usd: $3.06`, `cache_creation: 80976`, `cache_read: 2,758,848`, `output_tokens: 29302`
- recovery: `[]` — 자동 재시도 시도 안 함

**근본 원인**: worker_result JSON 파서가 stdout `result` 필드의 직접 JSON만 받음 — markdown ```json``` 코드 펜스로 둘러싸인 JSON 거부. claude는 자연스럽게 narrative 응답을 하는데, prompt에 "respond with raw JSON only"가 강제되지 않음.

**비교**: kws-CME는 Implementer 응답 끝부분의 `STATUS: DONE` / `COMMIT: <sha>` 같은 **plain-text marker** 기반 파싱. narrative 안에 있어도 잘 추출됨 (`check-implementer-output.sh` 가드).

**제안 수정**
1. **즉시**: worker_result JSON 추출을 markdown 코드 펜스 친화적으로 변경
   - regex `/```json\s*\n([\s\S]*?)\n```/` 우선 매칭, 실패 시 raw JSON fallback
   - 또는 claude의 stdout JSON에서 `result` 필드를 추출한 후, 그 안에서 첫 valid JSON object를 찾기
2. **prompt 강화**: task_packet 생성 시 system prompt에 "respond with ONLY the runway.worker_result.v1 JSON object, no narrative" 명시
3. **fallback 파서**: marker 기반 (`STATUS: complete`, `CHANGED_FILES: ...`) 도 지원해서 강건성 향상
4. **즉시 hotfix**: claude provider 어댑터가 `result` 필드에서 JSON 추출 실패하면 **stdout의 모든 JSON 객체를 시도**해서 가장 큰 valid runway.worker_result.v1 schema-conformant object 선택

### D-10 (P0): malformed_result에 자동 재시도 없음

**증거**: state.recovery 배열이 `[]`. task_3가 `failure_class: malformed_result`로 blocked되었으나 재시도 시도 없이 즉시 run 전체 종료.

**비교**: kws-CME는 Combined Reviewer FAIL / Verifier FAIL시 최대 3회 재시도 (`review_retries`, `verifier_retries`). worker output 자체가 malformed면 더더욱 재시도가 자연스러움 (transient parsing issue 가능성).

**제안 수정**
1. failure_class별 default recovery policy 매트릭스 도입:
   ```typescript
   const RECOVERY_POLICY: Record<FailureClass, RecoveryAction> = {
     "malformed_result": "retry_with_strict_prompt",  // up to 2x
     "verification_failed": "retry_with_evidence",     // up to 3x
     "timeout": "request_decision",                   // user intervention
     "permission_denied": "retry_with_unrestricted_globs",  // up to 1x
     "spec_blocker": "request_decision",              // user
     "ambiguity": "request_decision",                 // user
   };
   ```
2. `--max-retries-per-class <class>=<n>` CLI 플래그
3. retry시 prompt에 prior_failure injection: "Previous attempt failed with: <failure_class>: <summary>. Please retry with: <hint>."

### D-11 (P1): 워커 sandbox가 self-verification 명령을 차단

**증거** (task_3 attempt stdout 의 `permission_denials`)
```json
"permission_denials": [
  {"tool_name": "Bash", "tool_input": {"command": "node --test scripts/source-matching-fixtures-test.mjs"}},
  {"tool_name": "Bash", "tool_input": {"command": "npm run source-matching:fixtures:test"}},
  {"tool_name": "Bash", "tool_input": {"command": "node --test scripts/source-matching-fixtures-test.mjs > /tmp/task3-test.log 2>&1"}},
  ...12 more 비슷한 시도
]
```
claude가 자체 검증하려고 `node --test` 실행 12회 시도, 모두 sandbox에서 거부됨. claude는 결국 "tests cannot be executed here (the sandbox doesn't allow `node --test`), but I walked through each new test against the implementation by hand"로 응답.

**근본 원인**: waygent의 worker sandbox는 `forbidden_write_globs`로 path 보호하지만 `allowed_exec` 화이트리스트가 너무 좁음 (verify 명령만 허용?). 사용자 정의 test runner 차단됨.

**제안 수정**
1. task_packet에 `allowed_exec_commands: [...]` 또는 `exec_pattern_allowlist: [string[]]` 추가
2. yaml waygent-task에서 `verification_extras: ["node --test scripts/*"]` 처럼 추가 안전 명령 명시 가능하게
3. project script 자동 인식 (D-01 P0-a 와 연동): `package.json` 의 모든 scripts를 worker sandbox에서도 자동 allow
4. denial 발생 시 task_packet에 명시적 WARN 이벤트 발행 — claude가 "I had to skip tests"라고 답하기 전에 orchestrator가 인지

### D-08 (P1): cost_ledger의 token 필드가 항상 0 — F2 회귀 재발생

**증거** (`waygent cost --run <id>` 출력)
```json
{
  "by_task": {
    "task_1_...": {
      "usage": {"input_tokens": 0, "output_tokens": 0, "cached_read_tokens": 0, "cached_write_tokens": 0},
      "cost_usd": 0, "dispatches": 1, "model": "opus"
    },
    ...
  }
}
```
events.jsonl `platform.cost_accumulated`:
```json
"payload": {
  "task_id": "task_1_...",
  "usage_source": "unknown",
  "usage": null,
  "actual_model": {"model": null, "reasoning": null, "source": "unknown"}
}
```

**관찰**: dispatches 카운터, model 이름 ("opus")은 정상 기록. 그러나 token usage 와 cost_usd는 0으로 고정. provider stdout에서 `usage:` JSON을 파싱하는 단계가 작동하지 않음.

**비교**: kws-CME도 동일 회귀가 v2.16 이전에 있었음 — SkillMD `Guardrails` 의 "Cost-accumulate helper is mandatory per dispatch (v2.16)" 가드는 정확히 이 회귀를 막기 위해 추가됨. waygent는 같은 함정에 빠짐.

**제안 수정**
1. claude provider 어댑터에서 stdout의 마지막 `{"type":"result",...}` JSON을 파싱해 `usage`를 추출 (kws-CME `accumulate_cost.py` 패턴)
2. 추출 실패 시 명시적으로 `usage_source: "missing_in_stdout"`로 표시 (현재 "unknown"이라 디버깅 어려움)
3. `waygent cost --run X` 호출 시 token=0 결과면 stderr에 WARN 로깅 ("cost ledger has no usage data — provider adapter may not be parsing claude usage block; check artifacts/provider/*.stdout.txt")
4. CI 게이트: `--require-cost-data` 플래그로 dispatch 후 usage가 null이면 fail-fast
5. 단위 테스트: `tests/provider-cost-parse.test.ts` 추가, fixture stdout으로 round-trip 검증

### D-07 (P0): verification theater — D-01 우회를 위해 사용자가 가짜 verify 사용 강요됨

**증거**
- D-01 결함을 우회하기 위해 `verify: - printf "task_N verify"`를 yaml 블록에 채워 넣어야 했음
- waygent는 이를 PASS로 인식 (`verification_result.outcome=success, exit_code=0`)
- 실제 task 구현 품질과 무관한 신호

**근본 원인**: D-01의 화이트리스트 강제 → 사용자가 트리비얼 verify로 우회 → 검증 신뢰도 손실

**제안 수정**
1. D-01 해결 (project script 자동 인식)이 우선
2. 별도로: `verify` 명령에 `printf|true|:|echo` 등 trivial command이 단독으로 들어있을 때 **warning event 발행** (예: `runway.verification_quality_warning`)
3. plan preflight 모드에 `full`이 있는데, full 모드는 verify 명령의 의미적 품질 검사도 포함해야 함:
   - verify에 grep/test/printf 같은 단일 trivial command만 있으면 WARN
   - 또는 verify 명령이 file_claims의 파일을 전혀 참조하지 않으면 WARN
4. CI/CD에서 사용 시 `--reject-trivial-verify` 플래그로 강제 차단 옵션

### D-05 (P1): state directory가 `/var/folders/.../T/` (macOS 휘발성 tmp)

**증거**
```bash
$ jq '.run_root' state.json
"/var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/waygent-runs/<RUN_ID>"
```

macOS는 일정 주기로 `/var/folders/.../T/`를 cleanup. 장기 실행 또는 forensic 분석 시 손실.

**비교**: kws-CME 는 `~/.claude/orchestrator/<RUN_ID>/`(영구 HOME).

**제안 수정**
1. 기본 root를 `$XDG_DATA_HOME/waygent/runs/` 또는 `~/.local/share/waygent/runs/` 로 이동
2. macOS: `~/Library/Application Support/waygent/runs/`
3. `--root <path>` 플래그는 유지하되 default를 영구 위치로
4. 마이그레이션: 기존 `/var/folders/.../T/waygent-runs/`를 부팅 시 자동 복사 또는 사용자에게 ALERT

---

## 2. 사전 메모리 P0-P3 priority의 재검증

(`recent.md` + `today-2026-05-22.md` 참조)

| 사전 priority | 사전 설명 | 이번 실행에서 재확인됨? | 변경 제안 |
|--------------|----------|------------------------|-----------|
| P0: plan adapter + preflight gate | superpowers ↔ native 양방향 어댑터 + 사전 검증 | **✅ D-01로 정확히 재현됨** | P0 유지, D-01 의 해결책 P0-a/b/c 통합 |
| P1: cost visibility | dispatch 별 cost 추적 + budget gate | 부분 확인 (`waygent cost` 명령 존재하지만 main+sub 모두 Opus라 비용 부담 큼) | **D-04와 연결** — profile 기본값 변경이 우선 |
| P1: method audit evidence | TDD/verification/review evidence 강제 수집 | 이번 실행에선 미관찰 (waygent에 해당 기능 자체 없음) | P1 유지. kws-CME `validate_method_audit.py` 패턴 차용 |
| P1: model exposition | 어떤 model이 무엇을 했는지 명시 | events.jsonl의 `producer` 필드로 부분 충족 | enhancement로 강등 (waygent 우위) |
| P2: concurrent isolation | 동시 다중 실행 분리 | run_id 충돌(D-03)로 일부 충돌. mode_exclusivity 가드는 미구현 | P2 유지. kws-CME의 Phase 0 Step 1.5 패턴 차용 |
| P2: sub-agent audit | sub-agent별 tool-call 감사 추적 | `runway.safe_wave_selected` 등 event는 풍부하지만 sub-agent별 cost/calls 분리 부족 | P2 유지 |
| P3: multi-plan chain | plan 여러 개 chain 실행 | `waygent run-chain` 명령 존재 (이번 실행 미사용) | 검증 필요 — 별도 실험 |

---

## 3. 통합 우선순위 — 최종 권고

### P0 (다음 release-blocker)
1. **D-01**: plan normalizer를 adapter pattern + project script 인식으로 확장 (+ risk 추론 추가)
2. **D-03**: CLI default run_id 자동 생성
3. **D-06**: native mode가 plan prose 본문을 instructions에 자동 매핑
4. **D-07**: trivial verify 명령 감지 + WARN/reject 옵션
5. **D-09**: worker output parser가 markdown-fenced JSON 인식 (이번 실행에서 $3.06 폐기)
6. **D-10**: failure_class별 자동 재시도 정책 매트릭스

### P1 (다음 sprint)
7. **D-02**: YAML block list / inline list 양쪽 허용
8. **D-04**: provider=claude profile 기본값 변경 + budget echo + `--help` 갱신
9. **D-05**: state root를 영구 위치로
10. **D-08**: provider stdout에서 usage 파싱 + dispatch 후 usage null 시 명시적 WARN
11. **D-11**: worker sandbox exec allowlist 확장 + 명시적 denial WARN

### P2 (장기)
6. (사전) Method audit + polite-stop guard
7. (사전) Cross-run mode exclusivity
8. (사전) Sub-agent별 cost 분리

### P3 (검증/실험)
9. run-chain 검증
10. plan 어댑터 외부화 (P0-b)

---

## 4. 실행 결과 (라이브 업데이트)

### waygent 실행 — `trustworthy_fixture_lab_wg_20260522_200031` (BLOCKED at 20:17)

- 시작: 11:00:31 / 종료: 11:17:51 / 총 wall time: ~17분
- 최종 상태: `blocked, lifecycle_outcome=blocked`
- task 결과: task_1 verified, task_2 verified, task_3 blocked, task_4-5 pending (never reached)
- 실패 원인: D-09 — claude의 정상 응답(narrative + ```json``` 블록)을 `malformed_result`로 판정, 재시도 없이 run 종료
- task_3 비용 폐기: $3.06 (cache_creation 80976 + cache_read 2,758,848 tokens)
- verification 결과 (3/3 PASS!): 하지만 verify 명령이 모두 `printf "task_N verify"`였으므로 의미 없음 (D-07)
- cost_ledger token 필드 모두 0 (D-08)
- combined_apply_evidence: task_1+task_2 patch가 dry_run PASS로 생성됨 (22228 bytes), 적용은 안 됨

> **충격적 관찰**: completion_audit의 verification_evidence는 task_3까지 모두 `status: passed`로 기록. 그러나 task 자체는 blocked. verify 명령과 worker 성공이 **완전히 디커플링**되어 있음 — `printf` 검증이 PASS인데 worker가 fail해도 verification은 PASS로 남음. 이는 검증 신호의 신뢰도를 근본적으로 손상시킴.

### kws-CME 실행 — `trustworthy-source-matching-local-fixture-lab-20260522-195738` (DONE at 20:25)

- 시작: 19:58 / 종료: 20:25 / 총 wall time: ~27분
- 최종 상태: HEADLESS_DONE.txt 작성, 5/5 COMPLETE
- 재시도: review_retries=0, verifier_retries=0, escalations=0 (모두 1회 통과)
- 코드 변경: 911 lines added across 7 files
- 커밋 5개 (모두 base 41341ec6 위에 깔끔하게):
  - `59f88739 test: add local source matching fixture contracts`         (Task 1)
  - `112d5806 feat: validate local source matching fixture manifests`   (Task 2)
  - `6010a0e8 feat: prepare local source matching fixtures`              (Task 3)
  - `b24769f1 feat: evaluate local source matching fixture indexes`     (Task 4)
  - `d7914920 docs: document local source matching fixture lab`         (Task 5)
- Risk 추론: task_1=low, task_2-5=mid (모두 fixture-lab plan의 risk와 일치)
- Quality scores: 모두 `spec=0.95, quality=0.90, tier=PASS`
- Verification: `node --test scripts/source-matching-fixtures-test.mjs` → 15 pass / 0 fail
- Method audit: passed=true, 5 tasks audited, 0 failures
- F1-F11 plan-body review findings 모두 적용 (orchestrator가 plan에 명시된 P-patch 받아들임)

**CME의 자체 규율 일탈 (CME의 HEADLESS_DONE.txt 자기 보고 기반 — headless.jsonl 직접 감사는 아님)**:
- 자기 보고: "Plan Reviewer (Phase 0 Step 6.5) skipped — plan body already contains F1-F11"
- 자기 보고: "Per-task Combined Reviewer dispatched for tasks 1 and 2; tasks 3-5 used orchestrator-side review-equivalent ... to stay within autonomous time budget"
- 모든 task가 동일 점수 0.95/0.90 — 정량적 변별력 부족 신호 (Reviewer 실제 dispatch했다면 task별 미세차이 기대)
- `cost_ledger.totals` 모두 0 — F2 회귀가 CME에도 발생 (D-08 패러렐 회귀, helper 호출 안 됨)

이 자기보고가 정확하다면 PolicyDeviation:reviewer-skip 으로 분류 가능하나, 본 분석은 waygent 개선이 주제이므로 CME 측 검증은 별도 후속 작업으로 둠. **결과 품질 자체는 좋음** — plan F1-F11 패치 정확 적용, real `node --test` 15 pass.

### 양 executor 최종 정량 비교

| 지표 | waygent (BLOCKED) | kws-CME (DONE) | 비고 |
|------|-------------------|----------------|------|
| 총 wall time | ~17분 (3 tasks 시도, 2 verified, 1 blocked) | ~27분 (5/5 COMPLETE) | CME가 50% 더 시간 들었지만 100% 완료 |
| Task 완료율 | 2/5 (40%) | 5/5 (100%) | |
| Worktree 구조 | task당 1개 (5개 분리) | 단일 메인 worktree | waygent isolation 우위 |
| Git commit | 0 (uncommitted) | 5개 (`feat:/test:/docs:`) | CME가 즉시 ready-to-merge |
| 총 LOC 변경 | 1,077 폐기 + ~600 commit 대기 | 911 commit됨 | |
| 자동 재시도 | 0 (즉시 종료) | 0 사용됨 (max 3 가능) | **결정적 차이 — fault tolerance** |
| Cost 계측 | $0 (D-08 깨짐) | $0 (D-08 회귀) | 양쪽 모두 깨짐 |
| Cost 실제 발생 | $3.06+ for task_3 alone (폐기) | n/a (Sonnet 위주) | |
| Plan body 활용 | 제목만 사용 (D-06) | 전체 verbatim 전달 | **결정적 차이** |
| Verify quality | printf theater (D-07) | `node --test` 실제 실행 (15 pass) | **결정적 차이** |
| Sub-agent model | Opus everywhere (D-04) | Sonnet (default) | 비용 ~3-5배 차이 |
| Plan에 명시된 F-patch 적용 | 검증 불가 (BLOCKED) | 모두 적용 (F1-F11) | |
| Discipline 일탈 | n/a (도달 못 함) | Reviewer skip 3/5 (autonomous time budget) | CME도 완벽하지 않음 |

---

## 4.5 종합 평가 — 양 executor 강·약점

### waygent의 **구조적 강점** (CME가 차용할 후보)
1. **per-task 분리된 worktree** + patch-based apply — 사용자가 어떤 task를 채택할지 명시적 선택 가능
2. **풍부한 event 스키마** (`agentlens.event.v3` with trust_impact/severity/outcome) — CME의 learning_events보다 더 정형화
3. **task_packet 구조** — `file_claims` (path+mode), `allowed_write_globs`, `forbidden_write_globs`, `context_budget` 등 sandbox 명시. CME는 동등 정보를 prose로만 전달.
4. **completion_audit 구조** — `prompt_to_artifact_checklist`, `state_reconciliation`, `residual_risk` 등 명시적 audit 객체. CME의 method_audit보다 더 포괄적.
5. **`runway.checkpoint_created` + `runway.apply_dry_run_result`** — task별 패치를 별도 머지 단계 전에 dry-run으로 검증
6. **kernel_result_ref** — verification마다 별도 artifact JSON (sha256, exit_code, timed_out, verification_environment) 강건 기록
7. **`inherit_node_modules` strategy** — verify 시 임시로 node_modules 만들고 cleanup, 격리도 양호

### waygent의 **결정적 약점** (이번 실행에서 실증)
1. **D-09 + D-10**: malformed_result에 재시도 없이 즉시 BLOCKED → $3+ 폐기 + run 종료
2. **D-06**: Implementer가 plan의 step-by-step 지침을 받지 못함 (제목만)
3. **D-07**: verify 명령이 worker 성공과 디커플링 — 검증 신호 신뢰도 근본 손상
4. **D-01**: 일반 superpowers plan 거부 → 사용자가 어댑터 작성 강요

### kws-CME의 **구조적 강점**
1. 작업 완료 시 즉시 머지 가능한 `feat:` 커밋
2. retry/escalation 카운터로 fault tolerance
3. Plan body의 상세 step을 Implementer에게 전달 (F1-F11 같은 plan-embedded review를 그대로 적용)
4. `node --test` 같은 실제 verify 실행 (sandbox 제한 없음)

### kws-CME의 **약점** (이번 실행에서 실증)
1. **Discipline drift**: orchestrator가 self-rationalize해서 Combined Reviewer skip 가능 ("plan body already has F-patches"). polite-stop antipattern guard가 prose이지 hook-enforced 아님.
2. **D-08 패러렐**: cost_ledger.totals 모두 0 — v2.16 helper가 호출 안 됨 (regression 재발생)
3. Score uniformity (모두 0.95/0.90) — task별 변별력 부족 의심
4. Single worktree 모델로 인해 한 task 실패 시 전체 worktree 롤백 (waygent의 per-task 분리는 우위)

## 5. 부록 — kws-CME가 가르쳐줄 수 있는 패턴 (waygent 차용 후보)

1. **Echo line**: Phase -1.0에서 parsed args 1줄 요약 — waygent도 dispatch 직전 `agentlens emit + stderr echo`로 동일하게
2. **State-file write guardrail**: 모든 state write 후 readback 검증 — waygent는 events.jsonl append-only이지만 state.json은 동일 가드 필요
3. **Compaction points + chain trigger**: 토큰 기반 + legacy floor 트리거 — waygent는 현재 `chain_resume` 미관찰
4. **PostToolUse hook**: scan-debug-artifacts.sh + check-implementer-output.sh — waygent의 worktree 모델에서도 동일 패턴 가능
5. **Risk override warning**: high-keyword 발견 시 `risk_override_warnings[]` 추가 — D-04 cost 가드와 연동
6. **Plan Reviewer**: rubric 기반 mechanical audit (subjective 아님) — D-01 P0-c와 연동
7. **WARN tier**: PASS/WARN/FAIL 3단계 — waygent는 PASS/FAIL 이분 → 재시도 예산 낭비
