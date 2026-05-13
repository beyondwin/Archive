# Onboarding for AI agents

Read this when you (a Claude / Codex / similar agent) are continuing work
on this skill in a new session. It establishes operating norms, points to
the load-bearing documents in the right order, and lists the things that
typically go wrong.

## Read order — the first 10 minutes

Open these in sequence. Don't deep-read; skim for "do I know where this
is" rather than "do I understand every line".

1. **[`../README.md`](../README.md)** — orientation + document map. The
   table of contents tells you where to find specifics.
2. **This file** (you are here) — operating norms.
3. **[`../AGENTS.md`](../AGENTS.md)** — *required* protocol for AI
   contributors: experiment record-keeping, learning-log handling, file
   responsibilities, ARCHITECTURE.md sync rule.
4. **[`../ARCHITECTURE.md`](../ARCHITECTURE.md) §1-§4** — orchestrator-worker
   mental model + 3-phase lifecycle. (Skim §5-§14 only if you need state /
   isolation / risk / scoring specifics.)
5. **[`./risks-and-limitations.md`](./risks-and-limitations.md)** — known
   fragilities. Don't try to "fix" something here without reading the
   mitigation history.
6. **[`../HISTORY.md`](../HISTORY.md) §1 most-recent two entries** — what
   changed recently and why.

The remaining files are loaded on demand:
- `SKILL.md` if you need the precise runtime contract
- `references/*.md` if you're touching prompts
- `evals/*` if you're modifying the eval system
- `docs/experiments/<version>/` if you're researching a past decision

## What "AI contributor" means here

You're a session in Claude Code (or a similar agent) doing one or more of:

- Designing a new experiment (v2.X) for this skill
- Implementing a change (prompt edit, helper script, eval harness)
- Reviewing prior work (code review, document audit)
- Debugging a regression
- Continuing prior work that ran out of context

Each of those has slightly different norms — covered below.

## Operating norms

### 1. Don't bypass the experiment protocol

If you're about to make a SKILL.md change ≥50 lines, or a multi-file
behavioral change, or a change with a hypothesis that could be wrong:
**start an experiment record FIRST** under `docs/experiments/v2.X-<name>/`.

Use [`docs/experiments/_template/`](./experiments/_template/) as the
scaffold. Without an experiment record:
- Your reasoning is invisible to future agents.
- The "why" of your decision is lost the moment your session ends.
- The advisor + the user lose the ability to audit your decisions.

The [`../AGENTS.md`](../AGENTS.md) §Protocol section is the authoritative
rule. Read it before opening your first big change.

### 2. Honor the learning log

If your work surfaces a notable boundary (Reviewer WARN/FAIL, verification
failure, sub-agent ESCALATE, recurring issue, successful workaround,
user correction, completion learning), emit a learning event.

Sub-agents emit by writing JSON candidates to
`<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`.
**Never call the helper script directly** — see
[`../references/learning-log.md`](../references/learning-log.md) for the
single-writer contract.

