# CPE v2.20 Context Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the useful context-management ideas from `kws-claude-multi-agent-executor` into `kws-codex-plan-executor` without changing CPE's conservative subagent safety boundary.

**Architecture:** Keep CPE state-authoritative and Codex-native. Add a spec manifest, per-task packet builder, decisions register, local environment preflight, compaction state anchors, natural-language invocation parsing, and stale-run inspection as small deterministic scripts plus explicit skill contract updates. Subagents remain opt-in through explicit user request or `subagents=on`; task packets make opt-in delegation cheaper and safer.

**Tech Stack:** Python 3 standard library, Markdown plan/spec files, JSON state under `~/.codex/orchestrator/<run_id>`, shell eval harness, existing CPE eval scripts.

---

## Scope

This plan covers the v2.20 "context intelligence" upgrade for `skills/kws-codex-plan-executor`.

Included:

- `spec_manifest` with stable section ids, line ranges, char counts, and hashes.
- `task_to_sections` mapping from plan tasks to relevant spec sections.
- `task_packets/task_<N>.json` as the compact per-task execution context.
- `decisions_register` and rendered `<run_dir>/DECISIONS.md`.
- `preflight_warnings` for missing local config and stale dependencies.
- `last_completed_task`, `last_completed_at`, and per-task `timing`.
- Natural-language invocation hints and one-line parsed echo.
- Cross-run isolation and stale active-run reporting.
- `subagents=on` task-sliced delegation guidance that uses task packets.
- Deterministic evals for all new scripts and state fields.

Excluded from v2.20:

- Default autonomous multi-agent execution. CPE keeps `subagents=auto` as non-spawning unless the user explicitly asks.
- Claude-specific runtime write hooks. Codex cannot rely on `.claude/settings.json` style write interception.
- CME `plan_chain` multi-plan execution.
- Cost ledger and budget pause behavior.
- Fully automatic resource-key scheduling. The implementation may parse `resource_key` later, but v2.20 does not schedule from it.

## File Structure

Create:

- `skills/kws-codex-plan-executor/scripts/build_spec_manifest.py` - parse a Markdown spec into stable section metadata.
- `skills/kws-codex-plan-executor/scripts/build_task_packet.py` - build compact task context from parsed plan, spec manifest, and decisions.
- `skills/kws-codex-plan-executor/scripts/preflight_local_env.py` - detect missing local config and stale dependency installs.
- `skills/kws-codex-plan-executor/scripts/parse_invocation_args.py` - deterministic `key=value` plus Korean/English natural-language argument parsing.
- `skills/kws-codex-plan-executor/scripts/inspect_runs.py` - inspect active/stale CPE runs under `~/.codex/orchestrator`.
- `skills/kws-codex-plan-executor/scripts/update_decisions_register.py` - append/supersede decisions and render `DECISIONS.md`.
- `skills/kws-codex-plan-executor/evals/check_spec_manifest.py` - deterministic tests for spec manifest generation.
- `skills/kws-codex-plan-executor/evals/check_task_packet.py` - deterministic tests for task packets and spec slicing.
- `skills/kws-codex-plan-executor/evals/check_local_env_preflight.py` - deterministic tests for preflight warnings.
- `skills/kws-codex-plan-executor/evals/check_invocation_args.py` - deterministic tests for invocation parser conflict handling.
- `skills/kws-codex-plan-executor/evals/check_inspect_runs.py` - deterministic tests for stale active-run reporting.
- `skills/kws-codex-plan-executor/evals/check_decisions_register.py` - deterministic tests for append/supersede/render behavior.
- `skills/kws-codex-plan-executor/references/context-intelligence.md` - operator-facing contract for manifests, packets, decisions, and compaction.
- `skills/kws-codex-plan-executor/references/local-env-preflight.md` - local-env warning contract and escalation usage.

Modify:

- `skills/kws-codex-plan-executor/SKILL.md` - add v2.20 invariants, args, workflow hooks, and opt-in subagent packet rules.
- `skills/kws-codex-plan-executor/HISTORY.md` - add v2.20.0 entry.
- `skills/kws-codex-plan-executor/README.md` - list the new validation commands and context artifacts.
- `skills/kws-codex-plan-executor/docs/how-it-works.md` - summarize task packet flow.
- `skills/kws-codex-plan-executor/docs/state-and-logging.md` - document new runtime artifacts.
- `skills/kws-codex-plan-executor/docs/evals-and-verification.md` - add new eval commands.
- `skills/kws-codex-plan-executor/references/context-budget.md` - update from snapshot-only to manifest/packet-aware budgeting.
- `skills/kws-codex-plan-executor/references/execution-cycle.md` - insert preflight, manifest, packet, decisions, timing, and compaction steps.
- `skills/kws-codex-plan-executor/references/headless-runner.md` - include headless bootstrap for parser and task packets.
- `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md` - require task packet and disjoint write scopes before opt-in delegation.
- `skills/kws-codex-plan-executor/references/state-schema.md` - add schema fields for v2.20.
- `skills/kws-codex-plan-executor/references/unit-context-manifest.md` - align `max_context_chars` and `context_mode` with task packets.
- `skills/kws-codex-plan-executor/scripts/build_context_snapshot.py` - include manifest summary and packet index in `context.json`.
- `skills/kws-codex-plan-executor/scripts/parse_plan.py` - extract `spec_refs` and preserve task body ranges for packet building.
- `skills/kws-codex-plan-executor/scripts/validate_state.py` - validate v2.20 state fields and completed-task timing.
- `skills/kws-codex-plan-executor/evals/run.sh` - run the new deterministic checks.
- `skills/kws-codex-plan-executor/evals/baselines/v2.20.0.json` - add after eval harness produces stable output.

## Acceptance Criteria

- `bash skills/kws-codex-plan-executor/evals/run.sh` passes from the skill directory.
- `python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py skills/kws-codex-plan-executor/evals/*.py` passes.
- Existing v2.19 behavior remains intact:
  - `subagents=auto` does not spawn by itself.
  - prompt/handoff modes are export-only.
  - execution modes still require declared `Files` blocks.
  - state and runtime artifacts remain under `~/.codex/orchestrator/<run_id>`.
- A task with explicit `**Spec Refs:**` receives only the referenced spec sections in its task packet.
- A task without matching spec refs receives a safe full-spec fallback marker, not silently incomplete context.
- Completed execution state records valid `timing`, `last_completed_task`, `last_completed_at`, `decisions_register`, and packet metadata.
- Stale active runs are reported without deleting or mutating them.

## Tasks

### Task 1: Add v2.20 Reference Documents

**Files:**

- Create: `skills/kws-codex-plan-executor/references/context-intelligence.md`
- Create: `skills/kws-codex-plan-executor/references/local-env-preflight.md`
- Modify: `skills/kws-codex-plan-executor/docs/how-it-works.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`

- [ ] **Step 1: Write context intelligence reference**

Create `references/context-intelligence.md` with these sections:

```markdown
# Context Intelligence

Context intelligence keeps the active Codex session focused on the current unit
of work. State remains authoritative; raw prior task output is disposable after
compaction points.

## Artifacts

- `context.json`: run-level source snapshot and budget summary.
- `spec_manifest.json`: spec section ids, ranges, sizes, and hashes.
- `task_packets/task_<N>.json`: compact per-task execution context.
- `DECISIONS.md`: human-readable projection of `state.decisions_register`.

## Required Flow

1. Parse invocation args and echo resolved values.
2. Parse plan.
3. Build `spec_manifest` when `spec=` is present.
4. Compute `task_to_sections`.
5. Build one task packet before each task contract.
6. Execute only from the active task packet plus declared files.
7. Append decisions discovered during the task.
8. At compaction points, write state, render `DECISIONS.md`, and drop raw prior
   task context from active reasoning.

## Spec Mapping

Explicit `**Spec Refs:**` entries win. Unknown section ids are blockers.
When no explicit refs exist, map from task files to section titles using
case-insensitive path-component matching. If no section matches, set
`fallback_used=true` and include the full spec for that task packet.

## Compaction

After a compaction point, future work may use:

- `state.tasks`
- `state.task_summaries`
- `state.decisions_register`
- `DECISIONS.md`
- changed files on disk

Future work must not rely on raw subagent output or raw previous task prompts
remaining in the active conversation.
```

