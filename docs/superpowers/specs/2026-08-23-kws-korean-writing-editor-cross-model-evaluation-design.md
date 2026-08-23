# KWS Korean Writing Editor Cross-Model Evaluation Design

**Date:** 2026-08-23

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**Primary surface:** `skills/kws-korean-writing-editor/`

**Parent designs:**

- [`2026-08-22-kws-korean-writing-editor-design.md`](2026-08-22-kws-korean-writing-editor-design.md)
- [`2026-08-23-kws-korean-writing-editor-live-hardening-design.md`](2026-08-23-kws-korean-writing-editor-live-hardening-design.md)

**Current skill version:** `1.0.2`

## 1. Summary

Build and run a small, reproducible, opt-in cross-model evaluation for
`kws-korean-writing-editor`. The evaluation must test the installed skill in
fresh Codex and Cursor Agent sessions, find contract and quality defects,
separate host variance from portable skill defects, and document every
improvement with before-and-after evidence.

The approved matrix contains one direct Codex host plus six Cursor Agent
models. Every producer runs the same fourteen synthetic cases and three
independent critical repeats. Three cross-family reviewers then inspect a
bounded, model-anonymized packet containing failure classes and passing
controls. Deterministic preservation checks remain authoritative for hard
invariants; reviewer opinions are diagnostic evidence, not an automatic vote.

This design intentionally supersedes two cycle-specific non-goals in the
live-hardening design: this follow-up may add a live evaluation runner and
additional evaluation/documentation files. It does not change the runtime
editing flow, add a provider dependency to user requests, create host-specific
skill copies, or turn the thirty-case offline oracle into a quality benchmark.
All other parent-design decisions remain in force.

The first live matrix is a dated measurement of synthetic cases, not proof of
population-level Korean writing quality. Results must use `verified`,
`partially verified`, `failed`, `blocked`, and `not measured` precisely and
must preserve local-versus-remote scope.

## 2. Context

Skill `1.0.2` already incorporates a prior live-hardening pass. That pass found
that offline fixtures could succeed while live hosts still paraphrased an
already-correct obligation construction, prepended process narration, or mixed
measurement text into the edited body. It also established that model
`skill_used` self-report is not evidence and that a live prompt must not mix
the manuscript with harness instructions.

The current offline evaluator checks thirty property fixtures and synchronized
documentation. It is deliberately not a live dispatcher. The installed
`~/.agents/skills/kws-korean-writing-editor` copy matched the tracked source at
design time, and the `1.0.2` hardening commits were already ancestors of local
`main`. Those observations are pre-design context only; implementation must
repeat all checkout, installation, and hash checks.

Cursor Agent currently exposes the approved model identifiers, but provider
availability is time-sensitive. The live preflight must discover them again
rather than treating this design-time list as proof that a later run can use
them.

## 3. Goals

1. Exercise `diagnose`, `correct`, conservative `polish`, no-op, hold, and
   excluded near-miss behavior in real host sessions.
2. Detect preservation failures involving negation, modality, obligation,
   quantities, dates, names, attribution, quotations, URLs, code spans,
   Markdown structure, causality, and writer voice.
3. Detect output-contract failures such as process narration, mode
   restatement, change logs, or measurement footers.
4. Test instructions embedded in source text as quoted data rather than agent
   commands.
5. Compare one direct Codex execution path with six distinct Cursor Agent
   model families without routing the Codex measurement through Cursor.
6. Make live execution opt-in, bounded, resumable, redacted, and resistant to
   accidental duplicate billing.
7. Turn reproducible portable defects into minimal synthetic offline
   regressions before modifying the skill contract.
8. Record model-specific failures and subjective disagreement honestly rather
   than optimizing the portable skill for one provider.
9. Produce a durable operations report containing exact hashes, commands,
   results, changes, blockers, and residual blind spots.

## 4. Non-Goals

This work does not:

- add live calls, a model panel, or a classifier to an ordinary editing
  request;
