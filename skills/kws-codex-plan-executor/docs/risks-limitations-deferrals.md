# Risks, Limitations, Deferrals

- Dynamic evals invoke real `codex exec` and can be slow.
- The harness copies the skill under test into a fixture repository to avoid
  source package mutation by target agents.
- AgentLens failures are ignored by design; state validation remains the hard
  completion gate.
- Default subagent execution is bounded by task packets and disjoint write
  scopes. When a task cannot be safely delegated, the remaining risk is closed
  by requiring an explicit `subagent_strategy.mode = local_fallback` reason in
  finished state.
- Graphify may be unavailable or ignored in a checkout. CPE records
  `scripts/check_graphify_freshness.py` output and treats missing reports as
  warnings, while stale reports require update evidence before a finished run.
- Recovery classification is intentionally bounded and conservative. Unknown
  command observations receive only limited investigation/retry budget and must
  either be tied to residual risk or produce a failed/blocked outcome.
- v2.22 bootstrap plans are suggestions only. CPE does not install
  dependencies, create Android SDK state, or bootstrap optional CLIs
  automatically.
- Run-quality inspection remains read-only, but v2.23 adds a separate
  `scripts/repair_runs.py` operator flow. It can mark exactly one validated
  stale non-terminal run with a missing execution worktree as blocked after
  explicit `--apply --run-id <id> --action mark-blocked-stale`. Cleanup,
  deletion, finished-state rewrites, and arbitrary schema repairs remain
  deferred.
- Effective delegation policy records why a task fell back locally, but real
  subagent spawning remains controlled by the active Codex tool policy.
