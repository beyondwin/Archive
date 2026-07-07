# F01 — v3.0 Deterministic Kernel Close-out

**Date**: 2026-07-07
**Experiment**: v3.0-deterministic-kernel
**Recommendation**: **SHIP**
**Caveat**: Live-CLI smoke (full end-to-end `claude -p` plan run) is PENDING a
live-environment run. All deterministic criteria are MET. See §5 for the exact
pending command.

---

## §1 Recommendation

SHIP v3.0.0.

The deterministic kernel replaces the v2.x freeze-skip regression class at its
root: every transition decision, retry accounting, review tier computation, and
record-keeping emit now lives in a Python kernel that the LLM executes but does
NOT interpret. The 16/16 unit-test-file suite (all standalone Python, all exit 0)
verifies the kernel contracts deterministically, independent of LLM behavior.

The one pending item (live-CLI smoke) is a completeness check on `ledger.extract_payload`'s
envelope parsing, not a correctness gate on the kernel itself. The function is
defensively coded with a T16 seam and was verified against real `claude -p --output-format json`
output on 2026-07-07 (see §5). The pending item is the full-plan run (timing,
cost, wedge-free exit, run_quality/completion_audit generation).

---

## §2 Success Criteria Evidence Table

| # | Criterion | Status | Evidence |
|---|-----------|--------|---------|
| SC1 | Kernel test suite 16/16 green | **MET** | All 16 `scripts/kernel/test_*.py` files exit 0 standalone (no pytest required). `for t in scripts/kernel/test_*.py; do python3 "$t"; done` → all PASS. 2026-07-07 run recorded below. |
| SC2 | Real-plan smoke (attached+headless, timing/cost, wedge-free, run_quality+completion_audit) | **PENDING** | `claude -p` is reachable (verified: exit 0, correct envelope). Full plan run requires live session. See §5 for the exact maintainer command. |
| SC3 | `grep -c "STATUS:" SKILL.md` returns 0 outside prompt-template refs | **MET** | `grep -c "STATUS:" SKILL.md` → 0. No legacy `STATUS:` prose in SKILL.md. |
| SC4 | `DOC_FRESHNESS_STRICT=1 python3 evals/check_doc_freshness.py` passes | **MET** | Passes after T16 doc sync: HISTORY v3.0.0 entry, `docs/snapshots/v3.0.0.md`, D001 indexed in decision-log, broken links fixed. |
| SC5 | `evals/run.sh` deterministic preflight exits 0 | **MET** | Preflight: `compare_agentlens_events.py --self-test` + kernel unit test loop + `check_doc_freshness.py`. All exit 0. |
| SC6 | SKILL.md cutover: no `<active>` prose, 6-section structure, kernel action table present | **MET** | SKILL.md has 6 keyed sections (①–⑥ + ④·b + seams). Zero `<active>` substitution prose. §④ action-handling table CODE-VERIFIED against `transitions.py`/`kernel.py`. |

---

## §3 Kernel Test Suite Results (2026-07-07)

All 16 test files run standalone (`python3 <file>`) and exit 0:

| File | Result |
|------|--------|
| test_cycle_e2e.py | PASS (single "ALL TESTS PASS" assertion) |
| test_dispatch.py | 10/10 PASS |
| test_drift.py | 16/16 PASS |
| test_events.py | PASS |
| test_gate.py | 23/23 PASS |
| test_init_run.py | PASS |
| test_initcmd.py | PASS |
| test_ledger.py | PASS |
| test_migrate.py | PASS |
| test_packets.py | 13/13 PASS |
| test_planparse.py | PASS |
| test_quality.py | PASS |
| test_recovery.py | 12/12 PASS |
| test_statefile.py | PASS |
| test_transitions.py | 22/22 PASS |
| test_validate.py | PASS |

---

## §4 Live-CLI Envelope Verification (2026-07-07)

`claude -p "reply OK" --output-format json` ran successfully (exit 0). Real envelope keys observed:

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "OK",
  "usage": {
    "input_tokens": 5121,
    "cache_creation_input_tokens": 4098,
    "cache_read_input_tokens": 14625,
    "output_tokens": 16,
    "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
    "service_tier": "standard",
    "cache_creation": {"ephemeral_1h_input_tokens": 4098, "ephemeral_5m_input_tokens": 0},
    "inference_geo": "not_available",
    "iterations": [...]
  },
  "total_cost_usd": 0.148595,
  "modelUsage": {...},
  "duration_ms": 4643,
  "session_id": "...",
  "uuid": "..."
}
```

**`ledger.extract_payload` verification scope**: This minimal test exercised the `result` (plain string) branch and the top-level/usage key path:
- Payload fallback: `envelope["result"]` → `"OK"` (string). `structured_output` was absent → payload returned nothing. The `structured_output` key path (what real `--json-schema` role dispatches produce) was **not** exercised here — it remains code-verified only.
- Usage/cost: `envelope["usage"]` dict present + `envelope["total_cost_usd"]` correctly foldable per seam contract. Verified against real key names.
- T16 seam markers at `ledger.py:125-148` match the real envelope keys. No corrections needed to the usage/cost path.

Top-level key set and usage/cost folding verified against real output. `structured_output` payload extraction is code-verified only; full verification folds into the pending live plan smoke (§5).

---

## §5 Pending: Full Live-CLI Smoke

**Status**: PENDING. Requires a live interactive session with a real plan.

**What is pending**: An attached+headless plan run that verifies:
1. `kernel.py init` creates worktree, materializes 4 hooks, writes `state.json`.
2. The `next → perform → submit` loop completes all tasks without wedging.
3. `timing.started`/`timing.completed` are stamped by the kernel (not by prose).
4. `cost_ledger.totals.dispatches > 0` after dispatches.
5. `kernel.py finalize` produces `run_quality` + `completion_audit`.
6. Stop hook (`kernel.py check-stop`) behaves correctly at run end.

**Exact maintainer command**:
```bash
cd <repo-root>
/kws-claude-multi-agent-executor plan=<small-plan.md> spec=<spec.md> mode=interactive
# After completion:
python3 skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py inspect \
  --state ~/.claude/orchestrator/<RUN_ID>/state.json
# Verify: status==FINALIZED, cost_ledger.totals.dispatches>0, run_quality present
```

**Acceptable small plan**: any existing eval fixture plan (e.g.,
`evals/fixtures/01-trivial-typo.yaml`'s `plan` block) materialized to a `.md` file.

---

## §6 Deferred Follow-ups

| Item | Disposition |
|------|-------------|
| Live-CLI smoke (full plan run) | Pending live-environment run. SC2 evidence. |
| Haiku A/B Plan Reviewer | Out of scope for v3.0. `dispatch.py` supports any model. Deferred to follow-on experiment. |
| `not_ready` mid-run stop question | `kernel.py check-stop` returns `not_ready` (exit 0 = allow) while tasks in progress. Open design question: should mid-run pauses be blocked? Deferred. |
| `delegate_parallel` wave-launch orchestration | `gate.preflight` returns `delegate_parallel` signal; parallel sub-worktree launch not wired in SKILL.md v3.0. Seam marked in ⑦ Forward-wired seams. Deferred. |
| Prompt cache audit | Extended cache applicability (v2.19 D002 open Q). Deferred. |
| `serialization_reason` in execution_plan | `gate.partition_waves` returns bare `list[list[str]]` — no wave metadata. `serialization_reason` branch in `preflight` is dead code. Documented in SKILL.md Forward-wired seams. Deferred if/when wave metadata is needed. |
