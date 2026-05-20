from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REFERENCE_FILES = {
    "protocol.md": ("Host session", "Runner", "Worker"),
    "model-profiles.md": ("codex-default", "claude-default", "reasoning_effort"),
    "task-packet.md": ("task_packet.v1", "file_claims", "acceptance_commands"),
    "file-claims.md": ("owned", "shared_append", "forbidden"),
    "runtime-adapters.md": ("AdapterCapabilities", "network_egress", "WorkerHandle"),
    "agentlens-events.md": ("kws.kao", "redaction", "best-effort"),
    "superpowers-bootstrap.md": ("using-superpowers", "test-driven-development", "method_audit"),
    "merge-queue.md": ("review", "verification", "cherry-pick"),
    "context-policy.md": ("snapshot", "compaction", "rotation"),
    "worktree-policy.md": ("workspace_id", "dirty source", "registry.sqlite"),
    "watchdog.md": ("stall", "timeout", "retry"),
    "failure-policy.md": ("failure", "retry", "blocked"),
}


def test_reference_docs_exist_and_cover_required_terms() -> None:
    for name, terms in REFERENCE_FILES.items():
        text = (ROOT / "references" / name).read_text(encoding="utf-8")
        assert "Source-of-truth" in text
        for term in terms:
            assert term in text


def test_skill_contract_names_runner_and_agentlens_namespace() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/kao.py" in text
    assert "kws.kao.*" in text
    assert "using-superpowers" in text
