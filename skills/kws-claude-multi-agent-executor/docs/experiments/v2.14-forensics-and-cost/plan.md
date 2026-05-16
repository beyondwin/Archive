# v2.14 — Forensics & Cost (Implementation Plan)

**Spec**: `docs/experiments/v2.14-forensics-and-cost/spec.md` · **Target version**: `2.14.0` · **Test command**: `bash scripts/run-tests.sh` (or skill's derived default)

---

## Phase 1 — F2 (cost foundation) — must land first

v2.15 depends on the cost ledger; v2.14 F3/F4 also consume the same fields. F2 is the schema-change-heaviest piece — landing it first keeps later tasks additive.

### Task 0: Create price table module

**Files:**
- `scripts/price_table.py` (new)

Create the module per spec §F2.5. Hardcode `PRICES`, `ALIASES`, and the two functions `get_price(model_id, kind)` and `compute_cost(model_id, usage)`. Include a module-level docstring stating "Frozen pricing — update on Anthropic rate change. Historical runs preserve commit-time rates." Module must be importable both as `from price_table import compute_cost` (when scripts/ on path) and via direct path execution.

**Acceptance Criteria:**

```bash
python3 -c "import sys; sys.path.insert(0, 'scripts'); from price_table import compute_cost, get_price; \
  assert abs(get_price('sonnet', 'input_per_mtok') - 3.00) < 0.001; \
  assert abs(get_price('opus', 'output_per_mtok') - 75.00) < 0.001; \
  assert get_price('unknown', 'input_per_mtok') == 0.0; \
  c = compute_cost('sonnet', {'input_tokens': 2_000_000, 'output_tokens': 1_000_000, 'cached_read_tokens': 0, 'cached_write_tokens': 0}); \
  assert 20.99 < c < 21.01, c"
```

**Risk**: LOW (isolated new file).

---

### Task 1: Extend Phase 0 Step 7 state.json initialization

**Files:**
- `SKILL.md` (Phase 0 Step 7 single-plan + multi-plan shape blocks)

Add to both the single-plan and multi-plan state.json initializer blocks in Phase 0 Step 7:

```json
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
"archive": null
```

These are run-level fields (top-level), NOT per-plan — explicitly state this in the surrounding prose. Update Phase 0 Step 0 resume protocol prose to specify defaults for legacy state.json: `setdefault('cost_ledger', <init>)`, `setdefault('budget_cap_usd', None)`, `setdefault('budget_action', 'warn')`, `setdefault('archive', None)`.

**Acceptance Criteria:**

```bash
grep -A 2 'budget_cap_usd' SKILL.md | grep -q '"warn"'
grep -A 5 'cost_ledger' SKILL.md | grep -q '"totals"'
grep -B 2 'setdefault.*cost_ledger' SKILL.md
```

**Risk**: MID (touches both single-plan and multi-plan schema blocks; reviewers must verify both updated).

**Depends on**: Task 0.

---

### Task 2: Extend Phase -1.0 Pass 1 argument parser

**Files:**
- `SKILL.md` (Phase -1.0 Pass 1 — "Recognized keys" list)

Add `budget`, `budget_action` to the recognized keys enumeration. Add validation prose:

> "`budget=<USD>` is a positive float or zero. Negative → halt with `Invalid budget=<value>; must be ≥ 0.`
> `budget_action=<value>` must be one of `pause`, `warn`, `off`. Else halt with `Unknown budget_action=<value>. Allowed: pause, warn, off.`
> NL lexicon: no entries added for budget — explicit-only by design."

Also extend the Phase -1.0 echo line format to include `budget=<value or "off">` so the user sees it before detach.

**Acceptance Criteria:**

```bash
grep -E 'budget=<USD>' SKILL.md
grep -E 'budget_action.*pause.*warn.*off' SKILL.md
grep -E 'echo.*budget' SKILL.md  # echo line update
```

**Risk**: LOW.

**Depends on**: Task 1.

---

### Task 3: Implement Phase 1 Step 4 cost accumulation

**Files:**
- `SKILL.md` (Phase 1 Step 4 — Agent Cleanup section)

Insert a new substep before "Update state file" (current step 2):

```
1.5. Accumulate cost (F2):
  For the just-completed Agent tool dispatch (Implementer / Combined Reviewer), extract `usage`
  from the Agent result. For just-completed headless subprocess (Verifier / Plan Reviewer / Docs Updater),
  parse final `result` stream-json line from <name>.stdout.

  Compute:
    cost_usd = compute_cost(model, usage) via scripts/price_table.py
    key = "<active_plan>::<task_id>"

  Update state.cost_ledger atomically:
    by_task[key] = {input_tokens, output_tokens, cached_read_tokens, cached_write_tokens,
                    cost_usd, model, role, dispatched_at}
    by_role[<role>]  += increments
    by_model[<model>] += increments
    totals            += increments

  Failure modes:
    - Missing usage block → record entry with zeros, model="unknown", role="<role>". Do not halt.
    - state.json write failure → existing hard-halt rule applies (state-file write guardrail).
    - price_table import failure → log warning, record cost_usd=0.0, continue.
```

Reference `scripts/price_table.py` explicitly.

**Acceptance Criteria:**

```bash
grep -B 1 -A 15 'Accumulate cost' SKILL.md | grep -q 'compute_cost'
grep -A 3 'Accumulate cost' SKILL.md | grep -q 'price_table'
```

**Risk**: MID (touches the hot per-task loop; reviewers must verify no extra writes interfere with two-phase commit guard).

**Depends on**: Tasks 0, 1.

---

### Task 4: Implement Phase Transition T3 budget evaluation

**Files:**
- `SKILL.md` (Phase Transition T3 — between current Step 2 and Step 3)

Insert a new substep T3 step 2.5:

```
2.5. Evaluate budget (F2):
  If state.budget_action == "off" OR state.budget_cap_usd is None: skip.
  Else if state.cost_ledger.totals.cost_usd >= state.budget_cap_usd:
    If state.budget_action == "warn":
      Emit context_health learning event with severity=high, issue_key=budget_warning,
      summary="Budget warning: ${totals} of ${cap} cap consumed."
      Continue execution.
    If state.budget_action == "pause":
      Call close-run --outcome=blocked.
      Write HEADLESS_HALTED.txt with first line "reason: budget_exceeded".
      Exit orchestrator (headless child) or halt (interactive).
```

Also add the same check at Phase 2 Step 0 BEFORE batch verifier dispatch — last chance to halt before incurring more cost.

**Acceptance Criteria:**

```bash
grep -B 1 -A 12 'Evaluate budget' SKILL.md | grep -q 'budget_exceeded'
grep -A 5 'Phase 2 Step 0' SKILL.md | grep -q 'budget'
```

**Risk**: MID (touches halt path — must coordinate with close-run lifecycle).

**Depends on**: Task 3.

---

### Task 5: Add F2 guardrails

**Files:**
- `SKILL.md` (Guardrails table)

Add 3 rows:

| Rule | Detail |
|------|--------|
| **Cost ledger frozen pricing** | `scripts/price_table.py` hardcodes rates at commit time. Historical runs reflect contemporaneous rates — re-running with a later price_table does NOT retroactively recompute past runs. Update price_table when Anthropic adjusts rates; do NOT auto-fetch. |
| **`budget_action=pause` halts at compaction boundaries only** | Budget is evaluated at Phase Transition T3 and Phase 2 Step 0 — never mid-task. Cost overruns within a single task complete the task, then the next compaction triggers halt. This is intentional: aborting mid-task wastes the in-flight dispatch. |
| **Cost ledger is run-level** | `cost_ledger`, `budget_cap_usd`, `budget_action` live at top-level state.json (never inside `plan_chain[N]`). Cross-plan chains accumulate one unified ledger. Per-plan totals derivable via `by_task` key prefix `<plan_index>::`. |

**Acceptance Criteria:**

```bash
grep -q "Cost ledger frozen pricing" SKILL.md
grep -q "budget_action=pause.*halts at compaction" SKILL.md
grep -q "Cost ledger is run-level" SKILL.md
```

**Risk**: LOW.

**Depends on**: Tasks 3, 4.

---

## Phase 2 — F1 (archive) — depends on F2 schema

### Task 6: Implement redact_archive.py

**Files:**
- `scripts/redact_archive.py` (new)

Implement per spec §F1.5. Required interface:

```python
def redact_archive(tar_path: Path, meta: dict) -> dict:
    """Extract → redact → re-tar atomically. Returns {'replacements': int, 'errors': list}."""
```

Replacement rules (in order):
1. `os.environ['HOME']` → `<HOME>`
2. `/Users/<name>/` (regex `^/Users/[^/]+/`) → `<HOME>/`
3. `meta['worktree_path']` (absolute) → `<WORKTREE>`
4. `meta['repo_root']` if present (absolute) → `<REPO>`

For `headless.jsonl` files (stream-json): parse each line as JSON. If it parses, redact:
- `cwd`, `env` at top level → set to `"<REDACTED>"` (preserve key for shape).
- Nested under `tool_use.input`: same.
- Any string value whose KEY matches `(?i)(api_key|token|password|secret|credential)` → `"<REDACTED>"`.

Lines that don't parse as JSON: pass through unchanged (defensive — stream-json sometimes has partial lines).

Binary file detection: read first 8 KB, if contains `\x00` → skip redaction.

CLI entry: `python3 redact_archive.py <tar_path> [--meta <json>]`. Returns nonzero on hard error (file unreadable). Returns zero with `replacements: 0` if nothing matched.

**Acceptance Criteria:**

```bash
python3 -m py_compile scripts/redact_archive.py
# Smoke: create a fake tar with one file containing $HOME and a stream-json line with cwd
TMP=$(mktemp -d) && mkdir -p "$TMP/sample" && \
  echo "path: $HOME/foo" > "$TMP/sample/a.txt" && \
  echo '{"type":"text","cwd":"'"$HOME"'/repo","text":"hi"}' > "$TMP/sample/h.jsonl" && \
  tar -czf "$TMP/test.tar.gz" -C "$TMP" sample && \
  python3 scripts/redact_archive.py "$TMP/test.tar.gz" && \
  tar -xzf "$TMP/test.tar.gz" -C "$TMP/out" && \
  grep -q '<HOME>/foo' "$TMP/out/sample/a.txt" && \
  grep -q '<REDACTED>' "$TMP/out/sample/h.jsonl" && \
  ! grep -q "$HOME" "$TMP/out/sample/a.txt"
```

**Risk**: MID (privacy-critical; missing a substitution leaks PII).

**Depends on**: none (parallel-eligible with Task 7).

---

### Task 7: Implement archive_run.sh

**Files:**
- `scripts/archive_run.sh` (new, executable)

Bash script. Required interface:

```
Usage: archive_run.sh --worktree <abs_path> --run-id <id> [--outcome <success|blocked|aborted>]

Steps:
  1. Determine target dir: $HOME/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run-id>/artifacts
  2. mkdir -p target dir
  3. cp <worktree>/.orchestrator/state.json target/state.final.json
  4. Build exclude args: --exclude='*.appended' --exclude='headless.pid' --exclude='exec/' --exclude='hooks/' --exclude='*.tar.gz'
  5. tar -czf <tempfile>.tar.gz -C <worktree> <exclude args> .orchestrator/
  6. python3 redact_archive.py <tempfile>.tar.gz with meta={worktree_path, repo_root}
  7. mv <tempfile>.tar.gz target/orchestrator.tar.gz
  8. Compute file counts, write archive_meta.json
  9. Update state.json's "archive" field via jq + atomic write (read → modify → write to tempfile → mv)
```

Set executable bit. Handle each step's failure independently:
- Step 3 fails → exit 1, no partial artifacts.
- Step 5 fails → log to stderr, exit 1.
- Step 6 fails → write archive_meta.json with `redaction_applied: false, error: ...`, exit 2 (best-effort partial). Caller decides if it tolerates partial.
- Step 7 fails → cleanup tempfile, exit 1.

CLI must be sourceable AND directly executable.

**Acceptance Criteria:**

```bash
test -x scripts/archive_run.sh
bash -n scripts/archive_run.sh
# Smoke: against a stubbed worktree
TMP=$(mktemp -d) && mkdir -p "$TMP/wt/.orchestrator" && \
  echo '{"mode":"headless_running","worktree":"'$TMP'/wt"}' > "$TMP/wt/.orchestrator/state.json" && \
  echo 'fake jsonl' > "$TMP/wt/.orchestrator/headless.jsonl" && \
  HOME="$TMP/home" scripts/archive_run.sh --worktree "$TMP/wt" --run-id testrun --outcome success && \
  test -f "$TMP/home/.claude/learning/kws-claude-multi-agent-executor/runs/$(date +%Y-%m-%d)/testrun/artifacts/orchestrator.tar.gz" && \
  test -f "$TMP/home/.claude/learning/kws-claude-multi-agent-executor/runs/$(date +%Y-%m-%d)/testrun/artifacts/archive_meta.json"
```

**Risk**: MID (file I/O sequencing, atomic move semantics).

**Depends on**: Task 6.

---

### Task 8: Wire archive into Phase 2 Step 2 close-run

**Files:**
- `SKILL.md` (Phase 2 Step 2 — Generate Final Summary Report section)

Insert a new substep AFTER `close-run --outcome=success` succeeds, BEFORE printing the summary report:

```
**Archive run (F1):** call scripts/archive_run.sh with the worktree path,
run ID (from MAE_LEARNING_RUN_ID), and outcome. Failure is silent — log to user
but do NOT halt; close-run already succeeded.

```bash
if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
  <skill_dir>/scripts/archive_run.sh \
    --worktree "$WORKTREE_ABS" \
    --run-id "$MAE_LEARNING_RUN_ID" \
    --outcome success 2>&1 || echo "ARCHIVE: failed (see archive output above) — worktree retained"
fi
```

After archive, the Final Summary Report includes a new "Archive" section:

| Item | Value |
|------|-------|
| Archive path | `<archive_meta.tar_path or "FAILED">` |
| Size | `<bytes formatted>` |
| Redacted | `<yes/no>` |
| Worktree | `<still present at> <path>` |
```

ALSO add the same archive call in two more places:
1. The "exhausted escalations halting the entire run" block in Escalation Protocol step 1 — best-effort archive before exit.
2. The Phase Transition T3 budget=pause halt block (Task 4) — best-effort archive before exit.

**Acceptance Criteria:**

```bash
grep -B 1 -A 5 "Archive run (F1)" SKILL.md | grep -q "archive_run.sh"
grep -c "archive_run.sh" SKILL.md | awk '$1 >= 3 {exit 0} {exit 1}'
```

**Risk**: MID (touches multiple halt paths; missing one means archive isn't called on that exit).

**Depends on**: Tasks 5, 7.

---

### Task 9: Add F1 guardrails

**Files:**
- `SKILL.md` (Guardrails table)

Add 2 rows:

| Rule | Detail |
|------|--------|
| **Archive on close-run is best-effort** | `scripts/archive_run.sh` is invoked AFTER `close-run` succeeds. Archive failure is logged but does NOT halt the orchestrator (the primary run already completed). The worktree is never auto-deleted by archive — user retains it for manual recovery if archive fails. |
| **Redaction is mandatory** | `redact_archive.py` MUST run before the tar moves to its final path. Redaction failure → tar discarded, `archive_meta.json` written with `redaction_applied: false, error: ...`, user-visible warning. Never write a non-redacted tar to `~/.claude/learning/`. |

**Acceptance Criteria:**

```bash
grep -q "Archive on close-run is best-effort" SKILL.md
grep -q "Redaction is mandatory" SKILL.md
```

**Risk**: LOW.

**Depends on**: Task 8.

---

## Phase 3 — F3 (HTML report) + F4 (query scripts) — independent

### Task 10: Implement render_html_report.py

**Files:**
- `scripts/render_html_report.py` (new)

Implement per spec §F3. Single-file Python with no external dependencies (stdlib only — json, pathlib, html, datetime, math, argparse). All CSS/JS inlined in output.

Sections per spec §F3.3 (9 sections in order).

SVG charts: hand-rolled. Two helpers:
- `render_bar_chart(data, labels) -> str` — vertical bars, value labels above
- `render_line_chart(series, x_labels) -> str` — multiple lines (one per plan), legend
- `render_dag(nodes, edges, colors) -> str` — Sugiyama-style layered layout (simple greedy layering)

Color palette per spec §F3.4. Print CSS per spec.

CLI: `python3 render_html_report.py --archive-dir <path> --output <path>`. Exit 0 always (silent failure with placeholder HTML).

Must fall back gracefully when:
- events.jsonl missing → section 9 shows "No notable events."
- multi-plan absent → section 4 (quality trend) shows one line.
- DAG > 50 nodes → render as table (DAG with 50+ nodes is unreadable in screen-width SVG).

**Acceptance Criteria:**

```bash
python3 -m py_compile scripts/render_html_report.py
# Smoke: render against minimal archive
TMP=$(mktemp -d) && mkdir -p "$TMP/artifacts" && \
  echo '{"mode":"headless_running","tasks":{"task_0":{"status":"COMPLETE","risk":"low","review_tier":"PASS","spec_score":0.9,"quality_score":0.85}}}' > "$TMP/artifacts/state.final.json" && \
  echo '{"run_id":"t","outcome":"success","started_at":"2026-05-16T00:00:00Z","completed_at":"2026-05-16T00:10:00Z","plan_path":"p.md"}' > "$TMP/meta.json" && \
  : > "$TMP/events.jsonl" && \
  python3 scripts/render_html_report.py --archive-dir "$TMP" --output "$TMP/REPORT.html" && \
  test -s "$TMP/REPORT.html" && \
  grep -q "<html" "$TMP/REPORT.html" && \
  ! grep -q "src=\"http" "$TMP/REPORT.html"  # no external refs
```

**Risk**: MID (most code-heavy task; SVG charting is fiddly).

**Depends on**: Tasks 7, 8 (needs archive dir layout).

---

### Task 11: Wire HTML rendering into new Phase 2 Step 3

**Files:**
- `SKILL.md` (insert new Phase 2 Step 3 between current Step 2 and Step 3 — renumber existing "Step 3" sections downstream if any)

Add a new top-level Phase 2 step:

```
### Step 3: Render HTML run report (F3)

After Step 2's archive completes (regardless of archive success/failure), invoke the HTML renderer:

```bash
if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
  ARCHIVE_DIR="$HOME/.claude/learning/kws-claude-multi-agent-executor/runs/$(date +%Y-%m-%d)/${MAE_LEARNING_RUN_ID}"
  if [ -d "$ARCHIVE_DIR/artifacts" ]; then
    python3 <skill_dir>/scripts/render_html_report.py \
      --archive-dir "$ARCHIVE_DIR" \
      --output "$ARCHIVE_DIR/artifacts/REPORT.html" \
      2>"$ARCHIVE_DIR/artifacts/render.log" || \
      echo "REPORT_RENDER: failed (see $ARCHIVE_DIR/artifacts/render.log)"
  fi
fi
```

Update state.json's `archive.report_html_path` if rendering succeeds (atomic R-M-W).

Append a row to the Final Summary Report's Archive section:

| Item | Value |
|------|-------|
| HTML report | `<file://path/to/REPORT.html or "FAILED (see render.log)">` |
```

**Acceptance Criteria:**

```bash
grep -E "^### Step 3:.*HTML.*report" SKILL.md
grep -A 10 "Render HTML run report" SKILL.md | grep -q "render_html_report.py"
```

**Risk**: LOW.

**Depends on**: Tasks 8, 10.

---

### Task 12: Implement query_state.sh and query_run.sh

**Files:**
- `scripts/query_state.sh` (new, executable)
- `scripts/query_run.sh` (new, executable)

Bash + jq. Per spec §F4.

`query_state.sh` resolves `--worktree <path>` → reads `<path>/.orchestrator/state.json`. Forwards `--run-id <id>` calls to `query_run.sh`.

`query_run.sh` resolves `--run-id` per spec rules. `list-runs` scans `~/.claude/learning/kws-claude-multi-agent-executor/runs/*/*/` reverse-chronologically, prints last 20.

All 9+3 subcommands implemented. Subcommand logic shared via a helper function (e.g., `cost_summary(state_json_path)`).

ETA subcommand uses `started_at` from timestamps + completed_count/total_count linear projection.

**Acceptance Criteria:**

```bash
bash -n scripts/query_state.sh
bash -n scripts/query_run.sh
test -x scripts/query_state.sh
test -x scripts/query_run.sh
# Smoke
TMP=$(mktemp -d) && mkdir -p "$TMP/wt/.orchestrator" && \
  echo '{"mode":"x","active_plan":"plan1","tasks":{"task_0":{"status":"COMPLETE","review_tier":"PASS"},"task_1":{"status":"COMPLETE","review_tier":"WARN"},"task_2":{"status":"IN_PROGRESS"}},"current_task":2,"current_step_within_task":1}' > "$TMP/wt/.orchestrator/state.json" && \
  scripts/query_state.sh --worktree "$TMP/wt" progress | grep -E "2/3.*COMPLETE.*1.*WARN"
```

**Risk**: LOW (read-only, well-bounded jq).

**Depends on**: Tasks 1, 3 (needs cost_ledger schema present).

---

### Task 13: Update Phase -1 echo line + detach message

**Files:**
- `SKILL.md` (Phase -1 step e — detach message + Phase -1.0 echo line)

Extend the detach message (currently shows `tail -f`, `jq`, `test -f`) with the 4th block from spec §F4.3:

```
Quick queries (no LLM, ~10ms each):
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> progress
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> cost
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> warn

Post-run, archived analysis:
  <skill_dir>/scripts/query_run.sh list-runs
  <skill_dir>/scripts/query_run.sh last cost
```

Resolve `<skill_dir>` at message-construction time (use the absolute path the skill was loaded from).

Also update the echo line format (Phase -1.0 Pass 3 final step) to include `budget=<value>`:

```
Parsed: <N> plan(s) [...], implementer_model=<value> [from <source>], parallel=<value> [...], mode=<value> [...], risk=<value or "per-task">, budget=<value or "off"> [from <source>].
```

**Acceptance Criteria:**

```bash
grep -A 8 "Quick queries (no LLM" SKILL.md | grep -q "query_state.sh"
grep -A 8 "Post-run, archived analysis" SKILL.md | grep -q "query_run.sh"
grep -E 'budget=<value or "off">' SKILL.md
```

**Risk**: LOW.

**Depends on**: Tasks 2, 12.

---

### Task 14: Bump version + HISTORY.md + JOURNAL.md

**Files:**
- `SKILL.md` (metadata.version)
- `HISTORY.md`
- `docs/experiments/v2.14-forensics-and-cost/JOURNAL.md` (new)

Update `SKILL.md` frontmatter: `version: "2.14.0"`, `updated_at: "<today YYYY-MM-DD>"`.

Add HISTORY.md `# v2.14.0` section with the bundle summary (one paragraph per feature from spec).

Create JOURNAL.md with initial entry:

```markdown
# v2.14 Journal

## <YYYY-MM-DD> — execution begin
- Plan: docs/experiments/v2.14-forensics-and-cost/plan.md
- Spec: docs/experiments/v2.14-forensics-and-cost/spec.md
- Branch: <auto-derived>

(Append per-phase entries as execution proceeds.)
```

**Acceptance Criteria:**

```bash
grep -q 'version: "2.14.0"' SKILL.md
grep -q '# v2.14' HISTORY.md
test -f docs/experiments/v2.14-forensics-and-cost/JOURNAL.md
```

**Risk**: LOW.

**Depends on**: ALL prior tasks (this is the close-out).

---

## Dependency graph (compaction points marked)

```
Task 0 (price_table.py)                      [LOW, SMALL]
  └─ Task 1 (state schema)                   [MID, MEDIUM]
       └─ Task 2 (args parser)               [LOW, SMALL]
            └─ Task 3 (cost accumulation)    [MID, MEDIUM]
                 └─ Task 4 (budget eval)     [MID, MEDIUM]
                      └─ Task 5 (F2 guards)  [LOW, SMALL]
═══════════════ compaction point 1 (F2 complete) ═══════════════
Task 6 (redact_archive.py)  ┐                [MID, MEDIUM]
Task 7 (archive_run.sh)     ┤ parallel       [MID, MEDIUM]
       └─ both ─┐
                └─ Task 8 (wire archive)     [MID, MEDIUM]
                     └─ Task 9 (F1 guards)   [LOW, SMALL]
═══════════════ compaction point 2 (F1 complete) ═══════════════
Task 10 (render_html_report.py)              [MID, LARGE]
  └─ Task 11 (wire HTML)                     [LOW, SMALL]
Task 12 (query scripts)                      [LOW, MEDIUM]
  └─ Task 13 (echo + detach)                 [LOW, SMALL]
═══════════════ compaction point 3 (F3+F4 complete) ═══════════════
Task 14 (version + history + journal)        [LOW, SMALL]
═══════════════ compaction point 4 (FINAL) ═══════════════
```

## Risk override

Default per-task risk levels above. If user passes `risk=low` override: log warning that Tasks 1, 3, 4, 6, 7, 8 are MID-by-design and the override may skip needed verification. Tasks 1 and 3 touch the schema authoritative path — the warning should be explicit about regression risk.

## Parallelization opportunities

- Tasks 6 and 7 declare disjoint files (`scripts/redact_archive.py` vs `scripts/archive_run.sh`); same wave.
- Tasks 10 and 12 declare disjoint files (`scripts/render_html_report.py` vs `scripts/query_*.sh`); same wave.

## Resource Key annotations

- Tasks 1, 2, 3, 4, 5, 8, 9, 11, 13, 14: **Resource Key:** `skill-md` (all edit SKILL.md — serialize within wave).

No other resource-key collisions.

## Definition of Done — referenced from spec

See spec §"Definition of Done" — all checkboxes must be checked at Phase 2 method audit.
