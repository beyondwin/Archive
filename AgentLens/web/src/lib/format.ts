export function relativeFromNow(iso: string | null | undefined): string {
  if (!iso) return "-";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "-";
  const sec = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export function durationOf(startedAt?: string, endedAt?: string): string {
  if (!startedAt || !endedAt) return "-";
  const sec = Math.max(
    0,
    Math.floor((Date.parse(endedAt) - Date.parse(startedAt)) / 1000),
  );
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m${(sec % 60).toString().padStart(2, "0")}s`;
}
