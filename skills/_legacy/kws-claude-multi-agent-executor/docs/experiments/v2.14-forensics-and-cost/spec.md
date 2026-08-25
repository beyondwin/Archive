# v2.14 — Forensics & Cost (Specification)

**Skill version target**: `2.14.0` · **Schema version**: stays `"2"` (additive only) · **Backward compat**: full (legacy state.json keeps working)

---

## Goals

| ID | Statement | Why |
|----|-----------|-----|
| G1 | Detail logs of every run survive worktree deletion. | `events.jsonl` is notable-boundary-only; successful routine runs leave `event_count == 0`. Detail (stream-json transcript, raw sub-agent outputs, final state.json) lives only inside the worktree and is destroyed by `git worktree remove`. |
| G2 | Token usage and USD cost are visible per task, per role, and total — and optionally capped. | Currently zero cost tracking. Long chain-resumed runs can burn budget invisibly. v2.15 also needs token measurement to validate context-engineering effect. |
| G3 | Each completed run produces one self-contained HTML report. | Markdown summary is text-only; reviewers need score distribution, dep graph, cost breakdown, quality trend in visual form. |
| G4 | Run status is queryable without spinning up an LLM. | Monitor jq one-liners scattered across docs; archived runs need ad-hoc commands. ~10ms queries beat 30s LLM calls. |

## Non-goals

- No change to per-task dispatch loop, model selection, retry budgets, parallel scheduling, or hook contracts.
- No new sub-agent dispatches (Final Milestone Validator is deferred to a later version).
- No state migration script — every new field has a defined default for legacy state.json.
- No live Anthropic price API integration — price table is frozen at file commit time.

## Architecture invariants preserved

- Schema version stays `"2"` (additive only — no field renames or type changes).
- Active-tree resolution rule (v2.13) untouched. Every new per-plan field resolves through `<active>`.
- Phase ordering unchanged. F1 hooks at Phase 2 Step 2 (close-run), F3 at Phase 2 Step 3 (new), F2 accumulates at Phase 1 Step 4, F2 evaluates at Phase Transition T3.
- Learning-log lifecycle invariant unchanged (Phase 0 Step 7.5 init-run, Phase 1 Step 3.5 candidate scan, Phase 2 Step 2 close-run). F1 archive happens *after* close-run completes — never before, never instead of.

---

## Feature F1 — Archive `.orchestrator/` to user-local store

### F1.1 Trigger points

| Source | When | Outcome required |
|--------|------|------------------|
| Phase 2 Step 2 close-run | After `close-run --outcome=success` succeeds | Full archive |
| Whole-orchestrator hard halt (state-write fail, exhausted escalations halting the run) | After `close-run --outcome=blocked` or `aborted` succeeds | Best-effort archive (failure silent) |
| `HEADLESS_HALTED.txt` write (headless child only) | Just before writing the halt marker | Best-effort archive (failure silent) |
| Resume Chain parent exit | NEVER archives | Child inherits archive responsibility |

### F1.2 Archive layout

```
~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/
├── meta.json               (existing — written by init-run/close-run)
├── events.jsonl            (existing — appended throughout)
└── artifacts/              (NEW — written at archive time)
    ├── state.final.json    (verbatim copy of <worktree>/.orchestrator/state.json at close)
    ├── orchestrator.tar.gz (gzipped tar of <worktree>/.orchestrator/, post-redaction)
    └── archive_meta.json   (manifest — see F1.4)
```

### F1.3 Exclude list (tar)

The tar MUST exclude these globs (use `--exclude`):

- `*.appended` — post-emit learning-event candidate dross (already forwarded)
- `headless.pid` — runtime-only; meaningless post-mortem
- `exec/` — present only if v2.15 ② lands; not archived (large, low forensic value)
- `hooks/` — verbatim copies from skill `references/hooks/`; archived shape is identical to skill repo
- `*.tar.gz` — defensive (prevents nested archives if rerun)

