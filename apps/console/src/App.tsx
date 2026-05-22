import { useEffect, useMemo, useState } from "react";
import {
  buildConsoleUiModel,
  buildRunDetailModel,
  consoleRunToRealDetail,
  demoConsoleSnapshot,
  realRunDetailToConsoleRun,
  realRunSummaryToConsoleRun,
  type ConsoleRun,
  type ConsoleSnapshot,
  type RealRunDetailResponse,
  type RealRunSummaryResponse,
  type RunDetailModel,
  type TrustVerdict
} from "./uiModel";
import "./styles.css";

const verdictLabels: Record<TrustVerdict, string> = {
  trusted: "Trusted",
  failed: "Failed",
  insufficient_evidence: "Insufficient evidence"
};

interface AppProps {
  apiRoot?: string;
}

function RunList({
  runs,
  selectedRunId,
  onSelect
}: {
  runs: ConsoleRun[];
  selectedRunId: string;
  onSelect: (runId: string) => void;
}) {
  return (
    <aside className="run-list" aria-label="Run list">
      <div className="panel-heading">
        <span>Runs</span>
        <span>{runs.length}</span>
      </div>
      <div className="run-list-items">
        {runs.map((run) => (
          <button
            className={run.runId === selectedRunId ? "run-row selected" : "run-row"}
            key={run.runId}
            onClick={() => onSelect(run.runId)}
            type="button"
          >
            <span className={`status-dot ${run.status}`} />
            <span>
              <strong>{run.title}</strong>
              <small>{run.runId}</small>
              <small>{run.applyStatus.state} · {run.applyStatus.reason}</small>
            </span>
            <span className={`verdict ${run.trust.verdict}`}>{verdictLabels[run.trust.verdict]}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function TaskTimeline({ run }: { run: ConsoleRun }) {
  return (
    <section className="section-band" aria-labelledby="tasks-heading">
      <h2 id="tasks-heading">Task Timeline</h2>
      <div className="timeline-grid">
        {run.tasks.map((task) => (
          <div className="timeline-row" key={task.taskId}>
            <span>{task.taskId}</span>
            <strong>{task.title}</strong>
            <span>{task.owner}</span>
            <span>{task.status}</span>
            <span>{task.checkpoint}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function EventTimeline({ run }: { run: ConsoleRun }) {
  const detail = buildRunDetailModel(consoleRunToRealDetail(run));
  return (
    <section className="section-band" aria-labelledby="events-heading">
      <h2 id="events-heading">Event Timeline</h2>
      <div className="event-stack">
        {detail.timeline.map((event) => (
          <article
            className={`event-row ${event.outcome === "failed" ? "error" : event.outcome === "blocked" ? "warning" : "info"}`}
            key={`${event.sequence}-${event.event_type}`}
          >
            <span>{event.sequence}</span>
            <strong>{event.event_type}</strong>
            <span>{event.outcome}</span>
            <p>{event.summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function TrustReport({ run }: { run: ConsoleRun }) {
  return (
    <section className="section-band compact" aria-labelledby="trust-heading">
      <h2 id="trust-heading">Trust Report</h2>
      <div className={`trust-meter ${run.trust.verdict}`}>
        <span>{verdictLabels[run.trust.verdict]}</span>
        <strong>{Math.round(run.trust.score * 100)}%</strong>
      </div>
      <ul>
        {run.trust.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </section>
  );
}

function FailureBarriers({ run }: { run: ConsoleRun }) {
  return (
    <section className="section-band compact" aria-labelledby="failures-heading">
      <h2 id="failures-heading">Failure Barriers</h2>
      {run.failures.length === 0 ? (
        <p className="empty-state">No active barriers</p>
      ) : (
        run.failures.map((failure) => (
          <article className="barrier-row" key={`${failure.taskId}-${failure.failureClass}`}>
            <strong>{failure.failureClass}</strong>
            <span>{failure.taskId}</span>
            <p>{failure.summary}</p>
            <small>{failure.recoveryAction}</small>
          </article>
        ))
      )}
    </section>
  );
}

function DecisionPackets({ run }: { run: ConsoleRun }) {
  return (
    <section className="section-band compact" aria-labelledby="decisions-heading">
      <h2 id="decisions-heading">Decision Packets</h2>
      {run.decisionPackets.length === 0 ? (
        <p className="empty-state">No decision packet</p>
      ) : (
        run.decisionPackets.map((packet) => (
          <article className="decision-row" key={`${packet.taskId}-${packet.failureClass}`}>
            <strong>{packet.taskId}</strong>
            <span>{packet.failureClass}</span>
            <p>{packet.summary}</p>
            <small>{packet.allowedActions.join(", ")}</small>
          </article>
        ))
      )}
    </section>
  );
}

function ApplyStatus({ run }: { run: ConsoleRun }) {
  const checkpointRefs = run.applyStatus.checkpointRefs.length > 0
    ? run.applyStatus.checkpointRefs.join(", ")
    : run.applyStatus.checkpointRef || "none";
  const commandText = run.applyStatus.canApply
    ? "Apply checkpoint"
    : `Apply disabled: ${run.applyStatus.reason}`;

  return (
    <section className="section-band compact" aria-labelledby="apply-heading">
      <h2 id="apply-heading">Apply Status</h2>
      <div className={`apply-box ${run.applyStatus.state}`}>
        <strong>{run.applyStatus.state}</strong>
        <span>reason: {run.applyStatus.reason}</span>
        <span>checkpoint refs: {checkpointRefs}</span>
        <span>combined patch: {run.applyStatus.combinedPatchRef ?? "none"}</span>
        <p>{run.applyStatus.canApply ? "Apply command enabled" : "Apply command disabled"}</p>
      </div>
      <button disabled={!run.applyStatus.canApply} type="button">
        {commandText}
      </button>
    </section>
  );
}

function EvidenceList({
  title,
  items,
  empty
}: {
  title: string;
  items: object[];
  empty: string;
}) {
  return (
    <section className="section-band compact evidence-list" aria-label={title}>
      <h2>{title}</h2>
      {items.length === 0 ? (
        <p className="empty-state">{empty}</p>
      ) : (
        items.map((item, index) => (
          <article className="evidence-row" key={`${title}-${index}`}>
            {Object.entries(item).slice(0, 4).map(([key, value]) => (
              <div key={key}>
                <span>{key}</span>
                <strong>{formatEvidenceValue(value)}</strong>
              </div>
            ))}
          </article>
        ))
      )}
    </section>
  );
}

function ExecutionIntelligence({ detail }: { detail: RunDetailModel }) {
  const explanation = detail.execution_explanation;
  return (
    <section className="section-band execution-intelligence" aria-label="Execution intelligence">
      <h2>Execution Intelligence</h2>
      {explanation ? (
        <>
          <p className="summary-line">{explanation.status_summary}</p>
          <div className="intel-grid">
            <div>
              <span>Waves</span>
              <strong>{explanation.waves.length}</strong>
            </div>
            <div>
              <span>Barriers</span>
              <strong>{explanation.barriers.length}</strong>
            </div>
            <div>
              <span>Indexed artifacts</span>
              <strong>{explanation.artifact_health.indexed_count}</strong>
            </div>
            <div>
              <span>Artifact blockers</span>
              <strong>{explanation.artifact_health.missing_count + explanation.artifact_health.drift_count}</strong>
            </div>
          </div>
          {detail.next_action ? (
            <p className="next-action">Next action: {detail.next_action}</p>
          ) : null}
          {detail.provider_log_summary ? (
            <div className="provider-signal-panel">
              <h3>Provider Signals</h3>
              <div className="signal-grid">
                <span>Errors {detail.provider_log_summary.counts.error}</span>
                <span>Warnings {detail.provider_log_summary.counts.warning}</span>
                <span>Plugin {detail.provider_log_summary.counts.plugin_manifest}</span>
                <span>MCP {detail.provider_log_summary.counts.mcp}</span>
                <span>Skills {detail.provider_log_summary.counts.skill_loader}</span>
                <span>Other {detail.provider_log_summary.counts.other}</span>
              </div>
            </div>
          ) : null}
          <EvidenceList title="Cost Hotspots" items={explanation.cost_hotspots} empty="No cost hotspots" />
          <EvidenceList title="Scheduling Barriers" items={explanation.barriers} empty="No scheduling barriers" />
        </>
      ) : (
        <p className="empty-state">No execution explanation</p>
      )}
    </section>
  );
}

function OperationalMaturity({ detail }: { detail: RunDetailModel }) {
  const dogfood = detail.dogfood_evidence;
  const runtimeCost = detail.runtime_cost;
  const provider = detail.provider_readiness;
  const hardBlocker = detail.operational_maturity?.hard_blocker;
  const topHotspot = runtimeCost?.top_hotspots[0] ?? detail.execution_explanation?.cost_hotspots[0] ?? null;

  return (
    <section className="section-band operational-maturity" aria-label="Operational maturity">
      <div className="section-title-row">
        <h2>Operational Maturity</h2>
        <strong>{detail.operational_maturity?.apply_readiness.status ?? detail.header.apply_status}</strong>
      </div>
      <div className="maturity-grid">
        <div>
          <span>Hard blocker</span>
          <strong>{hardBlocker?.failure_class ?? "none"}</strong>
          <small>{hardBlocker?.summary ?? "No active failure barrier"}</small>
        </div>
        <div>
          <span>Runtime hotspot</span>
          <strong>{topHotspot ? `${topHotspot.phase} ${topHotspot.duration_ms}ms` : "none"}</strong>
          <small>{runtimeCost ? `${runtimeCost.measured_wave_count} waves, score ${runtimeCost.parallelism_score}` : "No runtime-cost projection"}</small>
        </div>
        <div>
          <span>Dogfood evidence</span>
          <strong>{dogfood?.status ?? "missing"}</strong>
          <small>{dogfood?.missing_reasons[0] ?? "Evidence checklist is complete"}</small>
        </div>
        <div>
          <span>Provider readiness</span>
          <strong>{provider?.status ?? "unknown"}</strong>
          <small>{provider?.provider ?? "not configured"}</small>
        </div>
      </div>
      {detail.next_action ? (
        <p className="next-action">Next action: {detail.next_action}</p>
      ) : null}
      <div className="maturity-lists">
        <EvidenceList title="Dogfood Checklist" items={dogfood?.checklist ?? []} empty="No dogfood checklist" />
        <EvidenceList title="Runtime Phase Cost" items={runtimeCost?.phase_totals ?? []} empty="No runtime-cost totals" />
        <EvidenceList title="Provider Readiness" items={provider ? [provider] : []} empty="No provider readiness" />
      </div>
    </section>
  );
}

function OperationalEvidence({ detail }: { detail: RunDetailModel }) {
  return (
    <div className="projection-grid v2-grid">
      <EvidenceList title="Provider Attempts" items={detail.provider_attempts} empty="No provider attempts" />
      <EvidenceList title="Verification Evidence" items={detail.verification} empty="No verification evidence" />
      <EvidenceList title="Review Findings" items={detail.reviews} empty="No review findings" />
      <EvidenceList title="Recovery Decisions" items={detail.recovery} empty="No recovery decisions" />
      <section className="section-band compact evidence-list" aria-label="Drift">
        <h2>Drift</h2>
        {detail.drift ? (
          <article className="evidence-row">
            <div>
              <span>last_checked_at</span>
              <strong>{detail.drift.last_checked_at ?? "not checked"}</strong>
            </div>
            <div>
              <span>records</span>
              <strong>{detail.drift.records.length}</strong>
            </div>
            <div>
              <span>unrepaired_blockers</span>
              <strong>{detail.drift.unrepaired_blockers.length}</strong>
            </div>
          </article>
        ) : (
          <p className="empty-state">No drift report</p>
        )}
      </section>
    </div>
  );
}

function OutcomeStrip({ detail }: { detail: RunDetailModel }) {
  const outcome = detail.outcome_strip;
  return (
    <section className="outcome-strip" aria-label="Operator outcome">
      <div>
        <span>Status</span>
        <strong>{outcome.display_status}</strong>
      </div>
      <div>
        <span>Primary blocker</span>
        <strong>{outcome.primary_blocker ?? "none"}</strong>
      </div>
      <div>
        <span>Next action</span>
        <strong>{outcome.next_action ?? "inspect_run"}</strong>
      </div>
      <div>
        <span>Apply</span>
        <strong>{outcome.apply_status}</strong>
      </div>
      <div>
        <span>Confidence</span>
        <strong>{outcome.confidence}</strong>
      </div>
      <p>{outcome.summary}</p>
    </section>
  );
}

function OperatorTimeline({ detail }: { detail: RunDetailModel }) {
  return (
    <section className="operator-timeline" aria-label="Operator timeline">
      <div className="section-title-row">
        <h2>Operator Timeline</h2>
        <span>{detail.operator_timeline.length}</span>
      </div>
      <div className="timeline-controls" aria-label="Timeline filters">
        {["all", "blockers", "verification", "checkpoint", "provider", "apply", "recovery", "raw"].map((filter) => (
          <button type="button" key={filter}>{filter}</button>
        ))}
      </div>
      <div className="operator-rows">
        {detail.operator_timeline.map((row) => (
          <article className={`operator-row ${row.severity}`} key={row.id}>
            <span>{row.sequence}</span>
            <strong>{row.row_type}</strong>
            <p>{String(row.metadata.summary ?? row.title)}</p>
            <small>{row.evidence_refs.join(", ") || "no evidence ref"}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function DecisionRail({ detail }: { detail: RunDetailModel }) {
  const decision = detail.operator_decision;
  return (
    <aside className="decision-rail" aria-label="Decision and evidence rail">
      <section>
        <h2>Operator Decision</h2>
        <strong>{decision?.primary_blocker?.code ?? "none"}</strong>
        <p>{decision?.primary_blocker?.summary ?? detail.outcome_strip.summary}</p>
      </section>
      <section>
        <h3>Allowed Actions</h3>
        {(decision?.allowed_actions ?? []).map((action) => (
          <button className="rail-action" key={action.id} type="button">
            <span>{action.label}</span>
            <small>{action.reason}</small>
          </button>
        ))}
      </section>
      <section>
        <h3>Blocked Actions</h3>
        {(decision?.blocked_actions ?? []).map((action) => (
          <button className="rail-action disabled" disabled key={action.id} type="button">
            <span>{action.label}</span>
            <small>{action.reason}</small>
          </button>
        ))}
      </section>
      <section>
        <h3>AI Handoff</h3>
        <p>{decision?.ai_handoff.prompt_summary ?? "No AI handoff projection"}</p>
        <code>{decision?.ai_handoff.evidence_refs.join(", ") ?? "no evidence refs"}</code>
      </section>
      <section>
        <h3>Raw Evidence</h3>
        {detail.raw_evidence_refs.length === 0 ? (
          <p className="empty-state">No raw evidence refs</p>
        ) : (
          <ul>
            {detail.raw_evidence_refs.map((ref) => <li key={ref}>{ref}</li>)}
          </ul>
        )}
      </section>
    </aside>
  );
}

export function App({ apiRoot = defaultApiRoot() }: AppProps = {}) {
  const [snapshot, setSnapshot] = useState<ConsoleSnapshot>(demoConsoleSnapshot);
  const [selectedRunId, setSelectedRunId] = useState(demoConsoleSnapshot.runs[0]?.runId);
  const [apiDetail, setApiDetail] = useState<RunDetailModel | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    if (!apiRoot) return;

    let cancelled = false;
    async function loadApiSnapshot() {
      try {
        const runsBody = await fetchJson<{ runs: RealRunSummaryResponse[] }>(apiUrl(apiRoot, "/runs"));
        const runIds = runsBody.runs.map((item) => item.run_id);
        const nextRunId = selectedRunId && runIds.includes(selectedRunId) ? selectedRunId : runIds[0];
        if (!nextRunId) throw new Error("API returned no runs");

        const detailResponse = await fetchJson<RealRunDetailResponse>(apiUrl(apiRoot, `/runs/${nextRunId}`));
        const selectedRun = realRunDetailToConsoleRun(detailResponse);
        const runs = runsBody.runs.map((summary) =>
          summary.run_id === selectedRun.runId ? selectedRun : realRunSummaryToConsoleRun(summary)
        );

        if (cancelled) return;
        setSnapshot({ generatedAt: new Date().toISOString(), runs });
        setApiDetail(buildRunDetailModel(detailResponse));
        setApiError(null);
        if (selectedRunId !== nextRunId) {
          setSelectedRunId(nextRunId);
        }
      } catch (error) {
        if (cancelled) return;
        setSnapshot(demoConsoleSnapshot);
        setApiDetail(null);
        setApiError(error instanceof Error ? error.message : "API request failed");
      }
    }

    void loadApiSnapshot();
    return () => {
      cancelled = true;
    };
  }, [apiRoot, selectedRunId]);

  const model = useMemo(
    () => buildConsoleUiModel(snapshot, selectedRunId),
    [snapshot, selectedRunId]
  );
  const run = model.selectedRun;
  const detail = apiDetail?.header.run_id === run.runId
    ? apiDetail
    : buildRunDetailModel(consoleRunToRealDetail(run));

  return (
    <main className="console-shell">
      <header className="topbar">
        <div>
          <p>Waygent Lens</p>
          <h1>{run.title}</h1>
        </div>
        <div className="topbar-metrics">
          <span>{run.status}</span>
          <span>{detail.header.apply_status}</span>
          <span>{model.eventFamilies.join(" / ")}</span>
          <span>{model.generatedAt}</span>
        </div>
      </header>
      {apiError ? (
        <div className="api-error" role="status">
          API unavailable: {apiError}. Showing demo data.
        </div>
      ) : null}

      <div className="console-grid">
        <RunList runs={model.runs} selectedRunId={run.runId} onSelect={setSelectedRunId} />
        <div className="workbench-surface">
          <OutcomeStrip detail={detail} />
          <div className="workbench-main">
            <div className="workbench-center">
              <OperatorTimeline detail={detail} />
              <OperationalMaturity detail={detail} />
              <ExecutionIntelligence detail={detail} />
              <OperationalEvidence detail={detail} />
            </div>
            <DecisionRail detail={detail} />
          </div>
        </div>
      </div>
    </main>
  );
}

function defaultApiRoot(): string {
  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;
  return env?.VITE_WAYGENT_API_ROOT ?? "";
}

function apiUrl(apiRoot: string, path: string): string {
  return `${apiRoot.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`.trim());
  return response.json() as Promise<T>;
}

function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
