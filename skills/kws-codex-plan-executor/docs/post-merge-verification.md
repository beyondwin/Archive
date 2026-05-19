# Post-merge Manual Verification — kws-codex-plan-executor

These steps cannot run inside the autonomous worktree because they need
access to the user's real `~/.codex/` rollout JSONL transcripts (CLI
and Desktop, including archived sessions). Run them **once** after the
AgentLens-v1 + kws-skill-unification branch merges to main.

## 1. Real Codex session import (CLI + archived)

```bash
agentlens import codex-session --latest --include-archived
```

**Expected:**

- Exit code 0.
- At least one new capture-run row in `~/.agentlens/runs/<workspace_id>/`.
- The new run's `run.json` carries:
  - `run_kind == "capture"`
  - `recording.transcript_source == "codex-rollout-jsonl"`
  - `input.import_key == "codex-rollout:<uuidv7>"`
  - `meta.originator` preserved from `session_meta` (e.g. `"Codex CLI"`
    or `"Codex Desktop"`); confirm both originators show up across
    multiple imports if both clients were used recently.
- The transcript bytes live at
  `artifacts/transcripts/<session-id>.jsonl` and are byte-identical to
  the source JSONL.

## 2. Cross-skill query sanity

```bash
agentlens events --type 'kws-cpe.*' | head -5
```

**Expected:** at least one line of JSONL whose `type` begins with
`kws-cpe.` (e.g. `kws-cpe.phase_started`) emitted by a recent
orchestrator run.

## 3. Failure-isolation smoke (optional)

Confirm the orchestrator still completes when AgentLens is misconfigured:

```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash -c \
  "agentlens event append --run X --type kws-cpe.test --payload-json '{}' 2>/dev/null || true; echo ok"
```

**Expected:** prints `ok` even though `agentlens` is not on `PATH` in
the sub-shell.

---

The automated coverage for these contracts lives in
`AgentLens/tests/integration/test_failure_isolation.py` (Task 14) and
`AgentLens/tests/integration/test_phase1_smoke.py` (Task 9). The manual
steps above only re-verify against the user's real Codex rollout data,
which is intentionally never available inside an evaluator sandbox.
