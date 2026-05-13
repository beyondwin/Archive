# Troubleshooting

Common issues encountered while running, developing, or debugging this skill.
Each entry has: symptom · likely cause · diagnostic · fix.

If you're looking for a *risk* or *acknowledged limitation*, see
[`./risks-and-limitations.md`](./risks-and-limitations.md). This file is
for *operational issues with concrete fixes*.

---

## Skill execution issues

### Symptom: orchestrator skips Phase 0 Step 7.5 (no run dir created)

**Likely cause**: pre-v2.8.1 SKILL.md, or the orchestrator under heavy
contextual load.

**Diagnostic**:
```bash
grep "LEARNING_LOG_INIT:" <run.jsonl-path>
# Empty → Step 7.5 was not executed.
# Non-empty → step ran (check whether RUN_ID was emitted vs SKIPPED).
```

Filesystem cross-check:
```bash
find ~/.claude/learning/kws-claude-multi-agent-executor/runs -newer <run.jsonl> -type d
# Empty → no run dir was created.
```

**Fix**:
- If SKILL.md version < 2.8.1: bump to ≥2.8.1.
- If 2.8.1 and adherence still fails: surface the regression to the user.
  This is the scenario [`./deferred-candidates.md`](./deferred-candidates.md)
  §Hook-based enforcement is designed for.

**Reference**: [`./risks-and-limitations.md`](./risks-and-limitations.md) §Orchestrator adherence.

### Symptom: `MAE_LEARNING_RUN_ID` is empty when sub-agents try to use it

**Likely cause**: Step 7.5 helper script failed silently (file not
executable, Python missing, write failure to `~/.claude/learning/`).

**Diagnostic**:
```bash
python3 ~/.claude/skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py init-run \
  --repo-root $(pwd) --repo-name test --branch main \
  --plan-path /tmp/p.md --spec-path /tmp/s.md
# Expected: prints RUN_ID + creates run dir.
# If errors: read stderr — likely permissions, Python version, or
# learning-events directory missing.
```

**Fix**:
- Ensure `~/.claude/learning/` is writable.
- Verify `python3` is on PATH (`which python3`).
- Verify the helper script is executable (`chmod +x` not needed; it's
  invoked via `python3 <path>`).

### Symptom: meta.json says `outcome=unknown` after run finished

**Likely cause**: orchestrator did not reach a close-run path — hard crash,
SIGKILL, or a step path that skipped Phase 2.

**Diagnostic**:
- Check `state.json` in the worktree — is the last task `COMPLETE`?
- Check the run.jsonl tail — was there an unhandled exception?

**Fix**:
- If the run was successful but close-run was skipped → manually run:
  ```bash
  python3 ~/.claude/skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py close-run \
    --run-id <run_id> --outcome success
  ```
- If the run crashed → leaving `outcome=unknown` is honest. Investigate
  the crash root cause; don't manually rewrite the outcome.

### Symptom: orchestrator dispatched sub-agent but no Reviewer output appeared

**Likely cause**: Agent tool dispatch failed silently, or the sub-agent
hit a tool that wasn't approved.

**Diagnostic**:
- Search run.jsonl for `"name": "Agent"` tool_use entries near the
  expected dispatch point.
- Check whether the corresponding tool_result is present (means the
  sub-agent finished and returned).

**Fix**:
- If dispatch missing: rerun with `--debug` flag (Claude Code CLI option).
- If tool_result missing: subagent ran but didn't return — likely hung
  on an unapproved tool. Re-run with `--dangerously-skip-permissions`
  if appropriate.

---

## Eval system issues

### Symptom: doc freshness check reports drift

**Likely cause**: you shipped a change without the corresponding doc
update.

**Diagnostic**:
```bash
python3 evals/check_doc_freshness.py
```

Examine `failures[]` — each entry names the drift.

**Fix**: consult [`./doc-update-protocol.md`](./doc-update-protocol.md)
for the per-change-type checklist matching what you shipped. Common cases:
- Version mismatch → bump `SKILL.md`, the skill `README.md`, and `HISTORY.md`
  in the same commit.
- Broken link → fix the path or update the target
- Missing HISTORY entry → add §1 entry for current version
- Missing snapshot → write `docs/snapshots/v<X>.md` for minor bump
- ADR not indexed → add row to `docs/decision-log.md`

If the drift is intentional (e.g., a placeholder link in a template):
add it to the `_template` exclusion or wrap in backticks (code-span text
is skipped).

### Symptom: `evals/run.sh` fails preflight

**Likely cause**: contract eval regression (you broke a prompt or SKILL.md
edit that the 18 contract checks watch for).

**Diagnostic**:
```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_learning_log.py
```

The output identifies which check failed.

**Fix**: address the specific check. Common failures:
- `skill_call_in_references_reviewer-prompt.md` → Reviewer prompt
  missing the `Skill("superpowers:requesting-code-review")` invocation.
- `skill_md_v281_mandatory_framing` → SKILL.md Step 7.5 missing one of:
  MANDATORY / DO NOT SKIP THIS STEP / LEARNING_LOG_INIT:.
- `candidate_file_contract_in_references_*.md` → sub-agent prompt
  missing `.orchestrator/learning_events/` or "Do not call the helper".

### Symptom: `evals/run.sh` produces `judge mean = 0` / `judge invocation failed`

**Likely cause**: the judge `claude -p` invocation failed (network, auth,
or rate limit), OR the judge output was unparseable.

