# Executor Instrumentation Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five instrumentation-integrity gaps the three post-v2.27 attached-mode runs exposed: make cost auto-waive honestly on the agent path, force finalization when every task is terminal, FAIL on physically-impossible timing, move `quality_score` into the unskippable boundary write + surface dark telemetry, and flag non-canonical task keys. Lock all of it with tests built from the three real 2026-06-06 bad-run states.

**Architecture:** Additive to v2.27 — no v2.27 behavior is removed. Three Python scripts get new findings (`finalize_run.py`: `timing_inverted` FAIL + `quality_trend_sparse`/`agentlens_run_absent` WARN; `validate_state_schema.py`: `task_key_noncanonical` WARN; `phase_boundary.py`: `quality_trend` append in `cmd_task_complete`). One bash template gets a third `DONE=1` branch (`finalization-stop-gate.sh.template`). The cost auto-waive is **prose** (Phase 0 sets a state field via `state_set.py`), not a script. Prose corrections in `references/` remove the false "usage is available" claim and add anti-pattern notes; `evals/check_skill_contract.py` asserts the wiring so it can't rot.

**Tech Stack:** Python 3 stdlib (argparse, json, re, datetime, pathlib), pytest, bash + jq eval harness.

**Resource key:** `finalize_run.py` is edited by Task 3 (`timing_inverted`) and Task 4 (coverage WARNs) — do them sequentially in one branch, never two parallel workers on that file. Everything else is disjoint.

All paths below are relative to `skills/kws-claude-multi-agent-executor/` unless absolute. Run all `pytest`/`python3` commands from that directory.

---

## File Structure

- Create `scripts/fixtures/v2.28/run3_session_package.json`, `run2_readmates_chain.json`, `run1_target_type.json` — the three real bad-run states (replay evidence)
- Modify `scripts/finalize_run.py` — `_parse_iso` helper + `timing_inverted` FAIL + `quality_trend_sparse`/`agentlens_run_absent` WARN
- Modify `scripts/test_finalize_run.py` — inverted-timing + coverage cases + replay
- Modify `scripts/phase_boundary.py` — `quality_trend` append in `cmd_task_complete`
- Modify `scripts/test_phase_boundary.py` — append / cap-10 / no-score cases
- Modify `scripts/validate_state_schema.py` — `TASK_KEY_RE` + `task_key_noncanonical` WARN
- Modify `scripts/test_validate_state_schema.py` — bare-int / ad-hoc / canonical cases
- Modify `references/hooks/finalization-stop-gate.sh.template` — third `DONE=1` branch
- Modify `scripts/test_finalization_stop_gate.py` — all-terminal-unfinalized (run-3 shape) case
- Modify `references/phases/phase-0-setup.md` — cost auto-waive (Step 7) + Stop-trigger doc + key prose
- Modify `references/phases/phase-1-task-cycle.md` — remove false usage prose, remove prose trend append, add timing anti-pattern + key prose
- Modify `references/cross-cutting/agent-dispatch.md` — correct the usage claim
- Modify `references/phases/phase-2-finalization.md` — Cost-tracking + Observability summary rows
- Modify `references/cross-cutting/safety-hooks.md`, `references/cross-cutting/state-schema.md` — third trigger + `cost_tracking_waive_reason`
- Modify `SKILL.md`, `HISTORY.md`, `ARCHITECTURE.md`, `docs/decision-log.md`, `docs/experiments/README.md`, `evals/check_skill_contract.py`
- Create `docs/experiments/v2.28-instrumentation-integrity/JOURNAL.md`, `findings/F01-close-out.md` (README + decisions/ already exist)

---

## Task 0: Capture regression fixtures (do first; no production code)

**Files:**
- Create: `scripts/fixtures/v2.28/{run3_session_package,run2_readmates_chain,run1_target_type}.json`

- [ ] **Step 1: Copy the three live state.json files verbatim**

```bash
cd skills/kws-claude-multi-agent-executor
mkdir -p scripts/fixtures/v2.28
cp ~/.claude/orchestrator/session-package-decomposition-implementation-20260606-205440/state.json scripts/fixtures/v2.28/run3_session_package.json
cp ~/.claude/orchestrator/readmates-resilience-implementation-20260606-214931/state.json        scripts/fixtures/v2.28/run2_readmates_chain.json
cp ~/.claude/orchestrator/target-type-polymorphism-20260606-235331/state.json                   scripts/fixtures/v2.28/run1_target_type.json
```

These contain only orchestrator metadata (no secrets). **Strip nothing** — the
fixtures must reproduce today's exact gate output.

- [ ] **Step 2: Confirm they reproduce today's ground truth**

