# Experiments - kws-new-session-plan-prompt-gpt-5-5

Each non-trivial change to this skill that has a hypothesis to test, a
non-obvious trade-off, or could produce a negative result gets its own
experiment record here.

Small bug fixes and obvious wording clarifications do not need an experiment
record. A git commit plus `HISTORY.md` entry is enough.

## Index

| Experiment | Status | Outcome | Records |
|------------|--------|---------|---------|
| _(future experiments listed here)_ | | | |

## When To Start An Experiment Record

Open `docs/experiments/<version>-<short-name>/` when any of these are true:

- You are about to make a `SKILL.md` or template behavior change of roughly 50
  lines or more.
- You have a hypothesis that could be wrong.
- The change alters model routing, continuation behavior, verification
  semantics, or prompt output shape.
- The change requires a new fixture or scoring method.
- Cost is expected to exceed 1 hour of substantive work.

## Structure

```text
docs/experiments/<version>-<name>/
  README.md
  JOURNAL.md
  decisions/
    D001-<topic>.md
  findings/
    F001-<topic>.md
    Fnn-close-out.md
```

Use `_template/` as the starting point.

## Close-Out Requirements

1. Write a close-out finding with explicit ship, skip, or pivot decision.
2. Update the experiment README status and findings index.
3. Update this README index.
4. Update `../../HISTORY.md` Section 3.
5. If behavior ships, update `../../ARCHITECTURE.md` when the changed area is
   part of the current architecture.
