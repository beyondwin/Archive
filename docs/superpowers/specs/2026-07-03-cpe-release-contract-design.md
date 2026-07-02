# CPE Release Contract Design

작성일: 2026-07-03
상태: APPROVED DESIGN
대상 표면: `skills/kws-codex-plan-executor`

## Problem

`kws-codex-plan-executor`는 이미 하나의 독립 skill package처럼 운영되고 있다.
`SKILL.md`에는 metadata version이 있고, `HISTORY.md`, deterministic eval
baseline, verification log, doc update protocol도 있다.

하지만 현재 릴리스 운영 경계는 약하다. `SKILL.md`의 공식 버전은 `2.24.0`인
반면 `HISTORY.md`에는 `2.25.0 - Unreleased`가 쌓여 있고, 어떤 변경에서
버전을 올려야 하는지, baseline을 언제 갱신해야 하는지, 어떤 문서가 반드시 같이
바뀌어야 하는지에 대한 기계적 guard가 부족하다.

그 결과 CPE를 업데이트할 때마다 다음 위험이 반복된다.

- Runtime/script/prompt/eval 변경이 문서와 분리된다.
- `SKILL.md` version, `HISTORY.md`, `evals/baselines/v<version>.json`이
  서로 어긋난다.
- `docs/verification-log.md`가 변경 증거를 따라가지 못한다.
- 다음 agent가 릴리스 준비 상태인지, 아직 unreleased 작업인지 판단하기 어렵다.

## Goals

- CPE 버저닝 단위를 `skills/kws-codex-plan-executor` package로 고정한다.
- 공식 버전 source of truth를 `SKILL.md metadata.version`으로 명시한다.
- 버전 bump 기준을 `major`, `minor`, `patch`, `no bump`로 문서화한다.
- `HISTORY.md`, eval baseline, verification log, release docs를 하나의
  릴리스 계약으로 묶는다.
- 누락되기 쉬운 릴리스 계약을 deterministic eval로 검증한다.
- 기존 CPE execution/state/prompt machine contract는 바꾸지 않는다.

## Non-goals

- Waygent 전체 플랫폼 버저닝 체계를 새로 만들지 않는다.
- CPE runtime state schema나 execution behavior를 변경하지 않는다.
- `docs/experiments/v*`를 공식 release source of truth로 만들지 않는다.
- Git commit 날짜나 verification-log 최신성을 과도하게 추론하지 않는다.
- Baseline을 자동으로 갱신해서 failing change를 숨기지 않는다.
- Root-level docs index나 pruned documentation library를 재도입하지 않는다.

## Reviewed Approaches

### A. Recommended: Release Contract + Deterministic Guard

새 `docs/release-process.md`를 추가하고, 기존 `doc-update-protocol.md`,
`HISTORY.md`, `SKILL.md`, `evals/baselines/v*.json`, `verification-log.md`를
릴리스 계약에 묶는다. 새 `evals/check_release_contract.py`는 버전과 문서
계약의 기본 정합성을 확인하고 `evals/run.sh`에 포함된다.

장점:

- 기존 CPE 구조를 살린다.
- 버전, baseline, history 누락을 테스트로 잡는다.
- 다음 agent가 릴리스 절차를 파일 하나에서 확인할 수 있다.
- Waygent 전체 릴리스 체계로 확장할 여지를 남긴다.

단점:

- 새 문서와 eval을 유지해야 한다.
- 첫 도입 시 현재 `2.25.0 - Unreleased` 상태를 정리해야 한다.

이 접근을 선택한다.

### B. HISTORY 중심 수동 규칙 강화

`HISTORY.md`와 `doc-update-protocol.md`만 정리해서 사람이 릴리스 체크리스트를
따르게 한다.

장점:

- 구현량이 작다.
- 기존 eval harness를 건드리지 않는다.

단점:

- 누락을 자동으로 막지 못한다.
- CPE처럼 계약 문서와 eval이 많은 skill에는 반복 실수가 남는다.
- 현재 발생한 version/history drift를 구조적으로 해결하지 못한다.

