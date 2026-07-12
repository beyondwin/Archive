# Risks, Limitations, And Deferrals

- Published evidence state is **deterministic-ready; paid-live-verified**.
  Audited deterministic integrity gaps are closed by the current cost-free
  suite, and the reviewed four-treatment, eight-case subscription matrix passed
  the unchanged release gate. The tracked privacy audit passed and
  `release_ready=true`.
- That 3.1.0 state is historical v3 evidence. The unpublished v4 merge gate can
  claim `critical-path-live verified` only from a terminal generation; optional
  17-call certification remains `full paid-live certification deferred` until
  its own terminal pass.
- The v3 deterministic harness uses a maintained inventory, public CLI fixture
  repositories, fake providers, and an isolated oracle. This covers behavior,
  not real provider quality or latency; the reviewed live matrix supplies the
  release evidence for version 3.1.0.
- The live runner can verify ChatGPT login and remove API-key credentials from
  child environments, but it cannot prove which account-side subscription or
  existing-credit bucket a call consumed. Subscription reports therefore keep
  `cost_usd=null` and `cost_observability=unavailable`; operators must inspect
  account billing settings independently.
- A timeout, subscription limit, malformed result, missing digest, source or
  oracle drift, unavailable exact model route, or incomplete slot ledger blocks
  aggregation. Resume is explicit, and failed slots are not retried without
  `--retry-failed`.
- Live evidence is stored outside the repository and is not a release claim by
  itself. Version 3.1.0 was published only after independent implementation and
  sanitized-report review plus a tracked privacy audit; future evidence must
  repeat those gates before changing version, status, or `release_ready`.
- Raw per-slot transcripts, user-home paths, temporary execution paths, and
  oracle paths remain external and untracked; sanitized release evidence
  contains none of them.
- The v4 corrected-run predecessor importer proves continuity only from the
  exact filesystem root it validates at import time. It is not a signature or
  remote transparency service. A tampered root fails validation, while the new
  root retains only source digests and implementation identity needed to
  enforce the one-corrected-run cap.
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
