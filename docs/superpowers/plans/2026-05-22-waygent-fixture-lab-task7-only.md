# Waygent Fixture-Lab — task_7 Standalone Re-run

Companion: `2026-05-22-waygent-fixture-lab-detailed-implementation.md` (full
plan). This file isolates task_7 (Persistent State Root, D-05) for a
standalone Waygent run after tasks 1–6 have been applied to source.

The implementation guidance is the §T7 section of the full implementation
document and §S9 (`Module M21 — orchestrator.ts (defaultRunRoot)` and
`Module M07 — orphanRuns.ts`) of the spec
`2026-05-22-waygent-fixture-lab-detailed-spec.md`.

Files to create / modify and the verification command are declared in the
waygent-task block below.

```yaml waygent-task
id: task_7
title: Persistent State Root (D-05)
dependencies: []
file_claims:
  - path: packages/orchestrator/src/orphanRuns.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: docs/operations/state-root-migration.md
    mode: owned
  - path: packages/orchestrator/tests/defaultRunRoot.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/defaultRunRoot.test.ts
```
