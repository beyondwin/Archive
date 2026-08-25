# Post-merge Manual Verification — kws-claude-multi-agent-executor

These steps cannot run inside the autonomous worktree because they need
access to the user's real `~/.claude/projects/` JSONL transcripts. Run
them **once** after the AgentLens-v1 + kws-skill-unification branch
merges to main.

## 1. Real Claude session import

```bash
agentlens import claude-session --latest
```

**Expected:**

- Exit code 0.
- At least one new capture-run row in `~/.agentlens/runs/<workspace_id>/`.
- The new run's `run.json` carries:
  - `run_kind == "capture"`
  - `recording.transcript_source == "claude-session-jsonl"`
  - `input.import_key == "claude-session:<session-id>"`
- The transcript bytes live at
  `artifacts/transcripts/<session-id>.jsonl` and are byte-identical to
  the source JSONL.

## 2. Cross-skill query sanity

```bash
agentlens events --type 'kws-cme.*' | head -5
```

**Expected:** at least one line of JSONL whose `type` begins with
`kws-cme.` (e.g. `kws-cme.task_started`) emitted by a recent
orchestrator run.

## 3. Failure-isolation smoke (optional)

Confirm the orchestrator still completes when AgentLens is misconfigured:

```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash -c \
  "agentlens event append --run X --type kws-cme.test --payload-json '{}' 2>/dev/null || true; echo ok"
```

**Expected:** prints `ok` even though `agentlens` is not on `PATH` in
the sub-shell.

---

The automated coverage for these contracts lives in
`AgentLens/tests/integration/test_failure_isolation.py` (Task 14) and
`AgentLens/tests/integration/test_phase1_smoke.py` (Task 9). The manual
steps above only re-verify against the user's real Claude project data,
which is intentionally never available inside an evaluator sandbox.
