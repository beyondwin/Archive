from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
TOOL_PATH = SCRIPT_DIR / "plan-runner-cutover.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("plan_runner_cutover", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load cutover tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cutover = load_tool()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class CutoverFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="plan-runner-cutover-test-")
        self.addCleanup(self.temp.cleanup)
        # macOS exposes the temporary root through /var -> /private/var.
        # Canonicalize once so exact lexical symlink assertions are meaningful.
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "archive"
        self.home = self.root / "home"
        self.repo.mkdir()
        self.home.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Cutover Test"], cwd=self.repo, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "cutover@example.invalid"],
            cwd=self.repo,
            check=True,
        )
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "add", "seed.txt"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "test: seed"], cwd=self.repo, check=True
        )

    def state_path(self, provider: str, run_id: str) -> Path:
        if provider == "codex":
            return self.home / ".codex" / "orchestrator" / run_id / "state.json"
        return self.home / ".claude" / "clpe" / run_id / "run.json"

    def state(
        self,
        provider: str,
        run_id: str,
        status: str = "completed",
        *,
        resumable: bool | None = None,
    ) -> Path:
        value: dict[str, object] = {"run_id": run_id, "status": status}
        if resumable is not None:
            value["resumable"] = resumable
        path = self.state_path(provider, run_id)
        write_json(path, value)
        return path

    def audit(
        self,
        *,
        ps: str = "",
        process_cwds: dict[int, str] | None = None,
        abandonment: Path | None = None,
    ):
        return cutover.audit_repository(
            self.repo,
            home=self.home,
            process_snapshot=ps,
            process_cwds=process_cwds,
            abandonment_file=abandonment,
            runtime_identity={
                "uv_version": "uv 0.test",
                "python_version": "3.13.test",
                "python_executable": "/managed/python3.13",
                "architecture": "test",
                "gil_disabled": False,
            },
        )

    def abandonment(self, entries: list[dict[str, object]]) -> Path:
        path = self.root / "abandonment.json"
        write_json(path, {"format_version": 1, "runs": entries})
        return path


class AuditStateTests(CutoverFixture):
    def test_missing_and_empty_state_roots_are_allowed(self):
        report = self.audit()
        self.assertEqual([], report["states"])
        self.assertEqual([], report["blocker_codes"])
        (self.home / ".codex" / "orchestrator").mkdir(parents=True)
        (self.home / ".claude" / "clpe").mkdir(parents=True)
        self.assertEqual([], self.audit()["blocker_codes"])

    def test_only_completed_states_are_terminal(self):
        for provider, statuses in {
            "codex": (
                "completed",
                "pending",
                "running",
                "checkpointed",
                "blocked",
                "failed",
                "future",
            ),
            "claude": (
                "completed",
                "running",
                "resumable",
                "blocked",
                "failed",
                "future",
            ),
        }.items():
            for index, status in enumerate(statuses):
                self.state(provider, f"{provider}-{index}", status)
        report = self.audit()
        classifications = {
            (item["provider"], item["status"]): item["classification"]
            for item in report["states"]
        }
        self.assertEqual("terminal", classifications["codex", "completed"])
        self.assertEqual("terminal", classifications["claude", "completed"])
        for key, value in classifications.items():
            if key[1] != "completed":
                self.assertEqual("continuable", value)
        self.assertIn("legacy_nonterminal_state", report["blocker_codes"])

    def test_claude_resumable_true_blocks_even_with_completed_status(self):
        self.state("claude", "resume-me", "completed", resumable=True)
        report = self.audit()
        self.assertEqual("continuable", report["states"][0]["classification"])
        self.assertIn("legacy_nonterminal_state", report["blocker_codes"])

    def test_malformed_unknown_and_unsafe_states_block(self):
        malformed = self.state_path("codex", "malformed")
        malformed.parent.mkdir(parents=True)
        malformed.write_text("{", encoding="utf-8")
        symlinked = self.state_path("claude", "symlinked")
        symlinked.parent.mkdir(parents=True)
        symlinked.symlink_to(malformed)
        report = self.audit()
        by_id = {item["run_id"]: item for item in report["states"]}
        self.assertEqual("malformed", by_id["malformed"]["classification"])
        self.assertEqual("unsafe", by_id["symlinked"]["classification"])
        self.assertIn("legacy_state_integrity", report["blocker_codes"])

    def test_audit_hashes_without_mutating_state_metadata(self):
        path = self.state("codex", "stable", "running")
        os.chmod(path, 0o600)
        before = path.stat()
        payload = path.read_bytes()
        report = self.audit()
        after = path.stat()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report["states"][0]["sha256"])
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertEqual(before.st_mode, after.st_mode)
        self.assertEqual(before.st_uid, after.st_uid)
        self.assertEqual(payload, path.read_bytes())

    def test_duplicate_and_unsafe_run_directories_block(self):
        root = self.home / ".codex" / "orchestrator"
        (root / "unsafe.name").mkdir(parents=True)
        (root / "unsafe.name" / "state.json").write_text("{}", encoding="utf-8")
        report = self.audit()
        self.assertIn("legacy_state_integrity", report["blocker_codes"])

    def test_source_inventory_records_lstat_identity_without_following(self):
        source = self.repo / "skills" / "kws-codex-plan-executor"
        source.mkdir(parents=True)
        report = self.audit()
        fact = next(item for item in report["sources"] if item["path"] == str(source))
        metadata = source.lstat()
        self.assertEqual("directory", fact["kind"])
        self.assertEqual(metadata.st_dev, fact["device"])
        self.assertEqual(metadata.st_ino, fact["inode"])
        self.assertEqual(str(source), fact["resolved_path"])


