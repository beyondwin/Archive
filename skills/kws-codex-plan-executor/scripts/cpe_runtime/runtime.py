"""One durable CPE run around one Superpowers root controller."""
from __future__ import annotations
import json, os, secrets, subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from .controller import CodexController, ControllerOutcome, ControllerRequest
from .git import (
    WorktreeAssignment, _absolute_git_path, _cleanup_claimed_worktree, _commit_at,
    _common_repository, _git, adopt_worktree, capture_git_identity, create_worktree,
    observe_git, require_ancestor,
)
from .state import (DocumentSource, RunManifest, RunState, RunStore,
                    read_legacy_format, snapshot_documents)
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
def new_run_id() -> str:
    return f"cpe-{secrets.token_hex(8)}"
def resolve_repository(workspace: Path) -> Path:
    return _common_repository(workspace)[0]
def resolve_head(repository: Path) -> str:
    return _commit_at(repository, "HEAD")
def render_initial_prompt(
    manifest: RunManifest, *, manifest_path: Path, git_common_dir: Path,
    schema_path: Path,
) -> str:
    lines = [
        "Execute the immutable CPE document bundle in the assigned worktree.",
        "Read repository AGENTS.md. The manifest entries are caller-supplied documents "
        "in caller order; interpret and use them under Superpowers without asking CPE "
        "for document roles or validation.",
        "Use the installed Superpowers skill named in SUPERPOWERS_SKILL.",
        "Superpowers and Git own semantic progress and recovery.",
        "Do not merge, push, open a PR, tag, publish, release, or deploy.",
        "Return only the terminal envelope required by TERMINAL_SCHEMA.",
        "", f"MANIFEST={manifest_path}", f"RUN_ID={manifest.run_id}",
        f"SOURCE_REPOSITORY={manifest.source_repository}",
        f"BASE_COMMIT={manifest.base_commit}", f"BRANCH={manifest.branch}",
        f"WORKTREE={manifest.worktree}", f"GIT_COMMON_DIR={git_common_dir}",
        f"SUPERPOWERS_SKILL={manifest.superpowers_skill}",
        f"SANDBOX={manifest.sandbox}", f"APPROVAL_POLICY={manifest.approval_policy}",
        f"INTEGRATION_POLICY={manifest.integration_policy}",
        f"REMOTE_ACTION_POLICY={manifest.remote_action_policy}",
        f"TERMINAL_SCHEMA={schema_path}", "DOCUMENTS_IN_CALLER_ORDER:",
    ]
    lines += [f"DOCUMENT_{item.order:03d}={item.snapshot_path}"
              for item in manifest.documents]
    return "\n".join(lines) + "\n"
def render_resume_prompt(manifest: RunManifest, *, manifest_path: Path,
                         git_common_dir: Path, schema_path: Path) -> str:
    initial = render_initial_prompt(
        manifest, manifest_path=manifest_path, git_common_dir=git_common_dir, schema_path=schema_path)
    return initial + "CONTINUITY=same saved controller session; continue from Superpowers and Git\n"
def render_fallback_prompt(manifest: RunManifest, *, manifest_path: Path,
                           git_common_dir: Path, schema_path: Path, head: str,
                           status_digest: str, capsule: object, failure: object) -> str:
    recovery = json.dumps(
        {"resume_capsule": capsule, "failure": failure}, sort_keys=True, separators=(",", ":"))
    initial = render_initial_prompt(
        manifest, manifest_path=manifest_path, git_common_dir=git_common_dir, schema_path=schema_path)
    return initial + (
        "CONTINUITY=one fresh controller after explicit saved-session loss\n"
        f"CURRENT_HEAD={head}\nCURRENT_STATUS_DIGEST={status_digest}\n"
        f"BOUNDED_RECOVERY={recovery}\n")
def _save(store: RunStore, state: RunState, **changes: object) -> RunState:
    state = replace(state, updated_at=utc_now(), **changes)
    store.save_state(state); return state
