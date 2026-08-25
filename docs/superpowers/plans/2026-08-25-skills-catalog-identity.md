# Skills Catalog Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `skills/` a two-skill general catalog (`korean-writing-editor`, `image-workbench`), move runners/executors and the Waygent skill under `skills/_legacy/`, and retarget live agent/docs/verification pointers without rewriting legacy bodies.

**Architecture:** Fail the verification-map and agent-contract tests against the target layout first. `git mv` the trees, then retarget cwd/matchers and live scripts so those tests pass. Rename the two catalog skills in place, lock old `$kws-…` invocations as near-miss no-ops, and rewrite only present-tense catalog and routing docs.

**Tech Stack:** Git, Bun test (`scripts/agent`), Python 3 skill evals, Agent Skills Markdown/YAML

**Spec:** `docs/superpowers/specs/2026-08-25-skills-catalog-identity-design.md`

## Global Constraints

- Catalog skills are only `korean-writing-editor` and `image-workbench`.
- Waygent is the `waygent` CLI / `bun run waygent -- …`, not a catalog skill.
- Move deprecated trees with `git mv` to `skills/_legacy/`; keep their directory names (`kws-*`, `waygent`).
- Do not rewrite bodies under `skills/_legacy/` except a hard-coded repo-relative path that is itself a live verification entry listed in spec section 10.
- Hard cut: no `$kws-…` / `/kws-…` aliases. Near-miss fixtures must no-op those strings. One README cutover warning may name the old home path as something to remove.
- Human catalog and skill READMEs stay Korean. `SKILL.md`, `skills/AGENTS.md`, and `adding-a-skill.md` stay English.
- Both catalog skills bump to `metadata.version: "2.0.0"` and `updated_at: "2026-08-25"`.
- Do not rewrite `docs/superpowers/` (except marking this spec Approved), `docs/migration/`, dated `docs/operations/` reports, or dated `docs/architecture/2026-*` files.
- Do not delete `$HOME` skill directories.
- Do not relocate the Waygent NL lexicon into `apps/cli`.
- Use TDD for verification-map, contract, cutover, and skill evals. Keep commits task-local. Preserve unrelated worktree changes.
- Every task's requirements implicitly include this section.

---

## File Map

| File | Responsibility |
| --- | --- |
| `scripts/agent/verification-map.ts` | Matchers and cwd for catalog skills and `_legacy` trees; docs matchers for catalog markdown. |
| `scripts/agent/verification-map.test.ts` | TDD proof of the new layout. |
| `scripts/agent/verify.test.ts` | Dry-run cwd strings for moved trees. |
| `scripts/agent/contract.ts` | Required live paths after the move. |
| `scripts/agent/check-contract.test.ts` | TDD proof of required `_legacy` and catalog paths. |
| `scripts/agent/claude-offline.ts` | MAE offline cwd under `_legacy`. |
| `scripts/agent/claude-offline.test.ts` | TDD proof of that cwd. |
| `scripts/agent/check-plan-runner-parity.py` | Real repo source paths under `_legacy`. |
| `scripts/agent/plan-runner-cutover.py` | Source path helper `skills/_legacy/<name>`; home install names stay `kws-*`. |
| `scripts/agent/test_plan_runner_cutover.py` | Fixture repos create `_legacy` source trees. |
| `skills/_legacy/` | Frozen runners, executors, MAE, former Waygent skill. |
| `skills/_legacy/README.md` | Frozen, not catalog, not default-installed. |
| `skills/korean-writing-editor/` | Renamed catalog skill. |
| `skills/image-workbench/` | Renamed catalog skill. |
| `skills/README.md` | Korean five-minute catalog. |
| `skills/AGENTS.md` | Agent routing: two skills, Waygent CLI, `_legacy` forbidden unless named. |
| `skills/adding-a-skill.md` | Contributor layout contract. |
| `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/README.md`, `docs/architecture/waygent.md`, `docs/operations/waygent.md` | Present-tense live pointers. |

---

### Task 1: Fail verification routing tests for the target layout

**Files:**
- Modify: `scripts/agent/verification-map.test.ts`
- Modify: `scripts/agent/verify.test.ts`
- Modify: `scripts/agent/check-contract.test.ts`
- Modify: `scripts/agent/claude-offline.test.ts`
- Test: those same files

**Interfaces:**
- Consumes: current `selectVerification`, `REQUIRED_PATHS`, `runClaudeOffline`
- Produces: failing tests that encode `skills/korean-writing-editor`, `skills/image-workbench`, and `skills/_legacy/...` cwd/matchers

- [ ] **Step 1: Rewrite verification-map test constants and cases to the target paths**

In `scripts/agent/verification-map.test.ts` change the command helpers and table rows to:

