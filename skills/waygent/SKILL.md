---
name: waygent
description: Translate natural-language Waygent run, status, explain, resume, verify, and apply requests into stable CLI commands.
---

# Waygent

Use this skill when the user asks to run, inspect, resume, explain, verify, or
apply a Waygent execution from natural language.

Waygent is the product runtime. This skill translates operator intent into the
`waygent` CLI and then reports the command outcome. It must not implement
scheduling, provider execution, worktree mutation, trust scoring, or direct
AgentLens writes.

Hard boundaries:

- Waygent must not call `skills/kws-codex-plan-executor`.
- Waygent must not call `skills/kws-claude-multi-agent-executor`.
- KWS executor skills are not Waygent product dependencies.
- New Waygent runs use `platform.*`, `runway.*`, `kernel.*`, and `lens.*`
  event families.

Invocation boundary:

- If this skill is explicitly invoked and the user asks to implement, execute,
  run a plan, or run multi-agent work from a design/plan, treat that as a
  Waygent runtime run request.
- Do not use host `spawn_agent`, direct file edits, or chat-managed workers as
  a substitute for `waygent run`.
- The Waygent runtime owns worktree creation. If no Waygent run is created, no
  Waygent worktree should be expected.
- If the request names both a design file and an implementation plan, pass the
  plan with `--plan` and the design/spec with `--spec`.
- If the user says "멀티에이전트", "multi-agent", or similar, include
  `--execution-mode multi-agent`.
- `waygent run` auto-detects the host and picks the default provider when
  `--provider` is not passed: Claude Code (`CLAUDECODE=1` or
  `CLAUDE_CODE_ENTRYPOINT` set) → `claude`; Codex app/CLI (`CODEX_APP=1`,
  `CODEX_CLI=1`, or `CODEX_ENTRYPOINT` set) → `codex`; unknown host → `codex`
  (preserved fallback). Set `WAYGENT_HOST=claude|codex` to force a host.
  Execution mode defaults to `multi-agent` in every case.
- Explicit `--provider` always wins over auto-detection.
- `waygent demo` is the deterministic offline path and only supports the fake
  provider. Use `waygent run` for Codex or Claude provider execution.
- The repo-local fallback command is `bun run waygent -- run ...`; it maps to
  the same CLI as `waygent run ...`.

Host-agent model policy:

- When the host agent is asked to implement, review, or coordinate Waygent
  runtime work from a plan or design, the main coordinating agent should run
  with the strongest reasoning the host supports.
- Codex app / Codex CLI host:
  - Main coordinating agent: extra-high reasoning.
  - Implementation / review / verification subagents: prefer GPT-5.5 with high
    reasoning when the host supports explicit subagent model settings.
- Claude Code host:
  - Main coordinating agent: Opus with high reasoning.
  - Implementation / review / verification subagents: Opus with high reasoning
    when the host supports explicit subagent model settings.
