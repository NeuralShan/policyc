import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";

import { api, type RunDetail, type RunEvent, type Stage } from "../api";
import { useWriteGuard } from "../auth/AuthProvider";
import { useRunEvents } from "../hooks/useRunEvents";
import { Icon, type IconName } from "./icons";
import { Badge, Button, Card, ErrorNote, Mono, SkeletonList, Spinner, StatusBadge, Tooltip, cx, formatDuration } from "./ui";

type StageState = "pending" | "running" | "completed" | "failed" | "skipped" | "paused";

function stageState(key: string, events: RunEvent[], runStatus?: string): StageState {
  const last = events.filter((e) => e.stage === key).at(-1);
  if (last?.status === "started" || last?.status === "progress") {
    return runStatus === "failed" ? "failed" : "running";
  }
  if (last) return last.status;
  return runStatus === "failed" ? "skipped" : "pending";
}

/** The single, prominent "what now?" callout for a run, replacing the old rainbow of banners. */
export function NextAction({ run, ordered }: { run: RunDetail; ordered: RunEvent[] }) {
  const navigate = useNavigate();
  const guard = useWriteGuard();
  const rerun = useMutation({
    mutationFn: () => api.startRun(run.project_id, true),
    onSuccess: (r) => navigate(`/runs/${r.id}`),
  });
  const failedStage = [...ordered].reverse().find((e) => e.status === "failed" || e.status === "started" || e.status === "progress")?.stage;
  const lastMsg = ordered.at(-1)?.message;

  if (run.status === "paused")
    return (
      <Callout tone="amber" icon="pause2" title="Extraction awaiting your review">
        <p>The model extracted the procedure and the pipeline is paused so a human can confirm it before the engine analyses it.</p>
        <Link to={`/runs/${run.id}/ir-review`}>
          <Button variant="primary" icon="arrowRight">Review &amp; approve</Button>
        </Link>
      </Callout>
    );
  if (run.status === "failed")
    return (
      <Callout tone="red" icon="error" title={`Run failed${failedStage ? ` during ${failedStage}` : ""}`}>
        <p className="break-words font-mono text-xs">{run.error ?? lastMsg ?? "The pipeline stopped before finishing."}</p>
        <div className="flex flex-wrap gap-2">
          <Button icon="refresh" disabled={rerun.isPending} onClick={() => guard(() => rerun.mutate(), "Sign in to run your own SOPs")}>
            {rerun.isPending ? "Starting..." : "Re-run"}
          </Button>
          <Link to={`/projects/${run.project_id}`}><Button variant="secondary">Back to project</Button></Link>
        </div>
        <ErrorNote error={rerun.error} />
      </Callout>
    );
  if (run.status === "queued" || run.status === "running")
    return (
      <Callout tone="indigo" icon="refresh" title={run.status === "queued" ? "Queued" : "Compiling your procedure"} spin>
        <p className="text-sm">{lastMsg ?? "Waiting for the pipeline to start."}</p>
      </Callout>
    );
  return null;
}

const calloutTone = {
  amber: "border-amber-300 bg-amber-50 text-amber-900",
  red: "border-red-300 bg-red-50 text-red-900",
  indigo: "border-indigo-200 bg-indigo-50 text-indigo-900",
} as const;

