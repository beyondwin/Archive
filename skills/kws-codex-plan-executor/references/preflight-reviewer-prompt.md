# Preflight Reviewer Prompt

Audit the plan/spec mechanically. Do not suggest architecture, style, or product
improvements. Only identify blockers that would make execution ambiguous or
unsafe.

Inputs:

- Plan path and content
- Optional spec/design/docs content
- Parsed task JSON from `scripts/parse_plan.py`, if available

Return one JSON object:

```json
{
  "status": "PASS",
  "summary": "short summary",
  "issues": [
    {
      "severity": "BLOCKER",
      "task": "task_0",
      "category": "missing_files|missing_ac|contract_mismatch|dep_inconsistency|out_of_repo|ambiguity",
      "description": "one sentence",
      "evidence": "file:line or section",
      "suggested_fix": "smallest fix"
    }
  ]
}
```

Use `status: "FAIL"` when any blocker exists. Keep evidence concrete and tied
to a task, section, or file path.
