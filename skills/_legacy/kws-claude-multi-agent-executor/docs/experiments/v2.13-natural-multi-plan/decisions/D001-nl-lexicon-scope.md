# D001 — Natural-language lexicon: start small, additive only

**Status**: Accepted
**Date**: 2026-05-16

## Context

The natural-language argument feature lets users write keywords in the args text instead of `key=value` pairs. The lexicon is the lookup table from NL keywords (in any language the user happens to write) to canonical arg keys.

Risk if the lexicon is broad: false positives. The user types "I have a haiku about this bug" and the orchestrator interprets "haiku" as `implementer_model=haiku`. Or worse: the plan body itself, if quoted in the args (it shouldn't be, but accidents happen), contains a model name.

Risk if the lexicon is too small: it doesn't help the user, who has to fall back to `key=value` anyway. Failure mode is graceful (no surprise).

## Decision

The lexicon starts with **only the four most-requested mappings** and is additive only:

| Keyword (regex, case-insensitive) | Maps to | Notes |
|------------------------------------|---------|-------|
| `\b(opus\|오푸스)\b` | `implementer_model=opus` | Initial request from user |
| `\b(sonnet\|소넷)\b` | `implementer_model=sonnet` | Mirror; needed for explicit Sonnet preference |
| `\b(순차\|sequential\|직렬\|시리얼)\b` | `parallel=off` | Initial request from user |
| `\b(대화형\|interactive)\b` | `mode=interactive` | Cost-control mode; high-value |

`haiku`/`하이쿠`: NOT in lexicon (false-positive risk too high — "haiku" is a real English word). If the user really wants Haiku they pass `implementer_model=haiku` explicitly. The skill validates the literal value.

Future additions require a follow-up ADR with: the requested keyword, its mapping, and a survey of plausible false-positive contexts.

## Consequences

- Conservative — most user-facing UX wins (Opus override, sequential mode, interactive mode) covered.
- The lexicon is fixed-size and trivial to audit. No surprise interpretation.
- Pre-scanning excludes tokens with `/`, `.`, `=`, or backtick neighbors (path-like / code-like). Path names containing model words don't trigger.

## Alternatives considered

- **LLM-based interpretation of args.** Rejected — non-deterministic, hard to audit, and the args are short enough that simple regex suffices.
- **Full natural-language plan invocation** (e.g., "build me a CLI tool"). Rejected — way outside scope. The skill needs structured plan/spec docs anyway.
- **No NL parsing at all, just `key=value`.** Rejected — user explicitly requested NL.
