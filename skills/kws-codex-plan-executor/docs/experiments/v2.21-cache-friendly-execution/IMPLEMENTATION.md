# CPE v2.21 Cache-Friendly Execution Implementation Spec

## Summary

v2.21 makes `kws-codex-plan-executor` cheaper and more predictable in long
Codex sessions by keeping stable prompt content stable, moving dynamic run data
to task-local payloads, and adding deterministic checks that prevent cache-hostile
regressions.

This is a Codex-native port of the useful lessons from
`kws-claude-multi-agent-executor` cache work. It does not copy Claude-specific
`claude -p`, Anthropic `cache_control`, or 1-hour TTL behavior into Codex. Codex
keeps `mode=interactive` as the default because that is already the cache-warm
path for attended runs. `mode=headless` remains available when isolation or
fresh-session replay matters more than cache reuse.

## Problem Statement

The current CPE v2.20 design already avoids full-plan delegation by using
spec manifests, task packets, and context snapshots. It still leaves three
cache-risk surfaces:

1. Prompt templates do not explicitly separate stable system-prefix material
   from per-run or per-task dynamic material.
2. Headless and fresh-session prompts duplicate runtime-specific data in places
   that may become early-prefix drift.
3. Eval coverage proves correctness, but does not measure whether changes make
   prompts larger, less stable, or harder to cache.

The goal is to make the contract explicit enough that future prompt edits can be
reviewed mechanically before they become recurring runtime cost.

## Cache Model Used By This Spec

The implementation treats prompt caching as a prefix-stability problem:

- Stable prefix: instructions, output schemas, safety boundaries, mode contracts,
  and role-invariant guidance that should remain byte-identical across runs and
  dispatches of the same kind.
- Hot tail: plan paths, run ids, timestamps, git status, task text, spec slices,
  changed files, decisions, verification output, and any other per-run or
  per-task data.
- Cache-hostile drift: a dynamic value inserted before stable content, causing
  everything after it to become a different prefix.

Codex may or may not expose provider-level cache token counters in every runtime.
Therefore v2.21 records two classes of evidence:

- deterministic proxy evidence: stable-prefix hashes, byte counts, dynamic-token
  placement checks, and fixture prompt-size deltas.
- runtime evidence when available: input, cached-read, cached-write, and output
  token counters captured from Codex metadata or local logs without blocking
  execution when unavailable.

## Design Principles

- Keep `mode=interactive` as the default. It is already the attended,
  append-only, cache-friendlier mode in CPE.
- Do not add auto fan-out. `subagents=on` remains task-packet scoped and parent
  reviewed; `subagents=auto` still requires an explicit delegation or parallel
  request.
- Move dynamic content to user/task payloads, never earlier than stable role
  instructions and output schemas.
- Keep prompt templates useful as human-readable contracts. Do not over-optimize
  by hiding essential behavior in scripts.
- Prefer deterministic local evals over provider-specific billing assumptions.
- Treat real cache-token accounting as optional telemetry, not a correctness
  gate.

## Scope

Included:

- A cache strategy reference for CPE.
- Prompt-boundary annotations for templates and references that generate
  execution, headless, verifier, or handoff prompts.
- A prompt audit script that reports stable-prefix hashes, byte counts, dynamic
  markers before the boundary, and fixture deltas.
- A small runtime telemetry schema for cache-token observations when Codex
  exposes them.
- State schema and validation additions for optional cache metrics.
- README and history links to the new experiment.

Excluded:

- Changing the default from `mode=interactive`.
- Adding provider-specific cache controls unless Codex exposes a stable public
  API for them.
- Replacing task packets or context snapshots.
- Adding budget pause behavior. Cost limits are a separate product decision.
- Dispatching subagents solely for cache locality.

## Risk Closure Matrix

| Risk | Closure |
| --- | --- |
| Provider cache counters may not be exposed by Codex. | Cache counters are optional telemetry. Deterministic prompt-boundary audit is the required gate, and missing counters are recorded as `null`, not treated as zero savings. |
| Headless mode could be mistaken for the cache-optimal path. | `mode=interactive` remains the default. Headless docs explicitly describe it as replay-oriented and explicit, not cache-optimal. |
| Dynamic run data could drift into the stable prefix over time. | `audit_prompt_cache.py` rejects dynamic markers inside stable-prefix blocks and is wired into `evals/run.sh` and the finished-state gate. |
| Prompt audit could pass while actual provider cost regresses. | The audit records stable-prefix byte counts and hashes, so baseline growth is visible. Real token metrics may be appended when available, but correctness does not depend on provider billing fields. |
| Moving content behind cache boundaries could hide required instructions from workers. | Invariant role, safety, required-skill, and output-schema text stays in the stable prefix; task-specific inputs move to the hot tail. Prompt fixture tests continue to validate exported and execution prompts. |
| The plan could accidentally introduce new auto fan-out. | Scope excludes fan-out changes. `subagents=on` remains task-packet scoped and parent-reviewed; `subagents=auto` still requires explicit delegation intent. |
| Pre-v2.21 run state could fail validation after the schema expands. | New cache fields are optional. Validator changes must accept states without `cache_strategy`, `cache_observations`, or `prompt_audit`. |

