#!/usr/bin/env python3
"""Contract checks for the deterministic live-migration fixture store."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


EVALS_ROOT = Path(__file__).resolve().parent
if str(EVALS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALS_ROOT))

from live_migration.contracts import EXPECTED_CASES, CaseRef  # noqa: E402
from live_migration.fixtures import (  # noqa: E402
    FixtureError,
    MaterializedFixture,
    load_case,
    materialize_fixture,
)


EXPECTED_OUTCOMES = {
    "single-file-implementation": ("write", 1, "command_and_diff"),
    "cross-package-implementation": ("write", 1, "command_and_diff"),
    "root-cause-repair": ("write", 1, "command_and_diff"),
    "defect-review": ("read_only", 1, "finding_ids"),
    "failed-test-interpretation": ("read_only", 1, "fact_ids"),
    "security-migration-block": ("read_only", 0, "block_ids"),
    "resume-state-repair": ("write", 1, "command_and_diff"),
    "large-read-only-exploration": ("read_only", 0, "fact_ids"),
}
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_fixture_error(action: object, expected: str) -> None:
    try:
        action()  # type: ignore[operator]
    except FixtureError as exc:
        require(expected in str(exc), f"expected {expected!r}, got {exc!r}")
    else:
        raise AssertionError(f"expected FixtureError containing {expected!r}")


def materialize_from_copy(source: Path, case: CaseRef, destination: Path) -> MaterializedFixture:
    eval_dir = destination.parent / f"{destination.name}-eval"
    shutil.copytree(source, eval_dir / "fixtures", symlinks=True)
    shutil.copy2(EVALS_ROOT / "live-migration" / "case-schema.json", eval_dir / "case-schema.json")
    return materialize_fixture(eval_dir, case, destination)


def main() -> int:
    eval_dir = EVALS_ROOT / "live-migration"
    fixture_root = eval_dir / "fixtures"
    schema = json.loads((eval_dir / "case-schema.json").read_text())
    require(schema["$id"] == "cpe.live-migration.case.v1", "schema id drift")
    require(set(schema["required"]) == REQUIRED_FIELDS, "case schema required fields drift")
    require(len(EXPECTED_CASES) == 8, "fixture store must contain exactly eight approved cases")
    require({path.name for path in fixture_root.iterdir() if path.is_dir()} == set(EXPECTED_OUTCOMES), "fixture slug drift")

    for case in EXPECTED_CASES:
        expected_mode, baseline_exit_code, oracle_kind = EXPECTED_OUTCOMES[case.slug]
        contract = load_case(eval_dir, case)
        require(set(contract) == REQUIRED_FIELDS, f"{case.slug}: case fields drift")
        require(contract["case_id"] == case.id, f"{case.slug}: case_id mismatch")
        require(contract["slug"] == case.slug, f"{case.slug}: slug mismatch")
        require(contract["mode"] == expected_mode, f"{case.slug}: mode mismatch")
        require(contract["baseline_exit_code"] == baseline_exit_code, f"{case.slug}: baseline exit mismatch")
        require(contract["oracle_kind"] == oracle_kind, f"{case.slug}: oracle kind mismatch")

        with tempfile.TemporaryDirectory(prefix=f"cpe-{case.slug}-") as tmp:
            fixture = materialize_fixture(eval_dir, case, Path(tmp) / "repo")
            require(isinstance(fixture, MaterializedFixture), f"{case.slug}: wrong public return type")
            require(fixture.repo.joinpath(".git").is_dir(), f"{case.slug}: Git repository missing")
            require(len(fixture.seed_commit) == 40, f"{case.slug}: seed commit must be full SHA-1")
            require(fixture.contract == contract, f"{case.slug}: materialized contract drift")
            require(len(fixture.fixture_sha256) == 64, f"{case.slug}: combined digest missing")
            require(fixture.oracle_dir == fixture_root / case.slug / "oracle", f"{case.slug}: hidden oracle path drift")
            require(fixture.oracle_dir.joinpath("expected.json").is_file(), f"{case.slug}: expected IDs missing")
            require(not fixture.repo.joinpath("oracle").exists(), f"{case.slug}: oracle copied into repository")
            require(not any(fixture.repo.rglob("expected*.json")), f"{case.slug}: expected IDs leaked")
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            baseline = subprocess.run(
                shlex.split(str(contract["baseline_command"])),
                cwd=fixture.repo,
                env=environment,
                text=True,
                capture_output=True,
            )
            require(baseline.returncode == baseline_exit_code, f"{case.slug}: nondeterministic baseline")
            status = subprocess.run(
                ["git", "status", "--short"], cwd=fixture.repo, text=True, capture_output=True, check=True
            ).stdout
            require(status == "", f"{case.slug}: baseline mutated materialized repository")

    with tempfile.TemporaryDirectory(prefix="cpe-hostile-git-config-") as tmp:
        root = Path(tmp)
        case = EXPECTED_CASES[0]
        clean = materialize_fixture(eval_dir, case, root / "clean")
        hostile_homes = {
            "signing": "[commit]\n\tgpgSign = true\n[gpg]\n\tprogram = /definitely/missing/gpg\n",
            "sha256": "[init]\n\tdefaultObjectFormat = sha256\n",
        }
        for name, config in hostile_homes.items():
            home = root / f"{name}-home"
            home.mkdir()
            home.joinpath(".gitconfig").write_text(config)
            with patch.dict(os.environ, {"HOME": str(home)}):
                isolated = materialize_fixture(eval_dir, case, root / name)
            require(len(isolated.seed_commit) == 40, f"{name}: fixture seed is not SHA-1")
            require(isolated.seed_commit == clean.seed_commit, f"{name}: host Git config changed seed commit")

        with patch.dict(
            os.environ,
            {
                "GIT_DIR": str(root / "host-git-dir"),
                "GIT_INDEX_FILE": str(root / "host-index"),
                "GIT_OBJECT_DIRECTORY": str(root / "host-objects"),
                "GIT_WORK_TREE": str(root / "host-work-tree"),
            },
        ):
            isolated = materialize_fixture(eval_dir, case, root / "repository-env")
        require(isolated.seed_commit == clean.seed_commit, "host Git repository environment changed seed commit")

    for case in EXPECTED_CASES:
        with tempfile.TemporaryDirectory(prefix=f"cpe-{case.slug}-mutation-") as tmp:
            root = Path(tmp)
            original = materialize_fixture(eval_dir, case, root / "original")
            copied = root / "copied-fixtures"
            shutil.copytree(fixture_root, copied)
            seed = next(path for path in (copied / case.slug / "repo").rglob("*") if path.is_file())
            seed.write_bytes(seed.read_bytes() + b"\n# mutated\n")
            changed_seed = materialize_from_copy(copied, case, root / "seed")
            require(
                changed_seed.fixture_sha256 != original.fixture_sha256,
                f"{case.slug}: model-visible mutation did not change digest",
            )

            shutil.rmtree(copied)
            shutil.copytree(fixture_root, copied)
            expected = copied / case.slug / "oracle" / "expected.json"
            expected.write_text(expected.read_text() + "\n")
            changed_oracle = materialize_from_copy(copied, case, root / "oracle")
            require(
                changed_oracle.fixture_sha256 != original.fixture_sha256,
                f"{case.slug}: hidden-oracle mutation did not change digest",
            )

    case = EXPECTED_CASES[0]

    for location in ("repo", "oracle"):
        with tempfile.TemporaryDirectory(prefix=f"cpe-{location}-symlink-") as tmp:
            root = Path(tmp)
            copied = root / "fixtures"
            shutil.copytree(fixture_root, copied)
            target = copied / case.slug / location / "escape"
            target.symlink_to(root / "outside")
            expect_fixture_error(
                lambda: materialize_from_copy(copied, case, root / "destination"),
                "symlink",
            )

    with tempfile.TemporaryDirectory(prefix="cpe-case-symlink-") as tmp:
        root = Path(tmp)
        copied = root / "fixtures"
        shutil.copytree(fixture_root, copied)
        case_path = copied / case.slug / "case.json"
        outside = root / "outside.json"
        outside.write_bytes(case_path.read_bytes())
        case_path.unlink()
        case_path.symlink_to(outside)
        expect_fixture_error(lambda: materialize_from_copy(copied, case, root / "destination"), "symlink")

    unsafe_commands = {
        'bash -c "curl https://example.invalid"': "unsupported executable",
        "python3 /tmp/network.py": "absolute path",
        "python3 ../outside.py": "escapes the fixture",
    }
    for unsafe_command, expected_error in unsafe_commands.items():
        with tempfile.TemporaryDirectory(prefix="cpe-command-validation-") as tmp:
            root = Path(tmp)
            copied = root / "fixtures"
            shutil.copytree(fixture_root, copied)
            case_path = copied / case.slug / "case.json"
            contract = json.loads(case_path.read_text())
            contract["baseline_command"] = unsafe_command
            case_path.write_text(json.dumps(contract, indent=2) + "\n")
            expect_fixture_error(
                lambda: materialize_from_copy(copied, case, root / "destination"),
                expected_error,
            )

    overlapping_path_policies = (
        (["test_example.py"], ["test_example.py"]),
        (["src/example.py"], ["**/*"]),
        (["src/example.py"], ["src/**"]),
        (["src/*.py"], ["src/example.py"]),
        (["src/*.py"], ["src/example.*"]),
        (["src/ab*.py"], ["src/a*a*a.py"]),
        (["abb"], ["*b/"]),
    )
    for index, (allowed_paths, forbidden_paths) in enumerate(overlapping_path_policies):
        with tempfile.TemporaryDirectory(prefix="cpe-overlapping-path-policy-") as tmp:
            root = Path(tmp)
            copied = root / "fixtures"
            shutil.copytree(fixture_root, copied)
            case_path = copied / case.slug / "case.json"
            contract = json.loads(case_path.read_text())
            contract["allowed_paths"] = allowed_paths
            contract["forbidden_paths"] = forbidden_paths
            case_path.write_text(json.dumps(contract, indent=2) + "\n")
            expect_fixture_error(
                lambda index=index: materialize_from_copy(copied, case, root / f"destination-{index}"),
                "overlapping allowed_paths and forbidden_paths",
            )

    with tempfile.TemporaryDirectory(prefix="cpe-unsupported-path-policy-") as tmp:
        root = Path(tmp)
        copied = root / "fixtures"
        shutil.copytree(fixture_root, copied)
        case_path = copied / case.slug / "case.json"
        contract = json.loads(case_path.read_text())
        contract["allowed_paths"] = ["src/[!a].py"]
        contract["forbidden_paths"] = ["src/[!b].py"]
        case_path.write_text(json.dumps(contract, indent=2) + "\n")
        expect_fixture_error(
            lambda: materialize_from_copy(copied, case, root / "destination"),
            "negated character classes are unsupported",
        )

    with tempfile.TemporaryDirectory(prefix="cpe-character-class-path-policy-") as tmp:
        root = Path(tmp)
        copied = root / "fixtures"
        shutil.copytree(fixture_root, copied)
        case_path = copied / case.slug / "case.json"
        contract = json.loads(case_path.read_text())
        contract["allowed_paths"] = ["src/[ac].py"]
        contract["forbidden_paths"] = ["src/[bc].py"]
        case_path.write_text(json.dumps(contract, indent=2) + "\n")
        expect_fixture_error(
            lambda: materialize_from_copy(copied, case, root / "destination"),
            "character classes are unsupported",
        )

    with tempfile.TemporaryDirectory(prefix="cpe-question-mark-path-policy-") as tmp:
        root = Path(tmp)
        copied = root / "fixtures"
        shutil.copytree(fixture_root, copied)
        case_path = copied / case.slug / "case.json"
        contract = json.loads(case_path.read_text())
        contract["allowed_paths"] = ["src/a?c.py"]
        contract["forbidden_paths"] = ["src/ab?.py"]
        case_path.write_text(json.dumps(contract, indent=2) + "\n")
        expect_fixture_error(
            lambda: materialize_from_copy(copied, case, root / "destination"),
            "question-mark globs are unsupported",
        )

    with tempfile.TemporaryDirectory(prefix="cpe-disjoint-path-policy-") as tmp:
        root = Path(tmp)
        copied = root / "fixtures"
        shutil.copytree(fixture_root, copied)
        case_path = copied / case.slug / "case.json"
        contract = json.loads(case_path.read_text())
        contract["allowed_paths"] = ["src/*.py"]
        contract["forbidden_paths"] = ["src/*.js"]
        case_path.write_text(json.dumps(contract, indent=2) + "\n")
        materialize_from_copy(copied, case, root / "destination")

    print("live matrix fixture checks passed (8 deterministic repositories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
