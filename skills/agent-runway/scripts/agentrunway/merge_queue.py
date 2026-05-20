from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from .git_ops import Git


@dataclass(frozen=True)
class MergeCandidate:
    task_id: str
    worker_id: str
    commits: tuple[str, ...]
    changed_files: tuple[str, ...]


def validate_candidate_scope(candidate: MergeCandidate, allowed_globs: tuple[str, ...]) -> None:
    for path in candidate.changed_files:
        if not any(fnmatch.fnmatch(path, pattern) for pattern in allowed_globs):
            raise ValueError(f"{path} is outside allowed write scope")


def apply_candidate(git: Git, candidate: MergeCandidate) -> None:
    for commit in candidate.commits:
        git.run("cherry-pick", commit)