### F1.4 `archive_meta.json` schema

```json
{
  "tar_path": "artifacts/orchestrator.tar.gz",
  "tar_size_bytes": <int>,
  "state_final_path": "artifacts/state.final.json",
  "state_final_size_bytes": <int>,
  "redaction_applied": true,
  "redaction_replacements": <int>,
  "exclude_globs": ["*.appended", "headless.pid", "exec/", "hooks/", "*.tar.gz"],
  "archived_at": "<iso8601>",
  "archived_by": "v2.14",
  "source_worktree": "<WORKTREE>",
  "tar_inner_file_count": <int>
}
```

`source_worktree` is the **redacted** path placeholder, NOT the actual absolute path (privacy).

### F1.5 Redaction rules (`scripts/redact_archive.py`)

Operates on the tarball *after* tar creation, before final mv into `artifacts/`. Algorithm:

1. Extract tar to tempdir.
2. For each file inside (recursively):
   - If binary (heuristic: contains null byte in first 8KB): skip — do not modify.
   - If text: in-place rewrite with these substitutions, in order:
     - `<HOME>` token replaces absolute `os.environ['HOME']`.
     - `<HOME>/` replaces `/Users/<username>/` patterns matching `/Users/[^/]+/` (intentionally un-anchored so embedded paths in log lines and JSON values are scrubbed, not just line-start paths).
     - `<WORKTREE>` replaces the run's actual worktree absolute path (read from `meta.json.worktree_path` if available, otherwise from state.json).
     - `<REPO>` replaces the run's actual repo root absolute path (similar lookup).
3. Stream-json `headless.jsonl` files: for each line that parses as JSON, redact:
   - Top-level `cwd`, `env` (whole-object removal — keep key, set value `"<REDACTED>"`).
   - `cwd` and `env` nested under `tool_use.input` similarly.
   - Token fields matching regex `(api_key|token|password|secret|credential)` (case-insensitive) → `"<REDACTED>"`.
   - Preserve all `text`, `tool_name`, `usage`, `timing`, `status`.
4. Recompute tar from redacted tempdir.
5. Atomic mv into `artifacts/orchestrator.tar.gz`.
6. Count substitutions; report count back to archive_run.sh for `archive_meta.json.redaction_replacements`.

### F1.6 Failure handling

- tar fails (disk full, permission): archive aborts. Write `archive_meta.json` with `tar_path: null, error: "<message>"`. Do NOT delete the worktree-side `.orchestrator/`. Print user-visible warning. Do NOT halt the orchestrator (close-run already succeeded).
- redact_archive.py fails: discard partial tar, write `archive_meta.json` with `redaction_applied: false, error: "<message>"`. Print warning. Same continuation rule.
- ~/.claude/learning dir not writable: archive aborts with warning. Same.

### F1.7 Acceptance

A1. After `outcome=success` Phase 2 completion: `artifacts/orchestrator.tar.gz` exists, `tar -tzf` lists ≥ 3 expected files (state.json, at least one prompt, at least one event-candidate or empty), `state.final.json` is valid JSON parseable.
A2. After F1 archive + `git worktree remove --force`: `tar -xzf` succeeds, extracted state.json `jq -r '.mode'` returns a valid mode string.
A3. `grep -r "/Users/$(whoami)" artifacts/orchestrator.tar.gz` (after extract) returns 0 hits. Same for `grep -r "$HOME"`.
A4. `archive_meta.json.tar_inner_file_count` matches `tar -tzf orchestrator.tar.gz | wc -l`.
A5. tar fails simulation (set artifacts dir read-only): orchestrator continues; final summary report shows `Archive Status: FAILED (write permission)`.

---

## Feature F2 — Cost ledger + budget cap

### F2.1 New state.json fields

Added at the top level of state.json (run-level, NOT per-plan — totals span the entire chain):