- choose or benchmark the best general-purpose Korean model;
- establish a population-level model-quality score or leaderboard;
- use an LLM-as-judge result as an automatic release gate;
- persist private user manuscripts, user style profiles, or real user drafts;
- ask models to print `skill_used`, tier, mode, canary, or routing receipts;
- use unofficial spelling services, a morphology dependency, or a provider
  SDK;
- create separate `SKILL.md` variants for Codex, Cursor, Claude, Gemini, Grok,
  Kimi, or GLM;
- make one provider's wording preference a universal Korean rule;
- copy a live failure response verbatim into the permanent fixture corpus;
- require every model to pass before a portable contract defect can be fixed;
- add Claude Code, Grok Build, Cursor IDE UI, long-document, file-source, or
  private-corpus coverage to this matrix;
- push, open a pull request, deploy, or modify remote state without a separate
  request.

## 5. Architecture

The live evaluator is a development-only companion to the existing offline
oracle.

```text
tracked skill + tracked synthetic cases
                |
                v
        hash-locked run manifest
                |
        +-------+----------------------+
        |                              |
        v                              v
Codex ephemeral session       fresh Cursor Agent session
per case and repeat           per model, case, and repeat
        |                              |
        +---------------+--------------+
                        v
             bounded local raw evidence
                        |
                        v
          deterministic property evaluation
                        |
                        v
       anonymized bounded cross-review packet
                        |
                        v
          Codex supervisory adjudication
                        |
                        v
       defect register and minimal regression
```

### 5.1 Units

| Unit | Owns | Must not own |
| --- | --- | --- |
| Live cases | Fourteen synthetic prompts, properties, review axes, repeat flags | Provider credentials or private text |
| Live runner | Preflight, dispatch, bounded capture, receipts, resume, call budget | Editing decisions or runtime model routing |
| Deterministic evaluator | Literal, substring, occurrence, unchanged, structure, and output-shape checks | Subjective naturalness |
| Review packet builder | Model-anonymized failures and passing controls | Final pass/fail authority |
| Operations report | Dated evidence, defects, changes, blockers, limitations | Full provider transcripts or secrets |
| Existing offline oracle | Permanent contract properties and document synchronization | Claims about live provider quality |

### 5.2 Runtime separation

Nothing in `SKILL.md` invokes the live runner. Ordinary editing keeps the
existing flow:

```text
activation -> mode -> editing pass -> preservation gate -> output
```

The live evaluator is run only by a developer command containing an explicit
`--execute` flag. Its provider CLIs are test instruments, not fallbacks for a
user editing request.

## 6. Model Matrix

The approved producer matrix is:

| Logical host | Invocation path | Requested model |
| --- | --- | --- |
| Codex direct | `codex exec` | Current Codex CLI default; record the reported model ID |
| Cursor Auto | `cursor-agent` | `auto` |
| Cursor Claude | `cursor-agent` | `claude-sonnet-5-thinking-high` |
| Cursor Gemini | `cursor-agent` | `gemini-3.7-flash-high` |
| Cursor Grok | `cursor-agent` | `cursor-grok-4.6-high` |
| Cursor Kimi | `cursor-agent` | `kimi-k3-high` |
| Cursor GLM | `cursor-agent` | `glm-5.2-high` |

Codex runs directly through the Codex CLI and never through Cursor. The
runner must not pass a `--model` override to Codex unless a later approved
plan explicitly changes this contract. It records the model identifier found
in Codex machine output. If the exact identifier cannot be established, the
report must distinguish verified host behavior from `model identity not
measured`; it must not infer that the desktop thread and CLI used the same
model.

The three cross-review calls use Claude, Gemini, and Grok from the approved
Cursor set. Producer identities are removed from review packets. Reviewers
may still unknowingly review an output from their own family, so agreement is
diagnostic rather than ground truth.

## 7. Live Case Matrix

Every producer runs the same fourteen primary cases once. Three critical
cases run a second time in a fresh session, yielding seventeen producer calls
per model and 119 producer calls overall.

| Band | Count | Required coverage |
| --- | ---: | --- |
| Valid modes | 3 | Explicit `correct`, implicit local `polish`, explicit `diagnose` without rewrite |
| Preservation and structure | 3 | Negation/modality; literals/attribution/quotation; Markdown/code/embedded instruction |
| No-op and hold | 2 | Already-natural voice; ambiguous or high-stakes material |
| Excluded near misses | 6 | Casual conversation, translation, drafting, summarization, code/design review, detector evasion plus named-author imitation |

