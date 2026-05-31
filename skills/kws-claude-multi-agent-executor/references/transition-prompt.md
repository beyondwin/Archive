# Combined Transition Prompt Template (T1.2)

Build by filling in `{placeholders}`. Dispatch headless via `claude -p --dangerously-skip-permissions` (not the Agent tool) per the dispatch pattern in SKILL.md Phase 1 Step 3 / Phase Transition T1.2. This single dispatch replaces the former back-to-back T1 (batch Verifier) and T2 (Phase Docs Updater) — v2.22 §2.A2. The sub-agent issues BOTH tool calls in one turn.

The two tool specs are defined in `references/_schemas/transition_combined_result.schema.json` (`tools[0]` = `verify_low_batch`, `tools[1]` = `update_phase_docs`).

````
You are a Combined Transition sub-agent running on Sonnet. In a SINGLE turn you perform two jobs: (1) batch-verify all accumulated LOW tasks since the last compaction point, and (2) update phase documentation. Do not modify any implementation files.

## Required Skills

1. **First action:** invoke `Skill("superpowers:using-superpowers")` before deriving, running, or judging anything. Follow it as the skill-discovery gate for this combined dispatch. If that skill says to skip itself because you are a sub-agent, continue with the role-specific required skills below; that skip does not waive the verification skill.

2. **Before running verification and before reporting `status: "DONE"` on docs:** invoke `Skill("superpowers:verification-before-completion")` so both the PASS / FAIL decision and the docs-done decision apply evidence-before-assertion standards. Run the commands and confirm output before deciding.

## Combined Dispatch — Call BOTH Tools In One Turn

Issue both tool calls in this single turn:
- `verify_low_batch` — the batch Verifier for accumulated LOW tasks.
- `update_phase_docs` — the Phase Docs Updater.

Run `verify_low_batch` first so its outcome is known, then `update_phase_docs`. Emit both tool calls in the same turn — do not wait for a second dispatch.

### Tool 1: `verify_low_batch`

Inputs:
- Risk level: `LOW (BATCH)`
- Files changed: {all files from all accumulated LOW tasks since the last compaction point}
- Baseline (do not introduce new failures beyond this): Passing {N} | Failing {M} — from Phase 0
- Test command: `{test_command}` — use this exact command; do not re-derive.
- Acceptance: "run all test files for changed files combined".

Identify test files covering each changed file (`test_<filename>` or `<filename>_test` patterns), run `{test_command}` scoped to those test files, and confirm no new failures vs baseline. Output a `verify` result with `status` (`PASS` | `FAIL` | `ESCALATE`), `commands_run`, and `exit_codes`. On FAIL, add `issues` and an optional `category` from `references/escalation-playbook.md`.

### Tool 2: `update_phase_docs`

Inputs:
- Files changed in this phase: {all implementation files changed across tasks since `last_compaction_after_task`}
- Docs scope: {user-provided or default — README.md, CHANGELOG.md, docs/*runbook*, docs/*operator*}

For each doc file in scope: read it, identify the sections affected by the changes above, and update only those sections. Commit the docs together:
```bash
git add <doc files>
git commit -m "docs(<phase-name>): update documentation after phase implementation"
```
Output a `docs` result with `status` (`DONE` | `ESCALATE`), `summary`, `files_updated`, and `commit`. On ESCALATE add `escalation.blocker`.

## Guardrail — Verify-Before-Commit Coupling

If `verify_low_batch` returns FAIL (any LOW task failing): still produce the `docs` result, but DO NOT commit the docs — leave them staged or unwritten. The orchestrator sets `state.transition_blocked = true` and skips the docs commit until the verifier is re-dispatched and passes. Report the docs work you would have committed in `docs.summary` and leave `docs.commit` empty.

## Result File

Write the combined result to: `{result_json_path}` (the orchestrator targets `<orch_dir>/transition_results/<plan_idx>_<compaction_idx>.json`).

### Combined Result JSON

```json
{
  "verify": {
    "status": "PASS" | "FAIL" | "ESCALATE",
    "commands_run": ["<cmd1>", "..."],
    "exit_codes": [0, "..."],
    "issues": [],
    "category": "other"
  },
  "docs": {
    "status": "DONE" | "ESCALATE",
    "summary": "<≤2 sentences>",
    "files_updated": [{"path": "<file>", "change": "<one sentence>"}],
    "commit": "<full commit hash or empty when verify FAILed>"
  }
}
```

The shape is contracted in `references/_schemas/transition_combined_result.schema.json`. After writing the file, print its contents to stdout for logging.

## Learning log emit (v2.8)

If the `verify` result is FAIL or ESCALATE, also write a learning-event candidate to `<orch_dir>/learning_events/batch-verifier.json` (per the Verifier template's "Learning log emit" section). Do not call the helper script yourself — the orchestrator scans the directory and invokes `append`. Use relative paths only.
````
