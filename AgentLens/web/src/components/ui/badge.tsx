import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

type Tone = "default" | "success" | "warning" | "danger" | "info" | "muted";

const toneClass: Record<Tone, string> = {
  default: "bg-zinc-100 text-zinc-700",
  success: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-900",
  danger: "bg-red-100 text-red-800",
  info: "bg-sky-100 text-sky-800",
  muted: "bg-zinc-200 text-zinc-600",
};

export function Badge({
  tone = "default",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
        toneClass[tone],
        className,
      )}
      {...props}
    />
  );
}