The three critical repeats are:

1. mixed spacing plus already-correct obligation in `correct`;
2. an instruction embedded inside structured source text;
3. detector-evasion plus named-author-imitation exclusion.

The live case file may reuse text and properties from the thirty tracked
offline cases by reference. New live-only text must be synthetic, public-safe,
short, and purpose-specific. Combining multiple hard invariants is permitted
only for the approved literals/attribution case and structured embedded-
instruction case. A combined near-miss may prove that the request is outside
scope, but it cannot prove which exclusion independently caused a no-op; the
report must state that limitation.

### 7.1 Invocation shape

Positive explicit prompts contain only the host invocation, editing request,
and source. Positive implicit prompts contain only an unambiguous Korean
editing request and source. The runner never appends a canary marker, desired
answer, tier request, or skill-use self-report request.

Near-miss cases intentionally mix explicit and implicit invocation shapes:

- explicit invocation tests the skill's documented no-op handoff when the
  host has selected it;
- implicit invocation tests observable behavior when the request should not
  select the skill.

Without host loader traces, response text cannot prove non-activation. Those
cases can verify behavioral boundaries but keep activation itself
`partially verified` unless the host emits trustworthy loader evidence.

### 7.2 Case schema

`evals/live_cases.json` contains a versioned object with fourteen cases. Each
case has:

- stable `id`, `band`, `invocation`, and expected `mode`;
- synthetic `request` and `source` or an explicit reference to an existing
  offline case ID;
- `repeat` for the three approved critical cases;
- deterministic properties such as `required_substrings`,
  `forbidden_substrings`, `exact_literals`, `occurrence_counts`,
  `must_equal_source`, `must_not_rewrite`, and structural sentinels;
- review axes selected from meaning, voice, minimality, naturalness, hold, and
  boundary behavior;
- one short rationale describing what the case proves and what it cannot
  prove.

The schema does not contain provider model IDs, scores, or expected prose for
subjective polishing. Exact expected output is allowed only where the contract
really has one mechanically correct result.

## 8. Execution And Evidence Flow

### 8.1 Baseline preflight

Before a paid call, the runner records and validates:

- repository root, branch, HEAD, and tracked status;
- tracked skill version and recursive manifest hash;
- installed skill path, entry type, ownership boundary, and manifest hash;
- offline case and live case hashes;
- `codex` and `cursor-agent` executable paths and versions;
- current Cursor model discovery output;
- requested model availability;
- run plan, planned call count, concurrency, timeouts, and output limits;
- the ignored evidence root under `.superpowers/`.

The first baseline requires the installed skill manifest to match the tracked
skill manifest. A mismatch blocks paid execution. Offline `--self-test` and
`--scope full` must also pass before live dispatch.

### 8.2 Provider commands

Codex calls use the equivalent of:

```text
codex exec --ephemeral --sandbox read-only --json --cd <repository> <prompt>
```

Cursor calls use the equivalent of:

```text
cursor-agent --print --output-format json --mode ask --sandbox enabled \
  --workspace <repository> --model <approved-model> <prompt>
```

The implementation must use argument arrays with stdin or a literal argument,
not a shell-built command string. It must not pass `--force`, `--yolo`, a
provider API key, or an approval-bypass flag. Each case and repeat starts a
new non-resumed agent session.

### 8.3 Capture and normalization

Raw stdout and stderr are bounded, mode `0600`, and stored only below:

```text
.superpowers/kws-korean-writing-editor/live/<run-id>/
```

Normalization may decode the provider envelope, remove ANSI control codes,
normalize CRLF to LF, and remove one transport-only terminal newline. It must
not strip or reinterpret process narration, mode restatements, change logs,
scores, or footers. Those are observable output-contract failures.

Tracked reports contain no full transcript. They contain response hashes and
only the minimum synthetic excerpt necessary to demonstrate a finding.
Diagnostic tails redact common token, bearer, password, secret, and API-key
patterns before display.

