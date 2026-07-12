# CPE v4 release dogfood

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> or superpowers:executing-plans to implement this plan task-by-task.

### Task 1: Exercise one production checkpoint
```yaml
task_type: non_tdd_implementation
dependencies: []
file_claims: [dogfood.txt]
acceptance: ["python3 -c 'import pathlib,sys; sys.exit(0 if pathlib.Path(\"dogfood.txt\").is_file() else 1)'"]
```
