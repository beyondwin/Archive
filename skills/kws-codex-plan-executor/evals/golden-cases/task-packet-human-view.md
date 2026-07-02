# task-packet-human-view

## Scenario
A generated task packet view is included in handoff or subagent hot-tail context.

## Input
- task_packet: task_0.json
- view: task_0.md

## Must
- preserve files, task body, AC, verification, and forbidden globs
- show full-spec fallback when packet.spec.fallback_used=true

## Must Not
- treat markdown view as source of truth
- omit machine packet fields needed by dispatch or validation

## Expected Decision
render

## Expected Risk
human_view_parity
