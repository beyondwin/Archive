---
name: kws-claude-multi-agent-executor
description: Use when you have an implementation plan and design spec to execute autonomously — Opus orchestrates, Sonnet sub-agents implement/review/verify/document. Provide plan path and spec path at invocation. NOTE — single-session execution is preferable for ≤5-task plans or plans with deep cross-task coupling (multi-agent overhead exceeds the parallelism win).
metadata:
  version: "3.0.0"
  updated_at: "2026-07-07"
---

# KWS Claude Multi-Agent Executor (v3.0 — kernel-driven)

You are the **Orchestrator** running on Opus. You execute an implementation plan
from start to finish autonomously using fresh Sonnet sub-agents. You do NOT decide
transitions, compute review tiers, count retries, append `quality_trend`, or stamp
timing. **A deterministic Python kernel owns every one of those decisions.** Your
job is to run the kernel, perform the concrete action it returns, feed the result
back, and repeat. Do not ask the user for approval between tasks.

> **v3.0 is a cutover.** The prose transition-decision logic, `<active>`-substitution
> bookkeeping, retry accounting, and quality-trend appends that earlier versions
> carried in this document are **gone** — they moved into `scripts/kernel/`. If you
> find yourself "deciding what to do next" from prose, STOP: that is the kernel's
> job. Run `kernel.py next` and do exactly what it says.

The kernel CLI is `scripts/kernel/kernel.py` with subcommands:
`init` · `next` · `submit` · `check-stop` · `finalize` · `inspect` · `resolve-escalation`.
Every invocation prints a single JSON object to stdout. Exit code `3` = error
(hard halt), exit code `2` = halt/stop-blocked, exit code `0` = normal.

---

## ① Path conventions

**All persistent state lives under `$HOME/.claude/`, NOT inside the source repo.**
The kernel derives one `RUN_ID` per run and pairs two sibling directories by it:

| Placeholder | Resolved path | Contains |
|-------------|---------------|----------|
| `<worktree>` (`state.worktree`) | `$HOME/.claude/worktrees/<RUN_ID>/` | The git worktree — code, `.git`, and `<worktree>/.claude/settings.json` (the four safety hooks). Nothing else this skill adds. |
| `<orch_dir>` (`state.orchestrator_dir`) | `$HOME/.claude/orchestrator/<RUN_ID>/` | All orchestrator state — `state.json`, `hooks/`, `packets/`, `prompts/`, `results/`, `events.jsonl`. |

`RUN_ID` = `<plan-slug>-<YYYYMMDD-HHMMSS>`, derived ONCE by `kernel.py init` and
persisted into `state.worktree` / `state.orchestrator_dir`. Every downstream step
reads those fields — never re-derive paths. The worktree and orchestrator-state
directory are **siblings, NOT nested**.

`$HOME` MUST be an absolute path everywhere. The kernel writes absolute paths into
state.json and into the hook command strings; never write a literal `~`.

---

## ② Invocation contract

**At invocation the user provides** (as a single args string):
- `plan=<path>` — required. Multi-plan: `plan2=`, `plan3=`, … with matching `spec2=`, …
- `spec=<path>` — required for the primary plan.
- Optional: `risk=<low|mid|high>`, `implementer_model=<opus|sonnet>` (default sonnet),
  `parallel=off`, `mode=<...>`, `docs_scope=<...>`. Natural-language tokens (`opus`,
  `순차`/`sequential`, `대화형`/`interactive`) are also parsed. Explicit `key=value` wins.

**Step 1 — init.** Run:

```bash
python3 <skill_dir>/scripts/kernel/kernel.py init --args "<the user's args string>" --repo-root "<source repo root>"
```

`init` performs the dirty-tree check (`git status --porcelain` — uncommitted changes
→ `{"halt":"dirty_worktree"}`, exit 2, do NOT proceed), derives `RUN_ID`, creates the
worktree + branch, materializes the four worktree hooks, creates `<orch_dir>`
subdirs, and writes an initial `state.json` (schema_version 3, `status:"SETUP"`).
It returns `{"run_id", "state_path", "worktree", "orchestrator_dir", "echo_line"}`.
Print `echo_line` to the user immediately — it is their one chance to catch a
mis-parsed arg. Any `{"halt":...}` return (dirty_worktree / worktree_add_failed /
hooks_materialization_failed) is a **hard halt** — report and stop.

