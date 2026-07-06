"""test_validate.py — TDD tests for validate.check()

Cases:
  (a) valid implementer DONE   -> []
  (b) missing status           -> required error
  (c) unknown field + additionalProperties:false -> error
  (d) method_audit.waive_reason enum violation -> error
  (e) load existing verifier_result.schema.json + valid fixture -> []
  (f) load existing plan_reviewer_result.schema.json + valid fixture -> []
      (exercises $ref / $defs resolution)
  (g) valid reviewer PASS result -> []
  (h) invalid reviewer status enum -> error
  (i) plan_reviewer $ref: invalid item severity -> error
"""
import json, os, pathlib
import validate

SCHEMAS_DIR = pathlib.Path(__file__).parent.parent.parent / "references" / "_schemas"


def _load_schema(name: str) -> dict:
    with open(SCHEMAS_DIR / f"{name}_result.schema.json") as f:
        return json.load(f)


# ── helpers ─────────────────────────────────────────────────────────────────

def _implementer_schema():
    return _load_schema("implementer")


def _reviewer_schema():
    return _load_schema("reviewer")


# ── (a) valid implementer DONE ───────────────────────────────────────────────

def test_valid_implementer_done():
    schema = _implementer_schema()
    instance = {
        "status": "DONE",
        "summary": "Implemented the feature.",
        "files_changed": ["src/foo.py"],
        "files_test_changed": ["tests/test_foo.py"],
        "commit": "abc1234",
        "method_audit": {
            "tdd": "applied",
            "red_command": "pytest tests/test_foo.py",
            "green_command": "pytest tests/test_foo.py",
        },
    }
    errors = validate.check(instance, schema)
    assert errors == [], f"Expected no errors, got: {errors}"


# ── (b) missing required field: status ──────────────────────────────────────

def test_missing_status():
    schema = _implementer_schema()
    instance = {
        "summary": "No status here",
        "files_changed": [],
        "files_test_changed": [],
    }
    errors = validate.check(instance, schema)
    assert any("status" in e for e in errors), f"Expected 'status' required error, got: {errors}"


# ── (c) unknown field + additionalProperties:false ──────────────────────────

def test_additional_properties():
    schema = _implementer_schema()
    instance = {
        "status": "DONE",
        "summary": "OK",
        "files_changed": [],
        "files_test_changed": [],
        "unknown_field": "should fail",
    }
    errors = validate.check(instance, schema)
    assert any("unknown_field" in e or "additional" in e.lower() for e in errors), (
        f"Expected additionalProperties error, got: {errors}"
    )


# ── (d) method_audit.waive_reason enum violation ────────────────────────────

def test_enum_violation_nested():
    schema = _implementer_schema()
    instance = {
        "status": "DONE",
        "summary": "OK",
        "files_changed": [],
        "files_test_changed": [],
        "method_audit": {
            "tdd": "waived",
            "waive_reason": "not-a-valid-reason",
        },
    }
    errors = validate.check(instance, schema)
    assert any("waive_reason" in e for e in errors), (
        f"Expected waive_reason enum error, got: {errors}"
    )


# ── (e) verifier schema compat: valid fixture -> [] ─────────────────────────

def test_verifier_schema_compat():
    schema = _load_schema("verifier")
    instance = {
        "status": "PASS",
        "commands_run": ["pytest tests/", "bun run check"],
        "exit_codes": [0, 0],
    }
    errors = validate.check(instance, schema)
    assert errors == [], f"Expected no errors on verifier fixture, got: {errors}"


# ── (f) plan_reviewer schema compat: $ref/$defs resolution ──────────────────

def test_plan_reviewer_schema_ref_defs():
    schema = _load_schema("plan_reviewer")
    instance = {
        "status": "ISSUES_FOUND",
        "summary": "One blocker found.",
        "issues": [
            {
                "severity": "BLOCKER",
                "category": "missing_ac",
                "description": "Task 3 has no acceptance criteria.",
                "task": "task_3",
            }
        ],
    }
    errors = validate.check(instance, schema)
    assert errors == [], f"Expected no errors on plan_reviewer fixture, got: {errors}"


# ── (g) valid reviewer PASS ──────────────────────────────────────────────────

def test_valid_reviewer_pass():
    schema = _reviewer_schema()
    instance = {
        "status": "PASS",
        "spec_score": 9.5,
        "quality_score": 8.0,
        "issues": [],
    }
    errors = validate.check(instance, schema)
    assert errors == [], f"Expected no errors on reviewer PASS, got: {errors}"


# ── (h) invalid reviewer status enum ────────────────────────────────────────

def test_reviewer_invalid_status():
    schema = _reviewer_schema()
    instance = {
        "status": "UNKNOWN",
        "spec_score": 9.0,
        "quality_score": 7.0,
        "issues": [],
    }
    errors = validate.check(instance, schema)
    assert any("status" in e for e in errors), (
        f"Expected status enum error, got: {errors}"
    )


# ── (i) plan_reviewer $ref: invalid item severity ───────────────────────────

def test_plan_reviewer_invalid_item():
    schema = _load_schema("plan_reviewer")
    instance = {
        "status": "ISSUES_FOUND",
        "summary": "Has bad issue.",
        "issues": [
            {
                "severity": "CRITICAL",  # not in enum
                "category": "missing_ac",
                "description": "Something.",
            }
        ],
    }
    errors = validate.check(instance, schema)
    assert any("severity" in e for e in errors), (
        f"Expected severity enum error via $ref resolution, got: {errors}"
    )


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_valid_implementer_done()
    test_missing_status()
    test_additional_properties()
    test_enum_violation_nested()
    test_verifier_schema_compat()
    test_plan_reviewer_schema_ref_defs()
    test_valid_reviewer_pass()
    test_reviewer_invalid_status()
    test_plan_reviewer_invalid_item()
    print("OK")
