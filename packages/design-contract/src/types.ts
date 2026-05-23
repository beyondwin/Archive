/**
 * SP-1 design-contract types.
 *
 * These types describe the normalized JSON shape produced by parsing a
 * design or plan markdown source. Downstream pipeline stages consume
 * the normalized JSON — markdown is not re-parsed outside this package.
 */

export type ParserSource = "deterministic" | "ai" | "cached";

export type AckConfidence = "verified" | "best_effort";

export type FileClaimMode = "owned" | "shared" | "read-only";

export interface FileClaim {
  path: string;
  mode: FileClaimMode;
}

/**
 * Path matcher for binding invariants and prescriptive snippets to
 * a subset of file claims. `globs` matches against task `file_claims[].path`.
 */
export interface PathsBound {
  globs: string[];
}

export interface ShellCheck {
  kind: "shell";
  command: string;
  expect_exit_code?: number;
  cwd?: string;
}

export interface ExistsCheck {
  kind: "exists";
  path: string;
  expect: "present" | "absent";
}

export interface JsonEqualsCheck {
  kind: "json-equals";
  path: string;
  pointer?: string;
  expected: unknown;
}

export type CheckSpec = ShellCheck | ExistsCheck | JsonEqualsCheck;

export type CheckKind = CheckSpec["kind"];

/**
 * An invariant the design declares must hold across the working tree
 * or worker output. Pre-dispatch checks run against the working tree;
 * post-worker checks consult worker_result.v2 envelope contents.
 */
export interface Invariant {
  id: string;
  description: string;
  paths_bound: PathsBound;
  check: CheckSpec;
  ack: AckRequirement;
}

export interface AckRequirement {
  required: boolean;
  confidence: AckConfidence;
}

/**
 * A code snippet the design prescribes verbatim. The worker output is
 * hash-compared against `content_sha256`; drift is a blocker.
 */
export interface PrescriptiveSnippet {
  id: string;
  target_path: string;
  language?: string;
  content: string;
  content_sha256: string;
}

export interface SourceRange {
  start_line: number;
  end_line: number;
}

export interface EvidenceQuote {
  source_range: SourceRange;
  text: string;
}

/**
 * Audit log produced alongside a normalized contract. Records which
 * parser produced it, the prompt version when AI-extracted, source
 * hash, and per-field evidence quotes.
 */
export interface ExtractionLog {
  schema: "waygent.design_contract.extraction_log.v1";
  parser: ParserSource;
  extractor_version: string;
  source_sha256: string;
  prompt_sha256?: string;
  confidence: number;
  evidence: Record<string, EvidenceQuote[]>;
  notes?: string[];
}

export interface ContractMeta {
  source_path: string;
  source_sha256: string;
  extracted_at: string;
}

export interface DesignContract {
  schema: "waygent.design_contract.v1";
  meta: ContractMeta;
  invariants: Invariant[];
  prescriptive_snippets: PrescriptiveSnippet[];
  policy_acks_required: string[];
}

export interface PlanTaskRef {
  task_id: string;
  title: string;
  file_claims: FileClaim[];
  invariant_refs: string[];
  prescriptive_refs: string[];
}

export interface PlanContract {
  schema: "waygent.plan_contract.v1";
  meta: ContractMeta;
  tasks: PlanTaskRef[];
}

export type DesignContractArtifact = DesignContract | PlanContract;

/**
 * Blocker kinds emitted by SP-1. All route through the existing
 * intake_decision_required channel; this enum is the
 * `blocker_kind` payload, not a new event family.
 */
export type DesignContractBlockerKind =
  | "design_source_missing"
  | "design_extraction_uncertain"
  | "design_extraction_failed"
  | "plan_extraction_failed"
  | "invariant_violation_predispatch"
  | "invariant_violation_post_worker"
  | "policy_ack_missing"
  | "policy_ack_unverified"
  | "stale_test_candidates_missing"
  | "prescriptive_drift"
  | "cache_corruption";

export type BlockerSeverity = "block" | "warn" | "info";

export interface ContractBlocker {
  kind: DesignContractBlockerKind;
  severity: BlockerSeverity;
  message: string;
  invariant_id?: string;
  prescriptive_id?: string;
  task_id?: string;
  details?: Record<string, unknown>;
}

/**
 * Result of a single invariant check run (pre-dispatch or post-worker).
 */
