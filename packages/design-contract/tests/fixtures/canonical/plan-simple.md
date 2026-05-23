# Plan: Recovered Task Risk

## Task task_1

- title: Wire recovered risk in planNormalizer
- risk: high
- file_claims:
  - packages/orchestrator/src/planNormalizer.ts: write
- verification_commands:
  - bun test packages/orchestrator/tests/planNormalizer.test.ts
- prescriptive_block_ids:
  - SNIP-001
- required_invariant_acks:
  - INV-001
