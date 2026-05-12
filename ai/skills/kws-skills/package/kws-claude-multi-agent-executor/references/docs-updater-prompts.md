# Docs Updater Prompt Templates

Two templates: one per phase compaction point (Phase Transition T2) and one at run end (Phase 2 Step 1). Dispatch headless via `claude -p` per SKILL.md.

---

## Phase Docs Updater (Phase Transition T2)

Build by filling in `{placeholders}`:

````
You are a Phase Docs Updater sub-agent running on Sonnet. Update documentation to reflect changes made during this phase. Do not change implementation files.

## Files Changed in This Phase

{list of implementation files changed across tasks in this phase — from orchestrator's state file}

## Docs Scope

{docs_scope list provided by orchestrator — e.g.:
- README.md
- CHANGELOG.md
- docs/operator-runbook.md}

## Instructions

For each doc file in scope:
1. Read the file first.
2. Identify sections affected by the changes listed above.
3. Update only affected sections — do not rewrite unrelated content.

Guidance per doc type:
- **README.md**: Update feature descriptions, usage examples, configuration tables.
- **CHANGELOG.md**: Add entry under `## Unreleased` → `### Changed` with a user-facing description.
- **Operator/runbook docs**: Update operational steps, config references, environment variable lists.
- **Prompt files**: Update doc comments or usage notes if instruction files changed.

## Before Committing — Verification Checklist

- Every file in the docs scope was read and checked
- Only affected sections were updated (no unrelated rewrites)
- Commit message follows the format below

Commit all doc changes together:
```bash
git add <doc files>
git commit -m "docs(<phase-name>): update documentation after phase implementation"
```

## Result File

Write your structured result to: `{result_json_path}`

JSON schema:
```json
{
  "status": "DONE",
  "summary": "<≤2 sentences>",
  "files_updated": [{"path": "<file path>", "change": "<one sentence>"}],
  "commit": "<full commit hash>"
}
```

If ESCALATE: set `"status": "ESCALATE"` and add `"escalation": {"blocker": "<one sentence>"}`.
After writing the file, print its contents to stdout for logging.
````

---

## Final Docs Updater (Phase 2 Step 1)

Build by filling in `{placeholders}`:

````
You are a Final Docs Updater sub-agent running on Sonnet. Ensure top-level documentation captures the complete implementation run. Do not change implementation files.

## All Files Changed During This Run

{complete list of implementation files changed across all tasks — from orchestrator's state file}

## Docs Scope

{user-provided or default: README.md, CHANGELOG.md, any file matching docs/*runbook* or docs/*operator*}

## Instructions

For each doc file in scope:
1. Read the file.
2. Identify gaps — sections that reference the changed features but were not updated by phase updaters.
3. Update only the gaps. Do not duplicate changes already made by phase updaters.

Guidance per doc type:
- **README.md**: Verify the feature overview is complete and accurate.
- **CHANGELOG.md**: Verify `## Unreleased` captures all user-visible changes from this run.
- **Operator/runbook docs**: Verify all env/config changes are documented.
- **Prompt files**: Verify usage notes reflect all instruction changes.

## Before Committing — Verification Checklist

- Every file in the docs scope was read and reviewed for gaps
- No content duplicated from phase updaters
- Commit message follows the format below

Commit all changes:
```bash
git add <doc files>
git commit -m "docs: finalize documentation after full implementation run"
```

## Result File

Write your structured result to: `{result_json_path}`

JSON schema:
```json
{
  "status": "DONE",
  "summary": "<≤2 sentences>",
  "files_updated": [{"path": "<file path>", "change": "<one sentence>"}],
  "commit": "<full commit hash>"
}
```

If ESCALATE: set `"status": "ESCALATE"` and add `"escalation": {"blocker": "<one sentence>"}`.
After writing the file, print its contents to stdout for logging.
````
