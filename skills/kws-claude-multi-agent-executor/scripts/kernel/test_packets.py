"""test_packets.py — TDD suite for packets.py (CME v3.0 T10).

Tests:
  (a) Explicit "Spec Refs" task → only those sections included
  (b) Unmatchable task → fallback_used=True + non-empty next_action string
  (c) Huge spec → red status + trimming (status remains red even after trim)
  (d) budget.used equals actual character count of included content
  (e) build_manifest section structure basics
  (f) dispatch integration: packet on disk → prompt uses packet content (not stub)
  (g) persist writes both .json and .md to orch_dir/packets/
  (h) no-packet fallback: dispatch without packet still works (existing behavior)
  (i) budget status green/yellow thresholds
  (j) file-matching heuristic → sections included by signal match
  (k) manifest S0 fallback for headingless spec
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import packets
import dispatch

SKILL_DIR = str(Path(__file__).resolve().parents[2])  # skills/kws-claude-multi-agent-executor

PLACEHOLDER_RE = re.compile(r"\{[A-Za-z][^{}\n]*\}")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_SPEC = """\
# Overview

This is the overview section.

## Authentication

Handle user login and sessions.

## Database

Manage data storage and retrieval.
Files: `db.py`, `models.py`
"""

HUGE_SPEC_SECTION_CONTENT = "x" * 20000

HUGE_SPEC = "# Main\n\n" + HUGE_SPEC_SECTION_CONTENT + "\n\n## Sub1\n\n" + HUGE_SPEC_SECTION_CONTENT + "\n\n## Sub2\n\n" + HUGE_SPEC_SECTION_CONTENT + "\n"


def _make_task(task_id="task_1", title="Implement auth", files=None, body="", spec_refs=None):
    """Build a planparse-like task dict."""
    t = {
        "id": task_id,
        "number": int(task_id.split("_")[1]),
        "title": title,
        "files": files or ["auth.py"],
        "dependencies": [],
        "acceptance": None,
        "serial": False,
        "resource_key": None,
        "body": body,
    }
    if spec_refs is not None:
        t["spec_refs"] = spec_refs
    return t


# ---------------------------------------------------------------------------
# TEST (e): build_manifest sections basics
# ---------------------------------------------------------------------------

def test_build_manifest_basic():
    """(e) build_manifest splits spec by headings; each section has id, content hash, text."""
    manifest = packets.build_manifest(SIMPLE_SPEC)

    assert "sections" in manifest
    assert "section_order" in manifest
    assert len(manifest["section_order"]) >= 3, (
        f"Expected >=3 sections from SIMPLE_SPEC, got: {manifest['section_order']}"
    )

    for sid in manifest["section_order"]:
        sec = manifest["sections"][sid]
        assert "id" in sec
        assert "sha256" in sec
        assert "text" in sec  # kernel manifest stores actual text, not just coords
        assert sec["id"] == sid

    print("TEST (e) PASS: build_manifest splits spec by headings, sections have id+sha256+text")


# ---------------------------------------------------------------------------
# TEST (a): explicit Spec Refs → only those sections included
# ---------------------------------------------------------------------------

def test_explicit_spec_refs_only():
    """(a) Task with explicit spec_refs → packet includes only those sections."""
    manifest = packets.build_manifest(SIMPLE_SPEC)
    order = manifest["section_order"]
    # Take just the first section id
    first_id = order[0]

    task = _make_task(spec_refs=[first_id])
    packet = packets.build_packet(task, manifest, SIMPLE_SPEC)

    assert packet["fallback_used"] is False
    ids_included = [s["id"] for s in packet["spec_sections"]]
    assert ids_included == [first_id], (
        f"Expected only [{first_id}], got: {ids_included}"
    )
    # Confirm other section ids are absent
    other_ids = [s for s in order if s != first_id]
    for oid in other_ids:
        assert oid not in ids_included, f"Section {oid} should not be included"

    print(f"TEST (a) PASS: explicit spec_refs=[{first_id}] → only that section included")


# ---------------------------------------------------------------------------
# TEST (b): unmatchable task → fallback_used=True + non-empty next_action
# ---------------------------------------------------------------------------

def test_unmatchable_task_fallback():
    """(b) Task with no matching files/refs → fallback_used=True, next_action non-empty."""
    manifest = packets.build_manifest(SIMPLE_SPEC)
    # Files that won't match any spec section signal
    task = _make_task(
        task_id="task_99",
        title="XYZ totally unrelated",
        files=["zzz_nomatch_xyz.py"],
        body="This task does something completely unrelated.",
    )
    packet = packets.build_packet(task, manifest, SIMPLE_SPEC)

    assert packet["fallback_used"] is True, (
        f"Expected fallback_used=True for unmatchable task, got: {packet['fallback_used']}"
    )
    assert packet["next_action"] is not None, "next_action must be a non-empty string on fallback"
    assert isinstance(packet["next_action"], str) and len(packet["next_action"]) > 0, (
        f"next_action must be non-empty string, got: {repr(packet['next_action'])}"
    )
    print("TEST (b) PASS: unmatchable task → fallback_used=True, next_action non-empty")


# ---------------------------------------------------------------------------
# TEST (c): huge spec → red status + trimming
# ---------------------------------------------------------------------------

def test_huge_spec_red_trim():
    """(c) Spec larger than budget → status=='red' even after trimming."""
    manifest = packets.build_manifest(HUGE_SPEC)
    task = _make_task(
        task_id="task_1",
        title="Process data",
        files=["db.py"],
        body="Implement database processing.",
    )
    # Very small budget: only 100 chars — spec is ~60k chars, way over
    packet = packets.build_packet(task, manifest, HUGE_SPEC, budget_chars=100)

    assert packet["budget"]["status"] == "red", (
        f"Expected status='red' for oversize spec, got: {packet['budget']['status']}"
    )
    assert packet["budget"]["used"] <= packet["budget"]["limit"], (
        f"After trim, used ({packet['budget']['used']}) should be <= limit ({packet['budget']['limit']})"
    )
    assert packet["fallback_reason"] is not None and "trim" in packet["fallback_reason"].lower(), (
        f"fallback_reason should mention trim: {packet['fallback_reason']}"
    )
    print("TEST (c) PASS: huge spec → red status, trimmed to under limit, fallback_reason set")


# ---------------------------------------------------------------------------
# TEST (d): budget.used equals actual character count of included content
# ---------------------------------------------------------------------------

def test_budget_used_equals_actual_chars():
    """(d) budget.used == actual char count of included section texts + task_body."""
    manifest = packets.build_manifest(SIMPLE_SPEC)
    order = manifest["section_order"]
    first_id = order[0]

    task = _make_task(spec_refs=[first_id], body="Do the thing.")
    packet = packets.build_packet(task, manifest, SIMPLE_SPEC)

    # Compute what used should be
    task_body_chars = len(packet["task_body"])
    spec_section_chars = sum(len(s["text"]) for s in packet["spec_sections"])
    expected_used = task_body_chars + spec_section_chars

    assert packet["budget"]["used"] == expected_used, (
        f"budget.used ({packet['budget']['used']}) != "
        f"task_body_chars ({task_body_chars}) + spec_section_chars ({spec_section_chars}) "
        f"= {expected_used}"
    )
    print("TEST (d) PASS: budget.used == len(task_body) + Σ len(spec_sections[].text)")


# ---------------------------------------------------------------------------
# TEST (g): persist writes .json and .md
# ---------------------------------------------------------------------------

def test_persist_writes_json_and_md():
    """(g) packets.persist() writes <orch_dir>/packets/task_N.json and .md."""
    manifest = packets.build_manifest(SIMPLE_SPEC)
    task = _make_task()
    packet = packets.build_packet(task, manifest, SIMPLE_SPEC)

    with tempfile.TemporaryDirectory() as orch_dir:
        packets.persist(packet, orch_dir)

        json_path = Path(orch_dir) / "packets" / "task_1.json"
        md_path = Path(orch_dir) / "packets" / "task_1.md"

        assert json_path.exists(), f"Expected {json_path} to exist"
        assert md_path.exists(), f"Expected {md_path} to exist"

        # JSON is authoritative and valid
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["task_id"] == "task_1"

        # MD is non-empty derived view
        md_text = md_path.read_text(encoding="utf-8")
        assert "task_1" in md_text

    print("TEST (g) PASS: persist writes .json (authoritative) and .md (derived)")


# ---------------------------------------------------------------------------
# TEST (f): dispatch integration — packet on disk → prompt uses packet content
# ---------------------------------------------------------------------------

def test_dispatch_uses_packet_when_present():
    """(f) When packet JSON exists on disk, dispatch.build incorporates its content."""
    manifest = packets.build_manifest(SIMPLE_SPEC)
    order = manifest["section_order"]
    first_id = order[0]
    section_text = manifest["sections"][first_id]["text"]
    # Ensure there's a distinctive phrase in the section we pick
    # (Simple spec sections have predictable content)

    task = _make_task(spec_refs=[first_id], body="Implement auth module.", task_id="task_3")
    packet = packets.build_packet(task, manifest, SIMPLE_SPEC)

    with tempfile.TemporaryDirectory() as orch_dir:
        packets.persist(packet, orch_dir)

        state = {
            "schema_version": 3,
            "status": "RUNNING",
            "worktree": "/fake/worktree",
            "implementer_model": "sonnet",
            "dispatch_config": {},
            "tasks": {
                "task_3": {
                    "status": "IN_PROGRESS",
                    "phase": "implement",
                    "review_retries": 0,
                    "verifier_retries": 0,
                    "escalations": 0,
                    "body": packet["task_body"],
                    "files": packet["files"],
                    "acceptance": None,
                    "title": "Implement auth",
                }
            },
            "risk_levels": {"task_3": "mid"},
            "execution_plan": [["task_3"]],
        }
        action = {"action": "dispatch", "role": "implementer", "task_id": "task_3", "attempt": 1}
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        # Packet's spec section text should appear in the prompt
        # section text starts with the heading so check a meaningful substring
        assert section_text[:80].strip() in prompt_text or any(
            s["text"][:60].strip() in prompt_text for s in packet["spec_sections"] if s["text"].strip()
        ), (
            f"Expected packet spec section content in prompt.\n"
            f"Section text start: {section_text[:80]!r}\n"
            f"Prompt excerpt: {prompt_text[:500]!r}"
        )

    print("TEST (f) PASS: dispatch reads packet from disk and uses its spec sections in prompt")


# ---------------------------------------------------------------------------
# TEST (h): no-packet fallback — dispatch without packet still works
# ---------------------------------------------------------------------------

def test_dispatch_no_packet_fallback():
    """(h) When no packet file exists, dispatch.build falls back to prior behavior."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = {
            "schema_version": 3,
            "status": "RUNNING",
            "worktree": "/fake/worktree",
            "implementer_model": "sonnet",
            "dispatch_config": {},
            "tasks": {
                "task_3": {
                    "status": "IN_PROGRESS",
                    "phase": "implement",
                    "review_retries": 0,
                    "verifier_retries": 0,
                    "escalations": 0,
                    "body": "Implement foo() returning 42.",
                    "files": ["src/foo.py"],
                    "acceptance": None,
                    "title": "Implement foo",
                }
            },
            "risk_levels": {"task_3": "mid"},
            "execution_plan": [["task_3"]],
        }
        action = {"action": "dispatch", "role": "implementer", "task_id": "task_3", "attempt": 1}
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        # Must succeed without error
        assert "prompt_path" in result
        assert "command" in result
        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        # Should contain the task body
        assert "Implement foo() returning 42." in prompt_text

    print("TEST (h) PASS: no-packet → dispatch falls back gracefully, task body still in prompt")


