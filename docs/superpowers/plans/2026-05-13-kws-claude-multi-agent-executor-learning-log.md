# KWS Claude Multi-Agent Executor Learning Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` only when the user explicitly asks for subagents, delegation, parallel work, or `subagents=on`. Otherwise implement this plan in the current session task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add execution-only, per-run sharded JSONL learning logs to `kws-claude-multi-agent-executor` so notable boundaries across orchestrator and sub-agents can drive future skill improvements; close the review-side superpowers gap by adding `Skill("superpowers:...")` invocations to Plan Reviewer / Reviewer / Verifier prompts.

**Architecture:** Per-run directory under `~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/` containing `meta.json` (run metadata, including `session_ids[]` for Resume Chain handoffs) and `events.jsonl` (one redacted JSON object per line). Helper script has four idempotent subcommands: `init-run` / `append` / `close-run` / `append-session-id`. **The orchestrator is the only process that invokes the helper**; sub-agents write event candidate JSON files under `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json` and the orchestrator forwards them to `append`. `MAE_LEARNING_RUN_ID` env propagation is only required for Resume Chain handoff (`claude -p` subprocess spawn). Concurrent runs are isolated by directory, not by lock. `close-run` is called from every orchestrator exit path (success / blocked / aborted).

**Tech Stack:** Claude Code skill Markdown, Python 3 standard library, JSONL, deterministic eval scripts, shell package tests.

---

## Source Documents

- Spec: `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-learning-log-design.md`
- Experiment record: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/docs/experiments/v2.8-learning-log/`
- D001 (initial design decisions): `docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md`
- Existing skill package: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/`
- AGENTS.md protocol: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/AGENTS.md`
- Sibling pattern (Codex): `docs/superpowers/plans/2026-05-13-kws-codex-plan-executor-learning-log.md`

## Scope And Non-Goals

In scope:

- Add `scripts/append_learning_event.py` (3 subcommands).
- Add deterministic tests in `evals/check_learning_log.py`.
- Add `references/learning-log.md`.
- Update runtime instructions for Phase 0 / Phase 1 / Phase Transition / Phase 2 notable-boundary logging.
- Update `references/{implementer,reviewer,verifier,plan-reviewer}-prompt.md` for event emission.
- Add `Skill("superpowers:writing-plans")` to Plan Reviewer, `Skill("superpowers:requesting-code-review")` to Reviewer, `Skill("superpowers:verification-before-completion")` to Verifier.
- Update `references/escalation-playbook.md` so escalations link to event emission.
- Add new contract checks (`evals/check_skill_contract.py` if absent, otherwise extend) and wire into `evals/run.sh`.
- Update `SKILL.md` core invariants and Phase docs.
- Update `ARCHITECTURE.md` (§14 Learning Log Contract) per its §13 update protocol.
- Update `HISTORY.md` with v2.8.0 entry.
- Update `AGENTS.md` with learning-log operational protocol.
- Update manifest, README, CHANGELOG, baseline (if applicable).

Out of scope:

- Headless `--model` flag fix (separate v2.8.x mini-PR).
- Aggregator / reporting CLI.
- SubagentStop hook for automatic event pre-staging.
- Learning-log → experiment auto-trigger.
- Cross-machine syncing.
- Repository-local learning logs.

## File Structure

Create:

- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/learning-log.md`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_skill_contract.py` (if not already present; spec calls for it)

Modify:

- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md` — Core Invariants + Phase 0/1/Transition/2 boundary calls; bump version 2.6.0 → 2.8.0
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/implementer-prompt.md` — emit guidance for `verification_failure`, `escalation`, `successful_workaround`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/reviewer-prompt.md` — `Skill("superpowers:requesting-code-review")` + emit guidance for `reviewer_warn_or_fail`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/verifier-prompt.md` — `Skill("superpowers:verification-before-completion")` + emit guidance for `verification_failure`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/plan-reviewer-prompt.md` — `Skill("superpowers:writing-plans")` + emit guidance for plan `blocker`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/escalation-playbook.md` — escalation → event mapping
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/run.sh` — invoke `check_learning_log.py` + `check_skill_contract.py`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/ARCHITECTURE.md` — §14 Learning Log Contract + update §13 trigger list
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/HISTORY.md` — v2.8.0 entry
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/AGENTS.md` — learning-log operational protocol
- `ai/skills/kws-skills/manifest.json` — package 2.10.1 → 2.11.0, executor 2.6.0 → 2.8.0
- `ai/skills/kws-skills/README.md` — current version table
- `ai/skills/kws-skills/CHANGELOG.md` — `2.11.0` entry

## Task 0: Preflight And Branch State

**Files:**
- Read: `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-learning-log-design.md`
- Read: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md`
- Read: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/AGENTS.md`

- [ ] **Step 1: Confirm working tree state**

```bash
git status --short
git branch --show-current
```

Expected: branch is `codex/executor-learning-log` (or a new branch off it for Claude isolation if user requests). Only Claude executor files should be staged at any commit; do not co-mingle with Codex sibling changes in a single commit.

- [ ] **Step 2: Confirm current version targets**

```bash
python3 - <<'PY'
import json, re
from pathlib import Path
manifest = json.loads(Path("ai/skills/kws-skills/manifest.json").read_text())
skill = Path("ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md").read_text()
print("package", manifest["version"])
print("executor", re.search(r'(?m)^  version: "([^"]+)"', skill).group(1))
PY
```

Expected:

```text
package 2.10.1
executor 2.6.0
```

- [ ] **Step 3: Read the approved spec**

Verify the spec exists and contains `execution-only`, `notable-boundaries`, `redacted-context`, `per-run sharded layout`, and `MAE_LEARNING_RUN_ID`.

## Task 1: Add Failing Helper Eval (TDD)

**Files:**
- Create: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py`

