# KWS Korean Writing Editor Live Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden `kws-korean-writing-editor` to `1.0.2` so `correct` keeps already-correct obligation wording, default output stays the edited body only, and live canaries stop mixing harness instructions into the manuscript.

**Architecture:** Keep the existing seven-file portable skill. Encode the mixed spacing-plus-obligation property in the current 30-case oracle and two new mutations, then lock the same class into `SKILL.md`, the editorial guide, README, and change protocol. Do not add a canary runner, parser, host-specific skill copy, or eighth skill file.

**Tech Stack:** Agent Skills Markdown/YAML frontmatter, Korean documentation, JSON fixtures, Python 3 standard library, repository `bun run agent:verify` checks

**Spec:** `docs/superpowers/specs/2026-08-23-kws-korean-writing-editor-live-hardening-design.md`

Parent design remains in force except where the live-hardening spec overrides it: `docs/superpowers/specs/2026-08-22-kws-korean-writing-editor-design.md`

## Global Constraints

- Canonical skill name and directory: `kws-korean-writing-editor`.
- Edit only the existing seven files under `skills/kws-korean-writing-editor/` plus `evals/run.py` mutations/self-tests. Change `skills/README.md` only if the index would otherwise contradict this contract.
- Do not add an eighth skill file, live canary runner, parser, unofficial spelling API, morphology tool, installer, schema package, persistent ledger, provider wrapper, LLM-as-judge, or host-specific `SKILL.md`.
- Keep `diagnose`, `correct`, and conservative `polish`. Do not add modes or tiers.
- Model tiers remain `fast`, `balanced`, and `frontier`. Do not hard-code provider model names.
- Keep exactly thirty fixtures and `EXPECTED_CATEGORY_COUNTS`: normative 8, preservation 8, noop 6, voice 4, trigger 4.
- Keep these evaluator interfaces unchanged: `load_cases`, `validate_case`, `evaluate_candidate`, `validate_skill_tree`, `run_self_tests`, `main`.
- Do not persist user manuscripts as fixtures. The only allowed regression specimen is the public README sentence `이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.`
- Do not add a one-off ban list whose whole rule is the string `켜야 할 필요는`. The fixture may forbid that specimen; `SKILL.md` states the class.
- Do not teach the skill to ignore trailing verification lines such as `CANARY`.
- Leave the frontmatter `description` text unchanged unless a required evaluator term is missing. Do not lengthen it.
- Bump `SKILL.md` `metadata.version` to `1.0.2` in the behavior-change commit.
- Default `correct` / `polish` output is the edited text only. Do not prepend process narration.
- Live canaries stay opt-in, harness-free, and separately reported. Never describe offline fixture success as live model quality.
- Execute from an isolated git worktree. Do not edit `main` in place. Do not merge, push, or open a pull request unless the user separately asks.
- Use TDD for the evaluator. Keep commits task-local.

---

## File Map

| File | Responsibility this cycle |
| --- | --- |
| `skills/kws-korean-writing-editor/evals/cases.json` | Replace `norm-spacing-can-01` with the mixed spacing-plus-obligation specimen. |
| `skills/kws-korean-writing-editor/evals/run.py` | Add paraphrase and preamble mutations plus self-tests. Keep the six interfaces. |
| `skills/kws-korean-writing-editor/SKILL.md` | Preservation, editing-pass revert, output-contract wording, version `1.0.2`. |
| `skills/kws-korean-writing-editor/references/editorial-guide.md` | One compact mixed example. Keep the short `배포할수` spacing example. |
| `skills/kws-korean-writing-editor/README.md` | Result-format and live-canary isolation wording. Keep the existing specimen sentence. |
| `skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md` | Fixture and live-isolation rules under existing H2s. No new H2. |
| `skills/kws-korean-writing-editor/references/sources.md` | Unchanged. No new normative claim. |
| `skills/README.md` | Unchanged unless the index contradicts `1.0.2`. |

## Evaluator Interface

Do not rename, add, or remove these functions:

```python
load_cases(path: pathlib.Path) -> list[dict[str, object]]
validate_case(case: dict[str, object]) -> list[str]
evaluate_candidate(case: dict[str, object]) -> list[str]
validate_skill_tree(skill_root: pathlib.Path, scope: str) -> list[str]
run_self_tests() -> unittest.result.TestResult
main(argv: list[str] | None = None) -> int
```

Mutation error strings this cycle must use exactly:

```text
mutation: missing norm-spacing-can-01
mutation: paraphrasing already-correct obligation produced no error
mutation: adding process preamble produced no error
```

Existing mutation strings stay unchanged.

