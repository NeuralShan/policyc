import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  ViewportPortal,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";
import { memo, useEffect, useMemo, useState } from "react";

import type { FlowGraph, FlowNode } from "../../api";
import { useTheme } from "../../lib/theme";
import { Icon } from "../icons";
import { Skeleton, cx } from "../ui";
import { EDGE_MS, useWorkspace } from "./ctx";

type Dir = "DOWN" | "RIGHT";
const elk = new ELK();

const SIZE = {
  step: { w: 240, h: 78 },
  decision: { w: 250, h: 116 },
  terminal: { w: 160, h: 48 },
  start: { w: 120, h: 40 },
};

interface NodeData extends Record<string, unknown> {
  node: FlowNode | null;
  startNode?: boolean;
  selected: boolean;
  visited: boolean;
  current: boolean;
  finalOutcome: "good" | "bad" | null;
  dim: boolean;
}

function sizeOf(n: { kind: string }) {
  return n.kind === "decision" ? SIZE.decision : n.kind === "terminal" ? SIZE.terminal : n.kind === "start" ? SIZE.start : SIZE.step;
}

async function layoutGraph(flow: FlowGraph, dir: Dir) {
  const nodes = [{ id: "__start", ...SIZE.start }, ...flow.nodes.map((n) => ({ id: n.id, ...sizeOf(n) }))];
  const edges = [
    ...(flow.entry ? [{ id: "__start->entry", sources: ["__start"], targets: [flow.entry] }] : []),
    ...flow.edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  ];
  const res = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": dir,
      "elk.layered.spacing.nodeNodeBetweenLayers": dir === "DOWN" ? "56" : "90",
      "elk.spacing.nodeNode": dir === "DOWN" ? "48" : "36",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      "elk.layered.cycleBreaking.strategy": "GREEDY",
    },
    children: nodes.map((n) => ({ id: n.id, width: n.w, height: n.h })),
    edges,
  });
  const pos = new Map<string, { x: number; y: number }>();
  res.children?.forEach((c) => pos.set(c.id, { x: c.x ?? 0, y: c.y ?? 0 }));
  return pos;
}

/* ---------------------------------------------------------------- nodes */
const sevStyles = {
  error: { border: "border-red-500", bg: "bg-red-50", badge: "bg-red-600", stroke: "var(--color-red-500)", fill: "var(--color-red-50)" },
  warning: { border: "border-amber-500", bg: "bg-amber-50", badge: "bg-amber-600", stroke: "var(--color-amber-500)", fill: "var(--color-amber-50)" },
  info: { border: "border-blue-400", bg: "bg-white", badge: "bg-blue-600", stroke: "var(--color-blue-400)", fill: "var(--color-white, #fff)" },
} as const;

function Badge({ node }: { node: FlowNode }) {
  if (!node.severity || !node.finding_ids.length) return null;
  const s = sevStyles[node.severity];
  return (
    <span
      className={cx("absolute -right-2 -top-2 z-10 flex h-5 min-w-5 items-center justify-center gap-0.5 rounded-full px-1 text-[11px] font-bold text-white shadow", s.badge)}
      title={`${node.finding_ids.length} finding(s): ${node.codes.join(", ")}`}
    >
      <Icon name={node.severity === "error" ? "error" : "warning"} size={11} />
      {node.finding_ids.length}
    </span>
  );
}

function stateRing(d: NodeData) {
  return cx(
    d.selected && "ring-4 ring-indigo-500/40 [animation:node-pulse-indigo_1.2s_ease-out_2]",
    d.visited && !d.selected && "ring-2 ring-indigo-400/60",
    d.current && d.finalOutcome === "bad" && "ring-4 ring-red-500/50 [animation:node-pulse_1.1s_ease-out_infinite]",
    d.current && d.finalOutcome === "good" && "ring-4 ring-emerald-500/50",
    d.current && !d.finalOutcome && "ring-4 ring-indigo-500/50",
    d.dim && "opacity-45",
  );
}

const hidden = { opacity: 0, width: 1, height: 1, border: 0 } as const;
function Handles() {
  return (
    <>
      <Handle type="target" position={Position.Top} style={hidden} isConnectable={false} />
      <Handle type="target" position={Position.Left} id="l" style={hidden} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} style={hidden} isConnectable={false} />
      <Handle type="source" position={Position.Right} id="r" style={hidden} isConnectable={false} />
    </>
  );
}

