# AgentLens Dashboard

A read-only web view of every run AgentLens has recorded on this machine.

## Install + First Launch

```bash
pipx install agentlens
agentlens serve --demo
```

`--demo` boots with bundled sample runs so the UI is populated immediately.
Remove the flag to view your real `~/.agentlens` store.

## Default URL

`http://127.0.0.1:5757`

## Flags

| Flag | Default | Purpose |
|---|---:|---|
| `--host` | `127.0.0.1` | Bind host. Use `0.0.0.0` only on trusted networks. |
| `--port` | `5757` | TCP port. |
| `--demo` | off | Use bundled sample runs in a temp directory. |
| `--debug` | off | Include tracebacks in error responses for local development. |
| `--auto-port` | off | Try `port+1..+3` if the requested port is busy. |
| `--dev-proxy URL` | none | Reverse-proxy static assets to a loopback Vite dev server. |
| `--allow-origin URL` | none | Add a CORS allowlist entry. May be repeated. |

## What It Shows

- A list of all runs, with status pills and a red highlight when
  `agent_outcome=success` but `eval_status=failed`.
- AgentRunway trust verdicts from `artifacts/trust_report.json`, shown in the
  run list and at the top of run detail.
- A run-detail page that puts the agent's claimed outcome next to the
  evaluator's verdict and the trust report, then shows failures with linked
  evidence.
- A transcript view of `events.jsonl` in chronological order.
- A workspace summary with pass-rate aggregations.
- A live `doctor` status pill in the sidebar.

## What It Does Not Do

- Authenticate users.
- Write to the store. There is no marking, tagging, cancellation, or eval
  re-run workflow through the UI.
- Expose data beyond the chosen host and port.
- Track runs across machines.
- Stream updates in real time; refresh the page to pick up newly written runs.
