# 복구 task의 risk 정책

prose 형식의 plan에서 recover된 task는 항상 risk를 high로 정해야 한다.
이건 두 곳에 적용된다: 옛 planNormalizer의 superpowers 모드와, 새
intakeRecovery의 deterministicRepair. 두 곳 모두 `risk: "high" as const`가
하드코드되어 있어야 한다.
