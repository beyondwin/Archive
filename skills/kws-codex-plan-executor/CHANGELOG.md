# Changelog

## 3.0.0 - 2026-07-25

- Releases the format-5 state and public-contract-3 thin boundary for one
  local execution contract.
- Keeps the public command surface to `run`, `resume`, and `inspect`; repeated
  `--document` inputs remain opaque and preserve caller order.
- Resumes in the saved session first and permits only one fresh fallback when
  that saved session is unavailable.
- Makes `handed_off` a mechanical local handoff only; Superpowers owns
  engineering completion, and CPE has no remote or verification authority.
- Keeps recognized legacy roots read-only, defaults `run` to `workspace-write`,
  and requires explicit immutable opt-in for `danger-full-access`.
- Keeps deterministic offline gates separate from explicitly opt-in live
  provider canaries.
- Reconciles a strictly validated orphan handoff under the run lock before any
  resumed controller launch after parent interruption.
