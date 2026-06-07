"""Tests for build_context_slice.py (v2.29 — I5).

The helper must reproduce the in-prose `{context_slice}` derivation from
phase-1-task-cycle.md (lines ~89-132) 1:1, reading task_summaries /
global_constraints from state.json so the orchestrator no longer assembles the
~40-line block in-context.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_context_slice as bcs  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_context_slice.py")


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _run(state_path, *args):
    return subprocess.run(
        [sys.executable, SCRIPT, str(state_path), *args],
        capture_output=True, text=True,
    )


# --- no deps / no shared files (first task) --------------------------------

def test_no_deps_no_shared_degrades_gracefully(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}, "task_summaries": {},
                          "global_constraints": {"shared_files": {}}})
    out = bcs.build_slice_from_state(json.loads(p.read_text()), "task_0", None, [], [])
    assert "deps_for_this_task: []" in out
    assert "task_summaries: {}  # no upstream deps" in out
    assert "shared_files: {}  # none of files_to_touch are shared with other tasks" in out
    assert out.splitlines()[0] == "active_plan_index: single"


# --- deps include upstream task_summaries.for_next_tasks -------------------

def test_deps_include_for_next_tasks(tmp_path):
    state = {
        "schema_version": "2", "tasks": {},
        "task_summaries": {"task_0": {"for_next_tasks": "exports parseFoo(); returns Foo"}},
        "global_constraints": {"shared_files": {}},
    }
    out = bcs.build_slice_from_state(state, "task_1", None, ["task_0"], [])
    assert "deps_for_this_task: [\"task_0\"]" in out
    assert "task_summaries:" in out
    assert "  task_0:" in out
    assert "    for_next_tasks: |" in out
    assert "      exports parseFoo(); returns Foo" in out


def test_deps_accept_bare_int_form(tmp_path):
    # The legacy dependency-graph notes use bare ints; both forms must resolve.
    state = {"task_summaries": {"task_2": {"for_next_tasks": "x"}},
             "global_constraints": {"shared_files": {}}}
    out = bcs.build_slice_from_state(state, "task_3", None, [2], [])
    assert "  task_2:" in out
    assert "      x" in out


# --- shared_files intersection filter --------------------------------------

def test_shared_files_filtered_to_this_task_files(tmp_path):
    state = {
        "task_summaries": {"task_9": {"for_next_tasks": "owns the schema"}},
        "global_constraints": {"shared_files": {
            "src/a.ts": ["task_1", "task_9"],
            "src/unrelated.ts": ["task_5", "task_8"],
        }},
    }
    out = bcs.build_slice_from_state(state, "task_1", None, [], ["src/a.ts", "src/b.ts"])
    assert "shared_files:" in out
    assert "  src/a.ts: [\"task_1\", \"task_9\"]" in out
    assert "src/unrelated.ts" not in out          # filtered out (not in files)
    assert "# task_9.for_next_tasks: owns the schema" in out


def test_no_intersecting_shared_files(tmp_path):
    state = {"task_summaries": {},
             "global_constraints": {"shared_files": {"src/x.ts": ["task_1", "task_2"]}}}
    out = bcs.build_slice_from_state(state, "task_3", None, [], ["src/other.ts"])
    assert "shared_files: {}  # none of files_to_touch are shared with other tasks" in out


# --- global_constraints text ----------------------------------------------

def test_global_constraints_text_block(tmp_path):
    state = {"task_summaries": {}, "global_constraints": {"shared_files": {},
             "text": "line one\nline two"}}
    out = bcs.build_slice_from_state(state, "task_0", None, [], [])
    assert "global_constraints: |" in out
    assert "  line one" in out
    assert "  line two" in out


# --- multi-plan via --plan-index ------------------------------------------

def test_multi_plan_plan_index(tmp_path):
    state = {
        "schema_version": "2", "active_plan": 1,
        "plan_chain": [
            {"task_summaries": {}, "global_constraints": {"shared_files": {}}},
            {"task_summaries": {"task_0": {"for_next_tasks": "plan1 dep"}},
             "global_constraints": {"shared_files": {}}},
        ],
    }
    out = bcs.build_slice_from_state(state, "task_1", 1, ["task_0"], [])
    assert out.splitlines()[0] == "active_plan_index: 1"
    assert "      plan1 dep" in out


# --- CLI behaviour ---------------------------------------------------------

def test_cli_emits_slice_and_exit_0(tmp_path):
    p = _write(tmp_path, {"task_summaries": {}, "global_constraints": {"shared_files": {}}})
    r = _run(p, "--task", "task_0")
    assert r.returncode == 0
    assert "active_plan_index: single" in r.stdout


def test_cli_deps_files_csv_and_json(tmp_path):
    p = _write(tmp_path, {
        "task_summaries": {"task_0": {"for_next_tasks": "dep summary"}},
        "global_constraints": {"shared_files": {"f.ts": ["task_0", "task_1"]}},
    })
    # CSV form
    r1 = _run(p, "--task", "task_1", "--deps", "task_0", "--files", "f.ts")
    assert "dep summary" in r1.stdout and "  f.ts:" in r1.stdout
    # JSON form
    r2 = _run(p, "--task", "task_1", "--deps", '["task_0"]', "--files", '["f.ts"]')
    assert r2.stdout == r1.stdout


def test_cli_missing_state_exit_2(tmp_path):
    r = _run(tmp_path / "nope.json", "--task", "task_0")
    assert r.returncode == 2
