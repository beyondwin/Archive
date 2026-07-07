# v3.0-deterministic-kernel

**Status**: COMPLETE — SHIP recommended (live-smoke pending; see findings/F01-close-out.md)
**Branch**: `experiment/cme-v3-deterministic-kernel`
**Production baseline**: main

## Goal

Rebuild the kws-claude-multi-agent-executor skill around a deterministic Python kernel that owns judgment and record-keeping. Current skill suffers from freeze-skip regression class. Test hypothesis: moving determination and record-keeping to kernel layer eliminates this failure class.

## Hypothesis

판정·기록을 커널로 이관하면 프로즈-스킵 회귀 클래스가 소멸한다

(If we move judgment and record-keeping logic into the deterministic kernel layer, the freeze-skip regression class will disappear. This is because the kernel will have atomic state transitions and can accurately track which decision was made at which point, preventing the async race conditions that cause the current failures.)

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [Spec: 2026-07-06-cme-v3-deterministic-kernel-design.md](../../../../../docs/superpowers/specs/2026-07-06-cme-v3-deterministic-kernel-design.md)
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| T1: Kernel scaffold + atomic state I/O | COMPLETE | |
| T2: State schema v3 + init module | COMPLETE | |
| T3: Migration bridge | COMPLETE | |
| T4: Plan parser | COMPLETE | |
| T5: Validator + schemas | COMPLETE | |
| T6: Transitions module | COMPLETE | |
| T7: Dispatch module (headless-first) | COMPLETE | |
| T8: Ledger + events modules | COMPLETE | |
| T9: kernel.py CLI (init/next/submit/check-stop/finalize/inspect/resolve-escalation) | COMPLETE | |
| T10: Packets module | COMPLETE | |
| T11: Gate module | COMPLETE | |
| T12: Recovery module | COMPLETE | |
| T13: Drift module | COMPLETE | |
| T14: Quality module + Stop hook cutover | COMPLETE | |
| T15: SKILL.md cutover to v3.0 | COMPLETE | |
| T16: Eval rebaseline + docs sync + close-out | COMPLETE | |

## Decisions index

| ADR | Subject | Status |
|-----|---------|--------|
| [D001-local-fallback-adaptation.md](./decisions/D001-local-fallback-adaptation.md) | Local fallback for operator-review escalation vs full-context orchestrator implements | Shipped |

## Findings index

| Finding | Subject |
|---------|---------|
| [F01-close-out.md](./findings/F01-close-out.md) | v3.0 close-out: SHIP/SKIP recommendation + Success Criteria evidence |