Orchestrator (you, if you're the top-level session) calls
`scripts/append_learning_event.py append --run-id $MAE_LEARNING_RUN_ID ...`
after scanning the candidate directory.

### 3. Call advisor before substantive work

The `advisor` tool, when available, sees your full conversation
transcript. Call it:
- Before drafting design docs (validates the framing).
- Before writing eval/prompt changes (catches "the obvious thing
  wouldn't actually work" cases).
- Before declaring a task complete (final sanity check).

A passing self-test is not evidence the advisor is wrong. Honor advisor
output unless you have empirical evidence (primary source contradicts a
specific claim).

### 4. Tone, scope, and over-engineering — match what's in CLAUDE.md

The repo's `AGENTS.md` at the Archive root (`/Users/kws/source/private/Archive/AGENTS.md`) sets:
- No comments unless WHY is non-obvious.
- No backwards-compatibility shims when you can just change code.
- No design for hypothetical futures.
- Three similar lines is fine; premature abstraction is not.
- Match feature flag / config behavior to what's already in the codebase.

These apply to this skill too. The skill's reference prompts are slightly
more verbose because they're agent-facing, but the same scope discipline
applies.

### 5. Risk-aware action

For destructive or hard-to-reverse actions (force-push, branch delete,
SKILL.md major surgery, deleting an experiment directory), pause and
confirm with the user. The cost of pausing is low; the cost of
unrecoverable action is high.

Routine local actions (edit, run tests, run preflight, write a docs
file) — proceed.

### 6. Branch hygiene

Currently this skill's work lives on `codex/executor-learning-log` (shared
with the user's parallel Codex work). When committing:
- Stage Claude-executor files explicitly. Do not `git add -A`.
- Don't touch the user's unstaged Codex executor changes.
- Use the `co-authored` footer with `Claude Opus 4.7`.

See [`./risks-and-limitations.md`](./risks-and-limitations.md) §Branch hygiene.

---

## Common starting tasks

### "I'm continuing prior work that ran out of context"

1. Read the in-progress experiment's `JOURNAL.md` last 1-2 entries.
2. Read its `README.md` Phase status table.
3. Read this skill's [`HISTORY.md`](../HISTORY.md) §1 top entry.
4. Read the open task list (TaskList) if it exists in the session.
5. Then continue from where the JOURNAL says you left off — *don't*
   re-derive context the JOURNAL already captured.

### "User asked me to design a new experiment"

1. Sketch the hypothesis in 1-2 sentences.
2. Identify evidence — does this map to a *measured* failure in the
   eval corpus? If not, surface that to the user before writing design
   docs. (See [`./deferred-candidates.md`](./deferred-candidates.md)
   §omc candidates for the discipline.)
3. Create the experiment scaffold from the template.
4. Draft D001 covering: question, options, decision, rationale.
5. Call advisor on the design.
6. Then write spec doc + plan doc at the Archive level.
7. Commit before implementation work begins.

### "User asked me to fix a bug"

1. Reproduce locally (probably via `bash evals/run.sh <fixture>`).
2. Inspect the failing artifact — state.json, run.jsonl, events.jsonl.
3. Diagnose root cause.
4. Decide: small fix (just commit) or non-trivial (open an experiment record).
5. Implement, run preflight, commit.

### "User asked me to extend the eval suite"

1. Read [`../evals/README.md`](../evals/README.md) §Fixture format.
2. Add `evals/fixtures/0N-<short-name>.yaml` matching the format.
3. Verify spec-vs-rubric alignment (no v2.9 Phase 2-style ambiguity).
4. Run preflight (`evals/check_skill_contract.py` + `check_learning_log.py`).
5. Run the new fixture once in isolation to capture a baseline.
6. Commit fixture + baseline.

---

## Things that typically go wrong

- **Skipping the experiment protocol** because the change "feels small."
  Then 3 versions later, the rationale is lost. Solution: start the
  record. It's cheap insurance.
- **Treating advisor output as optional.** It frequently catches real
  flaws the agent missed. Honor it unless evidence contradicts.
- **Hallucinating helper invocation locations.** The helper is at
  `scripts/append_learning_event.py`, invoked by SKILL.md's Step 7.5 +
  Step 3.5 (Phase 1) + Phase 2 Step 2 + escalation playbook + Resume Chain.
- **Forgetting the single-writer contract.** Sub-agents NEVER call the
  helper. They write candidate JSON only.
- **Bundling unrelated changes in one experiment.** v2.7 D008 is the
  cautionary tale — 150-line SKILL.md change deferred forever because it
  bundled too many things. Keep experiments single-purpose.
- **Optimizing for fixture 08.** Most measured-failure evidence comes
  from fixture 08. Don't tune the entire system to that one fixture's
  characteristics.

---

## How to update this file

When you discover a new starting task or norm that applies to future
agents, add a section. When a norm becomes obsolete (e.g., a process
gets formalized into a Skill), move the relevant content to AGENTS.md
or remove it.

This file is for *AI-specific* onboarding. User-facing concerns live in
README.md. System-level architecture is in ARCHITECTURE.md. Don't
duplicate.