```json
{
  "cost_ledger": {
    "by_task": {
      "<plan_index_or_top>::<task_id>": {
        "input_tokens": <int>,
        "output_tokens": <int>,
        "cached_read_tokens": <int>,
        "cached_write_tokens": <int>,
        "cost_usd": <float>,
        "model": "sonnet" | "opus" | "haiku",
        "role": "implementer" | "reviewer" | "verifier" | "docs_updater" | "plan_reviewer",
        "dispatched_at": "<iso8601>"
      }
    },
    "by_role": {
      "implementer": {"input_tokens": N, "output_tokens": N, "cached_read_tokens": N, "cached_write_tokens": N, "cost_usd": F, "dispatches": <int>}
    },
    "by_model": {
      "sonnet": {"input_tokens": N, "output_tokens": N, "cached_read_tokens": N, "cached_write_tokens": N, "cost_usd": F, "dispatches": <int>}
    },
    "totals": {
      "input_tokens": N, "output_tokens": N,
      "cached_read_tokens": N, "cached_write_tokens": N,
      "cost_usd": F, "dispatches": <int>
    }
  },
  "budget_cap_usd": <number> | null,
  "budget_action": "pause" | "warn" | "off"
}
```

`by_task` key format: `"<active_plan>::<task_id>"` to disambiguate same task IDs across multi-plan chains (e.g., `"0::task_3"` vs `"1::task_3"`). For single-plan / legacy v2.12 runs, prefix is `"plan1::"` or `"plan2::"`.

### F2.2 New skill arguments

Phase -1.0 Pass 1 (`argument parser`) recognizes two new explicit keys:

- `budget=<USD>` — optional. Float. Sets `budget_cap_usd`. Missing → `null` (track only, never block).
- `budget_action=pause|warn|off` — optional. Default `"warn"`. Validation: must be one of three strings, else halt with `"Unknown budget_action=<value>. Allowed: pause, warn, off."`.

No natural-language lexicon entries added — budget MUST be explicit. (NL token "budget" / "예산" / "캡" reserved for future use; rejected with halt if seen in free text to avoid silent misinterpretation.)

### F2.3 Accumulation point — Phase 1 Step 4

After every Agent tool result and every headless subprocess completion:

1. **Agent tool path** (Implementer, Combined Reviewer): the tool result message contains a `usage` block. Extract `input_tokens`, `output_tokens`, `cache_creation_input_tokens` (→ `cached_write_tokens`), `cache_read_input_tokens` (→ `cached_read_tokens`).
2. **Headless subprocess path** (Verifier, Phase Docs Updater, Final Docs Updater, Plan Reviewer): parse the corresponding `.stdout` file. Look for `stream-json` final-message line where `type == "result"`; read `usage` field. If parse fails: log warning, record token entry with zeros, continue.
3. Lookup `cost_per_mtok` from `scripts/price_table.py` keyed by `(model, kind)`.
4. Compute `cost_usd = (input_tokens / 1e6) * input_per_mtok + ...` summed over all 4 kinds.
5. Atomically (via Read-modify-Write of state.json) update:
   - `cost_ledger.by_task["<active>::<task_id>"]` — new entry per dispatch
   - `cost_ledger.by_role[<role>]` — increment aggregates
   - `cost_ledger.by_model[<model>]` — increment aggregates
   - `cost_ledger.totals` — increment aggregates
6. Failure to read usage (missing field): record zero entry with `model: "unknown"`. Do NOT halt.

### F2.4 Budget evaluation point — Phase Transition T3 + Phase 2 Step 0

At Phase Transition T3, after the state anchor write succeeds (current step 1) and after the `context_health` snapshot (current step 3):

```python
if state.budget_action == "off" or state.budget_cap_usd is None:
    skip
elif state.cost_ledger.totals.cost_usd >= state.budget_cap_usd:
    if state.budget_action == "warn":
        emit_learning_event(
            type="context_health",
            severity="high",
            summary=f"Budget warning: ${totals} of ${cap} cap consumed.",
            issue_key="budget_warning"
        )
        # Continue execution.
    elif state.budget_action == "pause":
        close_run(outcome="blocked")
        write HEADLESS_HALTED.txt with reason="budget_exceeded"
        exit
```

