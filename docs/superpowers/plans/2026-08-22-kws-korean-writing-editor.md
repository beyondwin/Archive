# KWS Korean Writing Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small, evidence-backed Korean proofreading and polishing skill that activates narrowly, preserves meaning and voice, and can be discovered by Codex, Claude Code, Cursor, and Grok Build.

**Architecture:** Keep one portable `SKILL.md` as the behavior contract, two compact references for editorial guidance and evidence, two user/change documents, and a Python standard-library property evaluator with about 30 fixtures. Model routing is a three-tier policy inside the skill; it delegates at most once only when the active host already supports model selection, and otherwise uses the active model without adding an orchestration layer.

**Tech Stack:** Agent Skills Markdown/YAML frontmatter, Korean documentation, JSON fixtures, Python 3 standard library, repository `bun run agent:verify` checks

**Spec:** `docs/superpowers/specs/2026-08-22-kws-korean-writing-editor-design.md`

## Global Constraints

- Canonical skill name and directory: `kws-korean-writing-editor`.
- Create exactly seven files under `skills/kws-korean-writing-editor/`: `SKILL.md`, `README.md`, `CHANGE_PROTOCOL.md`, `references/editorial-guide.md`, `references/sources.md`, `evals/cases.json`, and `evals/run.py`.
- Modify `skills/README.md` only to list the skill, broaden the source-of-truth wording, and document its current portable installation paths.
- Support only existing Korean source text in v1: `diagnose`, `correct`, and conservative `polish`.
- Prefer explicit invocation; implicit invocation requires both a clear Korean-editing request and supplied source text.
- Exclude translation, drafting, summarization, general writing advice, code review, casual conversation, named-author imitation, and AI-detector evasion.
- Preserve facts, personal experience, names, dates, numbers, units, URLs, citations, quotations, attribution, negation, modality, conditions, and causal direction.
- Do not add a parser, external API, morphology dependency, persistent ledger, provider wrapper, installer, schema package, or model-judge loop.
- Use only portable Agent Skills frontmatter in the canonical skill. Do not add provider-only `allowed-tools`, model, effort, hooks, paths, or subagent fields.
- Model tiers are `fast`, `balanced`, and `frontier`; do not hard-code provider model names or call a separate classifier model.
- Make at most one delegated editing-model call, and only when the host already exposes a documented configured capability.
- Default output is the edited text only. Add `확인 필요` only for a material ambiguity or hold; explain changes only on request.
- Keep live provider calls separate and opt-in. Never report offline fixtures as live model-quality evidence.
- Do not copy third-party rule lists or corpora. Record source scope and rights limitations instead.
- Use TDD for the evaluator and behavior contract. Keep commits task-local.

---

## File Map

| File | Responsibility |
| --- | --- |
| `skills/kws-korean-writing-editor/SKILL.md` | Narrow trigger, modes, editing sequence, hard boundaries, default output, and model-tier policy. |
| `skills/kws-korean-writing-editor/README.md` | One-minute Korean quick start, runtime invocation, examples, installation/update/removal, privacy, and limitations. |
| `skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md` | Synchronization rules for trigger, behavior, evidence, fixtures, docs, and version metadata. |
| `skills/kws-korean-writing-editor/references/editorial-guide.md` | Normative-versus-editorial decision classes, compact genre guidance, holds, and voice-preservation examples. |
| `skills/kws-korean-writing-editor/references/sources.md` | Direct sources, evidence classes, checked date, scope, and reuse limitation. |
| `skills/kws-korean-writing-editor/evals/cases.json` | Thirty property-oriented reference cases and expected trigger/mode/tier behavior. |
| `skills/kws-korean-writing-editor/evals/run.py` | Standard-library schema, property, mutation, and skill-tree validator. |
| `skills/README.md` | Repository index and portable skill discovery guidance. |

## Evaluator Interface

`evals/run.py` owns these exact interfaces:

```python
load_cases(path: pathlib.Path) -> list[dict[str, object]]
validate_case(case: dict[str, object]) -> list[str]
evaluate_candidate(case: dict[str, object]) -> list[str]
validate_skill_tree(skill_root: pathlib.Path, scope: str) -> list[str]
run_self_tests() -> unittest.result.TestResult
main(argv: list[str] | None = None) -> int
```

