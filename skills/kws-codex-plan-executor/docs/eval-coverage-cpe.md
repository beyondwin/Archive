# CPE v3 Eval Coverage

| Risk | Deterministic evidence |
| --- | --- |
| Wrong model or override | model policy, surface, invocation, attestation checks |
| Mutable or corrupt history | manifest/evidence, event kernel, replay, fault injection |
| Divergent consumers | validation-consumer parity |
| Unsafe drift repair | reconciliation and repair checks |
| Out-of-scope or concurrent writes | execution runtime and diff evidence checks |
| Missing explicit spec mapping | task packet and plan executability checks |
| Inspection mutation | inspect and recent-run checks |
| Stale public contract | `check_docs_contract.py` |
| Release metadata drift | release contract plus docs contract |

## Maintained Inventory Boundary

`evals/run.sh` must execute the maintained eval inventory, including public
run/resume/export, packet dispatch, Git delta, canonical validation, scheduler
repair loops, reconciliation, safe repair, inspection, and result-schema
checks. Runtime checks drive the public CLI with temporary repositories and a
fake provider. Expected behavior comes from an isolated oracle that cannot
import or call the production scheduler, projector, validator, or repair
implementation. An inventory entry that does not run is a harness failure.

The deterministic suite does not substitute for the paid live migration gate.
Live quality, regression, attestation, and context-token targets remain pending
until the approved matrix runs successfully.
