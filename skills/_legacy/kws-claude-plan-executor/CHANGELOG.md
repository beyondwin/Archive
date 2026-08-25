# Changelog — kws-claude-plan-executor (CLPE)

All notable changes to this skill. Versioning follows [Semantic Versioning](https://semver.org):
`MAJOR` for a breaking change to the CLI contract or run-state format, `MINOR`
for backward-compatible capability, `PATCH` for fixes and docs. The
source-of-truth version is the `metadata.version` field in `SKILL.md`; this
file records what each version changed.

## 1.0.0 — 2026-07-22

Initial release. A thin (~550-line, stdlib-only) launcher for approved
Superpowers implementation plans on the `claude` CLI, replacing the fat v3
orchestrator's role (`kws-claude-multi-agent-executor`; its archival and the
`scripts/agent` verification-tooling migration are a pending follow-up).

Capabilities:
- `run` / `resume` / `inspect` subcommands; exit codes 0/1/2/3
  (completed/failed/blocked/resumable).
- Ownership boundary: CLPE maintains one execution environment and verifies
  submitted facts; the child `claude -p` Superpowers session owns all workflow
  semantics (task selection, review, retries, subagents, parallelism).
- Fail-closed completion: `subtype==success` + `structured_output` present +
  shape-valid + child `status==completed` + clean worktree + reported
  `head_commit` prefixes real `HEAD` + `merge-base --is-ancestor` + empty
  `open_findings`.
- Session-delegated resume via `claude -p --resume <session_id>` (gates never
  relaxed on resume; launches bounded at 5 per run).
- Process-group wall-clock timeout (SIGTERM → 10s → SIGKILL, stderr drained).
- Nested-session env scrub (`CLAUDECODE` / `CLAUDE_CODE_CHILD_SESSION` /
  `CLAUDE_CODE_ENTRYPOINT` + `_API_KEY`/`_TOKEN`/`_SECRET` suffixes removed;
  `ANTHROPIC_*` preserved).
- Deterministic, network-free, model-free evals via a fake `claude` on PATH.

Launch contract validated against a live `claude` v2.1.206 measurement, which
corrected four assumed-but-wrong CLI contracts before release (the fake-based
evals alone could not have caught these):
- `--json-schema` takes the schema's **inline JSON content**, not a file path.
- `--max-turns` does **not exist** and was removed (`--max-budget-usd` is the
  real budget flag; the child may still emit `error_max_turns` from its own
  internal limits, which resume handles).
- `--disallowedTools` is a **single variadic flag** carrying all deny rules,
  not the flag repeated per rule.
- Provider-block signals are read from a `rate_limit_event`
  (`rate_limit_info.status != "allowed"`) and the result event's
  `api_error_status`, not a `{"type":"system","error":...}` event the CLI
  never emits.

Notes:
- Billing: on the measured machine, headless `claude -p` bills the
  **subscription (OAuth)** (init `apiKeySource="none"`, five-hour window);
  `total_cost_usd` in the envelope is an API-equivalent display, not a metered
  credit charge.
- Known limitation: provider block-vs-fail classification is **defensive and
  partly inferred** — only the success stream shapes are verified against the
  real CLI; the exact rejected/error shapes are inferred, so the usage-vs-auth
  distinction may be imprecise (both map to `provider_unavailable` → blocked).
  See `SKILL.md` → "Known limitation: provider-block classification".
