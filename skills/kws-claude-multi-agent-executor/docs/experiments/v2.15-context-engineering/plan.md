# v2.15 — Context Engineering (Implementation Plan)

**Spec**: `docs/experiments/v2.15-context-engineering/spec.md` · **Target version**: `2.15.0` · **Hard dep**: v2.14.0 lands first (cost_ledger schema)

---

## Phase 1 — C1 (spec manifest)

### Task 0: Implement build_spec_manifest.py

**Files:**
- `scripts/build_spec_manifest.py` (new)

Per spec §C1.2. Stdlib only (re, json, sys, argparse, pathlib).

CLI: `python3 build_spec_manifest.py <spec_path>` prints JSON to stdout matching the `spec_manifest.sections` shape (no task_to_sections).

Algorithm:
1. Read file, split into lines.
2. First pass: detect fenced code block ranges (``` and ~~~ pairs). Headings inside code blocks are ignored.
3. Second pass: walk headings outside code blocks. For each heading: depth from `#` count, text from rest of line.
4. Assign hierarchical IDs by maintaining a stack `[counter_at_level_1, counter_at_level_2, ...]`. When a heading at depth `d` is seen: truncate stack to length `d-1`, increment/append counter at depth `d`. ID = `S` + dot-joined stack.
5. For each heading, range = (its_line_1indexed, next_heading_at_same_or_higher_level_line - 1, OR EOF).
6. chars = sum of len(line) for line in range.
7. anchor = lowercased text with non-alphanumerics → `-`, collapsed `--+` → `-`, stripped.
8. Emit `{section_id: {title, range, chars, anchor, level}}` sorted by section_id.

Edge cases handled:
- Empty file → `{"S0": {"title": "(empty)", "range": [1, 1], "chars": 0, "anchor": "empty", "level": 0}}`.
- No headings → single section S0 covering entire file.
- HTML-commented sections (`<!-- ... # heading ... -->` across multiple lines): tracked similarly to code blocks.

**Acceptance Criteria:**

```bash
python3 -m py_compile scripts/build_spec_manifest.py
# Smoke
TMP=$(mktemp) && cat >"$TMP" <<'EOF'
# Top
intro
## Sub A
text
### Deep
deep text
## Sub B
text
EOF
python3 scripts/build_spec_manifest.py "$TMP" | jq -e '.["S1"].level == 1 and .["S1.1"].level == 2 and .["S1.1.1"].level == 3 and .["S1.2"].level == 2'
```

**Risk**: LOW (isolated, pure parsing).

---

### Task 1: Extend Phase 0 Step 3 to build spec_manifest

**Files:**
- `SKILL.md` (Phase 0 Step 3 — "Read both documents fully")

Add after the current spec-read step:

```
3.7. Build spec manifest (C1):
  Call: python3 <skill_dir>/scripts/build_spec_manifest.py <spec_path>
  Capture stdout JSON. If parse fails: halt with "spec_manifest build failed: <stderr>".

  Write to <active>.spec_manifest:
    spec_path: <spec_path>
    spec_total_chars: <int from stdout sum>
    sections: <parsed JSON>
    task_to_sections: {}  (filled in Step 6)
    fallback_policy: state.manifest_fallback (arg-set, default "full_spec_on_blocker")
```

**Acceptance Criteria:**

```bash
grep -B 1 -A 10 'Build spec manifest' SKILL.md | grep -q 'build_spec_manifest.py'
grep -A 5 'task_to_sections' SKILL.md | grep -q 'Step 6'
```

**Risk**: MID (touches Phase 0 boot sequence).

**Depends on**: Task 0.

---

### Task 2: Extend Phase 0 Step 6 to compute task_to_sections

**Files:**
- `SKILL.md` (Phase 0 Step 6 — "Build dependency graph and identify compaction points")

Insert before the existing `compute global_constraints.shared_files` step:

```
6.3. Compute task_to_sections (C1):
  For each task in the plan, populate <active>.spec_manifest.task_to_sections[task_id]:

  a. Parse task body for "**Spec Refs:** <comma-separated section ids>" block.
     If present: use those IDs. Validate each in spec_manifest.sections — unknown ID is
     recorded as a Plan Reviewer BLOCKER input (Step 6.5).

  b. Else: heuristic. For each file in **Files:** block:
     - For each section in spec_manifest.sections:
       - If section.title contains any path component of the file (case-insensitive substring): match.
     - Collect matches across all files.
     - Dedupe.

  c. If no matches from step b: set ["*"] (full-spec fallback) AND record
     <active>.spec_manifest.task_to_sections[task_id] = {"sections": ["*"], "fallback_used": true}.

  Otherwise: <active>.spec_manifest.task_to_sections[task_id] = {"sections": [...], "fallback_used": false}.
```

**Acceptance Criteria:**

```bash
grep -B 1 -A 15 'Compute task_to_sections' SKILL.md | grep -q '"\*"'
grep -A 10 'Spec Refs' SKILL.md | grep -q 'BLOCKER'
```

**Risk**: MID (touches dependency graph pass).

**Depends on**: Task 1.

---

### Task 3: Extend Plan Reviewer with spec_manifest rubric

**Files:**
- `references/plan-reviewer-prompt.md`
- `SKILL.md` (Phase 0 Step 6.5 prose if it references rubric items)

Add 3 rubric items to `references/plan-reviewer-prompt.md`:

```markdown
### Rubric item: spec_manifest_invalid_ref (severity: BLOCKER)
Check every task body's **Spec Refs:** block. Each section ID must exist in the provided
spec_manifest.sections. Unknown ID → emit ISSUE_KEY {category: spec_manifest_invalid_ref,
task: <task_id>, evidence: <file:line of Spec Refs block>, suggested_fix: "<sentence>"}.

### Rubric item: spec_manifest_fallback_used (severity: WARN)
Check spec_manifest.task_to_sections. Any entry with fallback_used: true →
emit ISSUE_KEY {category: spec_manifest_fallback_used, task: <task_id>,
evidence: "<no **Spec Refs:** block and heuristic match failed>",
suggested_fix: "Add **Spec Refs:** <section_id_list> to task body to bypass full-spec fallback."}.

### Rubric item: spec_manifest_unused_section (severity: WARN)
Check spec_manifest.sections vs union of all task_to_sections lists. Any section
referenced by 0 tasks (excluding "*" tasks) → emit ISSUE_KEY {category:
spec_manifest_unused_section, section: <id>, evidence: "<section S{id} title='...'
not referenced by any task>", suggested_fix: "Either reference it explicitly or remove from spec."}.
```

Update `SKILL.md` Phase 0 Step 6.5 prose to pass `{spec_manifest_json}` to the Plan Reviewer prompt template.

**Acceptance Criteria:**

```bash
grep -q 'spec_manifest_invalid_ref' references/plan-reviewer-prompt.md
grep -q 'spec_manifest_fallback_used' references/plan-reviewer-prompt.md
grep -q 'spec_manifest_unused_section' references/plan-reviewer-prompt.md
grep -A 3 'Plan Reviewer prompt' SKILL.md | grep -q 'spec_manifest'
```

**Risk**: LOW.

**Depends on**: Task 2.

---

### Task 4: Update Implementer prompt builder to use spec_manifest

**Files:**
- `SKILL.md` (Phase 1 Step 1 — Implementer prompt builder)
- `references/implementer-prompt.md`

In `SKILL.md` Phase 1 Step 1, replace the existing `{relevant spec excerpt}` substitution logic with:

```
{relevant spec excerpt} substitution (v2.15):
  section_entry = <active>.spec_manifest.task_to_sections["task_<N>"]
  section_ids = section_entry.sections
  if "*" in section_ids:
    spec_text = full spec file contents
    section_label = "FULL (fallback)"
  else:
    spec_text = "## Spec context (sections: " + ", ".join(section_ids) + ")\n\n"
    for sid in section_ids in spec_manifest order:
      section = <active>.spec_manifest.sections[sid]
      slice = spec_file_lines[section.range[0]-1 : section.range[1]]
      spec_text += "\n".join(slice) + "\n\n"
    section_label = ", ".join(section_ids)
  Substitute {relevant spec excerpt} → spec_text
  Substitute {spec_section_label} → section_label (new placeholder — add to template)
```

In `references/implementer-prompt.md`, add `{spec_section_label}` placeholder near top in the run-context section.

Also handle SPEC_BLOCKER fallback (spec §C1.4): if Implementer ESCALATEs SPEC_BLOCKER and `blocker` text matches regex `(missing context|missing section|ambiguous reference|insufficient spec)`:
- If `<active>.spec_manifest.fallback_policy == "full_spec_on_blocker"`: re-dispatch with full spec, increment `spec_clarifications`, return to Step 1.
- Else: standard ESCALATE handling.

**Acceptance Criteria:**

```bash
grep -B 1 -A 15 'relevant spec excerpt' SKILL.md | grep -q 'section_ids'
grep -q '{spec_section_label}' references/implementer-prompt.md
grep -E 'full_spec_on_blocker' SKILL.md
```

**Risk**: MID (hot path; affects every Implementer dispatch).

**Depends on**: Tasks 1, 2.

---

### Task 5: Handle spec-edit branch manifest recompute

**Files:**
- `SKILL.md` (Phase 1 Step 2 spec-edit branch)

In the spec-edit branch (after spec edit commit succeeds, before re-dispatching Implementer):

```
After committing the spec edit:
  6.5 Recompute spec_manifest (C1):
      Re-run: python3 <skill_dir>/scripts/build_spec_manifest.py <spec_path>
      Update <active>.spec_manifest.sections in place.
      For incomplete downstream tasks whose previous task_to_sections.sections overlap the edited line range:
        re-run Step 6.3 heuristic for those tasks; update task_to_sections.
      Append to state.spec_edits[-1]: manifest_recompute: true, manifest_recompute_at: <iso>.
```

**Acceptance Criteria:**

```bash
grep -B 1 -A 6 'Recompute spec_manifest' SKILL.md | grep -q 'build_spec_manifest.py'
grep -q 'manifest_recompute' SKILL.md
```

**Risk**: MID (spec-edit branch is rare but high-impact when fired).

**Depends on**: Tasks 1, 4.

---

## Phase 2 — C2 (decisions register)

### Task 6: Extend Phase 1 Step 4 to append decisions_register

**Files:**
- `SKILL.md` (Phase 1 Step 4 — Agent Cleanup, AFTER task_summaries write)

Add a substep:

```
3.5. Append to decisions_register (C2):
  Read task_summaries.<task_id>.key_decision.
  If non-empty AND not "(none)" AND not "n/a" (case-insensitive):
    Append to <active>.decisions_register:
      {task: <task_id>,
       decision: <key_decision text, ≤15 words verified>,
       files: <task_summaries.files>,
       made_at: <iso8601>,
       supersedes: null}
  Atomic state.json write (R-M-W).
  Failure → log warning, continue (best-effort).
```

**Acceptance Criteria:**

```bash
grep -B 1 -A 10 'Append to decisions_register' SKILL.md | grep -q 'key_decision'
grep -E 'supersedes.*null' SKILL.md
```

**Risk**: LOW.

**Depends on**: none (independent of C1 — could land before).

---

### Task 7: Inject decisions_register into Implementer prompt

**Files:**
- `SKILL.md` (Phase 1 Step 1 — Implementer prompt builder)
- `references/implementer-prompt.md`

In `SKILL.md` Phase 1 Step 1, add a new substitution rule:

```
{decisions_register} substitution (v2.15):
  register = <active>.decisions_register
  if register is empty: spec_text = ""
  else:
    lines = ["## Project decisions so far (do NOT re-decide; raise objection via Reviewer if any seem wrong):"]
    for entry in register, sorted by made_at ascending:
      if entry.supersedes is not None:
        prefix = "~~[SUPERSEDED by " + entry.supersedes + "]~~ "
      else:
        prefix = ""
      file_list = ", ".join(entry.files) if entry.files else "(no files)"
      lines.append("- " + prefix + "[" + entry.task + "] " + entry.decision + " — " + file_list)
    spec_text = "\n".join(lines) + "\n\n"
  Substitute {decisions_register} → spec_text
```

In `references/implementer-prompt.md`, add `{decisions_register}` placeholder near top, immediately after role declaration and before the task description.

**Acceptance Criteria:**

```bash
grep -B 1 -A 15 'decisions_register substitution' SKILL.md | grep -q 'supersedes'
grep -q '{decisions_register}' references/implementer-prompt.md
grep -A 3 '{decisions_register}' references/implementer-prompt.md | grep -q 'Project decisions'
```

**Risk**: LOW.

**Depends on**: Task 6.

---

### Task 8: Inject decision-conflict rubric into Combined Reviewer

**Files:**
- `references/reviewer-prompt.md`
- `SKILL.md` (Phase 1 Step 2 — Combined Reviewer dispatch)

Add to `references/reviewer-prompt.md` (in the rubric section):

```markdown
### Decision consistency (C2)
You are provided the current decisions_register. For the diff under review:
- Identify any new approach (library choice, schema, naming convention, pattern) that contradicts an existing register entry.
- If found: emit a QUALITY_ISSUE with:
  - category: decision_conflict
  - issue_key: decision_conflict::<file>:<line>
  - text: "Conflicts with [<task_id>] '<existing decision text>' — new code uses <X> where register says <Y>."
- Do NOT downgrade SPEC_SCORE for decision conflicts — only QUALITY_SCORE.
- If the new approach is intentional supersession (e.g., diff includes a comment "supersedes <task_id>"): do NOT flag; instead emit an ADVISORY note.
```

In `SKILL.md` Phase 1 Step 2, add `{decisions_register}` to the Combined Reviewer prompt substitutions (rendered the same way as Implementer, see Task 7).

**Acceptance Criteria:**

```bash
grep -q 'Decision consistency (C2)' references/reviewer-prompt.md
grep -q 'decision_conflict' references/reviewer-prompt.md
grep -A 5 'Combined Reviewer' SKILL.md | grep -q 'decisions_register'
```

**Risk**: LOW (adds rubric — does not remove existing).

**Depends on**: Tasks 6, 7.

---

### Task 9: Project decisions_register to DECISIONS.md

**Files:**
- `SKILL.md` (Phase Transition T3, Phase 2 Step 1)

Add a substep at T3 (after batch verifier, before context_health emit):

```
T3.1.5. Project decisions to DECISIONS.md (C2):
  Render <worktree>/.orchestrator/DECISIONS.md from <active>.decisions_register.
  Format: markdown table with columns [Task, Decision, Files, Made at, Supersedes].
  Sort by made_at ascending. Group superseded entries at bottom.
  Atomic write (write to tmp, mv).
  File is included in archive tarball (F1).
```

Same projection runs at Phase 2 Step 1 as final pass.

**Acceptance Criteria:**

```bash
grep -B 1 -A 8 'Project decisions to DECISIONS' SKILL.md
grep -q 'DECISIONS.md' SKILL.md
```

**Risk**: LOW.

**Depends on**: Task 6.

---

## Phase 3 — C3 (token-based chain trigger)

### Task 10: Implement token-based should_chain logic

**Files:**
- `SKILL.md` (Resume Chain procedure — trigger section)

Replace the existing trigger paragraph ("Chain ONLY when both: compaction_points ≥ 2 AND completed ≥ 8.") with:

```
**Trigger (v2.15 — token-aware, deterministic, introspectable):**

Chain when ANY of the following holds at Phase Transition T3 (or end of Phase 1 Step 4 if
current_task is a compaction_point):

1. Token threshold (NEW, primary):
   - Requires state.budget_action != "off" AND state.cost_ledger present.
   - Compute: session_input_tokens = cost_ledger.totals.input_tokens - cost_ledger.totals.cached_read_tokens.
   - Threshold: state.context_budget.threshold_tokens (default 102000 = 60% of 170000).
   - Fire if session_input_tokens >= threshold.

2. Legacy floor (PRESERVED, fallback):
   - state.compaction_points_reached >= 2 AND complete_count >= 8.
   - Always evaluated regardless of budget_action.

If both evaluate true, log trigger_reason as "token_threshold" (first observed).
If only legacy, trigger_reason = "legacy_floor".
If neither, no chain.
```

Update the related Guardrail (currently "Resume Chain trigger is deterministic") with the new criteria.

**Acceptance Criteria:**

```bash
grep -B 1 -A 20 'Trigger.*v2.15.*token-aware' SKILL.md | grep -q 'session_input_tokens'
grep -E 'Legacy floor.*PRESERVED' SKILL.md
```

**Risk**: MID (changes chain dispatch — affects long-running sessions).

**Depends on**: v2.14 Task 3 (cost ledger must be populated).

---

### Task 11: Add context_budget fields + arg parser

**Files:**
- `SKILL.md` (Phase 0 Step 7 state.json init + Phase -1.0 Pass 1)

Add to state.json initializer:

```json
"context_budget": {
  "effective_input_budget": 170000,
  "threshold_ratio": 0.60,
  "threshold_tokens": 102000,
  "last_evaluation_at": null,
  "last_evaluation_tokens": 0
}
```

Run-level (top-level), NOT per-plan. Defaults apply.

If args contain `context_budget=<int>` or `context_threshold=<float>`: overwrite the corresponding field. Recompute threshold_tokens = effective_input_budget * threshold_ratio.

Add to Phase -1.0 Pass 1 recognized keys: `context_budget`, `context_threshold`, `manifest_fallback`.

Validation:
- `context_budget`: positive int, > 10000. Else halt.
- `context_threshold`: float in [0.05, 0.95]. Else halt.
- `manifest_fallback`: one of `full_spec_on_blocker`, `halt_on_blocker`. Else halt.

**Acceptance Criteria:**

```bash
grep -A 8 'context_budget.*effective_input_budget' SKILL.md
grep -E 'context_budget=<int>' SKILL.md
grep -E 'manifest_fallback=' SKILL.md
```

**Risk**: LOW.

**Depends on**: Task 10.

---

### Task 12: Wire chain_trigger_eval telemetry

**Files:**
- `SKILL.md` (Phase Transition T3 — context_health emit section)

After the existing context_health snapshot emit (T3 step 3), add a second context_health emit:

```
T3.3.5. Emit chain_trigger_eval (C3):
  Compute trigger result via should_chain logic (Task 10).
  Update state.context_budget.last_evaluation_tokens = session_input_tokens.
  Update state.context_budget.last_evaluation_at = now ISO.

  Write candidate event to <worktree>/.orchestrator/learning_events/trigger_<compaction_index>-orchestrator.json:
    schema_version: "1"
    phase: "phase_transition"
    event_type: "context_health"
    severity: "low"
    execution: {task_id: "transition_<compaction_index>", issue_key: "chain_trigger_eval"}
    summary: "Chain trigger eval: <result>"
    context: {
      trigger_decision: "chained" | "not_chained",
      trigger_reason: "token_threshold" | "legacy_floor" | "none",
      session_input_tokens: <int>,
      threshold_tokens: <int>,
      compactions_reached: <int>,
      completed_count: <int>
    }
    privacy: {redacted: true, notes: "Counters only."}

  Append silently (|| true).

  If trigger_decision == "chained": proceed with existing Resume Chain procedure.
```

**Acceptance Criteria:**

```bash
grep -B 1 -A 18 'Emit chain_trigger_eval' SKILL.md | grep -q 'trigger_decision'
grep -E 'chain_trigger_eval' SKILL.md
```

**Risk**: LOW.

**Depends on**: Tasks 10, 11.

---

## Phase 4 — Documentation + version

### Task 13: Add v2.15 guardrails

**Files:**
- `SKILL.md` (Guardrails table)

Add 4 rows:

| Rule | Detail |
|------|--------|
| **Spec manifest is per-plan** | `spec_manifest` lives under `<active>` per the v2.13 resolution rule. Each plan in a chain has its own manifest. `task_to_sections` references are validated by Plan Reviewer at Phase 0 Step 6.5 — unknown section IDs are BLOCKER. |
| **Decisions register is per-plan, append-only** | `decisions_register` lives under `<active>`. Entries are never deleted — supersession is recorded via `supersedes` field. Empty `key_decision` from task_summaries is ignored (not appended). |
| **Decision conflict is a QUALITY issue, not SPEC** | Combined Reviewer flags `decision_conflict` under QUALITY_ISSUES. Does NOT downgrade SPEC_SCORE. Standard retry budget applies — no spec-edit branch. Use it to nudge sub-agents toward consistency, not to halt. |
| **Token-based chain trigger is additive** | C3's `session_input_tokens >= threshold` trigger fires *in addition to* legacy `compactions ≥ 2 AND completed ≥ 8`. Never replaces. `budget_action=off` disables token trigger (legacy is sole criterion). |

**Acceptance Criteria:**

```bash
grep -q "Spec manifest is per-plan" SKILL.md
grep -q "Decisions register is per-plan" SKILL.md
grep -q "decision_conflict is a QUALITY" SKILL.md
grep -q "Token-based chain trigger" SKILL.md
```

**Risk**: LOW.

**Depends on**: Tasks 4, 7, 8, 10.

---

### Task 14: Bump version + HISTORY.md + JOURNAL.md + findings doc

**Files:**
- `SKILL.md` (metadata.version)
- `HISTORY.md`
- `docs/experiments/v2.15-context-engineering/JOURNAL.md` (new)
- `docs/experiments/v2.15-context-engineering/findings/v2.14-vs-v2.15-tokens.md` (new placeholder)

Update `SKILL.md`: `version: "2.15.0"`, `updated_at: "<today>"`.

Add `HISTORY.md` `# v2.15.0` section. Cover all 3 features briefly.

Create JOURNAL.md with opening entry (template matches v2.14).

Create findings/ doc as a TEMPLATE — the actual measurements get filled in after first real A/B run:

```markdown
# v2.14 vs v2.15 — Token cost A/B

Plan: <fixture plan, e.g., evals/fixtures/v2.15-ab-target.md>
Spec size: <chars>

## Baseline (v2.14)
- Total Implementer dispatches: N
- Median input_tokens per dispatch: X
- Total input_tokens (non-cached): Y

## Treatment (v2.15)
- Total Implementer dispatches: N
- Median input_tokens per dispatch: X'
- Total input_tokens (non-cached): Y'

## Verdict
- Median ratio (treatment / baseline): <ratio>
- G1 acceptance (≤ 0.50): <PASS|FAIL>

## Notes
(observations, edge cases, follow-ups)
```

**Acceptance Criteria:**

```bash
grep -q 'version: "2.15.0"' SKILL.md
grep -q '# v2.15' HISTORY.md
test -f docs/experiments/v2.15-context-engineering/JOURNAL.md
test -f docs/experiments/v2.15-context-engineering/findings/v2.14-vs-v2.15-tokens.md
```

**Risk**: LOW.

**Depends on**: ALL prior tasks.

---

## Dependency graph (compaction points marked)

```
Task 0 (build_spec_manifest.py)           [LOW, SMALL]
  └─ Task 1 (Phase 0 Step 3 patch)         [MID, MEDIUM]
       └─ Task 2 (Phase 0 Step 6 patch)    [MID, MEDIUM]
            ├─ Task 3 (Plan Reviewer rubric)  [LOW, SMALL]
            └─ Task 4 (Implementer prompt) [MID, MEDIUM]
                 └─ Task 5 (spec-edit recompute) [MID, MEDIUM]
═══════════════ compaction point 1 (C1 complete) ═══════════════
Task 6 (decisions_register append)        [LOW, SMALL]
  ├─ Task 7 (Implementer inject)          [LOW, SMALL]
  ├─ Task 8 (Reviewer rubric)             [LOW, SMALL]
  └─ Task 9 (DECISIONS.md projection)     [LOW, SMALL]
═══════════════ compaction point 2 (C2 complete) ═══════════════
Task 10 (should_chain logic)              [MID, MEDIUM]
  └─ Task 11 (context_budget fields)      [LOW, SMALL]
       └─ Task 12 (chain_trigger_eval)    [LOW, SMALL]
═══════════════ compaction point 3 (C3 complete) ═══════════════
Task 13 (guardrails)                      [LOW, SMALL]
  └─ Task 14 (version + history + journal + findings) [LOW, SMALL]
═══════════════ compaction point 4 (FINAL) ═══════════════
```

## Resource Key annotations

- Tasks 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14: **Resource Key:** `skill-md`
- Tasks 3, 8: **Resource Key:** `references-*` (different files — no collision)

## Parallelization opportunities

- Tasks 3 and 4 are file-disjoint (`references/plan-reviewer-prompt.md` vs SKILL.md) — but Task 3 depends on Task 2 (manifest_json plumbing). Sequence them.
- Tasks 7, 8, 9 are mostly file-disjoint after Task 6 lands — but all hit SKILL.md (`skill-md` resource key forces serialization).

## Risk override

Default per-task risk levels above. If `risk=low` override: Tasks 1, 2, 4, 5, 10 (MID-by-design due to hot-path touch) will skip per-task Verifier. Mitigation: batch verifier sweep at every compaction point will catch regressions but at higher remediation cost.

## Definition of Done

See spec §"Definition of Done" — all checkboxes verified at Phase 2 method audit.