No known runtime blocker remains open in this design. Provider-level cache TTL is
deliberately out of scope until Codex exposes a stable public API for it.

## Runtime Flow

### Interactive Execution

1. Parse invocation args with the existing deterministic parser.
2. Preserve `mode=interactive` unless the user explicitly requested a different
   mode.
3. Build `context.json`, `spec_manifest.json`, and task packets as in v2.20.
4. For each task, construct prompts in two conceptual segments:
   - stable prefix: role, safety boundary, required skills, output schema,
     invariant checklist.
   - hot tail: run config, task packet, decisions, changed files, verification
     evidence, retry context.
5. Record optional cache metrics in `state.cache_observations` when available.
6. Run prompt audit checks before reporting a finished lifecycle outcome.

### Headless Execution

Headless mode remains supported for fresh-session replay, but it is not described
as the cache-optimal path. The headless prompt must:

- start with a small stable bootstrap block.
- place run-specific paths, sandbox mode, task packet paths, and state paths
  after the stable bootstrap.
- avoid embedding timestamps or git status before the stable bootstrap.
- still include the existing skill bootstrap requirements for implementation
  work.

### Prompt And Handoff Export

Prompt and handoff modes remain export-only. They should benefit from the same
template boundary annotations, but they do not create state, cache observations,
or orchestrator artifacts.

## Prompt Boundary Contract

Prompt-generating artifacts may use these comments:

```text
<!-- CPE_CACHE_STABLE_PREFIX_START -->
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
```

Rules:

- Each checked prompt template has exactly one stable-prefix start and end.
- The hot tail begins after the stable-prefix end.
- Placeholder-like dynamic tokens are forbidden inside the stable prefix unless
  explicitly allowlisted.
- Stable-prefix content must not contain current time, git status, run id,
  absolute home paths, task packet paths, state paths, diff text, spec excerpts,
  or decisions.
- Output schemas and invariant checklists should live in the stable prefix.

Initial allowlist for stable-prefix placeholders:

- `{{STATIC_SKILL_NAME}}`
- `{{STATIC_OUTPUT_SCHEMA_NAME}}`

All existing `{{...}}` tokens in `templates/fresh-session-prompt.txt` are dynamic
unless moved behind the stable-prefix end marker.

## State Schema Additions

Top-level optional fields:

```json
{
  "cache_strategy": {
    "mode": "interactive-default",
    "stable_prefix_policy": "static-first-hot-tail",
    "provider_cache_control": "unavailable",
    "prompt_audit_version": "1"
  },
  "cache_observations": [
    {
      "observed_at": "2026-05-31T00:00:00Z",
      "source": "codex-metadata",
      "unit": "task_0",
      "mode": "interactive",
      "model": "unknown",
      "input_tokens": 0,
      "cached_read_tokens": null,
      "cached_write_tokens": null,
      "output_tokens": 0,
      "notes": "provider did not expose cache counters"
    }
  ],
  "prompt_audit": {
    "last_checked_at": "2026-05-31T00:00:00Z",
    "stable_prefix_hashes": {
      "fresh-session-prompt": "sha256"
    },
    "stable_prefix_bytes": {
      "fresh-session-prompt": 1234
    },
    "dynamic_marker_violations": []
  }
}
```

Validation rules:

- `cache_strategy` is optional for pre-v2.21 states.
- If present, `cache_strategy.mode` must be one of
  `interactive-default`, `headless-explicit`, `prompt-export`, or
  `handoff-export`.
- `provider_cache_control` must be `unavailable`, `available-unused`,
  `available-enabled`, or `unknown`.
- `cache_observations` is optional. If present, it must be a list.
- Token fields may be integers or null when unavailable.
- `prompt_audit.dynamic_marker_violations` must be an empty list before
  `lifecycle_outcome=finished`.

## Script Specs

### `scripts/audit_prompt_cache.py`

Purpose: statically audit prompt templates and generated fixture prompts for
cache-friendly boundaries.

CLI:

```bash
python3 scripts/audit_prompt_cache.py \
  --skill-root skills/kws-codex-plan-executor \
  --output /tmp/cpe-cache-audit.json
```

Inputs:

- `templates/fresh-session-prompt.txt`
- `references/headless-runner.md`
- `references/verifier-prompt.md`
- `references/prompt-export-checklist.md`
- generated fixture prompts under an optional `--fixture-output-dir`

Output:

```json
{
  "schema_version": "1",
  "templates": [
    {
      "id": "fresh-session-prompt",
      "path": "templates/fresh-session-prompt.txt",
      "stable_prefix_sha256": "sha256",
      "stable_prefix_bytes": 1234,
      "hot_tail_bytes": 5678,
      "dynamic_marker_violations": [],
      "missing_markers": []
    }
  ],
  "passed": true
}
```

