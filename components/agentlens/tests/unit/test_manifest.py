"""Tests for agentlens.store.manifest (spec §5.7, §6.2)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from agentlens.schema.validate import validate_doc
from agentlens.store.manifest import (
    ManifestEntry,
    collect_files,
    init_manifest,
    mark_recording_incomplete,
    seal,
    seal_final,
    seal_pre_eval,
    verify,
)

RUN_ID = "run_20260518_211328_abc123"
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "schemas" / "valid"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _make_run_dir(tmp_path: Path, *, with_eval: bool = False, with_final: bool = True) -> Path:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    # run.json: copy schema-valid fixture so atomic_write_json validation works.
    (run_dir / "run.json").write_text(
        json.dumps(_load_fixture("run"), sort_keys=True), encoding="utf-8"
    )
    # events.jsonl: arbitrary bytes — only need a hashable file.
    (run_dir / "events.jsonl").write_text(
        json.dumps(_load_fixture("event"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if with_final:
        (run_dir / "final.json").write_text(
            json.dumps(_load_fixture("final"), sort_keys=True), encoding="utf-8"
        )
    if with_eval:
        (run_dir / "eval.json").write_text(
            json.dumps(_load_fixture("eval"), sort_keys=True), encoding="utf-8"
        )
    artifacts = run_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "foo.txt").write_text("foo-bytes", encoding="utf-8")
    (artifacts / "nested").mkdir()
    (artifacts / "nested" / "bar.bin").write_bytes(b"\x00\x01\x02")
    return run_dir


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return "sha256:" + h.hexdigest()


# ---- collect_files --------------------------------------------------------


def test_collect_files_includes_durable_files_excludes_manifest(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=False, with_final=False)
    # Pre-existing manifest.json must be excluded (self-reference).
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

    entries = collect_files(run_dir, include_eval=False)
    paths = [e.path for e in entries]
    assert "manifest.json" not in paths
    assert "run.json" in paths
    assert "events.jsonl" in paths
    assert "artifacts/foo.txt" in paths
    assert "artifacts/nested/bar.bin" in paths


def test_collect_files_sorted_alphabetically(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=False, with_final=False)
    entries = collect_files(run_dir, include_eval=False)
    paths = [e.path for e in entries]
    assert paths == sorted(paths)


def test_collect_files_sha256_format(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=False, with_final=False)
    entries = collect_files(run_dir, include_eval=False)
    for e in entries:
        assert SHA256_PATTERN.match(e.sha256), e.sha256


def test_collect_files_excludes_eval_when_include_eval_false(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=True, with_final=False)
    entries = collect_files(run_dir, include_eval=False)
    assert "eval.json" not in [e.path for e in entries]


def test_collect_files_includes_eval_when_include_eval_true(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=True, with_final=False)
    entries = collect_files(run_dir, include_eval=True)
    assert "eval.json" in [e.path for e in entries]


def test_collect_files_skips_missing_final(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_final=False)
    entries = collect_files(run_dir, include_eval=False)
    assert "final.json" not in [e.path for e in entries]


def test_collect_files_excludes_temp_and_lock_files(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=False, with_final=False)
    (run_dir / ".tmp_partial.json").write_text("partial", encoding="utf-8")
    (run_dir / "events.jsonl.lock").write_text("", encoding="utf-8")
    entries = collect_files(run_dir, include_eval=False)
    paths = [e.path for e in entries]
    assert not any(p.startswith(".tmp_") for p in paths)
    assert not any(p.endswith(".lock") for p in paths)


def test_collect_files_sha256_matches_disk(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=False, with_final=False)
    entries = {e.path: e.sha256 for e in collect_files(run_dir, include_eval=False)}
    assert entries["artifacts/foo.txt"] == _file_sha256(run_dir / "artifacts" / "foo.txt")


# ---- seal -----------------------------------------------------------------


def test_seal_pre_eval_writes_valid_manifest(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    seal(run_dir, "pre_eval")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "agentlens.manifest.v1"
    assert manifest["sealed"] is True
    assert manifest["sealed_phase"] == "pre_eval"
    assert manifest["run_id"] == RUN_ID
    assert "sealed_at" in manifest
    assert isinstance(manifest["files"], list)
    assert manifest["redaction"]["absolute_paths"] == "masked"
    # Manifest should validate against the v1 schema.
    validate_doc(manifest)


def test_seal_pre_eval_excludes_eval(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=True)
    seal(run_dir, "pre_eval")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = [f["path"] for f in manifest["files"]]
    assert "eval.json" not in paths


def test_seal_final_includes_eval(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=True)
    seal(run_dir, "final")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = [f["path"] for f in manifest["files"]]
    assert "eval.json" in paths
    assert manifest["sealed_phase"] == "final"


def test_seal_final_overwrites_pre_eval(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=False)
    seal(run_dir, "pre_eval")
    # Add eval.json later.
    (run_dir / "eval.json").write_text(
        json.dumps(_load_fixture("eval"), sort_keys=True), encoding="utf-8"
    )
    seal(run_dir, "final")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sealed_phase"] == "final"
    paths = [f["path"] for f in manifest["files"]]
    assert "eval.json" in paths


def test_seal_recording_incomplete_best_effort(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    # Only run.json present; everything else missing.
    (run_dir / "run.json").write_text(
        json.dumps(_load_fixture("run"), sort_keys=True), encoding="utf-8"
    )
    seal(run_dir, "recording_incomplete")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sealed_phase"] == "recording_incomplete"
    assert manifest["sealed"] is True
    validate_doc(manifest)


def test_seal_invalid_phase_raises(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    with pytest.raises(ValueError):
        seal(run_dir, "bogus")  # type: ignore[arg-type]


def test_seal_manifest_excludes_self(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    seal(run_dir, "pre_eval")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = [f["path"] for f in manifest["files"]]
    assert "manifest.json" not in paths


# ---- plan-alias wrappers --------------------------------------------------


def test_init_manifest_writes_pre_eval(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    init_manifest(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sealed_phase"] == "pre_eval"


def test_seal_pre_eval_alias(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    seal_pre_eval(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sealed_phase"] == "pre_eval"


def test_seal_final_alias(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, with_eval=True)
    seal_final(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sealed_phase"] == "final"


def test_mark_recording_incomplete_alias(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    mark_recording_incomplete(run_dir, reason="disk full")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sealed_phase"] == "recording_incomplete"
    # reason is intentionally NOT in the manifest per spec (additionalProperties: false).
    assert "recording_incomplete_reason" not in manifest


# ---- verify ---------------------------------------------------------------


def test_verify_returns_empty_when_intact(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    seal(run_dir, "pre_eval")
    mismatches = verify(run_dir)
    assert mismatches == []


def test_verify_detects_tampering(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    seal(run_dir, "pre_eval")
    # Tamper with a tracked artifact.
    (run_dir / "artifacts" / "foo.txt").write_text("MUTATED", encoding="utf-8")
    mismatches = verify(run_dir)
    assert any(m.path == "artifacts/foo.txt" for m in mismatches)


def test_manifest_entry_is_frozen() -> None:
    entry = ManifestEntry(path="x", sha256="sha256:" + "0" * 64)
    with pytest.raises(Exception):
        entry.path = "y"  # type: ignore[misc]
