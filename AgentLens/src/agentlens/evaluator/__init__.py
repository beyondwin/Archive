"""AgentLens evaluator package (spec §S1.6.16, §S1.7.3).

For v0 the evaluator is a stub with two checks: ``schema_valid`` and
``final_present``. See :func:`agentlens.evaluator.engine.evaluate`.
"""
from .engine import evaluate

__all__ = ["evaluate"]
