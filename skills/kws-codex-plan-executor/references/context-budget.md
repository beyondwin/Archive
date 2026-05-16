# Context Budget

Context budget metadata makes `context.json` easier to inspect during long
execution runs. It is a character-based estimate, not an exact tokenizer.

Budget status:

```text
green: estimated_chars <= 70% of max_chars
yellow: estimated_chars > 70% and <= 100% of max_chars
red: estimated_chars > max_chars or required source omitted
```

Section record:

```json
{
  "role": "plan",
  "path": "docs/superpowers/plans/example.md",
  "section": "Task 2: Implement validator",
  "estimated_chars": 4210,
  "sha256": "..."
}
```

Snapshot-level summary:

```json
{
  "context_budget": {
    "status": "green",
    "max_chars": 120000,
    "estimated_chars": 4210,
    "included_sections": [],
    "omitted_sections": []
  }
}
```

Build snapshots with a budget:

```bash
python3 scripts/build_context_snapshot.py \
  --repo-root "$WORKTREE_ABS" \
  --run-id "$RUN_ID" \
  --plan "$PLAN_REL" \
  --spec "${SPEC_REL:-}" \
  --docs "${DOCS_REL:-}" \
  --max-chars 120000 \
  --output "$RUN_DIR/context.json"
```

Truncate or omit at Markdown section boundaries. Never truncate inside fenced
code blocks when the section is included.

Required source omission is always red. Optional source omission can be yellow
when the snapshot still preserves the active plan, spec, and docs needed for
the next task.
