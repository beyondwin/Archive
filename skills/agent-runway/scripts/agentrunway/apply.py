from __future__ import annotations

from pathlib import Path

from .git_ops import Git, assert_clean_source


class ApplyError(RuntimeError):
    pass


def apply_commits_to_source(
    repo: Path,
    commits: tuple[str, ...],
    *,
    strategy: str = "cherry-pick",
    already_applied: tuple[str, ...] = (),
) -> list[str]:
    try:
        assert_clean_source(repo)
    except Exception as exc:
        raise ApplyError(str(exc)) from exc
    if strategy != "cherry-pick":
        raise ApplyError(f"unsupported apply strategy: {strategy}")

    git = Git(repo)
    applied: list[str] = []
    skip = set(already_applied)
    for commit in commits:
        if commit in skip:
            continue
        result = git.run("cherry-pick", commit, check=False)
        if result.returncode != 0:
            git.run("cherry-pick", "--abort", check=False)
            raise ApplyError(result.stderr.strip() or result.stdout.strip() or "apply conflict")
        applied.append(commit)
    return applied
