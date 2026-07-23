# AGENTS.md - Claude Plan Runner

## Scope

This subtree is an independent Claude runner. Do not import production runtime
code from the Codex runner, root parity fixtures, or legacy executor state.

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
- Re-run the real `claude --help` contract and a bounded real stream event
  capture whenever CLI flags, stream event parsing, UUID capture, or resume
  invocation changes.
- Keep fake-provider validation separate from explicit live canaries.
- If a fix changes the candidate HEAD, invalidate and rerun all final evidence.

Review completion semantics, recovery bounds, Git/worktree identity, receipt
binding, nested-session scrubbing, credential minimization, and same-UID
residual-risk wording before reporting success.