- [ ] **Step 1: Write the deterministic helper eval**

Implement the 13 checks listed in the spec's §Testing section. Sketch:

```python
#!/usr/bin/env python3
"""Deterministic checks for append_learning_event.py."""

from __future__ import annotations
import json, subprocess, sys, tempfile, os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "append_learning_event.py"

def base_event(run_id: str) -> dict:
    return {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-claude-multi-agent-executor",
        "skill_version": "2.8.0",
        "phase": "phase_1",
        "risk_tier": "MID",
        "event_type": "reviewer_warn_or_fail",
        "severity": "medium",
        "execution": {"task_id": "task_3", "wave": 2, "compaction_index": 1,
                      "issue_key": "review_retry_quality_low"},
        "scores": {"spec_score": 0.82, "quality_score": 0.71, "tier": "WARN"},
        "subagent": {"role": "reviewer", "model": "sonnet", "dispatch": "agent_tool"},
        "summary": "Combined Reviewer returned WARN; quality_score below 0.75.",
        "context": {
            "user_intent": "Add JSON config parsing.",
            "agent_expectation": "Reviewer would PASS.",
            "actual_outcome": "WARN tier.",
            "root_cause": "Happy-path tests only.",
            "evidence": [{"kind": "relative_path", "value": "src/config.py"}],
        },
        "improvement": {"target": "references/reviewer-prompt.md",
                        "proposal": "Cite specific missing test category.",
                        "experiment_link": None},
        "privacy": {"redacted": True, "notes": "Worktree path relativized."},
    }

# ... 13 deterministic checks ...
```

Implement all 13 checks per the spec. Each check returns boolean; failure list populated.

- [ ] **Step 2: Run the eval and confirm it fails**

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py
```

Expected: FAIL because `scripts/append_learning_event.py` does not exist.

- [ ] **Step 3: Commit the failing eval**

```bash
git add ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py
git commit -m "test(kws-claude-multi-agent-executor): add learning log eval"
```

## Task 2: Implement Learning Event Helper

**Files:**
- Create: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py`
- Test: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py`

- [ ] **Step 1: Write the helper script**

Three subcommands: `init-run` / `append` / `close-run`. Sketch:

```python
#!/usr/bin/env python3
"""Per-run sharded learning event helper for kws-claude-multi-agent-executor."""

