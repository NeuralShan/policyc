import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { api } from "../api";
import { EmbeddedContext, PageHeader } from "../components/Layout";
import { PipelineCard } from "../components/RunProgress";
import { Icon } from "../components/icons";
import { ErrorNote, SkeletonList, Spinner, StatusBadge, Tabs, cx, formatDate, useMediaQuery } from "../components/ui";
import { WorkspaceProvider, useWorkspace, type BottomTab } from "../components/workspace/ctx";
import DocPane from "../components/workspace/DocPane";
import ExplainDialog from "../components/workspace/ExplainDialog";
import ProblemsPanel from "../components/workspace/ProblemsPanel";
import TestsPanel from "../components/workspace/TestsPanel";
import { Toolbar } from "../components/workspace/Toolbar";
import TracePanel from "../components/workspace/TracePanel";

const FlowChart = lazy(() => import("../components/workspace/FlowChart"));
const GraphPage = lazy(() => import("./GraphPage").then((m) => ({ default: m.GraphPage })));
const IRReviewPage = lazy(() => import("./IRReviewPage").then((m) => ({ default: m.IRReviewPage })));
const RealityPage = lazy(() => import("./RealityPage").then((m) => ({ default: m.RealityPage })));

export function RunPage() {
  const { runId = "" } = useParams();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });

  if (run.isLoading)
    return (
      <div className="mx-auto w-full max-w-4xl space-y-4 px-4 py-8">
        <div className="skeleton h-8 w-64" />
        <SkeletonList rows={6} />
      </div>
    );
  if (run.error || !run.data)
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        <ErrorNote error={run.error ?? new Error("Run not found")} onRetry={() => void run.refetch()} />
      </div>
    );

  if (run.data.status !== "succeeded") {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
        <PageHeader
          title={<span className="font-mono text-lg">{runId}</span>}
          subtitle={
            <span className="flex flex-wrap items-center gap-3">
              <StatusBadge status={run.data.status} />
              <span>queued {formatDate(run.data.created_at)}</span>
            </span>
          }
          actions={
            <Link to={`/projects/${run.data.project_id}`} className="text-sm font-medium text-indigo-700 hover:underline">
              Back to project
            </Link>
          }
        />
        <PipelineCard run={run.data} />
      </div>
    );
  }

  return (
    <WorkspaceProvider run={run.data}>
      <Workspace />
    </WorkspaceProvider>
  );
}

/* ----------------------------------------------------------- resizing */
function useStored(key: string, initial: number) {
  const [v, setV] = useState(() => {
    const s = Number(localStorage.getItem(key));
    return Number.isFinite(s) && s > 0 ? s : initial;
  });
  useEffect(() => {
    localStorage.setItem(key, String(Math.round(v)));
  }, [key, v]);
  return [v, setV] as const;
}

function Splitter({ orientation, onDrag, value, min, max, label }: {
  orientation: "vertical" | "horizontal";
  onDrag: (delta: number) => void;
  value: number;
  min: number;
  max: number;
  label: string;
}) {
  const last = useRef(0);
  const vertical = orientation === "vertical";
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        last.current = vertical ? e.clientX : e.clientY;
      }}
      onPointerMove={(e) => {
        if (!(e.target as HTMLElement).hasPointerCapture(e.pointerId)) return;
        const pos = vertical ? e.clientX : e.clientY;
        onDrag(pos - last.current);
        last.current = pos;
      }}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 60 : 20;
        if (vertical && e.key === "ArrowLeft") onDrag(-step);
        else if (vertical && e.key === "ArrowRight") onDrag(step);
        else if (!vertical && e.key === "ArrowUp") onDrag(-step);
        else if (!vertical && e.key === "ArrowDown") onDrag(step);
        else return;
        e.preventDefault();
      }}
      className={cx(
        "group relative z-10 shrink-0 touch-none bg-slate-200 transition-colors hover:bg-indigo-400 focus-visible:bg-indigo-500",
        vertical ? "w-1 cursor-col-resize" : "h-1 cursor-row-resize",
      )}
    >
      <span className={cx("absolute", vertical ? "-inset-x-1.5 inset-y-0" : "-inset-y-1.5 inset-x-0")} />
    </div>
  );
}

/* ---------------------------------------------------------- workspace */
function LazyPage({ children }: { children: ReactNode }) {
  return (
    <EmbeddedContext.Provider value={true}>
      <div className="h-full overflow-y-auto p-3 sm:p-4">
        <Suspense fallback={<SkeletonList rows={5} />}>{children}</Suspense>
      </div>
    </EmbeddedContext.Provider>
  );
}

