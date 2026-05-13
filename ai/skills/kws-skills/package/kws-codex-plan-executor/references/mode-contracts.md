# Mode Contracts

| Mode | Trigger | Mutates repo | Uses codex exec | Default sandbox |
|------|---------|--------------|-----------------|-----------------|
| `interactive` | default | yes | no | current session policy |
| `headless` | `mode=headless` | yes | yes | `workspace-write` |
| `prompt` | `mode=prompt` | no | no | n/a |
| `handoff` | `mode=handoff` or continuation request | no | no | n/a |

`interactive` is the default because it preserves Codex app context, connector
availability, user-visible progress, and approval handling.

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
- If the user passes `resume=latest`, resume from the only readable
  `.codex-orchestrator/state.json`; if there are multiple candidates, stop and
  ask which state to use.
- If the requested mode conflicts with the user's words, stop and ask one short
  question.