from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, socket, sys
from pathlib import Path
from typing import Any

DEFAULT_LOG_ROOT = Path("~/.claude/learning/kws-claude-multi-agent-executor").expanduser()
VALID_PHASES = {"phase_0", "phase_1", "phase_transition", "phase_2"}
VALID_RISK_TIERS = {"LOW", "MID", "HIGH", None}
VALID_EVENT_TYPES = {
    "blocker", "error", "verification_failure", "reviewer_warn_or_fail",
    "escalation", "recurring_issue", "user_correction",
    "parallel_dispatch_failure", "successful_workaround", "completion_learning",
}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_OUTCOMES = {"success", "blocked", "aborted", "unknown"}
VALID_SUBAGENT_ROLES = {"implementer", "reviewer", "verifier", "documenter",
                       "plan_reviewer", "orchestrator"}
VALID_SUBAGENT_DISPATCH = {"agent_tool", "claude_p", "orchestrator"}
SECRET_PATTERNS = [
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|cookie|private[_-]?key)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
]

# init-run, append, close-run subcommands ...
```

Implementation details:

- `init-run` writes `meta.json` with `started_at`, `outcome="unknown"`, `event_count=0`.
- Run dir path: `<log_root>/runs/<YYYY-MM-DD>/<run_id>/`.
- `run_id` = `f"{ts}Z-{session_short}-{pid}"` where ts is UTC compact ISO.
- `append`: validate, sanitize (relativize worktree-absolute paths, reject home paths, reject secret-like values), assign `event_id` (sha256 16 chars of `timestamp|run_id|event_type|summary`), write compact JSON line.
- `close-run`: read `meta.json`, count events.jsonl lines, write back with `ended_at` + `outcome` + `event_count`.
- All subcommands idempotent.

- [ ] **Step 2: Run the helper eval**

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py
```

Expected: PASS with `"passed": true`.

- [ ] **Step 3: Confirm helper CLI help**

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py --help
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py init-run --help
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py append --help
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py close-run --help
```

- [ ] **Step 4: Commit the helper**

```bash
git add ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py
git commit -m "feat(kws-claude-multi-agent-executor): add learning event helper"
```

## Task 3: Add Failing Contract Checks

**Files:**
- Create or modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_skill_contract.py`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/run.sh`

- [ ] **Step 1: Add contract checks**

If `check_skill_contract.py` does not exist, create it. Required assertions:

- `references/learning-log.md` exists
- `scripts/append_learning_event.py` exists
- `SKILL.md` contains: "execution-only", "MAE_LEARNING_RUN_ID", "references/learning-log.md"
- `references/plan-reviewer-prompt.md` contains `Skill("superpowers:writing-plans")`
- `references/reviewer-prompt.md` contains `Skill("superpowers:requesting-code-review")`
- `references/verifier-prompt.md` contains `Skill("superpowers:verification-before-completion")`
- `references/learning-log.md` mentions each of the 10 event types
- `references/learning-log.md` contains privacy text: "Do not store secrets", "Do not store full conversation transcripts", "Do not store absolute home paths", "Do not store absolute worktree paths"
- `references/learning-log.md` mentions per-run path `~/.claude/learning/kws-claude-multi-agent-executor/runs/`

- [ ] **Step 2: Add helper + contract evals to `run.sh`**

After the existing baseline-writing logic, before final summary:

```bash
python3 "$EVAL_DIR/check_learning_log.py" >/dev/null
python3 "$EVAL_DIR/check_skill_contract.py" --skill "$SKILL_DIR/SKILL.md" >/dev/null
```

- [ ] **Step 3: Run contract check and confirm it fails**

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_skill_contract.py \
  --skill ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md
```

Expected: FAIL listing the missing learning-log artifacts and prompt Skill invocations.

- [ ] **Step 4: Commit the failing contract**

```bash
git add \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_skill_contract.py \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/run.sh
git commit -m "test(kws-claude-multi-agent-executor): require learning log contract"
```

## Task 4: Add Runtime Learning-Log Reference Document