function OutcomeMark({ d }: { d: NodeData }) {
  if (!d.current || !d.finalOutcome) return null;
  return d.finalOutcome === "good" ? (
    <span className="absolute -left-2 -top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-white shadow" title="Completed">
      <Icon name="check" size={14} />
    </span>
  ) : (
    <span className="absolute -left-2 -top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-red-600 text-white shadow" title="Stuck here">
      <Icon name="x" size={14} />
    </span>
  );
}

const StepNode = memo(function StepNode({ data }: NodeProps<Node<NodeData>>) {
  const n = data.node!;
  const sev = n.severity ? sevStyles[n.severity] : null;
  return (
    <div
      className={cx(
        "relative h-full w-full rounded-xl border-[1.5px] bg-white px-3 py-2 text-left shadow-sm transition-shadow",
        sev ? `${sev.border} ${sev.bg}` : "border-slate-300",
        n.unreachable && "!border-dashed !border-slate-400 !bg-slate-100",
        n.inferred && !n.unreachable && "border-dashed",
        stateRing(data),
      )}
    >
      <Handles />
      <Badge node={n} />
      <OutcomeMark d={data} />
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {n.number && <span className="font-mono">{n.number}</span>}
        {n.modal && n.modal !== "unknown" && <span>{n.modal}</span>}
        {n.unreachable && <span className="text-slate-600">unreachable</span>}
        {n.inferred && <span className="text-slate-600">inferred</span>}
      </div>
      <p className="line-clamp-2 text-[12.5px] font-medium leading-snug text-slate-900">{n.label}</p>
      {n.actor && (
        <p className="mt-0.5 flex items-center gap-1 truncate text-[11px] text-slate-600">
          <Icon name="user" size={11} className="shrink-0" />
          <span className="truncate">{n.actor}</span>
        </p>
      )}
    </div>
  );
});

const DecisionNode = memo(function DecisionNode({ data }: NodeProps<Node<NodeData>>) {
  const n = data.node!;
  const sev = n.severity ? sevStyles[n.severity] : sevStyles.info;
  const w = SIZE.decision.w;
  const h = SIZE.decision.h;
  return (
    <div className={cx("relative h-full w-full", n.unreachable && "opacity-60")}>
      <Handles />
      <Badge node={n} />
      <OutcomeMark d={data} />
      <svg width={w} height={h} className={cx("absolute inset-0 overflow-visible drop-shadow-sm", data.dim && "opacity-45")} aria-hidden="true">
        <polygon
          points={`${w / 2},2 ${w - 2},${h / 2} ${w / 2},${h - 2} 2,${h / 2}`}
          fill={n.severity ? sev.fill : "var(--surface, #fff)"}
          stroke={n.severity ? sev.stroke : "var(--color-slate-400)"}
          strokeWidth={data.selected || data.current ? 3.5 : 1.8}
          strokeDasharray={n.unreachable || n.inferred ? "6 4" : undefined}
          className={cx(
            data.selected && "stroke-indigo-500",
            data.visited && !data.selected && "stroke-indigo-400",
            data.current && data.finalOutcome === "bad" && "stroke-red-500",
            data.current && data.finalOutcome === "good" && "stroke-emerald-500",
          )}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center px-12 text-center">
        <Icon name="git" size={12} className="mb-0.5 text-slate-500" />
        <p className="line-clamp-3 text-[11.5px] font-medium leading-tight text-slate-900">{n.label}</p>
      </div>
    </div>
  );
});

const TerminalNode = memo(function TerminalNode({ data }: NodeProps<Node<NodeData>>) {
  const n = data.node;
  const sev = n?.severity ? sevStyles[n.severity] : null;
  return (
    <div
      className={cx(
        "relative flex h-full w-full items-center justify-center rounded-full border-[5px] border-double bg-white px-4 text-xs font-semibold text-slate-800",
        sev ? sev.border : "border-slate-500",
        n?.unreachable && "!border-dashed !border-slate-400 !bg-slate-100",
        stateRing(data),
      )}
    >
      <Handles />
      {n && <Badge node={n} />}
      {n && <OutcomeMark d={data} />}
      <span className="truncate">{n?.label ?? "End"}</span>
    </div>
  );
});

const StartNode = memo(function StartNode({ data }: NodeProps<Node<NodeData>>) {
  return (
    <div className={cx("flex h-full w-full items-center justify-center gap-1 rounded-full bg-indigo-600 text-xs font-semibold text-white shadow-sm", data.dim && "opacity-45")}>
      <Handles />
      <Icon name="play" size={11} /> Start
    </div>
  );
});

