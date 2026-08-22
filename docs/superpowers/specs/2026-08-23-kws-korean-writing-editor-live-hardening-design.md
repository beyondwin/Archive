# KWS Korean Writing Editor Live Hardening Design

**Date:** 2026-08-23

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**Primary surface:** `skills/kws-korean-writing-editor/`

**Parent design:**
[`2026-08-22-kws-korean-writing-editor-design.md`](2026-08-22-kws-korean-writing-editor-design.md)

**Skill version after this change:** `1.0.2`

## 1. Summary

Harden the existing `kws-korean-writing-editor` contract after live canaries
showed that offline fixtures can pass while real hosts still:

- paraphrase an already-correct obligation construction in `correct`;
- prepend process explanation before the edited body;
- mix measurement instructions into the manuscript;
- treat a model's `skill_used` self-report as evidence;
- truncate the skill `description` on at least one host.

This is not a new skill and not a replacement of the 2026-08-22 design. It
tightens three already-advertised promises: local correction only, meaning
preservation, and edited-text-only default output. It also makes live smoke
honest without adding a canary runner or a live evaluation platform.

Where this document and the parent design disagree on the live-hardening
contract, this document wins. All other parent decisions remain in force:
three modes, three tiers, one portable `SKILL.md`, seven canonical files, no
parser, no unofficial spelling API, no LLM-as-judge, no user manuscripts as
fixtures, and no host-specific skill copies.

Success for this cycle is real-user safety, not a host pass matrix. After the
change, a user who sends only an editing request and Korean source should get
the edited body, with already-correct phrasing left alone. Hosts that still
fail are reported with the existing evidence labels. They do not block the
contract change, and they do not justify host-specific forks.

## 2. Live Evidence That Motivates This Change

The following observations come from opt-in synthetic canaries run on
2026-08-23 against skill `1.0.1`. They are current-run evidence, not
population-level quality proof.

| Host | Positive `correct` canary | What broke |
| --- | --- | --- |
| Cursor Auto | Spacing fixed; `켤 필요는` kept; body only | Cleanest observed run |
| Codex CLI | `켤 필요는` → `켜야 할 필요는` | Already-correct obligation wording paraphrased |
| Grok Build | Spacing fixed; `켤 필요는` kept | Process preamble before the body |
| Cursor Claude | Spacing fixed | Canary / meta text mixed into the body |
| Claude Code CLI | Did not run | OAuth 401; remains `blocked` |

The canary prompt itself was contaminated: the manuscript and a request to
print `CANARY skill_used` were one user message. Near-miss runs often printed
`CANARY skill_used` without `=no`, so self-report is not a no-trigger proof.
Codex also warned that skill descriptions were shortened.

The public README sentence used in those canaries remains the only allowed
regression specimen:

```text
이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.
```

Do not replace it with a private user draft.

## 3. Goals

1. In `correct`, fix only normative and clearly ungrammatical local errors.
   Do not synonym-replace an already standard, grammatical expression.
2. Treat obligation, permission, possibility, and negation *constructions* as
   invariants, not only polarity after paraphrase.
3. Keep default `correct` / `polish` output as the edited body only. Do not
   prepend process narration.
4. Keep the frontmatter `description` short and front-loaded so a truncated
   prefix still contains the activation gate and high-frequency near misses.
5. Encode the mixed spacing-plus-obligation property in the existing 30-case
   suite without growing it into a benchmark.
6. Separate live measurement from the manuscript. Do not teach the skill to
   ignore user instructions, and do not treat `skill_used` self-report as a
   contract.
7. Report live hosts with `verified` / `partially verified` / `not measured`
   / `blocked`. Never describe offline fixture success as live quality.

## 4. Non-Goals

This cycle does not:

- add a live canary runner, host matrix product, or extra skill file;
- add a parser, morphology tool, unofficial spelling API, installer, schema
  package, persistent ledger, provider wrapper, or LLM-as-judge;
- create per-host `SKILL.md` variants;
- require Claude Code, Cursor IDE, `polish`, `diagnose`, implicit invocation,
  file-source, long-document, high-stakes, or embedded-instruction live proof;