**Files:**
- Create: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/learning-log.md`

- [ ] **Step 1: Write the reference doc**

Sections:

- Purpose & scope
- Per-run path layout
- `run_id` format
- 10 event types with one-line trigger each
- meta.json schema
- events.jsonl schema (with one filled example)
- Redaction rules (allowed / not allowed)
- Helper interface (3 subcommands)
- Runtime flow (Phase 0 init-run → events → Phase 2 close-run)
- Sub-agent inheritance via `MAE_LEARNING_RUN_ID` env var
- Failure policy: logging never fails the primary task

- [ ] **Step 2: Verify contract passes the learning-log-existence + privacy checks**

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_skill_contract.py \
  --skill ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md 2>&1 | tail -5
```

Expected: some checks still FAIL (SKILL.md + sub-agent prompts not yet updated) but `learning_log_reference_exists` + `learning_log_privacy_guard` + `learning_log_event_types` PASS.

- [ ] **Step 3: Commit the reference doc**

```bash
git add ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/learning-log.md
git commit -m "docs(kws-claude-multi-agent-executor): add learning-log reference"
```

## Task 5: Wire Runtime — SKILL.md + Sub-agent Prompts + Escalation Playbook

**Files:**
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/implementer-prompt.md`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/reviewer-prompt.md`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/verifier-prompt.md`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/plan-reviewer-prompt.md`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/escalation-playbook.md`

- [ ] **Step 1: SKILL.md core invariant + Phase boundaries + exit-path closure**

Add to `## Guardrails` section (or equivalent invariants list):

```markdown
- Learning log: at Phase 0 setup invoke `scripts/append_learning_event.py init-run` and export `MAE_LEARNING_RUN_ID`. At notable boundaries (blocker, verification_failure, reviewer_warn_or_fail, escalation, recurring_issue, user_correction, parallel_dispatch_failure, successful_workaround, completion_learning) read sub-agent candidate JSON files from `<worktree>/.orchestrator/learning_events/` and call `append`. At every orchestrator exit path (Phase 2 success, ESCALATE halt, user/hook abort) call `close-run` with the appropriate outcome. Resume Chain preserves `MAE_LEARNING_RUN_ID` and calls `append-session-id` (NOT `init-run`). Logging failure must not fail the primary task. See `references/learning-log.md`.
```

Edit locations (described narratively to avoid step-number drift):

- **After worktree setup** (currently around Phase 0 Step 2): invoke `init-run` with `--repo-root`, `--repo-name`, `--branch`, `--plan-path`, `--spec-path`, `--session-id "$CLAUDE_SESSION_ID"`. Capture stdout as `MAE_LEARNING_RUN_ID`.
- **In each Phase 1 cycle step** (dispatch / review / verify): point to `references/learning-log.md` for emit triggers; do not duplicate the trigger list inline.
- **In Phase Transition T1/T2/T3 steps**: add brief pointer to learning-log emit rules for batch verifier fail / phase docs escalation / state anchor write.
- **In ESCALATE handling** (Escalation Protocol section): require the orchestrator to call `close-run --outcome blocked` before halting.
- **In Phase 2 Final Summary Report step**: call `close-run --outcome success` after the summary is written.
- **In Resume Chain handoff** (`SKILL.md` section "Resume Chain"): prepend `env MAE_LEARNING_RUN_ID="$MAE_LEARNING_RUN_ID"` to the `nohup claude -p ...` spawn command. The chained orchestrator must call `append-session-id` immediately on startup, NOT `init-run`. Also: the current (departing) orchestrator must NOT call `close-run` on handoff.

Bump SKILL.md frontmatter version: 2.6.0 → 2.8.0.

- [ ] **Step 2: Reviewer prompt — add Skill invocation + emit guidance**

In `references/reviewer-prompt.md`, add to preamble (before scoring instructions):