```ts
const waygentSkillEval = command("waygent-skill-eval", ["./evals/run.sh"], "skills/_legacy/waygent");
const koreanWritingEditorEval = command(
  "korean-writing-editor-eval",
  ["python3", "evals/run.py", "--scope", "full"],
  "skills/korean-writing-editor",
);
const imageWorkbenchEval = command(
  "image-workbench-eval",
  ["python3", "evals/run.py", "--scope", "full"],
  "skills/image-workbench",
);
const imageWorkbenchInspector = command(
  "image-workbench-inspector",
  ["python3", "scripts/inspect_asset.py", "--self-test"],
  "skills/image-workbench",
);
const codexPlanRunnerEval = command(
  "codex-plan-runner-eval",
  ["./evals/run.sh"],
  "skills/_legacy/kws-codex-plan-runner",
);
const claudePlanRunnerEval = command(
  "claude-plan-runner-eval",
  ["./evals/run.sh"],
  "skills/_legacy/kws-claude-plan-runner",
);
const claudeExecutorEval = command(
  "claude-executor-eval",
  ["./evals/run.sh"],
  "skills/_legacy/kws-claude-multi-agent-executor",
  true,
);
```

Replace the skill rows in `test.each` `selects the complete $0 command set`:

```ts
["Waygent skill", ["skills/_legacy/waygent/SKILL.md"], ["waygent-skill"], [contract, diffCheck, waygentSkillEval, check, platformDemo, scenarios]],
["Korean writing editor", ["skills/korean-writing-editor/SKILL.md"], ["korean-writing-editor"], [contract, diffCheck, koreanWritingEditorEval]],
["Image workbench", ["skills/image-workbench/SKILL.md"], ["image-workbench"], [contract, diffCheck, imageWorkbenchEval, imageWorkbenchInspector]],
["Codex plan runner", ["skills/_legacy/kws-codex-plan-runner/SKILL.md"], ["codex-plan-runner"], [contract, diffCheck, codexPlanRunnerEval, planRunnerParity, planRunnerCutoverTest, check]],
["Claude plan runner", ["skills/_legacy/kws-claude-plan-runner/scripts/runner"], ["claude-plan-runner"], [contract, diffCheck, claudePlanRunnerEval, planRunnerParity, planRunnerCutoverTest, check]],
["Claude executor", ["skills/_legacy/kws-claude-multi-agent-executor/scripts/kernel/kernel.py"], ["claude-executor"], [contract, diffCheck, claudeExecutorOffline, claudeExecutorEval, check]],
```

Change the inspector test path to `skills/image-workbench/scripts/inspect_asset.py`.

Add these paths to the docs classification `test.each` that currently lists `.codex/README.md` and `skills/README.md`:

```ts
["skills agent routing", "skills/AGENTS.md"],
["adding a skill", "skills/adding-a-skill.md"],
["legacy catalog note", "skills/_legacy/README.md"],
```

In `keeps independently relevant docs, native, and skill scopes with closure` change `skills/waygent/SKILL.md` to `skills/_legacy/waygent/SKILL.md`.

In `deduplicates commands by cwd and argv` change `skills/kws-codex-plan-runner/scripts/runner.py` to `skills/_legacy/kws-codex-plan-runner/scripts/runner.py`.

Keep `does not route either retired sequential executor` as-is: serialized scopes must still not contain `kws-codex-plan-executor` or `kws-claude-plan-executor` as scope ids or matchers. `_legacy` directory names of those two executor trees are allowed on disk but must not become verification scopes.

- [ ] **Step 2: Point verify.test.ts dry-run paths at `_legacy`**

Replace:

- `paths: ["skills/kws-claude-multi-agent-executor/SKILL.md"]` → `skills/_legacy/kws-claude-multi-agent-executor/SKILL.md`
- dry-run `--path` the same
- expected cwd strings `cwd="skills/kws-claude-multi-agent-executor"` → `cwd="skills/_legacy/kws-claude-multi-agent-executor"`
- Codex plan runner case: path `skills/_legacy/kws-codex-plan-runner/scripts/runner.py` and expected `cwd="skills/_legacy/kws-codex-plan-runner"`

- [ ] **Step 3: Point contract and claude-offline tests at catalog + `_legacy`**

In `scripts/agent/check-contract.test.ts`:

```ts
const EXECUTOR_GATES = [
  "skills/_legacy/kws-codex-plan-runner/evals/run.sh",
  "skills/_legacy/kws-claude-plan-runner/evals/run.sh",
  "skills/_legacy/kws-claude-multi-agent-executor/evals/run.sh",
] as const;
```

Replace the three “requires the … plan runner” / MAE assertions so they expect:

```ts
"skills/_legacy/kws-codex-plan-runner"
"skills/_legacy/kws-codex-plan-runner/AGENTS.md"
"skills/_legacy/kws-claude-plan-runner"
"skills/_legacy/kws-claude-plan-runner/AGENTS.md"
"skills/_legacy/kws-claude-multi-agent-executor"
"skills/_legacy/kws-claude-multi-agent-executor/AGENTS.md"
```

Add:

```ts
test("requires the general skill catalog roots", () => {
  expect(REQUIRED_PATHS).toEqual(expect.arrayContaining([
    "skills/korean-writing-editor",
    "skills/image-workbench",
    "skills/_legacy/waygent",
  ]));
});
```

Keep the retired-executor `not.toContain("skills/kws-codex-plan-executor")` checks: those exact strings without `_legacy` must stay absent from `REQUIRED_PATHS`.

In `scripts/agent/claude-offline.test.ts` set:

```ts
const EXECUTOR = "skills/_legacy/kws-claude-multi-agent-executor";
```

and replace every `/fixture/skills/kws-claude-multi-agent-executor` expected cwd with `/fixture/skills/_legacy/kws-claude-multi-agent-executor`.