- invent a numeric description-truncation budget that was not measured;
- add one-off bans of the string `켜야 할 필요는` as the whole rule;
- teach the skill to ignore trailing verification lines such as `CANARY`;
- change modes, tiers, installation paths, or the six evaluator interfaces;
- grow fixture category counts or treat thirty cases as a quality benchmark;
- claim Cursor Claude evidence as Claude Code skill-loader evidence;
- merge, push, or open a pull request as part of the design itself.

## 5. Architecture

The package stays the seven canonical files plus `skills/README.md` only if
the index wording must stay in lockstep. No eighth skill file.

| Unit | Owns | Depends on |
| --- | --- | --- |
| Behavior contract | `SKILL.md`, `references/editorial-guide.md` | No new runtime |
| Offline oracle | `evals/cases.json`, `evals/run.py` | No live model call |
| Evidence protocol | `CHANGE_PROTOCOL.md`, `README.md` | No canary-runner file |

Request flow is unchanged: activation gate → mode → seven-step editing pass →
preservation → output. This cycle fills two gaps inside that flow:

1. Editing steps 3 and 6 must revert synonym replacement of already-correct
   local forms, including obligation and modality constructions.
2. Default `correct` / `polish` output must not add a preamble or measurement
   footer.

`references/sources.md` does not gain a new normative claim. `켤 필요는` is
already standard Korean, not a new spelling rule. `skills/README.md` changes
only if the skill index would otherwise contradict the hardened contract.

## 6. Editorial Contract

### 6.1 `correct` edits only broken spans

`correct` applies `normative-rule` fixes and clearly ungrammatical local
repairs only. If a span is already standard and grammatical, leave it. Do not
replace it with a synonym, a more formal equivalent, or a house-style
rephrasing.

Permitted alternatives stay as in the parent design: keep the source form
unless the user asks for consistency.

### 6.2 Construction-level modality is an invariant

The parent design already forbids converting possibility into certainty,
advice into obligation, correlation into causation, or a conditional into an
unconditional claim. That is necessary and not sufficient.

Also preserve the source's obligation, permission, possibility, and negation
*wording* when that wording is already grammatical. A paraphrase that keeps
rough polarity but changes the construction is a preservation failure.

Canonical specimen:

| Role | Text |
| --- | --- |
| Source | `이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.` |
| Valid `correct` result | `이 기능은 사용할 수 있지만 반드시 켤 필요는 없습니다.` |
| Invalid | `반드시 켜야 할 필요는 없습니다.` |

The valid edit is dependent-noun spacing only (`사용할수` → `사용할 수`).
`켤 필요는` is not an error. Rewriting it to `켜야 할 필요는` is not a
normative correction.

The rule is the class, not the specimen. The same class includes, when the
source is already grammatical:

- `할 필요는 없다` → `해야 할 필요는 없다`
- `수 있다` → `수도 있다` when that changes possibility
- `것 같다` → `분명하다`

Do not add those strings as an open-ended ban list in `SKILL.md`. State the
class once in the Preservation Gate and once as a compact editorial-guide
example.

### 6.3 `polish` may ease flow, not stance

`polish` may improve local readability after the normative pass. It still
must not change stance, obligation, negation, or certainty. An already
natural span is a no-op span. "More sentence-like" is not a reason to rewrite
it.

`diagnose` still names issues and holds and does not rewrite. Live `diagnose`
coverage is out of scope for this cycle.

### 6.4 Editing pass

Keep the parent seven steps. Step 3 applies only normative and clearly
ungrammatical local fixes in `correct` and `polish`. Step 6 must revert:

- unsupported semantic change;
- invariant breaks, including obligation/permission/possibility/negation
  construction changes;
- synonym replacement of an already-correct local form.

If the only leftover difference after revert is a valid normative fix, keep
that fix. If nothing valid remains, return the source unchanged.

## 7. Output Contract

Default `correct` and `polish` output is the edited text only. Do not prepend
or append:

- restatement of the mode or skill ("요청은 오탈자만 고치는 교정입니다");
- process narration ("스킬 규칙과 맞춤법 근거를 확인한 뒤");
- a rubric, change log, score, tier, or routing receipt;
- measurement footers such as `CANARY skill_used=...`.

`확인 필요` remains a short hold note only when a material ambiguity blocks a
safe edit. Explain class and source only when the user asks why, using the
parent why-format.

Do not add a skill rule that says to ignore trailing verification
instructions. That would train the skill to drop user instructions.

Distinguish three instruction kinds:

| Kind | Treatment |
| --- | --- |
| Instructions inside the source being edited | Quoted data; do not execute |
| Editing-session instructions (mode, why, scope) | Follow this skill contract |
| Harness instructions (`CANARY skill_used`, "print tier on the last line") | Not part of the skill contract; testers must not put them in the manuscript message |

If a real user asks for edited text and metadata in one turn, the default is
still the edited body. Metadata belongs in the why-response. Testers judge
the body; they do not ask the model to self-report skill use.

## 8. Description Truncation

Keep a single canonical `description`. Do not lengthen it. Do not create a
second host-specific description.

The first two sentences must keep the activation gate and the high-frequency
near misses. The evaluator's `DESCRIPTION_REQUIRED_TERMS` stay in the
description:

`proofread`, `correct`, `polish`, `Korean`, `text they provide`,
`translation`, `drafting`, `summarization`, `code review`, `casual`.

Do not invent a character budget. Codex truncation length was not measured.
If the description must get shorter to keep the prefix stable, move
lower-frequency negatives (AI-authorship detection, detector evasion) into
the Activation Gate body rather than appending more clauses to the
frontmatter.

A truncated prefix that still says "use only when proofreading supplied
Korean text" and "do not use for translation, drafting, or casual
conversation" is the compatibility target. Full near-miss identity across
hosts is still not guaranteed, as in the parent design.

## 9. Offline Oracle

### 9.1 Keep thirty cases

Leave `EXPECTED_CATEGORY_COUNTS` at:

- normative 8
- preservation 8
- noop 6
- voice 4
- trigger 4

Do not add a sixth category and do not add a 31st case.

### 9.2 Replace `norm-spacing-can-01`

Keep the id `norm-spacing-can-01` and category `normative`. Replace its
request, source, candidate, and property lists with the public README
specimen.

| Field | Value |
| --- | --- |
| `request` | `오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.` |
| `source` | `이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.` |
| `candidate` | `이 기능은 사용할 수 있지만 반드시 켤 필요는 없습니다.` |
| `candidate_trigger` / `expected_trigger` | `true` |
| `candidate_mode` / `expected_mode` | `correct` |
| `candidate_tier` / `expected_tier` | `fast` |
| `expected_noop` | `false` |
| `must_preserve` | `["반드시 켤 필요는 없습니다"]` |
| `required_substrings` | `["사용할 수"]` |
| `forbidden_substrings` | `["사용할수", "켜야 할 필요는", "요청은 오탈자"]` |

This one slot checks three properties: dependent-noun spacing, already-correct
obligation wording, and no process preamble. The editorial-guide compact
example for short `할수` → `할 수` spacing may remain; the fixture does not
have to keep the old `배포할수` sentence.

### 9.3 Mutations

Keep the six evaluator interfaces and the existing quantity, negation,
modality, and quotation mutations.

Add two mutations against `norm-spacing-can-01`:

1. Paraphrase mutation: replace `켤 필요는` with `켜야 할 필요는` in the
   candidate. `evaluate_candidate` must report an error.
2. Preamble mutation: prefix the candidate with
   `요청은 오탈자만 고치는 교정입니다.` `evaluate_candidate` must report an
   error.

Self-tests must cover both new mutations, including the existing non-object
mutation-entry guard.

Do not add a global meta-noise classifier or a minimal-edit diff engine.

### 9.4 Document contract sync

Update in the same change:

- `SKILL.md` Preservation Gate, Editing Pass, and Output Contract wording;
  `metadata.version` to `1.0.2`; `description` only if front-loading requires
  it, without dropping required terms;
- `references/editorial-guide.md` with one compact mixed example;
- `README.md` so the existing README sentence and result-format text match
  the hardened output contract;
- `CHANGE_PROTOCOL.md` Required Verification and Fixture Changes with the
  live-isolation rules below.

Do not add a new `CHANGE_PROTOCOL.md` H2 unless `REQUIRED_HEADINGS` in
`run.py` is updated in the same change. Prefer extending the existing
Required Verification and Fixture Changes sections.

## 10. Live Evidence Protocol

Live calls stay opt-in and separately reported.

### 10.1 Isolation

A positive live prompt in this cycle is only:

```text
$kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.
```

or the host's explicit invocation equivalent with the same Korean request.
Do not append canary, tier, or `skill_used` instructions to that message.