- If the user explicitly names a different model in the request (e.g. "use
  sonnet", "gpt-5 only", "소넷으로"), honor the user's explicit choice over
  these defaults for that invocation.
- If the host cannot change the main agent or subagent model settings, state
  that limitation and use the strongest available configuration instead.
- This policy is a host-agent execution preference. It must not turn Waygent
  into a dependency on KWS executor skills, authorize host `spawn_agent` as the
  implementation path, or bypass the Waygent CLI/runtime boundaries above.

Default mappings:

Natural-language mappings are versioned in
`references/nl-lexicon.md` (`waygent.nl_lexicon.v1`). Keep explicit CLI
flags and explicit command names higher priority than NL interpretation.

- "최근 승인된 플랜 실행해줘" -> `waygent run --latest`
- "design.md plan.md 멀티에이전트로 구현해줘" ->
  `waygent run --plan plan.md --spec design.md --execution-mode multi-agent`
- "최고 품질로 실행해줘" ->
  `waygent run --plan plan.md --spec design.md --profile max-quality`
- "비용 절약 모드로 실행해줘" ->
  `waygent run --plan plan.md --profile cost-saver`
- "이 run id로 다시 실행해줘" -> `waygent run --plan plan.md --run <run_id>`
- "상태 보여줘" -> `waygent status --last`
- "이벤트 보여줘" -> `waygent events --run <run_id> --json`
- "자세히 검사해줘" -> `waygent inspect --run <run_id> --json`
- "왜 막혔어?" -> `waygent explain --last`
- "재개해줘" -> `waygent resume --last`
- "검증 다시 실행해줘" -> `waygent verify --last`
- "이 태스크만 검증 다시 실행해줘" -> `waygent verify --last --task <task_id>`
- "검증 통과한 것만 적용해줘" -> `waygent apply --run <run_id>`
- "고아 런 정리해줘" -> `waygent orphans` (delete via
  `waygent orphans --delete <id> --yes`)
- "실행 가능한 waygent-task 만들어줘" ->
  `waygent scaffold-plan --id <task_id> --title <title> --claim <path:mode> --risk <low|medium|high> --verify <command>`
- "design 검증해줘" -> `waygent lint-design --path design.md`
- "plan 검증해줘" -> `waygent lint-plan --path plan.md`

`--profile` presets:

- `max-quality`: main=opus/high, subagents=opus/high.
- `balanced`: main=opus/high, subagents=sonnet/medium.
- `cost-saver`: main=haiku/medium, subagents=sonnet/medium.

Explicit `--main-model`, `--main-reasoning`, `--subagent-model`, and
`--subagent-reasoning` override any preset.

Plan-author guidance — `verify_isolation` (optional):

Each task may declare `verify_isolation: "isolated" | "fast" | "auto"`. The
default is `"auto"`. Use `"isolated"` when the verify command must observe
the worker's cross-package changes (most integration tests). Use `"fast"`
to opt out of automatic escalation when you are certain the diff is
self-contained. See `docs/operations/verification.md` for failure surface
and kill switches.

Closeout loop:

- After a Waygent run, apply, resume, or implementation-producing command
  changes code or docs, inspect `git status --short --branch --untracked-files=all`
  before declaring the work complete.
- If code or documentation structure changed and `graphify-out/` exists, run
  `graphify update .` before the final status check. Treat resulting graph
  files as generated audit evidence, not runtime state.
- Run the smallest verification gate that proves the changed surface. Use
  `git diff --check` for docs-only changes, add the offline Waygent gates for
  runtime changes, and add console or native gates only when those surfaces
  changed.
- If verification or Graphify mutates tracked files after staging, restage the
  generated changes and rerun `git diff --check` before any commit or final
  completion claim.
- Report unresolved dirty state explicitly, separating pre-existing user
  changes from the current Waygent work.

Stop rules:

- If the plan is missing or `--latest` is ambiguous, ask for the plan path.
- If scaffold inputs do not include explicit file claims, risk, and
  verification commands, ask for those fields instead of inferring
  apply-capable write scope from prose.
- If apply reports `dirty_source_checkout`, report the blocker and do not retry.
- If verification fails, use `waygent explain --last` before `waygent verify`
  or `waygent resume`.
- If `resume` does not report `apply_verified_checkpoint`, do not run `apply`;
  inspect or explain the run first.
- If apply reports `checkpoint_manifest_missing`, `checkpoint_patch_missing`,
  or `checkpoint_digest_mismatch`, report the blocker and do not retry from
  chat.
- If a run reports `intake_decision_required`, explain the specific blocker
  and ask only the short question from the operator decision. Do not rewrite
  the plan from chat unless the user approves the change.
- If a run reports `invariant_violation_predispatch`, `prescriptive_drift`,
  `policy_ack_missing`, or `stale_test_candidates_missing`, the normalized
  design contract is the source of truth. Reference the `normalized_design`
  artifact when explaining the blocker.
- If intake recovery reports `recovered`, proceed with the run result and
  mention the normalized plan and recovery report artifact refs when useful.
