Source-of-truth: the design document wins when this reference and code disagree.

# Watchdog

The watchdog detects worker stall, wall-clock timeout, missing heartbeat, and retry exhaustion.

Actions escalate from observe to retry to recovery worker to blocked run.