Dynamic marker detection:

- `{{...}}`
- `<run_id>`
- `<state_path>`
- `<task_packet`
- `git status`
- `date`
- `timestamp`
- absolute `/Users/` paths

The script exits nonzero when:

- a checked template is missing stable-prefix markers.
- the end marker appears before the start marker.
- dynamic markers appear inside the stable prefix.
- a stable-prefix byte count increases by more than the configured threshold
  against a baseline file.

### `evals/check_prompt_cache_audit.py`

Purpose: deterministic tests for `audit_prompt_cache.py`.

Required cases:

- a valid template with dynamic content only after the boundary passes.
- a template with `{{STATE_PATH}}` inside the stable prefix fails.
- a template missing the end marker fails.
- stable-prefix hash is unchanged when hot-tail content changes.
- stable-prefix hash changes when invariant instructions change.

### `scripts/record_cache_observation.py`

Purpose: append optional cache-token observations to `state.json` without making
provider telemetry mandatory.

CLI:

```bash
python3 scripts/record_cache_observation.py \
  --state "$STATE_PATH" \
  --unit task_0 \
  --mode interactive \
  --source codex-metadata \
  --usage-json '{"input_tokens":1000,"output_tokens":200}'
```

Rules:

- Missing cache counters are stored as null, not zero.
- The script updates `timestamps.updated_at`.
- The script writes atomically.
- Invalid JSON exits nonzero.
- Unknown token fields are ignored.

### `evals/check_cache_observations.py`

Purpose: deterministic tests for optional cache telemetry.

Required cases:

- appends an observation with only input/output tokens.
- preserves null cache counters when unavailable.
- rejects negative token counts.
- rejects missing state file.
- validates finished state with empty `cache_observations` when telemetry was
  unavailable.

## Prompt Template Changes

### `templates/fresh-session-prompt.txt`

Restructure into:

```text
<!-- CPE_CACHE_STABLE_PREFIX_START -->
You are executing or exporting a CPE run.

Stable rules:
- Do not implement from the caller checkout.
- Keep runtime artifacts under ~/.codex/orchestrator/<run_id>.
- Use task packets, context health, completion audit, and state validation.
- Bootstrap applicable skills for implementation work.
<!-- CPE_CACHE_STABLE_PREFIX_END -->

<!-- CPE_CACHE_HOT_TAIL_START -->
Run inputs:
- plan: {{PLAN_PATH}}
- spec: {{SPEC_PATH}}
- docs: {{DOC_PATHS}}
- mode: {{MODE}}
- state: {{STATE_PATH}}
```

The exact wording can stay close to the existing prompt. The important change is
that every `{{...}}` token lives after the stable-prefix end marker.

### `references/verifier-prompt.md`

Keep the invariant verifier role, required output fields, and safety constraints
before the stable-prefix end marker. Put task id, files, commands, diffs,
state paths, and previous failures in the hot tail.

### `references/headless-runner.md`

Clarify that headless mode is explicit and replay-oriented, not cache-optimal.
State that dynamic boot data must not be inserted before the stable bootstrap.

## Eval And Baseline Updates

Update deterministic validation:

```bash
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Add `audit_prompt_cache.py` and the new checks to `evals/run.sh`.

Add cache audit fields to `evals/baselines/v2.21.0.json`:

```json
{
  "cache_audit": {
    "passed": true,
    "stable_prefix_bytes": {
      "fresh-session-prompt": 0,
      "verifier-prompt": 0
    },
    "dynamic_marker_violations": []
  }
}
```

The first implementation may record `0` for real cache-token counters when the
runtime does not expose them. The deterministic prompt audit is the required
gate.

## Acceptance Criteria

- `mode=interactive` remains the default in `SKILL.md`,
  `scripts/parse_invocation_args.py`, and README.
- No checked stable-prefix block contains `{{...}}`, run ids, state paths, task
  packet paths, timestamps, git status, or absolute home paths.
- Prompt audit passes and is wired into `evals/run.sh`.
- State validation accepts pre-v2.21 states and validates v2.21 cache fields when
  present.
- Finished v2.21 execution state cannot contain prompt audit violations.
- Existing prompt, handoff, interactive, and headless fixture behavior remains
  unchanged except for additional cache audit metadata.

## Rollout Notes

Recommended rollout order:

1. Add docs and deterministic audit script.
2. Annotate templates and references.
3. Add state fields and optional telemetry append script.
4. Wire evals and baseline.
5. Run the deterministic suite.
6. Run one real CPE prompt export and one interactive execution smoke to confirm
   the stable-prefix audit matches generated artifacts.

Rollback is simple: remove the audit from `evals/run.sh` and ignore optional
state fields. Template markers are comments and can remain harmlessly during
rollback.
