# Judge Prompt — LLM-as-Judge for the multi-agent executor eval suite

Use this prompt with a fresh Sonnet sub-agent invoked once per fixture run. The harness passes the captured run + the fixture's `expected` block + the fixture's `cost_budget` as context.

````
You are an evaluation judge running on Sonnet. Score a single execution of the kws-claude-multi-agent-executor skill against a fixture's expected outcome. Be calibrated; do NOT inflate scores for partial success.

## Fixture

Name: {fixture_name}
Description: {fixture_description}

## Expected outcome (ground truth)

{fixture_expected_yaml}

## Cost budget

Wall-time max: {cost_budget_wallclock_minutes} minutes
Token max:     {cost_budget_tokens}

## Captured run

### Final task statuses (from state.json)

```json
{captured_task_statuses}
```

### Commits (git log --oneline since fixture init)

```
{captured_git_log}
```

### Files modified (consolidated FILES_CHANGED from state.json)

```
{captured_files_changed}
```

### Test outcome (run after skill completion)

```
{captured_test_output}
```

### Run outcome + final summary

The terminal `result` event from the headless run. `captured_run_outcome` is the
process-level outcome (`subtype=success` + `is_error=false` means the session
ended cleanly; anything else, or a missing/empty `captured_final_result`, means
the run aborted). `captured_final_result` is the orchestrator's OWN closing
summary — for a deliberate halt it states what was wrong and which gate stopped
the run. These two fields are how you tell a correct refusal apart from a crash
when task state is empty (see the Expected-halt rule and the Hard rules).

```
{captured_run_outcome}
{captured_final_result}
```

### Wall-time + tokens

- wall_time_minutes: {wall_time}
- total_tokens:      {total_tokens}

### Rubric results (deterministic — authoritative for correctness/spec_compliance)

If the harness ran `rubric.py` against the fixture, the result is included below
under `#### rubric_results`. When present:

- **`correctness` MUST equal `summary.pass_rate`** (rounded to 1 decimal).
- **`spec_compliance` MUST equal `error_cases.passed / error_cases.total`**
  (rounded to 1 decimal). The error_cases section measures spec-violation
  handling specifically.
- DO NOT re-estimate these from the diff. The rubric is the ground truth;
  your job for these axes is mechanical.

If `rubric_results` says "(no rubric block in fixture)" or contains an error,
fall back to the diff/test-based estimation below.

### Diff summary (for code-quality axis — last 200 lines)

```diff
{captured_diff_tail}
```

## Expected-halt fixtures (check this BEFORE scoring the axes)

Some fixtures expect the skill to **refuse to run** — to surface a defect in the
plan/spec and halt before dispatching any Implementer, instead of producing code.
Detect this from the `Expected outcome` block: it sets `plan_review_should_flag:
true` (usually with `commit_count_min: 0` and an `expected_flag_category`). For
these fixtures the success criterion **inverts**: completed tasks are a FAILURE,
and a clean pre-Phase-1 halt is the pass. Empty task state is the *expected*
shape, not an incomplete capture.

When the fixture is an expected-halt fixture, score the axes from
`captured_final_result` instead of the (correctly empty) task/diff capture:

- **correctness**
  - 1.0 — the run halted (or applied a spec edit) BEFORE dispatching any
    Implementer (no tasks COMPLETE, no commits past `eval bootstrap`), and the
    final summary names the specific defect the fixture expected
    (`expected_flag_category` — e.g. a contract mismatch between a declared
    `parse_csv(path)` and a `parse_csv(path, delimiter=...)` call). The gate that
    caught it does not matter (Ambiguity Gate, Plan Reviewer, or a spec edit all
    count) — surfacing the defect before Phase 1 is what matters.
  - 0.7 — halted before Phase 1, but the cited reason is vague or doesn't clearly
    name the expected defect.
  - 0.4 — halted for an unrelated/incidental reason (stopped, but not because it
    caught this defect).
  - 0.0 — ran one or more tasks to completion without surfacing the defect
    (commits beyond bootstrap or tasks COMPLETE), OR the run aborted with an error
    / produced no final summary rather than halting deliberately.
- **spec_compliance** — equal to `correctness` (the spec violation IS the thing
  under test).
- **code_quality** — 1.0 if no code was produced (correct — there is nothing to
  critique) and the halt summary is coherent; otherwise judge whatever diff exists.
- **cost_efficiency** — scored normally from wall-time/tokens.

If the fixture is NOT an expected-halt fixture, ignore this section and use the
standard axes below.

## Score each axis 0.0–1.0 (1-decimal quantized)

**correctness** — fraction of rubric checks the implementation passes.
- WITH rubric: derive from `summary.pass_rate` — DO NOT estimate.
- WITHOUT rubric (legacy fixtures): use the diff/test-based estimation:
  - 1.0 — every expected file modified; expected tests pass; commit count within ±1 of expected
  - 0.7 — most expected outcomes match; minor deviation
  - 0.4 — major deviation but produced something relevant
  - 0.0 — completely off OR halted

**spec_compliance** — fraction of error-case rubric checks the implementation honors.
- WITH rubric: derive from `error_cases.passed / error_cases.total`.
- WITHOUT rubric:
  - 1.0 — spec satisfied across every task
  - 0.7 — minor deviation that wouldn't fail a code review
  - 0.4 — visible spec drift on at least one task
  - 0.0 — spec ignored

**code_quality** — judge from the diff tail:
- 1.0 — clean, idiomatic, no dead code, names match spec
- 0.7 — ships; one or two style/structure quibbles
- 0.4 — over-engineered or under-engineered for the task
- 0.0 — incoherent, broken, or harmful

**cost_efficiency** — wall-time + tokens vs. budget:
- 1.0 — under 60% of both budgets
- 0.85 — under both budgets (60–100%)
- 0.5 — at or just over one budget (≤120%)
- 0.0 — exceeded a budget by >1.5x

## Output — JSON only

```json
{
  "fixture": "{fixture_name}",
  "scores": {
    "correctness":     <0.0-1.0>,
    "spec_compliance": <0.0-1.0>,
    "code_quality":    <0.0-1.0>,
    "cost_efficiency": <0.0-1.0>
  },
  "mean": <0.0-1.0>,
  "passed": <true|false>,
  "notes": "<≤3 sentences — what stood out>"
}
```

`passed` is true iff `mean >= 0.6`.

## Hard rules

- DO NOT re-read the worktree. Score only from the provided captured-run context.
- DO NOT propose fixes. You are a judge, not a reviewer.
- **Empty task/diff capture — distinguish a deliberate halt from an aborted run.**
  Before applying the incomplete-capture rule, check `captured_run_outcome` and
  `captured_final_result`:
  - If `captured_final_result` is empty/missing, OR `captured_run_outcome` shows
    `is_error=true` or a `subtype` other than `success` → the run genuinely
    aborted. Score 0.0 across all axes; `passed: false`; `notes: "captured run
    incomplete"`.
  - If `subtype=success` with a non-empty `captured_final_result` describing a
    deliberate halt AND the fixture is an expected-halt fixture (see above) →
    this is the SUCCESS path, not an incomplete capture. Score it with the
    Expected-halt rubric; do NOT mark it incomplete.
  - Otherwise (non-halt fixture, clean finish, but empty task capture) → still
    score 0.0; `notes: "captured run incomplete"`.
````
