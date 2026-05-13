# How to extend the learning-log event-type set

Adding a new event type to the schema. This is a coordinated change
across the schema definition, the helper script, the deterministic
checks, the reference doc, and at least one sub-agent prompt that emits
the new type.

For the existing 10 event types and contract see
[`../../references/learning-log.md`](../../references/learning-log.md).
Before adding, verify the decision criteria below.

## Decision: should a new event type exist?

Adding an event type is a schema change. The 10 existing types were
chosen to be jointly exhaustive over notable boundaries the orchestrator
sees. Before adding:

1. **Can the new signal be expressed as a refinement of an existing
   type?** Most "I want to record X" needs map to an existing type +
   a richer `context` field. Prefer that.
2. **Is there *measured* need?** The omc-inspired conflict-mailbox type
   (Risk F in [`../deferred-candidates.md`](../deferred-candidates.md))
   is deferred precisely because no measured KCMAE failure currently
   uses it. Don't add speculatively.
3. **Will at least one current sub-agent prompt actually emit this?**
   An event type with no producer is dead code.

If all three answer yes, proceed. If not, record in deferred-candidates
and revisit when evidence accumulates.

## The five places to update

A new event type touches these artifacts; missing any breaks the
contract or makes the type invisible:

1. **`references/learning-log.md`** — schema documentation
2. **`scripts/append_learning_event.py`** — `EVENT_TYPES` validation set
3. **`evals/check_learning_log.py`** — schema test coverage
4. **`evals/check_skill_contract.py`** — `EVENT_TYPES` list (cross-check)
5. **At least one sub-agent prompt under `references/`** — emitter

Optional but recommended:
6. **`references/escalation-playbook.md`** — if this type maps to an
   ESCALATE category
7. **A new contract-eval check** verifying the schema honors any new
   required fields specific to this type

## Step 1 — Update `references/learning-log.md`

Add the new type to the "10 event types" enumeration (which will become
11). For each type the doc currently has:
- One-line description
- When the orchestrator emits it (or which sub-agent writes the candidate)
- Required `context` fields beyond the schema baseline
- One example payload

Match that pattern.

```markdown
### N. `your_new_type` (NEW in vX.Y.Z)

**When emitted**: <one sentence — orchestrator or sub-agent + trigger condition>

**Required context fields beyond baseline**:
- `field_a` (string) — <what it carries>
- `field_b` (object) — <structure>

**Example**:
\`\`\`json
{
  "schema_version": "1",
  "phase": "phase_1",
  "risk_tier": "MID",
  "event_type": "your_new_type",
  "severity": "medium",
  ...
}
\`\`\`
```

If the type changes the schema version (new required top-level field),
bump `schema_version` and document the migration in HISTORY.md.

## Step 2 — Update `scripts/append_learning_event.py`

Find the `EVENT_TYPES` constant or `validate_event` function:

```python
EVENT_TYPES = {
    "blocker",
    "error",
    "verification_failure",
    "reviewer_warn_or_fail",
    "escalation",
    "recurring_issue",
    "user_correction",
    "parallel_dispatch_failure",
    "successful_workaround",
    "completion_learning",
    "your_new_type",          # NEW vX.Y.Z
}
```

If your new type has type-specific required fields, add a validation
branch:

```python
if event["event_type"] == "your_new_type":
    for required in ("context.field_a", "context.field_b"):
        # Walk dotted path; raise if missing
        ...
```

## Step 3 — Update `evals/check_learning_log.py`

The deterministic check suite verifies that `append` rejects unknown
event types. Add at least one positive + one negative case:

```python
def check_your_new_type_accepted():
    """append accepts the new event type when fields are correct"""
    event = {
        "schema_version": "1",
        "phase": "phase_1",
        "event_type": "your_new_type",
        # ... full minimal valid event with required fields ...
    }
    result = run_helper("append", "--run-id", run_id, payload=event)
    assert result.returncode == 0

def check_your_new_type_missing_required_field_fails():
    """append rejects the new event type if a required type-specific field is missing"""
    event = {...}  # missing context.field_a
    result = run_helper("append", "--run-id", run_id, payload=event)
    assert result.returncode != 0
```

Run `python3 evals/check_learning_log.py` — should be 17/17+ (was 16/16
before).

## Step 4 — Update `evals/check_skill_contract.py`

The contract check has an `EVENT_TYPES` list it cross-references against
`references/learning-log.md`. Add your new type:

```python
EVENT_TYPES = [
    "blocker",
    "error",
    "verification_failure",
    "reviewer_warn_or_fail",
    "escalation",
    "recurring_issue",
    "user_correction",
    "parallel_dispatch_failure",
    "successful_workaround",
    "completion_learning",
    "your_new_type",          # NEW vX.Y.Z
]
```

Run `python3 evals/check_skill_contract.py --skill SKILL.md` — the
`learning_log_event_types` check should still pass (it greps for every
member of this list in `learning-log.md`).

## Step 5 — Wire at least one emitter

Pick the sub-agent prompt that should produce the new candidate file.
Edit `references/<role>-prompt.md` to add (or extend) a "Learning log
emit" section:

```markdown
## Learning log emit (vX.Y.Z)

If <trigger condition>, write a learning-event candidate JSON file to
`<worktree>/.orchestrator/learning_events/<task_id>-<role>.json` before
returning your output. **Do not call the helper script yourself** — the
orchestrator scans this directory and invokes `append`.

Minimal candidate body:

\`\`\`json
{
  "schema_version": "1",
  "phase": "<phase_0|phase_1|transition|phase_2>",
  "risk_tier": "<LOW|MID|HIGH>",
  "event_type": "your_new_type",
  "severity": "<low|medium|high>",
  "execution": {"task_id": "task_<N>", "issue_key": "<top_issue_key>"},
  "subagent": {"role": "<your-role>", "model": "sonnet", "dispatch": "agent_tool"},
  "summary": "<≤1 sentence — what occurred>",
  "context": {
    "user_intent": "<…>",
    "agent_expectation": "<…>",
    "actual_outcome": "<…>",
    "root_cause": "<…>",
    "evidence": [{"kind": "<…>", "value": "<…>"}],
    "field_a": "<value>",
    "field_b": {...}
  },
  "improvement": {
    "target": "<file the improvement would touch>",
    "proposal": "<≤1 sentence>",
    "experiment_link": null
  },
  "privacy": {"redacted": true, "notes": "<what was redacted>"}
}
\`\`\`
```

If multiple sub-agents emit the type, repeat for each.

If the orchestrator itself emits (rather than a sub-agent), update
`SKILL.md` directly with the appropriate phase step.

## Step 6 — Update escalation playbook (if applicable)

If the new event type corresponds to an ESCALATE category (e.g.,
`spec_blocked`, `implementation_blocked`, `test_blocked`), add a row to
`references/escalation-playbook.md`:

| ESCALATE type | Event type | Severity |
|---------------|------------|----------|
| ... | ... | ... |
| `<your_escalate>` | `your_new_type` | <severity> |

## Step 7 — Version bump

Adding an event type is a feature; bump the minor version (e.g.,
v2.9.0 → v2.10.0). Update:

- `SKILL.md` frontmatter `metadata.version`
- `manifest.json` skill_versions entry
- `README.md` (root) skill version table
- `HISTORY.md` v2.X.0 entry under §1 explaining the new type and
  evidence motivating it

## Step 8 — Run full preflight

```bash
python3 evals/check_learning_log.py      # 17+ checks pass
python3 evals/check_skill_contract.py --skill SKILL.md  # 18+ checks pass
```

Then a single fixture run to verify nothing else broke:

```bash
bash evals/run.sh evals/fixtures/01-trivial-typo.yaml  # smoke
```

## Step 9 — Commit + experiment record (if non-trivial)

If the new type came from an experiment (e.g., a v2.X-<name>/ directory
with D### deciding the type), commit the schema + emitter changes
together with the experiment finding that justified them.

If the change is small and uncontroversial: one commit with the schema
+ emitter is fine.

## Common pitfalls

- **Adding the type to the helper but not the contract eval**: tests
  pass locally but `check_skill_contract.py` fails on the contract
  check that cross-references the doc. Fix: keep the three lists
  (`learning-log.md`, helper, contract eval) in sync — they exist
  precisely to catch this drift.
- **Missing emitter**: schema accepts the new type but no sub-agent
  produces it. The type is dead. Fix: wire at least one prompt before
  shipping; verify a sample run produces the candidate file.
- **Type semantics overlap an existing type**: future readers will
  emit the wrong type. Fix: write a "use type X vs Y" section in
  `references/learning-log.md` distinguishing them.
- **Required fields are too permissive**: events come through with
  partial context, downstream analysis fails. Fix: make required
  fields actually required in helper validation (raise if missing).