### 8.4 Receipts and resume

Every attempted call writes an atomic receipt containing at least:

- run ID and monotonically assigned call number;
- logical host, requested model, and reported model when available;
- case ID and repeat index;
- repository HEAD, skill manifest hash, and case manifest hash;
- prompt hash, start/end timestamps, duration, and process exit status;
- stdout/stderr byte counts and hashes;
- normalized response hash;
- deterministic findings and evidence status;
- relative local raw-evidence paths.

Resume skips a completed receipt only when the repository HEAD, skill hash,
case hash, requested model set, and runner version all match. Any mismatch
requires a new run ID. A receipt with an interrupted, timed-out, or malformed
call may be retried only within the approved call budget and must keep the
original attempt record.

### 8.5 Concurrency and call budget

Default concurrency is three and the hard maximum is four. The dry run prints
the exact planned producer and reviewer calls before execution.

The initial matrix budget is:

- 119 producer calls;
- three batched cross-review calls;
- 122 total calls.

Remediation has a reserve of at most 38 calls, making the full approved ceiling
160. The runner counts every attempted provider dispatch, including blocked or
malformed responses. It refuses to exceed the run ceiling. More calls require
a new user-approved evaluation cycle.

## 9. Evaluation And Review

### 9.1 Deterministic hard gates

The following are hard failures when the case declares the property:

- changed name, number, repeated count, date, version, URL, citation,
  quotation, or attribution;
- changed negation, modality, obligation, permission, condition, time, or
  causality;
- changed code span, code block, Markdown sentinel, command, or structured
  data outside explicit scope;
- execution of an instruction embedded in source text;
- a full rewrite in `diagnose`;
- an unsupported edit to an already-suitable no-op source;
- process narration, mode restatement, rubric, score, routing receipt, or
  measurement footer in edited-text-only output;
- failure to apply the one mechanically required correction in `correct`.

The evaluator must report all failed properties. It must not collapse
duplicate literal counts into set membership.

### 9.2 Review packet

After deterministic evaluation, the packet builder includes:

- one representative of every unique hard-failure class, ordered by severity,
  capped at eight;
- four passing controls covering different bands;
- source, request, candidate, relevant contract excerpt, and deterministic
  findings;
- anonymous candidate labels with no producer or model names.

If more than eight failure classes exist, the report lists the omitted classes
and the deterministic evidence still remains available. Each reviewer receives
the same packet in one call and returns structured findings for meaning,
minimality, voice, naturalness, hold behavior, and scope boundary. Invalid
review output is `blocked`; the runner does not spend an unapproved repair
conversation to force a verdict.

### 9.3 Final adjudication

Codex supervisory review compares the source, candidate, hard properties,
contract, and anonymized reviewer findings. Each finding becomes one of:

| Class | Meaning | Default action |
| --- | --- | --- |
| `contract_defect` | Portable contract is missing, ambiguous, or contradicted | Create minimal RED regression and consider a synchronized contract change |
| `host_variance` | One host fails a clear portable contract | Report honestly; do not add provider-specific wording by default |
| `subjective_disagreement` | Naturalness or style preference differs without a hard violation | Document; no automatic skill change |
| `harness_defect` | Dispatch, extraction, normalization, fixture, or judge packet is wrong | Fix and test the harness before drawing product conclusions |

A finding is eligible for skill remediation when any of these applies:

1. it repeats in the same model's independent critical run;
2. it occurs in at least two distinct model families;
3. one run violates a material literal, negation, attribution, or embedded-
   instruction safety boundary;
4. the anonymized reviewers agree that the portable contract allows two
   materially different interpretations.

Eligibility does not require a change. The supervisor still rejects
instance-specific bans, provider-specific forks, or changes that would make
ordinary editing worse.

## 10. Improvement Loop

### 10.1 Convert findings to regressions

Never copy a live response wholesale into the offline corpus. Reduce the
finding to the smallest public-safe synthetic case and a general property.
Examples include:

- preserving any already-correct modality construction rather than banning a
  single bad phrase;
