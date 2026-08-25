# Skills Catalog Identity Design

**Date:** 2026-08-25

**Status:** Approved

**Repository:** Archive

**Primary surface:** `skills/`

## 1. Summary

Rebuild `skills/` as the source of truth for Archive-managed **general
personal skills** only. The catalog has two first-class skills:
`korean-writing-editor` and `image-workbench`. Their public names, directory
names, skill ids, install paths, and explicit invocations drop the `kws-`
prefix.

Waygent remains the product runtime and is invoked through the `waygent` CLI
(`apps/cli`, or `bun run waygent -- …`). It is not a catalog skill.

Plan runners, plan executors, the Claude multi-agent executor, and the former
`skills/waygent` skill tree move under `skills/_legacy/`. They stay in the
repository, keep their current directory names and internal history, are not
default-installed, and are not loaded unless the user names that path.

Human docs and agent routing are split. `skills/README.md` is a five-minute
use guide. `skills/AGENTS.md` is the agent routing contract. A short
`skills/adding-a-skill.md` tells contributors where a new general skill goes
and which files it must keep in lockstep.

## 2. Goals

1. Make the skill catalog match what people can actually use: two general
   skills, plus Waygent as a CLI, not a third skill.
2. Give those two skills names that state the work (`korean-writing-editor`,
   `image-workbench`) with no owner prefix and no aliases.
3. Put a human install/use guide, an agent routing file, and a contributor
   layout guide in `skills/` so the next general skill has a home.
4. Move deprecated execution trees out of the catalog root without rewriting
   their historical documents, event names, or CHANGELOG bodies.
5. Keep current live pointers true after the move so agent instructions and
   the documentation index do not 404 or still present runners as the default
   path.
6. Prove the rename and routing change with offline evals and the repository
   verification map. Live home-install cutover is opt-in and is not claimed
   by `bun run agent:verify`.

## 3. Non-Goals

This design does not:

- move Waygent operator docs or the NL lexicon into `apps/cli`;
- rewrite `docs/superpowers/`, `docs/migration/`, dated operations reports, or
  git history;
- rewrite bodies under `skills/_legacy/` after the move, including adding
  deprecation banners inside each legacy `SKILL.md`;
- keep `$kws-…` / `/kws-…` aliases, compatibility symlinks, or dual install
  names for the two active skills;
- delete or rewrite existing home-directory installs automatically;
- change Waygent CLI flags, runtime packages, event schemas, or
  `kws-cpe.*` / `kws-cme.*` historical event namespaces;
- archive or delete legacy executor code;
- fold the separate `kws-skills` plugin into this repository;
- build a documentation site or add skills beyond the two active ones;
- change the editorial, image, or eval *behavior* of the two active skills
  except names, paths, versions, and the old-name near-miss contract.

## 4. Decisions

| Topic | Choice |
|---|---|
| Brand model | Product name `waygent` stays. Remaining catalog skills use unprefixed role names. |
| First-class catalog | `korean-writing-editor`, `image-workbench` only. |
| Waygent skill | Out of the catalog. Operators and agents use the CLI. |
| Physical layout | Deprecated trees live under `skills/_legacy/`. |
| Old names | Hard cut. No aliases on the active surface. |
| Trace removal | Active surface only. `_legacy` history keeps `kws-*` names. |
| Docs success | Five-minute use plus a short contributor guide. |
| Approach | Thin catalog standard. No product-docs relocation in this spec. |

## 5. Ownership

| Layer | Home | Default agent action |
|---|---|---|
| General skills | `skills/<name>/` | Load that `SKILL.md` only when the trigger matches. |
| Waygent product | `apps/cli` and runtime packages | Run `waygent` / `bun run waygent -- …`. Read CLI help. Do not load a skill. |
| Legacy executors and the former Waygent skill | `skills/_legacy/` | Do not load unless the user names that path. |

`skills/` is no longer the home of product execution or Superpowers plan
runners. Root `AGENTS.md` must say that explicitly.

## 6. Target Tree

```text
skills/
  README.md
  AGENTS.md
  adding-a-skill.md
  korean-writing-editor/
  image-workbench/
  _legacy/
    README.md
    kws-codex-plan-runner/
    kws-claude-plan-runner/
    kws-codex-plan-executor/
    kws-claude-plan-executor/
    kws-claude-multi-agent-executor/
    waygent/
```

