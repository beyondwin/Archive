# Changelog

User-visible changes to the kws-claude-multi-agent-executor skill.

## v2.25.0

### Changed

- Added a third dispatch transport `"agent"` and made it the **default for all role gates** (Plan Reviewer, Verifier, Transition, Docs Updater, final sweep). `"agent"` dispatches the role in-session via the Agent tool on the **subscription pool** (Max/Pro), not metered API credits — a bare invocation now runs every role on the subscription with `$0` metered spend. Metered transports remain available by explicitly setting a gate to `"api"` or `"p"`.
- Plan Reviewer now runs on **Opus** (`claude-opus-4-7`) by default (was Haiku 4.5).
- Autonomous failure ladder (per D003): on a recoverable dispatch failure the orchestrator retries once, then falls back to `"api"` for that single dispatch, then records a gap marker and continues — it **never prompts the user**.
- Per-plan `verification_gaps` / `docs_gaps` fields are recorded in state and surfaced prominently in the Final Summary Report.

### Breaking / UX

- Under `detach=true`, agent-default gates (not explicitly set) fall back to `"api"` with a one-line warning (per D002), so the subscription default never causes surprise metering on a headless parent. Explicit `"agent"` gates are respected.

## v2.22.0

### Changed

- Headless dispatch (Plan Reviewer, Verifier, Transition, Docs Updater) now goes through the Anthropic Messages API with prompt caching instead of `claude -p`.
- Plan Reviewer runs on Haiku 4.5.
- Phase Transition T1 (batch Verifier) and T2 (Phase Docs Updater) merged into one combined dispatch.
- Phase 2 Step 0 final LOW sweep can use the Message Batches API (`dispatch_config.final_sweep`).

### Breaking / UX

- Bare invocation now runs attached in-session by default; pass `detach=true` for the previous headless self-spawn behavior (2-week deprecation warning during transition).
