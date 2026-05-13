# Future Agent Guide

Use this guide when maintaining or extending `kws-codex-plan-executor`.

## First Checks

Before editing:

1. Read [../SKILL.md](../SKILL.md) for current runtime invariants.
2. Read [../references/change-protocol.md](../references/change-protocol.md).
3. Read the relevant topic document:
   - runtime flow: [how-it-works.md](how-it-works.md)
   - state/logs: [state-and-logging.md](state-and-logging.md)
   - evals: [evals-and-verification.md](evals-and-verification.md)
   - decisions: [decisions.md](decisions.md)
   - risks: [risks-limitations-deferrals.md](risks-limitations-deferrals.md)
4. Check `git status --short` and preserve unrelated user changes.

## Change Classification

Classify the change before editing:

| Change | Update required |
| --- | --- |
| Runtime behavior | `SKILL.md`, references, deterministic eval, `HISTORY.md`, package metadata |
| Prompt export behavior | template, prompt checklist, contract check, prompt fixtures |
| State schema | `references/state-schema.md`, `validate_state.py`, `check_state_schema.py` |
| Learning log schema | `references/learning-log.md`, helper script, `check_learning_log.py` |
| Parser behavior | parser script, parser fixture, parser checker |
| Docs only | README/docs, optional `quick_validate.py`, no version bump unless policy changes |

Keep detailed contracts out of `SKILL.md` unless the executor must load them on
every use. Prefer `references/` for runtime detail and `docs/` for maintainer
explanations.

## Safe Edit Loop

1. Add or update the narrow deterministic check first when behavior changes.
2. Make the smallest code or document change that satisfies the contract.
3. Run the narrow check.
4. Run `evals/check_skill_contract.py --skill SKILL.md` if an invariant changed.
5. Run package validation before finalizing.
6. Update `HISTORY.md` and package metadata only for behavior or release
   changes.

## Minimum Verification By Area

Parser:

```bash
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/<fixture>.yaml
python3 -m py_compile scripts/parse_plan.py evals/check_parse_plan.py
```

State:

```bash
python3 evals/check_state_schema.py
python3 -m py_compile scripts/validate_state.py evals/check_state_schema.py
```

Learning log:

```bash
python3 evals/check_learning_log.py
python3 -m py_compile scripts/append_learning_event.py evals/check_learning_log.py
```

Prompt/runtime contract:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
```

Skill package:

```bash
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
../../tests/test-sync.sh
```

Full execution fixtures:

```bash
bash evals/run.sh
```

Use full execution fixtures for behavior changes that affect real executor
outcomes. They launch actual `codex exec` runs, so they are slower than unit
checks.

## How To Add A Parser Fixture

Create `evals/parser-fixtures/NN-short-name.yaml`:

```yaml
name: short-name
mode: interactive
plan: |
  ### Task 0: Example

  Files:
  - Modify: docs/example.md
expected:
  files:
    - docs/example.md
```

Run:

```bash
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/NN-short-name.yaml
```

Add negative fixtures when the parser should reject a plan. Prefer one concept
per fixture.

## How To Add An Execution Fixture

Create `evals/fixtures/NN-short-name.yaml` with only the test repository inputs
the target executor should see. Expected values are for the outer harness and
must not be leaked into prompts.

Then run:

```bash
bash evals/run.sh evals/fixtures/NN-short-name.yaml
```

The target executor must not read fixture YAML, baseline files, `.harness`
metadata, or expected values.

## Suggested Next Improvements

1. Add resume-time source drift detection: compare live plan/spec/docs hashes
   against `context.json` and warn or block based on risk.
2. Strengthen `completion_audit` quality checks: require artifact paths and
   command/status objects instead of accepting any non-empty list.
3. Add a `summarize_state.py` helper for humans and agents to inspect active
   run status without manually reading JSON.
4. Add a package-local Markdown link check for README/docs/reference links.
5. Add parser fixtures for malformed fences, nested comments, mixed-language
   headings, and `Depends on:` variants.
6. Add learning-log redaction fixtures using realistic command-output excerpts.

## Do Not Do This

- Do not move detailed maintainer rationale into `SKILL.md`.
- Do not weaken prompt export just because interactive mode is locally safe.
- Do not write learning events into the target repository.
- Do not use root `.codex-orchestrator/state.json` as the only active state.
- Do not make subagents default without a deliberate policy change and evals.
- Do not update baselines to hide a regression.