**Diagnostic**:
- Read `<tmpdir>/.harness/run.jsonl` tail — is there an error?
- Try invoking `claude -p` manually with a trivial prompt to verify auth.

**Fix**:
- Auth: `claude login` to refresh credentials.
- Rate limit: wait, then re-run.
- Unparseable: read `<tmpdir>/.harness/judge_input.txt` — the judge
  prompt may have leaked an unsubstituted placeholder. Fix the
  substitution in run.sh's `judge_prompt` block.

### Symptom: rubric pass_rate = null (no rubric output)

**Likely cause**: fixture YAML missing `expected.rubric` block, OR the
worktree path the rubric runner expected doesn't exist.

**Diagnostic**:
```bash
jq '.expected.rubric' evals/fixtures/<fixture>.yaml
# Empty → fixture lacks a rubric (run.sh prints null; not an error).
ls /var/folders/.../<tmpdir>/worktrees/
# Empty → orchestrator failed before creating the worktree.
```

**Fix**:
- If fixture intentionally has no rubric: ignore.
- If worktree missing: orchestrator failed at Phase 0; debug Phase 0
  (likely missing plan.md or spec.md file).

### Symptom: `learning_log_adherence: no` but the run succeeded

**Likely cause**: Step 7.5 was skipped, but the rest of the orchestrator
worked.

**Impact**: Per-run observability is lost (no meta.json, no events.jsonl).
The run's correctness is unaffected.

**Fix**: This is the v2.8.0-era regression that v2.8.1 fixes. If you see
this under v2.8.1+, file as a real bug — adherence has regressed.

---

## Branch / merge issues

### Symptom: cross-references to `../v2.8-learning-log/` fail to resolve

**Likely cause**: you're on `main` (or a branch off main before v2.8
merged in). v2.8 commits live on `codex/executor-learning-log`.

**Diagnostic**:
```bash
git log --oneline main..codex/executor-learning-log | grep "v2.8\|v2.9"
```

**Fix**:
- If you need to read v2.8/v2.9 docs: `git checkout codex/executor-learning-log`.
- If you're merging: cherry-pick or merge the Claude executor commits
  to main first, then resolve docs paths.

### Symptom: `git status` shows the user's Codex executor changes unstaged

**Likely cause**: this is normal. The branch is shared. User's parallel
work and your Claude executor work coexist as path-isolated changes.

**Diagnostic**:
```bash
git status --short | grep "skills/kws-codex"
# These belong to the user — don't touch.
```

**Fix**: Stage only Claude executor files
(`skills/kws-claude-multi-agent-executor/`) and any Archive-level README rows
for *your* skill version. Leave Codex changes alone.

---

## Learning-log issues

### Symptom: `find_open_run` returns the wrong run_id

**Likely cause**: a previous run left `outcome=unknown` (hard crash) and
the helper's idempotency probe is matching it.

**Diagnostic**:
```bash
ls ~/.claude/learning/kws-claude-multi-agent-executor/runs/<today>/
# For each run dir, check meta.outcome.
```

**Fix**:
- Manually close the stale run: `append_learning_event.py close-run
  --run-id <id> --outcome unknown` (records honest unknown).
- Or move the stale dir to an archive location if the run is truly defunct.

### Symptom: events.jsonl has duplicate entries

**Likely cause**: orchestrator scanned `learning_events/` twice without
deleting candidates, OR multiple orchestrator instances are sharing the
same `MAE_LEARNING_RUN_ID`.

**Diagnostic**:
- Compare `event_id` values in the JSONL — duplicates are the sentinel.
- Check process tree: `pgrep -f "claude -p"` should show only one
  orchestrator per worktree.

**Fix**:
- Single-writer contract: orchestrator must delete each candidate file
  after appending. If it didn't (e.g., crashed between append + delete),
  the next scan re-appends.
- The helper's `event_id` = sha256-16 of content; future de-dup logic
  could exploit this but isn't currently implemented.

### Symptom: meta.json's `worktree_path` looks absolute

**Likely cause**: pre-v2.8 helper (no relativization), or worktree was
created outside any repo root.

**Diagnostic**:
- Check helper version: `head -20 scripts/append_learning_event.py`
  should show the relativize function.
- Verify the worktree IS inside a git repo:
  `git -C <worktree_path> rev-parse --show-toplevel`.

**Fix**:
- If pre-v2.8 helper: install current version from this directory.
- If worktree truly is outside a repo: relativization fails-safe to
  absolute. Not a bug; the worktree creation logic should be re-checked.

---

## Catch-all

### When in doubt, gather these artifacts and surface to user

For any unfamiliar failure, collect:

```bash
# 1. State at failure time
cat <worktree>/.orchestrator/state.json | jq '.tasks'

# 2. Last 100 lines of run.jsonl
tail -100 <tmpdir>/.harness/run.jsonl

# 3. Learning log meta + events (if dir exists)
cat ~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/meta.json
cat ~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/events.jsonl

# 4. Git state
git -C <worktree> log --oneline -10
git -C <worktree> status

# 5. Any recent baselines
ls -la evals/baselines/
```

Then ask the user. This skill ships with a complex execution model;
many failures look identical at first glance.

## How to update this file

When you debug an issue that took >10 minutes to diagnose, add a section:
- Symptom (one sentence)
- Likely cause (one sentence)
- Diagnostic command (concrete)
- Fix (concrete)

The "what made this hard" knowledge is the most valuable part. Don't
let it die with your session.
