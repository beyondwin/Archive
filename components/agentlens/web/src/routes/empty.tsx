import { Copy, Database, Play } from "lucide-react";

import { Card, CardBody } from "@/components/ui/card";

const steps = [
  { icon: Play, label: "agentlens run -- <command>", detail: "record an agent run" },
  { icon: Database, label: "agentlens eval --latest", detail: "write evaluator output" },
  { icon: Copy, label: "agentlens serve --demo", detail: "load sample runs" },
];

export function EmptyRoute() {
  return (
    <div className="p-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold text-zinc-950">No runs found</h1>
        <p className="mt-2 text-sm text-zinc-600">
          AgentLens is pointed at an empty store. These commands populate the
          read-only viewer.
        </p>
      </div>
      <div className="mt-6 grid gap-3 md:grid-cols-3">
        {steps.map((step) => (
          <Card key={step.label}>
            <CardBody>
              <step.icon aria-hidden className="h-5 w-5 text-sky-700" />
              <div className="mt-3 font-mono text-sm">{step.label}</div>
              <div className="mt-1 text-sm text-zinc-500">{step.detail}</div>
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  );
}