- [ ] **Step 2: Write local-env preflight reference**

Create `references/local-env-preflight.md` with the warning schema from `IMPLEMENTATION.md`:

```markdown
# Local Environment Preflight

Local environment preflight is detection-only. It never copies secrets, never
installs dependencies, and never blocks execution by itself.

## Warning Kinds

- `missing_local_config`
- `dependencies_likely_stale`

## State Field

`state.preflight_warnings` is always present after preflight. It is `[]` when
the local environment looks clean.

## Escalation Use

If baseline or task verification fails with module-load, missing-config, or
dependency errors, compare the failure with `state.preflight_warnings` before
assigning root cause. A matching warning may classify the command observation as
`missing_local_env` or `dependency_bootstrap`.
```

- [ ] **Step 3: Update existing docs**

Add one paragraph to `docs/how-it-works.md` after the current summary:

```markdown
For v2.20+ runs, the executor also builds spec manifests and task packets so
the active task sees only the plan slice, spec slice, decisions, and write scope
it needs. Compaction points write durable state anchors and make prior raw task
context disposable.
```

Add these bullets to `docs/state-and-logging.md` under execution artifacts:

```markdown
- `spec_manifest.json`
- `task_packets/task_<N>.json`
- `DECISIONS.md`
- `preflight_warnings.json`
```

- [ ] **Step 4: Verify docs are linked by future tasks**

Run:

```bash
test -f skills/kws-codex-plan-executor/references/context-intelligence.md
test -f skills/kws-codex-plan-executor/references/local-env-preflight.md
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/references/context-intelligence.md \
  skills/kws-codex-plan-executor/references/local-env-preflight.md \
  skills/kws-codex-plan-executor/docs/how-it-works.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md
git commit -m "docs(cpe): describe context intelligence flow"
```

### Task 2: Implement Spec Manifest Builder

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/build_spec_manifest.py`
- Create: `skills/kws-codex-plan-executor/evals/check_spec_manifest.py`

- [ ] **Step 1: Write failing eval**

Create `evals/check_spec_manifest.py` with cases for:

- no-heading spec creates a single `S0` document section.
- heading spec creates stable ids `S1`, `S1.1`, `S2`.
- fenced headings are ignored.
- each section records `title`, `level`, `line_start`, `line_end`, `chars`, and `sha256`.
- `task_to_sections` starts as `{}`.

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_spec_manifest.py
```

Expected: FAIL because `scripts/build_spec_manifest.py` does not exist.

- [ ] **Step 2: Implement manifest CLI**

Implement `scripts/build_spec_manifest.py` with this CLI contract:

```bash
python3 scripts/build_spec_manifest.py <spec_path> \
  --output <path> \
  --fallback-policy full_spec_on_blocker
```

Stdout when `--output` is omitted must be JSON. With `--output`, write JSON and print the output path.

Required JSON shape:

```json
{
  "schema_version": "1",
  "spec_path": "spec.md",
  "spec_sha256": "<sha256>",
  "spec_total_chars": 1234,
  "fallback_policy": "full_spec_on_blocker",
  "sections": {
    "S1": {
      "id": "S1",
      "title": "Feature",
      "level": 1,
      "line_start": 1,
      "line_end": 20,
      "chars": 500,
      "sha256": "<section-sha256>"
    }
  },
  "section_order": ["S1"],
  "task_to_sections": {}
}
```