Move with `git mv` so file history is preserved. Legacy directory names stay
`kws-*` and `waygent`. Do not flatten, merge, or rename those trees.

Each first-class skill keeps this layout, which both skills already have:

```text
<name>/
  SKILL.md
  README.md
  CHANGE_PROTOCOL.md
  evals/
  references/          # when needed
  scripts/             # when needed
```

## 7. Naming And Install Identity

### 7.1 Public names

| Role | Skill id and directory | Explicit invocation | Install |
|---|---|---|---|
| Korean proofreading and polish | `korean-writing-editor` | `$korean-writing-editor` and `/korean-writing-editor` | Canonical copy at `~/.agents/skills/korean-writing-editor`. Claude Code uses `~/.claude/skills/korean-writing-editor` as a copy or link to that install. |
| Project-bound raster work | `image-workbench` | `$image-workbench` and `/image-workbench` | `~/.agents/skills/image-workbench` only. Codex-only, unchanged from today. |

`SKILL.md` `name` must equal the directory name. Titles drop `KWS`.

Install remains a documented manual copy or link. There is no installer
script.

### 7.2 Active-surface rename

In the two active skill trees and in live routing/docs, replace:

- directory names;
- `SKILL.md` `name`, headings, and explicit invocation strings;
- README install paths, invocation tables, and examples;
- shell variables such as `KWS_EDITOR_*` and `KWS_IMAGE_*` with unprefixed
  task variables (`EDITOR_SOURCE`, `EDITOR_AGENTS_TARGET`,
  `EDITOR_CLAUDE_TARGET`, `IMAGE_SOURCE`, `IMAGE_TARGET`);
- `CHANGE_PROTOCOL.md` verification command paths;
- eval fixtures, cases, and evaluator assertions that encode the skill id,
  path, parent directory, or supported invocation, including
  `evals/run.py` name constants and install-state fixtures;
- advertised current commands in `evals/README.md`. Replay snippets that
  reproduce a dated operations report may keep that report's run id,
  evidence-root, and report path, and must be labeled as replay of that
  report rather than the current default.

Bump both skills to `metadata.version: "2.0.0"` and `updated_at: "2026-08-25"`.
The trigger and install path are a breaking public contract. Add a 2.0.0 note
where a changelog exists; do not rewrite older changelog entries.

### 7.3 Permitted `kws-` strings in active trees

Catalog docs, `SKILL.md`, and READMEs must not teach old names as supported
invocations or install names, and must not keep aliases.

Allowed `kws-korean-writing-editor` / `kws-image-workbench` strings inside
those two trees:

- **near-miss fixtures**: a request that uses `$kws-…` or `/kws-…` is a
  no-op and must not activate the skill;
- **one cutover warning** in each skill README install section: after the
  new path exists, remove the previous home directory only if it is this
  skill's old install. That is a removal instruction, not a supported
  name.

### 7.4 Home directories

The repository must not delete `$HOME` skill directories. The human README
must tell the operator to:

1. confirm the new source path in this checkout;
2. install under the new names;
3. remove the old `kws-*` home path only after confirming it is this skill's
   previous install;
4. start a new agent session.

Do not leave a `kws-*` symlink next to the new name after that cutover.

## 8. Documentation

Human-facing catalog and skill READMEs stay Korean. Agent contracts
(`SKILL.md`, `skills/AGENTS.md`, `adding-a-skill.md`) stay English.

One fact, one home.

| File | Audience | Must contain | Must not contain |
|---|---|---|---|
| `skills/README.md` | Human | Two-skill table, five-minute install, invocations, when not to use each skill, `_legacy` is not default-installed | Runner/executor contracts, version history, Waygent CLI reference |
| `skills/AGENTS.md` | Agent | Load only the two catalog skills. Waygent is CLI. `_legacy` is forbidden until the user names the path | Install tutorial, legacy how-to |
| `skills/adding-a-skill.md` | Contributor | Layout, name=directory, README/SKILL/evals lockstep, catalog registration, verification-map registration when evals exist, no `kws-` prefix, no Waygent/executor skills here | Per-skill usage |
| `<skill>/README.md` | Human | One-minute start, modes, install for that skill | Whole-catalog policy |
| `<skill>/SKILL.md` | Agent | Triggers and behavior contract | Install procedure |
| `skills/_legacy/README.md` | Both | Frozen, not catalog, not default-installed. If the user names a path, follow that tree's `SKILL.md` | New usage guides |

