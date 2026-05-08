---
name: kws-doc-prompt-review
description: Use when reviewing or improving repository docs, AGENTS.md files, README files, agent routing guides, prompt docs, or operational instructions against GPT-5.5/OpenAI prompt-guidance principles. Do not use for Codex SKILL.md files or skill bundles.
metadata:
  version: "1.0.1"
  updated_at: "2026-05-05"
---

# KWS Doc Prompt Review

## Overview

Review project documentation and agent instructions through a GPT-5.5 prompt-guidance lens, then either report findings or make narrow doc patches when the user clearly asks for edits.

Use this for repository docs and agent-facing instructions. Use `kws-skill-prompt-review` instead when the artifact under review is a Codex `SKILL.md` or skill bundle.

## Workflow

1. **Find the local rules first.** For repository docs, read the nearest `AGENTS.md` and any repo-specific doc guide before opening broad docs. Follow source-of-truth order in the repo. For pasted or standalone docs, do not import unrelated repo rules unless the user names that repo.
2. **Define the review target.** Classify files as router instructions, README/product docs, development docs, deployment docs, or prompt/operator docs. Keep the review scoped to those files.
3. **Load the rubric.** Read `references/gpt-5-5-rubric.md` for the review dimensions. If the user asks for latest/current OpenAI guidance, check official OpenAI docs or OpenAI-owned domains first, cite what was checked, and disclose when only this bundled rubric was used.
4. **Review before editing.** Identify concrete gaps with file/line references: unclear outcome, missing success criteria, weak validation, unsafe absolutes, ambiguous routing, stale source hierarchy, or missing stop rules.
5. **Patch only when requested.** If the user asks to "review", report findings only. If they clearly ask to "fix", "apply these changes", "edit", or "update the file", edit the smallest relevant doc set and preserve project voice.
6. **Verify honestly.** Run the smallest doc checks required by local instructions, such as `git diff --check -- <changed-docs>`. For public-safety or release docs, also run named safety checks documented in `AGENTS.md`, package scripts, or repo docs; if no named check exists, say so.

## Review Emphasis

- Prefer outcome-first instructions over long procedural micromanagement.
- Add explicit "done when" criteria where agents otherwise guess.
- Separate routing rules, safety constraints, validation commands, and final-response expectations.
- Convert broad `ALWAYS`/`NEVER` language into conditional rules unless the rule is a true invariant.
- Make mixed-surface tasks explicit, for example docs plus frontend, UI plus frontend, or server plus E2E.
- Require source/citation behavior only where facts may be stale or where external docs are material.
- Make stop rules explicit: when to ask the user, when to disclose uncertainty, and when not to patch.

## Report Shape

For review-only work, lead with findings:

- **High impact:** likely to cause wrong edits, unsafe output, missed validation, or agent confusion.
- **Medium impact:** improves reliability, source clarity, or maintainability.
- **Optional polish:** wording or organization improvements with low behavioral risk.

For each finding, include the file path, line when available, why it matters, and a concise replacement or patch direction.

For patch work, summarize changed files and verification commands. If a check cannot run, say exactly why and what was checked instead.

## Boundaries

- Do not rewrite product docs just to match generic prompt style.
- Do not add OpenAI-specific implementation rules to apps that do not call OpenAI APIs.
- Do not add project-specific secrets, private paths, private domains, live deployment state, or token-shaped examples.
- Do not broaden validation beyond what the changed surface justifies unless local instructions require it.
