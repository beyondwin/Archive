# Memory Projection Spec

## Overview
Build a repository-grounded projection page that exposes selected memory nodes.

## Goals
- Give readers a public-safe map of memory topics.
- Keep private raw notes out of the public projection.

## Non-goals
- Do not expose private raw graph dumps.
- Do not replace the existing article index.

## Requirements
| ID | Requirement | Acceptance |
| --- | --- | --- |
| R1 | Render curated memory topics from repository seed data. | `npm run memory:project` writes deterministic JSON. |
| R2 | Hide private source text from public output. | Browser smoke shows summaries only. |

## User Experience
The page opens with the map, then lets the reader inspect topic summaries.

## Architecture
Projection code reads source JSON, normalizes nodes, and writes public artifacts.

## Data
Use repository-local JSON fixtures as source of truth. Do not scrape runtime state.

## Traceability Matrix
| Requirement | Implementation | Verification |
| --- | --- | --- |
| R1 | `src/memory/project.ts` | `npm run memory:project` |
| R2 | `src/pages/memory.astro` | Playwright smoke on `/memory` |

## Verification Plan
- `npm run memory:project`
- `npm run test`
- `npm run build`
- Manual smoke: open `/memory` and confirm private source text is absent.

## Risks
- Projection drift if seed fixtures change without validation.

## Open Questions
- Which topics should be curated first?