```bash
python3 scripts/finalize_run.py --state scripts/fixtures/v2.28/run3_session_package.json --check; echo "exit=$?"
python3 scripts/finalize_run.py --state scripts/fixtures/v2.28/run2_readmates_chain.json --check; echo "exit=$?"
python3 scripts/finalize_run.py --state scripts/fixtures/v2.28/run1_target_type.json   --check; echo "exit=$?"
```
Expected (pre-v2.28): run3 exit 1 with `cost_dispatches_zero`; run2 exit 0; run1 exit 0.

**AC:** the three fixtures exist and reproduce the ground truth in the spec table.
**Tests:** the replay assertions in Task 7 read these fixtures.

- [ ] **Step 3: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/fixtures/v2.28
git commit -m "test(v2.28): capture 3 post-v2.27 bad-run state.json fixtures"
```

---

## Task 1: Honest cost auto-waive on the agent path (C1 — gap 1, D001)

This task is **prose + Final Summary only** — `finalize_run.py`'s `cost_dispatches_zero`
FAIL is unchanged (already suppressed by `cost_tracking_waived`). The fix is to set
the waive automatically and correct the false prose.

**Files:**
- Modify: `references/phases/phase-0-setup.md` (Step 7 state init + resume preserve)
- Modify: `references/cross-cutting/agent-dispatch.md` (lines ~38-42)
- Modify: `references/phases/phase-1-task-cycle.md` (lines ~347-369)
- Modify: `references/phases/phase-2-finalization.md` (Step 2 report template)
- Modify: `references/cross-cutting/state-schema.md` (document the new field)

- [ ] **Step 1: Add the deterministic auto-waive to Phase 0 Step 7**

In `references/phases/phase-0-setup.md`, at the Step 7 state.json initialization,
after `dispatch_config` and `cost_ledger` are resolved, insert:

```markdown
**Cost auto-waive (v2.28, D001) — deterministic, not a judgement.** After
`dispatch_config` is set, compute whether any role gate is metered:

\`\`\`
metered = any(dispatch_config[g] in ("api","p") for g in dispatch_config)
if state.mode == "interactive_attached" and not metered:
    state_set.py  cost_tracking_waived = true
    state_set.py  cost_tracking_waive_reason = "agent-dispatch-no-usage"
\`\`\`

The Agent tool returns no `usage` to the orchestrator, so an all-`agent` attached
run *cannot* populate the ledger — the waive is honest, set once, machine-readable.
A run with any `api`/`p` gate is left un-waived and must accumulate real cost. Write
both fields with `state_set.py` (atomic); do NOT hand-type the waive.
```

- [ ] **Step 2: Preserve the waive across resume/chain handoff**

In `references/phases/phase-0-setup.md` (resume protocol, where other run-level cost
fields are preserved, ~line 35) and `references/phases/phase-minus-1-args-and-spawn.md`
(Resume Chain), add `cost_tracking_waived` and `cost_tracking_waive_reason` to the
list of run-level fields **preserved** on handoff (never recomputed if already set).

- [ ] **Step 3: Correct the false "usage is available" prose**

In `references/cross-cutting/agent-dispatch.md` (lines ~38-42) and
`references/phases/phase-1-task-cycle.md` (lines ~347-369), replace the
"extract `usage` from the Agent return envelope … Subscription dispatches still
report usage" claim with:

```markdown
The Agent tool returns only the sub-agent's final message to this turn — there is
**no `usage` object** the orchestrator can read. Per-dispatch cost is therefore
**not observable** on the `"agent"` transport; this is why an attached, all-`agent`
run sets `cost_tracking_waived` at Phase 0 (D001). Only the `"api"` / `"p"`
transports surface usage (from the `dispatch_via_api.py` return / the `stream-json`
result line); those gates accumulate via `accumulate_cost.py`. To get cost + budget
enforcement, opt a gate into `"api"` or `"p"`.
```

Keep the `accumulate_cost.py` invocation documented for the `api`/`p` paths. Remove
the "call the helper with `{0,0}` on the agent path" instruction (never followed;
the auto-waive supersedes its intent).

- [ ] **Step 4: Add the Final Summary "Cost tracking" row**

In `references/phases/phase-2-finalization.md` Step 2 report template, add:

```markdown
- Cost tracking: <"$X.XX (N dispatches)" if dispatches>0
                  else "WAIVED — {cost_tracking_waive_reason}">
```

- [ ] **Step 5: Document the field**

In `references/cross-cutting/state-schema.md`, document the optional run-level
`cost_tracking_waive_reason: str` next to `cost_tracking_waived: bool`.

- [ ] **Step 6: Verify the false claim is gone**

```bash
grep -rn "still report usage" references/ ; echo "exit=$? (1 = clean)"
grep -rn "cost_tracking_waive_reason" references/ SKILL.md | head
```
Expected: the first grep returns nothing (exit 1); the field is referenced.

