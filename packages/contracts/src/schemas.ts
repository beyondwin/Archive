const idPattern = "^[a-z][a-z0-9_:-]{2,127}$";
const isoTimestamp = "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$";
const noLegacyNamespace = "^(?!kws-cpe\\.)(?!kws-cme\\.)(?!kws\\.orchestrator\\.).+";
const failureClassValues = [
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
  "permission_denied",
  "service_unreachable",
  "dependency_missing",
  "environment_blocker",
  "flaky_unconfirmed",
  "command_not_found",
  "dependency_blocked",
  "file_claim_conflict",
  "dirty_source_checkout",
  "unsafe_apply",
  "state_drift",
  "artifact_missing",
  "stale_activity",
  "terminal_rejected"
] as const;
const riskValues = ["low", "medium", "high"] as const;
const providerRoleValues = ["implement", "review", "fix", "verify_assist"] as const;
const providerLogCategoryValues = ["error", "warning", "mcp", "plugin_manifest", "skill_loader", "other"] as const;
const usageSourceValues = ["provider_json", "event_stream", "unknown"] as const;
const budgetActionValues = ["warn", "pause", "off"] as const;
const specMappingSourceValues = ["explicit", "heuristic", "fallback"] as const;
const failureBarrierTypeValues = [
  "spec_blocker",
  "env_blocker",
  "ambiguity",
  "quality_fail",
  "verification_fail",
  "budget_paused",
  "checkpoint_missing",
  "evidence_missing"
] as const;
const operatorRunStatusValues = [
  "running",
  "recovering",
  "needs_input",
  "needs_approval",
  "blocked",
  "ready_to_apply",
  "done",
  "failed"
] as const;
const operatorActionIdValues = [
  "inspect_run",
  "explain_run",
  "open_raw_evidence",
  "open_ai_repair_handoff",
  "request_user_input",
  "approve_recovery",
  "resume_run",
  "regenerate_checkpoint",
  "rebase_checkpoint",
  "rerun_verification",
  "review_patch",
  "apply_run"
] as const;
const executionPhaseNameValues = [
  "worktree_setup",
  "provider",
  "verification",
  "checkpoint",
  "checkpoint_dry_run",
  "reconciliation",
  "wave",
  "total"
] as const;
const fileClaimSchema = {
  type: "object",
  additionalProperties: false,
  required: ["path", "mode"],
  properties: {
    path: { type: "string", minLength: 1 },
    mode: { enum: ["owned", "shared_append", "read_only"] }
  }
} as const;

const executionPhaseTimingSchema = {
  type: "object",
  additionalProperties: false,
  required: ["phase", "started", "completed", "duration_ms"],
  properties: {
    phase: { enum: executionPhaseNameValues },
    started: { type: "string", pattern: isoTimestamp, nullable: true },
    completed: { type: "string", pattern: isoTimestamp, nullable: true },
    duration_ms: { type: "number", minimum: 0, nullable: true }
  }
} as const;

const artifactIndexEntrySchema = {
  type: "object",
  additionalProperties: false,
  required: ["ref", "media_type", "sha256", "byte_length", "producer_phase", "task_id", "created_at"],
  properties: {
    ref: { type: "string", minLength: 1 },
    media_type: { type: "string", minLength: 1 },
    sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    byte_length: { type: "number", minimum: 0 },
    producer_phase: { enum: [...executionPhaseNameValues, "task_packet", "combined_apply", "decision"] },
    task_id: { type: "string", pattern: idPattern, nullable: true },
    created_at: { type: "string", pattern: isoTimestamp }
  }
} as const;

const tokenUsageSchema = {
  type: "object",
  additionalProperties: false,
  required: ["input_tokens", "output_tokens", "cached_read_tokens", "cached_write_tokens"],
  properties: {
    input_tokens: { type: "integer", minimum: 0 },
    output_tokens: { type: "integer", minimum: 0 },
    cached_read_tokens: { type: "integer", minimum: 0 },
    cached_write_tokens: { type: "integer", minimum: 0 }
  }
} as const;

const modelRequestSchema = {
  type: "object",
  additionalProperties: false,
  required: ["model", "reasoning"],
  properties: {
    model: { type: "string", nullable: true },
    reasoning: { type: "string", nullable: true }
  }
} as const;

