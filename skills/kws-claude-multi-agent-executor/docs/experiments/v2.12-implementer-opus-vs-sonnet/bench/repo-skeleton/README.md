# Benchmark repo skeleton

Copy this directory's contents into a fresh empty directory, run `git init`, and commit the result. The orchestrator will operate on that repo.

```bash
mkdir -p ~/scratch/v2.12-bench
cp -R bench/repo-skeleton/. ~/scratch/v2.12-bench/
cd ~/scratch/v2.12-bench
git init -q && git add -A && git commit -q -m "chore: benchmark skeleton"
```

No venv needed — `pyproject.toml` declares `pythonpath = ["src"]` for pytest, and the plan's `python -c` acceptance criteria use `PYTHONPATH=src` explicitly. Ensure `pytest` is on PATH (`python3 -m pytest --version`) before kicking off runs.

After that, invoke the skill from `~/scratch/v2.12-bench` with `plan=<...>/bench/plan.md spec=<...>/bench/spec.md` plus the `implementer_model` arg for the arm you want.