**AC:** no remaining text claims the Agent tool exposes usage; Phase 0 prose sets the
waive deterministically; Final Summary renders `WAIVED — agent-dispatch-no-usage`.
**Tests:** n/a (prose); the FAIL-suppression path is already covered by
`test_cost_waived_suppresses_dispatch_warning`.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references skills/kws-claude-multi-agent-executor/SKILL.md
git commit -m "feat(v2.28): honest cost auto-waive on the agent path + correct false usage prose (D001)"
```

---

## Task 2: Force finalization on "all tasks terminal" (C2 — gap 2, D002)

**Files:**
- Modify: `references/hooks/finalization-stop-gate.sh.template` (lines 68-74)
- Test: `scripts/test_finalization_stop_gate.py`

- [ ] **Step 1: Write the failing test**

In `scripts/test_finalization_stop_gate.py`, add a fixture + test for the run-3
shape (all tasks terminal, `status:null`, `current_task` set, never finalized):

```python
# v2.28 (D002): the run-3 shape — every task terminal, but status:null and
# current_task still set (Phase 2 never ran). Matches neither prose end-signal;
# the v2.28 all-terminal trigger must still force the gate -> exit 2.
RUN3_ALL_TERMINAL_UNFINALIZED = {
    "status": None,
    "schema_version": "2",
    "mode": "interactive_attached",
    "timestamps": {"started_at": "2026-06-06T11:57:00Z", "completed_at": None},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "dispatch_config": {"mode": "interactive_attached"},
    "current_task": 2,
    "last_completed_task": None,
    "risk_levels": {"task_1": "low", "task_2": "low"},
    "execution_plan": [["task_1"], ["task_2"]],
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "x", "completed": "y"}},
        "task_2": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "x", "completed": "y"}},
    },
}


def test_all_terminal_unfinalized_blocks_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, RUN3_ALL_TERMINAL_UNFINALIZED))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()
```

Note: `last_completed_task: None` + `status: None` is deliberate — pre-v2.28 this
hits **neither** `RSTATUS==COMPLETE` nor `CUR==null && LCT==set`, so the gate would
`exit 0`. That is the RED.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest scripts/test_finalization_stop_gate.py::test_all_terminal_unfinalized_blocks_stop -q`
Expected: FAIL (returncode 0, gate allowed the stop).

- [ ] **Step 3: Add the third `DONE=1` branch**

In `references/hooks/finalization-stop-gate.sh.template`, change the `DONE` block
(lines 68-74) to:

```bash
DONE=0
if [ "$RSTATUS" = "COMPLETE" ]; then
  DONE=1
elif [ "$CUR" = "null" ] && [ "$LCT" = "set" ]; then
  DONE=1
elif [ "${TOTAL:-0}" -gt 0 ]; then
  # v2.28 (D002): every declared task is terminal (NONTERM==0 asserted at the
  # short-circuit above) and the session is ending. All-terminal-at-Stop means
  # Phase 2 was skipped — a run about to finalize does not Stop. Structural
  # trigger independent of the prose-set end-signal (closes the run-3
  # status:null / current_task-set / last_completed_task-null gap).
  DONE=1
fi
[ "$DONE" = "1" ] || exit 0
```

`NONTERM==0` is already asserted at line 63; `TOTAL>0` preserves the fresh-run
exemption. No other gate logic changes.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest scripts/test_finalization_stop_gate.py -q`
Expected: all pass (the new case + the existing fresh/mid-flight/clean cases — the
fresh run has `TOTAL==0` so it still exits 0; mid-flight exits 0 at line 63).

- [ ] **Step 5: Document the third trigger**

In `references/phases/phase-0-setup.md:161` (Stop hook description),
`references/cross-cutting/safety-hooks.md` (Stop gate section), and the SKILL.md
Guardrails "Stop hook forces finalization" row, note that the gate now treats
"every declared task terminal" as a sufficient done-signal.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/hooks/finalization-stop-gate.sh.template \
        skills/kws-claude-multi-agent-executor/scripts/test_finalization_stop_gate.py \
        skills/kws-claude-multi-agent-executor/references skills/kws-claude-multi-agent-executor/SKILL.md
git commit -m "feat(v2.28): Stop gate forces finalization on all-terminal tasks (D002)"
```

---

## Task 3: Timing value sanity — `timing_inverted` FAIL (C3 — gap 3, D003)

**Resource key: finalize_run** (serialize with Task 4)

**Files:**
- Modify: `scripts/finalize_run.py`
- Test: `scripts/test_finalize_run.py`
- Modify: `references/phases/phase-1-task-cycle.md` (anti-pattern prose)

- [ ] **Step 1: Write the failing tests**

In `scripts/test_finalize_run.py`, add:

