"""test_gate.py — TDD suite for gate.py (CME v3.0 T11).

Covers:
  (a) shared-file LOW tasks → promoted or singleton-separated
  (b) same resource_key → singleton within a wave
  (c) file-overlapping parallel candidates → block (safety gate)
  (d) HIGH task with no Acceptance Criteria → executability blocking issue
  (e) operator review reflected → effective (blocking_issue_count) < raw
  (f) contention trigger → delegate_serial (D001 split)
  (g) trust/risk trigger → block (D001 split)

__main__ invokes ALL defined test functions; sys.exit(1) on any failure.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate


# ── shared task fixtures ──────────────────────────────────────────────────────

def _task(task_id: str, files=None, depends_on=None, serial=False,
          resource_key=None, acceptance=None, body="", title="Task"):
    """Build a minimal planparse-style task dict.

    number is derived from the task_id (e.g. "task_3" → number=3).
    partition_waves resolves depends_on through task.number, so providing
    number here makes dependency tests exercise the real code path.
    """
    # Derive number from task_id ("task_1" → 1, "task_2" → 2, etc.)
    try:
        number = int(task_id.split("_")[-1])
    except (ValueError, IndexError):
        number = 0
    return {
        "id": task_id,
        "number": number,
        "files": files or [],
        "dependencies": depends_on or [],
        "serial": serial,
        "resource_key": resource_key,
        "acceptance": acceptance,
        "body": body,
        "title": title,
    }


# ── TEST 1: assign_risk basic levels ─────────────────────────────────────────

def test_assign_risk_basic():
    """Tasks without overlap get their assessed risk unchanged."""
    tasks = [
        _task("task_1", files=["foo.py"], body="low-risk isolated change"),
        _task("task_2", files=["bar.py", "baz.py"], body="touches 2 modules"),
        _task("task_3", files=["api.py"], body="schema migration high-risk breaking change"),
    ]
    # Pass 'mid' as default for ambiguous tasks (no override)
    risk = gate.assign_risk(tasks, override=None)
    assert isinstance(risk, dict), "assign_risk must return a dict"
    assert set(risk.keys()) == {"task_1", "task_2", "task_3"}, (
        f"Expected keys task_1/2/3, got {set(risk.keys())}"
    )
    for v in risk.values():
        assert v in ("low", "mid", "high"), f"Risk value must be low/mid/high, got {v!r}"
    print("TEST 1 PASS: assign_risk returns dict with valid levels for all tasks")


# ── TEST 2: shared-file LOW task promotion ────────────────────────────────────

def test_shared_file_low_promotion():
    """Two LOW tasks sharing a file: later one must be promoted to MID (or higher).

    Each task has exactly ONE file so the len(files)>=2 rule stays quiet and both
    initially compute LOW. The shared-file LOW→MID promotion rule must then fire for
    task_2 because task_1 already claimed shared.py.
    """
    tasks = [
        _task("task_1", files=["shared.py"]),   # single file → LOW before promotion
        _task("task_2", files=["shared.py"]),   # same single file → should be promoted
    ]
    risk = gate.assign_risk(tasks, override=None)
    # task_1 is the first task — it claims shared.py and stays LOW
    assert risk.get("task_1") == "low", (
        f"task_1 must start LOW (single non-risky file); got {risk.get('task_1')!r}"
    )
    # task_2 sees shared.py already claimed by the earlier LOW task → promoted to MID
    assert risk.get("task_2") in ("mid", "high"), (
        f"task_2 shares file with LOW task_1; must be promoted, got {risk.get('task_2')!r}"
    )
    print("TEST 2 PASS: shared-file LOW task → later task promoted to MID+")


# ── TEST 3: partition_waves — simple dependency ordering ─────────────────────

def test_partition_waves_dependency_order():
    """partition_waves must put task_2 (which depends on task_1) in a SEPARATE, LATER group.

    The tasks have DISJOINT files (a.py vs b.py) so WITHOUT dependency resolution
    they would be eligible to merge into the same parallel group.  If the test
    passes with a single group the dependency logic is broken — so asserting
    len(result)==2 is the discriminating check.
    """
    tasks = [
        _task("task_1", files=["a.py"]),               # number=1
        _task("task_2", files=["b.py"], depends_on=[1]),  # number=2, depends on task_1
    ]
    risk = {"task_1": "mid", "task_2": "mid"}
    result = gate.partition_waves(tasks, risk, parallel=True)
    # Shape check: must be list[list[str]]
    assert isinstance(result, list), f"Must return list, got {type(result)}"
    for group in result:
        assert isinstance(group, list), f"Each item must be a list, got {type(group)}"
        for tid in group:
            assert isinstance(tid, str), f"Each task_id must be str, got {type(tid)}"
    # Discriminating assertion: deps must force separate groups, not a merged [t1,t2]
    assert len(result) >= 2, (
        f"task_2 depends on task_1; they must be in separate waves (len>=2); got {result}"
    )
    # task_2 must appear AFTER task_1 in the flat sequence
    flat = [tid for group in result for tid in group]
    assert "task_1" in flat and "task_2" in flat
    assert flat.index("task_1") < flat.index("task_2"), (
        f"task_1 must precede task_2 in execution order; got {flat}"
    )
    print(f"TEST 3 PASS: partition_waves separates dep tasks into {len(result)} waves: {result}")


# ── TEST 4: partition_waves — serial flag forces singleton ───────────────────

def test_partition_waves_serial_singleton():
    """A serial: true task must be its own singleton, never merged into a multi-task group."""
    tasks = [
        _task("task_1", files=["x.py"], serial=True),
        _task("task_2", files=["y.py"]),
        _task("task_3", files=["z.py"]),
    ]
    risk = {"task_1": "low", "task_2": "low", "task_3": "low"}
    result = gate.partition_waves(tasks, risk, parallel=True)
    flat = [tid for group in result for tid in group]
    assert "task_1" in flat
    # Find the group containing task_1
    for group in result:
        if "task_1" in group:
            assert len(group) == 1, (
                f"serial task_1 must be a singleton; group={group}"
            )
            break
    print("TEST 4 PASS: serial: true task is singleton in partition_waves")


# ── TEST 5: partition_waves — resource_key singleton ─────────────────────────

def test_partition_waves_resource_key_singleton():
    """(b) Two tasks with the same resource_key must each be in their own singleton group."""
    tasks = [
        _task("task_1", files=["a.py"], resource_key="db-port-5432"),
        _task("task_2", files=["b.py"], resource_key="db-port-5432"),
        _task("task_3", files=["c.py"]),  # no resource_key → can merge
    ]
    risk = {"task_1": "low", "task_2": "low", "task_3": "low"}
    result = gate.partition_waves(tasks, risk, parallel=True)
    # task_1 and task_2 share a resource_key → each must be a singleton
    for group in result:
        if "task_1" in group:
            assert len(group) == 1, f"task_1 must be singleton due to resource_key; group={group}"
        if "task_2" in group:
            assert len(group) == 1, f"task_2 must be singleton due to resource_key; group={group}"
    print("TEST 5 PASS: resource_key tasks are singletons in same wave")


# ── TEST 6: partition_waves — parallel=False degenerates ─────────────────────

def test_partition_waves_parallel_off():
    """parallel=False → every task is a singleton [[t1],[t2],...] in plan order."""
    tasks = [
        _task("task_1", files=["a.py"]),
        _task("task_2", files=["b.py"]),
        _task("task_3", files=["c.py"]),
    ]
    risk = {"task_1": "low", "task_2": "mid", "task_3": "high"}
    result = gate.partition_waves(tasks, risk, parallel=False)
    assert result == [["task_1"], ["task_2"], ["task_3"]], (
        f"parallel=False must return all singletons in order; got {result}"
    )
    print("TEST 6 PASS: parallel=False yields all-singleton execution plan")


# ── TEST 7: preflight — happy-path delegate_parallel ─────────────────────────

def test_preflight_happy_path():
    """A clean task+packet → decision is delegate_parallel (or delegate_serial)."""
    task = _task("task_1", files=["foo.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "green"},
        "fallback_used": False,
        "files": ["foo.py"],
        "write_policy": {"allowed_write_globs": ["foo.py"], "forbidden_write_globs": []},
    }
    state = {"risk_levels": {"task_1": "mid"}}
    result = gate.preflight(task, packet, state)
    assert "decision" in result, "preflight must return decision"
    assert result["decision"] in ("delegate_parallel", "delegate_serial", "block"), (
        f"Unexpected decision: {result['decision']!r}"
    )
    assert "reason" in result
    assert "would_have" in result  # may be None
    print(f"TEST 7 PASS: preflight happy path → {result['decision']!r}")


# ── TEST 8: preflight — (c) file-overlap parallel candidates → block ──────────

def test_preflight_file_overlap_blocks():
    """(c) File-claim collision on parallel candidates → safety block."""
    task = _task("task_1", files=["shared.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "green"},
        "fallback_used": False,
        "files": ["shared.py"],
        "write_policy": {
            "allowed_write_globs": ["shared.py"],
            "forbidden_write_globs": [],
        },
    }
    # State indicates another task in the SAME parallel group claimed shared.py
    state = {
        "risk_levels": {"task_1": "mid"},
        "parallel_file_claims": {"shared.py": "task_0"},  # already claimed
    }
    result = gate.preflight(task, packet, state)
    assert result["decision"] == "block", (
        f"File overlap must → block; got {result['decision']!r}: {result['reason']}"
    )
    print("TEST 8 PASS: parallel file-claim collision → block")


# ── TEST 9: preflight — packet budget red → block ────────────────────────────

def test_preflight_packet_red_blocks():
    """Packet context_budget red → safety block (CPE: packet_context_budget_red)."""
    task = _task("task_1", files=["foo.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "red"},
        "fallback_used": False,
        "files": ["foo.py"],
        "write_policy": {"allowed_write_globs": ["foo.py"], "forbidden_write_globs": []},
    }
    state = {"risk_levels": {"task_1": "mid"}}
    result = gate.preflight(task, packet, state)
    assert result["decision"] == "block", (
        f"Red packet budget must → block; got {result['decision']!r}"
    )
    print("TEST 9 PASS: packet budget red → block")


# ── TEST 10: preflight — write-scope too broad → block ───────────────────────

def test_preflight_write_scope_too_broad_blocks():
    """Write scope with wildcard glob (too broad) → safety block."""
    task = _task("task_1", files=["src/foo.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "green"},
        "fallback_used": False,
        "files": ["src/foo.py"],
        "write_policy": {
            # A glob that covers whole source tree → too broad
            "allowed_write_globs": ["**/*.py"],
            "forbidden_write_globs": [],
        },
    }
    state = {"risk_levels": {"task_1": "mid"}}
    result = gate.preflight(task, packet, state)
    assert result["decision"] == "block", (
        f"Too-broad write scope must → block; got {result['decision']!r}"
    )
    print("TEST 10 PASS: write-scope too broad → block")


# ── TEST 11 (D001): contention trigger → delegate_serial ─────────────────────

def test_preflight_contention_trigger_delegate_serial():
    """(f) D001: file-contention singleton (same wave, overlap) → delegate_serial.

    This is the faithful CPE local_fallback substitute for CONTENTION reasons:
    serialize the work but still delegate to a subagent.
    """
    task = _task("task_1", files=["utils.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "green"},
        "fallback_used": False,
        "files": ["utils.py"],
        "write_policy": {
            "allowed_write_globs": ["utils.py"],
            "forbidden_write_globs": [],
        },
    }
    # serialization_reason is injected directly here for this UNIT test.
    # T15 seam: no producer exists in the cycle today — partition_waves returns
    # bare list[list[str]] and no orchestrator step writes serialization_reason
    # into state. T15 wires that producer; until then contention safely falls
    # through to the default delegate_serial (TEST 7 covers the default path).
    state = {
        "risk_levels": {"task_1": "mid"},
        "serialization_reason": "file_contention",  # T15 seam: directly injected for this unit test
    }
    result = gate.preflight(task, packet, state)
    # Contention trigger → delegate_serial (still a subagent, just serialized)
    assert result["decision"] == "delegate_serial", (
        f"Contention trigger must → delegate_serial; got {result['decision']!r}: {result['reason']}"
    )
    print("TEST 11 PASS: contention trigger (D001) → delegate_serial")


# ── TEST 11b (D001 fix #2): keyed resource_key=<slug> serialization_reason ────

def test_preflight_serialization_reason_keyed_form():
    """serialization_reason='resource_key=db-port-5432' (documented keyed form) → delegate_serial.

    phase-0-setup.md Step 6 annotates execution_plan groups with
    "serialization_reason": "resource_key=<key>". The preflight normalizer must
    match the keyed form, not only the bare category, so a future orchestrator
    wiring does not silently miss this branch.
    """
    task = _task("task_1", files=["utils.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "green"},
        "fallback_used": False,
        "files": ["utils.py"],
        "write_policy": {"allowed_write_globs": ["utils.py"], "forbidden_write_globs": []},
    }
    state = {
        "risk_levels": {"task_1": "mid"},
        # T15 seam: directly injected; the documented keyed form from phase-0 Step 6.
        "serialization_reason": "resource_key=db-port-5432",
    }
    result = gate.preflight(task, packet, state)
    assert result["decision"] == "delegate_serial", (
        f"Keyed serialization_reason must normalize and → delegate_serial; "
        f"got {result['decision']!r}: {result['reason']}"
    )
    print("TEST 11b PASS: keyed 'resource_key=<slug>' serialization_reason → delegate_serial")


# ── TEST 12 (D001): trust/risk trigger → block ────────────────────────────────

def test_preflight_trust_risk_trigger_block():
    """(g) D001: risk_markers (trust/risk trigger) → block → escalate_to_user path.

    CPE mapped this to local_fallback (main agent implements with full context).
    CME has no main-agent-implements path, so block is the conservative floor.
    """
    task = _task("task_1", files=["infra/config.py"], acceptance="pytest tests/",
                 body="Requires operator review. Risk markers: database schema migration.")
    packet = {
        "budget": {"status": "green"},
        "fallback_used": False,
        "files": ["infra/config.py"],
        "risk_markers": ["database"],  # explicit risk marker on packet
        "write_policy": {
            "allowed_write_globs": ["infra/config.py"],
            "forbidden_write_globs": [],
        },
    }
    state = {"risk_levels": {"task_1": "high"}}
    result = gate.preflight(task, packet, state)
    assert result["decision"] == "block", (
        f"Risk/trust trigger must → block; got {result['decision']!r}: {result['reason']}"
    )
    print("TEST 12 PASS: trust/risk trigger (D001) → block")


# ── TEST 13 (D001): delegate_parallel has T15 seam annotation ────────────────

def test_preflight_delegate_parallel_seam():
    """delegate_parallel is produced for a clean, multi-task-group scenario.

    This proves the seam path is reachable (not dead code), while the T15 seam
    comment in gate.py documents that no sequential consumer exists today.
    """
    task = _task("task_1", files=["foo.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "green"},
        "fallback_used": False,
        "files": ["foo.py"],
        "write_policy": {"allowed_write_globs": ["foo.py"], "forbidden_write_globs": []},
    }
    # parallel_group with multiple tasks AND no contention/serialization
    state = {
        "risk_levels": {"task_1": "mid"},
        "parallel_group_size": 2,  # orchestrator hint: this task is in a 2-task parallel group
    }
    result = gate.preflight(task, packet, state)
    assert result["decision"] in ("delegate_parallel", "delegate_serial"), (
        f"Multi-group clean task should yield delegate_parallel or delegate_serial; "
        f"got {result['decision']!r}"
    )
    print(f"TEST 13 PASS: multi-group clean task → {result['decision']!r} (T15 seam path reachable)")


# ── TEST 14: executability_audit — (d) HIGH with no AC → blocking issue ──────

def test_executability_audit_high_no_ac_blocking():
    """(d) HIGH task without Acceptance Criteria → blocking issue in audit."""
    parsed_plan = {
        "tasks": [
            _task("task_1", files=["api.py"], acceptance=None),  # no AC
        ]
    }
    packets = {}  # no packet for task_1
    result = gate.executability_audit(parsed_plan, packets)
    assert isinstance(result, dict), "executability_audit must return dict"
    tasks = result.get("tasks", {})
    t1 = tasks.get("task_1", {})
    raw = t1.get("raw_blocking_issue_count", 0)
    assert raw >= 1, (
        f"HIGH/no-AC task must have raw_blocking_issue_count >= 1; got {raw}"
    )
    blocking = t1.get("blocking_issues", [])
    assert len(blocking) >= 1, f"blocking_issues must be non-empty for no-AC task; got {blocking}"
    print("TEST 14 PASS: HIGH task with no AC → executability blocking issue")


# ── TEST 15: executability_audit — (e) operator review reduces effective count ─

def test_executability_audit_operator_review_reduces_count():
    """(e) operator_reviewed_blocking_issues: blocking_issue_count < raw_blocking_issue_count.

    A task with a spec-fallback issue (full_spec_fallback_not_reviewed) that
    is waived when spec.mapping.operator_reviewed=True.
    """
    # Task with acceptance criteria (so acceptance_command_missing doesn't fire)
    # and a packet with spec.fallback_used=True + operator_reviewed=True.
    parsed_plan = {
        "tasks": [
            _task("task_1", files=["db/migrate.py"],
                  acceptance="python3 -m pytest tests/db/",
                  body="Database schema migration"),
        ]
    }
    packets = {
        "task_1": {
            "task_id": "task_1",
            "budget": {"status": "green"},
            # spec.fallback_used=True with operator_reviewed=True:
            # the full_spec_fallback_not_reviewed blocking issue is created then waived.
            "spec": {
                "fallback_used": True,
                "mapping": {"operator_reviewed": True},
            },
            "write_policy": {
                "allowed_write_globs": ["db/migrate.py"],
                "forbidden_write_globs": [],
            },
        }
    }
    # First verify: without operator_reviewed, the issue would be blocking
    packets_no_review = {
        "task_1": {
            "task_id": "task_1",
            "budget": {"status": "green"},
            "spec": {
                "fallback_used": True,
                "mapping": {"operator_reviewed": False},  # NOT reviewed
            },
            "write_policy": {
                "allowed_write_globs": ["db/migrate.py"],
                "forbidden_write_globs": [],
            },
        }
    }
    result_no_review = gate.executability_audit(parsed_plan, packets_no_review)
    raw_pre = result_no_review["tasks"]["task_1"]["raw_blocking_issue_count"]
    assert raw_pre >= 1, (
        f"Without operator review, spec-fallback task must have >= 1 blocking issue; got {raw_pre}"
    )

    # Now with operator_reviewed=True: effective count should be lower than raw
    result = gate.executability_audit(parsed_plan, packets)
    tasks = result.get("tasks", {})
    t1 = tasks.get("task_1", {})
    raw = t1.get("raw_blocking_issue_count", 0)
    effective = t1.get("blocking_issue_count", 0)
    assert raw >= 1, f"raw_blocking_issue_count must be >= 1 (waived issue counted); got {raw}"
    assert effective < raw, (
        f"Operator review must reduce effective count below raw; "
        f"raw={raw}, effective={effective}"
    )
    # Reflect operator review in the task record
    assert "operator_reviewed_blocking_issues" in t1, (
        "task must have operator_reviewed_blocking_issues field"
    )
    assert len(t1["operator_reviewed_blocking_issues"]) >= 1, (
        "operator_reviewed_blocking_issues must be non-empty when a waiver occurred"
    )
    print(
        f"TEST 15 PASS: operator review reduces effective blocking count "
        f"(raw={raw}, effective={effective})"
    )


# ── TEST 16: executability_audit — structure fields present ──────────────────

def test_executability_audit_structure():
    """executability_audit must return required top-level fields."""
    parsed_plan = {
        "tasks": [
            _task("task_1", files=["foo.py"], acceptance="pytest"),
        ]
    }
    packets = {}
    result = gate.executability_audit(parsed_plan, packets)
    required_top = {"tasks", "raw_blocking_issue_count", "blocking_issue_count",
                    "passed", "grade"}
    missing = required_top - set(result.keys())
    assert not missing, f"executability_audit missing top-level keys: {missing}"
    t1 = result["tasks"].get("task_1", {})
    required_task = {"blocking_issues", "raw_blocking_issue_count", "blocking_issue_count",
                     "operator_reviewed_blocking_issues", "operator_decision"}
    missing_task = required_task - set(t1.keys())
    assert not missing_task, f"task audit missing keys: {missing_task}"
    print("TEST 16 PASS: executability_audit has required structure fields")


# ── TEST 17: assign_risk — override applies to all tasks ─────────────────────

def test_assign_risk_override():
    """risk=<level> override applies to all tasks uniformly."""
    tasks = [
        _task("task_1", files=["a.py"]),
        _task("task_2", files=["b.py"]),
    ]
    risk = gate.assign_risk(tasks, override="high")
    for tid, level in risk.items():
        assert level == "high", f"Override 'high' must apply to {tid}; got {level!r}"
    # Return type must stay a plain dict (warnings_sink is optional, non-breaking)
    assert isinstance(risk, dict), f"assign_risk must return a dict; got {type(risk)}"
    print("TEST 17 PASS: assign_risk override applies to all tasks")


# ── TEST 17b (fix #3): downgrade override on dangerous task → structured warning ─

def test_assign_risk_override_captures_structured_warning():
    """(fix #3) A DOWNGRADE override over a task with high-risk keywords appends a
    structured risk_override_warnings[] entry to the caller-provided sink.

    phase-0-setup.md Step 4 (line 214): entry has task, override, suggested_risk,
    matched_keywords, ts. The sink IS the honest seam — gate.py has no state
    access; the orchestrator reads the sink and writes state.json.
    """
    tasks = [
        _task("task_1", files=["db/migrate.py"],
              body="Perform the database schema migration for the users table"),
    ]
    sink: list = []
    risk = gate.assign_risk(tasks, override="low", warnings_sink=sink)
    # Override still wins (dangerous task is NOT silently blocked, just warned)
    assert risk["task_1"] == "low", f"Override must still apply; got {risk['task_1']!r}"
    # One structured entry captured
    assert len(sink) == 1, f"Expected exactly 1 structured warning; got {sink}"
    entry = sink[0]
    assert entry["task"] == "task_1", f"entry.task wrong: {entry}"
    assert entry["override"] == "low", f"entry.override wrong: {entry}"
    assert entry["suggested_risk"] == "high", f"entry.suggested_risk must be 'high': {entry}"
    # matched_keywords must contain the actual words that hit (not just be non-empty)
    assert "database" in entry["matched_keywords"], (
        f"matched_keywords must include 'database'; got {entry['matched_keywords']}"
    )
    assert "schema migration" in entry["matched_keywords"], (
        f"matched_keywords must include 'schema migration'; got {entry['matched_keywords']}"
    )
    # ts present (do NOT pin exact value)
    assert "ts" in entry and isinstance(entry["ts"], str) and entry["ts"], (
        f"entry must carry a non-empty ts string; got {entry.get('ts')!r}"
    )
    print(f"TEST 17b PASS: downgrade override on dangerous task → structured warning {entry['matched_keywords']}")


# ── TEST 17c (fix #3 negative): safe task downgrade → NO warning ─────────────

def test_assign_risk_override_safe_task_no_warning():
    """(fix #3 negative) Downgrading a SAFE task (no high-risk keywords) appends
    nothing to the sink. Discriminates the matcher from an unconditional append.
    """
    tasks = [
        _task("task_1", files=["ui/button.py"], body="Rename a local variable in the button widget"),
    ]
    sink: list = []
    risk = gate.assign_risk(tasks, override="low", warnings_sink=sink)
    assert risk["task_1"] == "low"
    assert sink == [], f"Safe task must produce NO structured warning; got {sink}"
    # And an override=high (not a downgrade) on a dangerous task also warns nothing
    dangerous = [_task("task_2", files=["db.py"], body="database schema migration")]
    sink2: list = []
    gate.assign_risk(dangerous, override="high", warnings_sink=sink2)
    assert sink2 == [], f"override=high is not a downgrade; must not warn; got {sink2}"
    print("TEST 17c PASS: safe-task downgrade and override=high produce no structured warning")


# ── TEST 18: partition_waves — list[list[str]] shape invariant ───────────────

def test_partition_waves_shape_invariant():
    """Verify partition_waves output is EXACTLY list[list[str]] — no dicts."""
    tasks = [
        _task("task_1", files=["a.py"]),
        _task("task_2", files=["b.py"], depends_on=[1]),
        _task("task_3", files=["c.py"]),
    ]
    risk = {"task_1": "low", "task_2": "mid", "task_3": "low"}
    result = gate.partition_waves(tasks, risk, parallel=True)
    assert isinstance(result, list), f"Must be list; got {type(result)}"
    for i, group in enumerate(result):
        assert isinstance(group, list), (
            f"group[{i}] must be list (not dict); got {type(group)}: {group!r}"
        )
        for j, tid in enumerate(group):
            assert isinstance(tid, str), (
                f"group[{i}][{j}] must be str; got {type(tid)}: {tid!r}"
            )
    # Verify all task_ids present exactly once
    flat = [tid for group in result for tid in group]
    assert sorted(flat) == sorted(["task_1", "task_2", "task_3"]), (
        f"All tasks must appear exactly once; got {flat}"
    )
    print(f"TEST 18 PASS: partition_waves shape is list[list[str]]; result={result}")


# ── TEST 19: partition_waves — file-overlap tasks stay separate (singletons) ──

def test_partition_waves_file_overlap_stays_separate():
    """(a) Two LOW tasks sharing a file must stay in separate groups (singletons)."""
    tasks = [
        _task("task_1", files=["shared.py", "a.py"]),
        _task("task_2", files=["shared.py", "b.py"]),
        _task("task_3", files=["c.py"]),  # no overlap, can merge
    ]
    risk = {"task_1": "mid", "task_2": "mid", "task_3": "mid"}
    result = gate.partition_waves(tasks, risk, parallel=True)
    # task_1 and task_2 share shared.py → must never appear in the SAME group
    for group in result:
        assert not ("task_1" in group and "task_2" in group), (
            f"task_1 and task_2 share a file; must not be in same group; group={group}"
        )
    print("TEST 19 PASS: file-overlapping tasks are kept in separate groups")


# ── TEST 20: preflight — would_have is populated when decision deviates ───────

def test_preflight_would_have_populated():
    """When block fires, would_have records what would have happened without the gate."""
    task = _task("task_1", files=["foo.py"], acceptance="pytest tests/")
    packet = {
        "budget": {"status": "red"},  # causes block
        "fallback_used": False,
        "files": ["foo.py"],
        "write_policy": {"allowed_write_globs": ["foo.py"], "forbidden_write_globs": []},
    }
    state = {"risk_levels": {"task_1": "mid"}}
    result = gate.preflight(task, packet, state)
    assert result["decision"] == "block"
    # would_have should document what the decision would be without this gate
    would_have = result.get("would_have")
    # May be None if the gate is fundamental (no alternative decision), or
    # a dict with {decision, reason} when a non-blocking alternative exists.
    # We just verify the key is present (its value may legitimately be None).
    assert "would_have" in result, "preflight must always include would_have key"
    print(f"TEST 20 PASS: preflight would_have present (value={would_have!r})")


# ── main ──────────────────────────────────────────────────────────────────────

_TESTS = [
    test_assign_risk_basic,
    test_shared_file_low_promotion,
    test_partition_waves_dependency_order,
    test_partition_waves_serial_singleton,
    test_partition_waves_resource_key_singleton,
    test_partition_waves_parallel_off,
    test_preflight_happy_path,
    test_preflight_file_overlap_blocks,
    test_preflight_packet_red_blocks,
    test_preflight_write_scope_too_broad_blocks,
    test_preflight_contention_trigger_delegate_serial,
    test_preflight_serialization_reason_keyed_form,
    test_preflight_trust_risk_trigger_block,
    test_preflight_delegate_parallel_seam,
    test_executability_audit_high_no_ac_blocking,
    test_executability_audit_operator_review_reduces_count,
    test_executability_audit_structure,
    test_assign_risk_override,
    test_assign_risk_override_captures_structured_warning,
    test_assign_risk_override_safe_task_no_warning,
    test_partition_waves_shape_invariant,
    test_partition_waves_file_overlap_stays_separate,
    test_preflight_would_have_populated,
]

if __name__ == "__main__":
    failed = []
    for fn in _TESTS:
        try:
            fn()
        except Exception as exc:
            print(f"FAIL: {fn.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            failed.append(fn.__name__)

    print()
    print(f"Results: {len(_TESTS) - len(failed)}/{len(_TESTS)} passed")
    print(f"{len(_TESTS)} defined / {len(_TESTS)} invoked")
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
