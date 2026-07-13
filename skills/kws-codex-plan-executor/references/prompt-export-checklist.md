# Prompt Export Checklist

Export is a rendering operation, never execution.

## Required Checks

- At least one --plan is present.
- --spec and --plan may repeat.
- --program-plan appears at most once.
- --workspace and every document path are absolute and currently readable.
- mode is prompt or handoff.
- Output names the exact workspace, specs, plans, optional program plan, and
  intended CPE command.
- Repeated input order is not described as authority precedence.
- The rendered text does not claim that execution started or completed.

## Side-Effect Boundary

A successful export:

- writes only rendered UTF-8 text to stdout;
- does not create CODEX_HOME;
- does not create an orchestrator run;
- does not create or modify a Git worktree;
- does not snapshot inputs;
- does not launch Codex;
- does not append events or artifacts.

Verify both modes with check_lean_cli.py. When changing rendering, test from a
temporary environment where CODEX_HOME does not exist and assert it remains
absent.
