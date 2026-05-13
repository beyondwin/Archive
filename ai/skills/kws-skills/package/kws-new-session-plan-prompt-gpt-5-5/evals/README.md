# Evaluation Fixtures - kws-new-session-plan-prompt-gpt-5-5

Pressure scenarios for the prompt generator skill.

These fixtures are intentionally lightweight. They document the user request,
available paths, expected generated-prompt properties, and known regression
risk. They can be checked manually, by a reviewer, or by a future runner.

## Layout

```text
evals/
  README.md
  fixtures/
    01-prompt-only-plan.yaml
    02-continuation-session.yaml
    03-no-spark.yaml
    04-source-plan-status.yaml
    05-unreadable-doc.yaml
```

## Scoring Axes

Each fixture should be evaluated on:

- `paths`: uses only verified real paths; no placeholders.
- `output_shape`: honors prompt-only and language requirements.
- `invariants`: includes required execution blocks from `SKILL.md`.
- `model_routing`: preserves `gpt-5.5 high` ownership and Spark constraints.
- `verification`: includes risk-scaled, honest verification and ENV_BLOCKER
  triage.
- `overreach`: does not start implementation, create a plan, or invent docs.

Pass requires every applicable axis to be satisfied. A fixture may mark an axis
as not applicable only when the scenario cannot exercise it.

## When To Add A Fixture

Add or update a fixture when a change touches:

- Template tokens or optional document bullets.
- Prompt-only behavior.
- Workspace or path inference.
- Spark/model routing.
- Continuation handoff.
- Worktree, plan-progress, cleanup, verification, or doc-impact rules.

## Current Harness Status

No automated runner exists yet. Treat these fixtures as review cases. If an
automated runner is added, update `ARCHITECTURE.md` Section 6 and this README in
the same change.
