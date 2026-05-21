import { useMemo, useState } from "react";
import {
  buildConsoleUiModel,
  buildRunDetailModel,
  consoleRunToRealDetail,
  demoConsoleSnapshot,
  type ConsoleRun,
  type TrustVerdict
} from "./uiModel";
import "./styles.css";

const verdictLabels: Record<TrustVerdict, string> = {
  trusted: "Trusted",
  failed: "Failed",
  insufficient_evidence: "Insufficient evidence"
};

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
  return (
    <section className="section-band compact" aria-labelledby="apply-heading">
      <h2 id="apply-heading">Apply Status</h2>
      <div className={`apply-box ${run.applyStatus.state}`}>
        <strong>{run.applyStatus.state}</strong>
        <span>{run.applyStatus.checkpointRef}</span>
        <p>{run.applyStatus.reason}</p>
      </div>
      <button disabled={!run.applyStatus.canApply} type="button">
        Apply checkpoint
      </button>
    </section>
  );
}

export function App() {
  const [selectedRunId, setSelectedRunId] = useState(demoConsoleSnapshot.runs[0]?.runId);
  const model = useMemo(
    () => buildConsoleUiModel(demoConsoleSnapshot, selectedRunId),
    [selectedRunId]
  );
  const run = model.selectedRun;
  const detail = buildRunDetailModel(consoleRunToRealDetail(run));

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
        </div>
      </div>
    </main>
  );
}
