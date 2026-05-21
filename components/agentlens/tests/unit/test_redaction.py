"""Tests for agentlens.redaction (task_22, M8).

Covers spec §5.11 (patterns), §5.12 (redact), §8.1–8.2 (privacy default,
excerpt allow-list), and writer ER-6 (post-redact schema re-validation).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agentlens.constants import MAX_EXCERPT_CHARS
from agentlens.redaction.patterns import (
    EXCERPT_EXTRACTORS,
    HOME_PREFIXES,
    PROTECTED_KEYS,
    SECRET_PATTERNS,
)
from agentlens.redaction.redact import (
    apply_to_doc,
    make_excerpt,
    mask_path,
    mask_secret,
)
from agentlens.store.writer import atomic_write_json


# --- secret masking ---------------------------------------------------------


def test_mask_secret_openai_key() -> None:
    raw = "leaked sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ here"
    out = mask_secret(raw)
    assert "<REDACTED:openai_key>" in out
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV" not in out


def test_mask_secret_stripe_key_pk_live() -> None:
    raw = "key=pk_live_ABCDEFGHIJKLMNOPQRSTUVWXYZ end"
    out = mask_secret(raw)
    assert "<REDACTED:stripe_key>" in out
    assert "pk_live_ABCDEFGHIJKLMNOP" not in out


def test_mask_secret_stripe_key_sk_test() -> None:
    raw = "key=sk_test_ABCDEFGHIJKLMNOPQRSTUVWXYZ end"
    out = mask_secret(raw)
    assert "<REDACTED:stripe_key>" in out


def test_mask_secret_aws_key() -> None:
    raw = "AKIAIOSFODNN7EXAMPLE used"
    out = mask_secret(raw)
    assert "<REDACTED:aws_key>" in out
    assert "AKIA" not in out


def test_mask_secret_auth_header() -> None:
    raw = "Authorization: Bearer abc123tokenvalue"
    out = mask_secret(raw)
    # auth_header matches at line start (case-insensitive)
    assert "<REDACTED:" in out
    assert "abc123tokenvalue" not in out


def test_mask_secret_bearer_token() -> None:
    raw = "x-auth=Bearer abcdef0123456789ABCDEF.token-value"
    out = mask_secret(raw)
    assert "<REDACTED:" in out
    assert "abcdef0123456789ABCDEF" not in out


def test_mask_secret_private_key() -> None:
    raw = "-----BEGIN PRIVATE KEY-----\nMIIE..."
    out = mask_secret(raw)
    assert "<REDACTED:private_key>" in out
    assert "BEGIN PRIVATE KEY" not in out


def test_mask_secret_rsa_private_key_variant() -> None:
    raw = "-----BEGIN RSA PRIVATE KEY-----"
    out = mask_secret(raw)
    assert "<REDACTED:private_key>" in out


def test_mask_secret_no_secret_passthrough() -> None:
    raw = "no secrets here, just text"
    assert mask_secret(raw) == raw


# --- path masking -----------------------------------------------------------


def test_mask_path_home_prefix_users() -> None:
    raw = "open /Users/alice/source/file.py"
    out = mask_path(raw)
    assert "/Users/alice" not in out
    assert "<HOME>/" in out


def test_mask_path_home_prefix_linux() -> None:
    raw = "open /home/bob/project/x.py"
    out = mask_path(raw)
    assert "/home/bob" not in out
    assert "<HOME>/" in out


def test_mask_path_workspace_root_relative(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    raw = f"located at {workspace}/src/main.py"
    out = mask_path(raw, workspace_root=workspace)
    assert str(workspace) not in out
    assert "./src/main.py" in out


def test_mask_path_no_path_passthrough() -> None:
    raw = "no paths at all"
    assert mask_path(raw) == raw


# --- excerpt extractors -----------------------------------------------------


def test_make_excerpt_pytest_summary() -> None:
    raw = "lots of output\n============= 12 passed, 1 failed in 0.5s =============\n"
    out = make_excerpt(raw, extractor="pytest_summary")
    assert out is not None
    assert "12 passed" in out
    assert "1 failed" in out


def test_make_excerpt_exit_code_line() -> None:
    raw = "logs...\nProcess exited with code 137\nmore"
    out = make_excerpt(raw, extractor="exit_code_line")
    assert out is not None
    assert "137" in out


def test_make_excerpt_error_type() -> None:
    raw = "Traceback...\nTypeError: unsupported operand type\nmore lines"
    out = make_excerpt(raw, extractor="error_type")
    assert out is not None
    assert "TypeError" in out


def test_make_excerpt_unknown_extractor() -> None:
    with pytest.raises(KeyError):
        make_excerpt("anything", extractor="nope_not_real")


def test_make_excerpt_truncates_to_max() -> None:
    # Force an extractor to return a long line by faking the input.
    long_line = "TypeError: " + ("x" * (MAX_EXCERPT_CHARS + 200))
    out = make_excerpt(long_line, extractor="error_type")
    assert out is not None
    assert len(out) <= MAX_EXCERPT_CHARS


def test_make_excerpt_none_when_no_match() -> None:
    out = make_excerpt("just neutral text", extractor="pytest_summary")
    assert out is None


# --- apply_to_doc -----------------------------------------------------------


def test_apply_to_doc_masks_string_secret() -> None:
    doc = {"note": "leak sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ here"}
    out = apply_to_doc(doc)
    assert "<REDACTED:openai_key>" in out["note"]


def test_apply_to_doc_recurses_nested_dict_and_list() -> None:
    doc = {
        "top": {
            "middle": {
                "leaf": "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            },
            "items": ["plain", "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
        }
    }
    out = apply_to_doc(doc)
    assert "<REDACTED:openai_key>" in out["top"]["middle"]["leaf"]
    assert out["top"]["items"][0] == "plain"
    assert "<REDACTED:openai_key>" in out["top"]["items"][1]


def test_apply_to_doc_does_not_mutate_input() -> None:
    doc = {"note": "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    original = json.loads(json.dumps(doc))
    apply_to_doc(doc)
    assert doc == original


def test_apply_to_doc_protected_literal_keys_unchanged() -> None:
    # The same secret-looking string is protected in `run_id` but redacted
    # elsewhere.
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    doc = {
        "run_id": secret,
        "workspace_id": secret,
        "schema": secret,
        "elsewhere": secret,
    }
    out = apply_to_doc(doc)
    assert out["run_id"] == secret
    assert out["workspace_id"] == secret
    assert out["schema"] == secret
    assert "<REDACTED:openai_key>" in out["elsewhere"]


def test_apply_to_doc_hash_suffix_unchanged() -> None:
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    doc = {
        "git_remote_hash": secret,
        "root_hash": secret,
        "arbitrary_hash": secret,
        "sha256": secret,
    }
    out = apply_to_doc(doc)
    assert out["git_remote_hash"] == secret
    assert out["root_hash"] == secret
    assert out["arbitrary_hash"] == secret
    assert out["sha256"] == secret


def test_apply_to_doc_enum_status_keys_unchanged() -> None:
    doc = {
        "status": "ok",
        "type": "run.started",
        "category": "command",
        "severity": "info",
        "source": "shim",
        "agent_outcome": "success",
    }
    out = apply_to_doc(doc)
    assert out == doc


def test_apply_to_doc_path_label_forced_mask() -> None:
    doc = {"path_label": "/Users/alice/src/x.py"}
    out = apply_to_doc(doc)
    assert "/Users/alice" not in out["path_label"]
    assert "<HOME>/" in out["path_label"]


def test_apply_to_doc_excerpt_string_value_truncated() -> None:
    # When the `excerpt` key has a string value longer than MAX_EXCERPT_CHARS,
    # it is truncated rather than rejected.
    doc = {"excerpt": "x" * (MAX_EXCERPT_CHARS + 100)}
    out = apply_to_doc(doc)
    assert len(out["excerpt"]) <= MAX_EXCERPT_CHARS


def test_apply_to_doc_workspace_root_applied(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    doc = {"note": f"file at {workspace}/a/b.py"}
    out = apply_to_doc(doc, workspace_root=workspace)
    assert str(workspace) not in out["note"]
    assert "./a/b.py" in out["note"]


# --- patterns sanity --------------------------------------------------------


def test_secret_patterns_shape() -> None:
    assert isinstance(SECRET_PATTERNS, list)
    assert all(isinstance(name, str) and hasattr(rx, "search") for name, rx in SECRET_PATTERNS)
    names = [n for n, _ in SECRET_PATTERNS]
    for required in ("openai_key", "stripe_key", "aws_key", "auth_header", "bearer", "private_key"):
        assert required in names


def test_home_prefixes_include_users_and_home() -> None:
    assert "/Users/" in HOME_PREFIXES
    assert "/home/" in HOME_PREFIXES


def test_excerpt_extractors_keys() -> None:
    assert set(EXCERPT_EXTRACTORS) >= {"pytest_summary", "exit_code_line", "error_type"}


def test_protected_keys_contain_required() -> None:
    required = {
        "schema",
        "run_id",
        "workspace_id",
        "event_id",
        "parent_run_id",
        "sha256",
        "status",
        "type",
        "category",
        "severity",
        "source",
        "blame_scope",
        "recoverability",
        "sealed_phase",
        "agent_outcome",
    }
    assert required.issubset(PROTECTED_KEYS)


# --- writer integration -----------------------------------------------------


def test_writer_applies_redaction_and_revalidates(tmp_path: Path) -> None:
    # A valid run doc, but with a secret embedded in a non-protected place.
    doc = {
        "schema": "agentlens.run.v1",
        "run_id": "run_20260518_211328_abc123",
        "workspace_id": "ws_0123456789abcdef",
        "started_at": "2026-05-18T21:13:28Z",
        "agent": {
            "name": "claude_code",
            "mode": "cli",
            "version": "1.0.0 sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        },
        "workspace": {
            "root_label": "<workspace>",
            "root_hash": (
                "sha256:0123456789abcdef0123456789abcdef"
                "0123456789abcdef0123456789abcdef"
            ),
            "id_basis": "git",
            "git_branch": "main",
        },
        "recording": {
            "mode": "minimal",
            "adapter": "claude_code_shim",
        },
    }
    out_path = tmp_path / "run.json"
    atomic_write_json(out_path, doc)
    persisted = json.loads(out_path.read_text(encoding="utf-8"))
    # Secret in agent.version is redacted on disk.
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in persisted["agent"]["version"]
    assert "<REDACTED:openai_key>" in persisted["agent"]["version"]
    # run_id (protected) is preserved.
    assert persisted["run_id"] == "run_20260518_211328_abc123"
    # root_hash (suffix-protected) is preserved.
    assert persisted["workspace"]["root_hash"].startswith("sha256:")


def test_home_hash_deterministic() -> None:
    # mask_path should hash the home prefix; two calls produce same hash.
    s1 = mask_path("/Users/alice/x")
    s2 = mask_path("/Users/alice/y")
    # Both should use the same <HOME>/<HASH8> prefix.
    # Extract prefix tag.
    prefix1 = s1.split("/x")[0]
    prefix2 = s2.split("/y")[0]
    assert prefix1 == prefix2
    assert prefix1.startswith("<HOME>/")
    hash_part = prefix1[len("<HOME>/"):]
    assert len(hash_part) == 8
    # And it actually matches sha256("/Users/alice")[:8].
    expected = hashlib.sha256(b"/Users/alice").hexdigest()[:8]
    assert hash_part == expected