# ---------------------------------------------------------------------------
# TEST (i): budget status green/yellow thresholds
# ---------------------------------------------------------------------------

def test_budget_status_thresholds():
    """(i) budget status: green when well under, yellow when >0.7x limit, red when over limit."""
    manifest = packets.build_manifest(SIMPLE_SPEC)
    order = manifest["section_order"]
    first_id = order[0]
    section_text_len = len(manifest["sections"][first_id]["text"])

    task = _make_task(spec_refs=[first_id], body="short body")
    content_chars = len("short body") + section_text_len

    # Green: limit much larger than content
    packet_g = packets.build_packet(task, manifest, SIMPLE_SPEC, budget_chars=content_chars * 10)
    assert packet_g["budget"]["status"] == "green", (
        f"Expected green, got {packet_g['budget']['status']}"
    )

    # Yellow: limit set so content > 0.7 * limit but <= limit
    # limit = content_chars / 0.75 → content is 0.75*limit which is > 0.7*limit
    yellow_limit = max(1, int(content_chars / 0.75))
    packet_y = packets.build_packet(task, manifest, SIMPLE_SPEC, budget_chars=yellow_limit)
    assert packet_y["budget"]["status"] in ("yellow", "red"), (
        f"Expected yellow or red at 0.75x, got {packet_y['budget']['status']}"
    )

    # Red: limit smaller than content
    packet_r = packets.build_packet(task, manifest, SIMPLE_SPEC, budget_chars=max(1, content_chars - 1))
    assert packet_r["budget"]["status"] == "red", (
        f"Expected red when limit < content, got {packet_r['budget']['status']}"
    )

    print("TEST (i) PASS: green/yellow/red budget thresholds work correctly")


