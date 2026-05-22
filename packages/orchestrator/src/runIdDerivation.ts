import { basename } from "node:path";

export interface DeriveRunIdInput {
  plan_path?: string | null;
  now?: Date;
  suffix?: number;
}

export const RUN_ID_COLLISION_MAX_RETRIES = 16;

export function deriveRunId(input: DeriveRunIdInput = {}): string {
  const now = input.now ?? new Date();
  const stamp = formatStamp(now);
  const slug = slugFromPlan(input.plan_path);
  const base = slug ? `${slug}_${stamp}` : `run_${stamp}`;
  const suffix = input.suffix ?? 0;
  return suffix > 0 ? `${base}_${suffix}` : base;
}

export function planSlug(planPath?: string | null): string | null {
  return slugFromPlan(planPath);
}

function slugFromPlan(planPath?: string | null): string | null {
  if (!planPath) return null;
  const stem = basename(planPath).replace(/\.[^./]+$/, "");
  const stripped = stem.replace(/^\d{4}-\d{2}-\d{2}-/, "");
  const slug = stripped
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug.length > 0 ? slug : null;
}

function formatStamp(now: Date): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  return [
    now.getUTCFullYear(),
    pad(now.getUTCMonth() + 1),
    pad(now.getUTCDate())
  ].join("") + "_" + [
    pad(now.getUTCHours()),
    pad(now.getUTCMinutes()),
    pad(now.getUTCSeconds())
  ].join("");
}
