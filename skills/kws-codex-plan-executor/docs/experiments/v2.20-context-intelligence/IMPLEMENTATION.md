# CPE v2.20 Context Intelligence Implementation Spec

## Summary

v2.20 makes `kws-codex-plan-executor` use less main-agent context by replacing broad plan/spec carryover with structured, durable, per-task context artifacts.

The design intentionally does not make CPE a default autonomous multi-agent executor. Codex can use subagents, but CPE must keep the v2.19 safety boundary: subagents are permitted only when the user explicitly asks for delegation/parallel work or passes `subagents=on`.

## Design Principles

- State is authoritative. Conversation context is a cache.
- Per-task packets are the only rich context that a task or opt-in subagent should need.
- Raw prior task prompts, raw prior subagent outputs, and raw reviewer transcripts are disposable after compaction.
- Missing spec context is a blocker or full-spec fallback, never a silent omission.
- Local environment preflight warns and classifies; it never mutates local config or installs dependencies.
- CPE uses post-diff validation and state checks for write safety because Codex skills cannot enforce every low-level write with runtime hooks.

## Runtime Flow

### New Run

1. Parse invocation args with `scripts/parse_invocation_args.py`.
2. Print the parsed echo line.
3. Inspect existing runs with `scripts/inspect_runs.py`.
4. Create the isolated worktree under `~/.codex/worktrees/<run_id>`.
5. Create the orchestrator directory under `~/.codex/orchestrator/<run_id>`.
6. Parse the plan with `scripts/parse_plan.py --output "$RUN_DIR/plan.json"`.
7. Run `scripts/preflight_local_env.py` and record warnings.
8. Build `spec_manifest.json` when `spec=` is present.
9. Build `context.json`, including manifest summary and task packet index.
10. For each executable task:
    1. Build `task_packets/task_<N>.json`.
    2. Record `current_task_packet_path`.
    3. State the 5-line task execution contract.
    4. Execute locally or dispatch opt-in subagent from the packet.
    5. Record timing, decisions, verification, summaries, and diffs.
    6. Run drift reconciliation and state validation.
11. At compaction points, write a state anchor, render `DECISIONS.md`, and drop raw prior task context.

### Resume

Resume uses `state.json` as source of truth. The executor must re-read:

- `state.current_task`
- `state.current_task_packet_path`
- `state.spec_manifest_path`
- `state.decisions_register`
- `state.compaction`
- `state.context_health`

If `current_task_packet_path` is missing for an incomplete task, rebuild the packet from `plan.json`, `spec_manifest.json`, and current decisions before continuing.

## Invocation Args

Existing args remain valid:

```text
plan spec docs workspace resume mode subagents headless_sandbox
```

Add:

```text
context_mode=auto|sliced|full
context_budget=<positive-int>
context_threshold=<float>
manifest_fallback=full_spec_on_blocker|halt_on_blocker
parallel=off
```

Defaults:

```json
{
  "context_mode": "auto",
  "context_budget": 60000,
  "context_threshold": 0.70,
  "manifest_fallback": "full_spec_on_blocker",
  "parallel": "auto"
}
```

Natural-language hints are parsed by `scripts/parse_invocation_args.py` after stripping common Korean particles.

| Token | Resolved value |
| --- | --- |
| `대화형`, `interactive` | `mode=interactive` |
| `헤드리스`, `headless` | `mode=headless` |
| `프롬프트`, `prompt` | `mode=prompt` |
| `핸드오프`, `handoff` | `mode=handoff` |
| `병렬`, `parallel`, `서브에이전트`, `subagents` | `subagents=on` |
| `로컬`, `local` | `subagents=off` |
| `순차`, `sequential`, `직렬` | `parallel=off` |
| `슬라이스`, `sliced` | `context_mode=sliced` |
| `전체`, `full` | `context_mode=full` |

Conflict rule:

- explicit `key=value` wins only if NL agrees.
- explicit/NL disagreement halts.
- two NL tokens that resolve the same key differently halt.

Echo format:

```text
Parsed: 1 plan [<plan-slug>], mode=<value> [from <source>], subagents=<value> [from <source>], context_mode=<value> [from <source>], context_budget=<int>, manifest_fallback=<value>, parallel=<value>.
```

## State Schema Additions

Top-level fields:

```json
{
  "spec_manifest_path": "<run_dir>/spec_manifest.json",
  "task_packet_dir": "<run_dir>/task_packets",
  "current_task_packet_path": "<run_dir>/task_packets/task_0.json",
  "preflight_warnings": [],
  "decisions_register": [],
  "last_completed_task": null,
  "last_completed_at": null,
  "compaction": {
    "points": [],
    "last_compaction_after_task": null,
    "context_drop_count": 0
  }
}
```

