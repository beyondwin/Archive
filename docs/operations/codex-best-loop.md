# Codex Best Loop

Use this page when the operator asks for the best way to run Waygent through
Codex.

## Recommendation

Use the Waygent runtime, not CPE, host subagents, or chat-managed worker loops:

```bash
bun run waygent -- run \
  --plan docs/superpowers/plans/<implementation-plan>.md \
  --spec docs/superpowers/specs/<design>.md \
  --profile max-quality
```

In a Codex host, this resolves to the Codex provider and `multi-agent`
execution by default. `--profile max-quality` is provider-aware:

| Setting | Codex max-quality value |
| --- | --- |
| main model request | `gpt-5.5` |
| main reasoning | `xhigh` |
| implement/review/verify/repair model request | `gpt-5.5` |
| implement/review/verify/repair reasoning | `high` |
| plan preflight | `full` |
| spec slicing | `manifest` |
| hooks | `builtin` |
| method evidence | required |

## Why This Beats The Alternatives

The strongest external pattern is structural enforcement, not more prompts.
Superpowers, BMAD, Task Master, Agent OS, Spec Kit, and Task Orchestrator all
improve agent reliability in different ways, but Waygent already owns the
runtime surfaces those systems usually approximate:

- stateful task graph and dependency barriers;
- isolated worktrees;
- file claims;
- deterministic preflight;
- task packets;
- verification;
- checkpoints;
- completion audit;
- apply-readiness gates.

The Codex best loop therefore keeps Waygent as the runtime and imports only the
portable lessons:

- from Superpowers: explicit design/plan/TDD/review discipline;
- from Spec Kit: artifact ladder from spec to plan to tasks;
- from Task Master: task graph and dependency visibility;
- from Task Orchestrator: gate transitions in code, not prompt convention;
- from Agent OS: inject local standards through task context;
- from BMAD: use roles where they improve output, not as a substitute for
  verification.

## External Research Snapshot

On 2026-06-23 these repositories were shallow-cloned under
`/tmp/waygent-codex-loop-research` and checked locally:

| Repository | Commit | Command | Result |
| --- | --- | --- | --- |
| `obra/Superpowers` | `896224c` | `bash tests/codex-plugin-sync/test-sync-to-codex-plugin.sh` | passed |
| `bmad-code-org/bmad-method` | `6ac4c26` | `node test/test-workflow-path-regex.js` | passed |
| `eyaltoledano/claude-task-master` | `c0c98d3` | `node --check bin/task-master.js` | passed |
| `buildermethods/agent-os` | `cae8e66` | `bash -n scripts/project-install.sh` | passed |
| `github/spec-kit` | `3c11f4d` | `uv run --extra test python -m pytest tests/test_cli_version.py -q` | passed |
| `jpicklyk/task-orchestrator` | `20f2a9a` | `bash gradlew test --no-daemon` | failed locally on OpenJDK `25.0.2`/Gradle before tests ran |

The Task Orchestrator failure is an environment/toolchain caveat, not evidence
against the architecture. Its server-enforced gate model remains the strongest
external design signal for Waygent.

## Operator Flags

Default high-quality Codex run:

```bash
bun run waygent -- run --plan <plan.md> --spec <design.md> --profile max-quality
```

Deterministic offline rehearsal:

```bash
bun run waygent -- run --provider fake --plan <plan.md> --spec <design.md>
```

Debug a malformed plan without full preflight:

```bash
bun run waygent -- run --plan <plan.md> --profile max-quality --plan-preflight off
```

Disable spec slicing only when slicing itself is suspected:

```bash
bun run waygent -- run --plan <plan.md> --spec <design.md> --profile max-quality --spec-slice off
```

## Closeout Expectations

After a Codex best-loop run, apply only through Waygent:

```bash
bun run waygent -- explain --last
bun run waygent -- review --last
bun run waygent -- resume --last
bun run waygent -- apply --last
```

Do not manually apply worker patches from chat. `apply` must see clean source
checkout state, checkpoint manifests, dry-run evidence, completion audit,
reconciliation, and method evidence when the run required it.
