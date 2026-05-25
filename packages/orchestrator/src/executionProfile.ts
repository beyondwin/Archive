export type ProviderName = "codex" | "claude" | "fake";
export type ExecutionMode = "multi-agent" | "single-agent";
export type ReasoningLevel = "medium" | "high" | "xhigh";
export type WorkerRoleSlot = "implement" | "review" | "verify_assist";

export interface AgentProfile {
  model: string;
  reasoning: ReasoningLevel;
}

export type RoleRouting = Record<WorkerRoleSlot, AgentProfile>;

export interface ExecutionProfile {
  provider: ProviderName;
  execution_mode: ExecutionMode;
  main: AgentProfile;
  subagent: AgentProfile;
  // Optional for back-compat with literal constructions elsewhere.
  // resolveExecutionProfile() always populates it; consumers should treat a
  // missing value as "fall back to subagent" via roleProfileFor().
  roles?: RoleRouting;
  evidence_event_type: "runway.execution_profile_selected";
}

export interface ProfileOverride {
  provider?: ProviderName;
  execution_mode?: ExecutionMode;
  main_model?: string;
  main_reasoning?: ReasoningLevel;
  subagent_model?: string;
  subagent_reasoning?: ReasoningLevel;
  role_models?: Partial<Record<WorkerRoleSlot, string>>;
  role_reasoning?: Partial<Record<WorkerRoleSlot, ReasoningLevel>>;
}

export const ROLE_SLOTS: readonly WorkerRoleSlot[] = ["implement", "review", "verify_assist"];

export const defaultProfiles: Record<ProviderName, ExecutionProfile> = {
  codex: {
    provider: "codex",
    execution_mode: "multi-agent",
    main: { model: "gpt-5.5", reasoning: "xhigh" },
    subagent: { model: "gpt-5.5", reasoning: "high" },
    roles: {
      implement: { model: "gpt-5.5", reasoning: "high" },
      review: { model: "gpt-5.5", reasoning: "high" },
      verify_assist: { model: "gpt-5.5", reasoning: "high" }
    },
    evidence_event_type: "runway.execution_profile_selected"
  },
  claude: {
    provider: "claude",
    execution_mode: "multi-agent",
    main: { model: "opus", reasoning: "high" },
    subagent: { model: "opus", reasoning: "high" },
    roles: {
      implement: { model: "opus", reasoning: "high" },
      review: { model: "opus", reasoning: "high" },
      verify_assist: { model: "opus", reasoning: "high" }
    },
    evidence_event_type: "runway.execution_profile_selected"
  },
  fake: {
    provider: "fake",
    execution_mode: "multi-agent",
    main: { model: "fake", reasoning: "medium" },
    subagent: { model: "fake", reasoning: "medium" },
    roles: {
      implement: { model: "fake", reasoning: "medium" },
      review: { model: "fake", reasoning: "medium" },
      verify_assist: { model: "fake", reasoning: "medium" }
    },
    evidence_event_type: "runway.execution_profile_selected"
  }
};

export function resolveExecutionProfile(...layers: Array<ProfileOverride | undefined>): ExecutionProfile {
  const merged = mergeProfileOverrides(layers);
  const base = defaultProfiles[merged.provider ?? "codex"];
  const main: AgentProfile = {
    model: merged.main_model ?? base.main.model,
    reasoning: merged.main_reasoning ?? base.main.reasoning
  };
  const subagent: AgentProfile = {
    model: merged.subagent_model ?? base.subagent.model,
    reasoning: merged.subagent_reasoning ?? base.subagent.reasoning
  };
  const roles: RoleRouting = {
    implement: resolveRoleSlot(base, "implement", merged, subagent),
    review: resolveRoleSlot(base, "review", merged, subagent),
    verify_assist: resolveRoleSlot(base, "verify_assist", merged, subagent)
  };
  return {
    provider: merged.provider ?? base.provider,
    execution_mode: merged.execution_mode ?? base.execution_mode,
    main,
    subagent,
    roles,
    evidence_event_type: "runway.execution_profile_selected"
  };
}

function mergeProfileOverrides(layers: Array<ProfileOverride | undefined>): ProfileOverride {
  // Layers are applied in order, with later ones taking precedence by virtue of
  // Object.assign on the reversed list (matches existing semantics for the
  // primitive fields). Map overrides (role_models / role_reasoning) need to
  // merge per-key rather than replace wholesale so layered profiles compose.
  const reversed = [...layers].reverse();
  const merged: ProfileOverride = Object.assign({}, ...reversed) as ProfileOverride;
  const role_models: ProfileOverride["role_models"] = {};
  const role_reasoning: ProfileOverride["role_reasoning"] = {};
  for (const layer of reversed) {
    if (!layer) continue;
    if (layer.role_models) {
      for (const slot of ROLE_SLOTS) {
        const value = layer.role_models[slot];
        if (value !== undefined) role_models[slot] = value;
      }
    }
    if (layer.role_reasoning) {
      for (const slot of ROLE_SLOTS) {
        const value = layer.role_reasoning[slot];
        if (value !== undefined) role_reasoning[slot] = value;
      }
    }
  }
  if (Object.keys(role_models).length > 0) merged.role_models = role_models; else delete merged.role_models;
  if (Object.keys(role_reasoning).length > 0) merged.role_reasoning = role_reasoning; else delete merged.role_reasoning;
  return merged;
}

function resolveRoleSlot(
  base: ExecutionProfile,
  slot: WorkerRoleSlot,
  merged: ProfileOverride,
  subagent: AgentProfile
): AgentProfile {
  const baseRole = base.roles?.[slot] ?? base.subagent;
  // Priority (highest first): --role-model / --role-reasoning,
  // then --subagent-model / --subagent-reasoning, then profile default.
  const model = merged.role_models?.[slot]
    ?? merged.subagent_model
    ?? baseRole.model
    ?? subagent.model;
  const reasoning = merged.role_reasoning?.[slot]
    ?? merged.subagent_reasoning
    ?? baseRole.reasoning
    ?? subagent.reasoning;
  return { model, reasoning };
}

export function roleProfileFor(profile: ExecutionProfile, role: WorkerRoleSlot): AgentProfile {
  return profile.roles?.[role] ?? profile.subagent;
}

export function isWorkerRoleSlot(value: unknown): value is WorkerRoleSlot {
  return value === "implement" || value === "review" || value === "verify_assist";
}

export function isReasoningLevel(value: unknown): value is ReasoningLevel {
  return value === "medium" || value === "high" || value === "xhigh";
}