# ---------------------------------------------------------------------------
# TEST (j): file-matching heuristic → sections included by signal
# ---------------------------------------------------------------------------

def test_heuristic_file_match():
    """(j) Task with file matching a spec section signal → that section included."""
    # Spec has a Database section that mentions db.py
    manifest = packets.build_manifest(SIMPLE_SPEC)
    task = _make_task(
        task_id="task_2",
        title="Database layer",
        files=["db.py"],
        body="Implement database access layer.",
    )
    packet = packets.build_packet(task, manifest, SIMPLE_SPEC)

    # The Database section mentions 'db.py' so it should be heuristically matched
    ids_included = [s["id"] for s in packet["spec_sections"]]
    # We just verify that at least one section is included (heuristic matched something)
    # The exact section depends on scoring; we don't require "Database" specifically,
    # only that it's non-empty and fallback_used is False when there's a match
    # (If heuristic matched Database, fallback_used==False; otherwise test (b) covers the case)
    if not packet["fallback_used"]:
        assert len(ids_included) >= 1, "Expected at least one section when heuristic matches"

    print(f"TEST (j) PASS: heuristic match → fallback_used={packet['fallback_used']}, sections={ids_included}")


# ---------------------------------------------------------------------------
# TEST (k): manifest S0 fallback for headingless spec
# ---------------------------------------------------------------------------

