# Risks, Limitations, And Deferrals

- Release status is **integrity-closure-pending; paid-live-pending**. Audited
  deterministic integrity gaps must close before deterministic readiness. The credentialed
  four-treatment, eight-case migration matrix has not run. No live quality,
  regression, or context-reduction release claim is approved yet.
- The v3 deterministic harness currently disables the legacy static YAML
  execution-fixture loop. Production confidence therefore depends on the active
  module/integration checks and the still-pending live matrix.
- V2 runs cannot resume or migrate. Consumers preserve them and return
  `unsupported_schema`; operators must start a new v3 run.
- Sol/high unavailability or missing actual-model attestation blocks core work;
  there is no downgrade route.
- Terra/high scouts are advisory read-only evidence collectors. Sol must reopen
  critical evidence before implementation or a verdict.
- Safe repair is deliberately narrow. Invalid event history, changed source
  identity, evidence corruption, or diff-scope violations require operator
  resolution rather than automatic rewriting.
- Dependency preflight reports preparation commands but does not install or
  mutate operator environments.
