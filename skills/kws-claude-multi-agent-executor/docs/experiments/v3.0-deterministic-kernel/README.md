# v3.0-deterministic-kernel

**Status**: In progress
**Branch**: `experiment/cme-v3-deterministic-kernel`
**Production baseline**: main

## Goal

Rebuild the kws-claude-multi-agent-executor skill around a deterministic Python kernel that owns judgment and record-keeping. Current skill suffers from freeze-skip regression class. Test hypothesis: moving determination and record-keeping to kernel layer eliminates this failure class.

## Hypothesis

판정·기록을 커널로 이관하면 프로즈-스킵 회귀 클래스가 소멸한다

(If we move judgment and record-keeping logic into the deterministic kernel layer, the freeze-skip regression class will disappear. This is because the kernel will have atomic state transitions and can accurately track which decision was made at which point, preventing the async race conditions that cause the current failures.)

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [Spec: 2026-07-06-cme-v3-deterministic-kernel-design.md](../../../docs/superpowers/specs/2026-07-06-cme-v3-deterministic-kernel-design.md)
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| T1: Kernel scaffold + atomic state I/O | In progress | |
| T2-T16 | Pending | |

## Decisions index

(One line per ADR. Update as you write them.)

## Findings index

(One line per finding doc.)