Same check fires at Phase 2 Step 0 (final LOW batch sweep) BEFORE batch dispatch — last chance to halt before adding more cost.

### F2.5 `scripts/price_table.py`

```python
# Frozen pricing snapshot — Anthropic public list prices.
# Update this file on any rate change; historical runs preserve commit-time rates.
PRICES = {
    "claude-opus-4-7": {
        "input_per_mtok": 15.00,
        "output_per_mtok": 75.00,
        "cached_read_per_mtok": 1.50,
        "cached_write_per_mtok": 18.75,
    },
    "claude-sonnet-4-6": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cached_read_per_mtok": 0.30,
        "cached_write_per_mtok": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.00,
        "cached_read_per_mtok": 0.08,
        "cached_write_per_mtok": 1.00,
    },
}

ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
    "haiku": "claude-haiku-4-5-20251001",
    "unknown": None,
}

def get_price(model_id: str, kind: str) -> float:
    canonical = ALIASES.get(model_id, model_id)
    if canonical is None or canonical not in PRICES:
        return 0.0
    return PRICES[canonical][kind]

def compute_cost(model_id: str, usage: dict) -> float:
    return (
        usage.get("input_tokens", 0) / 1e6 * get_price(model_id, "input_per_mtok")
        + usage.get("output_tokens", 0) / 1e6 * get_price(model_id, "output_per_mtok")
        + usage.get("cached_read_tokens", 0) / 1e6 * get_price(model_id, "cached_read_per_mtok")
        + usage.get("cached_write_tokens", 0) / 1e6 * get_price(model_id, "cached_write_per_mtok")
    )
```

### F2.6 Resume semantics

Phase 0 Step 0 resume: if `state.cost_ledger` is absent (legacy state.json) → initialize empty (all aggregates zero). If present → preserve as-is and continue accumulating. Same for `budget_cap_usd`, `budget_action`.

Resume Chain handoff: `cost_ledger` is top-level run-level state — automatically inherited by the chained child via state.json. No special copy.

### F2.7 Acceptance

A1. After 1 task completes with default args: `cost_ledger.totals.cost_usd > 0`, `cost_ledger.by_task` has 1 entry per dispatch (≥ 2: Implementer + Combined Reviewer).
A2. `cost_ledger.totals.cost_usd == sum(by_role[r].cost_usd for r in by_role)` within $0.0001 absolute.
A3. Same equality for `by_model` aggregation.
A4. `budget=0.01 budget_action=pause` against any real plan: orchestrator halts at first Phase Transition T3 with HEADLESS_HALTED.txt containing `reason: budget_exceeded`; close-run records `outcome=blocked`.
A5. `budget=0.01 budget_action=warn`: orchestrator continues to completion; events.jsonl contains ≥ 1 entry with `event_type: context_health, issue_key: budget_warning`.
A6. Unknown model in Agent result (e.g., haiku used in some weird path): cost recorded as 0.0, `cost_ledger.by_task[...].model: "unknown"`, run continues.

---

## Feature F3 — HTML run report

### F3.1 Output

`~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/artifacts/REPORT.html`

Single self-contained file. No external dependencies (no CDN, no fonts, no JS framework). Opens standalone in Chrome/Safari/Firefox/Edge.

### F3.2 Input

Reads (in order):
1. `<artifacts>/archive_meta.json` — verifies archive succeeded
2. `<artifacts>/state.final.json` — primary data source
3. `<runs>/<id>/meta.json` — run metadata (outcome, plan/spec paths, session IDs)
4. `<runs>/<id>/events.jsonl` — notable events (one JSON per line)

If state.final.json is missing → write minimal placeholder report `<h1>Report unavailable — state.final.json missing</h1>` and exit 0.

