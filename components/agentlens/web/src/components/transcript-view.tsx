import { Badge } from "@/components/ui/badge";

type Event = Record<string, unknown> & {
  type?: string;
  _error?: string;
  line?: number;
};

const typeTone: Record<string, "success" | "info" | "warning" | "danger" | "muted"> = {
  "run.started": "success",
  "command.started": "info",
  "command.finished": "muted",
  "run.finalized": "success",
  "manifest.sealed": "warning",
};

export function TranscriptView({
  events,
  highlightSha,
}: {
  events: Event[];
  highlightSha?: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white font-mono text-xs leading-relaxed">
      {events.map((event, index) => {
        if (event._error === "parse") {
          return (
            <div key={index} className="border-b border-zinc-100 px-3 py-2 text-red-700">
              unparseable line {String(event.line ?? "?")}
            </div>
          );
        }
        const type = String(event.type ?? "event");
        const hit = Boolean(highlightSha && JSON.stringify(event).includes(highlightSha));
        return (
          <div
            key={index}
            className={hit ? "bg-yellow-50 px-3 py-2" : "border-b border-zinc-100 px-3 py-2"}
          >
            <div className="flex items-center gap-2">
              <span className="w-10 text-zinc-400">#{index + 1}</span>
              <Badge tone={typeTone[type] ?? "muted"}>{type}</Badge>
              <span className="truncate text-zinc-700">
                {JSON.stringify(
                  Object.fromEntries(
                    Object.entries(event).filter(
                      ([key]) => !["type", "_error", "line"].includes(key),
                    ),
                  ),
                )}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
