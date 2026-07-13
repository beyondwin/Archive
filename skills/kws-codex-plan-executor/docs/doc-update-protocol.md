# Documentation Update Protocol

The active CPE 4 documentation set is intentionally small. Update behavior and
its sole owning document together.

| File | Sole responsibility |
| --- | --- |
| SKILL.md | routing, public contract, roles, authority, verification |
| README.md | operator usage, commands, statuses, artifact layout |
| ARCHITECTURE.md | module, queue, role, and trust boundaries |
| HISTORY.md | released breaking changes |
| references/change-protocol.md | RED, GREEN, verification workflow |
| references/common-mistakes.md | operational misuse and authority misuse |
| references/execution-cycle.md | mapping through final integration |
| references/prompt-export-checklist.md | export-only guarantees |
| references/state-schema.md | durable files, events, artifacts, replay |
| docs/evals-and-verification.md | six checks, coverage, timing |
| docs/risks-limitations-deferrals.md | known risks and explicit deferrals |
| docs/user-guide.ko.md | Korean operator workflow |

Avoid copying a contract into several files. Link to the owner and keep the
other document focused on its audience.

For every behavior change:

1. identify the owning document;
2. change or add a focused deterministic test;
3. update that document in the same commit;
4. check every referenced command and path against the current tree;
5. run the six-check suite, syntax checks, CLI help, and git diff --check;
6. review the final tracked file inventory and broken relative links.

Documentation-only changes still require git diff --check and manual path/link
inspection. Do not add wording scanners or generated documentation as a
runtime quality gate. Historical implementation detail belongs in Git history,
not an active compatibility route.