Task fields:

```json
{
  "task_0": {
    "status": "pending",
    "risk": "low",
    "files_declared": ["scripts/parse_plan.py"],
    "contract": {},
    "unit_manifest": {},
    "review_retries": 0,
    "verifier_retries": 0,
    "task_packet_path": "<run_dir>/task_packets/task_0.json",
    "task_packet_sha256": "<sha256>",
    "spec_section_ids": ["S1"],
    "fallback_spec_used": false,
    "timing": {
      "started": null,
      "completed": null,
      "verified": null
    }
  }
}
```

Decision object:

```json
{
  "id": "dec_0001",
  "task": "task_0",
  "decision": "Use parser-level spec refs instead of prompt regex matching.",
  "files": ["scripts/parse_plan.py"],
  "made_at": "2026-05-19T00:00:00Z",
  "supersedes": null,
  "superseded_by": null,
  "reason": null
}
```

Preflight warning object:

```json
{
  "kind": "dependencies_likely_stale",
  "manifest": "package.json",
  "lockfile": "package-lock.json",
  "suggestion": "Run install before baseline, for example `npm install`.",
  "detected_at": "2026-05-19T00:00:00Z"
}
```

## Runtime Artifacts

All paths below are under `~/.codex/orchestrator/<run_id>/`.

```text
state.json
context.json
plan.json
spec_manifest.json
task_packets/
  task_0.json
  task_1.json
preflight_warnings.json
DECISIONS.md
stale_runs.json
learning_events/
```

No v2.20 runtime artifact belongs inside the source worktree except normal code changes made by the plan.

## Script Specs

### `build_spec_manifest.py`

Purpose: parse a Markdown spec into stable sections.

CLI:

```bash
python3 scripts/build_spec_manifest.py <spec_path> \
  --output "$RUN_DIR/spec_manifest.json" \
  --fallback-policy full_spec_on_blocker
```

Rules:

- Ignore headings inside fenced code, HTML comments, and indented code blocks.
- If the spec has no visible headings, create one section `S0` titled `document`.
- Heading ids are hierarchical by visible heading nesting:
  - `# A` -> `S1`
  - `## B` under `S1` -> `S1.1`
  - next `# C` -> `S2`
- Each section range includes its heading line through the line before the next same-or-higher-level heading.
- `line_start` and `line_end` are 1-based inclusive.
- `chars` counts the exact section text length.
- `sha256` hashes the exact section text as UTF-8.

Errors:

- unreadable spec exits nonzero with `error: spec is not readable: <path>`.
- invalid fallback policy exits nonzero.

### `parse_plan.py` Extensions

Add fields to each parsed task:

```json
{
  "spec_refs": ["S1", "S2.1"],
  "body_line_start": 10,
  "body_line_end": 42
}
```

Visible metadata aliases:

```text
Spec Refs
Spec refs
Spec references
스펙 참조
```

The parser must keep hidden Markdown blanking before extracting spec refs.

### `build_task_packet.py`

Purpose: create the smallest safe per-task context object.

CLI:

```bash
python3 scripts/build_task_packet.py \
  --plan-json "$RUN_DIR/plan.json" \
  --task-id task_0 \
  --spec "$SPEC_REL" \
  --spec-manifest "$RUN_DIR/spec_manifest.json" \
  --decisions "$RUN_DIR/decisions_register.json" \
  --max-chars 60000 \
  --output "$RUN_DIR/task_packets/task_0.json"
```

Spec mapping algorithm:

1. If task has explicit `spec_refs`, validate all ids exist in `spec_manifest.sections`.
2. If any explicit id is unknown, exit nonzero with `error: unknown spec ref for task_0: S9`.
3. If no explicit refs, compare lowercased task file path components with lowercased section titles.
4. If matches exist, use matched section ids in manifest order.
5. If no matches exist:
   - `manifest_fallback=full_spec_on_blocker`: set `section_ids=["*"]`, `fallback_used=true`, and include the full spec text.
   - `manifest_fallback=halt_on_blocker`: exit nonzero with `error: no spec section mapping for task_0`.

Packet budget status:

```text
green: estimated_chars <= max_chars * context_threshold
yellow: estimated_chars <= max_chars
red: estimated_chars > max_chars
```

The task packet may be red. A red packet is a context-health warning unless it omitted required source; required source omission is a blocker.

### `update_decisions_register.py`