```markdown
**Before reviewing:** invoke `Skill("superpowers:requesting-code-review")` so your spec_score and quality_score reflect a checklist-grounded review, not freeform impression.

**After scoring, if QUALITY_SCORE < 0.75 OR SPEC_SCORE < 0.85 OR tier is WARN/FAIL:** prepare a learning event candidate per `references/learning-log.md` event type `reviewer_warn_or_fail`. Write the JSON candidate to `<worktree>/.orchestrator/learning_events/<task_id>-reviewer.json` and stop. **Do not call the helper script yourself** — the orchestrator reads this file and invokes `append`.
```

- [ ] **Step 3: Verifier prompt — add Skill invocation + emit guidance**

In `references/verifier-prompt.md`:

```markdown
**Before running verification:** invoke `Skill("superpowers:verification-before-completion")` to apply evidence-before-assertion standards.

**If verification fails:** prepare a `verification_failure` event candidate per `references/learning-log.md`. Include risk_tier, the failing command (sanitized — no absolute paths), and a 1-line root-cause if known. Write the JSON to `<worktree>/.orchestrator/learning_events/<task_id>-verifier.json`. **Do not call the helper script yourself** — the orchestrator reads this file and invokes `append`.
```

- [ ] **Step 4: Plan Reviewer prompt — add Skill invocation + emit guidance**

In `references/plan-reviewer-prompt.md`:

```markdown
**Before reviewing the plan:** invoke `Skill("superpowers:writing-plans")` so your review criteria match the plan-writing standard.

**If the plan fails advisory thresholds and the orchestrator treats this as blocking:** the orchestrator emits a `blocker` learning event. You do not emit events directly; report your assessment normally.
```

- [ ] **Step 5: Implementer prompt — add learning-log emit guidance**

The Implementer already invokes 4 superpowers Skills. Add a single section:

```markdown
**Learning log:** if you send ESCALATE, also write an `escalation` event candidate to `<worktree>/.orchestrator/learning_events/<task_id>-implementer.json` per `references/learning-log.md`. If a root-cause-based recovery produced a reusable insight, write a `successful_workaround` candidate. **Do not call the helper script yourself** — the orchestrator reads these files and invokes `append`.
```

- [ ] **Step 6: Escalation playbook — escalation → event mapping**

In `references/escalation-playbook.md`, add a section mapping each escalation category (ENV_BLOCKER, SCOPE_AMBIGUITY, MID-RISK_CONCERN, etc.) to:

- whether it triggers an `escalation` event
- what `severity` to use
- what the `summary` should mention

- [ ] **Step 7: Run helper + contract evals**

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_skill_contract.py \
  --skill ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md
```

Both pass.

- [ ] **Step 8: Commit runtime contract changes**

```bash
git add \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/implementer-prompt.md \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/reviewer-prompt.md \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/verifier-prompt.md \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/plan-reviewer-prompt.md \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/escalation-playbook.md
git commit -m "feat(kws-claude-multi-agent-executor): wire learning log into runtime + add review-side Skill calls"
```

## Task 6: Update Architecture, History, AGENTS, Release Metadata

**Files:**
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/ARCHITECTURE.md`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/HISTORY.md`
- Modify: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/AGENTS.md`
- Modify: `ai/skills/kws-skills/manifest.json`
- Modify: `ai/skills/kws-skills/README.md`
- Modify: `ai/skills/kws-skills/CHANGELOG.md`

- [ ] **Step 1: ARCHITECTURE.md §14 Learning Log Contract**

Add a new section §14 covering:

- per-run sharded layout
- 3-subcommand helper
- 10 event types and source roles (orchestrator vs each sub-agent)
- privacy guard
- relation to `state.json` (state = per-run resume; log = cross-run learning)

Update §13 "Update protocol" trigger list to include "learning event schema or new event_type" as a triggering change.

- [ ] **Step 2: HISTORY.md v2.8.0 entry**

Add v2.8.0 entry to §1 Version timeline; cross-link the experiment under §3.

```markdown
### v2.8 — Learning log + review-side Skill invocations (2026-05-13)
- Added per-run sharded user-local learning log under `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/`.
- Helper script with 3 subcommands (`init-run`, `append`, `close-run`); sub-agents inherit `MAE_LEARNING_RUN_ID`.
- 10 event types covering Phase 0/1/transition/2 notable boundaries.
- Added `Skill("superpowers:writing-plans" | "requesting-code-review" | "verification-before-completion")` to Plan Reviewer / Reviewer / Verifier prompts.
- Records: `docs/experiments/v2.8-learning-log/`
- Branch: `codex/executor-learning-log`
```

