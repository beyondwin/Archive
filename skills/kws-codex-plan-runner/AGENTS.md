# AGENTS.md - Codex Plan Runner

## Scope

This subtree is an independent Codex runner. Do not import runtime code from the
Claude runner, a shared root contract fixture, or legacy executor state.

## Runtime contract

- Use uv-managed normal-GIL CPython `>=3.13,<3.14`.
- Keep production Python standard library only and preserve an independent runtime.
- Do not use `uv run`; resolve an installed interpreter with `uv python find`.
- Do not download Python during `run`, `resume`, deterministic eval, or launcher startup.
- Do not use system Python fallback.
- Preserve the self-locating launcher and shell-free execution of submitted argv.

## Change workflow

- Use TDD and run focused evals during work.
- Run the full deterministic eval exactly once at the final candidate HEAD.
- Re-run the real Codex CLI contract when command flags, JSONL event parsing,
  session ID capture, or resume invocation changes.
- Keep deterministic fake-provider coverage separate from explicit live canaries.
- If a required fix changes the candidate HEAD, invalidate and rerun all final
  evidence at the new HEAD.

Review completion semantics, recovery bounds, Git/worktree identity, receipt
binding, credential minimization, and same-UID residual-risk wording before
reporting success.
