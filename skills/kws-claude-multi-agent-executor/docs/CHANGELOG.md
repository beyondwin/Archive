# Changelog

User-visible changes to the kws-claude-multi-agent-executor skill.

## v2.22.0

### Changed

- Headless dispatch (Plan Reviewer, Verifier, Transition, Docs Updater) now goes through the Anthropic Messages API with prompt caching instead of `claude -p`.
- Plan Reviewer runs on Haiku 4.5.
- Phase Transition T1 (batch Verifier) and T2 (Phase Docs Updater) merged into one combined dispatch.
- Phase 2 Step 0 final LOW sweep can use the Message Batches API (`dispatch_config.final_sweep`).

### Breaking / UX

- Bare invocation now runs attached in-session by default; pass `detach=true` for the previous headless self-spawn behavior (2-week deprecation warning during transition).
