# Korean Writing Editor Live Evaluation

## Purpose And Evidence Boundary

This optional operator procedure compares the installed Korean Writing Editor
with its tracked source using only the synthetic cases in `live_cases.json`.
Only an operator with explicit authorization may run `--execute`; it may be
billable. A dry run, preflight, fixture pass, or blocked environment is not
evidence that a provider ran or that model quality was proven.

The approved baseline is 119 producer calls plus 3 independent review calls,
with a 122-call ceiling. A separately authorized remediation run may use at
most 38 calls, for one approved-cycle ceiling of 160. Starting multiple cycles
does not turn them into one approved 160-call result.

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

A missing executable or another pre-invocation prerequisite stops before
reservation and consumes zero calls; the run remains blocked. A requested
Cursor model known to be unavailable emits an honest zero-provider
`not_measured` receipt and consumes zero calls.

Receipt JSON uses an exact top-level key schema; unknown or omitted keys fail
closed. Explicit runner-version-10 compatibility permits its omitted
per-finding `certainty`, which reads as `hard`, and its original empty-finding
`partially_verified` shape. A positive call number can never claim
`not_measured`, including on resume, so a forged terminal receipt cannot hide a
charged call from the remaining-work or budget ledger.

## Safety And Privacy

Use synthetic prompts only. Do not place private manuscripts, credentials,
secrets, personal data, or full provider transcripts in `live_cases.json`,
receipts intended for review, commits, issues, or reports. Raw and normalized
provider bodies stay only in the ignored exact evidence root
`.superpowers/kws-korean-writing-editor/live`; reports contain hashes, status
facts, and only bounded redacted excerpts.

## Offline Validation

The offline command below does not call Codex, Cursor, or any provider and does
not authorize or prove live execution; it verifies only the thirty synthetic
offline fixtures and their mutation contract.

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
```

## Dry Run

This provider-free command prints only the approved call plan and budgets:

```bash
python3 skills/kws-korean-writing-editor/evals/live_matrix.py --dry-run
```

The payload must show 119 producer calls, 3 reviewer calls, and 122 baseline
calls, plus 38 remediation calls and `approved_total_ceiling` equal to 160.

## Baseline Preflight

Before execution, ensure that source and installed skill manifests match, the
relevant checkout is clean, and the approved run ID has only the complete Task
7 install bootstrap described below and no preflight or provider evidence.
Preflight writes the immutable identity to the ignored evidence root and makes
no provider call.

After Task 7's exact-target swap, the first non-resume preflight requires an
already-existing mode-`0700` real run directory whose complete contents are
exactly a real `install-previous` directory and a real mode-`0600`
`task-7-install-state.json` file; it never creates or accepts an absent, empty,
or partial run directory. Both `preflight.json` and `preflight-commit.json` must
be absent. The record's run ID, exact source/target/previous/stage paths, final
swap state, equal source/install hashes, and current source/install hashes must
match, while the complete previous tree is bounded and hashed recursively
through its held directory FD with no symlinks or special files.

Preflight holds the same run-directory FD, rechecks the exact install-state
bytes and recursive previous-tree manifest before and after publishing pending
mode-`0600` `preflight.json` and `preflight-commit.json` files, and never unlinks
either public name. A pending preflight or missing, partial, tampered, replaced,
unsafe, or oversized marker never authorizes reuse. The final marker suffix
write is the commit point; an fsync error after that complete write reports
committed success so a failed command cannot leave a reusable commit. The
completed marker binds the exact preflight device, inode, mode, size, SHA-256,
canonical bytes, bootstrap state and previous-tree binding, runner version, and
run ID. Reuse opens both files with bounded `O_NOFOLLOW` reads through the same
held run-directory FD and compares every current preflight payload field
exactly. It retains those three descriptors through execution and, immediately
before every provider attempt reservation, rechecks their exact held bytes and
metadata, both current evidence names, the bootstrap inputs, and the exact known
run-directory entry set. Completion of that recheck is the authorization
linearization point: a later swap can affect at most the immediately reserved
attempt, while persistent drift blocks every later reservation.

The approved Task 7 baseline run ID is
`kws-editor-20260823-baseline-02` because run-01 is already consumed, while the
approved operations artifact date remains intentionally `2026-08-23`. Keep
run-02 and that report date unchanged; do not substitute the current date.

```bash
RUN_ID="kws-editor-20260823-baseline-02"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --preflight --scope baseline --run-id "$RUN_ID" --jobs 3 --max-calls 122 \
  --evidence-root .superpowers/kws-korean-writing-editor/live \
  --report docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md
```

`--jobs` accepts 1 through 4. The report path must be the exact dated filename
under `docs/operations` shown above.

## Paid Baseline

After explicit authorization, execute the same preflighted identity. This is
the operation that may be billable.

```bash
RUN_ID="kws-editor-20260823-baseline-02"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --execute --scope baseline --run-id "$RUN_ID" --jobs 3 --max-calls 122 \
  --evidence-root .superpowers/kws-korean-writing-editor/live \
  --report docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md
```

Do not raise the baseline above 122. Remediation requires separate
authorization, and the approved baseline plus remediation total never exceeds
160.

## Resume

Use `--resume` only with `--execute` after an interrupted run, using the same
run ID and scope.

Resume validates the complete current preflight payload: run ID, runner
version, repository HEAD and branch, source and installed skill hashes,
`live_cases.json` hash, producer IDs, requested model IDs, scope, canonical
selected call IDs, CLI paths, versions and diagnostics, model availability, and
model-discovery digest and diagnostic. A missing field or any mismatch fails
closed and requires a new run ID.

When matching preflight state exists but both report target and report state
are absent, execute exclusively creates bounded pending content and persists
its exact state before any producer or reviewer dispatch. A target without
state, state without its exact target, an unsafe target, ownership drift, or
extra relevant checkout dirt fails before dispatch.

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

```bash
RUN_ID="kws-editor-20260823-baseline-02"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --execute --resume --scope baseline --run-id "$RUN_ID" --jobs 3 --max-calls 122 \
  --evidence-root .superpowers/kws-korean-writing-editor/live \
  --report docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md
