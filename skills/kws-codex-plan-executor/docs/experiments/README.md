# Experiments

Use this directory for non-trivial behavior changes, risky migrations, or eval
results that should be preserved beyond one session.

Create one directory per experiment:

```text
docs/experiments/YYYY-MM-DD-short-name/
  PLAN.md
  IMPLEMENTATION.md
  README.md        # optional
  JOURNAL.md       # optional
  decisions/       # optional
  findings/        # optional
```

Record only facts that help future maintainers: hypothesis, setup, commands,
outputs, decisions, and follow-up risks.

## Current Records

| Date | Record | Purpose |
| --- | --- | --- |
| 2026-05-16 | [2026-05-16-gsd-2-adoption](2026-05-16-gsd-2-adoption/PLAN.md) | v1.9.0 selective adoption of GSD-2 execution safeguards: unit manifests, event journal, drift reconciliation, context budget, headless result schema, opt-in subagent run store, and command observations. |
| 2026-05-14 | [2026-05-14-run-lifecycle-drift-hardening](2026-05-14-run-lifecycle-drift-hardening/PLAN.md) | Run lifecycle, drift, and context health hardening. |
| 2026-05-14 | [2026-05-14-log-driven-executor-hardening](2026-05-14-log-driven-executor-hardening/PLAN.md) | Learning-log and verification-resource hardening. |
| 2026-05-14 | [2026-05-14-oh-my-codex-adoption](2026-05-14-oh-my-codex-adoption/PLAN.md) | Initial Codex plan executor adoption and implementation notes. |