**Step 1.5 — SETUP (plan → state assembly). REQUIRED before the first `next`.**
`init` writes an EMPTY `tasks` / `execution_plan` / `risk_levels` / `compaction_points`
/ `spec_manifest`. `kernel.py next` on that empty state returns
`{"action":"halt","reason":"no_dispatchable_task"}`. There is deliberately **no
`kernel.py setup` subcommand** — the plan→state assembly is performed by the
orchestrator following **`references/phases/phase-0-setup.md`**, which drives the
kernel library modules (all under `scripts/kernel/`, importable, no CLI):

- `planparse.parse(plan_text)` → tasks list (id, title, files, body, acceptance) +
  structural-validation errors (missing Files block, out-of-repo path → halt to user).
- `gate.assign_risk(tasks, override)` → `risk_levels` per task.
- `gate.partition_waves(tasks, risk, parallel)` → `execution_plan` as **`list[list[str]]`**
  (the exact shape `decide()` iterates — a `list[dict]` silently breaks dispatch).
- `packets.build_packet(task, manifest, spec_text, budget_chars)` → write one packet
  per task to `<orch_dir>/packets/<task_id>.json` (dispatch reads these for context).
- `gate.preflight(task, packet, state)` — the **single source of dispatch decisions**
  per task (see the delegate/block seams in ④). Never bypass it.
- Take the baseline (`run_command` purpose baseline, ⑤), assign `compaction_points`,
  write `spec_manifest`, set `status:"RUNNING"`, and persist all of the above into
  `state.json`.

Read `phase-0-setup.md` and follow it to completion, then proceed to ③. This SETUP
step is a real contract boundary: the kernel cannot dispatch a task that SETUP did
not write into `state.execution_plan` + `state.tasks`.

---

## ③ Execution cycle: `next → perform action → submit`

This is the entire loop. Repeat until `finalize` returns `status:"finalized"`.

```
loop:
  action = python3 kernel.py next --state <state_path>     # kernel decides
  perform the action exactly as the §④ table dictates       # you perform it
  if action was a dispatch:
      python3 kernel.py submit --state <state_path> --task <id> --role <role> --result <result_path>
  # go back to loop
```

**The kernel decides; you perform.** `next` returns the next action AND (for a
dispatch) all materials needed to perform it. You never choose the action, the role,
the retry count, or whether a task passed — those are in the returned JSON.

**Loop exit — read this carefully.** `decide()` does NOT emit a `done` action, and
after finalize it does NOT stop returning `finalize` (it does not check
`status==FINALIZED`). Therefore:
- The loop ends when **`kernel.py finalize` returns `{"status":"finalized", ...}`**.
- Do NOT wait for a `done` action — it never comes; waiting spins `finalize` forever.
- Do NOT re-run `next` after a successful `finalize`; it would re-emit `finalize`.

**Polite-stop is forbidden (see ⑥).** A sub-agent PASS, a `submit` `accepted:true`,
a `next_hint` — none is a reporting moment. Proceed to the next loop iteration in the
same turn.

### Performing a `dispatch`

`next` returns, alongside `action/role/task_id/attempt`, the dispatch materials from
`dispatch.build`: `prompt_path`, `schema_path`, `result_path`, `transport`, `model`,
`cwd`, and either `command` (transport `"p"`) or `agent_instruction` (transport
`"agent"`).

- **transport `"p"`** — run the returned `command` verbatim (it is a
  `claude -p … --json-schema … > <result_path>` string, already shlex-quoted). Run it
  with cwd = the returned `cwd` (the worktree).
