# Claude Plan Executor Agent Instructions

- Preserve the thin launcher boundary: CLPE maintains the environment and
  verifies submitted facts; the child session's Superpowers owns all
  workflow semantics. Do not add task mapping, review tiers, or quality
  policy back into CLPE.
- Python standard library only; evals stay network-free and model-free.
- Run `./evals/run.sh` before claiming executor changes are complete.
