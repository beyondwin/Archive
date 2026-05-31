# Memory Projection Implementation

## Overview
Implement the approved memory projection in small, testable tasks.

## Files
- `src/memory/project.ts`
- `src/pages/memory.astro`
- `tests/memory-project.test.ts`

## Implementation Plan
| Task | Change | Files | Acceptance |
| --- | --- | --- | --- |
| T1 | Add deterministic projection builder. | `src/memory/project.ts` | `npm run memory:project` |
| T2 | Render public projection page. | `src/pages/memory.astro` | Browser smoke on `/memory` |
| T3 | Add regression coverage. | `tests/memory-project.test.ts` | `npm run test` |

## Traceability Matrix
| Requirement | Implementation | Verification |
| --- | --- | --- |
| R1 | T1 | `npm run memory:project` |
| R2 | T2 | Manual smoke: `/memory` hides private source text |

## Verification Plan
- `npm run memory:project`
- `npm run test`
- `npm run build`
- Manual smoke: inspect `/memory` in a browser.

## Rollback Plan
Revert the projection route and generated public JSON artifacts.

## Risks
- Existing content paths may move during implementation.

## Done When
- All verification commands pass.
- Spec requirements R1 and R2 are mapped to tasks.
