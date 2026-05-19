"""Release-path guards for the dashboard wheel workflow."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent


def test_makefile_wheel_path_uses_python_pip_instead_of_uv():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "uv pip" not in makefile
    assert "$(PYTHON) -m ensurepip --upgrade" in makefile
    assert "$(PYTHON) -m pip install" in makefile


def test_dashboard_ci_builds_wheel_and_smoke_checks_packaged_assets():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "dashboard-ci.yml"
    ).read_text(encoding="utf-8")

    assert "make wheel" in workflow
    assert "unzip -l dist/agentlens-0.1.0-py3-none-any.whl" in workflow
    assert "agentlens/web_assets/" in workflow
    assert "agentlens/demo_data/" in workflow
