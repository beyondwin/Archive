const idPattern = "^[a-z][a-z0-9_:-]{2,127}$";
const isoTimestamp = "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$";
const noLegacyNamespace = "^(?!kws-cpe\\.)(?!kws-cme\\.)(?!kws\\.orchestrator\\.).+";

export const artifactReferenceSchema = {
  type: "object",
  additionalProperties: false,
  required: ["path", "sha256", "byte_length", "media_type"],
  properties: {
    artifact_id: { type: "string", pattern: idPattern, nullable: true },
    path: { type: "string", minLength: 1 },
    sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    byte_length: { type: "integer", minimum: 0 },
    media_type: { type: "string", minLength: 1 }
  }
} as const;

export const agentLensEventSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "event_id",
    "agentlens_run_id",
    "orchestrator_run_id",
    "producer",
    "event_type",
    "occurred_at",
    "sequence",
    "phase",
    "outcome",
    "severity",
    "trust_impact",
    "summary",
    "payload"
  ],
  properties: {
    schema: { const: "agentlens.event.v3" },
    event_id: { type: "string", pattern: idPattern },
    agentlens_run_id: { type: "string", pattern: idPattern },
    orchestrator_run_id: { type: "string", pattern: idPattern },
    producer: {
      type: "object",
      additionalProperties: false,
      required: ["name", "kind", "version"],
      properties: {
        name: { type: "string", minLength: 1 },
        kind: { enum: ["orchestrator", "kernel", "provider", "lens", "policy"] },
        version: { type: "string", minLength: 1 }
      }
    },
    event_type: { type: "string", minLength: 1, pattern: noLegacyNamespace },
    occurred_at: { type: "string", pattern: isoTimestamp },
    sequence: { type: "integer", minimum: 1 },
    phase: { type: "string", minLength: 1 },
    outcome: { enum: ["success", "failed", "blocked", "cancelled", "running"] },
    severity: { enum: ["debug", "info", "warning", "error"] },
    trust_impact: {
      enum: [
        "supports_success",
        "supports_failure",
        "neutral",
        "requires_review",
        "contradicts_success"
      ]
    },
    summary: { type: "string", minLength: 1 },
    payload: { type: "object", additionalProperties: true },
    artifacts: { type: "array", items: artifactReferenceSchema, nullable: true }
  }
} as const;

export const kernelExecutionRequestSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "request_id",
    "run_id",
    "task_id",
    "cwd",
    "argv",
    "env",
    "timeout_ms",
    "stdin",
    "tty",
    "capture"
  ],
  properties: {
    schema: { const: "kernel.execution_request.v1" },
    request_id: { type: "string", pattern: idPattern },
    run_id: { type: "string", pattern: idPattern },
    task_id: { type: "string", pattern: idPattern },
    kind: { type: "string", const: "process.exec", nullable: true },
    cwd: { type: "string", minLength: 1 },
    argv: { type: "array", minItems: 1, items: { type: "string" } },
    env: { type: "object", additionalProperties: { type: "string" }, required: [] },
    timeout_ms: { type: "integer", minimum: 1 },
    stdin: {
      anyOf: [
        { const: "closed" },
        { const: "inherit" },
        {
          type: "object",
          additionalProperties: false,
          required: ["text"],
          properties: { text: { type: "string" } }
        }
      ]
    },
    tty: { type: "boolean" },
    permission_profile: {
      type: "object",
      nullable: true,
      additionalProperties: false,
      required: ["filesystem", "network", "command_prefixes"],
      properties: {
        filesystem: {
          type: "object",
          additionalProperties: false,
          required: ["read", "write", "deny"],
          properties: {
            read: { type: "array", items: { type: "string" } },
            write: { type: "array", items: { type: "string" } },
            deny: { type: "array", items: { type: "string" } }
          }
        },
        network: {
          anyOf: [
            { const: "disabled" },
            { const: "localhost" },
            {
              type: "object",
              additionalProperties: false,
              required: ["allow"],
              properties: { allow: { type: "array", items: { type: "string" } } }
            }
          ]
        },
        command_prefixes: { type: "array", items: { type: "string" } },
        escalation_reason: { type: "string", nullable: true }
      }
    },
    capture: {
      type: "object",
      additionalProperties: false,
      required: ["stdout_limit_bytes", "stderr_limit_bytes"],
      properties: {
        stdout_limit_bytes: { type: "integer", minimum: 1 },
        stderr_limit_bytes: { type: "integer", minimum: 1 }
      }
    }
  }
} as const;

