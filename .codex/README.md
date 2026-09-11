# Codex project config

Committed, project-scoped Codex config. Runtime state stays in ignored dirs
listed in `AGENTS.md`.

- `config.toml` — defaults for Codex sessions in this repo

No execpolicy rules are committed. Desktop Full Access tasks skip interactive
approvals, and a project rule that asks for confirmation can reject ordinary
Git commands. Destructive-operation boundaries stay in `AGENTS.md` and the
runner's isolated-copy / protected-ref / remote-mutation checks.

Restart Codex or start a new task after changing project config. See
[local setup](../docs/operations/codex-local-setup.md).
