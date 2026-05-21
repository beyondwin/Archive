# Waygent Commands

```bash
waygent run --plan <path> --spec <path> --provider fake
waygent run --latest --provider codex --execution-mode multi-agent
waygent run --topic <topic> --provider claude --main-model opus --main-reasoning high
waygent status --last
waygent status --run <run_id>
waygent events --run <run_id> --json
waygent inspect --run <run_id> --json
waygent explain --last
waygent resume --last
waygent apply --run <run_id>
```

`apply` is explicit and must refuse a dirty source checkout.
