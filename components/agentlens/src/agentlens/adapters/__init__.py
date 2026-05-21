"""AgentLens adapter modules (spec §5.16, §5.17).

Adapters wire AgentLens into agent runtimes. The core process wrapper
(:mod:`agentlens.adapters.process`) is the M5 ``agentlens run`` primitive
that spawns a child command and (in later tasks) records its lifecycle.
"""
