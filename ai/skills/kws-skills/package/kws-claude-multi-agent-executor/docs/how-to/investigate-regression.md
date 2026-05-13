# How to investigate a regression

When `bash evals/run.sh` produces a judge mean lower than the previous
baseline, or a rubric `pass_rate` drops, or `learning_log_adherence: no`
appears unexpectedly. A regression is a *change in eval output that
correlates with a known code/prompt change*.

This guide is the diagnostic recipe. For routine operational issues
without regression context, see [`../troubleshooting.md`](../troubleshooting.md).

## Step 1 — Confirm it is a regression

A single rep can fluctuate. Before chasing:

```bash
# Compare current baseline vs previous version
diff <(jq -S . evals/baselines/v<previous>.json) <(jq -S . evals/baselines/v<current>.json)
```

If only one fixture's mean dropped by ≤0.05 with similar rubric: likely
single-rep noise. Re-run to confirm.

```bash
# Re-run the suspect fixture
bash evals/run.sh evals/fixtures/<fixture>.yaml > /tmp/rerun.log 2>&1
tail -20 /tmp/rerun.log
```

If the second run also shows the regression: proceed. If it returns to
baseline: log the variance, no action needed.

## Step 2 — Localize the regression

Identify which axis dropped:

```bash
# Per-fixture axis breakdown
jq '.fixtures[] | {fixture, mean, scores}' evals/baselines/v<current>.json
```

Map the drop to a category:

| Drop in | Likely cause | First place to look |
|---------|--------------|---------------------|
| `correctness` (or rubric pass_rate) | Implementer regression | Implementer prompt, model defaults, fixture rubric |
| `spec_compliance` | Reviewer regression | Reviewer prompt (SPEC_COVERAGE_WALK), spec excerpt clarity |
| `code_quality` | Reviewer or judge regression | Reviewer prompt (Part 2), judge prompt thresholds |
| `cost_efficiency` | Token budget regression | Effort guidance, retry-loop behavior |
| `learning_log_adherence: no` | Step 7.5 skipped | SKILL.md framing, MAE_LEARNING_RUN_ID propagation |

## Step 3 — Locate the change that caused it

```bash
# What changed in this skill since the previous baseline?
git log --oneline v<previous-tag>..HEAD -- ai/skills/kws-skills/package/kws-claude-multi-agent-executor
```

Cross-reference each commit against the regression axis:

- Prompt change in `references/<role>-prompt.md` → check whether the
  edit changed scoring anchors, output format, or instruction strength.
- SKILL.md change → check phase-step numbering and dispatch logic.
- Helper script change → run the helper standalone to verify it works.
- Eval harness change → run preflight + recheck rubric.py output format.

## Step 4 — Extract the actual run.jsonl

```bash
# Find the fixture's tmpdir (most recent)
TMPDIR=$(ls -dt /var/folders/01/*/T/mae-eval-parent-<fixture>.* 2>/dev/null | head -1)
echo $TMPDIR

# The run transcript
RUN_JSONL=$TMPDIR/repo/.harness/run.jsonl
ls -la $RUN_JSONL
```

This file is the source of truth for what the orchestrator + sub-agents
actually did, not what they were told to do.

## Step 5 — Inspect by tool type

```python
# Save as /tmp/inspect.py and run with python3 /tmp/inspect.py
import json, sys
from collections import Counter

path = sys.argv[1]
tools = Counter()
agents = []
errors = []

for line in open(path):
    try: d = json.loads(line)
    except: continue
    msg = d.get('message', {})
    if d.get('type') == 'assistant':
        for c in msg.get('content', []):
            if isinstance(c, dict) and c.get('type') == 'tool_use':
                tools[c.get('name')] += 1
                if c.get('name') == 'Agent':
                    agents.append({
                        'id': c['id'],
                        'desc': c.get('input', {}).get('description', '?'),
                        'subtype': c.get('input', {}).get('subagent_type', '?'),
                    })
    if d.get('type') == 'user' and isinstance(msg.get('content'), list):
        for c in msg['content']:
            if isinstance(c, dict) and c.get('type') == 'tool_result' and c.get('is_error'):
                errors.append(c.get('content', '')[:200])

print("Tool counts:", dict(tools))
print("\nAgent dispatches:")
for a in agents:
    print(f"  - [{a['subtype']}] {a['desc']}")
print(f"\nError tool_results: {len(errors)}")
for e in errors[:5]:
    print(f"  - {e}")
```

