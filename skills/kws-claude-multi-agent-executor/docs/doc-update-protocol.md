# Doc-update protocol

A per-change-type checklist saying *exactly* which docs to touch when you
ship that kind of change. The goal: docs stay current without anyone
having to remember "what should I update?" — the protocol tells you.

This file is the cognitive aid; [`../evals/check_doc_freshness.py`](../evals/check_doc_freshness.py)
is the automated guard (catches the most regression-prone drift even if
this protocol is skipped).

For the broader contributing protocol see [`../AGENTS.md`](../AGENTS.md).

---

## Table of contents

- [Quick lookup: what change type am I making?](#quick-lookup)
- [Detailed checklists per change type](#detailed-checklists)
- [Freshness eval — what's automated](#freshness-eval)
- [Worked examples](#worked-examples)

---

## Quick lookup

| If you're changing... | Required updates | Detail |
|------------------------|------------------|--------|
| Skill behavior (SKILL.md edit) | SKILL.md version + README + HISTORY + ARCHITECTURE | [Skill behavior](#skill-behavior-change) |
| A sub-agent prompt | references/<role>-prompt.md + check_skill_contract.py if structure changes + experiment record if ≥50 lines | [Sub-agent prompt](#sub-agent-prompt-change) |
| Helper script | scripts/append_learning_event.py + check_learning_log.py if schema changes + references/learning-log.md | [Helper script](#helper-script-change) |
| Adding a learning-log event type | All 5 places in [extend-event-type.md](./how-to/extend-event-type.md) | [Event type addition](#event-type-addition) |
| Adding an eval fixture | evals/fixtures/<N>.yaml + baselines/v<X>.json + maybe HISTORY entry | [Fixture addition](#fixture-addition) |
| Discovering a new risk | docs/risks-and-limitations.md (always) + tracking in deferred-candidates if action deferred | [Risk discovery](#risk-discovery) |
| Closing a known risk | docs/risks-and-limitations.md (move to CLOSED) + HISTORY entry if shipped fix | [Risk closure](#risk-closure) |
| Making a design decision | docs/experiments/<v>/decisions/D###-*.md + decision-log.md index row | [Design decision](#design-decision) |
| Deferring a candidate | docs/deferred-candidates.md (add with revisit criteria) | [Candidate deferral](#candidate-deferral) |
| Version bump (any version) | SKILL.md frontmatter + README + HISTORY + snapshots/ (minor+) | [Version bump](#version-bump) |
| New experiment | docs/experiments/v<X>-<name>/ + docs/experiments/README.md index + HISTORY §3 row | [New experiment](#new-experiment) |
| Closing an experiment | finalize findings/ + JOURNAL close-out + HISTORY §3 row update + decision-log if shipped | [Experiment closure](#experiment-closure) |
| Major refactor / restructure | All of the above, plus a fresh snapshot in docs/snapshots/ | [Major refactor](#major-refactor) |
| Trivial fix (typo, formatting) | Just commit. No doc updates. | [Trivial change](#trivial-change) |

---

## Detailed checklists

### Skill behavior change

**Definition**: any edit to `SKILL.md` that changes runtime semantics
(phase steps, dispatch logic, scoring thresholds, escalation routing).

**Required updates**:

- [ ] `SKILL.md` — the edit itself + frontmatter `metadata.version` bump
- [ ] `README.md` — current version line
- [ ] `skills/README.md` — only if the Archive-level skill inventory changed
- [ ] `HISTORY.md` §1 — new version entry with: what changed, why,
      what's tested, what's NOT changed/deferred
- [ ] `ARCHITECTURE.md` — sync any section affected by the change
      (per AGENTS.md "ARCHITECTURE.md sync (REQUIRED on behavior
      changes)" rule)
- [ ] If contract-relevant: extend `evals/check_skill_contract.py` with
      a check that locks in the new behavior

**Optional but recommended**:
- [ ] Experiment record if ≥50 lines or has a hypothesis
- [ ] Snapshot file under `docs/snapshots/v<X>.md` if minor-version bump

### Sub-agent prompt change

**Definition**: edit to any `references/<role>-prompt.md`.

**Required updates**:

- [ ] The prompt file
- [ ] `evals/check_skill_contract.py` — if the change affects an
      asserted token (e.g., adding/removing a `Skill(...)` invocation,
      changing the output format), extend the contract check
- [ ] `references/learning-log.md` — if the prompt's candidate-emit
      contract changed

**Optional**:
- [ ] HISTORY.md entry — if user-visible behavior change
- [ ] Experiment record — if non-trivial (e.g., v2.9.0 Spec Coverage Walk)

### Helper script change

**Definition**: edit to `scripts/append_learning_event.py`.

**Required updates**:

- [ ] The script itself
- [ ] `evals/check_learning_log.py` — add tests covering the new behavior
- [ ] `references/learning-log.md` — if schema or subcommand changed

**Optional**:
- [ ] HISTORY.md entry — if user-visible
- [ ] Experiment record — if schema-breaking

### Event type addition

Use the full step-by-step at [`how-to/extend-event-type.md`](./how-to/extend-event-type.md).

**Required (5 places)**:

- [ ] `references/learning-log.md` — schema doc
- [ ] `scripts/append_learning_event.py` — `EVENT_TYPES` set
- [ ] `evals/check_learning_log.py` — positive + negative test cases
- [ ] `evals/check_skill_contract.py` — `EVENT_TYPES` list
- [ ] At least one `references/<role>-prompt.md` — emitter

### Fixture addition

Use the full step-by-step at [`how-to/add-a-fixture.md`](./how-to/add-a-fixture.md).

**Required**:

- [ ] `evals/fixtures/0N-<slug>.yaml` — the fixture
- [ ] `evals/baselines/v<current>.json` — captured first-run baseline
- [ ] Spec-vs-rubric audit (no hidden assumptions)

**Optional**:
- [ ] `evals/README.md` — update index if format docs change
- [ ] HISTORY.md entry — if shipping with a version

### Risk discovery

**Required**:

- [ ] `docs/risks-and-limitations.md` — add new entry with status,
      manifestation, mitigation, tracking pointer
- [ ] If the risk needs deferred action: also add to
      `docs/deferred-candidates.md` with revisit criteria

### Risk closure

**Required**:

- [ ] `docs/risks-and-limitations.md` — move entry to "Closed/resolved"
      section with `verified by` link
- [ ] `HISTORY.md` entry — if the closure was shipped as part of a
      version bump

### Design decision

**Required**:

- [ ] `docs/experiments/<v>/decisions/D###-<slug>.md` — the ADR itself
- [ ] `docs/decision-log.md` — add row to the experiment's section
- [ ] If decision overturns a prior ADR: also update the "Overturned"
      table in decision-log.md

### Candidate deferral

**Required**:

- [ ] `docs/deferred-candidates.md` — add section with proposed
      change, origin, why deferred, revisit criteria (concrete trigger)

**Optional**:
- [ ] `docs/decision-log.md` overturned table if it supersedes a prior decision

### Version bump

Whether patch / minor / major bump:

**Required**:

- [ ] `SKILL.md` frontmatter `metadata.version`
- [ ] `README.md` current version line
- [ ] `skills/README.md` only if the Archive-level inventory changed
- [ ] `HISTORY.md` §1 — new entry

**For minor+ bump (e.g., 2.8 → 2.9)**:
- [ ] `docs/snapshots/v<X>.md` — full state snapshot at ship time

**For major bump (e.g., 2.X → 3.0)**:
- [ ] All of the above plus a migration note in HISTORY.md

### New experiment

**Required**:

- [ ] `docs/experiments/v<X>-<name>/{README.md, JOURNAL.md, decisions/, findings/}`
      — created from `docs/experiments/_template/`
- [ ] `docs/experiments/README.md` — add row to the index table
- [ ] `HISTORY.md` §3 — add experiment row (status, link)

### Experiment closure

**Required**:

- [ ] `docs/experiments/<v>/findings/F00N-<close-out>.md` — final
      findings doc
- [ ] `docs/experiments/<v>/JOURNAL.md` — close-out section with
      outcome, what learned, residual risks
- [ ] `docs/experiments/<v>/README.md` — status field updated to
      CLOSED with outcome
- [ ] `docs/experiments/README.md` — index status updated
- [ ] `HISTORY.md` §3 — experiment row updated
- [ ] If shipped change: also do "Skill behavior change" checklist
- [ ] If decision overturned: update decision-log.md Overturned table

### Major refactor

Treat as compound change: do every relevant checklist above, AND:

- [ ] Add a fresh `docs/snapshots/v<X>.md` capturing the new state
- [ ] Open a v<X>-refactor experiment record if not already done
- [ ] Run full preflight + at least 2 fixture reps before commit

### Trivial change

Typos, whitespace, formatting, comment fixes:

- [ ] Just commit. No doc updates needed.

If you're unsure whether it's trivial → it's not trivial. Apply one of
the above.

---

## Freshness eval — what's automated

[`../evals/check_doc_freshness.py`](../evals/check_doc_freshness.py) runs
deterministic checks for the most regression-prone drift:

1. **Version consistency** — `SKILL.md` frontmatter version matches the skill
   README current-version line.
2. **Internal markdown links** — every ``[text](./path.md)`` or
   ``[text](../path.md)`` reference resolves to an existing file.
3. **HISTORY.md entry present** — for the current `SKILL.md` version,
   `HISTORY.md` §1 has a matching entry.
4. **Latest snapshot exists** — for the current minor version (e.g.,
   2.9.X for 2.9.0), `docs/snapshots/v2.9.0.md` exists.
5. **Decision-log indexes ADRs** — every D### file under
   `docs/experiments/*/decisions/` appears in `docs/decision-log.md`.
6. **Stale markers** — `TODO`, `FIXME`, `XXX`, `WIP:` count under
   `docs/` and `references/`. Reports count; doesn't fail.

The eval is **non-blocking by default**: it reports drift and exit
code 0 so `evals/run.sh` continues. To make blocking, set
`DOC_FRESHNESS_STRICT=1` in your shell before running the harness.

Run standalone:

```bash
python3 evals/check_doc_freshness.py
# or with strict mode
DOC_FRESHNESS_STRICT=1 python3 evals/check_doc_freshness.py
```

---

## Worked examples

### Example 1 — User asks "fix a typo in the Reviewer prompt"

- Edit `references/reviewer-prompt.md`.
- Trivial change. Commit. No doc updates.

### Example 2 — User asks "promote Step 7.5 to mandatory" (was the actual v2.8.1)

This is a skill behavior change. Checklist:

- [x] `SKILL.md` Step 7.5 edited
- [x] Frontmatter version 2.8.0 → 2.8.1
- [x] `README.md` current version line bumped
- [x] `HISTORY.md` §1 v2.8.1 entry added with what + why + verified-by
- [x] `evals/check_skill_contract.py` 18th check added
- [x] `evals/run.sh` adherence marker grep added (eval is contract-adjacent)
- [x] `docs/risks-and-limitations.md` "★★ Adherence" updated with mitigation
- [x] Experiment record NOT needed (empirical fix, inline rationale)
- [x] Snapshot NOT needed (patch bump, not minor)

### Example 3 — User asks "add a fixture for concurrency edge cases"

Fixture addition. Checklist:

- [ ] Decision audit: is there measured evidence?
- [ ] If yes: write `evals/fixtures/09-concurrency-edge-cases.yaml`
- [ ] Run preflight + first run; capture baseline
- [ ] Spec-vs-rubric audit
- [ ] Commit
- [ ] Optional: open experiment record if non-trivial design

### Example 4 — User asks "add `subagent_dispatched` event type"

Event type addition. Use [`how-to/extend-event-type.md`](./how-to/extend-event-type.md):

- [ ] `references/learning-log.md` — schema doc updated (11 event types now)
- [ ] `scripts/append_learning_event.py` — `EVENT_TYPES` set + type-specific validation
- [ ] `evals/check_learning_log.py` — positive + negative tests
- [ ] `evals/check_skill_contract.py` — `EVENT_TYPES` list extended
- [ ] At least one `references/<role>-prompt.md` — emitter wired
- [ ] Version bump (minor, since schema extended)
- [ ] HISTORY.md entry
- [ ] Snapshot if minor bump

---

## When the protocol is wrong

This protocol is a heuristic. If you find yourself:

- Bumping versions without changing user-visible behavior — the
  protocol is too prescriptive; drop the bump.
- Updating docs that won't be read until the next major refactor —
  the protocol forces noise; downgrade the requirement.
- Skipping a step because it "feels obvious" — that's the protocol
  doing its job; don't skip.

When the friction is too high: open a PR amending this file with the
relaxation + the rationale. Doc protocol is not sacred; it's a tool.
