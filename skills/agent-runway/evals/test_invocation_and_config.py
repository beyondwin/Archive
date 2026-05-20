from __future__ import annotations

from pathlib import Path

from agentrunway.config import BuiltinProfiles, load_effective_config, resolve_reasoning
from agentrunway.invocation import parse_key_value_invocation, parse_run_args


def test_parse_skill_key_value_invocation() -> None:
    parsed = parse_key_value_invocation(
        "plan=plans/auth.md spec=specs/auth.md runtime=codex worker_reasoning=high"
    )
    assert parsed["plan"] == "plans/auth.md"
    assert parsed["spec"] == "specs/auth.md"
    assert parsed["runtime"] == "codex"
    assert parsed["worker_reasoning"] == "high"


def test_parse_run_args_defaults_to_codex_profile() -> None:
    args = parse_run_args(["run", "--plan", "p.md", "--spec", "s.md"])
    assert args.plan == Path("p.md")
    assert args.spec == Path("s.md")
    assert args.model_profile == "codex-default"
    assert args.apply_to_source is False


def test_config_precedence_invocation_over_agentrunway_yaml(tmp_path: Path) -> None:
    (tmp_path / "agentrunway.yaml").write_text(
        "default_profile: claude-default\n"
        "profiles:\n"
        "  custom:\n"
        "    orchestrator: {runtime: codex, model: gpt-5.5, reasoning_effort: highest}\n",
        encoding="utf-8",
    )
    cfg = load_effective_config(tmp_path, {"model_profile": "codex-default"})
    assert cfg.default_profile == "codex-default"


def test_reasoning_resolution_maps_xhigh_alias() -> None:
    assert resolve_reasoning("codex", "xhigh") == ("highest", "xhigh")
    assert resolve_reasoning("claude", "highest") == ("highest", "high")


def test_builtin_profiles_are_explicit() -> None:
    profiles = BuiltinProfiles.default()
    assert profiles["codex-default"].orchestrator.runtime == "codex"
    assert profiles["codex-default"].orchestrator.reasoning_effort == "highest"
    assert profiles["claude-default"].workers["default"].runtime == "claude"