- [ ] **Step 3: Run eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_spec_manifest.py
```

Expected: PASS.

- [ ] **Step 4: Compile**

```bash
python3 -m py_compile skills/kws-codex-plan-executor/scripts/build_spec_manifest.py \
  skills/kws-codex-plan-executor/evals/check_spec_manifest.py
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/build_spec_manifest.py \
  skills/kws-codex-plan-executor/evals/check_spec_manifest.py
git commit -m "feat(cpe): build spec manifests"
```

### Task 3: Extend Plan Parser for Spec Refs and Body Ranges

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/parse_plan.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_parse_plan.py`
- Create: `skills/kws-codex-plan-executor/evals/parser-fixtures/11-spec-refs.yaml`
- Create: `skills/kws-codex-plan-executor/evals/parser-fixtures/12-spec-refs-hidden.yaml`

- [ ] **Step 1: Add parser fixtures**

Create fixture 11 with visible task metadata:

```yaml
plan: |
  ## Task 0: Add parser

  **Files:**
  - Modify: scripts/parse_plan.py

  **Spec Refs:** S1, S2.1

  **Acceptance Criteria**
  - Parser returns spec refs.
mode: interactive
expect:
  tasks:
    - id: task_0
      spec_refs: ["S1", "S2.1"]
```

Create fixture 12 with `**Spec Refs:** S9` inside a fenced code block and expected `spec_refs: []`.

- [ ] **Step 2: Update parser**

Add extraction for:

- `spec_refs`: from `Spec Refs`, `Spec refs`, `Spec references`, `스펙 참조`.
- `body_line_start`
- `body_line_end`

Keep existing hidden Markdown rules so fenced and commented refs are ignored.

- [ ] **Step 3: Run parser evals**

```bash
python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  --fixture skills/kws-codex-plan-executor/evals/parser-fixtures/11-spec-refs.yaml
python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  --fixture skills/kws-codex-plan-executor/evals/parser-fixtures/12-spec-refs-hidden.yaml
```

Expected: both PASS.

- [ ] **Step 4: Run all parser fixtures**

```bash
for f in skills/kws-codex-plan-executor/evals/parser-fixtures/*.yaml; do \
  python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py --fixture "$f"; \
done
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/parse_plan.py \
  skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  skills/kws-codex-plan-executor/evals/parser-fixtures/11-spec-refs.yaml \
  skills/kws-codex-plan-executor/evals/parser-fixtures/12-spec-refs-hidden.yaml
git commit -m "feat(cpe): parse task spec references"
```

### Task 4: Implement Task Packet Builder

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Create: `skills/kws-codex-plan-executor/evals/check_task_packet.py`

- [ ] **Step 1: Write failing eval**

Create `evals/check_task_packet.py` with three cases:

- explicit `spec_refs` maps to exact manifest sections.
- file-title heuristic maps `src/auth/session.py` to a spec section titled `Auth Session`.
- no match sets `fallback_used=true` and `section_ids=["*"]`.

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_task_packet.py
```

Expected: FAIL because `scripts/build_task_packet.py` does not exist.

- [ ] **Step 2: Implement packet CLI**

Implement:

```bash
python3 scripts/build_task_packet.py \
  --plan-json "$RUN_DIR/plan.json" \
  --task-id task_0 \
  --spec "$SPEC_REL" \
  --spec-manifest "$RUN_DIR/spec_manifest.json" \
  --decisions "$RUN_DIR/decisions_register.json" \
  --output "$RUN_DIR/task_packets/task_0.json"
