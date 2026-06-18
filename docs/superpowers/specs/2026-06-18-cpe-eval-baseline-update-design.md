# CPE Eval Baseline Update 설계

작성일: 2026-06-18
대상: `skills/kws-codex-plan-executor`
상태: 사용자 스펙 검토 대기
우선순위: A(검증 부작용/실행 마찰 제거)

## 목표

`kws-codex-plan-executor`의 `evals/run.sh`는 deterministic checks와 fixture
검증을 한 번에 실행하는 핵심 품질 게이트다. 현재 구조는 검증 결과를 항상
`evals/baselines/v<version>.json`에 다시 쓰기 때문에, 동작 변화가 없어도
baseline의 `date` 필드가 갱신되어 워크트리가 더러워진다.

이번 개선의 목표는 품질 게이트를 줄이지 않고 eval 실행 부작용을 제거하는
것이다.

1. 기본 `./evals/run.sh`는 검증 전용이어야 한다.
2. baseline 파일은 명시적인 갱신 옵션을 줄 때만 바뀌어야 한다.
3. fixture 결과가 기존 baseline과 다르면 기본 검증은 실패하고 갱신 명령을
   안내해야 한다.
4. 기존 deterministic checks, parser fixture checks, prompt/execution fixture
   checks는 그대로 유지해야 한다.

## 현재 상태

현재 `run.sh`는 다음 흐름을 가진다.

1. `SKILL.md`에서 version을 읽는다.
2. `evals/baselines/v<version>.json` 경로를 정한다.
3. 개별 deterministic checks를 실행한다.
4. parser fixtures를 실행한다.
5. prompt/handoff/interactive/headless fixtures를 deterministic runner로
   실행하고 checker 결과를 `.partial`에 쓴다.
6. `jq -s --arg version "$SKILL_VERSION" '{version: $version, date: now | todate, fixtures: .}'`
   로 baseline 파일을 항상 덮어쓴다.

이 구조의 문제는 검증과 baseline 갱신이 분리되어 있지 않다는 점이다. 실제
fixture 결과가 동일해도 `date`가 바뀌므로 검증만 실행한 작업자가 별도 cleanup을
해야 한다. 이전 CPE adaptive delegation 작업에서도 이 timestamp-only diff가 반복
정리 비용으로 관찰되었다.

## 설계 원칙

1. 검증 실행은 기본적으로 read-only에 가까워야 한다. fixture temp directory와
   transient partial file은 허용하지만 tracked baseline은 기본 실행에서 바꾸지
   않는다.
2. baseline 갱신은 의도적 행위여야 한다.
3. baseline 비교는 timestamp가 아니라 fixture 의미 결과를 기준으로 한다.
4. 검증 강도는 낮추지 않는다. 기존 checks와 fixture coverage는 제거하지 않는다.
5. 실패 메시지는 다음 행동을 명확히 말해야 한다.

## 목표 동작

### 기본 검증

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
```

기본 실행은 모든 기존 checks를 실행한 뒤 새 결과를 임시 JSON으로 만든다.
그 후 기존 baseline과 비교한다.

- baseline이 없으면 실패한다.
- fixture 목록, mode, runner/checker status, passed flag, checks payload가 다르면
  실패한다.
- baseline의 `date` 차이는 비교 대상이 아니다.
- 비교가 통과하면 tracked baseline 파일은 바뀌지 않는다.

불일치 시 출력은 다음을 포함한다.

```text
baseline mismatch: evals/baselines/v2.22.0.json
Run ./evals/run.sh --update-baseline after reviewing the changed eval output.
```

### 명시적 baseline 갱신

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh --update-baseline
```

`--update-baseline`은 모든 기존 checks를 통과한 뒤 baseline 파일을 새 결과로
쓴다. 이때 `date`는 현재 시간으로 갱신해도 된다. 즉, `date`는 baseline 갱신
이벤트의 metadata이고 기본 검증 비교 기준은 아니다.

### 특정 fixture 실행

기존처럼 fixture 인자를 받을 수 있어야 한다.

```bash
./evals/run.sh fixtures/01-prompt-only.yaml
./evals/run.sh --update-baseline fixtures/01-prompt-only.yaml
```

