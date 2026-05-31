# Cache Strategy

CPE treats prompt caching as a prefix-stability problem. The executor does not
assume a provider-specific cache-control API is available.

## Terms

- Stable prefix: role instructions, safety boundaries, required skills, output
  schemas, and invariant checklists.
- Hot tail: plan paths, run ids, state paths, timestamps, git status, task
  packets, changed files, diffs, decisions, verification output, and retry
  context.
- Cache-hostile drift: dynamic material inserted before stable prompt content.

## Rules

1. Keep `mode=interactive` as the default.
2. Put stable prefix before hot tail.
3. Do not put run ids, state paths, task packet paths, timestamps, git status,
   diffs, decisions, or absolute home paths in stable prefix blocks.
4. Put task/run payloads in the hot tail.
5. Treat provider cache-token counters as optional telemetry.

## Markers

Checked prompt artifacts use:

```text
<!-- CPE_CACHE_STABLE_PREFIX_START -->
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
```

All dynamic `{{...}}` placeholders belong after the stable-prefix end marker
unless they are explicitly allowlisted by `scripts/audit_prompt_cache.py`.
