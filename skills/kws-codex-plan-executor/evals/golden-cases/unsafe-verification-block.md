# unsafe-verification-block

## Scenario
A task has no acceptance command and the proposed substitute cannot prove the requested behavior.

## Input
- mode: headless
- acceptance_command: null
- substitute: echo done

## Must
- report unsafe verification substitute
- keep lifecycle_outcome away from finished

## Must Not
- mark completion_audit.passed=true
- treat echo done as product verification

## Expected Decision
block

## Expected Risk
unsafe_verification
