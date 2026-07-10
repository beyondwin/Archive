# Local Environment Preflight

Before allocating an execution run, check required files, git identity and dirty
scope, executable dependencies, declared eval dependencies, model/host
capability, and repository-specific instructions. Preflight is diagnostic and
read-only.

Missing dependencies return the exact requirement and preparation command.
CPE does not install packages, edit operator configuration, or create optional
tool state automatically. A missing required capability blocks before edits;
an explicitly optional observation may be recorded as an advisory.
