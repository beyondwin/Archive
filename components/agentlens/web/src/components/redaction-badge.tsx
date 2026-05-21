import { Badge } from "@/components/ui/badge";

export function RedactionBadge({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return <Badge tone="warning">redacted view</Badge>;
}