const modelAttestationSchema = {
  type: "object",
  additionalProperties: false,
  required: ["model", "reasoning", "source"],
  properties: {
    model: { type: "string", nullable: true },
    reasoning: { type: "string", nullable: true },
    source: { type: "string", minLength: 1 }
  }
} as const;

const decisionEntrySchema = {
  type: "object",
  additionalProperties: false,
  required: ["decision_id", "task_id", "decision", "files", "made_at", "supersedes"],
  properties: {
    decision_id: { type: "string", minLength: 1 },
    task_id: { type: "string", pattern: idPattern },
    decision: { type: "string", minLength: 1 },
    files: { type: "array", items: { type: "string" } },
    made_at: { type: "string", pattern: isoTimestamp },
    supersedes: { type: "string", nullable: true }
  }
} as const;

const specManifestSchema = {
  type: "object",
  additionalProperties: false,
  required: ["spec_path", "spec_total_chars", "sections", "task_to_sections", "fallback_policy", "built_at"],
  properties: {
    spec_path: { type: "string", nullable: true },
    spec_total_chars: { type: "integer", minimum: 0 },
    sections: {
      type: "object",
      additionalProperties: {
        type: "object",
        additionalProperties: false,
        required: ["id", "title", "range", "byte_offset"],
        properties: {
          id: { type: "string", minLength: 1 },
          title: { type: "string", minLength: 1 },
          range: {
            type: "array",
            minItems: 2,
            maxItems: 2,
            items: { type: "integer", minimum: 0 }
          },
          byte_offset: {
            type: "array",
            minItems: 2,
            maxItems: 2,
            items: { type: "integer", minimum: 0 }
          }
        }
      }
    },
    task_to_sections: {
      type: "object",
      additionalProperties: {
        type: "object",
        additionalProperties: false,
        required: ["sections", "fallback_used", "source"],
        properties: {
          sections: { type: "array", items: { type: "string", minLength: 1 } },
          fallback_used: { type: "boolean" },
          source: { enum: specMappingSourceValues }
        }
      }
    },
    fallback_policy: { enum: ["full_spec_on_blocker", "halt_on_blocker"] },
    built_at: { type: "string", pattern: isoTimestamp }
  }
} as const;

