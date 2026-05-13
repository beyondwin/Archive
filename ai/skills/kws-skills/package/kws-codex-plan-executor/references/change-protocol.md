# Change Protocol

Use this when editing `kws-codex-plan-executor`.

## Before Editing

- Identify whether the change affects runtime behavior, prompt export,
  headless execution, evals, or metadata only.
- Add or update a deterministic eval/check when behavior changes.
- Preserve prompt-export invariants inherited from
  `kws-new-session-plan-prompt-gpt-5-5` unless the change explicitly removes
  them.

## Edit Boundaries

- Keep runtime trigger and mode selection in `SKILL.md`.
- Keep detailed contracts in `references/`.
- Keep reusable deterministic checks in `scripts/` or `evals/`.
- Keep long-lived rationale in `ARCHITECTURE.md` or `HISTORY.md`.

## Release Updates

For behavior changes, update:

- `SKILL.md` metadata
- `HISTORY.md`
- `ARCHITECTURE.md` when contracts or flow changed
- `../../manifest.json`
- `../../README.md`
- `../../CHANGELOG.md`

## Verification

Run the narrowest relevant checks first, then package checks:

```bash
python3 scripts/parse_plan.py --help
python3 scripts/validate_state.py --help
python3 evals/check_prompt.py --help
python3 evals/check_execution.py --help
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
../../tests/test-sync.sh
```