function Callout({ tone, icon, title, children, spin }: { tone: keyof typeof calloutTone; icon: IconName; title: string; children: React.ReactNode; spin?: boolean }) {
  return (
    <div role={tone === "red" ? "alert" : "status"} className={cx("flex gap-3 rounded-xl border p-4 animate-fade-in", calloutTone[tone])}>
      <span className="mt-0.5 shrink-0">{spin ? <Spinner size={20} /> : <Icon name={icon} size={20} />}</span>
      <div className="min-w-0 flex-1 space-y-2 text-sm [&_p]:text-current">
        <h2 className="text-base font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}

const links: { to: string; label: string; icon: IconName; key?: string; text: (a: Record<string, number>) => string }[] = [
  { key: "analyze", to: "diagnostics", label: "Diagnostics", icon: "warning", text: (a) => `${a.total_errors ?? 0} errors, ${a.total_warnings ?? 0} warnings` },
  { key: "execute", to: "testrun", label: "Test report", icon: "checkCircle", text: (a) => `${a.passed ?? 0}/${a.total ?? 0} passed` },
  { key: "testgen", to: "tests", label: "Test suite", icon: "flask", text: (a) => `${a.total ?? 0} generated cases` },
  { key: "findings", to: "findings", label: "Findings", icon: "list", text: (a) => `${a.total ?? 0} total, ${a.open ?? 0} open` },
  { key: "link", to: "graph", label: "Knowledge graph", icon: "git", text: (a) => `${a.nodes ?? 0} nodes, ${a.edges ?? 0} edges` },
  { to: "simulator", label: "Simulator", icon: "play", text: () => "Trace your own facts" },
  { to: "reality", label: "Reality check", icon: "database", text: () => "Compare with real case logs" },
  { to: "ir-review", label: "Extraction (IR)", icon: "file", text: () => "Review what the model extracted" },
];

export function ResultLinks({ run }: { run: RunDetail }) {
  if (run.status !== "succeeded") return null;
  return (
    <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {links.map((l) => {
        const art = l.key ? (run.artifacts[l.key] as Record<string, number> | undefined) : {};
        if (l.key && (!art || (art as { stub?: boolean }).stub)) return null;
        return (
          <li key={l.to}>
            <Link to={`/runs/${run.id}/${l.to}`} className="group flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 transition-colors hover:border-indigo-300 hover:bg-indigo-50/40">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700 group-hover:bg-indigo-100 group-hover:text-indigo-700">
                <Icon name={l.icon} size={18} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-slate-900">{l.label}</span>
                <span className="block truncate text-xs text-slate-600">{l.text(art ?? {})}</span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Pipeline stepper. Subscribes to SSE while the run is active. */
export function PipelineCard({ run }: { run: RunDetail }) {
  const queryClient = useQueryClient();
  const stages = useQuery({ queryKey: ["stages"], queryFn: api.stages, staleTime: Infinity });
  const active = run.status === "queued" || run.status === "running";
  const live = useRunEvents(run.id, active, () => {
    queryClient.invalidateQueries({ queryKey: ["run", run.id] });
    queryClient.invalidateQueries({ queryKey: ["runs", run.project_id] });
    queryClient.invalidateQueries({ queryKey: ["documents", run.project_id] });
    queryClient.invalidateQueries({ queryKey: ["ast"] });
  });
  const events = new Map<number, RunEvent>(run.events.map((e) => [e.id, e]));
  live.forEach((e, id) => events.set(id, e));
  const ordered = [...events.values()].sort((a, b) => a.id - b.id);

  return (
    <div className="space-y-4">
      <NextAction run={run} ordered={ordered} />
      <ResultLinks run={run} />
      <Card title="Pipeline" actions={<span className="text-xs text-slate-500">Gemini translates, the engine proves</span>}>
        {stages.isLoading && <SkeletonList rows={5} />}
        <ErrorNote error={stages.error} onRetry={() => void stages.refetch()} />
        <ol className="space-y-1">
          {stages.data?.map((stage, i) => {
            const computed = stageState(stage.key, ordered, run.status);
            // A paused run waits at the first stage that has not finished: show it as awaiting review.
            const pausedAt = run.status === "paused" ? stages.data.find((s) => stageState(s.key, ordered, run.status) !== "completed")?.key : undefined;
            return (
            <StageRow
              key={stage.key}
              stage={stage}
              last={i === stages.data.length - 1}
              events={ordered.filter((e) => e.stage === stage.key)}
              state={pausedAt === stage.key ? "paused" : computed}
              artifact={run.artifacts[stage.key]}
            />
            );
          })}
        </ol>
      </Card>
    </div>
  );
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
          <Link to={`/documents/${d.document_id}`} className="font-medium text-indigo-700 hover:underline">
            {d.filename ?? d.document_id}
          </Link>
          {d.error ? (
            <span className="text-red-700">{d.error}</span>
          ) : (
            <span className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
              {d.doc_class && <Badge tone="indigo">{d.doc_class}</Badge>}
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
  pending: "border-slate-300 bg-white text-slate-500",
  running: "border-indigo-500 bg-indigo-50 text-indigo-700",
  completed: "border-emerald-600 bg-emerald-600 text-white",
  failed: "border-red-600 bg-red-600 text-white",
  skipped: "border-slate-200 bg-slate-100 text-slate-500",
  paused: "border-amber-500 bg-amber-50 text-amber-800",
};

function StageRow({ stage, events, state, artifact, last }: { stage: Stage; events: RunEvent[]; state: StageState; artifact: unknown; last: boolean }) {
  const started = events.find((e) => e.status === "started");
  const ended = events.findLast((e) => e.status === "completed" || e.status === "failed");
  const progress = events.filter((e) => e.status === "progress");
  const latest = state === "running" ? progress.at(-1) : ended;
  const message = latest?.message && latest.message !== "stub" ? latest.message : null;
  const isStub = !stage.implemented || (artifact as { stub?: boolean } | undefined)?.stub === true;

  return (
    <li className="relative flex gap-3 rounded-lg px-1 py-2">
      {!last && <span className="absolute bottom-[-8px] left-[19px] top-10 w-px bg-slate-200" aria-hidden="true" />}
      <div
        className={cx("z-[1] flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-[11px] font-bold", markerStyles[state], state === "running" && "animate-pulse")}
        title={`Layer ${stage.layer}`}
      >
        {state === "completed" ? <Icon name="check" size={14} /> : state === "failed" ? <Icon name="x" size={14} /> : `L${stage.layer}`}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-900">{stage.label}</span>
          <Mono>{stage.compiler_analogy}</Mono>
          <StatusBadge status={state} />
          {isStub && (
            <Tooltip content="This stage is a placeholder: it reports a status but does no real work yet.">
              <span tabIndex={0}><Badge tone="amber" icon="info">stub</Badge></span>
            </Tooltip>
          )}
          {started && ended && <span className="text-xs text-slate-500">{formatDuration(started.created_at, ended.created_at)}</span>}
        </div>
        <p className="text-sm text-slate-600">{stage.description}</p>
        {message && <p className={cx("mt-1 text-sm", state === "failed" ? "text-red-700" : "text-slate-700")}>{message}</p>}
        {stage.key === "ingest" && artifact !== undefined && <IngestResults artifact={artifact as { documents?: IngestedDocument[] }} />}
        {progress.length > 0 && state !== "running" && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-800">log ({progress.length})</summary>
            <ul className="mt-1 space-y-0.5 font-mono text-xs text-slate-600">
              {progress.map((e) => <li key={e.id} className="break-words">{e.message}</li>)}
            </ul>
          </details>
        )}
        {artifact !== undefined && !isStub && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-800">artifact</summary>
            <pre className="mt-1 max-w-full overflow-x-auto rounded bg-slate-50 p-2 font-mono text-xs text-slate-700">{JSON.stringify(artifact, null, 2)}</pre>
          </details>
        )}
      </div>
    </li>
  );
}