Add a corresponding row under §2 "Evaluation harness" and §2 "Hooks / safety".

- [ ] **Step 3: AGENTS.md learning-log operational protocol**

Add a section under "Experiment & history record-keeping (REQUIRED)" referencing the learning log as a complementary mechanism (per-run live signal; experiments are intentional). Do not duplicate the event-type list — point to `references/learning-log.md`.

- [ ] **Step 4: Bump versions**

`ai/skills/kws-skills/manifest.json`:

```json
"version": "2.11.0"
"kws-claude-multi-agent-executor": {
  "version": "2.8.0",
  "updated_at": "2026-05-13"
}
```

`ai/skills/kws-skills/README.md`: bump package + executor row.

`ai/skills/kws-skills/CHANGELOG.md`: add `2.11.0 - 2026-05-13` entry.

- [ ] **Step 5: Run sync + skill quick validation**

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_skill_contract.py \
  --skill ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md
sh ai/skills/kws-skills/tests/test-sync.sh 2>&1 | tail -10
python3 /Users/kws/.claude/skills/.system/skill-creator/scripts/quick_validate.py \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor 2>&1 | tail -10
```

Expected: all exit 0.

- [ ] **Step 6: Commit metadata**

```bash
git add \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/ARCHITECTURE.md \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/HISTORY.md \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor/AGENTS.md \
  ai/skills/kws-skills/manifest.json \
  ai/skills/kws-skills/README.md \
  ai/skills/kws-skills/CHANGELOG.md
git commit -m "chore(kws-claude-multi-agent-executor): release v2.8.0 learning log"
```

## Task 7: Smoke Run And Close-Out Finding

**Files:**
- Read: `evals/fixtures/01-trivial-typo.yaml`, `evals/fixtures/08-subtle-input-validation.yaml`
- Generated: `docs/experiments/v2.8-learning-log/findings/F001-smoke.md`

- [ ] **Step 1: Run TWO fixtures end-to-end with the learning log enabled**

**Smoke A (happy path):** `evals/fixtures/01-trivial-typo.yaml` (LOW, single-file).
Expected outcome:
- `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/meta.json` exists
- `meta.outcome == "success"`
- `meta.event_count == 0`
- `events.jsonl` is empty or absent
Validates: `init-run` + `close-run` on a clean path.

**Smoke B (designed to WARN):** `evals/fixtures/08-subtle-input-validation.yaml`
(MID, known to produce reviewer WARN at ~75% from v2.7 baseline).
Expected outcome:
- separate run directory created
- `meta.outcome == "success"` (WARN does not block)
- `meta.event_count >= 1`
- at least one `events.jsonl` line has `event_type == "reviewer_warn_or_fail"`
- the event line has a valid `scores` block with `tier == "WARN"`
Validates: the `append` path under real conditions, including sub-agent
candidate-file → orchestrator-helper handoff.

If Smoke B produces zero events (the 25% rep-4 case from v2.7), record this
as PARTIAL and rerun once. If still zero, dig into whether the Reviewer
candidate-file was written but not picked up.

- [ ] **Step 2: Write F001-smoke finding**

`docs/experiments/v2.8-learning-log/findings/F001-smoke.md`:

- Status (PASS / FAIL / PARTIAL) — PASS iff both Smoke A and B meet their expectations
- meta.json delta vs spec schema for each smoke
- events emitted in each smoke (compact dump)
- Resume Chain not exercised by these fixtures — flag as residual risk
- Implementer ESCALATE path not exercised by these fixtures — flag as residual risk
- close-out decision: ship / hold

- [ ] **Step 3: Update experiment README + JOURNAL**

Mark Phase status table as `complete` for T0-T8 rows. Update JOURNAL with close-out entry stating outcome.

- [ ] **Step 4: Commit smoke artifacts**

```bash
git add ai/skills/kws-skills/package/kws-claude-multi-agent-executor/docs/experiments/v2.8-learning-log/
git commit -m "docs(v2.8-experiment): smoke run finding + close-out"
```

## Task 8: Final Verification

**Files:**
- Read: changed files
- Run: full eval suite

- [ ] **Step 1: Run full eval + sync**

```bash
cd ai/skills/kws-skills/package/kws-claude-multi-agent-executor
python3 scripts/append_learning_event.py --help
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --skill SKILL.md
bash evals/run.sh evals/fixtures/01-trivial-typo.yaml 2>&1 | tail -20
cd /Users/kws/source/private/Archive
sh ai/skills/kws-skills/tests/test-sync.sh 2>&1 | tail -10
python3 /Users/kws/.claude/skills/.system/skill-creator/scripts/quick_validate.py \
  ai/skills/kws-skills/package/kws-claude-multi-agent-executor 2>&1 | tail -10