const intakeFindingSchema = {
  type: "object",
  additionalProperties: false,
  required: ["code", "severity", "message", "task_id", "evidence_refs"],
  properties: {
    code: { type: "string", minLength: 1 },
    severity: { enum: ["info", "warning", "blocking"] },
    message: { type: "string", minLength: 1 },
    task_id: { type: "string", nullable: true },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;

const intakeRepairActionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["action", "status", "reason", "evidence_refs"],
  properties: {
    action: { type: "string", minLength: 1 },
    status: { enum: ["applied", "blocked", "skipped"] },
    reason: { type: "string", minLength: 1 },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;

const intakeTaskRecoveryStatusSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "task_id",
    "status",
    "title",
    "file_claim_count",
    "verification_command_count",
    "blockers"
  ],
  properties: {
    task_id: { type: "string", pattern: idPattern },
    status: { enum: ["normalized", "recovered", "blocked", "warning"] },
    title: { type: "string", minLength: 1 },
    file_claim_count: { type: "integer", minimum: 0 },
    verification_command_count: { type: "integer", minimum: 0 },
    blockers: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;

const intakeRecoverySchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "status",
    "started_at",
    "completed_at",
    "normalized_plan_ref",
    "recovery_report_ref",
    "findings",
    "repair_actions",
    "can_start",
    "confidence",
    "question"
  ],
  properties: {
    status: { enum: ["not_needed", "recovered", "decision_required", "failed"] },
    started_at: { type: "string", pattern: isoTimestamp },
    completed_at: { type: "string", pattern: isoTimestamp },
    normalized_plan_ref: { type: "string", nullable: true },
    recovery_report_ref: { type: "string", nullable: true },
    findings: { type: "array", items: intakeFindingSchema },
    repair_actions: { type: "array", items: intakeRepairActionSchema },
    can_start: { type: "boolean" },
    confidence: { enum: ["deterministic", "ai_assisted", "blocked"] },
    question: { type: "string", nullable: true },
    strict_task_status: { type: "array", items: intakeTaskRecoveryStatusSchema },
    fallback_task_status: { type: "array", items: intakeTaskRecoveryStatusSchema },
    merged_task_status: { type: "array", items: intakeTaskRecoveryStatusSchema },
    blocked_tasks: { type: "array", items: intakeTaskRecoveryStatusSchema },
    extract_report_ref: { type: "string", nullable: true }
  }
} as const;

const costLedgerBucketSchema = {
  type: "object",
  additionalProperties: false,
  required: ["usage", "cost_usd", "dispatches"],
  properties: {
    usage: tokenUsageSchema,
    cost_usd: { type: "number", minimum: 0 },
    dispatches: { type: "integer", minimum: 0 }
  }
} as const;

const costLedgerSchema = {
  type: "object",
  additionalProperties: false,
  required: ["by_task", "by_role", "by_model", "totals", "price_table_commit"],
  properties: {
    by_task: {
      type: "object",
      additionalProperties: {
        type: "object",
        additionalProperties: false,
        required: ["usage", "cost_usd", "dispatches", "last_at", "model"],
        properties: {
          usage: tokenUsageSchema,
          cost_usd: { type: "number", minimum: 0 },
          dispatches: { type: "integer", minimum: 0 },
          last_at: { type: "string", pattern: isoTimestamp },
          model: { type: "string", nullable: true }
        }
      }
    },
    by_role: { type: "object", additionalProperties: costLedgerBucketSchema },
    by_model: { type: "object", additionalProperties: costLedgerBucketSchema },
    totals: {
      type: "object",
      additionalProperties: false,
      required: ["input_tokens", "output_tokens", "cached_read_tokens", "cached_write_tokens", "cost_usd", "dispatches"],
      properties: {
        input_tokens: { type: "integer", minimum: 0 },
        output_tokens: { type: "integer", minimum: 0 },
        cached_read_tokens: { type: "integer", minimum: 0 },
        cached_write_tokens: { type: "integer", minimum: 0 },
        cost_usd: { type: "number", minimum: 0 },
        dispatches: { type: "integer", minimum: 0 }
      }
    },
    price_table_commit: { type: "string", minLength: 1 }
  }
} as const;

const taskEvidencePolicySchema = {
  type: "object",
  additionalProperties: false,
  required: ["require_method_evidence", "verification_evidence", "method_audit_status", "waiver_reason"],
  properties: {
    require_method_evidence: { type: "boolean" },
    verification_evidence: { const: "required" },
    method_audit_status: { enum: ["missing", "present", "waived", "not_required"] },
    waiver_reason: { type: "string", nullable: true }
  }
} as const;

const failureBarrierProjectionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["schema", "run_id", "barrier_type", "task_id", "failure_class", "reason", "evidence_refs"],
  properties: {
    schema: { const: "waygent.failure_barrier.v1" },
    run_id: { type: "string", pattern: idPattern },
    barrier_type: { enum: [...failureBarrierTypeValues, null] },
    task_id: { type: "string", pattern: idPattern, nullable: true },
    failure_class: { type: "string", nullable: true },
    reason: { type: "string", nullable: true },
    evidence_refs: { type: "array", items: { type: "string" } }
  }
} as const;

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

