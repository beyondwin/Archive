# Common Mistakes

Recurring errors observed during orchestrated plan execution. Each entry describes the mistake, why it happens, and how to avoid it.

### Docker exit 137 mistaken for compile failure

When a multi-stage Docker build fails after the compilation step with no compiler error and an exit code of 137, the container was OOM-killed by the kernel, not the build. Check `docker inspect ... .State.OOMKilled`. Re-running with more memory resolves it; treating it as a compile failure burns Implementer retries.

### Gradle daemon disappearance without category check

"Daemon disappeared" is a symptom, not a cause. The cause lives in `~/.gradle/daemon/<version>/daemon-*.out.log`. Categorize as `gradle_metaspace`, OOM, or daemon crash *before* assuming the project's code broke the daemon.

<!-- for_next_tasks: Task 8 should append additional common-mistake entries below this point -->