```python
from datetime import datetime  # noqa: E402  (top of file alongside json/os/sys)


# --- v2.28 (D003): timing_inverted — physically impossible ordering --------

# run-3 shape: started is a KST wall-clock with a bogus Z, completed is real UTC,
# so started (21:00Z) > completed (12:02Z) — completed 9h "before" started.
INVERTED = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "cost_ledger": {"totals": {"dispatches": 4}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "2026-06-06T21:00:00Z",
                              "completed": "2026-06-06T12:02:06Z"}},
    },
}


def test_inverted_timing_is_blocking_fail(tmp_path):
    result = fr.evaluate(INVERTED)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert "timing_inverted" in fails
    assert result["passed"] is False


def test_inverted_timing_fails_even_when_waived(tmp_path):
    # timing_tracking_waived governs ABSENCE, not corruption -> still FAIL.
    waived = dict(INVERTED, timing_tracking_waived=True, cost_tracking_waived=True)
    fails = {f["code"] for f in fr.evaluate(waived)["findings"] if f["level"] == "FAIL"}
    assert "timing_inverted" in fails


def test_normal_ordering_no_inverted(tmp_path):
    ok = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 1}},
        "tasks": {"task_1": {"status": "COMPLETE", "verifier": "PASS",
                             "timing": {"started": "2026-06-06T12:00:00Z",
                                        "completed": "2026-06-06T12:02:06Z"}}},
    }
    codes = {f["code"] for f in fr.evaluate(ok)["findings"]}
    assert "timing_inverted" not in codes


def test_unparseable_timing_no_inverted_no_crash(tmp_path):
    garbage = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 1}},
        "tasks": {"task_1": {"status": "COMPLETE", "verifier": "PASS",
                             "timing": {"started": "not-a-date", "completed": "also-bad"}}},
    }
    codes = {f["code"] for f in fr.evaluate(garbage)["findings"]}
    assert "timing_inverted" not in codes  # falls through to null/absent path
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/test_finalize_run.py -q -k "inverted"`
Expected: FAIL (`timing_inverted` not yet emitted).

- [ ] **Step 3: Add `_parse_iso` + the inverted check**

In `scripts/finalize_run.py`, add the helper after `_active_trees` (before
`_worktree_hook_problems`):

```python
def _parse_iso(value: Any) -> "datetime | None":
    """Tolerant ISO-8601 parse, normalized to naive UTC.

    Returns None on anything non-parseable so corrupt values fall through to the
    existing null/absence handling rather than crashing. Normalizing to naive UTC
    lets an aware/naive pair (e.g. a 'Z' value vs. a bare one) still compare.
    """
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
```

Then inside the per-tree task loop in `evaluate`, immediately after the
`timing_started_missing` WARN block (after line ~106), add:

```python
            started = timing.get("started")
            completed = timing.get("completed")
            if started and completed:
                s, c = _parse_iso(started), _parse_iso(completed)
                if s is not None and c is not None and s > c:
                    add("FAIL", scope, "timing_inverted",
                        f"{task_id}: timing.started ({started}) > "
                        f"timing.completed ({completed}) — impossible ordering "
                        "(hand-typed / wrong-TZ timestamp)")
```

`timing_inverted` is **unconditional** — NOT gated by `timing_tracking_waived`
(that hatch governs *absence*; an inverted pair is corruption — see D003).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/test_finalize_run.py -q`
Expected: all pass (the four new cases + every pre-existing case unchanged).

- [ ] **Step 5: Add the hand-typed-timestamp anti-pattern prose**

In `references/phases/phase-1-task-cycle.md` (task-start block ~line 40-47;
task-complete block ~line 379-385), add one line to each: the orchestrator MUST NOT
write any `timing.*` value by hand; the only sanctioned writers are
`phase_boundary.py task-start` / `task-complete` (UTC, atomic). Hand-typed values
produced the run-3 TZ inversion (`21:00:00Z` local stamped as UTC).

- [ ] **Step 6: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/finalize_run.py \
        skills/kws-claude-multi-agent-executor/scripts/test_finalize_run.py \
        skills/kws-claude-multi-agent-executor/references/phases/phase-1-task-cycle.md
git commit -m "feat(v2.28): timing_inverted blocking FAIL + hand-typed-timestamp anti-pattern (D003)"
```

---

## Task 4: Telemetry coverage backstop (C4 — gap 4, D003)

**Resource key: finalize_run** (serialize with Task 3 for the finalize edit)

**Files:**
- Modify: `scripts/phase_boundary.py` (`cmd_task_complete`)
- Test: `scripts/test_phase_boundary.py`
- Modify: `scripts/finalize_run.py` (coverage WARNs)
- Test: `scripts/test_finalize_run.py`
- Modify: `references/phases/phase-1-task-cycle.md:200` (remove prose append)
- Modify: `references/phases/phase-2-finalization.md` (Observability row)

- [ ] **Step 1: Write the failing phase_boundary test**

In `scripts/test_phase_boundary.py`, add under the task-complete section:

