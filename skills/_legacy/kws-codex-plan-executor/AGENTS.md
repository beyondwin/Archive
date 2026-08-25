# Codex Plan Executor Agent Instructions

- Preserve the strict-thin sequential wrapper and Python standard-library runtime.
- One v3 run is one execution contract; repeated documents stay opaque and ordered.
- Approved Superpowers documents and the selected installed skill own all workflow meaning.
- Do not migrate this executor into Bun/Waygent or add task-mapping policy.
- Keep `run`, `resume`, and read-only `inspect` as the complete public command surface.
- Preserve `workspace-write` by default, one same-session attempt before one fresh
  fallback, read-only legacy roots, local-only `handed_off`, and
  `integration=not_observed`.
- Keep live provider canaries explicitly opt-in and outside the offline gate.
- Run `./evals/run.sh` before claiming executor changes are complete.