이 접근은 충분하지 않다.

### C. Experiment Directory 중심 버전 체계

`docs/experiments/v*`를 모든 변경의 중심으로 두고 각 기능마다
PLAN/IMPLEMENTATION/RESULTS를 관리한다.

장점:

- 변경 의도와 실험 과정을 자세히 보존한다.
- 큰 기능 개발의 맥락 추적이 쉽다.

단점:

- 공식 runtime source of truth인 `SKILL.md`, scripts, references, eval
  baseline과 분리될 수 있다.
- 실험 기록과 릴리스 계약이 섞인다.
- 작은 patch나 docs-only 변경에는 과하다.

이 접근은 실험 기록으로는 유지하되, 공식 릴리스 계약으로는 사용하지 않는다.

## Design

### 1. Release Source Of Truth

CPE package의 공식 version은 `skills/kws-codex-plan-executor/SKILL.md`의
`metadata.version`이다.

릴리스 계약은 다음 파일을 함께 묶는다.

- `SKILL.md`: 현재 공식 package version과 user-facing skill metadata
- `HISTORY.md`: released 및 unreleased 변경 이력
- `evals/baselines/v<version>.json`: 해당 version의 deterministic fixture
  baseline
- `docs/verification-log.md`: 변경 및 릴리스 검증 증거
- `docs/release-process.md`: 릴리스 운영 규칙
- `docs/doc-update-protocol.md`: 변경 유형별 문서 영향도 map

`docs/experiments/v*`는 설계/구현 기록으로 남기지만, 공식 version source of
truth가 아니다.

### 2. Release Process Document

새 `skills/kws-codex-plan-executor/docs/release-process.md`는 다음 내용을
포함한다.

- Version source of truth
- `major`, `minor`, `patch`, `no bump` 기준
- `Unreleased` 항목을 release version으로 닫는 절차
- Eval baseline 갱신 조건과 금지 조건
- Verification log 작성 규칙
- Release checklist
- Docs-only 변경에서 version bump를 생략할 수 있는 조건

기존 `docs/doc-update-protocol.md`는 변경 영향도별 문서 map에 집중하고,
릴리스 절차는 `release-process.md`를 참조한다.

`docs/future-agent-guide.md`와 `SKILL.md` Maintenance section은
`release-process.md`와 `doc-update-protocol.md`를 모두 읽도록 안내한다.

### 3. Version Bump Rules

Versioning은 semver로 운영한다.

`major`:

- 기존 state schema consumer를 깨는 변경
- prompt/headless output schema의 breaking change
- invocation semantics breaking change
- worktree/runtime layout breaking change
- 기존 eval fixture 또는 downstream operator workflow가 호환되지 않는 변경

`minor`:

- 새 기능
- 새 optional state field
- 새 script/eval
- 새 prompt/handoff/headless surface
- 새 inspection/readiness/replay 기능
- 호환 가능한 runtime behavior 확장

`patch`:

- 버그 수정
- 문서와 실제 동작의 불일치 수정
- 기존 기능의 호환 가능한 보정
- eval 안정화
- baseline output의 의도된 호환 보정

`no bump`:

- 순수 문서 정리
- 오타 수정
- verification-log 보강
- runtime, script, prompt, eval behavior, package metadata, public skill
  metadata를 바꾸지 않는 변경

### 4. Unreleased Policy

개발 중인 변경은 `HISTORY.md`의 `Unreleased` section에 쌓는다.

릴리스할 때:

1. `SKILL.md metadata.version`을 새 version으로 올린다.
2. `HISTORY.md`의 relevant unreleased 항목을 새 version section으로 닫는다.
3. `evals/run.sh --update-baseline`을 실행해
   `evals/baselines/v<version>.json`을 만든다.
4. `docs/verification-log.md`에 검증 증거를 남긴다.
5. `evals/run.sh`, `python3 -m py_compile scripts/*.py evals/*.py`,
   `bash -n evals/run.sh`, `git diff --check`로 닫는다.