---

### Task 1: Encode The Mixed Fixture And Mutations

**Files:**
- Modify: `skills/kws-korean-writing-editor/evals/run.py` (`run_mutation_checks`, `EvaluatorTests`)
- Modify: `skills/kws-korean-writing-editor/evals/cases.json` (`norm-spacing-can-01` only)

**Interfaces:**
- Consumes: existing `evaluate_candidate`, `run_mutation_checks`, `EXPECTED_CATEGORY_COUNTS`, and the six evaluator functions.
- Produces: `norm-spacing-can-01` with the spec field values below; two new mutations against that id; self-tests that fail if the id is missing.

- [ ] **Step 1: Write the failing mutation self-tests**

In `EvaluatorTests`, add this helper and tests. Extend the existing
non-object test. Do not change `cases.json` yet.

```python
    def obligation_case(self):
        return {
            "id": "norm-spacing-can-01",
            "category": "normative",
            "request": (
                "오탈자만 고쳐줘: 이 기능은 사용할수 있지만 "
                "반드시 켤 필요는 없습니다."
            ),
            "source": "이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.",
            "candidate": "이 기능은 사용할 수 있지만 반드시 켤 필요는 없습니다.",
            "candidate_trigger": True,
            "candidate_mode": "correct",
            "candidate_tier": "fast",
            "expected_trigger": True,
            "expected_mode": "correct",
            "expected_tier": "fast",
            "expected_noop": False,
            "must_preserve": ["반드시 켤 필요는 없습니다"],
            "required_substrings": ["사용할 수"],
            "forbidden_substrings": [
                "사용할수",
                "켜야 할 필요는",
                "요청은 오탈자",
            ],
            "rationale": (
                "Dependent-noun spacing plus already-correct obligation "
                "wording; no process preamble."
            ),
        }

    def test_rejects_obligation_paraphrase_candidate(self):
        case = self.obligation_case()
        case["candidate"] = case["candidate"].replace(
            "켤 필요는", "켜야 할 필요는"
        )
        self.assertIn(
            "norm-spacing-can-01: forbidden substring present '켜야 할 필요는'",
            evaluate_candidate(case),
        )

    def test_rejects_process_preamble_candidate(self):
        case = self.obligation_case()
        case["candidate"] = (
            "요청은 오탈자만 고치는 교정입니다." + case["candidate"]
        )
        self.assertIn(
            "norm-spacing-can-01: forbidden substring present '요청은 오탈자'",
            evaluate_candidate(case),
        )

    def test_mutation_checks_ignore_non_object_entries(self):
        errors = run_mutation_checks(["not-an-object"])
        self.assertIn("mutation: missing meaning-quantity-03", errors)
        self.assertIn("mutation: missing norm-spacing-can-01", errors)
```

- [ ] **Step 2: Run the self-test and confirm the new missing-id assertion fails**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
```

Expected: FAIL. `test_mutation_checks_ignore_non_object_entries` does not
see `mutation: missing norm-spacing-can-01`. The two `evaluate_candidate`
tests may already pass because they do not use `cases.json`.

- [ ] **Step 3: Add the two mutations to `run_mutation_checks`**

Append this block after the existing quotation mutation, still inside
`run_mutation_checks`, before `return errors`:

```python
    spacing = by_id.get("norm-spacing-can-01")
    if spacing is None:
        errors.append("mutation: missing norm-spacing-can-01")
    else:
        paraphrased = dict(spacing)
        paraphrased["candidate"] = str(spacing["candidate"]).replace(
            "켤 필요는", "켜야 할 필요는"
        )
        if not evaluate_candidate(paraphrased):
            errors.append(
                "mutation: paraphrasing already-correct obligation produced no error"
            )

        preamble = dict(spacing)
        preamble["candidate"] = (
            "요청은 오탈자만 고치는 교정입니다." + str(spacing["candidate"])
        )
        if not evaluate_candidate(preamble):
            errors.append(
                "mutation: adding process preamble produced no error"
            )
```

Do not add a global meta-noise classifier or a diff engine.

- [ ] **Step 4: Re-run self-test, then prove fixtures still fail**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
python3 skills/kws-korean-writing-editor/evals/run.py --scope fixtures
```

Expected: `--self-test` PASS. `--scope fixtures` FAIL with exactly:

```text
mutation: paraphrasing already-correct obligation produced no error
```

The current `norm-spacing-can-01` candidate is `지금 상태에선 배포할 수 있다.`
and does not contain `켤 필요는`, so the paraphrase mutation is a no-op and
must be rejected. Do not proceed if fixtures pass at this step.

