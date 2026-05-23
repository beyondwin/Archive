# Design: Recovered Task Risk

## Cross-Path Invariants

- id: INV-001
  description: Recovered tasks must emit risk=high
  paths_bound:
    - packages/orchestrator/src/planNormalizer.ts
    - packages/orchestrator/src/intakeRecovery.ts
  enforcement:
    mode: deterministic
    check:
      kind: rg
      pattern: "risk:\\s*\"high\"\\s+as const"
      paths:
        - packages/orchestrator/src/planNormalizer.ts
        - packages/orchestrator/src/intakeRecovery.ts
      must_match: true
  policy_ack_required: true
  policy_ack_min_confidence: verified

## Prescriptive Snippets

```ts id=SNIP-001
const useInferredRisk = input.infer_risk === true;
```