```

Packet JSON must include:

```json
{
  "schema_version": "1",
  "task_id": "task_0",
  "task_title": "Add parser",
  "task_body": "<exact parsed task body>",
  "files": ["scripts/parse_plan.py"],
  "depends_on": [],
  "acceptance": {
    "has_acceptance_criteria": true,
    "command": null
  },
  "spec": {
    "mode": "slice",
    "section_ids": ["S1"],
    "section_label": "S1",
    "fallback_used": false,
    "text": "## Spec context (sections: S1)\n..."
  },
  "decisions_register": [],
  "write_policy": {
    "allowed_write_globs": ["scripts/parse_plan.py"],
    "forbidden_write_globs": [".git/**", "graphify-out/**"]
  },
  "context_budget": {
    "estimated_chars": 2345,
    "max_chars": 60000,
    "status": "green"
  }
}
```

- [ ] **Step 3: Run eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_task_packet.py
```

Expected: PASS.

- [ ] **Step 4: Compile**

```bash
python3 -m py_compile skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/evals/check_task_packet.py
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/evals/check_task_packet.py
git commit -m "feat(cpe): build compact task packets"
```

### Task 5: Add Decisions Register Helper

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/update_decisions_register.py`
- Create: `skills/kws-codex-plan-executor/evals/check_decisions_register.py`

- [ ] **Step 1: Write failing eval**

Eval cases:

- append a first decision.
- append a second decision for different files.
- supersede a prior decision by id.
- render `DECISIONS.md` with active decisions first and superseded decisions under a separate heading.

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_decisions_register.py
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 2: Implement helper**

Required append command:

```bash
python3 scripts/update_decisions_register.py append \
  --state "$STATE_PATH" \
  --task task_2 \
  --decision "Use parser-level spec refs instead of prompt regex matching." \
  --files scripts/parse_plan.py,scripts/build_task_packet.py \
  --render "$RUN_DIR/DECISIONS.md"
```

Required supersede command:

```bash
python3 scripts/update_decisions_register.py supersede \
  --state "$STATE_PATH" \
  --decision-id dec_0001 \
  --by-task task_5 \
  --reason "Task packets now own the mapping." \
  --render "$RUN_DIR/DECISIONS.md"
```

Each decision entry must include:

```json
{
  "id": "dec_0001",
  "task": "task_2",
  "decision": "Use parser-level spec refs instead of prompt regex matching.",
  "files": ["scripts/parse_plan.py", "scripts/build_task_packet.py"],
  "made_at": "2026-05-19T00:00:00Z",
  "supersedes": null,
  "superseded_by": null,
  "reason": null
}
```

- [ ] **Step 3: Run eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_decisions_register.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/update_decisions_register.py \
  skills/kws-codex-plan-executor/evals/check_decisions_register.py
git commit -m "feat(cpe): record reusable execution decisions"
```

### Task 6: Add Local Environment Preflight

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/preflight_local_env.py`
- Create: `skills/kws-codex-plan-executor/evals/check_local_env_preflight.py`

- [ ] **Step 1: Write failing eval**

Eval cases:

- `/.env.example` plus ignored missing `/.env` emits `missing_local_config`.
- `package-lock.json` newer than `node_modules/.package-lock.json` emits `dependencies_likely_stale`.
- clean repo emits `[]`.

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_local_env_preflight.py
```

Expected: FAIL because `scripts/preflight_local_env.py` does not exist.

- [ ] **Step 2: Implement preflight CLI**

Implement:

```bash
python3 scripts/preflight_local_env.py \
  --repo-root "$WORKTREE_ABS" \
  --output "$RUN_DIR/preflight_warnings.json"
```

Output shape:

```json
{
  "schema_version": "1",
  "warnings": [
    {
      "kind": "missing_local_config",
      "file": ".env",
      "template": ".env.example",
      "suggestion": "Copy .env.example to .env and fill in local values.",
      "detected_at": "2026-05-19T00:00:00Z"
    }
  ]
}
```

- [ ] **Step 3: Run eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_local_env_preflight.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/preflight_local_env.py \
  skills/kws-codex-plan-executor/evals/check_local_env_preflight.py
git commit -m "feat(cpe): detect local environment blockers"
```

### Task 7: Add Invocation Argument Parser

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/parse_invocation_args.py`
- Create: `skills/kws-codex-plan-executor/evals/check_invocation_args.py`
- Modify: `skills/kws-codex-plan-executor/SKILL.md`