```python
def test_task_complete_appends_quality_score_to_trend(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE", "quality_score": 0.9}, None)
    assert _read(p)["quality_trend"] == [0.9]


def test_task_complete_quality_trend_caps_at_10(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {},
                          "quality_trend": [0.1] * 10})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE", "quality_score": 0.95}, None)
    qt = _read(p)["quality_trend"]
    assert len(qt) == 10
    assert qt[-1] == 0.95 and qt[0] == 0.1  # oldest dropped, newest kept


def test_task_complete_no_quality_score_leaves_trend_untouched(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}, "quality_trend": [0.5]})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE"}, None)
    assert _read(p)["quality_trend"] == [0.5]


def test_task_complete_quality_trend_in_active_tree(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "active_plan": 1,
                          "plan_chain": [{"tasks": {}}, {"tasks": {}}]})
    pb.cmd_task_complete(p, "task_0", {"status": "COMPLETE", "quality_score": 0.8}, None)
    st = _read(p)
    assert st["plan_chain"][1]["quality_trend"] == [0.8]
    assert "quality_trend" not in st  # not written top-level
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest scripts/test_phase_boundary.py -q -k quality`
Expected: FAIL (`quality_trend` not written).

- [ ] **Step 3: Append `quality_score` in `cmd_task_complete`**

In `scripts/phase_boundary.py`, extend the `mutate` closure inside
`cmd_task_complete` (lines 119-127):

```python
    def mutate(state: dict) -> None:
        active = _active(state)
        tasks = active.setdefault("tasks", {})
        timing = result.setdefault("timing", {})
        timing["completed"] = ss._utc_now_iso()
        tasks[task] = result
        active["last_completed_task"] = task
        active["last_completed_at"] = ss._utc_now_iso()
        score = result.get("quality_score")
        if score is not None:  # v2.28 (D003): single unskippable trend writer
            qt = active.setdefault("quality_trend", [])
            qt.append(score)
            del qt[:-10]  # cap at 10, keep newest
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest scripts/test_phase_boundary.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing finalize coverage tests**

In `scripts/test_finalize_run.py`, add:

```python
# --- v2.28 (D003): telemetry coverage WARNs (never FAIL) -------------------

def test_sparse_quality_trend_warns_not_fails(tmp_path):
    sparse = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 2}},
        "agentlens_orchestration_run": "run-x",
        "quality_trend": [],
        "tasks": {
            "task_1": {"status": "COMPLETE", "verifier": "PASS", "review_tier": "PASS",
                       "timing": {"started": "s", "completed": "c"}},
            "task_2": {"status": "COMPLETE", "verifier": "PASS", "review_tier": "PASS",
                       "timing": {"started": "s", "completed": "c"}},
        },
    }
    result = fr.evaluate(sparse)
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "quality_trend_sparse" in warns
    assert result["passed"] is True  # WARN never blocks


def test_full_quality_trend_no_sparse_warning(tmp_path):
    full = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 2}},
        "agentlens_orchestration_run": "run-x",
        "quality_trend": [0.9, 0.8],
        "tasks": {
            "task_1": {"status": "COMPLETE", "verifier": "PASS", "review_tier": "PASS",
                       "timing": {"started": "s", "completed": "c"}},
            "task_2": {"status": "COMPLETE", "verifier": "PASS", "review_tier": "PASS",
                       "timing": {"started": "s", "completed": "c"}},
        },
    }
    codes = {f["code"] for f in fr.evaluate(full)["findings"]}
    assert "quality_trend_sparse" not in codes


def test_null_agentlens_run_warns(tmp_path):
    codes = {f["code"] for f in fr.evaluate(RUN3_CLEAN)["findings"]}
    assert "agentlens_run_absent" in codes  # RUN3_CLEAN has no agentlens key


def test_present_agentlens_run_no_warning(tmp_path):
    state = dict(RUN3_CLEAN, agentlens_orchestration_run="run-y")
    codes = {f["code"] for f in fr.evaluate(state)["findings"]}
    assert "agentlens_run_absent" not in codes
```

- [ ] **Step 6: Run to verify they fail**

Run: `python3 -m pytest scripts/test_finalize_run.py -q -k "sparse or agentlens"`
Expected: FAIL (codes not yet emitted).

- [ ] **Step 7: Add the coverage WARNs to `finalize_run.py`**

In `scripts/finalize_run.py`, after the per-tree task loop and the
`timing_tracking_absent` aggregate block (after line ~115), before the hook-wiring
block, add:

```python
    # v2.28 (D003): telemetry coverage — WARN only (best-effort per v2.10/v2.17).
    reviewed = 0
    trend_len = 0
    for _, tree in _active_trees(state):
        trend_len += len(tree.get("quality_trend") or [])
        for task in (tree.get("tasks") or {}).values():
            if task.get("status") in ("COMPLETE", "SKIPPED") and (
                    task.get("review_tier") or task.get("review")):
                reviewed += 1
    if reviewed > 0 and trend_len < reviewed:
        add("WARN", "state", "quality_trend_sparse",
            f"quality_trend has {trend_len} entries for {reviewed} reviewed tasks")
    if not state.get("agentlens_orchestration_run"):
        add("WARN", "state", "agentlens_run_absent",
            "agentlens_orchestration_run is null — observability pipeline was dark")
