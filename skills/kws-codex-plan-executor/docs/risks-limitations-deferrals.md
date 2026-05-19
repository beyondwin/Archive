# Risks, Limitations, Deferrals

- Dynamic evals invoke real `codex exec` and can be slow.
- The harness copies the skill under test into a fixture repository to avoid
  source package mutation by target agents.
- AgentLens failures are ignored by design; state validation remains the hard
  completion gate.
