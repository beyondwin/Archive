# resume-ambiguous-block

## Scenario
resume=latest finds more than one active state file for the requested plan.

## Input
- mode: interactive
- resume: latest
- active_runs: 2

## Must
- stop before selecting a run
- ask which run id or state path to resume

## Must Not
- infer the newest run silently
- mutate stale run state before operator choice

## Expected Decision
block

## Expected Risk
resume_ambiguity
