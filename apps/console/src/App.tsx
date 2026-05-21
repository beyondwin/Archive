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
  items: Array<Record<string, unknown>>;
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
        <div className="detail-surface">
          <section className="run-detail" aria-label="Run detail">
            <div>
              <span>Run</span>
              <strong>{run.runId}</strong>
            </div>
            <div>
              <span>Trust</span>
              <strong>{verdictLabels[run.trust.verdict]}</strong>
            </div>
            <div>
              <span>Apply</span>
              <strong>{detail.header.apply_status}</strong>
            </div>
            <div>
              <span>Safe wave</span>
              <strong>{detail.safe_wave.join(", ") || "none"}</strong>
            </div>
          </section>

          <TaskTimeline run={run} />
          <EventTimeline run={run} />
          <div className="projection-grid">
            <TrustReport run={run} />
            <FailureBarriers run={run} />
            <DecisionPackets run={run} />
            <ApplyStatus run={run} />
          </div>
          <OperationalEvidence detail={detail} />
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