def _current(assignment: WorktreeAssignment) -> bool:
    try:
        return (
            Path(_git(assignment.worktree, "rev-parse", "--show-toplevel")
                 ).resolve(strict=True) == assignment.worktree
            and _absolute_git_path(assignment.worktree, "--git-common-dir")
            == assignment.git_common_dir
            and _git(assignment.worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
            == assignment.branch
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        return False
def _capsule(outcome: ControllerOutcome) -> dict[str, object] | None:
    terminal = outcome.terminal
    if terminal is None or terminal.resume_capsule is None:
        return None
    value = terminal.resume_capsule
    return {"head_commit": value.head_commit, "worktree_status_digest": value.worktree_status_digest,
        "note": value.note, "evidence_refs": list(value.evidence_refs),
    }
def _session_unavailable(outcome: ControllerOutcome) -> bool:
    return (outcome.terminal is None and (
        outcome.process_class == "session_unavailable" or
        outcome.process_class == "failed" and outcome.provider_code == "session_unavailable"))
def _assignment(manifest: RunManifest) -> WorktreeAssignment:
    repository, worktree = Path(manifest.source_repository), Path(manifest.worktree)
    return WorktreeAssignment(repository, worktree, manifest.branch, manifest.base_commit, _common_repository(repository)[1])
def _orphan_handoff(store: RunStore, state: RunState,
                    assignment: WorktreeAssignment) -> Path | None:
    if not os.path.lexists(store.handoff_path): return None
    payload = store.read_handoff()
    try:
        facts = observe_git(assignment.worktree)
        require_ancestor(assignment.worktree, assignment.base_commit, facts.head)
    except ValueError as exc:
        raise ValueError("handoff is invalid") from exc
    expected = {
        "format_version": 1, "run_id": store.manifest.run_id,
        "branch": assignment.branch, "saved_worktree": str(assignment.worktree),
        "base_commit": assignment.base_commit, "observed_head": facts.head,
        "tracked_clean": True, "untracked_present": facts.untracked_present,
        "controller_claim": "completed",
        "controller_session_id": state.controller_session_id,
        "controller_generation": state.controller_generation,
        "integration": "not_observed", "remote_actions_by_cpe": "none",
    }
    valid = (
        type(payload) is dict and payload == expected
        and all(type(payload[key]) is type(value) for key, value in expected.items())
        and state.status == "interrupted" and state.controller_session_id is not None
        and state.active_pid is None and state.active_process_group is None
        and state.last_observed_head == facts.head and state.tracked_clean
        and state.untracked_present == facts.untracked_present
        and state.status_digest == facts.status_digest
        and state.last_process_class == "completed" and state.last_exit_code == 0
        and state.blocker is None and _current(assignment)
    )
    if not valid: raise ValueError("handoff is invalid")
    return store.handoff_path
class CpeRuntime:
    def __init__(
        self, *, codex_home: Path | None = None, worktree_root: Path | None = None,
        controller: CodexController | None = None, schema_path: Path | None = None,
    ) -> None:
        home = codex_home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        self.codex_home = home.expanduser().resolve()
        self.worktree_root = (worktree_root or self.codex_home / "worktrees").resolve()
        self.controller = controller or CodexController()
        default = Path(__file__).resolve().parents[2] / "templates" / "terminal-envelope.schema.json"
        self.schema_path = (schema_path or default).resolve(strict=True)
    def run(
        self, *, workspace: Path, documents: Sequence[DocumentSource],
        superpowers_skill: str, sandbox: str,
        adopt_worktree_path: Path | None = None, base: str | None = None,
    ) -> dict[str, object]:
        repository = resolve_repository(workspace)
        identity, run_id = capture_git_identity(repository), new_run_id()
        selected_base = base if adopt_worktree_path is not None else resolve_head(repository)
        if selected_base is None:
            raise ValueError("--base is required with --adopt-worktree")
        assignment = (
            adopt_worktree(repository, worktree=adopt_worktree_path, base=selected_base)
            if adopt_worktree_path is not None else
            create_worktree(repository, base=selected_base, run_id=run_id,
                            root=self.worktree_root)
        )
        try:
            root = self.codex_home / "cpe-v3" / "runs" / run_id
            records = snapshot_documents(run_root=root, sources=documents)
            facts = observe_git(assignment.worktree)
            manifest = RunManifest(
                5, 3, run_id, str(assignment.repository), assignment.base_commit,
                assignment.branch, str(assignment.worktree), tuple(records),
                superpowers_skill, identity, sandbox, "never", "local-handoff-only",
                "prohibited", utc_now(),
            )
            state = RunState(
                "prepared", None, 0, False, None, None, facts.head,
                facts.tracked_clean, facts.untracked_present, facts.status_digest,
                None, None, None, None, utc_now(),
            )
            store = RunStore.create(self.codex_home, manifest, state)
        except BaseException:
            if adopt_worktree_path is None:
                _cleanup_claimed_worktree(
                    assignment.repository, worktree=assignment.worktree,
                    branch=assignment.branch, path_claimed=True,
                )
            raise
        return self._launch(store, assignment, mode="initial", session_id=None)
    def resume(self, *, run_id: str) -> dict[str, object]:
        store = RunStore.open(self.codex_home, run_id)
        if store.state.status == "handed_off":
            return {"status": "blocked", "run_id": run_id, "reason": "run_already_handed_off"}
        session_id = store.state.controller_session_id
        if session_id is None:
            return {"status": "blocked", "run_id": run_id, "reason": "saved_session_unavailable"}
        return self._launch(store, _assignment(store.manifest), mode="resume", session_id=session_id)
    def inspect(self, *, run_id: str) -> dict[str, object]:
        v5_root = RunStore._run_root(self.codex_home, run_id)
        if os.path.lexists(v5_root):
            store = RunStore.open(self.codex_home, run_id)
            return {"format_version": 5, "run_id": run_id, **store.state.to_payload()}
        version, root = read_legacy_format(self.codex_home, run_id)
        return {"status": "legacy_read_only", "format_version": version,
            "run_root": str(root), "recommended_action":
            "preserve artifacts; use explicit --adopt-worktree for continuation"}
    def _launch(self, store: RunStore, assignment: WorktreeAssignment, *, mode: str, session_id: str | None) -> dict[str, object]:
        with store.lock() as lock:
            store = RunStore.open(self.codex_home, store.manifest.run_id)
            state = store.state
            if mode == "resume":
                if state.status == "handed_off":
                    return {"status": "blocked", "run_id": store.manifest.run_id,
                            "reason": "run_already_handed_off"}
                handoff_path = _orphan_handoff(store, state, assignment)
                if handoff_path is not None:
                    _save(store, state, status="handed_off")
                    return {"status": "handed_off", "run_id": store.manifest.run_id,
                            "handoff_path": str(handoff_path)}
                session_id = state.controller_session_id
                if session_id is None:
                    return {"status": "blocked", "run_id": store.manifest.run_id,
                            "reason": "saved_session_unavailable"}
            def persist(**changes: object) -> None:
                nonlocal state
                state = _save(store, state, **changes)
            common = {"manifest_path": store.manifest_path,
                      "git_common_dir": assignment.git_common_dir, "schema_path": self.schema_path}
            renderer = render_initial_prompt if mode == "initial" else render_resume_prompt
            prompt = renderer(store.manifest, **common)
            def invoke(launch_mode: str, saved_session: str | None, generation: int,
                       launch_prompt: str) -> ControllerOutcome | dict[str, object]:
                persist(status="running")
                request = ControllerRequest(
                    launch_mode, assignment.worktree, assignment.git_common_dir,
                    store.manifest.sandbox, launch_prompt, self.schema_path,
                    saved_session, generation, store.manifest.git_identity, lock.fileno())
                try:
                    return self.controller.launch(
                        request, on_session_id=lambda value: persist(controller_session_id=value),
                        on_process_started=lambda pid, group: persist(
                            active_pid=pid, active_process_group=group))
                except KeyboardInterrupt:
                    return self._launch_error(store, state, assignment, "interrupted")
                except Exception:
                    return self._launch_error(store, state, assignment, "failed")
            launched = invoke(mode, session_id, state.controller_generation, prompt)
            if isinstance(launched, dict): return launched
            outcome = launched
            if not (mode == "resume" and session_id is not None
                    and _session_unavailable(outcome)):
                return self._finish(store, state, assignment, outcome)
            if state.fresh_fallback_used or state.controller_generation == 1:
                return self._block_session_unavailable(store, state, assignment, outcome)
            try: facts = observe_git(assignment.worktree)
            except ValueError: return self._launch_error(store, state, assignment, "failed")
            terminal = outcome.terminal
            state = _save(
                store, state, status="interrupted", controller_session_id=None,
                controller_generation=1, fresh_fallback_used=True,
                active_pid=None, active_process_group=None,
                last_observed_head=facts.head, tracked_clean=facts.tracked_clean,
                untracked_present=facts.untracked_present, status_digest=facts.status_digest,
                last_process_class="session_unavailable", last_exit_code=outcome.exit_code,
                blocker=terminal.blocker if terminal is not None else None)
            failure = {
                "process_class": "session_unavailable",
                "provider_code": outcome.provider_code,
                "blocker": terminal.blocker if terminal is not None else None}
            fallback_prompt = render_fallback_prompt(
                store.manifest, **common, head=facts.head,
                status_digest=facts.status_digest, capsule=state.resume_capsule,
                failure=failure)
            launched = invoke("fallback", None, 1, fallback_prompt)
            if isinstance(launched, dict): return launched
            if _session_unavailable(launched):
                return self._block_session_unavailable(store, state, assignment, launched)
            return self._finish(store, state, assignment, launched)
    def _block_session_unavailable(self, store: RunStore, state: RunState, assignment: WorktreeAssignment, outcome: ControllerOutcome) -> dict[str, object]:
        try: facts = observe_git(assignment.worktree)
        except ValueError: return self._launch_error(store, state, assignment, "failed")
        terminal = outcome.terminal
        _save(
            store, state, status="blocked", active_pid=None,
            active_process_group=None, last_observed_head=facts.head,
            tracked_clean=facts.tracked_clean,
            untracked_present=facts.untracked_present, status_digest=facts.status_digest,
            last_process_class="session_unavailable", last_exit_code=outcome.exit_code,
            blocker=terminal.blocker if terminal is not None else None)
        return {"status": "blocked", "run_id": store.manifest.run_id, "reason": "session_unavailable"}
    def _launch_error(self, store: RunStore, state: RunState,
                      assignment: WorktreeAssignment, status: str) -> dict[str, object]:
        changes: dict[str, object] = {
            "status": status, "active_pid": None, "active_process_group": None,
            "last_process_class": status, "last_exit_code": None,
        }
        try:
            facts = observe_git(assignment.worktree)
            changes.update(
                last_observed_head=facts.head, tracked_clean=facts.tracked_clean,
                untracked_present=facts.untracked_present,
                status_digest=facts.status_digest,
            )
        except ValueError:
            pass
        _save(store, state, **changes)
        return {"status": status, "run_id": store.manifest.run_id}
    def _finish(
        self, store: RunStore, state: RunState, assignment: WorktreeAssignment,
        outcome: ControllerOutcome,
    ) -> dict[str, object]:
        try:
            facts = observe_git(assignment.worktree)
        except ValueError:
            return self._launch_error(store, state, assignment, "failed")
        terminal = outcome.terminal
        status = (
            "blocked" if outcome.process_class == "blocked" else
            "failed" if outcome.process_class == "failed"
            and outcome.provider_code != "transport" else "interrupted"
        )
        state = _save(
            store, state, status=status, active_pid=None, active_process_group=None,
            last_observed_head=facts.head, tracked_clean=facts.tracked_clean,
            untracked_present=facts.untracked_present, status_digest=facts.status_digest,
            last_process_class=outcome.process_class, last_exit_code=outcome.exit_code,
            resume_capsule=_capsule(outcome) or state.resume_capsule,
            blocker=terminal.blocker if terminal is not None else None,
        )
        if outcome.process_class != "completed" or terminal is None:
            return {"status": status, "run_id": store.manifest.run_id,
                    "reason": outcome.process_class}
        complete = (
            terminal.claim == "completed" and terminal.head_commit == facts.head
            and facts.tracked_clean and state.controller_session_id is not None
            and _current(assignment)
        )
        try:
            require_ancestor(assignment.worktree, assignment.base_commit, facts.head)
        except ValueError:
            complete = False
        if not complete:
            return {"status": "interrupted", "run_id": store.manifest.run_id,
                    "reason": "handoff_incomplete"}
        handoff = {
            "format_version": 1, "run_id": store.manifest.run_id,
            "branch": assignment.branch, "saved_worktree": str(assignment.worktree),
            "base_commit": assignment.base_commit, "observed_head": facts.head,
            "tracked_clean": facts.tracked_clean,
            "untracked_present": facts.untracked_present,
            "controller_claim": "completed",
            "controller_session_id": state.controller_session_id,
            "controller_generation": state.controller_generation,
            "integration": "not_observed", "remote_actions_by_cpe": "none",
        }
        path = store.write_handoff(handoff)
        _save(store, state, status="handed_off")
        return {"status": "handed_off", "run_id": store.manifest.run_id,
                "handoff_path": str(path)}
