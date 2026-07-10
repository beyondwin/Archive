# CPE v3 검사 흐름

결정론적 harness는 실제 유료 모델을 호출하지 않고 v3 모듈과 임시 저장소를
검사합니다.

```mermaid
flowchart LR
  Dependency["의존성 preflight"] --> Policy["고정 모델 정책"]
  Policy --> Store["manifest, event, evidence"]
  Store --> Execute["가짜 provider 실행"]
  Execute --> Consumers["validate, reconcile, repair, inspect"]
  Consumers --> Fault["fault injection"]
  Fault --> Release["release/docs contract"]
```

검사는 이벤트 해시와 replay, 순차 쓰기, 읽기 전용 조사, 모델 attestation,
증거 digest, 소비자 간 오류 코드, 안전한 수리, 조회의 비변경성, 오래된 경로와
과장된 릴리스 문구를 다룹니다.

현재 v3 harness에서는 기존 정적 YAML 실행 fixture 반복이 비활성화되어
있습니다. 따라서 `./evals/run.sh` 통과는 결정론적 준비 상태를 뜻할 뿐,
유료 라이브 품질 gate 통과를 뜻하지 않습니다. 유료 gate는 별도 명시적 비용
승인 후 4개 treatment와 8개 case를 실행해 성공 보고서를 만들어야 합니다.
