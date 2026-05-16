# Evals And Verification

This skill has deterministic checks for parser behavior, state schema,
learning-log contracts, prompt/runtime contract drift, and real headless
execution fixtures.

## Fast Checks

Run from the skill directory:

```bash
python3 scripts/parse_plan.py --help
python3 scripts/build_context_snapshot.py --help
python3 scripts/validate_state.py --help
python3 scripts/check_learning_log_health.py --help
python3 scripts/check_learning_log_health.py --latest 5 --json
python3 evals/check_state_schema.py
python3 evals/check_run_diffs.py
python3 evals/check_event_journal.py
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

These checks do not launch real executor sessions. Use them first while editing
scripts, docs, or contracts.

After running verification for a package change, append a compact entry to
[verification-log.md](verification-log.md). Record command, result, skipped
checks, and residual risk; do not paste long logs.

## Parser Fixtures

Parser fixtures live in:

```text
evals/parser-fixtures/*.yaml
```

Run one fixture:

```bash
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/03-hidden-task-in-fence.yaml
```

Run all parser fixtures:

```bash
for fixture in evals/parser-fixtures/*.yaml; do
  python3 evals/check_parse_plan.py --fixture "$fixture"
done
```

Current parser fixture themes:

- required visible `Files` blocks
- English and Korean file-block aliases
- hidden task/file markers inside fenced code or comments
- visible parsing after a closed fence
- optional `Depends on:` metadata
- dependency cycle rejection

Add a parser fixture whenever `scripts/parse_plan.py` changes.

## State Schema Checks

`evals/check_state_schema.py` verifies `scripts/validate_state.py` against valid
and invalid state payloads. It covers:

- required top-level fields
- run-local `run_dir` and `state_path`
- task contract shape
- retry count types
- execution context snapshot requirements
- context health shape, finished-run handoff readiness, and terminal
  `last_checked_at` freshness
- lifecycle outcomes
- completion audit proof
- non-success `handoff_reason`
- `unit_manifest` enum, write-scope, and terminal-completion requirements

Add or update these cases whenever `references/state-schema.md` changes.

## Diff Policy Checks

`evals/check_run_diffs.py` creates temporary git repositories and verifies
`scripts/check_run_diffs.py` against changed files from the worktree, index,
and untracked set. It covers:

- changed file allowed by both task contract and manifest
- changed file outside `allowed_edits`
- changed file matching forbidden globs
- read-only manifest with no changed files
- docs policy allowing `docs/**`

Add cases here whenever the post-diff policy changes.

## Event Journal Checks

`evals/check_event_journal.py` verifies `scripts/append_run_event.py` and the
terminal state metadata expected for project-local `events.jsonl`. It covers:

- first append creates `events.jsonl` and sets `last_event_seq=1`
- second append increments sequence
- payload run-id mismatch rejection
- secret-like payload key redaction and long-string truncation
- finished state rejecting missing or stale event journal metadata

Add cases here when event types, redaction policy, or terminal event metadata
changes.

## Learning Log Checks

`evals/check_learning_log.py` validates helper behavior around:

- `init-run`
- `append`
- `close-run`
- event schema
- event type and severity enums
- redaction guardrails
- run identity isolation
- `run_dir` and `state_path` consistency
- terminal outcome health reporting
- project-state-aware run classification
- helper-pid diagnostics without stale classification
- stale candidate classification from old inactive project state
- missing worktree and project-state diagnostics
- git worktree dirty-state summaries
- zero-event success semantics

Add checks here when changing `scripts/append_learning_event.py` or
`scripts/check_learning_log_health.py` or [state-and-logging.md](state-and-logging.md).

## Contract Drift Checks

`evals/check_skill_contract.py` scans `SKILL.md`, templates, and references for
hard contract tokens. It is intentionally blunt: if a runtime invariant is
removed from one surface but not the others, the check should fail.

It currently protects:

- resume ambiguity handling
- task contract before edits
- dirty worktree classification
- per-run state layout
- headless artifact setup
- headless skill bootstrap
- learning-log lifecycle and privacy
- context snapshot contract
- context health contract
- completion audit contract
- lifecycle outcome contract
- high-risk verification matrix guidance
- mandatory dedicated `codex/...` worktree isolation and no-main execution

When adding a new cross-surface invariant, add a contract check here.

## Execution Fixtures

Full fixture runs are driven by:

```bash
bash evals/run.sh
```

The harness:

1. creates a temporary git repository
2. writes fixture `plan.md`, `spec.md`, docs, initial state, and dirty files
3. launches `codex exec`
4. captures `.harness/run.jsonl` and `.harness/final.md`
5. runs `check_prompt.py` for prompt/handoff modes or `check_execution.py` for
   interactive/headless modes
6. writes `evals/baselines/v<skill-version>.json`

Execution fixtures must not be inspected by the target executor. The harness
prompt forbids the target from reading fixture YAML, baselines, `.harness`
metadata, or expected values. The target may use only the plan/spec/docs,
repository files, skill references, and scripts.

## Execution Checker

`evals/check_execution.py` verifies the resulting temporary repo. It checks:

- state file exists unless the fixture explicitly allows no state
- state validates with `scripts/validate_state.py`
- expected files changed
- forbidden files did not change
- no out-of-scope changes except allowed orchestrator artifacts
- tasks reached complete or expected blocked status
- context snapshot exists for execution runs after preflight
- successful terminal runs set `lifecycle_outcome=finished`
- successful terminal runs include passing `completion_audit`
- optional final-output expectations
- optional forbidden log patterns

Use this checker for real execution behavior, not as a script the target run
calls from inside the fixture.

## Prompt Checker

`evals/check_prompt.py` verifies prompt and handoff output. It should catch
placeholder leakage, missing path grounding, mode contract drift, and forbidden
prompt content.

Use prompt fixtures when changing:

- [../templates/fresh-session-prompt.txt](../templates/fresh-session-prompt.txt)
- [../references/prompt-export-checklist.md](../references/prompt-export-checklist.md)
- prompt/handoff behavior in [../SKILL.md](../SKILL.md)

## When To Run Which Check

| Change type | Minimum checks |
| --- | --- |
| Parser regex or plan metadata | parser fixtures, `py_compile` |
| State schema or validator | `check_state_schema.py`, `validate_state.py --help` |
| Learning log helper | `check_learning_log.py`, helper `--help` |
| Prompt template | `check_prompt.py` fixture or checklist, contract check |
| Runtime docs or hard invariant | `check_skill_contract.py`, relevant narrow check |
| Headless/eval behavior | `bash evals/run.sh` or the affected fixture |
| Package sync behavior | `../../tests/test-sync.sh` |

For release-level behavior changes, run all fast checks plus affected execution
fixtures. For docs-only changes, run `quick_validate.py` and the contract check
if the docs mention runtime invariants.

Local environment preflight guidance is documentation-only today. Verify those
changes by checking the relevant reference text and running the contract check
when wording is promoted into `SKILL.md` or prompt/runtime templates.

Docker and Gradle resource triage is also policy guidance today. Verify edits by
checking that the failure categories and learning-event guidance remain aligned
between [../references/execution-cycle.md](../references/execution-cycle.md)
and [../references/common-mistakes.md](../references/common-mistakes.md).

## Baselines

Baseline files are generated under:

```text
evals/baselines/v<skill-version>.json
```

Update baselines only when behavior intentionally changes. Do not train the
target executor on baseline contents; they are outer-harness artifacts.
