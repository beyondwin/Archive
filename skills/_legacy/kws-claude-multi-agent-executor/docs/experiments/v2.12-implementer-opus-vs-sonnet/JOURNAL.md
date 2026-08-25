# JOURNAL — v2.12 Implementer Opus vs Sonnet quality comparison

Chronological log. Update **as you go**, not at the end.

---

## 2026-05-16

### Setup — experiment scaffold + skill patch

User asked: is the current sub-agent Implementer-on-Sonnet meaningfully worse than Opus, and on which task complexities does the gap show up? Built experiment scaffold to answer it cleanly:

- Branch `experiment/v2.12-implementer-opus-vs-sonnet` created off main (v2.10.2).
- New skill arg `implementer_model=opus|sonnet`, default `sonnet` — additive only.
- `state.json` now records `implementer_model: {used, default}` at Phase 0 Step 7 so post-hoc aggregation can group runs without re-asking. User specifically requested recording the default alongside, so the comparison stays unambiguous when reading state.json after the fact.
- Reviewer/Verifier held on Sonnet (ADR D001). Judge model is a confound — fixing it means deltas in `spec_score`/`quality_score` are attributable to the Implementer change rather than judge drift.
- Benchmark plan: 6 tasks, balanced 2×SMALL / 2×MEDIUM / 2×LARGE. Designed so Reviewer scoring has signal at every bucket (each task has at least one non-obvious spec contract or sub-requirement).
- Aggregation script `bench/aggregate.py` reads `state.json` from N run directories, groups by `implementer_model.used`, breaks down per-task by `task_complexity`. Outputs CSV + a compact terminal summary.
- Run procedure `RUN.md` covers: working tree clean, run each arm 3 times in series (or parallel if isolated worktrees), where state.json lands, how to feed paths to `aggregate.py`.

Reasoning trail for design choices:
- 3 runs per arm — minimum for variance to show. Sonnet/Opus stochasticity per Implementer call is non-trivial; n=1 is anecdote.
- SMALL/MEDIUM/LARGE mix — quality gap should grow with complexity. If gap is flat across buckets, that's itself the finding.
- Skill changes additive — never disrupt the production `main` baseline.

### Open questions for the user (deferred to first run)

- Whether to also run with Reviewer=Opus once for a sanity check (separate experiment, not in this comparison).
- Whether to mirror Combined Reviewer dispatch path for symmetry — current scope keeps it on Sonnet.

### ADVISOR REVIEW — round 1

Advisor flagged 3 issues:

1. 🔴 **BLOCKER — `implementer_model` doesn't propagate through Phase -1 self-spawn.** The minimal state.json at step b doesn't include the field, and `headless_prompt.txt` doesn't carry skill args. The headless child has no way to know about the override → both arms silently run Sonnet in default (non-interactive) mode. **Fix**: parse the arg in the interactive parent at Phase -1 step b and write `implementer_model` into the minimal state.json there. Phase 0 Step 7 in the headless child now reads from state.json instead of re-parsing args (split into two cases by entry path). Also explicitly noted in the headless-pending branch of Phase 0 Step 0 (Resume Protocol) that the field must be preserved. Updated guardrail row to spell out the propagation path.

