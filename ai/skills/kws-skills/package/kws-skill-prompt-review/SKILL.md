---
name: kws-skill-prompt-review
description: Use when reviewing or improving Codex SKILL.md files, skill metadata, trigger descriptions, workflow gates, references, or pressure scenarios against GPT-5.5/OpenAI prompt-guidance principles.
metadata:
  version: "1.0.1"
  updated_at: "2026-05-05"
---

# KWS Skill Prompt Review

## Overview

Review Codex skills as behavioral prompts: whether the skill triggers at the right time, loads the right amount of context, constrains risky work, and gives future agents enough validation guidance.

Use this for skill bundles under a skills directory. Use `kws-doc-prompt-review` instead for ordinary repository docs, `AGENTS.md`, README, or operational docs.

## Workflow

1. **Inspect the skill bundle.** Read `SKILL.md`, `agents/openai.yaml` if present, and the names of bundled `references/`, `scripts/`, and `assets/`. Load resource files only when they are relevant.
2. **Classify the skill.** Identify whether it is a workflow, technique, reference, tool integration, or domain guide. Review workflows for sequencing and gates, techniques for decision rules and mistakes, references for source policy and progressive disclosure, tool integrations for setup and failure modes, and domain guides for scope and validation.
3. **Load guidance.** If the user asks for latest/current OpenAI guidance, use official OpenAI docs first and treat `references/gpt-5-5-rubric.md` as a fallback checklist. Otherwise, read the bundled rubric directly.
4. **Review trigger behavior.** Check that frontmatter `description` states concrete use conditions without becoming a shortcut summary of the workflow.
5. **Review body behavior.** Check outcome, gates, stop rules, tool/source policy, validation, progressive disclosure, and token efficiency.
6. **Patch only when requested.** If the user asks to "review", report findings only. If they ask to "fix", "apply", "update", "make it", or equivalent wording in the user's language, edit the smallest necessary skill files.
7. **Validate.** Run `quick_validate.py` from the skill-creator tooling when available. For substantial skill changes, recommend or run forward-testing only when it is feasible and safe.

## Skill Review Checklist

### Trigger Metadata

- `name` is lowercase hyphen-case and scoped clearly enough to avoid collisions.
- `description` starts with concrete "Use when..." trigger language.
- The description includes task artifacts and symptoms users will actually name.
- The description does not summarize the full workflow in a way an agent might follow without reading the skill body.

### Workflow

- The first section states the outcome and the boundary of the skill.
- Steps are ordered around real decision points, not generic advice.
- Hard gates are reserved for genuinely risky or sequencing-critical work.
- The skill says when to ask, when to proceed, and when to stop.
- It preserves user intent while preventing broad or unrelated edits.

### Progressive Disclosure

- Core `SKILL.md` remains short enough to load frequently.
- Long rubrics, examples, provider details, schemas, and templates live in referenced files.
- Resource names and "when to read this" guidance are explicit.
- Duplicate information is removed unless repetition is needed for safety.

### Validation

- Basic metadata validation is documented or run.
- Pressure scenarios cover likely failures, not happy paths only.
- Forward-testing avoids leaking the intended diagnosis or fix.
- The skill requires honest reporting of skipped validation.

## Report Shape

For review-only work, lead with findings:

- **High impact:** likely to prevent triggering, skip required gates, cause unsafe edits, or invalidate review/testing.
- **Medium impact:** likely to make behavior inconsistent, verbose, or hard to validate.
- **Optional polish:** naming, wording, or organization improvements.

Include file and line references for actionable findings when available.

For patch work, summarize changed skill files and validation commands. If forward-testing is skipped, state why.

## Boundaries

- Do not turn every style preference into a hard gate.
- Do not add broad implementation workflows to a narrow reference skill.
- Do not create extra README, changelog, or process-history files inside a skill unless explicitly requested.
- Do not preserve TODO placeholders in a finished skill.