export interface InvariantCheckResult {
  invariant_id: string;
  passed: boolean;
  phase: "pre_dispatch" | "post_worker";
  evidence: {
    check: CheckSpec;
    stdout?: string;
    stderr?: string;
    exit_code?: number;
    actual?: unknown;
  };
}

/**
 * Result of a deterministic parse attempt. The deterministic parser is
 * the fast path for canonical scaffold output; ambiguous or incomplete
 * sources fall through to the AI extractor.
 */
export type DeterministicParseResult<T extends DesignContractArtifact> =
  | { ok: true; value: T }
  | { ok: false; reason: IncompleteParseReason; details?: string };

export type IncompleteParseReason =
  | "missing_required_heading"
  | "ambiguous_paths_bound"
  | "unparseable_check_block"
  | "non_canonical_format";

export interface IncompleteParse {
  ok: false;
  reason: IncompleteParseReason;
  details?: string;
}

/**
 * Carrier for run_state.v2.design_contract artifact refs.
 */
export interface DesignContractArtifactRefs {
  normalized_design_path?: string;
  normalized_plan_path?: string;
  extraction_log_design_path?: string;
  extraction_log_plan_path?: string;
  parser_design?: ParserSource;
  parser_plan?: ParserSource;
}

/**
 * Unified design contract shape produced by any parser source
 * (deterministic, ai, cached). Downstream pipeline stages consume this
 * uniformly via `ParseOutcome<DesignNormalized>`.
 */
export interface DesignNormalized {
  schema: "waygent.design_contract.v1";
  source_path: string;
  source_sha256: string;
  invariants: unknown[];
  prescriptive_blocks: Array<{
    id: string;
    language: string;
    body: string;
    sha256: string;
  }>;
  parser: ParserSource;
  extraction_confidence: "high" | "low";
  extracted_at: string;
}

/**
 * SP-1 invariant check kinds. The deterministic parser and AI extractor
 * both emit invariants whose `enforcement.check` matches one of these.
 */
export type InvariantCheck =
  | { kind: "shell"; command: string; expect_exit_zero: boolean }
  | { kind: "file_exists"; path: string }
  | { kind: "rg"; pattern: string; paths: string[]; must_match: boolean };

export type EnforcementMode = "deterministic" | "advisory";

export interface CrossPathInvariant {
  id: string;
  description: string;
  paths_bound: string[];
  enforcement:
    | { mode: "deterministic"; check: InvariantCheck }
    | { mode: "advisory"; rationale: string };
  policy_ack_required: boolean;
  policy_ack_min_confidence: AckConfidence;
}

export interface PolicyAck {
  invariant_id: string;
  confidence: AckConfidence;
  evidence: string;
}

/**
 * worker_result.v2 envelope shape consumed by SP-1's post-worker
 * validation. The envelope itself is owned by the orchestrator; SP-1
 * validates the additive fields (policy_ack, stale_test_candidates,
 * prescriptive_block_outputs).
 */
export interface WorkerEnvelopeV2 {
  schema: "waygent.worker_result.v2";
  task_id: string;
  summary: string;
  evidence: Record<string, unknown>;
  policy_ack: PolicyAck[];
  stale_test_candidates: string[];
  prescriptive_block_outputs: Array<{ id: string; sha256: string }>;
}

export interface PlanNormalized {
  schema: "waygent.plan_contract.v1";
  source_path: string;
  source_sha256: string;
  tasks: unknown[];
  parser: ParserSource;
  extraction_confidence: "high" | "low";
  extracted_at: string;
}

/**
 * Unified parse outcome returned by the fallback chain
 * (cache -> deterministic -> AI).
 */
export type ParseOutcome<T> =
  | { kind: "ok"; value: T; log: ParseExtractionLog }
  | { kind: "incomplete"; reason: IncompleteParseReason; details?: string }
  | { kind: "failed"; reason: string };

/**
 * Audit log written alongside the normalized JSON. Used to evidence which
 * parser ran, which prompt version (when AI), the source hash, and AI
 * evidence quotes.
 */
export interface ParseExtractionLog {
  source_path: string;
  source_sha256: string;
  parser: ParserSource;
  extracted_at: string;
  ai_prompt_sha256: string | null;
  ai_response_excerpt: string | null;
  evidence_quotes: Array<{ line_range: [number, number]; quote: string }>;
  reasoning: string | null;
}
