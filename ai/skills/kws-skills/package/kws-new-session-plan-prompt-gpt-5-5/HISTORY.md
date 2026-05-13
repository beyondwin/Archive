# Skill History - kws-new-session-plan-prompt-gpt-5-5

A two-axis summary of where this skill came from and what changed:

- **Section 1: Version timeline** - chronological version notes.
- **Section 2: Improvement areas** - grouped by topic, with versions that touched each area.
- **Section 3: Experiments** - active and closed experiment records.

Source of truth for current behavior: `SKILL.md` plus `templates/`.
This file is for humans navigating history and release intent.

Update protocol: see `references/change-protocol.md`.

---

## Section 1: Version Timeline

### v2.4.0 - Deprecated in favor of kws-codex-plan-executor (2026-05-13)

- Moved forward usage to `kws-codex-plan-executor mode=prompt`.
- Stopped maintaining a separate prompt-generation contract in this skill.
- Kept templates, eval fixtures, and historical notes for migration reference.

### v2.3.0 - Maintenance record scaffold (2026-05-13)

- Added this `HISTORY.md` as the skill-level narrative record.
- Added `ARCHITECTURE.md` for the synthesized current-state view.
- Added `references/change-protocol.md` so future edits have a consistent release, history, and validation loop.
- Added `evals/` pressure-scenario fixtures for prompt-generation regressions.
- Added `docs/experiments/` templates for larger or uncertain skill changes.
- Preserved the v2.2.8 recovery hardening in the release line.

### v2.2.8 - Recovery and cleanup hardening (2026-05-13)

- Added source-of-truth plan document git-status handling when generated prompts update plan checkboxes or status.
- Narrowed session-owned process cleanup to ledger-recorded PID/session id/port/worktree path evidence.
- Required cache-aware verification for test config, build input, test property, Dockerfile, migration, and generated-artifact input changes.
- Scoped doc safety/link scans to changed docs or added lines by default, separating existing false positives from newly introduced risk.
- Preserved default subagent implementation plus two-stage `gpt-5.5 high` review unless the user explicitly asks for lean/cost-optimized execution.

### v2.2.x - Conservative Spark and continuation recovery (2026-05-08 to 2026-05-09)

- Split Spark scout opt-in text into `templates/spark-scout-bullets.ko.txt`.
- Added conservative automatic Spark evidence packing while keeping implementation, review, root-cause, verification interpretation, and completion decisions on `gpt-5.5 high`.
- Added `.codex-orchestrator/session.json` as restart-critical state alongside human-readable `HANDOFF CHECKPOINT` text.
- Tightened prompt-only behavior, local path verification, placeholder removal, and continuation handoff handling.

### v2.1.x - Prompt body consolidation (2026-05-05 to 2026-05-08)

- Moved the fresh-session prompt body into `templates/fresh-session-prompt.txt`.
- Added `references/pre-send-checklist.md` and `references/common-mistakes.md`.
- Clarified workspace resolution, output language preservation, and optional document bullet removal.

### v2.0.0 - KWS rename (2026-04-30)

- Renamed the skill from `new-session-plan-prompt-gpt-5-5` to `kws-new-session-plan-prompt-gpt-5-5`.
- Kept the skill focused on generating paste-ready prompts rather than executing plans.

---

## Section 2: Improvement Areas

### Output contract

| Version | Change |
|---------|--------|
| v2.1.x | Single fenced `text` block default, strict prompt-only behavior, no unresolved template tokens |
| v2.2.x | Continuation handoff and session ledger requirements |
| v2.2.8 | Source-of-truth plan doc status handling |

### Model routing

| Version | Change |
|---------|--------|
| v2.2.x | Default quality-first `gpt-5.5 high`; conservative Spark evidence packing only |
| v2.2.8 | Lean/cost shortcuts forbidden unless explicitly requested |

### Verification and recovery

| Version | Change |
|---------|--------|
| v2.1.x | Pre-send checklist and common mistake reference |
| v2.2.x | Risk-scaled verification and ENV_BLOCKER triage rules |
| v2.2.8 | Cache-aware targeted checks and scoped doc scans |

### Maintainability

| Version | Change |
|---------|--------|
| v2.3.0 | Added history, architecture, change protocol, eval fixtures, and experiment templates |

---

## Section 3: Experiments

Each significant experiment gets its own subdirectory under `docs/experiments/`.

| Experiment | Status | Outcome | Path |
|------------|--------|---------|------|
| (future) | | | `docs/experiments/<version>-<name>/` |

See `docs/experiments/README.md` for the experiment protocol.

---

## How To Read This File Vs Other Artifacts

- `SKILL.md` frontmatter `metadata.version` - current shipped skill version.
- `ARCHITECTURE.md` - current-state design of how the skill works.
- `references/change-protocol.md` - how to edit this skill safely.
- `evals/` - pressure scenarios used to catch regressions.
- `docs/experiments/` - records for non-trivial changes, including negative results.
- `../../CHANGELOG.md` - package-level user-facing release notes.
