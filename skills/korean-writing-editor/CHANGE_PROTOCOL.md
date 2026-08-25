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

Keep the thirty-one property cases and mutation checks honest in
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

After producer dispatch, and again after reviewer dispatch for a baseline,
the controller reloads attempt reservations and receipts from disk, validates
their exact linkage, and requires one durable terminal receipt for every
planned logical call. Review packets, reports, statuses, and counts use only
those reloaded durable artifacts, never in-memory dispatch return values. A
crash-only reservation remains charged and resumable, but it cannot support a
successful packet or report until that logical call has a durable terminal
receipt. Remediation dispatches producers only and has no reviewer plan.

Dispatcher returns are completion claims only: every returned receipt must
match the exact canonical bytes of one reloaded durable receipt, and the return
value never contributes evidence. Each normalized producer or reviewer body
must be owned by the receipt's exact positive call path and match its
`response_sha256`. A reviewer receipt is reusable only when its `prompt_sha256`
matches the current review packet; stale, missing, deleted, or mutable evidence
fails closed before packet or report success.

One `ReportLease` holds one `O_RDWR` and `O_NOFOLLOW` target file FD plus one
open `docs/operations` directory FD from pending report reservation through
every producer and reviewer call and final publication. Report state persists
the target device, inode, and expected hash. Pending creation or owned-target
open happens relative to the held directory FD; validation reads the held
target FD and requires the current pathname to name the same device and inode.
Final publication verifies the old state hash from the held target FD, writes,
truncates, and fsyncs only that FD, verifies the pathname identity again, and
then atomically updates the ignored report-state hash. It never replaces the
report pathname. A path swap cannot redirect bytes into a replacement or user
inode. A crash during the in-place write leaves the old state hash against
partial report bytes, so the next resume fails closed. A swap after the last
provider pre-call validation may consume at most that already-reserved call;
persistent directory or target drift fails before another call or successful
publication.

## Versioning

- Behavior change: bump SemVer in `SKILL.md` `metadata.version`.
- Documentation-only wording change: do not bump the version unless
  behavior also changes.
- A live-harness or dated-report-only change does not bump the skill version.

## Required Verification

Required offline verification:

```bash
python3 skills/korean-writing-editor/evals/run.py --scope full
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
