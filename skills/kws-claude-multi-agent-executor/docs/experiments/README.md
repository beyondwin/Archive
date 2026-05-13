# Experiments — kws-claude-multi-agent-executor

Each non-trivial change to this skill that has a hypothesis to test, a non-obvious
trade-off, or could produce a negative result gets its own experiment record here.

Small bug fixes and obvious improvements don't need an experiment record — a
git commit + CHANGELOG entry is enough.

## Index

| Experiment | Status | Outcome | Records |
|------------|--------|---------|---------|
| `v2.7-quality-mode` | **CLOSED** (2026-05-13) | Negative on `quality_plus`; positive on rubric infrastructure | [v2.7-quality-mode/](./v2.7-quality-mode/) |
| _(future experiments listed here)_ | | | |

## When to start an experiment record

Open a new `docs/experiments/<version>-<short-name>/` subdirectory when **any** of:

- You are about to make a SKILL.md change ≥ 50 lines, or a multi-file behavioral change
- You have a hypothesis that could be wrong (e.g., "best-of-N improves quality")
- The change requires designing a fixture or evaluation method
- You expect to need user clarification, advisor calls, or external review
- Cost > $20 in API or > 1 hour of substantive work

If the change is mechanical (rename, typo fix, dependency bump): just commit. No experiment record needed.

## Structure (use the template)

Every experiment subdirectory follows this layout:

```
docs/experiments/<version>-<name>/
├── README.md              # one-page overview + status + decisions index
├── JOURNAL.md             # chronological narrative of work
├── decisions/             # one short ADR per major decision
│   ├── D001-<topic>.md
│   ├── D002-<topic>.md
│   └── ...
└── findings/              # results, data, close-out documents
    ├── F001-<topic>.md
    ├── F002-close-out.md  # final summary with ship/skip recommendation
    └── <raw-data-files>
```

See `_template/` for a starter scaffold.

## Required documents

At close-out, every experiment record must have:

1. **README.md** — current-status block + index of decisions + index of findings
2. **JOURNAL.md** — chronological log with timestamps, including:
   - Initial problem framing
   - Each major decision with reasoning
   - Each advisor review (capture the actual advice, don't paraphrase)
   - Each pivot or scope change with reason
   - Final close-out
3. **At least one findings/ document** — what data was collected, what was decided
4. **Close-out finding** (`Fnn-close-out.md` or similar) — explicit decision: ship / skip / pivot

## Documentation protocol (for the agent running the experiment)

- Update JOURNAL **as you go**, not at the end. Future-you and future-others
  need to know *what you were thinking when*, not just the outcome.
- Write ADRs (`D###-<topic>.md`) for any decision that:
  - Couldn't be made from existing code alone (required judgment)
  - Could plausibly be revisited later
  - Was rejected (record the rejection reason — equally valuable)
- Commit messages reference ADR IDs: e.g., `feat(skill): X (per D003)`.
- When close-out happens, update the index in this README and in
  `../HISTORY.md` §3.

## Closing an experiment

1. Write `findings/Fnn-close-out.md` with final recommendation
2. Update the experiment's own `README.md` status to CLOSED + outcome
3. Update this file's index table
4. Update `HISTORY.md` §3 if not already
5. Commit with message `docs(experiment): close-out v<X.Y>-<name> — <outcome>`
6. If branch-only: leave branch open as artifact. If anything from the experiment
   ships, separate cherry-pick commit(s) to main referencing the close-out.

## When you DON'T close an experiment

If you pause work without closing: leave JOURNAL with a "PAUSED YYYY-MM-DD"
entry stating *what's left to do, what's blocked, why*. Future-you needs to
resume from cold context.
