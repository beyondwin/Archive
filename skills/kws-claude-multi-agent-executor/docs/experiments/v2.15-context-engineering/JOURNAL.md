# v2.15 — Context Engineering · Journal

> Free-form running notes for the v2.15 experiment. Pair with [`spec.md`](./spec.md), [`plan.md`](./plan.md), and findings under [`findings/`](./findings/).

---

## 2026-05-16 — v2.15.0 landing

All 15 plan tasks COMPLETE under the multi-agent-executor headless chain (plan_chain[1], following v2.14 plan_chain[0]). Trigger: cross-plan boundary from v2.14 completion. Self-spawned chain handoff (`B1640C7D-20E5-40EE-AF72-C79394DCA311`).

### What landed

- **C1 (spec manifest):** Task 0–5. `scripts/build_spec_manifest.py` (stdlib markdown heading walker; 240 LOC; AC smoke verified on 4-heading fixture and the v2.15 spec itself — 32 sections). SKILL.md Phase 0 Step 3.7 (boot build), Step 6 task_to_sections compute (explicit `**Spec Refs:**` > Files-title heuristic > `["*"]` fallback). Plan Reviewer rubric (3 items). Phase 1 Step 1 prompt builder + new `{spec_section_label}` placeholder. SPEC_BLOCKER fallback (regex-matched re-dispatch with full spec under `full_spec_on_blocker`). Spec-edit branch manifest recompute (Phase 1 Step 2 substep 6.5).
- **C2 (decisions register):** Task 6–9. New per-plan `decisions_register` list, appended at Phase 1 Step 4 substep 2.3 when `key_decision` is non-empty / not `(none)` / not `n/a`. `{decisions_register}` placeholder threaded into both Implementer (right under role declaration) and Combined Reviewer (`## Project Decisions Register` with `Decision consistency (C2)` rubric). Atomic-mv projection to `<worktree>/.orchestrator/DECISIONS.md` at T3 and Phase 2 Step 1 (union across plans).
- **C3 (token-based chain trigger):** Task 10–12. Resume Chain trigger replaced with additive token+legacy logic. New top-level `state.context_budget` block (defaults 170000/0.60/102000). Three new args: `context_budget=<int>`, `context_threshold=<float>`, `manifest_fallback=<value>`. `chain_trigger_eval` telemetry emitted at every Phase Transition T3.
- **Docs:** Task 13 (4 guardrail rows), Task 14 (version bump + this journal + findings template).

### Discipline notes

- Multi-agent-executor pattern: this run alternated Implementer sub-agents and orchestrator-direct edits depending on context-budget pressure. Heavy SKILL.md edits with clear text-insertion semantics were applied directly by the orchestrator; novel-code Task 0 was dispatched to a fresh Sonnet sub-agent. Per-task method_audit and TDD waivers recorded in state.json.
- One minor verbatim/AC mismatch on Task 2 (backticks around `task_to_sections` made AC1 grep pattern fail). Orchestrator fixed the heading after the sub-agent surfaced the conflict honestly — exactly the failure-mode the receiving-code-review discipline catches.
- Compaction points triggered at tasks 5, 9, 12. Each one ran a batch-verification sweep (grep ACs on accumulated LOW tasks) + state anchor + phase-docs-skipped note (SKILL.md is canonical; no separate CHANGELOG.md to update).

### Goals — measurement status

- **G1** (≤0.50 median Implementer input-token ratio vs v2.14): not yet measured. Template at `findings/v2.14-vs-v2.15-tokens.md` awaits the first comparison run.
- **G2** (cross-task convention drift): forward-looking; needs ≥3 plans × ≥10 tasks each. Decisions register provides the mechanism; measurement is downstream.
- **G3** (no quality decline across chain handoffs): the cost ledger's chain-spanning design (v2.14) plus the manifest's per-plan resolution should preserve this; `chain_trigger_eval` events feed the post-hoc check.
- **G4** (token trigger fires before legacy on 30+ task plans): also forward-looking; `chain_trigger_eval` records the answer per run.

### Open follow-ups

- A/B fixture: pick a v2.14-already-run plan with ≥10KB spec, re-run on v2.15 head, populate findings doc.
- Plan Reviewer `{spec_manifest_json}` substitution needs an end-to-end smoke test against a plan with both a known-good and a known-bad `**Spec Refs:**` block. (Not part of plan AC — captured here.)
- Decisions register projection: confirm DECISIONS.md ends up inside the F1 tarball under the existing archive_run.sh include list (no archive_run.sh change needed; the file path is already under `.orchestrator/`).
