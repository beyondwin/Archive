# Verifier Prompt

Verify completed task work. Do not repair code. Do not reinterpret the plan
beyond the supplied acceptance criteria and changed files.

Inputs:

```text
{risk_level}
{files_changed}
{baseline}
{test_command}
{acceptance_criteria}
{result_json_path}
```

Pass JSON:

```json
{
  "status": "PASS",
  "commands": [
    {"cmd": "pytest", "exit_code": 0, "raw_output": ".codex-orchestrator/raw/task_0-pytest.txt"}
  ],
  "issues": [],
  "notes": "short"
}
```

Failure JSON:

```json
{
  "status": "FAIL",
  "commands": [
    {"cmd": "pytest", "exit_code": 1, "raw_output": ".codex-orchestrator/raw/task_0-pytest.txt"}
  ],
  "issues": [
    {"issue_key": "tests/test_example.py:test_name:assertion", "summary": "one sentence"}
  ],
  "notes": "short"
}
```

Every failing issue should include an `issue_key` stable enough to detect
recurrence across retries.
