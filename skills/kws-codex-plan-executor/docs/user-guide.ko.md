# CPE 4 사용자 가이드

CPE 4는 승인된 Superpowers 구현 계획을 오래 실행하기 위한 durable queue입니다.
작은 한 세션 작업은 direct Superpowers가 더 단순합니다. 여러 스펙과 계획을
며칠에 걸쳐 실행하거나 중단 후 정확히 재개해야 할 때 CPE를 사용합니다.

## 실행

spec과 plan은 여러 번 줄 수 있고 plan은 최소 하나가 필요합니다.
program-plan은 선택이며 한 번만 줄 수 있습니다.

    python3 scripts/cpe.py run \
      --spec /abs/spec-a.md \
      --spec /abs/spec-b.md \
      --plan /abs/plan-a.md \
      --plan /abs/plan-b.md \
      --program-plan /abs/program.md \
      --workspace /abs/repo

입력 순서는 우선순위가 아닙니다. 서로 충돌하는 승인 문서는 명시적 supersession
또는 사용자가 선택한 authority 답변으로만 해결합니다.

명령은 JSON 한 줄을 출력합니다.

| status | exit | 의미 |
| --- | ---: | --- |
| completed | 0 | 현재 revision의 terminal artifact가 저장됨 |
| failed | 1 | 호출 또는 무결성 실패로 안전한 진행 불가 |
| waiting_authority | 2 | 사용자 권한 결정이 필요한 항목 존재 |
| interrupted | 3 | durable state가 유효하며 resume 가능 |

completed는 실행 수명주기 상태입니다. 제품 품질 판단은 terminal artifact의
quality_verdict, 검증 exit, auditor verdict, limitations를 확인해야 합니다.

## 상태 확인과 재개

    python3 scripts/cpe.py inspect --run-id RUN_ID
    python3 scripts/cpe.py resume --run-id RUN_ID

inspect는 읽기 전용입니다. resume는 manifest, event chain, artifacts, 선택된
map publication, worktree, commit을 검증한 뒤 첫 미완료 항목부터 진행합니다.
이미 완료된 task나 clean review를 다시 dispatch하지 않습니다.

authority item이 있으면 packet에 제시된 선택지 중 하나를 그대로 사용합니다.

    python3 scripts/cpe.py resume --run-id RUN_ID \
      --authority-id AUTHORITY_ID \
      --authority-answer OFFERED_OPTION

사용자에게 물을 수 있는 경계는 credential, 외부 부작용, worktree 밖의
비가역적 삭제, 승인 문서 충돌, 중대한 범위 확대, 법률·보안·정책 권한뿐입니다.
일반 버그, 테스트 실패, 리뷰 지적, 구현 선택, 로컬 환경 복구는 자동으로
증거를 보존하고 전략을 바꿔 계속합니다.

원본 문서를 수정해도 진행 중 run은 자동 변경되지 않습니다.

    python3 scripts/cpe.py resume --run-id RUN_ID --refresh-inputs

refresh는 새 generation을 만들며 이전 snapshot과 완료 증거를 보존합니다.
변경된 brief나 의존성의 영향을 받는 task만 무효화합니다.

## Export

    python3 scripts/cpe.py export \
      --spec /abs/spec.md --plan /abs/plan.md \
      --workspace /abs/repo --mode prompt

    python3 scripts/cpe.py export \
      --plan /abs/plan.md --workspace /abs/repo --mode handoff

export는 stdout에 텍스트만 출력합니다. run directory, snapshot, event,
worktree를 만들지 않고 Codex를 실행하지 않습니다.

## 실행 흐름

1. 각 문서를 fresh read-only mapper가 snapshot에서 읽습니다.
2. program mapper가 exact brief, coverage, dependency, authority queue를 만듭니다.
3. non-LLM queue가 ready task를 하나씩 실행합니다.
4. task agent는 TDD와 focused test 후 clean commit을 남깁니다.
5. fresh reviewer가 exact diff를 검토하고 필요하면 investigator/fixer가
   다른 전략으로 수정합니다.
6. 문서별 auditor가 final revision의 source coverage를 확인합니다.
7. Program Final Integrator가 전체 diff를 검토하고 full verification을 한 번
   실행한 뒤 terminal artifact를 만듭니다.

write 가능한 role은 동시에 하나만 실행됩니다. 이후 write가 생기면 기존 audit와
final verification은 무효화됩니다.

## 파일과 보존

기본 run root는 ~/.codex/orchestrator/RUN_ID, worktree는
~/.codex/worktrees/RUN_ID입니다. events.jsonl이 권위 있는 상태 기록이고,
artifacts.jsonl이 immutable bytes를 digest와 연결합니다.

검증을 마친 generation mapping bundle만 immutable logical path에 설치되고
map.generation_created event가 선택합니다. 중단되거나 거부된 mapper 출력은
outbox에만 남아 권위 상태가 되지 않습니다. active run 내부 파일을 직접 개별
삭제하지 마세요.

schema-3 run은 inspect만 가능합니다. CPE 4 resume은 거부하며 기존 파일을
수정하지 않습니다.

## 검증

    ./evals/run.sh
    python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
    bash -n evals/run.sh
    python3 scripts/cpe.py --help
    python3 scripts/cpe.py run --help
    python3 scripts/cpe.py export --help

eval은 정확히 여섯 check이며 network, credential, 유료 호출 없이 개발
환경에서 60초 안에 끝나야 합니다.