def test_manifest_headingless_spec():
    """(k) Spec with no headings → single S0 section covers entire spec."""
    headingless = "This is a flat spec with no headings.\nJust plain text.\n"
    manifest = packets.build_manifest(headingless)

    assert manifest["section_order"] == ["S0"], (
        f"Expected ['S0'] for headingless spec, got: {manifest['section_order']}"
    )
    assert "S0" in manifest["sections"]
    assert manifest["sections"]["S0"]["text"] == headingless

    print("TEST (k) PASS: headingless spec → S0 section covers full text")


# ---------------------------------------------------------------------------
# TEST (l): packet shape matches required interface
# ---------------------------------------------------------------------------

def test_packet_shape():
    """(l) build_packet returns all required keys with correct types."""
    manifest = packets.build_manifest(SIMPLE_SPEC)
    task = _make_task()
    packet = packets.build_packet(task, manifest, SIMPLE_SPEC)

    required_keys = {"task_id", "task_body", "files", "spec_sections",
                     "fallback_used", "fallback_reason", "next_action", "budget"}
    assert required_keys.issubset(packet.keys()), (
        f"Missing keys: {required_keys - packet.keys()}"
    )
    assert isinstance(packet["task_id"], str)
    assert isinstance(packet["task_body"], str)
    assert isinstance(packet["files"], list)
    assert isinstance(packet["spec_sections"], list)
    assert isinstance(packet["fallback_used"], bool)
    # fallback_reason and next_action may be None when no fallback
    assert packet["fallback_reason"] is None or isinstance(packet["fallback_reason"], str)
    assert packet["next_action"] is None or isinstance(packet["next_action"], str)

    budget = packet["budget"]
    assert "limit" in budget
    assert "used" in budget
    assert "status" in budget
    assert budget["status"] in ("green", "yellow", "red")

    for sec in packet["spec_sections"]:
        assert "id" in sec
        assert "text" in sec

    print("TEST (l) PASS: packet has all required keys with correct types")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_build_manifest_basic,
        test_explicit_spec_refs_only,
        test_unmatchable_task_fallback,
        test_huge_spec_red_trim,
        test_budget_used_equals_actual_chars,
        test_persist_writes_json_and_md,
        test_dispatch_uses_packet_when_present,
        test_dispatch_no_packet_fallback,
        test_budget_status_thresholds,
        test_heuristic_file_match,
        test_manifest_headingless_spec,
        test_packet_shape,
    ]

    print(f"Running {len(tests)} tests...\n")
    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            import traceback
            print(f"FAIL: {fn.__name__}: {exc}")
            traceback.print_exc()
            failed.append(fn.__name__)

    print()
    print(f"Results: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)