class ProcessAuditTests(CutoverFixture):
    def test_exact_legacy_roots_scripts_and_installed_links_block(self):
        codex_root = self.repo / "skills" / "kws-codex-plan-executor"
        claude_link = self.home / ".claude" / "skills" / "kws-claude-plan-executor"
        snapshot = "\n".join(
            [
                f"101 1 101 python {codex_root}/scripts/cpe.py run",
                "102 1 102 python scripts/clpe.py --run-id clpe-live",
                f"103 1 103 python {claude_link}/scripts/clpe.py",
            ]
        )
        report = self.audit(ps=snapshot)
        self.assertEqual([101, 102, 103], [item["pid"] for item in report["processes"]])
        self.assertIn("legacy_process_active", report["blocker_codes"])
        for item in report["processes"]:
            self.assertRegex(item["command_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("command", item)

    def test_similarly_named_commands_do_not_block(self):
        snapshot = "\n".join(
            [
                "201 1 201 python scripts/cpe.py.bak",
                "202 1 202 python scripts/not-clpe.py",
                "203 1 203 python /tmp/kws-codex-plan-executor-copy/run.py",
            ]
        )
        self.assertEqual([], self.audit(ps=snapshot)["processes"])

    def test_process_absence_does_not_clear_nonterminal_state(self):
        self.state("codex", "no-process", "failed")
        self.assertIn("legacy_nonterminal_state", self.audit()["blocker_codes"])

    def test_process_presence_blocks_completed_state(self):
        self.state("codex", "live-completed", "completed")
        report = self.audit(ps="301 1 301 python scripts/cpe.py live-completed")
        self.assertIn("legacy_process_active", report["blocker_codes"])

    def test_exact_legacy_cwd_blocks_even_when_command_is_generic(self):
        source = self.repo / "skills" / "kws-codex-plan-executor"
        source.mkdir(parents=True)
        report = self.audit(
            ps="302 1 302 python worker.py",
            process_cwds={302: str(source / "scripts")},
        )
        self.assertIn("legacy_process_active", report["blocker_codes"])
        self.assertEqual(["codex"], report["processes"][0]["providers"])
        self.assertEqual(str(source / "scripts"), report["processes"][0]["cwd"])
        self.assertIn("codex_legacy_cwd", report["processes"][0]["match_codes"])

    def test_malformed_or_oversized_process_snapshot_fails_closed(self):
        report = self.audit(ps="not-a-valid-ps-line")
        self.assertIn("process_snapshot_integrity", report["blocker_codes"])
        report = self.audit(ps="1 1 1 " + "x" * (cutover.MAX_COMMAND_BYTES + 1))
        self.assertIn("process_snapshot_integrity", report["blocker_codes"])

    def test_linked_worktree_audit_recognizes_primary_legacy_root(self):
        linked = self.root / "linked"
        subprocess.run(
            ["git", "worktree", "add", "-q", "-b", "audit-feature", str(linked)],
            cwd=self.repo,
            check=True,
        )
        skill_home = self.home / ".codex" / "skills"
        skill_home.mkdir(parents=True)
        primary_source = self.repo / "skills" / "kws-codex-plan-executor"
        (skill_home / "kws-codex-plan-executor").symlink_to(primary_source)
        report = cutover.audit_repository(
            linked,
            home=self.home,
            process_snapshot=f"501 1 501 python {primary_source}/scripts/cpe.py",
            runtime_identity={
                "uv_version": "uv 0.test",
                "python_version": "3.13.test",
                "python_executable": "/managed/python3.13",
                "architecture": "test",
                "gil_disabled": False,
            },
        )
        self.assertNotIn("legacy_link_integrity", report["blocker_codes"])
        self.assertIn("legacy_process_active", report["blocker_codes"])
        self.assertEqual([501], [item["pid"] for item in report["processes"]])
        inspected = report["legacy_source_roots"]
        self.assertIn(str(primary_source), inspected)
        self.assertIn(
            str(linked / "skills" / "kws-codex-plan-executor"), inspected
        )


class AbandonmentTests(CutoverFixture):
    def entry(self, provider: str, run_id: str, digest: str) -> dict[str, object]:
        return {
            "provider": provider,
            "run_id": run_id,
            "state_sha256": digest,
            "reason": "operator explicitly abandoned this legacy run",
        }

    def test_exact_digest_suppresses_only_matching_nonterminal_state(self):
        path = self.state("codex", "abandoned-run", "failed")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        abandonment = self.abandonment([self.entry("codex", "abandoned-run", digest)])
        report = self.audit(abandonment=abandonment)
        self.assertEqual([], report["blocker_codes"])
        self.assertEqual("abandoned", report["states"][0]["classification"])
        self.assertEqual(payload := path.read_bytes(), path.read_bytes())
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

    def test_rejects_duplicate_unknown_unsafe_vague_and_mismatched_entries(self):
        path = self.state("codex", "run-one", "failed")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        invalid_sets = [
            [
                self.entry("codex", "run-one", digest),
                self.entry("codex", "run-one", digest),
            ],
            [self.entry("other", "run-one", digest)],
            [self.entry("codex", "../run-one", digest)],
            [{**self.entry("codex", "run-one", digest), "reason": "skip"}],
            [self.entry("codex", "run-one", "0" * 64)],
        ]
        for index, entries in enumerate(invalid_sets):
            with self.subTest(index=index):
                path = self.root / f"invalid-{index}.json"
                write_json(path, {"format_version": 1, "runs": entries})
                report = self.audit(abandonment=path)
                self.assertIn("abandonment_integrity", report["blocker_codes"])

    def test_state_change_after_abandonment_digest_blocks(self):
        path = self.state("claude", "changed", "resumable")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        abandonment = self.abandonment([self.entry("claude", "changed", digest)])
        write_json(path, {"run_id": "changed", "status": "running"})
        report = self.audit(abandonment=abandonment)
        self.assertIn("abandonment_integrity", report["blocker_codes"])
        self.assertEqual("continuable", report["states"][0]["classification"])

    def test_live_matching_process_prevents_abandonment(self):
        path = self.state("claude", "still-live", "resumable")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        abandonment = self.abandonment([self.entry("claude", "still-live", digest)])
        report = self.audit(
            abandonment=abandonment,
            ps="401 1 401 python scripts/clpe.py --run-id still-live",
        )
        self.assertIn("abandonment_live_process", report["blocker_codes"])
        self.assertNotEqual("abandoned", report["states"][0]["classification"])


class ReportTests(CutoverFixture):
    def test_report_is_content_addressed_and_written_atomically(self):
        output = self.root / "audit.json"
        report = self.audit()
        cutover.write_audit_report(output, report)
        stored = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(cutover.validate_report_digest(stored))
        self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))
        self.assertEqual([], list(output.parent.glob(f".{output.name}.*.tmp")))

    def test_tampered_report_is_rejected(self):
        report = self.audit()
        report["repository"]["head"] = "0" * 40
        self.assertFalse(cutover.validate_report_digest(report))

    def test_self_consistent_structurally_malformed_reports_are_rejected(self):
        original = self.audit()
        malformed_reports: list[dict[str, object]] = []
        missing_repository = json.loads(json.dumps(original))
        del missing_repository["repository"]
        malformed_reports.append(missing_repository)
        wrong_repository = json.loads(json.dumps(original))
        wrong_repository["repository"] = []
        malformed_reports.append(wrong_repository)
        missing_runtime_field = json.loads(json.dumps(original))
        del missing_runtime_field["runtime"]["python_executable"]
        malformed_reports.append(missing_runtime_field)
        invalid_source_fact = json.loads(json.dumps(original))
        invalid_source_fact["sources"] = [{"path": "relative", "kind": "directory"}]
        malformed_reports.append(invalid_source_fact)
        invalid_state = json.loads(json.dumps(original))
        invalid_state["states"] = [{"provider": "codex"}]
        malformed_reports.append(invalid_state)
        invalid_blockers = json.loads(json.dumps(original))
        invalid_blockers["blocker_codes"] = "none"
        malformed_reports.append(invalid_blockers)
        for index, malformed in enumerate(malformed_reports):
            with self.subTest(index=index):
                path = self.root / f"malformed-report-{index}.json"
                write_json(path, cutover.seal_report(malformed))
                with self.assertRaisesRegex(
                    cutover.CutoverError, "^report_integrity$"
                ):
                    cutover.read_report(path)

    def test_malformed_report_cli_exits_65_without_traceback(self):
        malformed = self.audit()
        malformed["repository"] = []
        path = self.root / "malformed-cli-report.json"
        write_json(path, cutover.seal_report(malformed))
        command = subprocess.run(
            [
                str(SCRIPT_DIR / "plan-runner-cutover"),
                "apply",
                "--repo",
                str(self.repo),
                "--audit-report",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(65, command.returncode)
        self.assertEqual("", command.stderr)
        self.assertEqual(
            {"reason_code": "report_integrity", "status": "blocked"},
            json.loads(command.stdout),
        )


class ApplyTests(CutoverFixture):
    def setUp(self) -> None:
        super().setUp()
        for name in ("kws-codex-plan-runner", "kws-claude-plan-runner"):
            (self.repo / "skills" / name).mkdir(parents=True)
        self.codex_legacy = self.repo / "skills" / "kws-codex-plan-executor"
        self.claude_legacy = self.repo / "skills" / "kws-claude-plan-executor"

    def make_links(self) -> None:
        for provider in ("codex", "claude"):
            skill_home = self.home / f".{provider}" / "skills"
            skill_home.mkdir(parents=True, exist_ok=True)
            (skill_home / "kws-codex-plan-executor").symlink_to(self.codex_legacy)
            (skill_home / "kws-claude-plan-executor").symlink_to(self.claude_legacy)

    def clean_report(self) -> dict[str, object]:
        report = self.audit()
        return json.loads(json.dumps(report))

    def test_apply_refuses_stale_nonzero_and_non_main_reports_without_mutation(self):
        self.make_links()
        before = {
            path: os.readlink(path)
            for path in self.home.glob(".*/*/kws-*-plan-executor")
        }
        report = self.clean_report()
        subprocess.run(
            ["git", "switch", "-q", "-c", "feature"], cwd=self.repo, check=True
        )
        with self.assertRaises(cutover.CutoverError):
            cutover.apply_cutover(
                self.repo,
                report,
                home=self.home,
                process_snapshot="",
                runtime_identity=report["runtime"],
            )
        self.assertEqual(before, {path: os.readlink(path) for path in before})

    def test_apply_installs_only_provider_matching_new_links(self):
        self.make_links()
        report = self.clean_report()
        with mock.patch.object(cutover, "git_branch", return_value="main"):
            result = cutover.apply_cutover(
                self.repo,
                report,
                home=self.home,
                process_snapshot="",
                runtime_identity=report["runtime"],
            )
        self.assertEqual("applied", result["status"])
        self.assertEqual(4, len(result["quarantined_legacy_links"]))
        for move in result["quarantined_legacy_links"]:
            self.assertFalse(Path(move["source"]).exists())
            self.assertTrue(Path(move["destination"]).is_symlink())
        self.assertEqual(
            str(self.repo / "skills" / "kws-codex-plan-runner"),
            os.readlink(self.home / ".codex" / "skills" / "kws-codex-plan-runner"),
        )
        self.assertEqual(
            str(self.repo / "skills" / "kws-claude-plan-runner"),
            os.readlink(self.home / ".claude" / "skills" / "kws-claude-plan-runner"),
        )
        self.assertFalse(
            (self.home / ".codex" / "skills" / "kws-claude-plan-runner").exists()
        )
        self.assertFalse(
            (self.home / ".claude" / "skills" / "kws-codex-plan-runner").exists()
        )
        for path in self.home.glob(".*/*/kws-*-plan-executor"):
            self.fail(f"legacy link remained: {path}")

    def test_apply_rejects_wrong_link_types_and_targets_before_mutation(self):
        self.make_links()
        bad = self.home / ".codex" / "skills" / "kws-codex-plan-executor"
        bad.unlink()
        bad.write_text("not a link", encoding="utf-8")
        report = self.clean_report()
        with mock.patch.object(cutover, "git_branch", return_value="main"):
            with self.assertRaises(cutover.CutoverError):
                cutover.apply_cutover(
                    self.repo,
                    report,
                    home=self.home,
                    process_snapshot="",
                    runtime_identity=report["runtime"],
                )
        self.assertTrue(bad.is_file())
        self.assertFalse(
            (self.home / ".codex" / "skills" / "kws-codex-plan-runner").exists()
        )

    def test_apply_discovers_broken_legacy_symlinks(self):
        self.make_links()
        self.assertFalse(self.codex_legacy.exists())
        self.assertTrue(
            (self.home / ".codex" / "skills" / "kws-codex-plan-executor").is_symlink()
        )
        report = self.clean_report()
        with mock.patch.object(cutover, "git_branch", return_value="main"):
            cutover.apply_cutover(
                self.repo,
                report,
                home=self.home,
                process_snapshot="",
                runtime_identity=report["runtime"],
            )
        self.assertFalse(
            (self.home / ".codex" / "skills" / "kws-codex-plan-executor").is_symlink()
        )

    def test_apply_preserves_multi_agent_links_byte_for_byte(self):
        self.make_links()
        target = self.repo / "skills" / "kws-claude-multi-agent-executor"
        link = self.home / ".claude" / "skills" / "kws-claude-multi-agent-executor"
        link.symlink_to(target)
        before = os.fsencode(os.readlink(link))
        report = self.clean_report()
        with mock.patch.object(cutover, "git_branch", return_value="main"):
            cutover.apply_cutover(
                self.repo,
                report,
                home=self.home,
                process_snapshot="",
                runtime_identity=report["runtime"],
            )
        self.assertEqual(before, os.fsencode(os.readlink(link)))

    def test_atomic_install_interruption_never_creates_regular_file(self):
        destination = self.home / ".codex" / "skills" / "kws-codex-plan-runner"
        destination.parent.mkdir(parents=True)
        target = self.repo / "skills" / "kws-codex-plan-runner"

        def interrupt(_temporary: Path, _destination: Path) -> None:
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            cutover.atomic_symlink(target, destination, before_rename=interrupt)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.is_symlink())
        self.assertFalse(any(destination.parent.glob(f".{destination.name}.*.tmp")))

    def test_atomic_install_never_replaces_raced_regular_destination(self):
        destination = self.home / ".codex" / "skills" / "kws-codex-plan-runner"
        destination.parent.mkdir(parents=True)
        target = self.repo / "skills" / "kws-codex-plan-runner"

        def create_regular(_temporary: Path, raced_destination: Path) -> None:
            raced_destination.write_text("operator data", encoding="utf-8")

        with self.assertRaisesRegex(
            cutover.CutoverError, "^legacy_link_integrity$"
        ):
            cutover.atomic_symlink(
                target, destination, before_rename=create_regular
            )
        self.assertTrue(destination.is_file())
        self.assertFalse(destination.is_symlink())
        self.assertEqual("operator data", destination.read_text(encoding="utf-8"))

    def test_quarantine_move_preserves_and_reports_raced_regular_or_directory(self):
        for replacement in ("regular", "directory"):
            with self.subTest(replacement=replacement):
                parent = self.home / replacement
                parent.mkdir()
                target = self.repo / "skills" / "kws-codex-plan-executor"
                link = parent / "kws-codex-plan-executor"
                link.symlink_to(target)
                expected = cutover._lstat_fact(link)

                def swap(_source: Path, _destination: Path) -> None:
                    link.unlink()
                    if replacement == "regular":
                        link.write_text("operator data", encoding="utf-8")
                    else:
                        link.mkdir()

                with self.assertRaisesRegex(
                    cutover.CutoverError, "^legacy_link_integrity$"
                ) as caught:
                    cutover.quarantine_legacy_entry(
                        link,
                        expected,
                        expected_target=str(target),
                        before_rename=swap,
                    )
                recovery = Path(
                    caught.exception.details["quarantine_recovery_path"]
                )
                self.assertFalse(link.exists())
                self.assertFalse(link.is_symlink())
                if replacement == "regular":
                    self.assertTrue(recovery.is_file())
                    self.assertEqual(
                        "operator data", recovery.read_text(encoding="utf-8")
                    )
                else:
                    self.assertTrue(recovery.is_dir())

    def test_quarantine_destination_race_never_overwrites_existing_entry(self):
        parent = self.home / "destination-race"
        parent.mkdir()
        target = self.repo / "skills" / "kws-codex-plan-executor"
        link = parent / "kws-codex-plan-executor"
        link.symlink_to(target)
        expected = cutover._lstat_fact(link)

        def occupy_destination(_source: Path, destination: Path) -> None:
            destination.write_text("existing quarantine data", encoding="utf-8")

        with self.assertRaisesRegex(
            cutover.CutoverError, "^legacy_link_integrity$"
        ) as caught:
            cutover.quarantine_legacy_entry(
                link,
                expected,
                expected_target=str(target),
                before_rename=occupy_destination,
            )
        self.assertTrue(link.is_symlink())
        collision = Path(caught.exception.details["quarantine_collision_path"])
        self.assertEqual(
            "existing quarantine data", collision.read_text(encoding="utf-8")
        )

    def test_post_move_io_failure_reports_exact_recovery_path(self):
        parent = self.home / "post-move-error"
        parent.mkdir()
        target = self.repo / "skills" / "kws-codex-plan-executor"
        link = parent / "kws-codex-plan-executor"
        link.symlink_to(target)
        expected = cutover._lstat_fact(link)
        with mock.patch.object(
            cutover.os, "fsync", side_effect=OSError("injected fsync failure")
        ):
            with self.assertRaisesRegex(
                cutover.CutoverError, "^legacy_link_integrity$"
            ) as caught:
                cutover.quarantine_legacy_entry(
                    link, expected, expected_target=str(target)
                )
        recovery = Path(caught.exception.details["quarantine_recovery_path"])
        self.assertFalse(link.exists())
        self.assertTrue(recovery.is_symlink())
        self.assertEqual(str(target), os.readlink(recovery))


class QuarantineTests(ApplyTests):
    def test_only_enumerated_cache_residuals_are_moved_to_trash(self):
        cache = self.codex_legacy / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "mod.cpython-313.pyc").write_bytes(b"cache")
        (self.claude_legacy / ".venv" / "bin").mkdir(parents=True)
        (self.claude_legacy / ".venv" / "bin" / "python").write_bytes(b"cache")
        report = self.clean_report()
        with mock.patch.object(cutover, "git_branch", return_value="main"):
            result = cutover.quarantine_legacy_caches(
                self.repo,
                report,
                home=self.home,
                process_snapshot="",
                runtime_identity=report["runtime"],
            )
        self.assertEqual(2, len(result["moves"]))
        self.assertFalse(self.codex_legacy.exists())
        self.assertFalse(self.claude_legacy.exists())
        for move in result["moves"]:
            self.assertTrue(Path(move["destination"]).is_dir())
            self.assertTrue(str(Path(move["destination"])).startswith(str(self.home / ".Trash")))

    def test_unknown_residual_blocks_without_moving_anything(self):
        (self.codex_legacy).mkdir(parents=True)
        (self.codex_legacy / "unknown.txt").write_text("keep", encoding="utf-8")
        (self.claude_legacy / "__pycache__").mkdir(parents=True)
        report = self.clean_report()
        with mock.patch.object(cutover, "git_branch", return_value="main"):
            with self.assertRaises(cutover.CutoverError):
                cutover.quarantine_legacy_caches(
                    self.repo,
                    report,
                    home=self.home,
                    process_snapshot="",
                    runtime_identity=report["runtime"],
                )
        self.assertTrue(self.codex_legacy.exists())
        self.assertTrue(self.claude_legacy.exists())

    def test_symlink_residual_blocks_without_following(self):
        self.codex_legacy.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        (self.codex_legacy / "__pycache__").symlink_to(outside)
        report = self.clean_report()
        with mock.patch.object(cutover, "git_branch", return_value="main"):
            with self.assertRaises(cutover.CutoverError):
                cutover.quarantine_legacy_caches(
                    self.repo,
                    report,
                    home=self.home,
                    process_snapshot="",
                    runtime_identity=report["runtime"],
                )
        self.assertTrue(outside.exists())
        self.assertTrue(self.codex_legacy.exists())


class LauncherTests(unittest.TestCase):
    def test_launcher_is_self_locating_and_never_downloads_python(self):
        launcher = SCRIPT_DIR / "plan-runner-cutover"
        text = launcher.read_text(encoding="utf-8")
        self.assertIn('SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)', text)
        self.assertIn(
            "uv python find --managed-python --no-python-downloads \\\n"
            "  --no-project --no-config --resolve-links 3.13",
            text,
        )
        self.assertIn('exec "$PYTHON_BIN" "$SCRIPT_DIR/plan-runner-cutover.py" "$@"', text)
        for forbidden in ("uv run", "uv python install", "python3"):
            self.assertNotIn(forbidden, text)
        self.assertTrue(launcher.stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