Supported commands:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
python3 skills/kws-korean-writing-editor/evals/run.py --scope fixtures
python3 skills/kws-korean-writing-editor/evals/run.py --scope core
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
```

The `scope` contract is:

- `fixtures`: validate all 30 fixture records, reference candidates, and
  deliberate mutations;
- `core`: `fixtures` plus `SKILL.md`, `references/editorial-guide.md`, and
  `references/sources.md`;
- `full`: `core` plus `README.md` and `CHANGE_PROTOCOL.md`, directory/name
  parity, required headings, relative links, and root `skills/README.md`
  discoverability.

Each case has this shape:

```json
{
  "id": "meaning-negation-01",
  "category": "preservation",
  "request": "자연스럽게 다듬어줘: 현재 버전에서는 이 기능을 끌 수 없지는 않습니다.",
  "source": "현재 버전에서는 이 기능을 끌 수 없지는 않습니다.",
  "candidate": "현재 버전에서도 이 기능을 끌 수 없지는 않습니다.",
  "candidate_trigger": true,
  "candidate_mode": "polish",
  "candidate_tier": "balanced",
  "expected_trigger": true,
  "expected_mode": "polish",
  "expected_tier": "balanced",
  "expected_noop": false,
  "must_preserve": ["없지는 않습니다"],
  "required_substrings": ["없지는 않습니다"],
  "forbidden_substrings": ["반드시 켜야 합니다"],
  "rationale": "Double negation is awkward but changing it without context can reverse the intended stance."
}
```

`evaluate_candidate` returns stable error strings prefixed with the case ID.
It checks exact occurrence counts for every `must_preserve` value, required
substrings, forbidden substrings, no-op equality, and the candidate-versus-
expected trigger, mode, and tier fields. It does not calculate an AI score,
readability score, embedding score, or semantic similarity score.

---

### Task 1: Build The Small Property Evaluator And Thirty Fixtures

**Files:**
- Create: `skills/kws-korean-writing-editor/evals/run.py`
- Create: `skills/kws-korean-writing-editor/evals/cases.json`

**Interfaces:**
- Consumes: Only Python 3 standard-library modules and the evaluator interface defined above.
- Produces: `--self-test`, `--scope fixtures`, `--scope core`, and `--scope full`; later tasks rely on their exit codes and stable error messages.

- [ ] **Step 1: Write the failing inline evaluator tests**

Create `evals/run.py` with imports, the CLI entry point, and a
`unittest.TestCase` named `EvaluatorTests`. The first tests must call the not-yet-defined
`validate_case`, `evaluate_candidate`, and `validate_skill_tree` functions and
assert these exact behaviors:

```python
def valid_case(self, **overrides):
    case = {
        "id": "case-01",
        "category": "preservation",
        "request": "다듬어줘",
        "source": "출시하지 않을 수 있다.",
        "candidate": "출시하지 않을 수 있다.",
        "candidate_trigger": True,
        "candidate_mode": "polish",
        "candidate_tier": "balanced",
        "expected_trigger": True,
        "expected_mode": "polish",
        "expected_tier": "balanced",
        "expected_noop": True,
        "must_preserve": ["출시하지 않을 수 있다"],
        "required_substrings": ["출시하지 않을 수 있다"],
        "forbidden_substrings": ["반드시 출시한다"],
        "rationale": "Negation and modality are material.",
    }
    case.update(overrides)
    return case

def test_rejects_missing_required_field(self):
    errors = validate_case({"id": "broken"})
    self.assertIn("broken: missing category", errors)

def test_preserved_literal_uses_occurrence_count(self):
    case = {
        "id": "duplicate-number",
        "category": "preservation",
        "request": "다듬어줘",
        "source": "7명 중 7명이 동의했다.",
        "candidate": "7명이 동의했다.",
        "candidate_trigger": True,
        "candidate_mode": "polish",
        "candidate_tier": "balanced",
        "expected_trigger": True,
        "expected_mode": "polish",
        "expected_tier": "balanced",
        "expected_noop": False,
        "must_preserve": ["7"],
        "required_substrings": [],
        "forbidden_substrings": [],
        "rationale": "Duplicate counts must survive.",
    }
    self.assertIn("duplicate-number: occurrence count changed for '7': 2 -> 1", evaluate_candidate(case))