2. 🟠 **Complexity bucket likely collapses to MEDIUM.** Heuristic SMALL gate is `file_count==1 AND new_decls<=1 AND risk_mult==1 AND spec_chars<1200`. My original plan had every task at file_count=2 with multiple decls per task. **Fix**: re-partitioned the plan into truly single-file SMALL tasks (Task 0 just adds `__version__`; Task 1 just adds `FlagType` enum), 2-file MEDIUM tasks (Tasks 2, 3), and HIGH-risk LARGE tasks (Tasks 4, 5 with "API surface" + "breaking change" wording that triggers Phase 0 Step 4's HIGH-risk override; Task 5 also has 5 files to reinforce LARGE via the file_count≥4 branch). Spec §1–§6 rewritten so each task introduces an isolated set of decls. Tests are deferred to retroactive task slots — Task 2 writes test_types.py, Task 3 writes test_registry.py, etc.

3. 🟡 **AGENTS.md doc-update protocol not followed.** Skill state-schema change requires same-commit ARCHITECTURE.md §5 update and HISTORY.md v2.12 entry. **Fix**: both updated. ARCHITECTURE.md §5 schema sample now shows the `implementer_model` field with its propagation note. HISTORY.md gets a v2.12 entry explaining the experiment status (branch-only, awaiting findings before main).

All three addressed in this turn before the user runs anything.

### ADVISOR REVIEW — round 2

Two more blockers, one cosmetic:

1. 🔴 **Empty tests/ → pytest exit 5 ("no tests collected")** — baseline at Phase 0 Step 5 would either record `0 passing / 1 failing` (phantom regression haunts every Verifier) or hard-halt depending on how the orchestrator interprets exit code 5. **Fix**: added `bench/repo-skeleton/tests/test_smoke.py` with one trivial assertion. Removed `.gitkeep`. Verified `pytest -q` from a copy of the skeleton: 1 passed in 0.00s. Baseline now `1 passing / 0 failing` — stable starting point.

2. 🔴 **Parallel Sub-Flow Step P.2 doesn't propagate the model param** — Tasks 0 and 1 have disjoint file sets and no deps, so they merge into one Wave 0 parallel group. Step P.2's prose said "same Implementer Prompt Template" but had no instruction to set the Agent tool's `model` parameter; the Opus arm would silently dispatch Task 0/1 on Sonnet. SMALL Δ would be uninterpretable. **Fix**: patched Step P.2 with an explicit bullet — `Sets the Agent tool model parameter to state.implementer_model.used` under the same `omit-for-sonnet / required-for-opus` rule as Step 1. Strengthened the guardrail row to call out this Step P.2 trap. Also added `parallel=off` to RUN.md's invocation strings as belt-and-suspenders (sequential dispatch also keeps wall-time comparison fair across arms).

3. 🟡 **RUN.md slug mismatch** — earlier draft showed `flagset-cli-library-benchmark-v2-12-<TIMESTAMP>/` but Phase 0 Step 2 derives slug from filename → `plan.md` becomes slug `plan`. **Fix**: corrected path examples in Step 4 and Step 5 to `worktrees/plan-<TIMESTAMP>/`.

After round 2, the ship-blocking issues for the experiment kickoff are addressed. The parallel-sub-flow gap is a v2.12 SKILL.md hardening item worth highlighting in the F001 close-out — anyone running `implementer_model=opus` on a more parallelizable plan without `parallel=off` would have hit the same bug before the fix.

### ADVISOR REVIEW — round 3

One blocker: `python -c "import flagset"` ACs would all fail under the Verifier because `pip install -e` was scoped to a venv that gets deactivated before the orchestrator runs. `pyproject.toml` declares `pythonpath = ["src"]` but that only applies to pytest, not plain Python. Reproduced by hand:

```
$ cd /tmp/_v && python3 -c "import flagset"
ModuleNotFoundError: No module named 'flagset'
$ PYTHONPATH=src python3 -c "import flagset; print('ok')"
ok
```

**Fix**: prepended `PYTHONPATH=src` to every `python -c` AC in `plan.md` and `spec.md`. Dropped the venv/pip install steps from `RUN.md` and `bench/repo-skeleton/README.md` — they were misleading (created a venv that wasn't carried forward) and now unnecessary. Caller just needs `pytest` on PATH. Verified end-to-end by running Task 0 and Task 1 AC simulations against the corrected skeleton: both print `ok`, smoke test still passes.

Minor noted: `tests/test_smoke.py` will appear in every Task 1+'s pytest run as `+1` passing. Documented in JOURNAL for F001 reference; doesn't affect comparison since both arms see the same +1.

After round 3 the experiment should kick off cleanly. No further blockers from this advisor pass.

---

## On close-out

(To be filled after 6 runs + F001 finding.)
