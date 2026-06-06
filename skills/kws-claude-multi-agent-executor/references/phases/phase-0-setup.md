# Phase 0: Setup

> **Loaded by**: `SKILL.md` Phase 0 entry stub — orchestrator MUST `Read` this
> file when it reaches Phase 0 (after Phase -1 mode selection) and follow it to
> completion before entering Phase 1.
>
> **Scope**: resume protocol + legacy state migration, plan/spec validation,
> clean-tree + cross-run isolation checks, worktree + safety-hook creation,
> document reading, ambiguity gate, spec manifest, risk assignment, local-env
> preflight, baseline test, dependency graph / compaction points / execution
> plan, Plan Reviewer preflight, state.json initialization, and the mandatory
> Phase 0 boundary emit.
>
> **Why extracted**: Phase 0 runs once per plan at the front of a run and is
> ~650 lines of setup detail that otherwise sits resident in the orchestrator
> prefix for the entire session. Extraction is v2.21 D005 (extends v2.19 D001).

---

## Phase 0: Setup

0. **Check for existing state file (Resume Protocol):**
   Check if `<orch_dir>/state.json` exists by attempting to read it.
   - If it does NOT exist: proceed normally to Step 1.
   - If it EXISTS and is valid JSON with `schema_version: "2"`:
     - If `"mode": "headless_pending"`: freshly-spawned headless instance — Phase -1 already ran Steps 1, 1.5, 2, 2.5 in interactive context and wrote minimal state. **MUST skip Phase 0 Steps 1, 1.5, 2, 2.5** (clean check, cross-run isolation, worktree creation, safety hooks — re-running breaks: `git status` flags `.claude/settings.json` inside the worktree as dirty; `git worktree add` errors on the existing branch; Step 1.5 mode-exclusivity check would self-block on the freshly-created `$ORCH_DIR/headless.pid`). PROCEED with Phase 0 Step 0.5 onward (`0.5 → 3 → 3.5 → 4 → 5 → 6 → 7`) to populate baseline, risk_levels, compaction_points, full task data. After Step 7, update `state.json.mode` from `"headless_pending"` to `"headless_running"` and write. **Preserve `state.implementer_model` exactly as the parent wrote it (v2.12)** — the parent already parsed the skill arg; do NOT overwrite. If the field is absent (legacy state.json), default to `{"used": "sonnet", "default": "sonnet"}`. **Preserve `state.plan_chain` exactly as the parent wrote it (v2.13)** — the parent already parsed the plan/plan2/.../planN args and constructed the chain. The child reads plan paths from `state.plan_chain[state.active_plan].plan_path` for multi-plan runs; do NOT re-parse skill args. If `plan_chain` is absent → this is a single-plan run, read from top-level `state.plan` and `state.spec`.
     - If `"mode": "headless_running"`, `"headless_chained"`, `"plan_chain_running"`, `"plan2_running"`, `"interactive_session"`, or no mode field: Standard resume path — load all fields. Do NOT overwrite. Verify git branch and worktree match `state.branch` / `state.worktree`. Set internal tracking from state.json: `current_task`, `current_step_within_task`, `current_pre_task_sha`, per-task counters. Output: "Resuming from state file: Task <N>, Step <M> (mode=<value or null>)." Skip Phase 0 Steps 1–7 (setup already done). Go directly to Phase 1 at the recorded task/step.
     - **Legacy state.json defaults (v2.14 — RUN-LEVEL fields):** before continuing the resume, backfill the four v2.14 run-level fields if missing (pre-v2.14 state.json will not have them). Apply each as a `setdefault` (write-only-if-absent) at the TOP level of `state` (NOT inside `plan_chain[i]`):
       - `state.setdefault('cost_ledger', {"by_task": {}, "by_role": {}, "by_model": {}, "totals": {"input_tokens": 0, "output_tokens": 0, "cached_read_tokens": 0, "cached_write_tokens": 0, "cost_usd": 0.0, "dispatches": 0}})`
       - `state.setdefault('budget_cap_usd', None)`
       - `state.setdefault('budget_action', 'warn')`
       - `state.setdefault('archive', None)`
       - `state.setdefault('agentlens_orchestration_run', None)` (v2.17 — RUN-LEVEL; AgentLens orchestration run ID opened by Phase -1 step b)
       - `state.setdefault('agentlens_healthy', None)` (v2.21 — RUN-LEVEL; one-shot reachability probe result from Phase -1 step b. `null` on a pre-v2.21 resume means "probe never ran" — treat as `false` for audit, but do NOT re-probe on resume; the field is only authoritative when written at run-open time)
       If `state.cost_ledger` is already present (v2.14+ state.json), preserve it as-is and continue accumulating. Same for `budget_cap_usd` and `budget_action`. These fields span the whole chain, so the resume MUST NOT reset them on plan_chain swap or chain handoff. **`cost_tracking_waived` and `cost_tracking_waive_reason` (v2.28, D001) are likewise RUN-LEVEL and PRESERVED on every resume/handoff** — once Phase 0 Step 7 sets the waive, never recompute or clear it on a subsequent resume; carry whatever was written through plan_chain swap and Resume Chain handoff.
     - **Legacy `plan2_state` migration (v2.21 — D004):** immediately after loading state.json on any resume path, if `state.plan_chain` is absent AND `state.plan2_state` is a non-null object, run the one-time conversion shim **before** any `<active>`-dependent logic executes:
       ```bash
       python3 <skill_dir>/scripts/migrate_legacy_state.py --state "$ORCH_DIR/state.json"
       ```
       The shim rewrites the legacy two-plan shape into a `plan_chain[]` of length 2 (index 0 = the former top-level per-plan fields, index 1 = `plan2_state`'s fields), converts `active_plan` to the integer index, removes `plan2_state`, and writes back atomically. It is a no-op when `plan_chain` already exists or when `plan2_state` is null/absent (single-plan), so it is safe to call unconditionally on every resume. A non-zero exit is a hard halt (a partially-readable state.json must not be executed against). After it runs, every downstream branch collapses to the single modern `plan_chain` path (multi-plan) or top-level `state` (single-plan) — no `<active>` resolution anywhere reads `plan2_state`, because no state.json reaching Phase 1 still carries it. The `mode` field is *not* rewritten, so a migrated state may still read `mode: "plan2_running"`; that string remains a recognized resume mode (it dispatches to the standard resume path above) and is unrelated to the now-removed `plan2_state` key. Single-plan v2.12 state.json (top-level `tasks`, no `plan2_state`) is unaffected.
     - **Source `ORCH_RUN_ID` (v2.17):** every Phase 1 / Phase Transition / Phase 2 emit site that talks to AgentLens reads from a shell variable named `ORCH_RUN_ID`. On any resume path (headless_pending child startup, headless_chained handoff, interactive resume), set it once near the top of Phase 0 Step 0 after state load: `ORCH_RUN_ID="${AGENTLENS_PARENT_RUN_ID:-$(jq -r '.agentlens_orchestration_run // ""' "$ORCH_DIR/state.json" 2>/dev/null)}"`. The env var (set by Phase -1 step d / Resume Chain step 4) takes precedence; state.json is the fallback for resume paths that did not inherit the env (e.g., the user manually re-attaching). If both are empty the value stays `""` and every `agentlens event append` guarded by `[ -n "${ORCH_RUN_ID:-}" ]` becomes a silent no-op — the run proceeds without AgentLens.
   - If it EXISTS but is invalid (empty, malformed JSON):
     - Warn user: "State file exists but is corrupted at <path>. Recommend manual inspection before proceeding."
     - Do NOT overwrite. Halt.

0.5. **Validate plan file (pre-flight):**
   Read the plan file. Before proceeding:
   - If the file is unreadable or missing: halt. "Plan file not found or unreadable at <path>."
   - **Detect task header level (v2.17):** scan for both `### Task N:` (H3) and `## Task N:` (H2) section headers via case-sensitive line-anchored regex `^(##|###)\s+Task\s+\d+:`. Resolve which level the plan uses:
     - If `### Task N:` matches exist: use H3 (`### `). This is the canonical format; H2 occurrences (if any) are treated as Phase headers per Step 3.
     - Else if `## Task N:` matches exist: use H2 (`## `). The plan's internal `### N. <step>` substeps under each task are then *substeps*, NOT tasks — the detected level is what scoping uses for "the task block".
     - Else: halt. "Plan has no `## Task N:` or `### Task N:` sections. Cannot execute."
   - Hold the detected prefix in your internal notes as `task_header_prefix` (literal string `"### "` or `"## "`). It is persisted into `<active>.task_header_prefix` at Step 7. Every later mention in this SKILL.md of `### Task N:` (Steps 3, 3.5, 6, prompt placeholders) refers to "Task N: at the detected level"; substitute `task_header_prefix` when constructing regex or instructions for sub-agents.
   
   This gate runs before worktree creation — structural failures cost zero infrastructure.

1. **Check working tree is clean:**
   ```bash
   git status
   ```
   If there are uncommitted changes, stop immediately. Tell the user: "Working tree is dirty. Please commit or stash changes before running multi-agent-executor." Do not proceed.

1.5. **Cross-run isolation checks:**
   Enumerate every orchestrator-state directory under `~/.claude/orchestrator/` and catch state that prior crashed runs left behind. Two independent checks:

   **(a) Mode exclusivity — repo-scoped (v2.20)** — refuse to start only if another run **targeting the same source repo** is alive. The exclusivity key is the source repo's git common dir (`git rev-parse --git-common-dir`, canonicalized): every worktree this skill creates for a repo shares that common dir, so it is a stable per-repo identity. Two runs against *different* repos have disjoint `.git` object stores and branch namespaces — they cannot race on git operations — so they are allowed to run concurrently. Enumerate every orchestrator-state directory directly and compare `source_repo`:
   ```bash
   # Identity of THIS invocation's repo (Step 1.5 runs before worktree creation,
   # so cwd is still the source repo). All worktrees of a repo share this value.
   SELF_REPO="$(cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P)"
   for dir in "$HOME/.claude/orchestrator/"*/; do
     [ -d "$dir" ] || continue
     pid_file="${dir}headless.pid"
     done_file="${dir}HEADLESS_DONE.txt"
     halted_file="${dir}HEADLESS_HALTED.txt"
     if [ -f "$pid_file" ] && [ ! -f "$done_file" ] && [ ! -f "$halted_file" ]; then
       pid=$(cat "$pid_file")
       if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
         other_repo=$(jq -r '.source_repo // ""' "${dir}state.json" 2>/dev/null)
         # Different repo with a known identity on BOTH sides → no git/branch race; allow.
         if [ -n "$other_repo" ] && [ -n "$SELF_REPO" ] && [ "$other_repo" != "$SELF_REPO" ]; then
           echo "INFO: live run at $dir (PID $pid) targets a different repo ($other_repo); not blocking this run ($SELF_REPO)." >&2
           continue
         fi
         # Same repo, OR either identity unknown (legacy state.json / not-in-git) → conservative block.
         echo "BLOCKED: active run at $dir (PID $pid) targets the same repo ($SELF_REPO), or its repo identity is unknown. Halt with 'kill $pid' or wait for HEADLESS_DONE.txt. To force-clear after confirming the process is dead, remove $pid_file." >&2
         exit 1
       fi
     fi
   done
   ```
   On detection: halt with the message above. Do NOT silently proceed when the repos match — same-repo concurrent runs can race on git operations, branch namespace, and the shared worktree object store. **Conservative-block rule:** if either `source_repo` is empty (a pre-v2.20 run with no `source_repo` field, or this invocation is somehow not inside a git repo), block — an unknown identity cannot be proven safe. Cross-repo AgentLens emits are safe: each run owns a distinct `agentlens_orchestration_run` id and events are appended per-run, so concurrent different-repo runs do not collide on the event stream.

   **(b) Stale-state report (advisory, NOT auto-delete)** — for any `$HOME/.claude/orchestrator/<RUN_ID>/` directory with **no `state.json`** AND mtime > 7 days, list it to the user once:
   > "Orphan orchestrator-state directories detected (no state.json, last modified >7d ago):
   >   - `<path1>` (<age> days)
   >   - `<path2>` (<age> days)
   > These appear to be from interrupted runs. Inspect manually with `ls <path>` and the matching worktree under `~/.claude/worktrees/<same-suffix>/`. Remove the worktree with `git worktree remove <wt-path> --force && git worktree prune` and the state dir with `rm -rf <path>` if no in-progress work. Continuing with this run."

   **Do NOT auto-delete.** A state directory missing state.json may still pair with a worktree holding uncommitted manual debugging work; the user must decide. The report is one-shot per invocation; it does not halt.

   **Headless skip:** when the resume protocol detects `mode == "headless_pending"`, this step is part of the "MUST skip" set (already covered by Phase -1's interactive run).

2. **Create worktree:**
   - First invoke `Skill("superpowers:using-git-worktrees")` and follow its guidance.
   - Capture the timestamp once now (e.g., `20260508-143022`) — used as the shared suffix for BOTH the branch name, the worktree path, AND the orchestrator-state path. The three names MUST stay in sync.
   - Derive `plan-slug` from the plan filename: lowercase, replace spaces and underscores with hyphens, strip the date prefix (e.g., `2026-05-08-my-feature.md` → `my-feature`). The combined `<plan-slug>-<YYYYMMDD-HHMMSS>` is the run identifier — record it internally as `RUN_ID`.
   - Compute absolute paths (expand `~` to `$HOME`):
     - `WORKTREE_ABS = $HOME/.claude/worktrees/<RUN_ID>`
     - `ORCH_DIR    = $HOME/.claude/orchestrator/<RUN_ID>`
   - Before executing: run `git branch --list "<plan-slug>-*"` to check for an existing branch with the same slug prefix. If a match is found and no state.json exists at `$ORCH_DIR/state.json` (i.e., this is not a resume): ask the user — "Branch <name> already exists with no state file. Rename with a new timestamp suffix, or halt?" Do not silently overwrite. Also halt if `$WORKTREE_ABS` or `$ORCH_DIR` already exist on disk without a matching state.json (collision is impossible with a fresh timestamp, but defends against clock skew).
   - Ensure parent directories exist, then create the worktree:
   ```bash
   mkdir -p $HOME/.claude/worktrees $HOME/.claude/orchestrator
   git worktree add -b <plan-slug>-<YYYYMMDD-HHMMSS> $HOME/.claude/worktrees/<plan-slug>-<YYYYMMDD-HHMMSS>
   mkdir -p $HOME/.claude/orchestrator/<plan-slug>-<YYYYMMDD-HHMMSS>
   ```
   - Capture both paths into your internal notes; they will be persisted into `state.worktree` and `state.orchestrator_dir` at Step 7.
   - **Capture `source_repo` (v2.20 — repo-scoped exclusivity):** before this step `cd`s into the worktree, resolve the source repo identity with `SELF_REPO="$(cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P)"` and record it in internal notes; persist it into `state.source_repo` at Step 7. This is the key Step 1.5(a) uses to allow concurrent runs against *different* repos. (Self-spawn runs already captured this in Phase -1 step b; the headless child resuming from `mode=headless_pending` **preserves the parent's `state.source_repo` as-is** at Step 7 — it does NOT recompute, since the child's cwd is the worktree whose common dir resolves to the same value but recomputation is unnecessary.) Empty value → write `null`.
   - Throughout the rest of this document, `<worktree_path>` (or `<worktree>`) refers to `WORKTREE_ABS` and `<orch_dir>` refers to `ORCH_DIR`. The two are no longer nested — `<orch_dir>` is NOT under `<worktree_path>`.

2.5. **Write worktree safety hooks + gate hooks (P1) — v2.18 paths:**
   `<worktree_path>/.claude/settings.json` is the only file this step writes inside the worktree (claude code loads it from cwd). All helper scripts live in `<orch_dir>/hooks/` so they survive worktree teardown and don't pollute the working tree.
   ```bash
   mkdir -p <worktree_path>/.claude
   mkdir -p <orch_dir>/hooks
   ```

   **Materialize hook scripts** by copying the templates from this skill's `references/hooks/` into `<orch_dir>/hooks/`, stripping the `.template` suffix and making them executable:
   ```bash
   cp <skill_dir>/references/hooks/scan-debug-artifacts.sh.template \
      <orch_dir>/hooks/scan-debug-artifacts.sh
   cp <skill_dir>/references/hooks/check-implementer-output.sh.template \
      <orch_dir>/hooks/check-implementer-output.sh
   cp <skill_dir>/references/hooks/finalization-stop-gate.sh.template \
      <orch_dir>/hooks/finalization-stop-gate.sh
   chmod +x <orch_dir>/hooks/*.sh
   ```
   `<skill_dir>` is the directory containing this SKILL.md. Resolve via `dirname` of the skill path or the absolute path captured when the skill was invoked.

   **Materialize + verify `<worktree_path>/.claude/settings.json`** via the
   deterministic script (v2.27 — replaces the prior hand-written JSON, which had
   no merge step and silently dropped hooks when the source repo already shipped a
   `.claude/settings.json`; see D001):
   ```bash
   python3 <skill_dir>/scripts/materialize_worktree_hooks.py \
     --worktree <worktree_path> --orch-dir <orch_dir> --skill-dir <skill_dir>
   ```
   The script reads any existing `<worktree_path>/.claude/settings.json`,
   **deep-merges** the four hook events (preserving the repo's `permissions`,
   `$schema`, and any other hook events), atomic-writes, and self-asserts the four
   events are present with `Stop` wired to `finalization-stop-gate.sh`. **A
   non-zero exit is a hard halt** — do not proceed to Phase 1 with unwired hooks.
   The canonical settings.json shape it emits is documented in
   `references/cross-cutting/safety-hooks.md`.

   **What each hook does:**
   - `PreToolUse` (Bash) blocks `rm -rf /`, force-push to protected branches, and `DROP TABLE/DATABASE/SCHEMA` in sub-agent Bash calls. The hook extracts `.command` from the JSON `$CLAUDE_TOOL_INPUT` via `jq` before grep-matching (raw-JSON matching has too many false positives/negatives due to quoting and escaping). If `jq` is unavailable or extraction fails (no `.command` key), the hook falls back to matching the raw payload — strictly more permissive than the jq path, never less. Does NOT block `git reset --hard` — the orchestrator uses it for verifier-fail recovery.
   - `PostToolUse` (Edit|Write) — `scan-debug-artifacts.sh` — runtime-enforced debug-artifact gate. On detection of `console.log|debugger|TODO|FIXME` in added content (outside string literals and `*.md` paths), exits 2; Claude Code surfaces the failure to the sub-agent which retries the edit. Replaces the prose-only Phase 1 Step 4.1 grep (now removed) — discipline lives in the runtime, not in the loop.
   - `SubagentStop` — `check-implementer-output.sh` — STATUS sanity check on Implementer output. Verifies presence of `STATUS:`, `SUMMARY:`, `FILES_CHANGED:`, `FILES_TEST_CHANGED:` (and `COMMIT:` when STATUS=DONE; ESCALATE fields when STATUS=ESCALATE). Missing field → exit 2 → orchestrator receives failure and re-dispatches.
   - `Stop` — `finalization-stop-gate.sh` (v2.26) — finalization forcing function. When the session tries to STOP, a cheap single-`jq` pass checks the active tree; while any task is still non-terminal it exits 0 immediately (negligible per-turn cost). Only once **every** task is terminal AND a real end-signal fired (run-level `status: COMPLETE`, or `current_task` cleared with a recorded `last_completed_task`) does it run `finalize_run.py --check` and `validate_state_schema.py`. If either reports a blocking problem → exit 2 with corrective guidance on stderr, blocking the stop until Phase 2 finalization completes. This resolves the two remaining v2.26 risks — a run that **never enters Phase 2** (the source-matching failure) and attached-mode schema improvisation — that the Phase-2-only gates could not catch (D001). Fail-open on hook-internal error (missing args/tools/state, validator exit 2) so a broken hook never traps the session; fail-closed on a detected inconsistency.

   **Why this layering matters (P1):** prior versions kept these checks in prose (Orchestrator-driven), so a context drift or malformed reply could silently skip the gate. With hooks they cannot be bypassed.

3. **Read both documents fully:**
   - Read the plan document. Extract the ordered task list: every section whose header matches the detected `task_header_prefix` from Step 0.5 followed by `Task N:` (so either `### Task N:` for H3 plans or `## Task N:` for H2 plans). Capture each task's full text from its header up to the next header at the same or higher level. Note any explicit phase groupings:
     - For H3 plans: `## Phase 1`, `## Phase 2` define phase boundaries.
     - For H2 plans: phases come from `# Phase 1` (H1) or any non-`Task` H2 header (e.g., `## Phase 1: Foundation`). Do NOT treat substep headers (`### 1. <step>`) inside an H2 task as task or phase boundaries — they are scoped to their parent task.
   - Read the spec document. Keep relevant sections in context for prompt construction.

3.5. **Validate document content (Ambiguity Gate):**
   After reading both documents, before assigning risk levels:

   1. **Missing Files blocks:** List every task section (header at the detected `task_header_prefix` from Step 0.5) that has no `**Files:**` block. If any found: ask the user one short question — "Tasks N, M have no Files block. Should I infer from task descriptions, or halt for you to add them?" Halt until answered.

   2. **Ambiguity scan:** Check each task description for:
      - Verbs without referents: "fix the bug", "optimize the query", "update the config" — which one?
      - Missing acceptance thresholds: "improve performance" with no metric, "reduce errors" with no target
      - Named contracts (function/type/API names) in the task that contradict the spec — same entity, different name or signature
      
      For each ambiguity found: ask one targeted question. Halt until all are resolved. Do not proceed to risk assignment until all ambiguities are cleared.

   3. **Out-of-repo paths:** Verify all paths in `**Files:**` blocks resolve within the repo root. Any path that escapes (e.g., `../../other-repo/file.py`): halt. "Task N references path outside repo root: <path>. Resolve before proceeding."

   **Why this gate exists:** Every ambiguity caught here saves one Implementer dispatch + SPEC_BLOCKER escalation + git reset cycle downstream.

3.7. **Build spec manifest (C1):**
   Call: `python3 <skill_dir>/scripts/build_spec_manifest.py <spec_path>`
   Capture stdout JSON. If parse fails: halt with `"spec_manifest build failed: <stderr>"`.

   Write to `<active>.spec_manifest`:
   ```json
   {
     "spec_path": "<spec_path>",
     "spec_total_chars": <int from stdout sum>,
     "sections": <parsed JSON>,
     "task_to_sections": {},  
     "fallback_policy": "<state.manifest_fallback arg-set; default 'full_spec_on_blocker'>"
   }
   ```

   `task_to_sections` starts empty here; it is populated at Step 6 (Compute task_to_sections — C1, added by Task 2). The Plan Reviewer (Step 6.5) validates downstream references.

4. **Assign risk levels** to each task:
   - `low` — isolated change, single file or module, no shared state, no API surface change
   - `mid` — touches 2+ modules, shared state, moderate coupling, or config changes
   - `high` — cross-cutting change, database/schema/API surface, or explicitly marked high-risk in plan

   Record: `Task 0: low | Task 1: mid | ...` in your internal notes.

   After initial assignment: if a LOW task touches any file already touched by an earlier LOW task in the same plan, upgrade the LATER task to MID. Record the upgrade reason. This prevents batch Verifier from accumulating file-level conflicts.

   If the user provided `risk=<level>` override: apply it to all tasks. However, if any task's description in the plan contains the words 'high-risk', 'schema migration', 'database', 'API surface', or 'breaking change': **(a)** echo a one-line warning to the orchestrator's stdout (interactive parent) — `WARN: risk=<level> override applied to task_<N>, but task description suggests HIGH risk. Proceeding with override as instructed.`; **(b)** append a structured entry to `<active>.risk_override_warnings[]` (initialize as `[]` if absent):
   ```json
   {"task": "task_<N>", "override": "<level>", "suggested_risk": "high",
    "matched_keywords": ["<word1>", "<word2>"], "ts": "<iso8601>"}
   ```
   Do not silently downgrade dangerous tasks. The Final Summary Report (Phase 2 Step 2) lists `risk_override_warnings` in a dedicated section if non-empty so the operator sees overrides retrospectively.

### Step 4.7: Local-env preflight (v2.11)

After risk assignment, before baseline test. Detection-only — never halts, never auto-copies.

1. **Unfilled local-config counterpart scan:**
   ```bash
   cd <worktree_path>
   for tmpl in $(find . -maxdepth 3 -type f \( -name '*.example' -o -name '*.template' -o -name '*.dist' \) 2>/dev/null); do
     real="${tmpl%.example}"
     real="${real%.template}"
     real="${real%.dist}"
     if [ ! -e "$real" ] && git check-ignore -q "$real" 2>/dev/null; then
       echo "MISSING_LOCAL_CONFIG: counterpart=$real template=$tmpl"
     fi
   done
   ```
   Each `MISSING_LOCAL_CONFIG:` line becomes a warning entry:
   ```json
   {"kind": "missing_local_config", "file": "<counterpart>", "template": "<template>",
    "suggestion": "Copy <template> to <counterpart> and fill in the local values",
    "detected_at": "<iso8601>"}
   ```

2. **Stale-dependency detection** — check each manifest/lockfile pair against its install marker:
   | Manifest | Lockfile | Install marker |
   |----------|----------|----------------|
   | `package.json` | `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` | `node_modules/.package-lock.json` |
   | `pyproject.toml` | `poetry.lock` / `uv.lock` | `.venv/pyvenv.cfg` or `venv/pyvenv.cfg` |
   | `Cargo.toml` | `Cargo.lock` | `target/.rustc_info.json` |
   | `build.gradle` / `build.gradle.kts` | `gradle/wrapper/gradle-wrapper.properties` | `.gradle/<version>/` or `build/` |

   For each pair: if lockfile mtime > install-marker mtime + 1s OR install-marker missing while lockfile exists → warning entry:
   ```json
   {"kind": "dependencies_likely_stale", "manifest": "<manifest>", "lockfile": "<lockfile>",
    "suggestion": "Run install before baseline (e.g., `npm install`, `poetry install`, `cargo fetch`).",
    "detected_at": "<iso8601>"}
   ```

3. **Record into state.json:**
   ```json
   "preflight_warnings": [<warning entries>]
   ```
   Always present; empty list when clean.

4. **One-line summary to user:**
   - clean → `Preflight: clean`
   - warnings → `Preflight: <N> warnings (see state.preflight_warnings)` followed by the bulleted list with `kind` + `file` + `suggestion`.

5. Never halt on preflight. ENV_BLOCKER triage (`references/escalation-playbook.md`) cross-references `state.preflight_warnings` when baseline or task tests fail — a `dependencies_likely_stale` warning matches a `module not found` symptom and short-circuits dependency-install triage.

5. **Take baseline test snapshot:**
   Before running: derive the test command from `Makefile`, `package.json`, `pyproject.toml`, or `Cargo.toml`. Record this exact command in **run-level** `state.test_command` (top-level — shared across all plans in a chain). Use this same command everywhere in the skill (Verifier prompts, Phase Transition batch Verifier). Verifiers do NOT need to re-derive the test command.

   Run the full test suite in the worktree before any changes:
   ```bash
   cd <worktree_path> && <test_command>
   ```
   Record `baseline: <N> passing, <M> failing` into **`<active>.baseline`** (resolves to `state.plan_chain[state.active_plan].baseline` for v2.13 multi-plan, top-level `state.baseline` otherwise). This is the regression reference for the CURRENT plan — multi-plan chains re-measure baseline at every Cross-Plan Trigger (Phase 2 Step -1) because each plan's starting state is the post-completion HEAD of its predecessor.

6. **Build dependency graph and identify compaction points:**
   For each task, note which prior tasks it depends on (by shared files or logical data flow). Record:
   ```
   Task 0: deps=[]
   Task 1: deps=[Task 0]
   Task 2: deps=[]          ← independent of Task 1
   Task 3: deps=[Task 1, Task 2]
   ```
   Mark **compaction points** — tasks after which no later task depends on any earlier task's raw details. At each compaction point you will: (a) run a batch Verifier for accumulated LOW tasks, (b) dispatch a Phase Docs Updater, and (c) write a state anchor and drop prior context. Explicit plan phase boundaries are always compaction points.

   - **When in doubt, be conservative:** If dependency analysis is unreliable for any segment, treat tasks as DEPENDENT and restrict compaction points to explicit plan phase boundaries. `compaction_points` must always include the index of the final task (or the final task before Phase 2). Fewer compaction points are safer than wrong ones.
   - **SKIPPED propagation:** If task X is SKIPPED, automatically mark all tasks with X in their deps as SKIPPED as well. Record each propagated SKIPPED with reason 'dependency task_X was SKIPPED'.
   - **Compute task_to_sections (C1):** For each task in the plan, populate `<active>.spec_manifest.task_to_sections[task_id]`:

     a. Parse task body for `**Spec Refs:**` block (comma-separated section IDs, e.g. `**Spec Refs:** S1.2, S3.1`). If present: use those IDs verbatim. Validate each in `spec_manifest.sections` — any unknown ID is recorded as a Plan Reviewer **BLOCKER** input (consumed at Step 6.5).

     b. Else (heuristic from **Files:** block): for each file in the task's Files block, compare path components against each `spec_manifest.sections[*].title` (case-insensitive substring match). Collect and dedupe matches across all files.

     c. If step b yields no matches: set the entry to `{"sections": ["*"], "fallback_used": true}` — the Implementer will receive the full spec for this task. Otherwise: `{"sections": [<ids>], "fallback_used": false}`.

     Write final values into `<active>.spec_manifest.task_to_sections`. Unknown-ID rows from step (a) are still written (with the unknown IDs intact) so the Plan Reviewer in Step 6.5 can see and BLOCKER them.

   - **Compute `global_constraints.shared_files`:** Build a map of file → list of task IDs that touch it (from each task's `**Files:**` block). Keep only files referenced by ≥ 2 tasks. Write this to **`<active>.global_constraints.shared_files`** in Step 7 (top-level `state.global_constraints.shared_files` for single-plan; `state.plan_chain[state.active_plan].global_constraints.shared_files` for multi-plan). The Implementer template's *Shared files alert* reads from the same resolved path.

   - **Compute `task_complexity` (P5 — effort scaling):** For each task, derive a complexity bucket SMALL / MEDIUM / LARGE used to scale the Implementer prompt at Phase 1 Step 1.

     Inputs per task:
     - `file_count` = number of paths in **Files:** block
     - `spec_chars` = character count of the relevant spec excerpt assigned to this task (rough LOC proxy)
     - `new_decls` = count of new functions, types, constants, or APIs the spec/task names as outputs of this task (parse for "introduce", "add function", "new type", `\bnew\b` headers, function-arrow definitions in spec code blocks)
     - `risk_mult` = 1 (LOW), 2 (MID), 3 (HIGH)

     Bucket rule (apply in order — first match wins):
     | Condition | Bucket |
     |-----------|--------|
     | `file_count == 1` AND `spec_chars < 1200` AND `new_decls <= 1` AND `risk_mult == 1` | SMALL |
     | `file_count >= 4` OR `risk_mult == 3` OR `new_decls >= 4` | LARGE |
     | (else) | MEDIUM |

     Heuristic biases upward — under-instructing is worse than mild over-engineering. Record per-task: `<active>.task_complexity.task_N = "SMALL" | "MEDIUM" | "LARGE"`.

     Effort-guidance strings (the Implementer prompt at Phase 1 Step 1 injects one of these into `{effort_guidance}`):
     - SMALL: `aim for ≤8 tool calls; TDD is still required for executable code or behavior; docs/config/generated-only tasks may mark TDD not applicable; do not add abstractions, helpers, or refactors`
     - MEDIUM: `aim for 10–25 tool calls; use TDD for executable code or behavior; refactor only what the task touches`
     - LARGE: `aim for 25–60 tool calls; use TDD for executable code or behavior; if you exceed 60 tool calls without DONE, ESCALATE with AMBIGUITY rather than continue`

   - **Compute `execution_plan` — waves + parallel groups (P2 — parallel dispatch):**

     After the dependency graph is built, compute waves greedily:
     - Wave 0 = all tasks with `deps == []`
     - Wave N = all tasks whose deps are all in waves 0..N-1
     - Tasks within a wave have no inter-dependency by construction.

     Within each wave, partition tasks into **parallel groups** by file-disjointness:
     1. Start with each task as its own singleton group.
     2. Greedily merge two groups iff the UNION of their declared `Files:` sets has no overlap AND no task in either group has a `serial: true` annotation in the plan.
     3. Tasks whose Files: blocks overlap any other in the same wave MUST stay in their own singleton group (run sequentially within the wave).

     **v2.11 — `resource_key` partition rule:**

     A task may declare `**Resource Key:** <slug>` in its task body (similar to `**Files:**`). Slug is lowercased and whitespace-stripped. Examples: `gradle-test-output`, `db-port-5432`, `playwright-browser`.

     After file-disjointness merging, before finalizing the wave's parallel groups:

     1. Build a `resource_key → [task_ids]` map for tasks in this wave.
     2. For each key with ≥ 2 task IDs in the same wave:
        - Move each affected task to its own singleton group within the wave. If a multi-task group contained two collision-tagged tasks, split into singletons.
        - Annotate each resulting singleton group in `<active>.execution_plan` with `"serialization_reason": "resource_key=<key>"`.

     The wave still respects the file-disjointness invariant (groups within a wave never share files). Splits only widen serialization — they never merge file-overlapping tasks.

     Tasks with no `Resource Key:` block are unaffected. The annotation is opt-in.

     Write to `<active>.execution_plan`:
     ```json
     [
       {"wave": 0, "parallel_groups": [["task_0", "task_2"], ["task_1"]]},
       {"wave": 1, "parallel_groups": [["task_3"], ["task_4"]]}
     ]
     ```

     Each inner list is one parallel group: a single-element list means standard sequential execution; a multi-element list triggers the Parallel Sub-Flow in Phase 1.

     **Disable parallel dispatch via** skill argument `parallel=off` — write a degenerate `execution_plan` where every task is its own singleton group preserving plan order. Use this as a fallback when sub-worktree creation is constrained (e.g., shallow clones).

6.5. **Plan Reviewer preflight (P3 — mechanical plan audit):**

   Skip this step if the user passed `preflight=off` in skill arguments (regression runs of already-validated plans).

   Build the Plan Reviewer prompt from `references/plan-reviewer-prompt.md`. Fill in:
   - `{plan_path}`, `{plan_full_text}` — the plan document
   - `{spec_manifest_json}` — the rendered JSON of `<active>.spec_manifest` (sections + task_to_sections; built in Steps 3.7 and 6) for the spec_manifest rubric items (C1)
   - `{spec_path}`, `{spec_full_text}` — the spec document
   - `{risk_levels_yaml}` — from Step 4 (YAML-formatted `task_N: <risk>`)
   - `{result_json_path}` — `<orch_dir>/plan_review.json`

   **Dispatch mode (v2.22 §2.B1):** branch on `state.dispatch_config.plan_reviewer` (default `"agent"` in v2.25; `"api"`/`"p"` remain selectable):
   - `"agent"` (default, v2.25) → dispatch the Plan Reviewer in-session via the
     Agent tool per `references/cross-cutting/agent-dispatch.md` with
     ROLE=plan_reviewer, MODEL=opus (honor `dispatch_config.plan_reviewer_model`),
     PROMPT_TEMPLATE=`references/plan-reviewer-prompt.md`, RESULT_PATH=
     `<orch_dir>/plan_review.json`. Read + validate the result exactly as the
     metered paths do. Plan Reviewer is advisory: a missing/invalid result after
     the failure ladder's retry+api-fallback logs a warning and proceeds (no halt).
   - `"api"` → dispatch via `scripts/dispatch_via_api.py --role plan_reviewer --task-context <orch_dir>/plan_review_ctx.json --output <orch_dir>/plan_review.json --model <selected-model> --orch-dir <orch_dir>`. Write the placeholder values (`plan_path`, `plan_full_text`, `spec_path`, `spec_full_text`, `risk_levels_yaml`, `spec_manifest_json`, `result_json_path`) into `<orch_dir>/plan_review_ctx.json` first; the helper splits the cached scaffold from the per-invocation payload, forces structured output via the `report_plan_reviewer` tool, accumulates cost, and emits the `kws-cme.dispatch_via_api` AgentLens event. An ENV_BLOCKER ESCALATE result (`status: "ESCALATE"`, `type: "ENV_BLOCKER"`) means the API failed after 3 retries — do NOT silently fall back to `-p`; surface it so the user can rerun with `dispatch_config.plan_reviewer="p"`.
   - `"p"` → use the legacy path below.

   **Legacy dispatch headless** (`dispatch_config.plan_reviewer == "p"`) via `claude -p --dangerously-skip-permissions` (same pattern as Verifier — Phase 1 Step 3). Prompt path: `<orch_dir>/plan_review_prompt.txt`. Result path: `<orch_dir>/plan_review.json`. Missing/malformed result → log warning and proceed (Plan Reviewer is advisory; absence is NOT a halt).

   **Model selection (forensics):** the Plan Reviewer runs on `claude-opus-4-8` by default (v2.25; mechanical rubric but Opus per the executor's Opus-everywhere preference; overridable via `state.dispatch_config.plan_reviewer_model`). The orchestrator records the selected model into `state.plan_review.model_used` (`model_used` token) so later analysis can attribute review decisions to the exact model used. Selection logic lives in `scripts/dispatch_plan_reviewer.py`.

   **Parse the result:**

   - `status: "PASS"` → record `<active>.plan_review = {status: "PASS", warnings: []}` at Step 7. Proceed.
   - `status: "ISSUES_FOUND"` →
     - Partition issues by severity: `BLOCKER` vs `WARN`.
     - All `WARN` only: record `<active>.plan_review = {status: "WARN", warnings: [...]}`. Log to user as a one-line summary. Proceed.
     - Any `BLOCKER`: ask the user ONE batched question with all blocker issues listed:
       ```
       Plan Reviewer found <N> BLOCKER issue(s) that will likely cause SPEC_BLOCKER escalations during Phase 1:
         1. [task_<id> / <category>] <description>
            evidence: <file:line>
            suggested fix: <one-sentence fix>
         ...
       Proceed anyway, halt for manual fix, or auto-apply each `suggested_fix` (max 2 retry cycles)?
       ```
       Halt until answered. If user picks auto-apply: edit plan/spec per each `suggested_fix`, re-read both documents, re-dispatch Plan Reviewer (max 2 cycles). If still ISSUES_FOUND after 2 cycles: halt with manual-fix message.

   **Why this gate exists:** every BLOCKER caught here costs ~30s + 5k tokens; each one missed costs one Implementer dispatch + SPEC_BLOCKER escalation + git reset (~2–3 min + tokens).

6.7. **Scaffold byte-stability lint (v2.22 §2.B1 — MANDATORY when scaffold markers are used):**

   Once the role prompts are prepared (Step 6.5), and before state.json is initialized, the Orchestrator MUST lint every role-prompt file that carries the SCAFFOLD/PAYLOAD markers — i.e. every `references/<role>-prompt.md` consumed by `scripts/dispatch_via_api.py` (`plan_reviewer`, `verifier`, `docs_updater`, `transition_combined` as each role is migrated). The `dispatch_via_api.py` path splits the cacheable SCAFFOLD from the per-dispatch PAYLOAD; if the checked-in scaffold drifts from the SCAFFOLD region, the Anthropic prompt-cache prefix misses silently on every dispatch (no error, just lost savings). This lint is the only thing that catches that drift before a run.

   For each such prompt file:
   ```bash
   python3 <skill_dir>/scripts/validate_scaffold_split.py references/<role>-prompt.md
   ```
   The linter enforces, byte-exact: all four markers present exactly once in order; the sibling `references/_scaffolds/<role>-scaffold.md` (role underscored) matches the SCAFFOLD region byte-for-byte; the SCAFFOLD region is `{`-free (placeholder-free cache prefix); and stripping only the marker lines reassembles the original.

   **A non-zero exit halts setup as an ENV_BLOCKER** (it is an environment/contract defect, not a plan defect — handle per `references/escalation-playbook.md`). Do NOT proceed to Step 7 with a failing scaffold split: dispatching against a drifted scaffold would burn full input-token cost on every headless role for the entire run. Surface the linter's stderr (`SCAFFOLD_LINT_FAIL:` lines) verbatim so the operator can repair the prompt/scaffold pair and rerun.

7. **Initialize state file:**
   ```bash
   mkdir -p <orch_dir>
   ```
   `<orch_dir>` was already created in Step 2 alongside the worktree; this mkdir is idempotent and defends against resume paths that may have skipped Step 2.

   **Branch on plan count (v2.13):**

   *Single-plan run* (`state.plan_chain` was NOT written by Phase -1 step b, OR this is a fresh interactive run with one plan): write state.json in v2.12 shape. The fields below populate top-level — `tasks`, `risk_levels`, `compaction_points`, etc. all live at the root of state.json. `active_plan = "plan1"` (string, v2.12 form).

   *Multi-plan run* (`state.plan_chain` IS present from Phase -1 step b, OR this is a fresh interactive run with `plan2=` or beyond): write state.json with `plan_chain[]` as the source of truth. Populate the CURRENT plan's entry (`plan_chain[state.active_plan]`) with the same fields v2.12 wrote at the top level — `tasks`, `task_summaries`, `risk_levels`, `task_complexity`, `compaction_points`, `execution_plan`, `global_constraints`, `quality_trend`, `low_tasks_pending_verification`, `last_compaction_after_task`, `plan_review`. Top-level `tasks` etc. are NOT written for multi-plan runs — code reads through `state.plan_chain[state.active_plan]`. `active_plan` is an integer index (0, 1, 2, ...).

   Write `<orch_dir>/state.json` using the Write tool. Schema below shows the SINGLE-PLAN shape; multi-plan moves the per-plan fields into `plan_chain[active].*`:

   ```json
   {
     "schema_version": "2",
     "mode": "<interactive_session | headless_running>",
     "active_plan": "plan1",
     "plan": "<plan path>",
     "spec": "<spec path>",
     "branch": "<branch name>",
     "worktree": "<worktree path — $HOME/.claude/worktrees/<RUN_ID>>",
     "orchestrator_dir": "<orch_dir path — $HOME/.claude/orchestrator/<RUN_ID>>",
     "source_repo": "<canonical git common dir of the source repo — repo-scoped exclusivity key (v2.20)>",
     "test_command": "<derived in Phase 0 baseline step>",
     "baseline": {"passing": 0, "failing": 0},
     "risk_levels": {},
     "compaction_points": [],
     "execution_plan": [],
     "task_header_prefix": "### ",
     "global_constraints": {
       "shared_files": {}
     },
     "plan_review": {"status": "SKIPPED", "warnings": []},
     "implementer_model": {"used": "<sonnet | opus>", "default": "sonnet"},
     "task_complexity": {},
     "quality_trend": [],
     "tasks": {},
     "task_summaries": {},
     "spec_edits": [],
     "low_tasks_pending_verification": [],
     "last_compaction_after_task": -1,
     "last_completed_task": null,
     "last_completed_at": null,
     "current_task": 0,
     "current_step_within_task": 1,
     "current_pre_task_sha": null,
     "current_pre_group_sha": null,
     "current_review_retries": 0,
     "current_verifier_retries": 0,
     "current_escalation_count": 0,
     "current_previous_issues": [],
     "phase_summaries": [],
     "phase_doc_commits": [],
     "chain_resume": null,
     "budget_cap_usd": null,
     "budget_action": "warn",
     "dispatch_config": {
       "plan_reviewer": "agent", "verifier_batch": "agent", "verifier_per_task": "agent",
       "transition_combined": "agent", "docs_updater_phase": "agent", "docs_updater_final": "agent",
       "final_sweep": "agent", "plan_reviewer_model": null
     },
     "verification_gaps": [],
     "docs_gaps": [],
     "cost_ledger": {
       "by_task": {},
       "by_role": {},
       "by_model": {},
       "totals": {
         "input_tokens": 0,
         "output_tokens": 0,
         "cached_read_tokens": 0,
         "cached_write_tokens": 0,
         "cost_usd": 0.0,
         "dispatches": 0
       }
     },
     "archive": null,
     "agentlens_orchestration_run": null,
     "agentlens_healthy": null,
     "context_budget": {
       "effective_input_budget": 170000,
       "threshold_ratio": 0.60,
       "threshold_tokens": 102000,
       "last_evaluation_at": null,
       "last_evaluation_tokens": 0
     },
     "timestamps": {
       "started_at": null,
       "completed_at": null
     }
   }
   ```

   **Run-level `context_budget` (v2.15 — C3):** lives at the TOP of state.json (NOT inside any `plan_chain[i]`), like `cost_ledger`. Defaults: `effective_input_budget=170000`, `threshold_ratio=0.60`, `threshold_tokens=102000`. If the user passed `context_budget=<int>`: overwrite `effective_input_budget`. If `context_threshold=<float>`: overwrite `threshold_ratio`. After either override, recompute `threshold_tokens = round(effective_input_budget * threshold_ratio)`. The chained orchestrator preserves this block on resume.

   Fill in the actual values from steps 4–6.

   **Run-level `dispatch_config` + per-plan gap fields (v2.25):** `dispatch_config` is run-level (top of state.json, preserved across plan_chain swap); any gate the user passed explicitly, or any Phase -1 detach reconciliation, is applied before this write and must NOT be overwritten. `verification_gaps`/`docs_gaps` are per-plan (live under `plan_chain[active]` for multi-plan runs).

   **Run-level cost/budget/archive fields (v2.14):** the four fields `cost_ledger`, `budget_cap_usd`, `budget_action`, and `archive` are **RUN-LEVEL** — they live at the top of `state.json` and span the entire orchestrator invocation, including every plan in a multi-plan chain. They are NOT per-plan and MUST NOT be duplicated inside `plan_chain[i]`. `cost_ledger.by_task` is keyed `"<plan_index_or_'top'>::<task_id>"` so a single ledger covers the chain. `budget_cap_usd` is a number (USD) or `null` (no cap). `budget_action ∈ {"pause", "warn", "off"}` controls behavior when the cap is crossed. `archive` defaults to `null` and is populated by the post-run forensics archive step (v2.14).

   **Cost auto-waive (v2.28, D001) — deterministic, not a judgement.** After
   `dispatch_config` is set (above), compute whether any role gate is metered:

   ```
   metered = any(dispatch_config[g] in ("api","p") for g in dispatch_config)
   if state.mode == "interactive_attached" and not metered:
       state_set.py  cost_tracking_waived = true
       state_set.py  cost_tracking_waive_reason = "agent-dispatch-no-usage"
   ```

   The Agent tool returns no `usage` to the orchestrator, so an all-`agent`
   attached run *cannot* populate the ledger — the waive is honest, set once,
   machine-readable. A run with any `api`/`p` gate is left un-waived and must
   accumulate real cost. Write both fields with `scripts/state_set.py` (atomic);
   do NOT hand-type the waive. The waive is derived purely from `dispatch_config`
   + `mode`, not from any model judgement.

   **Honest limitation:** auto-waiving cost also disables `budget_cap_usd`
   enforcement and the token-based chain-resume trigger on the default path,
   because both read the now-empty ledger. This is the accepted cost of the
   agent-pool default; users who need budget enforcement opt a gate into
   `api`/`p` (which un-waives the run and re-enables both).

   **Run-level AgentLens orchestration field (v2.17):** `agentlens_orchestration_run` is a `string | null` — the AgentLens run ID opened by Phase -1 step b via `agentlens run-open`. It is RUN-LEVEL (top of state.json, NOT inside `plan_chain[i]`); a single orchestrator invocation owns at most one AgentLens orchestration run regardless of plan chain length. If AgentLens was unavailable at Phase -1 step b the field is `null` and all subsequent emit sites no-op. Preserved across plan_chain swap and Resume Chain handoff. Already initialized in the minimal state.json from Phase -1 step b; this Step 7 write must preserve whatever was written there (do NOT reset to `null`).

   **Run-level AgentLens health field (v2.21):** `agentlens_healthy` is a `bool | null` — the result of the one-shot reachability probe run at Phase -1 step b (`true` iff `agentlens run-open` returned a non-empty run ID, i.e. CLI present AND registry write succeeded; `false` otherwise). It is RUN-LEVEL (top of state.json, NOT inside `plan_chain[i]`) and preserved across plan_chain swap / Resume Chain handoff exactly like `agentlens_orchestration_run`. Its purpose is post-run forensics: an empty AgentLens event stream is ambiguous (nothing happened vs. every emit silently no-op'd on an unreachable CLI), and this boolean disambiguates. `null` means the probe never ran (pre-v2.21 state.json); treat `null` like `false` for audit purposes. Already written by Phase -1 step b; this Step 7 write must preserve it (do NOT reset).

   **Multi-plan shape (v2.13):** when `plan_chain` exists, the equivalent state.json is:

   ```json
   {
     "schema_version": "2",
     "mode": "<...>",
     "active_plan": 0,
     "plan": "<plan_path_0 — mirrors plan_chain[0] for legacy readers>",
     "spec": "<spec_path_0 — mirror>",
     "branch": "...",
     "worktree": "<$HOME/.claude/worktrees/<RUN_ID>>",
     "orchestrator_dir": "<$HOME/.claude/orchestrator/<RUN_ID>>",
     "source_repo": "<canonical git common dir of the source repo — repo-scoped exclusivity key (v2.20)>",
     "test_command": "<shared across all plans — derived once>",
     "implementer_model": {"used": "...", "default": "sonnet"},
     "plan_chain": [
       {
         "index": 0, "plan_path": "...", "spec_path": "...",
         "status": "running", "blocked_until": null,
         "baseline": {"passing": N, "failing": M},
         "tasks": {"task_0": {...}, ...},
         "task_summaries": {...},
         "risk_levels": {...},
         "task_complexity": {...},
         "compaction_points": [...],
         "execution_plan": [...],
         "global_constraints": {"shared_files": {...}},
         "quality_trend": [...],
         "low_tasks_pending_verification": [...],
         "last_compaction_after_task": -1,
         "last_completed_task": null,
         "last_completed_at": null,
         "plan_review": {"status": "PASS", "warnings": []}
       },
       {
         "index": 1, "plan_path": "...", "spec_path": "...",
         "status": "queued", "blocked_until": "plan_chain[0].all_tasks_complete_or_skipped",
         "baseline": null, "tasks": {}, "task_summaries": {}, "...": "..."
       }
     ],
     "spec_edits": [...],
     "current_task": 0,
     "current_step_within_task": 1,
     "current_pre_task_sha": null,
     "current_pre_group_sha": null,
     "current_review_retries": 0,
     "current_verifier_retries": 0,
     "current_escalation_count": 0,
     "current_previous_issues": [],
     "phase_summaries": [],
     "phase_doc_commits": [],
     "chain_resume": null,
     "budget_cap_usd": null,
     "budget_action": "warn",
     "cost_ledger": {
       "by_task": {},
       "by_role": {},
       "by_model": {},
       "totals": {
         "input_tokens": 0,
         "output_tokens": 0,
         "cached_read_tokens": 0,
         "cached_write_tokens": 0,
         "cost_usd": 0.0,
         "dispatches": 0
       }
     },
     "archive": null,
     "agentlens_orchestration_run": null,
     "agentlens_healthy": null,
     "timestamps": {"started_at": "...", "completed_at": null}
   }
   ```

   Note: in the multi-plan shape, `budget_cap_usd`, `budget_action`, `cost_ledger`, `archive`, `agentlens_orchestration_run`, and `agentlens_healthy` appear at the TOP level (siblings of `plan_chain`, NOT inside any `plan_chain[i]` entry). See the "Run-level cost/budget/archive fields (v2.14)" and "Run-level AgentLens orchestration field (v2.17)" paragraphs above — these fields are shared across all plans in the chain.

   For multi-plan runs at the START of Phase 0 (active_plan == 0): populate `plan_chain[0]` with all the data Steps 3–6 produced for plan 0. Other plan_chain entries (i ≥ 1) keep their `status: "queued"` placeholders and only become populated when their swap fires at Phase 2 Step -1.

   **Mode field rule (P13a):** `mode` MUST always be a string — never `null`. Set to `"interactive_session"` when not under Phase -1 self-spawn, `"headless_running"` immediately after Phase 0 completes under `headless_pending` resume.

   **Active task tree resolution rule (v2.13):** every subsequent step in Phase 1 / Phase Transition / Phase 2 that reads or writes "the current plan's tasks/summaries/quality_trend/etc." MUST do so through this resolution:

   - `state.plan_chain` exists → active tree is `state.plan_chain[state.active_plan]`. Read `state.plan_chain[state.active_plan].tasks` (not top-level `state.tasks`). Same for task_summaries, quality_trend, risk_levels, compaction_points, execution_plan, global_constraints, low_tasks_pending_verification, last_compaction_after_task, last_completed_task, last_completed_at, plan_review.
   - Otherwise → single-plan. Read top-level fields.

   All earlier prose in this SKILL.md that says "read `state.tasks`" or "write to top-level `quality_trend`" should be interpreted with this resolution rule applied. In a multi-plan run `active_plan` is an integer index into `plan_chain[]` (≥ 1 selects a later plan).

   **`implementer_model` field rule (v2.12):**

   Two cases by entry path:

   - **You are the headless child (resume from `mode=headless_pending`)**: `state.implementer_model` was already written by the interactive parent at Phase -1 step b. **Read it from state.json. Do NOT re-parse skill args** — the original args are not available to you, only the headless prompt text. Preserve the field as-is.
   - **You are an interactive run (no headless self-spawn — `mode=interactive` was passed, OR you are the parent during Phase -1 itself)**: parse the optional `implementer_model=<opus|sonnet>` skill argument. Case-insensitive. Unknown values → halt with: "Unknown implementer_model=<value>. Allowed: opus, sonnet." Set `state.implementer_model.used = <parsed value, or "sonnet" if not provided>`. Set `state.implementer_model.default = "sonnet"` literally — this records what the skill would have dispatched in the absence of an override at the time of this run. Do NOT compute `default` from the args.

   On a Phase 2 Step -1 `plan_chain` swap: do NOT reset this field. Every plan in the chain inherits the same Implementer model selection within one orchestrator invocation.

7.5. **Phase 0 boundary emit (v2.17 — MANDATORY):**

   **DO NOT SKIP THIS STEP.** This is a required Phase 0 checkpoint, equivalent in priority to git worktree creation and state.json initialization. Even on simple single-task plans, even when the plan looks trivial, even under headless `claude -p`, you MUST execute this block in the orchestrator session before any Phase 1 work begins. Skipping it disables institutional-memory observability for the entire run (no `kws-cme.phase_0_started` event in AgentLens) and is the most reproducible adherence regression observed historically (v2.8 F001 Smoke B).

   v2.17 cutover note: pre-v2.17 versions also ran `scripts/append_learning_event.py init-run` here to create a parallel `~/.claude/learning/.../events.jsonl`. That helper was removed in Task 11 after AgentLens parity was verified. AgentLens is now the sole event sink; `ORCH_RUN_ID` (opened at Phase -1 step b) is the run identifier for the entire orchestrator invocation.

   **Emit `kws-cme.phase_0_started` via `phase_boundary.py` (v2.21 — D002 enforcement):**

   Do NOT hand-write the emit + timestamp as separate prose steps (that is the exact shape of the historical silent-skip). Call the boundary helper, which bundles the emit AND the paired `timestamps.started_at` stamp into one atomic, eval-checkable call:

   ```bash
   TASK_COUNT=$(jq -r 'if .plan_chain then .plan_chain[.active_plan] else . end | (.tasks | length)' "$ORCH_DIR/state.json" 2>/dev/null || echo 0)
   python3 <skill_dir>/scripts/phase_boundary.py phase-emit \
     --state "$ORCH_DIR/state.json" \
     --run-id "${ORCH_RUN_ID:-}" \
     --type phase_0_started \
     --payload-json "$(jq -nc \
       --arg plan "$PLAN_PATH" \
       --arg spec "$SPEC_PATH" \
       --argjson tasks "${TASK_COUNT:-0}" \
       '{plan:$plan, spec:$spec, task_count:$tasks}')"
   ```

   What the helper guarantees (so the prose no longer has to): it emits `kws-cme.phase_0_started` (taxonomy name verbatim — it fires at END of Phase 0, about to enter Phase 1; don't rename) AND `setdefault`s `state.timestamps.started_at` to now if still null/absent (preserving any earlier real start). The emit is best-effort: an empty `--run-id` (AgentLens CLI absent or registry write failed at Phase -1 step b) makes the emit a no-op while the timestamp stamp still succeeds; a non-zero `agentlens` exit is swallowed. A non-zero exit from the helper itself means the *state write* failed — treat it as a hard halt. **Failure to invoke this helper IS the regression we are guarding against.**

   Sub-agents do NOT publish to AgentLens directly. They write event candidate JSON files to `<orch_dir>/learning_events/<task_id>-<role>.json`. The orchestrator scans this directory after each cycle step (Phase 1 Step 3.5) and publishes each candidate to AgentLens as `kws-cme.<event_type>`. See `references/learning-log.md` for the schema and event types.

   **active_plan pointer (P13b + v2.13):** Single-plan run: `"plan1"` (string). Multi-plan run: integer index `0, 1, 2, ...` into `state.plan_chain[]`. All Phase 1 / Phase Transition / Phase 2 / Monitor code MUST resolve through `<active>` per the placeholder rule. Phase 2 Step -1 swaps this pointer at every cross-plan boundary.

   **Subsequent plan entries (multi-plan):** when invocation includes `plan2=`/`planN=`, the queued `plan_chain[i]` entries (i ≥ 1) are constructed by Phase -1 step b with `status: "queued"` and `blocked_until: "plan_chain[i-1].all_tasks_complete_or_skipped"`. Phase 0 Step 7 does NOT build them — it only populates the *current* plan's entry (`plan_chain[state.active_plan]`). Each queued entry is filled with full per-plan data when its swap fires at Phase 2 Step -1.

   Each task entry written into `<active>.tasks` (resolving to top-level `tasks` for single-plan, or `plan_chain[N].tasks` for multi-plan, per the resolution table) later uses this format:
   ```json
   "task_N": {
     "status": "COMPLETE | SKIPPED | IN_PROGRESS",
     "risk": "<level>",
     "complexity": "SMALL | MEDIUM | LARGE",
     "files": [],
     "files_test": [],
     "commit": "<sha>",
     "pre_task_sha": "<sha>",
     "escalations": 0,
     "review_retries": 0,
     "verifier_retries": 0,
     "spec_clarifications": 0,
     "spec_score": null,
     "quality_score": null,
     "review_tier": null,
     "timing": {
       "started": null,
       "implementer_done": null,
       "reviewer_done": null,
       "verifier_done": null,
       "completed": null
     }
   }
   ```

   `files_test` (Previous #3): list of test-file paths the Implementer touched, separated from `files` (the broader change set). Populated from Implementer's `FILES_TEST_CHANGED:` output. Phase Transition T1 pre-filter uses this — if empty AND `files` are all `.md`, the task is treated as docs-only.

   `spec_clarifications` (P15): per-task counter for the spec-edit branch in Step 2, kept distinct from `review_retries` so spec issues don't burn the implementer-retry budget.