### 8.1 `skills/README.md` required shape

1. One-paragraph definition: this directory is the source of truth for
   Archive-managed general skills.
2. Table of the two skills with one-line use and a link to each README.
3. When not to use them (reuse each skill's existing exclusions, shortened).
4. Portable install for `korean-writing-editor` (agents copy, Claude link or
   copy) and Codex-only install for `image-workbench`.
5. Explicit invocations per runtime (Codex `$`, Claude/Cursor/Grok Build `/`).
6. A short `_legacy` note: not listed above, not installed by this guide,
   frozen. Point to `_legacy/README.md`.
7. A one-line pointer to `adding-a-skill.md`.

### 8.2 `skills/AGENTS.md` required rules

Replace the current five-line file with these rules, in this order:

1. Read the target skill's `SKILL.md`, README, and change protocol before
   editing that skill.
2. Catalog skills are only `korean-writing-editor` and `image-workbench`.
3. Korean proofread/correct/polish of supplied Korean text →
   `korean-writing-editor`.
4. Project-bound raster plan/generate/edit/audit → `image-workbench`.
5. Run, resume, inspect, explain, verify, review, or apply a Waygent
   execution → `waygent` CLI or `bun run waygent -- …`. Do not load
   `skills/_legacy/waygent`.
6. Do not load any path under `skills/_legacy/` unless the user explicitly
   names that path.
7. Keep skill docs, evals, and advertised commands synchronized.
8. Skills do not redefine Waygent product ownership.

### 8.3 `adding-a-skill.md` required rules

A new general skill must:

- live at `skills/<kebab-name>/` with `SKILL.md` `name` equal to `<kebab-name>`;
- use letters, numbers, and hyphens only; no `kws-` prefix;
- include `SKILL.md`, a Korean human `README.md`, `CHANGE_PROTOCOL.md`, and
  `evals/` that can fail closed offline;
- keep trigger, README, and fixtures in lockstep on contract changes;
- be added to the `skills/README.md` table and the `skills/AGENTS.md` routing
  list in the same change;
- register `scripts/agent/verification-map.ts` matchers and commands when it
  has evals;
- not host Waygent product runtime or Superpowers plan execution.

## 9. Live Pointer Rule

After the move, any **present-tense live pointer** to `skills/waygent/` or
`skills/kws-*` must be updated so the path exists and the catalog meaning
matches this spec.

Live pointers include at least:

- `AGENTS.md` task routing and Claude-executor follow-up path;
- `CLAUDE.md` start notes, sequential-runner routing, and useful checks;
- root `README.md` skill links;
- `docs/README.md` “Skill Docs” section;
- present-tense sentences in `docs/architecture/waygent.md` that name
  `skills/waygent` as an active product tree or operator entrypoint;
- present-tense eval paths in `docs/operations/waygent.md`;
- `scripts/agent/verification-map.ts` and its tests;
- `scripts/agent/check-plan-runner-parity.py`;
- `scripts/agent/plan-runner-cutover.py` and `scripts/agent/test_plan_runner_cutover.py`
  **source** paths (repo trees become `skills/_legacy/kws-…`);
- `scripts/agent/verify.test.ts` strings that encode those cwd paths.

Do not rewrite:

- `docs/superpowers/` specs and plans;
- `docs/migration/`;
- dated files under `docs/operations/` and `docs/architecture/2026-*`;
- bodies already moved into `skills/_legacy/`.

`docs/README.md` “Skill Docs” becomes: link `skills/README.md` as the catalog;
do not list runners, executors, or the Waygent skill as current skill docs.
One sentence may say deprecated execution skills live under `skills/_legacy/`
and are not the default path.

`docs/architecture/waygent.md` remains Waygent architecture. Change only the
false present-tense claims (`skills/waygent/` is part of the active product
tree; `skills/waygent` maps operator intent). Replacement: the active product
tree is `apps/`, `packages/`, `native/`, `tests/`, `docs/`; operators use the
`waygent` CLI; the former skill tree is `skills/_legacy/waygent` and is not
the catalog entrypoint. Do not relocate the NL lexicon in this change.

Root `AGENTS.md` Project Shape and task routing replacement:

- `skills/` is the source of truth for general personal skills, not Waygent
  execution or plan-runner skills.
- Waygent workflow contract: `apps/cli` and the `waygent` CLI, not a skill.
- Sequential Codex/Claude plan-runner skills and the Claude multi-agent
  executor skill are not default routing. They live under `skills/_legacy/`
  and are used only when the user names that path.
- General skills: `skills/korean-writing-editor/`,
  `skills/image-workbench/`.
- Keep the existing warning that historical `kws-cpe.*` and `kws-cme.*` event
  namespaces are not the active Waygent integration model.

`CLAUDE.md` must not tell agents to use the Claude plan-runner skill as the
default sequential path. Waygent CLI remains the product execution path. If
the user names the legacy executor tree, follow
`skills/_legacy/kws-claude-multi-agent-executor/AGENTS.md`. Keep the MAE
eval as an opt-in useful check with the `_legacy` cwd; do not present it as
default routing.

## 10. Verification Map And Legacy Tools

Retarget cwd and matchers. Do not drop offline coverage for moved trees.

| Scope id | Matcher after move |
|---|---|
| `korean-writing-editor` | `skills/korean-writing-editor/` |
| `image-workbench` | `skills/image-workbench/` |
| `waygent-skill` | `skills/_legacy/waygent/` |
| `codex-plan-runner` | `skills/_legacy/kws-codex-plan-runner/` |
| `claude-plan-runner` | `skills/_legacy/kws-claude-plan-runner/` |
| `claude-executor` | `skills/_legacy/kws-claude-multi-agent-executor/` |

`WAYGENT_SKILL_EVAL` cwd becomes `skills/_legacy/waygent`. Product Waygent
gates (`waygent:scenarios`, CLI tests, closure) stay on `apps/` and
`packages/`.

`docs` matchers must include `skills/adding-a-skill.md` and
`skills/_legacy/README.md` if those files are not already covered by
`skills/README.md` / a directory matcher. Prefer matching `skills/` catalog
markdown without pulling every legacy body into the docs-only scope: catalog
files `skills/README.md`, `skills/AGENTS.md`, `skills/adding-a-skill.md`, and
`skills/_legacy/README.md` are docs-scope. Changes under a skill tree still
select that skill's scope.

Plan-runner parity and cutover **source** paths follow `_legacy`. Cutover may
still install legacy names into a home directory; that tool is not part of
the new catalog install guide and must not be added back to `skills/README.md`.

## 11. Failure Modes

| Condition | Required behavior |
|---|---|
| `$kws-korean-writing-editor` or `/kws-korean-writing-editor` | No-op. Do not activate `korean-writing-editor`. Locked by near-miss fixtures. |
| `$kws-image-workbench` or `/kws-image-workbench` | No-op. Do not activate `image-workbench`. Locked by near-miss fixtures. |
| Waygent run/resume/verify/apply request | Use the CLI. Do not load `skills/_legacy/waygent`. |
| User does not name a `_legacy` path | Do not load legacy skills, even if they remain in the checkout. |
| Home has both `kws-*` and new names | Repository does nothing. README tells the operator to remove the old path after confirming it is the previous install. |
| Contributor adds a new executor under `skills/` root | Reject. `adding-a-skill.md` and `skills/AGENTS.md` allow general skills only. |

## 12. Migration Order

1. Update verification-map tests and related path assertions to the target
   layout so they fail on the current tree (RED).
2. `git mv` deprecated trees into `skills/_legacy/`.
3. `git mv` the two active skills to the new directory names.
4. Write `_legacy/README.md`.
5. Rename active-surface strings, versions, fixtures, and near-misses in the
   two skills.
6. Rewrite `skills/README.md`, `skills/AGENTS.md`, and add
   `skills/adding-a-skill.md`.
7. Apply the live pointer rule to root agent docs, `docs/README.md`, present
   tense architecture/operations pointers, and agent scripts.
8. Run the required verification set at the final candidate.

Do not edit `_legacy` file bodies in step 2 except as required for a script
that hard-codes its own repo-relative path *and* is itself a live verification
entry (those scripts are listed in section 10). Prefer updating the
verification wrapper's cwd over patching legacy internals. If a legacy eval
hard-codes `skills/kws-…` and breaks after the move, change only that
hard-coded path to `skills/_legacy/kws-…` and leave the rest of the file
alone.

## 13. Verification

Required offline evidence, from the repository root unless noted:

```bash
python3 skills/korean-writing-editor/evals/run.py --scope full
python3 skills/image-workbench/evals/run.py --self-test
python3 skills/image-workbench/evals/run.py --scope full
python3 skills/image-workbench/scripts/inspect_asset.py --self-test
bun test scripts/agent/verification-map.test.ts scripts/agent/verify.test.ts
bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD
git diff --check
```

If plan-runner or MAE trees moved, the verification map must select their
retargeted evals when those paths are in the diff. Run those selected
commands; do not skip them because the skills are deprecated.

Success meaning:

- Korean editor full scope: current fixture count still passes, plus the new
  old-name near-miss records.
- Image workbench full scope and inspector self-test pass.
- Verification-map unit tests pass with the new matchers.
- `agent:verify` for this change's base/head is green.
- `git diff --check` is clean.

Not claimed by the required gate:

- live model quality;
- live image generation;
- that the operator's home directory was rewritten;
- that host skill catalogs have been reloaded.

If Codex `quick_validate.py` is still listed in
`image-workbench/CHANGE_PROTOCOL.md`, retarget its path argument to
`skills/image-workbench`. If that helper is missing on the machine, report it
as skipped host tooling, not as skill-eval failure.

## 14. Files

Create:

- `skills/_legacy/README.md`
- `skills/adding-a-skill.md`

Move (git mv):

- `skills/kws-korean-writing-editor/` → `skills/korean-writing-editor/`
- `skills/kws-image-workbench/` → `skills/image-workbench/`
- `skills/kws-codex-plan-runner/` → `skills/_legacy/kws-codex-plan-runner/`
- `skills/kws-claude-plan-runner/` → `skills/_legacy/kws-claude-plan-runner/`
- `skills/kws-codex-plan-executor/` → `skills/_legacy/kws-codex-plan-executor/`
- `skills/kws-claude-plan-executor/` → `skills/_legacy/kws-claude-plan-executor/`
- `skills/kws-claude-multi-agent-executor/` → `skills/_legacy/kws-claude-multi-agent-executor/`
- `skills/waygent/` → `skills/_legacy/waygent/`

Rewrite or retarget (live surface):

- `skills/README.md`
- `skills/AGENTS.md`
- `skills/korean-writing-editor/SKILL.md`
- `skills/korean-writing-editor/README.md`
- `skills/korean-writing-editor/CHANGE_PROTOCOL.md`
- `skills/korean-writing-editor/evals/**` as needed for names and near-misses
- `skills/korean-writing-editor/references/sources.md` (skill id mention)
- `skills/image-workbench/SKILL.md`
- `skills/image-workbench/README.md`
- `skills/image-workbench/CHANGE_PROTOCOL.md`
- `skills/image-workbench/evals/**` as needed for names and near-misses
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/README.md`
- `docs/architecture/waygent.md` (present-tense product-tree sentences only)
- `docs/operations/waygent.md` (present-tense eval paths only)
- `scripts/agent/verification-map.ts`
- `scripts/agent/verification-map.test.ts`
- `scripts/agent/verify.test.ts`
- `scripts/agent/check-plan-runner-parity.py`
- `scripts/agent/plan-runner-cutover.py`
- `scripts/agent/test_plan_runner_cutover.py`

## 15. Follow-Ups (Explicitly Out Of Scope)

- Relocate Waygent NL lexicon and operator skill material into `apps/cli`.
- Remove or further archive `_legacy` trees.
- Rename historical event families.
- Unify the external `kws-skills` plugin with this catalog.