```bash
python3 /tmp/inspect.py $RUN_JSONL
```

Key questions:
- Did the expected number of Implementer + Reviewer + Verifier dispatches happen?
- Are there error tool_results (indicating sub-agent failures)?
- Is the LEARNING_LOG_INIT: marker present in non-empty run dirs?

## Step 6 — Extract the failing sub-agent's output

If you know which sub-agent regressed (e.g., Reviewer), extract its
full output:

```python
# Save as /tmp/extract.py
import json, sys, re

path, role = sys.argv[1], sys.argv[2]   # e.g. "Reviewer" or "Verifier"
agent_uses, agent_results = {}, {}

for line in open(path):
    try: d = json.loads(line)
    except: continue
    msg = d.get('message', {})
    if d.get('type') == 'assistant':
        for c in msg.get('content', []):
            if isinstance(c, dict) and c.get('type') == 'tool_use' and c.get('name') == 'Agent':
                agent_uses[c['id']] = c.get('input', {}).get('description', '?')
    if d.get('type') == 'user' and isinstance(msg.get('content'), list):
        for c in msg['content']:
            if isinstance(c, dict) and c.get('type') == 'tool_result':
                tid = c.get('tool_use_id')
                if tid in agent_uses:
                    ct = c.get('content', '')
                    if isinstance(ct, list): ct = ''.join(b.get('text','') for b in ct if isinstance(b, dict))
                    agent_results[tid] = ct

for tid, desc in agent_uses.items():
    if role in desc:
        print(f"\n{'='*70}\n{desc}\n{'='*70}")
        print(agent_results.get(tid, '(no result)'))
```

```bash
python3 /tmp/extract.py $RUN_JSONL Reviewer
```

Compare against the prompt template (`references/<role>-prompt.md`):
- Did the sub-agent follow the output format?
- Are scores in the expected range?
- Are `SPEC_FAULT` / `SPEC_COVERAGE_WALK` / etc. present per the version?

## Step 7 — Compare against the prior-version artifact

If the regression is on a specific Reviewer behavior, run the *previous
version's* prompt against the same fixture (manually, via the Agent tool
in your session) and diff:

```bash
git show v<previous-tag>:ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/reviewer-prompt.md > /tmp/prev-reviewer-prompt.md
diff /tmp/prev-reviewer-prompt.md references/reviewer-prompt.md
```

Identify which line of the diff plausibly caused the behavior change.

## Step 8 — Decide: fix or document

If the regression is small and tractable: fix it. Open an experiment
record if the fix is ≥50 lines or has its own hypothesis.

If the regression is real but the cost of fixing exceeds the cost of
the loss: document in [`../risks-and-limitations.md`](../risks-and-limitations.md)
and HISTORY.md, ship a known-limitation note.

If the regression turns out to be eval-side (judge calibration drift,
fixture spec ambiguity): the *eval* is the bug. Fix the fixture or
recalibrate the judge — don't fix the skill.

## Step 9 — Recover the baseline

Once fixed:

```bash
# Re-run the affected fixture(s)
bash evals/run.sh evals/fixtures/<fixture>.yaml

# Verify the baseline JSON matches expectation
cat evals/baselines/v<current>.json | jq '.fixtures'

# Commit the recovered baseline
git add evals/baselines/v<current>.json
git commit -m "test: recover baseline for <fixture> after <fix summary>"
```

## Worked example — F001 PARTIAL diagnosis

The full pattern played out for v2.8 F001 Smoke B:

1. **Symptom**: `learning_log_adherence: no` after fixture 08 run
   under v2.8.0.
2. **Localized to**: Step 7.5 adherence axis.
3. **Confirmed via**: `grep -c LEARNING_LOG_INIT: run.jsonl` → 0 lines.
4. **Filesystem cross-check**: no run dir created under
   `~/.claude/learning/...`.
5. **Tool-type inspection**: 47 Bash invocations, 0 referenced
   `append_learning_event`.
6. **Locate cause**: SKILL.md Step 7.5 used "must NOT block plan
   execution" wording that orchestrator read as "may skip".
7. **Fix**: v2.8.1 — MANDATORY framing + marker + eval-side adherence
   check.
8. **Recovery**: T5 n=4 reps all showed `learning_log_adherence: yes`.

See [`../experiments/v2.8-learning-log/findings/F001-smoke.md`](../experiments/v2.8-learning-log/findings/F001-smoke.md)
for the full narrative.