export const lensRunwayProjectionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["schema", "run_id", "status", "safe_wave", "trust_status", "event_count"],
  properties: {
    schema: { const: "lens.runway_projection.v1" },
    run_id: { type: "string", pattern: idPattern },
    status: { enum: ["pending", "running", "blocked", "failed", "completed", "applied"] },
    safe_wave: { type: "array", items: { type: "string", pattern: idPattern } },
    trust_status: { enum: ["trusted", "failed", "insufficient_evidence"] },
    event_count: { type: "integer", minimum: 0 }
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
      enum: failureClassValues,
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

export const waygentTaskPacketSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "run_id",
    "task_id",
    "role",
    "task_title",
    "plan_excerpt",
    "spec_excerpt",
    "file_claims",
    "allowed_write_globs",
    "forbidden_write_globs",
    "dependencies",
    "checkpoint_inputs",
    "acceptance_commands",
    "verification_commands",
    "risk",
    "previous_failures",
    "decisions",
    "context_budget",
    "sha256"
  ],
  properties: {
    schema: { const: "waygent.task_packet.v1" },
    run_id: { type: "string", pattern: idPattern },
    task_id: { type: "string", pattern: idPattern },
    role: { enum: providerRoleValues },
    task_title: { type: "string", minLength: 1 },
    plan_excerpt: { type: "string", minLength: 1 },
    spec_excerpt: { type: "string" },
    file_claims: { type: "array", items: fileClaimSchema },
    allowed_write_globs: { type: "array", items: { type: "string", minLength: 1 } },
    forbidden_write_globs: { type: "array", items: { type: "string", minLength: 1 } },
    dependencies: { type: "array", items: { type: "string", pattern: idPattern } },
    checkpoint_inputs: { type: "array", items: { type: "string" } },
    acceptance_commands: { type: "array", items: { type: "string", minLength: 1 } },
    verification_commands: { type: "array", items: { type: "string", minLength: 1 } },
    risk: { enum: riskValues },
    previous_failures: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["failure_class", "evidence_refs", "summary"],
        properties: {
          failure_class: { enum: failureClassValues },
          evidence_refs: { type: "array", items: { type: "string" } },
          summary: { type: "string", minLength: 1 }
        }
      }
    },
    decisions: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["decision_id", "summary"],
        properties: {
          decision_id: { type: "string", minLength: 1 },
          summary: { type: "string", minLength: 1 }
        }
      }
    },
    context_budget: {
      type: "object",
      additionalProperties: false,
      required: ["estimated_chars", "max_chars", "status"],
      properties: {
        estimated_chars: { type: "integer", minimum: 0 },
        max_chars: { type: "integer", minimum: 1 },
        status: { enum: ["green", "yellow", "red"] }
      }
    },
    sha256: { type: "string", pattern: "^[a-f0-9]{64}$" }
  }
} as const;

export const reviewResultSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "run_id",
    "task_id",
    "attempt_id",
    "provider",
    "verdict",
    "spec_score",
    "quality_score",
    "findings",
    "residual_risk",
    "summary"
  ],
  properties: {
    schema: { const: "runway.review_result.v1" },
    run_id: { type: "string", pattern: idPattern },
    task_id: { type: "string", pattern: idPattern },
    attempt_id: { type: "string", pattern: idPattern },
    provider: { type: "string", minLength: 1 },
    verdict: { enum: ["pass", "needs_fix", "reject"] },
    spec_score: { type: "number", minimum: 0, maximum: 1 },
    quality_score: { type: "number", minimum: 0, maximum: 1 },
    findings: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["severity", "summary"],
        properties: {
          severity: { enum: ["critical", "important", "minor"] },
          file: { type: "string", nullable: true },
          line: { type: "integer", minimum: 1, nullable: true },
          summary: { type: "string", minLength: 1 }
        }
      }
    },
    residual_risk: { type: "array", items: { type: "string" } },
    summary: { type: "string", minLength: 1 }
  }
} as const;

const providerLogSummarySchema = {
  type: "object",
  additionalProperties: false,
  required: ["total_lines", "counts", "samples"],
  properties: {
    total_lines: { type: "integer", minimum: 0 },
    counts: {
      type: "object",
      additionalProperties: false,
      required: providerLogCategoryValues,
      properties: Object.fromEntries(providerLogCategoryValues.map((category) => [category, { type: "integer", minimum: 0 }]))
    },
    samples: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["category", "line"],
        properties: {
          category: { enum: providerLogCategoryValues },
          line: { type: "string" }
        }
      }
    }
  }
} as const;

export const providerProcessEvidenceSchema = {
  type: "object",
  additionalProperties: false,
  required: ["stdout", "stderr", "exit_code", "timed_out", "started_at", "completed_at"],
  properties: {
    stdout: { type: "string" },
    stderr: { type: "string" },
    exit_code: { type: "integer", nullable: true },
    timed_out: { type: "boolean" },
    started_at: { type: "string", pattern: isoTimestamp },
    completed_at: { type: "string", pattern: isoTimestamp, nullable: true },
    event_stream: { type: "string", nullable: true },
    stderr_summary: providerLogSummarySchema
  }
} as const;

