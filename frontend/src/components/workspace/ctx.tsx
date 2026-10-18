import { useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  api,
  orNull,
  type AggregatedFinding,
  type Diagnostic,
  type DocAST,
  type ExecutionTrace,
  type FlowGraph,
  type Health,
  type RunDetail,
  type SopIR,
  type TestRunReport,
} from "../../api";
import {
  buildFlowFromIr,
  decorateFlow,
  deriveHealth,
  findingNodeId,
  findingRanges,
  nodeRange,
  severityRank,
  type CharRange,
} from "../../lib/workspace";
import { usePrefersReducedMotion } from "../ui";

/** "flow" and "doc" are only reachable as tabs on small screens; on desktop they are always visible panes. */
export type BottomTab = "problems" | "tests" | "trace" | "reality" | "graph" | "extraction" | "pipeline" | "flow" | "doc";

export interface TraceState {
  trace: ExecutionTrace;
  label: string;
}

interface Workspace {
  runId: string;
  run: RunDetail;
  ready: boolean;
  findings: AggregatedFinding[];
  flow: FlowGraph | undefined;
  health: Health | undefined;
  ast: DocAST | undefined;
  documentId: string | undefined;
  diagnostics: Diagnostic[];
  testrun: TestRunReport | null | undefined;
  ir: SopIR | undefined;
  loading: boolean;
  findingsError: unknown;
  // selection
  selectedFindingId: string | null;
  selectedNodeId: string | null;
  highlight: CharRange[];
  selectFinding: (id: string | null) => void;
  selectNode: (id: string | null, ranges?: CharRange[]) => void;
  // dialogs
  explainFor: string | null;
  openExplain: (findingId: string | null) => void;
  // tabs
  tab: BottomTab;
  setTab: (t: BottomTab) => void;
  // trace player
  traceState: TraceState | null;
  traceIdx: number;
  playing: boolean;
  speed: number;
  setSpeed: (n: number) => void;
  showTrace: (t: ExecutionTrace, label: string) => void;
  clearTrace: () => void;
  play: () => void;
  pause: () => void;
  stepTo: (idx: number) => void;
  reducedMotion: boolean;
  refetchAll: () => void;
}

const Ctx = createContext<Workspace | null>(null);
export function useWorkspace() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useWorkspace outside provider");
  return c;
}

export const EDGE_MS = 600;

