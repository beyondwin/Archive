"""Deterministic, offline fixture repositories for the live migration matrix."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import CaseRef, canonical_json


class FixtureError(ValueError):
    """Raised when a fixture contract or its bound content is invalid."""


@dataclass(frozen=True)
class MaterializedFixture:
    repo: Path
    oracle_dir: Path
    contract: dict[str, object]
    seed_commit: str
    fixture_sha256: str


REQUIRED_FIELDS = {
    "schema_version",
    "case_id",
    "slug",
    "mode",
    "task",
    "allowed_paths",
    "forbidden_paths",
    "baseline_command",
    "baseline_exit_code",
    "acceptance_command",
    "oracle_kind",
    "expected_policy",
}
ALLOWED_MODES = {"write", "read_only"}
ALLOWED_ORACLE_KINDS = {"command_and_diff", "finding_ids", "fact_ids", "block_ids"}
ALLOWED_POLICIES = {"core_only", "block"}
ALLOWED_PYTHON_MODULES = {"unittest"}
GIT_CONFIG_ENVIRONMENT_KEYS = {
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_SYSTEM",
}
GIT_REPOSITORY_ENVIRONMENT_KEYS = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
}


def _reject_symlinks(root: Path, label: str) -> None:
    if root.is_symlink():
        raise FixtureError(f"{label} must not be a symlink")
    if not root.exists():
        raise FixtureError(f"{label} missing: {root}")
    if root.is_file():
        return
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            path = current_path / name
            if path.is_symlink():
                raise FixtureError(f"{label} contains symlink: {path.relative_to(root)}")


def _tree_files(root: Path) -> tuple[Path, ...]:
    _reject_symlinks(root, root.name)
    files = tuple(sorted(path for path in root.rglob("*") if path.is_file()))
    if not files:
        raise FixtureError(f"empty fixture tree: {root}")
    return files


def _update_digest(digest: Any, label: str, relative: str, content: bytes) -> None:
    for value in (label.encode(), relative.encode(), content):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)


def _fixture_digest(case_path: Path, repo_dir: Path, oracle_dir: Path) -> str:
    digest = hashlib.sha256()
    _update_digest(digest, "contract", "case.json", case_path.read_bytes())
    for label, root in (("repo", repo_dir), ("oracle", oracle_dir)):
        for path in _tree_files(root):
            _update_digest(digest, label, path.relative_to(root).as_posix(), path.read_bytes())
    return digest.hexdigest()


def _validate_schema(schema_path: Path) -> None:
    _reject_symlinks(schema_path, "case schema")
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureError(f"invalid case schema: {exc}") from exc
    if schema.get("$id") != "cpe.live-migration.case.v1" or set(schema.get("required", [])) != REQUIRED_FIELDS:
        raise FixtureError("case schema does not match the v1 fixture contract")


def _validate_path_list(slug: str, field: str, value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise FixtureError(f"{slug}: {field} must contain paths")
    if len(value) != len(set(value)):
        raise FixtureError(f"{slug}: duplicate {field}")
    for item in value:
        path = Path(item)
        if path.is_absolute() or ".." in path.parts:
            raise FixtureError(f"{slug}: {field} escapes the fixture")
        if "?" in item:
            raise FixtureError(f"{slug}: {field} question-mark globs are unsupported")
        negated_class = item.find("[!")
        if negated_class != -1 and item.find("]", negated_class + 2) != -1:
            raise FixtureError(f"{slug}: {field} negated character classes are unsupported")
        character_class = item.find("[")
        if character_class != -1 and item.find("]", character_class + 1) != -1:
            raise FixtureError(f"{slug}: {field} character classes are unsupported")


def _glob_tokens(pattern: str) -> tuple[str, ...]:
    """Collapse each wildcard run into one language-level star token."""

    tokens: list[str] = []
    for character in pattern:
        if character == "*" and tokens and tokens[-1] == "*":
            continue
        tokens.append(character)
    return tuple(tokens)


def _glob_languages_overlap(left: str, right: str) -> bool:
    """Decide whether two supported glob languages can share a path.

    Stars conservatively include path separators. This covers both ordinary
    segment stars and the recursive ``/**`` policy extension without allowing
    a false-negative overlap; a conservative false positive fails closed.
    """

    left_tokens = _glob_tokens(left)
    right_tokens = _glob_tokens(right)
    pending = [(0, 0)]
    visited: set[tuple[int, int]] = set()

    while pending:
        left_index, right_index = pending.pop()
        state = (left_index, right_index)
        if state in visited:
            continue
        visited.add(state)

        if left_index == len(left_tokens) and right_index == len(right_tokens):
            return True

        left_token = left_tokens[left_index] if left_index < len(left_tokens) else None
        right_token = right_tokens[right_index] if right_index < len(right_tokens) else None

        if left_token == "*":
            pending.append((left_index + 1, right_index))
        if right_token == "*":
            pending.append((left_index, right_index + 1))

        if left_token == "*" and right_token not in (None, "*"):
            pending.append((left_index, right_index + 1))
        elif right_token == "*" and left_token not in (None, "*"):
            pending.append((left_index + 1, right_index))
        elif left_token is not None and left_token == right_token:
            pending.append((left_index + 1, right_index + 1))

    return False


def _policy_glob_languages(pattern: str) -> tuple[str, ...]:
    """Return conservative languages for PurePath matching and ``/**`` roots."""

    normalized = PurePosixPath(pattern).as_posix()
    languages = [normalized, f"*/{normalized}"]
    if normalized.endswith("/**"):
        root = normalized[:-3].rstrip("/")
        if root:
            languages.extend((root, f"*/{root}"))
    return tuple(languages)