Purpose: keep durable decisions out of raw conversation context.

Commands:

```bash
python3 scripts/update_decisions_register.py append --state "$STATE_PATH" \
  --task task_0 --decision "<sentence>" --files a.py,b.py --render "$RUN_DIR/DECISIONS.md"

python3 scripts/update_decisions_register.py supersede --state "$STATE_PATH" \
  --decision-id dec_0001 --by-task task_3 --reason "<sentence>" --render "$RUN_DIR/DECISIONS.md"
```

Rendering:

- active decisions first.
- superseded decisions under `## Superseded`.
- columns: `ID`, `Task`, `Decision`, `Files`, `Made at`, `Superseded by`, `Reason`.
- empty register renders `# Decisions register (empty)`.

### `preflight_local_env.py`

Purpose: detect likely local setup blockers.

CLI:

```bash
python3 scripts/preflight_local_env.py --repo-root "$WORKTREE_ABS" \
  --output "$RUN_DIR/preflight_warnings.json"
```

Detection:

- Missing local config:
  - find templates up to depth 3 matching `*.example`, `*.template`, `*.dist`.
  - compute counterpart by removing that suffix.
  - warn only if counterpart is missing and ignored by git.
- Stale dependencies:
  - `package.json` plus lockfile newer than `node_modules/.package-lock.json`.
  - `pyproject.toml` plus `poetry.lock` or `uv.lock` newer than `.venv/pyvenv.cfg` or `venv/pyvenv.cfg`.
  - `Cargo.toml` plus `Cargo.lock` newer than `target/.rustc_info.json`.
  - Gradle build files plus wrapper newer than `.gradle/` marker or `build/`.

This script must never run install commands.

### `parse_invocation_args.py`

Purpose: make CPE argument interpretation deterministic and visible.

CLI:

```bash
python3 scripts/parse_invocation_args.py --args 'plan=p.md spec=s.md 병렬 슬라이스'
```

Output:

```json
{
  "values": {
    "plan": "p.md",
    "spec": "s.md",
    "subagents": "on",
    "context_mode": "sliced"
  },
  "sources": {
    "subagents": "NL '병렬'",
    "context_mode": "NL '슬라이스'"
  },
  "echo": "Parsed: 1 plan [p], mode=interactive [from default], subagents=on [from NL '병렬'], context_mode=sliced [from NL '슬라이스'], context_budget=60000, manifest_fallback=full_spec_on_blocker, parallel=auto."
}
```

### `inspect_runs.py`

Purpose: report ambiguous or stale active runs before starting new work.

CLI:

```bash
python3 scripts/inspect_runs.py --codex-home "$HOME/.codex" --plan "$PLAN_REL" \
  --output "$RUN_DIR/stale_runs.json"
```

Read-only report:

```json
{
  "schema_version": "1",
  "plan": "docs/plan.md",
  "active_runs": [
    {
      "run_id": "plan-20260519-120000",
      "state_path": "~/.codex/orchestrator/plan-20260519-120000/state.json",
      "worktree": "~/.codex/worktrees/plan-20260519-120000",
      "current_task": "task_2",
      "lifecycle_outcome": null,
      "missing_worktree": false,
      "state_mtime": "2026-05-19T12:05:00Z"
    }
  ],
  "ambiguous": false
}
```

The script must not delete or repair runs.

## Skill Contract Updates

### `SKILL.md`

Add to invocation:

```markdown
- `context_mode=auto|sliced|full` optional, default `auto`.
- `context_budget=<positive-int>` optional, default `60000`.
- `context_threshold=<float>` optional, default `0.70`.
- `manifest_fallback=full_spec_on_blocker|halt_on_blocker` optional, default `full_spec_on_blocker`.
- Natural-language hints are resolved by the deterministic parser; print the parsed echo line before run setup.
```

Add to hard boundary:

```markdown
When subagents are permitted, dispatch from task packets, not raw full-plan
context. The main agent remains responsible for post-diff review, state
validation, and accepting or rejecting delegated output.
```

Add to core invariants:

```markdown
- Execution runs with `spec=` build `spec_manifest.json` before task execution.
- Every executable task builds and records `task_packets/task_<N>.json` before
  the 5-line task execution contract.
- Completed tasks record `timing.started`, `timing.completed`,
  `task_packet_path`, and `task_packet_sha256`.
- Compaction points render `DECISIONS.md` and make prior raw task context
  disposable; future tasks use state, summaries, decisions, and files on disk.
```

### `execution-cycle.md`

Insert phases:

1. argument parse and echo.
2. stale-run inspection.
3. local-env preflight.
4. plan parse to `plan.json`.
5. spec manifest build.
6. task packet build per task.
7. decisions append after task.
8. compaction anchor and context drop.

### `pre-dispatch-pipeline.md`

Delegation gates:

1. explicit user request or `subagents=on`.
2. readable current task packet.
3. declared files and non-overlapping dirty files.
4. writable state.
5. disjoint write scope no broader than packet write policy.
6. recorded `subagent_runs` entry.
7. post-diff and state review by main agent before acceptance.

## Context Health Changes

Add context-health fields:

```json
{
  "packet_present": true,
  "packet_budget_status": "green",
  "spec_manifest_present": true,
  "decisions_register_present": true,
  "compaction_anchor_current": true
}
```

Finished runs must not have:

- missing packet for a completed task.
- red packet status caused by required-source omission.
- unrendered decisions when `decisions_register` is non-empty.

## Subagent Behavior

`subagents=auto`:

- no spawning unless the user's message explicitly asks for subagents, delegation, or parallel work.

`subagents=off`:

- no spawning.

`subagents=on`:

- subagents may be used.
- each worker receives:
  - task id.
  - task packet path.
  - state path.
  - allowed write globs.
  - forbidden write globs.
  - acceptance command.
  - instruction that it is not alone in the codebase and must not revert others' edits.
- the main agent reviews the result and runs `scripts/check_run_diffs.py` before accepting.

CPE must not copy CME's always-on implementer/reviewer/verifier loop in v2.20.

## Eval Coverage

Add these deterministic checks to `evals/run.sh`:

```bash
python3 "$EVAL_DIR/check_spec_manifest.py" >/dev/null
python3 "$EVAL_DIR/check_task_packet.py" >/dev/null
python3 "$EVAL_DIR/check_local_env_preflight.py" >/dev/null
python3 "$EVAL_DIR/check_invocation_args.py" >/dev/null
python3 "$EVAL_DIR/check_inspect_runs.py" >/dev/null
python3 "$EVAL_DIR/check_decisions_register.py" >/dev/null
```

Existing checks that must be updated:

- `check_context_snapshot.py`
- `check_state_schema.py`
- `check_skill_contract.py`
- `check_headless_result.py`
- `check_parse_plan.py`

## Verification Matrix

| Area | Command | Expected |
| --- | --- | --- |
| Python syntax | `python3 -m py_compile scripts/*.py evals/*.py` | exit 0 |
| Shell syntax | `bash -n evals/run.sh` | exit 0 |
| Spec manifest | `python3 evals/check_spec_manifest.py` | PASS |
| Task packet | `python3 evals/check_task_packet.py` | PASS |
| Preflight | `python3 evals/check_local_env_preflight.py` | PASS |
| Invocation args | `python3 evals/check_invocation_args.py` | PASS |
| Run inspector | `python3 evals/check_inspect_runs.py` | PASS |
| Decisions | `python3 evals/check_decisions_register.py` | PASS |
| Full harness | `bash evals/run.sh` | PASS |

## Migration and Compatibility

Existing state files without v2.20 fields remain resumable if:

- `lifecycle_outcome` is not `finished`.
- missing `spec_manifest_path` can be rebuilt from `spec`.
- missing task packets can be rebuilt from `plan.json` or reparsed plan.

Finished v2.19 state files should not be rewritten. `validate_state.py` should validate v2.19 fields normally unless v2.20 fields are present or the skill version is `2.20.0+`.

## Risks

Risk: spec slicing omits needed context.

Mitigation: explicit refs win, unknown refs block, unmatched tasks can full-spec fallback.

Risk: decisions register becomes stale.

Mitigation: allow supersede records and render superseded decisions separately.

Risk: local-env warnings become noisy.

Mitigation: preflight is detection-only, never blocking, and only influences root-cause classification when command evidence matches.

Risk: subagents over-edit from insufficient context.

Mitigation: dispatch only from task packets with narrow write globs, then require post-diff validation before acceptance.

Risk: too much new state makes resumes brittle.

Mitigation: every generated artifact is rebuildable from plan, spec, state, and repository files; validator checks paths but does not require generated files for prompt/handoff modes.

## Release Checklist

- Bump `SKILL.md` metadata version to `2.20.0`.
- Add `HISTORY.md` entry dated `2026-05-19`.
- Update README validation list.
- Run static checks.
- Run full eval harness.
- Confirm `subagents=auto` remains non-spawning by contract text and eval.
- Confirm `graphify update .` is run if implementation changes code files in this repository session.
