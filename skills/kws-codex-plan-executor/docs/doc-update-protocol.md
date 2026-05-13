# Documentation Update Protocol

Use this protocol before finalizing any change to `kws-codex-plan-executor`.
Its purpose is to keep runtime docs, maintainer docs, eval notes, and
verification history aligned with the actual implementation.

## Required Habit

Every update must include a documentation impact check. The result can be:

- docs updated in the same change
- no docs needed, with a concrete reason in the final summary
- deferred docs, with a concrete follow-up and risk

Do not treat passing tests as proof that documentation is current.

## Change-To-Docs Map

| Change | Documentation to inspect |
| --- | --- |
| Runtime trigger, arguments, mode selection | `SKILL.md`, `README.md`, `docs/how-it-works.md` |
| Execution flow or state transitions | `references/execution-cycle.md`, `docs/how-it-works.md`, `ARCHITECTURE.md` |
| Headless behavior | `references/headless-runner.md`, `docs/how-it-works.md`, `docs/evals-and-verification.md` |
| Prompt or handoff export | `templates/fresh-session-prompt.txt`, `references/prompt-export-checklist.md`, `docs/evals-and-verification.md` |
| State schema | `references/state-schema.md`, `docs/state-and-logging.md`, `docs/how-it-works.md` |
| Context health | `references/state-schema.md`, `docs/state-and-logging.md`, `docs/how-it-works.md`, `docs/decisions.md` |
| Learning log schema or privacy | `references/learning-log.md`, `docs/state-and-logging.md`, `docs/risks-limitations-deferrals.md` |
| Parser behavior | `docs/how-it-works.md`, `docs/evals-and-verification.md`, parser fixtures |
| Eval harness or commands | `docs/evals-and-verification.md`, `docs/verification-log.md` |
| Design rationale or accepted tradeoff | `docs/decisions.md`, `ARCHITECTURE.md` when stable |
| New risk, limit, or intentional deferral | `docs/risks-limitations-deferrals.md` |
| Maintenance workflow | `docs/future-agent-guide.md`, `references/change-protocol.md`, this file |
| Release-level behavior change | `SKILL.md` version, `HISTORY.md`, `README.md`, and affected runtime docs |

## Pre-Final Checklist

Before final response, commit, push, or PR:

1. Identify the changed surface: runtime, prompt, headless, parser, state,
   learning log, eval, metadata, or docs-only.
2. Use the map above to inspect the affected docs.
3. Update docs that would mislead the next agent.
4. Add or update deterministic checks when behavior changed.
5. Run the narrowest relevant verification and any package-level checks needed.
6. Append a concise entry to [verification-log.md](verification-log.md).
7. In the final summary, report documentation impact and verification evidence.

## Verification Log Rules

Append to [verification-log.md](verification-log.md) whenever this skill package
is changed. Keep entries compact and factual.

Each entry should include:

- date and local timezone
- branch and commit when known
- scope of the change
- commands run
- result of each command
- skipped checks with reason
- residual risk or follow-up

Do not paste long logs. Prefer the command, exit status, and one short evidence
line such as `Skill is valid!`, `passed=true`, or `markdown links ok`.

If a command fails and the failure is accepted as an environment blocker, record
the blocker and the honest substitute that was used.

## Versioning Rule

Docs-only maintenance can avoid a version bump when runtime behavior, prompt
export, scripts, eval behavior, package metadata, and public skill metadata do
not change.

Behavior changes still follow
[../references/change-protocol.md](../references/change-protocol.md): update
skill metadata, history, architecture, runtime docs, and deterministic checks
as appropriate. If this standalone skill is later reattached to a plugin
package, update that package metadata in the same change.

## What Not To Do

- Do not hide a missing docs update behind a passing test run.
- Do not update `README.md` alone when a detailed contract in `references/`
  also changed.
- Do not write long transient command logs into docs.
- Do not update eval baselines to make a failing change look intentional.
- Do not leave `docs/verification-log.md` stale after a committed package
  change.
