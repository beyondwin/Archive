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
- Voice cases protect small register or stance spans. They must not require
  the whole candidate string to equal the source.
- Mixed normative cases may protect an already-correct obligation or
  modality span in the same record as a local spelling fix.
- A candidate with process preamble must fail the replaced
  `norm-spacing-can-01` properties.
- Passing fixtures proves the offline oracle contract. It does not prove
  live model quality. The evaluator prints that disclaimer on success.
- Live-harness changes keep `evals/live_cases.json`, `evals/live_matrix.py`,
  `evals/test_live_matrix.py`, and [evals/README.md](evals/README.md) in
  sync. Live cases remain synthetic; none of these artifacts may contain
  private manuscripts or full transcripts.
- Live budget changes keep the 119-producer, 3-reviewer, 122-baseline,
  38-remediation, and 160-total dry-run and parser assertions synchronized.
  Report-bearing resume changes need a real temporary-Git test for both the
  absent-report first publication and a crash after report publication before
  report-state persistence.
- Remediation needs one or more immutable planned producer call IDs, in
  canonical full-plan order, bound into the run identity. It never dispatches
  reviewer calls unless a separately approved reviewer mechanism is designed.
  Reserve a report target and its matching state before any paid dispatch; do
  not treat a final report write as the first ownership claim.

## Live Harness Invariants

Before every Codex or Cursor provider process invocation, the runner validates
CLI availability, argv, immutable run identity, and the active report lease,
then durably records one immutable attempt reservation immediately before
process invocation. The reservation binds the complete run identity, logical
and actual call IDs, positive gap-free global call number, producer or reviewer
kind, host, requested model, case ID, and repeat index. Only a true
zero-provider `not_measured` receipt may use call number zero without a
reservation; every `verified`, `partially_verified`, `failed`, or `blocked`
receipt must match one positive reservation exactly, and a reviewer receipt
cannot match a producer reservation. Crash-only reservations remain charged,
drive unique `:attempt-N` retry IDs, and count in budgets and reports.

One `ReportLease` holds one open `docs/operations` directory FD from pending
report reservation through every producer and reviewer call and final report
replacement. Pending creation, owned-state hash validation, temporary-file
creation, owned inode and hash recheck, replacement, and directory fsync all
use that same FD. Immediately before every provider process invocation, the
current repository `docs/operations` path must resolve to the leased device and
inode, and the leased report must match the expected target, state, device,
inode, and hash; drift consumes zero next call. A path swap after the last
validation may consume at most the already-reserved current call, but it does
not redirect report mutation because every mutation remains relative to the
held FD; the next validation, if any, fails and the old leased inode may retain
a safe pending or owned residual. This is the achievable invariant, not an
atomic guarantee against a malicious rename after process spawn.

## Versioning

- Behavior change: bump SemVer in `SKILL.md` `metadata.version`.
- Documentation-only wording change: do not bump the version unless
  behavior also changes.
- A live-harness or dated-report-only change does not bump the skill version.

## Required Verification

Required offline verification:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
bun run agent:verify
git diff --check
```

Live canaries remain opt-in and are reported separately. Do not describe
offline fixture results as live invocation or model-quality evidence.

The dated operations report uses `verified`, `partially_verified`, `blocked`,
`failed`, and `not_measured` as executed-evidence labels. Keep provider IDs
out of `SKILL.md`; the skill contract must not advertise a particular runtime
or provider identity.

A positive live prompt is only the host explicit invocation plus the Korean
editing request and source. Do not append CANARY, tier, or skill_used
instructions to that message. Near-miss prompts omit self-report
instructions. Judge the returned body. `skill_used` self-report is not a
contract.
