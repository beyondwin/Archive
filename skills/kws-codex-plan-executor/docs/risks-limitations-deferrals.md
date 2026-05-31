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
