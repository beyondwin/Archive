Source-of-truth: the design document wins when this reference and code disagree.

# Watchdog

The watchdog is runner-driven polling. It detects worker stall, wall-clock
timeout, missing heartbeat, stdout/stderr mtime drift, output artifact absence,
and retry exhaustion.

Actions escalate from observe to cancel, retry, recovery worker, or blocked run.
Classification maps successful process exit without `worker_result.json` to
malformed result, nonzero exit to adapter crash, timed-out process lifecycle to
timeout, and missing process handles to stalled.
