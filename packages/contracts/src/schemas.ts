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
    process: providerProcessEvidenceSchema
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
    phase_timings: { type: "array", items: executionPhaseTimingSchema }
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
  "waygent.run_state.v2": waygentRunStateV2Schema
} as const;

export type ContractSchemaName = keyof typeof schemas;
