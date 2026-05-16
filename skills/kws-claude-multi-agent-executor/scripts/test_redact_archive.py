"""Tests for redact_archive module — TDD red/green checks."""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redact_archive import redact_archive  # noqa: E402


def _make_tar(tmp: Path, files: dict) -> Path:
    """Build a tar.gz from a {relpath: bytes_or_str} dict and return its path."""
    src = tmp / "src"
    src.mkdir(parents=True, exist_ok=True)
    for relpath, content in files.items():
        f = src / relpath
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            f.write_bytes(content)
        else:
            f.write_text(content)
    tar_path = tmp / "archive.tar.gz"
    with tarfile.open(tar_path, "w:gz") as t:
        t.add(src, arcname="src")
    return tar_path


def _extract(tar_path: Path, dest: Path) -> dict:
    """Extract tar and return {relpath: bytes}."""
    with tarfile.open(tar_path, "r:gz") as t:
        t.extractall(dest)
    out = {}
    for root, _, files in os.walk(dest):
        for fn in files:
            full = Path(root) / fn
            out[str(full.relative_to(dest))] = full.read_bytes()
    return out


def test_home_path_redacted_in_text_file():
    home = os.environ["HOME"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        tar = _make_tar(tmp, {"a.txt": f"path: {home}/foo\n"})
        result = redact_archive(tar, {"worktree_path": "/tmp/nope"})
        assert result["replacements"] >= 1
        extracted = _extract(tar, tmp / "out")
        content = extracted["src/a.txt"].decode()
        assert "<HOME>/foo" in content
        assert home not in content


def test_jsonl_cwd_redacted():
    home = os.environ["HOME"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        line = json.dumps({"type": "text", "cwd": f"{home}/repo", "text": "hi"})
        tar = _make_tar(tmp, {"headless.jsonl": line + "\n"})
        result = redact_archive(tar, {"worktree_path": "/tmp/nope"})
        assert result["replacements"] >= 1
        extracted = _extract(tar, tmp / "out")
        content = extracted["src/headless.jsonl"].decode()
        obj = json.loads(content.strip())
        assert obj["cwd"] == "<REDACTED>"


def test_binary_file_not_modified():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        home = os.environ["HOME"]
        # First 8KB contains a null byte; also contains $HOME path
        binary = b"\x00\x01\x02" + home.encode() + b"/foo" + b"\x00" * 100
        tar = _make_tar(tmp, {"bin.dat": binary})
        redact_archive(tar, {"worktree_path": "/tmp/nope"})
        extracted = _extract(tar, tmp / "out")
        assert extracted["src/bin.dat"] == binary  # unmodified


def test_invalid_json_line_passed_through():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        invalid = "this is not json at all { broken\n"
        tar = _make_tar(tmp, {"headless.jsonl": invalid})
        redact_archive(tar, {"worktree_path": "/tmp/nope"})
        extracted = _extract(tar, tmp / "out")
        # Pass-through unchanged
        assert extracted["src/headless.jsonl"].decode() == invalid


def test_api_key_in_nested_dict_redacted():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        obj = {
            "type": "tool_use",
            "tool_use": {
                "input": {
                    "api_key": "sk-secret-123",
                    "other": "ok",
                }
            },
        }
        line = json.dumps(obj)
        tar = _make_tar(tmp, {"headless.jsonl": line + "\n"})
        result = redact_archive(tar, {"worktree_path": "/tmp/nope"})
        assert result["replacements"] >= 1
        extracted = _extract(tar, tmp / "out")
        out = json.loads(extracted["src/headless.jsonl"].decode().strip())
        assert out["tool_use"]["input"]["api_key"] == "<REDACTED>"
        assert out["tool_use"]["input"]["other"] == "ok"


def test_users_path_regex_redacted():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # /Users/somebody/ pattern not equal to current $HOME
        content = "ref: /Users/otheruser/project/file.txt\n"
        tar = _make_tar(tmp, {"b.txt": content})
        result = redact_archive(tar, {"worktree_path": "/tmp/nope"})
        assert result["replacements"] >= 1
        extracted = _extract(tar, tmp / "out")
        out = extracted["src/b.txt"].decode()
        assert "<HOME>/project/file.txt" in out
        assert "/Users/otheruser/" not in out


def test_worktree_path_redacted():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wt = "/Volumes/work/wt-foo"
        content = f"wt: {wt}/scripts/run.py\n"
        tar = _make_tar(tmp, {"c.txt": content})
        result = redact_archive(tar, {"worktree_path": wt})
        assert result["replacements"] >= 1
        extracted = _extract(tar, tmp / "out")
        out = extracted["src/c.txt"].decode()
        assert "<WORKTREE>" in out
        assert wt not in out


def test_repo_root_redacted():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo = "/srv/repos/myrepo"
        content = f"repo: {repo}/src/x.py\n"
        tar = _make_tar(tmp, {"d.txt": content})
        result = redact_archive(tar, {"worktree_path": "/tmp/nope", "repo_root": repo})
        assert result["replacements"] >= 1
        extracted = _extract(tar, tmp / "out")
        out = extracted["src/d.txt"].decode()
        assert "<REPO>" in out
        assert repo not in out


def test_returns_dict_with_replacements_and_errors():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        tar = _make_tar(tmp, {"e.txt": "no matches here\n"})
        result = redact_archive(tar, {"worktree_path": "/tmp/nope"})
        assert isinstance(result, dict)
        assert "replacements" in result
        assert "errors" in result
        assert isinstance(result["replacements"], int)
        assert isinstance(result["errors"], list)


def test_cli_smoke():
    """CLI invocation should rewrite tar in place and exit 0."""
    home = os.environ["HOME"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        tar = _make_tar(tmp, {"a.txt": f"path: {home}/foo\n"})
        script = Path(__file__).parent / "redact_archive.py"
        proc = subprocess.run(
            [sys.executable, str(script), str(tar)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        extracted = _extract(tar, tmp / "out")
        # File could be either at src/a.txt or a.txt depending on tar structure
        keys = list(extracted.keys())
        assert any("a.txt" in k for k in keys)
        content = next(v for k, v in extracted.items() if "a.txt" in k).decode()
        assert "<HOME>/foo" in content