- [ ] **Step 4: Run the failing tests**

Run:

```bash
bun test scripts/agent/verification-map.test.ts scripts/agent/verify.test.ts scripts/agent/check-contract.test.ts scripts/agent/claude-offline.test.ts
```

Expected: FAIL. `selectVerification(["skills/korean-writing-editor/SKILL.md"])` does not yield scope `korean-writing-editor` with cwd `skills/korean-writing-editor`. Contract tests fail because `REQUIRED_PATHS` still lists `skills/waygent` and `skills/kws-codex-plan-runner`. Do not implement production code in this task.

- [ ] **Step 5: Commit**

```bash
git add -A -- scripts/agent/verification-map.test.ts scripts/agent/verify.test.ts scripts/agent/check-contract.test.ts scripts/agent/claude-offline.test.ts ':(exclude)**/.DS_Store'
git commit -m "test: expect skills catalog and _legacy verification paths"
```

---

### Task 2: Move trees and make routing tests pass

**Files:**
- Create: `skills/_legacy/` (via `git mv`)
- Move: the eight skill trees listed below
- Modify: `scripts/agent/verification-map.ts`
- Modify: `scripts/agent/contract.ts`
- Modify: `scripts/agent/claude-offline.ts`
- Modify: `scripts/agent/check-plan-runner-parity.py`
- Modify: `scripts/agent/plan-runner-cutover.py`
- Modify: `scripts/agent/test_plan_runner_cutover.py`
- Test: Task 1 tests plus `python3 -m unittest scripts.agent.test_plan_runner_cutover`

**Interfaces:**
- Consumes: failing tests from Task 1
- Produces: `selectVerification` cwd/matchers, `REQUIRED_PATHS`, `EXECUTOR_ROOT`, cutover `_source_paths(repo) -> dict[str, Path]` using `repo / "skills" / "_legacy" / name`

- [ ] **Step 1: Fail cutover tests against `_legacy` source paths**

In `scripts/agent/test_plan_runner_cutover.py` `ApplyTests.setUp`, create runner stubs under `_legacy`:

```python
for name in ("kws-codex-plan-runner", "kws-claude-plan-runner"):
    (self.repo / "skills" / "_legacy" / name).mkdir(parents=True)
self.codex_legacy = self.repo / "skills" / "_legacy" / "kws-codex-plan-executor"
self.claude_legacy = self.repo / "skills" / "_legacy" / "kws-claude-plan-executor"
```

Change every expected `self.repo / "skills" / "kws-codex-plan-runner"` (and claude runner, MAE, executor) **source** path to insert `"_legacy"` after `"skills"`. Home destinations stay `self.home / ".codex" / "skills" / "kws-codex-plan-runner"` (legacy install names).

Grep the test file for ` / "skills" / "kws-` and update source-side paths only.

- [ ] **Step 2: Run cutover tests to see RED**

```bash
python3 -m unittest scripts.agent.test_plan_runner_cutover
```

Expected: FAIL because `_source_paths` still returns `repo / "skills" / name`.

- [ ] **Step 3: Retarget cutover and parity source paths**

In `scripts/agent/plan-runner-cutover.py` add and use:

```python
def _legacy_skill_dir(repo: Path, name: str) -> Path:
    return repo / "skills" / "_legacy" / name
```

Replace `_source_paths` with:

```python
def _source_paths(repo: Path) -> dict[str, Path]:
    return {
        name: _legacy_skill_dir(repo, name)
        for name in (*LEGACY_NAMES, *NEW_NAMES)
    }
```

Replace every `repo / "skills" / name` and `repository / "skills" / name` and `root / "skills" / LEGACY_NAMES[…]` **source-tree** construction with `_legacy_skill_dir(...)`. Do not change `_link_paths` home destinations.

In `_tracked_legacy_paths` change the git pathspecs to `skills/_legacy/{name}`.

In `scripts/agent/check-plan-runner-parity.py` `PROVIDERS`:

```python
"runner": REPO_ROOT / "skills/_legacy/kws-codex-plan-runner/scripts/runner",
"fake": REPO_ROOT / "skills/_legacy/kws-codex-plan-runner/evals/fake_codex.py",
```

and the matching `kws-claude-plan-runner` paths.

Do not rewrite other `_legacy` skill bodies.

- [ ] **Step 4: `git mv` the trees**

```bash
mkdir -p skills/_legacy
git mv skills/kws-codex-plan-runner skills/_legacy/kws-codex-plan-runner
git mv skills/kws-claude-plan-runner skills/_legacy/kws-claude-plan-runner
git mv skills/kws-codex-plan-executor skills/_legacy/kws-codex-plan-executor
git mv skills/kws-claude-plan-executor skills/_legacy/kws-claude-plan-executor
git mv skills/kws-claude-multi-agent-executor skills/_legacy/kws-claude-multi-agent-executor
git mv skills/waygent skills/_legacy/waygent
git mv skills/kws-korean-writing-editor skills/korean-writing-editor
git mv skills/kws-image-workbench skills/image-workbench
```

Do not edit files inside the moved `_legacy` trees in this step.

- [ ] **Step 5: Implement map, contract, and claude-offline cwd**

`scripts/agent/verification-map.ts`:

```ts
const WAYGENT_SKILL_EVAL: CommandSpec = { id: "waygent-skill-eval", argv: ["./evals/run.sh"], cwd: "skills/_legacy/waygent" };
```

Set `KOREAN_WRITING_EDITOR_EVAL.cwd` to `"skills/korean-writing-editor"`.
Set both image-workbench command cwds to `"skills/image-workbench"`.
Set plan-runner eval cwds to `"skills/_legacy/kws-codex-plan-runner"` and `"skills/_legacy/kws-claude-plan-runner"`.
Set `CLAUDE_EXECUTOR_EVAL.cwd` to `"skills/_legacy/kws-claude-multi-agent-executor"`.

Matchers:

```ts
{ id: "waygent-skill", matchers: ["skills/_legacy/waygent/"], ... }
{ id: "korean-writing-editor", matchers: ["skills/korean-writing-editor/"], ... }
{ id: "image-workbench", matchers: ["skills/image-workbench/"], ... }
{ id: "codex-plan-runner", matchers: ["skills/_legacy/kws-codex-plan-runner/"], ... }
{ id: "claude-plan-runner", matchers: ["skills/_legacy/kws-claude-plan-runner/"], ... }
{ id: "claude-executor", matchers: ["skills/_legacy/kws-claude-multi-agent-executor/"], ... }
```

Docs matchers add `"skills/AGENTS.md"`, `"skills/adding-a-skill.md"`, `"skills/_legacy/README.md"` next to `"skills/README.md"`.

`scripts/agent/contract.ts` `REQUIRED_PATHS`:

```ts
export const REQUIRED_PATHS = [
  "apps/cli", "apps/api", "apps/console",
  "packages/orchestrator", "packages/runway-control",
  "packages/provider-adapters", "packages/lens-store",
  "packages/lens-projectors", "native/kernel",
  "skills/korean-writing-editor",
  "skills/image-workbench",
  "skills/_legacy/waygent",
  "skills/_legacy/kws-codex-plan-runner",
  "skills/_legacy/kws-claude-plan-runner",
  "skills/_legacy/kws-claude-multi-agent-executor",
] as const;
```

`SUBTREE_GUIDANCE_FILES` skill entries:

```ts
"skills/AGENTS.md",
"skills/_legacy/kws-codex-plan-runner/AGENTS.md",
"skills/_legacy/kws-claude-plan-runner/AGENTS.md",
"skills/_legacy/kws-claude-multi-agent-executor/AGENTS.md",
```

`scripts/agent/claude-offline.ts`:

```ts
const EXECUTOR_ROOT = "skills/_legacy/kws-claude-multi-agent-executor";
```

- [ ] **Step 6: Run routing tests**

```bash
bun test scripts/agent/verification-map.test.ts scripts/agent/verify.test.ts scripts/agent/check-contract.test.ts scripts/agent/claude-offline.test.ts
python3 -m unittest scripts.agent.test_plan_runner_cutover
```

Expected: PASS. `bun run agent:contract` is not required yet if catalog markdown is still the old README; if it fails because `skills/_legacy/README.md` is missing, that is Task 3. If it fails because required `_legacy` AGENTS.md files are missing, the `git mv` was incomplete — fix the move, do not recreate files.

- [ ] **Step 7: Commit**

```bash
git add -A -- . ':(exclude)**/.DS_Store'
git commit -m "refactor: move legacy skills under skills/_legacy"
```

Stage only the move plus the routing/cutover/parity/contract files from this task. Leave still-kws-named catalog skill internals for later tasks.

---

### Task 3: Catalog markdown (README, AGENTS, adding-a-skill, `_legacy` README)

**Files:**
- Create: `skills/_legacy/README.md`
- Create: `skills/adding-a-skill.md`
- Modify: `skills/README.md`
- Modify: `skills/AGENTS.md`
- Test: `bun test scripts/agent/verification-map.test.ts` (docs classification) and `bun run agent:contract`

**Interfaces:**
- Consumes: target tree from Task 2
- Produces: catalog files whose facts match spec sections 8.1–8.3

- [ ] **Step 1: Write `skills/_legacy/README.md` exactly**

```markdown
# Legacy skills

이 디렉터리는 카탈로그가 아닙니다. 기본 설치 대상도 아닙니다.

Frozen local execution trees live here: plan runners, plan executors,
the Claude multi-agent executor, and the former Waygent skill. Keep their
directory names. Do not treat them as general skills.

Agent rules:

- Do not load any path under `skills/_legacy/` unless the user explicitly
  names that path.
- If the user names a path, follow that tree's `SKILL.md`.
- Waygent product execution is the `waygent` CLI, not `waygent/` in this
  directory.
- Do not add new usage guides here. Historical documents stay as-is.
```

- [ ] **Step 2: Write `skills/adding-a-skill.md` exactly**

```markdown
# Adding a general skill

Use this file when adding a skill under `skills/`. Do not put Waygent
product runtime or Superpowers plan execution here.

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
- Add the skill to the `skills/README.md` table and the `skills/AGENTS.md`
  routing list in the same change.
- If the skill has evals, register matchers and commands in
  `scripts/agent/verification-map.ts` in the same change.
```

(The inner tree fence in the file should be a markdown code fence as in the
spec. Do not nest equal-length fences; use a 4-backtick outer fence in the
skill file if needed.)

