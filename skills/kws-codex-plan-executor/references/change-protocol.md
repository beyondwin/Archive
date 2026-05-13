# Change Protocol

Use this when editing `kws-codex-plan-executor`.

## Before Editing

- Identify whether the change affects runtime behavior, prompt export,
  headless execution, evals, or metadata only.
- Add or update a deterministic eval/check when behavior changes.
- Read `docs/doc-update-protocol.md` and identify which docs must be updated
  before finalizing.
- Preserve prompt-export invariants documented in `templates/` and
  `references/prompt-export-checklist.md` unless the change explicitly updates
  those contracts.

## Edit Boundaries

- Keep runtime trigger and mode selection in `SKILL.md`.
- Keep detailed contracts in `references/`.
- Keep reusable deterministic checks in `scripts/` or `evals/`.
- Keep long-lived rationale in `ARCHITECTURE.md` or `HISTORY.md`.
- Keep maintainer-facing explanations, verification history, and follow-up
  guidance in `docs/`.

## Release Updates

For behavior changes, update:

- `SKILL.md` metadata
- `HISTORY.md`
- `ARCHITECTURE.md` when contracts or flow changed
- `README.md`
- affected files under `docs/`, `references/`, `templates/`, and `evals/`

For every package change, update or explicitly check:

- `README.md` when the reading path or public package overview changes.
- `docs/doc-update-protocol.md` when the maintenance workflow changes.
- `docs/evals-and-verification.md` when commands, fixtures, or harness behavior
  change.
- `docs/verification-log.md` with compact evidence for commands run and checks
  skipped.
- `docs/decisions.md` or `docs/risks-limitations-deferrals.md` when a change
  introduces a durable rationale, tradeoff, risk, limitation, or deferral.

## Verification

Run the narrowest relevant checks first, then package checks:

```bash
python3 scripts/parse_plan.py --help
python3 scripts/validate_state.py --help
python3 evals/check_prompt.py --help
python3 evals/check_execution.py --help
python3 evals/check_parse_plan.py --help
python3 evals/check_state_schema.py
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --help
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

After verification, append the command outcomes and any skipped-check rationale
to `docs/verification-log.md` before finalizing the change.
