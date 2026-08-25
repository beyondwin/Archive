# Escalation Protocol — v3.0 (kernel-owned)

> **v3.0 cutover.** The escalation DECISION (which signal escalates, when a budget is
> exhausted, whether a task is SKIPPED vs the run halts) is owned by the kernel.
> `transitions.apply_result` counts `task.escalations` / `spec_clarifications` and,
> on budget exhaustion, sets `state.pending_escalation`; `transitions.decide` then
> returns `{"action":"escalate_to_user","reason","questions":[…]}`.

**How to perform an `escalate_to_user` action** (per `SKILL.md §④`): batch the
`questions` to the user and WAIT for their answer — this is one of the four legitimate
reporting moments (`SKILL.md §⑥`). Do not guess an answer. After the user responds,
resolve the state (clear `pending_escalation` / apply the clarification) and loop back
to `kernel.py next`.

**What routes to `escalate_to_user`:**

| Source | Kernel producer |
|--------|-----------------|
| Spec-clarification budget exhausted (`spec_contradicts`/`unclear` > 3) | `transitions.py` `_apply_reviewer` → `pending_escalation` + task SKIPPED |
| Repeated ENV_BLOCKER (same `root_signature` twice) | `transitions.py` `_apply_verifier` recovery path → `pending_escalation` |
| Gate operator-review of a blocking executability issue (risk_markers, un-reviewed spec fallback) | `gate.preflight` trust/risk `block` (D001) — surfaced by the orchestrator via `escalate_to_user` |

There is **no full-context "orchestrator implements it" fallback** in CME — a trust/risk
block escalates to the human (D001). Per-task retry/verifier budget exhaustion does NOT
escalate; the kernel SKIPs the task and records `verification_gaps`, and the run
continues.

ENV_BLOCKER triage detail: [`../escalation-playbook.md`](../escalation-playbook.md).
