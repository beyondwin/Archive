## Task 1: Audit

```yaml agentrunway-task
task_id: task_001
title: Audit
risk: low
phase: implementation
dependencies: []
spec_refs: [S1.1]
file_claims:
  - {path: src/audit.py, mode: owned}
acceptance_commands: [pytest]
resource_keys: []
required_skills: [test-driven-development]
serial: false
```

Check audit behavior.
