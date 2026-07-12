# Lossless Task Contract Fixture

### Task 1: Preserve The Complete Task Source

```yaml
task_type: tdd_implementation
risk_class: high
dependencies: []
spec_refs: ["S1.6"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/task_contracts.py
forbidden_paths:
  - run_manifest.json
  - events.jsonl
  - state.json
acceptance:
  - python3 check_contract.py
required_methods:
  - using-superpowers
  - test-driven-development
required_evidence:
  - red
  - green
checkpoint_message: "feat(cpe): preserve lossless task source"
operator_reviewed: true
```

**Interfaces:** Preserve prose, metadata, and every fenced block verbatim.

**RED**

```python
def test_lossless_contract():
    assert False, "contract compiler is not implemented"
```

**GREEN**

```bash
python3 -m unittest tests.test_task_contract
```

### Task 2: Bound The First Task Source

```yaml
task_type: verification
risk_class: low
dependencies: ["task_1"]
file_claims:
  - skills/kws-codex-plan-executor/evals/check_task_contract_v4.py
acceptance:
  - python3 check_second_task.py
```

The first contract must stop before this heading.
