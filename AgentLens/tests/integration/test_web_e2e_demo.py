"""--demo flag: store points at a temp copy of bundled demo data."""
from __future__ import annotations

import shutil


def test_demo_flag_seeds_temp_home():
    from agentlens.commands.serve import _materialise_demo_home

    home, marker = _materialise_demo_home()
    try:
        assert home.is_dir()
        assert (home / "runs").is_dir()
        assert marker.exists()
    finally:
        shutil.rmtree(home, ignore_errors=True)
