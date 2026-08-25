# Adding a general skill

Use this file when adding a skill under `skills/`. Do not put Waygent
product runtime or Superpowers plan execution here.

## Layout

```text
skills/<kebab-name>/
  SKILL.md
  README.md
  CHANGE_PROTOCOL.md
  evals/
  references/    # when needed
  scripts/       # when needed
```

Rules:

- Directory name is letters, numbers, and hyphens only. No `kws-` prefix.
- `SKILL.md` `name` equals the directory name.
- `SKILL.md` is the English agent contract (triggers and behavior).
- `README.md` is the Korean human one-minute start and install guide.
- `evals/` must fail closed offline without network, credentials, or models.
- On a contract change, keep trigger, README, and fixtures in lockstep.
- Add the skill to the `skills/README.md` table and the `skills/AGENTS.md`
  routing list in the same change.
- If the skill has evals, register matchers and commands in
  `scripts/agent/verification-map.ts` in the same change.
