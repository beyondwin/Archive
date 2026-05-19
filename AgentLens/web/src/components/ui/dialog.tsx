import * as RD from "@radix-ui/react-dialog";

import { cn } from "@/lib/cn";

export const Dialog = RD.Root;
export const DialogTrigger = RD.Trigger;
export const DialogClose = RD.Close;

export function DialogContent({
  className,
  children,
  ...props
}: RD.DialogContentProps) {
  return (
    <RD.Portal>
      <RD.Overlay className="fixed inset-0 bg-zinc-950/35" />
      <RD.Content
        className={cn(
          "fixed left-1/2 top-1/2 w-[90vw] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-4 shadow-xl",
          className,
        )}
        {...props}
      >
        {children}
      </RD.Content>
    </RD.Portal>
  );
}
