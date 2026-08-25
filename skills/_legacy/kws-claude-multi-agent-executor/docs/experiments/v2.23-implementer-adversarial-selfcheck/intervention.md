# The intervention (reverted — preserved here for revival)

This is the exact `references/implementer-prompt.md` change that was tested and
SKIPPED (see [findings/F001-close-out-skip.md](./findings/F001-close-out-skip.md)).
It was reverted from the working tree because the baseline defect it targets
(v2.7 F002) no longer reproduces on the current Sonnet. If a future Sonnet
regresses (re-test trigger: `bench/run_ab.py --arm control` meta-rule pass-rate
drops below ~75% on fixture 08), re-apply the three blocks below.

## Block 1 — new instruction 1.c (insert after instruction 1.b, before `2. Follow the spec requirement above strictly.`)

```markdown
1.c **Adversarial meta-rule self-check** (the Implementer-side mirror of the
   Reviewer's Spec Coverage Walk sub-step B): before reporting GREEN, scan the
   spec for meta-rules — wording like "strict", "strictly", "reject", "anything
   else", "must validate", "rule is", "beyond these examples", "exhaustive",
   "not exhaustive". For each meta-rule found, generate ≥3 adversarial inputs
   that the meta-rule (not any explicit example) makes invalid — covering at
   least the repeated-segment, casing/whitespace, and format-exclusion classes
   (e.g. `30m20m`, `1H`, `1h 30m`, `s`). Confirm each is handled per spec by
   writing a failing test for it as part of the TDD RED step (if test files are
   in this task's Files: scope) OR by running an explicit verification command
   (if test files are out of scope, e.g. a Files: block of only `src/duration.py`).
```

## Block 2 — new output line (add to the `## Output Format` section)

```markdown
ADVERSARIAL_SELFCHECK: <meta-rules found: N | none> ; inputs tested: <comma-separated adversarial inputs you generated and confirmed, or "none">
```

## Block 3 — TDD Required Skill #2 amendment

Append to Required Skills item 2 (the `superpowers:test-driven-development` bullet):

```markdown
Your RED step MUST include the adversarial meta-rule inputs required by Instruction 1.c below.
```

## Validation status at revival

- Mechanism confirmed working (treatment reps emitted a correct, non-fabricated
  `ADVERSARIAL_SELFCHECK:` line with genuinely-generated adversarial inputs).
- `evals/check_skill_contract.py --skill ./SKILL.md` passed with the intervention applied.
- Re-run the A/B (`bench/run_ab.py`) before shipping; only ship if control
  meta-rule pass-rate has dropped enough that treatment shows a real gain.
