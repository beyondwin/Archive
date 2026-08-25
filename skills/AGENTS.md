# Skills Agent Instructions

1. Read the target skill's `SKILL.md`, README, and change protocol before
   editing that skill.
2. Catalog skills are only `korean-writing-editor` and `image-workbench`.
3. Korean proofread, correct, or polish of supplied Korean text →
   `korean-writing-editor`.
4. Project-bound raster plan, generate, edit, or audit → `image-workbench`.
5. Run, resume, inspect, explain, verify, review, or apply a Waygent
   execution → `waygent` CLI or `bun run waygent -- …`. Do not load
   `skills/_legacy/waygent`.
6. Do not load any path under `skills/_legacy/` unless the user explicitly
   names that path.
7. Keep skill docs, evals, and advertised commands synchronized.
8. Skills do not redefine Waygent product ownership.
