# JOURNAL — v2.25 Subscription-pool agent dispatch

Chronological log. Update **as you go**, not at the end.

---

## 2026-06-04

### Kickoff — billing concern with `-p`

User asked for a better way than `claude -p` dispatch because its billing
structure is changing. Established the core fact: both `-p` and the v2.22 `api`
default are **metered** (off-subscription). The only subscription-pool path is
the in-session Agent tool (already used by Implementer/Reviewer).

### Option exploration

- Option 1 (manual per-terminal) — fully subscription but abandons autonomy.
- Option 2 (in-session Agent dispatch for the headless roles) — keeps autonomy
  + subscription. User rejected manual hand-off; chose Option 2.

### Design decisions (via brainstorming, one at a time)

- **Default flip → `"agent"`** for all role gates (D001). Bare invocation =
  fully subscription.
- **detach conflict** (D002): agent-default gates fall back to `"api"` under
  `detach=true`; explicit-agent gates warn + proceed.
- **Plan Reviewer → Opus** — user override of the mechanical-rubric Haiku
  default. Recorded to auto-memory (Opus-everywhere stance for this executor).
- **Autonomous error handling** (D003): recoverable errors never prompt the
  user — retry → api fallback → best-effort continue with recorded gap.
  Escalation autonomy extended to runtime AMBIGUITY/SPEC_BLOCKER (best-judgment
  interpretation, no SKIP). Hard-halt retained only for data-integrity failures
  and Phase 0 pre-flight structural/config errors.

### Architecture note

The `"agent"` path cannot be a helper script (a script can't invoke the Agent
tool). It is a prose dispatch pattern in the phase files, reusing the existing
`-p` role prompts and the result-file seam (sub-agent writes
`{result_json_path}`; downstream reads + schema-validates unchanged).

### Next

Design doc written to this experiment README. Pending: user review of the
written spec, then superpowers:writing-plans to produce the implementation plan.

---

## On close-out

(to be written at close-out: outcome, what shipped, what didn't, what was learned)