def _path_policies_overlap(allowed_paths: list[str], forbidden_paths: list[str]) -> bool:
    for allowed in allowed_paths:
        for forbidden in forbidden_paths:
            for allowed_language in _policy_glob_languages(allowed):
                for forbidden_language in _policy_glob_languages(forbidden):
                    if _glob_languages_overlap(allowed_language, forbidden_language):
                        return True
    return False


def _validate_command(slug: str, field: str, value: Any, repo_dir: Path) -> None:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{slug}: {field} must be a non-empty string")
    try:
        words = shlex.split(value)
    except ValueError as exc:
        raise FixtureError(f"{slug}: invalid {field}: {exc}") from exc
    if not words or words[0] != "python3":
        raise FixtureError(f"{slug}: {field} uses an unsupported executable")
    if len(words) == 3 and words[1] == "-m":
        if words[2] not in ALLOWED_PYTHON_MODULES:
            raise FixtureError(f"{slug}: {field} uses an unsupported Python module")
        return
    if len(words) != 2:
        raise FixtureError(f"{slug}: {field} does not match the fixture command grammar")
    script = Path(words[1])
    if script.is_absolute():
        raise FixtureError(f"{slug}: {field} contains an absolute path")
    if ".." in script.parts:
        raise FixtureError(f"{slug}: {field} escapes the fixture")
    if script.suffix != ".py":
        raise FixtureError(f"{slug}: {field} must target a Python script")
    resolved_repo = repo_dir.resolve()
    resolved_script = (resolved_repo / script).resolve()
    if not resolved_script.is_relative_to(resolved_repo) or not resolved_script.is_file():
        raise FixtureError(f"{slug}: {field} script target is not fixture-local")


def _validate_contract(raw: Any, case: CaseRef, repo_dir: Path) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != REQUIRED_FIELDS:
        raise FixtureError(f"{case.slug}: case fields do not match schema")
    if raw["schema_version"] != "1":
        raise FixtureError(f"{case.slug}: unsupported schema_version")
    if raw["case_id"] != case.id or raw["slug"] != case.slug:
        raise FixtureError(f"{case.slug}: CaseRef does not match case contract")
    if raw["mode"] not in ALLOWED_MODES:
        raise FixtureError(f"{case.slug}: invalid mode")
    if raw["oracle_kind"] not in ALLOWED_ORACLE_KINDS:
        raise FixtureError(f"{case.slug}: invalid oracle_kind")
    if raw["expected_policy"] not in ALLOWED_POLICIES:
        raise FixtureError(f"{case.slug}: invalid expected_policy")
    if not isinstance(raw["task"], str) or not raw["task"].strip():
        raise FixtureError(f"{case.slug}: task must be a non-empty string")
    _validate_path_list(case.slug, "allowed_paths", raw["allowed_paths"])
    _validate_path_list(case.slug, "forbidden_paths", raw["forbidden_paths"])
    if _path_policies_overlap(raw["allowed_paths"], raw["forbidden_paths"]):
        raise FixtureError(f"{case.slug}: overlapping allowed_paths and forbidden_paths")
    _validate_command(case.slug, "baseline_command", raw["baseline_command"], repo_dir)
    _validate_command(case.slug, "acceptance_command", raw["acceptance_command"], repo_dir)
    if type(raw["baseline_exit_code"]) is not int or raw["baseline_exit_code"] < 0:
        raise FixtureError(f"{case.slug}: baseline_exit_code must be a non-negative integer")
    return dict(raw)