- [ ] **Step 3: Replace `skills/AGENTS.md` with these rules in this order**

```markdown
# Skills Agent Instructions

1. Read the target skill's `SKILL.md`, README, and change protocol before
   editing that skill.
2. Catalog skills are only `korean-writing-editor` and `image-workbench`.
3. Korean proofread, correct, or polish of supplied Korean text →
   `korean-writing-editor`.
4. Project-bound raster plan, generate, edit, or audit → `image-workbench`.
5. Run, resume, inspect, explain, verify, review, or apply a Waygent
   execution → `waygent` CLI or `bun run waygent -- …`. Do not load
   `skills/_legacy/waygent`.
6. Do not load any path under `skills/_legacy/` unless the user explicitly
   names that path.
7. Keep skill docs, evals, and advertised commands synchronized.
8. Skills do not redefine Waygent product ownership.
```

- [ ] **Step 4: Replace `skills/README.md` with the Korean catalog**

The file must contain, in order:

1. One paragraph: 이 디렉터리는 Archive가 관리하는 일반 스킬의 원본이다.
2. Table:

| 스킬 | 용도 |
| --- | --- |
| [`korean-writing-editor`](./korean-writing-editor/) | 이미 있는 한국어 글을 뜻과 말투를 유지하며 교정·윤문합니다. |
| [`image-workbench`](./image-workbench/) | 프로젝트에 맞는 래스터 자산을 계획·생성·편집·검토합니다. Codex 전용입니다. |

3. 쓰지 말아야 할 때: 일상 한국어 대화·번역·초안·요약·코드 리뷰·검출 회피는 `korean-writing-editor`가 아니다. 한 장짜리 취미 이미지·SVG/아이콘/실제 UI 구현은 `image-workbench`가 아니다.
4. 설치: 스크립트 없음. `korean-writing-editor`는 `~/.agents/skills/korean-writing-editor` 사본, Claude는 그 사본을 `~/.claude/skills/korean-writing-editor`로 링크하거나 복사. `image-workbench`는 `~/.agents/skills/image-workbench`만 (Codex). 홈의 실제 디렉터리는 확인 없이 덮어쓰지 않는다.
5. 호출: Codex `$korean-writing-editor` / `$image-workbench`. Claude Code, Cursor, Grok Build `/korean-writing-editor` / `/image-workbench`.
6. `_legacy`는 위 표에 없고 이 가이드로 설치하지 않으며 동결이다. [`_legacy/README.md`](./_legacy/README.md)를 가리킨다.
7. 새 일반 스킬은 [`adding-a-skill.md`](./adding-a-skill.md).

Do not list runners, executors, versions, or Waygent CLI flags. Do not teach `$kws-…` as a supported invocation.

- [ ] **Step 5: Prove docs classification and contract**

```bash
bun test scripts/agent/verification-map.test.ts
bun run agent:contract
```

Expected: PASS. `selectVerification(["skills/adding-a-skill.md"]).scopeIds` equals `["docs"]`. `checkContract` finds `skills/_legacy/waygent` and the catalog roots.

- [ ] **Step 6: Commit**

```bash
git add -A -- skills/README.md skills/AGENTS.md skills/adding-a-skill.md skills/_legacy/README.md ':(exclude)**/.DS_Store'
git commit -m "docs: rewrite skills catalog for two general skills"
```

---

### Task 4: Rename `korean-writing-editor` contract and lock old invocations

**Files:**
- Modify: `skills/korean-writing-editor/evals/run.py`
- Modify: `skills/korean-writing-editor/evals/cases.json`
- Modify: `skills/korean-writing-editor/SKILL.md`
- Modify: `skills/korean-writing-editor/README.md`
- Modify: `skills/korean-writing-editor/CHANGE_PROTOCOL.md`
- Modify: `skills/korean-writing-editor/references/sources.md`
- Modify: `skills/korean-writing-editor/evals/README.md` (advertised current commands only)
- Test: `python3 skills/korean-writing-editor/evals/run.py --scope full`

**Interfaces:**
- Consumes: `SKILL_NAME`, `EXPECTED_CATEGORY_COUNTS`, `REQUIRED_HEADINGS`, cases
- Produces: `SKILL_NAME = "korean-writing-editor"`; trigger count 5; old `$kws-korean-writing-editor` is `expected_trigger: false`

- [ ] **Step 1: Change evaluator identity and add the failing near-miss case**

In `evals/run.py`:

```python
SKILL_NAME = "korean-writing-editor"
EXPECTED_CATEGORY_COUNTS = {
    "normative": 8,
    "preservation": 8,
    "noop": 6,
    "voice": 4,
    "trigger": 5,
}
```

`REQUIRED_HEADINGS["SKILL.md"]` first heading becomes `"# Korean Writing Editor"`.
`REQUIRED_HEADINGS["README.md"]` first heading becomes `"# korean-writing-editor"`.

Replace remaining `kws-korean-writing-editor` strings in `run.py` (module docstring, heading checks, any advertised-command checks) with `korean-writing-editor`, except strings that will live only in the new near-miss case.

In `evals/cases.json`:

- Change `trigger-explicit-01` `request` to `$korean-writing-editor 이 문장을 자연스럽게 다듬어줘: 결과 공유가 늦어져서 미안해요.` Keep `expected_trigger: true`.
- Append:

```json
{
  "id": "trigger-legacy-kws-05",
  "category": "trigger",
  "request": "$kws-korean-writing-editor 이 문장을 자연스럽게 다듬어줘: 결과 공유가 늦어져서 미안해요.",
  "source": "결과 공유가 늦어져서 미안해요.",
  "candidate": "결과 공유가 늦어져서 미안해요.",
  "candidate_trigger": false,
  "candidate_mode": "none",
  "candidate_tier": "none",
  "expected_trigger": false,
  "expected_mode": "none",
  "expected_tier": "none",
  "expected_noop": true,
  "must_preserve": ["결과 공유가 늦어져서 미안해요."],
  "required_substrings": ["결과 공유가 늦어져서 미안해요."],
  "forbidden_substrings": ["번역하면"],
  "rationale": "Former kws- invocation is a near-miss; do not activate."
}
```

- [ ] **Step 2: Run eval to confirm RED**

```bash
python3 skills/korean-writing-editor/evals/run.py --scope full
```

Expected: FAIL on directory/frontmatter/README heading/name (`kws-korean-writing-editor` vs `korean-writing-editor`) and/or missing catalog heading until SKILL/README match. Keep the failure; do not weaken the evaluator.

- [ ] **Step 3: Update SKILL.md, README, CHANGE_PROTOCOL, sources, evals README**

`SKILL.md`:

- `name: korean-writing-editor`
- `metadata.version: "2.0.0"`
- `updated_at: "2026-08-25"`
- Title `# Korean Writing Editor`
- Explicit invocation `$korean-writing-editor` and `/korean-writing-editor` only
- Do not list kws- as supported

`README.md`:

- Title `# korean-writing-editor`
- Invocation table uses the new names
- Install paths `~/.agents/skills/korean-writing-editor` and `~/.claude/skills/korean-writing-editor`
- Variables `EDITOR_SOURCE`, `EDITOR_AGENTS_TARGET`, `EDITOR_CLAUDE_TARGET`
- Verification command `python3 skills/korean-writing-editor/evals/run.py --scope full`
- One cutover warning in 설치: 새 경로를 만든 뒤에, 이 스킬의 이전 설치임이 확인된 `~/.agents/skills/kws-korean-writing-editor`(및 대응 Claude 경로)만 제거한다. 지원하는 호출 이름이 아니다.
- Do not teach `$kws-korean-writing-editor` as a current command

`CHANGE_PROTOCOL.md` verification path: `python3 skills/korean-writing-editor/evals/run.py --scope full`

`references/sources.md`: skill id `` `korean-writing-editor` ``

`evals/README.md`: advertised current commands use `skills/korean-writing-editor/...`. Replay blocks that reproduce `docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md` may keep that report's `RUN_ID`, evidence-root, and report path, and must say they replay that dated report, not the current default. New default evidence-root is `.superpowers/korean-writing-editor/live`.

Grep the tree:

```bash
rg -n 'kws-korean-writing-editor|KWS_EDITOR_|KWS Korean' skills/korean-writing-editor
```

Allowed hits: `evals/cases.json` `trigger-legacy-kws-05`, the one README cutover warning, and labeled dated-report replay snippets. Nothing else.

- [ ] **Step 4: Run eval GREEN**

```bash
python3 skills/korean-writing-editor/evals/run.py --scope full
```

Expected: PASS, including 5 trigger cases. Offline success is not live model quality.

- [ ] **Step 5: Commit**

```bash
git add -A -- skills/korean-writing-editor ':(exclude)**/.DS_Store'
git commit -m "feat: rename korean-writing-editor and reject kws- invocation"
```

---

### Task 5: Rename `image-workbench` contract and lock old invocations

**Files:**
- Modify: `skills/image-workbench/evals/run.py`
- Modify: `skills/image-workbench/evals/cases.json`
- Modify: `skills/image-workbench/SKILL.md`
- Modify: `skills/image-workbench/README.md`
- Modify: `skills/image-workbench/CHANGE_PROTOCOL.md`
- Test: `python3 skills/image-workbench/evals/run.py --self-test` and `--scope full`; `python3 skills/image-workbench/scripts/inspect_asset.py --self-test`

**Interfaces:**
- Consumes: evaluator name checks, `EXPECTED_CATEGORY_COUNTS`, README approved requests
- Produces: canonical name `image-workbench`; routing count 9; `$kws-image-workbench` `expected_trigger: false`

- [ ] **Step 1: Change evaluator identity and add the failing near-miss case**

In `evals/run.py`:

- Module docstring: `image-workbench`
- `name: image-workbench` in `canonical_frontmatter` and every test fixture that currently writes `kws-image-workbench`
- `EXPECTED_CATEGORY_COUNTS["routing"] = 9`
- Frontmatter regex `name:\s*image-workbench`
- Heading `# Image Workbench` and README `# image-workbench`
- Canonical directory check:

```python
if skill_root.name != "image-workbench" or skill_root.parent.name != "skills":
    errors.append(
        "skill tree: canonical directory must be skills/image-workbench"
    )
```