def test_mutated_negation_is_rejected(self):
    case = self.valid_case(candidate="출시할 수 있다.")
    case["required_substrings"] = ["출시하지 않을 수 있다"]
    self.assertIn("case-01: missing required substring '출시하지 않을 수 있다'", evaluate_candidate(case))

def test_full_scope_requires_readme(self):
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        errors = validate_skill_tree(root, "full")
    self.assertIn("skill tree: missing README.md", errors)
```

Dispatch `--self-test` by loading this test case with
`unittest.defaultTestLoader.loadTestsFromTestCase(EvaluatorTests)` and returning
exit 0 only when it succeeds.

- [ ] **Step 2: Run the inline tests to verify RED**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
```

Expected: FAIL with `NameError: name 'validate_case' is not defined`.

- [ ] **Step 3: Implement the evaluator functions**

Add the six exact interfaces from the evaluator section. Use `json`,
`argparse`, `pathlib`, `re`, `sys`, `tempfile`, and `unittest` only.

Implement these concrete rules:

```python
REQUIRED_CASE_FIELDS = (
    "id", "category", "request", "source", "candidate",
    "candidate_trigger", "candidate_mode", "candidate_tier",
    "expected_trigger", "expected_mode", "expected_tier",
    "expected_noop", "must_preserve", "required_substrings",
    "forbidden_substrings", "rationale",
)
ALLOWED_CATEGORIES = {"normative", "preservation", "noop", "voice", "trigger"}
ALLOWED_MODES = {"diagnose", "correct", "polish", "none"}
ALLOWED_TIERS = {"fast", "balanced", "frontier", "none"}
EXPECTED_CATEGORY_COUNTS = {
    "normative": 8,
    "preservation": 8,
    "noop": 6,
    "voice": 4,
    "trigger": 4,
}
```

`load_cases` must require a top-level JSON object with `version == "1"` and a
`cases` array. `validate_case` must reject missing fields, invalid IDs, invalid
enum values, non-boolean trigger/no-op fields, and non-string list members. The
fixture-scope runner must reject duplicate IDs across the loaded array.
`evaluate_candidate` must compare each `candidate_*` field with its matching
`expected_*` field and use `str.count` on source and candidate for each
preserved literal so duplicates cannot collapse into a set.

`main` resolves the default skill root as
`pathlib.Path(__file__).resolve().parents[1]` and the default cases path as
`skill_root / "evals" / "cases.json"`. Successful fixture validation prints
the exact category-count summary required in Step 6.

`validate_skill_tree` must reject missing required files and check:

- directory basename equals `kws-korean-writing-editor` when validating the
  real tree;
- `SKILL.md` frontmatter includes matching `name`, a narrow `description`, and
  string `metadata.version`;
- the description contains the positive concepts `proofread`, `correct`,
  `polish`, `Korean`, and `text they provide` plus the exclusions
  `translation`, `drafting`, `summarization`, `code review`, and `casual`;
- the core documents name all three modes and model tiers;
- the full documents contain every required heading listed in Tasks 2 and 3;
- relative Markdown links resolve inside the skill directory;
- `skills/README.md` contains `kws-korean-writing-editor` in full scope.