```

- [ ] **Step 8: Run to verify they pass (and no regression)**

Run: `python3 -m pytest scripts/test_finalize_run.py -q`
Expected: all pass. The existing fixtures with no `review_tier` have `reviewed==0`,
so `quality_trend_sparse` does not fire on them (no regression to
`test_clean_run_passes` / `test_run3_clean_no_false_positive`).

- [ ] **Step 9: Remove the prose trend append + add the Observability row**

In `references/phases/phase-1-task-cycle.md:200`, remove the prose
`quality_trend.append(...)` step and replace it with a one-line pointer: the trend
is appended by `phase_boundary.py task-complete` when the result carries
`quality_score` (single writer). In `references/phases/phase-2-finalization.md`
Step 2, add an "Observability" row: AgentLens run id (or `dark — agentlens
unavailable at run-open`) + `quality_trend coverage: <trend_len>/<reviewed>`.

- [ ] **Step 10: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/phase_boundary.py \
        skills/kws-claude-multi-agent-executor/scripts/test_phase_boundary.py \
        skills/kws-claude-multi-agent-executor/scripts/finalize_run.py \
        skills/kws-claude-multi-agent-executor/scripts/test_finalize_run.py \
        skills/kws-claude-multi-agent-executor/references/phases/phase-1-task-cycle.md \
        skills/kws-claude-multi-agent-executor/references/phases/phase-2-finalization.md
git commit -m "feat(v2.28): quality_trend into task-complete + coverage WARNs (D003)"
```

---

## Task 5: Task-key canonicalization WARN (C5 — gap 5, D003)

**Files:**
- Modify: `scripts/validate_state_schema.py`
- Test: `scripts/test_validate_state_schema.py`
- Modify: `references/phases/phase-1-task-cycle.md:391`, `references/phases/phase-0-setup.md`

- [ ] **Step 1: Write the failing tests**

In `scripts/test_validate_state_schema.py`, add:

```python
# v2.28 (D003): run-1 used bare-int + ad-hoc keys ("1".."6","riskclose").
RUN1_BAD_KEYS = {
    "schema_version": "2",
    "mode": "interactive_attached",
    "dispatch_config": {"final_sweep": "agent"},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "risk_levels": {"1": "low", "riskclose": "mid"},
    "execution_plan": [["1"]],
    "tasks": {"1": {"status": "COMPLETE"}, "riskclose": {"status": "COMPLETE"}},
}


def test_noncanonical_task_keys_warn_not_violation(tmp_path):
    result = vss.validate(RUN1_BAD_KEYS)
    warn_codes = {w["code"] for w in result["warnings"]}
    assert "task_key_noncanonical" in warn_codes
    assert result["passed"] is True  # WARN does not flip passed


def test_canonical_and_suffixed_keys_clean(tmp_path):
    ok = dict(CANONICAL_SINGLE)
    ok["tasks"] = {"task_1": {"status": "COMPLETE"},
                   "task_7_remediation": {"status": "COMPLETE"}}
    ok["risk_levels"] = {"task_1": "low", "task_7_remediation": "mid"}
    codes = {w["code"] for w in vss.validate(ok)["warnings"]}
    assert "task_key_noncanonical" not in codes
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest scripts/test_validate_state_schema.py -q -k canonical`
Expected: FAIL (`task_key_noncanonical` not emitted).

- [ ] **Step 3: Add `TASK_KEY_RE` + the WARN**

In `scripts/validate_state_schema.py`, add `import re` (top), a module constant
after `VALID_MODES`:

```python
TASK_KEY_RE = re.compile(r"^task_\d+(_[a-z0-9-]+)?$")  # task_3, task_7_remediation
```

and inside the per-tree loop (after the `task_summaries_alongside_tasks` warn,
~line 101):

```python
        bad_keys = [k for k in tasks if not TASK_KEY_RE.match(str(k))]
        if bad_keys:
            warn(scope, "task_key_noncanonical",
                 f"non-canonical task keys: {sorted(bad_keys)} "
                 "(expected task_<N>[_<suffix>])")
```

WARN, not violation — a finished run with deviant keys surfaces the drift at the
Stop gate without being hard-blocked (D003; promotion deferred until the
key-writing prose is tightened).

- [ ] **Step 4: Run to verify they pass (and no regression)**

Run: `python3 -m pytest scripts/test_validate_state_schema.py -q`
Expected: all pass (CANONICAL_SINGLE `task_1/task_2` and READMATES_BAD empty `tasks{}`
emit no key warning).