현재 도입 시점에는 `2.25.0 - Unreleased`에 이미 기능이 쌓여 있으므로,
release-contract 도입과 함께 `2.25.0`을 공식 release로 닫는 것을 기본 방향으로
한다. 단, 구현 계획에서 실제 diff와 baseline 결과를 확인한 뒤 최종 결정한다.

### 5. Deterministic Release Contract Check

새 `skills/kws-codex-plan-executor/evals/check_release_contract.py`를 추가한다.

첫 구현 범위의 검사 항목:

- `SKILL.md`에서 semver를 파싱할 수 있다.
- `evals/baselines/v<version>.json`이 존재한다.
- baseline JSON의 `version` 값이 `SKILL.md` version과 같다.
- `HISTORY.md`에 현재 version section이 있다.
- `HISTORY.md`에 중복 version heading이 없다.
- `docs/release-process.md`가 존재한다.
- `docs/release-process.md`가 `major`, `minor`, `patch`, `no bump`,
  `baseline`, `verification-log` 핵심 용어를 포함한다.
- `docs/doc-update-protocol.md`가 `release-process.md`를 참조한다.
- `docs/future-agent-guide.md`가 `release-process.md`를 참조한다.
- `SKILL.md` Maintenance section이 `release-process.md`와
  `doc-update-protocol.md`를 모두 언급한다.

`evals/run.sh`는 이 check를 full harness에 포함한다.

에러 메시지는 바로 고칠 수 있는 파일과 기대값을 포함한다. 예:

```text
missing baseline for SKILL.md version: evals/baselines/v2.25.0.json
```

### 6. Error Handling

`check_release_contract.py`는 read-only여야 한다. 파일을 생성하거나 baseline을
자동 갱신하지 않는다.

검사 실패는 JSON summary와 사람이 읽을 수 있는 failure message를 출력한다.
다른 CPE eval과 동일하게 non-zero exit code로 실패한다.

첫 버전에서는 다음을 의도적으로 검사하지 않는다.

- Git commit 날짜 기반 verification-log 최신성
- `HISTORY.md` 항목과 diff의 semantic matching
- 모든 reference doc의 deep link 유효성
- Root-level docs index 존재 여부

이 항목들은 false positive 위험이 커서 후속 개선으로 남긴다.

### 7. Testing And Verification

Implementation must add focused coverage first:

- `python3 evals/check_release_contract.py`
- `./evals/run.sh`
- `python3 -m py_compile scripts/*.py evals/*.py`
- `bash -n evals/run.sh`
- `git diff --check`

If the release contract implementation officially closes `2.25.0`, the plan
must also run:

```bash
./evals/run.sh --update-baseline
./evals/run.sh
```

The updated baseline must be reviewed as an intentional artifact, not used to
hide failing fixture behavior.

## Acceptance Criteria

- CPE has a documented release process at
  `skills/kws-codex-plan-executor/docs/release-process.md`.
- `doc-update-protocol.md`, `future-agent-guide.md`, and `SKILL.md` point future
  agents to the release process.
- A deterministic release-contract eval prevents version/history/baseline drift.
- `evals/run.sh` includes the release-contract eval.
- If `2.25.0` is made official, `SKILL.md`, `HISTORY.md`, and
  `evals/baselines/v2.25.0.json` agree.
- Verification evidence is appended to `docs/verification-log.md`.
- Existing CPE execution, state, prompt, and headless behavior remain unchanged
  unless explicitly covered by a future implementation plan.

## Open Risks

- `check_release_contract.py` can become too strict if it tries to infer intent
  from git history. Keep the first pass structural.
- The current `HISTORY.md` has `2.25.0 - Unreleased`; implementation must decide
  whether to close it as official `2.25.0` or normalize headings before release.
- Baseline updates can mask behavior changes if reviewed casually. The release
  process must require human review of generated baseline diff.
- The CPE package may later be reattached to a plugin package. If that happens,
  release-process must add plugin metadata as another required version surface.