- Catalog check: `"image-workbench" not in index_path.read_text(...)`
- README approved requests become `$image-workbench …` (same four Korean sentences)
- `required_commands` paths become `skills/image-workbench/...`
- Self-test README snippets that currently contain `$kws-image-workbench` become `$image-workbench`

Append to `evals/cases.json` (routing category):

```json
{
  "id": "near-miss-legacy-kws-invocation",
  "category": "routing",
  "request": "$kws-image-workbench 이 프로젝트 랜딩 페이지 hero 이미지를 만들어줘.",
  "candidate_trigger": false,
  "candidate_mode": "none",
  "candidate_route": "no_op",
  "candidate_tool_action": "none",
  "candidate_input_roles": [],
  "candidate_invariants": ["ordinary_imagegen"],
  "candidate_destination_action": "none",
  "candidate_ignored_embedded_instructions": true,
  "candidate_statuses": {},
  "candidate_report_fields": ["route"],
  "expected_trigger": false,
  "expected_mode": "none",
  "expected_route": "no_op",
  "expected_tool_action": "none",
  "required_input_roles": [],
  "required_invariants": ["ordinary_imagegen"],
  "expected_destination_action": "none",
  "expected_ignored_embedded_instructions": true,
  "required_statuses": {},
  "required_report_fields": ["route"],
  "replacement_authorized": false,
  "rationale": "Former kws- invocation is a near-miss; do not activate."
}
```

- [ ] **Step 2: Run eval RED**

```bash
python3 skills/image-workbench/evals/run.py --self-test
python3 skills/image-workbench/evals/run.py --scope full
```

Expected: FAIL on name/path/heading mismatches and the new case count until SKILL/README/CHANGE_PROTOCOL match.

- [ ] **Step 3: Update SKILL.md, README, CHANGE_PROTOCOL**

`SKILL.md`:

- `name: image-workbench`
- version `"2.0.0"`, `updated_at: "2026-08-25"`
- Title `# Image Workbench`
- Inspect command `python3 skills/image-workbench/scripts/inspect_asset.py <path>`

`README.md`:

- `# image-workbench`
- Examples `$image-workbench …`
- Install `~/.agents/skills/image-workbench`
- Variables `IMAGE_SOURCE`, `IMAGE_TARGET`
- Verification commands with `skills/image-workbench/`
- One cutover warning: 새 경로를 만든 뒤 이전 `~/.agents/skills/kws-image-workbench`는 이 스킬의 옛 설치임이 확인될 때만 제거한다.

`CHANGE_PROTOCOL.md` retarget `quick_validate.py` argument and python paths to `skills/image-workbench`. If `quick_validate.py` is still listed, keep it with the new path; missing host helper is skipped later, not deleted here unless the evaluator no longer requires it.

Grep:

```bash
rg -n 'kws-image-workbench|KWS_IMAGE_|KWS Image' skills/image-workbench
```

Allowed: the new near-miss case request string and the one README cutover warning.

- [ ] **Step 4: Run eval GREEN**

```bash
python3 skills/image-workbench/evals/run.py --self-test
python3 skills/image-workbench/evals/run.py --scope full
python3 skills/image-workbench/scripts/inspect_asset.py --self-test
```

Expected: PASS. Do not call live image generation.

- [ ] **Step 5: Commit**

```bash
git add -A -- skills/image-workbench ':(exclude)**/.DS_Store'
git commit -m "feat: rename image-workbench and reject kws- invocation"
```

---

### Task 6: Retarget present-tense live pointers

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/superpowers/specs/2026-08-25-skills-catalog-identity-design.md` (status only)
- Test: `git diff --check` and `bun run agent:contract`

**Interfaces:**
- Consumes: spec sections 9 and 5
- Produces: present-tense docs that name the new tree and do not 404

- [ ] **Step 1: Rewrite root `AGENTS.md` Project Shape and Task Routing**

Project Shape `skills/` bullet:

```markdown
- `skills/` - source of truth for general personal skills
  (`korean-writing-editor`, `image-workbench`), not Waygent execution or
  plan-runner skills. Frozen execution trees live under `skills/_legacy/`.
```

Task Routing replacements (keep orchestration/provider/lens/product bullets):

```markdown
- Waygent workflow contract: `apps/cli` and the `waygent` CLI, not a skill
- General skills: `skills/korean-writing-editor/`,
  `skills/image-workbench/`
```

Remove default routing to plan-runner and MAE skills. Replace the Claude-executor follow-up sentence with:

```markdown
Waygent owns scheduling, state, worktrees, runtime adapters, verification,
recovery, apply, and Lens emission. Do not manually orchestrate workers from
chat context when a Waygent run is requested. If the user names the legacy
Claude executor tree, follow
`skills/_legacy/kws-claude-multi-agent-executor/AGENTS.md`.
```

Keep the `kws-cpe.*` / `kws-cme.*` event-namespace warning unchanged.

- [ ] **Step 2: Rewrite `CLAUDE.md`**

Start-here item 3: `Read the target skill's SKILL.md before changing that skill.`

Claude-specific notes:

- Delete default sequential `skills/kws-claude-plan-runner` routing.
- Waygent CLI remains the product execution path (keep the existing `apps/cli` / `waygent` sentence).
- If the user names the legacy executor tree, follow `skills/_legacy/kws-claude-multi-agent-executor/AGENTS.md`.
- Useful checks: replace `cd skills/kws-claude-multi-agent-executor && ./evals/run.sh` with `cd skills/_legacy/kws-claude-multi-agent-executor && ./evals/run.sh` and a one-line note that this eval is opt-in, not default routing.

