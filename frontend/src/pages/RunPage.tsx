import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { api, type RunDetail, type RunEvent, type Stage } from "../api";
import { PageHeader } from "../components/Layout";
import {
  Badge,
  Card,
  ErrorNote,
  Mono,
  StatusBadge,
  cx,
  formatDate,
  formatDuration,
} from "../components/ui";
import { useRunEvents } from "../hooks/useRunEvents";

type StageState = "pending" | "running" | "completed" | "failed" | "skipped";

export function RunPage() {
  const { runId = "" } = useParams();
  const queryClient = useQueryClient();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });
  const stages = useQuery({ queryKey: ["stages"], queryFn: api.stages, staleTime: Infinity });

  const active = run.data?.status === "queued" || run.data?.status === "running";
  const paused = run.data?.status === "paused";
  const live = useRunEvents(runId, active, () => {
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
    queryClient.invalidateQueries({ queryKey: ["runs", run.data?.project_id] });
    queryClient.invalidateQueries({ queryKey: ["documents", run.data?.project_id] });
    queryClient.invalidateQueries({ queryKey: ["ast"] });
  });

  const events = new Map<number, RunEvent>(run.data?.events.map((e) => [e.id, e]));
  live.forEach((e, id) => events.set(id, e));
  const ordered = [...events.values()].sort((a, b) => a.id - b.id);

  return (
    <>
      <PageHeader
        title={<span className="font-mono">{runId}</span>}
        subtitle={run.data && <RunSummary run={run.data} />}
        actions={
          run.data && (
            <Link to={`/projects/${run.data.project_id}`} className="text-sm text-slate-600 hover:text-slate-900">
              ← Project
            </Link>
          )
        }
      />
      <ErrorNote error={run.error ?? stages.error} />
      {run.data?.error && (
        <div className="mb-6">
          <ErrorNote error={run.data.error} />
        </div>
      )}
      {paused && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3">
          <span className="text-sm font-medium text-amber-800">
            Awaiting IR review before the pipeline continues.
          </span>
          <Link
            to={`/runs/${runId}/ir-review`}
            className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
          >
            Review IR →
          </Link>
        </div>
      )}
      {run.data?.status === "succeeded" && run.data?.artifacts?.link && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-indigo-200 bg-indigo-50 px-4 py-3">
          <span className="text-sm font-medium text-indigo-800">
            Knowledge graph ready —{" "}
            {(run.data.artifacts.link as Record<string, number>).nodes ?? 0} nodes,{" "}
            {(run.data.artifacts.link as Record<string, number>).edges ?? 0} edges.
          </span>
          <Link
            to={`/runs/${runId}/graph`}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            View Graph →
          </Link>
        </div>
      )}
      {run.data?.status === "succeeded" && run.data?.artifacts?.analyze && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3">
          <span className="text-sm font-medium text-rose-800">
            Static analysis complete —{" "}
            {(run.data.artifacts.analyze as Record<string, number>).total_errors ?? 0} error(s),{" "}
            {(run.data.artifacts.analyze as Record<string, number>).total_warnings ?? 0} warning(s).
          </span>
          <Link
            to={`/runs/${runId}/diagnostics`}
            className="rounded-md bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700"
          >
            View Diagnostics →
          </Link>
        </div>
      )}
      {run.data?.status === "succeeded" && run.data?.artifacts?.extract && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-violet-200 bg-violet-50 px-4 py-3">
          <span className="text-sm font-medium text-violet-800">
            Process simulator ready — run scenarios to trace execution paths.
          </span>
          <Link
            to={`/runs/${runId}/simulator`}
            className="rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700"
          >
            Open Simulator →
          </Link>
        </div>
      )}
      {run.data?.status === "succeeded" && run.data?.artifacts?.testgen && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-teal-200 bg-teal-50 px-4 py-3">
          <span className="text-sm font-medium text-teal-800">
            Test suite ready —{" "}
            {(run.data.artifacts.testgen as Record<string, number>).total ?? 0} test cases
            ({(run.data.artifacts.testgen as Record<string, number>).boundary ?? 0} boundary,{" "}
            {(run.data.artifacts.testgen as Record<string, number>).branch ?? 0} branch,{" "}
            {(run.data.artifacts.testgen as Record<string, number>).fault ?? 0} fault).
          </span>
          <Link
            to={`/runs/${runId}/tests`}
            className="rounded-md bg-teal-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-700"
          >
            View Tests →
          </Link>
        </div>
      )}
      {run.data?.status === "succeeded" && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
          <span className="text-sm font-medium text-slate-700">
            Reality check — upload real case history to measure conformance against this SOP.
          </span>
          <Link
            to={`/runs/${runId}/reality`}
            className="rounded-md bg-slate-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
          >
            Open Reality →
          </Link>
        </div>
      )}
      {run.data?.status === "succeeded" && run.data?.artifacts?.execute && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3">
          <span className="text-sm font-medium text-emerald-800">
            Test run complete —{" "}
            {(run.data.artifacts.execute as Record<string, number>).passed ?? 0}/
            {(run.data.artifacts.execute as Record<string, number>).total ?? 0} passed,{" "}
            step coverage{" "}
            {(run.data.artifacts.execute as Record<string, number>).step_coverage_pct ?? 0}%.
          </span>
          <Link
            to={`/runs/${runId}/testrun`}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
          >
            View Report →
          </Link>
        </div>
      )}
      {run.data?.status === "succeeded" && run.data?.artifacts?.findings && (
        <div className="mb-6 flex items-center gap-4 rounded-md border border-orange-200 bg-orange-50 px-4 py-3">
          <span className="text-sm font-medium text-orange-800">
            {(run.data.artifacts.findings as Record<string, number>).total ?? 0} findings aggregated —{" "}
            {(run.data.artifacts.findings as Record<string, number>).open ?? 0} open.
          </span>
          <Link
            to={`/runs/${runId}/findings`}
            className="rounded-md bg-orange-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-orange-700"
          >
            View Findings →
          </Link>
        </div>
      )}
      <Card title="Pipeline">
        <ol className="space-y-2">
          {stages.data?.map((stage) => (
            <StageRow
              key={stage.key}
              stage={stage}
              events={ordered.filter((e) => e.stage === stage.key)}
              state={stageState(stage.key, ordered, run.data?.status)}
              artifact={run.data?.artifacts[stage.key]}
            />
          ))}
        </ol>
      </Card>
    </>
  );
}

