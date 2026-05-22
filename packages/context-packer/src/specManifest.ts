import type { SpecManifest } from "@waygent/contracts";

export interface SpecManifestTaskInput {
  id: string;
  title: string;
  instructions?: string[];
}

export interface BuildSpecManifestInput {
  spec: string;
  spec_path: string | null;
  tasks: SpecManifestTaskInput[];
  built_at?: string;
}

export interface SpecSlice {
  text: string;
  sections_used: string[];
  fallback_used: boolean;
  fallback_reason: string | null;
  slice_bytes: number;
}

const HEADING = /^(#{2,3})\s+(.+)$/gm;

export function buildSpecManifest(input: BuildSpecManifestInput): SpecManifest {
  const sections = parseSections(input.spec);
  const byId = Object.fromEntries(sections.map((section) => [section.id, section]));
  const taskToSections: SpecManifest["task_to_sections"] = {};
  for (const task of input.tasks) {
    const matched = matchTaskSections(task, sections);
    taskToSections[task.id] = matched.length > 0
      ? { sections: matched, fallback_used: false, source: hasExplicitRef(task, sections) ? "explicit" : "heuristic" }
      : { sections: [], fallback_used: true, source: "fallback" };
  }
  return {
    spec_path: input.spec_path,
    spec_total_chars: input.spec.length,
    sections: byId,
    task_to_sections: taskToSections,
    fallback_policy: "full_spec_on_blocker",
    built_at: input.built_at ?? new Date().toISOString()
  };
}

export function specSliceForTask(spec: string, manifest: SpecManifest | null | undefined, taskId: string): SpecSlice {
  const mapping = manifest?.task_to_sections[taskId];
  if (!manifest || !mapping || mapping.fallback_used || mapping.sections.length === 0) {
    return {
      text: spec,
      sections_used: [],
      fallback_used: true,
      fallback_reason: !manifest ? "no_spec_manifest" : !mapping ? "no_task_mapping" : "no_matching_sections",
      slice_bytes: Buffer.byteLength(spec)
    };
  }
  const chunks: string[] = [];
  const used: string[] = [];
  for (const sectionId of mapping.sections) {
    const section = manifest.sections[sectionId];
    if (!section) continue;
    chunks.push(spec.slice(section.range[0], section.range[1]).trim());
    used.push(sectionId);
  }
  if (chunks.length === 0) {
    return {
      text: spec,
      sections_used: [],
      fallback_used: true,
      fallback_reason: "section_ranges_missing",
      slice_bytes: Buffer.byteLength(spec)
    };
  }
  const text = `${chunks.join("\n\n")}\n`;
  return {
    text,
    sections_used: used,
    fallback_used: false,
    fallback_reason: null,
    slice_bytes: Buffer.byteLength(text)
  };
}

function parseSections(spec: string): SpecManifest["sections"][string][] {
  const matches = [...spec.matchAll(HEADING)];
  if (matches.length === 0 && spec.trim().length > 0) {
    return [{
      id: "full_spec",
      title: "Full Spec",
      range: [0, spec.length],
      byte_offset: [0, Buffer.byteLength(spec)]
    }];
  }
  const seen = new Map<string, number>();
  return matches.map((match, index) => {
    const start = match.index ?? 0;
    const end = index + 1 < matches.length ? matches[index + 1]!.index ?? spec.length : spec.length;
    const title = (match[2] ?? "").trim();
    const baseId = sectionId(title);
    return {
      id: uniqueSectionId(baseId, seen),
      title,
      range: [start, end],
      byte_offset: [Buffer.byteLength(spec.slice(0, start)), Buffer.byteLength(spec.slice(0, end))]
    };
  });
}

function matchTaskSections(task: SpecManifestTaskInput, sections: SpecManifest["sections"][string][]): string[] {
  const haystack = [task.title, ...(task.instructions ?? [])].join("\n").toLowerCase();
  const explicit = sections
    .filter((section) => {
      const leading = section.title.match(/^([a-z]\d+)\b/i)?.[1]?.toLowerCase();
      return (leading && haystack.includes(leading)) || haystack.includes(section.id.toLowerCase());
    })
    .map((section) => section.id);
  if (explicit.length > 0) return [...new Set(explicit)];
  const words = significantWords(haystack);
  return sections
    .filter((section) => [...significantWords(section.title.toLowerCase())].some((word) => words.has(word)))
    .map((section) => section.id);
}

function hasExplicitRef(task: SpecManifestTaskInput, sections: SpecManifest["sections"][string][]): boolean {
  const haystack = [task.title, ...(task.instructions ?? [])].join("\n").toLowerCase();
  return sections.some((section) => {
    const leading = section.title.match(/^([a-z]\d+)\b/i)?.[1]?.toLowerCase();
    return (leading && haystack.includes(leading)) || haystack.includes(section.id.toLowerCase());
  });
}

function significantWords(value: string): Set<string> {
  return new Set(value
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((word) => word.length >= 4 && !["task", "spec", "design", "runtime", "implement"].includes(word)));
}

function sectionId(title: string): string {
  const normalized = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return normalized || "section";
}

function uniqueSectionId(baseId: string, seen: Map<string, number>): string {
  const count = (seen.get(baseId) ?? 0) + 1;
  seen.set(baseId, count);
  return count === 1 ? baseId : `${baseId}_${count}`;
}