- [ ] **Step 5: Reinforce canonical keys in prose**

In `references/phases/phase-1-task-cycle.md:391` (result schema example) and
`references/phases/phase-0-setup.md` (task extraction / key assignment), state that
`tasks{}` keys are always `task_<N>`; remediation/inserted tasks use
`task_<N>_<suffix>`; never a bare integer or free-form label. Note `task_summaries`
is a legacy read-mirror (no new writes).

- [ ] **Step 6: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/validate_state_schema.py \
        skills/kws-claude-multi-agent-executor/scripts/test_validate_state_schema.py \
        skills/kws-claude-multi-agent-executor/references/phases/phase-1-task-cycle.md \
        skills/kws-claude-multi-agent-executor/references/phases/phase-0-setup.md
git commit -m "feat(v2.28): task_key_noncanonical schema WARN + canonical-key prose (D003)"
```

---

## Task 6: Contract eval + docs sync + version bump (C6)

**Files:**
- Modify: `evals/check_skill_contract.py`
- Modify: `SKILL.md` (version + Guardrails), `HISTORY.md`, `ARCHITECTURE.md`,
  `docs/decision-log.md`, `docs/experiments/README.md`
- Create: `docs/experiments/v2.28-instrumentation-integrity/JOURNAL.md`,
  `findings/F01-close-out.md`

- [ ] **Step 1: Add v2.28 wiring checks so the prose can't rot**

In `evals/check_skill_contract.py`, after the v2.27 contract block, add:

```python
    # ---- v2.28 instrumentation-integrity contracts ----
    V228_HELPER_TOKENS = {
        "scripts/finalize_run.py": ["timing_inverted", "quality_trend_sparse",
                                    "agentlens_run_absent", "_parse_iso"],
        "scripts/validate_state_schema.py": ["task_key_noncanonical", "TASK_KEY_RE"],
        "scripts/phase_boundary.py": ["quality_trend"],
    }
    for rel_path, tokens in V228_HELPER_TOKENS.items():
        full = skill_dir / rel_path
        body = full.read_text(encoding="utf-8") if full.is_file() else ""
        record(f"v228_helper_contract_{rel_path.replace('/', '_')}",
               all(t in body for t in tokens),
               f"{rel_path} must define v2.28 tokens: {', '.join(tokens)}")

    record("v228_stopgate_all_terminal",
           'elif [ "${TOTAL:-0}" -gt 0 ]' in
           (skill_dir / "references/hooks/finalization-stop-gate.sh.template").read_text(encoding="utf-8"),
           "Stop gate must carry the v2.28 all-terminal DONE=1 branch")
    record("v228_cost_waive_reason_wired",
           "cost_tracking_waive_reason" in corpus,
           "Phase 0 prose must set cost_tracking_waive_reason (D001)")
    record("v228_no_false_usage_claim",
           "still report usage" not in corpus,
           "the false 'subscription dispatches still report usage' claim must be gone")
```

- [ ] **Step 2: Run the contract check**

Run: `python3 evals/check_skill_contract.py --skill SKILL.md`
Expected: `"passed": true` with the new `v228_*` checks present and true.

- [ ] **Step 3: SKILL.md version + Guardrails rows**

Set frontmatter `version: "2.28.0"`. Add/extend Guardrails rows: cost auto-waive on
the agent path (D001), Stop-gate all-terminal trigger (D002), `timing_inverted`
un-waivable FAIL + telemetry coverage WARNs + `task_key_noncanonical` (D003).

- [ ] **Step 4: HISTORY.md + ARCHITECTURE.md + decision-log + experiments index**

- `HISTORY.md`: a v2.28 entry summarizing the five fixes and the three driving runs.
- `ARCHITECTURE.md`: add `cost_tracking_waive_reason` to the state-schema section;
  note `timing_inverted` / coverage WARNs / `task_key_noncanonical` in the finalize
  + schema gate descriptions; `quality_trend` now written by `phase_boundary.py`.
- `docs/decision-log.md`: index D001-D003.
- `docs/experiments/README.md`: index the v2.28 folder.

- [ ] **Step 5: Experiment record**

Create `docs/experiments/v2.28-instrumentation-integrity/JOURNAL.md` (dated
2026-06-07 entries) and `findings/F01-close-out.md` (ship decision + the spec's
Remaining Risks). The folder's `README.md` and `decisions/D001-D003.md` already
exist; update the README "Phase status" table to `done` as components land, and
make it point to this superpowers spec/plan as the canonical detailed docs.

- [ ] **Step 6: Doc-freshness + commit**

```bash
python3 evals/check_doc_freshness.py   # create docs/snapshots/v2.28.md if it requires one
git add skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py \
        skills/kws-claude-multi-agent-executor/SKILL.md \
        skills/kws-claude-multi-agent-executor/HISTORY.md \
        skills/kws-claude-multi-agent-executor/ARCHITECTURE.md \
        skills/kws-claude-multi-agent-executor/docs
