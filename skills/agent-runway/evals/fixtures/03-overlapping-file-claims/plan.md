## Task 1: Shared one

```yaml agentrunway-task
task_id: task_001
title: Shared one
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.1]
file_claims:
  - {path: src/shared.py, mode: owned}
acceptance_commands: [pytest]
resource_keys: []
required_skills: [test-driven-development]
serial: false
```

Edit shared.

## Task 2: Shared two

```yaml agentrunway-task
task_id: task_002
title: Shared two
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.1]
file_claims:
  - {path: src/shared.py, mode: owned}
acceptance_commands: [pytest]
resource_keys: []
required_skills: [test-driven-development]
serial: false
```

Edit shared too.