- **transport `"agent"`** — dispatch a fresh sub-agent via the Agent tool using
  `agent_instruction` (read the prompt at `prompt_path`, do the work, write structured
  JSON to `result_path`), passing the returned `model`. For `opus` you MUST set the
  model parameter explicitly; `sonnet` may omit it.

Read the role prompt template only at dispatch time — the kernel has already written
the fully-substituted prompt to `prompt_path`, so you dispatch that file, you do not
re-assemble it. After the sub-agent writes `result_path`, call `submit`.

`next` also auto-stamps `timing.started` (set-if-absent) and persists state — you do
NOT stamp timing yourself.

### Submitting a result

```bash
python3 kernel.py submit --state <state_path> --task <task_id> --role <role> --result <result_path>
```

`submit` reads the result file, extracts the payload+usage, validates against the
role schema, folds the result into state (tier computed BY THE KERNEL from
spec_score/quality_score — never trust the sub-agent's self-reported status), records
cost, stamps `timing.completed` on terminal transition, emits a `task_progress`
event, and returns one of the shapes in §④. Handle its return per the table, then
loop back to `next`.

---

## ④ Action-handling table — CODE-VERIFIED

Every action below is verified against `scripts/kernel/transitions.py::decide` and
`scripts/kernel/kernel.py` handlers. Handle EACH exactly as stated. An action the
kernel emits that you mishandle is a runtime break the kernel tests cannot catch
(SKILL.md is prose the tests do not read).

### `kernel.py next` → `decide()` actions

| Action JSON | How to perform it | Kernel source |
|-------------|-------------------|---------------|
| `{"action":"dispatch","role","task_id","attempt", …materials}` (normal per-task) | Run the returned `command` (transport `p`) or Agent-tool dispatch via `agent_instruction` (transport `agent`); write result to `result_path`; then `submit`. | `transitions.py:236-241` (dispatch); `kernel.py:90-111` (materials merge); `dispatch.py:401-491` |
| `{"action":"dispatch","role":"verifier","batch":true,"task_ids":[…],"task_id":<first>,"attempt":1}` (LOW batch-verify sweep before finalize) | Dispatch the verifier over the whole `task_ids` batch (LOW tasks accumulated as PENDING_BATCH); write result to `result_path`; then `submit` with `--role verifier --task <first task_id>`. Fires when all tasks terminal AND ≥1 PENDING_BATCH remains. | `transitions.py:196-212` |
| `{"action":"run_command","purpose":"reset","command":"git reset --hard <sha>","task_id"}` | Run the git reset (restores pre-task SHA before re-dispatching a verifier-FAILed task), then loop back to `next`. The `PreToolUse` hook does NOT block `git reset --hard`. **`reset` is the only `run_command` purpose `decide()` emits.** | `transitions.py:222-230` |
| `{"action":"compact","steps":["batch_verifier","docs_updater","anchor"]}` | Perform context compaction in the given step order (batch-verify accumulated LOW tasks → update phase docs → drop raw task context, anchor on state.json), then loop back to `next`. Fires only when `last_completed_task` is a `compaction_points` entry not yet compacted. **NOTE:** `compaction_points` has no kernel producer — this action never fires unless SETUP (②) wrote `compaction_points` into state. | `transitions.py:188-192` |
| `{"action":"escalate_to_user","reason","questions":[…]}` | Batch the `questions` to the user and wait for their answer. This is the channel for: spec-clarification budget exhaustion, repeated ENV_BLOCKER, AND gate operator-review of a blocking executability issue (a trust/risk `block` from `gate.preflight`, per D001). After the user answers, **clear the escalation THROUGH THE KERNEL** — run `python3 kernel.py resolve-escalation --state <state_path> --answer "<the user's answer>"`. That is the ONLY sanctioned way to unblock this loop: `decide()` returns `escalate_to_user` while `pending_escalation` is truthy and clears it for nothing (the ENV_BLOCKER task is non-terminal, so it re-escalates forever otherwise). `resolve-escalation` clears the flag, records the answer to `escalations_resolved` + `decisions_register` (audit), and writes via the single-writer atomic path. **Never hand-edit `state.json`** to clear it. Then apply any spec/plan clarification and loop back to `next`. | `transitions.py:178-184` (producer branches `:328-338` spec-fault / `:489-500` ENV_BLOCKER); resolver `kernel.py::handle_resolve_escalation` |
| `{"action":"finalize"}` | Run `kernel.py finalize` (see below). Fires when all tasks terminal AND zero PENDING_BATCH. | `transitions.py:213-214` |
| `{"action":"halt","reason":"no_dispatchable_task"}` | **Hard halt.** Emitted when no task is dispatchable but not all are terminal — a state inconsistency (usually SETUP did not populate `execution_plan`). Report the reason and stop. No prose fallback (⑤). | `transitions.py:218-220` |
| `{"action":"done"}` | **Never emitted.** Listed in the decide() docstring but no `return` produces it, and `decide()` does not gate on `status==FINALIZED`. Do NOT wait for it. Loop exit is `finalize` returning `status:finalized` (③). | `transitions.py:167` (docstring only — no return) |

### `kernel.py submit` responses

| Response JSON | How to handle it | Kernel source |
|---------------|------------------|---------------|
| `{"accepted":false,"violations":[…],"retry_hint":…}` | Schema violation. Re-dispatch per `retry_hint` (fix the flagged fields), then `submit` again. `submit` exits 0 — this is not an error. | `kernel.py:164-185` |
| `{"accepted":false,"violations":[…],"retry_hint":…,"halt_pending":true}` | Same as above BUT 3 consecutive schema violations for this task have accumulated — a hard halt is imminent on the next violation. Fix the sub-agent's output contract; do not blindly re-dispatch. | `kernel.py:183-184` (`sv >= 3`) |
| `{"accepted":true,"next_hint":<action>}` | Proceed. `next_hint` is a PREVIEW of `decide()`'s next action (advisory only — the authoritative call is the next `kernel.py next`). Loop back to `next` in the same turn (no polite stop). | `kernel.py:224-229` |
| `{"error":"cannot_read_result_file: …"}` / `{"error":"ledger_parse_error: …"}` / `{"error":"cannot_read_schema: …"}` | **Hard halt** (exit 3). The result file is missing/unreadable, the `claude -p` envelope is unparseable, or the role schema is missing. Report and stop — no prose fallback (⑤). | `kernel.py:146,152,160,481-482` |

### `kernel.py check-stop` signals (Stop hook — see ④ below the table)

| Response JSON | Exit | Meaning / next action | Kernel source |
|---------------|------|-----------------------|---------------|
| `{"halt":"all_tasks_terminal_finalize_pending","reason","next_action":"run kernel.py finalize"}` | 2 (BLOCK stop) | All tasks terminal, zero PENDING_BATCH, not finalized → run `kernel.py finalize`. | `kernel.py:288-295` |
| `{"halt":"batch_drain_pending","reason","next_action":"run kernel.py next to dispatch the batch verifier, then finalize"}` | 2 (BLOCK stop) | ≥1 PENDING_BATCH lingers → run `kernel.py next` (dispatches the batch verifier), submit it, THEN finalize. Allowing the stop here ships LOW tasks UNVERIFIED — the wedge invariant. | `kernel.py:278-286` |
| `{"check_stop":"already_finalized","stop":false}` | 0 (ALLOW) | `status==FINALIZED` — nothing to block. | `kernel.py:260-261` |
| `{"check_stop":"not_ready","stop":false}` | 0 (ALLOW) | Tasks still in progress — a different loop drives them; the Stop hook does not block a mid-run pause. | `kernel.py:297` |

### `kernel.py finalize`

Run when `next` returns `finalize`, or when `check-stop` blocks with a finalize-pending
halt. `finalize` runs `drift.check` (blocking drift → `{"error":"finalize_refused_blocking_drift", …}`,
exit 3 — resolve the drift, do not force), a non-blocking method-audit checklist, stamps
`timestamps.completed_at`, builds `run_quality` + `completion_audit`, sets
`status:"FINALIZED"`, emits `phase_2_complete`, and returns
`{"status":"finalized","grade","completion_passed","method_audit_warnings"}`. **This
return is the loop-exit signal.** Report the run summary (grade, worktree location,
any gaps) to the user. Never auto-delete the worktree.

---

## ④·b Guardrails — what the KERNEL enforces vs what YOU observe

These are absolute. The left column is enforced deterministically by the kernel or
the worktree hooks — you cannot bypass or re-decide them. The right column is your
responsibility as orchestrator.

| Enforced BY THE KERNEL / hooks (do not re-implement in prose) | Observed BY YOU (the orchestrator) |
|---|---|
| Review tier computed from spec_score/quality_score (SPEC 0.85 / QUALITY 0.75 / WARN 0.70·0.60). LLM self-status is advisory only. (`transitions._compute_review_tier`) | Perform each returned action verbatim; never substitute your own judgment for `decide()`. |
| Max 3 review retries, 3 verifier retries, 3 escalations, 3 spec-clarifications per task; exhaustion → SKIPPED + `verification_gaps` (retries) or `escalate_to_user` (escalation/spec-fault). (`transitions.apply_result`) | Run `kernel.py init` from a clean tree only. `dirty_worktree` halt = stop. |
| `git reset --hard <pre_task_sha>` directive before verifier re-dispatch, emitted as `run_command purpose=reset`. (`transitions.py:222-230`) | The orchestrator never writes code. All implementation goes through sub-agents. |
| LOW tasks → PENDING_BATCH → drained by the batch-verify dispatch before finalize; lingering PENDING_BATCH blocks the Stop hook. (`transitions.py`, `kernel.py check-stop`) | Read the role prompt template only at dispatch time (the kernel already wrote `prompt_path`); dispatch that file. |
| `quality_trend` appended (rolling max 10) SOLELY by `transitions.apply_result` on verifier PASS. **Never append it by hand — the v2 `phase_boundary.py` writer is deleted in v3.** | Maintain any run-level escalation VIEW you need for reporting; the kernel tracks per-task `task.escalations` (run-level counter is the orchestrator's if it needs one). |
| `timing.started` (set-if-absent at `next`) and `timing.completed` (at `submit` on terminal) stamped by the kernel. | Verify each `state.json` write implicitly via the kernel's exit code; a kernel exit 3 or a write failure = hard halt (⑤). |
| Cost/usage recorded per dispatch into `cost_ledger` by `ledger.record` inside `submit`. No manual `accumulate_cost` call. | `escalate_to_user` → actually batch the questions to the user and wait; do not guess an answer. |
| Four worktree safety hooks (PreToolUse dangerous-cmd, PostToolUse debug-artifact, SubagentStop implementer-structure, Stop = `kernel.py check-stop`). (`materialize_worktree_hooks.py`) | Never auto-delete the worktree; report its path and let the user decide to merge. |
| `gate.preflight` is the single source of per-task dispatch decisions (delegate_serial / delegate_parallel / block). | Never bypass `gate.preflight` for any task. |

---

## ⑤ Hard-halt rules — NO prose fallback

When the kernel signals a hard failure, you STOP and report. You do **not** improvise
a prose workaround around a kernel error — that reintroduces exactly the silent-green
class the kernel exists to eliminate.

- **kernel.py exit 3 / any `{"error":…}` return** (`cannot_read_result_file`,
  `ledger_parse_error`, `cannot_read_schema`, `finalize_refused_blocking_drift`,
  `unknown_command`) → hard halt. Report the error verbatim and stop.
- **`{"halt":…}` from `init`** (dirty_worktree, worktree_add_failed,
  hooks_materialization_failed) or **`{"action":"halt",…}` from `next`**
  (no_dispatchable_task) → hard halt. Report and stop.
- **State-write failure** — the kernel owns every state.json write; if a kernel
  subcommand exits non-zero for an I/O reason, treat it as a hard halt. **The LLM
  NEVER writes `state.json` directly — the kernel is the sole state writer, via
  `init` / `next` / `submit` / `finalize` / `resolve-escalation`.** There is no
  sanctioned hand-edit, not even to clear a `pending_escalation` (use
  `resolve-escalation`, ④). Hand-editing state.json to "recover" is forbidden.
- **`submit` `halt_pending:true`** is a warning, not yet a halt — fix the sub-agent's
  output contract before the next (fatal) violation.

A hard halt is a legitimate reporting moment (⑥). Nothing else is, until the run
finalizes.

---

## ⑥ Polite-stop-prohibition invariant

**A sub-agent returning PASS / APPROVED, a `submit` `accepted:true`, or a `next_hint`
is a checkpoint inside the autonomous loop — NEVER a reporting moment.** The
orchestrator MUST proceed immediately to the next loop iteration (`kernel.py next`) in
the same turn.

The ONLY legitimate moments to stop and report to the user are:
1. `kernel.py finalize` returned `{"status":"finalized"}` (run complete).
2. An `escalate_to_user` action (batched questions the user must answer).
3. A hard halt (⑤) — kernel error, init/next halt, or refused-drift finalize.
4. A worktree hook denial the sub-agent cannot self-resolve.

Any behavior that "summarizes and waits for user acknowledgment" between a PASS and the
next kernel call IS the regression this invariant exists to prevent.

---

## Forward-wired seams (state honestly)

- **`run_command purpose="reset"`** — wired; the only `run_command` purpose `decide()`
  emits (④). `baseline` runs at SETUP (②); `acceptance` runs INSIDE the verifier
  dispatch (the verifier prompt runs the task's `## Acceptance Criteria` shell) — neither
  is a `decide()` action.
- **`delegate_parallel`** — a `gate.preflight` RETURN consumed at SETUP/wave-launch, NOT
  a `decide()` action. When a parallel wave (an `execution_plan` group of size ≥ 2) is
  cleared for parallel dispatch, the orchestrator launches the group's `claude -p` (or
  Agent) dispatches as a parallel wave, then submits each result. The kernel cycle is
  otherwise sequential. (`gate.py`; D001 open-question T15.)
- **operator-review of a blocking executability issue** — a trust/risk `block` from
  `gate.preflight` (risk_markers, un-reviewed spec fallback) surfaces via
  `escalate_to_user` (④). There is NO full-context orchestrator-implements fallback in
  CME (D001).
- **`serialization_reason` is NOT wired.** `gate.partition_waves` returns a bare
  `list[list[str]]` with no wave metadata; no step writes `serialization_reason` into
  state; `preflight`'s `serialization_reason` branch is dead code. Same-wave contention
  (file overlap / shared `resource_key` / `serial:true`) falls through to `preflight`'s
  DEFAULT `delegate_serial` — the conservative floor. Do NOT claim `serialization_reason`
  is produced. (D001.)
- **batch-verify dispatch + `check-stop batch_drain_pending`** — both wired (④): LOW
  PENDING_BATCH tasks are drained by a kernel-returned batch-verify dispatch before
  finalize, and the Stop hook blocks a stop while any PENDING_BATCH lingers.

---

## Sub-agent prompt templates & references

The kernel writes the fully-substituted prompt to `<orch_dir>/prompts/…` at dispatch
time — you dispatch that file, you do not assemble it. The source templates live in
`references/` (`implementer-prompt.md`, `reviewer-prompt.md`, `verifier-prompt.md`,
`docs-updater-prompts.md`, `plan-reviewer-prompt.md`), with cache scaffolds in
`references/_scaffolds/` and result schemas in `references/_schemas/`. All sub-agent
prompts bootstrap `Skill("superpowers:using-superpowers")` first; implementers
additionally invoke `Skill("superpowers:test-driven-development")` for executable work
and report RED/GREEN evidence.

Cross-cutting detail lives in `references/cross-cutting/` (state-schema, agentlens
emit-sites, safety-hooks, agent-dispatch). Phase docs in `references/phases/` are the
"how to perform kernel-returned actions" guides — `phase-0-setup.md` is the SETUP
assembler (②), the rest are mechanics references; the kernel owns all transition
decisions.
