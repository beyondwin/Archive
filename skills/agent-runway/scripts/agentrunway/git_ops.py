from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


class DirtySourceError(GitError):
    pass


class Git:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(["git", *args], cwd=self.root, text=True, capture_output=True)
        if check and result.returncode != 0:
            raise GitError(result.stderr.strip() or result.stdout.strip())
        return result

    def rev_parse(self, ref: str) -> str:
        return self.run("rev-parse", ref).stdout.strip()

    def common_dir(self) -> Path:
        raw = self.run("rev-parse", "--git-common-dir").stdout.strip()
        path = Path(raw)
        return (self.root / path).resolve() if not path.is_absolute() else path.resolve()


def dirty_files(repo: Path) -> list[str]:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo, text=True, capture_output=True, check=True)
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        files.append(line[3:] if len(line) > 3 else line)
    return files


def assert_clean_source(repo: Path, allow_dirty: bool = False, ignored: set[str] | None = None) -> list[str]:
    ignored = ignored or set()
    dirty = [path for path in dirty_files(repo) if path not in ignored]
    if dirty and not allow_dirty:
        raise DirtySourceError("dirty source checkout: " + ", ".join(dirty))
    return dirty