```

Expected: every command exits 0.

- [ ] **Step 2: Inspect final diff**

```bash
git status --short
git diff --stat $(git merge-base HEAD main)..HEAD
git diff --check
```

Expected: no whitespace errors. Diff contains only Claude executor + cross-skill metadata files.

- [ ] **Step 3: Final summary**

Summarize:

```text
changed_files:
- helper script + helper eval
- learning-log reference doc
- contract check + run.sh
- SKILL.md (version bump + Phase boundary calls)
- 4 sub-agent prompts (reviewer/verifier/plan-reviewer/implementer)
- escalation-playbook
- ARCHITECTURE/HISTORY/AGENTS sync
- manifest/README/CHANGELOG release metadata
- experiment record + F001-smoke finding

verification:
- helper CLI help
- check_learning_log.py
- check_skill_contract.py
- evals/run.sh fixture smoke
- skill quick validation
- package sync test

residual_risk:
- learning event quality still depends on sub-agents constructing concise candidates
- no aggregation/reporting tool yet (deferred to v2.9+)
- headless --model flag still not explicit (separate v2.8.x mini-PR)
- Skill-invocation enforcement is by prompt only (not hook-enforced)
```

## Plan Self-Review

Spec coverage:

- `execution-only`: §Runtime Flow covers Phase 0/1/transition/2; out-of-execution paths (CHANGELOG generation, etc.) do not log.
- `notable-boundaries`: Task 5 documents each event type; Task 3 contract-checks the event type list in `references/learning-log.md`.
- `redacted-context`: Task 2 helper rejects home paths, worktree paths, secret-like values; Task 4 reference doc states privacy rules.
- `schema + helper script`: Task 1 + Task 2 add deterministic eval + helper.
- Per-run shard layout: Task 2 helper writes `runs/<date>/<run_id>/{meta.json,events.jsonl}`; Task 1 eval covers concurrent-runs isolation.
- Sub-agent skill-invocation additions: Task 5 wires three Skill calls; Task 3 contract-checks their presence.
- ARCHITECTURE/HISTORY/AGENTS sync: Task 6.
- Smoke + close-out: Task 7.

Placeholder scan:

- No placeholder tokens, unfinished sections, or missing commands.

Type consistency:

- Helper path consistently `scripts/append_learning_event.py`.
- Helper subcommands: `init-run` / `append` / `close-run` / `append-session-id` (four).
- Eval path consistently `evals/check_learning_log.py`.
- Reference path consistently `references/learning-log.md`.
- Log path consistently `~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/`.
- Candidate path consistently `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`.
- Env var consistently `MAE_LEARNING_RUN_ID`.
- New skill version consistently `2.8.0`.
- New package version consistently `2.11.0`.

Post-advisor patches (recorded in D001 §Post-advisor corrections):

- Sub-agents NEVER call the helper directly (Q4) — they only write candidate files.
- `close-run` is called from EVERY exit path, not just Phase 2 (Q5).
- Resume Chain preserves `MAE_LEARNING_RUN_ID` and uses `append-session-id` (Q6).
- F001 smoke uses TWO fixtures (Q7): happy + designed-to-WARN.