- [ ] **Step 3: Fix index links**

Root `README.md`: keep `[skills/README.md](skills/README.md)`. Replace `Waygent skill: [skills/waygent/README.md](...)` with a CLI pointer such as `Waygent CLI: \`apps/cli\` / \`waygent\``. Do not link the legacy skill as the operator entry.

`docs/README.md` Skill Docs section becomes:

```markdown
## Skill Docs

- [Skills overview](../skills/README.md)

The catalog is two general skills. Deprecated execution skills live under
`skills/_legacy/` and are not the default path. Operators run Waygent through
the `waygent` CLI, not a skill.
```

`docs/architecture/waygent.md` present-tense only:

- Active product tree sentence: `apps/`, `packages/`, `native/`, `tests/`, `docs/` — drop `skills/waygent/`.
- Runtime parity bullet: operators use the `waygent` CLI; the former skill tree is `skills/_legacy/waygent` and is not the catalog entrypoint.

`docs/operations/waygent.md`: change present-tense `skills/waygent/evals/run.sh` to `skills/_legacy/waygent/evals/run.sh` in the two default verification blocks. Do not rewrite the rest of the operations guide.

Spec status line: `**Status:** Approved`.

- [ ] **Step 4: Sweep live pointers**

```bash
rg -n 'skills/waygent|skills/kws-' AGENTS.md CLAUDE.md README.md docs/README.md docs/architecture/waygent.md docs/operations/waygent.md skills/README.md skills/AGENTS.md
```

Expected: remaining `skills/kws-` / `skills/waygent` hits are only `_legacy` paths or the event-namespace warning. No present-tense `skills/waygent/` as catalog/product entry. Dated files under `docs/operations/2026-*` and `docs/migration/` are not in this sweep.

- [ ] **Step 5: Check**

```bash
bun run agent:contract
git diff --check
```

Expected: PASS / clean.

- [ ] **Step 6: Commit**

```bash
git add -A -- AGENTS.md CLAUDE.md README.md docs/README.md docs/architecture/waygent.md docs/operations/waygent.md docs/superpowers/specs/2026-08-25-skills-catalog-identity-design.md ':(exclude)**/.DS_Store'
git commit -m "docs: route Waygent through CLI and drop kws skill defaults"
```

---

### Task 7: Final offline verification

**Files:**
- None unless a selected gate fails; then fix only the failing live pointer or eval assertion from earlier tasks

**Interfaces:**
- Consumes: all previous tasks
- Produces: required evidence in spec section 13

- [ ] **Step 1: Run skill evals**

```bash
python3 skills/korean-writing-editor/evals/run.py --scope full
python3 skills/image-workbench/evals/run.py --self-test
python3 skills/image-workbench/evals/run.py --scope full
python3 skills/image-workbench/scripts/inspect_asset.py --self-test
```

Expected: PASS. If Codex `quick_validate.py` is invoked from CHANGE_PROTOCOL but missing on the machine, do not fail this task for that helper; report it skipped.

- [ ] **Step 2: Run agent tests**

```bash
bun test scripts/agent/verification-map.test.ts scripts/agent/verify.test.ts
bun test scripts/agent/check-contract.test.ts scripts/agent/claude-offline.test.ts
python3 -m unittest scripts.agent.test_plan_runner_cutover
```

Expected: PASS.

- [ ] **Step 3: Run repository verify on this change**

```bash
bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD
git diff --check
```

`MERGE_BASE` is `git merge-base origin/main HEAD` (or `main` if that is the parent of this work). `CANDIDATE_HEAD` is `HEAD`.

Expected: green. Because plan-runner and MAE trees moved, the map must select their `_legacy` evals; run them; do not skip because they are deprecated. Opt-in `claude-executor-eval` and live provider smoke stay skipped unless explicitly requested.

Report skipped opt-in evidence. Do not claim home installs were rewritten or that host skill catalogs reloaded.

- [ ] **Step 4: Commit only if Step 3 required a fix**

If no files changed, do not create an empty commit. If a fix was required:

```bash
git add -A -- . ':(exclude)**/.DS_Store'
git commit -m "fix: close skills catalog identity verification gaps"
```

---

## Spec Coverage

| Spec section | Task |
| --- | --- |
| 5 Ownership, 6 target tree, 12 steps 1–3 | 1–2 |
| 8 catalog docs, 8.1–8.3 | 3 |
| 7 naming, 7.3 near-miss, 11 old invocations, version 2.0.0 | 4–5 |
| 9 live pointer rule, 5 AGENTS routing | 6 |
| 10 verification map and legacy tools | 1–2 |
| 13 verification | 7 |
| 3 non-goals / 15 follow-ups | not implemented |
| 14 file list | tasks 2–6 |

## Placeholder / consistency notes

- Cutover home install names remain `kws-*`; only repo source paths move. That matches spec section 10.
- `kws-codex-plan-executor` / `kws-claude-plan-executor` stay out of `REQUIRED_PATHS` and verification scopes. They still move on disk.
- Spec status is marked Approved in Task 6, not rewritten otherwise.
