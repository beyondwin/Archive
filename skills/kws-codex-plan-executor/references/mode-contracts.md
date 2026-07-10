# Mode Contracts

| Mode | Mutates product worktree | Creates run artifacts | Contract |
| --- | --- | --- | --- |
| `interactive` | yes | yes | Execute v3 tasks in the current Codex interaction |
| `headless` | yes | yes | Execute through structured Codex CLI workers |
| `prompt` | no | no | Export one paste-ready Sol/high launcher and prompt |
| `handoff` | no | no | Export the launcher and an explicit handoff checkpoint |

`run` accepts only execution modes. `export` accepts only prompt or handoff.
`resume` requires an explicit v3 run ID and replays durable events before doing
new work. Multiple ambiguous runs are never guessed.

All modes use the fixed two-route model contract. Exported launchers carry the
model and reasoning flags; the prompt body does not act as model enforcement.
