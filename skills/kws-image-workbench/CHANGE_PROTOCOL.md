# Change Protocol

## Contract Changes

trigger, mode, authorization을 바꾸면 `SKILL.md`, positive fixture, near-miss
fixture, README를 같은 change에 갱신합니다. `brief`/`audit`의 read-only 경계와
generate/edit의 explicit authorization은 fixture로 재확인합니다.

## ImageSpec And Rubric Changes

`ImageSpec`, input role, route 변경은 skill, [ImageSpec reference](references/image-spec.md),
fixture를 동기화합니다. acceptance가 달라지면 [quality rubric](references/quality-rubric.md)도
함께 바꿉니다. status 또는 handoff 변경은 rubric, evaluator, fixture, README를 함께
수정합니다.

## Evidence Changes

provider 또는 source claim은 direct authoritative locator, checked date, adopted idea,
rejected boundary를 갖춰야 하며 자동으로 runtime behavior를 바꾸지 않습니다. 외부
repository를 새로 사용하려면 immutable revision, 그 revision에서 읽은 license file,
reuse boundary를 [evidence register](references/sources.md)에 기록합니다. license는
code에 대한 조건일 수 있으나 prompt·gallery·example image의 권리를 자동으로 주지
않습니다.

## Fixture And Inspector Changes

fixture schema나 판단 규칙은 evaluator self-test와 positive/near-miss fixture를 먼저
바꿔 RED를 확인한 뒤 구현합니다. inspector output 변경은 script self-test, evaluator
full-scope expectation, README를 같이 고치고 behavior가 달라지면 SemVer를 올립니다.
offline fixture는 image quality의 증명이 아니며 live canary는 opt-in으로 별도 보고합니다.

## Versioning

behavior 변경은 `SKILL.md`의 `metadata.version`을 SemVer로 bump합니다. wording-only
문서 변경은 behavior를 바꾸지 않는 한 version bump가 필요 없습니다. provider source
refresh도 adopted/rejected boundary와 behavior가 그대로면 version bump를 자동으로
요구하지 않습니다.

## Required Verification

Repository acceptance는 다음 정확한 command set입니다.

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" skills/kws-image-workbench
python3 skills/kws-image-workbench/evals/run.py --self-test
python3 skills/kws-image-workbench/evals/run.py --scope full
python3 skills/kws-image-workbench/scripts/inspect_asset.py --self-test
bun run agent:verify
git diff --check
```

live image canary는 opt-in이며 위 offline acceptance와 분리해 status, cost/consent
boundary, output evidence를 따로 보고합니다.
