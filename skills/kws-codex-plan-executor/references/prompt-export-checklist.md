# Prompt And Handoff Export Checklist

- Resolve the plan, optional spec/docs, and workspace paths without allocating
  a run ID.
- Render the tracked fresh-session template with only source paths and SHA-256
  references. Never embed plan/spec/doc bodies or selectable model IDs.
- Derive the quoted heredoc delimiter from the rendered payload and ensure it
  is absent as a complete payload line.
- Use one outer Markdown fence longer than every inner backtick run.
- For handoff, render the literal `HANDOFF CHECKPOINT` marker through the same
  template and renderer.
- Leave no template tokens, worktree, branch, run directory, state, manifest,
  event, log, or task artifact.
- Verify with `python3 evals/check_prompt.py --real-plan`.