### F3.3 Sections (in order)

| § | Title | Data source | Visual |
|---|-------|-------------|--------|
| 1 | Run summary | meta.json + state.final.json | Header card: plan, spec, branch, run_id, outcome, duration, total cost USD, dispatch count |
| 2 | Task table | state.tasks (all plans iterated) | Sortable HTML table — columns: plan, id, status, risk, complexity, spec_score, quality_score, tier, retries, escalations, duration, cost |
| 3 | Cost breakdown | cost_ledger.by_role + by_model | Two SVG bar charts side-by-side (role and model). Stacked bar if multi-plan chain. |
| 4 | Quality trend | quality_trend (per plan) | SVG line chart, one line per plan, x=task index, y=quality_score 0.0–1.0 |
| 5 | Dependency DAG | execution_plan + tasks | SVG layered DAG. Node color: PASS green / WARN yellow / FAIL red / SKIPPED grey. Edge: dep arrows. |
| 6 | WARN tasks | tasks where review_tier == "WARN" | Collapsible per-task block with warnings list from task_summaries.warnings |
| 7 | Method audit | tasks.*.method_audit | Per-task evidence list: applied / missing / waived |
| 8 | Spec edits | state.spec_edits | Timeline list: task / line / reason / fault / timestamp / commit |
| 9 | Events summary | events.jsonl | Count by event_type; click event_type to expand all events of that type |

### F3.4 Visual constraints

- All CSS inlined in `<style>` tag.
- All JS inlined in `<script>` tag. Total JS ≤ 8 KB.
- Charts are hand-rolled SVG — no D3, no Chart.js, no Plotly.
- Color palette: WCAG AA contrast on both light and dark print. Tier colors: PASS `#10a37f`, WARN `#d97706`, FAIL `#dc2626`, SKIPPED `#6b7280`.
- Print CSS (`@media print`): hides interactive sort/collapse controls, expands all collapsibles, page-break before each top-level section ≥ 3.
- File size ≤ 500 KB typical (≤ 2 MB hard cap — chain runs with 50+ tasks may grow).

### F3.5 Trigger

NEW phase: **Phase 2 Step 3 — Render HTML report**. Runs AFTER F1 archive (needs the archive dir) and AFTER F2 close-run. Same failure policy: silent failure with warning to user, run completion not blocked.

```bash
if [ -d "$ARCHIVE_DIR/artifacts" ]; then
    python3 <skill_dir>/scripts/render_html_report.py \
        --archive-dir "$ARCHIVE_DIR" \
        --output "$ARCHIVE_DIR/artifacts/REPORT.html" \
        2>"$ARCHIVE_DIR/artifacts/render.log" || \
        echo "REPORT_RENDER: failed (see render.log)"
fi
```

### F3.6 Acceptance

A1. REPORT.html opens in Chrome with no console errors, no failed network requests.
A2. Sortable task table — click column header reorders rows.
A3. Print preview matches screen content (no JS-only sections missing).
A4. File size < 2 MB for any successful run.
A5. Empty events.jsonl: section 9 renders "No notable events." without error.
A6. Multi-plan chain: section 4 (quality trend) renders one line per plan, labeled.

---

## Feature F4 — Query scripts (no LLM)

### F4.1 `scripts/query_state.sh`

Read-only queries against a LIVE worktree's state.json. Bash + jq only — no Python, no Node.

```
Usage: scripts/query_state.sh --worktree <abs_path> <subcommand> [opts]
       scripts/query_state.sh --run-id <id> <subcommand> [opts]   (forwards to query_run.sh)

Subcommands:
  current      — current task + step within task
  progress     — N/M complete + warn + fail + skipped + active per plan
  cost         — totals + by-role + by-model breakdown
  warn         — list WARN tasks with truncated warning text
  tier-dist    — count of PASS / WARN / FAIL / SKIPPED across all plans
  quality      — first-5 mean, last-5 mean, trend direction
  eta          — projection: completed_count / total_count × elapsed_time
  failures     — list tasks with escalation_count > 0 or review_retries > 0
```