export const providerAttemptSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "attempt_id",
    "run_id",
    "task_id",
    "role",
    "provider",
    "command",
    "cwd",
    "stdin_ref",
    "stdout_ref",
    "stderr_ref",
    "event_stream_ref",
    "exit_code",
    "timed_out",
    "started_at",
    "completed_at",
    "worker_result_ref",
    "failure_class"
  ],
  properties: {
    schema: { const: "runway.provider_attempt.v1" },
    attempt_id: { type: "string", pattern: idPattern },
    run_id: { type: "string", pattern: idPattern },
    task_id: { type: "string", pattern: idPattern },
    role: { enum: providerRoleValues },
    provider: { type: "string", minLength: 1 },
    command: { type: "array", minItems: 1, items: { type: "string" } },
    cwd: { type: "string", minLength: 1 },
    stdin_ref: { type: "string", minLength: 1 },
    stdout_ref: { type: "string", minLength: 1 },
    stderr_ref: { type: "string", minLength: 1 },
    event_stream_ref: { type: "string", nullable: true },
    exit_code: { type: "integer", nullable: true },
    timed_out: { type: "boolean" },
    started_at: { type: "string", pattern: isoTimestamp },
    completed_at: { type: "string", pattern: isoTimestamp, nullable: true },
    worker_result_ref: { type: "string", nullable: true },
    failure_class: { enum: [...failureClassValues, null] },
    process: providerProcessEvidenceSchema,
    requested_model: modelRequestSchema,
    actual_model: modelAttestationSchema,
    usage: { ...tokenUsageSchema, nullable: true },
    usage_source: { enum: usageSourceValues }
  }
} as const;

export const waygentSourcePreflightSchema = {
  type: "object",
  additionalProperties: false,
  required: ["status", "dirty_files", "related", "unrelated", "checked_at", "reason", "decision_packet_ref"],
  properties: {
    status: { enum: ["clean", "dirty_unrelated", "dirty_related"] },
    dirty_files: { type: "array", items: { type: "string" } },
    related: { type: "array", items: { type: "string" } },
    unrelated: { type: "array", items: { type: "string" } },
    checked_at: { type: "string", pattern: isoTimestamp },
    reason: { type: "string", nullable: true },
    decision_packet_ref: { type: "string", nullable: true }
  }
} as const;

export const waygentWorktreeManifestSchema = {
  type: "object",
  additionalProperties: false,
  required: ["task_id", "branch", "path", "source", "source_commit", "cleanup_status"],
  properties: {
    task_id: { type: "string", pattern: idPattern },
    branch: { type: "string", minLength: 1 },
    path: { type: "string", minLength: 1 },
    source: { type: "string", minLength: 1 },
    source_commit: { type: "string", nullable: true },
    cleanup_status: { enum: ["active", "removed", "failed", "unknown"] }
  }
} as const;

const waygentRunStateTaskV2Schema = {
  type: "object",
  additionalProperties: false,
  required: [
    "id",
    "status",
    "risk",
    "dependencies",
    "file_claims",
    "attempts",
    "task_packet_path",
    "task_packet_sha256",
    "unit_manifest",
    "checkpoint_refs",
    "latest_failure_class",
    "decision_packet_ref",
    "timing"
  ],
  properties: {
    id: { type: "string", pattern: idPattern },
    status: { enum: ["pending", "ready", "running", "needs_fix", "verified", "blocked", "failed", "applied"] },
    risk: { enum: riskValues },
    dependencies: { type: "array", items: { type: "string", pattern: idPattern } },
    file_claims: { type: "array", items: fileClaimSchema },
    attempts: { type: "array", items: { type: "string", pattern: idPattern } },
    task_packet_path: { type: "string", nullable: true },
    task_packet_sha256: { type: "string", pattern: "^[a-f0-9]{64}$", nullable: true },
    unit_manifest: { type: "object", additionalProperties: true, nullable: true },
    checkpoint_refs: { type: "array", items: { type: "string" } },
    latest_failure_class: { type: "string", nullable: true },
    decision_packet_ref: { type: "string", nullable: true },
    timing: { type: "object", additionalProperties: { type: "string" } },
    phase_timings: { type: "array", items: executionPhaseTimingSchema },
    evidence_policy: taskEvidencePolicySchema,
    hook_retries: { type: "integer", minimum: 0 },
    model_used: { type: "array", items: modelAttestationSchema }
  }
} as const;

