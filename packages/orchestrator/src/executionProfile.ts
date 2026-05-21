export type ProviderName = "codex" | "claude" | "fake";
export type ExecutionMode = "multi-agent" | "single-agent";
export type ReasoningLevel = "medium" | "high" | "xhigh";

export interface AgentProfile {
  model: string;
  reasoning: ReasoningLevel;
}

export interface ExecutionProfile {
  provider: ProviderName;
  execution_mode: ExecutionMode;
  main: AgentProfile;
  subagent: AgentProfile;
  evidence_event_type: "runway.execution_profile_selected";
}

export interface ProfileOverride {
  provider?: ProviderName;
  execution_mode?: ExecutionMode;
  main_model?: string;
  main_reasoning?: ReasoningLevel;
  subagent_model?: string;
  subagent_reasoning?: ReasoningLevel;
}

export const defaultProfiles: Record<ProviderName, ExecutionProfile> = {
  codex: {
    provider: "codex",
    execution_mode: "multi-agent",
    main: { model: "gpt-5.5", reasoning: "xhigh" },
    subagent: { model: "gpt-5.5", reasoning: "high" },
    evidence_event_type: "runway.execution_profile_selected"
  },
  claude: {
    provider: "claude",
    execution_mode: "multi-agent",
    main: { model: "opus", reasoning: "high" },
    subagent: { model: "opus", reasoning: "high" },
    evidence_event_type: "runway.execution_profile_selected"
  },
  fake: {
    provider: "fake",
    execution_mode: "multi-agent",
    main: { model: "fake", reasoning: "medium" },
    subagent: { model: "fake", reasoning: "medium" },
    evidence_event_type: "runway.execution_profile_selected"
  }
};

export function resolveExecutionProfile(...layers: Array<ProfileOverride | undefined>): ExecutionProfile {
  const merged = Object.assign({}, ...layers.reverse()) as ProfileOverride;
  const base = defaultProfiles[merged.provider ?? "codex"];
  return {
    provider: merged.provider ?? base.provider,
    execution_mode: merged.execution_mode ?? base.execution_mode,
    main: {
      model: merged.main_model ?? base.main.model,
      reasoning: merged.main_reasoning ?? base.main.reasoning
    },
    subagent: {
      model: merged.subagent_model ?? base.subagent.model,
      reasoning: merged.subagent_reasoning ?? base.subagent.reasoning
    },
    evidence_event_type: "runway.execution_profile_selected"
  };
}
