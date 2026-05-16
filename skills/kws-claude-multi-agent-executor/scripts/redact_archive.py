"""Redact a forensics tar archive in place.

Extract → redact each file → re-tar → atomic replace. Used by the multi-agent
executor's forensics pipeline to strip user-identifying paths and obvious
secrets before archives are shared.

Replacement order (matches spec §F1.5):
  1. os.environ['HOME']                  → <HOME>
  2. ^/Users/<name>/ (regex)              → <HOME>/
  3. meta['worktree_path'] (absolute)     → <WORKTREE>
  4. meta['repo_root']     (absolute)     → <REPO>

For *.jsonl files (stream-json), each line is additionally JSON-parsed and
sensitive keys (cwd, env at top level or under tool_use.input, plus any key
matching api_key/token/password/secret/credential) get value <REDACTED>.
Unparseable lines pass through unchanged. Binary files (null byte in first
8 KB) are skipped entirely.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

SENSITIVE_KEY_RE = re.compile(r"(?i)(api_key|token|password|secret|credential)")
USERS_PATH_RE = re.compile(r"/Users/[^/]+/")
JSONL_SUFFIX = ".jsonl"
BINARY_PROBE_BYTES = 8 * 1024


def _is_binary(path: Path) -> bool:
    """Return True if first 8 KB of file contains a NUL byte."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(BINARY_PROBE_BYTES)
        return b"\x00" in chunk
    except OSError:
        return True  # unreadable -> treat as binary, skip


def _apply_text_replacements(text: str, meta: dict) -> tuple[str, int]:
    """Apply the four ordered string replacements; return (new_text, count)."""
    count = 0

    home = os.environ.get("HOME", "")
    if home:
        n = text.count(home)
        if n:
            text = text.replace(home, "<HOME>")
            count += n

    # /Users/<name>/ regex
    def _users_sub(_match: re.Match) -> str:
        return "<HOME>/"

    new_text, n = USERS_PATH_RE.subn(_users_sub, text)
    count += n
    text = new_text

    wt = meta.get("worktree_path")
    if wt:
        n = text.count(wt)
        if n:
            text = text.replace(wt, "<WORKTREE>")
            count += n

    repo = meta.get("repo_root")
    if repo:
        n = text.count(repo)
        if n:
            text = text.replace(repo, "<REPO>")
            count += n

    return text, count


def _redact_obj(obj: Any, replacements: list[int]) -> Any:
    """Recursively redact a parsed JSON object in place. Returns redacted obj."""
    if isinstance(obj, dict):
        new = {}
        for k, v in obj.items():
            if k in ("cwd", "env"):
                if v != "<REDACTED>":
                    replacements[0] += 1
                new[k] = "<REDACTED>"
            elif isinstance(v, str) and SENSITIVE_KEY_RE.search(k):
                if v != "<REDACTED>":
                    replacements[0] += 1
                new[k] = "<REDACTED>"
            else:
                new[k] = _redact_obj(v, replacements)
        return new
    if isinstance(obj, list):
        return [_redact_obj(x, replacements) for x in obj]
    return obj


def _redact_jsonl_line(line: str) -> tuple[str, int]:
    """Redact a single JSONL line. Pass through if not valid JSON. Returns (line, count)."""
    stripped = line.rstrip("\n")
    if not stripped.strip():
        return line, 0
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return line, 0
    counter = [0]
    redacted = _redact_obj(obj, counter)
    suffix = "\n" if line.endswith("\n") else ""
    return json.dumps(redacted) + suffix, counter[0]


def _process_file(path: Path, meta: dict, errors: list) -> int:
    """Redact a single file in place. Returns substitution count."""
    if _is_binary(path):
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as e:
        errors.append(f"{path}: {e!r}")
        return 0

    total = 0
    if path.suffix == JSONL_SUFFIX:
        new_lines = []
        for line in text.splitlines(keepends=True):
            new_line, n = _redact_jsonl_line(line)
            total += n
            new_lines.append(new_line)
        text = "".join(new_lines)

    text, n = _apply_text_replacements(text, meta)
    total += n

    try:
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        errors.append(f"{path}: {e!r}")
    return total


def redact_archive(tar_path: Path, meta: dict) -> dict:
    """Extract → redact → re-tar atomically.

    Args:
        tar_path: Path to a .tar.gz to redact in place.
        meta: Forensics metadata dict; recognised keys are 'worktree_path' and
              optional 'repo_root'.

    Returns:
        {'replacements': int, 'errors': list[str]}
    """
    tar_path = Path(tar_path)
    errors: list[str] = []

    if not tar_path.exists():
        raise FileNotFoundError(str(tar_path))

    total = 0
    with tempfile.TemporaryDirectory(prefix="redact-extract-") as extract_dir_s:
        extract_dir = Path(extract_dir_s)
        try:
            with tarfile.open(tar_path, "r:*") as tf:
                tf.extractall(extract_dir)
        except (tarfile.TarError, OSError) as e:
            raise RuntimeError(f"Failed to extract {tar_path}: {e!r}") from e

        for root, _, files in os.walk(extract_dir):
            for fn in files:
                full = Path(root) / fn
                if not full.is_file() or full.is_symlink():
                    continue
                total += _process_file(full, meta, errors)

        # Re-tar to a sibling tempfile, then atomic replace.
        tmp_fd, tmp_out_s = tempfile.mkstemp(
            prefix=tar_path.name + ".",
            suffix=".tmp",
            dir=str(tar_path.parent),
        )
        os.close(tmp_fd)
        tmp_out = Path(tmp_out_s)
        try:
            with tarfile.open(tmp_out, "w:gz") as tf:
                # Add each top-level entry under extract_dir to preserve original
                # archive layout.
                for entry in sorted(extract_dir.iterdir()):
                    tf.add(str(entry), arcname=entry.name)
            os.replace(tmp_out, tar_path)
        except Exception:
            if tmp_out.exists():
                try:
                    tmp_out.unlink()
                except OSError:
                    pass
            raise

    return {"replacements": total, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redact a forensics tar archive in place.")
    parser.add_argument("tar_path", help="Path to .tar.gz")
    parser.add_argument(
        "--meta",
        default="{}",
        help="JSON dict with optional keys: worktree_path, repo_root",
    )
    args = parser.parse_args(argv)

    try:
        meta = json.loads(args.meta)
        if not isinstance(meta, dict):
            print(f"--meta must be a JSON object, got {type(meta).__name__}", file=sys.stderr)
            return 2
    except json.JSONDecodeError as e:
        print(f"Invalid --meta JSON: {e}", file=sys.stderr)
        return 2

    try:
        result = redact_archive(Path(args.tar_path), meta)
    except FileNotFoundError as e:
        print(f"File not found: {e}", file=sys.stderr)
        return 1
    except (RuntimeError, OSError, tarfile.TarError) as e:
        print(f"Hard error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
