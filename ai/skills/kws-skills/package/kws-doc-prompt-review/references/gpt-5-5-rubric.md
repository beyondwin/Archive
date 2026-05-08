# GPT-5.5 Prompt Review Rubric

Use this as a local fallback rubric for reviewing prompts, agent instructions, repository docs, and skill files. If the user asks for current/latest OpenAI guidance, fetch official OpenAI docs first and treat this file as a compact checklist.

## Core Dimensions

1. **Outcome first**
   - State what successful work looks like before listing procedures.
   - Avoid over-prescribing internal steps when the model can choose an efficient route.

2. **Success criteria**
   - Include concrete "done when" criteria.
   - Say what must be verified before claiming completion.

3. **Scope and constraints**
   - Name files, surfaces, ownership boundaries, safety rules, and public/private data limits.
   - Keep invariants distinct from preferences.

4. **Output shape**
   - Specify the final answer format only when it matters.
   - Keep review outputs finding-first when risk assessment is the task.

5. **Stop rules**
   - Say when to ask a question, when to continue with assumptions, and when to stop before editing.
   - Require uncertainty disclosure for unverified facts or skipped checks.

6. **Tool and source policy**
   - Use current official sources for unstable facts, product/API docs, laws, pricing, schedules, or safety-sensitive claims.
   - Avoid unnecessary browsing when local source-of-truth files are enough.

7. **Verification**
   - Match checks to blast radius.
   - Include targeted checks for docs-only, frontend, server, E2E, security, and public-release changes when relevant.

8. **Preambles and progress**
   - For long work, tell the user what is being checked or changed.
   - Keep status updates short and concrete.

9. **Avoid brittle absolutes**
   - Use `always`/`never` only for true invariants, safety boundaries, or required output fields.
   - Convert judgment calls into conditional rules.

10. **Progressive disclosure**
   - Keep core instructions short.
   - Move detailed examples, provider variants, long rubrics, and checklists into references loaded only when needed.

## Common Smells

- The instruction says what to do but not what a good result is.
- The doc gives checks but no rule for skipped or failing checks.
- A mixed task needs two guides, but routing says to open only one.
- Public-safety rules list forbidden data but omit examples of safe placeholders.
- The prompt includes many hard absolutes for judgment-heavy behavior.
- The final answer format is vague for review tasks.
- External facts are treated as stable without source guidance.
- A skill description summarizes workflow instead of trigger conditions.
- A skill body repeats long reference material instead of linking to it.

## Severity Guide

- **High impact:** likely to cause unsafe disclosure, wrong file edits, missed verification, or a blocked workflow.
- **Medium impact:** likely to cause inconsistent agent behavior, wasted work, or unclear review output.
- **Optional polish:** wording or organization change that improves readability without changing behavior.