- [ ] **Step 5: Replace `norm-spacing-can-01` in `cases.json`**

Keep the id and `"category": "normative"`. Replace the object with:

```json
    {
      "id": "norm-spacing-can-01",
      "category": "normative",
      "request": "오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.",
      "source": "이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.",
      "candidate": "이 기능은 사용할 수 있지만 반드시 켤 필요는 없습니다.",
      "candidate_trigger": true,
      "candidate_mode": "correct",
      "candidate_tier": "fast",
      "expected_trigger": true,
      "expected_mode": "correct",
      "expected_tier": "fast",
      "expected_noop": false,
      "must_preserve": ["반드시 켤 필요는 없습니다"],
      "required_substrings": ["사용할 수"],
      "forbidden_substrings": ["사용할수", "켜야 할 필요는", "요청은 오탈자"],
      "rationale": "Dependent-noun spacing plus already-correct obligation wording; no process preamble."
    }
```

Do not add a 31st case. Do not change other case ids or category counts.

- [ ] **Step 6: Run fixtures and confirm they pass**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
python3 skills/kws-korean-writing-editor/evals/run.py --scope fixtures
```

Expected: both exit 0. Stdout from fixtures includes
`30 cases: normative=8 preservation=8 noop=6 voice=4 trigger=4` and
`mutation checks: PASS`.

- [ ] **Step 7: Commit**

```bash
git add -- skills/kws-korean-writing-editor/evals/cases.json \
          skills/kws-korean-writing-editor/evals/run.py
git commit -m "$(cat <<'EOF'
test: lock Korean editor obligation preservation

Replace the spacing canary fixture with the public mixed specimen and reject
obligation paraphrase plus process-preamble mutations.
EOF
)"
```

---

### Task 2: Lock The Behavior Contract And Docs

**Files:**
- Modify: `skills/kws-korean-writing-editor/SKILL.md`
- Modify: `skills/kws-korean-writing-editor/references/editorial-guide.md`
- Modify: `skills/kws-korean-writing-editor/README.md`
- Modify: `skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md`

**Interfaces:**
- Consumes: Task 1 `norm-spacing-can-01` specimen and mutation strings; existing `REQUIRED_HEADINGS` (do not add a new `CHANGE_PROTOCOL.md` H2).
- Produces: skill version `1.0.2`; Preservation Gate class wording; output-contract no-preamble rule; editorial mixed example; live-canary isolation in README and CHANGE_PROTOCOL.

- [ ] **Step 1: Write the failing document-contract checks as reviewer-facing assertions**

Do not add new evaluator required-term lists. The failing check this step is
human-and-diff visible: `metadata.version` is still `"1.0.1"`, and
`SKILL.md` does not yet contain the class sentences below. Confirm that
before editing:

```bash
python3 - <<'PY'
from pathlib import Path
text = Path("skills/kws-korean-writing-editor/SKILL.md").read_text()
assert 'version: "1.0.1"' in text
assert "already standard, grammatical" not in text
assert "process narration" not in text
print("precondition OK")
PY
```

Expected: prints `precondition OK`.

- [ ] **Step 2: Update `SKILL.md` version and editing/preservation/output wording**

Keep the current `description` string unchanged. Change only:

1. `metadata.version` from `"1.0.1"` to `"1.0.2"`. Leave `updated_at` as
   `"2026-08-23"` unless the calendar date of the commit is later; if later,
   set `updated_at` to that date.

2. Editing Pass item 6, replace:

```markdown
6. Compare with the original and revert any unsupported semantic change or
   invariant break.
```

with:

```markdown
6. Compare with the original and revert any unsupported semantic change,
   invariant break, or synonym replacement of an already-correct local form.
```

3. In the Preservation Gate `Never:` list, insert these two bullets immediately
   after the possibility/certainty bullet:

```markdown
- replace an already standard, grammatical local expression with a synonym
  in `correct`
- rewrite obligation, permission, possibility, or negation wording when
  that wording is already grammatical
```

4. In Output Contract, immediately after
   `Do not print a rubric, change log, score, or routing receipt.`
   add:

```markdown
Do not prepend process narration, mode restatement, or measurement footers.
```

Do not add a rule that ignores `CANARY` or other trailing verification
instructions. Do not add host-specific frontmatter. Do not lengthen
`description`.

- [ ] **Step 3: Add the compact mixed example to the editorial guide**

In `references/editorial-guide.md`, keep the existing **Normative spacing**
`배포할수` example. Insert this bullet immediately after it:

```markdown
- **Already-correct obligation.** `이 기능은 사용할수 있지만 반드시 켤 필요는
  없습니다.` → `이 기능은 사용할 수 있지만 반드시 켤 필요는 없습니다.`
  Class: spacing is `normative-rule`; `켤 필요는` stays. Do not write
  `켜야 할 필요는`. Valid in `correct`.
