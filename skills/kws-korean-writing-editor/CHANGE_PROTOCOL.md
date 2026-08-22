# Change Protocol

Keep the advertised trigger, modes, output, evidence, fixtures, and version
in lockstep. A prompt-only edit that leaves fixtures or the user guide stale
is a contract break.

## Contract Changes

Synchronize these files together. Do not ship a behavior change in only one
of them.

- Trigger or near-miss change: update [SKILL.md](SKILL.md) activation text,
  positive and near-miss fixtures in [evals/cases.json](evals/cases.json),
  and [README.md](README.md).
- Mode or output-contract change (`diagnose`, `correct`, `polish`, default
  edited-text-only output, or `확인 필요`): update `SKILL.md`,
  [references/editorial-guide.md](references/editorial-guide.md), fixtures,
  and `README.md`.
- Model-tier change (`fast`, `balanced`, `frontier`, routing, or delegation):
  update routing fixtures in `evals/cases.json` and `README.md`. Do not
  hard-code provider model names or call a classifier model.

## Evidence Changes

- Normative claim change: update the authoritative source locator in
  [references/sources.md](references/sources.md) and add or adjust a fixture
  that encodes the claim boundary.
- External project use: record the pinned revision, license, checked date,
  and an explicit adopted/rejected boundary in `references/sources.md`. Do
  not copy third-party rule lists or corpora.

## Fixture Changes

Keep the thirty property cases and mutation checks honest in
`evals/cases.json` and [evals/run.py](evals/run.py).

- Trigger work needs both positive and near-miss records.
- Mode, output, preservation, and tier work needs matching
  `expected_mode`, `expected_tier`, and `expected_noop` records.
- Passing fixtures proves the offline oracle contract. It does not prove
  live model quality.

## Versioning

- Behavior change: bump SemVer in `SKILL.md` `metadata.version`.
- Documentation-only wording change: do not bump the version unless
  behavior also changes.

## Required Verification

Required offline verification:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
bun run agent:verify
git diff --check
```

Live canaries remain opt-in and are reported separately. Do not describe
offline fixture results as live invocation or model-quality evidence.