function Workspace() {
  const ws = useWorkspace();
  const desktop = useMediaQuery("(min-width: 1024px)");
  const [docW, setDocW] = useStored("policyc.docW", 340);
  const [bottomH, setBottomH] = useStored("policyc.bottomH", 300);
  const container = useRef<HTMLDivElement>(null);

  // Trace started on mobile -> show flowchart? Keep the trace tab: users switch to Flow to watch.
  const clampDoc = useCallback((d: number) => setDocW((w) => Math.max(220, Math.min(w + d, Math.round((container.current?.clientWidth ?? 1200) * 0.6)))), [setDocW]);
  const clampBottom = useCallback((d: number) => setBottomH((h) => Math.max(120, Math.min(h - d, Math.round(window.innerHeight * 0.75)))), [setBottomH]);

  const tab = ws.tab;
  const bottomTab: BottomTab = tab === "flow" || tab === "doc" ? "problems" : tab;

  const panel = (t: BottomTab): ReactNode => {
    switch (t) {
      case "problems": return <ProblemsPanel />;
      case "tests": return <TestsPanel />;
      case "trace": return <TracePanel />;
      case "reality": return <LazyPage><RealityPage /></LazyPage>;
      case "graph": return <LazyPage><GraphPage /></LazyPage>;
      case "extraction": return <LazyPage><IRReviewPage /></LazyPage>;
      case "pipeline": return <LazyPage><PipelineCard run={ws.run} /></LazyPage>;
      case "doc": return <DocPane />;
      case "flow": return <Flow />;
    }
  };

  const bottomTabs: { id: BottomTab; label: string; count?: number; icon: "warning" | "flask" | "play" | "database" | "git" | "file" | "layers" }[] = [
    { id: "problems", label: "Problems", count: ws.findings.length, icon: "warning" },
    { id: "tests", label: "Tests", count: ws.testrun?.total, icon: "flask" },
    { id: "trace", label: "Trace", icon: "play" },
    { id: "reality", label: "Reality", icon: "database" },
    { id: "graph", label: "Graph / Cypher", icon: "git" },
    { id: "extraction", label: "Extraction", icon: "file" },
    { id: "pipeline", label: "Pipeline", icon: "layers" },
  ];

  // Selecting on desktop while viewing a long panel keeps the Problems tab visible.
  return (
    <div className="flex h-[calc(100dvh-3.5rem)] min-h-[560px] flex-col">
      <Toolbar />
      {desktop ? (
        <div ref={container} className="flex min-h-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1">
            <aside className="min-w-0 shrink-0 overflow-hidden bg-white" style={{ width: docW }} aria-label="Document">
              <DocPane />
            </aside>
            <Splitter orientation="vertical" onDrag={clampDoc} value={docW} min={220} max={900} label="Resize document pane" />
            <section className="min-w-0 flex-1 bg-slate-50" aria-label="Flowchart">
              <Flow />
            </section>
          </div>
          <Splitter orientation="horizontal" onDrag={clampBottom} value={bottomH} min={120} max={900} label="Resize bottom panel" />
          <section className="flex shrink-0 flex-col bg-white" style={{ height: bottomH }} aria-label="Analysis panels">
            <div className="border-b border-slate-200 px-2">
              <Tabs tabs={bottomTabs} value={bottomTab} onChange={ws.setTab} label="Analysis panels" />
            </div>
            <div className="min-h-0 flex-1" role="tabpanel" id={`panel-${bottomTab}`} aria-labelledby={`tab-${bottomTab}`}>
              {panel(bottomTab)}
            </div>
          </section>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col bg-white">
          <div className="border-b border-slate-200 px-1">
            <Tabs
              label="Workspace views"
              value={tab}
              onChange={ws.setTab}
              tabs={[
                { id: "problems", label: "Problems", count: ws.findings.length },
                { id: "flow", label: "Flowchart" },
                { id: "doc", label: "Document" },
                { id: "tests", label: "Tests", count: ws.testrun?.total },
                { id: "trace", label: "Trace" },
                { id: "reality", label: "Reality" },
                { id: "graph", label: "Graph" },
                { id: "extraction", label: "Extraction" },
                { id: "pipeline", label: "Pipeline" },
              ]}
            />
          </div>
          <div className="min-h-0 flex-1" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
            {panel(tab)}
          </div>
        </div>
      )}
      <ExplainDialog />
    </div>
  );
}

function Flow() {
  const ws = useWorkspace();
  if (ws.loading || (!ws.flow && !ws.ready))
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
        <Spinner /> Building flowchart...
      </div>
    );
  if (!ws.flow || ws.flow.nodes.length === 0)
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-slate-600">
        <Icon name="flag" size={28} className="text-slate-400" />
        <p>No flowchart could be built: the extraction did not produce any steps.</p>
      </div>
    );
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500"><Spinner /> Loading flowchart...</div>}>
      <FlowChart flow={ws.flow} />
    </Suspense>
  );
}
