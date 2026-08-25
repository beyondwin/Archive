# Waygent Natural Language Lexicon

Schema: `waygent.nl_lexicon.v1`

This file is the human-readable source for natural-language Waygent command
mapping. Explicit CLI flags and explicit command names always win over natural
language interpretation.

## Commands

| Intent | English terms | Korean terms | Command |
|---|---|---|---|
| Run latest approved plan | `latest` | `최근`, `승인` | `waygent run --latest` |
| Status | `status` | `상태` | `waygent status --last` |
| Events | `event`, `events` | `이벤트` | `waygent events --last` |
| Inspect | `inspect` | `검사` | `waygent inspect --last` |
| Explain blocker | `blocked`, `explain` | `왜` | `waygent explain --last` |
| Resume | `resume` | `재개` | `waygent resume --last` |
| Apply | `apply` | `적용` | `waygent apply --last` |

## Providers

| Provider | Terms |
|---|---|
| Codex | `codex` |
| Claude | `claude`, `opus` |

## Execution Mode

| Mode | English terms | Korean terms |
|---|---|---|
| `single-agent` | `single` | `단일` |
| `multi-agent` | `multi` | `멀티` |

## Model And Reasoning

Model keywords such as `opus`, `sonnet`, `haiku`, and `claude-*` may set
`--main-model` or `--subagent-model` when no explicit CLI flag already set the
same value. Reasoning keywords map to `--main-reasoning` and
`--subagent-reasoning`.
