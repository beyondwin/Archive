# Mode Contracts

| Mode | Trigger | Mutates repo | Uses codex exec | Default sandbox |
|------|---------|--------------|-----------------|-----------------|
| `interactive` | default | yes, inside a dedicated `codex/...` worktree | no | current session policy |
| `headless` | `mode=headless` | yes, inside a dedicated `codex/...` worktree | yes | `workspace-write` |
| `prompt` | `mode=prompt` | no | no | n/a |
| `handoff` | `mode=handoff` or continuation request | no | no | n/a |

`interactive` is the default because it preserves Codex app context, connector
availability, user-visible progress, and approval handling. It still must not
implement from the caller's original checkout; execution starts only after a
dedicated non-conflicting `codex/...` git worktree exists.

`headless` is for eval, CI, or explicitly detached work. It must write logs and
final output paths.

`prompt` and `handoff` produce only a fenced `text` prompt and must not edit the
repo.

## Selection Rules

- If no mode is provided, use `interactive`.
- If the user asks for a paste-ready prompt, fresh-session prompt, prompt-only
  output, or no edits, use `prompt`.
- If the user asks for a continuation prompt or handoff, use `handoff`.
- If the user asks for eval, CI, background, or detached `codex exec`, use
  `headless`.
- If the user passes `resume=latest`, scan `.codex-orchestrator/runs/*/state.json`
  first. Resume from the only readable active run; if there are multiple active
  candidates, stop and ask which run/state to use. Use
  `.codex-orchestrator/state.json` only as a backwards-compatible latest pointer
  or copy.
- If the requested mode conflicts with the user's words, stop and ask one short
  question.
