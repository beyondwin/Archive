# Adding a general skill

Archive is not a general skill catalog. Do not add a new general skill here.
Frozen execution trees live under `skills/_legacy/`. Do not put Waygent
runtime or Superpowers plan execution here.

Layout below is historical reference for those frozen trees.

```text
skills/<kebab-name>/
  SKILL.md
  README.md
  CHANGE_PROTOCOL.md
  evals/
  references/    # when needed
  scripts/       # when needed
```

- Directory name: letters, numbers, hyphens. No `kws-` prefix.
- `SKILL.md` `name` equals the directory name.
- `SKILL.md` is the English agent contract.
- `README.md` is the Korean one-minute start.
- `evals/` fail closed offline: no network, credentials, or models.
- On a contract change, keep trigger, README, and fixtures in lockstep.
- Do not add a catalog table for a new general skill.
- Frozen `_legacy` trees keep their own README and change protocol.
- If a frozen tree has evals, keep matchers and commands in
  `scripts/agent/verification-map.ts` in lockstep.
