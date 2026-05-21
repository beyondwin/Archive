"""AgentLens CLI subcommand modules (spec §10.1).

Each module exports a Typer-friendly callable (decorated as a command in
:mod:`agentlens.cli`). Submodules use lazy imports so that ``--help`` and
test collection stay cheap.
"""
