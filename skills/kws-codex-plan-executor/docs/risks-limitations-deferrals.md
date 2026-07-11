# Risks, Limitations, And Deferrals

- Published evidence state is **deterministic-ready; paid-live-pending**. Audited
  deterministic integrity gaps are closed by the current cost-free suite. The
  credentialed four-treatment, eight-case migration matrix has not run. No live
  quality, regression, or context-reduction release claim is approved yet, and
  `release_ready=false` remains required.
- The v3 deterministic harness uses a maintained inventory, public CLI fixture
  repositories, fake providers, and an isolated oracle. This covers behavior,
  not real provider quality, latency, or cost; those remain with the pending
  paid live matrix.
- V2 runs cannot resume or migrate. Consumers preserve them and return
  `unsupported_schema`; operators must start a new v3 run.
- Sol/high unavailability or missing actual-model attestation blocks core work;
  there is no downgrade route.
- Terra/high scouts are advisory read-only evidence collectors. Sol must reopen
  critical evidence before implementation or a verdict.
- Safe repair is deliberately narrow. Invalid event history, changed source
  identity, evidence corruption, or diff-scope violations require operator
  resolution rather than automatic rewriting.
- Repair can legitimately return `applied=false` when the declared projection
  delta is not observed. Blocked work is resumable only when evidence identifies
  an exact retry phase; neither outcome is equivalent to success.
- Dependency preflight reports preparation commands but does not install or
  mutate operator environments.
