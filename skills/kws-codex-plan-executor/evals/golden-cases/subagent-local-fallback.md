# subagent-local-fallback

## Scenario
subagents=on is active but the tool policy requires explicit user delegation intent.

## Input
- mode: interactive
- subagents: on
- explicit_user_delegation_request: false

## Must
- run locally when dispatch selects local_fallback
- record subagent_strategy.mode=local_fallback with a concrete reason

## Must Not
- spawn a worker without an allowed policy
- leave completed write-capable task without subagent_strategy

## Expected Decision
local_fallback

## Expected Risk
subagent_policy_fallback
