# How to add a new eval fixture

Step-by-step for adding a fixture to `evals/fixtures/`. Anthropic eval
guidance suggests 5-8 fixtures is the sweet spot — adding a 9th makes
sense only when there's a measured failure type that existing fixtures
don't cover.

For format-level details see [`../../evals/README.md`](../../evals/README.md).
For the why-add-this decision pattern see
[`../deferred-candidates.md`](../deferred-candidates.md) §Fixture spec audit.

## Decision: should this fixture exist?

Before writing YAML, answer:

1. **What failure mode does this fixture test that no existing fixture
   covers?** If "none specifically, just feels useful" → don't add.
   Fixture set grows = eval cost grows.
2. **Is there *measured* evidence the failure mode occurs?** If yes,
   reference the learning-log event or experiment finding. If no, the
   fixture is speculative — record it as a candidate in
   [`../deferred-candidates.md`](../deferred-candidates.md) and add only
   if the failure surfaces.
3. **What risk tier?** LOW (single small fix, <5 lines), MID (file
   creation + tests, ≤2 files), HIGH (cross-file refactor or new module).

## File layout

```
evals/fixtures/0N-<short-slug>.yaml      ← the fixture
evals/baselines/v<X.Y.Z>.json            ← captured after first run
```

`N` = next sequential number (currently 08 is highest). Use kebab-case
slug ≤ 30 chars.

## YAML structure

```yaml
name: <fixture-name-matching-filename>
description: |
  <one-paragraph "what does this test"; include risk tier and expected
   complexity. This appears in the judge prompt.>

bootstrap: |
  <bash commands that set up the empty repo before plan execution starts.
   Create dirs, write pyproject.toml / package.json / Makefile, install
   minimal deps. End state: empty src/ + empty tests/, ready for plan
   to populate.>

plan: |
  ### Task 0: <imperative title>
  
  **Files:**
  - path/to/file.py
  
  <Markdown body the orchestrator reads. Should include "## Acceptance
   Criteria" subsection with concrete commands.>

  ### Task 1: <…>
  
  <repeat for as many tasks as needed; typically 1-3>

spec: |
  # Spec: <component name>
  
  <Markdown body the Reviewer reads. Should be self-contained — the
   Reviewer doesn't see the plan when reviewing. Include:
   - Input/output contract
   - Examples (happy path)
   - Error cases (must raise / reject)
   - Notes (constraints not captured in examples)
   - Meta-rules (sentences with "strict", "reject", etc.) for the
     v2.9 Spec Coverage Walk to consume>

invocation: ""              # optional extra args to /kws-claude-multi-agent-executor

expected:
  task_count: <int>          # number of tasks in plan
  expected_files_changed:    # files the orchestrator should touch
    - <path>
  commit_count_min: <int>
  commit_count_max: <int>
  test_after: |              # bash command run after orchestrator finishes
    <test invocation>
  rubric:                    # OPTIONAL but RECOMMENDED — deterministic correctness
    valid_inputs:
      - check: <bash one-liner; exit 0 = pass>
    error_cases:
      - check: <bash one-liner that asserts a ValueError is raised>
        desc: <human-readable name; appears in rubric.json>
    code_quality_dimensions: # OPTIONAL — judge consumes these
      - <one-sentence dimension>
  notes: |                   # optional context for judge

cost_budget:
  wallclock_minutes: <int>   # advisory; for harness reporting
  tokens: <int>              # advisory
```

See `evals/fixtures/08-subtle-input-validation.yaml` for a complete
working example.

## Critical: spec-vs-rubric alignment

This is the v2.9 Phase 2 lesson — fixture 08's spec was ambiguous about
repeated units; the rubric required ValueError. The Reviewer reasoned
the spec permitted them. Result: rubric FAIL but Reviewer PASS, confusing
the eval signal.

**Before saving the fixture, audit:**

- For each `error_cases` rubric check: is there a corresponding
  explicit statement in the `spec:` body? Either as a bullet in the
  Examples / Error cases section, OR a Notes bullet making it
  unambiguous?
- For each `valid_inputs` rubric check: is the value derivable from the
  spec, or is it a hidden assumption?

If a rubric requires a behavior the spec only implies via a meta-rule,
either:
1. Add an explicit Notes bullet to the spec.
2. Remove the rubric check.

Don't ship a fixture with hidden spec assumptions. See
[`../risks-and-limitations.md`](../risks-and-limitations.md) §Spec
ambiguity vs rubric strictness.

## Preflight + first run

```bash
# 1. Validate YAML parses
python3 -c "import yaml; yaml.safe_load(open('evals/fixtures/0N-<slug>.yaml'))"

# 2. Contract evals still pass (catches missing fields, etc.)
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_learning_log.py

# 3. Run the fixture once to capture a baseline
bash evals/run.sh evals/fixtures/0N-<slug>.yaml > /tmp/0N-baseline.log 2>&1

# 4. Inspect baseline result
tail -20 /tmp/0N-baseline.log
cat evals/baselines/v<current-version>.json | jq '.fixtures[] | select(.fixture == "0N-<slug>")'

# 5. If passed: commit the fixture + baseline.
```

## Adherence + walk verification (v2.8.1+)

After the first run, verify:

```bash
# Was Step 7.5 executed?
grep -c "LEARNING_LOG_INIT:" <run.jsonl-path>     # should be ≥1

# Did the Reviewer emit SPEC_COVERAGE_WALK?
grep -c "SPEC_COVERAGE_WALK" <run.jsonl-path>     # should be ≥1 per Reviewer

# Did the walk include adversarial rows (sub-step B)?
# Inspect Reviewer output for at least 3 rows that are NOT direct quotes
# from the spec's Examples/Error cases sections.
```

If the walk is sparse or sub-step B is empty, the fixture's spec may
lack meta-rule signals — add a "strict" / "reject" / "must validate"
sentence to surface the adversarial-generation trigger.

## Commit

```bash
git add evals/fixtures/0N-<slug>.yaml evals/baselines/v<version>.json
git commit -m "test(kws-claude-multi-agent-executor): add fixture 0N — <one-line description>

Why: <one sentence — what failure mode this measures>.
Evidence: <pointer to learning-log event or finding that justifies adding>.

First-run baseline: <judge mean>, rubric <pass_rate>.
"
```

Then add a row to [`../experiments/`](../experiments/) if this fixture
was part of a v2.X experiment, and update HISTORY.md if shipping with a
version bump.

## Common pitfalls

- **Fixture too easy**: judge mean = 1.0 in n=1, no signal for
  regressions. Fix: add a subtle edge case or meta-rule that should
  catch implementation laziness.
- **Fixture too hard**: judge mean = 0.5 in n=4. Eval noise drowns
  signal. Fix: simplify or move to a separate "stretch" fixture file.
- **Bootstrap leaves dirty git tree**: orchestrator's Phase 0 dirty-tree
  check trips. Fix: bootstrap creates a single initial commit so the
  worktree starts clean.
- **`test_after` references binaries not in bootstrap**: run.sh's
  test invocation fails. Fix: bootstrap installs all required tools.
- **Plan task names don't match `expected_files_changed`**: orchestrator
  modifies file A but expected says file B. Fix: align the plan body's
  `**Files:**` list with the YAML's expected_files_changed.

## When to retire a fixture

If a fixture has been stable (no failures) across 3+ versions, it's a
ratchet — keeps the floor from regressing but rarely surfaces new info.
Don't retire; the cost is low.

Retire only if the underlying failure mode is structurally impossible
(e.g., the function was renamed or removed). Move retired fixtures to
`evals/fixtures/_archive/` with a `RETIRED.md` note explaining why.
