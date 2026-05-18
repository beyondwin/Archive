# AgentLens Integration Levels (v1 locked)

This document defines the four-level integration taxonomy AgentLens uses to describe how deeply it is wired into a host agent or tool. The level names, the per-adapter defaults, and the R1 "Codex App never reports `full`" rule are **v1 잠금 / v1 locked**: they are surfaced by `agentlens doctor integrations` and consumed by downstream dashboards, so renames or semantic shifts require a v2 contract.

## 1. The five reported states

`agentlens doctor integrations` reports each adapter with one of five states. (The `doctor` command also accepts `paths` and `all` scopes — see `cli.md` §4 — and a `--format text|json` flag; integration reporting is the focus of this document.) For each adapter, the reported record contains `integration_level` and, when a shim is installed, `shim_integrity` (`ok` | `drift_warning`) so the four-level taxonomy below can be paired with the live shim sha256 check from `security.md` §4:

- **`none`** — no integration, AgentLens is not aware of the tool.
- **`watcher-only`** — file/log watcher only, no behavioral wiring.
- **`shim`** — PATH shim is installed; AgentLens wraps the real binary.
- **`full`** — native integration (settings injection, plugin, or first-party API hook).
- **`native-experimental`** — an experimental native hook that is not promoted to `full` because it does not yet meet the `full`-level reliability bar.

The five states collapse onto a **four-level taxonomy** for capability planning:

| Level | State(s) included | Meaning |
|------:|-------------------|---------|
| Level 0 | `none` | Tool may be installed; AgentLens does not record anything from it. |
| Level 1 | `watcher-only` | File-system / log watcher; events are best-effort and may miss boundaries. |
| Level 2 | `shim` | PATH shim wraps invocations; argv, exit, and excerpted output are captured deterministically. |
| Level 3 | `full`, `native-experimental` | Native hook; full lifecycle including tool-use granularity. `native-experimental` is the experimental sub-tier. |

Read references to "Level 0" / "level-0" through "Level 3" / "level-3" throughout this repo through this table.

## 2. Per-adapter defaults

| Adapter | Default level | Allowed states | Notes |
|---------|--------------:|----------------|-------|
| `claude` (Claude Code CLI) | Level 2 (`shim`) | `none`, `watcher-only`, `shim`, `full` | `full` is reachable via settings.json hook injection. |
| `codex_cli` (Codex CLI) | Level 2 (`shim`) | `none`, `watcher-only`, `shim`, `full` | Same upgrade path as `claude`. |
| `codex_app` (Codex desktop app) | Level 1 (`watcher-only`) | `none`, `watcher-only`, `native-experimental`, `unavailable` | **R1: never report `full`.** Native hooks are experimental only. |

`unavailable` is reserved for adapters that detect a host they cannot integrate with at all (e.g., Codex App on a platform where the watcher target does not exist) and is rendered as `none` for capability purposes.

## 3. R1 — Codex App is never `full`

The R1 policy exists because the Codex App does not expose a stable, first-party extension point that meets the AgentLens `full` reliability contract (deterministic lifecycle boundaries, redaction at the source, no missed tool-use events). Any native hook we ship for the Codex App is reported as **`native-experimental`** and is gated behind an explicit opt-in flag. `agentlens doctor` will refuse to print `full` for the `codex_app` adapter even if a user manually edits config to force it.

## 4. How a level is chosen

1. `agentlens doctor integrations` probes the host environment.
2. For each adapter it determines the highest **available** state given installed binaries, settings files, and permissions.
3. It then clamps that state to the adapter's allow-list above.
4. The configured `mode` (`minimal` vs `full`) can further down-clamp to `watcher-only` or `none` if the user wants a lighter footprint.

## 5. v1 잠금 정책 (v1 lock policy)

- The five state names (`none`, `watcher-only`, `shim`, `full`, `native-experimental`) and the four numbered levels (`Level 0` … `Level 3`) are **locked**.
- The R1 rule (Codex App is never `full`) is **locked**.
- Per-adapter default levels are part of the v1 contract; lowering a default requires a deprecation cycle, raising it requires a new adapter capability test.
- New adapters are added by appending to the table — they may not reuse retired names.
