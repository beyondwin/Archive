import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";
import { appendEvent as appendJournalEvent, runPaths } from "@waygent/lens-store";
import { writeRunStateV2 } from "./runState";

export interface RunExecutionContextInput {
  root: string;
  state: WaygentRunStateV2;
  next_sequence: number;
}

export interface RunExecutionContext {
  readonly root: string;
  readonly run_id: string;
  readonly state: WaygentRunStateV2;
  appendEvent(build: (sequence: number) => AgentLensEvent): AgentLensEvent;
  mutateState(mutator: (state: WaygentRunStateV2) => void): void;
  flushState(): void;
  nextSequence(): number;
}

export function createRunExecutionContext(input: RunExecutionContextInput): RunExecutionContext {
  let sequence = input.next_sequence;
  const state = input.state;
  const eventsPath = runPaths(input.root, state.run_id).events;

  function nextSequence(): number {
    const current = sequence;
    sequence += 1;
    return current;
  }

  return {
    root: input.root,
    run_id: state.run_id,
    state,
    appendEvent(build) {
      const event = build(nextSequence());
      appendJournalEvent(eventsPath, event);
      return event;
    },
    mutateState(mutator) {
      mutator(state);
      state.timestamps.updated_at = new Date().toISOString();
    },
    flushState() {
      writeRunStateV2(input.root, state);
    },
    nextSequence
  };
}