export const kernelExecutionResultSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "request_id",
    "run_id",
    "task_id",
    "exit_code",
    "signal",
    "timed_out",
    "stdout",
    "stderr",
    "stdout_truncated",
    "stderr_truncated",
    "stdout_sha256",
    "stderr_sha256",
    "changed_files"
  ],
  properties: {
    schema: { const: "kernel.execution_result.v1" },
    request_id: { type: "string", pattern: idPattern },
    run_id: { type: "string", pattern: idPattern },
    task_id: { type: "string", pattern: idPattern },
    exit_code: { type: "integer", nullable: true },
    signal: { type: "string", nullable: true },
    timed_out: { type: "boolean" },
    stdout: { type: "string" },
    stderr: { type: "string" },
    stdout_truncated: { type: "boolean" },
    stderr_truncated: { type: "boolean" },
    stdout_sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    stderr_sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    changed_files: { type: "array", items: { type: "string" } },
    permission_decision: { type: "object", nullable: true, additionalProperties: true },
    artifacts: { type: "array", items: artifactReferenceSchema, nullable: true }
  }
} as const;

export const workerResultSchema = {
  type: "object",
  additionalProperties: false,
  required: ["schema", "task_id", "candidate_id", "status", "changed_files", "summary", "evidence"],
  properties: {
    schema: { const: "runway.worker_result.v1" },
    task_id: { type: "string", pattern: idPattern },
    candidate_id: { type: "string", pattern: idPattern },
    status: { enum: ["completed", "failed", "blocked"] },
    changed_files: { type: "array", items: { type: "string" } },
    summary: { type: "string", minLength: 1 },
    evidence: { type: "object", additionalProperties: true },
    failure_class: {
      type: "string",
      enum: [
        "adapter_crashed",
        "timeout",
        "cancelled",
        "malformed_result",
        "diff_scope_failed",
        "review_changes_requested",
        "review_rejected",
        "verification_failed",
        "merge_conflict",
        "needs_rebase",
        "needs_plan_fix",
        "needs_split",
        "needs_infra_fix",
        "missing_checkpoint",
        "missing_resume_handler",
        "stale_activity",
        "terminal_rejected"
      ],
      nullable: true
    }
  }
} as const;

export const providerCapabilityManifestSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "provider",
    "supported_modes",
    "tool_calls",
    "file_edits",
    "shell",
    "streaming",
    "approvals",
    "result_schema"
  ],
  properties: {
    schema: { const: "provider.capability_manifest.v1" },
    provider: { type: "string", minLength: 1 },
    supported_modes: {
      type: "array",
      items: { enum: ["single-agent", "multi-agent", "review", "verify"] }
    },
    tool_calls: { type: "boolean" },
    file_edits: { type: "boolean" },
    shell: { type: "boolean" },
    streaming: { type: "boolean" },
    approvals: { type: "boolean" },
    result_schema: { const: "runway.worker_result.v1" }
  }
} as const;

export const permissionDecisionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["schema", "allowed", "reason", "profile"],
  properties: {
    schema: { const: "policy.permission_decision.v1" },
    allowed: { type: "boolean" },
    reason: { type: "string", minLength: 1 },
    denied_by: { type: "string", nullable: true },
    profile: { type: "object", additionalProperties: true }
  }
} as const;

export const decisionPacketSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "task_id",
    "failure_class",
    "evidence_refs",
    "allowed_actions",
    "blocked_actions",
    "resume_input_shape",
    "summary"
  ],
  properties: {
    schema: { const: "runway.decision_packet.v1" },
    task_id: { type: "string", pattern: idPattern },
    failure_class: { type: "string", minLength: 1 },
    evidence_refs: { type: "array", items: { type: "string" } },
    allowed_actions: { type: "array", items: { type: "string" } },
    blocked_actions: { type: "array", items: { type: "string" } },
    resume_input_shape: { type: "object", additionalProperties: true },
    summary: { type: "string", minLength: 1 }
  }
} as const;

export const schemas = {
  "agentlens.event.v3": agentLensEventSchema,
  "kernel.execution_request.v1": kernelExecutionRequestSchema,
  "kernel.execution_result.v1": kernelExecutionResultSchema,
  "runway.worker_result.v1": workerResultSchema,
  "provider.capability_manifest.v1": providerCapabilityManifestSchema,
  "policy.permission_decision.v1": permissionDecisionSchema,
  "runway.decision_packet.v1": decisionPacketSchema
} as const;

export type ContractSchemaName = keyof typeof schemas;
