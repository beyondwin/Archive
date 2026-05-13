# Decisions

This document records why the current design exists. The detailed v1.5.0 source
analysis lives in
[experiments/2026-05-14-oh-my-codex-adoption/PLAN.md](experiments/2026-05-14-oh-my-codex-adoption/PLAN.md)
and
[experiments/2026-05-14-oh-my-codex-adoption/IMPLEMENTATION.md](experiments/2026-05-14-oh-my-codex-adoption/IMPLEMENTATION.md).

## Source Basis

The v1.5.0 hardening pass reviewed `Yeachan-Heo/oh-my-codex` at commit
`148effde4e7c6a35f5bdde3ecd5db3488b3156b5`, dated
`2026-05-12T15:55:29+09:00`.

The intent was not to port `oh-my-codex`. The useful part was identifying
workflow contracts that make autonomous execution safer:

- parse only visible plan text
- ground execution in a source snapshot
- require explicit completion proof
- separate internal phase from terminal outcome
- use dependency metadata as advisory structure
- increase verification scrutiny for high-risk work

## Adopted Patterns

| Pattern | Decision | Reason |
| --- | --- | --- |
| Visible Markdown parsing | Adopt | Prevents examples or comments from becoming executable tasks. |
| Source snapshot hashes | Adopt | Resume and handoff need stable inputs, not chat memory. |
| Completion audit | Adopt | Tests passing does not prove every prompt requirement was satisfied. |
| Lifecycle outcome | Adopt | `current_phase` is not a user-facing terminal result. |
| Optional task dependencies | Adopt as metadata | Dependencies help ordering and review, but must not bypass task contracts. |
| High-risk matrix | Adopt only for high-risk tasks | Adds adversarial checks where risk justifies the cost. |

## Rejected Or Deferred Patterns

| Pattern | Decision | Reason |
| --- | --- | --- |
| tmux/HUD/native hook runtime | Reject | Too product-specific for a portable Codex skill. |
| default team workers | Reject | This skill's subagent policy is explicit opt-in only. |
| mandatory full adversarial QA | Defer | Too heavy for low-risk docs and isolated code changes. |
| mandatory architect/deslop review | Defer | Useful in some plans, but not a universal executor invariant. |
| plan-creation gate before execution | Reject | This skill starts from `plan=`; plan authoring belongs elsewhere. |
| repository-local learning events | Reject | Logs could pollute project repos and expose private context. |

## Why State Is Per Run

Earlier versions used root `.codex-orchestrator/state.json` as the active
ledger. That is ambiguous when multiple runs exist. The current source of truth
is:

```text
.codex-orchestrator/runs/<run_id>/state.json
```

The root state file remains only as a compatibility copy or pointer. This keeps
resume semantics deterministic and allows multiple same-repo runs to coexist.

## Why Context Snapshot Exists

Agents can lose conversation context, resume in a fresh session, or generate a
handoff prompt. `context.json` records the plan/spec/docs paths and hashes so a
future agent can verify what source basis the run used.

This is intentionally lightweight. It does not store full source contents and
does not replace the actual plan/spec/docs.

## Why Completion Audit Exists

Verification commands can be too narrow, cached, skipped, or unrelated to a
prompt requirement. `completion_audit` forces the executor to map requirements
to artifacts and verification evidence before claiming `finished`.

It is deliberately stored in state, not only in the final chat response, because
future agents need a machine-readable resume artifact.

## Why Learning Logs Are User-Local

Learning events are meant to improve this executor across repositories. They are
not project deliverables and can contain process observations. Keeping them
under `~/.codex/learning/kws-codex-plan-executor/` avoids repository pollution
and makes cross-project review possible.

The helper also enforces redaction because learning logs are more durable than a
single chat answer.

## Why Prompt Export Mirrors Runtime

`mode=prompt` and `mode=handoff` do not execute anything. However, they create
the instructions that a later executor will follow. If prompt export omits a
runtime invariant, future sessions can silently regress.

For this reason `check_skill_contract.py` checks `SKILL.md`, references, and
templates together.

## Why Subagents Remain Opt-In

Subagents are useful when the user asks for delegation or when independent
tasks can safely run in parallel. They are also a source of coordination cost,
state ambiguity, and merge conflict risk.

The default executor is local, single-session execution. This keeps ownership
clear and avoids accidental parallel mutation. The policy can be changed only by
an explicit user request or `subagents=on`.

## Why Deterministic Evals Come First

The fragile parts of this skill are contracts, not model fluency. Parser
behavior, state schema, learning event redaction, and prompt/runtime drift are
best protected by deterministic checks. LLM judging is reserved for subjective
quality after mechanical contracts pass.
