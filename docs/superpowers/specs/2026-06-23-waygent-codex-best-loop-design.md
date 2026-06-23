# Waygent Codex Best Loop Design

## Goal

Make `waygent run` choose the best Codex-native execution loop when an operator
asks for maximum quality from Codex: strong model routing, structural runtime
gates, task-scoped context, method evidence, and durable verification evidence.

## Research Basis

I reviewed current public harness and workflow projects on 2026-06-23 and
cloned representative repositories under `/tmp/waygent-codex-loop-research`.
The useful lessons were:

| Source | Commit checked | Local verification | Useful pattern |
| --- | --- | --- | --- |
| [Superpowers](https://github.com/obra/Superpowers) | `896224c` | `bash tests/codex-plugin-sync/test-sync-to-codex-plugin.sh` passed | Skill-gated TDD and plan execution are effective, but should be enforced by Waygent state rather than chat memory. |
| [BMAD Method](https://github.com/bmad-code-org/bmad-method) | `6ac4c26` | `node test/test-workflow-path-regex.js` passed | Role depth is useful during planning; runtime should keep only roles with hard product value. |
| [Task Master](https://github.com/eyaltoledano/claude-task-master) | `c0c98d3` | `node --check bin/task-master.js` passed | Persistent task graph and dependency tracking matter more than persona count. |
| [Agent OS](https://github.com/buildermethods/agent-os) | `cae8e66` | `bash -n scripts/project-install.sh` passed | Project standards injection is valuable, but Waygent should source it from plan/spec/task packet context. |
| [GitHub Spec Kit](https://github.com/github/spec-kit) | `3c11f4d` | `uv run --extra test python -m pytest tests/test_cli_version.py -q` passed | Spec, plan, tasks, implement is the right artifact ladder for agent work. |
| [MCP Task Orchestrator](https://github.com/jpicklyk/task-orchestrator) | `20f2a9a` | `bash gradlew test --no-daemon` failed on local OpenJDK `25.0.2`/Gradle | Server-enforced gates are the strongest transferable idea: invalid transitions should fail structurally, not by prompt convention. |

Primary outside references used for framing:

- [OpenAI, Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
- [VS Code, The Coding Harness Behind GitHub Copilot in VS Code](https://code.visualstudio.com/blogs/2026/05/15/agent-harnesses-github-copilot-vscode)
- [GitHub Spec Kit README](https://github.com/github/spec-kit)

## Current Waygent Fit

Waygent already has the hardest parts of a reliable Codex loop:

- runtime-owned worktrees and run state;
- `waygent-task` file claims and dependency graph;
- deterministic plan preflight;
- task packets and optional spec manifest slicing;
- safe-wave scheduling;
- provider process evidence and model attestation;
- verification, checkpoint, completion audit, reconciliation, and apply gates;
- optional method evidence policy.

The gap was not another orchestrator layer. The gap was that `--profile
max-quality` was provider-neutral in name but Claude-shaped in content, so
Codex runs could receive `opus`/`sonnet` model names and still leave the
stronger harness toggles off unless the operator remembered every flag.

## Decision

Keep Waygent as the product runtime and make Codex max quality a first-class
provider-aware profile:

```bash
bun run waygent -- run \
  --plan docs/superpowers/plans/<plan>.md \
  --spec docs/superpowers/specs/<design>.md \
  --profile max-quality
```

When the resolved provider is Codex, `--profile max-quality` means:

- provider: `codex`;
- execution mode: `multi-agent`;
- main coordinator model request: `gpt-5.5`, reasoning `xhigh`;
- implement, review, verify, and repair role requests: `gpt-5.5`, reasoning
  `high`;
- plan preflight: `full`;
- spec slicing: `manifest`;
- runtime hooks: `builtin`;
- method evidence: required.

When the resolved provider is Claude, existing `opus`-based behavior remains.
Explicit flags still override model and harness settings where Waygent already
has an override flag.

## Non-Goals

- Do not make Waygent call CPE or CME.
- Do not add prompt-managed host subagents as a substitute for `waygent run`.
- Do not add another persistent task database; Waygent run state remains the
  source of truth.
- Do not default every live provider run to full preflight during burn-in; the
  stronger defaults are tied to Codex `max-quality`.

## Expected Operator Behavior

For Codex in this checkout, the best default is:

```bash
bun run waygent -- run --plan <plan.md> --spec <design.md> --profile max-quality
```

Use explicit flags only to narrow scope:

- `--plan-preflight off` when testing a deliberately malformed fixture;
- `--spec-slice off` when debugging spec slicing itself;
- `--hook-config off` only when hook behavior is the suspected failure surface;
- `--provider fake` for deterministic offline tests.

## Acceptance

- Unit tests prove provider-aware profile resolution.
- Unit tests prove Codex `max-quality` maps to full preflight, manifest spec
  slicing, builtin hooks, and method evidence.
- Existing CLI tests still pass.
- Documentation names the exact external repositories, local validation
  commands, and residual external-test caveats.
