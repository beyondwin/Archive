import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { useParams } from "react-router-dom";

import {
  type RunArtifact,
  type RunDetail,
  useRun,
  useRunArtifacts,
  useRunEvents,
  useRunFailures,
} from "@/api/runs";
import { FailuresPanel } from "@/components/failures-panel";
import { OutcomeEvalPills } from "@/components/outcome-eval-pills";
import { RedactionBadge } from "@/components/redaction-badge";
import { TranscriptView } from "@/components/transcript-view";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function artifactHref(runId: string, artifact: RunArtifact): string | undefined {
  if (!artifact.downloadable || !artifact.sha256) return undefined;
  return `/api/v1/runs/${runId}/artifacts/${encodeURIComponent(artifact.sha256)}`;
}

function ArtifactsSealPanel({
  runId,
  seal,
  artifacts,
  artifactsLoading,
  artifactsError,
}: {
  runId: string;
  seal?: RunDetail["manifest_seal"];
  artifacts: RunArtifact[];
  artifactsLoading: boolean;
  artifactsError: boolean;
}) {
  const hasSealData = Boolean(
    seal?.manifest_digest ||
      seal?.integrity ||
      seal?.phase ||
      seal?.mismatches_count !== undefined,
  );

  return (
    <div className="space-y-4">
      {hasSealData && (
        <div className="grid gap-3 rounded-lg border border-zinc-200 bg-white p-4 text-sm md:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="text-xs text-zinc-500">Manifest digest</div>
            <div className="mt-1 break-all font-mono text-xs text-zinc-900">
              {seal?.manifest_digest ?? "-"}
            </div>
          </div>
          <div>
            <div className="text-xs text-zinc-500">Integrity</div>
            <div className="mt-1 font-medium text-zinc-900">{seal?.integrity ?? "-"}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-500">Mismatches</div>
            <div className="mt-1 font-medium text-zinc-900">
              {seal?.mismatches_count ?? 0} mismatches
            </div>
          </div>
          <div>
            <div className="text-xs text-zinc-500">Phase</div>
            <div className="mt-1 font-medium text-zinc-900">{seal?.phase ?? "-"}</div>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900">
          Artifacts
        </div>
        {artifactsLoading ? (
          <div className="p-4 text-sm text-zinc-500">Loading artifacts...</div>
        ) : artifacts.length > 0 ? (
          <div className="divide-y divide-zinc-100">
            {artifacts.map((artifact, index) => {
              const href = artifactHref(runId, artifact);
              return (
                <div
                  key={`${artifact.path ?? "artifact"}-${artifact.sha256 ?? index}`}
                  className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]"
                >
                  <div className="min-w-0">
                    {href ? (
                      <a
                        href={href}
                        className="inline-flex items-center gap-1 break-all font-mono text-xs text-sky-700 hover:text-sky-900"
                      >
                        <ExternalLink aria-hidden className="h-3 w-3 shrink-0" />
                        {artifact.path ?? artifact.sha256}
                      </a>
                    ) : (
                      <span className="break-all font-mono text-xs text-zinc-700">
                        {artifact.path ?? artifact.sha256 ?? "unknown artifact"}
                      </span>
                    )}
                  </div>
                  <div className="break-all font-mono text-xs text-zinc-500">
                    {artifact.sha256 ?? "-"}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="p-4 text-sm text-zinc-500">
            {artifactsError ? "Artifact list unavailable." : "No artifacts reported."}
          </div>
        )}
      </div>
    </div>
  );
}

export function RunDetailRoute() {
  const { runId } = useParams();
  const run = useRun(runId);
  const events = useRunEvents(runId);
  const failures = useRunFailures(runId);
  const artifacts = useRunArtifacts(runId);
  const [highlightSha, setHighlightSha] = useState<string | undefined>();
  const [tab, setTab] = useState<string | undefined>();

  if (run.isLoading) return <div className="p-6 text-sm">Loading run...</div>;
  if (run.error || !run.data) {
    return <div className="p-6 text-sm text-red-700">Run not found.</div>;
  }

  const detail = run.data;
  const failureList = detail.failures.length > 0 ? detail.failures : (failures.data ?? []);
  const defaultTab = failureList.length > 0 ? "failures" : "transcript";
  const seal = detail.manifest_seal;
  const artifactList = detail.artifacts ?? artifacts.data ?? [];

  return (
    <div className="p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">
            workspaces / {detail.workspace_short || detail.workspace_id}
          </div>
          <h1 className="mt-1 truncate font-mono text-lg text-zinc-950">{runId}</h1>
        </div>
        <RedactionBadge visible />
      </div>

      <div className="mt-4">
        <OutcomeEvalPills
          agentOutcome={detail.agent_outcome}
          evalStatus={detail.eval_status}
          failureCount={failureList.length}
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-4 text-xs text-zinc-600">
        <span>
          agent <b className="text-zinc-900">{detail.agent_name ?? detail.agent}</b>
        </span>
        <span>sealed {seal?.phase ?? "-"}</span>
        <span>integrity {seal?.integrity ?? "-"}</span>
        {seal?.manifest_digest && (
          <span>
            manifest{" "}
            <code className="text-[10px]">{seal.manifest_digest.slice(0, 24)}...</code>
          </span>
        )}
        {detail.partial && <span className="font-medium text-amber-700">partial run</span>}
      </div>

      <Tabs value={tab ?? defaultTab} onValueChange={setTab} className="mt-5">
        <TabsList>
          <TabsTrigger value="failures">Failures ({failureList.length})</TabsTrigger>
          <TabsTrigger value="risks">Risks ({detail.risks.length})</TabsTrigger>
          <TabsTrigger value="transcript">Transcript</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts/Seal</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>
        <TabsContent value="failures">
          <FailuresPanel
            failures={failureList}
            onEvidenceClick={(sha) => {
              setHighlightSha(sha);
              setTab("transcript");
            }}
          />
        </TabsContent>
        <TabsContent value="risks">
          <FailuresPanel failures={detail.risks} />
        </TabsContent>
        <TabsContent value="transcript">
          {events.isLoading ? (
            <div className="text-sm text-zinc-500">Loading events...</div>
          ) : (
            <TranscriptView events={events.data ?? []} highlightSha={highlightSha} />
          )}
        </TabsContent>
        <TabsContent value="artifacts">
          <ArtifactsSealPanel
            runId={detail.run_id}
            seal={detail.manifest_seal}
            artifacts={artifactList}
            artifactsLoading={artifacts.isLoading}
            artifactsError={artifacts.isError}
          />
        </TabsContent>
        <TabsContent value="metadata">
          <pre className="overflow-auto rounded-lg bg-zinc-950 p-4 text-xs text-zinc-100">
            {JSON.stringify(detail, null, 2)}
          </pre>
        </TabsContent>
      </Tabs>
    </div>
  );
}
