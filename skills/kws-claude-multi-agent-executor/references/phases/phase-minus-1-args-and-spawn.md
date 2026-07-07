# Phase -1: Argument Parsing & Run Bootstrap — v3.0 (kernel-owned)

> **v3.0 cutover.** Argument parsing and run bootstrap are owned by
> `kernel.py init` (→ `scripts/kernel/initcmd.py`). The three-pass arg parser
> (`key=value`, multi-plan `plan\d*=` auto-detection, the NL keyword lexicon
> `opus`/`순차`/`대화형`) runs inside `initcmd.parse_args`; the echo line, dirty-tree
> check, RUN_ID derivation, worktree add, hook materialization, and initial
> `state.json` write run inside `initcmd.run_init`. The orchestrator simply invokes
> `kernel.py init --args "<user args>" --repo-root "<repo>"` (SKILL.md §②) and prints
> the returned `echo_line`.

**Invocation contract:** see SKILL.md §②. `init` returns
`{"run_id","state_path","worktree","orchestrator_dir","echo_line"}` on success, or a
`{"halt":…}` dict (dirty_worktree / worktree_add_failed / hooks_materialization_failed)
that is a hard halt (SKILL.md §⑤).

## Long-run continuation (Resume Chain / token-health)

A single subprocess has a bounded context. For long runs the orchestrator hands off to
a fresh subprocess that resumes from the persisted `state.json` — the entire point is
to start the next subprocess with a *small* resident context, re-reading specific state
paths just-in-time rather than pulling the whole state file into context. `state.json`
remains the single source of truth across the handoff, and every WRITE still goes
through the kernel (`kernel.py submit` / `finalize`) — never a hand-edit.

**Honest note:** the v2 self-spawn / detached-headless machinery and the v2
resume-digest convenience read are v2 artifacts. In v3 the resume story is
"a fresh session re-opens the same `state.json` and re-enters the SKILL.md §③ loop";
the kernel's `next`/`submit` are idempotent with respect to already-recorded results,
so a resumed session picks up at the next un-dispatched task. AgentLens run identity is
carried on `state.agentlens_run_id` (propagated, not re-opened, across a handoff).