- [ ] **Step 1: Write failing eval**

Eval cases:

- `plan=a.md spec=s.md 순차` resolves `parallel=off`.
- `오푸스로` resolves `implementer_model=opus` only when v2.20 accepts the optional field.
- explicit `subagents=off` plus NL `병렬` produces a conflict.
- unknown `key=value` fails with a clear error.
- echo line includes plan count, mode, subagents, context mode, and fallback policy.

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_invocation_args.py
```

Expected: FAIL because the parser does not exist.

- [ ] **Step 2: Implement parser**

Recognized keys:

```text
plan spec docs workspace resume mode subagents headless_sandbox
context_mode context_budget context_threshold manifest_fallback parallel
```

Accepted NL tokens after Korean particle stripping:

```text
대화형, interactive -> mode=interactive
헤드리스, headless -> mode=headless
프롬프트, prompt -> mode=prompt
핸드오프, handoff -> mode=handoff
병렬, parallel -> subagents=on
서브에이전트, subagents -> subagents=on
로컬, local -> subagents=off
순차, sequential, 직렬 -> parallel=off
슬라이스, sliced -> context_mode=sliced
전체, full -> context_mode=full
```

Explicit keys always win when they agree; explicit/NL contradictions halt.

- [ ] **Step 3: Update SKILL invocation section**

Add:

```markdown
- `context_mode=auto|sliced|full` optional, default `auto`; `auto` uses task packets when a spec exists.
- `context_budget=<positive-int>` optional, default `60000` per task packet.
- `context_threshold=<float>` optional, default `0.70`; values must be in `[0.05,0.95]`.
- `manifest_fallback=full_spec_on_blocker|halt_on_blocker` optional, default `full_spec_on_blocker`.
- Natural-language hints are accepted only after deterministic parser resolution; print the parsed echo line before preflight.
```

- [ ] **Step 4: Run eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_invocation_args.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/parse_invocation_args.py \
  skills/kws-codex-plan-executor/evals/check_invocation_args.py \
  skills/kws-codex-plan-executor/SKILL.md
git commit -m "feat(cpe): parse natural language invocation hints"
```

### Task 8: Add Cross-Run Isolation Inspector

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/inspect_runs.py`
- Create: `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/headless-runner.md`

- [ ] **Step 1: Write failing eval**

Eval cases:

- one active run for the same plan is reported.
- multiple active runs return `ambiguous=true`.
- stale run with missing worktree is reported as `orphaned_worktree=false`, `missing_worktree=true`.
- finished runs are ignored unless `--include-finished` is passed.

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_inspect_runs.py
```

Expected: FAIL because the inspector does not exist.

- [ ] **Step 2: Implement inspector**

Implement:

```bash
python3 scripts/inspect_runs.py \
  --codex-home "${CODEX_HOME:-$HOME/.codex}" \
  --plan "$PLAN_REL" \
  --output "$RUN_DIR/stale_runs.json"
```

The script must be read-only. It must not delete stale directories or remove worktrees.

- [ ] **Step 3: Add workflow rule**

In `references/execution-cycle.md`, insert before worktree creation:

```markdown
Run `scripts/inspect_runs.py` for the target plan. If one unambiguous active run
exists and the invocation did not request resume, stop and ask whether to resume
or start a new run. If multiple active runs exist, stop with the stale-run report.
Do not mutate stale runs automatically.
```

- [ ] **Step 4: Run eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_inspect_runs.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/inspect_runs.py \
  skills/kws-codex-plan-executor/evals/check_inspect_runs.py \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/references/headless-runner.md
git commit -m "feat(cpe): inspect active runs before execution"
```

### Task 9: Extend State Schema and Validator

**Files:**

- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`

- [ ] **Step 1: Add failing state-schema evals**

Add cases that fail until validator supports:

- `spec_manifest_path`
- `task_packet_dir`
- `current_task_packet_path`
- `decisions_register`
- `preflight_warnings`
- `last_completed_task`
- `last_completed_at`
- per-task `timing.started`, `timing.completed`
- `compaction.last_compaction_after_task`

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
```

Expected: FAIL with missing validator support.

- [ ] **Step 2: Update state schema docs**

Add this state shape:

```json
{
  "spec_manifest_path": "<run_dir>/spec_manifest.json",
  "task_packet_dir": "<run_dir>/task_packets",
  "current_task_packet_path": "<run_dir>/task_packets/task_0.json",
  "decisions_register": [],
  "preflight_warnings": [],
  "last_completed_task": null,
  "last_completed_at": null,
  "compaction": {
    "points": [],
    "last_compaction_after_task": null,
    "context_drop_count": 0
  }
}
```

- [ ] **Step 3: Update validator**

Rules:

- If `spec_manifest_path` is present, it must equal `run_dir/spec_manifest.json`.
- If `task_packet_dir` is present, it must equal `run_dir/task_packets`.
- If `current_task_packet_path` is present, it must live under `task_packet_dir`.
- `decisions_register` must be a list of valid decision objects.
- `preflight_warnings` must be a list of valid warning objects.
- Completed tasks in finished runs must have `timing.started` and `timing.completed`.
- `last_completed_task` must either be null or a key in `tasks`.

- [ ] **Step 4: Run state eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py
git commit -m "feat(cpe): validate context intelligence state"
```

### Task 10: Integrate Context Snapshot and Execution Cycle

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/build_context_snapshot.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_context_snapshot.py`
- Modify: `skills/kws-codex-plan-executor/references/context-budget.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/unit-context-manifest.md`

- [ ] **Step 1: Add failing context snapshot eval**

Add a fixture that passes `--spec-manifest` and `--task-packet-dir` and expects:

```json
{
  "context_budget": {
    "active_strategy": "task_packet",
    "packet_count": 2
  }
}
```

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_context_snapshot.py
```

Expected: FAIL until snapshot builder accepts the new inputs.

- [ ] **Step 2: Update snapshot builder**

Add optional CLI args:

```bash
--spec-manifest "$RUN_DIR/spec_manifest.json"
--task-packet-dir "$RUN_DIR/task_packets"
```

Do not inline all packet text into `context.json`. Store packet index records:

```json
{
  "task_id": "task_0",
  "path": "<run_dir>/task_packets/task_0.json",
  "sha256": "<packet-sha256>",
  "estimated_chars": 4567
}
```

- [ ] **Step 3: Update references**

Document that per-task `unit_manifest.max_context_chars` should match the packet builder's `--max-chars`, default `60000`.

- [ ] **Step 4: Run eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_context_snapshot.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/build_context_snapshot.py \
  skills/kws-codex-plan-executor/evals/check_context_snapshot.py \
  skills/kws-codex-plan-executor/references/context-budget.md \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/references/unit-context-manifest.md
git commit -m "feat(cpe): index task packets in context snapshots"
```

### Task 11: Add Opt-In Subagent Packet Dispatch Contract

**Files:**

- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/references/subagent-run-store.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_skill_contract.py`

- [ ] **Step 1: Add failing contract eval**

Extend `check_skill_contract.py` to require:

- `subagents=auto` does not spawn without explicit user request.
- `subagents=on` requires a task packet before dispatch.
- Delegated subagents receive only packet path, task id, write scope, state path, and verification expectation.
- Main agent must review post-diff and state before accepting subagent output.

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py \
  --skill skills/kws-codex-plan-executor/SKILL.md
```

Expected: FAIL until skill text includes the contract.

- [ ] **Step 2: Update dispatch reference**

Replace the pre-dispatch pipeline with:

```markdown
Before delegating work:

1. Confirm explicit user request or `subagents=on`.
2. Confirm `current_task_packet_path` exists and is readable.
3. Confirm declared files are non-empty.
4. Confirm dirty files do not overlap the task.
5. Confirm state is writable.
6. Assign a disjoint write scope equal to or narrower than packet `write_policy.allowed_write_globs`.
7. Tell the worker it is not alone in the codebase and must not revert edits made by others.
8. Record the delegation in `subagent_runs`.
9. After completion, run `scripts/check_run_diffs.py` and review changed files before marking accepted.
```

- [ ] **Step 3: Update SKILL hard boundary**

Keep the existing `spawn_agent` restriction and add:

```markdown
When subagents are permitted, dispatch from task packets, not raw full-plan
context. Do not ask a subagent to infer its write scope from the entire plan.
```

- [ ] **Step 4: Run contract eval**

```bash
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py \
  --skill skills/kws-codex-plan-executor/SKILL.md
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/references/subagent-run-store.md \
  skills/kws-codex-plan-executor/evals/check_skill_contract.py
git commit -m "feat(cpe): constrain opt-in subagents to task packets"
```

### Task 12: Update Headless Runner and Evals

**Files:**

- Modify: `skills/kws-codex-plan-executor/references/headless-runner.md`
- Modify: `skills/kws-codex-plan-executor/templates/headless-output-schema.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_headless_result.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`

- [ ] **Step 1: Add headless result expectations**

Headless final output should include:

```json
{
  "context_artifacts": {
    "spec_manifest_path": "string|null",
    "task_packet_dir": "string|null",
    "decisions_path": "string|null"
  }
}
```

Update `check_headless_result.py` first and confirm it fails against the old schema.

- [ ] **Step 2: Update runner docs and schema**

Document that headless mode must:

- parse invocation args once.
- create worktree and run dir.
- run local-env preflight.
- write `plan.json`.
- build `spec_manifest.json` when spec exists.
- build task packets before task execution.
- avoid nested `codex exec`.

- [ ] **Step 3: Update eval harness**

Add these checks to `evals/run.sh`:

```bash
python3 "$EVAL_DIR/check_spec_manifest.py" >/dev/null
python3 "$EVAL_DIR/check_task_packet.py" >/dev/null
python3 "$EVAL_DIR/check_local_env_preflight.py" >/dev/null
python3 "$EVAL_DIR/check_invocation_args.py" >/dev/null
python3 "$EVAL_DIR/check_inspect_runs.py" >/dev/null
python3 "$EVAL_DIR/check_decisions_register.py" >/dev/null
```

- [ ] **Step 4: Run full static checks**

```bash
python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py \
  skills/kws-codex-plan-executor/evals/*.py
bash -n skills/kws-codex-plan-executor/evals/run.sh
```

Expected: no output.

- [ ] **Step 5: Run full eval harness**

```bash
cd skills/kws-codex-plan-executor
bash evals/run.sh
```

Expected: PASS and updated `evals/baselines/v2.20.0.json`.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/references/headless-runner.md \
  skills/kws-codex-plan-executor/templates/headless-output-schema.json \
  skills/kws-codex-plan-executor/evals/check_headless_result.py \
  skills/kws-codex-plan-executor/evals/run.sh \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/evals/baselines/v2.20.0.json
git commit -m "chore(cpe): wire v2.20 context intelligence evals"
```

## Final Verification

Run from repository root:

```bash
python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py \
  skills/kws-codex-plan-executor/evals/*.py
bash -n skills/kws-codex-plan-executor/evals/run.sh
cd skills/kws-codex-plan-executor && bash evals/run.sh
```

Expected:

- Python compile succeeds.
- Shell syntax check succeeds.
- Deterministic eval harness succeeds.
- No v2.19 regression in subagent default behavior.

## Rollout Notes

Ship as `2.20.0` because this adds visible invocation args, state fields, runtime artifacts, and eval coverage. Keep `subagents=auto` conservative. If future data shows task packets are stable, a later version can consider richer opt-in parallel groups, but v2.20 should not import CME's default autonomous multi-agent loop.