function RunSummary({ run }: { run: RunDetail }) {
  return (
    <span className="flex flex-wrap items-center gap-3">
      <StatusBadge status={run.status} />
      <span>{run.document_ids.length} document{run.document_ids.length === 1 ? "" : "s"}</span>
      <span>queued {formatDate(run.created_at)}</span>
      <span>duration {formatDuration(run.started_at, run.finished_at)}</span>
    </span>
  );
}

function stageState(key: string, events: RunEvent[], runStatus?: string): StageState {
  const last = events.filter((e) => e.stage === key).at(-1);
  if (last?.status === "started" || last?.status === "progress") {
    if (runStatus === "failed") return "failed";
    if (runStatus === "paused") return "running"; // interrupted mid-stage
    return "running";
  }
  if (last) return last.status;
  return runStatus === "failed" ? "skipped" : "pending";
}

interface IngestedDocument {
  document_id: string;
  filename?: string;
  error?: string;
  nodes?: number;
  tables?: number;
  figures?: number;
  diagrams?: number;
  ocr_pages?: number;
  vision_corrected?: number;
  warnings?: number;
  doc_class?: string | null;
}

function IngestResults({ artifact }: { artifact: { documents?: IngestedDocument[] } }) {
  if (!artifact.documents?.length) return null;
  return (
    <ul className="mt-2 space-y-1 text-sm">
      {artifact.documents.map((d) => (
        <li key={d.document_id} className="flex flex-wrap items-center gap-2">
          <Link to={`/documents/${d.document_id}`} className="text-slate-900 hover:underline">
            {d.filename ?? d.document_id}
          </Link>
          {d.error ? (
            <span className="text-red-700">{d.error}</span>
          ) : (
            <span className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
              {d.doc_class && <Badge tone="blue">{d.doc_class}</Badge>}
              {d.nodes} nodes · {d.tables} tables · {d.figures} figures
              {!!d.diagrams && <Badge tone="violet">{d.diagrams} diagram(s)</Badge>}
              {!!d.ocr_pages && <Badge tone="amber">{d.ocr_pages} OCR page(s)</Badge>}
              {!!d.vision_corrected && <Badge tone="violet">{d.vision_corrected} vision-corrected</Badge>}
              {!!d.warnings && <Badge tone="amber">{d.warnings} warning(s)</Badge>}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

const markerStyles: Record<StageState, string> = {
  pending: "border-slate-300 bg-white text-slate-400",
  running: "border-blue-500 bg-blue-50 text-blue-700 animate-pulse",
  completed: "border-emerald-500 bg-emerald-500 text-white",
  failed: "border-red-500 bg-red-500 text-white",
  skipped: "border-slate-200 bg-slate-100 text-slate-400",
};

function StageRow({ stage, events, state, artifact }: {
  stage: Stage;
  events: RunEvent[];
  state: StageState;
  artifact: unknown;
}) {
  const started = events.find((e) => e.status === "started");
  const ended = events.findLast((e) => e.status === "completed" || e.status === "failed");
  const progress = events.filter((e) => e.status === "progress");
  const latest = state === "running" ? progress.at(-1) : ended;
  const message = latest?.message && latest.message !== "stub" ? latest.message : null;

  return (
    <li className="flex gap-4 rounded-md px-2 py-2">
      <div
        className={cx(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold",
          markerStyles[state],
        )}
        title={`Layer ${stage.layer}`}
      >
        L{stage.layer}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-900">{stage.label}</span>
          <Mono>{stage.compiler_analogy}</Mono>
          <StatusBadge status={state} />
          {!stage.implemented && <Badge tone="amber">stub</Badge>}
          {started && ended && (
            <span className="text-xs text-slate-500">{formatDuration(started.created_at, ended.created_at)}</span>
          )}
        </div>
        <p className="text-sm text-slate-600">{stage.description}</p>
        {message && <p className={cx("mt-1 text-sm", state === "failed" ? "text-red-700" : "text-slate-700")}>{message}</p>}
        {stage.key === "ingest" && artifact !== undefined && (
          <IngestResults artifact={artifact as { documents?: IngestedDocument[] }} />
        )}
        {progress.length > 0 && state !== "running" && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">log ({progress.length})</summary>
            <ul className="mt-1 space-y-0.5 font-mono text-xs text-slate-600">
              {progress.map((e) => <li key={e.id}>{e.message}</li>)}
            </ul>
          </details>
        )}
        {artifact !== undefined && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">artifact</summary>
            <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-xs text-slate-700">
              {JSON.stringify(artifact, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </li>
  );
}
