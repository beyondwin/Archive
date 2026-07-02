# Release Process

This is the release contract for `kws-codex-plan-executor`.

## Version Source Of Truth

The official CPE package version is `metadata.version` in `SKILL.md`.
`HISTORY.md`, `evals/baselines/v<version>.json`, and
`docs/verification-log.md` must agree with that version when a release is
closed.

`docs/experiments/v*` files are design and implementation records. They are not
the official release source of truth.

## Version Bump Rules

Use semantic versioning.

`major` changes break existing state consumers, prompt or headless output
schema, invocation semantics, worktree/runtime layout, deterministic fixture
expectations, or downstream operator workflows.

`minor` changes add compatible behavior: new features, optional state fields,
scripts, evals, prompt or handoff surfaces, inspection, readiness, replay, or
other compatible runtime behavior.

`patch` changes fix bugs, correct docs that disagree with behavior, stabilize
evals, or make compatible corrections to existing behavior.

`no bump` is allowed only for pure documentation cleanup, typo fixes, and
verification-log additions that do not change runtime behavior, scripts, prompt
output, eval behavior, package metadata, or public skill metadata.

## Unreleased Policy

Accumulate in-progress changes under `HISTORY.md` `Unreleased` entries.
Close a release by moving the relevant entries into a dated version section,
for example `## 2.25.0 - 2026-07-03`.

## Baseline Rules

The full harness reads `SKILL.md` version and compares generated fixture output
with `evals/baselines/v<version>.json`.

Run `./evals/run.sh --update-baseline` only after reviewing the intended
fixture output change. Do not update a baseline to hide a failing or
unexplained behavior change.

`check_release_contract.py` is read-only and must never write baseline files.

## Verification Log

Append `docs/verification-log.md` whenever this skill package changes. Keep the
entry compact:

- date and local timezone
- branch and commit when known
- scope of the change
- commands run
- result of each command
- skipped checks with reasons
- residual risk or follow-up

## Release Checklist

1. Decide `major`, `minor`, `patch`, or `no bump`.
2. Update `SKILL.md metadata.version` when a bump is required.
3. Close relevant `HISTORY.md` entries under the release version.
4. Update docs according to `docs/doc-update-protocol.md`.
5. Run `./evals/run.sh --update-baseline` when fixture output intentionally
   changes or when a new version needs its baseline.
6. Review the baseline diff.
7. Run `./evals/run.sh`.
8. Run `python3 -m py_compile scripts/*.py evals/*.py`.
9. Run `bash -n evals/run.sh`.
10. Run `git diff --check`.
11. Append `docs/verification-log.md`.
