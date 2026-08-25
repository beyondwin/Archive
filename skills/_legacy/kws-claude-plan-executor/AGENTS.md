# Claude Plan Executor Agent Instructions

- Preserve the thin launcher boundary: CLPE maintains the environment and
  verifies submitted facts; the child session's Superpowers owns all
  workflow semantics. Do not add task mapping, review tiers, or quality
  policy back into CLPE.
- Python standard library only; evals stay network-free and model-free.
- Run `./evals/run.sh` before claiming executor changes are complete.
- On a meaningful runtime change, bump `metadata.version` in `SKILL.md` (SemVer),
  mirror it in `README.md`, and add a `CHANGELOG.md` entry in the same commit.
  Docs-only cleanups do not need a version bump.
- The launch contract is validated against the real `claude` CLI, not only the
  fake: if you change flags, argv shape, or stream-event parsing, re-check against
  a live `claude --help` / transcript before trusting green evals (the fake can
  mask a real-CLI contract drift — see CHANGELOG 1.0.0).