export const waygentRunStateV2Schema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "run_id",
    "workspace",
    "source_branch",
    "worktree_root",
    "run_root",
    "artifact_root",
    "state_path",
    "event_journal_path",
    "plan_path",
    "spec_path",
    "provider_profile",
    "status",
    "lifecycle_outcome",
    "current_phase",
    "tasks",
    "safe_waves",
    "provider_attempts",
    "reviews",
    "verification",
    "recovery",
    "apply",
    "context",
    "drift",
    "completion_audit",
    "timestamps"
  ],
  properties: {
    schema: { const: "waygent.run_state.v2" },
    run_id: { type: "string", pattern: idPattern },
    workspace: { type: "string", minLength: 1 },
    source_branch: { type: "string", nullable: true },
    worktree_root: { type: "string", minLength: 1 },
    run_root: { type: "string", minLength: 1 },
    artifact_root: { type: "string", minLength: 1 },
    state_path: { type: "string", minLength: 1 },
    event_journal_path: { type: "string", minLength: 1 },
    plan_path: { type: "string", nullable: true },
    spec_path: { type: "string", nullable: true },
    provider_profile: { type: "object", additionalProperties: true },
    intake_recovery: intakeRecoverySchema,
    decisions_register: { type: "array", items: decisionEntrySchema },
    spec_manifest: specManifestSchema,
    cost_ledger: costLedgerSchema,
    budget_cap_usd: { type: "number", minimum: 0, nullable: true },
    budget_action: { enum: budgetActionValues },
    method_evidence_required: { type: "boolean" },
    hook_config: { type: "string" },
    status: { enum: ["initializing", "running", "blocked", "failed", "completed", "applying", "applied"] },
    lifecycle_outcome: { enum: ["finished", "blocked", "failed", "aborted", null] },
    current_phase: { enum: ["preflight", "dispatch", "review", "verify", "recover", "apply", "complete"] },
    preflight: waygentSourcePreflightSchema,
    worktrees: { type: "array", items: waygentWorktreeManifestSchema },
    artifact_index: { type: "array", items: artifactIndexEntrySchema },
    tasks: { type: "object", additionalProperties: waygentRunStateTaskV2Schema },
    safe_waves: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["wave_id", "ready", "withheld"],
        properties: {
          wave_id: { type: "string", minLength: 1 },
          ready: { type: "array", items: { type: "string", pattern: idPattern } },
          concurrency: { type: "integer", minimum: 1, nullable: true },
          timing: {
            type: "object",
            additionalProperties: false,
            nullable: true,
            required: ["started", "completed", "duration_ms"],
            properties: {
              started: { type: "string", pattern: isoTimestamp },
              completed: { type: "string", pattern: isoTimestamp },
              duration_ms: { type: "number", minimum: 0 }
            }
          },
          withheld: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["task_id", "reason"],
              properties: {
                task_id: { type: "string", pattern: idPattern },
                reason: { type: "string", minLength: 1 },
                detail: { type: "string", nullable: true }
              }
            }
          }
        }
      }
    },
    provider_attempts: { type: "array", items: providerAttemptSchema },
    reviews: { type: "array", items: reviewResultSchema },
    verification: { type: "array", items: { type: "object", additionalProperties: true } },
    recovery: { type: "array", items: { type: "object", additionalProperties: true } },
    apply: {
      type: "object",
      additionalProperties: false,
      required: ["status"],
      properties: {
        status: { enum: ["not_applied", "not_ready", "blocked", "applying", "applied", "failed"] },
        reason: { type: "string", nullable: true },
        checkpoint_ref: { type: "string", nullable: true }
      }
    },
    context: {
      type: "object",
      additionalProperties: false,
      required: ["snapshot_path", "basis_hash"],
      properties: {
        snapshot_path: { type: "string", nullable: true },
        basis_hash: { type: "string", pattern: "^[a-f0-9]{64}$", nullable: true }
      }
    },
    drift: {
      type: "object",
      additionalProperties: false,
      required: ["last_checked_at", "records", "unrepaired_blockers"],
      properties: {
        last_checked_at: { type: "string", pattern: isoTimestamp, nullable: true },
        records: { type: "array", items: { type: "object", additionalProperties: true } },
        unrepaired_blockers: { type: "array", items: { type: "object", additionalProperties: true } }
      }
    },
    completion_audit: { type: "object", additionalProperties: true, nullable: true },
    timestamps: {
      type: "object",
      additionalProperties: false,
      required: ["started_at", "updated_at", "completed_at"],
      properties: {
        started_at: { type: "string", pattern: isoTimestamp },
        updated_at: { type: "string", pattern: isoTimestamp },
        completed_at: { type: "string", pattern: isoTimestamp, nullable: true }
      }
    }
  }
} as const;