특정 fixture만 실행한 기본 검증은 두 가지 중 하나로 명확히 동작해야 한다.

- 추천: partial fixture result를 기존 baseline의 해당 fixture subset과 비교한다.
- 대안: fixture subset 실행에서는 baseline 비교를 생략하고 summary만 출력한다.

추천은 subset 비교다. 이렇게 하면 빠른 focused eval도 tracked baseline을 더럽히지
않으면서 회귀를 잡을 수 있다.

특정 fixture와 `--update-baseline`을 함께 쓰는 경우에는 전체 baseline을 subset
결과로 덮어쓰지 않는다. 기존 baseline을 읽고 실행한 fixture 항목만 교체하며,
실행하지 않은 fixture 항목과 top-level version은 보존한다. `date`는 baseline
갱신 이벤트 metadata로 갱신한다.

## 구현 경계

변경 대상은 CPE skill package 내부로 제한한다.

- `skills/kws-codex-plan-executor/evals/run.sh`
- `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
- 필요 시 `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- 필요 시 `skills/kws-codex-plan-executor/HISTORY.md`

이번 변경은 다음을 하지 않는다.

- fixture runner/checker coverage 축소
- baseline JSON schema 대규모 변경
- dynamic model eval 재도입
- Waygent runtime 변경
- state schema 변경

## 검증 설계

`check_eval_harness.py`에 다음 계약을 추가한다.

1. `run.sh`는 `--update-baseline` 옵션을 지원한다.
2. 기본 실행은 baseline 파일을 항상 쓰는 구조가 아니다.
3. 기본 실행은 generated result와 baseline을 비교하는 경로를 가진다.
4. baseline mismatch 시 `--update-baseline` 안내 문자열을 포함한다.
5. `--update-baseline` 경로는 baseline 파일을 쓰는 명시 경로다.

정적 검사만으로 부족한 경우, `check_eval_harness.py`는 작은 임시 baseline/result
fixture를 사용해 비교 helper를 직접 실행하는 방식으로 보강할 수 있다. 단,
전체 `run.sh`를 중첩 실행해 느린 fixture suite를 반복 실행하지 않는다.

수동 검증 명령:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_eval_harness.py
./evals/run.sh
git diff -- evals/baselines/v2.22.0.json
./evals/run.sh --update-baseline
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

기대 결과:

- 기본 `./evals/run.sh` 뒤 baseline timestamp-only diff가 생기지 않는다.
- 실제 fixture 결과가 바뀌면 기본 실행이 실패한다.
- `--update-baseline`을 명시하면 baseline 파일이 갱신된다.

## 에러 처리

- baseline 파일이 없으면 기본 실행은 실패하고 `--update-baseline`을 안내한다.
- baseline JSON이 parse되지 않으면 실패한다.
- fixture subset 비교에서 해당 fixture가 baseline에 없으면 실패하고
  `--update-baseline`을 안내한다.
- deterministic check가 실패하면 기존처럼 즉시 실패한다.
- checker failure가 있으면 baseline 비교 전 전체 실행은 실패 상태를 유지한다.

## 문서 업데이트

`docs/evals-and-verification.md`는 다음 내용을 반영한다.

- `./evals/run.sh`는 기본 검증 명령이다.
- baseline을 의도적으로 갱신할 때만 `./evals/run.sh --update-baseline`을 쓴다.
- 검증 중 baseline 파일이 바뀌면 의도치 않은 부작용으로 보고 원인을 확인한다.

`HISTORY.md`의 unreleased 섹션에는 eval baseline 갱신이 명시 옵션으로 분리됐다는
내용을 추가한다.

## 성공 기준

1. 기본 eval 실행이 tracked baseline 파일을 수정하지 않는다.
2. baseline mismatch는 검증 실패로 드러난다.
3. baseline 갱신은 `--update-baseline`으로만 발생한다.
4. 기존 deterministic checks와 fixture checks는 모두 유지된다.
5. 변경은 CPE skill package 내부에 머문다.
6. `git diff --check`, `python3 -m py_compile scripts/*.py evals/*.py`,
   `bash -n evals/run.sh`, `./evals/run.sh`로 검증 가능하다.