```

Do not copy a third-party pattern list. Do not delete other compact examples.

- [ ] **Step 4: Update README result format and verification wording**

In `README.md` section `## 결과 형식`, after
`점수, 변경 목록, 모델 이름은 붙지 않습니다.`
add this sentence:

```markdown
앞에 작업 설명을 붙이지 않습니다.
```

In `## 검증`, after
`라이브 카나리는 별도 선택이며 따로 보고합니다.`
add:

```markdown
라이브 양성 프롬프트에는 원고와 교정 요청만 넣습니다. 모델에게 CANARY나
skill_used를 적으라고 시키지 않습니다. 본문을 보고 판정합니다.
```

Keep the existing invocation example that uses the public specimen sentence.
Do not add a user manuscript. Do not add an installer.

- [ ] **Step 5: Extend CHANGE_PROTOCOL without a new H2**

Under `## Fixture Changes`, after the voice-case bullet, add:

```markdown
- Mixed normative cases may protect an already-correct obligation or
  modality span in the same record as a local spelling fix.
- A candidate with process preamble must fail the replaced
  `norm-spacing-can-01` properties.
```

Under `## Required Verification`, replace the final two sentences:

```markdown
Live canaries remain opt-in and are reported separately. Do not describe
offline fixture results as live invocation or model-quality evidence.
```

with:

```markdown
Live canaries remain opt-in and are reported separately. Do not describe
offline fixture results as live invocation or model-quality evidence.

A positive live prompt is only the host explicit invocation plus the Korean
editing request and source. Do not append CANARY, tier, or skill_used
instructions to that message. Near-miss prompts omit self-report
instructions. Judge the returned body. `skill_used` self-report is not a
contract.
```

Do not add `## Live Canaries` or any other new H2. `REQUIRED_HEADINGS` stays
as it is.

- [ ] **Step 6: Run core and full skill-tree verification**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
python3 skills/kws-korean-writing-editor/evals/run.py --scope core
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
```

Expected: all three exit 0. Full scope still prints the 30-case counts,
`mutation checks: PASS`, `skill tree (full): PASS`, and the offline-contract
disclaimer.

Also confirm the new strings exist:

```bash
python3 - <<'PY'
from pathlib import Path
skill = Path("skills/kws-korean-writing-editor/SKILL.md").read_text()
guide = Path("skills/kws-korean-writing-editor/references/editorial-guide.md").read_text()
readme = Path("skills/kws-korean-writing-editor/README.md").read_text()
protocol = Path("skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md").read_text()
assert 'version: "1.0.2"' in skill
assert "already standard, grammatical" in skill
assert "process narration" in skill
assert "CANARY" not in skill
assert "켤 필요는" in guide
assert "skill_used" in protocol
assert "CANARY나" in readme
print("contract strings OK")
PY
```

Expected: `contract strings OK`. The Preservation Gate must not tell the
model to ignore CANARY.

- [ ] **Step 7: Commit**

```bash
git add -- skills/kws-korean-writing-editor/SKILL.md \
          skills/kws-korean-writing-editor/references/editorial-guide.md \
          skills/kws-korean-writing-editor/README.md \
          skills/kws-korean-writing-editor/CHANGE_PROTOCOL.md
git commit -m "$(cat <<'EOF'
fix: harden Korean editor preservation and output

State the already-correct-phrasing class, forbid process preambles, and
keep live canary harness instructions out of the manuscript.
EOF
)"
```

---

### Task 3: Verify Offline, Report Live Honestly, And Close Out

**Files:**
- Test: `skills/kws-korean-writing-editor/evals/run.py`
- Test: repository `bun run agent:verify` and `git diff --check`
- Modify: local install copy only if `~/.agents/skills/kws-korean-writing-editor` already exists and is this skill. Do not create a new install. Do not write skill files into git from the install path.

**Interfaces:**
- Consumes: Task 1 oracle and Task 2 `1.0.2` documents.
- Produces: exact offline command output; live evidence labeled `verified`, `partially verified`, `not measured`, or `blocked`; no merge or push.

- [ ] **Step 1: Run required offline verification**

Run:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --self-test
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
bun run agent:verify
bun run agent:verify -- --base origin/main --head HEAD
git diff --check
git status --short --branch --untracked-files=all
```

