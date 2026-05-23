import { createHash } from "node:crypto";
import type {
  DesignNormalized,
  PlanNormalized,
  ParseOutcome,
  ParseExtractionLog
} from "../types";

export const EXTRACTOR_VERSION = "v1";

export interface ExtractorRequest {
  kind: "design" | "plan";
  sourcePath: string;
  sourceMarkdown: string;
}

export interface ExtractorResponse {
  schemaPayload: unknown;
  reasoning: string | null;
  evidenceQuotes: Array<{ line_range: [number, number]; quote: string }>;
  confidence: "high" | "low";
}

export interface ExtractorProvider {
  extract(req: ExtractorRequest): Promise<ExtractorResponse>;
  readonly name: string;
}

export class FakeExtractorProvider implements ExtractorProvider {
  readonly name = "fake";
  constructor(
    private readonly responses: Map<string, ExtractorResponse | "throw" | "malformed">
  ) {}

  async extract(req: ExtractorRequest): Promise<ExtractorResponse> {
    const key = `${req.kind}:${req.sourcePath}`;
    const r = this.responses.get(key);
    if (!r) throw new Error(`fake provider has no fixture for ${key}`);
    if (r === "throw") throw new Error("simulated transient");
    if (r === "malformed") {
      return {
        schemaPayload: { bogus: true },
        reasoning: null,
        evidenceQuotes: [],
        confidence: "low"
      };
    }
    return r;
  }
}

function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

function nowIso(): string {
  return new Date().toISOString();
}

function isDesignPayload(value: unknown): value is { invariants: unknown[]; prescriptive_blocks: DesignNormalized["prescriptive_blocks"] } {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v.invariants) && Array.isArray(v.prescriptive_blocks);
}

function isPlanPayload(value: unknown): value is { tasks: unknown[] } {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v.tasks);
}

export async function extractDesignWithAI(
  provider: ExtractorProvider,
  markdown: string,
  sourcePath: string
): Promise<ParseOutcome<DesignNormalized>> {
  const req: ExtractorRequest = { kind: "design", sourcePath, sourceMarkdown: markdown };
  let resp: ExtractorResponse | undefined;
  let attempt = 0;
  while (true) {
    try {
      resp = await provider.extract(req);
      if (!isDesignPayload(resp.schemaPayload)) {
        if (attempt >= 1) return { kind: "failed", reason: "ai_malformed_payload" };
        attempt++;
        continue;
      }
      break;
    } catch (err) {
      if (attempt >= 2) return { kind: "failed", reason: `ai_provider_error: ${(err as Error).message}` };
      attempt++;
      await new Promise((r) => setTimeout(r, 50 * Math.pow(2, attempt)));
    }
  }
  const payload = resp!.schemaPayload as { invariants: unknown[]; prescriptive_blocks: DesignNormalized["prescriptive_blocks"] };
  const log: ParseExtractionLog = {
    source_path: sourcePath,
    source_sha256: sha256(markdown),
    parser: "ai",
    extracted_at: nowIso(),
    ai_prompt_sha256: sha256(`design:${sourcePath}`),
    ai_response_excerpt: JSON.stringify(payload).slice(0, 200),
    evidence_quotes: resp!.evidenceQuotes,
    reasoning: resp!.reasoning
  };
  return {
    kind: "ok",
    value: {
      schema: "waygent.design_contract.v1",
      source_path: sourcePath,
      source_sha256: sha256(markdown),
      invariants: payload.invariants,
      prescriptive_blocks: payload.prescriptive_blocks,
      extracted_at: log.extracted_at,
      parser: "ai",
      extraction_confidence: resp!.confidence
    },
    log
  };
}

export async function extractPlanWithAI(
  provider: ExtractorProvider,
  markdown: string,
  sourcePath: string
): Promise<ParseOutcome<PlanNormalized>> {
  const req: ExtractorRequest = { kind: "plan", sourcePath, sourceMarkdown: markdown };
  let resp: ExtractorResponse | undefined;
  let attempt = 0;
  while (true) {
    try {
      resp = await provider.extract(req);
      if (!isPlanPayload(resp.schemaPayload)) {
        if (attempt >= 1) return { kind: "failed", reason: "ai_malformed_payload" };
        attempt++;
        continue;
      }
      break;
    } catch (err) {
      if (attempt >= 2) return { kind: "failed", reason: `ai_provider_error: ${(err as Error).message}` };
      attempt++;
      await new Promise((r) => setTimeout(r, 50 * Math.pow(2, attempt)));
    }
  }
  const payload = resp!.schemaPayload as { tasks: unknown[] };
  const log: ParseExtractionLog = {
    source_path: sourcePath,
    source_sha256: sha256(markdown),
    parser: "ai",
    extracted_at: nowIso(),
    ai_prompt_sha256: sha256(`plan:${sourcePath}`),
    ai_response_excerpt: JSON.stringify(payload).slice(0, 200),
    evidence_quotes: resp!.evidenceQuotes,
    reasoning: resp!.reasoning
  };
  return {
    kind: "ok",
    value: {
      schema: "waygent.plan_contract.v1",
      source_path: sourcePath,
      source_sha256: sha256(markdown),
      tasks: payload.tasks,
      extracted_at: log.extracted_at,
      parser: "ai",
      extraction_confidence: resp!.confidence
    },
    log
  };
}