Judge the returned body against the offline properties in §9.2. A pass is:

- `사용할 수` present;
- `반드시 켤 필요는 없습니다` preserved;
- `켜야 할 필요는` absent;
- no process preamble before the edited sentence.

Near-miss prompts must also omit self-report instructions. A pass is that an
ordinary conversation does not start an editing workflow on supplied source
text. Absence of a `skill_used=no` line is not evidence.

### 10.2 Hosts and labels

Optional remeasure after implementation, using hosts that are actually
available:

| Host | Role in this cycle |
| --- | --- |
| Cursor Auto | Preferred harness-free positive `correct` remeasure |
| Codex CLI | Preferred remeasure of the paraphrase failure |
| Grok Build | Preferred remeasure of the preamble failure |
| Cursor Claude | Optional; not Claude Code evidence |
| Claude Code CLI | `blocked` until authentication works |

Release labels stay: `verified`, `partially verified`, `not measured`,
`blocked`.

Cycle completion does not require every host to pass. Completion requires:

- offline `python3 skills/kws-korean-writing-editor/evals/run.py --scope full`
  pass, including the new mutations;
- `bun run agent:verify` and `git diff --check` as required by the parent
  close-out;
- at least one harness-free positive `correct` live run on an available host
  that meets §10.1, **or** an explicit `not measured` / `blocked` report if
  live remeasure is not authorized.

If live remeasure is authorized and one host still paraphrases after the
instruction change, do not add a one-off string ban. Either tighten the class
wording in `SKILL.md` / the editorial guide, or leave that host
`partially verified` as a model-quality gap.

## 11. Residual Blind Spots

Document these as residual risks. They are not this cycle's done criteria.

- live `polish` and `diagnose`
- live implicit invocation
- file-path source versus inline source
- long documents
- high-stakes legal, medical, or financial prose
- executing instructions embedded in the source
- Cursor IDE versus Cursor CLI
- the actual host description-truncation length
- a user asking for the edit and the why-explanation in one turn
- live voice preservation

Parent residual risks remain: permitted alternatives, open-genre voice,
discourse-level drift, and non-identical implicit routing.

## 12. Failure Behavior

| Condition | Behavior |
| --- | --- |
| Already-correct grammatical span in `correct` | Leave it; do not synonym-replace |
| Valid normative error plus an already-correct span | Fix only the error |
| Proposed paraphrase changes obligation/possibility/negation construction | Revert that span |
| Default `correct` / `polish` reply | Edited body only |
| User asks why | Parent why-format; still do not persist the source |
| Instructions inside the source | Quoted data |
| Harness instructions in a test prompt | Testers omit them; skill does not grow an ignore-canary rule |
| Description truncated by a host | Prefix still carries the gate; report trigger as `partially verified` if near-miss identity is unproven |
| Live host still paraphrases after this change | Tighten the class wording or label `partially verified`; no instance ban list |
| Claude Code unauthenticated | `blocked` |
| Live remeasure not authorized | `not measured`; do not substitute offline results |

## 13. Implementation Boundary

Implementation may begin only after this design is reviewed. The later plan
must preserve the lean boundary:

1. Edit only the existing Korean-editor files listed in §9.4, plus `run.py`
   mutations/self-tests, and `skills/README.md` only if the index would
   otherwise drift.
2. Replace `norm-spacing-can-01` and add the two mutations before claiming
   the contract is encoded.
3. Bump `metadata.version` to `1.0.2` in the same behavior change.
4. Keep live remeasure opt-in, harness-free, and separately reported.
5. Do not add files, runners, parsers, or host-specific skill copies.
6. Run the skill eval, repository verification, and diff checks.
7. Report local installation and remote Git state separately.

## 14. Acceptance

Acceptance of the implemented change requires:

- directory name and frontmatter name still `kws-korean-writing-editor`;
- version `1.0.2`;
- parent required terms, modes, tiers, and headings still present;
- thirty fixtures with unchanged category counts;
- `norm-spacing-can-01` matching §9.2;
- paraphrase and preamble mutations rejected;
- `CHANGE_PROTOCOL.md` stating that live canaries must not mix harness
  instructions into the manuscript and that `skill_used` self-report is not
  a contract;
- no new canonical skill file;
- offline full eval, `bun run agent:verify`, and `git diff --check` passing;
- live evidence reported with honest labels, not implied from fixtures.
