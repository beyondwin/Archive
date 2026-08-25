# JOURNAL — v2.30 failure-taxonomy coverage

Chronological log. Updated as work proceeded.

---

## 2026-06-08

### Kickoff — scope confirmation

Design docs (`docs/improvements/품질개선-v2.30-{플랜,구현}-ko.md`) already authored:
a J1–J9 roadmap across three axes (D eval-coverage, E data-driven shelf-revisit,
F new orchestrator behavior). The docs are *design proposals*, not a CME-executable
task plan (no `### Task N:` headers), so running the multi-agent executor on them
verbatim would halt at Phase 0 Step 0.5.

User decision (asked before any execution):

- **Execution = single-session, in-session (Opus).** No worktree / sub-agent
  fan-out. Rationale: plan §3.1 explicitly forbids fan-out ("v2.30 은 병렬성을
  늘리지 않는다") and the user prefers manual per-terminal dispatch. The work
  (P0 = eval docs + 2 fixtures + judge edit) is low-risk and orthogonal to SKILL.md.
- **Depth = P0 (J1–J4) full; P1/P2 (J5–J9) design records only.**

### Baseline (deterministic, pre-change)

All green per plan §6.1:
`check_skill_contract.py` failures:[] · `check_doc_freshness.py` failures:[] ·
`pytest scripts/` 280 passed · `git diff --check` clean.

### J1 — MAST coverage matrix

Wrote `docs/eval-coverage-mast.md` (14-mode / 3-category table, fixture↔FM mapping
for 01–10, gap list + revisit triggers, update protocol). Added a `mast_coverage:`
annotation to fixtures 01–08 (09/10 carry it natively). Updated `evals/README.md`
fixture list (was 01–07, missing 08) → 01–10 + link to the coverage doc. See D001.

### J2/J3 — probe fixtures, harness-contract pivot

**Pivot from the spec YAML.** The spec's illustrative fixture YAML did not match the
real harness contract in three ways, discovered by reading `evals/rubric.py` +
`evals/run.sh` before writing:

1. `rubric.py` reads `valid_inputs` + `error_cases` as lists of `{check:, desc:}`
   **dicts** — the spec's `happy_path:` + plain-string shape would crash it.
2. `run.sh` runs `git init` + bootstrap + `git commit "eval bootstrap"` itself; the
   spec's bootstrap (which re-ran git init/config/commit) would double-init.
3. `bootstrap` must be a `|` block string (existing fixtures), not a YAML list.

Adapted both fixtures to the real contract (D002). Also corrected an arithmetic
error: I initially picked `to_cents(2.675)` as a discriminating boundary, but
`round(2.675*100)==268` (the float lands at/above 267.5) — it does NOT discriminate
naive-round from correct. Replaced with `2.005` (→201), which discriminates both
naive-round and int-truncation defects. Verified numerically before committing.

### F01 — probe validity (deterministic, $0)

Seeded good vs broken impls and ran the real `rubric.py`:

- 09 broken (no range check): error 0/2, rate 0.6 → probe catches rubber-stamp.
- 09 good: valid 3/3, error 2/2, rate 1.0.
- 10 broken (naive round, propagating): valid 2/3, error 0/2, rate 0.4 → catches propagation.
- 10 good (Decimal half-up): valid 3/3, error 2/2, rate 1.0.

Both probes discriminate (delta 0.4 / 0.6). This is the §5 top-risk mitigation
("probe is inert") done deterministically. See findings/F01.

### J4 — judge bias guards

Added a **Bias guards** section to `evals/judge.md` before "Score each axis",
scoped to the subjective `code_quality` axis only (verbosity ≠ quality, no position
bias, no self-preference). Deterministic axes (correctness/spec_compliance) left
mechanical and explicitly excluded. Added a regression note to
`evals/calibration/README.md` (good/broken Δ≥0.2 must hold after the edit). See D003.

### P1/P2 — design records

J5/J7/J8 recorded at design level (D004/D006/D007) with start conditions; J6/J9
recorded as deferred (D005/D008). No code for any P1/P2 item this round, per the
user's depth decision.

### Verification

Re-ran the full deterministic suite green (see F01 / close section). NOT bumping
SKILL.md version — the paid eval (1-rep pilot → n=4 SHIP) and version bump remain
the SHIP step, which a single in-session run cannot perform.

---

### Close-out (2026-06-08)

Re-scoped the "remaining risks" against the orthogonality fact: P0 (J1–J4) changes
**no SKILL.md runtime behavior**, so the paid pipeline eval — which certifies
*pipeline* behavior — is not a P0 ship gate. It is the gate for the J7/J8
behavioral round (D006/D007), where prompts actually change. The §5 top risk
("probe is inert") is closed deterministically by F01. So the residual paid eval +
full LLM calibration re-run are carried forward as a manual step for that round
(per the no-fan-out / single-session decision), not run here.

User decisions (2026-06-08): **no version bump** (`metadata.version` stays 2.29.0;
eval-layer is orthogonal — recorded under HISTORY §3 + F02, not a §1 timeline
release) and **main fast-forward** (commit P0 on this branch, ff main to HEAD —
brings v2.29.0 + v2.30 P0; no push).

Wrote F02-close-out (ship recommendation). Updated experiment README → CLOSED —
P0 SHIPPED, `docs/experiments/README.md` index, and HISTORY §3. Re-verified the
full deterministic suite green before committing. No CHANGELOG (the project uses
HISTORY + snapshots; no snapshot since no version bump).

**Outcome: P0 SHIPPED; behavioral round (J7/J8) reopen-on-demand.**
