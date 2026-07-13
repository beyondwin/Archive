#!/usr/bin/env python3
"""Deterministic checks for vNext single- and multi-plan document sets."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cpe import build_parser  # noqa: E402
from cpe_runtime.document_set import (  # noqa: E402
    DocumentSetBlocked,
    compile_document_set,
)
from cpe_runtime.plan_compiler import compile_run  # noqa: E402


def _write(path: Path, title: str, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"# {title}\n\n{body}\n".encode("utf-8"))
    return path


def _expect_blocked(category: str, operation) -> bool:
    try:
        operation()
    except DocumentSetBlocked as exc:
        return exc.category == category and bool(exc.evidence)
    return False


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    repeated = build_parser().parse_args(
        [
            "run",
            "--spec",
            "spec.md",
            "--plan",
            "a.md",
            "--plan",
            "b.md",
            "--program-plan",
            "program.md",
            "--workspace",
            ".",
        ]
    )
    checks["cli_repeats_plans"] = repeated.plan == ["a.md", "b.md"]
    checks["cli_accepts_program_plan"] = repeated.program_plan == "program.md"
    single = build_parser().parse_args(
        ["run", "--spec", "spec.md", "--plan", "only.md", "--workspace", "."]
    )
    checks["cli_preserves_single_plan"] = single.plan == ["only.md"]
    checks["cli_program_plan_is_optional"] = single.program_plan is None

    signature = inspect.signature(compile_run)
    plans_parameter = signature.parameters.get("plans")
    checks["compiler_uses_tuple_interface"] = (
        plans_parameter is not None
        and plans_parameter.kind is inspect.Parameter.KEYWORD_ONLY
        and plans_parameter.default is inspect.Parameter.empty
        and "program_plan" in signature.parameters
        and "plan" not in signature.parameters
        and all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
    )

    with tempfile.TemporaryDirectory(prefix="cpe-document-set-") as temp:
        root = Path(temp)
        (root / ".git").mkdir()
        spec = _write(root / "spec.md", "Quality Spec", "spec body")
        program = _write(root / "program.md", "Delivery Program", "program body")
        plan_a = _write(root / "waves" / "a.md", "Wave Alpha", "alpha body")
        plan_b = _write(root / "waves" / "b.md", "Wave Beta", "beta body")
        doc = _write(root / "references" / "guide.md", "Operator Guide", "guide body")

        compiled = compile_document_set(spec, (plan_a, plan_b), program, (doc,))
        checks["document_order_is_canonical"] = [item.kind for item in compiled.documents] == [
            "spec",
            "program",
            "plan",
            "plan",
            "doc",
        ]
        checks["documents_are_immutable_tuple"] = isinstance(compiled.documents, tuple)
        try:
            compiled.documents[0].sha256 = "mutated"  # type: ignore[misc]
        except FrozenInstanceError:
            checks["input_document_is_frozen"] = True
        else:
            checks["input_document_is_frozen"] = False

        checks["stored_paths_are_workspace_relative"] = all(
            not item.path.is_absolute() for item in compiled.documents
        )
        checks["bytes_and_hash_are_exact"] = all(
            item.content == (compiled.source_root / item.path).resolve().read_bytes()
            and item.sha256 == hashlib.sha256(item.content).hexdigest()
            for item in compiled.documents
        )
        checks["document_ids_are_unique"] = len(
            {item.document_id for item in compiled.documents}
        ) == len(compiled.documents)
        checks["document_set_hash_is_stable"] = (
            compiled.sha256 == compile_document_set(spec, (plan_a, plan_b), program, (doc,)).sha256
        )
        plan_a_identity = next(
            item.document_id for item in compiled.documents if item.path == Path("waves/a.md")
        )
        reduced = compile_document_set(spec, (plan_a,), None, ())
        checks["identity_is_stable_when_inputs_change"] = plan_a_identity == next(
            item.document_id for item in reduced.documents if item.path == Path("waves/a.md")
        )

        without_program = compile_document_set(spec, (plan_a, plan_b), None, ())
        checks["no_program_fallback_preserves_plan_order"] = [
            item.path.name for item in without_program.documents
        ] == ["spec.md", "a.md", "b.md"]
        reordered = compile_document_set(spec, (plan_b, plan_a), None, ())
        checks["reordered_plans_change_only_order"] = (
            [item.document_id for item in reordered.documents[1:]]
            == [item.document_id for item in reversed(without_program.documents[1:])]
            and reordered.sha256 != without_program.sha256
        )

        normalized = root / "waves" / "nested" / ".." / "a.md"
        normalized_set = compile_document_set(spec, (normalized,), None, ())
        checks["paths_are_normalized"] = normalized_set.documents[1].path == Path("waves/a.md")

        relocated_sets = []
        relocated_workspace_sets = []
        for checkout_name in ("checkout-a", "checkout-b"):
            checkout = root / checkout_name
            (checkout / ".git").mkdir(parents=True)
            relocated_spec = _write(checkout / "specs" / "quality.md", "Quality Spec", "spec body")
            relocated_program = _write(
                checkout / "programs" / "delivery.md", "Delivery Program", "program body"
            )
            relocated_plan_a = _write(
                checkout / "plans" / "a.md", "Wave Alpha", "alpha body"
            )
            relocated_plan_b = _write(
                checkout / "plans" / "b.md", "Wave Beta", "beta body"
            )
            relocated_doc = _write(
                checkout / "references" / "guide.md", "Operator Guide", "guide body"
            )
            arguments = (
                relocated_spec,
                (relocated_plan_a, relocated_plan_b),
                relocated_program,
                (relocated_doc,),
            )
            relocated_sets.append(compile_document_set(*arguments))
            relocated_workspace_sets.append(compile_document_set(*arguments, workspace=checkout))

        checks["relocated_default_ids_are_stable"] = (
            [item.document_id for item in relocated_sets[0].documents]
            == [item.document_id for item in relocated_sets[1].documents]
            and relocated_sets[0].sha256 == relocated_sets[1].sha256
        )
        checks["relocated_workspace_ids_are_stable"] = (
            [item.document_id for item in relocated_workspace_sets[0].documents]
            == [item.document_id for item in relocated_workspace_sets[1].documents]
            and relocated_workspace_sets[0].sha256 == relocated_workspace_sets[1].sha256
        )
        checks["relocated_paths_are_canonical_relative"] = [
            item.path.as_posix() for item in relocated_workspace_sets[0].documents
        ] == [
            "specs/quality.md",
            "programs/delivery.md",
            "plans/a.md",
            "plans/b.md",
            "references/guide.md",
        ]
        checks["relocated_reads_stay_bound_to_source_root"] = all(
            item.content
            == (document_set.source_root / item.path).resolve(strict=True).read_bytes()
            for document_set in relocated_workspace_sets
            for item in document_set.documents
        )

        checks["empty_plan_set_blocks"] = _expect_blocked(
            "plans_missing", lambda: compile_document_set(spec, (), None, ())
        )
        checks["duplicate_path_blocks"] = _expect_blocked(
            "duplicate_path", lambda: compile_document_set(spec, (plan_a, plan_a), None, ())
        )

        same_title = _write(root / "waves" / "same-title.md", "Wave Alpha", "different body")
        checks["duplicate_identity_blocks"] = _expect_blocked(
            "duplicate_identity",
            lambda: compile_document_set(spec, (plan_a, same_title), None, ()),
        )

        copied = root / "references" / "copied-plan.md"
        copied.write_bytes(plan_a.read_bytes())
        checks["duplicate_content_blocks"] = _expect_blocked(
            "duplicate_content",
            lambda: compile_document_set(spec, (plan_a,), None, (copied,)),
        )

        directory = root / "directory.md"
        directory.mkdir()
        checks["non_file_blocks"] = _expect_blocked(
            "source_not_file", lambda: compile_document_set(spec, (directory,), None, ())
        )

        symlink = root / "linked-plan.md"
        symlink.symlink_to(plan_a)
        checks["symlink_blocks"] = _expect_blocked(
            "source_symlink", lambda: compile_document_set(spec, (symlink,), None, ())
        )

        unreadable = _write(root / "unreadable.md", "Unreadable Plan", "secret")
        unreadable.chmod(0)
        try:
            checks["unreadable_blocks"] = _expect_blocked(
                "source_unreadable", lambda: compile_document_set(spec, (unreadable,), None, ())
            )
        finally:
            unreadable.chmod(0o600)

        missing = root / "missing.md"
        checks["missing_source_blocks"] = _expect_blocked(
            "source_unreadable", lambda: compile_document_set(spec, (missing,), None, ())
        )

        no_title = root / "no-title.md"
        no_title.write_text("body without a declared title\n", encoding="utf-8")
        checks["missing_title_blocks"] = _expect_blocked(
            "declared_title_missing", lambda: compile_document_set(spec, (no_title,), None, ())
        )

    with tempfile.TemporaryDirectory(prefix="cpe-document-set-standalone-") as standalone_temp:
        standalone_root = Path(standalone_temp)
        standalone_plan = _write(
            standalone_root / "plan.md", "Standalone Plan", "standalone body"
        )
        checks["standalone_requires_explicit_workspace"] = _expect_blocked(
            "workspace_required",
            lambda: compile_document_set(None, (standalone_plan,), None, ()),
        )
        standalone = compile_document_set(
            None,
            (standalone_plan,),
            None,
            (),
            workspace=standalone_root,
        )
        checks["standalone_explicit_workspace_is_usable"] = (
            standalone.documents[0].path == Path("plan.md")
            and standalone.documents[0].content == standalone_plan.read_bytes()
        )

    failures.extend(name for name, passed in checks.items() if not passed)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
