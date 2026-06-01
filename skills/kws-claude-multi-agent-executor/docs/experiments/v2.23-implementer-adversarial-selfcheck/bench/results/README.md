# Results provenance

The JSON files here do not self-record the dispatch model, so it is pinned here.
All valid runs used CLI `claude` 2.1.145 on **Sonnet** (`--model sonnet`), fixture
08 Task 0, reviewer walk excluded (pure first-pass). See
[../../findings/F001-close-out-skip.md](../../findings/F001-close-out-skip.md).

| File | Arm | Model | n | Meta-rule first-pass | Notes |
|------|-----|-------|---|----------------------|-------|
| `control.json` | control | Sonnet | 4 | 16/16 = 100% | the decisive baseline (T4); overwrote earlier control runs |
| `treatment.json` | treatment | Sonnet | 1 | 4/4 = 100% | pilot only (T3); treatment n=4 never run — control was at ceiling, so no headroom |

**Discarded / not stored here:**
- The first pilot ran on Opus 4.8 (the user's default model — `_run_implementer`
  omitted `--model` at that point). Both arms ceilinged; that run is invalid for
  the Sonnet baseline and was overwritten. Only the `/tmp/v223-*.log` traces of it
  existed and are ephemeral.

**Re-running** `bench/run_ab.py` overwrites these files. The treatment arm now
aborts before dispatch unless the intervention is re-applied (see
[../../intervention.md](../../intervention.md)), so re-running `--arm treatment`
will NOT silently overwrite `treatment.json` with a control-identical run.