export function WorkspaceProvider({ run, children }: { run: RunDetail; children: ReactNode }) {
  const runId = run.id;
  const enabled = run.status === "succeeded";
  const documentId = run.document_ids[0];

  const findingsQ = useQuery({ queryKey: ["findings", runId], queryFn: () => api.runFindings(runId), enabled });
  const irQ = useQuery({ queryKey: ["ir", runId], queryFn: () => api.runIr(runId), enabled });
  const testrunQ = useQuery({
    queryKey: ["testrun", runId],
    queryFn: () => orNull(api.runTestrun(runId)),
    enabled,
  });
  const diagQ = useQuery({ queryKey: ["diagnostics", runId], queryFn: () => api.runDiagnostics(runId), enabled });
  const astQ = useQuery({
    queryKey: ["ast", documentId],
    queryFn: () => api.documentAst(documentId),
    enabled: enabled && !!documentId,
  });
  const flowQ = useQuery({
    queryKey: ["flow", runId, irQ.data?.ir_id ?? null],
    queryFn: async () => (await orNull(api.runFlow(runId))) ?? (irQ.data ? buildFlowFromIr(runId, irQ.data.ir) : null),
    enabled: enabled && !irQ.isLoading,
  });
  const healthQ = useQuery({
    queryKey: ["health", runId],
    queryFn: () => orNull(api.runHealth(runId)),
    enabled,
  });

  const findings = useMemo(
    () =>
      [...(findingsQ.data?.findings ?? [])].sort(
        (a, b) => severityRank(b.severity) - severityRank(a.severity) || a.rank - b.rank,
      ),
    [findingsQ.data],
  );
  const flow = useMemo(() => (flowQ.data ? decorateFlow(flowQ.data, findings) : undefined), [flowQ.data, findings]);
  const health = useMemo(
    // The server score is authoritative, but only trusted once the findings it summarises are loadable.
    () => (findingsQ.data ? (healthQ.data ?? deriveHealth(findings, testrunQ.data)) : undefined),
    [healthQ.data, findings, testrunQ.data, findingsQ.data],
  );
  const diagnostics = useMemo(() => diagQ.data?.diagnostics ?? [], [diagQ.data]);

  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<CharRange[]>([]);
  const [explainFor, setExplainFor] = useState<string | null>(null);
  const [tab, setTab] = useState<BottomTab>("problems");

  const selectFinding = useCallback(
    (id: string | null) => {
      setSelectedFindingId(id);
      const f = findings.find((x) => x.id === id);
      if (!f) {
        setSelectedNodeId(null);
        setHighlight([]);
        return;
      }
      setSelectedNodeId(findingNodeId(f));
      setHighlight(findingRanges(f, diagnostics, flow));
    },
    [findings, diagnostics, flow],
  );

  const selectNode = useCallback(
    (id: string | null, ranges?: CharRange[]) => {
      setSelectedNodeId(id);
      const node = flow?.nodes.find((n) => n.id === id);
      setHighlight(ranges ?? nodeRange(node));
      const f = node?.finding_ids[0];
      setSelectedFindingId(f ?? null);
    },
    [flow],
  );

  // --- trace player ---
  const reducedMotion = usePrefersReducedMotion();
  const [traceState, setTraceState] = useState<TraceState | null>(null);
  const [traceIdx, setTraceIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const timer = useRef<number | undefined>(undefined);

  const lastIdx = (traceState?.trace.steps.length ?? 1) - 1;
  const showTrace = useCallback(
    (trace: ExecutionTrace, label: string) => {
      setTraceState({ trace, label });
      setTraceIdx(reducedMotion ? trace.steps.length - 1 : 0);
      setPlaying(!reducedMotion && trace.steps.length > 1);
      setTab("trace");
    },
    [reducedMotion],
  );
  const clearTrace = useCallback(() => {
    setTraceState(null);
    setPlaying(false);
    setTraceIdx(0);
  }, []);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!playing || !traceState) return;
    if (traceIdx >= lastIdx) {
      setPlaying(false);
      return;
    }
    timer.current = window.setTimeout(() => setTraceIdx((i) => Math.min(i + 1, lastIdx)), EDGE_MS / speed);
    return () => window.clearTimeout(timer.current);
  }, [playing, traceIdx, lastIdx, speed, traceState]);

  const play = useCallback(() => {
    if (!traceState) return;
    if (reducedMotion) {
      setTraceIdx(lastIdx);
      return;
    }
    if (traceIdx >= lastIdx) setTraceIdx(0);
    setPlaying(true);
  }, [traceState, traceIdx, lastIdx, reducedMotion]);
  const pause = useCallback(() => setPlaying(false), []);
  const stepTo = useCallback(
    (i: number) => {
      setPlaying(false);
      setTraceIdx(Math.max(0, Math.min(i, lastIdx)));
    },
    [lastIdx],
  );

  // Reset transient selection when switching runs.
  useEffect(() => {
    setSelectedFindingId(null);
    setSelectedNodeId(null);
    setHighlight([]);
    clearTrace();
  }, [runId, clearTrace]);

  const refetchAll = useCallback(() => {
    void findingsQ.refetch();
    void flowQ.refetch();
    void healthQ.refetch();
    void testrunQ.refetch();
  }, [findingsQ, flowQ, healthQ, testrunQ]);

  const value: Workspace = {
    runId,
    run,
    ready: enabled && !!findingsQ.data && !!flow,
    findings,
    flow,
    health,
    ast: astQ.data,
    documentId,
    diagnostics,
    testrun: testrunQ.data,
    ir: irQ.data?.ir,
    loading: enabled && (findingsQ.isPending || flowQ.isPending || irQ.isPending) && !findingsQ.isError,
    findingsError: findingsQ.error,
    selectedFindingId,
    selectedNodeId,
    highlight,
    selectFinding,
    selectNode,
    explainFor,
    openExplain: setExplainFor,
    tab,
    setTab,
    traceState,
    traceIdx,
    playing,
    speed,
    setSpeed,
    showTrace,
    clearTrace,
    play,
    pause,
    stepTo,
    reducedMotion,
    refetchAll,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