- [ ] **Step 4: Run the inline tests to verify GREEN**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
```

Expected: PASS with `4 tests` and exit 0.

- [ ] **Step 5: Create the 30-case fixture file**

Create `evals/cases.json` with `version: "1"` and exactly these case IDs and
purposes. Every record includes a safe reference candidate plus property
fields; no case claims that the candidate was generated by a live model.

| Category | Case IDs and exact protected focus |
| --- | --- |
| Normative (8) | `norm-spacing-can-01`: `할수 있다` → `할 수 있다`; `norm-spacing-negation-02`: `하지않았다` → `하지 않았다`; `norm-word-days-03`: `몇일` → `며칠`; `norm-word-soon-04`: `금새` → `금세`; `norm-word-what-05`: `왠일` → `웬일`; `norm-contraction-06`: `되요` → `돼요`; `norm-word-how-07`: `어떻해` → `어떡해`; `norm-word-role-08`: `역활` → `역할`. All use `correct` and `fast`. |
| Preservation (8) | `meaning-negation-01`: preserve `출시하지 않을 수 있다`; `meaning-modality-02`: preserve `가능성이 있다` and forbid `확실하다`; `meaning-quantity-03`: preserve both occurrences of `12.5%` and `40명`; `meaning-date-version-04`: preserve `2026-08-22` and `v2.1.0`; `meaning-names-05`: preserve `김민수` and `박지영` with their actions; `meaning-url-06`: preserve `https://example.com/a?x=1&y=2`; `meaning-quote-07`: preserve `“보류하겠습니다”` and speaker `이서연`; `meaning-causality-08`: preserve `관련이 있었다` and forbid `원인이었다`. Use `balanced`, except a dense technical attribution case may use `frontier`. |
| No-op (6) | `noop-message-01`: `오늘은 조금 늦을 것 같아요.`; `noop-review-02`: `좋았지만, 선뜻 권하기는 어려운 책이었다.`; `noop-work-03`: `검토 후 내일까지 의견을 보내겠습니다.`; `noop-technical-04`: `캐시는 원본이 아니라 다시 만들 수 있는 색인입니다.`; `noop-fragment-05`: `아무튼. 그때는 그게 최선이었다.`; `noop-repetition-06`: `그래도 나는, 그래도 한 번은 믿어 보고 싶었다.` Candidate equals source exactly. |
| Voice (4) | `voice-personal-01`: retain `나는` and reflective `-었다` endings without corporate phrasing; `voice-work-02`: retain polite `-습니다` register and action/date; `voice-technical-03`: retain code span `` `state.json` `` and causal boundary; `voice-review-04`: retain ambivalent evaluation rather than making praise categorical. Use `balanced`. |
| Trigger (4) | `trigger-explicit-01`: explicit `$kws-korean-writing-editor` plus Korean text, trigger `polish`; `trigger-implicit-02`: `이 한국어 문장을 자연스럽게 다듬어줘:` plus source, trigger `polish`; `trigger-translation-03`: Korean-to-English translation request, no trigger/mode/tier; `trigger-casual-04`: ordinary Korean greeting and question, no trigger/mode/tier. |

For every preservation case, populate `must_preserve`,
`required_substrings`, and `forbidden_substrings` so the intended negation,
modality, value count, attribution, or causal boundary is mechanically
observable. For voice cases, protect only the small expressions that encode
register or stance; do not require an exact whole candidate string.

- [ ] **Step 6: Verify fixtures and deliberate mutations**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope fixtures
```

Expected: PASS with `30 cases: normative=8 preservation=8 noop=6 voice=4 trigger=4` and `mutation checks: PASS`.

The mutation checks must internally prove that removing one repeated number,
flipping a required negation, adding a forbidden certainty claim, and changing
a quote's speaker each produce at least one evaluator error.

- [ ] **Step 7: Commit the evaluator contract**

```bash
git add skills/kws-korean-writing-editor/evals/run.py \
        skills/kws-korean-writing-editor/evals/cases.json
git commit -m "test: define Korean editor skill contract"
```

---

### Task 2: Implement The Portable Skill And Evidence References

**Files:**
- Create: `skills/kws-korean-writing-editor/SKILL.md`
- Create: `skills/kws-korean-writing-editor/references/editorial-guide.md`
- Create: `skills/kws-korean-writing-editor/references/sources.md`
- Test: `skills/kws-korean-writing-editor/evals/run.py`

**Interfaces:**
- Consumes: The case modes, tiers, trigger expectations, and required headings enforced by Task 1.
- Produces: The canonical behavior contract that the user guide and runtime smoke use.

- [ ] **Step 1: Run the core contract to verify RED**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope core
```

Expected: FAIL naming the three missing core files.

- [ ] **Step 2: Create `SKILL.md` with portable frontmatter**

Use this exact frontmatter shape:

```yaml
---
name: kws-korean-writing-editor
description: Use only when the user asks to proofread, correct, or polish Korean text they provide. Do not use for translation, drafting, summarization, general writing advice, code review, casual Korean conversation, AI-authorship detection, or detector evasion.
compatibility: Requires Korean source text and local Agent Skills file access. Model delegation is optional and host-dependent.
metadata:
  version: "1.0.0"
  updated_at: "2026-08-22"
---
```

Write a concise body with these exact headings:

```markdown
# KWS Korean Writing Editor
## Activation Gate
## Modes
## Default Interaction
## Editing Pass
## Preservation Gate
## Model Tier
## Output Contract
## Refuse Or Hold
## References
```

Under `Activation Gate`, require both clear editing intent and supplied Korean
text for implicit use, prefer explicit invocation, and no-op on every excluded
near miss. Under `Modes`, define only `diagnose`, `correct`, and conservative
default `polish`.

Under `Editing Pass`, require this order:

1. determine mode and explicit protected expressions;
2. note material propositions and invariants without persisting user text;
3. apply normative local corrections;
4. apply local grammar and flow improvements only in `polish`;
5. restore intentional voice features;
6. compare and revert any unsupported semantic change;
7. return unchanged text when no edit is needed.

Under `Model Tier`, define:

- `fast`: short local correction;
- `balanced`: ordinary non-trivial polishing;
- `frontier`: material ambiguity, dense technical/academic attribution, or
  high-risk structural editing;
- length alone never escalates;
- high-stakes content may be held instead of escalated;
- no classifier-model call, no panel, no provider model names, and at most one
  host-supported delegation;
- use the active model and say `routing unavailable` on request when the host
  cannot switch models.

Under `Output Contract`, return edited text only by default, add a short
`확인 필요` note only for a material hold, and explain class/source only when
asked. Link both reference files with relative links.

- [ ] **Step 3: Create the compact editorial guide**

Write `references/editorial-guide.md` with these exact headings:

```markdown
# Korean Editorial Guide
## Decision Classes
## Normative Pass
## Grammar And Local Flow
## Voice Preservation
## Genre Boundaries
## Material Holds
## Compact Examples
```

Define `normative-rule`, `permitted-alternative`, `editorial-suggestion`,
`style-judgment`, and `hold`. State that permitted forms remain unchanged by
default and that public-language guidance is not a universal style rule.

The compact examples must cover:

- `할수 있다` → `할 수 있다` as a normative local correction;
- an already natural sentence returning unchanged;
- `가능성이 있다` not becoming `확실하다`;
- ambivalent book-review language staying ambivalent;
- intentional fragments and repetition being retained;
- legal, medical, or financial claims defaulting to mechanical correction or
  diagnosis without separate source verification.

- [ ] **Step 4: Create the evidence register**

Write `references/sources.md` with columns `Source`, `Evidence class`, `Used
for`, `Not proof of`, `Checked`, and `Reuse boundary`. Include these sources:

| Source | Evidence class | Used for | Not proof of |
| --- | --- | --- | --- |
| [Korean language norms](https://www.korean.go.kr/kornorms/m/m_regltn.do) | Normative | spelling, spacing, punctuation, standard language, loanword, romanization | a universal prose style |
| [NIKL 2024 correction-corpus study](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=45&pageIndex=5&report_seq=1184&searchOrder=) | Empirical | correction categories and accepted-form cautions | current model quality |
| [NIKL 2025 correction-support study](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=207&pageIndex=1&report_seq=1226&searchOrder=years) | Empirical | factuality, evidence fidelity, clarity, fluency categories | open-genre voice preservation |
| [KAGAS](https://aclanthology.org/2023.acl-long.371/) | Empirical | Korean GEC edit types and precision focus | document-level meaning or voice |
| [StyleKQC](https://aclanthology.org/2022.lrec-1.771.pdf) | Empirical | separate style and content-preservation axes | all Korean genres |
| [NIST AI 600-1](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) | Risk guidance | fabrication, homogenization, non-English variance, automation bias | Korean grammar rules |
| [KatFishNet](https://aclanthology.org/2025.acl-long.1030/) | Detector research | why detector signals are diagnostic only | better writing or human authorship |
| [Shared report](https://chatgpt.com/share/6a89a698-c790-83ee-8d20-7fe092d2badc) | Design input | source-first and minimal-edit framing | live generalization |

Add a short related-project section with the three pinned commits from the
spec, their licenses, the verified test observations, and the statement that
no code, corpus, or rule list was copied. Every checked date is `2026-08-22`.

- [ ] **Step 5: Run the core contract to verify GREEN**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope core
```

Expected: PASS for fixtures, frontmatter, modes, tiers, hard boundaries,
relative references, and source register.

- [ ] **Step 6: Review the core against the approved spec**

Read:

```bash
sed -n '1,620p' docs/superpowers/specs/2026-08-22-kws-korean-writing-editor-design.md
sed -n '1,260p' skills/kws-korean-writing-editor/SKILL.md
sed -n '1,260p' skills/kws-korean-writing-editor/references/editorial-guide.md
sed -n '1,260p' skills/kws-korean-writing-editor/references/sources.md
```

Confirm that no drafting, translation, detector evasion, mandatory external
call, morphology dependency, provider model name, or persistent user-text
artifact was introduced.

- [ ] **Step 7: Commit the portable core**

```bash
git add skills/kws-korean-writing-editor/SKILL.md \
        skills/kws-korean-writing-editor/references/editorial-guide.md \
        skills/kws-korean-writing-editor/references/sources.md
git commit -m "feat: add Korean writing editor skill"
```

---

### Task 3: Add The Intuitive Guide, Change Protocol, And Repository Index

**Files:**
- Create: `skills/kws-korean-writing-editor/README.md`
- Create: `skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md`
- Modify: `skills/README.md`
- Test: `skills/kws-korean-writing-editor/evals/run.py`

**Interfaces:**
- Consumes: The exact invocation, modes, tiers, output, privacy, and source links from Task 2.
- Produces: User-facing setup and usage guidance plus repository discoverability.

- [ ] **Step 1: Run the full contract to verify RED**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
```

Expected: FAIL naming missing `README.md`, missing `CHANGE_PROTOCOL.md`, and
missing root index entry.

- [ ] **Step 2: Create the one-minute Korean user guide**

Write `README.md` in Korean with these exact headings:

```markdown
# kws-korean-writing-editor
## 1분 시작
## 언제 사용하나
## 세 가지 모드
## 호출 예시
## 결과 형식
## 모델 선택
## 설치
## 업데이트와 제거
## 개인정보와 한계
## 검증
```

Lead with these examples before any architecture explanation:

```text
이 문장을 자연스럽게 다듬어줘. 뜻과 내 말투는 유지해줘: ...
오탈자만 고쳐줘: ...
고치지 말고 어색한 부분만 알려줘: ...
```

List the four explicit invocation forms. Explain that ordinary Korean chat,
translation, drafting, summaries, code review, and detector evasion should use
the ordinary assistant or a different workflow. Limit the guide to six usage
examples total.

Document `fast`, `balanced`, and `frontier` in one compact table. State that
the active runtime may not support model switching, model names are not fixed,
and no extra classifier model is called.

Use safe, explicit installation guidance:

1. treat the tracked Archive directory as canonical;
2. for Codex, Cursor, and Grok Build, materialize a validated copy at
   `~/.agents/skills/kws-korean-writing-editor`;
3. for Claude Code, copy or link that validated installation at
   `~/.claude/skills/kws-korean-writing-editor`;
4. never overwrite an existing real directory without inspecting it;
5. start a new agent session after installation;
6. state that Grok support means Grok Build, not grok.com or mobile.

Do not add an installer script. Show commands with a task-specific variable
such as `KWS_EDITOR_SOURCE`; never repurpose `HOME`, `CODEX_HOME`, or a broad
directory as a copy/delete target.

- [ ] **Step 3: Create the change protocol**

Write `CHANGE_PROTOCOL.md` with these exact headings:

```markdown
# Change Protocol
## Contract Changes
## Evidence Changes
## Fixture Changes
## Versioning
## Required Verification
```

Require these synchronized changes:

- trigger change → positive and near-miss fixtures plus README;
- mode/output change → `SKILL.md`, editorial guide, fixtures, and README;
- model-tier change → routing fixtures and README;
- normative claim change → authoritative source locator and fixture;
- external project use → pinned revision, license, checked date, and explicit
  adopted/rejected boundary;
- behavior change → SemVer update in `metadata.version`;
- documentation-only wording change → no version bump unless behavior changes.

Required offline verification is:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
bun run agent:verify
git diff --check
```

State that live canaries remain opt-in and are reported separately.

- [ ] **Step 4: Update the repository skill index**

Modify `skills/README.md` as follows:

- change the opening from only “개인용 runner/executor 스킬” to
  “Archive에서 관리하는 개인용 스킬” while preserving runner/executor
  boundaries;
- add a table row for `kws-korean-writing-editor` describing narrow Korean
  correction and polishing with meaning/voice preservation;
- add a short portable-skill installation subsection linking to the new
  README and current `.agents/skills` plus Claude discovery targets;
- amend the final note so `kws-korean-writing-editor` is the deliberate
  repository-owned general-skill exception while other general skills remain
  in the separate `kws-skills` plugin;
- do not rewrite the existing runner runtime, cutover, or Waygent sections.

- [ ] **Step 5: Run the full contract and documentation checks**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
bun run scripts/agent/check-markdown-links.ts \
  skills/kws-korean-writing-editor/SKILL.md \
  skills/kws-korean-writing-editor/README.md \
  skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md \
  skills/kws-korean-writing-editor/references/editorial-guide.md \
  skills/kws-korean-writing-editor/references/sources.md \
  skills/README.md
git diff --check
```

Expected: all commands exit 0. The evaluator reports exactly 30 fixture cases.

- [ ] **Step 6: Commit the guide and index**

```bash
git add skills/kws-korean-writing-editor/README.md \
        skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md \
        skills/README.md
git commit -m "docs: guide Korean writing editor usage"
```

---

### Task 4: Install Safely, Run Proportional Runtime Smoke, And Close Out

**Files:**
- Verify: `skills/kws-korean-writing-editor/`
- Verify: `skills/README.md`
- Local installation only when the exact target paths are absent or safely identified

**Interfaces:**
- Consumes: The complete canonical tree and README installation contract.
- Produces: Current-run installation/discovery evidence and final repository verification; no new repository framework.

- [ ] **Step 1: Run repository preflight and inspect exact local targets**

Run:

```bash
pwd
git status --short --branch --untracked-files=all
git branch --show-current
git rev-parse HEAD
git worktree list --porcelain
ls -ld /Users/kws/.agents /Users/kws/.agents/skills \
       /Users/kws/.claude /Users/kws/.claude/skills 2>/dev/null || true
ls -ld /Users/kws/.agents/skills/kws-korean-writing-editor \
       /Users/kws/.claude/skills/kws-korean-writing-editor 2>/dev/null || true
```

Expected: exact targets are absent, or their type and destination are known.
If either target is an existing real directory, stop installation and report
the conflict; do not overwrite or delete it.

- [ ] **Step 2: Materialize the common installation and Claude discovery link**

Only after Step 1 proves both exact targets are absent, run:

```bash
mkdir -p /Users/kws/.agents/skills /Users/kws/.claude/skills
cp -R /Users/kws/source/private/Archive/skills/kws-korean-writing-editor \
      /Users/kws/.agents/skills/kws-korean-writing-editor
ln -s /Users/kws/.agents/skills/kws-korean-writing-editor \
      /Users/kws/.claude/skills/kws-korean-writing-editor
```

Then compare the installed file list and content without modifying either
tree:

```bash
diff -ru \
  /Users/kws/source/private/Archive/skills/kws-korean-writing-editor \
  /Users/kws/.agents/skills/kws-korean-writing-editor
readlink /Users/kws/.claude/skills/kws-korean-writing-editor
```

Expected: `diff` exits 0 and the Claude link points to the materialized common
installation.

- [ ] **Step 3: Run no-cost discovery checks**

Run:

```bash
codex --version
claude --version
cursor-agent --version
grok --version
grok inspect --json
```

Verify that the current Grok inspection contains `kws-korean-writing-editor`.
For Codex, Claude, and Cursor, record the installed supported path and current
CLI version; do not claim invocation until a live canary runs.

- [ ] **Step 4: Request explicit authorization before billable live canaries**

Explain that the next commands may call provider models and transmit only the
synthetic canary text below. If authorization is not given, skip Step 5 and
report all four invocation checks as `not measured`. Offline checks and local
installation remain valid evidence.

Use this exact positive canary text:

```text
오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.
이 검증에서만 응답 마지막 줄에 CANARY tier와 skill_used를 표시해줘.
```

Expected semantic properties: `사용할 수` is corrected, `반드시 켤 필요는
없습니다` is preserved, and the selected tier is `fast`.

Use this exact near-miss text:

```text
한국어로 짧게 답해줘. 오늘 날씨가 좋네요.
이 검증에서만 응답 마지막 줄에 CANARY skill_used를 표시해줘.
```

Expected property: ordinary conversation proceeds without Korean-editor
behavior and reports `skill_used=no`.

- [ ] **Step 5: If authorized, run one positive and one near-miss canary per runtime**

Use fresh, non-persistent, read-only or plan-mode sessions and the installed
skill paths. Do not select a hard-coded model name.

```bash
codex exec --ephemeral --sandbox read-only -C /Users/kws/source/private/Archive \
  '$kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다. 이 검증에서만 응답 마지막 줄에 CANARY tier와 skill_used를 표시해줘.'

claude --print --no-session-persistence --permission-mode plan --tools "" \
  '/kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다. 이 검증에서만 응답 마지막 줄에 CANARY tier와 skill_used를 표시해줘.'

cursor-agent --print --mode ask --workspace /Users/kws/source/private/Archive \
  '/kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다. 이 검증에서만 응답 마지막 줄에 CANARY tier와 skill_used를 표시해줘.'

grok --cwd /Users/kws/source/private/Archive --permission-mode plan \
  --disable-web-search --no-subagents --single \
  '/kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다. 이 검증에서만 응답 마지막 줄에 CANARY tier와 skill_used를 표시해줘.'
```

Repeat the same four commands with the near-miss text but without the explicit
skill name. Each runtime runs only two provider calls. Record exact runtime
version, command, exit status, output, selected tier, and whether actual model
delegation was observed. Do not infer delegation from a requested tier.

- [ ] **Step 6: Run final offline verification**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
bun run agent:verify
git diff --check
git status --short --branch --untracked-files=all
```

Expected: evaluator self-tests pass, all 30 fixture records pass, repository
verification exits 0, diff check exits 0, and the worktree contains no
uncommitted implementation changes.

- [ ] **Step 7: Review against `code_review.md` and report honest support**

Read `code_review.md` and report findings first. The handoff must include:

- changed files and three implementation commits;
- exact offline commands and outputs;
- current local installation targets and copy/link state;
- per-runtime status as `verified`, `partially verified`, `not measured`, or
  `blocked`;
- whether model tier selection was observed and whether actual delegation was
  observed;
- skipped opt-in live calls;
- residual risks from the design spec;
- local branch/HEAD, clean/dirty state, and remote divergence;
- no claim that the 30 offline cases prove live model quality.

Do not push, merge, publish, or delete any existing installation unless the
user separately requests that action.

---

## Self-Review Checklist

- [ ] Every approved design section maps to Tasks 1–4.
- [ ] The skill still creates exactly seven files and modifies only the root skill index.
- [ ] Trigger exclusions and near-miss cases are mechanically represented.
- [ ] The default experience remains edited-text-only and low-configuration.
- [ ] The evidence register distinguishes normative, empirical, risk, and design input.
- [ ] The evaluator states that reference candidates do not prove live quality.
- [ ] Model routing has no hard-coded provider model names and no classifier call.
- [ ] Live calls are opt-in and limited to two synthetic canaries per runtime.
- [ ] No external dependency, parser, installer, persistent ledger, or provider wrapper was introduced.
- [ ] File names, CLI flags, function names, enums, and fixture counts are consistent across tasks.
