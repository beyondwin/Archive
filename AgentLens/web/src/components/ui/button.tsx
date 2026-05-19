import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

type Variant = "default" | "ghost" | "outline";

export function Button({
  variant = "default",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cn(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-700",
        variant === "default" &&
          "bg-zinc-950 text-white hover:bg-zinc-800 disabled:opacity-50",
        variant === "ghost" && "text-zinc-700 hover:bg-zinc-100",
        variant === "outline" &&
          "border border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50",
        className,
      )}
      {...props}
    />
  );
}
