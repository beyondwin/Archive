# Cross-cutting: `"agent"` dispatch transport (v2.25)

A third value for every `state.dispatch_config` role gate, alongside `"p"`
(headless `claude -p`) and `"api"` (`scripts/dispatch_via_api.py`). `"agent"`
dispatches the role **in-session via the Agent tool** — the same transport the
Implementer and Combined Reviewer already use (Phase 1 Steps 1–2) — so the
dispatch bills against the **subscription pool**, not metered API credits.

`"agent"` is the **default** for all role gates (v2.25). See D001.

## Why this is prose, not a script

The `-p`/`api` transports are script-driven. `"agent"` is fundamentally an
**inline Agent-tool call the orchestrator model makes itself** — a script cannot
invoke the Agent tool. There is therefore no `dispatch_via_agent.py`; this file
is the procedure the orchestrator follows directly.

## The dispatch procedure

When a role gate resolves to `"agent"`, dispatch that role as follows. The
caller supplies `ROLE`, `MODEL`, `PROMPT_TEMPLATE`, and `RESULT_PATH`.

1. **Build the prompt** from the SAME template the `-p` path uses for `ROLE`,
   with `{result_json_path}` set to `RESULT_PATH` and all other placeholders
   filled exactly as the `-p` path fills them. Do NOT author a new prompt body.
2. **Dispatch via the Agent tool** with `model: MODEL` and the built prompt as a
   fresh sub-agent. Models by role:
   - Verifier → `sonnet`
   - Docs Updater → `sonnet`
   - Plan Reviewer → `opus` (matches the `dispatch_plan_reviewer.py` default;
     honor `state.dispatch_config.plan_reviewer_model` if set)
3. **The sub-agent writes its structured result JSON to `RESULT_PATH`** (its
   prompt already instructs this) and returns. The caller does NOT parse the
   returned message for the result.
4. **Read + schema-validate `RESULT_PATH`** exactly as the `-p`/`api` path does
   for `ROLE` (`verifier_result.schema.json`, `docs_updater_result.schema.json`,
   or the `report_plan_reviewer` shape). Downstream consumption is unchanged.
5. **Cost on the agent path is NOT observable (v2.28, D001).** The Agent tool
   returns only the sub-agent's final message to this turn — there is **no
   `usage` object** the orchestrator can read. Per-dispatch cost is therefore
   **not observable** on the `"agent"` transport; this is why an attached,
   all-`agent` run sets `cost_tracking_waived` at Phase 0 (D001). Only the
   `"api"` / `"p"` transports surface usage (from the `dispatch_via_api.py`
   return / the `stream-json` result line); those gates accumulate via
   `scripts/accumulate_cost.py --role ROLE --model MODEL ...` (normalize per
   Phase 1 Step 4 substep 1.5). To get cost + budget enforcement, opt a gate
   into `"api"` or `"p"`.

   **Honest limitation of the agent default:** auto-waiving cost also disables
   `budget_cap_usd` enforcement and the token-based chain-resume trigger on the
   default path, because both read the now-empty ledger. This is the accepted
   cost of the agent-pool default; users who need budget enforcement opt a gate
   into `"api"`/`"p"`.

For the **combined transition** (`transition_combined`), a SINGLE Agent
sub-agent runs the `-p` combined prompt and writes the combined
`{verify, docs}` JSON to its result path. Do NOT split into two dispatches.

## Failure ladder (autonomous — never prompt the user). See D003.

1. **Result file missing or fails schema validation → retry once** (re-dispatch
   the same `ROLE` as a fresh Agent sub-agent).
2. **Still failing → auto-fallback to `"api"` for this one dispatch.** Run the
   role's `scripts/dispatch_via_api.py` path, log it, and emit
   `kws-cme.dispatch_fallback` (best-effort, `2>/dev/null || true`). This is the
   ONLY sanctioned automatic transport fallback, and only `agent → api`, only
   after the retry.
3. **`api` also fails** (after its own retry budget → ENV_BLOCKER):
   - **Plan Reviewer (advisory):** log a warning and proceed (existing "absence
     is not a halt" policy).
   - **Verifier / Docs (load-bearing):** write a gap marker into state —
     `<active>.verification_gaps += [{task, reason, ts}]` (Verifier) or
     `<active>.docs_gaps += [{scope, reason, ts}]` (Docs) — emit
     `kws-cme.blocker`, then **continue the run**. The Final Summary Report
     (Phase 2 Step 2) MUST render these gaps in a dedicated row. Never silent,
     never halt, never prompt.

## detach interaction. See D002.

`"agent"` reaches the subscription pool ONLY when the orchestrator runs
attached. Under `detach=true` the orchestrator is a `claude -p` process and its
Agent sub-agents bill against that metered parent. Phase -1 resolves this before
dispatch (see `references/phases/phase-minus-1-args-and-spawn.md`):
- `detach=true` + gate at the agent **default** → that gate falls back to
  `"api"` (one-line warning).
- `detach=true` + gate **explicitly** `"agent"` → warn + proceed.