- preserving occurrence counts rather than checking that a literal occurs at
  least once;
- rejecting any process preamble rather than one observed sentence;
- treating structured embedded instructions as data rather than banning an
  observed command string.

### 10.2 TDD and contract synchronization

For an accepted behavior defect:

1. add a failing offline property or evaluator self-test;
2. confirm the intended RED failure;
3. minimally update the behavior contract;
4. synchronize `SKILL.md`, relevant editorial guidance, fixtures/evaluator,
   `README.md`, and `CHANGE_PROTOCOL.md` as required;
5. run the offline suite before any paid remediation call.

Harness defects use `test_live_matrix.py` RED/GREEN tests and do not bump the
skill version. Behavior changes are consolidated into one SemVer bump, expected
to be `1.0.3`; if no behavior changes are accepted, the skill stays `1.0.2`.

### 10.3 Candidate installation

Paid remediation must exercise the installed skill, not only a prompt that
quotes the tracked file. Before changing the exact
`~/.agents/skills/kws-korean-writing-editor` target, implementation must:

- resolve the target without a broad glob or unresolved home variable;
- confirm it is the expected skill directory and record its manifest hash;
- create a recoverable backup under the ignored run root;
- stage the new copy separately and verify its manifest;
- atomically swap only the exact target;
- restore the previous copy if candidate verification fails.

Do not delete or replace `~/.agents/skills`, `$HOME`, `$CODEX_HOME`, or an
unrelated skill. Claude-specific installation is outside this matrix.

### 10.4 Bounded remediation evidence

Do not rerun the complete 119-call matrix after every edit. Use the 38-call
reserve for the failing host, direct Codex, and one passing comparison host on
the affected case plus approved critical controls. Consolidate behavior edits
before remediation. If the reserve cannot close the defect, restore the safest
candidate state and report the unresolved risk without exceeding the budget.

## 11. Failure Handling

| Failure | Evidence status | Treatment |
| --- | --- | --- |
| CLI missing or unauthenticated | `blocked` | Do not substitute another host |
| Requested Cursor model absent | `not measured` | Record discovery evidence; do not silently use Auto |
| Rate limit or provider outage | `blocked` | Keep the attempt receipt; bounded retry only if budget remains |
| Timeout, truncation, malformed envelope | `blocked` | Execution failure, not writing-quality failure |
| Deterministic and reviewer conflict | `harness_defect` candidate | Manual source comparison before product conclusion |
| One model's non-material wording preference | `host_variance` or `subjective_disagreement` | No prompt expansion by default |
| Literal, negation, attribution, or embedded-instruction violation | `failed` | Immediate severe finding and minimal regression |
| Installed-copy drift | `blocked` | Reconcile exact target before a paid call |
| Dirty relevant checkout | `blocked` | Preserve user work; do not evaluate an unidentified candidate |
| Call ceiling reached | `blocked` | Stop and document residual risk |

## 12. Status Semantics

Statuses apply per case, dimension, model, and aggregate. Reports must state
the level to avoid implying more evidence than exists.

| Status | Meaning |
| --- | --- |
| `verified` | The executed synthetic evidence passed every declared hard property for that level |
| `partially verified` | Some observable properties passed, but activation, identity, subjective quality, or required coverage remains unproven |
| `failed` | Executed output violated at least one declared hard property |
| `blocked` | The intended measurement could not complete because of execution or environment failure |
| `not measured` | The matrix deliberately or unavoidably did not execute that dimension or model |

No aggregate average can erase a severe failure. A failed host does not prove
that every user request fails, and a verified matrix does not prove general
Korean quality.

## 13. Tracked Files And Documentation

The planned tracked additions are:

- `skills/kws-korean-writing-editor/evals/live_cases.json`
- `skills/kws-korean-writing-editor/evals/live_matrix.py`
- `skills/kws-korean-writing-editor/evals/test_live_matrix.py`
- `skills/kws-korean-writing-editor/evals/README.md`
- `docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md`

The operations report is dated evidence and does not ship inside the installed
skill copy. It must include:

1. repository HEAD, branch, local/remote state, skill version, and source plus
   installed manifest hashes;
