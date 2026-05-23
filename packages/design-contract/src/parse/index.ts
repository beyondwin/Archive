import { createHash } from "node:crypto";
import type {
  DesignNormalized,
  PlanNormalized,
  ParseOutcome,
  ParseExtractionLog
} from "../types";
import {
  parseDesignDeterministic,
  parsePlanDeterministic,
  type DesignDeterministicOutput,
  type PlanDeterministicOutput
} from "./deterministic";
import {
  extractDesignWithAI,
  extractPlanWithAI,
  EXTRACTOR_VERSION,
  type ExtractorProvider
} from "./ai";
import { ArtifactCache, type CacheKey } from "./cache";

export interface ParseOptions {
  cacheRoot: string;
  provider: ExtractorProvider;
}

function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

function nowIso(): string {
  return new Date().toISOString();
}

function normalizeDesignFromDeterministic(
  d: DesignDeterministicOutput,
  sourceMarkdown: string
): DesignNormalized {
  return {
    schema: "waygent.design_contract.v1",
    source_path: d.source_path,
    source_sha256: sha256(sourceMarkdown),
    invariants: d.invariants,
    prescriptive_blocks: d.prescriptive_blocks.map((b) => ({
      id: b.id,
      language: b.language,
      body: b.body,
      sha256: b.sha256
    })),
    parser: "deterministic",
    extraction_confidence: d.extraction_confidence,
    extracted_at: nowIso()
  };
}

function normalizePlanFromDeterministic(
  p: PlanDeterministicOutput,
  sourceMarkdown: string
): PlanNormalized {
  return {
    schema: "waygent.plan_contract.v1",
    source_path: p.source_path,
    source_sha256: sha256(sourceMarkdown),
    tasks: p.tasks,
    parser: "deterministic",
    extraction_confidence: p.extraction_confidence,
    extracted_at: nowIso()
  };
}

function deterministicLog(value: { source_path: string; source_sha256: string }): ParseExtractionLog {
  return {
    source_path: value.source_path,
    source_sha256: value.source_sha256,
    parser: "deterministic",
    extracted_at: nowIso(),
    ai_prompt_sha256: null,
    ai_response_excerpt: null,
    evidence_quotes: [],
    reasoning: null
  };
}

function cachedLog(parsed: DesignNormalized | PlanNormalized): ParseExtractionLog {
  return {
    source_path: parsed.source_path,
    source_sha256: parsed.source_sha256,
    parser: "cached",
    extracted_at: nowIso(),
    ai_prompt_sha256: null,
    ai_response_excerpt: null,
    evidence_quotes: [],
    reasoning: null
  };
}

function isDesignNormalized(value: unknown): value is DesignNormalized {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return v.schema === "waygent.design_contract.v1" && Array.isArray(v.invariants);
}

function isPlanNormalized(value: unknown): value is PlanNormalized {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return v.schema === "waygent.plan_contract.v1" && Array.isArray(v.tasks);
}

export async function parseDesignSource(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<ParseOutcome<DesignNormalized>> {
  const cache = new ArtifactCache(options.cacheRoot);
  const key: CacheKey = {
    sourcePath,
    sourceSha256: sha256(markdown),
    extractorVersion: EXTRACTOR_VERSION
  };
  const cached = await cache.read(key);
  if (isDesignNormalized(cached)) {
    const value = { ...cached, parser: "cached" as const };
    return { kind: "ok", value, log: cachedLog(value) };
  }
  const det = parseDesignDeterministic(markdown, sourcePath);
  if (det.kind === "ok") {
    const value = normalizeDesignFromDeterministic(det.value, markdown);
    await cache.write(key, value);
    return { kind: "ok", value, log: deterministicLog(value) };
  }
  const ai = await extractDesignWithAI(options.provider, markdown, sourcePath);
  if (ai.kind === "ok") {
    await cache.write(key, ai.value);
  }
  return ai;
}

export async function parsePlanSource(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<ParseOutcome<PlanNormalized>> {
  const cache = new ArtifactCache(options.cacheRoot);
  const key: CacheKey = {
    sourcePath,
    sourceSha256: sha256(markdown),
    extractorVersion: EXTRACTOR_VERSION
  };
  const cached = await cache.read(key);
  if (isPlanNormalized(cached)) {
    const value = { ...cached, parser: "cached" as const };
    return { kind: "ok", value, log: cachedLog(value) };
  }
  const det = parsePlanDeterministic(markdown, sourcePath);
  if (det.kind === "ok") {
    const value = normalizePlanFromDeterministic(det.value, markdown);
    await cache.write(key, value);
    return { kind: "ok", value, log: deterministicLog(value) };
  }
  const ai = await extractPlanWithAI(options.provider, markdown, sourcePath);
  if (ai.kind === "ok") {
    await cache.write(key, ai.value);
  }
  return ai;
}