const operatorBlockerSchema = {
  type: "object",
  additionalProperties: false,
  required: ["code", "title", "summary", "severity", "evidence_refs", "missing_refs", "recommended_action_ids"],
  properties: {
    code: { type: "string", minLength: 1 },
    title: { type: "string", minLength: 1 },
    summary: { type: "string", minLength: 1 },
    severity: { enum: ["info", "warning", "blocking", "critical"] },
    task_id: { type: "string", pattern: idPattern, nullable: true },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
    missing_refs: { type: "array", items: { type: "string", minLength: 1 } },
    recommended_action_ids: { type: "array", items: { enum: operatorActionIdValues } },
    failure_barrier: { ...failureBarrierProjectionSchema, nullable: true }
  }
} as const;

const operatorAllowedActionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["id", "label", "reason", "evidence_refs", "requires_approval", "requires_runtime_revalidation", "command"],
  properties: {
    id: { enum: operatorActionIdValues },
    label: { type: "string", minLength: 1 },
    reason: { type: "string", minLength: 1 },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
    requires_approval: { type: "boolean" },
    requires_runtime_revalidation: { type: "boolean" },
    command: { type: "string", nullable: true }
  }
} as const;

const operatorBlockedActionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["id", "label", "reason", "evidence_refs", "unblocks_when"],
  properties: {
    id: { enum: operatorActionIdValues },
    label: { type: "string", minLength: 1 },
    reason: { type: "string", minLength: 1 },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
    unblocks_when: { type: "string", minLength: 1 }
  }
} as const;

const operatorEvidencePacketSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "state_refs",
    "event_refs",
    "artifact_refs",
    "verification_refs",
    "checkpoint_refs",
    "projection_refs",
    "missing_refs",
    "redaction_notes"
  ],
  properties: {
    state_refs: { type: "array", items: { type: "string", minLength: 1 } },
    event_refs: { type: "array", items: { type: "string", minLength: 1 } },
    artifact_refs: { type: "array", items: { type: "string", minLength: 1 } },
    verification_refs: { type: "array", items: { type: "string", minLength: 1 } },
    checkpoint_refs: { type: "array", items: { type: "string", minLength: 1 } },
    projection_refs: { type: "array", items: { type: "string", minLength: 1 } },
    missing_refs: { type: "array", items: { type: "string", minLength: 1 } },
    redaction_notes: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;

export const operatorDecisionProjectionSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "run_id",
    "generated_at",
    "status_summary",
    "primary_blocker",
    "secondary_blockers",
    "allowed_actions",
    "blocked_actions",
    "evidence_packet",
    "ai_handoff",
    "confidence",
    "unknown_reasons",
    "source_projection_refs"
  ],
  properties: {
    schema: { const: "waygent.operator_decision.v1" },
    run_id: { type: "string", pattern: idPattern },
    generated_at: { type: "string", pattern: isoTimestamp },
    status_summary: {
      type: "object",
      additionalProperties: false,
      required: [
        "display_status",
        "runtime_status",
        "lifecycle_outcome",
        "current_phase",
        "active_tasks",
        "completed_tasks",
        "blocked_tasks",
        "apply_status",
        "summary"
      ],
      properties: {
        display_status: { enum: operatorRunStatusValues },
        runtime_status: {
          enum: [
            "initializing",
            "running",
            "blocked",
            "failed",
            "completed",
            "applying",
            "applied",
            "missing",
            "invalid",
            "unsupported"
          ]
        },
        lifecycle_outcome: { enum: ["finished", "blocked", "failed", "aborted", null] },
        current_phase: { enum: ["preflight", "dispatch", "review", "verify", "recover", "apply", "complete", null] },
        active_tasks: { type: "integer", minimum: 0 },
        completed_tasks: { type: "integer", minimum: 0 },
        blocked_tasks: { type: "integer", minimum: 0 },
        apply_status: { enum: ["ready", "not_ready", "blocked", "applied", "unknown"] },
        summary: { type: "string", minLength: 1 }
      }
    },
    primary_blocker: { ...operatorBlockerSchema, nullable: true },
    secondary_blockers: { type: "array", items: operatorBlockerSchema },
    allowed_actions: { type: "array", items: operatorAllowedActionSchema },
    blocked_actions: { type: "array", items: operatorBlockedActionSchema },
    evidence_packet: operatorEvidencePacketSchema,
    ai_handoff: {
      type: "object",
      additionalProperties: false,
      required: [
        "purpose",
        "prompt_summary",
        "run_id",
        "current_status",
        "primary_blocker",
        "secondary_blockers",
        "allowed_action_ids",
        "blocked_action_ids",
        "constraints",
        "evidence_refs",
        "missing_evidence",
        "raw_fallback_refs",
        "safety_notes"
      ],
      properties: {
        purpose: { enum: ["draft_repair_plan", "summarize_blocker", "compare_recovery_options"] },
        prompt_summary: { type: "string", minLength: 1 },
        run_id: { type: "string", pattern: idPattern },
        current_status: { enum: operatorRunStatusValues },
        primary_blocker: { type: "string", nullable: true },
        secondary_blockers: { type: "array", items: { type: "string", minLength: 1 } },
        allowed_action_ids: { type: "array", items: { enum: operatorActionIdValues } },
        blocked_action_ids: { type: "array", items: { enum: operatorActionIdValues } },
        constraints: { type: "array", items: { type: "string", minLength: 1 } },
        evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
        missing_evidence: { type: "array", items: { type: "string", minLength: 1 } },
        raw_fallback_refs: { type: "array", items: { type: "string", minLength: 1 } },
        safety_notes: { type: "array", items: { type: "string", minLength: 1 } }
      }
    },
    confidence: { enum: ["deterministic", "partial", "unknown"] },
    unknown_reasons: { type: "array", items: { type: "string", minLength: 1 } },
    intake_recovery: {
      type: "object",
      additionalProperties: false,
      nullable: true,
      required: ["status", "can_start", "confidence", "finding_codes", "artifact_refs", "question"],
      properties: {
        status: { enum: ["not_needed", "recovered", "decision_required", "failed"] },
        can_start: { type: "boolean" },
        confidence: { enum: ["deterministic", "ai_assisted", "blocked"] },
        finding_codes: { type: "array", items: { type: "string", minLength: 1 } },
        artifact_refs: { type: "array", items: { type: "string", minLength: 1 } },
        question: { type: "string", nullable: true }
      }
    },
    source_projection_refs: {
      type: "object",
      additionalProperties: false,
      required: ["run_state_v2", "apply_readiness", "execution_explanation", "operational_maturity"],
      properties: {
        run_state_v2: { type: "string", nullable: true },
        apply_readiness: { type: "string", nullable: true },
        execution_explanation: { type: "string", nullable: true },
        operational_maturity: { type: "string", nullable: true }
      }
    }
  }
} as const;

export const schemas = {
  "agentlens.event.v3": agentLensEventSchema,
  "lens.runway_projection.v1": lensRunwayProjectionSchema,
  "kernel.execution_request.v1": kernelExecutionRequestSchema,
  "kernel.execution_result.v1": kernelExecutionResultSchema,
  "runway.worker_result.v1": workerResultSchema,
  "provider.capability_manifest.v1": providerCapabilityManifestSchema,
  "policy.permission_decision.v1": permissionDecisionSchema,
  "runway.decision_packet.v1": decisionPacketSchema,
  "waygent.task_packet.v1": waygentTaskPacketSchema,
  "runway.review_result.v1": reviewResultSchema,
  "runway.provider_attempt.v1": providerAttemptSchema,
  "waygent.run_state.v2": waygentRunStateV2Schema,
  "waygent.failure_barrier.v1": failureBarrierProjectionSchema,
  "waygent.operator_decision.v1": operatorDecisionProjectionSchema
} as const;

export type ContractSchemaName = keyof typeof schemas;