Exit codes: `0` success, `1` state.json missing, `2` jq parse failure, `3` unknown subcommand.

### F4.2 `scripts/query_run.sh`

Read-only queries against ARCHIVED state. Same subcommands plus:

```
Additional subcommands:
  list-runs              — last 20 run IDs reverse chronological, with date + plan slug + outcome
  last [<subcommand>]    — apply <subcommand> to most recent run
  find <plan-slug> [<subcommand>]  — apply <subcommand> across all runs matching slug

Resolution rule:
  --run-id <id>          — full run ID
  --run-id <date>/<id>   — date-scoped
  --run-id last          — most recent run regardless of date
```

Reads from `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<id>/artifacts/state.final.json`. Failover: if state.final.json missing, read `meta.json` for outcome-only queries (`list-runs`, `last outcome`).

### F4.3 Echo line integration

Phase -1 step e detach message (currently shows `tail -f`, `jq`, `test -f`) gains a 4th block:

```
Quick queries (no LLM, ~10ms each):
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> progress
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> cost
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> warn

Post-run, archived analysis:
  <skill_dir>/scripts/query_run.sh list-runs
  <skill_dir>/scripts/query_run.sh last cost
```

Substitute `<skill_dir>` and `<abs_path>` at message construction time.

### F4.4 Acceptance

A1. `query_state.sh --worktree <wt> progress` returns within 100ms for a state.json with 30 tasks.
A2. `query_state.sh --worktree <missing> progress` returns exit code 1, prints clear diagnostic to stderr.
A3. `query_run.sh list-runs` returns last 20 in reverse chronological order with no truncation of run_id.
A4. `query_run.sh last cost` outputs single-line breakdown: `last (<date>, <slug>, <outcome>): $X.XX total | implementer X% (sonnet $Y.YY, opus $Z.ZZ) | reviewer X% | verifier X%`.
A5. All subcommands print to stdout; diagnostics to stderr; never mixed.

---

## Consolidated state.json schema delta

```diff
{
  "schema_version": "2",
  "mode": "...",
  "active_plan": "plan1" | <int>,
  "plan": "...",
  "spec": "...",
  "branch": "...",
  "worktree": "...",
  "test_command": "...",
  "implementer_model": {"used": "...", "default": "sonnet"},
+ "budget_cap_usd": <number> | null,                  // F2 (run-level)
+ "budget_action": "pause" | "warn" | "off",          // F2 (run-level, default "warn")
+ "cost_ledger": {                                    // F2 (run-level, accumulates across chain)
+   "by_task": {...},
+   "by_role": {...},
+   "by_model": {...},
+   "totals": {...}
+ },
+ "archive": {                                        // F1 (run-level, written at close)
+   "tar_path": "<HOME>/.claude/learning/.../orchestrator.tar.gz",
+   "tar_size_bytes": <int>,
+   "redaction_applied": true,
+   "archived_at": "<iso8601>",
+   "report_html_path": "<HOME>/.claude/learning/.../REPORT.html"  // F3 (set if rendered)
+ } | null,
  "plan_chain": [...] | absent,
  "tasks": {...} | absent (multi-plan),
  ...
}
```

All new fields have defined defaults (`null`, `"warn"`, empty objects). Resume from legacy state.json: initialize via `dict.setdefault(...)`.

---

## Backward compatibility

| Scenario | Behavior |
|----------|----------|
| Resume from v2.13 state.json (no new fields) | Phase 0 Step 0 initializes `cost_ledger={by_task:{},by_role:{},by_model:{},totals:{...zeros}}`, `budget_cap_usd=null`, `budget_action="warn"`, `archive=null`. Continue normally. |
| Resume from v2.14 state.json after partial run | Use as-is. Cost accumulators continue from current totals. |
| Archive of a v2.13 run (post-upgrade) | `archive_run.sh` works on any `.orchestrator/` shape. `redact_archive.py` handles missing optional fields. |
| `budget=` arg given to v2.13 skill (downgrade) | v2.13 halts at Phase -1.0 Pass 1 with "Unknown argument: budget=...". Expected — no auto-detection. |