def load_case(eval_dir: Path, case: CaseRef) -> dict[str, object]:
    """Load and validate one exact CaseRef contract."""

    eval_dir = eval_dir.resolve()
    _validate_schema(eval_dir / "case-schema.json")
    case_dir = eval_dir / "fixtures" / case.slug
    case_path = case_dir / "case.json"
    _reject_symlinks(case_path, f"{case.slug} case.json")
    _reject_symlinks(case_dir / "repo", f"{case.slug} repository")
    oracle_dir = case_dir / "oracle"
    _reject_symlinks(oracle_dir, f"{case.slug} oracle")
    if not oracle_dir.joinpath("expected.json").is_file():
        raise FixtureError(f"{case.slug}: oracle expected.json missing")
    try:
        raw: Any = json.loads(case_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureError(f"{case.slug}: invalid case.json: {exc}") from exc
    return _validate_contract(raw, case, case_dir / "repo")


def materialize_fixture(eval_dir: Path, case: CaseRef, destination: Path) -> MaterializedFixture:
    """Copy only model-visible bytes, seed Git, verify baseline, and bind all fixture bytes."""

    eval_dir = eval_dir.resolve()
    contract = load_case(eval_dir, case)
    case_dir = eval_dir / "fixtures" / case.slug
    case_path = case_dir / "case.json"
    repo_source = case_dir / "repo"
    oracle_dir = case_dir / "oracle"
    fixture_sha256 = _fixture_digest(case_path, repo_source, oracle_dir)
    destination = destination.resolve()
    if destination.exists():
        raise FixtureError(f"destination already exists: {destination}")
    shutil.copytree(repo_source, destination)
    environment = os.environ.copy()
    for key in tuple(environment):
        if (
            key in GIT_CONFIG_ENVIRONMENT_KEYS
            or key in GIT_REPOSITORY_ENVIRONMENT_KEYS
            or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
        ):
            environment.pop(key)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "CPE Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "CPE Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    try:
        for command in (
            ["git", "init", "--quiet", "--initial-branch=main", "--object-format=sha1", "--template="],
            ["git", "-c", f"core.hooksPath={os.devnull}", "add", "--all"],
            [
                "git",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "--quiet",
                "-m",
                f"fixture: {case.slug}",
            ],
        ):
            subprocess.run(command, cwd=destination, env=environment, check=True, capture_output=True, text=True)
        seed_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=destination, env=environment, check=True, capture_output=True, text=True
        ).stdout.strip()
        baseline = subprocess.run(
            shlex.split(str(contract["baseline_command"])),
            cwd=destination,
            env=environment,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FixtureError(f"{case.slug}: failed to materialize Git repository: {exc}") from exc
    if baseline.returncode != contract["baseline_exit_code"]:
        raise FixtureError(
            f"{case.slug}: baseline exit code mismatch: expected {contract['baseline_exit_code']}, got {baseline.returncode}"
        )
    status = subprocess.run(
        ["git", "status", "--short"], cwd=destination, env=environment, check=True, capture_output=True, text=True
    ).stdout
    if status:
        raise FixtureError(f"{case.slug}: baseline command mutated the fixture")
    return MaterializedFixture(
        repo=destination,
        oracle_dir=oracle_dir,
        contract=contract,
        seed_commit=seed_commit,
        fixture_sha256=fixture_sha256,
    )
