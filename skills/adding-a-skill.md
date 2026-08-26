# Adding a general skill

Archive is not a general skill catalog. Do not add a new general skill
here. Frozen execution trees live under `skills/_legacy/`. Do not put
Waygent product runtime or Superpowers plan execution here.

The layout below is historical reference for frozen trees only.

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
- Do not add a catalog table or routing entry for a new general skill.
- Frozen `_legacy` trees keep their own README and change protocol.
- If a frozen tree has evals, keep matchers and commands in
  `scripts/agent/verification-map.ts` in lockstep with that tree.