---

## Privacy

- All redaction policy from `references/learning-log.md` applies to archived tarball.
- `redact_archive.py` is mandatory. If it fails, the run-level archive_meta.json records `redaction_applied: false` and tar.gz is NOT moved into final position — the partial tar in tempdir is discarded. User-visible warning printed.
- HTML report writes the SAME redacted view — never the raw worktree paths. `render_html_report.py` reads from archived (already-redacted) state.final.json; if it falls back to live state.json, it applies redaction in-memory before rendering.

---

## Security

- `scripts/archive_run.sh` writes to user-home dir; never to system paths.
- `redact_archive.py` operates on tempdir then atomic mv — no in-place mutation of user files.
- Query scripts are strictly read-only — no `mv`, no `rm`, no `git` mutating commands.
- No new shell subprocess permissions required beyond existing skill.

---

## Definition of Done (DoD)

Run-level mechanical criteria — these are checked by the Phase 2 method audit + Final Summary Report:

- [ ] All 14 plan tasks COMPLETE or SKIPPED with documented reason.
- [ ] `scripts/price_table.py` exists and `python3 -c "from price_table import compute_cost; print(compute_cost('sonnet', {'input_tokens': 1000, 'output_tokens': 500}))"` prints non-zero float.
- [ ] `scripts/archive_run.sh` exists with executable bit set.
- [ ] `scripts/redact_archive.py` exists; `python3 -m py_compile` succeeds.
- [ ] `scripts/render_html_report.py` exists; `python3 -m py_compile` succeeds.
- [ ] `scripts/query_state.sh` and `scripts/query_run.sh` exist; `bash -n` passes.
- [ ] SKILL.md `metadata.version` updated to `"2.14.0"`.
- [ ] SKILL.md Guardrails table contains rows: `Archive on close-run is best-effort`, `Cost ledger frozen pricing`, `Query scripts are read-only`, `Budget action validates explicit string`.
- [ ] SKILL.md Phase 2 Step 2 references the archive step explicitly.
- [ ] SKILL.md Phase 2 gains a "Step 3" section for HTML rendering.
- [ ] SKILL.md Phase 1 Step 4 documents the cost-accumulation step.
- [ ] SKILL.md Phase Transition T3 documents the budget-evaluation step.
- [ ] SKILL.md Phase -1.0 Pass 1 lists `budget`, `budget_action` as recognized keys.
- [ ] HISTORY.md gains v2.14 section with feature summary.
- [ ] `docs/experiments/v2.14-forensics-and-cost/JOURNAL.md` opening entry written.
- [ ] Eval run completed against a known plan (e.g., evals/fixtures sample) producing artifacts/REPORT.html that opens cleanly in browser.

## Acceptance Criteria (executable, for Verifier)

```bash
# F1
test -x scripts/archive_run.sh
python3 -m py_compile scripts/redact_archive.py

# F2
python3 -c "import sys; sys.path.insert(0, 'scripts'); from price_table import compute_cost; \
  c = compute_cost('sonnet', {'input_tokens': 1_000_000, 'output_tokens': 1_000_000, 'cached_read_tokens': 0, 'cached_write_tokens': 0}); \
  assert 17.99 < c < 18.01, f'expected ~18.00 (3+15), got {c}'"

# F3
python3 -m py_compile scripts/render_html_report.py

# F4
bash -n scripts/query_state.sh
bash -n scripts/query_run.sh

# SKILL.md version
grep -q 'version: "2.14.0"' SKILL.md

# Guardrail entries
grep -q "Archive on close-run" SKILL.md
grep -q "Cost ledger" SKILL.md
grep -q "budget_action" SKILL.md
```