const nodeTypes = { step: StepNode, decision: DecisionNode, terminal: TerminalNode, start: StartNode };

/* ---------------------------------------------------------------- chart */
function Chart({ flow }: { flow: FlowGraph }) {
  const ws = useWorkspace();
  const { resolved } = useTheme();
  const rf = useReactFlow();
  const [dir, setDir] = useState<Dir>("DOWN");
  const [pos, setPos] = useState<Map<string, { x: number; y: number }> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const layoutKey = `${flow.run_id}|${flow.nodes.length}|${flow.edges.length}|${dir}`;
  useEffect(() => {
    let live = true;
    setError(null);
    layoutGraph(flow, dir)
      .then((p) => live && setPos(p))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey]);

  const trace = ws.traceState?.trace;
  const visitedIds = useMemo(() => {
    if (!trace) return new Set<string>();
    return new Set(trace.steps.slice(0, ws.traceIdx + 1).map((s) => s.node_id));
  }, [trace, ws.traceIdx]);
  const currentId = trace?.steps[ws.traceIdx]?.node_id;
  const isFinal = !!trace && ws.traceIdx >= trace.steps.length - 1;
  const finalOutcome: "good" | "bad" | null = isFinal && trace ? (trace.outcome === "completed" ? "good" : "bad") : null;

  const travelled = useMemo(() => {
    const s = new Set<string>();
    if (!trace) return s;
    for (let i = 0; i < ws.traceIdx && i < trace.steps.length - 1; i++) {
      const a = trace.steps[i].node_id;
      const b = trace.steps[i + 1].node_id;
      flow.edges.filter((e) => e.source === a && e.target === b).forEach((e) => s.add(e.id));
    }
    return s;
  }, [trace, ws.traceIdx, flow.edges]);

  const nodes: Node<NodeData>[] = useMemo(() => {
    if (!pos) return [];
    const mk = (id: string, type: string, n: FlowNode | null, size: { w: number; h: number }, extra?: Partial<NodeData>): Node<NodeData> => {
      const p = pos.get(id) ?? { x: 0, y: 0 };
      return {
        id,
        type,
        position: p,
        width: size.w,
        height: size.h,
        draggable: false,
        ariaLabel: n ? `${n.kind} ${n.number ?? ""} ${n.label}${n.severity ? `, ${n.finding_ids.length} ${n.severity} finding(s)` : ""}` : "Start",
        data: {
          node: n,
          selected: ws.selectedNodeId === id,
          visited: visitedIds.has(id),
          current: currentId === id,
          finalOutcome: currentId === id ? finalOutcome : null,
          dim: !!trace && !visitedIds.has(id),
          ...extra,
        },
      };
    };
    return [
      mk("__start", "start", null, SIZE.start, { startNode: true, dim: !!trace && false }),
      ...flow.nodes.map((n) => mk(n.id, n.kind === "decision" ? "decision" : n.kind === "terminal" ? "terminal" : "step", n, sizeOf(n))),
    ];
  }, [pos, flow.nodes, ws.selectedNodeId, visitedIds, currentId, finalOutcome, trace]);

  const edges: Edge[] = useMemo(() => {
    const mkEdge = (id: string, source: string, target: string, label: string | null, inferred: boolean): Edge => {
      const t = travelled.has(id);
      const stroke = t ? "var(--color-indigo-500)" : "var(--color-slate-400)";
      return {
        id,
        source,
        target,
        type: "smoothstep",
        label: label ?? undefined,
        labelStyle: { fontSize: 11, fontWeight: 600, fill: "var(--color-slate-700)" },
        labelBgStyle: { fill: "var(--surface, #fff)", fillOpacity: 0.95 },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 6,
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 18, height: 18 },
        style: { stroke, strokeWidth: t ? 3 : 1.6, strokeDasharray: inferred ? "5 4" : undefined, opacity: trace && !t ? 0.4 : 1 },
        animated: false,
      };
    };
    return [
      ...(flow.entry ? [mkEdge("__start->entry", "__start", flow.entry, null, false)] : []),
      ...flow.edges.map((e) => mkEdge(e.id, e.source, e.target, e.label, e.inferred)),
    ];
  }, [flow.edges, flow.entry, travelled, trace]);

  // Fit the view whenever a new layout arrives.
  useEffect(() => {
    if (!pos) return;
    requestAnimationFrame(async () => {
      await rf.fitView({ padding: 0.12, duration: 0, maxZoom: 1.1 });
      // Long linear procedures become unreadably small when fitted whole: start at readable zoom on the top.
      if (rf.getZoom() < 0.55) {
        const first = ["__start", ...flow.nodes.slice(0, 5).map((n) => n.id)].map((id) => ({ id }));
        await rf.fitView({ nodes: first, padding: 0.15, duration: 0, minZoom: 0.6, maxZoom: 1 });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos]);

  // Focus the selected node when selection comes from elsewhere (problems list, clause click).
  useEffect(() => {
    if (!ws.selectedNodeId || !pos) return;
    rf.fitView({ nodes: [{ id: ws.selectedNodeId }], duration: 350, maxZoom: 1.15, padding: 1.2 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws.selectedNodeId, pos]);

  // Follow the trace dot.
  useEffect(() => {
    if (!currentId || !pos) return;
    rf.fitView({ nodes: [{ id: currentId }], duration: ws.reducedMotion ? 0 : 400, maxZoom: 1, padding: 1.6 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  const dot = currentId ? pos?.get(currentId) : null;
  const dotSize = currentId ? sizeOf(flow.nodes.find((n) => n.id === currentId) ?? { kind: "step" as const }) : SIZE.step;

  if (error) return <div className="p-4 text-sm text-red-700">Layout failed: {error}</div>;
  if (!pos)
    return (
      <div className="space-y-4 p-8">
        <Skeleton className="mx-auto h-8 w-28 rounded-full" />
        <Skeleton className="mx-auto h-16 w-60" />
        <Skeleton className="mx-auto h-24 w-60" />
      </div>
    );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      colorMode={resolved}
      minZoom={0.15}
      maxZoom={1.8}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      onNodeClick={(_, n) => n.id !== "__start" && ws.selectNode(n.id)}
      onPaneClick={() => ws.selectNode(null)}
      aria-label="Process flowchart"
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} />
      <Controls showInteractive={false} position="bottom-left" aria-label="Flowchart zoom controls" />
      <MiniMap
        pannable
        zoomable
        className="!hidden sm:!block"
        nodeColor={(n) => {
          const fn = (n.data as NodeData).node;
          return fn?.severity === "error" ? "#ef4444" : fn?.severity === "warning" ? "#f59e0b" : fn?.unreachable ? "#94a3b8" : "#6366f1";
        }}
        maskColor={resolved === "dark" ? "rgba(10,14,26,0.6)" : "rgba(241,245,249,0.6)"}
        style={{ background: "var(--surface, #fff)" }}
      />
      <Panel position="top-left" className="!m-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-slate-200 glass px-2.5 py-1.5 text-[11px] text-slate-600 shadow-sm backdrop-blur">
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm border-2 border-red-500" /> error</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm border-2 border-amber-500" /> warning</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm border-2 border-dashed border-slate-500" /> inferred / unreachable</span>
        </div>
      </Panel>
      <Panel position="top-right" className="!m-2">
        <button
          onClick={() => setDir((d) => (d === "DOWN" ? "RIGHT" : "DOWN"))}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 glass px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm backdrop-blur hover:bg-slate-100"
          title="Switch layout direction"
        >
          <Icon name="split" size={13} className={dir === "RIGHT" ? "" : "rotate-90"} />
          {dir === "DOWN" ? "Vertical" : "Horizontal"}
        </button>
      </Panel>
      {dot && trace && !ws.reducedMotion && (
        <ViewportPortal>
          <div
            aria-hidden="true"
            className="pointer-events-none absolute left-0 top-0 z-20"
            style={{
              transform: `translate(${dot.x + (dotSize.w > 200 ? 14 : dotSize.w / 2 - 9)}px, ${dot.y + dotSize.h / 2 - 9}px)`,
              transition: `transform ${EDGE_MS / ws.speed}ms linear`,
            }}
          >
            <div
              className={cx(
                "h-[18px] w-[18px] rounded-full border-2 border-white shadow-lg",
                finalOutcome === "bad" ? "bg-red-600" : finalOutcome === "good" ? "bg-emerald-500" : "bg-indigo-600",
              )}
            />
          </div>
        </ViewportPortal>
      )}
    </ReactFlow>
  );
}

export default function FlowChart({ flow }: { flow: FlowGraph }) {
  return (
    <div className="h-full w-full" role="region" aria-label="Process flowchart">
      <ReactFlowProvider>
        <Chart flow={flow} />
      </ReactFlowProvider>
    </div>
  );
}
