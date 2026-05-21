import * as RT from "@radix-ui/react-tabs";

import { cn } from "@/lib/cn";

export const Tabs = RT.Root;

export function TabsList({ className, ...props }: RT.TabsListProps) {
  return (
    <RT.List
      className={cn("flex gap-1 border-b border-zinc-200", className)}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: RT.TabsTriggerProps) {
  return (
    <RT.Trigger
      className={cn(
        "px-3 py-2 text-sm text-zinc-600 hover:text-zinc-950",
        "data-[state=active]:-mb-px data-[state=active]:border-b-2 data-[state=active]:border-zinc-950 data-[state=active]:text-zinc-950",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: RT.TabsContentProps) {
  return <RT.Content className={cn("py-4", className)} {...props} />;
}