Expected: evaluator commands exit 0, both `bun run agent:verify` forms exit 0,
`git diff --check` exits 0, and there are no uncommitted skill edits. If this
branch has no `origin/main` ref, use the merge-base with local `main` as
`--base`.
Record the exact output. Do not call this live quality evidence.

- [ ] **Step 2: Refresh the existing local install only when it is already this skill**

```bash
KWS_EDITOR_SOURCE="$(pwd)/skills/kws-korean-writing-editor"
KWS_EDITOR_AGENTS_TARGET="$HOME/.agents/skills/kws-korean-writing-editor"
KWS_EDITOR_CLAUDE_TARGET="$HOME/.claude/skills/kws-korean-writing-editor"

ls -ld "$KWS_EDITOR_SOURCE" "$KWS_EDITOR_AGENTS_TARGET" "$KWS_EDITOR_CLAUDE_TARGET"
```

If the agents target exists and `SKILL.md` there names
`kws-korean-writing-editor`, replace that directory from the canonical
source:

```bash
rm -rf "$KWS_EDITOR_AGENTS_TARGET"
cp -R "$KWS_EDITOR_SOURCE" "$KWS_EDITOR_AGENTS_TARGET"
```

If the Claude target is a symlink to that copy, leave it. If it is a real
directory, do not overwrite it. If neither target exists, skip install and
report it. Do not touch `$HOME` or `~/.agents/skills` as a whole.

- [ ] **Step 3: Request authorization before any live remeasure**

If live remeasure is not authorized, skip Step 4 and report every host as
`not measured` except Claude Code CLI, which stays `blocked` while OAuth
fails. Do not reuse the old canary that asked the model to print `CANARY`.

If authorized, the only positive prompt is the host explicit invocation plus
this Korean request, with nothing after the source sentence:

```text
오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.
```

Pass:

- `사용할 수` present
- `반드시 켤 필요는 없습니다` preserved
- `켜야 할 필요는` absent
- no process preamble before the edited sentence

Near-miss, also without self-report instructions:

```text
한국어로 짧게 답해줘. 오늘 날씨가 좋네요.
```

Pass: ordinary conversation, no editing workflow. Missing `skill_used=no`
is not evidence.

- [ ] **Step 4: If authorized, run harness-free canaries on available hosts**

Do not pass `--model` or otherwise hard-code a provider model name.

```bash
codex exec --ephemeral --sandbox read-only -C "$(pwd)" \
  '$kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.'

cursor-agent --print --mode ask --trust --workspace "$(pwd)" \
  '/kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.'

grok --cwd "$(pwd)" --permission-mode plan \
  --disable-web-search --no-subagents --verbatim --single \
  '/kws-korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.'
```

Repeat near-miss commands without the skill name. Cursor Claude is optional
and is not Claude Code evidence. Claude Code CLI remains `blocked` until
authentication works.

Cycle completion does not require every host to pass. One harness-free
positive `correct` pass on an available host is enough live evidence for
this cycle. Remaining hosts use honest labels. If a host still paraphrases,
do not add a one-off string ban; label it `partially verified` or tighten
only the class wording already specified in Task 2.

- [ ] **Step 5: Review against `code_review.md` and write the close-out report**

Read `code_review.md` and report findings first. The handoff must include:

- changed files and the Task 1–2 commits
- exact offline commands and outputs
- local install copy/link state
- per-host live status with the four labels
- skipped opt-in live calls
- residual blind spots from spec §11
- local branch, HEAD, clean/dirty, and remote divergence
- no claim that the 30 offline cases prove live model quality

Do not push, merge, publish, or delete unrelated installations.

---

## Self-Review Checklist

- Spec §6 already-correct phrasing and construction-level modality → Task 2 Preservation Gate plus Task 1 fixture/mutations.
- Spec §7 output contract and no ignore-CANARY rule → Task 2 Output Contract and CHANGE_PROTOCOL; Task 3 harness-free prompt.
- Spec §8 description truncation → Task 2 leaves description unchanged and does not lengthen it.
- Spec §9 thirty cases, replaced `norm-spacing-can-01`, two mutations, no new H2 → Task 1 and Task 2 Step 5.
- Spec §10 live isolation and labels → Task 3 Steps 3–4.
- Spec §11 residual blind spots remain unrequired → Task 3 report.
- Spec §13 lean boundary, version `1.0.2`, no eighth file → Global Constraints and Tasks 1–2.
- No TBD, TODO, "implement later", or "similar to Task N" steps.
- Mutation error strings and fixture field values are identical in Task 1 and the spec.
- `run_mutation_checks` still consumes `list[dict[str, object]]` and returns `list[str]`.