```

Completed `verified`, `partially_verified`, `failed`, and `not_measured`
receipts remain complete. A `blocked` logical call may receive a new actual
`:attempt-N` ID only when spare budget remains.

Runner version 16 validates the exact receipt and nested identity/finding
schemas at load, publication, resume budgeting, report assembly, and review
sampling. Integers reject booleans and out-of-range values; timestamps, hashes,
stream byte/hash pairs, terminal statuses, evidence paths, call identity, and
reservation relationships must be coherent before a receipt can authorize any
later step. Every current `partially_verified` receipt carries at least one
typed `not_measured` finding. Immutable runner-version-10 evidence remains
readable with only its original omitted finding certainty and empty-finding
`partially_verified` shape treated as explicit legacy compatibility; it is not
reusable as a runner-version-16 execution identity.

## Review Packet

The baseline reserves three reviewer calls after the producer matrix. Review
packets contain bounded synthetic candidates rather than full transcripts.
Reviewer opinions are diagnostic evidence, not an automatic release decision
or a numeric truth score.

The packet contains at most eight evidence samples plus exactly four band
controls. Within those existing eight evidence slots, up to two deterministic
`semantic_not_measured` representatives are selected before hard-failure
representatives, prioritizing diagnostic and structural semantic families.
Each sample has an explicit `sample_kind`; hard findings and not-deterministically
measured signals remain separate, and representative case IDs and response
hashes stay bound to the durable receipt and are emitted into the canonical
review prompt. A missing control uses an explicit `not_measured` response-hash
sentinel. Changing either the validated case ID or response hash changes the
reviewer prompt hash, so a stale assessment cannot be reused for different
evidence. Activation-only soft evidence may be reported as a limitation, but
cannot displace both diagnostic and structural semantic representatives.
Selection is stable under input ordering, deduplicated,
identity-redacted, and never expands the 8+4 cap.

## Status Meanings

The dated report uses exactly these executed-evidence definitions:

- `verified`: the provider process executed, the returned body met every declared deterministic hard property, and every required semantic dimension was proven by a positive canonical form.
- `partially_verified`: the provider process executed and observed hard properties passed, but activation or a semantic dimension remained not deterministically measured.
- `failed`: the provider process executed and returned output violated at least one declared deterministic hard property.
- `blocked`: a positively reserved provider attempt could not produce usable evidence because execution or response processing failed.
- `not_measured`: no provider process was invoked for that evidence item; this is the only status permitted to have call number zero and no reservation.

The deterministic judge is three-valued. It NFC-normalizes bounded horizontal
whitespace, including NBSP, and canonicalizes safe quotation and Unicode
punctuation variants only for positive structural forms. Definite exact-output,
forbidden-output, numeric, literal-count, list-marker, code-span, and
quoted-instruction loss is a hard finding and produces `failed`. Free-form diagnose or
structural prose whose Korean scope, polarity, relation, or execution meaning
cannot be proven from a positive canonical form emits
`diagnostic_semantics_not_measured` or
`structural_semantics_not_measured` and produces `partially_verified`, never an
unsupported hard failure or `verified`. Finding certainty is serialized as
`hard` or `not_measured`; legacy receipts without the field remain readable as
`hard`. A response whose host activation cannot be observed and has no hard
failure adds `activation_not_measured`, including alongside another soft
signal. Reviewer packets and reports keep not-measured signals separate from
hard findings.

No aggregate average erases a severe failure. Every report states the level at
which a status applies.

## Remediation Budget

Keep 38 calls in reserve for a separately authorized `--scope remediation`
run. The remediation CLI defaults to 38 and rejects a higher value. Task 8
supplies the approved remediation run ID and exact immutable producer call IDs
from evidence; do not invent either value here. Repeat `--remediation-call`
only for those exact IDs, in canonical plan order.

```bash
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --preflight --scope remediation --run-id "<Task-8 approved remediation run ID>" \
  --jobs 3 --max-calls 38 \
  --remediation-call "<Task-8 exact planned producer call ID>" \
  --evidence-root .superpowers/kws-korean-writing-editor/live
```

```bash
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --execute --scope remediation --run-id "<Task-8 approved remediation run ID>" \
  --jobs 3 --max-calls 38 \
  --remediation-call "<Task-8 exact planned producer call ID>" \
  --evidence-root .superpowers/kws-korean-writing-editor/live
```

## Evidence Layout

Each successfully committed ignored run directory contains immutable
`preflight.json` and `preflight-commit.json` state, `attempt-reservations/`,
`receipts/`, `raw/`, and `normalized/` evidence plus report ownership state when
a report was requested. Positive reservation numbers and filenames are exactly
gap-free `1..N`; crash-only reservations are part of that ledger. Every
positive receipt matches the full reservation identity. Report ownership state
also persists the held target device, inode, and expected hash. Raw and
normalized bodies are local operational evidence, not report attachments.

The optional dated report is written only to
`docs/operations/YYYY-MM-DD-kws-korean-writing-editor-cross-model-evaluation.md`.

## Limitations

An explicit host invocation and a compliant returned body do not prove that the
host activated the skill internally. Cases whose activation is not observable
carry `activation_not_measured` and are `partially_verified`; the evaluator
does not infer hidden routing or activation from a self-report. Offline
fixtures and synthetic live evidence do not establish general writing quality,
authorship, or provider-wide reliability.