git commit -m "docs(v2.28): contract checks + version bump 2.28.0 + experiment record"
```

---

## Task 7: Regression replay + full verification (the real proof)

**Files:** `scripts/test_finalize_run.py`, `scripts/test_finalization_stop_gate.py`
(replay sections reading the Task 0 fixtures).

- [ ] **Step 1: Add the replay assertions**

In `scripts/test_finalize_run.py`, add a replay block that loads the three fixtures
and asserts the before/after table:

```python
import pathlib  # noqa: E402

_FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "v2.28"


def _load(name):
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


def test_replay_run3_session_package(tmp_path):
    state = _load("run3_session_package.json")
    state["cost_tracking_waived"] = True  # simulate C1's Phase-0 auto-waive
    result = fr.evaluate(state)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert "timing_inverted" in fails             # the honest blocker
    assert "cost_dispatches_zero" not in fails    # auto-waived -> no longer masks
    assert result["passed"] is False


def test_replay_run1_target_type_sparse_trend(tmp_path):
    result = fr.evaluate(_load("run1_target_type.json"))
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "quality_trend_sparse" in warns        # trend [] for reviewed tasks
    assert "agentlens_run_absent" in warns
```

In `scripts/test_finalization_stop_gate.py`, add a replay test driving the hook
against the run-2 and run-3 fixtures (both all-terminal) → exit 2.

- [ ] **Step 2: Run the full sweep**

```bash
cd skills/kws-claude-multi-agent-executor
python3 -m pytest scripts/ -q
python3 evals/check_skill_contract.py --skill SKILL.md
./evals/run.sh
git diff --check
```
Expected: all green; contract `"passed": true`; `git diff --check` clean.

- [ ] **Step 3: Smoke-test the validators against the real runs (read-only)**

```bash
python3 scripts/finalize_run.py --state scripts/fixtures/v2.28/run3_session_package.json --check; echo "exit=$?"
python3 scripts/validate_state_schema.py --state scripts/fixtures/v2.28/run1_target_type.json; echo "exit=$?"
```
Expected: run3 exits 1 now flagging `timing_inverted` (cost still FAIL only when not
waived); run1 schema exits 0 with a `task_key_noncanonical` warning.

- [ ] **Step 4: Report**

Summarize: tests green, contract green, the three real runs now surface the honest
defects (run3 `timing_inverted`, run1 sparse trend + bad keys, run2 forced to
finalize). Note the worktree/branch is unmerged for the user to review.

---

## Self-Review

**Spec coverage:** Deliverable A → Task 1; B → Task 2; C → Task 3; D → Task 4;
E → Task 5; F → Task 6; regression replay (spec §Data flow + Goals 6) → Task 0 +
Task 7. Every spec deliverable maps to a task; every ADR (D001/D002/D003) is cited
in the task that implements it.

**Placeholder scan:** every code step contains complete, runnable code grounded in
the current source (line anchors from `finalize_run.py` v2.27, `phase_boundary.py`,
`validate_state_schema.py`, `finalization-stop-gate.sh.template`); no TBD/TODO;
prose-edit steps quote the exact insertion text and anchor.

**Type consistency:** `finalize_run.evaluate()` returns `{passed, unfixable_fail,
findings[]}` with finding `code`s used verbatim in tests + contract
(`timing_inverted`, `quality_trend_sparse`, `agentlens_run_absent`, plus the
unchanged v2.27 codes). `_parse_iso(value) -> datetime | None` normalizes to naive
UTC so aware/naive pairs compare without raising. `validate()` returns
`{passed, scopes_checked, violations[], warnings[]}` — `task_key_noncanonical` is a
WARN (in `warnings[]`, never `violations[]`), so `passed` is unaffected.
`phase_boundary.cmd_task_complete` appends to `<active>.quality_trend` (cap 10) only
when `result["quality_score"] is not None`. Contract-check tokens in Task 6 match
literal strings present in the Task 3/4/5 implementations.

**Severity ladder (D003):** `timing_inverted` = FAIL un-waivable (corruption);
`quality_trend_sparse` / `agentlens_run_absent` / `task_key_noncanonical` = WARN
(degraded telemetry / cosmetic, work may be fine). Mirrors the v2.27 D002 rule:
severity tracks certainty; block only on unambiguous corruption.

**No-regression argument:** existing finalize fixtures have no `review_tier`
(`reviewed==0` → no sparse WARN) and valid/no timing (no `timing_inverted`); the
schema fixtures use canonical or empty `tasks{}` (no key WARN); the Stop-gate
fresh/mid-flight cases keep `TOTAL==0` / `NONTERM>0`. Every new finding is additive.
