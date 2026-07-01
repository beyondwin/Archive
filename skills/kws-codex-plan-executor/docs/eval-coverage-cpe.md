# CPE Eval Coverage Map

| Failure mode | Primary eval | Supporting evals |
| --- | --- | --- |
| YAML spec refs hidden/visible parsing | `check_parse_plan.py` | `check_task_packet.py` |
| Manifest task-to-section slicing | `check_task_packet.py` | `check_run_readiness.py` |
| Write-scope formatting | `check_run_readiness.py` | `check_preflight_dispatch.py` |
| Plan audit/state parity | `check_state_schema.py` | `check_operational_run_quality.py` |
| Expected local fallback vs prevented delegation | `check_operational_run_quality.py` | `check_preflight_dispatch.py` |
| Structured residual risk | `check_state_schema.py` | `check_cpe_replay.py` |
| Normalized replay forbidden patterns | `check_cpe_replay.py` | `check_eval_harness.py` |
