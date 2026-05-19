import { ShieldCheck } from "lucide-react";

import { useMeta } from "@/api/meta";
import { Badge } from "@/components/ui/badge";

export function TopBar() {
  const meta = useMeta();
  return (
    <header className="flex min-h-14 items-center justify-between border-b border-zinc-200 bg-white px-5">
      <div>
        <div className="text-sm font-semibold text-zinc-950">Run Observatory</div>
        <div className="text-xs text-zinc-500">
          {meta.data?.store_path ?? "AGENTLENS_HOME"}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {meta.data?.demo_mode && <Badge tone="warning">demo</Badge>}
        <Badge tone={meta.data?.store_exists ? "success" : "muted"}>
          <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
          {meta.data?.schema_version ?? "v1"}
        </Badge>
      </div>
    </header>
  );
}