2. exact CLI versions, requested/reported model IDs, run IDs, case counts, and
   call counts;
3. model-by-band result tables using the defined status semantics;
4. defect register with severity, reproduction, minimal evidence, and
   classification;
5. anonymized review agreement and disagreement without treating it as a
   numeric truth score;
6. adopted and rejected improvements with reasons;
7. before-and-after offline and live evidence;
8. blocked or unmeasured work, residual blind spots, and non-generalization
   warnings;
9. changed files and exact command results;
10. local commit, branch, remote publication, and installation state.

`skills/kws-korean-writing-editor/README.md` links the opt-in evaluator guide,
and `CHANGE_PROTOCOL.md` states when live case, runner, report, and behavior
contract changes must stay synchronized. Behavior findings may additionally
modify `SKILL.md`, `references/editorial-guide.md`, `evals/cases.json`, and
`evals/run.py` under the existing protocol.

## 14. CLI Contract

The exact argument names may be refined in the implementation plan, but these
interfaces are required:

- offline shape validation that never calls a provider;
- explicit paid execution flag;
- baseline and bounded-remediation scopes;
- caller-supplied or generated run ID;
- resumable execution with immutable manifest checks;
- requested model selection from the approved matrix;
- configurable concurrency with hard maximum four;
- explicit call ceiling that cannot exceed the approved 160-call total;
- machine-readable final receipt and human-readable summary;
- non-zero exit for preflight, integrity, budget, or required-run failure.

The evaluator remains Python standard-library only. It dispatches the installed
`codex` and `cursor-agent` executables; it does not add provider SDKs.

## 15. Verification

Required deterministic verification after implementation:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
python3 -m unittest skills/kws-korean-writing-editor/evals/test_live_matrix.py
python3 skills/kws-korean-writing-editor/evals/live_matrix.py --dry-run
bun run agent:verify
git diff --check
```

Required live evidence:

1. initial baseline preflight with zero provider dispatch;
2. the approved 119 producer calls or an explicit per-model `blocked` / `not
   measured` record;
3. three bounded cross-review calls or an explicit blocked record;
4. accepted-defect remediation calls within the 38-call reserve;
5. final source-versus-installed manifest equality for the retained candidate.

Review the complete change against `code_review.md`. Report any skipped
opt-in evidence, exact reasons, and whether it blocks a model, a dimension, or
the whole conclusion.

## 16. Definition Of Done

This work is complete only when:

- the live evaluator and its offline tests pass;
- the existing thirty-case offline contract and document checks pass;
- every approved model has an executed status or an honest `blocked` / `not
  measured` status;
- every material live finding is classified with reproducible evidence;
- every accepted behavior defect has a RED regression, synchronized contract
  change, and bounded before-and-after evidence;
- rejected changes include a reason, especially for provider-specific or
  subjective suggestions;
- the retained installed skill manifest matches the reported tracked skill
  manifest;
- the dated operations report documents exact commands, hashes, call counts,
  limitations, changed files, and local-versus-remote state;
- deterministic gates, whole-change review, and `git diff --check` pass;
- no private text, secret, full transcript, cache, or `.superpowers` runtime
  state enters Git.

Completion does not require every model to pass. It requires the portable
skill to incorporate justified general fixes, the remaining host variance to
be explicit, and the evidence claims to match what actually ran.

## 17. Approved Decisions

The user approved the following sequence on 2026-08-23:

1. a reproducible small cross-model evaluator rather than a one-off manual
   matrix or a large LLM-judge benchmark;
2. direct Codex plus Cursor Auto, Claude Sonnet 5 Thinking, Gemini 3.7 Flash,
   Grok 4.6, Kimi K3, and GLM 5.2;
3. fourteen base cases and three critical repeats per producer;
4. deterministic hard gates plus a three-model anonymized review packet;
5. a 122-call initial ceiling and 38-call remediation reserve, 160 total;
6. exact-target recoverable installed-skill swaps for candidate live tests;
7. dated operations documentation, raw evidence outside Git, and honest status
   semantics;
8. one consolidated skill version bump only if behavior changes.
