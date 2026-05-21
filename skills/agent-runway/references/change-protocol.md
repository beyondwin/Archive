Source-of-truth: AgentRunway code and evals win when this protocol and behavior disagree.

# Change Protocol

Use this before editing AgentRunway behavior.

1. Read `SKILL.md`, `README.md`, and the reference file for the touched behavior.
2. Add or update a focused eval before production code when behavior changes.
3. Keep AgentLens emission non-blocking; local SQLite and run artifacts remain authoritative.
4. Preserve `agentrunway.*` as the only active AgentLens executor namespace. Do not add CPE/CME bridges.
5. Update `README.md` and the relevant `references/*.md` file for operator-visible behavior.
6. Run focused evals, then `python -m pytest evals -q`, then `graphify update .` from the repo root after code changes.
